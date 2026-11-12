"""Integracao: simulador da Meower -> fonte UDP -> gravador -> Parquet.

O erro de sincronizacao e medido pelo pulso do fotodiodo simulado, que acende em multiplos
exatos de 1 s do relogio do host: reconstruido a partir do Parquet, deve cair nesses instantes.
"""
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import pytest

from sentir.recorder import Recorder
from sentir.sources.meower_udp import MeowerUdpSource

TOOLS = Path(__file__).resolve().parents[2] / "tools"


def run_sim(ads: int, ctrl: int, data: int, seconds: float, tmp_path: Path):
    sim = subprocess.Popen([sys.executable, str(TOOLS / "meower_sim.py"), "--ads", str(ads),
                            "--ctrl-port", str(ctrl), "--data-port", str(data), "--drift-ppm", "35",
                            "--photodiode-period-s", "1.0", "--wifi-jitter-ms", "2"],
                           stdout=subprocess.DEVNULL)
    try:
        time.sleep(1.0)
        rec = Recorder(tmp_path / f"s{ads}", flush_interval_s=0.5, flat=True)
        m = MeowerUdpSource("A", rec, ctrl_port=ctrl, data_port=data, board_ctrl_port=ctrl + 100,
                            fs=1000, pga_gain=1, init_commands=[], tsync_interval_s=0.2)
        m.prepare()
        assert m.tsync_supported and m.clock.fit is not None
        assert m.n_channels == (8 if ads == 1 else 16)
        m.start()
        time.sleep(seconds)
        m.stop()
        stats = rec.close()
    finally:
        sim.terminate()
    return stats, pq.read_table(tmp_path / f"s{ads}" / "eeg.parquet").to_pandas()


def edge_error_ms(ts, high):
    edges = ts[1:][high[1:] & ~high[:-1]]
    assert len(edges) >= 3
    return (edges - np.round(edges)) * 1e3


@pytest.mark.parametrize("ads", [1, 2])
def test_meower_sim_end_to_end(ads, tmp_path):
    stats, eeg = run_sim(ads, 5600 + ads * 20, 5601 + ads * 20, 5, tmp_path)
    assert stats["eeg"] > 4000
    ts = eeg["host_ts"].to_numpy()
    assert np.all(np.diff(ts) > 0)
    assert abs(np.median(np.diff(ts)) - 1e-3) < 2e-5
    if ads == 1:
        assert list(eeg.columns[2:10]) == [f"CH{i}" for i in range(1, 9)]
        assert "photodiode" in eeg and "CH9" not in eeg
        high = eeg["photodiode"].to_numpy() > 0.5
    else:
        high = eeg["CH16"].to_numpy() > 100000
    err = edge_error_ms(ts, high)
    assert np.abs(err).max() < 3.0, err
