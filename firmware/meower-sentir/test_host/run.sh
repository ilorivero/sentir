#!/usr/bin/env bash
# Teste do emulador do ADS1299 no PC (sem ESP32): g++ + stubs minimos.
set -e
cd "$(dirname "$0")"
g++ -std=c++17 -DSENTIR_FAKE_ADC=1 -Istub -I../Meower_SENTIR test_fake_adc.cpp ../Meower_SENTIR/sentir_fake_adc.cpp -o /tmp/test_fake_adc
/tmp/test_fake_adc
