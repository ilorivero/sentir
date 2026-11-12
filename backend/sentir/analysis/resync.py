"""Reajuste offline do eixo de tempo com todos os pares TSYNC da sessao.

O timestamp gravado em tempo real (host_ts) usa uma janela deslizante e "slew"; depois
da sessao temos todos os pares e podemos ajustar uma unica reta (offset + deriva) por
dispositivo, ou uma reta por trecho se o dispositivo reiniciou. O resultado e a coluna
``t`` (relogio do host, s) usada pelo pipeline de ML.

Uso:  python -m sentir.analysis.resync <pasta_da_sessao | pasta_da_estacao>
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from ..clock import SyncSample, fit_clock

CLOCK_FOR_STREAM = {"eeg": "clock_meower"}


def fit_from_parquet(path: Path, keep_fraction: float = 0.2):
    t = pq.read_table(path).to_pandas()
    samples = [SyncSample(r.t1, r.t2, r.t3, r.t4) for r in t.itertuples()]
    return fit_clock(samples, keep_fraction=keep_fraction, min_span_for_drift_s=20)


def resync_dir(d: Path) -> dict:
    """Reajusta os fluxos de uma pasta de sessao (eeg.parquet + clock_meower.parquet)."""
    report = {}
    fits = {}
    for clock in set(CLOCK_FOR_STREAM.values()):
        f = d / f"{clock}.parquet"
        if f.exists():
            fits[clock] = fit_from_parquet(f)
    for stream, clock in CLOCK_FOR_STREAM.items():
        f = d / f"{stream}.parquet"
        fit = fits.get(clock)
        if not f.exists() or fit is None:
            continue
        tbl = pq.read_table(f)
        dev = tbl.column("dev_ts").to_numpy()
        t = fit.to_host(dev)
        delta_ms = (t - tbl.column("host_ts").to_numpy()) * 1e3
        if "t" in tbl.column_names:
            tbl = tbl.set_column(tbl.column_names.index("t"), "t", pa.array(t))
        else:
            tbl = tbl.append_column("t", pa.array(t))
        pq.write_table(tbl, f, compression="zstd")
        report[stream] = {
            "drift_ppm": round(fit.drift_ppm, 2),
            "uncertainty_ms": round(fit.uncertainty_ms, 3),
            "max_abs_change_vs_online_ms": round(float(np.max(np.abs(delta_ms))), 3),
        }
    return report


def resync_session(session_dir: str | Path) -> dict:
    """Aceita a pasta da sessao do agente ou uma pasta acima dela (varre as subpastas)."""
    sdir = Path(session_dir)
    if (sdir / "eeg.parquet").exists():
        return resync_dir(sdir)
    return {str(p.parent.relative_to(sdir)): resync_dir(p.parent) for p in sorted(sdir.rglob("eeg.parquet"))}


if __name__ == "__main__":
    import json
    print(json.dumps(resync_session(sys.argv[1]), indent=2))
