// SPDX-License-Identifier: MIT OR Apache-2.0
// SENTIR - opcoes de compilacao do firmware Meower (Arduino IDE e ESP-IDF).
//
// Arduino IDE: edite os valores abaixo.
// ESP-IDF:     use `idf.py menuconfig` -> "SENTIR Meower" (o Kconfig define CONFIG_SENTIR_*),
//              ou edite aqui; o CMake do projeto IDF repassa CONFIG_* para estes nomes.
#pragma once
#if defined(__has_include)
  #if __has_include("sdkconfig.h")
    #include "sdkconfig.h"   // ESP-IDF: opcoes CONFIG_SENTIR_* do menuconfig
  #endif
#endif

#define SENTIR_FW_VERSION "sentir-meower-0.2"

// Numero de ADS1299 montados: 0 = detecta no boot (le o ID do escravo na cadeia),
// 1 = forca 8 canais (so o mestre), 2 = forca 16 canais.
#ifndef SENTIR_ADS_COUNT
  #if defined(CONFIG_SENTIR_ADS_COUNT)
    #define SENTIR_ADS_COUNT CONFIG_SENTIR_ADS_COUNT
  #else
    #define SENTIR_ADS_COUNT 0
  #endif
#endif

// 1 = ADS1299 emulado em software (teste num ESP32-C3 qualquer, SEM a placa):
//     registradores emulados, DRDY gerado por timer na taxa configurada, sinais sinteticos
//     (alfa 10 Hz, rede 60 Hz, ruido) e bit de "fotodiodo" no GPIO1 do status.
// NUNCA usar para coletar dados de participantes.
#ifndef SENTIR_FAKE_ADC
  #if defined(CONFIG_SENTIR_FAKE_ADC)
    #define SENTIR_FAKE_ADC 1
  #else
    #define SENTIR_FAKE_ADC 0
  #endif
#endif

// Com SENTIR_FAKE_ADC: quantos ADS1299 emular (1 = placa de 8 canais da v1).
#ifndef SENTIR_FAKE_ADS_COUNT
  #if defined(CONFIG_SENTIR_FAKE_ADS_COUNT)
    #define SENTIR_FAKE_ADS_COUNT CONFIG_SENTIR_FAKE_ADS_COUNT
  #else
    #define SENTIR_FAKE_ADS_COUNT 1
  #endif
#endif

// Com SENTIR_FAKE_ADC: GPIO do ESP32 lido como "fotodiodo" (nivel ALTO = luz).
// -1 = onda quadrada interna de 1 Hz (para testes automaticos).
// Ex.: 3 = pino do DRDY (livre no modo emulado) com um fototransistor e pull-down;
//      9 = botao BOOT da maioria dos devkits (ativo em BAIXO -> invertido no codigo).
#ifndef SENTIR_FAKE_PD_PIN
  #if defined(CONFIG_SENTIR_FAKE_PD_PIN)
    #define SENTIR_FAKE_PD_PIN CONFIG_SENTIR_FAKE_PD_PIN
  #else
    #define SENTIR_FAKE_PD_PIN -1
  #endif
#endif

#ifdef __cplusplus
#include <stdint.h>
// Numero de ADS1299 efetivamente em uso (definido no boot por sentir_detect_ads_count()).
extern volatile uint8_t g_adsCount;
#endif
