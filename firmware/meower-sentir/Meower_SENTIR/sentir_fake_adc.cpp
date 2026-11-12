// SPDX-License-Identifier: MIT OR Apache-2.0
// SENTIR - emulador do ADS1299 (ver sentir_config.h, SENTIR_FAKE_ADC).
//
// Emula o suficiente do ADS1299 para o firmware Meower rodar sem modificacoes no resto:
//  - comandos SPI SDATAC/RDATAC/START/STOP/RESET (ignorados ou resetam registradores);
//  - RREG/WREG nos alvos 'M', 'S' e 'B' (leitura em cadeia de 30 bytes: mestre em rx[2],
//    escravo em rx[29]), com ID 0x3E e valores de reset do datasheet;
//  - leitura de dados (54 bytes de zeros enviados): 2 x (status de 3 bytes + 8 canais),
//    com o ganho PGA dos registradores CHnSET aplicado;
//  - DRDY: esp_timer periodico na taxa de CONFIG1 (250..4000 Hz) acordando a tarefa do ADC.
#include "sentir_fake_adc.h"

#if SENTIR_FAKE_ADC
#include <Arduino.h>
#include <esp_timer.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <math.h>
#include <string.h>

namespace {
constexpr int NREG = 0x18;
uint8_t regs[2][NREG];               // [0] mestre, [1] escravo
bool present[2] = {true, SENTIR_FAKE_ADS_COUNT >= 2};
TaskHandle_t adcTask = nullptr;
esp_timer_handle_t timer = nullptr;
uint32_t currentPeriodUs = 0;
uint32_t sampleIndex = 0;
uint32_t rng = 0x12345678u;
constexpr float LSB_UV = 4.5f / 8388608.0f * 1e6f;

void resetRegs(int chip) {
    memset(regs[chip], 0, NREG);
    regs[chip][0x00] = 0x3E;            // ID ADS1299
    regs[chip][0x01] = 0x96;            // CONFIG1: 250 SPS
    regs[chip][0x02] = 0xC0;
    regs[chip][0x03] = 0x60;
    for (int r = 0x05; r <= 0x0C; r++) regs[chip][r] = 0x61;  // CHnSET: PGA 24, entrada em curto
    regs[chip][0x14] = 0x0F;            // GPIO: todos entradas
}

inline uint32_t xorshift() { rng ^= rng << 13; rng ^= rng >> 17; rng ^= rng << 5; return rng; }
inline float gaussish() {               // soma de 4 uniformes ~ gaussiana (barato)
    float s = 0; for (int i = 0; i < 4; i++) s += (xorshift() & 0xFFFF) / 65535.0f;
    return (s - 2.0f) * 1.7f;
}

int pgaFromReg(uint8_t chset) {
    static const int lut[8] = {1, 2, 4, 6, 8, 12, 24, 24};
    return lut[(chset >> 4) & 0x07];
}

uint32_t periodFromConfig1() {
    static const uint32_t hz[8] = {16000, 8000, 4000, 2000, 1000, 500, 250, 250};
    return 1000000u / hz[regs[0][0x01] & 0x07];
}

bool photodiodeLevel() {
#if SENTIR_FAKE_PD_PIN >= 0
    // BOOT (GPIO9) e ativo em baixo; um fototransistor com resistor de pull-down e ativo em alto.
    int v = digitalRead(SENTIR_FAKE_PD_PIN);
    return SENTIR_FAKE_PD_PIN == 9 ? (v == LOW) : (v == HIGH);
#else
    return (esp_timer_get_time() % 1000000) < 500000;  // 1 Hz, 50 %
#endif
}

void put24(uint8_t* p, int32_t v) {
    if (v > 8388607) v = 8388607;
    if (v < -8388608) v = -8388608;
    p[0] = (uint8_t)((v >> 16) & 0xFF);
    p[1] = (uint8_t)((v >> 8) & 0xFF);
    p[2] = (uint8_t)(v & 0xFF);
}

void fillSample(uint8_t* rx, uint8_t length) {
    memset(rx, 0, length);
    const float t = sampleIndex * (periodFromConfig1() * 1e-6f);
    sampleIndex++;
    const uint8_t gpioIn = photodiodeLevel() ? 0x1 : 0x0;   // GPIO1 = fotodiodo
    for (int chip = 0; chip < 2; chip++) {
        uint8_t* blk = rx + chip * 27;
        if (chip * 27 + 27 > length) break;
        if (!present[chip]) continue;          // sem chip: DAISY_IN com pull-down -> zeros
        // status: 1100 + LOFF_STATP(8) + LOFF_STATN(8) + GPIO[4:1]
        uint32_t status = 0xC00000u | (chip == 0 ? gpioIn : 0);
        blk[0] = (status >> 16) & 0xFF; blk[1] = (status >> 8) & 0xFF; blk[2] = status & 0xFF;
        for (int ch = 0; ch < 8; ch++) {
            const int g = pgaFromReg(regs[chip][0x05 + ch]);
            const uint8_t mux = regs[chip][0x05 + ch] & 0x07;
            float uv;
            if (mux == 0x01) {                  // SHORTED: so ruido do amplificador
                uv = 0.3f * gaussish();
            } else if (mux == 0x05) {           // TEST: quadrada interna ~3,75 mV, 1 Hz
                uv = (fmodf(t, 1.0f) < 0.5f) ? 1875.0f : -1875.0f;
            } else {
                const int idx = chip * 8 + ch;
                uv = 20.0f * sinf(2.0f * (float)M_PI * 10.0f * t + idx)     // alfa
                   + 5.0f * sinf(2.0f * (float)M_PI * 60.0f * t)           // rede eletrica
                   + 3.0f * gaussish();
            }
            put24(blk + 3 + ch * 3, (int32_t)lroundf(uv * g / LSB_UV));
        }
    }
}

void IRAM_ATTR onTimer(void*) {
    if (adcTask) xTaskNotifyGive(adcTask);
}
}  // namespace

bool sentir_fake_xfer(char target, uint8_t length, const uint8_t* tx, uint8_t* rx) {
    static bool init = false;
    if (!init) { resetRegs(0); resetRegs(1); init = true; }
    const uint8_t op = tx[0];
    int chips[2]; int n = 0;
    if (target == 'M' || target == 'B') chips[n++] = 0;
    if (target == 'S' || target == 'B') chips[n++] = 1;

    if (op == 0x00 && length >= 27) {           // leitura de amostra (RDATAC: zeros no MOSI)
        fillSample(rx, length);
        return true;
    }
    memset(rx, 0, length);
    if (op == 0x06) { resetRegs(0); resetRegs(1); return true; }   // RESET
    if ((op & 0xE0) == 0x20 && length >= 3) {   // RREG
        const uint8_t addr = op & 0x1F, cnt = tx[1] + 1;
        for (int k = 0; k < n; k++) {
            const int chip = chips[k];
            if (!present[chip]) continue;
            const int base = (target == 'B') ? chip * 27 : 0;
            for (int i = 0; i < cnt && base + 2 + i < length && addr + i < NREG; i++)
                rx[base + 2 + i] = regs[chip][addr + i];
        }
        return true;
    }
    if ((op & 0xE0) == 0x40 && length >= 3) {   // WREG
        const uint8_t addr = op & 0x1F, cnt = tx[1] + 1;
        for (int k = 0; k < n; k++) {
            const int chip = chips[k];
            if (!present[chip]) continue;
            for (int i = 0; i < cnt && 2 + i < length && addr + i < NREG; i++)
                if (addr + i != 0x00) regs[chip][addr + i] = tx[2 + i];
        }
        return true;
    }
    return true;  // SDATAC/RDATAC/START/STOP/WAKEUP/STANDBY: nada a fazer
}

void sentir_fake_begin(void* handle) {
    adcTask = (TaskHandle_t)handle;
#if SENTIR_FAKE_PD_PIN >= 0
    pinMode(SENTIR_FAKE_PD_PIN, SENTIR_FAKE_PD_PIN == 9 ? INPUT_PULLUP : INPUT_PULLDOWN);
#endif
    esp_timer_create_args_t args = {};
    args.callback = &onTimer;
    args.name = "fake_drdy";
    esp_timer_create(&args, &timer);
    currentPeriodUs = periodFromConfig1();
    esp_timer_start_periodic(timer, currentPeriodUs);
}

void sentir_fake_update() {
    if (!timer) return;
    const uint32_t p = periodFromConfig1();
    if (p != currentPeriodUs) {
        esp_timer_stop(timer);
        currentPeriodUs = p;
        esp_timer_start_periodic(timer, p);
    }
}
#endif  // SENTIR_FAKE_ADC
