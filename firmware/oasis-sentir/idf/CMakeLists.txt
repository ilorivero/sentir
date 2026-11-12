# SENTIR - firmware do Monitor Oasis pelo ESP-IDF (Arduino como componente).
# Fontes: ../Oasis_SENTIR (as MESMAS da Arduino IDE). Bibliotecas: ../libraries (fetch_libs).
cmake_minimum_required(VERSION 3.16)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
idf_build_set_property(COMPILE_DEFINITIONS "ARDUINO_USB_MODE=1" APPEND)
idf_build_set_property(COMPILE_DEFINITIONS "ARDUINO_USB_CDC_ON_BOOT=1" APPEND)
project(oasis_sentir)
