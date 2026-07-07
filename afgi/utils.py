from __future__ import annotations

import math
import statistics
from datetime import datetime
from zoneinfo import ZoneInfo


CN_TZ = ZoneInfo("Asia/Shanghai")


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def safe_float(value) -> float | None:
    if value in (None, "", "-", "None"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def pct_to_score(pct: float, scale: float = 2.0) -> float:
    return clamp(50.0 + pct / scale * 50.0)


def mean(values: list[float]) -> float | None:
    clean = [v for v in values if v is not None and math.isfinite(v)]
    if not clean:
        return None
    return statistics.fmean(clean)


def today_cn():
    return datetime.now(CN_TZ).date()
