// SPDX-License-Identifier: MIT OR Apache-2.0
// SENTIR - emulador do ADS1299 para testar o firmware Meower num ESP32-C3 sem a placa.
#pragma once
#include <stdint.h>
#include "sentir_config.h"

#if SENTIR_FAKE_ADC
// Substitui a transferencia SPI (chamado no inicio de xfer()). Retorna true se tratou.
bool sentir_fake_xfer(char target, uint8_t length, const uint8_t* tx, uint8_t* rx);
// Inicia o timer que imita o DRDY (chamar no fim do setup()).
void sentir_fake_begin(void* adcTaskHandle);
// Ajusta o periodo do timer quando a taxa muda (chamar no loop()).
void sentir_fake_update();
#endif
