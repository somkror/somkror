#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
===============================================================================
 weekly_screener.py — คัดหุ้น US สำหรับ swing trade จบภายในสัปดาห์ (ส่วนหนึ่งของ MADE)
===============================================================================
 ขั้นตอน
   1. จัดอันดับ sector ETF เทียบ SPY (5 วัน + 20 วัน) -> เลือกกลุ่มที่แข็ง
   2. ไล่หุ้นในกลุ่ม หา 2 รูปแบบ
        PULLBACK  เทรนด์ขึ้น (ราคา > EMA50, EMA20 > EMA50, ADX > 20)
                  ย่อแตะ EMA20 แล้ว RSI/Stochastic เริ่มเด้ง
        BREAKOUT  Bollinger บีบแคบ แล้วปิดทะลุขอบบนพร้อมวอลุ่ม >= 1.5 เท่า
   3. ตัดตัวที่ "ประกาศงบก่อนปิดวันศุกร์" ทิ้ง (ห้ามถือข้ามงบ)
   4. คำนวณจุดเข้า / stop (1.5 ATR หรือ swing low) / เป้า 2R / จำนวนหุ้น

 ใช้ข้อมูลแท่งรายวันจาก Webull ผ่าน webull_market.Webull (ชุดละ <= 20 ตัว)
 ทั้งจักรวาล ~45 ตัว = 3 request ต่อการสแกนหนึ่งครั้ง

 ใช้งาน
   python weekly_screener.py                       สแกนด้วยทุน 1,000 USD เสี่ยง 1%
   python weekly_screener.py --capital 2500 --risk 1.5
   python weekly_screener.py --json screener.json

 ระบบช่วยตัดสินใจ ไม่ส่งคำสั่งซื้อขาย และไม่ใช่คำแนะนำการลงทุน
===============================================================================
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
#  จักรวาลหุ้น — แก้เพิ่ม/ลดได้ตามใจ (รวมทั้งหมดควรไม่เกิน ~60 ตัว = 3 request)
# ---------------------------------------------------------------------------
BENCH = "SPY"
SECTORS = {
    "XLE": ("พลังงาน",          ["XOM", "CVX", "COP", "EOG", "SLB"]),
    "XLP": ("บริโภคจำเป็น",     ["COST", "WMT", "KO", "PG"]),
    "XLV": ("สุขภาพ",            ["LLY", "ABT", "TMO", "ISRG", "UNH"]),
    "XLF": ("การเงิน",           ["JPM", "GS", "AXP", "V"]),
    "XLK": ("เทคโนโลยี",        ["MSFT", "AAPL", "AVGO", "NVDA"]),
    "XLI": ("อุตสาหกรรม",       ["CAT", "GE", "HON"]),
    "XLU": ("สาธารณูปโภค",      ["NEE", "SO"]),
    "XLY": ("บริโภคฟุ่มเฟือย",  ["AMZN", "HD", "TSLA"]),
    "XLC": ("สื่อสาร",           ["META", "GOOGL", "NFLX"]),
    "XLB": ("วัตถุดิบ",          ["LIN", "NEM"]),
    "XLRE": ("อสังหา",           ["PLD", "AMT"]),
}
TOP_SECTORS = 3          # สแกนหุ้นเฉพาะ N กลุ่มที่แข็งที่สุด
BARS = 120               # EMA50 + ADX ต้องการประวัติพอสมควร
MIN_BARS = 60

DEFAULT_CAPITAL = float(os.environ.get("MADE_STOCK_CAPITAL", "1000"))
DEFAULT_RISK = float(os.environ.get("MADE_STOCK_RISK", "1.0"))


# ---------------------------------------------------------------------------
#  Indicator — รับ list เรียงเก่า -> ใหม่ คืน list ยาวเท่ากัน (None ช่วงอุ่นเครื่อง)
# ---------------------------------------------------------------------------

def ema(x: List[float], n: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(x)
    if len(x) < n:
        return out
    k = 2 / (n + 1)
    v = sum(x[:n]) / n
    out[n - 1] = v
    for i in range(n, len(x)):
        v = x[i] * k + v * (1 - k)
        out[i] = v
    return out


def sma(x: List[float], n: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(x)
    for i in range(n - 1, len(x)):
        out[i] = sum(x[i - n + 1:i + 1]) / n
    return out


def stdev(x: List[float], n: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(x)
    for i in range(n - 1, len(x)):
        w = x[i - n + 1:i + 1]
        m = sum(w) / n
        out[i] = (sum((a - m) ** 2 for a in w) / n) ** 0.5
    return out


def rsi(c: List[float], n: int = 14) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(c)
    if len(c) <= n:
        return out
    gains = [max(c[i] - c[i - 1], 0) for i in range(1, len(c))]
    losses = [max(c[i - 1] - c[i], 0) for i in range(1, len(c))]
    ag, al = sum(gains[:n]) / n, sum(losses[:n]) / n
    for i in range(n, len(c)):
        if i > n:
            ag = (ag * (n - 1) + gains[i - 1]) / n
            al = (al * (n - 1) + losses[i - 1]) / n
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def true_range(h, l, c) -> List[float]:
    tr = [h[0] - l[0]]
    for i in range(1, len(c)):
        tr.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
    return tr


def wilder(x: List[float], n: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(x)
    if len(x) < n:
        return out
    v = sum(x[:n]) / n
    out[n - 1] = v
    for i in range(n, len(x)):
        v = (v * (n - 1) + x[i]) / n
        out[i] = v
    return out


def atr(h, l, c, n: int = 14):
    return wilder(true_range(h, l, c), n)


def adx(h, l, c, n: int = 14) -> List[Optional[float]]:
    L = len(c)
    out: List[Optional[float]] = [None] * L
    if L < n * 2 + 1:
        return out
    pdm, ndm = [0.0], [0.0]
    for i in range(1, L):
        up, dn = h[i] - h[i - 1], l[i - 1] - l[i]
        pdm.append(up if up > dn and up > 0 else 0.0)
        ndm.append(dn if dn > up and dn > 0 else 0.0)
    tr = wilder(true_range(h, l, c), n)
    sp, sn = wilder(pdm, n), wilder(ndm, n)
    dx: List[float] = []
    idx: List[int] = []
    for i in range(L):
        if tr[i] and sp[i] is not None and sn[i] is not None:
            pdi, ndi = 100 * sp[i] / tr[i], 100 * sn[i] / tr[i]
            s = pdi + ndi
            dx.append(0.0 if s == 0 else 100 * abs(pdi - ndi) / s)
            idx.append(i)
    sm = wilder(dx, n)
    for j, i in enumerate(idx):
        out[i] = sm[j]
    return out


def stoch(h, l, c, k: int = 14, d: int = 3):
    K: List[Optional[float]] = [None] * len(c)
    for i in range(k - 1, len(c)):
        hh, ll = max(h[i - k + 1:i + 1]), min(l[i - k + 1:i + 1])
        K[i] = 50.0 if hh == ll else 100 * (c[i] - ll) / (hh - ll)
    vals = [x for x in K if x is not None]
    D_core = sma(vals, d)
    D: List[Optional[float]] = [None] * (len(c) - len(vals)) + D_core
    return K, D


# ---------------------------------------------------------------------------
#  โหลดโมดูลข้างเคียง
# ---------------------------------------------------------------------------

def _load(name: str):
    path = os.path.join(HERE, f"{name}.py")
    if not os.path.exists(path):
        return None
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _series(q):
    """Quote ของ webull_market เก็บใหม่ -> เก่า แปลงเป็นเก่า -> ใหม่ และตัดแท่งเสีย"""
    rows = [(c, h, l, v) for c, h, l, v in zip(q.closes, q.highs, q.lows, q.vols)
            if c > 0 and h > 0 and l > 0]
    rows.reverse()
    return ([r[0] for r in rows], [r[1] for r in rows],
            [r[2] for r in rows], [r[3] for r in rows])


def _ret(c: List[float], n: int) -> float:
    return (c[-1] / c[-1 - n] - 1) * 100 if len(c) > n and c[-1 - n] > 0 else 0.0


# ---------------------------------------------------------------------------
#  ปฏิทินงบ — ตัดตัวที่ประกาศงบก่อนปิดศุกร์
# ---------------------------------------------------------------------------

def earnings_until_friday(symbols: List[str]) -> dict:
    """คืน {symbol: 'YYYY-MM-DD เวลา'} ของตัวที่มีงบตั้งแต่วันนี้ถึงศุกร์นี้"""
    nc = _load("news_calendar")
    out = {"ok": False, "hits": {}, "days": [], "error": None}
    if not nc:
        out["error"] = "ไม่พบ news_calendar.py"
        return out
    today = datetime.now(timezone.utc) - timedelta(hours=4)       # เวลานิวยอร์กโดยประมาณ
    days_to_fri = (4 - today.weekday()) % 7
    if today.weekday() > 4:                                        # เสาร์/อาทิตย์ -> สัปดาห์หน้า
        today += timedelta(days=7 - today.weekday())
        days_to_fri = 4
    want = {s.upper() for s in symbols}
    fails = 0
    for d in range(days_to_fri + 1):
        day = (today + timedelta(days=d)).strftime("%Y-%m-%d")
        out["days"].append(day)
        raw = nc.fetch(nc.NASDAQ_EARNINGS.format(date=day), ttl=3600)
        if not raw:
            fails += 1
            continue
        try:
            rows = (json.loads(raw.decode("utf-8", "ignore")).get("data") or {}).get("rows") or []
        except Exception:
            fails += 1
            continue
        for r in rows:
            s = str(r.get("symbol", "")).upper().strip()
            if s in want:
                tm = str(r.get("time", "")).replace("time-", "")
                tm = {"pre-market": "ก่อนเปิด", "after-hours": "หลังปิด"}.get(tm, tm or "?")
                out["hits"][s] = f"{day} {tm}"
    out["ok"] = fails < len(out["days"])
    if fails:
        out["error"] = f"ดึงปฏิทินงบไม่ได้ {fails}/{len(out['days'])} วัน"
    return out


# ---------------------------------------------------------------------------
#  วิเคราะห์หุ้นหนึ่งตัว
# ---------------------------------------------------------------------------

def analyze(sym: str, q, spy_c: List[float]) -> Optional[dict]:
    c, h, l, v = _series(q)
    if len(c) < MIN_BARS:
        return None
    e20, e50 = ema(c, 20), ema(c, 50)
    r = rsi(c, 14)
    a = atr(h, l, c, 14)
    dx = adx(h, l, c, 14)
    k, d = stoch(h, l, c)
    mid, sd = sma(c, 20), stdev(c, 20)
    i = len(c) - 1
    if None in (e20[i], e50[i], r[i], r[i - 1], a[i], mid[i], sd[i], k[i], d[i]):
        return None

    close, A = c[i], a[i]
    upper = mid[i] + 2 * sd[i]
    width = [(4 * sd[j] / mid[j]) if (sd[j] is not None and mid[j]) else None
             for j in range(len(c))]
    wins = [w for w in width[-61:-1] if w is not None]
    squeeze = bool(wins) and min(width[i - 3:i]) <= sorted(wins)[max(0, len(wins) // 5)]
    vol_avg = sum(v[-21:-1]) / 20 if len(v) > 21 else 0
    vol_ratio = v[i] / vol_avg if vol_avg else 0.0
    adx_v = dx[i] or 0.0
    rs20 = _ret(c, 20) - _ret(spy_c, 20)

    trend_up = close > e50[i] and e20[i] > e50[i]
    touched = min(l[-3:]) <= e20[i] + 0.25 * A
    rsi_turn = 38 <= r[i] <= 62 and r[i] > r[i - 1]
    stoch_turn = k[i] > d[i] and k[i] < 60

    setup, why = None, []
    if trend_up and adx_v >= 20 and touched and rsi_turn and stoch_turn:
        setup = "PULLBACK"
        why = [f"เทรนด์ขึ้น ADX {adx_v:.0f}", "ย่อแตะ EMA20",
               f"RSI เด้ง {r[i-1]:.0f}→{r[i]:.0f}", "Stoch ตัดขึ้น"]
    elif squeeze and close > upper and vol_ratio >= 1.5 and close > e50[i]:
        setup = "BREAKOUT"
        why = ["BB บีบแล้วทะลุขอบบน", f"วอลุ่ม {vol_ratio:.1f}x", f"ADX {adx_v:.0f}"]

    # สถานะใกล้เข้า — ให้เห็นตัวที่ "รอ" ด้วย ไม่ใช่แค่ตัวที่ผ่านแล้ว
    watch = None
    if not setup and trend_up and adx_v >= 18:
        dist = (close - e20[i]) / A
        if 0 < dist <= 1.5:
            watch = f"เทรนด์ขึ้น ห่าง EMA20 {dist:.1f} ATR — รอย่อ"
        elif squeeze:
            watch = "BB บีบแคบในเทรนด์ขึ้น — รอทะลุพร้อมวอลุ่ม"

    swing_low = min(l[-5:])
    stop = max(swing_low - 0.1 * A, close - 2.0 * A)      # ไม่ให้ไกลเกิน 2 ATR
    stop = min(stop, close - 1.0 * A)                      # และไม่ใกล้กว่า 1 ATR
    R = close - stop
    score = rs20 + (adx_v - 20) * 0.2 + (5 if setup else 0)

    return {"symbol": sym, "close": round(close, 2), "setup": setup, "watch": watch,
            "why": why, "rsi": round(r[i], 1), "adx": round(adx_v, 1),
            "atr": round(A, 2), "vol_ratio": round(vol_ratio, 2),
            "rs20": round(rs20, 2), "d5": round(_ret(c, 5), 2),
            "ema20": round(e20[i], 2), "ema50": round(e50[i], 2),
            "entry": round(close, 2), "stop": round(stop, 2),
            "target": round(close + 2 * R, 2), "R": round(R, 2),
            "score": round(score, 2)}


def size(row: dict, capital: float, risk_pct: float) -> dict:
    risk_usd = capital * risk_pct / 100
    sh = risk_usd / row["R"] if row["R"] > 0 else 0
    sh = min(sh, capital / row["entry"])                    # ไม่ใช้เงินเกินทุน
    return {"risk_usd": round(risk_usd, 2), "shares": round(sh, 3),
            "whole_shares": int(sh), "cost": round(sh * row["entry"], 2)}


# ---------------------------------------------------------------------------
#  ตัวหลัก
# ---------------------------------------------------------------------------

def run_screener(capital: float = DEFAULT_CAPITAL, risk_pct: float = DEFAULT_RISK,
                 quotes: Optional[Dict] = None) -> dict:
    out = {"ok": False, "at": datetime.now().isoformat(timespec="seconds"),
           "error": None, "capital": capital, "risk_pct": risk_pct,
           "sectors": [], "picks": [], "watch": [], "skipped": [], "notes": []}

    universe = [BENCH] + list(SECTORS) + [s for _, (_, ss) in SECTORS.items() for s in ss]
    universe = list(dict.fromkeys(universe))

    if quotes is None:
        wm = _load("webull_market")
        if not wm:
            out["error"] = "ไม่พบ webull_market.py"; return out
        cfg = wm.WebullConfig.load()
        if not cfg:
            out["error"] = "ไม่พบ webull_config.json"; return out
        wb = wm.Webull(cfg)
        wb.BAR_COUNT = BARS
        if not wb.connect():
            out["error"] = wb.last_error; return out
        quotes = wb.quotes(universe)
        out["api"] = wb.stats
        if not quotes:
            out["error"] = wb.last_error or "ดึงข้อมูลไม่ได้"; return out

    if BENCH not in quotes:
        out["error"] = "ไม่มีข้อมูล SPY ใช้เทียบไม่ได้"; return out
    spy_c = _series(quotes[BENCH])[0]

    # 1) อันดับ sector
    for etf, (name, _) in SECTORS.items():
        q = quotes.get(etf)
        if not q:
            continue
        c = _series(q)[0]
        rs5, rs20 = _ret(c, 5) - _ret(spy_c, 5), _ret(c, 20) - _ret(spy_c, 20)
        out["sectors"].append({"etf": etf, "name": name, "rs5": round(rs5, 2),
                               "rs20": round(rs20, 2),
                               "score": round(rs5 * 0.6 + rs20 * 0.4, 2)})
    out["sectors"].sort(key=lambda s: s["score"], reverse=True)
    top = [s["etf"] for s in out["sectors"][:TOP_SECTORS]]
    for s in out["sectors"]:
        s["selected"] = s["etf"] in top

    # 2) วิเคราะห์หุ้นในกลุ่มที่แข็ง
    rows = []
    for etf in top:
        for sym in SECTORS[etf][1]:
            q = quotes.get(sym)
            if not q:
                out["skipped"].append({"symbol": sym, "reason": "ไม่มีข้อมูล"}); continue
            res = analyze(sym, q, spy_c)
            if not res:
                out["skipped"].append({"symbol": sym, "reason": "ข้อมูลไม่พอ"}); continue
            res["sector"] = SECTORS[etf][0]
            rows.append(res)

    # 3) ตัดตัวที่ติดงบ
    earn = earnings_until_friday([r["symbol"] for r in rows])
    out["earnings"] = earn
    if not earn["ok"]:
        out["notes"].append("⚠ เช็กปฏิทินงบไม่ได้ — ตรวจวันประกาศงบเองก่อนเข้าทุกตัว")
    for r in rows:
        if r["symbol"] in earn["hits"]:
            r["earnings"] = earn["hits"][r["symbol"]]
            out["skipped"].append({"symbol": r["symbol"],
                                   "reason": f"ประกาศงบ {r['earnings']} — ห้ามถือข้ามงบ"})
            continue
        if r["setup"]:
            r.update(size(r, capital, risk_pct))
            out["picks"].append(r)
        elif r["watch"]:
            out["watch"].append(r)

    out["picks"].sort(key=lambda r: r["score"], reverse=True)
    out["watch"].sort(key=lambda r: r["score"], reverse=True)

    # 4) จังหวะของสัปดาห์
    ny = datetime.now(timezone.utc) - timedelta(hours=4)
    wd = ny.weekday()
    if wd == 3:
        out["notes"].append("วันพฤหัส — เหลือเวลาถึงศุกร์น้อย เป้า 2R อาจไม่ทัน พิจารณาเป้า 1R")
    elif wd == 4:
        out["notes"].append("วันศุกร์ — ไม่ควรเปิดไม้ใหม่ ปิดของเดิมก่อนตลาดปิด")
    elif wd >= 5:
        out["notes"].append("ตลาดปิด — ผลนี้ใช้เตรียมแผนของสัปดาห์หน้า")
    out["ok"] = True
    return out


# ---------------------------------------------------------------------------
#  แสดงผล (ใช้ร่วมกับ GUI ผ่าน format_report)
# ---------------------------------------------------------------------------

def _dw(t: str) -> int:
    import unicodedata
    return sum(0 if unicodedata.category(ch) == "Mn" else 1 for ch in str(t))


def _pad(t: str, w: int) -> str:
    return str(t) + " " * max(0, w - _dw(t))


def format_report(r: dict) -> List[tuple]:
    """คืน list ของ (ข้อความ, tag) — tag: good/bad/warn/muted/head/None"""
    L: List[tuple] = []
    if not r.get("ok"):
        L.append(("สแกนไม่สำเร็จ: " + str(r.get("error")) + "\n", "bad"))
        return L
    L.append((f"Weekly Screener  {r['at']}   ทุน {r['capital']:,.0f} USD  "
              f"เสี่ยง {r['risk_pct']}% ต่อไม้\n", "head"))
    for n in r["notes"]:
        L.append((n + "\n", "warn"))

    L.append(("\n━━ อันดับ sector เทียบ SPY ━━\n", "head"))
    L.append(("   " + _pad("", 22) + "    RS 5 วัน   RS 20 วัน\n", "muted"))
    for s in r["sectors"]:
        mark = "★" if s["selected"] else " "
        L.append((f" {mark} {s['etf']:<5}{_pad(s['name'], 16)}{s['rs5']:>+9.2f}%"
                  f"{s['rs20']:>+10.2f}%\n", "good" if s["selected"] else "muted"))

    L.append(("\n━━ ตัวที่ผ่านเงื่อนไข ━━\n", "head"))
    if not r["picks"]:
        L.append(("  ยังไม่มีตัวไหนผ่านครบ — ไม่เข้าก็คือการตัดสินใจที่ดี\n", "muted"))
    for p in r["picks"]:
        L.append((f"\n  {p['symbol']}  [{p['setup']}]  {p['sector']}   "
                  f"RS20 {p['rs20']:+.1f}%  คะแนน {p['score']}\n", "good"))
        L.append(("    " + " · ".join(p["why"]) + "\n", None))
        L.append((f"    เข้า {p['entry']}   stop {p['stop']}   เป้า 2R {p['target']}"
                  f"   (R = {p['R']})\n", None))
        L.append((f"    ขนาด {p['shares']} หุ้น (เต็มหุ้น {p['whole_shares']})  "
                  f"ใช้เงิน {p['cost']:,.0f} USD  เสี่ยง {p['risk_usd']} USD\n", "muted"))

    if r["watch"]:
        L.append(("\n━━ รอจังหวะ ━━\n", "head"))
        for w in r["watch"][:8]:
            L.append((f"  {w['symbol']:<6}{w['close']:>9.2f}  RSI {w['rsi']:>4.0f}  "
                      f"ADX {w['adx']:>4.0f}  {w['watch']}\n", "warn"))

    if r["skipped"]:
        L.append(("\n━━ ตัดออก ━━\n", "head"))
        for s in r["skipped"]:
            L.append((f"  {s['symbol']:<6}{s['reason']}\n", "muted"))

    L.append(("\nกติกา: ปิดทุกไม้ภายในศุกร์ · ห้ามถือข้ามงบ · ถึง 1R เลื่อน stop มาจุดเข้า\n"
              "ข้อมูลประกอบการตัดสินใจ ไม่ใช่คำแนะนำการลงทุน\n", "muted"))
    return L


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--capital", type=float, default=DEFAULT_CAPITAL)
    p.add_argument("--risk", type=float, default=DEFAULT_RISK, help="%% ของทุนต่อไม้")
    p.add_argument("--json", default=None)
    a = p.parse_args()
    r = run_screener(a.capital, a.risk)
    print("".join(t for t, _ in format_report(r)))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=2)
        print(f"บันทึก {a.json}")
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
