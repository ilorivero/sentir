// SENTIR - Monitor Oasis: implementacao (ver Oasis_SENTIR.ino para o resumo das mudancas).
// Em .cpp (e nao no .ino) para a IDE do Arduino nao gerar prototipos automaticos.

#include <Arduino.h>
#include <Wire.h>
#include <esp_timer.h>
#include <esp_mac.h>
#include "MAX30105.h"
#include "heartRate.h"
#include <Adafruit_MLX90614.h>
#include <Adafruit_AHTX0.h>
#include <Adafruit_BMP280.h>

// ------------------------------------------------------------------------------- opcoes
#define OASIS_FW_VERSION "sentir-oasis-0.2"
#ifndef SENTIR_FAKE_SENSORS
  #if defined(CONFIG_SENTIR_FAKE_SENSORS)
    #define SENTIR_FAKE_SENSORS 1
  #else
    #define SENTIR_FAKE_SENSORS 0   // 1 = sinais sinteticos, sem sensores. NUNCA em coleta real.
  #endif
#endif
#ifndef OASIS_I2C_SDA
  #define OASIS_I2C_SDA 8           // C3 Super Mini (como no monitor_oasis original)
#endif
#ifndef OASIS_I2C_SCL
  #define OASIS_I2C_SCL 9
#endif
#ifndef OASIS_BMP280_ADDR
  #define OASIS_BMP280_ADDR 0x77
#endif

static const uint32_t PPG_HZ = 100;                 // 400 Hz com media de 4
static const uint32_t PPG_DT_US = 1000000UL / PPG_HZ;
static const uint32_t MLX_INTERVAL_US = 250000;     // 4 Hz
static const uint32_t ENV_INTERVAL_US = 2000000;    // 0,5 Hz (como o original)

MAX30105 particleSensor;
Adafruit_MLX90614 mlx = Adafruit_MLX90614();
Adafruit_AHTX0 aht;
Adafruit_BMP280 bmp;
bool hasPpg = false, hasMlx = false, hasAht = false, hasBmp = false;

// estado dos sinais
const byte RATE_SIZE = 4;
byte rates[RATE_SIZE];
byte rateSpot = 0;
int64_t lastBeatUs = 0;
int beatAvg = 0;
int hrv = 0;           // IBI instantaneo (ms) - nao e metrica de HRV (ver monitor_oasis/CLAUDE.md)
int spo2 = 0;          // aproximacao NAO calibrada (idem original)
double objectTemp = 0.0;
float ambientTemp = 0.0, humidity = 0.0, pressure = 0.0;
int64_t lastMlxUs = 0, lastEnvUs = 0;
uint32_t sampleCounter = 0;
int64_t lastSampleUs = 0;

static inline int64_t nowUs() { return esp_timer_get_time(); }

// Serial.print de inteiros de 64 bits sem depender de %lld
static void printI64(int64_t v) {
  char tmp[21]; int i = 0;
  if (v < 0) { Serial.write('-'); v = -v; }
  do { tmp[i++] = char('0' + (v % 10)); v /= 10; } while (v && i < 20);
  while (i) Serial.write(tmp[--i]);
}

// ------------------------------------------------------------- ping/pong (Elo A do app)
// Nao bloqueante (nunca Serial.readStringUntil). t2 = chegada do 1o byte da linha.
static char syncBuf[72];
static int syncLen = 0;
static int64_t syncFirstByteUs = 0;

static void handleSyncLine(const char* line, int64_t t2) {
  const char* p = strstr(line, "\"id\":");
  if (!p) {
    if (strncmp(line, "ID?", 3) == 0) {   // identificacao (SENTIR)
      Serial.print("{\"hello\":\"oasis\",\"fw\":\"" OASIS_FW_VERSION "\",\"mac\":\"");
      uint8_t mac[6]; esp_read_mac(mac, ESP_MAC_WIFI_STA);
      Serial.printf("%02X:%02X:%02X:%02X:%02X:%02X", mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
      Serial.print("\",\"ppg_hz\":"); Serial.print(PPG_HZ);
      Serial.print(",\"fake\":"); Serial.print(SENTIR_FAKE_SENSORS);
      Serial.printf(",\"sensors\":\"%d%d%d%d\"}\n", hasPpg, hasMlx, hasAht, hasBmp);
    }
    return;
  }
  long id = atol(p + 5);
  Serial.print("{\"pong\":"); Serial.print(id);
  Serial.print(",\"t2\":"); printI64(t2);
  Serial.print(",\"pt\":"); printI64(nowUs());   // t3, 64 bits (compativel: o app le "pt")
  Serial.println("}");
}

static void checkSyncPing() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (syncLen == 0) syncFirstByteUs = nowUs();
    if (c == '\n') {
      syncBuf[syncLen] = '\0';
      handleSyncLine(syncBuf, syncFirstByteUs);
      syncLen = 0;
    } else if (c != '\r') {
      if (syncLen < (int)sizeof(syncBuf) - 1) syncBuf[syncLen++] = c; else syncLen = 0;
    }
  }
}

// -------------------------------------------------------------------------- pacote
static void sendJson(int64_t tu, long ir, long red, bool beatDetected) {
  Serial.print("{\"t\":"); Serial.print((uint32_t)(tu / 1000));
  Serial.print(",\"tu\":"); printI64(tu);
  Serial.print(",\"n\":"); Serial.print(sampleCounter);
  Serial.print(",\"ir\":"); Serial.print(ir);
  Serial.print(",\"red\":"); Serial.print(red);
  Serial.print(",\"bpm\":"); Serial.print(beatAvg);
  Serial.print(",\"spo2\":"); Serial.print(spo2);
  Serial.print(",\"hrv\":"); Serial.print(hrv);
  Serial.print(",\"temp\":"); Serial.print(objectTemp);
  Serial.print(",\"amb_temp\":"); Serial.print(ambientTemp);
  Serial.print(",\"hum\":"); Serial.print(humidity);
  Serial.print(",\"press\":"); Serial.print(pressure);
  Serial.print(",\"beat\":"); Serial.print(beatDetected ? 1 : 0);
  Serial.println("}");
}

// Processa UMA amostra de PPG capturada em tu (mesma logica do original)
static void processSample(int64_t tu, long irValue, long redValue) {
  sampleCounter++;
  if (irValue < 50000) {           // sem dedo
    beatAvg = 0; spo2 = 0; hrv = 0;
    sendJson(tu, irValue, redValue, false);
    return;
  }
  // SpO2: mesma aproximacao empirica NAO calibrada do original
  float ratio = (float)redValue / (float)irValue;
  int calc = 110 - (int)(15 * ratio);
  if (calc > 100) calc = 100;
  if (calc < 80) calc = 80;
  spo2 = (int)(spo2 * 0.9 + calc * 0.1);

  bool beat = checkForBeat(irValue);
  if (beat) {
    int64_t delta = tu - lastBeatUs;          // entre instantes de captura (us)
    lastBeatUs = tu;
    float bpm = 60.0f / (delta / 1e6f);
    hrv = (int)(delta / 1000);
    if (bpm < 255 && bpm > 20) {
      rates[rateSpot++] = (byte)bpm;
      rateSpot %= RATE_SIZE;
      int sum = 0;
      for (byte x = 0; x < RATE_SIZE; x++) sum += rates[x];
      beatAvg = sum / RATE_SIZE;
    }
  }
  sendJson(tu, irValue, redValue, beat);
}

// Instante de captura de cada amostra do FIFO: cadencia nominal de 10 ms, puxada devagar
// (1/64 por leitura) para "agora - (pendentes-1)*dt". Intervalos suaves (bom para IBI) e sem
// erro acumulado; reancora se o erro passar de 50 ms (ex.: travamento do laco).
static int64_t nextSampleTime(int pendingIncludingThis) {
  const int64_t anchor = nowUs() - (int64_t)(pendingIncludingThis - 1) * PPG_DT_US;
  int64_t t;
  if (lastSampleUs == 0) {
    t = anchor;
  } else {
    t = lastSampleUs + PPG_DT_US;
    const int64_t err = anchor - t;
    if (err > 50000 || err < -50000) t = anchor; else t += err / 64;
  }
  lastSampleUs = t;
  return t;
}

#if SENTIR_FAKE_SENSORS
static void fakePoll() {
  static int64_t next = 0;
  int64_t now = nowUs();
  if (next == 0) next = now;
  while (now >= next) {
    float s = next / 1e6f;
    float phase = fmodf(s, 60.0f / 72.0f) / (60.0f / 72.0f);       // ~72 bpm
    float pulse = expf(-powf((phase - 0.15f) / 0.06f, 2.0f));
    long ir = 110000 + (long)(1500 * pulse) + (long)random(-30, 30);
    long red = 90000 + (long)(900 * pulse) + (long)random(-30, 30);
    lastSampleUs = next;
    processSample(next, ir, red);
    next += PPG_DT_US;
  }
}
#endif

void oasis_setup() {
  Serial.begin(115200);
  delay(1000);
#if SENTIR_FAKE_SENSORS
  hasPpg = hasMlx = hasAht = hasBmp = false;
  objectTemp = 33.5; ambientTemp = 24.0; humidity = 50.0; pressure = 1013.0;
#else
  Wire.begin(OASIS_I2C_SDA, OASIS_I2C_SCL);
  Wire.setClock(100000);   // MLX90614 (SMBus) aceita no maximo 100 kHz
  delay(100);
  hasPpg = particleSensor.begin(Wire, I2C_SPEED_STANDARD);
  hasMlx = mlx.begin();
  hasAht = aht.begin();
  hasBmp = bmp.begin(OASIS_BMP280_ADDR);
  if (hasPpg) {
    // brilho 60, media 4, modo 2 (RED+IR), 400 Hz -> 100 Hz de saida, 411 us, faixa 4096
    particleSensor.setup(60, 4, 2, 400, 411, 4096);
  }
#endif
}

void oasis_loop() {
  checkSyncPing();   // antes de qualquer I2C: menor atraso no pong

#if SENTIR_FAKE_SENSORS
  fakePoll();
#else
  if (hasPpg) {
    particleSensor.check();                  // le tudo o que ha no FIFO do sensor
    int pending = particleSensor.available();
    while (particleSensor.available()) {
      const int64_t tu = nextSampleTime(pending--);
      const long ir = particleSensor.getFIFOIR();
      const long red = particleSensor.getFIFORed();
      particleSensor.nextSample();
      processSample(tu, ir, red);
      checkSyncPing();
    }
  }
  const int64_t now = nowUs();
  if (hasMlx && now - lastMlxUs >= (int64_t)MLX_INTERVAL_US) {
    lastMlxUs = now;
    objectTemp = mlx.readObjectTempC();
  }
  if (now - lastEnvUs >= (int64_t)ENV_INTERVAL_US) {
    lastEnvUs = now;
    if (hasAht) {
      sensors_event_t hum, temp;
      aht.getEvent(&hum, &temp);
      ambientTemp = temp.temperature;
      humidity = hum.relative_humidity;
    }
    if (hasBmp) {
      float p = bmp.readPressure();
      pressure = isnan(p) ? 0 : p / 100.0F;
    }
  }
  if (!hasPpg && now - lastSampleUs >= 100000) {
    // sem MAX30102: mantem um pacote a 10 Hz para o app validar os sensores ambientais
    lastSampleUs = now;
    sampleCounter++;
    sendJson(now, 0, 0, false);
  }
#endif
}
