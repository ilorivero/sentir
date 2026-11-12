"""Agente EEG + simulador da Meower (8 canais) + app monitor_oasis simulado (tools/app_sim.py).

Verifica: sessao gravada na estacao, fases do app (relogio 5 s adiantado e com deriva)
convertidas para o eixo do EEG, e latencia fotodiodo x inicio do estimulo ~0 ms.
"""
import asyncio
import importlib.util
import subprocess
import sys
import threading
import time
from pathlib import Path

import pyarrow.parquet as pq
import uvicorn

from sentir.agent import create_app
from sentir.analysis.photodiode import match_onsets
from sentir.config import AgentConfig, MeowerConfig

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("app_sim", ROOT / "tools/app_sim.py")
app_sim = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app_sim)


def test_agent_with_app_and_meower(tmp_path):
    sim = subprocess.Popen([sys.executable, str(ROOT / "tools/meower_sim.py"), "--ads", "1",
                            "--ctrl-port", "5650", "--data-port", "5651",
                            "--photodiode-period-s", "2.0", "--wifi-jitter-ms", "2"],
                           stdout=subprocess.DEVNULL)
    cfg = AgentConfig(station_id="A", data_dir=str(tmp_path), port=8799, status_interval_s=0.25,
                      meower=MeowerConfig(driver="udp", ip="127.0.0.1", ctrl_port=5650, data_port=5651,
                                          board_ctrl_port=5750, pga_gain=1, init_commands=[]))
    server = uvicorn.Server(uvicorn.Config(create_app(cfg), host="127.0.0.1", port=8799, log_level="warning"))
    th = threading.Thread(target=server.run, daemon=True)
    try:
        time.sleep(0.8)
        th.start()
        time.sleep(4.0)   # agente conecta a Meower e aquece os relogios
        args = type("A", (), dict(agent="127.0.0.1:8799", subject="A-PARTICIPANTE_7", stimuli=4,
                                  period=2.0, offset_s=5.0, drift_ppm=15.0, warmup_s=3.0))
        out = asyncio.run(app_sim.run(args))
    finally:
        server.should_exit = True
        th.join(timeout=5)
        sim.terminate()

    st = out["last_status"]
    assert st["meower"]["channels"] == 8 and st["app_sync_ms"] is not None
    summary = out["stopped"]["summary"]
    sdir = Path(summary["dir"])
    assert sdir.parent.name == "A-PARTICIPANTE_7" and sdir.parent.parent.name == "A"
    assert summary["rows"]["eeg"] > 5000 and summary["rows"]["clock_app"] >= 3
    ev = pq.read_table(sdir / "events.parquet").to_pandas()
    onsets = ev[(ev.kind == "phase_onset") & (ev.phase == "stimulus")].host_ts.to_numpy()
    assert len(onsets) == 4
    err_ms = (onsets - out["onsets_host"]) * 1e3          # relogio do app corrigido
    assert abs(err_ms).max() < 5, err_ms
    pd = match_onsets(sdir)
    assert pd["matched"] == 4 and abs(pd["latency_ms_median"]) < 3, pd
    assert "eeg" in summary["resync"]
