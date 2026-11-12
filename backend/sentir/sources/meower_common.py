"""Partes comuns as fontes Meower (UDP nativa e BrainFlow).

Placa de 8 canais (um so ADS1299, firmware SENTIR): os slots dos canais 9-15 chegam zerados
e o slot do canal 16 traz a palavra de STATUS do ADS1299 mestre (24 bits):

    [23:20] = 1100 (cabecalho)   [19:12] = LOFF_STATP   [11:4] = LOFF_STATN   [3:0] = GPIO4..GPIO1

GPIO1 = fotodiodo (comparador ligado ao pino GPIO1 do ADS1299) -> instante real do estimulo
amostrado pelo MESMO ADC do EEG. LOFF_STATP/N = deteccao de eletrodo solto (se o lead-off
estiver habilitado no ADS1299).
"""
from __future__ import annotations

import numpy as np

from ..model import Chunk

LSB_UV = 4.5 / 8388608.0 * 1e6


def parse_id_reply(reply: str) -> dict:
    """'ID 02:00:.. SENTIR-TSYNC/1 ads=1 fake=0 fw=sentir-meower-0.2' -> dict."""
    out: dict = {"raw": reply}
    parts = reply.split()
    if len(parts) >= 2 and parts[0] == "ID":
        out["mac"] = parts[1]
    for p in parts[2:]:
        if "=" in p:
            k, v = p.split("=", 1)
            out[k] = int(v) if v.isdigit() else v
        elif p.startswith("SENTIR-TSYNC/"):
            out["protocol"] = p
    return out


def decode_status(raw24: np.ndarray) -> dict[str, np.ndarray]:
    """Decodifica a palavra de status (inteiros sem sinal de 24 bits)."""
    s = np.asarray(raw24, dtype=np.int64) & 0xFFFFFF
    return {
        "status_valid": ((s >> 20) == 0xC).astype(np.float32),
        "loff_statp": ((s >> 12) & 0xFF).astype(np.float32),
        "loff_statn": ((s >> 4) & 0xFF).astype(np.float32),
        "photodiode": (s & 0x1).astype(np.float32),        # GPIO1
        "gpio": (s & 0xF).astype(np.float32),
    }


def eeg_columns(n_channels: int, channel_names: list[str]) -> list[str]:
    names = list(channel_names[:n_channels])
    names += [f"CH{i + 1}" for i in range(len(names), n_channels)]
    cols = [*names, "battery_v"]
    if n_channels == 8:
        cols += ["photodiode", "loff_statp", "loff_statn", "status_raw"]
    return cols


def make_eeg_chunk(participant: str, raw: np.ndarray, host: np.ndarray, dev: np.ndarray,
                   battery: float | np.ndarray, n_channels: int, channel_names: list[str],
                   pga_gain: float, digital_gain: float, meta: dict | None = None,
                   uv: np.ndarray | None = None) -> Chunk:
    """Monta o Chunk 'eeg'. ``raw`` = inteiros int24 com sinal (n, 16); se ``uv`` for dado
    (fonte BrainFlow, ja em uV), ele e usado nos canais de EEG."""
    n = raw.shape[0]
    cols = eeg_columns(n_channels, channel_names)
    data = np.zeros((n, len(cols)), dtype=np.float32)
    if uv is None:
        data[:, :n_channels] = raw[:, :n_channels] * (LSB_UV / (pga_gain * digital_gain))
    else:
        data[:, :n_channels] = uv[:, :n_channels]
    data[:, n_channels] = battery
    if n_channels == 8:
        status = raw[:, 15].astype(np.int64) & 0xFFFFFF   # int24 com sinal -> sem sinal
        st = decode_status(status)
        data[:, 9] = st["photodiode"]
        data[:, 10] = st["loff_statp"]
        data[:, 11] = st["loff_statn"]
        data[:, 12] = status.astype(np.float32)
        meta = {**(meta or {}), "status_valid": float(st["status_valid"].mean()) if n else 0.0}
    return Chunk(participant, "eeg", cols, host, dev, data, meta or {})
