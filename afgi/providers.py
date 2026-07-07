from __future__ import annotations

from datetime import datetime
import re
from typing import Callable

from .http_client import HttpClient
from .models import KLine, MarketBreadth, Quote, SectorSnapshot
from .utils import safe_float


CSI300_SECID = "1.000300"

INDEX_ALLOCATION_UNIVERSE = [
    ("上证50", "000016", "1.000016"),
    ("沪深300", "000300", "1.000300"),
    ("中证500", "000905", "1.000905"),
    ("中证1000", "000852", "1.000852"),
    ("创业板指", "399006", "0.399006"),
    ("科创50", "000688", "1.000688"),
    ("深证成指", "399001", "0.399001"),
]

YAHOO_INDEX_SYMBOLS = {
    "1.000016": "000016.SS",
    "1.000300": "000300.SS",
    "1.000905": "000905.SS",
    "1.000852": "000852.SS",
    "0.399006": "399006.SZ",
    "1.000688": "000688.SS",
    "0.399001": "399001.SZ",
}

TENCENT_INDEX_SYMBOLS = {
    "1.000016": "sh000016",
    "1.000300": "sh000300",
    "1.000905": "sh000905",
    "1.000852": "sh000852",
    "0.399006": "sz399006",
    "1.000688": "sh000688",
    "0.399001": "sz399001",
}


class DataProviders:
    def __init__(self, http: HttpClient) -> None:
        self.http = http

    def eastmoney_csi300_quote(self) -> Quote:
        url = (
            "https://push2.eastmoney.com/api/qt/stock/get"
            f"?secid={CSI300_SECID}&fields=f58,f43,f44,f45,f46,f47,f48,f60,f170,f168"
        )
        data = self.http.get_json(url).get("data") or {}
        price = (safe_float(data.get("f43")) or 0) / 100
        previous_close = (safe_float(data.get("f60")) or 0) / 100
        pct_change = (safe_float(data.get("f170")) or 0) / 100
        return Quote(
            source="东方财富",
            name=data.get("f58") or "沪深300",
            price=price,
            previous_close=previous_close or None,
            pct_change=pct_change,
            amount=safe_float(data.get("f48")),
            trade_date=None,
        )

    def sina_csi300_quote(self) -> Quote:
        url = "https://hq.sinajs.cn/list=sh000300"
        text = self.http.get_text(url, headers={"Referer": "https://finance.sina.com.cn/"})
        fields = _parse_sina_hq(text)
        price = safe_float(fields[3])
        previous_close = safe_float(fields[2])
        pct_change = None
        if price is not None and previous_close:
            pct_change = (price / previous_close - 1) * 100
        return Quote(
            source="新浪财经",
            name=fields[0] or "沪深300",
            price=price or 0,
            previous_close=previous_close,
            pct_change=pct_change,
            amount=safe_float(fields[9]) if len(fields) > 9 else None,
            trade_date=fields[30] if len(fields) > 30 else None,
        )

    def tencent_csi300_quote(self) -> Quote:
        url = "https://qt.gtimg.cn/q=sh000300"
        text = self.http.get_text(url)
        fields = _parse_tencent_hq(text)
        name = fields[1] if len(fields) > 1 else "沪深300"
        price = safe_float(fields[3]) if len(fields) > 3 else None
        previous_close = safe_float(fields[4]) if len(fields) > 4 else None
        pct_change = None
        if price is not None and previous_close:
            pct_change = (price / previous_close - 1) * 100
        return Quote(
            source="腾讯财经",
            name=name,
            price=price or 0,
            previous_close=previous_close,
            pct_change=pct_change,
            amount=None,
            trade_date=None,
        )

    def index_klines(self, secid: str, limit: int = 120) -> list[KLine]:
        candidates: list[list[KLine]] = []
        for fn in (
            self._eastmoney_index_klines,
            self._tencent_index_klines,
            self._yahoo_index_klines,
        ):
            try:
                klines = fn(secid, limit=limit)
            except Exception:
                continue
            if len(klines) >= min(60, limit):
                return klines
            if klines:
                candidates.append(klines)
        return max(candidates, key=len) if candidates else []

    def _eastmoney_index_klines(self, secid: str, limit: int = 120) -> list[KLine]:
        url = (
            "https://push2his.eastmoney.com/api/qt/stock/kline/get"
            f"?secid={secid}&fields1=f1,f2,f3,f4,f5,f6"
            "&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
            "&klt=101&fqt=1&beg=0&end=20500101"
            f"&lmt={limit}"
        )
        data = self.http.get_json(url).get("data") or {}
        rows = data.get("klines") or []
        klines: list[KLine] = []
        for row in rows[-limit:]:
            parts = row.split(",")
            if len(parts) < 7:
                continue
            klines.append(
                KLine(
                    trade_date=parts[0],
                    open=float(parts[1]),
                    close=float(parts[2]),
                    high=float(parts[3]),
                    low=float(parts[4]),
                    volume=float(parts[5]),
                    amount=float(parts[6]),
                )
            )
        return klines

    def _tencent_index_klines(self, secid: str, limit: int = 120) -> list[KLine]:
        symbol = TENCENT_INDEX_SYMBOLS.get(secid)
        if not symbol:
            raise ValueError(f"No Tencent symbol mapping for {secid}")
        url = (
            "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
            f"?param={symbol},day,,,{limit},qfq"
        )
        data = self.http.get_json(url).get("data") or {}
        rows = ((data.get(symbol) or {}).get("day")) or []
        klines: list[KLine] = []
        for row in rows[-limit:]:
            if len(row) < 6:
                continue
            close = float(row[2])
            volume = float(row[5])
            klines.append(
                KLine(
                    trade_date=str(row[0]),
                    open=float(row[1]),
                    close=close,
                    high=float(row[3]),
                    low=float(row[4]),
                    volume=volume,
                    amount=volume * close,
                )
            )
        return klines

    def _yahoo_index_klines(self, secid: str, limit: int = 120) -> list[KLine]:
        symbol = YAHOO_INDEX_SYMBOLS.get(secid)
        if not symbol:
            raise ValueError(f"No Yahoo symbol mapping for {secid}")
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=2y&interval=1d"
        result = ((self.http.get_json(url).get("chart") or {}).get("result") or [None])[0]
        if not result:
            raise ValueError(f"Yahoo chart has no result for {symbol}")
        timestamps = result.get("timestamp") or []
        quote = (((result.get("indicators") or {}).get("quote") or [None])[0]) or {}
        opens = quote.get("open") or []
        highs = quote.get("high") or []
        lows = quote.get("low") or []
        closes = quote.get("close") or []
        volumes = quote.get("volume") or []
        klines: list[KLine] = []
        for index, timestamp in enumerate(timestamps):
            try:
                open_price = opens[index]
                high_price = highs[index]
                low_price = lows[index]
                close_price = closes[index]
                volume = volumes[index] if index < len(volumes) else 0
            except IndexError:
                continue
            if None in (open_price, high_price, low_price, close_price):
                continue
            trade_date = datetime.fromtimestamp(int(timestamp)).date().isoformat()
            amount = (float(volume or 0) * float(close_price or 0)) if volume else 0.0
            klines.append(
                KLine(
                    trade_date=trade_date,
                    open=float(open_price),
                    close=float(close_price),
                    high=float(high_price),
                    low=float(low_price),
                    volume=float(volume or 0),
                    amount=amount,
                )
            )
        return klines[-limit:]

    def csi300_klines(self, limit: int = 120) -> list[KLine]:
        return self.index_klines(CSI300_SECID, limit=limit)

    def eastmoney_breadth(self) -> MarketBreadth:
        rows = self._eastmoney_clist(
            "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
            fields="f12,f14,f2,f3,f6",
            page_size=6000,
        )
        changes = [safe_float(row.get("f3")) for row in rows]
        changes = [item for item in changes if item is not None]
        total_amount = sum(safe_float(row.get("f6")) or 0 for row in rows)
        up = sum(1 for value in changes if value > 0)
        down = sum(1 for value in changes if value < 0)
        flat = sum(1 for value in changes if value == 0)
        return MarketBreadth(
            source="东方财富",
            total=len(changes),
            up=up,
            down=down,
            flat=flat,
            limit_up=sum(1 for value in changes if value >= 9.5),
            limit_down=sum(1 for value in changes if value <= -9.5),
            total_amount=total_amount,
        )

    def eastmoney_sectors(self) -> list[SectorSnapshot]:
        rows = self._eastmoney_clist("m:90+t:2", fields="f12,f14,f3,f6", page_size=100)
        sectors: list[SectorSnapshot] = []
        for row in rows:
            pct = safe_float(row.get("f3"))
            if pct is None:
                continue
            sectors.append(
                SectorSnapshot(
                    code=str(row.get("f12") or ""),
                    name=str(row.get("f14") or ""),
                    pct_change=pct,
                    amount=safe_float(row.get("f6")),
                )
            )
        return sectors

    def eastmoney_etfs(self) -> list[Quote]:
        etfs = [
            "1.510300",
            "1.510330",
            "0.159919",
            "1.510310",
            "1.510050",
            "0.159922",
            "1.512500",
        ]
        quotes: list[Quote] = []
        for secid in etfs:
            try:
                url = (
                    "https://push2.eastmoney.com/api/qt/stock/get"
                    f"?secid={secid}&fields=f58,f43,f48,f60,f170"
                )
                data = self.http.get_json(url).get("data") or {}
                price = (safe_float(data.get("f43")) or 0) / 1000
                previous_close = (safe_float(data.get("f60")) or 0) / 1000
                pct_change = (safe_float(data.get("f170")) or 0) / 100
                quotes.append(
                    Quote(
                        source="东方财富ETF",
                        name=data.get("f58") or secid,
                        price=price,
                        previous_close=previous_close or None,
                        pct_change=pct_change,
                        amount=safe_float(data.get("f48")),
                        trade_date=None,
                    )
                )
            except Exception:
                continue
        return quotes

    def sina_if_main(self) -> Quote:
        url = "https://hq.sinajs.cn/list=CFF_RE_IF0"
        text = self.http.get_text(url, headers={"Referer": "https://finance.sina.com.cn/"})
        fields = _parse_sina_hq(text)
        price = safe_float(fields[3]) or safe_float(fields[8])
        previous_close = safe_float(fields[10]) if len(fields) > 10 else None
        pct_change = None
        if price is not None and previous_close:
            pct_change = (price / previous_close - 1) * 100
        return Quote(
            source="新浪期货",
            name=fields[0] if fields else "IF主连",
            price=price or 0,
            previous_close=previous_close,
            pct_change=pct_change,
            amount=None,
            trade_date=None,
        )

    def _eastmoney_clist(self, fs: str, fields: str, page_size: int) -> list[dict]:
        rows: list[dict] = []
        page = 1
        per_page = min(max(page_size, 1), 100)
        total = page_size
        while len(rows) < min(page_size, total):
            url = (
                "https://push2.eastmoney.com/api/qt/clist/get"
                f"?pn={page}&pz={per_page}&po=1&np=1&fltt=2&invt=2"
                f"&fs={fs}&fields={fields}"
            )
            data = self.http.get_json(url).get("data") or {}
            total = int(data.get("total") or total)
            diff = data.get("diff") or []
            if not diff:
                break
            rows.extend(diff)
            page += 1
        return rows[:page_size]


def collect_attempts(
    functions: list[tuple[str, Callable[[], Quote]]],
) -> list[tuple[str, Quote | None, str | None]]:
    attempts: list[tuple[str, Quote | None, str | None]] = []
    for source_name, fn in functions:
        try:
            quote = fn()
            if quote.price > 0:
                attempts.append((source_name, quote, None))
            else:
                attempts.append((source_name, None, "empty quote"))
        except Exception as exc:
            attempts.append((source_name, None, str(exc)))
    return attempts


def _parse_sina_hq(text: str) -> list[str]:
    match = re.search(r'="(.*)"', text)
    if not match:
        raise ValueError("Sina response has no quote payload")
    return match.group(1).split(",")


def _parse_tencent_hq(text: str) -> list[str]:
    match = re.search(r'="(.*)"', text)
    if not match:
        raise ValueError("Tencent response has no quote payload")
    return match.group(1).split("~")
