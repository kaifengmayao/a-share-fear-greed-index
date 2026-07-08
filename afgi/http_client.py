from __future__ import annotations

import requests


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "*/*",
}


class HttpClient:
    def __init__(self, timeout: float = 12.0) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update(DEFAULT_HEADERS)

    def get_json(self, url: str, **kwargs):
        timeout = kwargs.pop("timeout", self.timeout)
        response = self.session.get(url, timeout=timeout, **kwargs)
        response.raise_for_status()
        return response.json()

    def get_text(self, url: str, **kwargs) -> str:
        timeout = kwargs.pop("timeout", self.timeout)
        response = self.session.get(url, timeout=timeout, **kwargs)
        response.raise_for_status()
        response.encoding = response.apparent_encoding or response.encoding
        return response.text
