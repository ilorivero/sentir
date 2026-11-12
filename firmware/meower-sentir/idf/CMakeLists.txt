# SENTIR - firmware Meower compilado pelo ESP-IDF (Arduino como componente).
# Fontes: ../Meower_SENTIR (as MESMAS da Arduino IDE).  idf.py set-target esp32c3 && idf.py build
cmake_minimum_required(VERSION 3.16)
# O Arduino como componente vem do registro da Espressif (main/idf_component.yml) ou, sem
# internet, de uma copia local em ./components/arduino (ver ../README.md).
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
# Equivalente a "USB CDC On Boot: Enabled" da Arduino IDE: Serial = USB nativo do ESP32-C3.
# Precisa valer para TODOS os componentes (inclusive o nucleo do Arduino).
idf_build_set_property(COMPILE_DEFINITIONS "ARDUINO_USB_MODE=1" APPEND)
idf_build_set_property(COMPILE_DEFINITIONS "ARDUINO_USB_CDC_ON_BOOT=1" APPEND)
project(meower_sentir)
