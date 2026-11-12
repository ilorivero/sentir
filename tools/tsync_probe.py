#!/usr/bin/env python3
"""Mede a qualidade do TSYNC de um dispositivo (etapa E1).

  python tsync_probe.py meower 192.168.50.11 5000        # Meower real (porta de controle)
  python tsync_probe.py meower 127.0.0.1 5000 --board-port 5100   # simulador local
  python tsync_probe.py oasis COM5                        # Monitor Oasis por USB

Mostra RTT (tempo de ida e volta) mediano/p95, perdas e a deriva estimada.
"""
import argparse
import json
import socket
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from sentir.clock import SyncSample, fit_clock  # noqa: E402


def probe_meower(a):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", a.port))
    s.settimeout(0.3)
    dst = (a.target, a.board_port or a.port)
    s.sendto(b"WOOF_WOOF", dst)
    time.sleep(0.2)
    s.sendto(b"ID?", dst)
    out, lost = [], 0
    for seq in range(1, a.n + 1):
        if seq % 20 == 0:
            s.sendto(b"WOOF_WOOF", dst)
        t1 = time.time()
        s.sendto(f"TSYNC {seq}".encode(), dst)
        got = False
        while True:
            try:
                pkt, _ = s.recvfrom(512)
            except socket.timeout:
                break
            t4 = time.time()
            msg = pkt.decode(errors="replace").split()
            if msg[:1] == ["ID"]:
                print("ID:", " ".join(msg[1:]))
            if len(msg) == 4 and msg[0] == "TSYNC" and int(msg[1]) == seq:
                out.append(SyncSample(t1, int(msg[2]) * 8e-6, int(msg[3]) * 8e-6, t4))
                got = True
                break
        lost += not got
        time.sleep(a.interval)
    return out, lost


def probe_oasis(a):
    """Protocolo do monitor_oasis: {"cmd":"ping","id":N} -> {"pong":N,"pt":<us>[,"t2":<us>]}.

    Com o firmware SENTIR (Oasis_SENTIR) ha t2 (chegada) e pt=t3 (resposta) em 64 bits; com o
    firmware original so pt (micros() de 32 bits) e o calculo usa t2 = t3 = pt.
    """
    import serial
    ser = serial.serial_for_url(a.target, baudrate=115200, timeout=0.3)
    ser.write(b"ID?\n")
    out, lost = [], 0
    buf = b""
    for seq in range(1, a.n + 1):
        t1 = time.time()
        ser.write(json.dumps({"cmd": "ping", "id": seq}).encode() + b"\n")
        got = False
        t_end = time.time() + 0.3
        while time.time() < t_end and not got:
            buf += ser.read(max(1, ser.in_waiting))
            t4 = time.time()
            *lines, buf = buf.split(b"\n")
            for ln in lines:
                try:
                    m = json.loads(ln)
                except json.JSONDecodeError:
                    continue
                if "hello" in m:
                    print("hello:", m)
                if m.get("pong") == seq:
                    t3 = m["pt"] * 1e-6
                    t2 = m.get("t2", m["pt"]) * 1e-6
                    out.append(SyncSample(t1, t2, t3, t4))
                    got = True
        lost += not got
        time.sleep(a.interval)
    return out, lost


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("kind", choices=["meower", "oasis"])
    p.add_argument("target")
    p.add_argument("port", type=int, nargs="?", default=5000)
    p.add_argument("--board-port", type=int, default=0)
    p.add_argument("-n", type=int, default=100)
    p.add_argument("--interval", type=float, default=0.1)
    a = p.parse_args()
    samples, lost = (probe_meower if a.kind == "meower" else probe_oasis)(a)
    if not samples:
        print("Nenhuma resposta TSYNC. Firmware sem o patch SENTIR?")
        return 1
    rtt = sorted(s.rtt * 1e3 for s in samples)
    fit = fit_clock(samples, min_span_for_drift_s=5)
    print(f"respostas {len(samples)}/{a.n}  perdidas {lost}")
    print(f"RTT ms: min {rtt[0]:.2f}  mediana {statistics.median(rtt):.2f}  "
          f"p95 {rtt[int(0.95 * (len(rtt) - 1))]:.2f}  max {rtt[-1]:.2f}")
    print(f"incerteza estimada {fit.uncertainty_ms:.2f} ms   deriva {fit.drift_ppm:+.1f} ppm "
          f"(confiavel so com >= 20 s de medida)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
