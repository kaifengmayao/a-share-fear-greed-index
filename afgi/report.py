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
    ScoreAdjustment,
)


REPORT_SCHEMA_VERSION = 15


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
        f"- 加权原始分：{'N/A' if result.raw_score is None else f'{result.raw_score:.1f}'} / 100",
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
        lines.append("| 因子 | 因子分 | 有效权重 | 对原始分贡献 | 相对中性影响 | 状态 |")
        lines.append("|---|---:|---:|---:|---:|---|")
        for item in result.factor_contributions:
            lines.append(
                f"| {item.name} | {item.score:.1f} | {item.effective_weight:.1%} | "
                f"{item.contribution:.2f} | {item.impact_vs_neutral:+.2f} | "
                f"{item.status.value} |"
            )
    else:
        lines.append("- 暂无因子贡献拆解。")

    if result.score_adjustments:
        lines.extend(["", "## 分数校准项", ""])
        for item in result.score_adjustments:
            lines.append(
                f"- {item.name}：{item.before:.1f} -> {item.after:.1f} "
                f"（{item.impact:+.1f}），{item.condition}"
            )

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
        lines.extend([_sector_line(item) for item in strong])
    if weak:
        lines.append("")
        lines.append("弱势退潮板块：")
        lines.extend([_sector_line(item) for item in weak])

    lines.extend(["", "## 分项指标", ""])
    for component in result.components:
        lines.append(
            f"- {component.name}：{component.score:.1f}，权重 {component.weight:.0%}，"
            f"状态 {component.status.value}，置信度 {component.confidence:.0%}"
        )
    breadth_lines = _breadth_detail_lines(result.components)
    if breadth_lines:
        lines.extend(["", "## 市场宽度明细", ""])
        lines.extend(breadth_lines)

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
        f"> 加权原始分：{'N/A' if result.raw_score is None else f'{result.raw_score:.1f}'} / 100",
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

    if result.score_adjustments:
        lines.extend(["", "### 分数校准项"])
        for item in result.score_adjustments[:2]:
            lines.append(f"- {item.name}：{item.before:.1f} -> {item.after:.1f}（{item.impact:+.1f}）")

    breadth_lines = _breadth_detail_lines(result.components)
    if breadth_lines:
        lines.extend(["", "### 市场宽度明细"])
        lines.extend(breadth_lines[:5])

    lines.extend(["", "### 数据质量提示"])
    lines.extend([f"- {item}" for item in warnings])
    lines.extend(["", "### 机构态度"])
    lines.extend([f"- {item}" for item in result.institution_view[:3]])
    lines.extend(["", "### 风险提示"])
    lines.extend([f"- {item}" for item in result.risk_tips[:3]])
    if strong:
        lines.extend(["", "### 情绪地图：强势板块"])
        lines.extend([_sector_line(item) for item in strong])
    if weak:
        lines.extend(["", "### 弱势板块"])
        lines.extend([_sector_line(item) for item in weak])
    return "\n".join(lines)


def _sector_line(item: dict) -> str:
    flow = _money(item.get("main_net_inflow"))
    ratio = item.get("main_net_inflow_ratio")
    ratio_text = "" if ratio is None else f"，主力净占比 {float(ratio):.2f}%"
    up = item.get("up")
    down = item.get("down")
    breadth_text = ""
    if up is not None and down is not None:
        breadth_text = f"，板块内上涨 {up} / 下跌 {down}"
    return (
        f"- {item['name']}：涨跌幅 {item['pct_change']}%，"
        f"主力净流入 {flow}{ratio_text}{breadth_text}"
    )


def _breadth_detail_lines(components: list[ComponentScore]) -> list[str]:
    breadth = next((item for item in components if item.key == "breadth"), None)
    if not breadth:
        return []
    details = breadth.details or {}
    total = details.get("total")
    up = details.get("up")
    down = details.get("down")
    if total is None or up is None or down is None:
        return []
    flat = details.get("flat", 0)
    up_ratio = _pct(up, total)
    down_ratio = _pct(down, total)
    lines = [
        f"- 全A涨跌：上涨 {up} 家（{up_ratio}），下跌 {down} 家（{down_ratio}），平盘 {flat} 家。",
        f"- 涨跌停：涨停 {details.get('limit_up', 0)} 家，跌停 {details.get('limit_down', 0)} 家。",
    ]
    first = details.get("first_limit_up")
    second = details.get("second_limit_up")
    third = details.get("third_or_more_limit_up")
    consecutive = details.get("consecutive_limit_up")
    highest = details.get("highest_consecutive_limit_up")
    if any(value is not None for value in (first, second, third, consecutive, highest)):
        lines.append(
            "- 连板结构："
            f"首板 {first or 0} 家，二板 {second or 0} 家，三板及以上 {third or 0} 家，"
            f"连板 {consecutive or 0} 家，最高 {highest or 0} 板。"
        )
    market_parts = details.get("market_parts") or []
    if market_parts:
        part_text = []
        for item in market_parts:
            part_text.append(
                f"{item.get('market') or item.get('name')} 上涨 {item.get('up', 0)} / "
                f"下跌 {item.get('down', 0)} / 平盘 {item.get('flat', 0)}"
            )
        lines.append("- 市场拆分：" + "；".join(part_text) + "。")
    error = details.get("limit_up_pool_error")
    if error:
        lines.append(f"- 涨跌停池提示：{error}")
    return lines


def _pct(value: object, total: object) -> str:
    try:
        denominator = float(total)
        if denominator <= 0:
            return "N/A"
        return f"{float(value) / denominator:.1%}"
    except (TypeError, ValueError):
        return "N/A"


def _money(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "N/A"
    sign = "-" if number < 0 else ""
    number = abs(number)
    if number >= 100000000:
        return f"{sign}{number / 100000000:.2f}亿"
    if number >= 10000:
        return f"{sign}{number / 10000:.2f}万"
    return f"{sign}{number:.0f}"


def save_reports(result: AfgiResult, directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    markdown_path = directory / f"{result.run_date.isoformat()}.md"
    json_path = directory / f"{result.run_date.isoformat()}.json"
    latest_path = directory / "latest.md"
    markdown = render_markdown(result)
    markdown_path.write_text(markdown, encoding="utf-8")
    latest_path.write_text(markdown, encoding="utf-8")
    payload = asdict(result)
    payload["report_schema_version"] = REPORT_SCHEMA_VERSION
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
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
    if data.get("report_schema_version") != REPORT_SCHEMA_VERSION:
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
    score_adjustments = [
        ScoreAdjustment(
            name=item["name"],
            before=float(item["before"]),
            after=float(item["after"]),
            impact=float(item["impact"]),
            condition=item["condition"],
            message=item["message"],
        )
        for item in data.get("score_adjustments", [])
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
        raw_score=data.get("raw_score"),
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
        score_adjustments=score_adjustments,
        index_allocation=index_allocation,
    )
