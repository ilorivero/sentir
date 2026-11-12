import json
import random
import struct

import numpy as np

from sentir.clock import ClockModel, SyncSample, TickUnwrapper, fit_clock
from sentir.sources.meower_udp import parse_datagram
from sentir.sources.meower_common import decode_status, eeg_columns, make_eeg_chunk, parse_id_reply


def simulated_samples(offset=1000.0, ppm=30.0, n=200, jitter_ms=3.0, seed=0):
    rng = random.Random(seed)
    k = 1 + ppm * 1e-6
    out = []
    for i in range(n):
        t1 = 1.7e9 + i * 1.0
        up = 0.0008 + rng.expovariate(1 / (jitter_ms / 1000))
        down = 0.0008 + rng.expovariate(1 / (jitter_ms / 1000))
        dev = lambda h: offset + (h - 1.7e9) * k  # noqa: E731
        t2 = dev(t1 + up)
        t3 = t2 + 0.0001
        t4 = t1 + up + 0.0001 / k + down
        out.append(SyncSample(t1, t2, t3, t4))
    return out, (lambda d: 1.7e9 + (d - offset) / k)


def test_clock_fit_recovers_offset_and_drift():
    samples, truth = simulated_samples()
    fit = fit_clock(samples)
    assert abs(fit.drift_ppm - 30.0) < 3.0
    dev = np.array([1000.0, 1100.0, 1199.0])
    err_ms = np.abs(fit.to_host(dev) - truth(dev)) * 1e3
    assert err_ms.max() < 1.0, err_ms


def test_clock_model_window_and_invalid():
    m = ClockModel(window=50)
    samples, _ = simulated_samples(n=80)
    for s in samples:
        m.add(s)
    assert len(m.samples) == 50
    assert m.add(SyncSample(10, 0, 0, 5)) is m.fit  # t4 < t1 rejeitado


def test_tick_unwrap():
    u = TickUnwrapper()
    vals = [0xFFFFFFF0, 0xFFFFFFFF, 0x00000005, 0x00000100]
    out = [u(v) for v in vals]
    assert out == [0xFFFFFFF0, 0xFFFFFFFF, 0x100000005, 0x100000100]
    u2 = TickUnwrapper()
    u2.set_reference(3 * 2**32 + 10)
    assert u2(20) == 3 * 2**32 + 20


def make_datagram(samples, ticks, battery=3.9):
    buf = bytearray()
    for row, t in zip(samples, ticks):
        for v in row:
            buf += (int(v) & 0xFFFFFF).to_bytes(3, "big")
        buf += struct.pack("<I", t)
    return bytes(buf + struct.pack("<f", battery))


def test_parse_datagram_sign_and_ticks():
    rows = [[-8388608, 8388607, -1, 0] + [i] * 12 for i in range(5)]
    pkt = make_datagram(rows, [10, 135, 260, 385, 510])
    raw, ticks, bat = parse_datagram(pkt)
    assert raw.shape == (5, 16)
    assert raw[0, 0] == -8388608 and raw[0, 1] == 8388607 and raw[0, 2] == -1
    assert list(ticks) == [10, 135, 260, 385, 510]
    assert abs(bat - 3.9) < 1e-6


def test_id_reply_and_status_word():
    info = parse_id_reply("ID 02:00:00:00:00:01 SENTIR-TSYNC/1 ads=1 fake=1 fw=sentir-meower-0.2")
    assert info["mac"] == "02:00:00:00:00:01" and info["ads"] == 1 and info["fake"] == 1
    # cabecalho 1100, LOFF_STATP=0x81, LOFF_STATN=0x02, GPIO1=1
    word = (0xC << 20) | (0x81 << 12) | (0x02 << 4) | 0x1
    st = decode_status(np.array([word, 0xC00000]))
    assert st["status_valid"].tolist() == [1, 1]
    assert st["loff_statp"][0] == 0x81 and st["loff_statn"][0] == 0x02
    assert st["photodiode"].tolist() == [1, 0]


def test_eeg_chunk_8_channels():
    raw = np.zeros((3, 16), dtype=np.int64)
    raw[:, 0] = 1000
    raw[:, 15] = [-4194303, 0xC00000 - (1 << 24), 0xC00001 - (1 << 24)]  # int24 com sinal
    c = make_eeg_chunk("A", raw, np.arange(3.0), np.arange(3.0), 3.9, 8, ["Fp1"], 1, 1)
    assert c.columns == eeg_columns(8, ["Fp1"]) and c.columns[0] == "Fp1" and c.columns[7] == "CH8"
    assert abs(c.data[0, 0] - 1000 * 4.5 / 8388608 * 1e6) < 1e-3
    pd = c.data[:, c.columns.index("photodiode")]
    assert pd.tolist() == [1.0, 0.0, 1.0]
    c16 = make_eeg_chunk("A", raw, np.arange(3.0), np.arange(3.0), 3.9, 16, [], 1, 1)
    assert "photodiode" not in c16.columns and len(c16.columns) == 17
