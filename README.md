# SENTIR

**S**istema para **E**studo **N**eurofisiológico da respos**T**a a **I**magens e **R**eações.

Une três projetos numa infraestrutura de coleta com **um computador por participante** e **um servidor** de controle:

* **[monitor_oasis](https://github.com/ilorivero/monitor_oasis)** — app Flutter que apresenta as imagens OASIS (Open Affective Standardized Image Set), captura os sinais vitais do Monitor Oasis por USB (MAX30102, MLX90614, AHT20/BMP280), grava em SQLite e tem modo Estação + Painel Central;
* **[Meower](https://github.com/nikki-uwu/Meower)** — placa de EEG (eletroencefalografia) ESP32-C3 + ADS1299 por Wi-Fi; aqui na versão de **8 canais** (1 ADS1299, *footprint* do 2º pronto);
* **[BrainFlow](https://github.com/brainflow-dev/brainflow)** — aquisição, com o driver `MeowerBoard`.

O SENTIR acrescenta um **agente EEG** em cada estação, que grava o EEG localmente no mesmo eixo de tempo dos estímulos e dos vitais, e um **fotodiodo** na tela, lido pelo próprio ADC do EEG, que mede o instante real de cada imagem.

```
 Meower ──Wi-Fi──▶ agente EEG ◀──WebSocket local──▶ monitor_oasis (Estação) ◀──USB── Monitor Oasis
                   (Parquet)                         (SQLite)   │
                                                                └──WebSocket──▶ monitor_oasis (Painel Central, servidor)
```

## Estrutura

```
SENTIR/
├── AGENTS.md                     regras para agentes (Antigravity) e colaboradores
├── docs/                         00 análise · 01 arquitetura · 02 sincronização · 03 protocolos
│   │                             04 dados · 05 protocolo experimental · 06 hardware · 07 ML
│   │                             08 testes sem placa
│   └── etapas/                   E1 firmware · E2 backend · E3 frontend · E4 validação (com prompts)
├── firmware/
│   ├── meower-sentir/            Meower_SENTIR (Arduino IDE) + idf/ (ESP-IDF) + teste do emulador
│   ├── oasis-sentir/             Oasis_SENTIR (Arduino IDE) + idf/ (ESP-IDF) + fetch_libs
│   └── build_all.sh              compila as 8 variantes (2 placas × 2 toolchains × real/teste)
├── brainflow/                    driver MeowerBoard + integração/compilação do BrainFlow
├── backend/                      agente EEG (Python): sentir/agent.py, fontes, relógio, gravação, análises
├── integration/monitor_oasis/    patch para o monitor_oasis (cliente do agente, fotodiodo, Painel Central)
├── tools/                        meower_sim · app_sim · tsync_probe
└── config/                       agent.example.yaml · agent.sim.yaml
```

## Estado (v0.2 — 12/11/2026)

| Parte | Estado | Verificação |
|---|---|---|
| Firmware Meower (TSYNC, 8/16 canais, status, ADS1299 emulado) | pronto para E1 | **compila** na Arduino IDE (core 3.3.4) e no ESP-IDF 5.5.1, real e emulado; emulador testado no PC |
| Firmware Oasis (compatível com o app, PPG a 100 Hz, `pt` em 64 bits) | pronto para E1 | **compila** nas duas toolchains, real e simulado |
| Driver BrainFlow `MeowerBoard` | pronto | compilado (Linux) e testado com o simulador de 8 e 16 canais |
| Agente EEG | pronto para E2 | 9 testes `pytest` (agente + Meower simulada + app simulado) |
| Patch do monitor_oasis | escrito | **não compilado** (sem Flutter no ambiente de geração) |
| Hardware ESP32 | — | nada rodou em placa ainda: roteiro em [docs/08](docs/08-testes-sem-placa.md) |

## Testar sem hardware

```bash
cd SENTIR
python -m pip install -e "backend[dev]"
cd backend && pytest -q
# ao vivo (3 terminais, a partir de SENTIR/):
python tools/meower_sim.py --ads 1 --photodiode-period-s 2
cd backend && python -m sentir.agent --config ../config/agent.sim.yaml
python tools/app_sim.py --stimuli 5
```

Depois, o monitor_oasis com o patch e "Simular ESP32"; depois um ESP32-C3 comum com o firmware em modo emulado. Ver [docs/08-testes-sem-placa.md](docs/08-testes-sem-placa.md).

## No laboratório (por estação)

1. Gravar os firmwares ([docs/etapas/E1-firmware.md](docs/etapas/E1-firmware.md)).
2. `brainflow/build_windows.ps1`; copiar `config/agent.example.yaml` para `config/agent.yaml` (ID da estação, IP da Meower, pasta de dados).
3. `sentir-agent --config config/agent.yaml` e o monitor_oasis com "Agente EEG SENTIR = 127.0.0.1:8765".
4. Servidor: monitor_oasis em modo Painel Central.

## Documentação

[00 Análise](docs/00-analise-dos-repositorios.md) · [01 Arquitetura](docs/01-arquitetura.md) · [02 Sincronização](docs/02-sincronizacao.md) · [03 Protocolos](docs/03-protocolos.md) · [04 Dados](docs/04-modelo-de-dados.md) · [05 Protocolo experimental](docs/05-protocolo-experimental.md) · [06 Hardware](docs/06-hardware.md) · [07 ML](docs/07-contrato-pipeline-ml.md) · [08 Testes sem placa](docs/08-testes-sem-placa.md)

## Licenças

Firmware e driver da Meower derivam do projeto Meower (Gleb Manokhin, MIT ou Apache-2.0, à escolha); o driver integra o BrainFlow (MIT). Hardware Meower: CERN-OHL-S-2.0. Imagens OASIS: termos de uso dos autores (Kurdi, Lozano & Banaji, 2017) — não incluídas.
