# Firmware Meower — SENTIR

Firmware da placa EEG (ESP32-C3 + ADS1299), derivado de [nikki-uwu/Meower](https://github.com/nikki-uwu/Meower) (commit `c6f4102`, MIT ou Apache-2.0). **Um único código-fonte** (`Meower_SENTIR/`) compila na **Arduino IDE** e no **ESP-IDF**.

O diff completo em relação ao original está em `patches/sentir-vs-upstream-c6f4102.diff`. Todas as alterações estão marcadas com `SENTIR` no código.

## O que muda em relação ao Meower original

| Mudança | Arquivo | Por quê |
|---|---|---|
| `TSYNC <seq>` → `TSYNC <seq> <t2> <t3>` e `ID?` → `ID <mac> SENTIR-TSYNC/1 ads=<1/2> fake=<0/1> fw=…`, respondidos no *callback* AsyncUDP | `net_manager.cpp` | sincronização de relógio sem os ~50 ms da fila de comandos |
| Detecção de quantos ADS1299 estão montados (ID do escravo na leitura em cadeia) | `helpers.cpp` | a placa v1 tem **só o ADS1299 mestre** (8 canais) |
| Verificação de registradores ignora o escravo ausente | `messages_lib.cpp` | sem isso, **todo** comando `usr` (ganho, entradas, SRB2…) responde `ERR` numa placa de 8 canais |
| Placa de 8 canais: slots 9–15 zerados e **status do ADS1299 no slot 16** | `main.cpp` | lead-off e **fotodiodo no GPIO1** do ADS1299, sem gastar canal de EEG; formato do pacote inalterado |
| `SENTIR_FAKE_ADC`: ADS1299 emulado | `sentir_fake_adc.*`, `spi_lib.cpp` | testar firmware + Wi-Fi + PC num ESP32-C3 comum, **antes de fabricar a placa** |

## Opções (`sentir_config.h` ou `idf.py menuconfig` → "SENTIR Meower")

| Opção | Padrão | Efeito |
|---|---|---|
| `SENTIR_ADS_COUNT` | 0 | 0 = detecta no boot; 1 = força 8 canais; 2 = força 16 |
| `SENTIR_FAKE_ADC` | 0 | 1 = ADS1299 emulado (**nunca** com participantes; o `ID?` responde `fake=1` e o agente avisa) |
| `SENTIR_FAKE_ADS_COUNT` | 1 | chips emulados |
| `SENTIR_FAKE_PD_PIN` | -1 | GPIO lido como fotodiodo no modo emulado (-1 = onda de 1 Hz; 3 = pino do DRDY, livre no modo emulado; 9 = botão BOOT) |

## Arduino IDE

1. Core **esp32 da Espressif 3.3.x** (Gerenciador de Placas).
2. Abra `Meower_SENTIR/Meower_SENTIR.ino`.
3. Placa **ESP32C3 Dev Module** · USB CDC On Boot **Enabled** · CPU **160 MHz** · Flash Mode **DIO** · Partition **Default 4MB with spiffs**.
4. Para testar sem a placa: `#define SENTIR_FAKE_ADC 0` → `1` em `sentir_config.h`.

Não precisa de bibliotecas externas: o firmware só usa as do core (WiFi, AsyncUDP, SPI, Preferences, WebServer).

## ESP-IDF 5.5 (Arduino como componente)

```bash
cd idf
idf.py set-target esp32c3
idf.py build flash monitor                       # placa real
# modo de teste (ADS1299 emulado) numa pasta de build separada:
idf.py -B build_fake -D SDKCONFIG=build_fake/sdkconfig \
       -D SDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.fake" build flash monitor
```

`main/idf_component.yml` baixa `espressif/arduino-esp32 3.3.4` do registro da Espressif. Sem internet: clone `https://github.com/espressif/arduino-esp32` (tag `3.3.4`) em `idf/components/arduino-esp32` e exporte `IDF_COMPONENT_MANAGER=0`.

As flags de compilação (USB CDC no boot, 160 MHz, partição grande, `-O3`) estão em `idf/CMakeLists.txt`, `idf/main/CMakeLists.txt` e `idf/sdkconfig.defaults`.

## Verificação feita (12/11/2026)

| Build | Resultado |
|---|---|
| Arduino core 3.3.4, real e emulado | compila (1,05 MB, 80 % da partição padrão) |
| ESP-IDF v5.5.1 + arduino-esp32 3.3.4, real e emulado | compila (0xFCD80 / 0xFE780 bytes, 33 % livre na partição *single app large*) |
| `test_host/run.sh` (emulador no PC) | ID 0x3E/0x00 (1 chip), registradores, status com GPIO1, sinal com RMS esperado |

**Ainda não rodou num ESP32-C3 de verdade** — é o primeiro passo da etapa E1 ([docs/08-testes-sem-placa.md](../../docs/08-testes-sem-placa.md)).
