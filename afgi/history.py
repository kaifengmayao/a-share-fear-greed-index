from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any, Callable

from .providers import DataProviders, INDEX_ALLOCATION_UNIVERSE, collect_attempts


HISTORY_SCHEMA_VERSION = 21


def save_market_history(
    providers: DataProviders,
    directory: Path,
    run_date: date,
) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    csi300_klines = _capture(lambda: providers.csi300_klines(limit=260))
    snapshot = {
        "schema_version": HISTORY_SCHEMA_VERSION,
        "run_date": run_date.isoformat(),
        "universe": {
            "primary_index": {
                "name": "CSI300",
                "display_name": "CSI300 Index",
                "code": "000300",
                "secid": "1.000300",
                "asset_type": "index",
            },
            "allocation_indices": [
                {"name": name, "code": code, "secid": secid, "asset_type": "index"}
                for name, code, secid in INDEX_ALLOCATION_UNIVERSE
            ],
        },
        "sources": {
            "csi300_index_quotes": _capture(lambda: _csi300_quote_attempts(providers)),
            "csi300_index_klines": csi300_klines,
            "csi300_index_volume_summary": _capture(
                lambda: _volume_summary(csi300_klines.get("data") or [])
            ),
            "allocation_index_klines": _capture(lambda: _allocation_index_klines(providers)),
            "market_breadth": _capture(providers.eastmoney_breadth),
            "market_profit_effect": _capture(lambda: providers.market_profit_effect()),
            "sectors": _capture(providers.eastmoney_sectors),
            "institution_auxiliary": {
                "broad_etf_quotes": _capture(providers.broad_etfs),
                "eastmoney_etf_quotes": _capture(providers.eastmoney_etfs),
                "sina_etf_quotes": _capture(providers.sina_etfs),
                "if_main": _capture(providers.sina_if_main),
                "margin_summary": _capture(providers.eastmoney_margin_summary),
            },
        },
    }

    daily_path = directory / f"{run_date.isoformat()}.json"
    latest_path = directory / "latest.json"
    content = json.dumps(snapshot, ensure_ascii=False, indent=2, default=str)
    daily_path.write_text(content, encoding="utf-8")
    latest_path.write_text(content, encoding="utf-8")
    return daily_path, latest_path


def history_snapshot_needs_refresh(path: Path) -> bool:
    if not path.exists():
        return True
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return True
    return snapshot.get("schema_version") != HISTORY_SCHEMA_VERSION


def _csi300_quote_attempts(providers: DataProviders) -> list[dict[str, Any]]:
    attempts = collect_attempts(
        [
            ("eastmoney_index_000300", providers.eastmoney_csi300_quote),
            ("sina_index_000300", providers.sina_csi300_quote),
            ("tencent_index_000300", providers.tencent_csi300_quote),
        ]
    )
    return [
        {
            "source": source,
            "status": "OK" if quote is not None else "MISSING",
            "data": _to_jsonable(quote) if quote is not None else None,
            "error": error,
        }
        for source, quote, error in attempts
    ]


def _allocation_index_klines(providers: DataProviders) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    for name, code, secid in INDEX_ALLOCATION_UNIVERSE:
        item = {
            "name": name,
            "code": code,
            "secid": secid,
            "klines": _capture(lambda secid=secid: providers.index_klines(secid, limit=120)),
        }
        snapshots.append(item)
    return snapshots


def _volume_summary(klines: list[dict[str, Any]]) -> dict[str, Any]:
    if not klines:
        raise ValueError("CSI300 index kline data is missing")

    latest = klines[-1]
    return {
        "source": "csi300_index_klines",
        "latest_trade_date": latest.get("trade_date"),
        "latest_volume": latest.get("volume"),
        "latest_amount": latest.get("amount"),
        "avg_volume_5": _rolling_mean(klines, "volume", 5),
        "avg_volume_20": _rolling_mean(klines, "volume", 20),
        "avg_volume_60": _rolling_mean(klines, "volume", 60),
        "avg_amount_5": _rolling_mean(klines, "amount", 5),
        "avg_amount_20": _rolling_mean(klines, "amount", 20),
        "avg_amount_60": _rolling_mean(klines, "amount", 60),
        "volume_ratio_5_to_20": _safe_ratio(
            _rolling_mean(klines, "volume", 5),
            _rolling_mean(klines, "volume", 20),
        ),
        "amount_ratio_5_to_20": _safe_ratio(
            _rolling_mean(klines, "amount", 5),
            _rolling_mean(klines, "amount", 20),
        ),
    }


def _rolling_mean(rows: list[dict[str, Any]], key: str, window: int) -> float | None:
    values = [row.get(key) for row in rows[-window:]]
    numbers = [float(value) for value in values if value is not None]
    if not numbers:
        return None
    return round(sum(numbers) / len(numbers), 2)


def _safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or not denominator:
        return None
    return round(numerator / denominator, 4)


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
