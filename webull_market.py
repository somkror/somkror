#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
===============================================================================
 webull_market.py — ดึงบริบทตลาดจาก Webull OpenAPI มาเสริมระบบ MADE
===============================================================================
 MT5 ให้แค่ราคาดัชนี (US30/US100/US500) ซึ่งบอกไม่ได้ว่า "ใครทำให้ขยับ"
 โมดูลนี้เติมสิ่งที่ MT5 ให้ไม่ได้ 4 อย่าง

   1. BREADTH   หุ้นในดัชนีขึ้นกี่ตัว ลงกี่ตัว ใครฉุด ใครหนุน
                -> แยกได้ว่า "ตลาดลง" หรือ "หุ้นไม่กี่ตัวลาก"
   2. SECTOR    เงินไหลเข้าออกกลุ่มไหน (ผ่าน sector ETF ของ S&P)
                -> ยืนยัน rotation ที่เราเห็นจากราคาดัชนี
   3. CROSS     พันธบัตร ทอง น้ำมัน ดอลลาร์ ความผันผวน
                -> ใช้เช็ก regime ว่าตรงกับที่ MT5 บอกไหม
   4. RISK      รวมทุกอย่างเป็นคะแนน risk-on / risk-off

 ใช้งาน
   python webull_market.py                  รายงานเต็ม
   python webull_market.py --json ctx.json  บันทึกให้ GUI อ่าน
   python webull_market.py --raw AAPL       ดู response ดิบ (ไว้ debug ชื่อฟิลด์)
   python webull_market.py --only dow       เลือกเฉพาะบางส่วน
===============================================================================
"""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "webull_config.json")
DEFAULT_OUT = os.path.join(HERE, "market_context.json")

# ---------------------------------------------------------------------------
#  รายชื่อที่ดึง — แยกตามหน้าที่ ไม่ใช่แค่กองรวมกัน
# ---------------------------------------------------------------------------

# US30: Dow ถ่วงด้วย "ราคา" หุ้นแพงมีอิทธิพลสูงสุด จึงเอาตัวราคาสูงเป็นหลัก
# เอาเฉพาะตัวที่ "ราคาสูง" ซึ่งมีอิทธิพลต่อดัชนีจริง ๆ (Dow ถ่วงด้วยราคา)
# ตัวราคาต่ำอย่าง VZ/CSCO/KO ขยับ 1% ก็กระทบดัชนีไม่กี่จุด ตัดออกเพื่อประหยัด request
DOW_NAMES = ["GS", "UNH", "MSFT", "HD", "CAT", "V", "SHW", "MCD", "AXP", "AMGN",
             "TRV", "CRM", "IBM", "HON", "JNJ", "BA", "NVDA", "AAPL"]
DOW_DIVISOR = float(os.environ.get("DOW_DIVISOR", "0.1627"))

# US100: Nasdaq-100 ถ่วงด้วยมูลค่าตลาด ตัวใหญ่ไม่กี่ตัวคุมดัชนีเกือบครึ่ง
NDX_NAMES = ["NVDA", "MSFT", "AAPL", "AMZN", "AVGO", "META", "GOOGL", "TSLA",
             "NFLX", "AMD", "MU"]

# US500: ดูผ่าน sector ETF ชัดกว่าไล่หุ้นทีละตัว เห็น rotation ทันที
SECTOR_ETFS = {
    "XLK": "เทคโนโลยี", "XLF": "การเงิน", "XLE": "พลังงาน",
    "XLV": "สุขภาพ", "XLI": "อุตสาหกรรม", "XLY": "บริโภคฟุ่มเฟือย",
    "XLP": "บริโภคจำเป็น", "XLU": "สาธารณูปโภค", "XLB": "วัตถุดิบ",
    "XLRE": "อสังหา", "XLC": "สื่อสาร",
}

# สินทรัพย์อ้างอิงข้ามตลาด — ใช้ยืนยัน regime ที่ MT5 คำนวณได้
CROSS_ASSETS = {
    "TLT": ("พันธบัตร 20Y+", "yield ลง = TLT ขึ้น"),
    "IEF": ("พันธบัตร 7-10Y", "ตัวแทน yield กลาง"),
    "UUP": ("ดอลลาร์", "ตัวแทน DXY"),
    "GLD": ("ทองคำ", "เทียบกับ GOLDm# ใน MT5"),
    "USO": ("น้ำมัน", "เทียบกับ BRENTCash#"),
    "VIXY": ("ความผันผวน", "ขึ้น = ตลาดกลัว"),
    "HYG": ("หุ้นกู้เสี่ยงสูง", "ลง = เริ่มหนีความเสี่ยง"),
    "SMH": ("เซมิคอนดักเตอร์", "ตัวนำของ US100"),
    "IWM": ("หุ้นเล็ก", "ขึ้น = เชื่อมั่นเศรษฐกิจในประเทศ"),
    "RSP": ("S&P ถ่วงเท่ากัน", "เทียบกับ SPY เพื่อดูการกระจุกตัว"),
    "SPY": ("S&P 500", "ดัชนีอ้างอิง"),
}


# 5 ตัวสำคัญ — โหมดเริ่มต้น ใช้ 1 request ต่อรอบ
#   NVDA  น้ำหนักสูงสุดใน US500/US100
#   MSFT  อยู่ในทั้งสามดัชนี
#   GS    ราคาแพงสุดใน Dow = ตัวลาก US30 อันดับหนึ่ง
#   TLT   พันธบัตรยาว = ทิศทาง yield (driver ของทองและดัชนี)
#   VIXY  ความกลัวของตลาด
CORE_SYMBOLS = {
    "NVDA": ("ผู้นำ US500/US100", "index"),
    "MSFT": ("อยู่ในทั้ง 3 ดัชนี", "index"),
    "GS":   ("ตัวลาก US30", "index"),
    "TLT":  ("พันธบัตร 20Y+", "macro"),
    "VIXY": ("ความผันผวน", "macro"),
}
# หุ้น/ETF สำคัญเพิ่มเติม — ดึงพร้อม core ในชุดเดียว (29 ตัว = 2 request ต่อรอบ)
EXTRA_SYMBOLS = {
    # Mega-cap คุม US100/US500
    "AAPL": "Apple", "AMZN": "Amazon", "GOOGL": "Alphabet", "META": "Meta",
    "AVGO": "Broadcom", "TSLA": "Tesla", "AMD": "AMD", "NFLX": "Netflix", "MU": "Micron",
    # ตัวลาก US30 (ราคาสูง)
    "UNH": "UnitedHealth", "HD": "Home Depot", "CAT": "Caterpillar", "V": "Visa",
    "AXP": "American Express", "AMGN": "Amgen", "IBM": "IBM",
    # ETF ดัชนี / ตัวยืนยันข้ามตลาด
    "SPY": "S&P 500", "QQQ": "Nasdaq-100", "DIA": "Dow 30", "IWM": "หุ้นเล็ก",
    "SMH": "เซมิคอนดักเตอร์", "UUP": "ดอลลาร์", "GLD": "ทองคำ", "HYG": "หุ้นกู้เสี่ยงสูง",
}

# น้ำหนักในดัชนี (% ของดัชนี) — ค่าประมาณ ปรับได้ตามรอบ rebalance
#   US100 / US500 ถ่วงด้วยมูลค่าตลาด ส่วน US30 ถ่วงด้วย "ราคา" คำนวณสดจาก DOW_DIVISOR
#   GOOGL ใส่น้ำหนักรวม GOOG+GOOGL แล้ว
INDEX_WEIGHTS = {
    "US100": {"NVDA": 9.0, "MSFT": 8.0, "AAPL": 7.5, "AMZN": 5.5, "AVGO": 5.0,
              "GOOGL": 5.0, "META": 3.5, "TSLA": 3.0, "AMD": 1.5, "NFLX": 1.3, "MU": 1.0},
    "US500": {"NVDA": 7.5, "MSFT": 6.3, "AAPL": 6.2, "AMZN": 3.9, "GOOGL": 4.0,
              "META": 2.8, "AVGO": 2.6, "TSLA": 2.0, "AMD": 0.8, "NFLX": 0.7, "MU": 0.6,
              "V": 0.9, "UNH": 0.6, "HD": 0.6, "CAT": 0.5, "GS": 0.4, "IBM": 0.4,
              "AXP": 0.4, "AMGN": 0.3},
}
DOW_MEMBERS = ["GS", "MSFT", "CAT", "HD", "V", "UNH", "AXP", "AMGN", "IBM",
               "AAPL", "NVDA", "AMZN"]
INDEX_ETF = {"US100": "QQQ", "US500": "SPY", "US30": "DIA"}

# โหมด: core (5 ตัว, ค่าเริ่มต้น) หรือ full (ชุดเต็ม ~55 ตัว ใช้ 3 request)
WEBULL_MODE = os.environ.get("WEBULL_MODE", "core").lower()


# ---------------------------------------------------------------------------
#  การตั้งค่า + ตัวเชื่อม
# ---------------------------------------------------------------------------

@dataclass
class WebullConfig:
    app_key: str
    app_secret: str
    region: str = "th"
    endpoint: str = "api.webull.co.th"

    @staticmethod
    def load(path: str = CONFIG_PATH) -> Optional["WebullConfig"]:
        k, s = os.environ.get("WEBULL_APP_KEY"), os.environ.get("WEBULL_APP_SECRET")
        if k and s:
            return WebullConfig(k, s, os.environ.get("WEBULL_REGION", "th"),
                                os.environ.get("WEBULL_ENDPOINT", "api.webull.co.th"))
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    d = json.load(f)
                return WebullConfig(d["app_key"], d["app_secret"],
                                    d.get("region", "th"),
                                    d.get("endpoint", "api.webull.co.th"))
            except Exception as e:
                print(f"อ่าน config ไม่ได้: {e}")
        return None


@dataclass
class Quote:
    """
    เก็บแท่งรายวันหลายแท่ง (ใหม่->เก่า) เพื่อคำนวณได้มากกว่าการเปลี่ยนแปลงวันเดียว
    closes/highs/lows/vols index 0 = วันล่าสุด
    """
    symbol: str
    price: float = 0.0
    prev_close: float = 0.0
    closes: List[float] = None
    highs: List[float] = None
    lows: List[float] = None
    vols: List[float] = None

    def __post_init__(self):
        for n in ("closes", "highs", "lows", "vols"):
            if getattr(self, n) is None:
                setattr(self, n, [])

    @property
    def pct(self) -> float:
        return (self.price / self.prev_close - 1) * 100 if self.prev_close > 0 else 0.0

    @property
    def abs_change(self) -> float:
        return self.price - self.prev_close

    @property
    def dow_points(self) -> float:
        return self.abs_change / DOW_DIVISOR if DOW_DIVISOR else 0.0

    def _pct_back(self, n: int) -> float:
        """ผลตอบแทนย้อนหลัง n วัน — ใช้ดูว่าการเคลื่อนไหววันนี้สอดคล้องกับเทรนด์ไหม"""
        if len(self.closes) <= n or self.closes[n] <= 0:
            return 0.0
        return (self.closes[0] / self.closes[n] - 1) * 100

    @property
    def pct_5d(self) -> float:
        return self._pct_back(5)

    @property
    def pct_20d(self) -> float:
        return self._pct_back(20)

    @property
    def vol_ratio(self) -> float:
        """ปริมาณวันนี้เทียบค่าเฉลี่ย 20 วัน — >1.5 คือมีของจริงเข้ามา"""
        if len(self.vols) < 6 or self.vols[0] <= 0:
            return 0.0
        hist = [v for v in self.vols[1:21] if v > 0]
        if not hist:
            return 0.0
        return self.vols[0] / (sum(hist) / len(hist))

    @property
    def range_pos(self) -> float:
        """ราคาอยู่ตรงไหนของกรอบ 20 วัน (0=ต่ำสุด 100=สูงสุด)"""
        hs = [h for h in self.highs[:20] if h > 0]
        ls = [l for l in self.lows[:20] if l > 0]
        if not hs or not ls:
            return 50.0
        hi, lo = max(hs), min(ls)
        if hi <= lo:
            return 50.0
        return max(0.0, min(100.0, (self.price - lo) / (hi - lo) * 100))


class Webull:
    """ห่อ SDK ไว้ ไม่ให้ error ของมันทะลุไปล้มระบบหลัก และจำ category ที่ใช้ได้"""

    def __init__(self, cfg: WebullConfig):
        self.cfg = cfg
        self.client = None
        self.last_error = ""
        self._cat_cache: Dict[str, str] = {}
        self._categories: List[str] = []
        self._all: Dict[str, Quote] = {}      # รวมทุกตัวที่ดึงมา ใช้วิเคราะห์ข้ามชุด

        # --- การคุมอัตราการยิง API ---
        self.min_interval = float(os.environ.get("WEBULL_MIN_INTERVAL", "0.35"))
        self.budget = int(os.environ.get("WEBULL_MAX_REQUESTS", "90"))
        self._used = 0                 # ใช้ไปกี่ request ในรอบนี้
        self._last_call = 0.0
        self._denied: set = set()      # symbol ที่ไม่มีสิทธิ์ดู จะไม่ยิงซ้ำ
        self._throttled = False        # โดน TOO_MANY_REQUESTS แล้วหยุดรอบนี้
        self._no_sub = 0               # นับ NOT_SUBSCRIBED ติดกัน
        self._all_fresh: set = set()   # ดึงสำเร็จแล้วในรอบนี้ ไม่ยิงซ้ำ
        self.unsubscribed = False      # ทั้งบัญชียังไม่ได้สมัคร market data

    BATCH_MAX = 20       # Webull จำกัด 1–20 symbol ต่อ request (ILLEGAL_PARAMETER ถ้าเกิน)
    BAR_COUNT = 40       # แท่งรายวันที่ต้องใช้: pct_20d ใช้ 21, vol_ratio ใช้ 20
    FALLBACK_MAX = 6     # ตัวที่ batch ไม่คืนมา ลองเดี่ยวได้ไม่เกินนี้

    def _gate(self) -> bool:
        """หน่วงเวลาระหว่าง request และหยุดเมื่อใช้งบครบ — กันโดน rate limit"""
        if self._throttled or self.unsubscribed or self._used >= self.budget:
            return False
        gap = time.time() - self._last_call
        if gap < self.min_interval:
            time.sleep(self.min_interval - gap)
        self._last_call = time.time()
        self._used += 1
        return True


    SUB_HINT = ("บัญชียังไม่ได้สมัคร market data (STOCK QUOTES)\n"
                "   การเชื่อมต่อและ token ถูกต้องแล้ว ติดแค่สิทธิ์ดูราคา\n"
                "   แก้ที่ developer.webull.co.th > Market Data > สมัคร STOCK QUOTES\n"
                "   ระหว่างนี้ระบบจะข้ามส่วน Webull ไป ส่วนอื่นยังทำงานปกติ")

    def _mark_no_sub(self, symbol: str) -> None:
        """
        ถ้าโดน NOT_SUBSCRIBED ติดกันหลายตัว แปลว่าทั้งบัญชีไม่มีสิทธิ์
        ไม่ใช่เฉพาะ symbol นั้น จึงหยุดทั้งรอบ ไม่ยิงต่อให้เปลืองโควตา
        """
        self._denied.add(symbol)
        self._no_sub += 1
        if self._no_sub >= 3:
            self.unsubscribed = True
            self.last_error = self.SUB_HINT

    @property
    def stats(self) -> dict:
        return {"requests": self._used, "budget": self.budget,
                "denied": sorted(self._denied), "throttled": self._throttled,
                "unsubscribed": self.unsubscribed}

    def connect(self) -> bool:
        # SDK เขียน log ลงไฟล์ทุก request ถ้าไม่ปิดจะโตเป็นสิบ MB ภายในวันเดียว
        import logging
        for name in ("webull", "webull.core", "webull.core.client"):
            lg = logging.getLogger(name)
            lg.setLevel(logging.CRITICAL)
            lg.propagate = False
            for h in list(lg.handlers):
                lg.removeHandler(h)

        try:
            from webull.core.client import ApiClient
            from webull.data.data_client import DataClient
            from webull.data.common.category import Category
        except ImportError:
            self.last_error = "ไม่พบ SDK -> pip install webull-openapi-python-sdk"
            return False
        try:
            api = ApiClient(self.cfg.app_key, self.cfg.app_secret, self.cfg.region)
            if self.cfg.endpoint:
                api.add_endpoint(self.cfg.region, self.cfg.endpoint)
            self.client = DataClient(api)

            # ⚠️ ห้ามไล่ยิงทุก category
            # เวอร์ชันก่อนหน้าวนทุกค่าที่ขึ้นต้นด้วย US (US_OPTION/US_FUTURES/
            # US_CRYPTO/US_EVENT) ทำให้ยิง API เกินจำเป็น 5 เท่า โดนทั้ง
            # UNSUPPORTED_CATEGORY และ TOO_MANY_REQUESTS จนเกือบถูกล็อกบัญชี
            names = [c.name for c in Category]
            self._categories = (["US_STOCK"] if "US_STOCK" in names
                                else names[:1])
            return True
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            return False

    def raw(self, symbol: str, timespan: str = "D"):
        """คืน response ดิบไว้ตรวจชื่อฟิลด์ตอน debug"""
        from webull.data.common.timespan import Timespan
        ts = getattr(Timespan, timespan, Timespan.D).name
        for cat in self._categories:
            try:
                res = self.client.market_data.get_batch_history_bar(
                    [symbol], cat, ts, count='40')
                if getattr(res, "status_code", None) == 200:
                    return cat, res.json()
            except Exception as e:
                self.last_error = f"{symbol}/{cat}: {type(e).__name__}: {e}"
        return None, None

    # -- ตัวช่วยอ่านค่าจาก response ที่ชื่อฟิลด์อาจต่างกันไป --
    @staticmethod
    def _rows(payload):
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for k in ("data", "bars", "result", "items", "list"):
                v = payload.get(k)
                if isinstance(v, list):
                    # รูปแบบ Webull TH: {"result":[{"symbol":..,"result":[แท่ง...]}]}
                    if v and isinstance(v[0], dict) and isinstance(v[0].get("result"), list):
                        return v[0]["result"]
                    return v
                if isinstance(v, dict):
                    for k2 in ("bars", "list", "items"):
                        if isinstance(v.get(k2), list):
                            return v[k2]
        return []

    @staticmethod
    def _num(row, *names) -> float:
        for n in names:
            if isinstance(row, dict) and row.get(n) not in (None, ""):
                try:
                    return float(row[n])
                except (TypeError, ValueError):
                    pass
        return 0.0

    # -- batch: แกะ response ที่รวมหลาย symbol มาในก้อนเดียว -----------------
    @staticmethod
    def _by_symbol(payload, wanted):
        """
        /market-data/stocks/bars/list ส่งหลาย symbol มาในก้อนเดียว
        แต่รูปร่าง payload ต่างกันได้หลายแบบ จึงไล่เช็กทุกแบบที่เป็นไปได้
        คืน dict: symbol -> list ของแท่ง
        """
        out = {}
        up = {s.upper(): s for s in wanted}

        def take(sym, rows):
            s = up.get(str(sym).upper())
            if s and isinstance(rows, list) and rows:
                out.setdefault(s, rows)

        def walk(node):
            if isinstance(node, list):
                for item in node:
                    walk(item)
                return
            if not isinstance(node, dict):
                return
            sym = (node.get("symbol") or node.get("ticker") or
                   node.get("instrument_id") or node.get("disSymbol"))
            if sym:
                for k in ("result", "bars", "data", "list", "items", "candles", "klines"):
                    if isinstance(node.get(k), list):
                        take(sym, node[k])
                        return
                # บางรุ่นแบนราบ: หนึ่ง dict = หนึ่งแท่ง มี symbol ติดมาด้วย
                if any(k in node for k in ("close", "c", "closePrice")):
                    s = up.get(str(sym).upper())
                    if s:
                        out.setdefault(s, []).append(node)
                    return
            for k in ("data", "result", "list", "items", "bars"):
                if k in node:
                    walk(node[k])

        walk(payload)
        return out

    def _quote_from_rows(self, symbol, rows):
        """สร้าง Quote จาก list ของแท่ง — ใช้ร่วมกันทั้งทางเดี่ยวและทาง batch"""
        if not isinstance(rows, list) or len(rows) < 2:
            return None

        def ts(r):
            return str(self._num(r, "timestamp", "tradeTime", "time", "t") or
                       r.get("tradeDate", r.get("date", "")))

        a, b = rows[0], rows[1]
        try:
            last_is_first = ts(a) >= ts(b)
        except Exception:
            last_is_first = True
        ordered = rows if last_is_first else list(reversed(rows))
        g = self._num
        px = g(ordered[0], "close", "c", "closePrice", "close_price")
        pv = g(ordered[1], "close", "c", "closePrice", "close_price")
        if px <= 0 or pv <= 0:
            return None
        return Quote(
            symbol, px, pv,
            closes=[g(r, "close", "c", "closePrice", "close_price") for r in ordered],
            highs=[g(r, "high", "h", "highPrice") for r in ordered],
            lows=[g(r, "low", "l", "lowPrice") for r in ordered],
            vols=[g(r, "volume", "v", "tradeVolume") for r in ordered])

    def _classify_error(self, msg, symbols):
        """แปลข้อความ error เป็นสถานะ แล้วบอกว่าควรหยุดทั้งรอบหรือไม่"""
        if "TOO_MANY_REQUESTS" in msg or "429" in msg:
            self._throttled = True
            self.last_error = ("โดนจำกัดอัตราการเรียก (TOO_MANY_REQUESTS) "
                               "— หยุดรอบนี้ ลดจำนวน symbol หรือเพิ่มรอบอัปเดต")
            return True
        if "NOT_SUBSCRIBED" in msg:
            for s in symbols:
                self._mark_no_sub(s)
            return True
        return False

    def quote(self, symbol: str) -> Optional[Quote]:
        """ดึงแท่งรายวันของตัวเดียว — ใช้เป็นทางสำรองเมื่อ batch ใช้ไม่ได้"""
        from webull.data.common.timespan import Timespan
        if symbol in self._denied or self._throttled or self.unsubscribed:
            return None
        cats = ([self._cat_cache[symbol]] if symbol in self._cat_cache
                else self._categories)
        for cat in cats:
            if not self._gate():
                return None
            try:
                # get_history_bar เลิกใช้แล้ว (endpoint bars/get ปิดไป) SDK
                # แปลงไปเรียก bars/list ให้เอง จึงส่ง list ตัวเดียวตรง ๆ แทน
                res = self.client.market_data.get_batch_history_bar(
                    [symbol], cat, Timespan.D.name, count=str(self.BAR_COUNT))
            except Exception as e:
                msg = f"{type(e).__name__}: {e}"
                self.last_error = f"{symbol}: {msg}"
                if self._classify_error(msg, [symbol]):
                    return None
                continue
            if getattr(res, "status_code", None) != 200:
                code = getattr(res, "status_code", "?")
                body = str(getattr(res, "text", ""))[:160]
                self.last_error = f"{symbol}: HTTP {code} {body}"
                if self._classify_error(f"{code} {body}", [symbol]):
                    return None
                continue
            payload = res.json()
            rows = (self._by_symbol(payload, [symbol]).get(symbol) or
                    self._rows(payload))
            q = self._quote_from_rows(symbol, rows)
            if q:
                self._cat_cache[symbol] = cat
                return q
        return None

    def quotes(self, symbols: List[str]) -> Dict[str, Quote]:
        """
        ดึงหลาย symbol ด้วย endpoint batch — หัวใจของการลดจำนวน request
        เดิมยิงตัวละ 1 request (55 ตัว = 55 request) ตอนนี้ยิงก้อนละ
        BATCH_MAX ตัว เหลือ 2 request ต่อรอบ
        """
        from webull.data.common.timespan import Timespan
        out: Dict[str, Quote] = {s: self._all[s] for s in symbols
                                 if s in self._all_fresh and s in self._all}
        want = [s for s in symbols
                if s not in self._denied and s not in self._all_fresh]
        if not want or self._throttled or self.unsubscribed:
            return out

        cat = self._categories[0] if self._categories else "US_STOCK"
        pending: List[str] = []

        for i in range(0, len(want), self.BATCH_MAX):
            chunk = want[i:i + self.BATCH_MAX]
            if not self._gate():
                break
            try:
                res = self.client.market_data.get_batch_history_bar(
                    chunk, cat, Timespan.D.name, count=str(self.BAR_COUNT))
            except Exception as e:
                msg = f"{type(e).__name__}: {e}"
                self.last_error = f"batch({len(chunk)} ตัว): {msg}"
                if self._classify_error(msg, chunk):
                    break
                pending += chunk
                continue
            if getattr(res, "status_code", None) != 200:
                code = getattr(res, "status_code", "?")
                body = str(getattr(res, "text", ""))[:160]
                self.last_error = f"batch: HTTP {code} {body}"
                if self._classify_error(f"{code} {body}", chunk):
                    break
                pending += chunk
                continue

            payload = res.json()
            found = self._by_symbol(payload, chunk)
            if not found:
                # แกะไม่ออก — เก็บ response ดิบไว้ให้ตรวจรูปร่างข้อมูล
                try:
                    with open(os.path.join(HERE, "webull_last_raw.json"), "w",
                              encoding="utf-8") as f:
                        json.dump({"symbols": chunk, "category": cat,
                                   "payload": payload}, f, ensure_ascii=False, indent=2)
                    self.last_error = ("แกะข้อมูลไม่ออก — บันทึก response ดิบไว้ที่ "
                                       "webull_last_raw.json")
                except Exception:
                    pass
            for s in chunk:
                q = self._quote_from_rows(s, found.get(s))
                if q:
                    out[s] = q
                    self._cat_cache[s] = cat
                else:
                    pending.append(s)

        # ตัวที่ batch ไม่คืนมา ลองทีละตัวครั้งเดียว แต่ไม่เกิน FALLBACK_MAX
        # เพื่อไม่ให้ย้อนกลับไปยิงทีละตัวทั้งชุดเหมือนเดิม
        if pending and not self._throttled and not self.unsubscribed:
            for s in pending[:self.FALLBACK_MAX]:
                q = self.quote(s)
                if q:
                    out[s] = q
            missed = [s for s in pending if s not in out]
            if missed:
                self.last_error = (self.last_error or
                                   f"ไม่ได้ข้อมูล {len(missed)} ตัว: "
                                   + ", ".join(missed[:8]))

        self._all.update(out)
        self._all_fresh.update(out.keys())
        return out


# ---------------------------------------------------------------------------
#  การวิเคราะห์
# ---------------------------------------------------------------------------

def breadth(quotes: Dict[str, Quote], weighted: bool = False) -> dict:
    """
    ตอบคำถามเดียว: ดัชนีขยับเพราะตลาดทั้งตลาด หรือเพราะหุ้นไม่กี่ตัว
    weighted=True ใช้จุดดัชนีแบบ Dow (ถ่วงด้วยราคา) ไม่งั้นใช้ % ล้วน
    """
    ok = [q for q in quotes.values() if q.prev_close > 0]
    if not ok:
        return {"ok": False, "error": "ไม่มีข้อมูล"}

    up = [q for q in ok if q.pct > 0]
    down = [q for q in ok if q.pct < 0]
    key = (lambda q: q.dow_points) if weighted else (lambda q: q.pct)
    ranked = sorted(ok, key=key)
    total = sum(key(q) for q in ok)
    avg = sum(q.pct for q in ok) / len(ok)

    top3 = sum(key(q) for q in (ranked[:3] if total < 0 else ranked[-3:]))
    conc = abs(top3 / total) * 100 if total else 0.0

    maj_up = len(up) >= len(ok) * 0.6
    maj_down = len(down) >= len(ok) * 0.6
    divergent = (maj_up and total < 0) or (maj_down and total > 0)

    if divergent:
        verdict = ("⚠ ดัชนีสวนทางหุ้นส่วนใหญ่ — ถูกลากด้วยตัวหนักไม่กี่ตัว "
                   "ไม่ใช่ทิศทางตลาดจริง")
        grade = "DIVERGENT"
    elif conc > 120:
        verdict = "ดัชนีกระจุกตัวที่หุ้นไม่กี่ตัว — ระวังการกลับตัว"
        grade = "CONCENTRATED"
    elif len(down) >= len(ok) * 0.7:
        verdict = "ลงทั้งกระดาน (breadth แย่จริง)"
        grade = "BROAD_DOWN"
    elif len(up) >= len(ok) * 0.7:
        verdict = "ขึ้นทั้งกระดาน (breadth ดีจริง)"
        grade = "BROAD_UP"
    else:
        verdict = "ผสม ไม่มีข้อสรุปชัด"
        grade = "MIXED"

    def fmt(q):
        d = {"symbol": q.symbol, "pct": round(q.pct, 2)}
        if weighted:
            d["points"] = round(q.dow_points, 1)
        return d

    return {"ok": True, "counted": len(ok), "up": len(up), "down": len(down),
            "avg_pct": round(avg, 2), "grade": grade, "verdict": verdict,
            "concentration_pct": round(conc, 1),
            "total_points": round(total, 1) if weighted else None,
            "drags": [fmt(q) for q in ranked[:5]],
            "lifts": [fmt(q) for q in reversed(ranked[-5:])]}


def sectors(quotes: Dict[str, Quote]) -> dict:
    """จัดอันดับกลุ่มอุตสาหกรรม — เห็น rotation ตรง ๆ"""
    rows = [{"etf": s, "name": SECTOR_ETFS.get(s, s), "pct": round(q.pct, 2)}
            for s, q in quotes.items() if q.prev_close > 0]
    rows.sort(key=lambda r: r["pct"], reverse=True)
    if not rows:
        return {"ok": False}

    # กลุ่มเชิงรับ vs เชิงรุก บอกอารมณ์ตลาดได้ดีกว่าดูดัชนีเฉย ๆ
    defensive = [r["pct"] for r in rows if r["etf"] in ("XLP", "XLU", "XLV", "XLRE")]
    cyclical = [r["pct"] for r in rows if r["etf"] in ("XLK", "XLY", "XLF", "XLI", "XLC")]
    d_avg = sum(defensive) / len(defensive) if defensive else 0.0
    c_avg = sum(cyclical) / len(cyclical) if cyclical else 0.0
    tilt = c_avg - d_avg

    return {"ok": True, "ranking": rows,
            "defensive_avg": round(d_avg, 2), "cyclical_avg": round(c_avg, 2),
            "tilt": round(tilt, 2),
            "mood": ("เงินเข้ากลุ่มเชิงรุก = risk-on" if tilt > 0.3 else
                     "เงินหนีเข้ากลุ่มเชิงรับ = risk-off" if tilt < -0.3 else
                     "ไม่เอียงชัด")}


def cross_assets(quotes: Dict[str, Quote]) -> dict:
    rows = []
    for s, q in quotes.items():
        if q.prev_close <= 0:
            continue
        label, note = CROSS_ASSETS.get(s, (s, ""))
        rows.append({"symbol": s, "name": label, "pct": round(q.pct, 2), "note": note})
    rows.sort(key=lambda r: r["pct"], reverse=True)

    g = {q.symbol: q.pct for q in quotes.values()}
    signals = []
    if "VIXY" in g and g["VIXY"] > 3:
        signals.append("ความผันผวนพุ่ง — ลดขนาดไม้")
    if "HYG" in g and g["HYG"] < -0.5:
        signals.append("หุ้นกู้เสี่ยงสูงถูกขาย — เงินเริ่มหนีความเสี่ยง")
    if "TLT" in g and g["TLT"] < -1:
        signals.append("พันธบัตรร่วง = yield พุ่ง — กดดันหุ้นเติบโตและทอง")
    if "SPY" in g and "RSP" in g and (g["SPY"] - g["RSP"]) > 0.5:
        signals.append("SPY นำ RSP มาก — ตลาดพึ่งหุ้นใหญ่ไม่กี่ตัว")
    if "SMH" in g and g["SMH"] < -1.5:
        signals.append("ชิปถูกเทขาย — ตัวนำของ US100 อ่อนแรง")
    return {"ok": bool(rows), "rows": rows, "signals": signals}


INDEX_PROXY = {"DIA": "US30", "QQQ": "US100", "SPY": "US500", "IWM": "หุ้นเล็ก"}


def index_momentum(quotes: Dict[str, Quote]) -> dict:
    """
    จัดอันดับดัชนีด้วย ETF ตัวแทน — ใช้ cross-check กับอันดับที่ MADE คำนวณจาก MT5
    ถ้าสองฝั่งบอกตรงกัน ความมั่นใจสูงขึ้นมาก
    """
    rows = []
    for sym, name in INDEX_PROXY.items():
        q = quotes.get(sym)
        if not q or q.prev_close <= 0:
            continue
        rows.append({"symbol": sym, "name": name,
                     "d1": round(q.pct, 2), "d5": round(q.pct_5d, 2),
                     "d20": round(q.pct_20d, 2),
                     "range_pos": round(q.range_pos, 0),
                     "vol_ratio": round(q.vol_ratio, 2)})
    rows.sort(key=lambda r: r["d5"], reverse=True)
    note = ""
    if len(rows) >= 2:
        best, worst = rows[0], rows[-1]
        if best["d5"] - worst["d5"] > 1.5:
            note = (f"รอบ 5 วัน {best['name']} นำ {worst['name']} "
                    f"อยู่ {best['d5'] - worst['d5']:.1f}% — rotation ชัดเจน")
        else:
            note = "ดัชนีเคลื่อนไหวใกล้เคียงกัน ยังไม่มี rotation ชัด"
    return {"ok": bool(rows), "ranking": rows, "note": note}


def unusual_volume(all_quotes: Dict[str, Quote], limit: int = 8) -> dict:
    """
    หาตัวที่ปริมาณผิดปกติ — ราคาขยับพร้อมวอลุ่มสูงคือของจริง
    ขยับโดยไม่มีวอลุ่มมักเป็น noise
    """
    rows = []
    for q in all_quotes.values():
        vr = q.vol_ratio
        if vr >= 1.5 and abs(q.pct) >= 0.5:
            rows.append({"symbol": q.symbol, "pct": round(q.pct, 2),
                         "vol_ratio": round(vr, 2),
                         "kind": "แรงซื้อจริง" if q.pct > 0 else "แรงขายจริง"})
    rows.sort(key=lambda r: r["vol_ratio"], reverse=True)
    return {"ok": bool(rows), "rows": rows[:limit]}


def extremes(all_quotes: Dict[str, Quote]) -> dict:
    """ตัวที่อยู่ปลายกรอบ 20 วัน — ใกล้ breakout หรือ breakdown"""
    hi = [{"symbol": q.symbol, "pos": round(q.range_pos), "pct": round(q.pct, 2)}
          for q in all_quotes.values() if q.range_pos >= 90]
    lo = [{"symbol": q.symbol, "pos": round(q.range_pos), "pct": round(q.pct, 2)}
          for q in all_quotes.values() if q.range_pos <= 10]
    hi.sort(key=lambda r: -r["pos"]); lo.sort(key=lambda r: r["pos"])
    return {"ok": bool(hi or lo), "near_high": hi[:8], "near_low": lo[:8]}


def risk_score(bd: dict, sec: dict, cr: dict) -> dict:
    """รวมทุกอย่างเป็นคะแนนเดียว -10 (risk-off สุด) ถึง +10 (risk-on สุด)"""
    score, why = 0.0, []
    for name, b in bd.items():
        if not b.get("ok"):
            continue
        if b["grade"] == "BROAD_UP":
            score += 1.5; why.append(f"{name}: ขึ้นทั้งกระดาน")
        elif b["grade"] == "BROAD_DOWN":
            score -= 1.5; why.append(f"{name}: ลงทั้งกระดาน")
        elif b["grade"] in ("DIVERGENT", "CONCENTRATED"):
            score -= 0.8; why.append(f"{name}: ฐานแคบ ไม่น่าไว้ใจ")
    if sec.get("ok"):
        score += max(-2.0, min(2.0, sec["tilt"]))
        why.append(f"กลุ่มอุตสาหกรรม: {sec['mood']}")
    if cr.get("ok"):
        score -= 0.7 * len(cr["signals"])
        why += cr["signals"]
    score = max(-10.0, min(10.0, score))
    label = ("RISK-ON ชัดเจน" if score >= 3 else "RISK-ON อ่อน ๆ" if score >= 1 else
             "RISK-OFF ชัดเจน" if score <= -3 else "RISK-OFF อ่อน ๆ" if score <= -1 else
             "เป็นกลาง")
    return {"score": round(score, 1), "label": label, "reasons": why}


def _dw(text: str) -> int:
    """ความกว้างที่เห็นบนจอ — สระบน/ล่างและวรรณยุกต์ไทยไม่กินช่อง"""
    import unicodedata
    return sum(0 if unicodedata.category(ch) == "Mn" else 1 for ch in str(text))


def pad(text: str, width: int) -> str:
    """เติมช่องว่างตามความกว้างที่เห็นจริง ให้ตารางภาษาไทยตรงคอลัมน์"""
    text = str(text)
    return text + " " * max(0, width - _dw(text))


def core_snapshot(quotes: Dict[str, Quote]) -> dict:
    """สรุป 5 ตัวสำคัญ: หุ้นนำดัชนีไปทางไหน + yield/ความกลัวบอกอะไร"""
    rows = []
    for s, (name, kind) in CORE_SYMBOLS.items():
        q = quotes.get(s)
        if not q or q.prev_close <= 0:
            continue
        rows.append({"symbol": s, "name": name, "kind": kind,
                     "d1": round(q.pct, 2), "d5": round(q.pct_5d, 2),
                     "d20": round(q.pct_20d, 2), "range_pos": round(q.range_pos, 0),
                     "vol_ratio": round(q.vol_ratio, 2)})
    g = {r["symbol"]: r for r in rows}
    signals, score = [], 0.0

    leaders = [g[s]["d1"] for s in ("NVDA", "MSFT", "GS") if s in g]
    if leaders:
        up = sum(1 for x in leaders if x > 0); dn = sum(1 for x in leaders if x < 0)
        if up == len(leaders):
            score += 1.5; signals.append("หุ้นนำดัชนีขึ้นพร้อมกัน — หนุน US30/US100/US500")
        elif dn == len(leaders):
            score -= 1.5; signals.append("หุ้นนำดัชนีลงพร้อมกัน — กดดันดัชนีทั้งสาม")
        else:
            signals.append("หุ้นนำดัชนีแยกทาง — ดัชนีอาจเคลื่อนไม่เท่ากัน")
    if "NVDA" in g and "GS" in g and abs(g["NVDA"]["d1"] - g["GS"]["d1"]) > 1.5:
        lead = "US100" if g["NVDA"]["d1"] > g["GS"]["d1"] else "US30"
        signals.append(f"NVDA กับ GS ห่างกันมาก — {lead} น่าจะแข็งกว่า")
    if "TLT" in g:
        t = g["TLT"]["d1"]
        if t < -0.7:
            score -= 1.0; signals.append("TLT ร่วง = yield ขึ้น — กดดันทองและหุ้นเติบโต")
        elif t > 0.7:
            score += 0.5; signals.append("TLT ขึ้น = yield ลง — เป็นบวกกับทองและ US100")
    if "VIXY" in g:
        v = g["VIXY"]["d1"]
        if v > 3:
            score -= 1.5; signals.append("VIXY พุ่ง — ตลาดกลัว ลดขนาดไม้")
        elif v < -3:
            score += 0.5; signals.append("VIXY ลดลงแรง — ความกลัวคลาย")
    for r in rows:
        if r["vol_ratio"] >= 1.5 and abs(r["d1"]) >= 0.5:
            signals.append(f"{r['symbol']} ขยับ {r['d1']:+.2f}% พร้อมวอลุ่ม "
                           f"{r['vol_ratio']}x — แรงจริง")
    score = max(-10.0, min(10.0, score))
    label = ("RISK-ON ชัดเจน" if score >= 3 else "RISK-ON อ่อน ๆ" if score >= 1 else
             "RISK-OFF ชัดเจน" if score <= -3 else "RISK-OFF อ่อน ๆ" if score <= -1 else
             "เป็นกลาง")
    return {"ok": bool(rows), "rows": rows, "signals": signals,
            "risk": {"score": round(score, 1), "label": label, "reasons": signals}}


def index_pulse(quotes: Dict[str, Quote]) -> dict:
    """
    ถ่วงน้ำหนักหุ้นตัวใหญ่ตามสัดส่วนในดัชนี เพื่อบอกว่า "ใคร" ลากดัชนีวันนี้
      contrib = น้ำหนัก% × การเปลี่ยนแปลง% / 100  → หน่วยเป็น % ของดัชนี
      US30    = ราคาเปลี่ยน / DOW_DIVISOR        → หน่วยเป็นจุด Dow
    เทียบกับ ETF ของดัชนี: ส่วนที่เหลือ (rest) บอกว่าหุ้นที่เหลือทั้งตลาดไปทางเดียวกันไหม
    """
    out, score, sig = {}, 0.0, []

    for idx, wmap in INDEX_WEIGHTS.items():
        rows = []
        for sym, w in wmap.items():
            q = quotes.get(sym)
            if not q or q.prev_close <= 0:
                continue
            rows.append({"symbol": sym, "weight": w, "d1": round(q.pct, 2),
                         "d5": round(q.pct_5d, 2),
                         "contrib": round(w * q.pct / 100, 3),
                         "contrib5": round(w * q.pct_5d / 100, 3)})
        if not rows:
            continue
        cov = sum(r["weight"] for r in rows)
        tot = sum(r["contrib"] for r in rows)
        tot5 = sum(r["contrib5"] for r in rows)
        etf = quotes.get(INDEX_ETF[idx])
        etf_d1 = round(etf.pct, 2) if etf and etf.prev_close > 0 else None
        rest = (round((etf_d1 - tot) / max(1e-6, (100 - cov) / 100), 2)
                if etf_d1 is not None and cov < 100 else None)
        rows.sort(key=lambda r: r["contrib"])
        out[idx] = {"coverage": round(cov, 1), "contrib": round(tot, 2),
                    "contrib5": round(tot5, 2), "basket_avg": round(tot / cov * 100, 2),
                    "etf": INDEX_ETF[idx], "etf_d1": etf_d1, "rest": rest,
                    "drags": [r for r in rows if r["contrib"] < 0][:4],
                    "lifts": [r for r in reversed(rows) if r["contrib"] > 0][:4],
                    "rows": rows}

    # US30: ถ่วงด้วยราคา — จุดที่แต่ละตัวลากดัชนีได้ตรง ๆ
    rows = []
    for sym in DOW_MEMBERS:
        q = quotes.get(sym)
        if not q or q.prev_close <= 0:
            continue
        rows.append({"symbol": sym, "price": round(q.price, 2), "d1": round(q.pct, 2),
                     "points": round(q.dow_points, 1)})
    if rows:
        pts = sum(r["points"] for r in rows)
        dia = quotes.get("DIA")
        level = dia.prev_close * 100 if dia and dia.prev_close > 0 else 0
        etf_d1 = round(dia.pct, 2) if dia and dia.prev_close > 0 else None
        etf_pts = round(level * etf_d1 / 100, 1) if level and etf_d1 is not None else None
        rows.sort(key=lambda r: r["points"])
        out["US30"] = {"points": round(pts, 1),
                       "contrib": round(pts / level * 100, 2) if level else None,
                       "etf": "DIA", "etf_d1": etf_d1, "etf_points": etf_pts,
                       "rest_points": round(etf_pts - pts, 1) if etf_pts is not None else None,
                       "drags": [r for r in rows if r["points"] < 0][:4],
                       "lifts": [r for r in reversed(rows) if r["points"] > 0][:4],
                       "rows": rows}

    # ---- แปลงเป็นสัญญาณ + คะแนน ----
    for idx in ("US100", "US500", "US30"):
        p = out.get(idx)
        if not p:
            continue
        c = p.get("contrib")
        if c is None:
            continue
        if c >= 0.25:
            score += 0.75
        elif c <= -0.25:
            score -= 0.75
        top = (p["drags"] if c < 0 else p["lifts"])[:2]
        if abs(c) >= 0.25 and top:
            who = ", ".join(x["symbol"] for x in top)
            sig.append(f"{idx}: หุ้นใหญ่{'ลาก' if c < 0 else 'ดัน'} {c:+.2f}% ของดัชนี (หลัก ๆ {who})")
        rest = p.get("rest") if idx != "US30" else (
            p["rest_points"] / (p["points"] or 1) if p.get("rest_points") is not None and p["points"] else None)
        if idx != "US30" and rest is not None and abs(c) >= 0.25 and rest * c < 0 and abs(rest) >= 0.2:
            score -= 0.5
            sig.append(f"{idx}: หุ้นที่เหลือไปคนละทางกับตัวใหญ่ ({rest:+.2f}%) — ฐานแคบ ระวังกลับตัว")
        if idx == "US30" and p.get("rest_points") is not None and abs(p["points"]) >= 100 \
                and p["rest_points"] * p["points"] < 0 and abs(p["rest_points"]) >= 60:
            score -= 0.5
            sig.append(f"US30: ตัวราคาสูง {p['points']:+.0f} จุด แต่ที่เหลือ {p['rest_points']:+.0f} จุด — ฐานแคบ")

    g = {k: quotes.get(k) for k in ("HYG", "IWM", "SPY", "UUP", "GLD", "SMH", "QQQ")}
    if g["HYG"] and g["HYG"].pct <= -0.4:
        score -= 1.0; sig.append(f"HYG {g['HYG'].pct:+.2f}% — เงินเริ่มหนีความเสี่ยง")
    if g["IWM"] and g["SPY"] and g["IWM"].pct_5d - g["SPY"].pct_5d >= 1.5:
        score += 0.5; sig.append("หุ้นเล็ก (IWM) นำ SPY รอบ 5 วัน — ความเชื่อมั่นกระจายตัวดี")
    if g["SMH"] and g["QQQ"] and abs(g["SMH"].pct - g["QQQ"].pct) >= 1.5:
        sig.append(f"เซมิฯ (SMH) {g['SMH'].pct:+.2f}% แยกจาก QQQ {g['QQQ'].pct:+.2f}% — "
                   f"US100 ขึ้นกับชิปเป็นหลัก")
    if g["UUP"] and abs(g["UUP"].pct) >= 0.4:
        sig.append(f"ดอลลาร์ (UUP) {g['UUP'].pct:+.2f}% — "
                   f"{'กดดันทอง' if g['UUP'].pct > 0 else 'หนุนทอง'}")
    if g["GLD"]:
        sig.append(f"GLD {g['GLD'].pct:+.2f}% (5 วัน {g['GLD'].pct_5d:+.2f}%) — ใช้เทียบ GOLD ใน MT5")

    return {"ok": bool(out), "index": out, "score": round(score, 2), "signals": sig}


# ---------------------------------------------------------------------------
#  ตัวรัน
# ---------------------------------------------------------------------------

def fetch_market_context(cfg: Optional[WebullConfig] = None,
                         only: Optional[List[str]] = None) -> dict:
    """ฟังก์ชันหลักที่ GUI เรียกใช้ — คืน dict ที่พร้อมแสดงผล"""
    cfg = cfg or WebullConfig.load()
    out = {"ok": False, "at": datetime.now().isoformat(timespec="seconds"),
           "error": None, "breadth": {}, "sectors": {}, "cross": {}, "risk": {},
           "index_momentum": {}, "unusual_volume": {}, "extremes": {}}
    if not cfg:
        out["error"] = "ไม่พบ webull_config.json"
        return out

    wb = Webull(cfg)
    if not wb.connect():
        out["error"] = wb.last_error
        return out

    out["mode"] = "full" if only else WEBULL_MODE
    if out["mode"] != "full":
        # core 5 + หุ้นสำคัญ 24 = 29 ตัว = 2 request
        cq = wb.quotes(list(CORE_SYMBOLS) + [s for s in EXTRA_SYMBOLS if s not in CORE_SYMBOLS])
        core = core_snapshot(cq)
        out["core"] = core
        pulse = index_pulse(cq)
        out["pulse"] = pulse
        out["index_momentum"] = index_momentum(cq)
        # รวมคะแนน core + การถ่วงน้ำหนักดัชนี
        rs = dict(core["risk"])
        sc = max(-10.0, min(10.0, rs["score"] + pulse.get("score", 0)))
        rs["score"] = round(sc, 1)
        rs["label"] = ("RISK-ON ชัดเจน" if sc >= 3 else "RISK-ON อ่อน ๆ" if sc >= 1 else
                       "RISK-OFF ชัดเจน" if sc <= -3 else "RISK-OFF อ่อน ๆ" if sc <= -1 else
                       "เป็นกลาง")
        rs["reasons"] = list(core["risk"]["reasons"]) + list(pulse.get("signals", []))
        out["risk"] = rs
        out["unusual_volume"] = unusual_volume(cq)
        out["extremes"] = extremes(cq)
        out["api"] = wb.stats
        out["ok"] = core["ok"]
        if not out["ok"]:
            out["error"] = wb.last_error or "ดึงข้อมูลไม่ได้เลย"
        return out

    want = set(only or ["dow", "ndx", "sector", "cross"])

    # ดึงรวบเดียวก่อน เพื่อให้ทุกชุดข้างล่างอ่านจาก cache — 55 ตัว = 2 request
    prefetch: List[str] = []
    if "dow" in want:
        prefetch += list(DOW_NAMES)
    if "ndx" in want:
        prefetch += list(NDX_NAMES)
    if "sector" in want:
        prefetch += list(SECTOR_ETFS)
    if "cross" in want:
        prefetch += list(CROSS_ASSETS) + list(INDEX_PROXY)
    seen = set()
    wb.quotes([s for s in prefetch if not (s in seen or seen.add(s))])

    if "dow" in want:
        out["breadth"]["US30"] = breadth(wb.quotes(DOW_NAMES), weighted=True)
    if "ndx" in want:
        out["breadth"]["US100"] = breadth(wb.quotes(NDX_NAMES))
    if "sector" in want:
        sq = wb.quotes(list(SECTOR_ETFS))
        out["sectors"] = sectors(sq)
        out["breadth"]["US500"] = breadth(sq)      # ใช้ sector ETF เป็นตัวแทน breadth
    if "cross" in want:
        cq = wb.quotes(list(CROSS_ASSETS) + list(INDEX_PROXY))
        out["cross"] = cross_assets({k: v for k, v in cq.items() if k in CROSS_ASSETS})
        out["index_momentum"] = index_momentum(cq)
        wb._all.update(cq)

    out["unusual_volume"] = unusual_volume(wb._all)
    out["extremes"] = extremes(wb._all)
    out["risk"] = risk_score(out["breadth"], out["sectors"], out["cross"])
    out["api"] = wb.stats
    out["ok"] = any(b.get("ok") for b in out["breadth"].values())
    if not out["ok"] and not out["error"]:
        out["error"] = wb.last_error or "ดึงข้อมูลไม่ได้เลย"
    return out


def print_context(c: dict) -> None:
    print("=" * 74)
    print(" บริบทตลาดจาก Webull ".center(74, "="))
    print("=" * 74)
    if not c.get("ok"):
        print(" ผิดพลาด:", c.get("error"))
        return
    print(f" เวลา {c['at']}")

    r = c.get("risk", {})
    if r:
        print(f"\n ความเสี่ยงโดยรวม: {r['score']:+.1f}  ({r['label']})")
        for w in r["reasons"][:6]:
            print(f"   - {w}")

    k = c.get("core", {})
    if k.get("ok"):
        print("\n━━ 5 ตัวสำคัญ ━━")
        print("   " + " " * 26 + "".join(" " * (8 - _dw(h)) + h for h in
                                         ("1 วัน", "5 วัน", "20 วัน", "กรอบ20", "วอลุ่ม")))
        for r in k["rows"]:
            print(f"   {r['symbol']:<6}{pad(r['name'], 20)}{r['d1']:>7.2f}%{r['d5']:>7.2f}%"
                  f"{r['d20']:>7.2f}%{r['range_pos']:>7.0f}%{r['vol_ratio']:>7.2f}x")

    for name, b in c.get("breadth", {}).items():
        if not b.get("ok"):
            continue
        print(f"\n━━ {name} ━━")
        pts = f" | รวม {b['total_points']:+,.1f} จุด" if b.get("total_points") else ""
        print(f" ขึ้น {b['up']} / ลง {b['down']} จาก {b['counted']} | "
              f"เฉลี่ย {b['avg_pct']:+.2f}%{pts}")
        print(f" กระจุกตัว {b['concentration_pct']}% -> {b['verdict']}")
        print("   ฉุด : " + ", ".join(
            f"{x['symbol']} {x['pct']:+.2f}%" for x in b["drags"][:4]))
        print("   หนุน: " + ", ".join(
            f"{x['symbol']} {x['pct']:+.2f}%" for x in b["lifts"][:4]))

    s = c.get("sectors", {})
    if s.get("ok"):
        print(f"\n━━ กลุ่มอุตสาหกรรม ━━  {s['mood']} (tilt {s['tilt']:+.2f})")
        for row in s["ranking"]:
            bar = "█" * min(20, int(abs(row["pct"]) * 8))
            print(f"   {row['etf']:<5}{row['name']:<16}{row['pct']:>7.2f}%  {bar}")

    x = c.get("cross", {})
    if x.get("ok"):
        print("\n━━ สินทรัพย์อ้างอิง ━━")
        for row in x["rows"]:
            print(f"   {row['symbol']:<6}{row['name']:<18}{row['pct']:>7.2f}%")
        if x["signals"]:
            print("\n   สัญญาณเตือน:")
            for sg in x["signals"]:
                print(f"     ⚠ {sg}")
    a = c.get("api", {})
    if a and a.get("unsubscribed"):
        print("\n━━ สถานะบัญชี Webull ━━")
        print("  ✅ เชื่อมต่อและยืนยันตัวตนสำเร็จ (token ปกติ)")
        print("  ❌ ยังไม่ได้สมัคร market data")
        print("     ต้องสมัคร STOCK QUOTES ที่ developer.webull.co.th")
        print("     ส่วนอื่นของระบบ (MT5, ข่าว, ปฏิทิน) ยังทำงานได้ตามปกติ")
    if a:
        print(f"\n━━ การใช้ API ━━")
        print(f"  ยิงไป {a.get('requests',0)}/{a.get('budget',0)} request")
        if a.get("throttled"):
            print("  ⚠ โดนจำกัดอัตราการเรียก — ลดจำนวน symbol หรือเพิ่มระยะรอบอัปเดต")
        if a.get("denied"):
            print(f"  ไม่มีสิทธิ์ดู {len(a['denied'])} ตัว: "
                  f"{', '.join(a['denied'][:12])}")

    print("\n" + "=" * 74)
    print(" ข้อมูลประกอบการตัดสินใจ ไม่ใช่คำแนะนำการลงทุน")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--json", nargs="?", const=DEFAULT_OUT, default=None)
    p.add_argument("--only", default=None, help="dow,ndx,sector,cross (โหมดเต็ม)")
    p.add_argument("--full", action="store_true", help="ดึงชุดเต็ม ~55 ตัว (3 request)")
    p.add_argument("--raw", default=None, help="ดู response ดิบของ symbol นี้")
    a = p.parse_args()

    if a.raw:
        cfg = WebullConfig.load()
        wb = Webull(cfg)
        if not wb.connect():
            print("ต่อไม่ได้:", wb.last_error); return 1
        cat, payload = wb.raw(a.raw.upper())
        print("category ที่ใช้ได้:", cat)
        print(json.dumps(payload, ensure_ascii=False, indent=2)[:3000])
        return 0

    only = [x.strip() for x in a.only.split(",")] if a.only else None
    if a.full and not only:
        only = ["dow", "ndx", "sector", "cross"]
    c = fetch_market_context(only=only)
    print_context(c)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(c, f, ensure_ascii=False, indent=2)
        print(f"\nบันทึก {a.json}")
    return 0 if c.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
