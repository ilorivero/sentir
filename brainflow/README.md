# Driver BrainFlow `MeowerBoard` (SENTIR)

Driver C++ para a placa Meower (ESP32-C3 + 2× ADS1299) dentro do BrainFlow, derivado do `VrchatBoard` do repositório Meower e corrigido para o SENTIR (lista de correções em [../docs/00-analise-dos-repositorios.md](../docs/00-analise-dos-repositorios.md)).

## Conteúdo

| Arquivo | Função |
|---|---|
| `meower_board/meower_board.cpp`, `meower_board/inc/meower_board.h` | driver |
| `integrate_meower.py` | registra o driver num checkout do BrainFlow (enum, switch, CMake, descritor JSON, enum Python) — idempotente |
| `build_windows.ps1` / `build_linux.sh` | clona, integra, compila e instala o pacote Python |
| `test_driver_with_sim.py` | teste ponta a ponta com `tools/meower_sim.py` |

## Compilar

Windows (Visual Studio 2022 + CMake + Python):

```powershell
cd SENTIR\brainflow
.\build_windows.ps1                 # clona em SENTIR\_deps\brainflow
python test_driver_with_sim.py      # esperado: monotonic True, erro do fotodiodo ~1 ms
```

Linux: `./build_linux.sh`.

O ID é escolhido como último ID oficial + 1 (o BrainFlow valida `FIRST..LAST`). Em 12/11/2026 ficou **69**. Use sempre `BoardIds.MEOWER_BOARD` no código; o número fica em `MEOWER_BOARD_ID.txt` no checkout.

## Uso

```python
from brainflow.board_shim import BoardShim, BrainFlowInputParams, BoardIds, BrainFlowPresets

p = BrainFlowInputParams()
p.ip_address = "192.168.50.11"   # vazio = descoberta por beacon MEOW_MEOW
p.ip_port = 5001                 # dados
p.ip_port_aux = 5000             # controle
p.other_info = "pga_gain=24"     # ganho inicial (o driver acompanha 'usr gain' depois)
b = BoardShim(BoardIds.MEOWER_BOARD, p)
b.prepare_session()              # WOOF_WOOF + rajada de 20 TSYNC
b.config_board("usr set_sampling_freq 1000")
b.config_board("usr gain ALL 24")
print(b.config_board("sentir:info"))    # "ads=1 channels=8 fake=0 id=ID <mac> ..." (consulta local)
print(b.config_board("sentir:clock"))   # estado do modelo de relógio (local, não vai à placa)
b.start_stream()
...
eeg = b.get_board_data()                                   # 24 linhas, ver abaixo
tsync = b.get_board_data(preset=BrainFlowPresets.ANCILLARY_PRESET)  # pares TSYNC
```

### Linhas do preset DEFAULT (24)

| Linha | Conteúdo |
|---|---|
| 0–15 | EEG em µV |
| 16 | bateria (V) |
| 17 | **timestamp** (UNIX do host, sincronizado) |
| 18 | tempo do dispositivo (s, desdobrado) |
| 19 | contador de quadros |
| 20 | marcador |
| 21 | incerteza de sincronização (ms) |
| 22 | quadros perdidos (acumulado) |
| 23 | status do ADS1299 (só placa de 8 canais): `[23:20]=1100`, LOFF_STATP, LOFF_STATN, GPIO4..1 (GPIO1 = fotodiodo) |

### Linhas do preset ANCILLARY (9)

`seq, t1, t2, t3, t4, rtt_ms, offset_s, timestamp, marker` — uma linha por troca TSYNC.

### `other_info`

`discovery_timeout=3000 tsync_interval_ms=1000 tsync_window=120 pga_gain=1 digital_gain=1 ads_count=<1|2, força> board_ctrl_port=<só simulador local>`

### Placa de 8 canais

No `prepare_session` o driver envia `ID?`; com `ads=1` (um ADS1299), as linhas 8–15 saem zeradas e a palavra de status do chip (enviada pelo firmware no slot do canal 16) vai, sem sinal, para a linha 23.

## Uma placa por estação

No SENTIR cada estação recebe a sua Meower (IP fixo); portas 5000/5001 em todas. Duas placas no mesmo PC exigiriam portas distintas (ex. 5010/5011).

## Verificado

Compilado (GCC, C++11, sem *warnings* no driver) e testado no Linux contra o simulador (8 e 16 canais): 1000 Hz, timestamps estritamente crescentes, 0 perdas, erro do pulso de fotodiodo 0,6–1,1 ms com TSYNC e 0,6 ms no modo *fallback* (simulador local, sem atraso de rede). **Ainda não compilado no Windows/MSVC** — primeira tarefa da etapa E2.
