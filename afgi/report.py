from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .models import AfgiResult


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
        "## 数据质量提示",
        "",
    ]
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
        "### 数据质量提示",
    ]
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
