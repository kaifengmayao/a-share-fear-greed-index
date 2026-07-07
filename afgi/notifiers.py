from __future__ import annotations

import requests

from .config import Settings


def send_wechat(settings: Settings, title: str, content: str) -> list[str]:
    if not settings.send_enabled or settings.dry_run:
        return ["发送已跳过：AFGI_SEND_ENABLED=false 或 AFGI_DRY_RUN=true。"]

    results: list[str] = []
    if settings.wecom_webhook_url:
        response = requests.post(
            settings.wecom_webhook_url,
            json={"msgtype": "markdown", "markdown": {"content": content[:3900]}},
            timeout=settings.request_timeout,
        )
        response.raise_for_status()
        results.append("企业微信机器人发送成功。")

    if settings.wxpusher_app_token and settings.wxpusher_uids:
        response = requests.post(
            "https://wxpusher.zjiecode.com/api/send/message",
            json={
                "appToken": settings.wxpusher_app_token,
                "content": content,
                "summary": title[:96],
                "contentType": 3,
                "uids": settings.wxpusher_uids,
            },
            timeout=settings.request_timeout,
        )
        response.raise_for_status()
        results.append("WxPusher发送成功。")

    if settings.serverchan_sendkey:
        response = requests.post(
            f"https://sctapi.ftqq.com/{settings.serverchan_sendkey}.send",
            data={"title": title, "desp": content},
            timeout=settings.request_timeout,
        )
        response.raise_for_status()
        results.append("Server酱发送成功。")

    if not results:
        results.append("未配置微信推送密钥，已只生成本地报告。")
    return results
