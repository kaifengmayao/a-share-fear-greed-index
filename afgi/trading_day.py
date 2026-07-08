from __future__ import annotations

import os

from .http_client import HttpClient
from .providers import DataProviders
from .utils import today_cn


def main() -> None:
    run_date = today_cn()
    fail_open = os.getenv("AFGI_TRADING_DAY_FAIL_OPEN", "false").lower() == "true"

    if run_date.weekday() >= 5:
        _emit(False, f"{run_date.isoformat()} is weekend", run_date.isoformat(), None)
        return

    try:
        timeout = float(os.getenv("AFGI_REQUEST_TIMEOUT", "15"))
        providers = DataProviders(HttpClient(timeout=timeout))
        klines = providers.csi300_klines(limit=5)
        latest_trade_date = klines[-1].trade_date if klines else None
        is_trading_day = latest_trade_date == run_date.isoformat()
        reason = (
            "latest CSI300 kline matches today"
            if is_trading_day
            else f"latest CSI300 kline is {latest_trade_date or 'missing'}"
        )
        _emit(is_trading_day, reason, run_date.isoformat(), latest_trade_date)
    except Exception as exc:
        _emit(fail_open, f"trading day check failed: {exc}", run_date.isoformat(), None)


def _emit(should_run: bool, reason: str, run_date: str, latest_trade_date: str | None) -> None:
    print(f"should_run={'true' if should_run else 'false'}")
    print(f"run_date={run_date}")
    if latest_trade_date:
        print(f"latest_trade_date={latest_trade_date}")
    safe_reason = reason.replace("\r", " ").replace("\n", " ")
    print(f"reason={safe_reason}")
    print(f"Trading day check: {'run' if should_run else 'skip'} - {safe_reason}")


if __name__ == "__main__":
    main()
