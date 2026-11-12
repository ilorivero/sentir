# Etapa E4 — Integração e validação em bancada

**Objetivo**: provar com medição, antes de coletar com participantes, que o sistema entrega o sincronismo prometido.

| # | Teste | Como | Critério |
|---|---|---|---|
| V1 | Relógio Meower | 60 min de streaming, sem participante | incerteza < 2 ms em 95 % do tempo; deriva estável (±2 ppm, partes por milhão) |
| V2 | Perda de pacotes | idem, com o Wi-Fi do laboratório em uso normal | perda < 0,01 %; nenhum buraco > 50 ms |
| V3 | Latência de tela | 200 estímulos de 1 s com fotodiodo, nas duas estações | p95 − mediana < 5 ms; diferença entre monitores documentada |
| V4 | Amplitude e frequência | gerador de função (10 Hz, 50 µV) via divisor na entrada | ±5 % de amplitude; pico exato no espectro |
| V5 | Ruído de entrada | `usr ch_input ALL SHORTED` | ruído RMS (valor eficaz) compatível com o datasheet do ADS1299 |
| V6 | EEG × vitais | batida mecânica registrada no EEG (artefato) e no PPG (fotopletismografia) | alinhamento < 10 ms após o `resync` |
| V7 | Sessão completa | 1 pessoa da equipe, 2 estações + Painel Central | arquivos completos; fases do SQLite = fases do agente; resumo do fotodiodo em `session.json` |

## Prompt para o agente do Antigravity

```
Leia AGENTS.md e docs/02-sincronizacao.md. Crie backend/sentir/analysis/validation.py que gere um
relatorio HTML (um arquivo) por sessao do agente: incerteza e deriva do relogio ao longo do tempo,
RTT, buracos no EEG pelo tick, histograma da latencia do fotodiodo, conferencia fases do
events.parquet x exposures do SQLite do monitor_oasis. Teste com uma sessao gerada pelos simuladores.
```
