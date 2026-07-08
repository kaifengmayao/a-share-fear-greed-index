from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any


class QualityStatus(str, Enum):
    OK = "OK"
    WARN = "WARN"
    STALE = "STALE"
    CONFLICT = "CONFLICT"
    MISSING = "MISSING"


@dataclass(frozen=True)
class SourceValue:
    source: str
    value: float | None
    trade_date: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass(frozen=True)
class QualityResult:
    name: str
    status: QualityStatus
    value: float | None
    confidence: float
    sources: list[SourceValue]
    message: str


@dataclass(frozen=True)
class Quote:
    source: str
    name: str
    price: float
    previous_close: float | None
    pct_change: float | None
    amount: float | None
    trade_date: str | None


@dataclass(frozen=True)
class KLine:
    trade_date: str
    open: float
    close: float
    high: float
    low: float
    volume: float
    amount: float


@dataclass(frozen=True)
class SectorSnapshot:
    code: str
    name: str
    pct_change: float
    amount: float | None
    main_net_inflow: float | None = None
    main_net_inflow_ratio: float | None = None
    up: int | None = None
    down: int | None = None
    flat: int | None = None
    source: str | None = None


@dataclass(frozen=True)
class MarketBreadth:
    source: str
    total: int
    up: int
    down: int
    flat: int
    limit_up: int
    limit_down: int
    total_amount: float
    first_limit_up: int | None = None
    second_limit_up: int | None = None
    third_or_more_limit_up: int | None = None
    consecutive_limit_up: int | None = None
    highest_consecutive_limit_up: int | None = None
    limit_up_pool_source: str | None = None
    limit_up_pool_error: str | None = None
    market_parts: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ComponentScore:
    key: str
    name: str
    score: float
    weight: float
    status: QualityStatus
    confidence: float
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FactorContribution:
    key: str
    name: str
    score: float
    raw_weight: float
    confidence: float
    effective_weight: float
    contribution: float
    impact_vs_neutral: float
    status: QualityStatus
    message: str


@dataclass(frozen=True)
class ScoreAdjustment:
    name: str
    before: float
    after: float
    impact: float
    condition: str
    message: str


@dataclass(frozen=True)
class IndexAllocationScore:
    rank: int
    name: str
    code: str
    secid: str
    score: float
    signal: str
    expected_20d_return: float
    up_probability: float
    momentum_20d: float
    momentum_60d: float
    trend_score: float
    volume_ratio_5_20: float | None
    volatility_20d: float
    max_drawdown_60d: float
    reason: str
    warning: str | None = None


@dataclass(frozen=True)
class AfgiResult:
    run_date: date
    score: float | None
    label: str
    formal: bool
    suggested_position: str
    outlook: dict[str, float]
    components: list[ComponentScore]
    warnings: list[str]
    institution_view: list[str]
    risk_tips: list[str]
    emotion_map: dict[str, Any]
    raw_score: float | None = None
    factor_contributions: list[FactorContribution] = field(default_factory=list)
    score_adjustments: list[ScoreAdjustment] = field(default_factory=list)
    index_allocation: list[IndexAllocationScore] = field(default_factory=list)
