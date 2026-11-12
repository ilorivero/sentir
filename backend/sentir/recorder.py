"""Gravacao da sessao em Parquet (um arquivo por fluxo) + eventos + manifesto.

Estrutura de uma sessao do agente EEG (ver docs/04-modelo-de-dados.md):

  <data_dir>/<estacao>/<codigo_participante>/<AAAAMMDD-HHMMSS>/
    session.json         manifesto (estacao, participante, sessao do monitor_oasis, placa, versoes)
    events.parquet       fases confirmadas pelo monitor_oasis (BASELINE/STIMULUS/FIXATION) e notas
    eeg.parquet          host_ts, dev_ts, canais (uV), battery_v [, photodiode, loff_statp/n, status_raw]
    clock_meower.parquet pares TSYNC brutos agente <-> Meower
    clock_app.parquet    pares TSYNC brutos agente <-> app monitor_oasis
"""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from .model import Chunk, Event

log = logging.getLogger(__name__)


class _StreamWriter:
    def __init__(self, path: Path, columns: list[str], dtype):
        self.path = path
        self.columns = columns
        fields = [pa.field("host_ts", pa.float64()), pa.field("dev_ts", pa.float64())]
        arrow_t = pa.float32() if np.dtype(dtype) == np.float32 else pa.float64()
        fields += [pa.field(c, arrow_t) for c in columns]
        self.schema = pa.schema(fields)
        self.writer = pq.ParquetWriter(path, self.schema, compression="zstd")
        self.pending: list[Chunk] = []
        self.rows = 0

    def add(self, c: Chunk) -> None:
        self.pending.append(c)

    def flush(self) -> None:
        if not self.pending:
            return
        host = np.concatenate([c.host_ts for c in self.pending])
        dev = np.concatenate([c.dev_ts for c in self.pending])
        data = np.concatenate([c.data for c in self.pending])
        arrays = [pa.array(host), pa.array(dev)] + [pa.array(data[:, i]) for i in range(data.shape[1])]
        self.writer.write_table(pa.Table.from_arrays(arrays, schema=self.schema))
        self.rows += len(host)
        self.pending.clear()

    def close(self) -> None:
        self.flush()
        self.writer.close()


class Recorder:
    """Recebe ``Chunk``/``Event`` de qualquer thread e grava em disco numa thread propria."""

    def __init__(self, session_dir: Path, flush_interval_s: float = 2.0, flat: bool = False):
        self.dir = Path(session_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.q: queue.Queue = queue.Queue()
        self.flush_interval_s = flush_interval_s
        self.flat = flat   # True: todos os fluxos na propria pasta da sessao (agente EEG)
        self.writers: dict[tuple[str, str], _StreamWriter] = {}
        self.events: list[Event] = []
        self.listeners: list = []  # callbacks para visualizacao ao vivo
        self._stop = threading.Event()
        self._th = threading.Thread(target=self._loop, name="recorder", daemon=True)
        self._th.start()

    # chamado pelas fontes (thread-safe)
    def __call__(self, c: Chunk) -> None:
        self.q.put(c)
        for fn in self.listeners:
            try:
                fn(c)
            except Exception:  # noqa: BLE001
                pass

    def event(self, e: Event) -> None:
        self.q.put(e)

    def write_manifest(self, manifest: dict) -> None:
        (self.dir / "session.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False),
                                               encoding="utf-8")

    def _writer(self, c: Chunk) -> _StreamWriter:
        key = (c.participant, c.stream)
        w = self.writers.get(key)
        if w is None:
            sub = self.dir if self.flat else self.dir / c.participant
            sub.mkdir(parents=True, exist_ok=True)
            name = c.stream
            w = _StreamWriter(sub / f"{name}.parquet", c.columns, c.data.dtype)
            self.writers[key] = w
        return w

    def _loop(self) -> None:
        last = time.time()
        while not (self._stop.is_set() and self.q.empty()):
            try:
                item = self.q.get(timeout=0.2)
                if isinstance(item, Chunk):
                    if len(item):
                        self._writer(item).add(item)
                elif isinstance(item, Event):
                    self.events.append(item)
            except queue.Empty:
                pass
            if time.time() - last > self.flush_interval_s:
                self._flush_all()
                last = time.time()
        self._flush_all()

    def _flush_all(self) -> None:
        for w in self.writers.values():
            try:
                w.flush()
            except Exception:  # noqa: BLE001
                log.exception("falha ao gravar %s", w.path)
        if self.events:
            rows = [asdict(e) for e in self.events]
            pq.write_table(pa.Table.from_pylist(rows), self.dir / "events.parquet")

    def stats(self) -> dict:
        return {(s if self.flat else f"{p}/{s}"): w.rows + sum(len(c) for c in w.pending)
                for (p, s), w in self.writers.items()}

    def close(self) -> dict:
        self._stop.set()
        self._th.join(timeout=10)
        for w in self.writers.values():
            w.close()
        return self.stats()
