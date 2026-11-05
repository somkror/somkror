# -*- coding: utf-8 -*-
"""แสดงผลการถ่วงน้ำหนักหุ้นตัวใหญ่ในกล่อง 'ตลาดโดยรวม'"""
import sys
p = sys.argv[1]
s = open(p, encoding="utf-8").read()

def rep(old, new):
    global s
    n = s.count(old)
    if n != 1:
        raise SystemExit(f"anchor พบ {n} ครั้ง: {old[:60]!r}")
    s = s.replace(old, new)

rep('''        for w in r.get("reasons", [])[:8]:
            t.insert("end", f"   - {w}\\n")

        k = c.get("core", {})''', '''        for w in r.get("reasons", [])[:12]:
            t.insert("end", f"   - {w}\\n")

        pl = c.get("pulse", {})
        if pl.get("ok"):
            t.insert("end", "\\n━━ ใครลากดัชนีวันนี้ (ถ่วงน้ำหนัก) ━━\\n")
            for idx in ("US30", "US100", "US500"):
                p = pl["index"].get(idx)
                if not p:
                    continue
                if idx == "US30":
                    head = f"  {idx:<6}หุ้นราคาสูง {p['points']:+,.0f} จุด"
                    if p.get("etf_points") is not None:
                        head += (f" | DIA {p['etf_d1']:+.2f}% ≈ {p['etf_points']:+,.0f} จุด"
                                 f" (ที่เหลือ {p['rest_points']:+,.0f})")
                    val = p["points"]
                    fmt = lambda x: f"{x['symbol']} {x['points']:+.0f}จ"
                else:
                    head = (f"  {idx:<6}ตัวใหญ่ {p['coverage']:.0f}% ของดัชนี ลาก {p['contrib']:+.2f}%"
                            f" (5 วัน {p['contrib5']:+.2f}%)")
                    if p.get("etf_d1") is not None:
                        head += f" | {p['etf']} {p['etf_d1']:+.2f}%"
                        if p.get("rest") is not None:
                            head += f" ที่เหลือ {p['rest']:+.2f}%"
                    val = p["contrib"]
                    fmt = lambda x: f"{x['symbol']} {x['contrib']:+.2f}"
                t.insert("end", head + "\\n", "good" if val > 0 else "bad" if val < 0 else ())
                if p["lifts"]:
                    t.insert("end", "      ดัน : " + ", ".join(fmt(x) for x in p["lifts"]) + "\\n", "good")
                if p["drags"]:
                    t.insert("end", "      ลาก : " + ", ".join(fmt(x) for x in p["drags"]) + "\\n", "bad")
            t.insert("end", "  (น้ำหนัก US100/US500 เป็นค่าประมาณ — US30 คิดจากราคาจริง)\\n", "muted")

        k = c.get("core", {})''')

open(p, "w", encoding="utf-8").write(s)
print("gui patched")
