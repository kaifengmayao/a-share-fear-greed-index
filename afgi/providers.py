from __future__ import annotations

from datetime import date
from datetime import datetime
import re
import time
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

EASTMONEY_CLIST_HOSTS = [
    "push2.eastmoney.com",
    "82.push2.eastmoney.com",
    "33.push2.eastmoney.com",
    "push2his.eastmoney.com",
]

MARKET_BREADTH_INDICES = [
    ("上证市场", "1.000001"),
    ("深证市场", "0.399001"),
    ("北证市场", "0.899050"),
]


class DataProviders:
    def __init__(self, http: HttpClient) -> None:
        self.http = http
        self._cache: dict[str, object] = {}

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
        cached = self._cache.get("eastmoney_breadth")
        if isinstance(cached, MarketBreadth):
            return cached
        try:
            breadth = self._eastmoney_aggregate_breadth()
        except Exception:
            breadth = self._eastmoney_list_breadth()
        self._cache["eastmoney_breadth"] = breadth
        return breadth

    def _eastmoney_aggregate_breadth(self) -> MarketBreadth:
        fields = "f58,f113,f114,f115"
        parts: list[dict] = []
        up = down = flat = 0
        for market_name, secid in MARKET_BREADTH_INDICES:
            url = f"http://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fields={fields}"
            data = self.http.get_json(
                url,
                headers={
                    "Connection": "close",
                    "Referer": "https://quote.eastmoney.com/",
                },
            ).get("data") or {}
            part_up = int(safe_float(data.get("f113")) or 0)
            part_down = int(safe_float(data.get("f114")) or 0)
            part_flat = int(safe_float(data.get("f115")) or 0)
            parts.append(
                {
                    "market": market_name,
                    "name": data.get("f58") or secid,
                    "secid": secid,
                    "up": part_up,
                    "down": part_down,
                    "flat": part_flat,
                }
            )
            up += part_up
            down += part_down
            flat += part_flat

        if up + down + flat <= 0:
            raise ValueError("Eastmoney aggregate market breadth is empty")

        limit_stats = self._eastmoney_limit_stats()
        return MarketBreadth(
            source="东方财富指数聚合",
            total=up + down + flat,
            up=up,
            down=down,
            flat=flat,
            limit_up=int(limit_stats.get("limit_up") or 0),
            limit_down=int(limit_stats.get("limit_down") or 0),
            total_amount=0,
            first_limit_up=limit_stats.get("first_limit_up"),
            second_limit_up=limit_stats.get("second_limit_up"),
            third_or_more_limit_up=limit_stats.get("third_or_more_limit_up"),
            consecutive_limit_up=limit_stats.get("consecutive_limit_up"),
            highest_consecutive_limit_up=limit_stats.get("highest_consecutive_limit_up"),
            limit_up_pool_source=limit_stats.get("source"),
            limit_up_pool_error=limit_stats.get("error"),
            market_parts=parts,
        )

    def _eastmoney_list_breadth(self) -> MarketBreadth:
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
        limit_up = sum(1 for value in changes if value >= 9.5)
        limit_down = sum(1 for value in changes if value <= -9.5)
        limit_stats = self._eastmoney_limit_stats()
        if limit_stats.get("limit_up") is not None:
            limit_up = int(limit_stats["limit_up"])
        if limit_stats.get("limit_down") is not None:
            limit_down = int(limit_stats["limit_down"])
        breadth = MarketBreadth(
            source="东方财富分页列表",
            total=len(changes),
            up=up,
            down=down,
            flat=flat,
            limit_up=limit_up,
            limit_down=limit_down,
            total_amount=total_amount,
            first_limit_up=limit_stats.get("first_limit_up"),
            second_limit_up=limit_stats.get("second_limit_up"),
            third_or_more_limit_up=limit_stats.get("third_or_more_limit_up"),
            consecutive_limit_up=limit_stats.get("consecutive_limit_up"),
            highest_consecutive_limit_up=limit_stats.get("highest_consecutive_limit_up"),
            limit_up_pool_source=limit_stats.get("source"),
            limit_up_pool_error=limit_stats.get("error"),
        )
        return breadth

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
            try:
                data = self._eastmoney_clist_page(fs, fields, page, per_page)
            except Exception:
                if rows:
                    break
                raise
            total = int(data.get("total") or total)
            diff = data.get("diff") or []
            if not diff:
                break
            rows.extend(diff)
            page += 1
            time.sleep(0.15)
        return rows[:page_size]

    def _eastmoney_clist_page(
        self, fs: str, fields: str, page: int, per_page: int
    ) -> dict:
        last_error: Exception | None = None
        for attempt in range(4):
            for host in EASTMONEY_CLIST_HOSTS:
                url = (
                    f"https://{host}/api/qt/clist/get"
                    f"?pn={page}&pz={per_page}&po=1&np=1&fltt=2&invt=2"
                    f"&fs={fs}&fields={fields}"
                )
                try:
                    return self.http.get_json(
                        url,
                        headers={
                            "Connection": "close",
                            "Referer": "https://quote.eastmoney.com/",
                        },
                    ).get("data") or {}
                except Exception as exc:
                    last_error = exc
            time.sleep(0.5 * (attempt + 1))
        if last_error is not None:
            raise last_error
        return {}

    def _eastmoney_limit_stats(self) -> dict:
        stats = {
            "source": "东方财富涨跌停池",
            "limit_up": None,
            "limit_down": None,
            "first_limit_up": None,
            "second_limit_up": None,
            "third_or_more_limit_up": None,
            "consecutive_limit_up": None,
            "highest_consecutive_limit_up": None,
            "error": None,
        }
        errors: list[str] = []
        try:
            payload = self._eastmoney_topic_payload("getTopicZTPool")
            pool = self._topic_pool(payload)
            consecutive_values = [_limit_board_count(item) for item in pool]
            consecutive_values = [value for value in consecutive_values if value is not None]
            first = sum(1 for value in consecutive_values if value == 1)
            second = sum(1 for value in consecutive_values if value == 2)
            third_or_more = sum(1 for value in consecutive_values if value >= 3)
            consecutive = sum(1 for value in consecutive_values if value >= 2)
            highest = max(consecutive_values) if consecutive_values else None
            stats.update(
                {
                    "limit_up": int(safe_float(payload.get("tc")) or len(pool)),
                    "first_limit_up": first,
                    "second_limit_up": second,
                    "third_or_more_limit_up": third_or_more,
                    "consecutive_limit_up": consecutive,
                    "highest_consecutive_limit_up": highest,
                }
            )
        except Exception as exc:
            errors.append(f"涨停池: {exc}")

        try:
            payload = self._eastmoney_topic_payload("getTopicDTPool")
            down_pool = self._topic_pool(payload)
            stats["limit_down"] = int(safe_float(payload.get("tc")) or len(down_pool))
        except Exception as exc:
            errors.append(f"跌停池: {exc}")

        if errors:
            stats["error"] = "; ".join(errors)
        return stats

    def _eastmoney_topic_payload(self, endpoint: str) -> dict:
        today = date.today().strftime("%Y%m%d")
        url = (
            f"http://push2ex.eastmoney.com/{endpoint}"
            "?ut=7eea3edcaed734bea9cbfc24409ed989"
            "&dpt=wz.ztzt"
            f"&Pageindex=0&pagesize=1000&sort=fbt:asc&date={today}"
        )
        data = self.http.get_json(
            url,
            headers={
                "Connection": "close",
                "Referer": "https://quote.eastmoney.com/ztb/",
            },
        )
        if data.get("rc") != 0:
            raise ValueError(f"{endpoint} rc={data.get('rc')}")
        payload = data.get("data") or {}
        if not isinstance(payload, dict):
            raise ValueError(f"{endpoint} response data is not a dict")
        return payload

    def _topic_pool(self, payload: dict) -> list[dict]:
        pool = payload.get("pool") or []
        if not isinstance(pool, list):
            raise ValueError("topic response pool is not a list")
        return [item for item in pool if isinstance(item, dict)]


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


def _limit_board_count(item: dict) -> int | None:
    for key in ("lbc", "连板数", "lb"):
        value = safe_float(item.get(key))
        if value is not None:
            return int(value)
    return None
