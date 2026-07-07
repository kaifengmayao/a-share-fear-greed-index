from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    request_timeout: float = 12.0
    send_enabled: bool = True
    wecom_webhook_url: str | None = None
    wxpusher_app_token: str | None = None
    wxpusher_uids: list[str] = field(default_factory=list)
    serverchan_sendkey: str | None = None
    dry_run: bool = False
    force_recalculate: bool = False

    @staticmethod
    def from_env() -> "Settings":
        send_enabled = os.getenv("AFGI_SEND_ENABLED", "true").lower() == "true"
        dry_run = os.getenv("AFGI_DRY_RUN", "false").lower() == "true"
        force_recalculate = os.getenv("AFGI_FORCE_RECALCULATE", "false").lower() == "true"
        wxpusher_uids = [
            item.strip()
            for item in os.getenv("WXPUSHER_UIDS", "").split(",")
            if item.strip()
        ]
        return Settings(
            request_timeout=float(os.getenv("AFGI_REQUEST_TIMEOUT", "12")),
            send_enabled=send_enabled,
            wecom_webhook_url=os.getenv("WECHAT_WEBHOOK_URL") or None,
            wxpusher_app_token=os.getenv("WXPUSHER_APP_TOKEN") or None,
            wxpusher_uids=wxpusher_uids,
            serverchan_sendkey=os.getenv("SERVERCHAN_SENDKEY") or None,
            dry_run=dry_run,
            force_recalculate=force_recalculate,
        )
