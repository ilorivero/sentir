"""Sincronizacao de relogios (dispositivo -> relogio do host).

Todos os fluxos do SENTIR sao gravados no MESMO eixo de tempo: o relogio UNIX do PC
host (``time.time()``, segundos, float64). Cada dispositivo tem seu proprio relogio
(ESP32 do Meower em ticks de 8 us, ESP32-C3 do Monitor Oasis em us, apresentador
Flutter em us). O modelo aqui estima

    host = host0 + a + b * (dev - dev0)

a partir de trocas estilo NTP (t1 host envia, t2 dispositivo recebe, t3 dispositivo
responde, t4 host recebe). Para cada troca:

    rtt     = (t4 - t1) - (t3 - t2)
    offset  = (t1 + t4)/2 - (t2 + t3)/2

Somente as trocas com menor RTT (menos fila no Wi-Fi/USB) entram na regressao, o que
torna o estimador robusto a picos de latencia. ``b`` captura a deriva do cristal
(tipicamente 10-40 ppm: 36-144 ms por hora se nao for corrigida).

O mesmo modulo serve para o ajuste offline: os pares TSYNC sao gravados em
``clock_<dispositivo>.parquet`` e podem ser re-ajustados sobre a sessao inteira.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class SyncSample:
    t1: float  # host, envio (s)
    t2: float  # dispositivo, recepcao (s)
    t3: float  # dispositivo, resposta (s)
    t4: float  # host, recepcao (s)

    @property
    def rtt(self) -> float:
        return (self.t4 - self.t1) - (self.t3 - self.t2)

    @property
    def host_mid(self) -> float:
        return 0.5 * (self.t1 + self.t4)

    @property
    def dev_mid(self) -> float:
        return 0.5 * (self.t2 + self.t3)

    @property
    def offset(self) -> float:
        return self.host_mid - self.dev_mid


@dataclass
class ClockFit:
    host0: float
    dev0: float
    a: float
    b: float
    uncertainty_ms: float
    n_used: int

    def to_host(self, dev):
        return self.host0 + self.a + self.b * (np.asarray(dev, dtype=np.float64) - self.dev0)

    @property
    def drift_ppm(self) -> float:
        """Quanto o relogio do dispositivo adianta (+) ou atrasa (-) em relacao ao host."""
        return (1.0 / self.b - 1.0) * 1e6


@dataclass
class ClockModel:
    """Modelo online com janela deslizante de trocas TSYNC."""

    window: int = 120
    keep_fraction: float = 0.3
    min_span_for_drift_s: float = 20.0
    max_drift_ppm: float = 500.0
    samples: deque = field(default_factory=deque)
    fit: ClockFit | None = None

    def add(self, s: SyncSample) -> ClockFit | None:
        if s.rtt < 0 or s.t4 < s.t1:
            return self.fit  # amostra invalida (relogio do host pulou?)
        self.samples.append(s)
        while len(self.samples) > self.window:
            self.samples.popleft()
        self.fit = fit_clock(list(self.samples), self.keep_fraction,
                             self.min_span_for_drift_s, self.max_drift_ppm)
        return self.fit

    def to_host(self, dev):
        if self.fit is None:
            raise RuntimeError("relogio ainda nao sincronizado")
        return self.fit.to_host(dev)


def fit_clock(samples: list[SyncSample], keep_fraction: float = 0.3,
              min_span_for_drift_s: float = 20.0, max_drift_ppm: float = 500.0) -> ClockFit | None:
    if len(samples) < 3:
        return None
    rtt = np.array([s.rtt for s in samples])
    k = max(3, int(len(samples) * keep_fraction))
    idx = np.argsort(rtt)[:k]
    idx.sort()
    x = np.array([samples[i].dev_mid for i in idx])
    y = np.array([samples[i].host_mid for i in idx])
    dev0, host0 = x[0], y[0]
    xr, yr = x - dev0, y - host0
    span = xr.max() - xr.min()
    if span >= min_span_for_drift_s:
        b, a = np.polyfit(xr, yr, 1)
        if abs(b - 1.0) * 1e6 > max_drift_ppm:
            b = 1.0
            a = float(np.mean(yr - xr))
    else:
        b = 1.0
        a = float(np.mean(yr - xr))
    resid = yr - (a + b * xr)
    unc = 0.5 * float(rtt.min()) * 1e3 + float(np.sqrt(np.mean(resid ** 2))) * 1e3
    return ClockFit(float(host0), float(dev0), float(a), float(b), unc, int(k))


class ArrivalMinEstimator:
    """Fallback sem TSYNC: offset = minimo deslizante de (chegada - tempo do dispositivo).

    O atraso de rede nunca e negativo, entao o minimo aproxima o atraso fixo. Erro tipico
    de alguns ms no Wi-Fi; use apenas quando o firmware nao tiver o patch.
    """

    def __init__(self, window_s: float = 10.0):
        self.window_s = window_s
        self.buf: deque[tuple[float, float]] = deque()

    def update(self, arrival_host: float, dev_time: float) -> float:
        off = arrival_host - dev_time
        self.buf.append((arrival_host, off))
        while self.buf and arrival_host - self.buf[0][0] > self.window_s:
            self.buf.popleft()
        return min(o for _, o in self.buf)


class TickUnwrapper:
    """Desdobra contadores de 32 bits (ticks de 8 us do Meower dao a volta a cada ~9,5 h)."""

    def __init__(self, bits: int = 32):
        self.mod = 1 << bits
        self.half = self.mod >> 1
        self.ref: int | None = None

    def set_reference(self, full_value: int) -> None:
        self.ref = int(full_value)

    def __call__(self, value: int) -> int:
        if self.ref is None:
            self.ref = int(value)
            return self.ref
        low = self.ref % self.mod
        delta = (int(value) - low) % self.mod
        if delta >= self.half:
            delta -= self.mod
        self.ref += delta
        return self.ref


class ContinuousMapper:
    """Converte tempo do dispositivo -> host em tempo real sem saltos.

    Cada novo ajuste do ``ClockModel`` muda levemente a reta; aplicar a reta nova direto
    criaria pequenos saltos (inclusive para tras) entre blocos. Aqui o salto e absorvido
    por uma correcao que decai a no maximo ``max_slew`` s/s (padrao 1000 ppm), como o
    "slew" do NTP: os timestamps ficam continuos e estritamente crescentes.

    O eixo definitivo para analise e o reajuste offline (``sentir.analysis.resync``),
    que usa todos os pares TSYNC da sessao; ``dev_ts`` e sempre gravado para isso.
    """

    def __init__(self, model: ClockModel, max_slew: float = 1e-3, step_threshold_s: float = 0.1):
        self.model = model
        self.max_slew = max_slew
        self.step_threshold_s = step_threshold_s
        self._fit: ClockFit | None = None
        self._corr = 0.0
        self._last_dev: float | None = None

    def __call__(self, dev):
        dev = np.asarray(dev, dtype=np.float64)
        fit = self.model.fit
        if fit is None:
            raise RuntimeError("relogio ainda nao sincronizado")
        if fit is not self._fit:
            if self._fit is not None and self._last_dev is not None:
                old = float(self._fit.to_host(self._last_dev)) + self._corr
                new = float(fit.to_host(self._last_dev))
                self._corr = old - new
                if abs(self._corr) > self.step_threshold_s:
                    self._corr = 0.0  # salto grande (ex. reboot do dispositivo): aceita o degrau
            self._fit = fit
        base = fit.to_host(dev)
        if self._last_dev is None:
            elapsed = np.zeros_like(dev)
        else:
            elapsed = np.maximum(dev - self._last_dev, 0.0)
        budget = self.max_slew * elapsed
        corr = np.sign(self._corr) * np.maximum(abs(self._corr) - budget, 0.0)
        self._corr = float(corr[-1]) if corr.size else self._corr
        self._last_dev = float(dev[-1]) if dev.size else self._last_dev
        return base + corr
