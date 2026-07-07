from __future__ import annotations

import statistics

from .models import QualityResult, QualityStatus, SourceValue


def consensus(
    name: str,
    sources: list[SourceValue],
    relative_tolerance: float,
    absolute_tolerance: float = 0.0,
) -> QualityResult:
    available = [item for item in sources if item.value is not None]
    failed = [item for item in sources if item.value is None]

    if not available:
        return QualityResult(
            name=name,
            status=QualityStatus.MISSING,
            value=None,
            confidence=0.0,
            sources=sources,
            message=f"{name} 未获取到可用数据。",
        )

    values = [item.value for item in available if item.value is not None]
    center = statistics.median(values)

    if len(available) == 1:
        return QualityResult(
            name=name,
            status=QualityStatus.WARN,
            value=center,
            confidence=0.7,
            sources=sources,
            message=f"{name} 只有 1 个数据来源可用，可信度降低。",
        )

    max_gap = max(abs(value - center) for value in values)
    allowed_gap = max(abs(center) * relative_tolerance, absolute_tolerance)
    if max_gap > allowed_gap:
        return QualityResult(
            name=name,
            status=QualityStatus.CONFLICT,
            value=None,
            confidence=0.0,
            sources=sources,
            message=f"{name} 多来源差异过大，今日不参与指数计算。",
        )

    message = f"{name} 已通过 {len(available)} 个来源交叉验证。"
    if failed:
        message += f" {len(failed)} 个来源异常。"
    return QualityResult(
        name=name,
        status=QualityStatus.OK,
        value=statistics.fmean(values),
        confidence=1.0,
        sources=sources,
        message=message,
    )
