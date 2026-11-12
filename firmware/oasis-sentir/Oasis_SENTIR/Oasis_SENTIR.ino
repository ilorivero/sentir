// SENTIR - firmware do Monitor Oasis (ESP32-C3 + MAX30102 + MLX90614 + AHT20/BMP280).
//
// Derivado de monitor_oasis/esp32/monitorcardiaco/monitorcardiaco.ino e 100 % compativel com
// o app monitor_oasis: as mesmas chaves JSON (t, ir, red, bpm, spo2, hrv, temp, amb_temp, hum,
// press, beat) e o mesmo ping/pong de relogio ({"cmd":"ping","id":N} -> {"pong":N,"pt":...}).
//
// O que muda (ver docs/00-analise-dos-repositorios.md, secao monitor_oasis):
//  1. PPG a 100 Hz de verdade: sampleRate=400 com media de 4 (o original, 100 com media de 4,
//     entregava 25 Hz -> IBI quantizado em 40 ms) e o FIFO do sensor e esvaziado a cada volta,
//     um pacote por amostra (nenhuma amostra perdida).
//  2. "tu": instante de CAPTURA da amostra em us (esp_timer, 64 bits) e "n": contador de
//     amostras (detecta perdas). "t" (millis) continua existindo, agora tambem do instante da
//     captura (antes era o instante do envio).
//  3. "pt" do pong em 64 bits (esp_timer). O original usava micros() de 32 bits, que da a volta
//     a cada ~71,6 min de ligado: depois disso o bootEpochUs do app salta 71 min.
//     Pong ganha "t2" (chegada do 1o byte do ping) para o calculo NTP completo.
//  4. MLX90614 lido a 4 Hz (antes a cada volta: ~1 ms de I2C por amostra).
//  5. IBI ("hrv") medido entre os instantes de captura dos batimentos, nao do processamento.
//  6. SENTIR_FAKE_SENSORS: testa todo o caminho USB/sincronizacao num ESP32-C3 sem sensores.
//
// Compila na Arduino IDE (core esp32 3.x, placa "ESP32C3 Dev Module", USB CDC On Boot: Enabled)
// e no ESP-IDF (pasta ../idf, Arduino como componente). Bibliotecas: SparkFun MAX3010x,
// Adafruit MLX90614, Adafruit AHTX0, Adafruit BMP280 (+ Adafruit BusIO e Unified Sensor).

#include "oasis_sentir.h"

void setup() { oasis_setup(); }
void loop() { oasis_loop(); }
