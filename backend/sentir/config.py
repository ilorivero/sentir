"""Configuracao do agente EEG da estacao (YAML). Ver config/agent.example.yaml."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class MeowerConfig:
    driver: str = "brainflow"      # "brainflow" (producao) | "udp" (Python puro / simulador)
    ip: str = ""                   # vazio = descoberta pelo beacon MEOW_MEOW
    ctrl_port: int = 5000
    data_port: int = 5001
    board_ctrl_port: int | None = None   # so para o simulador no mesmo PC
    fs: int = 1000
    pga_gain: int = 24
    digital_gain: int = 1
    channels: int | str = "auto"   # "auto" = pergunta a placa (ID?: ads=1 -> 8, ads=2 -> 16)
    channel_names: list[str] = field(default_factory=lambda: [
        "Fp1", "Fp2", "F3", "F4", "C3", "C4", "O1", "O2",
        "CH9", "CH10", "CH11", "CH12", "CH13", "CH14", "CH15", "CH16"])
    init_commands: list[str] = field(default_factory=lambda: [
        "sys networkfreq 60", "sys filters_off"])


@dataclass
class AgentConfig:
    station_id: str = "A"
    data_dir: str = "dados_eeg"
    host: str = "127.0.0.1"        # so a propria estacao fala com o agente
    port: int = 8765
    preview_hz: float = 50.0       # taxa do traco de EEG enviado ao app (0 = desliga)
    status_interval_s: float = 0.5
    meower: MeowerConfig = field(default_factory=MeowerConfig)


def load_config(path: str | Path | None) -> AgentConfig:
    if path is None or not Path(path).exists():
        return AgentConfig()
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    m = raw.pop("meower", None) or {}
    return AgentConfig(**raw, meower=MeowerConfig(**m))
