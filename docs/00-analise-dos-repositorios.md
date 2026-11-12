# 00 — Análise dos repositórios de origem

Análise de 12/11/2026.

| Repositório | Versão | Papel no SENTIR |
|---|---|---|
| [nikki-uwu/Meower](https://github.com/nikki-uwu/Meower) | `c6f4102` | base do firmware e do driver BrainFlow da placa EEG (eletroencefalografia) |
| [brainflow-dev/brainflow](https://github.com/brainflow-dev/brainflow) | `master` de 10/11/2026 | biblioteca de aquisição; recebe o driver `MeowerBoard` |
| [ilorivero/monitor_oasis](https://github.com/ilorivero/monitor_oasis) | `1944b19` | **app das estações e do Painel Central**, firmware do Monitor Oasis |

## 1. monitor_oasis

App Flutter/Windows maduro: protocolo OASIS (Open Affective Standardized Image Set) com pré-carregamento e confirmação de apresentação (`presentation_ack`), captura serial em *isolate* dedicada, SQLite versionado, HRV (variabilidade da frequência cardíaca) validada, CUSUM (soma cumulativa) para instante de reação, modo distribuído Estação + Painel Central com comandos remotos e sincronização de relógio em dois elos. O próprio `CLAUDE.md` do projeto aponta o limite: "para precisão sub-quadro (ex.: ERPs) seria necessário fotodiodo". O SENTIR entra exatamente aí, sem refazer o que já funciona.

**Decisão**: o monitor_oasis continua sendo o app de estações e servidor. O SENTIR acrescenta um **agente EEG** separado (Python + BrainFlow) em cada estação e um patch pequeno no app (`integration/monitor_oasis`). O esqueleto Flutter próprio da v0.1 do SENTIR foi descartado.

### Problemas encontrados no firmware `esp32/monitorcardiaco/monitorcardiaco.ino`

| # | Problema | Consequência | Corrigido em `firmware/oasis-sentir` |
|---|---|---|---|
| 1 | `particleSensor.setup(60, 4, 2, 100, 411, 4096)`: taxa 100 Hz com média de 4 | o MAX30102 entrega **25 Hz**; o IBI (intervalo entre batimentos) fica quantizado em 40 ms, o que enviesa SDNN/rMSSD/pNN50. O `CLAUDE.md` assume ~100 Hz | 400 Hz com média de 4 = 100 Hz (configuração para a qual o `checkForBeat` da SparkFun foi ajustado) e leitura de todo o FIFO |
| 2 | `"pt": micros()` (32 bits) | dá a volta a cada **71,6 min** de ESP32 ligado: `bootEpochUs = meio do RTT − pt` salta 71 min e `device_wall_clock_us` fica errado. Num dia de laboratório o ESP32 fica ligado por horas | `pt` em 64 bits (`esp_timer_get_time`) |
| 3 | `"t": millis()` no envio, IBI medido com `millis()` do laço | *jitter* do laço entra no timestamp e no IBI | instante de captura (`t`, `tu`) e IBI entre capturas |
| 4 | MLX90614 lido a cada volta do laço | ~1 ms de I²C por amostra | 4 Hz |

O `.ino` original foi compilado aqui sem alterações (Arduino core 3.3.4) para comparar o tamanho do binário.

## 2. Meower (placa EEG)

ESP32-C3 + 2× ADS1299 em cadeia (*daisy-chain*), 16 canais, Wi-Fi/UDP, bateria. Tarefa do ADC (conversor analógico-digital) acordada pelo DRDY (*data ready*); cada quadro leva um tick de 8 µs (32 bits).

### Placa de 8 canais (só o ADS1299 mestre)

A afirmação "como ele trabalha em cascata, não vai ser um problema" vale para os **dados**, mas não para os **comandos**:

| Situação | O que acontece no firmware original | Correção SENTIR |
|---|---|---|
| leitura de dados (54 bytes em cadeia) | os 27 bytes do escravo vêm do pino DAISY_IN do mestre: lixo, se o pino estiver solto | slots 9–15 zerados; slot 16 recebe o **status do mestre** (lead-off + GPIO) |
| `modify_register_bits` (usado por `usr gain ALL`, entradas, SRB2, BIAS…) | escreve nos dois chips e **exige que o escravo confirme** → todo comando responde **`ERR`** | verifica só o mestre quando há 1 chip |
| comando em canal 9–16 | falha silenciosa | `ERR` explícito |
| quantos chips? | fixo em 2 | detecta no boot pelo ID do escravo (0x3E), com opção de forçar |

**Recomendação de PCB (placa de circuito impresso)**: resistor de *pull-down* (10 kΩ) no DAISY_IN do mestre até o 2º chip ser montado, e os pinos GPIO1–4 do ADS1299 mestre em um conector (fotodiodo no GPIO1). Ver [06-hardware.md](06-hardware.md).

### Outros pontos

1. Comandos passam por uma fila de 50 ms → TSYNC respondido no *callback* AsyncUDP.
2. `printf` com newlib-nano não formata 64 bits → conversão manual.
3. O código compila na **Arduino IDE** (core 3.3.4) e no **ESP-IDF** 5.5.1 com o Arduino como componente — verificado aqui, nos dois modos (real e emulado).

## 3. Driver BrainFlow do Meower (`BrainFlow_files/vrchatboard`)

Não está no BrainFlow oficial. Problemas: ID 65 já é `IRONBCI_32_BOARD`; *keep-alive* `floof` (o firmware espera `WOOF_WOOF`, então a placa nunca aceitaria comandos); offset de tempo fixado no 1º pacote (36–144 ms/h de deriva); tick de 32 bits sem desdobramento; EEG em volts sem dividir pelo ganho; `start_cnt` antes da thread de leitura. O driver `MeowerBoard` corrige tudo, lê o `ID?` (8 ou 16 canais) e exporta o status na linha 23. Compilado e testado com o simulador.

## 4. BrainFlow

IDs validados em `FIRST..LAST` → o ID novo precisa ser contíguo (hoje **69**). *Preset* `ancillary` usado para os pares TSYNC. `insert_marker` tem até 20 ms de erro com pacotes de 20 ms → os eventos ficam em `events.parquet` com tempo próprio.
