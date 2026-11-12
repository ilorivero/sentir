# Etapa E1 — Firmware

**Objetivo**: os dois firmwares rodando em ESP32-C3 reais, compilados pela Arduino IDE **e** pelo ESP-IDF, validados *antes* de fabricar a placa nova.

## Já entregue (v0.2)

* `firmware/meower-sentir/Meower_SENTIR` — Meower + TSYNC/ID + detecção de 8/16 canais + status no slot 16 + correção da verificação de registradores + ADS1299 emulado. **Compila** com Arduino core 3.3.4 e com ESP-IDF 5.5.1 (real e emulado). Emulador testado no PC (`test_host/run.sh`).
* `firmware/oasis-sentir/Oasis_SENTIR` — compatível com o app; PPG a 100 Hz, `pt` em 64 bits, timestamps de captura, sensores simulados. **Compila** nas duas toolchains.
* `firmware/build_all.sh` — compila as 8 variantes.

## Tarefas

| # | Tarefa | Aceite |
|---|---|---|
| E1.1 | Gravar `SENTIR_FAKE_ADC 1` num ESP32-C3 comum (Arduino IDE **e** ESP-IDF, uma vez cada) | `tsync_probe.py meower` → `ID … ads=1 fake=1`, RTT mediano < 5 ms, 0 perdas em 100 sondas |
| E1.2 | Fotodiodo real no GPIO3 do devkit (`SENTIR_FAKE_PD_PIN 3`) | bit `photodiode` acompanha o quadrado branco do monitor_oasis |
| E1.3 | 30 min de streaming do devkit pelo agente | `lost` < 0,01 %; incerteza de sync < 2 ms; reconexão após desligar o roteador por 10 s |
| E1.4 | Gravar o Oasis SENTIR no Monitor Oasis atual | app funciona sem mudanças; `_timeseries.csv` com ~100 linhas/s; IBI (intervalo entre batimentos) sem degraus de 40 ms |
| E1.5 | Revisar o esquemático da Meower com o checklist de [06-hardware.md](../06-hardware.md) | *pull-down* no DAISY_IN; GPIO1–4 no conector; circuito do fotodiodo |
| E1.6 | Placa fabricada: `SENTIR_FAKE_ADC 0` | `ID … ads=1 fake=0`; `usr gain ALL 24` responde `OK`; sinal de teste interno visível |
| E1.7 | (opcional) ESP32-C5 | relatório RTT/perdas C3 × C5 |

## Prompt para o agente do Antigravity

```
Leia AGENTS.md, docs/03-protocolos.md e docs/08-testes-sem-placa.md.
Etapa E1 - firmware. Os fontes em firmware/meower-sentir/Meower_SENTIR e
firmware/oasis-sentir/Oasis_SENTIR compilam na Arduino IDE (core esp32 3.3.x) e no ESP-IDF 5.5
(pastas idf/, Arduino como componente). Regras: UM codigo-fonte para as duas toolchains; toda
opcao nova vai em sentir_config.h E no Kconfig.projbuild; nao mudar o formato do datagrama da
Meower nem as chaves JSON do Oasis (o app monitor_oasis depende delas); nada de %llu (newlib-nano).
1) Rode firmware/build_all.sh e corrija o que falhar.
2) Grave o modo emulado num ESP32-C3 e rode tools/tsync_probe.py; registre RTT e perdas em
   docs/etapas/E1-resultados.md.
3) Se mudar o firmware, atualize patches/sentir-vs-upstream-c6f4102.diff e rode test_host/run.sh.
```
