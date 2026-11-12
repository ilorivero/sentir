"""Tipos de dados trocados entre fontes, gravador e API."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class Chunk:
    """Bloco de amostras de um fluxo, ja no eixo de tempo do host.

    participant: id do participante (ex. "P01")
    stream:      "eeg", "ppg", "temp", "env", "vitals", "clock", ...
    columns:     nomes das colunas de ``data``
    host_ts:     (n,) float64, segundos UNIX no relogio do host (sincronizado)
    dev_ts:      (n,) float64, segundos no relogio do dispositivo (bruto, para reajuste offline)
    data:        (n, len(columns)) float32/float64
    """

    participant: str
    stream: str
    columns: list[str]
    host_ts: np.ndarray
    dev_ts: np.ndarray
    data: np.ndarray
    meta: dict[str, Any] = field(default_factory=dict)

    def __len__(self) -> int:
        return int(self.host_ts.shape[0])


@dataclass
class Event:
    """Evento discreto (marcador de estimulo, anotacao do operador, estado da sessao)."""

    host_ts: float
    participant: str  # "*" para eventos da sessao inteira
    kind: str         # ex. "phase_onset", "session_start", "note", "sam_rating"
    trial: int = -1
    phase: str = ""
    stimulus: str = ""
    value: float = float("nan")
    source: str = "backend"   # "presenter", "photodiode", "operator", "backend"
    extra: str = ""           # JSON livre
    wall_ts: float = field(default_factory=time.time)
