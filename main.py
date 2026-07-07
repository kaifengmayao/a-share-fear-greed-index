from __future__ import annotations

from pathlib import Path

from .calculator import calculate_afgi
from .config import Settings
from .http import HttpClient
from .notifiers import send_wechat
from .providers import DataProviders
from .report import render_wechat_markdown, save_reports


def main() -> None:
    settings = Settings.from_env()
    providers = DataProviders(HttpClient(timeout=settings.request_timeout))
    result = calculate_afgi(providers)
    markdown_path, json_path = save_reports(result, Path("reports"))
    title = f"A股恐惧贪婪指数 {result.run_date.isoformat()}：{result.label}"
    content = render_wechat_markdown(result)
    send_results = send_wechat(settings, title=title, content=content)

    print(f"Markdown report: {markdown_path}")
    print(f"JSON report: {json_path}")
    for item in send_results:
        print(item)


if __name__ == "__main__":
    main()
