from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

from .models import (
    AfgiResult,
    ComponentScore,
    FactorContribution,
    IndexAllocationScore,
    QualityStatus,
)


def render_markdown(result: AfgiResult) -> str:
    score_text = "N/A" if result.score is None else f"{result.score:.1f}"
    title_prefix = "A股恐惧贪婪指数"
    if not result.formal:
        title_prefix += "（试算）"

    lines = [
        f"# {title_prefix}",
        "",
        f"- 日期：{result.run_date.isoformat()}",
        f"- 指数：{score_text} / 100",
        f"- 状态：{result.label}",
        f"- 建议仓位：{result.suggested_position}",
        "",
        "## 明日展望",
        "",
        f"- 上涨概率：{result.outlook['up']:.1f}%",
        f"- 震荡概率：{result.outlook['flat']:.1f}%",
        f"- 下跌概率：{result.outlook['down']:.1f}%",
        "",
        "## 未来20天指数配置雷达",
        "",
    ]
    if result.index_allocation:
        lines.append("| 排名 | 指数 | 配置信号 | 评分 | 20天预期 | 上涨概率 | 核心原因 |")
        lines.append("|---:|---|---|---:|---:|---:|---|")
        for item in result.index_allocation[:7]:
            lines.append(
                f"| {item.rank} | {item.name}({item.code}) | {item.signal} | "
                f"{item.score:.1f} | {item.expected_20d_return:.2f}% | "
                f"{item.up_probability:.1f}% | {item.reason} |"
            )
    else:
        lines.append("- 指数横向配置模型暂未获得足够历史数据。")

    lines.extend(["", "## 因子贡献拆解", ""])
    if result.factor_contributions:
        lines.append("| 因子 | 因子分 | 有效权重 | 对总分贡献 | 相对中性影响 | 状态 |")
        lines.append("|---|---:|---:|---:|---:|---|")
        for item in result.factor_contributions:
            lines.append(
                f"| {item.name} | {item.score:.1f} | {item.effective_weight:.1%} | "
                f"{item.contribution:.2f} | {item.impact_vs_neutral:+.2f} | "
                f"{item.status.value} |"
            )
    else:
        lines.append("- 暂无因子贡献拆解。")

    lines.extend([
        "",
        "## 数据质量提示",
        "",
    ])
    if result.warnings:
        lines.extend([f"- {warning}" for warning in result.warnings])
    else:
        lines.append("- 多源数据校验正常。")

    lines.extend(["", "## 机构态度", ""])
    lines.extend([f"- {item}" for item in result.institution_view])

    lines.extend(["", "## 风险提示", ""])
    lines.extend([f"- {item}" for item in result.risk_tips])

    lines.extend(["", "## 情绪地图", ""])
    strong = result.emotion_map.get("strong", [])[:6]
    weak = result.emotion_map.get("weak", [])[:6]
    if strong:
        lines.append("强势吸金/领涨板块：")
        lines.extend([f"- {item['name']}：{item['pct_change']}%" for item in strong])
    if weak:
        lines.append("")
        lines.append("弱势退潮板块：")
        lines.extend([f"- {item['name']}：{item['pct_change']}%" for item in weak])

    lines.extend(["", "## 分项指标", ""])
    for component in result.components:
        lines.append(
            f"- {component.name}：{component.score:.1f}，权重 {component.weight:.0%}，"
            f"状态 {component.status.value}，置信度 {component.confidence:.0%}"
        )

    return "\n".join(lines) + "\n"


def render_wechat_markdown(result: AfgiResult) -> str:
    score_text = "N/A" if result.score is None else f"{result.score:.1f}"
    formal_note = "" if result.formal else "（试算）"
    warnings = result.warnings[:4] or ["多源数据校验正常。"]
    strong = result.emotion_map.get("strong", [])[:5]
    weak = result.emotion_map.get("weak", [])[:5]

    lines = [
        f"## A股恐惧贪婪指数{formal_note}",
        f"> 日期：{result.run_date.isoformat()}",
        f"> 指数：<font color=\"warning\">{score_text}</font> / 100",
        f"> 状态：{result.label}",
        f"> 建议仓位：{result.suggested_position}",
        "",
        f"明日展望：上涨 {result.outlook['up']:.1f}% / "
        f"震荡 {result.outlook['flat']:.1f}% / 下跌 {result.outlook['down']:.1f}%",
        "",
    ]
    if result.index_allocation:
        lines.extend(["### 未来20天指数配置"])
        for item in result.index_allocation[:3]:
            lines.append(
                f"- {item.rank}. {item.name}：{item.signal}，评分 {item.score:.1f}，"
                f"上涨概率 {item.up_probability:.1f}%"
            )

    if result.factor_contributions:
        lines.extend(["", "### 因子贡献拆解"])
        for item in result.factor_contributions[:4]:
            lines.append(
                f"- {item.name}：贡献 {item.contribution:.2f} 分，"
                f"相对中性 {item.impact_vs_neutral:+.2f}"
            )

    lines.extend(["", "### 数据质量提示"])
    lines.extend([f"- {item}" for item in warnings])
    lines.extend(["", "### 机构态度"])
    lines.extend([f"- {item}" for item in result.institution_view[:3]])
    lines.extend(["", "### 风险提示"])
    lines.extend([f"- {item}" for item in result.risk_tips[:3]])
    if strong:
        lines.extend(["", "### 情绪地图：强势板块"])
        lines.extend([f"- {item['name']}：{item['pct_change']}%" for item in strong])
    if weak:
        lines.extend(["", "### 弱势板块"])
        lines.extend([f"- {item['name']}：{item['pct_change']}%" for item in weak])
    return "\n".join(lines)


def save_reports(result: AfgiResult, directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    markdown_path = directory / f"{result.run_date.isoformat()}.md"
    json_path = directory / f"{result.run_date.isoformat()}.json"
    latest_path = directory / "latest.md"
    markdown = render_markdown(result)
    markdown_path.write_text(markdown, encoding="utf-8")
    latest_path.write_text(markdown, encoding="utf-8")
    json_path.write_text(
        json.dumps(asdict(result), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return markdown_path, json_path


def report_needs_refresh(json_path: Path) -> bool:
    if not json_path.exists():
        return True
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return True
    return not data.get("factor_contributions") or not data.get("index_allocation")


def load_report(json_path: Path) -> AfgiResult:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    components = [
        ComponentScore(
            key=item["key"],
            name=item["name"],
            score=float(item["score"]),
            weight=float(item["weight"]),
            status=QualityStatus(item["status"]),
            confidence=float(item["confidence"]),
            message=item["message"],
            details=item.get("details", {}),
        )
        for item in data.get("components", [])
    ]
    factor_contributions = [
        FactorContribution(
            key=item["key"],
            name=item["name"],
            score=float(item["score"]),
            raw_weight=float(item["raw_weight"]),
            confidence=float(item["confidence"]),
            effective_weight=float(item["effective_weight"]),
            contribution=float(item["contribution"]),
            impact_vs_neutral=float(item["impact_vs_neutral"]),
            status=QualityStatus(item["status"]),
            message=item["message"],
        )
        for item in data.get("factor_contributions", [])
    ]
    index_allocation = [
        IndexAllocationScore(
            rank=int(item["rank"]),
            name=item["name"],
            code=item["code"],
            secid=item["secid"],
            score=float(item["score"]),
            signal=item["signal"],
            expected_20d_return=float(item["expected_20d_return"]),
            up_probability=float(item["up_probability"]),
            momentum_20d=float(item["momentum_20d"]),
            momentum_60d=float(item["momentum_60d"]),
            trend_score=float(item["trend_score"]),
            volume_ratio_5_20=(
                None
                if item.get("volume_ratio_5_20") is None
                else float(item["volume_ratio_5_20"])
            ),
            volatility_20d=float(item["volatility_20d"]),
            max_drawdown_60d=float(item["max_drawdown_60d"]),
            reason=item["reason"],
            warning=item.get("warning"),
        )
        for item in data.get("index_allocation", [])
    ]
    return AfgiResult(
        run_date=date.fromisoformat(data["run_date"]),
        score=data.get("score"),
        label=data["label"],
        formal=bool(data["formal"]),
        suggested_position=data["suggested_position"],
        outlook=data["outlook"],
        components=components,
        warnings=data.get("warnings", []),
        institution_view=data.get("institution_view", []),
        risk_tips=data.get("risk_tips", []),
        emotion_map=data.get("emotion_map", {}),
        factor_contributions=factor_contributions,
        index_allocation=index_allocation,
    )
