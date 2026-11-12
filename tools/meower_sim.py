#!/usr/bin/env python3
"""Emulador da placa Meower (firmware + patch SENTIR TSYNC) para desenvolvimento sem hardware.

Implementa o mesmo protocolo UDP do firmware real:
  - beacon "MEOW_MEOW" em broadcast na porta de controle ate receber "WOOF_WOOF"
  - comandos sys/usr (start_cnt, stop_cnt, set_sampling_freq, gain, ...) -> "OK: ..."
  - "TSYNC <seq>" -> "TSYNC <seq> <t2_ticks> <t3_ticks>"   (desligue com --no-tsync)
  - "ID?" -> "ID <mac> SENTIR-TSYNC/1"
  - dados: datagramas de N quadros de 52 bytes + bateria float32

O relogio da placa e simulado com offset e deriva (ppm) para testar a sincronizacao.
O canal --photodiode-ch recebe um pulso quadrado (simula o fotodiodo da tela) cujo
instante real (relogio do host) e gravado em --truth-csv para validar a latencia.

Exemplo (duas placas no mesmo PC):
  python meower_sim.py --ctrl-port 5000 --data-port 5001 --drift-ppm 25
  python meower_sim.py --ctrl-port 5010 --data-port 5011 --drift-ppm -18 --mac 02:00:00:00:00:02
"""
import argparse
import math
import random
import socket
import struct
import threading
import time

LSB_UV = 4.5 / 8388608.0 * 1e6


class Clock:
    """Relogio do ESP32: ticks de 8 us com offset e deriva em relacao ao host."""

    def __init__(self, offset_s: float, drift_ppm: float):
        self.t0_host = time.time()
        self.offset_s = offset_s
        self.k = 1.0 + drift_ppm * 1e-6

    def ticks(self, host_t: float | None = None) -> int:
        if host_t is None:
            host_t = time.time()
        dev_s = self.offset_s + (host_t - self.t0_host) * self.k
        return int(dev_s / 8e-6)


class MeowerSim:
    def __init__(self, a):
        self.a = a
        self.clock = Clock(a.offset_s, a.drift_ppm)
        self.fs = a.fs
        self.gain = 1.0
        self.streaming = False
        self.peer = None
        self.ctrl = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.ctrl.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.ctrl.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        # o firmware escuta na mesma porta de controle; o simulador usa ctrl_port+100
        # localmente para nao colidir com o PC quando ambos estao na mesma maquina
        self.ctrl.bind(("0.0.0.0", a.listen_port or a.ctrl_port + 100))
        self.data = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.truth = open(a.truth_csv, "w") if a.truth_csv else None
        if self.truth:
            self.truth.write("host_time,event\n")

    # ------------------------------------------------------------------ control
    def beacon_loop(self):
        while True:
            if self.peer is None:
                for dst in self.a.beacon_targets:
                    self.ctrl.sendto(b"MEOW_MEOW", (dst, self.a.ctrl_port))
            time.sleep(1.0)

    def ctrl_loop(self):
        while True:
            pkt, addr = self.ctrl.recvfrom(1500)
            t2 = self.clock.ticks()
            if self.a.wifi_jitter_ms:
                time.sleep(random.expovariate(1.0 / (self.a.wifi_jitter_ms / 1000.0)))
            msg = pkt.decode(errors="replace").strip()
            if msg == "WOOF_WOOF":
                if self.peer is None:
                    print(f"[sim] PC descoberto em {addr}")
                self.peer = addr
                continue
            if self.peer is None:
                continue
            if msg.startswith("TSYNC "):
                if self.a.no_tsync:
                    reply = f"ERR: unknown family '{msg.split()[0]}'"
                else:
                    seq = msg.split()[1]
                    reply = f"TSYNC {seq} {t2} {self.clock.ticks()}"
            elif msg == "ID?":
                reply = f"ID {self.a.mac} SENTIR-TSYNC/1 ads={self.a.ads} fake=1 fw=sim"
            else:
                reply = self.handle_cmd(msg)
            if reply:
                if self.a.wifi_jitter_ms:
                    time.sleep(random.expovariate(1.0 / (self.a.wifi_jitter_ms / 1000.0)))
                self.ctrl.sendto(reply.encode(), addr)

    def handle_cmd(self, msg: str) -> str | None:
        parts = msg.split()
        if len(parts) < 2:
            return "ERR: unknown"
        fam, cmd = parts[0].lower(), parts[1].lower()
        if fam == "sys" and cmd == "start_cnt":
            self.streaming = True
            return None
        if fam == "sys" and cmd == "stop_cnt":
            self.streaming = False
            return None
        if fam == "usr":
            self.streaming = False  # como no firmware real
            if cmd == "set_sampling_freq" and len(parts) > 2:
                fs = int(parts[2])
                if fs not in (250, 500, 1000, 2000, 4000):
                    return "ERR: invalid sampling freq"
                self.fs = fs
                return f"OK: sampling freq set to {fs}"
            if cmd == "gain" and len(parts) > 3:
                self.gain = float(parts[3])
                return f"OK: gain {parts[2]} {parts[3]}"
        return f"OK: {' '.join(parts[:2])}"

    # --------------------------------------------------------------------- data
    def frames_per_packet(self) -> int:
        return max(1, min(28, self.fs // 50))

    def data_loop(self):
        n = 0
        n0 = 0
        start_host = None
        start_fs = self.fs
        rng = random.Random(1)
        next_t = time.perf_counter()
        pd_period = self.a.photodiode_period_s
        while True:
            if not self.streaming or self.peer is None:
                time.sleep(0.01)
                next_t = time.perf_counter()
                start_host = None
                continue
            fpp = self.frames_per_packet()
            dt = 1.0 / self.fs
            buf = bytearray()
            if start_host is None or self.fs != start_fs:
                # o relogio do ADC define o instante de cada amostra (como no ADS1299)
                start_host, start_fs, n0 = time.time() - (fpp - 1) * dt, self.fs, n
            for i in range(fpp):
                host_t = start_host + (n - n0) * dt
                t = n / self.fs
                phase = (host_t % pd_period) < (pd_period / 2)
                for ch in range(16):
                    if self.a.ads == 1 and ch >= 8:
                        # placa de 8 canais: slots 9-15 zerados, slot 16 = status do ADS1299
                        # (cabecalho 1100, lead-off 0, GPIO1 = fotodiodo)
                        word = (0xC00000 | (1 if phase else 0)) if ch == 15 else 0
                        buf += word.to_bytes(3, "big")
                        continue
                    if self.a.ads == 2 and ch == self.a.photodiode_ch:
                        uv = 200000.0 if phase else 0.0
                    else:
                        uv = (20 * math.sin(2 * math.pi * 10 * t + ch)  # alfa 10 Hz
                              + 5 * math.sin(2 * math.pi * 60 * t)      # rede eletrica
                              + rng.gauss(0, 3))
                    raw = int(round(uv * self.gain / LSB_UV))
                    raw = max(-8388608, min(8388607, raw))
                    buf += (raw & 0xFFFFFF).to_bytes(3, "big")
                buf += struct.pack("<I", self.clock.ticks(host_t) & 0xFFFFFFFF)
                n += 1
            buf += struct.pack("<f", 3.95)
            if rng.random() >= self.a.loss:
                self.data.sendto(bytes(buf), (self.peer[0], self.a.data_port))
            next_t += fpp * dt
            time.sleep(max(0.0, next_t - time.perf_counter()))

    def run(self):
        for target in (self.beacon_loop, self.ctrl_loop, self.data_loop):
            threading.Thread(target=target, daemon=True).start()
        print(f"[sim] Meower simulada: ctrl {self.a.ctrl_port} data {self.a.data_port} "
              f"drift {self.a.drift_ppm} ppm tsync={'off' if self.a.no_tsync else 'on'}")
        while True:
            time.sleep(1)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ctrl-port", type=int, default=5000)
    p.add_argument("--data-port", type=int, default=5001)
    p.add_argument("--listen-port", type=int, default=0, help="porta local do simulador (padrao ctrl+100)")
    p.add_argument("--beacon-targets", nargs="+", default=["127.0.0.1"])
    p.add_argument("--fs", type=int, default=1000)
    p.add_argument("--offset-s", type=float, default=1234.5, help="tempo de boot simulado")
    p.add_argument("--drift-ppm", type=float, default=20.0)
    p.add_argument("--wifi-jitter-ms", type=float, default=1.5)
    p.add_argument("--loss", type=float, default=0.0, help="fracao de datagramas perdidos")
    p.add_argument("--no-tsync", action="store_true", help="simula firmware sem o patch")
    p.add_argument("--mac", default="02:00:00:00:00:01")
    p.add_argument("--ads", type=int, choices=[1, 2], default=1,
                   help="1 = placa de 8 canais (fotodiodo no GPIO1 do status); 2 = 16 canais")
    p.add_argument("--photodiode-ch", type=int, default=15, help="so com --ads 2: canal analogico")
    p.add_argument("--photodiode-period-s", type=float, default=2.0)
    p.add_argument("--truth-csv", default="")
    MeowerSim(p.parse_args()).run()


if __name__ == "__main__":
    main()
