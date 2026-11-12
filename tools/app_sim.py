#!/usr/bin/env python3
"""Simula o app monitor_oasis (modo Estacao) falando com o agente EEG.

Usa exatamente o protocolo de docs/03-protocolos.md ("App monitor_oasis <-> agente EEG"):
responde TSYNC com o "relogio do app" (DateTime.now em us, aqui com offset/deriva simulados),
abre a sessao, envia as fases confirmadas e fecha a sessao. Serve para testar o agente sem
Flutter e como referencia para a implementacao Dart (integration/monitor_oasis).

As fases de ESTIMULO comecam em multiplos exatos de --period no relogio do host - o mesmo
instante em que o fotodiodo do meower_sim acende - entao a latencia medida deve ser ~0 ms.

  python tools/meower_sim.py --ads 1 --photodiode-period-s 2
  python -m sentir.agent --config config/agent.sim.yaml     (na pasta backend)
  python tools/app_sim.py --stimuli 5
"""
import argparse
import asyncio
import json
import math
import time

import websockets


class AppClock:
    def __init__(self, offset_s: float, drift_ppm: float):
        self.t0 = time.time()
        self.offset = offset_s
        self.k = 1 + drift_ppm * 1e-6

    def us(self, host: float | None = None) -> int:
        host = time.time() if host is None else host
        return int((host + self.offset + (host - self.t0) * (self.k - 1)) * 1e6)


async def run(a) -> dict:
    clock = AppClock(a.offset_s, a.drift_ppm)
    async with websockets.connect(f"ws://{a.agent}/ws/app") as ws:
        statuses: list[dict] = []
        replies: dict[str, dict] = {}

        async def reader():
            async for raw in ws:
                t2 = clock.us()
                m = json.loads(raw)
                if m["type"] == "tsync":
                    await ws.send(json.dumps({"type": "tsync", "seq": m["seq"], "t2": t2, "t3": clock.us()}))
                elif m["type"] == "eeg_status":
                    statuses.append(m)
                elif m["type"] in ("session_started", "session_stopped"):
                    replies[m["type"]] = m

        rt = asyncio.create_task(reader())
        await asyncio.sleep(a.warmup_s)
        await ws.send(json.dumps({"type": "session_start", "station_id": "A", "subject_code": a.subject,
                                  "session_id": 1, "protocol": {"baseline_s": 1, "image_s": 1, "fixation_s": 1}}))
        while "session_started" not in replies:
            await asyncio.sleep(0.05)
        sent = []
        for k in range(a.stimuli):
            onset = math.ceil(time.time() / a.period + 0.3) * a.period   # proximo multiplo do periodo
            await asyncio.sleep(max(0.0, onset - time.time()))
            start_ms = clock.us(onset) / 1000.0
            await ws.send(json.dumps({"type": "phase", "exposure_id": 100 + k, "event_type": "STIMULUS",
                                      "image_name": f"img{k}.jpg", "start_ms": start_ms, "latency_ms": 3}))
            sent.append(onset)
            await asyncio.sleep(a.period / 2)
            fix = time.time()
            await ws.send(json.dumps({"type": "phase", "exposure_id": 200 + k, "event_type": "FIXATION",
                                      "image_name": "FIXATION", "start_ms": clock.us(fix) / 1000.0,
                                      "latency_ms": 2}))
        await asyncio.sleep(1.0)
        await ws.send(json.dumps({"type": "session_stop"}))
        while "session_stopped" not in replies:
            await asyncio.sleep(0.05)
        rt.cancel()
        return {"onsets_host": sent, "last_status": statuses[-1] if statuses else None,
                "stopped": replies["session_stopped"]}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--agent", default="127.0.0.1:8765")
    p.add_argument("--subject", default="A-PARTICIPANTE_1")
    p.add_argument("--stimuli", type=int, default=5)
    p.add_argument("--period", type=float, default=2.0)
    p.add_argument("--offset-s", type=float, default=5.0, help="relogio do app adiantado (s)")
    p.add_argument("--drift-ppm", type=float, default=15.0)
    p.add_argument("--warmup-s", type=float, default=3.0)
    out = asyncio.run(run(p.parse_args()))
    print(json.dumps(out["stopped"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
