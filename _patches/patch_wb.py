# -*- coding: utf-8 -*-
"""เพิ่มหุ้นสำคัญ 24 ตัว + ถ่วงน้ำหนักตามดัชนี เข้า webull_market.py (โหมด core)"""
import sys
p = sys.argv[1]
s = open(p, encoding="utf-8").read()

def rep(old, new):
    global s
    n = s.count(old)
    if n != 1:
        raise SystemExit(f"anchor พบ {n} ครั้ง: {old[:60]!r}")
    s = s.replace(old, new)

rep('''# โหมด: core (5 ตัว, ค่าเริ่มต้น)''', '''# หุ้น/ETF สำคัญเพิ่มเติม — ดึงพร้อม core ในชุดเดียว (29 ตัว = 2 request ต่อรอบ)
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

# โหมด: core (5 ตัว, ค่าเริ่มต้น)''')

# ---- ฟังก์ชันถ่วงน้ำหนัก ต่อท้าย core_snapshot ----
rep('''# ---------------------------------------------------------------------------
#  ตัวรัน
# ---------------------------------------------------------------------------''', '''def index_pulse(quotes: Dict[str, Quote]) -> dict:
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
        if idx == "US30" and p.get("rest_points") is not None and abs(p["points"]) >= 100 \\
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
# ---------------------------------------------------------------------------''')

# ---- fetch: core + extra ในชุดเดียว ----
rep('''        cq = wb.quotes(list(CORE_SYMBOLS))           # 5 ตัว = 1 request
        core = core_snapshot(cq)
        out["core"] = core
        out["risk"] = core["risk"]''', '''        # core 5 + หุ้นสำคัญ 24 = 29 ตัว = 2 request
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
        out["risk"] = rs''')

open(p, "w", encoding="utf-8").write(s)
print("webull_market patched")
