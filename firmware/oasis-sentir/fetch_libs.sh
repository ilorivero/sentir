#!/usr/bin/env bash
# Baixa as bibliotecas Arduino do Monitor Oasis (versoes fixas) para ./libraries.
# Arduino IDE: alternativa = Gerenciador de Bibliotecas, mesmas versoes.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p libraries && cd libraries
get() { [ -d "$2" ] || git -c advice.detachedHead=false clone -q --depth 1 --branch "$3" "https://github.com/$1.git" "$2"; }
get sparkfun/SparkFun_MAX3010x_Sensor_Library SparkFun_MAX3010x_Sensor_Library v1.1.2
get adafruit/Adafruit-MLX90614-Library Adafruit-MLX90614-Library 2.1.7
get adafruit/Adafruit_AHTX0 Adafruit_AHTX0 2.0.6
get adafruit/Adafruit_BMP280_Library Adafruit_BMP280_Library 3.0.0
get adafruit/Adafruit_BusIO Adafruit_BusIO 1.17.4
get adafruit/Adafruit_Sensor Adafruit_Sensor 1.1.15
echo "Bibliotecas em $(pwd)"
