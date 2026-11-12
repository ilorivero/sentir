# 05 — Protocolo experimental

O protocolo (seleção das imagens OASIS — Open Affective Standardized Image Set —, ordem, durações) é **conduzido pelo monitor_oasis**, como já é hoje: baseline, estímulo e fixação, com pré-carregamento e confirmação de apresentação. O SENTIR não muda o protocolo; ele grava o EEG (eletroencefalografia) em sincronia com cada fase.

## Durações

| Fase | Padrão do monitor_oasis | Proposta MoSIS (disciplina) |
|---|---|---|
| Baseline inicial | 60 s | 60 s de repouso |
| Por imagem | estímulo 15 s + fixação 10 s | baseline 5 s + estímulo 6 s + intervalo 4 s |

As durações são parâmetros da `ConfigScreen` do monitor_oasis (ou do comando `configure_and_start` do Painel Central). Para análise de EEG por épocas, estímulos de 6 s com intervalos curtos rendem mais ensaios por sessão; para HRV (variabilidade da frequência cardíaca), o próprio monitor_oasis documenta que janelas de 10–30 s são o mínimo para rMSSD/SDNN. **Escolha e pré-registre** a combinação; o SENTIR grava ambas igualmente.

## Marcador do fotodiodo

Com o agente EEG configurado, a janela do participante desenha um quadrado de 60×60 px no canto inferior esquerdo: **branco durante o estímulo, preto no resto**. O fotodiodo fica colado sobre ele. Isso precisa constar no termo e nas instruções ao participante ("um pequeno quadrado no canto pode piscar; ignore").

## Dois participantes simultâneos

* Cada estação conduz o seu protocolo; o Painel Central inicia as duas. O início não é simultâneo ao milissegundo (comandos chegam por rede), mas cada fase de cada participante tem onset medido no seu próprio EEG.
* Para análise de sincronia entre cérebros (*hyperscanning*), a mesma ordem de imagens nas duas estações e a correção por fotodiodo de cada tela permitem alinhar os dois registros com erro da ordem de 1–2 ms + o Elo B (estação ↔ central) reportado pelo monitor_oasis.
* Divisória física entre participantes.

## Checklist da estação antes de iniciar

1. Bateria da Meower > 3,8 V (aparece no app e no Painel Central); Meower **sem cabo USB** (ruído e segurança).
2. `eeg_status` sem canais saturados; repouso de olhos fechados mostra alfa (~10 Hz) em O1/O2.
3. Agente sem aviso de `fake` (firmware de teste).
4. Fotodiodo no canto inferior esquerdo; brilho do monitor fixo; escala do Windows 100 %; notificações desligadas.
5. Oasis no indicador da mão não dominante, mão apoiada.
