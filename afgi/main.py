from __future__ import annotations

from pathlib import Path

from .calculator import calculate_afgi
from .config import Settings
from .history import history_snapshot_needs_refresh, save_market_history
from .http_client import HttpClient
from .notifiers import send_wechat
from .providers import DataProviders
from .report import load_report, render_wechat_markdown, save_reports
from .utils import today_cn


def main() -> None:
    settings = Settings.from_env()
    reports_dir = Path("reports")
    data_dir = Path("data/history")
    run_date = today_cn()
    json_path = reports_dir / f"{run_date.isoformat()}.json"
    history_path = data_dir / f"{run_date.isoformat()}.json"
    providers = DataProviders(HttpClient(timeout=settings.request_timeout))

    if json_path.exists() and not settings.force_recalculate:
        result = load_report(json_path)
        markdown_path = reports_dir / f"{result.run_date.isoformat()}.md"
        print(f"Using cached daily report: {json_path}")
    else:
        result = calculate_afgi(providers)
        markdown_path, json_path = save_reports(result, reports_dir)

    if history_snapshot_needs_refresh(history_path) or settings.force_recalculate:
        saved_history_path, _ = save_market_history(providers, data_dir, run_date)
        print(f"Market history snapshot: {saved_history_path}")

    title = f"A股恐惧贪婪指数 {result.run_date.isoformat()}：{result.label}"
    content = render_wechat_markdown(result)
    send_results = send_wechat(settings, title=title, content=content)

    print(f"Markdown report: {markdown_path}")
    print(f"JSON report: {json_path}")
    for item in send_results:
        print(item)


if __name__ == "__main__":
    main()
