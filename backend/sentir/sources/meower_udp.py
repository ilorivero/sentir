"""Fonte Meower em Python puro (UDP), sem depender do build do BrainFlow.

Usada em desenvolvimento (com ``tools/meower_sim.py``), em testes automatizados e como
plano B caso o driver BrainFlow nao esteja disponivel na maquina. A fonte de producao e
``meower_brainflow.MeowerBrainFlowSource``; as duas entregam exatamente o mesmo formato
de ``Chunk`` ao gravador.
"""
from __future__ import annotations

import logging
import socket
import struct
import time

import numpy as np

from ..clock import ArrivalMinEstimator, ContinuousMapper, SyncSample, TickUnwrapper
from ..model import Chunk
from .base import ChunkSink, Source
from .meower_common import make_eeg_chunk, parse_id_reply

log = logging.getLogger(__name__)

FRAME = 52
BATTERY = 4
TICK_S = 8e-6
LSB_UV = 4.5 / 8388608.0 * 1e6
VALID_FS = (250, 500, 1000, 2000, 4000)


def parse_datagram(buf: bytes) -> tuple[np.ndarray, np.ndarray, float]:
    """Decodifica um datagrama Meower.

    Retorna (amostras int32 (n,16), ticks uint32 (n,), bateria_V).
    Canais em int24 big-endian; timestamp e bateria little-endian.
    """
    n_bytes = len(buf)
    if n_bytes < FRAME + BATTERY or (n_bytes - BATTERY) % FRAME:
        raise ValueError(f"tamanho de datagrama invalido: {n_bytes}")
    n = (n_bytes - BATTERY) // FRAME
    arr = np.frombuffer(buf, dtype=np.uint8, count=n * FRAME).reshape(n, FRAME)
    ch = arr[:, :48].reshape(n, 16, 3).astype(np.int32)
    raw = (ch[:, :, 0] << 16) | (ch[:, :, 1] << 8) | ch[:, :, 2]
    raw = (raw << 8) >> 8  # extensao de sinal 24 -> 32 bits
    ticks = arr[:, 48:52].copy().view("<u4").reshape(n)
    battery = struct.unpack("<f", buf[-4:])[0]
    return raw, ticks, battery


class MeowerUdpSource(Source):
    kind = "meower"

    def __init__(self, participant: str, sink: ChunkSink, *, ip: str = "", ctrl_port: int = 5000,
                 data_port: int = 5001, board_ctrl_port: int | None = None, fs: int = 1000,
                 pga_gain: int = 24, digital_gain: int = 1, channel_names: list[str] | None = None,
                 init_commands: list[str] | None = None, tsync_interval_s: float = 1.0,
                 discovery_timeout_s: float = 5.0, channels: int | str = "auto", **_):
        super().__init__(participant, sink)
        if fs not in VALID_FS:
            raise ValueError(f"fs deve ser um de {VALID_FS}")
        self.ip = ip
        self.ctrl_port = ctrl_port
        self.data_port = data_port
        self.board_ctrl_port = board_ctrl_port or ctrl_port
        self.fs = fs
        self.pga_gain = pga_gain
        self.digital_gain = digital_gain
        self.channel_names = channel_names or [f"CH{i + 1}" for i in range(16)]
        self.init_commands = init_commands or []
        self.channels_cfg = channels      # "auto" (pergunta a placa), 8 ou 16
        self.n_channels = 16
        self.device_info: dict = {}
        self.tsync_interval_s = tsync_interval_s
        self.discovery_timeout_s = discovery_timeout_s
        self.unwrap = TickUnwrapper()
        self.fallback = ArrivalMinEstimator()
        self.mapper = ContinuousMapper(self.clock)
        self.tsync_supported = False
        self._seq = 0
        self._pending: dict[int, float] = {}
        self._ctrl: socket.socket | None = None
        self._data: socket.socket | None = None
        self.frames = 0
        self.lost = 0
        self._last_tick: int | None = None
        self._replies: list[str] = []

    # ------------------------------------------------------------------ controle
    def _send(self, msg: str) -> None:
        assert self._ctrl is not None
        self._ctrl.sendto(msg.encode(), (self.ip, self.board_ctrl_port))

    def command(self, msg: str, timeout: float = 1.0) -> str:
        """Envia comando sys/usr e espera a resposta (as respostas TSYNC sao tratadas a parte)."""
        self._replies.clear()
        self._send(msg)
        t_end = time.time() + timeout
        while time.time() < t_end:
            if self._replies:
                return self._replies.pop(0)
            time.sleep(0.005)
        return "TIMEOUT"

    def _ctrl_loop(self) -> None:
        assert self._ctrl is not None
        self._ctrl.settimeout(0.2)
        while not self._stop.is_set():
            try:
                pkt, addr = self._ctrl.recvfrom(2048)
            except socket.timeout:
                continue
            t4 = time.time()
            if addr[0] != self.ip:
                continue
            msg = pkt.decode(errors="replace").strip()
            if msg.startswith("MEOW_MEOW") or msg == "WOOF_WOOF":
                continue
            if msg.startswith("TSYNC "):
                parts = msg.split()
                if len(parts) == 4:
                    seq = int(parts[1])
                    t1 = self._pending.pop(seq, None)
                    if t1 is not None:
                        t2, t3 = int(parts[2]), int(parts[3])
                        self.unwrap.set_reference(t3)
                        self.tsync_supported = True
                        self._emit_sync(SyncSample(t1, t2 * TICK_S, t3 * TICK_S, t4), "meower")
                continue
            if "TSYNC" in msg.upper() and not msg.startswith("ID "):
                continue  # firmware sem patch responde ERR ao TSYNC
            self._replies.append(msg)

    def _ping_loop(self) -> None:
        last_keep = 0.0
        last_sync = 0.0
        while not self._stop.is_set():
            now = time.time()
            if now - last_keep > 4.0:
                self._send("WOOF_WOOF")
                last_keep = now
            interval = self.tsync_interval_s if self.tsync_supported else 5.0
            if now - last_sync > interval:
                self._seq += 1
                self._pending[self._seq] = time.time()
                self._send(f"TSYNC {self._seq}")
                last_sync = now
                if len(self._pending) > 50:
                    self._pending = dict(list(self._pending.items())[-10:])
            time.sleep(0.02)

    def _discover(self) -> None:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("0.0.0.0", self.ctrl_port))
        s.settimeout(0.2)
        t_end = time.time() + self.discovery_timeout_s
        try:
            while time.time() < t_end:
                try:
                    pkt, addr = s.recvfrom(256)
                except socket.timeout:
                    continue
                if pkt.startswith(b"MEOW_MEOW"):
                    self.ip = addr[0]
                    return
        finally:
            s.close()
        raise TimeoutError(f"nenhum beacon MEOW_MEOW na porta {self.ctrl_port}")

    def prepare(self) -> None:
        self.status["state"] = "preparing"
        if not self.ip:
            self._discover()
        self._ctrl = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._ctrl.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._ctrl.bind(("0.0.0.0", self.ctrl_port))
        self._data = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._data.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
        self._data.bind(("0.0.0.0", self.data_port))
        self._spawn(self._ctrl_loop, "ctrl")
        self._spawn(self._ping_loop, "ping")
        time.sleep(0.2)
        reply = self.command("ID?")
        self.device_info = parse_id_reply(reply) if reply.startswith("ID ") else {}
        if self.channels_cfg == "auto":
            self.n_channels = 8 if self.device_info.get("ads") == 1 else 16
        else:
            self.n_channels = int(self.channels_cfg)
        if self.device_info.get("fake") == 1:
            log.warning("[%s] Meower com ADC EMULADO (firmware de teste) - nao usar com participantes",
                        self.participant)
        for cmd in [f"usr set_sampling_freq {self.fs}", f"usr gain ALL {self.pga_gain}",
                    f"sys digitalgain {self.digital_gain}", *self.init_commands]:
            reply = self.command(cmd)
            log.info("[%s] %s -> %s", self.participant, cmd, reply)
            if reply.startswith("ERR"):
                raise RuntimeError(f"Meower recusou '{cmd}': {reply}")
        # aquecimento do relogio
        t_end = time.time() + 3.0
        while time.time() < t_end and self.clock.fit is None:
            time.sleep(0.05)
        self.status.update(state="ready", ip=self.ip, tsync=self.tsync_supported, fs=self.fs,
                           channels=self.n_channels, device=self.device_info)

    def start(self) -> None:
        self._spawn(self._data_loop, "data")  # leitor antes do start_cnt: evita fila no socket
        self._send("sys start_cnt")
        self.status["state"] = "streaming"

    def stop(self) -> None:
        try:
            if self._ctrl:
                self._send("sys stop_cnt")
        finally:
            super().stop()
            for s in (self._ctrl, self._data):
                if s:
                    s.close()

    # --------------------------------------------------------------------- dados
    def _data_loop(self) -> None:
        assert self._data is not None
        self._data.settimeout(0.2)
        dt_ticks = 1.0 / self.fs / TICK_S
        while not self._stop.is_set():
            try:
                pkt = self._data.recv(2048)
            except socket.timeout:
                continue
            arrival = time.time()
            try:
                raw, ticks32, battery = parse_datagram(pkt)
            except ValueError:
                continue
            ticks = np.array([self.unwrap(int(t)) for t in ticks32], dtype=np.int64)
            if self._last_tick is not None:
                gaps = np.diff(np.concatenate([[self._last_tick], ticks]))
                self.lost += int(np.sum(np.maximum(np.round(gaps / dt_ticks) - 1, 0)))
            self._last_tick = int(ticks[-1])
            dev_s = ticks * TICK_S
            if self.clock.fit is not None:
                host = self.mapper(dev_s)
                unc = self.clock.fit.uncertainty_ms
            else:
                off = self.fallback.update(arrival, float(dev_s[-1]))
                host = dev_s + off
                unc = float("nan")
            self.frames += len(ticks)
            self.sink(make_eeg_chunk(self.participant, raw, host, dev_s, battery, self.n_channels,
                                     self.channel_names, self.pga_gain, self.digital_gain,
                                     {"sync_unc_ms": unc}))
            self.status.update(frames=self.frames, lost=self.lost, battery_v=round(battery, 2),
                               latency_ms=round((arrival - float(host[-1])) * 1e3, 2))
