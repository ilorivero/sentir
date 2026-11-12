# Firmware Monitor Oasis — SENTIR

Evolução do `esp32/monitorcardiaco/monitorcardiaco.ino` do [monitor_oasis](https://github.com/ilorivero/monitor_oasis), **compatível com o app atual**: mesmas chaves JSON e o mesmo ping/pong de relógio. Um único código (`Oasis_SENTIR/`) compila na **Arduino IDE** e no **ESP-IDF**.

## Correções em relação ao firmware atual

| # | Problema no firmware atual | Efeito | Correção |
|---|---|---|---|
| 1 | `setup(…, sampleAverage=4, …, sampleRate=100, …)` → saída de **25 Hz** (100/4) | IBI quantizado em 40 ms: SDNN/rMSSD/pNN50 enviesados | `sampleRate=400`, média 4 → **100 Hz** reais; FIFO esvaziado a cada volta (nenhuma amostra perdida) |
| 2 | `"pt": micros()` de 32 bits | dá a volta a cada **71,6 min** de ESP32 ligado: `bootEpochUs` do app salta 71 min e `device_wall_clock_us` fica errado | `pt` com `esp_timer_get_time()` (64 bits) |
| 3 | `"t": millis()` no instante do **envio** | erro de alguns ms por amostra | `"t"` e `"tu"` (µs, 64 bits) no instante de **captura**; `"n"` = contador (detecta perdas) |
| 4 | MLX90614 lido a cada volta (~1 ms de I²C) | atrasa o laço | 4 Hz |
| 5 | IBI medido com `millis()` do processamento | *jitter* do laço entra no IBI | diferença entre instantes de captura |
| 6 | pong sem instante de chegada | NTP incompleto | `"t2"` (chegada do 1º byte do ping) além de `"pt"` (= t3) |

Campos novos (`tu`, `n`, `t2`) são ignorados pelo app atual; aproveitá-los no `serial_capture_isolate.dart` é tarefa da etapa E3.

`SENTIR_FAKE_SENSORS 1` gera PPG sintético (~72 bpm) num ESP32-C3 **sem sensores** para testar o caminho USB → app → SQLite. Nunca use em coleta real.

## Arduino IDE

1. Core esp32 3.3.x; placa **ESP32C3 Dev Module**; USB CDC On Boot **Enabled**.
2. Bibliotecas (Gerenciador de Bibliotecas, nestas versões): SparkFun MAX3010x 1.1.2 · Adafruit MLX90614 2.1.7 · Adafruit AHTX0 2.0.6 · Adafruit BMP280 3.0.0 · Adafruit BusIO 1.17.4 · Adafruit Unified Sensor 1.1.15.
3. Abra `Oasis_SENTIR/Oasis_SENTIR.ino`. A lógica está em `oasis_sentir.cpp`, para a IDE não gerar protótipos automáticos.

## ESP-IDF 5.5

```bash
./fetch_libs.sh            # Windows: .\fetch_libs.ps1  — baixa as bibliotecas nas versões acima
cd idf
idf.py set-target esp32c3
idf.py build flash monitor
idf.py -B build_fake -D SDKCONFIG=build_fake/sdkconfig \
       -D SDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.fake" build    # sensores simulados
```

As bibliotecas Arduino viram um componente IDF (`idf/components/oasis_arduino_libs`).

## Verificação feita (12/11/2026)

| Build | Resultado |
|---|---|
| Arduino core 3.3.4 — real, simulado e o `monitorcardiaco.ino` original | os três compilam (339 KB para o SENTIR; 336 KB para o original) |
| ESP-IDF v5.5.1 — real e simulado | compilam (0x509C0 bytes, 69 % livre) |

Não rodou em hardware.
