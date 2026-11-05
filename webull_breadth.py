#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
===============================================================================
 webull_breadth.py — ดึงหุ้นรายตัวจาก Webull OpenAPI เพื่อวิเคราะห์ Dow Breadth
===============================================================================
 ทำไมต้องมีโมดูลนี้
   MT5 ให้แค่ US30Cash# ซึ่งเป็นตัวเลขดัชนีรวม บอกไม่ได้ว่าใครฉุด
   Webull ให้หุ้นรายตัว ทำให้แยกได้ว่า "ดัชนีลงเพราะตลาด" หรือ "เพราะหุ้นไม่กี่ตัว"

 ความต้องการ
   pip install webull-openapi-python-sdk       (รองรับ Python 3.8–3.13)
   ต้องมี OpenAPI market data subscription ที่ใช้งานอยู่ ไม่งั้นจะได้ 403

 การตั้งค่า (เลือกอย่างใดอย่างหนึ่ง — ห้ามใส่ key ลงในโค้ด)
   1) ตัวแปรสภาพแวดล้อม
        WEBULL_APP_KEY, WEBULL_APP_SECRET, WEBULL_REGION, WEBULL_ENDPOINT
   2) ไฟล์ webull_config.json ข้างไฟล์นี้
        {"app_key":"...","app_secret":"...","region":"th","endpoint":"..."}
      อย่าลืมใส่ไฟล์นี้ใน .gitignore

 ใช้งาน
   python webull_breadth.py                 ทดสอบการเชื่อมต่อ + รายงาน breadth
   python webull_breadth.py --json out.json
===============================================================================
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "webull_config.json")

# หุ้นน้ำหนักหนักใน Dow — Dow ถ่วงด้วย "ราคา" ไม่ใช่มูลค่าตลาด
# หุ้นราคาแพงจึงมีอิทธิพลมากกว่า ไม่ว่าบริษัทจะใหญ่แค่ไหน
DOW_HEAVY = ["GS", "UNH", "MSFT", "HD", "CAT", "V", "SHW", "MCD", "AXP", "AMGN",
             "TRV", "CRM", "IBM", "HON", "JNJ", "PG", "JPM", "WMT", "CVX", "MRK"]

# ตัวหารของ Dow (Dow Divisor) เปลี่ยนเมื่อมี split/เปลี่ยนตัวหุ้น
# ค่านี้ต้องอัปเดตเอง ใช้ประมาณการผลกระทบเป็น "จุดดัชนี"
DOW_DIVISOR = float(os.environ.get("DOW_DIVISOR", "0.1627"))


# =============================================================================
#  การตั้งค่า
# =============================================================================

@dataclass
class WebullConfig:
    app_key: str
    app_secret: str
    region: str = "th"
    endpoint: str = ""

    @staticmethod
    def load() -> Optional["WebullConfig"]:
        """อ่านจาก env ก่อน ถ้าไม่มีค่อยอ่านจากไฟล์ — ไม่มี key ฝังในโค้ดเลย"""
        k = os.environ.get("WEBULL_APP_KEY")
        s = os.environ.get("WEBULL_APP_SECRET")
        if k and s:
            return WebullConfig(k, s,
                                os.environ.get("WEBULL_REGION", "th"),
                                os.environ.get("WEBULL_ENDPOINT", ""))
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, encoding="utf-8") as f:
                    d = json.load(f)
                return WebullConfig(d["app_key"], d["app_secret"],
                                    d.get("region", "th"), d.get("endpoint", ""))
            except Exception as e:
                print(f"อ่าน {CONFIG_PATH} ไม่ได้: {e}")
        return None


# =============================================================================
#  ตัวเชื่อม Webull
# =============================================================================

@dataclass
class StockQuote:
    symbol: str
    price: float = 0.0
    prev_close: float = 0.0

    @property
    def change_pct(self) -> float:
        if self.prev_close <= 0:
            return 0.0
        return (self.price / self.prev_close - 1) * 100

    @property
    def change_abs(self) -> float:
        return self.price - self.prev_close

    @property
    def dow_points(self) -> float:
        """หุ้นตัวนี้ทำให้ดัชนี Dow ขยับกี่จุด = การเปลี่ยนแปลงราคา / ตัวหาร"""
        return self.change_abs / DOW_DIVISOR if DOW_DIVISOR else 0.0


class WebullSource:
    """ห่อ SDK ของ Webull ให้เรียกใช้ง่าย และไม่ให้ error ของมันทะลุไปล้มระบบหลัก"""

    def __init__(self, cfg: WebullConfig):
        self.cfg = cfg
        self.data_client = None
        self.last_error = ""

    def connect(self) -> bool:
        try:
            from webull.core.client import ApiClient
            from webull.data.data_client import DataClient
        except ImportError:
            self.last_error = ("ไม่พบ webull-openapi-python-sdk  ->  "
                               "pip install webull-openapi-python-sdk")
            return False
        try:
            api = ApiClient(self.cfg.app_key, self.cfg.app_secret, self.cfg.region)
            if self.cfg.endpoint:
                api.add_endpoint(self.cfg.region, self.cfg.endpoint)
            self.data_client = DataClient(api)
            return True
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            return False

    def daily_bars(self, symbol: str, count: int = 2) -> Optional[list]:
        """
        ดึงแท่งรายวันเพื่อหาราคาปิดวันก่อนและราคาปัจจุบัน
        ใช้ get_history_bar ตามที่เอกสาร Getting Started แสดงไว้
        """
        try:
            from webull.data.common.category import Category
            from webull.data.common.timespan import Timespan
            res = self.data_client.market_data.get_history_bar(
                symbol, Category.US_STOCK.name, Timespan.D.name)
            if getattr(res, "status_code", None) != 200:
                self.last_error = (f"{symbol}: HTTP {getattr(res,'status_code','?')} "
                                   f"{getattr(res,'text','')[:120]}")
                return None
            data = res.json()
            rows = data.get("data", data) if isinstance(data, dict) else data
            return rows[:count] if isinstance(rows, list) else None
        except Exception as e:
            self.last_error = f"{symbol}: {type(e).__name__}: {e}"
            return None

    def quote(self, symbol: str) -> Optional[StockQuote]:
        rows = self.daily_bars(symbol, 2)
        if not rows:
            return None

        def pick(row, *names):
            for n in names:
                if isinstance(row, dict) and row.get(n) is not None:
                    try:
                        return float(row[n])
                    except (TypeError, ValueError):
                        pass
            return 0.0

        # แท่งล่าสุดอาจอยู่หัวหรือท้าย list แล้วแต่ API — เทียบวันที่ไม่ได้ก็ใช้ลำดับ
        last, prev = rows[0], (rows[1] if len(rows) > 1 else rows[0])
        return StockQuote(symbol,
                          price=pick(last, "close", "c", "closePrice"),
                          prev_close=pick(prev, "close", "c", "closePrice"))


# =============================================================================
#  การวิเคราะห์ Breadth
# =============================================================================

def analyze_breadth(quotes: List[StockQuote]) -> dict:
    """
    ตอบคำถามเดียวที่สำคัญ: ดัชนีขยับเพราะตลาดทั้งตลาด หรือเพราะหุ้นไม่กี่ตัว
    """
    ok = [q for q in quotes if q.prev_close > 0]
    if not ok:
        return {"ok": False, "error": "ไม่มีข้อมูลที่ใช้ได้"}

    up = [q for q in ok if q.change_pct > 0]
    down = [q for q in ok if q.change_pct < 0]
    by_impact = sorted(ok, key=lambda q: q.dow_points)
    total_pts = sum(q.dow_points for q in ok)

    # หุ้น 3 ตัวที่ฉุดแรงสุด คิดเป็นกี่ % ของการเคลื่อนไหวทั้งหมด
    worst3 = sum(q.dow_points for q in by_impact[:3])
    best3 = sum(q.dow_points for q in by_impact[-3:])
    concentration = 0.0
    if total_pts != 0:
        dominant = worst3 if total_pts < 0 else best3
        concentration = abs(dominant / total_pts) * 100

    # ลำดับการตรวจสำคัญมาก: ต้องเช็ก "ดัชนีสวนทางหุ้นส่วนใหญ่" ก่อนเสมอ
    # ไม่งั้นกรณีที่หุ้น 11 จาก 13 ตัวขึ้นแต่ดัชนีลง (เพราะ 2 ตัวหนักร่วงแรง)
    # จะถูกสรุปผิดว่า "ขึ้นทั้งกระดาน" ซึ่งตรงข้ามกับความจริงที่เทรดเดอร์เห็น
    majority_up = len(up) >= len(ok) * 0.6
    majority_down = len(down) >= len(ok) * 0.6
    divergent = (majority_up and total_pts < 0) or (majority_down and total_pts > 0)

    if len(ok) == 0:
        verdict = "ไม่พอประเมิน"
    elif divergent:
        direction = "ลง" if total_pts < 0 else "ขึ้น"
        side = "ขึ้น" if majority_up else "ลง"
        verdict = (f"⚠ ดัชนี{direction}สวนทางกับหุ้นส่วนใหญ่ที่{side} "
                   f"— ถูกลากด้วยหุ้นน้ำหนักหนักไม่กี่ตัว ไม่ใช่ทิศทางตลาดจริง")
    elif concentration > 120:
        verdict = "ดัชนีถูกลากด้วยหุ้นไม่กี่ตัว — ระวังการกลับตัว"
    elif len(down) >= len(ok) * 0.7:
        verdict = "ตลาดลงทั้งกระดาน (breadth แย่จริง)"
    elif len(up) >= len(ok) * 0.7:
        verdict = "ตลาดขึ้นทั้งกระดาน (breadth ดีจริง)"
    else:
        verdict = "ผสม ไม่มีข้อสรุปชัด"

    return {
        "ok": True,
        "at": datetime.now().isoformat(timespec="seconds"),
        "counted": len(ok), "up": len(up), "down": len(down),
        "total_points": round(total_pts, 1),
        "concentration_pct": round(concentration, 1),
        "verdict": verdict,
        "top_drags": [{"symbol": q.symbol, "pct": round(q.change_pct, 2),
                       "points": round(q.dow_points, 1)} for q in by_impact[:5]],
        "top_lifts": [{"symbol": q.symbol, "pct": round(q.change_pct, 2),
                       "points": round(q.dow_points, 1)} for q in reversed(by_impact[-5:])],
    }


def print_report(r: dict) -> None:
    print("=" * 70)
    print(" DOW BREADTH".center(70))
    print("=" * 70)
    if not r.get("ok"):
        print(" ", r.get("error"))
        return
    print(f" เวลา {r['at']} | นับได้ {r['counted']} ตัว")
    print(f" ขึ้น {r['up']} / ลง {r['down']} | ผลรวม {r['total_points']:+,.1f} จุด")
    print(f" กระจุกตัว {r['concentration_pct']}% ของการเคลื่อนไหว")
    print(f"\n สรุป: {r['verdict']}")
    print("\n ตัวที่ฉุดมากที่สุด")
    for x in r["top_drags"]:
        print(f"   {x['symbol']:<6}{x['pct']:>7.2f}%  {x['points']:>8,.1f} จุด")
    print("\n ตัวที่หนุนมากที่สุด")
    for x in r["top_lifts"]:
        print(f"   {x['symbol']:<6}{x['pct']:>7.2f}%  {x['points']:>8,.1f} จุด")
    print("=" * 70)
    print(" หมายเหตุ: จุดดัชนีเป็นค่าประมาณจาก Dow Divisor ที่ตั้งไว้")
    print(f" ค่าที่ใช้อยู่ = {DOW_DIVISOR} (ตั้งใหม่ได้ด้วย env DOW_DIVISOR)")


def main(symbols: List[str], json_path: Optional[str]) -> int:
    cfg = WebullConfig.load()
    if not cfg:
        print("ไม่พบการตั้งค่า — ตั้ง WEBULL_APP_KEY/WEBULL_APP_SECRET")
        print(f"หรือสร้างไฟล์ {CONFIG_PATH}")
        print('  {"app_key":"...","app_secret":"...","region":"th","endpoint":"..."}')
        return 1

    print(f"region={cfg.region} | key={cfg.app_key[:12]}... | "
          f"endpoint={cfg.endpoint or '(ยังไม่ได้ตั้ง)'}")
    src = WebullSource(cfg)
    if not src.connect():
        print("เชื่อมต่อไม่สำเร็จ:", src.last_error)
        return 1
    print("สร้าง client สำเร็จ กำลังดึงข้อมูล...\n")

    quotes, failed = [], []
    for s in symbols:
        q = src.quote(s)
        if q and q.prev_close > 0:
            quotes.append(q)
        else:
            failed.append(s)
    if failed:
        print(f"ดึงไม่ได้ {len(failed)} ตัว: {', '.join(failed[:10])}")
        print(f"error ล่าสุด: {src.last_error}")
        if "403" in src.last_error:
            print("403 มักแปลว่ายังไม่ได้สมัคร market data subscription\n")
    if not quotes:
        return 1

    r = analyze_breadth(quotes)
    print_report(r)
    if json_path:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=2)
        print(f"\nบันทึก {json_path}")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Dow breadth จาก Webull OpenAPI")
    p.add_argument("--symbols", default=",".join(DOW_HEAVY),
                   help="รายชื่อหุ้นคั่นด้วยจุลภาค")
    p.add_argument("--json", default=None)
    a = p.parse_args()
    raise SystemExit(main([s.strip().upper() for s in a.symbols.split(",") if s.strip()],
                          a.json))
