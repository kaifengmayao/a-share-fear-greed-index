from __future__ import annotations

import json
from pathlib import Path

from .calculator import calculate_afgi
from .config import Settings
from .history import history_snapshot_needs_refresh, save_market_history
from .http_client import HttpClient
from .notifiers import send_wechat
from .providers import DataProviders
from .report import load_report, render_wechat_markdown, report_needs_refresh, save_reports
from .utils import today_cn


def main() -> None:
    settings = Settings.from_env()
    reports_dir = Path("reports")
    data_dir = Path("data/history")
    sent_dir = Path("data/sent")
    run_date = today_cn()
    json_path = reports_dir / f"{run_date.isoformat()}.json"
    history_path = data_dir / f"{run_date.isoformat()}.json"
    sent_marker_path = sent_dir / f"{run_date.isoformat()}.json"
    providers = DataProviders(HttpClient(timeout=settings.request_timeout))

    if settings.skip_if_sent and sent_marker_path.exists():
        print(f"Daily report already sent, marker exists: {sent_marker_path}")
        return

    if json_path.exists() and not settings.force_recalculate and not report_needs_refresh(json_path):
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

    if _should_write_sent_marker(send_results):
        sent_dir.mkdir(parents=True, exist_ok=True)
        sent_marker_path.write_text(
            json.dumps(
                {
                    "date": run_date.isoformat(),
                    "report": str(json_path),
                    "title": title,
                    "send_results": send_results,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"Sent marker: {sent_marker_path}")

    print(f"Markdown report: {markdown_path}")
    print(f"JSON report: {json_path}")
    for item in send_results:
        print(item)


def _should_write_sent_marker(send_results: list[str]) -> bool:
    return any("发送成功" in item for item in send_results)


if __name__ == "__main__":
    main()
