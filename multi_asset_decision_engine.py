#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
 MULTI-ASSET DECISION ENGINE  (MADE)
 ระบบสนับสนุนการตัดสินใจเทรดรายวัน แบบ Multi-Chart + Relative Strength
================================================================================

 แนวคิด: ไม่ทำนายทิศทาง แต่ "จัดอันดับความแข็งแรง" แล้วเลือก
          Buy ตัวที่แข็งที่สุด / Sell ตัวที่อ่อนที่สุด ภายใต้ regime เดียวกัน

 โครงสร้าง 3 ชั้น (ชั้นล่างห้ามขัดชั้นบน):
   Layer 1  DRIVER   : USDX, BRENT        -> ตลาดอยู่โหมดไหน
   Layer 2  CONTEXT  : US30, US100, US500 -> เงินไหลไปไหน (risk-on/off, rotation)
   Layer 3  EXECUTION: GOLD + ทุกตัวข้างบน -> เข้าตรงไหน SL/TP/lot เท่าไร

 ความต้องการ:
   pip install MetaTrader5 pandas numpy
   ต้องเปิดโปรแกรม MT5 ค้างไว้ และเปิด symbol ใน Market Watch ให้ครบ

 วิธีใช้:
   python multi_asset_decision_engine.py
   python multi_asset_decision_engine.py --risk 2.0 --json out.json

 ⚠️ ระบบนี้เป็นเครื่องมือ "สนับสนุนการตัดสินใจ" ไม่ใช่ระบบส่งคำสั่งอัตโนมัติ
    และไม่ใช่คำแนะนำการลงทุน ผู้ใช้ต้องตัดสินใจและรับความเสี่ยงเอง
================================================================================
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

# ---- ชั้นดึงข้อมูล: ใช้ MT5 โดยตรงถ้ามี ไม่งั้นอ่านจากไฟล์ JSON ที่ export มา ----
try:
    import MetaTrader5 as mt5
    HAS_MT5 = True
except ImportError:
    mt5 = None
    HAS_MT5 = False


class _TF:
    """ค่าคงที่ timeframe แบบไม่ผูกกับแพ็กเกจ MT5 เพื่อให้ import ได้บน Linux"""
    H1, H2, H4, M15, D1 = "H1", "H2", "H4", "M15", "D1"


_MT5_TF_MAP = {}
if HAS_MT5:
    _MT5_TF_MAP = {
        "M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1,
        "H2": mt5.TIMEFRAME_H2, "H4": mt5.TIMEFRAME_H4, "D1": mt5.TIMEFRAME_D1,
    }


# ==============================================================================
# SECTION 0 : CONFIG  — แก้ชื่อ symbol ให้ตรงกับ Market Watch ของโบรกเกอร์
# ==============================================================================

@dataclass
class AssetConfig:
    symbol: str                 # ชื่อใน MT5
    alias: str                  # ชื่อที่ใช้แสดงผล
    role: str                   # DRIVER | CONTEXT | EXECUTION
    tradable: bool = True       # ระบบจะเสนอไม้ให้เฉพาะตัวที่ tradable=True
    timeframe: str = _TF.H1


ASSETS: List[AssetConfig] = [
    # --- Layer 1 : DRIVER (ไม่เทรด ใช้อ่านบริบทอย่างเดียว) ---
    AssetConfig("USDX-DEC26",  "USDX",   "DRIVER",    tradable=False),
    AssetConfig("BRENTCash#",  "BRENT",  "DRIVER",    tradable=True),
    # --- Layer 2 : CONTEXT (เทรดได้ และใช้อ่าน rotation) ---
    AssetConfig("US30Cash#",   "US30",   "CONTEXT",   tradable=True),
    AssetConfig("US100Cash#",  "US100",  "CONTEXT",   tradable=True),
    AssetConfig("US500Cash#",  "US500",  "CONTEXT",   tradable=True),
    # --- Layer 3 : EXECUTION ---
    AssetConfig("GOLDm#",      "GOLD",   "EXECUTION", tradable=True),
]

# ---- พารามิเตอร์ของระบบ ----
CFG = {
    "bars":                400,     # จำนวนแท่งที่ดึง
    "ema_fast":            8,
    "ema_mid":             21,
    "sma_slow":            50,
    "atr_period":          14,
    "adx_period":          14,
    "rs_lookback":         20,      # แท่งที่ใช้วัด relative strength
    "pivot_width":         5,       # ความกว้าง fractal สำหรับหา swing
    "swing_atr_filter":    0.5,     # swing ต้องห่างกันเกินกี่ ATR จึงนับ (กรอง noise)

    "score_entry_min":     4.0,     # คะแนนขั้นต่ำที่ยอมให้เสนอไม้
    "score_spread_min":    3.0,     # ส่วนต่างคะแนนแข็งสุด-อ่อนสุด ถ้าต่ำกว่านี้ = ตลาดไม่ชัด
    "chase_atr_limit":     1.5,     # ห่าง EMA21 เกินกี่ ATR ถือว่า "ไล่ราคา"
    "sl_atr_buffer":       0.5,     # เผื่อ SL จาก swing กี่ ATR
    "sl_atr_max":          3.0,     # SL กว้างสุดกี่ ATR (กัน swing ที่อยู่ไกลเกินจนเสี่ยงบาน)
    "rr_tp1":              2.0,
    "rr_tp2":              3.0,

    "risk_percent":        2.0,     # ความเสี่ยงต่อไม้ (% ของ balance)
    "max_spread_atr":      0.15,    # spread เกินกี่ ATR ถือว่าแพงเกินเข้า
    "max_signals":         2,       # เสนอไม้สูงสุดกี่ตัวต่อวัน
    "chart_bars":          120,     # เก็บกี่แท่งไว้ให้ GUI วาดกราฟ
}


# ==============================================================================
# SECTION 0.5 : DATA SOURCE  — แยกชั้นดึงข้อมูลออกจาก logic
#
#   LiveSource : ใช้ได้เฉพาะเครื่องที่ติดตั้ง MetaTrader5 ได้ (Windows + Python <3.13)
#   FileSource : อ่านจากไฟล์ JSON ที่ export ไว้ -> รันได้ทุก OS ทุกเวอร์ชัน Python
#
#   โครงสร้างไฟล์ที่ FileSource ต้องการ (1 ไฟล์ต่อ 1 symbol) ใน --data-dir:
#     <ALIAS>.json = {
#        "symbol": "GOLDm#",
#        "spec":   {"trade_tick_value":1.0,"trade_tick_size":0.01,
#                   "volume_min":0.01,"volume_max":50.0,"volume_step":0.01},
#        "tick":   {"bid":4185.20,"ask":4185.47},
#        "rates":  [{"time":"...","open":..,"high":..,"low":..,"close":..}, ...]
#     }
#   และไฟล์ _account.json = {"login":..,"company":..,"balance":..,"equity":..,"currency":"USD"}
# ==============================================================================

class DataSource:
    def connect(self) -> bool: raise NotImplementedError
    def account(self) -> Optional[dict]: raise NotImplementedError
    def rates(self, symbol: str, tf: str, bars: int) -> Optional[pd.DataFrame]: raise NotImplementedError
    def tick(self, symbol: str) -> Optional[dict]: raise NotImplementedError
    def spec(self, symbol: str) -> Optional[dict]: raise NotImplementedError
    def close(self) -> None: pass


class LiveSource(DataSource):
    """ต่อ MT5 โดยตรง (ต้องเปิดโปรแกรม MT5 ค้างไว้บนเครื่องเดียวกัน)"""

    def connect(self) -> bool:
        if not HAS_MT5:
            print("เครื่องนี้ไม่มีแพ็กเกจ MetaTrader5 (รองรับเฉพาะ Windows + Python < 3.13)")
            return False
        if not mt5.initialize():
            print(f"เชื่อมต่อ MT5 ไม่ได้: {mt5.last_error()} — เปิดโปรแกรม MT5 และ login ก่อน")
            return False
        return True

    def account(self):
        a = mt5.account_info()
        return a._asdict() if a else None

    def rates(self, symbol, tf, bars):
        if not mt5.symbol_select(symbol, True):
            return None
        r = mt5.copy_rates_from_pos(symbol, _MT5_TF_MAP.get(tf, mt5.TIMEFRAME_H1), 0, bars)
        if r is None or len(r) == 0:
            return None
        df = pd.DataFrame(r)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        return df

    def tick(self, symbol):
        t = mt5.symbol_info_tick(symbol)
        return {"bid": t.bid, "ask": t.ask} if t else None

    def spec(self, symbol):
        i = mt5.symbol_info(symbol)
        if not i:
            return None
        return {"trade_tick_value": i.trade_tick_value, "trade_tick_size": i.trade_tick_size,
                "volume_min": i.volume_min, "volume_max": i.volume_max, "volume_step": i.volume_step}

    def close(self):
        if HAS_MT5:
            mt5.shutdown()


class FileSource(DataSource):
    """อ่านจากไฟล์ JSON ที่ export จากเครื่องที่มี MT5 — รันได้ทุกแพลตฟอร์ม"""

    def __init__(self, data_dir: str):
        self.dir = data_dir
        self.cache: Dict[str, dict] = {}

    def _load(self, symbol: str) -> Optional[dict]:
        if symbol in self.cache:
            return self.cache[symbol]
        import glob as _g, os
        for path in _g.glob(os.path.join(self.dir, "*.json")):
            if os.path.basename(path).startswith("_"):
                continue
            try:
                with open(path, encoding="utf-8") as f:
                    d = json.load(f)
            except Exception:
                continue
            if d.get("symbol") == symbol:
                self.cache[symbol] = d
                return d
        return None

    def connect(self) -> bool:
        import os
        if not os.path.isdir(self.dir):
            print(f"ไม่พบโฟลเดอร์ข้อมูล: {self.dir}")
            return False
        return True

    def account(self):
        import os
        p = os.path.join(self.dir, "_account.json")
        if not os.path.exists(p):
            return None
        with open(p, encoding="utf-8") as f:
            return json.load(f)

    def rates(self, symbol, tf, bars):
        d = self._load(symbol)
        if not d or not d.get("rates"):
            return None
        df = pd.DataFrame(d["rates"])
        for c in ("open", "high", "low", "close"):
            if c not in df.columns:
                return None
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df.dropna(subset=["open", "high", "low", "close"]).tail(bars).reset_index(drop=True)

    def tick(self, symbol):
        d = self._load(symbol)
        return d.get("tick") if d else None

    def spec(self, symbol):
        d = self._load(symbol)
        return d.get("spec") if d else None


class MT5LinuxSource(DataSource):
    """
    ต่อ MT5 ที่รันใน Wine ผ่าน mt5server.exe (ซึ่งเป็น rpyc classic server)

    หมายเหตุสำคัญ: ไม่ใช้คลาส MetaTrader5 ของ mt5linux เพราะเวอร์ชัน 1.1.1
    บังคับสร้าง ContainerManager เสมอ ทำให้ต้องมี docker/udocker แม้จะใช้ Wine
    เราจึงต่อ rpyc ตรง ๆ แบบเดียวกับที่ไลบรารีทำภายใน ซึ่งใช้ได้ทั้ง Wine และ Docker
    """

    def __init__(self, host: str = "localhost", port: int = 18812, timeout: int = 120):
        self.host, self.port, self.timeout = host, port, timeout
        self.conn = None
        self.api = None
        self._obtain = None

    def connect(self) -> bool:
        try:
            import rpyc
            from rpyc.utils.classic import connect as _rpyc_connect, obtain
            self._obtain = obtain
            self._rpyc_connect = _rpyc_connect
        except ImportError:
            print("ไม่พบแพ็กเกจ rpyc  ->  pip install 'rpyc>=6.0.0,<7'")
            return False

        try:
            self.conn = self._rpyc_connect(self.host, self.port)
            self.conn._config["sync_request_timeout"] = self.timeout
        except Exception as e:
            print(f"ต่อ mt5server ที่ {self.host}:{self.port} ไม่ได้: {type(e).__name__}: {e}")
            print("  ตรวจ 1) เปิด MT5 ใน Wine และ login แล้วหรือยัง")
            print("  ตรวจ 2) สตาร์ท 'wine mt5server.exe' ค้างไว้อีกหน้าต่างหรือยัง")
            print("  ตรวจ 3) ss -ltnp | grep 18812")
            return False

        try:
            # mt5server วางไลบรารีไว้ที่ C:\mt5libs — ต้อง append path ก่อน import
            self.conn.execute("import sys; sys.path.append('C:\\\\mt5libs')")
            self.conn.execute("import MetaTrader5 as mt5")
            self.api = self.conn.modules.MetaTrader5
        except Exception as e:
            print(f"import MetaTrader5 ฝั่ง server ไม่ได้: {type(e).__name__}: {e}")
            return False

        try:
            if not self.api.initialize():
                print(f"initialize() ล้มเหลว: {self.api.last_error()}")
                print("  เปิดโปรแกรม MT5 ใน Wine และ login ให้เรียบร้อยก่อน")
                return False
        except Exception as e:
            print(f"initialize() error: {type(e).__name__}: {e}")
            return False
        return True

    def _val(self, obj, *names):
        """
        อ่านค่าจาก object ฝั่ง server
        namedtuple ของ MetaTrader5 เป็น C-extension ที่ pickle ข้าม rpyc ไม่ได้
        จึงอ่านทีละ attribute แทนการ obtain ทั้งก้อน (issue #57 ของโปรเจกต์)
        """
        out = {}
        for n in names:
            try:
                out[n] = getattr(obj, n)
            except Exception:
                out[n] = None
        return out

    def account(self):
        a = self.api.account_info()
        if a is None:
            return None
        return self._val(a, "login", "company", "currency", "balance", "equity")

    def rates(self, symbol, tf, bars):
        tf_const = getattr(self.api, f"TIMEFRAME_{tf}", None)
        if tf_const is None:
            tf_const = self.api.TIMEFRAME_H1
        if not self.api.symbol_select(symbol, True):
            return None
        raw = self.api.copy_rates_from_pos(symbol, tf_const, 0, bars)
        if raw is None:
            return None
        # numpy structured array ส่งข้าม rpyc ได้ ใช้ obtain ดึงมาทั้งก้อนรอบเดียว
        try:
            raw = self._obtain(raw)
        except Exception:
            pass
        if len(raw) == 0:
            return None
        df = pd.DataFrame(raw)
        if "time" in df.columns:
            df["time"] = pd.to_datetime(df["time"], unit="s")
        return df

    def tick(self, symbol):
        t = self.api.symbol_info_tick(symbol)
        if t is None:
            return None
        d = self._val(t, "bid", "ask")
        return d if d.get("bid") is not None else None

    def spec(self, symbol):
        i = self.api.symbol_info(symbol)
        if i is None:
            return None
        return self._val(i, "trade_tick_value", "trade_tick_size",
                         "volume_min", "volume_max", "volume_step")

    def close(self):
        try:
            if self.api:
                self.api.shutdown()
            if self.conn:
                self.conn.close()
        except Exception:
            pass


SRC: DataSource = LiveSource()      # ตั้งค่าจริงใน run()


# ==============================================================================
# SECTION 1 : INDICATORS  — คำนวณเองทั้งหมด ไม่พึ่ง TA-Lib
# ==============================================================================

def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def atr(df: pd.DataFrame, n: int) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def macd_hist(s: pd.Series, fast=12, slow=26, signal=9) -> pd.Series:
    line = ema(s, fast) - ema(s, slow)
    return line - ema(line, signal)


def adx_di(df: pd.DataFrame, n: int) -> pd.DataFrame:
    up = df["high"].diff()
    dn = -df["low"].diff()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = atr(df, n)
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / tr
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / tr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return pd.DataFrame({
        "adx": dx.ewm(alpha=1 / n, adjust=False).mean(),
        "plus_di": plus_di,
        "minus_di": minus_di,
    })


def find_swings(df: pd.DataFrame, w: int, min_move: float = 0.0):
    """
    หา swing high / swing low แบบ fractal สำหรับอ่านโครงสร้าง HH-HL / LH-LL

    min_move : ระยะขั้นต่ำ (หน่วยราคา ปกติใช้ ~0.5 ATR) ที่ swing ใหม่ต้องห่างจาก
               swing ก่อนหน้าจึงจะนับ — ถ้าไม่กรอง fractal เล็ก ๆ ที่เป็น noise
               จะทำให้อ่านโครงสร้างผิดทิศทั้งแท่ง
    """
    raw_h, raw_l = [], []
    h, l = df["high"].values, df["low"].values
    for i in range(w, len(df) - w):
        if h[i] == max(h[i - w:i + w + 1]):
            raw_h.append((i, float(h[i])))
        if l[i] == min(l[i - w:i + w + 1]):
            raw_l.append((i, float(l[i])))

    def _filter(points, keep_max: bool):
        """ยุบ swing ที่เกาะกลุ่มกันให้เหลือตัวแทนตัวเดียว แล้วตัดตัวที่ขยับไม่ถึง min_move"""
        if not points:
            return []
        merged = [points[0]]
        for idx, px in points[1:]:
            pi, pp = merged[-1]
            if idx - pi <= w:                       # อยู่ในกลุ่มเดียวกัน -> เก็บตัวที่สุดโต่งกว่า
                if (keep_max and px > pp) or (not keep_max and px < pp):
                    merged[-1] = (idx, px)
            else:
                merged.append((idx, px))
        if min_move <= 0:
            return merged
        out = [merged[0]]
        for idx, px in merged[1:]:
            if abs(px - out[-1][1]) >= min_move:    # ขยับน้อยเกิน = noise ทิ้ง
                out.append((idx, px))
            elif (keep_max and px > out[-1][1]) or (not keep_max and px < out[-1][1]):
                out[-1] = (idx, px)
        return out

    return _filter(raw_h, True), _filter(raw_l, False)


# ==============================================================================
# SECTION 2 : SCORING  — ให้คะแนนความแข็งแรง ช่วง -10 ถึง +10
# ==============================================================================

@dataclass
class AssetState:
    alias: str
    symbol: str
    role: str
    tradable: bool
    price: float = 0.0
    atr: float = 0.0
    spread: float = 0.0
    ema_fast: float = 0.0
    ema_mid: float = 0.0
    sma_slow: float = 0.0
    macd: float = 0.0
    macd_prev: float = 0.0
    adx: float = 0.0
    plus_di: float = 0.0
    minus_di: float = 0.0
    roc: float = 0.0
    last_swing_high: float = 0.0
    last_swing_low: float = 0.0
    structure: str = "RANGE"
    score: float = 0.0
    breakdown: Dict[str, float] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)
    zones: List["Zone"] = field(default_factory=list)   # โซนรอเข้าเทรด
    ohlc: List[tuple] = field(default_factory=list)     # (time, o, h, l, c) สำหรับวาดกราฟ
    ema_series: List[float] = field(default_factory=list)
    pdh: float = 0.0                                    # Previous Day High
    pdl: float = 0.0                                    # Previous Day Low


def score_structure(df: pd.DataFrame, st: AssetState) -> float:
    """เกณฑ์ 2: โครงสร้างตลาด HH-HL (+2) / LH-LL (-2)"""
    min_move = st.atr * CFG["swing_atr_filter"] if st.atr else 0.0
    highs, lows = find_swings(df, CFG["pivot_width"], min_move)
    if len(highs) < 2 or len(lows) < 2:
        st.structure = "RANGE"
        return 0.0
    st.last_swing_high = highs[-1][1]
    st.last_swing_low = lows[-1][1]
    hh = highs[-1][1] > highs[-2][1]
    hl = lows[-1][1] > lows[-2][1]
    lh = highs[-1][1] < highs[-2][1]
    ll = lows[-1][1] < lows[-2][1]
    if hh and hl:
        st.structure = "UPTREND (HH-HL)"
        return 2.0
    if lh and ll:
        st.structure = "DOWNTREND (LH-LL)"
        return -2.0
    if hh or hl:
        st.structure = "WEAK UP"
        return 1.0
    if lh or ll:
        st.structure = "WEAK DOWN"
        return -1.0
    st.structure = "RANGE"
    return 0.0


def build_state(cfg: AssetConfig) -> Optional[AssetState]:
    df = SRC.rates(cfg.symbol, cfg.timeframe, CFG["bars"])
    if df is None or len(df) < 120:
        got = 0 if df is None else len(df)
        print(f"  [!] {cfg.symbol}: ข้อมูลไม่พอ (ได้ {got} แท่ง ต้องการ 120+) — ข้ามตัวนี้")
        return None

    st = AssetState(cfg.alias, cfg.symbol, cfg.role, cfg.tradable)
    st.price = float(df["close"].iloc[-1])
    st.ema_fast = float(ema(df["close"], CFG["ema_fast"]).iloc[-1])
    st.ema_mid = float(ema(df["close"], CFG["ema_mid"]).iloc[-1])
    st.sma_slow = float(df["close"].rolling(CFG["sma_slow"]).mean().iloc[-1])
    st.atr = float(atr(df, CFG["atr_period"]).iloc[-1])

    mh = macd_hist(df["close"])
    st.macd, st.macd_prev = float(mh.iloc[-1]), float(mh.iloc[-2])

    a = adx_di(df, CFG["adx_period"])
    st.adx = float(a["adx"].iloc[-1])
    st.plus_di = float(a["plus_di"].iloc[-1])
    st.minus_di = float(a["minus_di"].iloc[-1])

    n = CFG["rs_lookback"]
    st.roc = float((df["close"].iloc[-1] / df["close"].iloc[-n] - 1) * 100)

    tk = SRC.tick(cfg.symbol)
    if tk:
        st.spread = float(tk["ask"]) - float(tk["bid"])

    b = {}
    # เกณฑ์ 1 : ตำแหน่งราคาเทียบ MA และการเรียงตัวของเส้น
    s = 0.0
    if st.price > st.ema_fast: s += 0.7
    else:                      s -= 0.7
    if st.price > st.ema_mid:  s += 0.7
    else:                      s -= 0.7
    if st.price > st.sma_slow: s += 0.6
    else:                      s -= 0.6
    b["MA"] = round(s, 2)

    # เกณฑ์ 2 : โครงสร้าง
    b["STRUCTURE"] = round(score_structure(df, st), 2)

    # เกณฑ์ 3 : MACD ทิศทาง + การขยายตัวของ histogram
    s = 1.0 if st.macd > 0 else -1.0
    if abs(st.macd) > abs(st.macd_prev):
        s *= 1.5                       # histogram ขยาย = โมเมนตัมเร่ง
    else:
        s *= 0.6                       # histogram หด = โมเมนตัมแผ่ว
    b["MACD"] = round(max(-1.5, min(1.5, s)), 2)

    # เกณฑ์ 4 : ADX + ทิศของ DI (วัดว่าเทรนด์มีแรงจริงไหม)
    if st.adx >= 20:
        b["ADX"] = 1.0 if st.plus_di > st.minus_di else -1.0
    else:
        b["ADX"] = 0.0
        st.notes.append("ADX ต่ำ = ไร้เทรนด์ชัด")

    st.breakdown = b
    st.zones = compute_zones(df, st)

    # เก็บแท่งเทียนชุดเล็กไว้ให้ GUI วาด (เก็บเท่าที่จำเป็น ไม่เก็บทั้ง DataFrame)
    n = min(CFG["chart_bars"], len(df))
    tail = df.tail(n)
    ema_mid_series = ema(df["close"], CFG["ema_mid"]).tail(n)
    st.ohlc = [(str(t), float(o), float(h), float(l), float(c))
               for t, o, h, l, c in zip(
                   tail["time"] if "time" in tail.columns else range(n),
                   tail["open"], tail["high"], tail["low"], tail["close"])]
    st.ema_series = [float(x) for x in ema_mid_series]
    return st


def apply_relative_strength(states: List[AssetState]) -> None:
    """เกณฑ์ 5 : เทียบกันเอง — ตัวที่วิ่งดีกว่าเพื่อนได้แต้มบวก (หัวใจของระบบ)"""
    tradables = [s for s in states if s.role in ("CONTEXT", "EXECUTION")]
    if len(tradables) < 2:
        return
    rocs = np.array([s.roc for s in tradables])
    mean, std = rocs.mean(), rocs.std()
    for s in tradables:
        z = 0.0 if std == 0 else (s.roc - mean) / std
        s.breakdown["REL_STRENGTH"] = round(float(max(-2.0, min(2.0, z * 1.2))), 2)
    for s in states:
        s.breakdown.setdefault("REL_STRENGTH", 0.0)
        s.score = round(sum(s.breakdown.values()), 2)



# ==============================================================================
# SECTION 2.5 : ZONE ENGINE — โซนที่ควร "รอ" ก่อนเข้า แทนการไล่ราคา
#
#   แนวคิด: ราคาที่ดีที่สุดไม่ใช่ราคาตอนนี้ แต่เป็นราคาที่สถาบันทิ้งร่องรอยไว้
#   โซนที่หา:
#     OB  (Order Block)  แท่งสวนทางสุดท้ายก่อนราคาวิ่งแรง = ที่ที่ออเดอร์ใหญ่ถูกวาง
#     FVG (Fair Value Gap) ช่องว่างราคาระหว่าง 3 แท่ง = ความไม่สมดุลที่ราคามักกลับมาเติม
#     LIQ (Liquidity)    PDH/PDL และ equal highs/lows = ที่ที่ stop กองอยู่
# ==============================================================================

@dataclass
class Zone:
    kind: str                 # DEMAND | SUPPLY | FVG_BULL | FVG_BEAR | LIQ_BUY | LIQ_SELL
    side: str                 # BUY | SELL — ถ้าราคามาถึงโซนนี้ ควรมองฝั่งไหน
    low: float
    high: float
    dist_atr: float = 0.0     # ราคาห่างจากโซนกี่ ATR (0 = อยู่ในโซนแล้ว)
    fresh: bool = True        # ยังไม่เคยถูกทดสอบ = แรงกว่า
    strength: str = "ปานกลาง"
    trigger: str = ""         # ต้องเห็นอะไรก่อนถึงจะเข้า
    note: str = ""

    @property
    def mid(self) -> float:
        return (self.low + self.high) / 2


def _find_order_blocks(df: pd.DataFrame, atr_val: float, lookback: int = 120):
    """
    OB = แท่งสุดท้ายที่สวนทาง ก่อนที่ราคาจะวิ่งแรงออกไป
    เงื่อนไข "วิ่งแรง" ใช้ระยะทางจากแท่ง OB อย่างน้อย 1.2 ATR ภายใน 3 แท่งถัดไป
    """
    bulls, bears = [], []
    o, h, l, c = (df[x].values for x in ("open", "high", "low", "close"))
    n = len(df)
    start = max(2, n - lookback)
    for i in range(start, n - 3):
        move = max(h[i + 1:i + 4]) - c[i]
        if c[i] < o[i] and move >= 1.2 * atr_val:          # แท่งแดงก่อนวิ่งขึ้น
            bulls.append((i, float(l[i]), float(max(o[i], c[i]))))
        move_dn = c[i] - min(l[i + 1:i + 4])
        if c[i] > o[i] and move_dn >= 1.2 * atr_val:       # แท่งเขียวก่อนวิ่งลง
            bears.append((i, float(min(o[i], c[i])), float(h[i])))
    return bulls, bears


def _find_fvg(df: pd.DataFrame, atr_val: float, lookback: int = 120):
    """
    FVG = ช่องว่างระหว่างแท่งที่ 1 และ 3 ที่แท่งกลางกระโดดข้ามไป
    เก็บเฉพาะช่องที่กว้างพอ (>= 0.25 ATR) ไม่งั้นจะเจอ noise เต็มไปหมด
    """
    bull, bear = [], []
    h, l = df["high"].values, df["low"].values
    n = len(df)
    for i in range(max(2, n - lookback), n - 1):
        if l[i + 1] > h[i - 1] and (l[i + 1] - h[i - 1]) >= 0.25 * atr_val:
            bull.append((i, float(h[i - 1]), float(l[i + 1])))      # ช่องว่างขาขึ้น
        if h[i + 1] < l[i - 1] and (l[i - 1] - h[i + 1]) >= 0.25 * atr_val:
            bear.append((i, float(h[i + 1]), float(l[i - 1])))      # ช่องว่างขาลง
    return bull, bear


def _touched_after(df: pd.DataFrame, idx: int, lo: float, hi: float) -> bool:
    """โซนนี้ถูกราคาแตะอีกครั้งหลังเกิดแล้วหรือยัง (ถูกแตะแล้ว = อ่อนแรงลง)"""
    if idx + 2 >= len(df):
        return False
    seg = df.iloc[idx + 2:]
    return bool(((seg["low"] <= hi) & (seg["high"] >= lo)).any())


def _dist_atr(price: float, lo: float, hi: float, atr_val: float) -> float:
    if atr_val <= 0:
        return 0.0
    if lo <= price <= hi:
        return 0.0
    return (lo - price if price < lo else price - hi) / atr_val


def compute_zones(df: pd.DataFrame, st: AssetState) -> List[Zone]:
    """หาโซนรอเข้าทั้งฝั่ง BUY และ SELL พร้อมเงื่อนไขยืนยันของแต่ละโซน"""
    zones: List[Zone] = []
    if st.atr <= 0 or len(df) < 30:
        return zones
    price, a = st.price, st.atr

    # ---- PDH / PDL : แนวที่ stop กองอยู่หนาที่สุดในกรอบวัน ----
    if "time" in df.columns:
        d = df.copy()
        d["day"] = pd.to_datetime(d["time"]).dt.date
        days = sorted(d["day"].unique())
        if len(days) >= 2:
            prev = d[d["day"] == days[-2]]
            st.pdh, st.pdl = float(prev["high"].max()), float(prev["low"].min())
            for px, what in ((st.pdh, "Previous Day High"), (st.pdl, "Previous Day Low")):
                lo, hi = px - 0.15 * a, px + 0.15 * a
                broken = (what.endswith("High") and price > hi) or \
                         (what.endswith("Low") and price < lo)
                # แนวที่ถูกทะลุไปแล้วจะสลับบทบาท: ต้านกลายเป็นรับ และรับกลายเป็นต้าน
                side = "BUY" if price > hi else "SELL"
                zones.append(Zone(
                    kind="LIQ_BUY" if side == "BUY" else "LIQ_SELL",
                    side=side, low=lo, high=hi,
                    dist_atr=round(_dist_atr(price, lo, hi, a), 2),
                    strength="สูง",
                    trigger=("รอราคาย่อลงมาทดสอบแนวที่ทะลุไปแล้ว แล้วเด้งกลับขึ้น"
                             if broken and side == "BUY" else
                             "รอราคาเด้งขึ้นมาทดสอบแนวที่หลุดไปแล้ว แล้วถูกตีกลับลง"
                             if broken else
                             "รอให้ราคาหลุดลงไปกวาด stop แล้วปิดแท่งกลับขึ้นเหนือแนว "
                             "(ไม่ใช่เข้าทันทีที่แตะ)" if side == "BUY" else
                             "รอให้ราคาทะลุขึ้นไปกวาด stop แล้วปิดแท่งกลับลงมาใต้แนว "
                             "(ไม่ใช่เข้าทันทีที่แตะ)"),
                    note=(f"{what} — ถูกทะลุไปแล้ว กลายเป็นแนว" +
                          ("รับ" if side == "BUY" else "ต้าน")) if broken else
                         f"{what} — liquidity ที่ smart money มักมากวาดก่อนกลับทิศ"))

    # ---- Order Block ----
    bulls, bears = _find_order_blocks(df, a)
    for i, lo, hi in reversed(bulls):
        if hi < price:                                   # โซนซื้อต้องอยู่ใต้ราคา
            fresh = not _touched_after(df, i, lo, hi)
            zones.append(Zone(
                kind="DEMAND", side="BUY", low=lo, high=hi,
                dist_atr=round(_dist_atr(price, lo, hi, a), 2), fresh=fresh,
                strength="สูง" if fresh else "ต่ำ (เคยถูกทดสอบแล้ว)",
                trigger="รอแท่งปฏิเสธในโซน (ไส้ล่างยาว / engulfing) หรือ CHoCH ขึ้นบน M15",
                note="Bullish Order Block — แท่งสุดท้ายก่อนราคาวิ่งขึ้นแรง"))
            break
    for i, lo, hi in reversed(bears):
        if lo > price:                                   # โซนขายต้องอยู่เหนือราคา
            fresh = not _touched_after(df, i, lo, hi)
            zones.append(Zone(
                kind="SUPPLY", side="SELL", low=lo, high=hi,
                dist_atr=round(_dist_atr(price, lo, hi, a), 2), fresh=fresh,
                strength="สูง" if fresh else "ต่ำ (เคยถูกทดสอบแล้ว)",
                trigger="รอแท่งปฏิเสธในโซน (ไส้บนยาว / engulfing) หรือ CHoCH ลงบน M15",
                note="Bearish Order Block — แท่งสุดท้ายก่อนราคาวิ่งลงแรง"))
            break

    # ---- Fair Value Gap (เอาเฉพาะที่ยังไม่ถูกเติม) ----
    fb, fs = _find_fvg(df, a)
    for i, lo, hi in reversed(fb):
        if hi < price and not _touched_after(df, i, lo, hi):
            zones.append(Zone(
                kind="FVG_BULL", side="BUY", low=lo, high=hi,
                dist_atr=round(_dist_atr(price, lo, hi, a), 2),
                strength="ปานกลาง",
                trigger="รอราคาเติมช่องว่างแล้วเด้งกลับ ถ้าปิดแท่งใต้ช่องถือว่าเสีย",
                note="ช่องว่างขาขึ้นที่ยังไม่ถูกเติม ราคามักกลับมาเติมก่อนไปต่อ"))
            break
    for i, lo, hi in reversed(fs):
        if lo > price and not _touched_after(df, i, lo, hi):
            zones.append(Zone(
                kind="FVG_BEAR", side="SELL", low=lo, high=hi,
                dist_atr=round(_dist_atr(price, lo, hi, a), 2),
                strength="ปานกลาง",
                trigger="รอราคาเติมช่องว่างแล้วถูกตีกลับ ถ้าปิดแท่งเหนือช่องถือว่าเสีย",
                note="ช่องว่างขาลงที่ยังไม่ถูกเติม ราคามักกลับมาเติมก่อนไปต่อ"))
            break

    # ---- EMA กลาง: โซนย่อของเทรนด์ที่กำลังวิ่ง ----
    # ฝั่งของโซนตัดสินจากตำแหน่งราคาเทียบ EMA ไม่ใช่คะแนน
    # (คะแนนยังไม่ถูกคำนวณตอนนี้ และโซนใต้ราคาต้องเป็น BUY เสมอ)
    if st.ema_mid > 0:
        lo, hi = st.ema_mid - 0.4 * a, st.ema_mid + 0.4 * a
        side = "BUY" if price > st.ema_mid else "SELL"
        zones.append(Zone(
            kind="DEMAND" if side == "BUY" else "SUPPLY", low=lo, high=hi, side=side,
            dist_atr=round(_dist_atr(price, lo, hi, a), 2),
            strength="ปานกลาง",
            trigger=("รอราคาย่อลงมาแตะแล้วตั้ง higher low" if side == "BUY"
                     else "รอราคาเด้งขึ้นมาแตะแล้วตั้ง lower high"),
            note=f"โซนย่อตามเทรนด์รอบ EMA{CFG['ema_mid']}"))

    zones.sort(key=lambda z: z.dist_atr)      # โซนที่ราคาใกล้จะถึงก่อน อยู่บนสุด
    return zones



# ==============================================================================
# SECTION 2.6 : EXPORT โซนไปให้ MT5 วาด
#
#   Python วาดบนกราฟ MT5 เองไม่ได้ (ObjectCreate มีเฉพาะใน MQL5)
#   จึงเขียนโซนเป็น CSV ลงโฟลเดอร์ Common/Files แล้วให้ EA ฝั่ง MQL5 อ่านไปวาด
#   ใช้ CSV แทน JSON เพราะ MQL5 อ่าน CSV ได้ในตัว ไม่ต้องเขียน parser เอง
# ==============================================================================

def mt5_common_files_dir() -> Optional[str]:
    """หาโฟลเดอร์ Common/Files ของ MetaTrader (ที่ EA อ่านไฟล์ได้โดยไม่ต้องตั้งค่า)"""
    import platform
    if platform.system() == "Windows":
        appdata = os.environ.get("APPDATA")
        if appdata:
            d = os.path.join(appdata, "MetaQuotes", "Terminal", "Common", "Files")
            return d
    # Wine: ชี้ไปที่ drive_c ของ prefix
    home = os.path.expanduser("~")
    for base in (os.path.join(home, ".wine", "drive_c", "users", os.environ.get("USER", "user"),
                              "AppData", "Roaming", "MetaQuotes", "Terminal", "Common", "Files"),):
        if os.path.isdir(os.path.dirname(base)):
            return base
    return None


# ข้อความที่แสดงบนกราฟ MT5 เป็นภาษาอังกฤษ (GUI ยังใช้ภาษาไทยตามเดิม)
_CHART_EN = {
    "สูง": "High",
    "ปานกลาง": "Medium",
    "ต่ำ (เคยถูกทดสอบแล้ว)": "Low (already tested)",
    "รอราคาย่อลงมาทดสอบแนวที่ทะลุไปแล้ว แล้วเด้งกลับขึ้น":
        "Wait for a pullback to retest the broken level, then a bounce up",
    "รอราคาเด้งขึ้นมาทดสอบแนวที่หลุดไปแล้ว แล้วถูกตีกลับลง":
        "Wait for a rally to retest the broken level, then a rejection down",
    "รอให้ราคาหลุดลงไปกวาด stop แล้วปิดแท่งกลับขึ้นเหนือแนว (ไม่ใช่เข้าทันทีที่แตะ)":
        "Wait for a sweep of stops below the level and a close back above it (do not enter on first touch)",
    "รอให้ราคาทะลุขึ้นไปกวาด stop แล้วปิดแท่งกลับลงมาใต้แนว (ไม่ใช่เข้าทันทีที่แตะ)":
        "Wait for a sweep of stops above the level and a close back below it (do not enter on first touch)",
    "รอแท่งปฏิเสธในโซน (ไส้ล่างยาว / engulfing) หรือ CHoCH ขึ้นบน M15":
        "Wait for a rejection candle in the zone (long lower wick / engulfing) or a bullish CHoCH on M15",
    "รอแท่งปฏิเสธในโซน (ไส้บนยาว / engulfing) หรือ CHoCH ลงบน M15":
        "Wait for a rejection candle in the zone (long upper wick / engulfing) or a bearish CHoCH on M15",
    "รอราคาเติมช่องว่างแล้วเด้งกลับ ถ้าปิดแท่งใต้ช่องถือว่าเสีย":
        "Wait for the gap to be filled and a bounce; a close below the gap invalidates it",
    "รอราคาเติมช่องว่างแล้วถูกตีกลับ ถ้าปิดแท่งเหนือช่องถือว่าเสีย":
        "Wait for the gap to be filled and a rejection; a close above the gap invalidates it",
    "รอราคาย่อลงมาแตะแล้วตั้ง higher low":
        "Wait for a pullback to touch the zone and form a higher low",
    "รอราคาเด้งขึ้นมาแตะแล้วตั้ง lower high":
        "Wait for a bounce to touch the zone and form a lower high",
}


def export_zones_csv(ranked: List[AssetState], path: Optional[str] = None) -> Optional[str]:
    """
    เขียนโซนทั้งหมดเป็น CSV ให้ EA ฝั่ง MT5 อ่านไปวาด
    คอลัมน์: symbol,kind,side,low,high,dist_atr,strength,trigger
    คืนค่า path ที่เขียน หรือ None ถ้าเขียนไม่ได้
    """
    if path is None:
        d = mt5_common_files_dir()
        if not d:
            return None
        path = os.path.join(d, "made_zones.csv")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write("symbol,kind,side,low,high,dist_atr,strength,trigger\n")
            for st in ranked:
                for z in st.zones:
                    # ตัดจุลภาคออกจากข้อความ ไม่งั้นคอลัมน์ CSV จะเพี้ยน
                    # MT5 อ่านไฟล์เป็น ANSI: ข้อความที่ไม่ใช่ ASCII จะเพี้ยน จึงบังคับ ASCII
                    trig = _CHART_EN.get(z.trigger, z.trigger).replace(",", " ").replace("\n", " ")
                    stren = _CHART_EN.get(z.strength, z.strength).replace(",", " ")
                    trig = trig.encode("ascii", "replace").decode("ascii")
                    stren = stren.encode("ascii", "replace").decode("ascii")
                    f.write(f"{st.symbol},{z.kind},{z.side},{z.low:.5f},{z.high:.5f},"
                            f"{z.dist_atr:.2f},{stren},{trig}\n")
        os.replace(tmp, path)       # เขียนทับแบบ atomic กัน EA อ่านไฟล์ครึ่ง ๆ กลาง ๆ
        return path
    except Exception:
        return None


# ==============================================================================
# SECTION 3 : REGIME  — Layer 1 อ่าน driver ก่อนเสมอ
# ==============================================================================

@dataclass
class Regime:
    usdx: float = 0.0
    brent: float = 0.0
    dollar: str = "NEUTRAL"
    oil: str = "NEUTRAL"
    label: str = ""
    narrative: str = ""
    vetoes: Dict[str, str] = field(default_factory=dict)


def read_regime(states: Dict[str, AssetState]) -> Regime:
    r = Regime()
    usdx = states.get("USDX")
    brent = states.get("BRENT")
    r.usdx = usdx.score if usdx else 0.0
    r.brent = brent.score if brent else 0.0

    r.dollar = "STRONG" if r.usdx >= 3 else "WEAK" if r.usdx <= -3 else "NEUTRAL"
    r.oil = "RISING" if r.brent >= 3 else "FALLING" if r.brent <= -3 else "NEUTRAL"

    # --- ตารางความหมาย: น้ำมัน -> เงินเฟ้อ -> เฟด -> yield -> สินทรัพย์ ---
    if r.oil == "FALLING" and r.dollar != "STRONG":
        r.label = "DISINFLATION / RISK-ON"
        r.narrative = ("น้ำมันลง = แรงกดดันเงินเฟ้อผ่อนคลาย = ลดโอกาสเฟดเร่งขึ้นดอกเบี้ย "
                       "เป็นบวกกับหุ้นทุกดัชนี และเป็นกลางถึงบวกกับทอง")
    elif r.oil == "RISING":
        r.label = "INFLATION SHOCK / RISK-OFF"
        r.narrative = ("น้ำมันขึ้น = เงินเฟ้อกลับมา = ตลาดคาดเฟดเข้มขึ้น = yield ขึ้น "
                       "กดดันหุ้นเติบโตหนักสุด และกดทองผ่านช่องทาง yield")
        r.vetoes["US100"] = "น้ำมันขาขึ้นกดหุ้นเติบโตหนักที่สุด — ห้าม Buy US100"
    elif r.dollar == "STRONG":
        r.label = "DOLLAR DOMINANCE"
        r.narrative = "ดอลลาร์แข็งนำตลาด กดดันสินทรัพย์ที่ตั้งราคาด้วย USD โดยเฉพาะทอง"
        r.vetoes["GOLD"] = "USDX แข็ง — ห้าม Buy ทอง (ถ้าจะเล่นให้มองฝั่ง Sell เท่านั้น)"
    elif r.dollar == "WEAK":
        r.label = "DOLLAR WEAKNESS"
        r.narrative = "ดอลลาร์อ่อนหนุนทองและสินค้าโภคภัณฑ์เป็นหลัก"
    else:
        r.label = "MIXED / NO CLEAR DRIVER"
        r.narrative = "driver ยังไม่ตัดสินใจ ควรลดขนาดไม้ลงครึ่งหนึ่งหรือพักมือ"
    return r


# ==============================================================================
# SECTION 4 : VETO + TIMING + SIZING  — Layer 4-6
# ==============================================================================

@dataclass
class Signal:
    alias: str
    symbol: str
    side: str                  # BUY | SELL
    score: float
    status: str                # READY | WAIT_PULLBACK | VETOED
    price: float = 0.0
    entry_zone: str = ""
    stop_loss: float = 0.0
    tp1: float = 0.0
    tp2: float = 0.0
    lot: float = 0.0
    risk_usd: float = 0.0
    reward_tp1: float = 0.0
    reasons: List[str] = field(default_factory=list)
    invalidation: str = ""


def calc_lot(symbol: str, sl_distance: float, risk_usd: float):
    """
    คำนวณ lot จากระยะ SL จริงและ tick value ของ symbol นั้น ๆ
    คืนค่า (lot, actual_risk_usd) — lot = 0.0 แปลว่าเสี่ยงเกินเกณฑ์ ห้ามเข้า
    """
    info = SRC.spec(symbol)
    if info is None or sl_distance <= 0:
        return 0.0, 0.0
    tick_value = float(info.get("trade_tick_value", 0))
    tick_size = float(info.get("trade_tick_size", 0))
    if tick_value <= 0 or tick_size <= 0:
        return 0.0, 0.0
    loss_per_lot = (sl_distance / tick_size) * tick_value
    if loss_per_lot <= 0:
        return 0.0, 0.0
    raw_lot = risk_usd / loss_per_lot
    step = float(info.get("volume_step") or 0.01)
    vmin = float(info.get("volume_min", 0.01))
    vmax = float(info.get("volume_max", 100.0))

    # ⚠️ สำคัญมากกับพอร์ตเล็ก: ถ้า lot ที่คำนวณได้ต่ำกว่า volume_min
    #    การปัดขึ้นเป็น volume_min = เสี่ยงเกินที่ตั้งใจไว้โดยไม่รู้ตัว
    #    ระบบจะคืน 0 พร้อมความเสี่ยงจริง เพื่อให้ชั้น VETO ปฏิเสธไม้นั้น
    if raw_lot < vmin:
        return 0.0, round(vmin * loss_per_lot, 2)

    lot = min(vmax, round(raw_lot / step) * step)
    return round(lot, 2), round(lot * loss_per_lot, 2)


def build_signal(st: AssetState, side: str, regime: Regime, balance: float) -> Signal:
    sig = Signal(st.alias, st.symbol, side, st.score, "READY", st.price)

    # ---------- ด่าน VETO ----------
    if st.alias in regime.vetoes and side == "BUY":
        sig.status = "VETOED"
        sig.reasons.append("VETO: " + regime.vetoes[st.alias])
        return sig
    if abs(st.score) < CFG["score_entry_min"]:
        sig.status = "VETOED"
        sig.reasons.append(f"VETO: คะแนน {st.score} ต่ำกว่าเกณฑ์ {CFG['score_entry_min']}")
        return sig
    if st.atr > 0 and st.spread > st.atr * CFG["max_spread_atr"]:
        sig.status = "VETOED"
        sig.reasons.append(f"VETO: spread {st.spread:.2f} กว้างเกินเทียบ ATR {st.atr:.2f}")
        return sig
    if (side == "BUY" and st.score < 0) or (side == "SELL" and st.score > 0):
        sig.status = "VETOED"
        sig.reasons.append("VETO: ทิศของสัญญาณขัดกับคะแนนรวม")
        return sig

    # ---------- ด่าน TIMING : กันไล่ราคา ----------
    dist_atr = abs(st.price - st.ema_mid) / st.atr if st.atr else 0
    if dist_atr > CFG["chase_atr_limit"]:
        sig.status = "WAIT_PULLBACK"
        lo, hi = st.ema_mid - 0.5 * st.atr, st.ema_mid + 0.5 * st.atr
        sig.entry_zone = f"{lo:,.2f} – {hi:,.2f}  (รอย่อกลับหา EMA{CFG['ema_mid']})"
        sig.reasons.append(f"ราคาห่าง EMA{CFG['ema_mid']} ถึง {dist_atr:.1f} ATR = ไล่ราคา ห้ามเข้าทันที")
    else:
        sig.entry_zone = f"{st.price:,.2f} (ราคาปัจจุบัน อยู่ใกล้ MA แล้ว)"

    # ---------- ด่าน SIZING : SL/TP จาก ATR + swing จริง ----------
    buf = CFG["sl_atr_buffer"] * st.atr
    cap = CFG["sl_atr_max"] * st.atr          # เพดานความกว้างของ SL
    if side == "BUY":
        swing = st.last_swing_low if st.last_swing_low else st.price - 2 * st.atr
        sig.stop_loss = min(swing - buf, st.price - 1.0 * st.atr)
        if st.price - sig.stop_loss > cap:    # swing ไกลเกิน -> ใช้เพดานแทน
            sig.stop_loss = st.price - cap
            sig.reasons.append(f"SL ถูกจำกัดที่ {CFG['sl_atr_max']} ATR (swing อยู่ไกลเกินไป)")
        risk = st.price - sig.stop_loss
        sig.tp1 = st.price + risk * CFG["rr_tp1"]
        sig.tp2 = st.price + risk * CFG["rr_tp2"]
        sig.invalidation = f"ปิดแท่งต่ำกว่า {sig.stop_loss:,.2f} = โครงสร้างขาขึ้นเสีย"
    else:
        swing = st.last_swing_high if st.last_swing_high else st.price + 2 * st.atr
        sig.stop_loss = max(swing + buf, st.price + 1.0 * st.atr)
        if sig.stop_loss - st.price > cap:
            sig.stop_loss = st.price + cap
            sig.reasons.append(f"SL ถูกจำกัดที่ {CFG['sl_atr_max']} ATR (swing อยู่ไกลเกินไป)")
        risk = sig.stop_loss - st.price
        sig.tp1 = st.price - risk * CFG["rr_tp1"]
        sig.tp2 = st.price - risk * CFG["rr_tp2"]
        sig.invalidation = f"ปิดแท่งสูงกว่า {sig.stop_loss:,.2f} = โครงสร้างขาลงเสีย"

    budget = round(balance * CFG["risk_percent"] / 100, 2)
    sig.lot, actual_risk = calc_lot(st.symbol, abs(risk), budget)
    sig.risk_usd = actual_risk

    if sig.lot <= 0:
        sig.status = "VETOED"
        sig.reasons.insert(0, (f"VETO: lot ขั้นต่ำของ {st.symbol} ทำให้เสี่ยงถึง {actual_risk:,.2f} USD "
                               f"ซึ่งเกินงบ {budget:,.2f} USD ({CFG['risk_percent']}% ของพอร์ต) "
                               f"— พอร์ตยังเล็กเกินจะเทรดตัวนี้อย่างปลอดภัย"))
        return sig

    sig.reward_tp1 = round(sig.risk_usd * CFG["rr_tp1"], 2)

    sig.reasons.append(f"โครงสร้าง: {st.structure}")
    sig.reasons.append(f"คะแนนย่อย: {st.breakdown}")
    sig.reasons.append(f"regime: {regime.label}")
    return sig


# ==============================================================================
# SECTION 5 : ORCHESTRATOR + REPORT
# ==============================================================================

def make_source(data_dir: Optional[str] = None, mt5linux: Optional[str] = None):
    """สร้าง DataSource ตามโหมดที่เลือก พร้อมชื่อโหมดสำหรับแสดงผล"""
    if data_dir:
        return FileSource(data_dir), f"FILE ({data_dir})"
    if mt5linux:
        host, _, port = mt5linux.partition(":")
        h, pt = host or "localhost", int(port or 18812)
        return MT5LinuxSource(h, pt), f"MT5 REALTIME ผ่าน rpyc ({h}:{pt})"
    return LiveSource(), "MT5 LIVE (native MetaTrader5 package)"


def analyze(balance: float, risk_percent: Optional[float] = None) -> dict:
    """
    รันไปป์ไลน์วิเคราะห์ทั้งหมดแล้วคืนผลเป็น dict (ไม่พิมพ์อะไรเลย)
    ใช้ร่วมกันระหว่าง CLI และ GUI — SRC ต้องถูก connect() ไว้แล้วก่อนเรียก

    คืนค่า: {ok, error, balance, regime, ranked, signals, spread_score, no_trade, warnings}
    """
    if risk_percent is not None:
        CFG["risk_percent"] = risk_percent

    out = {"ok": False, "error": None, "balance": balance, "regime": None,
           "ranked": [], "signals": [], "spread_score": 0.0,
           "no_trade": False, "warnings": [], "at": datetime.now()}

    states: List[AssetState] = []
    for cfg in ASSETS:
        try:
            st = build_state(cfg)
        except Exception as e:                      # symbol เดียวพังต้องไม่ล้มทั้งระบบ
            out["warnings"].append(f"{cfg.alias}: {type(e).__name__}: {e}")
            continue
        if st:
            states.append(st)
        else:
            out["warnings"].append(f"{cfg.alias}: ข้อมูลไม่พอหรือดึงไม่ได้")

    if len(states) < 3:
        out["error"] = "ข้อมูลไม่พอสำหรับเปรียบเทียบ (ต้องได้อย่างน้อย 3 สินทรัพย์)"
        return out

    apply_relative_strength(states)
    smap = {s.alias: s for s in states}
    regime = read_regime(smap)
    ranked = sorted([s for s in states if s.role in ("CONTEXT", "EXECUTION")],
                    key=lambda x: x.score, reverse=True)

    out.update({"regime": regime, "ranked": ranked, "ok": True})
    if not ranked:
        out["error"] = "ไม่มีสินทรัพย์ในชั้น CONTEXT/EXECUTION"
        return out

    out["spread_score"] = round(ranked[0].score - ranked[-1].score, 2)
    if out["spread_score"] < CFG["score_spread_min"]:
        out["no_trade"] = True
        return out

    signals: List[Signal] = []
    for s in ranked:
        if s.tradable and s.score > 0:
            signals.append(build_signal(s, "BUY", regime, balance))
            break
    for s in reversed(ranked):
        if s.tradable and s.score < 0:
            signals.append(build_signal(s, "SELL", regime, balance))
            break
    out["signals"] = signals
    return out


def run(risk_percent: float, json_path: Optional[str], data_dir: Optional[str],
        mt5linux: Optional[str] = None) -> None:
    global SRC
    if data_dir:
        SRC = FileSource(data_dir)
        mode = f"FILE ({data_dir})"
    elif mt5linux:
        host, _, port = mt5linux.partition(":")
        SRC = MT5LinuxSource(host or "localhost", int(port or 18812))
        mode = f"MT5 REALTIME ผ่าน rpyc ({host or 'localhost'}:{port or 18812})"
    else:
        SRC = LiveSource()
        mode = "MT5 LIVE (native MetaTrader5 package)"

    # พิมพ์โหมดก่อนต่อเสมอ เพื่อให้รู้ทันทีว่าระบบเลือกแหล่งข้อมูลไหน
    print(f"แหล่งข้อมูล: {mode}")
    if not SRC.connect():
        if not data_dir:
            print("\nทางเลือก: export ข้อมูลจากเครื่องที่มี MT5 แล้วรันด้วย --data-dir ./data")
        return

    CFG["risk_percent"] = risk_percent
    acc = SRC.account()
    balance = float(acc.get("balance", 0.0)) if acc else 0.0

    print("=" * 78)
    print(" MULTI-ASSET DECISION ENGINE".center(78))
    print(f" {datetime.now():%Y-%m-%d %H:%M:%S}".center(78))
    print("=" * 78)
    if acc:
        print(f" บัญชี {acc.get('login','-')} | {acc.get('company','-')}")
        print(f" Balance {balance:,.2f} {acc.get('currency','USD')} | "
              f"Equity {float(acc.get('equity', balance)):,.2f} | "
              f"ความเสี่ยงต่อไม้ {CFG['risk_percent']}% = {balance*CFG['risk_percent']/100:,.2f}")
    else:
        print(" [!] ไม่พบข้อมูลบัญชี — lot จะคำนวณไม่ได้ (แต่ ranking ยังใช้ได้)")

    # ---- [0]+[2] ดึงข้อมูลและให้คะแนน ----
    print("\n[0] ดึงข้อมูลและคำนวณ...")
    states: List[AssetState] = []
    for cfg in ASSETS:
        s = build_state(cfg)
        if s:
            states.append(s)
    if len(states) < 3:
        print("ข้อมูลไม่พอสำหรับเปรียบเทียบ — ตรวจชื่อ symbol ใน ASSETS")
        SRC.close()
        return

    apply_relative_strength(states)
    smap = {s.alias: s for s in states}

    # ---- [1] REGIME ----
    regime = read_regime(smap)
    print("\n" + "-" * 78)
    print(f"[1] REGIME : {regime.label}")
    print("-" * 78)
    print(f"  USDX score {regime.usdx:+.2f} -> ดอลลาร์ {regime.dollar}")
    print(f"  BRENT score {regime.brent:+.2f} -> น้ำมัน {regime.oil}")
    print(f"  ความหมาย: {regime.narrative}")

    # ---- [3] RANKING ----
    ranked = sorted([s for s in states if s.role in ("CONTEXT", "EXECUTION")],
                    key=lambda x: x.score, reverse=True)
    print("\n" + "-" * 78)
    print("[3] RANKING — เรียงความแข็งแรง")
    print("-" * 78)
    print(f"  {'อันดับ':<7}{'สินทรัพย์':<10}{'คะแนน':>8}  {'ราคา':>12}  {'ATR':>9}  โครงสร้าง")
    for i, s in enumerate(ranked, 1):
        tag = "แข็งสุด" if i == 1 else ("อ่อนสุด" if i == len(ranked) else "")
        print(f"  {i:<7}{s.alias:<10}{s.score:>+8.2f}  {s.price:>12,.2f}  "
              f"{s.atr:>9,.2f}  {s.structure} {tag}")

    # ---- [4] NO-TRADE CHECK ----
    spread_score = ranked[0].score - ranked[-1].score
    print(f"\n  ส่วนต่างคะแนนแข็งสุด-อ่อนสุด = {spread_score:.2f}")
    if spread_score < CFG["score_spread_min"]:
        print("\n" + "=" * 78)
        print(" ⛔ NO TRADE — ไม่มีตัวไหนเด่นพอ ตลาดยังไม่ตัดสินใจ")
        print("    การอยู่เฉยคือการตัดสินใจที่ถูกต้องที่สุดในสภาพแบบนี้")
        print("=" * 78)
        SRC.close()
        return

    # ---- [5]+[6] สร้างสัญญาณ ----
    candidates: List[Signal] = []
    for s in ranked:
        if s.tradable and s.score > 0:
            candidates.append(build_signal(s, "BUY", regime, balance))
            break
    for s in reversed(ranked):
        if s.tradable and s.score < 0:
            candidates.append(build_signal(s, "SELL", regime, balance))
            break

    # ---- [7] REPORT ----
    print("\n" + "=" * 78)
    print(" [7] ข้อเสนอแนะสำหรับวันนี้")
    print("=" * 78)
    if not candidates:
        print("  ไม่มีสินทรัพย์ที่ผ่านเกณฑ์ทั้งสองฝั่ง")
    for sig in candidates:
        icon = {"READY": "🟢", "WAIT_PULLBACK": "🟡", "VETOED": "🔴"}[sig.status]
        print(f"\n{icon} {sig.side}  {sig.alias}  ({sig.symbol})   [{sig.status}]")
        print(f"   คะแนน       : {sig.score:+.2f}")
        for r in sig.reasons:
            print(f"   - {r}")
        if sig.status != "VETOED":
            print(f"   โซนเข้า     : {sig.entry_zone}")
            print(f"   Stop Loss   : {sig.stop_loss:,.2f}")
            print(f"   TP1 (1:{CFG['rr_tp1']:.0f})   : {sig.tp1:,.2f}   -> กำไรประมาณ {sig.reward_tp1:,.2f} USD")
            print(f"   TP2 (1:{CFG['rr_tp2']:.0f})   : {sig.tp2:,.2f}")
            print(f"   Lot         : {sig.lot}  (เสี่ยง {sig.risk_usd:,.2f} USD)")
            print(f"   ยกเลิกเมื่อ : {sig.invalidation}")

    print("\n" + "-" * 78)
    print(" กฎที่ระบบบังคับเสมอ")
    print("-" * 78)
    print(f"  1. เข้าสูงสุด {CFG['max_signals']} ไม้ต่อวัน")
    print("  2. WAIT_PULLBACK = ห้ามเข้าทันที ต้องรอราคาเข้าโซนก่อน")
    print("  3. ปิดครึ่งที่ TP1 แล้วเลื่อน SL มา breakeven")
    print("  4. ขาดทุนรวม 5% ของพอร์ตในวันเดียว = ปิดจอ ไม่มีข้อยกเว้น")
    print("  5. ก่อนข่าวใหญ่ (PMI/CPI/NFP/FOMC) ไม่เปิดไม้ใหม่")
    print("\n  ⚠️ เครื่องมือสนับสนุนการตัดสินใจ ไม่ใช่คำแนะนำการลงทุน")
    print("=" * 78)

    if json_path:
        payload = {
            "generated_at": datetime.now().isoformat(),
            "balance": balance,
            "regime": asdict(regime),
            "ranking": [asdict(s) for s in ranked],
            "signals": [asdict(s) for s in candidates],
        }
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
        print(f"\nบันทึก JSON ที่ {json_path}")

    SRC.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Multi-Asset Decision Engine")
    p.add_argument("--risk", type=float, default=CFG["risk_percent"],
                   help="ความเสี่ยงต่อไม้เป็น %% ของ balance (ค่าเริ่มต้น 2.0)")
    p.add_argument("--json", type=str, default=None, help="path สำหรับบันทึกผลเป็น JSON")
    p.add_argument("--data-dir", type=str, default=None,
                   help="อ่านข้อมูลจากไฟล์ JSON ในโฟลเดอร์นี้แทนการต่อ MT5 สด "
                        "(ใช้เมื่อรันบนเครื่องที่ติดตั้ง MetaTrader5 ไม่ได้ เช่น Linux)")
    p.add_argument("--mt5linux", nargs="?", const="localhost:18812", default=None,
                   metavar="HOST:PORT",
                   help="ดึงข้อมูล realtime จาก MT5 ผ่าน mt5linux (ค่าเริ่มต้น localhost:18812)")
    args = p.parse_args()
    run(args.risk, args.json, args.data_dir, args.mt5linux)
