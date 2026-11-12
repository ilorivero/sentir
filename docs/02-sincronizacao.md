# 02 — Sincronização temporal

## Cadeia de relógios numa estação

```
 Meower (esp_timer, ticks de 8 us) --TSYNC/UDP--> agente EEG (time.time do PC) <--tsync/WebSocket--> monitor_oasis (DateTime.now do PC)
                                                                                                             ^
 Monitor Oasis (esp_timer, us) ------------------------------ ping/pong serial (Elo A) ----------------------+
 Tela (vsync + painel) --luz--> fotodiodo --> GPIO1 do ADS1299 (mesmo ADC do EEG)
 Estação --- Elo B (WebSocket) --- Painel Central (só monitoramento)
```

| Elo | Quem mede | Método | Gravado em |
|---|---|---|---|
| Meower → agente | agente (driver BrainFlow ou fonte UDP) | TSYNC a 1 Hz, 30 % das trocas com menor RTT (tempo de ida e volta), regressão offset + deriva, *slew* | `clock_meower.parquet` |
| app → agente | agente | tsync pelo WebSocket local a cada 0,5–2 s, mesmo algoritmo | `clock_app.parquet` |
| Oasis → app | app (Elo A, já existe) | ping/pong serial, menor RTT entre os últimos 10 | SQLite `clock_sync_samples` |
| estação → central | app (Elo B, já existe) | NTP (Network Time Protocol) de 4 tempos | SQLite `clock_sync_samples` |
| tela → EEG | **hardware** | fotodiodo no GPIO1 do ADS1299 | coluna `photodiode` de `eeg.parquet` |

A base de tempo comum é o **relógio de parede do PC da estação**. O agente lê com `time.time()` e o app com `DateTime.now()`. Os dois consultam o mesmo relógio do Windows, mas por APIs (interfaces de programação) com resoluções possivelmente diferentes. Por isso o agente **mede** a relação app → host por tsync em vez de supor que são iguais, e o erro medido fica gravado.

## TSYNC (estilo NTP)

```
 host                         dispositivo
  t1 ──── "TSYNC 17" ───────▶ t2   (carimbo na chegada)
  t4 ◀── "TSYNC 17 t2 t3" ─── t3   (carimbo na resposta)

 rtt    = (t4 − t1) − (t3 − t2)          offset = (t1 + t4)/2 − (t2 + t3)/2
```

`sentir/clock.py` (Python) e `MeowerBoard::refit_clock_locked` (C++) fazem o mesmo cálculo:

1. guardam as últimas 120 trocas;
2. usam só as 30 % de menor RTT — o atraso de rede só soma, então as trocas mais rápidas são as menos contaminadas por fila no Wi-Fi;
3. ajustam `host = host0 + a + b·(dev − dev0)` por mínimos quadrados, onde `b` é a deriva do cristal (estimada quando a janela cobre ≥ 20 s).

A conversão em tempo real é contínua (*slew* de até 1 ms por segundo), então os timestamps nunca saltam nem voltam. Depois da sessão, `sentir.analysis.resync` reajusta com todos os pares e grava a coluna `t` — **o eixo oficial de análise**.

No firmware, o TSYNC é respondido direto no *callback* AsyncUDP, porque a fila de comandos do Meower tem ~50 ms de latência variável.

## Do comando de tela ao EEG

1. O app manda `show_image` à janela do participante; ela pinta e responde `presentation_ack` com `DateTime.now()` no *post-frame* → `exposures.start_timestamp` (já existe).
2. O app envia `phase{start_ms}` ao agente, que converte para o relógio do host e grava em `events.parquet`.
3. O quadro com a imagem leva também o quadrado branco do fotodiodo; o compositor do Windows e o painel do monitor só o exibem de fato 1 a 3 quadros depois.
4. A luz muda o GPIO1 do ADS1299 → o bit `photodiode` sobe na **mesma amostra** de EEG em que a luz chegou.

O passo 4 é a verdade de referência. `sentir.analysis.photodiode` casa cada onset do app com a borda de luz seguinte e informa latência mediana, p95 e desvio-padrão; o agente grava esse resumo em `session.json` ao fim de cada sessão. Para análises de ERP (potencial relacionado a evento), use o onset do fotodiodo.

## Orçamento de erro esperado

| Componente | Erro | Base |
|---|---|---|
| EEG Meower → host (TSYNC, Wi-Fi dedicado) | 0,5–2 ms | simulador com *jitter* de 2 ms: 0,6–1,1 ms, incluindo a quantização de 1 amostra a 1000 Hz |
| app → host (WebSocket local) | < 1 ms | teste do agente: fases reposicionadas com erro < 5 ms, com relógio do app 5 s adiantado e deriva de 15 ppm (partes por milhão) |
| onset reportado × luz na tela | 1–3 quadros (17–50 ms a 60 Hz), variável | medido pelo fotodiodo em cada sessão |
| fotodiodo × EEG | ≤ 1 amostra (1 ms a 1000 Hz) | mesmo ADC (conversor analógico-digital) |
| PPG (Oasis) | ±5 ms por amostra a 100 Hz | firmware SENTIR com timestamps de captura |

## Testes que garantem isso

* `backend/tests/test_simulators.py` — 8 e 16 canais: borda do fotodiodo simulado com erro < 3 ms; timestamps estritamente crescentes.
* `backend/tests/test_agent.py` — agente + Meower simulada + app simulado: 4 estímulos, fases convertidas com erro < 5 ms, latência fotodiodo × onset com mediana < 3 ms.
* `brainflow/test_driver_with_sim.py` — o mesmo pelo driver BrainFlow compilado.
* Em bancada: [08-testes-sem-placa.md](08-testes-sem-placa.md) e [etapas/E4-integracao-validacao.md](etapas/E4-integracao-validacao.md).
