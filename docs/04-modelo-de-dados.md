# 04 — Modelo de dados

Cada estação grava **dois conjuntos** locais, ligados pelo código do participante e pelo eixo de tempo comum (relógio de parede do PC da estação).

## 1. monitor_oasis (SQLite `bio_scientific_v3.db`) — sem mudanças

`sessions`, `exposures` (`start_timestamp` em ms = onset confirmado), `sensor_data` (vitais, `device_wall_clock_us`), `hrv_features`, `clock_sync_samples`. Exportação: `<subject_code>_features.csv`, `_timeseries.csv`, `_clock_sync.csv`. Ver `CLAUDE.md` do monitor_oasis.

## 2. Agente EEG (Parquet, compressão zstd, blocos a cada 2 s)

```
<data_dir>/<estação>/<subject_code>/<AAAAMMDD-HHMMSS>/
├── session.json          estação, subject_code, session_id do monitor_oasis, protocolo,
│                         placa (MAC, ads, fake, fw), configuração, resumo final (resync, fotodiodo)
├── events.parquet        session_start/stop, phase_onset, note
├── eeg.parquet           host_ts, dev_ts, <canais em µV>, battery_v,
│                         [photodiode, loff_statp, loff_statn, status_raw]  (placa de 8 canais), [t]
├── clock_meower.parquet  host_ts, dev_ts, t1, t2, t3, t4, rtt_ms     (TSYNC agente ⇄ Meower)
└── clock_app.parquet     idem                                         (tsync agente ⇄ app)
```

### Colunas de tempo

| Coluna | Significado |
|---|---|
| `host_ts` | tempo UNIX do host (s, float64), calculado em tempo real com *slew* |
| `dev_ts` | tempo da Meower (s), bruto e desdobrado — **nunca descartar** |
| `t` | criada no fim da sessão por `sentir.analysis.resync`: `host_ts` reajustado com a sessão inteira. **Use esta na análise.** |

### `events.parquet`

| Campo | Exemplo | Descrição |
|---|---|---|
| `host_ts` | 1794503555.123 | onset no relógio do host (convertido do relógio do app) |
| `participant` | `A` | estação |
| `kind` | `phase_onset`, `session_start`, `session_stop`, `note` | tipo |
| `trial` | 345 | `exposures.id` do SQLite (`exposure_id`) |
| `phase` | `baseline`, `stimulus`, `fixation` | `exposures.event_type` em minúsculas |
| `stimulus` | `Dog 4.jpg` | `exposures.image_name` |
| `value` | 7 | `presentation_latency_ms` |
| `source` | `app`, `app_unsynced` | `app_unsynced` = relógio do app ainda não sincronizado (descartar ou corrigir) |
| `extra` | JSON | mensagem original, com `start_ms` (igual ao `start_timestamp` do SQLite) |

## Como juntar EEG e vitais

* **Chave**: `session.json → subject_code` = `sessions.subject_code`; `events.trial` = `exposures.id`.
* **Tempo**: `exposures.start_timestamp`/1000 e `sensor_data.device_wall_clock_us`/10⁶ estão no relógio de parede do PC da estação, que é o `host_ts` do agente **a menos do offset medido** em `clock_app.parquet` (tipicamente < 1 ms). Para precisão máxima, converta os tempos do SQLite com a reta ajustada sobre `clock_app.parquet` (mesmo código: `sentir.clock.fit_clock`).
* **Onset de estímulo para EEG**: prefira a borda do fotodiodo (`sentir.analysis.photodiode`).

## Exportações previstas (etapa de ML)

* BIDS (Brain Imaging Data Structure) EEG: `*_eeg.edf`, `*_events.tsv`, `*_channels.tsv`, `*_physio.tsv.gz` (PPG e temperatura como *physio*).
* MNE-Python: `Raw` + `Annotations`.

## Privacidade

Dados demográficos ficam só no SQLite do monitor_oasis. O agente não recebe nem grava dados pessoais além do `subject_code` (LGPD — Lei Geral de Proteção de Dados).
