# Etapa E3 — Frontend: monitor_oasis com EEG

**Objetivo**: o monitor_oasis (estações e Painel Central) operando com o agente EEG, com o EEG visível ao vivo para o operador.

## Já entregue (v0.2) — patch `integration/monitor_oasis/0001-sentir-eeg-agent.patch`

* `lib/eeg_agent_client.dart` — cliente do agente (no-op sem endereço), TSYNC com `DateTime.now`, sessão/fases, `eeg_status`/`eeg_preview`.
* `ConfigScreen` — campo "Agente EEG SENTIR (host:porta)".
* `ExperimentScreen` — `session_start` no baseline, `phase` após cada `startExposure`, `session_stop` no fim; resumo `eeg` no `status` ao Central.
* `participant_app.dart` — marcador do fotodiodo (60×60 px, branco no estímulo).
* `central_dashboard.dart` — linha de EEG no cartão; `eeg_preview` não é confundido com `status`.
* `station_client.dart` — `sendEegPreview`.
* `CLAUDE.md` — seção "EEG (SENTIR)".

**Não compilado** (o ambiente de geração não tinha Flutter): `flutter analyze` e `flutter test` são o primeiro passo.

## Tarefas

| # | Tarefa | Aceite |
|---|---|---|
| E3.1 | Aplicar o patch, `flutter analyze` e `flutter test` | sem erros |
| E3.2 | Sessão completa com Meower simulada (nível 1 de [08-testes-sem-placa.md](../08-testes-sem-placa.md)) | `events.parquet` com os mesmos `exposure_id` do SQLite |
| E3.3 | Indicador de EEG na `ExperimentScreen` (bateria, canais saturados, sync, aviso de `fake`) | operador local vê problema de eletrodo em < 2 s |
| E3.4 | Gráfico de EEG no cartão do Painel Central a partir de `eeg_preview` (reaproveitar `VitalStripChart`) | 8 traços rolando, escala fixa em µV |
| E3.5 | Usar `tu`/`n` do Oasis SENTIR no `serial_capture_isolate.dart` (timestamp de captura e detecção de perdas) | `device_wall_clock_us` vindo de `tu` |
| E3.6 | Opção para desligar o marcador do fotodiodo e escolher o canto | preferência persistida |

## Prompt para o agente do Antigravity

```
Trabalhe no repositorio monitor_oasis (leia o CLAUDE.md dele, secao "EEG (SENTIR)") e no SENTIR
(docs/03-protocolos.md secoes 3 e 4). Aplique integration/monitor_oasis/0001-sentir-eeg-agent.patch
com `git am`, rode flutter analyze e flutter test e corrija o que falhar sem mudar o protocolo.
Depois: E3.3 (indicador de EEG na ExperimentScreen) e E3.4 (grafico de EEG no cartao do Painel
Central a partir de eeg_preview, reaproveitando VitalStripChart). Para testar sem hardware:
tools/meower_sim.py --ads 1 + python -m sentir.agent --config config/agent.sim.yaml (no SENTIR) e
"Simular ESP32" no app. Respeite as convencoes do CLAUDE.md (pt-BR, sem gerenciador de estado,
migracoes de banco so incrementais).
```
