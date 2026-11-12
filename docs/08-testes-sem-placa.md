# 08 — Testar todo o software antes de fabricar a placa

Objetivo: chegar à fabricação da Meower com firmware, Wi-Fi, agente EEG, monitor_oasis, Painel Central e sincronização já validados. São três níveis, do mais barato ao mais próximo do real.

## Nível 0 — só no PC (nenhum hardware)

```bash
cd SENTIR
python -m pip install -e "backend[dev]"
cd backend && pytest -q              # 9 testes: relógio, pacotes, 8/16 canais, agente + app simulados
```

Para ver funcionando "ao vivo" (3 terminais):

```bash
python tools/meower_sim.py --ads 1 --photodiode-period-s 2          # Meower de 8 canais simulada
cd backend && python -m sentir.agent --config ../config/agent.sim.yaml
python tools/app_sim.py --stimuli 5                                 # app monitor_oasis simulado
```

O agente grava em `backend/dados_eeg_sim/A/A-PARTICIPANTE_1/<data-hora>/`. O `app_sim` imprime o resumo com a latência do fotodiodo (deve ser ≈ 0 ms) e o ajuste de relógio.

Com o BrainFlow compilado (`brainflow/build_windows.ps1`): `python brainflow/test_driver_with_sim.py`.

## Nível 1 — monitor_oasis de verdade + Meower simulada

1. Aplique o patch no monitor_oasis (`integration/monitor_oasis/README.md`) e rode `flutter analyze` e `flutter test`.
2. Rode `meower_sim.py` e o agente como acima.
3. No monitor_oasis: Estação, "Simular ESP32" marcado e **Agente EEG SENTIR = `127.0.0.1:8765`**.
4. Execute um protocolo curto. Confira:
   * a pasta da sessão criada pelo agente, com `events.parquet` contendo cada fase (mesmos `exposure_id` do SQLite);
   * o quadrado do fotodiodo piscando na janela do participante;
   * no Painel Central (outra instância, ou o mesmo PC), a linha "EEG 8ch · bat … · sync ±… ms" no cartão.

Com o simulador, o fotodiodo pisca no próprio ritmo dele (não está vendo a tela), então a latência de tela só é medida nos níveis 2 e 3.

## Nível 2 — ESP32-C3 comum como "Meower sem ADS1299"

Qualquer placa ESP32-C3 (DevKitM-1, C3 Super Mini…) roda o **firmware real da Meower** com o ADS1299 emulado. Isso testa o que nenhum simulador testa: Wi-Fi real, portal `EEG-SETUP`, AsyncUDP, TSYNC sobre o rádio, bateria/USB, gravação, reconexão.

1. Compile com `SENTIR_FAKE_ADC 1` (Arduino IDE: `sentir_config.h`; ESP-IDF: `sdkconfig.fake`) e grave.
2. Configure o Wi-Fi pelo portal `EEG-SETUP` (como no Meower original).
3. `python tools/tsync_probe.py meower <ip> 5000` — anote RTT mediano/p95; o `ID` deve mostrar `ads=1 fake=1`.
4. Agente com `driver: brainflow` (ou `udp`) apontando para o IP; o `eeg_status` mostra o aviso de firmware de teste.
5. **Fotodiodo de verdade no devkit**: ligue o circuito da [06-hardware.md](06-hardware.md) (ou só um fototransistor entre 3,3 V e o pino, com *pull-down*) no **GPIO3** — o pino do DRDY, que fica livre no modo emulado — e compile com `SENTIR_FAKE_PD_PIN 3`. O bit do fotodiodo passa a refletir a **luz real da tela** → a latência de tela do monitor da estação já pode ser medida antes da placa existir. Sem circuito, `SENTIR_FAKE_PD_PIN 9` usa o botão BOOT (aperte quando a imagem aparecer).
6. Rode 30 min com o monitor_oasis: perdas (`lost`), incerteza de sync, bateria, quedas de Wi-Fi.

O mesmo vale para o Monitor Oasis: `SENTIR_FAKE_SENSORS 1` num ESP32-C3 sem sensores testa USB → app → SQLite com o firmware novo.

## Nível 3 — placa fabricada

Grave o firmware normal (`SENTIR_FAKE_ADC 0`). O `ID?` deve responder `ads=1 fake=0`. Siga a etapa E4 ([etapas/E4-integracao-validacao.md](etapas/E4-integracao-validacao.md)): sinal de teste interno (`usr ch_input ALL TEST`), gerador de função, ruído com entradas em curto, fotodiodo.

## O que cada nível valida

| Item | 0 | 1 | 2 | 3 |
|---|:-:|:-:|:-:|:-:|
| protocolo UDP, TSYNC, 8 canais, status, gravação | ✔ | ✔ | ✔ | ✔ |
| integração com o monitor_oasis (fases, fotodiodo na tela, Painel Central) | | ✔ | ✔ | ✔ |
| Wi-Fi real, firmware real no ESP32-C3, latência de tela real | | | ✔ | ✔ |
| ADS1299, eletrodos, ruído, lead-off | | | | ✔ |
