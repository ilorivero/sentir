#!/usr/bin/env bash
# SENTIR - compila os dois firmwares nas duas toolchains (Arduino e ESP-IDF), nos modos
# real e de teste (emulado). Requisitos: arduino-cli com o core esp32 3.3.x e as bibliotecas
# do Oasis instaladas; ESP-IDF 5.5 exportado (". $IDF_PATH/export.sh").
# Uso: ./build_all.sh [arduino|idf|all]
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
WHAT="${1:-all}"
FQBN="espressif:esp32:esp32c3:CDCOnBoot=cdc,CPUFreq=160"
OUT="$HERE/_out"; mkdir -p "$OUT"

if [[ "$WHAT" == arduino || "$WHAT" == all ]]; then
  for fake in 0 1; do
    echo "== Arduino: Meower (SENTIR_FAKE_ADC=$fake)"
    arduino-cli compile --fqbn "$FQBN" --build-property "compiler.cpp.extra_flags=-DSENTIR_FAKE_ADC=$fake" \
      --output-dir "$OUT/meower_arduino_fake$fake" "$HERE/meower-sentir/Meower_SENTIR"
    echo "== Arduino: Oasis (SENTIR_FAKE_SENSORS=$fake)"
    arduino-cli compile --fqbn "$FQBN" --build-property "compiler.cpp.extra_flags=-DSENTIR_FAKE_SENSORS=$fake" \
      --output-dir "$OUT/oasis_arduino_fake$fake" "$HERE/oasis-sentir/Oasis_SENTIR"
  done
fi

if [[ "$WHAT" == idf || "$WHAT" == all ]]; then
  [ -d "$HERE/oasis-sentir/libraries" ] || "$HERE/oasis-sentir/fetch_libs.sh"
  for proj in meower-sentir oasis-sentir; do
    cd "$HERE/$proj/idf"
    echo "== ESP-IDF: $proj (real)"
    idf.py -B build -D SDKCONFIG=build/sdkconfig build
    echo "== ESP-IDF: $proj (teste/emulado)"
    idf.py -B build_fake -D SDKCONFIG=build_fake/sdkconfig \
      -D SDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.fake" build
  done
fi
echo "OK"
