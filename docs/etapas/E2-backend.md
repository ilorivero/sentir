# Etapa E2 — Backend: agente EEG + driver BrainFlow

**Objetivo**: agente EEG estável em cada estação Windows, com o driver BrainFlow compilado, por sessões de 30 min sem perda.

## Já entregue (v0.2)

* `brainflow/` — driver `MeowerBoard` (TSYNC, `ID?`, 8/16 canais, status na linha 23, µV, perdas, *slew*), compilado no Linux e testado com o simulador; `integrate_meower.py`; scripts de build.
* `backend/sentir/agent.py` — agente: conecta a Meower ao iniciar, WebSocket `/ws/app` para o monitor_oasis, gravação por sessão em Parquet, `eeg_status`/`eeg_preview`, reajuste de relógio e latência do fotodiodo ao fechar.
* Fontes `meower_brainflow.py` (produção) e `meower_udp.py` (Python puro); `analysis/resync.py`, `analysis/photodiode.py`.
* 9 testes `pytest`, incluindo agente + Meower simulada + app simulado.

## Tarefas

| # | Tarefa | Aceite |
|---|---|---|
| E2.1 | Compilar o BrainFlow com o driver no Windows (`brainflow/build_windows.ps1`) | `BoardIds.MEOWER_BOARD` existe; `test_driver_with_sim.py` com `monotonic True` |
| E2.2 | Instalar o agente como serviço/atalho em cada estação (`sentir-agent --config config/agent.yaml`) | sobe com o Windows; log em arquivo |
| E2.3 | Fechar a sessão se o app cair (WebSocket fechado por mais de N s durante a gravação) | sessão nunca fica aberta indefinidamente; evento `session_abort` |
| E2.4 | Lead-off: comando para habilitar a detecção (corrente DC) e mostrar `loff_statp/n` por canal no `eeg_status` | eletrodo solto aparece em < 2 s |
| E2.5 | Exportação BIDS/MNE juntando EEG (Parquet) e vitais (SQLite do monitor_oasis) — `analysis/export_bids.py` | `mne_bids` valida o dataset |
| E2.6 | Converter tempos do SQLite pela reta de `clock_app.parquet` no export | diferença documentada (< 1 ms esperado) |

## Prompt para o agente do Antigravity

```
Leia AGENTS.md, docs/02-sincronizacao.md, docs/03-protocolos.md (secao 3) e docs/04-modelo-de-dados.md.
Etapa E2 - backend. Codigo em backend/sentir; testes: cd backend && pytest -q (usam tools/meower_sim.py
e tools/app_sim.py). Regras: todo timestamp vem do ClockModel/ContinuousMapper; dev_ts e os pares
de relogio sao sempre gravados; mudou o protocolo do /ws/app? atualize docs/03, tools/app_sim.py,
integration/monitor_oasis e os testes juntos.
Tarefas: E2.3 (encerrar sessao orfa), E2.4 (lead-off), E2.5 (export BIDS lendo o SQLite do monitor_oasis).
Para cada uma: teste primeiro, implementacao, pytest verde, e atualize este arquivo.
```
