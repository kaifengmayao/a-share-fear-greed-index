from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any, Callable

from .providers import DataProviders


def save_market_history(
    providers: DataProviders,
    directory: Path,
    run_date: date,
) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    snapshot = {
        "run_date": run_date.isoformat(),
        "sources": {
            "csi300_klines": _capture(lambda: providers.csi300_klines(limit=260)),
            "market_breadth": _capture(providers.eastmoney_breadth),
            "sectors": _capture(providers.eastmoney_sectors),
            "etfs": _capture(providers.eastmoney_etfs),
            "if_main": _capture(providers.sina_if_main),
        },
    }

    daily_path = directory / f"{run_date.isoformat()}.json"
    latest_path = directory / "latest.json"
    content = json.dumps(snapshot, ensure_ascii=False, indent=2, default=str)
    daily_path.write_text(content, encoding="utf-8")
    latest_path.write_text(content, encoding="utf-8")
    return daily_path, latest_path


def _capture(fn: Callable[[], Any]) -> dict[str, Any]:
    try:
        value = fn()
        return {"status": "OK", "data": _to_jsonable(value)}
    except Exception as exc:
        return {"status": "MISSING", "error": str(exc), "data": None}


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    return value
