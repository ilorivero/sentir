"""Inicio real dos estimulos medido pelo fotodiodo, comparado as fases do monitor_oasis.

Placa de 8 canais: o fotodiodo entra (via comparador) no GPIO1 do ADS1299 e aparece na
coluna binaria ``photodiode`` de eeg.parquet - amostrada pelo MESMO ADC do EEG.
Placa de 16 canais: pode-se usar um canal analogico (passe o nome da coluna).

O app monitor_oasis precisa desenhar o marcador do fotodiodo na janela do participante
(quadrado branco durante o estimulo - ver integration/monitor_oasis).

Uso:  python -m sentir.analysis.photodiode <pasta_da_sessao> [coluna]
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq


def detect_edges(t: np.ndarray, x: np.ndarray, min_interval_s: float = 0.5) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    if np.isin(np.unique(x), [0.0, 1.0]).all():
        high = x > 0.5                       # coluna binaria (GPIO1)
    else:
        x = x - np.median(x)
        high = np.abs(x) > 0.5 * np.percentile(np.abs(x), 99.5)
    idx = np.where(high[1:] & ~high[:-1])[0] + 1
    out, last = [], -np.inf
    for i in idx:
        if t[i] - last >= min_interval_s:
            out.append(t[i])
            last = t[i]
    return np.asarray(out)


def match_onsets(session_dir: str | Path, column: str = "photodiode", max_lag_s: float = 0.2) -> dict:
    sdir = Path(session_dir)
    names = pq.read_schema(sdir / "eeg.parquet").names
    tcol = "t" if "t" in names else "host_ts"
    eeg = pq.read_table(sdir / "eeg.parquet", columns=[tcol, column]).to_pandas()
    edges = detect_edges(eeg[tcol].to_numpy(), eeg[column].to_numpy())
    ev = pq.read_table(sdir / "events.parquet").to_pandas()
    ons = ev[(ev.kind == "phase_onset") & (ev.phase == "stimulus")]
    lat = []
    for ts in ons.host_ts.to_numpy():
        j = np.searchsorted(edges, ts - max_lag_s)
        cand = edges[j: j + 3]
        cand = cand[np.abs(cand - ts) < max_lag_s]
        if cand.size:
            lat.append(cand[np.argmin(np.abs(cand - ts))] - ts)
    lat_ms = np.asarray(lat) * 1e3
    return {"edges": int(edges.size), "stimuli": int(len(ons)), "matched": int(lat_ms.size),
            "latency_ms_median": float(np.median(lat_ms)) if lat_ms.size else None,
            "latency_ms_p95": float(np.percentile(lat_ms, 95)) if lat_ms.size else None,
            "jitter_ms_sd": float(np.std(lat_ms)) if lat_ms.size else None}


if __name__ == "__main__":
    print(match_onsets(*sys.argv[1:3]))
