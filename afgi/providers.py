from __future__ import annotations

import json
from datetime import date
from datetime import datetime
import re
import time
from typing import Callable

from .http_client import HttpClient
from .models import KLine, MarginSnapshot, MarketBreadth, Quote, SectorSnapshot
from .utils import CN_TZ, safe_float


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

EASTMONEY_STOCK_GET_BASES = [
    "http://push2.eastmoney.com",
    "https://push2.eastmoney.com",
    "https://82.push2.eastmoney.com",
    "https://33.push2.eastmoney.com",
    "https://push2his.eastmoney.com",
]

EASTMONEY_TOPIC_BASES = [
    "http://push2ex.eastmoney.com",
    "https://push2ex.eastmoney.com",
]

EASTMONEY_ULIST_BASES = [
    "https://push2.eastmoney.com",
    "http://push2.eastmoney.com",
    "https://82.push2.eastmoney.com",
    "https://33.push2.eastmoney.com",
    "https://push2his.eastmoney.com",
]

SINA_MARKET_CENTER_URL = (
    "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
    "Market_Center.getHQNodeData"
)

BROAD_ETFS = [
    ("1.510300", "sh510300"),
    ("1.510330", "sh510330"),
    ("0.159919", "sz159919"),
    ("1.510310", "sh510310"),
    ("1.510050", "sh510050"),
    ("0.159922", "sz159922"),
    ("1.512500", "sh512500"),
]

MARKET_BREADTH_INDICES = [
    ("上证市场", "1.000001"),
    ("深证市场", "0.399001"),
    ("北证市场", "0.899050"),
]

MIN_MARKET_BREADTH_TOTAL = 4000

MARKET_BREADTH_LIST_SOURCES = [
    ("eastmoney_all_a_clist", "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"),
    ("eastmoney_sh_sz_clist", "m:0+t:6,m:0+t:80,m:1+t:2"),
    ("eastmoney_sh_clist", "m:1+t:2,m:1+t:23"),
    ("eastmoney_sz_clist", "m:0+t:6,m:0+t:80"),
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
        errors: list[str] = []
        try:
            breadth = self._eastmoney_aggregate_breadth()
            self._validate_market_breadth(breadth)
            self._cache["eastmoney_breadth"] = breadth
            return breadth
        except Exception as exc:
            errors.append(f"aggregate: {exc}")
        try:
            breadth = self._eastmoney_list_breadth()
            self._validate_market_breadth(breadth)
            self._cache["eastmoney_breadth"] = breadth
            return breadth
        except Exception as exc:
            errors.append(f"clist: {exc}")
        try:
            breadth = self._sina_market_center_breadth()
            self._validate_market_breadth(breadth)
            self._cache["eastmoney_breadth"] = breadth
            return breadth
        except Exception as exc:
            errors.append(f"sina_market_center: {exc}")
        raise ValueError("Market breadth data failed coverage checks: " + " | ".join(errors))

    def _eastmoney_aggregate_breadth(self) -> MarketBreadth:
        fields = "f58,f113,f114,f115"
        parts: list[dict] = []
        up = down = flat = 0
        for market_name, secid in MARKET_BREADTH_INDICES:
            data = self._eastmoney_stock_get(secid, fields)
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

    def _eastmoney_stock_get(self, secid: str, fields: str) -> dict:
        last_error: Exception | None = None
        for base_url in EASTMONEY_STOCK_GET_BASES:
            url = f"{base_url}/api/qt/stock/get?secid={secid}&fields={fields}"
            try:
                data = self.http.get_json(
                    url,
                    headers={
                        "Connection": "close",
                        "Referer": "https://quote.eastmoney.com/",
                    },
                ).get("data") or {}
                if data:
                    return data
                last_error = ValueError(f"Eastmoney stock/get empty for {secid} via {base_url}")
            except Exception as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise ValueError(f"Eastmoney stock/get failed for {secid}")

    def _eastmoney_list_breadth(self) -> MarketBreadth:
        errors: list[str] = []
        for source, fs in MARKET_BREADTH_LIST_SOURCES:
            try:
                breadth = self._eastmoney_list_breadth_for(source, fs)
                self._validate_market_breadth(breadth)
                return breadth
            except Exception as exc:
                errors.append(f"{source}: {exc}")
        raise ValueError("Eastmoney list breadth unavailable: " + " | ".join(errors))

    def _eastmoney_list_breadth_for(self, source: str, fs: str) -> MarketBreadth:
        rows = self._eastmoney_clist(
            fs,
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
            source=source,
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

    def _validate_market_breadth(self, breadth: MarketBreadth) -> None:
        counted = breadth.up + breadth.down + breadth.flat
        if breadth.total < MIN_MARKET_BREADTH_TOTAL:
            raise ValueError(
                f"{breadth.source} returned only {breadth.total} stocks; "
                f"expected at least {MIN_MARKET_BREADTH_TOTAL}"
            )
        if counted < MIN_MARKET_BREADTH_TOTAL:
            raise ValueError(
                f"{breadth.source} counted only {counted} up/down/flat stocks; "
                f"expected at least {MIN_MARKET_BREADTH_TOTAL}"
            )
        if abs(counted - breadth.total) > max(20, breadth.total * 0.02):
            raise ValueError(
                f"{breadth.source} inconsistent breadth total: "
                f"total={breadth.total}, counted={counted}"
            )

    def _sina_market_center_breadth(self) -> MarketBreadth:
        rows: list[dict] = []
        per_page = 80
        for page in range(1, 90):
            text = self.http.get_text(
                SINA_MARKET_CENTER_URL,
                params={
                    "page": page,
                    "num": per_page,
                    "sort": "changepercent",
                    "asc": "0",
                    "node": "hs_a",
                    "symbol": "",
                    "_s_r_a": "page",
                },
                headers={
                    "Connection": "close",
                    "Referer": "https://vip.stock.finance.sina.com.cn/mkt/",
                },
            )
            page_rows = _parse_sina_market_center_rows(text)
            if not page_rows:
                break
            rows.extend(page_rows)
            if len(page_rows) < per_page:
                break
            time.sleep(0.12)

        changes = [safe_float(row.get("changepercent")) for row in rows]
        changes = [item for item in changes if item is not None]
        if not changes:
            raise ValueError("Sina market center breadth is empty")

        total_amount = sum(safe_float(row.get("amount")) or 0 for row in rows)
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

        return MarketBreadth(
            source="新浪行情中心全A分页",
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

    def eastmoney_sectors(self) -> list[SectorSnapshot]:
        try:
            return self._eastmoney_sector_fund_flow()
        except Exception:
            return self._eastmoney_sector_clist_fallback()

    def _eastmoney_sector_fund_flow(self) -> list[SectorSnapshot]:
        fund_rows = self._eastmoney_bkzj_rows("f62")
        pct_rows = {str(row.get("f12") or ""): row for row in self._eastmoney_bkzj_rows("f3")}
        amount_rows = {str(row.get("f12") or ""): row for row in self._eastmoney_bkzj_rows("f6")}
        ratio_rows = {str(row.get("f12") or ""): row for row in self._eastmoney_bkzj_rows("f184")}
        codes = [str(row.get("f12") or "") for row in fund_rows if row.get("f12")]
        try:
            quote_rows = {
                str(row.get("f12") or ""): row
                for row in self._eastmoney_sector_quote_rows(codes)
            }
        except Exception:
            quote_rows = {}

        sectors: list[SectorSnapshot] = []
        for row in fund_rows:
            code = str(row.get("f12") or "")
            if not code:
                continue
            quote = quote_rows.get(code) or {}
            pct_row = pct_rows.get(code) or {}
            amount_row = amount_rows.get(code) or {}
            ratio_row = ratio_rows.get(code) or {}
            pct = safe_float(quote.get("f3"))
            if pct is None:
                pct = _scaled_percent(pct_row.get("f3"))
            if pct is None:
                continue
            sectors.append(
                SectorSnapshot(
                    code=code,
                    name=str(quote.get("f14") or row.get("f14") or code),
                    pct_change=pct,
                    amount=safe_float(quote.get("f6")) or safe_float(amount_row.get("f6")),
                    main_net_inflow=safe_float(quote.get("f62")) or safe_float(row.get("f62")),
                    main_net_inflow_ratio=safe_float(quote.get("f184"))
                    or _scaled_percent(ratio_row.get("f184")),
                    up=_safe_int(quote.get("f104")),
                    down=_safe_int(quote.get("f105")),
                    flat=_safe_int(quote.get("f106")),
                    source="东方财富板块资金流"
                    if quote_rows
                    else "东方财富板块资金流降级",
                )
            )
        if len(sectors) < 10:
            raise ValueError("Eastmoney sector fund flow returned too few rows")
        return sectors

    def _eastmoney_sector_clist_fallback(self) -> list[SectorSnapshot]:
        rows = self._eastmoney_clist(
            "m:90+s:4",
            fields="f12,f14,f3,f6,f62,f184,f104,f105,f106",
            page_size=150,
        )
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
                    main_net_inflow=safe_float(row.get("f62")),
                    main_net_inflow_ratio=safe_float(row.get("f184")),
                    up=_safe_int(row.get("f104")),
                    down=_safe_int(row.get("f105")),
                    flat=_safe_int(row.get("f106")),
                    source="东方财富板块列表兜底",
                )
            )
        return sectors

    def _eastmoney_bkzj_rows(self, key: str) -> list[dict]:
        url = "https://data.eastmoney.com/dataapi/bkzj/getbkzj"
        data = self.http.get_json(
            url,
            params={"key": key, "code": "m:90+s:4"},
            headers={
                "Connection": "close",
                "Referer": "https://data.eastmoney.com/bkzj/hy.html",
            },
        )
        if data.get("rc") != 0:
            raise ValueError(f"Eastmoney bkzj {key} rc={data.get('rc')}")
        payload = data.get("data") or {}
        rows = payload.get("diff") or []
        if not isinstance(rows, list):
            raise ValueError(f"Eastmoney bkzj {key} diff is not a list")
        return [row for row in rows if isinstance(row, dict)]

    def _eastmoney_sector_quote_rows(self, codes: list[str]) -> list[dict]:
        rows: list[dict] = []
        fields = "f12,f14,f3,f6,f62,f184,f104,f105,f106"
        for start in range(0, len(codes), 20):
            secids = ",".join(f"90.{code}" for code in codes[start : start + 20])
            if not secids:
                continue
            rows.extend(self._eastmoney_ulist(secids, fields))
            time.sleep(0.1)
        return rows

    def _eastmoney_ulist(self, secids: str, fields: str) -> list[dict]:
        last_error: Exception | None = None
        for base_url in EASTMONEY_ULIST_BASES:
            url = (
                f"{base_url}/api/qt/ulist.np/get"
                f"?fltt=2&secids={secids}&fields={fields}"
                "&ut=b2884a393a59ad64002292a3e90d46a5"
            )
            try:
                data = self.http.get_json(
                    url,
                    headers={
                        "Connection": "close",
                        "Referer": "https://data.eastmoney.com/bkzj/hy.html",
                    },
                )
                if data.get("rc") != 0:
                    raise ValueError(f"Eastmoney ulist rc={data.get('rc')}")
                payload = data.get("data") or {}
                rows = payload.get("diff") or []
                if isinstance(rows, list):
                    return [row for row in rows if isinstance(row, dict)]
                raise ValueError("Eastmoney ulist diff is not a list")
            except Exception as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        return []

    def broad_etfs(self) -> list[Quote]:
        eastmoney_quotes = self.eastmoney_etfs()
        if self._current_quote_count(eastmoney_quotes) >= 4:
            return eastmoney_quotes
        sina_quotes = self.sina_etfs()
        if self._current_quote_count(sina_quotes) >= 4:
            return sina_quotes
        return eastmoney_quotes + sina_quotes

    def _current_quote_count(self, quotes: list[Quote]) -> int:
        today = datetime.now(CN_TZ).date().isoformat()
        return sum(1 for quote in quotes if quote.trade_date == today and quote.pct_change is not None)

    def eastmoney_etfs(self) -> list[Quote]:
        quotes: list[Quote] = []
        for secid, _ in BROAD_ETFS:
            try:
                data = self._eastmoney_stock_get(secid, "f58,f43,f48,f60,f170,f86")
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
                        trade_date=_timestamp_to_cn_date(data.get("f86")),
                    )
                )
            except Exception:
                continue
        return quotes

    def sina_etfs(self) -> list[Quote]:
        symbols = ",".join(symbol for _, symbol in BROAD_ETFS)
        text = self.http.get_text(
            f"https://hq.sinajs.cn/list={symbols}",
            headers={
                "Connection": "close",
                "Referer": "https://finance.sina.com.cn/",
            },
        )
        quotes: list[Quote] = []
        for symbol, fields in _parse_sina_hq_quotes(text):
            if len(fields) < 31:
                continue
            price = safe_float(fields[3])
            previous_close = safe_float(fields[2])
            if price is None or not previous_close:
                continue
            amount = safe_float(fields[9])
            pct_change = (price / previous_close - 1) * 100
            quotes.append(
                Quote(
                    source="新浪ETF",
                    name=fields[0] or symbol,
                    price=price,
                    previous_close=previous_close,
                    pct_change=pct_change,
                    amount=amount,
                    trade_date=fields[30] if len(fields) > 30 and fields[30] else None,
                )
            )
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
        trade_date = fields[36] if len(fields) > 36 and fields[36] else None
        return Quote(
            source="新浪期货",
            name=fields[0] if fields else "IF主连",
            price=price or 0,
            previous_close=previous_close,
            pct_change=pct_change,
            amount=None,
            trade_date=trade_date,
        )

    def eastmoney_margin_summary(self) -> MarginSnapshot:
        url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
        data = self.http.get_json(
            url,
            params={
                "reportName": "RPTA_RZRQ_LSHJ",
                "columns": "ALL",
                "source": "WEB",
                "sortColumns": "DIM_DATE",
                "sortTypes": "-1",
                "pageNumber": "1",
                "pageSize": "1",
            },
            headers={
                "Connection": "close",
                "Referer": "https://data.eastmoney.com/rzrq/total.html",
            },
        )
        rows = (data.get("result") or {}).get("data") or []
        if not rows:
            raise ValueError("Eastmoney margin summary is empty")
        row = rows[0]
        trade_date = str(row.get("DIM_DATE") or "").split(" ")[0] or None
        return MarginSnapshot(
            source="东方财富融资融券",
            trade_date=trade_date,
            rzrq_balance=safe_float(row.get("RZRQYE")),
            rzrq_balance_change=safe_float(row.get("RZRQYECZ")),
            financing_net_buy=safe_float(row.get("RZJME")),
            short_net_sell=safe_float(row.get("RQJMG")),
            rz_balance=safe_float(row.get("RZYE")),
            rq_balance=safe_float(row.get("RQYE")),
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
        last_error: Exception | None = None
        for base_url in EASTMONEY_TOPIC_BASES:
            url = (
                f"{base_url}/{endpoint}"
                "?ut=7eea3edcaed734bea9cbfc24409ed989"
                "&dpt=wz.ztzt"
                f"&Pageindex=0&pagesize=1000&sort=fbt:asc&date={today}"
            )
            try:
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
            except Exception as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise ValueError(f"{endpoint} failed")

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


def _parse_sina_hq_quotes(text: str) -> list[tuple[str, list[str]]]:
    matches = re.findall(r'var hq_str_([^=]+)="([^"]*)"', text)
    if not matches:
        raise ValueError("Sina response has no quote payload")
    return [(symbol, payload.split(",")) for symbol, payload in matches if payload]


def _parse_sina_market_center_rows(text: str) -> list[dict]:
    payload = text.strip()
    if not payload:
        return []
    if "=" in payload and not payload.startswith("["):
        payload = payload.split("=", 1)[1].strip().rstrip(";")
    data = json.loads(payload)
    if data is None:
        return []
    if not isinstance(data, list):
        raise ValueError("Sina market center response is not a list")
    return [item for item in data if isinstance(item, dict)]


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


def _scaled_percent(value) -> float | None:
    number = safe_float(value)
    if number is None:
        return None
    return number / 100


def _safe_int(value) -> int | None:
    number = safe_float(value)
    if number is None:
        return None
    return int(number)


def _timestamp_to_cn_date(value) -> str | None:
    timestamp = safe_float(value)
    if not timestamp:
        return None
    return datetime.fromtimestamp(timestamp, CN_TZ).date().isoformat()
