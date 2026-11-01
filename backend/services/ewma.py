"""Pure EWMA utilities (no I/O).

Streaming smoothing is *time-aware*: alpha = 1 - exp(-dt / tau), so irregular
sampling gives the same smoothing as regular sampling. Missing values are never
imputed. Gaps re-seed the state. Outliers are flagged and kept out of the state.
Daily smoothing uses a fixed per-day alpha stretched over multi-day gaps.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return float(default)


@dataclass(frozen=True)
class SignalConfig:
    tau_seconds: float      # smoothing time constant
    min_dev: float          # floor for the robust deviation estimate (signal units)
    lo: float               # physiological/plausible lower bound (reject below)
    hi: float               # plausible upper bound (reject above)


@dataclass(frozen=True)
class EwmaConfig:
    version: int
    heartrate: SignalConfig
    pedometer: SignalConfig
    daily_alpha: float
    max_gap_seconds: float
    outlier_k: float
    outlier_reseed_after: int
    warmup_samples: int
    future_skew_seconds: float


def load_config() -> EwmaConfig:
    return EwmaConfig(
        version=int(_env_float("EWMA_CONFIG_VERSION", 1)),
        heartrate=SignalConfig(_env_float("EWMA_HR_TAU_SECONDS", 60), 2.0, 25, 230),
        pedometer=SignalConfig(_env_float("EWMA_STEPS_TAU_SECONDS", 300), 50.0, 0, 5000),
        daily_alpha=_env_float("EWMA_DAILY_ALPHA", 0.2),
        max_gap_seconds=_env_float("EWMA_MAX_GAP_SECONDS", 900),
        outlier_k=_env_float("EWMA_OUTLIER_K", 4.0),
        outlier_reseed_after=int(_env_float("EWMA_OUTLIER_RESEED_AFTER", 5)),
        warmup_samples=int(_env_float("EWMA_WARMUP_SAMPLES", 5)),
        future_skew_seconds=_env_float("EWMA_FUTURE_SKEW_SECONDS", 300),
    )


def time_aware_alpha(dt_seconds: float, tau_seconds: float) -> float:
    if dt_seconds <= 0 or tau_seconds <= 0:
        return 0.0
    return 1.0 - math.exp(-dt_seconds / tau_seconds)


@dataclass
class EwmaState:
    value: float
    dev: float                 # EWMA of absolute deviation (robust spread)
    last_ts: float             # epoch seconds of the last accepted sample
    n: int = 1
    outlier_run: int = 0

    def to_dict(self) -> dict:
        return {"value": self.value, "dev": self.dev, "last_ts": self.last_ts, "n": self.n,
                "outlier_run": self.outlier_run}

    @staticmethod
    def from_dict(d: dict) -> "EwmaState":
        return EwmaState(float(d["value"]), float(d["dev"]), float(d["last_ts"]), int(d["n"]),
                         int(d.get("outlier_run", 0)))


def step(state: EwmaState | None, x: float, ts: float, sig: SignalConfig, cfg: EwmaConfig):
    """Advance the smoother by one sample. Returns (new_state, smoothed_or_None, flags).

    smoothed is None only for out-of-order samples (the state is left untouched).
    """
    flags: list[str] = []
    if state is None:
        return EwmaState(x, sig.min_dev, ts, 1), x, ["warmup"]
    dt = ts - state.last_ts
    if dt <= 0:
        return state, None, ["out_of_order"]
    if dt > cfg.max_gap_seconds:
        return EwmaState(x, sig.min_dev, ts, 1), x, ["reseeded", "warmup"]

    residual = abs(x - state.value)
    sigma = 1.2533 * max(state.dev, sig.min_dev)          # mean-abs-deviation -> sigma
    if state.n >= cfg.warmup_samples and residual > cfg.outlier_k * sigma:
        run = state.outlier_run + 1
        if run < cfg.outlier_reseed_after:
            # keep the raw value but do not let it move the state
            state.outlier_run = run
            return state, state.value, ["outlier"]
        # sustained shift: accept as the new level instead of ignoring it forever
        return EwmaState(x, sig.min_dev, ts, 1), x, ["level_shift", "warmup"]

    alpha = time_aware_alpha(dt, sig.tau_seconds)
    new_value = state.value + alpha * (x - state.value)
    new_dev = state.dev + alpha * (residual - state.dev)
    n = state.n + 1
    if n < cfg.warmup_samples:
        flags.append("warmup")
    return EwmaState(new_value, new_dev, ts, n, 0), new_value, flags


def ewma_series(values, alpha: float):
    """EWMA over an ordered sequence. ``None`` entries are skipped (never imputed) and stay ``None``."""
    out, current = [], None
    for v in values:
        if v is None:
            out.append(None)
            continue
        current = float(v) if current is None else current + alpha * (float(v) - current)
        out.append(current)
    return out


def daily_ewma(days, values, alpha: float):
    """Day-indexed EWMA; the effective alpha grows over multi-day gaps so stale history decays."""
    out, current, last_day = [], None, None
    for day, v in zip(days, values):
        if v is None:
            out.append(None)
            continue
        if current is None:
            current = float(v)
        else:
            gap = max(1, (day - last_day).days)
            a = 1.0 - (1.0 - alpha) ** gap
            current = current + a * (float(v) - current)
        last_day = day
        out.append(current)
    return out
