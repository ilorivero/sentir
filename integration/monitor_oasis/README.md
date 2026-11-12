# Integração com o monitor_oasis

`0001-sentir-eeg-agent.patch` — um commit sobre `ilorivero/monitor_oasis@1944b19` (branch `sentir-eeg`):

| Arquivo | Mudança |
|---|---|
| `lib/eeg_agent_client.dart` (novo) | cliente WebSocket do agente EEG local; no-op sem endereço |
| `lib/main.dart` | campo "Agente EEG SENTIR" na `ConfigScreen`; sessão/fases enviadas ao agente na `ExperimentScreen`; resumo `eeg` no `status` |
| `lib/participant_app.dart` | marcador do fotodiodo (quadrado de 60×60 px no canto inferior esquerdo, branco durante o estímulo) |
| `lib/central_dashboard.dart` | linha de EEG no cartão da estação; `eeg_preview` ignorado como status |
| `lib/station_client.dart` | `sendEegPreview` |
| `CLAUDE.md` | seção "EEG (SENTIR)" |

Sem endereço do agente configurado, o app se comporta exatamente como antes.

## Aplicar

```bash
cd monitor_oasis
git checkout -b sentir-eeg
git am ../SENTIR/integration/monitor_oasis/0001-sentir-eeg-agent.patch
flutter pub get && flutter analyze && flutter test
```

**Não foi compilado** no ambiente de geração (sem Flutter). Rode `flutter analyze` antes de tudo (etapa E3.1).

## Firmware do Monitor Oasis

O firmware novo fica em `SENTIR/firmware/oasis-sentir` (compatível com o app atual). Para levá-lo ao repositório do monitor_oasis, copie `Oasis_SENTIR/` para `esp32/` — o `monitorcardiaco.ino` original pode continuar lá para comparação.
