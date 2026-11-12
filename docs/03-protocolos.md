# 03 — Protocolos (contratos entre as partes)

Estes contratos são a fronteira entre firmware, agente EEG e monitor_oasis. Mudou algo aqui? Atualize os dois lados, os simuladores em `tools/` e os testes no mesmo commit.

## 1. Meower ⇄ agente EEG — UDP (User Datagram Protocol)

Formato de dados **igual ao do Meower original**.

### Portas e endereços

Cada estação recebe a sua Meower; como cada uma tem IP próprio, as portas podem ser as mesmas em todas: controle **5000**, dados **5001**. Configure o Wi-Fi e as portas pelo portal `EEG-SETUP` da placa ou pela serial (`set port_ctrl …`, `set port_data …`, `apply`).

### Datagrama de dados

```
[quadro 0][quadro 1]...[quadro N-1][bateria float32 LE]      N = 1..28
quadro (52 B) = 16 slots x int24 big-endian + uint32 little-endian (tick de 8 us)
```

* EEG em µV: `raw × (4,5 V / 2²³) × 10⁶ / (PGA × ganho_digital)` (PGA = amplificador de ganho programável).
* **Placa de 8 canais** (`ads=1` no `ID?`): slots 1–8 = EEG; slots 9–15 = 0; **slot 16 = status do ADS1299 mestre**:

| Bits | Campo | Uso |
|---|---|---|
| 23..20 | `1100` | cabeçalho (valida o status) |
| 19..12 | LOFF_STATP | eletrodo positivo solto, 1 bit por canal (com lead-off habilitado) |
| 11..4 | LOFF_STATN | eletrodo negativo solto |
| 3..0 | GPIO4..GPIO1 | **GPIO1 = fotodiodo** (via comparador) |

### Controle (texto UTF-8)

| PC → placa | Placa → PC | Notas |
|---|---|---|
| `WOOF_WOOF` | — | descoberta e *keep-alive* (enviar a cada menos de 10 s) |
| `sys start_cnt` / `sys stop_cnt` | — | sem resposta |
| `usr set_sampling_freq 1000`, `usr gain ALL 24`, … | `OK: …` / `ERR: …` | param o streaming; com 1 ADS1299, canais 9–16 respondem `ERR` |
| **`TSYNC <seq>`** | **`TSYNC <seq> <t2> <t3>`** | ticks de 8 µs, 64 bits, em decimal; respondido no *callback* |
| **`ID?`** | **`ID <mac> SENTIR-TSYNC/1 ads=<1/2> fake=<0/1> fw=<versão>`** | `fake=1` = firmware de teste com ADS1299 emulado |

Placa → PC em broadcast: `MEOW_MEOW` (1 Hz) enquanto não descobriu o PC.

## 2. Monitor Oasis ⇄ monitor_oasis — serial USB (protocolo do monitor_oasis)

O SENTIR **mantém o protocolo existente** e só acrescenta campos. Uma linha JSON por pacote a 115200 baud.

```json
{"t":81234,"tu":81234567,"n":4512,"ir":112034,"red":90321,"bpm":72,"spo2":97,"hrv":833,
 "temp":33.42,"amb_temp":24.10,"hum":51.2,"press":1013.2,"beat":0}
{"pong":17,"t2":81299990,"pt":81300002}
{"hello":"oasis","fw":"sentir-oasis-0.2","mac":"AA:BB:CC:DD:EE:FF","ppg_hz":100,"fake":0,"sensors":"1111"}
```

| Campo | Firmware atual | Firmware SENTIR |
|---|---|---|
| `t` | `millis()` no envio | `millis()` no instante de **captura** |
| `tu`, `n` | — | µs de captura (64 bits) e contador de amostras |
| taxa de PPG | 25 Hz efetivos (`sampleRate` 100 com média de 4) | **100 Hz** (400 com média de 4) |
| `pt` do pong | `micros()` 32 bits (dá a volta em 71,6 min) | `esp_timer` 64 bits (= t3) |
| `t2` do pong | — | chegada do 1º byte do ping |
| `ID?` | — | responde `hello` |

PC → dispositivo: `{"cmd":"ping","id":N}\n` (Elo A) e, opcional, `ID?\n`.

## 3. monitor_oasis ⇄ agente EEG — WebSocket `ws://127.0.0.1:8765/ws/app`

Implementação de referência: `integration/monitor_oasis` (Dart) e `tools/app_sim.py` (Python).

| Direção | Mensagem | Quando |
|---|---|---|
| agente → app | `{"type":"tsync","seq":n}` | a cada 0,5 s até sincronizar, depois a cada 2 s |
| app → agente | `{"type":"tsync","seq":n,"t2":<us>,"t3":<us>}` | na hora; `DateTime.now().microsecondsSinceEpoch` |
| app → agente | `{"type":"session_start","station_id":"A","subject_code":"A-PARTICIPANTE_3","session_id":12,"protocol":{…}}` | 1º onset confirmado (baseline) |
| agente → app | `{"type":"session_started","dir":"…"}` | |
| app → agente | `{"type":"phase","exposure_id":345,"event_type":"STIMULUS","image_name":"Dog 4.jpg","category":"…","valence":5.9,"arousal":4.1,"start_ms":<ms>,"latency_ms":7}` | após cada `startExposure`, com o mesmo `start_timestamp` |
| app → agente | `{"type":"note","text":"…","t_ms":<ms>}` | anotação |
| app → agente | `{"type":"session_stop"}` | `_finishExperiment` |
| agente → app | `{"type":"session_stopped","summary":{"dir","rows","resync","photodiode_latency_ms"}}` | |
| agente → app | `{"type":"eeg_status",…}` | a cada 0,5 s (ver abaixo) |
| agente → app | `{"type":"eeg_preview","t0":<s>,"dt":<s>,"channels":[…],"data":[[…]]}` | a cada 0,5 s, EEG decimado a `preview_hz` |

`eeg_status` (resumo): `meower{state, channels, fs, frames, lost, battery_v, latency_ms, clock{uncertainty_ms, drift_ppm}}`, `device{mac, ads, fake, fw}`, `signal{channels, rms_uv[], saturated[], battery_v, loff_statp, loff_statn, photodiode}`, `recording`, `session_dir`, `events`, `app_sync_ms`, `photodiode_latency_ms`, `error`, `warning`.

REST de apoio (testes e uso sem o app): `GET /api/status`, `POST /api/session/start {"subject_code"}`, `POST /api/session/stop`.

## 4. Estação ⇄ Painel Central — WebSocket do monitor_oasis

Sem mudanças nas mensagens existentes (`status`, `telemetry_batch`, `command`, `time_sync_*`). O SENTIR acrescenta:

* `status.eeg`: `{state, channels, battery_v, lost, sync_ms, app_sync_ms, rms_uv[], saturated[], photodiode_latency_ms, recording, error, warning}`;
* mensagem `eeg_preview` (mesmo conteúdo da seção 3), repassada pela estação. O Painel Central atual a ignora; o gráfico é a tarefa E3.4.
