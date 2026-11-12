"""Agente EEG da estacao do participante (SENTIR).

Roda no PC de cada participante, ao lado do app monitor_oasis (Flutter):

  Meower --Wi-Fi/UDP--> [agente EEG] <--WebSocket local--> [monitor_oasis: estacao]
                             |                                  |  USB: Oasis (MAX30102,
                             v                                  |  MLX90614, AHT20/BMP280)
                   Parquet local (EEG)                    SQLite local (sinais vitais)
                                                                | WebSocket
                                                                v
                                                    [monitor_oasis: Painel Central]

O agente:
  * mantem a Meower conectada e transmitindo (qualidade do sinal visivel antes da sessao);
  * grava EEG + relogios + eventos em Parquet NA PROPRIA ESTACAO entre session_start/stop;
  * sincroniza o relogio do app (DateTime.now, o mesmo dos start_timestamp do SQLite) com o
    do host por TSYNC, e converte cada fase confirmada (presentation_ack) para o eixo do EEG;
  * envia ao app um resumo (eeg_status) e um traco reduzido (eeg_preview), que o app repassa
    ao Painel Central junto com a telemetria que ja existe.

Executar:  python -m sentir.agent --config config/agent.yaml
Protocolo: docs/03-protocolos.md, secao "App monitor_oasis <-> agente EEG".
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import platform
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from . import __version__
from .clock import ClockModel, SyncSample
from .config import AgentConfig, load_config
from .model import Chunk, Event
from .recorder import Recorder

log = logging.getLogger("sentir.agent")


class LiveStats:
    """Janela curta de EEG para qualidade de sinal, fotodiodo e preview (thread-safe)."""

    def __init__(self, window_s: float = 2.0):
        self.window_s = window_s
        self.lock = threading.Lock()
        self.chunks: deque[Chunk] = deque()
        self.columns: list[str] = []
        self.n_channels = 0
        self.pd_edges: deque[float] = deque(maxlen=200)
        self._pd_last = 0.0
        self.preview_since = 0.0

    def add(self, c: Chunk) -> None:
        if c.stream != "eeg" or not len(c):
            return
        with self.lock:
            self.columns = c.columns
            self.n_channels = c.columns.index("battery_v")
            self.chunks.append(c)
            while self.chunks and c.host_ts[-1] - self.chunks[0].host_ts[-1] > self.window_s:
                self.chunks.popleft()
            if "photodiode" in c.columns:
                pd = c.data[:, c.columns.index("photodiode")]
                prev = np.concatenate([[self._pd_last], pd[:-1]])
                for i in np.where((pd > 0.5) & (prev <= 0.5))[0]:
                    self.pd_edges.append(float(c.host_ts[i]))
                self._pd_last = float(pd[-1])

    def snapshot(self) -> dict:
        with self.lock:
            if not self.chunks:
                return {}
            data = np.concatenate([c.data for c in self.chunks])
            host = np.concatenate([c.host_ts for c in self.chunks])
        n = self.n_channels
        last1s = host >= host[-1] - 1.0
        x = data[last1s, :n].astype(np.float64)
        x = x - x.mean(axis=0)
        out = {
            "channels": self.columns[:n],
            "rms_uv": np.round(np.sqrt((x ** 2).mean(axis=0)), 2).tolist() if len(x) else [],
            # perto do fundo de escala (+-4,5 V / PGA) -> eletrodo solto / saturacao
            "saturated": (np.abs(data[last1s, :n]).max(axis=0) > 0.95 * 4.5e6 / 24).tolist()
            if len(x) else [],
            "battery_v": round(float(data[-1, n]), 2),
            "last_sample_host": float(host[-1]),
        }
        if "loff_statp" in self.columns:
            i = self.columns.index("loff_statp")
            out["loff_statp"] = int(data[-1, i])
            out["loff_statn"] = int(data[-1, i + 1])
            out["photodiode"] = int(data[-1, self.columns.index("photodiode")])
        return out

    def preview(self, hz: float) -> dict | None:
        """Traco decimado (media por bloco) desde o ultimo preview, para o Painel Central."""
        with self.lock:
            chunks = [c for c in self.chunks if c.host_ts[-1] > self.preview_since]
            if not chunks:
                return None
            host = np.concatenate([c.host_ts for c in chunks])
            data = np.concatenate([c.data for c in chunks])[:, : self.n_channels]
            names = self.columns[: self.n_channels]
        keep = host > self.preview_since
        host, data = host[keep], data[keep]
        if len(host) < 2:
            return None
        fs = 1.0 / np.median(np.diff(host))
        step = max(1, int(round(fs / hz)))
        m = (len(host) // step) * step
        if m == 0:
            return None
        self.preview_since = float(host[m - 1])
        d = data[:m].reshape(-1, step, data.shape[1]).mean(axis=1)
        return {"t0": float(host[0]), "dt": step / fs, "channels": names,
                "data": np.round(d, 1).T.tolist()}


class EegAgent:
    def __init__(self, cfg: AgentConfig):
        self.cfg = cfg
        self.live = LiveStats()
        self.source = None
        self.source_error: str | None = None
        self.recorder: Recorder | None = None
        self.session_meta: dict = {}
        self.app_clock = ClockModel(window=60, min_span_for_drift_s=30)
        self.app_pending: dict[int, float] = {}
        self.app_seq = 0
        self.last_stimulus_host: float | None = None
        self.pd_latencies_ms: deque[float] = deque(maxlen=200)
        self.events_count = 0
        self.lock = threading.Lock()

    # ------------------------------------------------------------- fonte Meower
    def _sink(self, c: Chunk) -> None:
        self.live.add(c)
        rec = self.recorder
        if rec is not None:
            rec(c)

    def start_source(self) -> None:
        """Conecta a Meower em segundo plano, tentando de novo ate conseguir."""
        def run():
            while True:
                try:
                    m = asdict(self.cfg.meower)
                    driver = m.pop("driver")
                    if driver == "brainflow":
                        from .sources.meower_brainflow import MeowerBrainFlowSource as Src
                    else:
                        from .sources.meower_udp import MeowerUdpSource as Src
                    src = Src(self.cfg.station_id, self._sink, **m)
                    src.prepare()
                    src.start()
                    self.source = src
                    self.source_error = None
                    return
                except Exception as e:  # noqa: BLE001
                    self.source_error = str(e)
                    log.warning("Meower indisponivel (%s); nova tentativa em 3 s", e)
                    time.sleep(3)
        threading.Thread(target=run, name="meower-connect", daemon=True).start()

    # ----------------------------------------------------------------- sessao
    def session_start(self, msg: dict) -> dict:
        with self.lock:
            if self.recorder is not None:
                self._close_recorder()
            subject = str(msg.get("subject_code") or "SEM_CODIGO").replace("/", "_").replace("\\", "_")
            sdir = Path(self.cfg.data_dir) / self.cfg.station_id / subject / time.strftime("%Y%m%d-%H%M%S")
            self.recorder = Recorder(sdir, flat=True)
            src = self.source
            self.session_meta = {
                "sentir_version": __version__,
                "station_id": self.cfg.station_id,
                "subject_code": msg.get("subject_code"),
                "monitor_oasis_session_id": msg.get("session_id"),
                "protocol": msg.get("protocol"),
                "created_host_time": time.time(),
                "host": platform.node(),
                "time_base": "host UNIX time (time.time), seconds; app clock mapped by TSYNC",
                "meower": None if src is None else {"status": dict(src.status), "fs": self.cfg.meower.fs,
                                                    "pga_gain": self.cfg.meower.pga_gain},
                "config": asdict(self.cfg),
            }
            self.recorder.write_manifest(self.session_meta)
            self.events_count = 0
            self.pd_latencies_ms.clear()
            self._event(Event(time.time(), self.cfg.station_id, "session_start", source="app",
                              extra=json.dumps(msg)))
            log.info("sessao iniciada em %s", sdir)
            return {"type": "session_started", "dir": str(sdir.resolve())}

    def _close_recorder(self) -> dict:
        rec, self.recorder = self.recorder, None
        stats = rec.close() if rec else {}
        summary = {"rows": stats}
        if rec is not None:
            try:
                from .analysis.resync import resync_session
                summary["resync"] = resync_session(rec.dir)
            except Exception as e:  # noqa: BLE001
                summary["resync_error"] = str(e)
            if self.pd_latencies_ms:
                lat = np.asarray(self.pd_latencies_ms)
                summary["photodiode_latency_ms"] = {"n": int(lat.size), "median": float(np.median(lat)),
                                                    "p95": float(np.percentile(lat, 95)),
                                                    "sd": float(np.std(lat))}
            self.session_meta["summary"] = summary
            rec.write_manifest(self.session_meta)
            summary["dir"] = str(rec.dir.resolve())
        return summary

    def session_stop(self) -> dict:
        with self.lock:
            if self.recorder is None:
                return {"type": "session_stopped", "summary": {}}
            self._event(Event(time.time(), self.cfg.station_id, "session_stop", source="app"))
            return {"type": "session_stopped", "summary": self._close_recorder()}

    def _event(self, e: Event) -> None:
        if self.recorder is not None:
            self.recorder.event(e)
            self.events_count += 1

    def app_to_host(self, app_us: float) -> tuple[float, str]:
        fit = self.app_clock.fit
        if fit is None:
            return time.time(), "app_unsynced"
        return float(fit.to_host(app_us * 1e-6)), "app"

    def phase(self, msg: dict) -> None:
        """Fase confirmada pelo presentation_ack do monitor_oasis (start_ms = DateTime.now)."""
        host, src = self.app_to_host(float(msg["start_ms"]) * 1000.0)
        etype = str(msg.get("event_type", "")).upper()
        if etype == "STIMULUS":
            self.last_stimulus_host = host
        self._event(Event(host, self.cfg.station_id, "phase_onset", int(msg.get("exposure_id", -1)),
                          etype.lower(), str(msg.get("image_name", "")),
                          float(msg.get("latency_ms", float("nan"))), src, json.dumps(msg)))

    def note(self, msg: dict) -> None:
        host, src = self.app_to_host(float(msg.get("t_ms", time.time() * 1000)) * 1000.0)
        self._event(Event(host, self.cfg.station_id, "note", source=src, extra=str(msg.get("text", ""))))

    def app_sync_reply(self, msg: dict, t4: float) -> None:
        t1 = self.app_pending.pop(int(msg["seq"]), None)
        if t1 is None:
            return
        s = SyncSample(t1, msg["t2"] * 1e-6, msg["t3"] * 1e-6, t4)
        self.app_clock.add(s)
        if self.recorder is not None:
            self.recorder(Chunk(self.cfg.station_id, "clock_app", ["t1", "t2", "t3", "t4", "rtt_ms"],
                                np.array([t4]), np.array([s.t3]),
                                np.array([[s.t1, s.t2, s.t3, s.t4, s.rtt * 1e3]])))

    # ----------------------------------------------------------------- status
    def status(self) -> dict:
        src = self.source
        snap = self.live.snapshot()
        # latencia tela->fotodiodo: borda de luz seguinte ao ultimo inicio de estimulo confirmado
        if self.last_stimulus_host is not None:
            for e in list(self.live.pd_edges):
                if 0 <= e - self.last_stimulus_host < 0.5:
                    self.pd_latencies_ms.append((e - self.last_stimulus_host) * 1e3)
                    self.last_stimulus_host = None
                    break
        fit = self.app_clock.fit
        s = {
            "type": "eeg_status",
            "station_id": self.cfg.station_id,
            "host_time": time.time(),
            "meower": None if src is None else {k: v for k, v in src.status.items() if k != "device"},
            "device": None if src is None else src.status.get("device"),
            "error": self.source_error,
            "recording": self.recorder is not None,
            "session_dir": None if self.recorder is None else str(self.recorder.dir),
            "events": self.events_count,
            "app_sync_ms": None if fit is None else round(fit.uncertainty_ms, 3),
            "signal": snap,
            "photodiode_latency_ms": None if not self.pd_latencies_ms else
            round(float(np.median(self.pd_latencies_ms)), 2),
        }
        if src is not None and src.status.get("device", {}).get("fake") == 1:
            s["warning"] = "Meower com ADC EMULADO (firmware de teste)"
        return s


# ======================================================================= API
def create_app(cfg: AgentConfig, start_source: bool = True) -> FastAPI:
    agent = EegAgent(cfg)

    @asynccontextmanager
    async def lifespan(_app):
        if start_source:
            agent.start_source()
        yield
        with agent.lock:
            if agent.recorder is not None:
                agent._close_recorder()
        if agent.source is not None:
            agent.source.stop()

    app = FastAPI(title="SENTIR - agente EEG", version=__version__, lifespan=lifespan)
    app.state.agent = agent

    class StartBody(BaseModel):
        subject_code: str = "TESTE"
        session_id: int | None = None

    @app.get("/api/status")
    def get_status():
        return agent.status()

    @app.post("/api/session/start")
    def post_start(body: StartBody):
        return agent.session_start(body.model_dump())

    @app.post("/api/session/stop")
    def post_stop():
        return agent.session_stop()

    @app.websocket("/ws/app")
    async def ws_app(ws: WebSocket):
        await ws.accept()

        async def sync_loop():
            while True:
                agent.app_seq += 1
                agent.app_pending[agent.app_seq] = time.time()
                await ws.send_json({"type": "tsync", "seq": agent.app_seq})
                if len(agent.app_pending) > 50:
                    agent.app_pending = dict(list(agent.app_pending.items())[-10:])
                await asyncio.sleep(0.5 if agent.app_clock.fit is None else 2.0)

        async def status_loop():
            while True:
                await ws.send_json(agent.status())
                if cfg.preview_hz > 0:
                    pv = agent.live.preview(cfg.preview_hz)
                    if pv:
                        await ws.send_json({"type": "eeg_preview", **pv})
                await asyncio.sleep(cfg.status_interval_s)

        tasks = [asyncio.create_task(sync_loop()), asyncio.create_task(status_loop())]
        try:
            while True:
                msg = await ws.receive_json()
                t4 = time.time()
                kind = msg.get("type")
                if kind == "tsync":
                    agent.app_sync_reply(msg, t4)
                elif kind == "session_start":
                    await ws.send_json(await asyncio.to_thread(agent.session_start, msg))
                elif kind == "phase":
                    agent.phase(msg)
                elif kind == "note":
                    agent.note(msg)
                elif kind == "session_stop":
                    await ws.send_json(await asyncio.to_thread(agent.session_stop))
        except WebSocketDisconnect:
            pass
        finally:
            for t in tasks:
                t.cancel()

    return app


def main() -> None:
    import uvicorn

    p = argparse.ArgumentParser(description="SENTIR - agente EEG da estacao")
    p.add_argument("--config", default="config/agent.yaml")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config(a.config)
    uvicorn.run(create_app(cfg), host=cfg.host, port=cfg.port, log_level="warning")


if __name__ == "__main__":
    main()
