"""Interface comum das fontes de dados (Meower, Monitor Oasis, ...)."""
from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from typing import Callable

from ..clock import ClockModel, SyncSample
from ..model import Chunk

log = logging.getLogger(__name__)

ChunkSink = Callable[[Chunk], None]


class Source(ABC):
    """Fonte que roda em threads proprias e entrega ``Chunk`` ao ``sink``.

    Cada fonte publica tambem o fluxo ``clock`` (pares TSYNC brutos) para que a
    sincronizacao possa ser refeita offline com a sessao inteira.
    """

    kind = "source"

    def __init__(self, participant: str, sink: ChunkSink):
        self.participant = participant
        self.sink = sink
        self.clock = ClockModel()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self.status: dict = {"state": "idle"}

    # ciclo de vida -------------------------------------------------------------
    @abstractmethod
    def prepare(self) -> None:
        """Abre conexoes, descobre o dispositivo, aplica configuracao, sincroniza o relogio."""

    @abstractmethod
    def start(self) -> None:
        """Inicia o streaming."""

    def stop(self) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout=3)
        self._threads.clear()
        self.status["state"] = "stopped"

    # utilidades ----------------------------------------------------------------
    def _spawn(self, target, name: str) -> None:
        t = threading.Thread(target=self._guard(target), name=f"{self.kind}-{self.participant}-{name}",
                             daemon=True)
        self._threads.append(t)
        t.start()

    def _guard(self, fn):
        def run():
            try:
                fn()
            except Exception:  # noqa: BLE001
                log.exception("thread %s/%s falhou", self.kind, self.participant)
                self.status["state"] = "error"
        return run

    def _emit_sync(self, s: SyncSample, device: str) -> None:
        import numpy as np
        fit = self.clock.add(s)
        self.status["clock"] = None if fit is None else {
            "uncertainty_ms": round(fit.uncertainty_ms, 3),
            "drift_ppm": round(fit.drift_ppm, 2),
            "n": fit.n_used,
        }
        self.sink(Chunk(
            participant=self.participant, stream=f"clock_{device}",
            columns=["t1", "t2", "t3", "t4", "rtt_ms"],
            host_ts=np.array([s.t4]), dev_ts=np.array([s.t3]),
            data=np.array([[s.t1, s.t2, s.t3, s.t4, s.rtt * 1e3]], dtype=np.float64),
        ))
