"""Fonte Meower via BrainFlow (driver MeowerBoard compilado com ``brainflow/integrate_meower.py``).

O driver ja entrega timestamps sincronizados (linha 17) e os pares TSYNC no preset
ANCILLARY; aqui apenas lemos o buffer do BrainFlow periodicamente e convertemos para
``Chunk`` no mesmo formato da fonte UDP nativa.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import numpy as np

from ..clock import SyncSample
from ..model import Chunk
from .base import ChunkSink, Source
from .meower_common import make_eeg_chunk, parse_id_reply

log = logging.getLogger(__name__)

ROW_BATTERY, ROW_TS, ROW_DEV, ROW_PKG, ROW_MARKER, ROW_UNC, ROW_LOST, ROW_STATUS = 16, 17, 18, 19, 20, 21, 22, 23


def resolve_board_id(explicit: int | None = None) -> int:
    from brainflow.board_shim import BoardIds  # import tardio: brainflow e opcional

    if explicit:
        return explicit
    if hasattr(BoardIds, "MEOWER_BOARD"):
        return int(BoardIds.MEOWER_BOARD)
    raise RuntimeError("BrainFlow instalado nao tem MEOWER_BOARD. Rode brainflow/integrate_meower.py, "
                       "recompile e reinstale o pacote Python (ver brainflow/README.md).")


class MeowerBrainFlowSource(Source):
    kind = "meower"

    def __init__(self, participant: str, sink: ChunkSink, *, ip: str = "", ctrl_port: int = 5000,
                 data_port: int = 5001, fs: int = 1000, pga_gain: int = 24, digital_gain: int = 1,
                 channel_names: list[str] | None = None, init_commands: list[str] | None = None,
                 board_id: int | None = None, board_ctrl_port: int | None = None,
                 poll_interval_s: float = 0.05, raw_backup_dir: str | None = None,
                 channels: int | str = "auto", **_):
        super().__init__(participant, sink)
        from brainflow.board_shim import BoardShim, BrainFlowInputParams

        p = BrainFlowInputParams()
        p.ip_address = ip
        p.ip_port = data_port
        p.ip_port_aux = ctrl_port
        other = [f"pga_gain={pga_gain}", f"digital_gain={digital_gain}"]
        if board_ctrl_port:
            other.append(f"board_ctrl_port={board_ctrl_port}")
        p.other_info = " ".join(other)
        self.board_id = resolve_board_id(board_id)
        self.board = BoardShim(self.board_id, p)
        self.fs = fs
        self.pga_gain = pga_gain
        self.digital_gain = digital_gain
        self.channel_names = channel_names or [f"CH{i + 1}" for i in range(16)]
        self.init_commands = init_commands or []
        self.poll_interval_s = poll_interval_s
        self.raw_backup_dir = raw_backup_dir
        self.channels_cfg = channels
        self.n_channels = 16
        self.device_info: dict = {}

    def prepare(self) -> None:
        self.status["state"] = "preparing"
        self.board.prepare_session()
        # "ads=1 channels=8 fake=0 id=ID <mac> SENTIR-TSYNC/1 ads=1 ..." (consulta local ao driver)
        head, _, id_reply = self.board.config_board("sentir:info").partition(" id=")
        info = dict(kv.split("=", 1) for kv in head.split() if "=" in kv)
        self.device_info = parse_id_reply(id_reply) if id_reply else {}
        self.n_channels = int(info.get("channels", 16)) if self.channels_cfg == "auto" else int(self.channels_cfg)
        if info.get("fake") == "1":
            log.warning("[%s] Meower com ADC EMULADO (firmware de teste)", self.participant)
        for cmd in [f"usr set_sampling_freq {self.fs}", f"usr gain ALL {self.pga_gain}",
                    f"sys digitalgain {self.digital_gain}", *self.init_commands]:
            reply = self.board.config_board(cmd)
            log.info("[%s] %s -> %s", self.participant, cmd, reply)
        self.status.update(state="ready", clock_model=self.board.config_board("sentir:clock"),
                           channels=self.n_channels, device=self.device_info)

    def start(self) -> None:
        streamer = ""
        if self.raw_backup_dir:
            Path(self.raw_backup_dir).mkdir(parents=True, exist_ok=True)
            streamer = f"file://{self.raw_backup_dir}/brainflow_{self.participant}.csv:w"
        self.board.start_stream(45000 * 10, streamer)
        self._spawn(self._poll_loop, "poll")
        self.status["state"] = "streaming"

    def insert_marker(self, value: float) -> None:
        """Marcador redundante dentro do fluxo BrainFlow (o oficial vai para events.parquet)."""
        try:
            self.board.insert_marker(value)
        except Exception:  # noqa: BLE001
            pass

    def _poll_loop(self) -> None:
        from brainflow.board_shim import BrainFlowPresets

        while not self._stop.is_set():
            time.sleep(self.poll_interval_s)
            d = self.board.get_board_data()
            if d.shape[1]:
                raw = np.zeros((d.shape[1], 16), dtype=np.int64)
                raw[:, 15] = d[ROW_STATUS].astype(np.int64)      # status (placa de 8 canais)
                self.sink(make_eeg_chunk(self.participant, raw, d[ROW_TS].copy(), d[ROW_DEV].copy(),
                                         d[ROW_BATTERY], self.n_channels, self.channel_names,
                                         self.pga_gain, self.digital_gain,
                                         {"sync_unc_ms": float(d[ROW_UNC, -1])}, uv=d[:16].T))
                self.status.update(frames=int(d[ROW_PKG, -1]) + 1, lost=int(d[ROW_LOST, -1]),
                                   battery_v=round(float(d[ROW_BATTERY, -1]), 2))
            a = self.board.get_board_data(preset=BrainFlowPresets.ANCILLARY_PRESET)
            for i in range(a.shape[1]):
                self._emit_sync(SyncSample(a[1, i], a[2, i], a[3, i], a[4, i]), "meower")

    def stop(self) -> None:
        super().stop()
        try:
            self.board.stop_stream()
        finally:
            self.board.release_session()
