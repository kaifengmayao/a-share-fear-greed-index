from __future__ import annotations

import math
import statistics

from .models import (
    AfgiResult,
    ComponentScore,
    FactorContribution,
    IndexAllocationScore,
    KLine,
    MarketBreadth,
    QualityStatus,
    Quote,
    ScoreAdjustment,
    SectorSnapshot,
    SourceValue,
)
from .providers import DataProviders, INDEX_ALLOCATION_UNIVERSE, collect_attempts
from .quality import consensus
from .utils import clamp, mean, pct_to_score, today_cn


WEIGHTS = {
    "trend": 0.20,
    "breadth": 0.18,
    "liquidity": 0.15,
    "institution": 0.20,
    "risk": 0.12,
    "sector": 0.15,
}


def calculate_afgi(providers: DataProviders) -> AfgiResult:
    warnings: list[str] = []
    components: list[ComponentScore] = []

    quote_attempts = collect_attempts(
        [
            ("东方财富", providers.eastmoney_csi300_quote),
            ("新浪财经", providers.sina_csi300_quote),
            ("腾讯财经", providers.tencent_csi300_quote),
        ]
    )
    quotes = [quote for _, quote, _ in quote_attempts if quote is not None]
    price_quality = consensus(
        "沪深300点位",
        [
            SourceValue(quote.source, quote.price, quote.trade_date)
            if quote is not None
            else SourceValue(source_name, None, error=error)
            for source_name, quote, error in quote_attempts
        ],
        relative_tolerance=0.001,
        absolute_tolerance=2.0,
    )
    pct_quality = consensus(
        "沪深300涨跌幅",
        [
            SourceValue(quote.source, quote.pct_change, quote.trade_date)
            if quote is not None
            else SourceValue(source_name, None, error=error)
            for source_name, quote, error in quote_attempts
        ],
        relative_tolerance=0.25,
        absolute_tolerance=0.12,
    )
    for quality in (price_quality, pct_quality):
        if quality.status != QualityStatus.OK:
            warnings.append(quality.message)

    klines = _safe_call(providers.csi300_klines, [])
    latest_kline_date = klines[-1].trade_date if klines else None
    run_date = today_cn()
    if latest_kline_date and latest_kline_date < run_date.isoformat() and run_date.weekday() < 5:
        warnings.append(f"沪深300历史行情最新日期为 {latest_kline_date}，可能不是今日收盘数据。")
    components.append(_trend_component(klines, pct_quality))
    components.append(_liquidity_component(klines))

    breadth = _safe_call(providers.eastmoney_breadth, None)
    components.append(_breadth_component(breadth))

    sectors = _safe_call(providers.eastmoney_sectors, [])
    components.append(_sector_component(sectors))

    etfs = _safe_call(providers.eastmoney_etfs, [])
    future_quote = _safe_call(providers.sina_if_main, None)
    components.append(_institution_component(etfs, future_quote, price_quality))

    components.append(_risk_component(klines))

    for component in components:
        if component.status != QualityStatus.OK:
            warnings.append(component.message)

    available = [
        c for c in components if c.status not in (QualityStatus.MISSING, QualityStatus.CONFLICT)
    ]
    available_weight = sum(c.weight * c.confidence for c in available)
    formal = available_weight >= 0.70
    score = None
    raw_score = None
    if available_weight > 0:
        raw_score = sum(c.score * c.weight * c.confidence for c in available) / available_weight
        raw_score = round(clamp(raw_score), 1)
        score = raw_score

    score, score_adjustments = apply_score_adjustments(score, breadth, components)
    if score_adjustments:
        warnings.extend([item.message for item in score_adjustments])

    label = classify_score(score)
    emotion_map = build_emotion_map(sectors)
    outlook = build_outlook(score, components)
    institution_view = build_institution_view(etfs, future_quote, price_quality)
    risk_tips = build_risk_tips(score, components, emotion_map, formal)
    factor_contributions = build_factor_contributions(components)
    index_allocation = build_index_allocation(providers)

    return AfgiResult(
        run_date=run_date,
        score=score,
        raw_score=raw_score,
        label=label,
        formal=formal,
        suggested_position=suggest_position(score),
        outlook=outlook,
        components=components,
        warnings=_dedupe(warnings),
        institution_view=institution_view,
        risk_tips=risk_tips,
        emotion_map=emotion_map,
        factor_contributions=factor_contributions,
        score_adjustments=score_adjustments,
        index_allocation=index_allocation,
    )


def classify_score(score: float | None) -> str:
    if score is None:
        return "无法计算"
    if score < 10:
        return "极度恐惧"
    if score < 30:
        return "恐惧"
    if score < 70:
        return "中立"
    if score < 90:
        return "贪婪"
    return "极度贪婪"


def suggest_position(score: float | None) -> str:
    if score is None:
        return "暂停新增仓位，等待数据恢复"
    if score < 10:
        return "0%-20%"
    if score < 30:
        return "20%-40%"
    if score < 70:
        return "40%-60%"
    if score < 90:
        return "60%-80%"
    return "50%-65%，避免追高"


def build_outlook(score: float | None, components: list[ComponentScore]) -> dict[str, float]:
    if score is None:
        return {"up": 33.0, "flat": 34.0, "down": 33.0}
    breadth = _component_score(components, "breadth", 50)
    trend = _component_score(components, "trend", 50)
    institution = _component_score(components, "institution", 50)
    edge = (score - 50) * 0.35 + (trend - 50) * 0.25 + (breadth - 50) * 0.2 + (
        institution - 50
    ) * 0.2
    up = clamp(34 + edge * 0.35, 12, 68)
    down = clamp(34 - edge * 0.32, 12, 68)
    flat = clamp(100 - up - down, 18, 55)
    total = up + flat + down
    return {
        "up": round(up / total * 100, 1),
        "flat": round(flat / total * 100, 1),
        "down": round(down / total * 100, 1),
    }


def apply_score_adjustments(
    score: float | None, breadth: MarketBreadth | None, components: list[ComponentScore]
) -> tuple[float | None, list[ScoreAdjustment]]:
    if score is None:
        return score, []
    if not breadth or breadth.total <= 0:
        trend = _component_score(components, "trend", 50)
        institution = _component_score(components, "institution", 50)
        risk = _component_score(components, "risk", 50)
        cap = 13.5 if institution < 15 and trend < 45 and risk < 40 else 18.0
        if score <= cap:
            return score, []
        adjusted = round(cap, 1)
        message = (
            "市场宽度核心数据缺失，最终指数保守封顶在恐惧区，"
            f"从 {score:.1f} 下调至 {adjusted:.1f}。"
        )
        condition = "市场宽度数据缺失"
        if cap < 18.0:
            condition += f"，且机构/趋势/风险同步偏弱（机构 {institution:.1f}，趋势 {trend:.1f}，风险 {risk:.1f}）"
        return adjusted, [
            ScoreAdjustment(
                name="市场宽度缺失保守校准",
                before=round(score, 1),
                after=adjusted,
                impact=round(adjusted - score, 1),
                condition=condition,
                message=message,
            )
        ]

    down_ratio = breadth.down / breadth.total
    up_ratio = breadth.up / breadth.total
    trend = _component_score(components, "trend", 50)
    institution = _component_score(components, "institution", 50)
    sector_details = _component_details(components, "sector")
    sector_up_ratio = sector_details.get("sector_up_ratio")
    fund_positive_ratio = sector_details.get("fund_positive_ratio")
    if (
        down_ratio >= 0.65
        and up_ratio <= 0.32
        and _lte(sector_up_ratio, 0.30)
        and _lte(fund_positive_ratio, 0.35)
        and institution <= 20
        and trend <= 40
    ):
        panic_cap = clamp(
            2
            + up_ratio * 14
            + float(sector_up_ratio) * 5
            + float(fund_positive_ratio) * 3,
            6,
            12,
        )
        if score > panic_cap:
            adjusted = round(panic_cap, 1)
            condition = (
                f"下跌股票占比 {down_ratio:.1%}，板块上涨占比 {float(sector_up_ratio):.1%}，"
                f"主力资金为正板块占比 {float(fund_positive_ratio):.1%}，"
                f"机构 {institution:.1f}，趋势 {trend:.1f}"
            )
            message = (
                f"扩散式恐慌校准：{condition}，个股、板块、资金与机构态度同步偏弱，"
                f"最终指数从 {score:.1f} 下调至 {adjusted:.1f}。"
            )
            return adjusted, [
                ScoreAdjustment(
                    name="扩散式恐慌校准",
                    before=round(score, 1),
                    after=adjusted,
                    impact=round(adjusted - score, 1),
                    condition=condition,
                    message=message,
                )
            ]

    cap = None
    if down_ratio >= 0.80:
        cap = clamp(8 + up_ratio * 45, 10, 18)
    elif down_ratio >= 0.75:
        cap = 22.0
    elif down_ratio >= 0.70:
        cap = 26.0

    if cap is None or score <= cap:
        return score, []

    adjusted = round(cap, 1)
    condition = f"下跌股票占比 {down_ratio:.1%}（{breadth.down}/{breadth.total}）"
    message = (
        f"极端普跌压力校准：{condition}，市场宽度进入极端恐惧区，"
        f"最终指数从 {score:.1f} 下调至 {adjusted:.1f}。"
    )
    return adjusted, [
        ScoreAdjustment(
            name="极端普跌压力校准",
            before=round(score, 1),
            after=adjusted,
            impact=round(adjusted - score, 1),
            condition=condition,
            message=message,
        )
    ]


def build_factor_contributions(components: list[ComponentScore]) -> list[FactorContribution]:
    available = [
        c for c in components if c.status not in (QualityStatus.MISSING, QualityStatus.CONFLICT)
    ]
    denominator = sum(c.weight * c.confidence for c in available)
    result: list[FactorContribution] = []
    for component in components:
        usable = component.status not in (QualityStatus.MISSING, QualityStatus.CONFLICT)
        raw_effective = component.weight * component.confidence if usable else 0.0
        effective_weight = raw_effective / denominator if denominator else 0.0
        contribution = component.score * effective_weight
        impact = (component.score - 50.0) * effective_weight
        result.append(
            FactorContribution(
                key=component.key,
                name=component.name,
                score=round(component.score, 1),
                raw_weight=round(component.weight, 4),
                confidence=round(component.confidence, 4),
                effective_weight=round(effective_weight, 4),
                contribution=round(contribution, 2),
                impact_vs_neutral=round(impact, 2),
                status=component.status,
                message=component.message,
            )
        )
    return result


def build_index_allocation(providers: DataProviders) -> list[IndexAllocationScore]:
    scores: list[IndexAllocationScore] = []
    for name, code, secid in INDEX_ALLOCATION_UNIVERSE:
        klines = _safe_call(lambda secid=secid: providers.index_klines(secid, limit=120), [])
        scores.append(_index_allocation_score(name, code, secid, klines))

    ranked = sorted(scores, key=lambda item: item.score, reverse=True)
    return [
        IndexAllocationScore(
            rank=index,
            name=item.name,
            code=item.code,
            secid=item.secid,
            score=item.score,
            signal=item.signal,
            expected_20d_return=item.expected_20d_return,
            up_probability=item.up_probability,
            momentum_20d=item.momentum_20d,
            momentum_60d=item.momentum_60d,
            trend_score=item.trend_score,
            volume_ratio_5_20=item.volume_ratio_5_20,
            volatility_20d=item.volatility_20d,
            max_drawdown_60d=item.max_drawdown_60d,
            reason=item.reason,
            warning=item.warning,
        )
        for index, item in enumerate(ranked, start=1)
    ]


def _index_allocation_score(
    name: str, code: str, secid: str, klines: list[KLine]
) -> IndexAllocationScore:
    if len(klines) < 60:
        return IndexAllocationScore(
            rank=0,
            name=name,
            code=code,
            secid=secid,
            score=0.0,
            signal="数据不足",
            expected_20d_return=0.0,
            up_probability=0.0,
            momentum_20d=0.0,
            momentum_60d=0.0,
            trend_score=0.0,
            volume_ratio_5_20=None,
            volatility_20d=0.0,
            max_drawdown_60d=0.0,
            reason="历史K线不足，暂不参与配置排序。",
            warning="历史K线不足60个交易日。",
        )

    closes = [item.close for item in klines]
    amounts = [item.amount for item in klines]
    close = closes[-1]
    ma20 = statistics.fmean(closes[-20:])
    ma60 = statistics.fmean(closes[-60:])
    momentum_20d = (close / closes[-20] - 1) * 100
    momentum_60d = (close / closes[-60] - 1) * 100
    trend_gap = (ma20 / ma60 - 1) * 100 if ma60 else 0.0
    trend_score = clamp(50 + trend_gap * 8 + momentum_20d * 2.2)
    returns = [(closes[i] / closes[i - 1] - 1) * 100 for i in range(1, len(closes))]
    volatility_20d = statistics.pstdev(returns[-20:]) if len(returns) >= 20 else 0.0
    amount_5 = statistics.fmean(amounts[-5:]) if len(amounts) >= 5 else 0.0
    amount_20 = statistics.fmean(amounts[-20:]) if len(amounts) >= 20 else 0.0
    volume_ratio = amount_5 / amount_20 if amount_20 else None
    high_60 = max(closes[-60:])
    max_drawdown_60d = (close / high_60 - 1) * 100 if high_60 else 0.0

    volume_boost = math.log(max(volume_ratio or 1.0, 0.2)) * 10
    raw_score = (
        50
        + momentum_20d * 1.8
        + momentum_60d * 0.7
        + trend_gap * 4.0
        + volume_boost
        - volatility_20d * 3.8
        + max_drawdown_60d * 0.65
    )
    score = round(clamp(raw_score), 1)
    expected_20d_return = clamp(
        momentum_20d * 0.35
        + trend_gap * 0.55
        + ((volume_ratio or 1.0) - 1.0) * 2.0
        - volatility_20d * 0.18,
        -8.0,
        8.0,
    )
    up_probability = clamp(50 + expected_20d_return * 4.0 + (score - 50) * 0.25, 20, 80)
    signal = _allocation_signal(score)
    reason = (
        f"20日动量 {momentum_20d:.2f}%，60日动量 {momentum_60d:.2f}%，"
        f"5/20日成交额比 {volume_ratio:.2f}，20日波动 {volatility_20d:.2f}%。"
        if volume_ratio is not None
        else f"20日动量 {momentum_20d:.2f}%，60日动量 {momentum_60d:.2f}%，成交额缺失。"
    )
    return IndexAllocationScore(
        rank=0,
        name=name,
        code=code,
        secid=secid,
        score=score,
        signal=signal,
        expected_20d_return=round(expected_20d_return, 2),
        up_probability=round(up_probability, 1),
        momentum_20d=round(momentum_20d, 2),
        momentum_60d=round(momentum_60d, 2),
        trend_score=round(trend_score, 1),
        volume_ratio_5_20=round(volume_ratio, 3) if volume_ratio is not None else None,
        volatility_20d=round(volatility_20d, 3),
        max_drawdown_60d=round(max_drawdown_60d, 2),
        reason=reason,
    )


def _allocation_signal(score: float) -> str:
    if score >= 68:
        return "优先配置"
    if score >= 56:
        return "适度配置"
    if score >= 45:
        return "观察等待"
    return "低配回避"


def build_institution_view(
    etfs: list[Quote], future_quote: Quote | None, price_quality
) -> list[str]:
    notes: list[str] = []
    etf_pct = mean([q.pct_change for q in etfs if q.pct_change is not None])
    if etf_pct is None:
        notes.append("ETF资金：未获取到可用宽基ETF行情。")
    elif etf_pct > 0.6:
        notes.append("ETF资金：宽基ETF整体走强，机构/被动资金态度偏积极。")
    elif etf_pct < -0.6:
        notes.append("ETF资金：宽基ETF整体走弱，机构/被动资金偏谨慎。")
    else:
        notes.append("ETF资金：宽基ETF波动不大，机构态度中性。")

    if future_quote and price_quality.value:
        basis = future_quote.price - price_quality.value
        if basis > price_quality.value * 0.002:
            notes.append("股指期货：IF主连相对沪深300升水，期货端偏乐观。")
        elif basis < -price_quality.value * 0.002:
            notes.append("股指期货：IF主连相对沪深300贴水，期货端偏谨慎。")
        else:
            notes.append("股指期货：IF主连基差接近中性。")
    else:
        notes.append("股指期货：期货数据源异常或不足，已降低机构态度权重。")

    notes.append("融资融券：1.0版本暂以接口可用性为前提，若未接入官方两市数据会在质量提示中说明。")
    return notes


def build_risk_tips(
    score: float | None,
    components: list[ComponentScore],
    emotion_map: dict,
    formal: bool,
) -> list[str]:
    tips: list[str] = []
    if not formal:
        tips.append("今日可用数据权重不足70%，指数为试算值，不建议作为正式仓位信号。")
    if score is not None and score >= 90:
        tips.append("情绪进入极度贪婪区，防止追高和主线拥挤回撤。")
    elif score is not None and score <= 10:
        tips.append("情绪进入极度恐惧区，短线波动大，左侧布局应控制节奏。")

    breadth = _component_score(components, "breadth", 50)
    trend = _component_score(components, "trend", 50)
    if trend > 65 and breadth < 45:
        tips.append("指数强于个股宽度，可能是权重股拉动，注意结构分化。")
    if emotion_map.get("concentration", 0) > 0.55:
        tips.append("板块热度集中度偏高，主线退潮时回撤可能放大。")
    if not tips:
        tips.append("暂无明显极端风险，继续观察资金扩散和期货基差变化。")
    return tips


def build_emotion_map(sectors: list[SectorSnapshot]) -> dict:
    max_abs_flow = max((abs(item.main_net_inflow or 0) for item in sectors), default=0) or 1
    ranked = sorted(
        sectors,
        key=lambda item: _sector_strength_score(item, max_abs_flow),
        reverse=True,
    )
    top = ranked[:8]
    bottom = ranked[-8:][::-1]
    abs_sum = sum(abs(item.pct_change) for item in ranked[:20]) or 1
    concentration = sum(abs(item.pct_change) for item in ranked[:5]) / abs_sum
    return {
        "strong": [
            _sector_map_item(item, max_abs_flow)
            for item in top
        ],
        "weak": [
            _sector_map_item(item, max_abs_flow)
            for item in bottom
        ],
        "concentration": round(concentration, 3),
    }


def _trend_component(klines: list[KLine], pct_quality) -> ComponentScore:
    if len(klines) < 60:
        return _missing("trend", "沪深300趋势", WEIGHTS["trend"], "沪深300历史行情不足，趋势模块缺失。")
    closes = [k.close for k in klines]
    close = closes[-1]
    ma20 = statistics.fmean(closes[-20:])
    ma60 = statistics.fmean(closes[-60:])
    pct20 = (close / closes[-20] - 1) * 100
    score = 50 + (close / ma20 - 1) * 900 + (ma20 / ma60 - 1) * 700 + pct20 * 2.2
    status = QualityStatus.WARN if pct_quality.status != QualityStatus.OK else QualityStatus.OK
    confidence = 0.8 if status == QualityStatus.WARN else 1.0
    return ComponentScore(
        key="trend",
        name="沪深300趋势",
        score=round(clamp(score), 1),
        weight=WEIGHTS["trend"],
        status=status,
        confidence=confidence,
        message="沪深300趋势仅部分来源通过验证，已降低权重。" if status == QualityStatus.WARN else "趋势数据正常。",
        details={"close": close, "ma20": round(ma20, 2), "ma60": round(ma60, 2), "pct20": round(pct20, 2)},
    )


def _breadth_component(breadth: MarketBreadth | None) -> ComponentScore:
    if not breadth or breadth.total <= 0:
        return _missing("breadth", "市场宽度", WEIGHTS["breadth"], "市场宽度数据未获取到。")
    up_ratio = breadth.up / breadth.total
    down_ratio = breadth.down / breadth.total
    limit_balance = (breadth.limit_up - breadth.limit_down) / max(1, breadth.limit_up + breadth.limit_down)
    limit_up_ratio = breadth.limit_up / max(1, breadth.total)
    limit_down_ratio = breadth.limit_down / max(1, breadth.total)
    consecutive_heat = min((breadth.consecutive_limit_up or 0) / 30, 1.0)
    high_board_heat = min((breadth.third_or_more_limit_up or 0) / 12, 1.0)
    limit_score = (limit_balance + 1) * 10 + consecutive_heat * 8 + high_board_heat * 5
    drawdown_penalty = min(limit_down_ratio * 900, 15)
    score = up_ratio * 67 + limit_score - drawdown_penalty
    message = "市场宽度目前只有东方财富一个来源，可信度降低。"
    if down_ratio >= 0.80:
        message = "全市场下跌占比超过80%，普跌压力极端，市场宽度触发强恐惧信号。"
    elif down_ratio >= 0.70:
        message = "全市场下跌占比超过70%，普跌压力较强，市场宽度显著偏弱。"
    elif breadth.consecutive_limit_up and breadth.consecutive_limit_up >= 20:
        message = "连板家数较多，短线资金活跃，市场宽度偏强但需留意情绪拥挤。"
    elif breadth.limit_down >= max(10, breadth.limit_up):
        message = "跌停压力高于涨停接力，短线情绪偏弱。"
    return ComponentScore(
        key="breadth",
        name="市场宽度",
        score=round(clamp(score), 1),
        weight=WEIGHTS["breadth"],
        status=QualityStatus.WARN,
        confidence=0.7,
        message=message,
        details={
            "total": breadth.total,
            "up": breadth.up,
            "down": breadth.down,
            "flat": breadth.flat,
            "limit_up": breadth.limit_up,
            "limit_down": breadth.limit_down,
            "limit_up_ratio": round(limit_up_ratio, 4),
            "limit_down_ratio": round(limit_down_ratio, 4),
            "first_limit_up": breadth.first_limit_up,
            "second_limit_up": breadth.second_limit_up,
            "third_or_more_limit_up": breadth.third_or_more_limit_up,
            "consecutive_limit_up": breadth.consecutive_limit_up,
            "highest_consecutive_limit_up": breadth.highest_consecutive_limit_up,
            "limit_up_pool_source": breadth.limit_up_pool_source,
            "limit_up_pool_error": breadth.limit_up_pool_error,
            "market_parts": breadth.market_parts,
            "up_ratio": round(up_ratio, 3),
            "down_ratio": round(down_ratio, 3),
        },
    )


def _liquidity_component(klines: list[KLine]) -> ComponentScore:
    if len(klines) < 30:
        return _missing("liquidity", "成交与流动性", WEIGHTS["liquidity"], "历史成交额不足，流动性模块缺失。")
    amounts = [k.amount for k in klines]
    recent = statistics.fmean(amounts[-5:])
    base = statistics.fmean(amounts[-30:])
    ratio = recent / base if base else 1
    score = 50 + math.log(max(ratio, 0.1)) * 55
    return ComponentScore(
        key="liquidity",
        name="成交与流动性",
        score=round(clamp(score), 1),
        weight=WEIGHTS["liquidity"],
        status=QualityStatus.WARN,
        confidence=0.8,
        message="成交额基于东方财富沪深300历史行情，暂无第二来源校验。",
        details={"recent_amount": round(recent, 2), "base_amount": round(base, 2), "ratio": round(ratio, 3)},
    )


def _institution_component(
    etfs: list[Quote], future_quote: Quote | None, price_quality
) -> ComponentScore:
    sub_scores: list[float] = []
    details = {}
    etf_pct = mean([q.pct_change for q in etfs if q.pct_change is not None])
    if etf_pct is not None:
        sub_scores.append(pct_to_score(etf_pct, scale=1.8))
        details["etf_avg_pct"] = round(etf_pct, 3)

    if future_quote and price_quality.value:
        basis_pct = (future_quote.price / price_quality.value - 1) * 100
        sub_scores.append(pct_to_score(basis_pct, scale=0.8))
        details["if_basis_pct"] = round(basis_pct, 3)

    if not sub_scores:
        return _missing("institution", "机构态度", WEIGHTS["institution"], "ETF、股指期货、融资融券均未获取到可用数据。")

    status = QualityStatus.WARN
    confidence = 0.65 if len(sub_scores) == 1 else 0.75
    return ComponentScore(
        key="institution",
        name="机构态度",
        score=round(clamp(statistics.fmean(sub_scores)), 1),
        weight=WEIGHTS["institution"],
        status=status,
        confidence=confidence,
        message="机构态度模块未完成多源全量校验，ETF/期货/融资融券任一缺失都会降低权重。",
        details=details,
    )


def _risk_component(klines: list[KLine]) -> ComponentScore:
    if len(klines) < 30:
        return _missing("risk", "风险波动", WEIGHTS["risk"], "波动率数据不足。")
    closes = [k.close for k in klines]
    returns = [(closes[i] / closes[i - 1] - 1) * 100 for i in range(1, len(closes))]
    vol20 = statistics.pstdev(returns[-20:])
    pct5 = (closes[-1] / closes[-5] - 1) * 100
    score = 62 - vol20 * 12 + pct5 * 3
    return ComponentScore(
        key="risk",
        name="风险波动",
        score=round(clamp(score), 1),
        weight=WEIGHTS["risk"],
        status=QualityStatus.WARN,
        confidence=0.8,
        message="风险波动基于沪深300历史行情计算，暂无第二来源校验。",
        details={"vol20": round(vol20, 3), "pct5": round(pct5, 3)},
    )


def _sector_component(sectors: list[SectorSnapshot]) -> ComponentScore:
    if len(sectors) < 10:
        return _missing("sector", "板块强弱", WEIGHTS["sector"], "行业板块数据不足。")
    max_abs_flow = max((abs(item.main_net_inflow or 0) for item in sectors), default=0) or 1
    ranked = sorted(
        sectors,
        key=lambda item: _sector_strength_score(item, max_abs_flow),
        reverse=True,
    )
    top_mean = statistics.fmean([item.pct_change for item in ranked[:8]])
    bottom_mean = statistics.fmean([item.pct_change for item in ranked[-8:]])
    breadth = sum(1 for item in sectors if item.pct_change > 0) / len(sectors)
    fund_positive_ratio = (
        sum(1 for item in sectors if (item.main_net_inflow or 0) > 0) / len(sectors)
    )
    internal_up_ratios = []
    for item in sectors:
        total = (item.up or 0) + (item.down or 0) + (item.flat or 0)
        if total > 0 and item.up is not None:
            internal_up_ratios.append(item.up / total)
    internal_up_ratio = statistics.fmean(internal_up_ratios) if internal_up_ratios else None
    internal_boost = 0 if internal_up_ratio is None else (internal_up_ratio - 0.5) * 20
    source = sectors[0].source or "未知来源"
    degraded = "降级" in source
    score = (
        50
        + top_mean * 5
        + bottom_mean * 2
        + (breadth - 0.5) * 35
        + (fund_positive_ratio - 0.5) * 18
        + internal_boost
    )
    return ComponentScore(
        key="sector",
        name="板块强弱",
        score=round(clamp(score), 1),
        weight=WEIGHTS["sector"],
        status=QualityStatus.WARN,
        confidence=0.55 if degraded else 0.7,
        message=(
            "板块强弱使用东方财富板块资金流降级数据，板块内部涨跌家数未补齐，已降低权重。"
            if degraded
            else "板块强弱基于东方财富板块资金流与板块指数行情，仍为单平台来源，需结合人工复核。"
        ),
        details={
            "source": source,
            "sector_count": len(sectors),
            "top_mean": round(top_mean, 3),
            "bottom_mean": round(bottom_mean, 3),
            "sector_up_ratio": round(breadth, 3),
            "fund_positive_ratio": round(fund_positive_ratio, 3),
            "internal_up_ratio": None
            if internal_up_ratio is None
            else round(internal_up_ratio, 3),
            "top_by_strength": [
                _sector_map_item(item, max_abs_flow) for item in ranked[:5]
            ],
        },
    )


def _sector_strength_score(item: SectorSnapshot, max_abs_flow: float) -> float:
    flow_score = ((item.main_net_inflow or 0) / max_abs_flow) * 3
    internal_score = 0.0
    total = (item.up or 0) + (item.down or 0) + (item.flat or 0)
    if total > 0 and item.up is not None:
        internal_score = (item.up / total - 0.5) * 4
    return item.pct_change + flow_score + internal_score


def _sector_map_item(item: SectorSnapshot, max_abs_flow: float) -> dict:
    return {
        "name": item.name,
        "code": item.code,
        "pct_change": round(item.pct_change, 2),
        "amount": item.amount,
        "main_net_inflow": item.main_net_inflow,
        "main_net_inflow_ratio": item.main_net_inflow_ratio,
        "up": item.up,
        "down": item.down,
        "flat": item.flat,
        "strength": round(_sector_strength_score(item, max_abs_flow), 3),
    }


def _missing(key: str, name: str, weight: float, message: str) -> ComponentScore:
    return ComponentScore(
        key=key,
        name=name,
        score=50.0,
        weight=weight,
        status=QualityStatus.MISSING,
        confidence=0.0,
        message=message,
    )


def _component_score(components: list[ComponentScore], key: str, default: float) -> float:
    for component in components:
        if component.key == key:
            return component.score
    return default


def _component_details(components: list[ComponentScore], key: str) -> dict:
    for component in components:
        if component.key == key:
            return component.details or {}
    return {}


def _lte(value, threshold: float) -> bool:
    try:
        return float(value) <= threshold
    except (TypeError, ValueError):
        return False


def _safe_call(fn, default):
    try:
        return fn()
    except Exception:
        return default


def _dedupe(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        if item and item not in seen:
            result.append(item)
            seen.add(item)
    return result
