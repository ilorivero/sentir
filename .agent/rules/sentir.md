<!-- Copia de AGENTS.md para as regras de workspace do Antigravity. Mantenha as duas iguais. -->
# AGENTS.md — regras do projeto SENTIR

Leia este arquivo antes de qualquer alteração. Vale para agentes do Antigravity e para pessoas.

## Contexto

Pesquisa de doutorado (grupo MoSIS, PUC Minas): resposta neurofisiológica a imagens afetivas OASIS. Dados de pesquisa com seres humanos → reprodutibilidade e integridade dos dados vêm antes de conveniência.

## Idioma

Documentação, comentários de alto nível e mensagens ao operador em **português**. Identificadores de código em inglês. Siglas por extenso na primeira ocorrência de cada documento.

## Invariantes (não quebre)

1. **Base de tempo única por estação**: todo timestamp gravado pelo agente é tempo UNIX do host (`time.time()`, s). Meower e app monitor_oasis são mapeados por TSYNC (`sentir/clock.py`, `ClockModel` + `ContinuousMapper`). Nunca use o tempo de chegada de um pacote como timestamp de amostra (exceto no *fallback* documentado).
2. **`dev_ts` sempre gravado** ao lado de `host_ts`. Os pares TSYNC brutos (`clock_*.parquet`) também. Sem eles não há reajuste offline.
3. **Dados brutos**: não filtrar EEG nem PPG antes de gravar. Filtros só em análise.
4. **Contratos** em `docs/03-protocolos.md`. Mudou protocolo? Atualize no mesmo commit: o documento, os dois lados, os simuladores em `tools/` e os testes.
5. **Apresentação de estímulos é do monitor_oasis**: o SENTIR não duplica o protocolo; recebe as fases confirmadas pelo `presentation_ack`. Mudanças no app seguem o `CLAUDE.md` do monitor_oasis.
6. **Firmware**: um único código para Arduino IDE e ESP-IDF; opção nova vai em `sentir_config.h` **e** no `Kconfig.projbuild`. Meower: não alterar o formato do datagrama; sem `%llu` (newlib-nano); TSYNC fora da fila de comandos. Oasis: não remover nem renomear chaves JSON usadas pelo app.
7. Nada de dados pessoais de participantes em `session.json` ou no repositório (LGPD — Lei Geral de Proteção de Dados).
8. Imagens OASIS não entram no repositório.
9. **Modo de teste** (`SENTIR_FAKE_ADC`, `SENTIR_FAKE_SENSORS`, simuladores) nunca em coleta real; o `ID?` e o `eeg_status` precisam continuar sinalizando `fake`.

## Como testar

```bash
cd backend && python -m pip install -e ".[dev]" && pytest -q        # usa tools/meower_sim.py e tools/app_sim.py
python brainflow/test_driver_with_sim.py                             # após compilar o BrainFlow
firmware/meower-sentir/test_host/run.sh                              # emulador do ADS1299 no PC
firmware/build_all.sh                                                # 8 variantes de firmware
python tools/tsync_probe.py meower <ip> 5000                         # ESP32 real
```

Todo PR/tarefa: testes passando + documento da etapa (`docs/etapas/E*.md`) atualizado com o que foi feito e medido.

## Mapa do código

| Caminho | O quê |
|---|---|
| `backend/sentir/agent.py` | agente EEG da estação: WebSocket `/ws/app`, sessão, status, preview |
| `backend/sentir/clock.py` | modelo de relógio, *slew*, desdobramento de ticks |
| `backend/sentir/sources/` | `meower_brainflow.py` (produção), `meower_udp.py` (Python puro), `meower_common.py` (8/16 canais, status) |
| `backend/sentir/recorder.py` | gravação Parquet |
| `backend/sentir/analysis/` | pós-sessão: `resync`, `photodiode` |
| `brainflow/meower_board/` | driver C++ |
| `firmware/meower-sentir/Meower_SENTIR/` | firmware da Meower (marcas `SENTIR` no código) |
| `firmware/oasis-sentir/Oasis_SENTIR/` | firmware do Monitor Oasis |
| `firmware/*/idf/` | projetos ESP-IDF que compilam os mesmos fontes |
| `integration/monitor_oasis/` | patch do app (cliente do agente, fotodiodo, Painel Central) |
| `tools/` | `meower_sim`, `app_sim`, `tsync_probe` |
