#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ทดสอบดึง "หุ้นตัวสำคัญเพิ่มเติม" จาก Webull — แยกจาก dashboard ไม่แตะ made_gui.py
- ใช้ตัวเชื่อม Webull ใน webull_market.py (batch ≤20 ตัว/request, มีหน่วงเวลา + งบ request)
- ชุดทดสอบ 24 ตัว = 2 request เท่านั้น
- ผลลัพธ์: แสดงบนจอ + บันทึก webull_extra_test_result.txt / .json
"""
import json, os, sys, time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("WEBULL_MAX_REQUESTS", "6")      # กันพลาด: ยิงได้ไม่เกิน 6 ครั้ง
import webull_market as W

GROUPS = {
    "Mega-cap คุม US100/US500": {
        "AAPL": "Apple", "AMZN": "Amazon", "GOOGL": "Alphabet", "META": "Meta",
        "AVGO": "Broadcom", "TSLA": "Tesla", "AMD": "AMD", "NFLX": "Netflix", "MU": "Micron",
    },
    "ตัวลาก US30 (ราคาสูง)": {
        "UNH": "UnitedHealth", "HD": "Home Depot", "CAT": "Caterpillar", "V": "Visa",
        "AXP": "American Express", "AMGN": "Amgen", "IBM": "IBM",
    },
    "ETF ดัชนี / ตัวยืนยันข้ามตลาด": {
        "SPY": "S&P 500", "QQQ": "Nasdaq-100", "DIA": "Dow 30", "IWM": "หุ้นเล็ก",
        "SMH": "เซมิคอนดักเตอร์", "UUP": "ดอลลาร์ (แทน DXY)", "GLD": "ทองคำ", "HYG": "หุ้นกู้เสี่ยงสูง",
    },
}

def main():
    lines = []
    def out(s=""):
        print(s); lines.append(s)

    cfg = W.WebullConfig.load()
    if not cfg:
        out("ไม่พบ webull_config.json"); return 1
    wb = W.Webull(cfg)
    if not wb.connect():
        out(f"เชื่อมต่อไม่ได้: {wb.last_error}"); return 1

    allsyms = [s for g in GROUPS.values() for s in g]
    t0 = time.time()
    q = wb.quotes(allsyms)
    dt = time.time() - t0

    out(f"ทดสอบหุ้นเพิ่มจาก Webull  {datetime.now():%Y-%m-%d %H:%M:%S}")
    out(f"ขอ {len(allsyms)} ตัว · ได้ {len(q)} ตัว · ใช้ {wb.stats['requests']} request · {dt:.1f} วินาที")
    if wb.stats.get("denied"):
        out(f"ไม่มีสิทธิ์ดู: {', '.join(wb.stats['denied'])}")
    if wb.last_error:
        out(f"ข้อความล่าสุดจาก API: {wb.last_error}")
    rows = {}
    for gname, members in GROUPS.items():
        out(""); out(f"■ {gname}")
        out(f"  {'SYM':<6}{'ชื่อ':<20}{'ราคา':>10}{'1วัน%':>8}{'5วัน%':>8}{'20วัน%':>8}{'กรอบ20':>8}{'วอลุ่ม':>8}{'แท่ง':>6}")
        for s, name in members.items():
            x = q.get(s)
            if not x:
                out(f"  {s:<6}{W.pad(name, 20)}{'— ไม่ได้ข้อมูล':>14}")
                rows[s] = {"ok": False}; continue
            r = {"ok": True, "price": round(x.price, 2), "d1": round(x.pct, 2), "d5": round(x.pct_5d, 2),
                 "d20": round(x.pct_20d, 2), "range_pos": round(x.range_pos), "vol_ratio": round(x.vol_ratio, 2),
                 "bars": len(x.closes)}
            rows[s] = r
            out(f"  {s:<6}{W.pad(name, 20)}{r['price']:>10,.2f}{r['d1']:>8.2f}{r['d5']:>8.2f}{r['d20']:>8.2f}"
                f"{r['range_pos']:>7}%{r['vol_ratio']:>7.2f}x{r['bars']:>6}")

    with open(os.path.join(HERE, "webull_extra_test_result.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    with open(os.path.join(HERE, "webull_extra_test_result.json"), "w", encoding="utf-8") as f:
        json.dump({"at": datetime.now().isoformat(timespec="seconds"), "api": wb.stats,
                   "last_error": wb.last_error, "rows": rows}, f, ensure_ascii=False, indent=2)
    out(""); out("บันทึกผลไว้ที่ webull_extra_test_result.txt")
    return 0

if __name__ == "__main__":
    sys.exit(main())
