# 06 — Hardware

## Por estação (participante)

| Item | Qtde | Observação |
|---|---|---|
| Meower SENTIR (ESP32-C3 + 1× ADS1299; *footprint* do 2º pronto) | 1 | 8 canais na v1 |
| LiPo 3,7 V 1100 mAh ou mais | 1 (+1 reserva) | só bateria durante a coleta |
| Eletrodos (Ag/AgCl comerciais ou próprios) | 8 + referência + BIAS | montagem sugerida abaixo |
| Monitor Oasis (ESP32-C3 + MAX30102 + MLX90614 + AHT20/BMP280) | 1 | USB ao PC da estação |
| Fotodiodo + comparador (circuito abaixo) | 1 | ligado ao GPIO1 do ADS1299 da Meower |
| PC da estação + monitor do participante | 1 | taxa de atualização fixa, modo de baixa latência |

Infraestrutura: 1 PC servidor (Painel Central), roteador Wi-Fi dedicado (PCs por cabo), *switch* se necessário.

## Montagem sugerida (8 canais)

| Canal | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| Local | Fp1 | Fp2 | F3 | F4 | C3 | C4 | O1 | O2 |

Referência comum em SRB2 (mastoide ou lóbulo da orelha), BIAS (eletrodo de polarização) na outra. Fp1/Fp2 também captam as piscadas, úteis para limpeza por ICA (análise de componentes independentes). Os nomes ficam em `channel_names` do agente.

## Fotodiodo → GPIO1 do ADS1299 (recomendado para a placa nova)

Com 1 ADS1299, o firmware SENTIR envia a palavra de status do chip no slot 16. Os 4 GPIOs do ADS1299 vêm nela, **na mesma amostra do EEG** — por isso o fotodiodo vai num GPIO, sem gastar canal de EEG.

```
 DVDD (3,3 V) ──┬──────────────┐
                │              │
             R1 10 kΩ       VCC do comparador (TLV7011, LMV7219…)
                │
   +IN ─────────┼── fototransistor TEPT5700 (coletor) ── emissor ── DGND
                │
   -IN ── divisor ajustável (trimpot 10 kΩ) entre DVDD e DGND
   OUT (push-pull, 3,3 V) ── 100 Ω ── GPIO1 do ADS1299 mestre
```

* Ajuste o trimpot com o quadrado preto/branco na tela (no claro a saída muda de nível); a polaridade não importa — a análise detecta a primeira transição após o onset.
* Alternativa sem comparador: porta Schmitt-trigger (74LVC1G17) — menos ajustável.
* No GPIO do ADS1299 a tensão deve ficar entre DGND e DVDD. Confirme no esquemático em qual alimentação digital o ADS1299 trabalha (DVDD 1,8–3,6 V).
* O registrador GPIO (0x14) sai do reset como 0x0F = todos entradas; não precisa configurar.
* O sensor e o comparador são alimentados pela própria Meower (bateria): sem caminho galvânico até o PC.

## Checklist da PCB antes de mandar fabricar

| Item | Por quê |
|---|---|
| *Pull-down* 10 kΩ do **DAISY_IN** do mestre a DGND | sem o 2º chip, DAISY_IN fica solto: a detecção de quantos chips existem (ID do escravo) e os slots 9–16 recebem lixo |
| GPIO1–GPIO4 do mestre num conector (com DVDD e DGND) | fotodiodo no GPIO1; os outros ficam para gatilhos futuros |
| *Footprint* completo do 2º ADS1299 com o CLK do mestre roteado (CLKSEL) | permite passar a 16 canais só soldando o chip; o firmware detecta sozinho |
| Pontos de teste em DRDY, SCLK, MISO, CS, START e RESET | depuração com analisador lógico |
| Botão BOOT (GPIO9) e acesso ao USB do ESP32-C3 | gravação, modo de configuração (`EEG-SETUP`) |
| Divisor de bateria igual ao do Meower (GPIO4) | o firmware já mede e envia a tensão |
| Plano de terra analógico/digital como no Meower | ruído |

Antes de fabricar, rode o roteiro de [08-testes-sem-placa.md](08-testes-sem-placa.md): ele valida firmware, Wi-Fi, agente, app e sincronização com um ESP32-C3 comum.

## Monitor Oasis

Pinagem e lista de materiais em `monitor_oasis/esp32/monitorcardiaco/diagrama.md` (I²C em SDA=8, SCL=9 no C3 Super Mini). O firmware SENTIR mantém essa pinagem.

## Futuro: ESP32-C5

Wi-Fi 6 em 2,4/5 GHz. Firmware: portar pinos e `spi_lib`; driver e agente não mudam. Compare o RTT (tempo de ida e volta) do TSYNC com `tools/tsync_probe.py` antes e depois.
