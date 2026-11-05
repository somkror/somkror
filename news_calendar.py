#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
===============================================================================
 news_calendar.py — ข่าวและปฏิทินฟรี สำหรับเสริมระบบ MADE
===============================================================================
 ปัญหาที่โมดูลนี้แก้
   13 ต.ค. 2026 US30 ร่วง 621 จุดใน 2 ชม. เพราะ JNJ/CAT ร่วงแรงวันประกาศงบ
   ระบบที่อ่านแต่ราคา "รู้ทีหลัง" เสมอ แต่วันประกาศงบเป็นข้อมูลที่รู้ล่วงหน้าได้

 แหล่งข้อมูล (ฟรี ไม่ต้องสมัคร key)
   ปฏิทินเศรษฐกิจ : nfs.faireconomy.media (ForexFactory feed)
   ปฏิทินงบ       : api.nasdaq.com/api/calendar/earnings
   ข่าว RSS       : Yahoo Finance, CNBC, MarketWatch, Investing.com

 ใช้ stdlib ล้วน (urllib + xml.etree) ไม่ต้อง pip install อะไรเพิ่ม
 มี cache ในไฟล์ กันยิงซ้ำทุก 15 นาทีโดยไม่จำเป็น

 ใช้งาน
   python news_calendar.py                 รายงานเต็ม
   python news_calendar.py --json out.json
   python news_calendar.py --hours 4       ดูเฉพาะเหตุการณ์ใน 4 ชม. ข้างหน้า
===============================================================================
"""

from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(HERE, ".cache")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# ---------------------------------------------------------------------------
#  แหล่งข้อมูล
# ---------------------------------------------------------------------------

FF_CALENDAR = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
NASDAQ_EARNINGS = "https://api.nasdaq.com/api/calendar/earnings?date={date}"

RSS_FEEDS = [
    ("CNBC", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    ("Yahoo", "https://finance.yahoo.com/news/rssindex"),
    ("Investing", "https://www.investing.com/rss/news_25.rss"),      # เศรษฐกิจ
    ("Investing-Cmdty", "https://www.investing.com/rss/news_11.rss"),  # สินค้าโภคภัณฑ์
]

# หุ้นน้ำหนักหนักใน Dow — ถ้าตัวพวกนี้ประกาศงบ ดัชนีจะผันผวนผิดปกติ
DOW_HEAVY = {"GS", "UNH", "MSFT", "HD", "CAT", "V", "SHW", "MCD", "AXP", "AMGN",
             "TRV", "CRM", "IBM", "HON", "JNJ", "PG", "JPM", "WMT", "CVX", "MRK",
             "BA", "NVDA", "DIS", "MMM", "KO", "CSCO", "VZ", "NKE", "AAPL", "AMZN"}

# คำสำคัญ -> สินทรัพย์ที่กระทบ ใช้คัดข่าวที่เกี่ยวกับเราจริง ๆ
TOPICS = {
    "GOLD": ["gold", "bullion", "xau", "precious metal"],
    "OIL": ["oil", "crude", "opec", "brent", "wti", "barrel", "hormuz", "energy"],
    "FED": ["fed", "fomc", "powell", "warsh", "rate hike", "rate cut", "interest rate",
            "inflation", "cpi", "pce", "ppi", "jobless", "payroll", "nfp"],
    "USD": ["dollar", "dxy", "greenback", "treasury", "yield", "bond"],
    "US30": ["dow", "industrial average", "blue chip"],
    "US100": ["nasdaq", "tech stock", "semiconductor", "chip", "ai stock"],
    "US500": ["s&p", "sp500", "wall street", "stocks"],
}

HIGH_IMPACT_WORDS = ["cpi", "non-farm", "nonfarm", "payroll", "fomc", "interest rate",
                     "gdp", "pce", "unemployment", "retail sales", "ppi", "powell",
                     "warsh", "fed chair"]


# ---------------------------------------------------------------------------
#  ตัวช่วยดึงข้อมูล + cache
# ---------------------------------------------------------------------------

def _cache_path(key: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_.-]", "_", key)[:80]
    return os.path.join(CACHE_DIR, safe)


def fetch(url: str, ttl: int = 900, timeout: int = 15) -> Optional[bytes]:
    """
    ดึง URL พร้อม cache ตาม ttl วินาที (ค่าเริ่มต้น 15 นาที = รอบอัปเดตของระบบ)
    ถ้าดึงไม่ได้แต่มี cache เก่าอยู่ จะคืน cache เก่าแทนการคืน None
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    cp = _cache_path(url)
    if os.path.exists(cp) and time.time() - os.path.getmtime(cp) < ttl:
        try:
            with open(cp, "rb") as f:
                return f.read()
        except Exception:
            pass
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": UA, "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9"})
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            data = r.read()
        with open(cp, "wb") as f:
            f.write(data)
        return data
    except Exception:
        if os.path.exists(cp):          # ดึงใหม่ไม่ได้ ใช้ของเก่าดีกว่าไม่มีเลย
            try:
                with open(cp, "rb") as f:
                    return f.read()
            except Exception:
                pass
        return None


def _parse_dt(s: str) -> Optional[datetime]:
    """รองรับรูปแบบเวลาหลายแบบที่แต่ละแหล่งใช้"""
    if not s:
        return None
    s = s.strip()
    fmts = ["%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S",
            "%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z",
            "%a, %d %b %Y %H:%M:%S GMT", "%Y-%m-%d"]
    for f in fmts:
        try:
            d = datetime.strptime(s, f)
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:                                     # เผื่อรูปแบบ ISO อื่น ๆ
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _topics_of(text: str) -> List[str]:
    low = text.lower()
    return [k for k, words in TOPICS.items() if any(w in low for w in words)]


# ---------------------------------------------------------------------------
#  ปฏิทินเศรษฐกิจ
# ---------------------------------------------------------------------------

def economic_calendar(hours_ahead: int = 24) -> dict:
    raw = fetch(FF_CALENDAR, ttl=1800)
    if not raw:
        return {"ok": False, "error": "ดึงปฏิทินเศรษฐกิจไม่ได้", "events": []}
    try:
        items = json.loads(raw.decode("utf-8", "ignore"))
    except Exception as e:
        return {"ok": False, "error": f"อ่าน JSON ไม่ได้: {e}", "events": []}

    now = datetime.now(timezone.utc)
    horizon = now + timedelta(hours=hours_ahead)
    events = []
    for it in items if isinstance(items, list) else []:
        cur = str(it.get("country", it.get("currency", ""))).upper()
        title = str(it.get("title", it.get("event", "")))
        impact = str(it.get("impact", "")).lower()
        when = _parse_dt(str(it.get("date", "")))
        if not when or not title:
            continue
        high = impact.startswith("high") or any(w in title.lower() for w in HIGH_IMPACT_WORDS)
        if cur not in ("USD", "ALL") and not high:
            continue                          # สนใจเฉพาะ USD หรือข่าวแรงจริง
        if when < now - timedelta(hours=2) or when > horizon:
            continue
        mins = (when - now).total_seconds() / 60
        events.append({
            "at": when.isoformat(timespec="minutes"),
            # แปลงเป็นเวลาเครื่อง (ไทย) เพราะเทรดเดอร์ดูเวลาท้องถิ่น ไม่ใช่ UTC
            "local": when.astimezone().strftime("%H:%M"),
            "date_local": when.astimezone().strftime("%d/%m"),
            "in_minutes": round(mins),
            "currency": cur, "title": title,
            "impact": "HIGH" if high else impact.upper() or "MEDIUM",
            "forecast": it.get("forecast", ""), "previous": it.get("previous", ""),
        })
    events.sort(key=lambda e: e["in_minutes"])
    return {"ok": True, "events": events,
            "imminent": [e for e in events if 0 <= e["in_minutes"] <= 120
                         and e["impact"] == "HIGH"]}


# ---------------------------------------------------------------------------
#  ปฏิทินงบ
# ---------------------------------------------------------------------------

def earnings_calendar(days: int = 2) -> dict:
    out, errors = [], []
    for d in range(days):
        day = (datetime.now(timezone.utc) + timedelta(days=d)).strftime("%Y-%m-%d")
        raw = fetch(NASDAQ_EARNINGS.format(date=day), ttl=3600)
        if not raw:
            errors.append(day)
            continue
        try:
            js = json.loads(raw.decode("utf-8", "ignore"))
            rows = (js.get("data") or {}).get("rows") or []
        except Exception:
            errors.append(day)
            continue
        for r in rows:
            sym = str(r.get("symbol", "")).upper().strip()
            if not sym:
                continue
            out.append({"date": day, "symbol": sym,
                        "name": r.get("name", ""),
                        "time": r.get("time", ""),
                        "eps_forecast": r.get("epsForecast", ""),
                        "dow_heavy": sym in DOW_HEAVY})
    heavy = [e for e in out if e["dow_heavy"]]
    return {"ok": bool(out), "errors": errors, "count": len(out),
            "dow_heavy": sorted(heavy, key=lambda e: (e["date"], e["symbol"])),
            "warning": (f"วันนี้/พรุ่งนี้มีหุ้นน้ำหนักหนักใน Dow ประกาศงบ "
                        f"{len(heavy)} ตัว — US30 จะผันผวนผิดปกติ" if heavy else "")}


# ---------------------------------------------------------------------------
#  ข่าว RSS
# ---------------------------------------------------------------------------

def rss_news(limit_per_feed: int = 12, hours_back: int = 12) -> dict:
    now = datetime.now(timezone.utc)
    items, failed = [], []
    for name, url in RSS_FEEDS:
        raw = fetch(url, ttl=900)
        if not raw:
            failed.append(name)
            continue
        try:
            root = ET.fromstring(raw)
        except Exception:
            failed.append(name)
            continue
        nodes = root.findall(".//item") or root.findall(
            ".//{http://www.w3.org/2005/Atom}entry")
        for n in nodes[:limit_per_feed]:
            def txt(*tags):
                for t in tags:
                    el = n.find(t)
                    if el is not None and (el.text or el.get("href")):
                        return (el.text or el.get("href", "")).strip()
                return ""
            title = txt("title", "{http://www.w3.org/2005/Atom}title")
            if not title:
                continue
            when = _parse_dt(txt("pubDate", "published",
                                 "{http://www.w3.org/2005/Atom}updated"))
            if when and (now - when) > timedelta(hours=hours_back):
                continue
            tops = _topics_of(title)
            items.append({
                "source": name, "title": title,
                "link": txt("link", "{http://www.w3.org/2005/Atom}link"),
                "at": when.isoformat(timespec="minutes") if when else "",
                "minutes_ago": round((now - when).total_seconds() / 60) if when else None,
                "topics": tops,
                "relevant": bool(tops),
            })
    seen, uniq = set(), []
    for it in items:                       # ข่าวเดียวกันมักโผล่หลายสำนัก
        key = re.sub(r"\W+", "", it["title"].lower())[:60]
        if key in seen:
            continue
        seen.add(key)
        uniq.append(it)
    uniq.sort(key=lambda i: (not i["relevant"],
                             i["minutes_ago"] if i["minutes_ago"] is not None else 9999))

    by_topic: Dict[str, int] = {}
    for it in uniq:
        for t in it["topics"]:
            by_topic[t] = by_topic.get(t, 0) + 1
    return {"ok": bool(uniq), "failed_feeds": failed,
            "items": uniq, "relevant": [i for i in uniq if i["relevant"]][:20],
            "topic_counts": dict(sorted(by_topic.items(), key=lambda kv: -kv[1]))}


# ---------------------------------------------------------------------------
#  รวมเป็นคำเตือนที่ใช้ตัดสินใจได้
# ---------------------------------------------------------------------------

def build_alerts(eco: dict, earn: dict, news: dict) -> List[dict]:
    """แปลงข้อมูลดิบเป็นคำเตือนที่บอกได้ว่า "ควรทำอะไร" ไม่ใช่แค่ "เกิดอะไร" """
    alerts = []
    for e in eco.get("imminent", []):
        alerts.append({
            "level": "high",
            "text": (f"อีก {e['in_minutes']} นาที ({e['local']} น.): "
                     f"{e['title']} [{e['currency']}]"),
            "action": "ไม่เปิดไม้ใหม่ และพิจารณาลดขนาดไม้ที่ถืออยู่"})
    for e in eco.get("events", []):
        if e["impact"] == "HIGH" and 120 < e["in_minutes"] <= 480:
            alerts.append({
                "level": "medium",
                "text": f"วันนี้ {e['local']} น.: {e['title']}",
                "action": "วางแผนล่วงหน้า หลีกเลี่ยงการถือข้ามช่วงประกาศ"})
    if earn.get("dow_heavy"):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        tds = [e["symbol"] for e in earn["dow_heavy"] if e["date"] == today]
        if tds:
            alerts.append({
                "level": "high",
                "text": f"วันนี้ประกาศงบ: {', '.join(tds)}",
                "action": "US30 เสี่ยงถูกลากด้วยหุ้นรายตัว — เทคนิคเชื่อถือได้น้อยลง"})
        tm = [e["symbol"] for e in earn["dow_heavy"] if e["date"] != today]
        if tm:
            alerts.append({
                "level": "medium",
                "text": f"พรุ่งนี้ประกาศงบ: {', '.join(tm)}",
                "action": "ระวังการถือ US30 ข้ามคืน"})
    tc = news.get("topic_counts", {})
    for topic, n in tc.items():
        if n >= 4:
            alerts.append({
                "level": "info",
                "text": f"ข่าวเกี่ยวกับ {topic} หนาแน่น ({n} ข่าวใน 12 ชม.)",
                "action": "อ่านหัวข้อก่อนเทรดสินทรัพย์นี้"})
    order = {"high": 0, "medium": 1, "info": 2}
    alerts.sort(key=lambda a: order.get(a["level"], 3))
    return alerts


def fetch_news_calendar(hours_ahead: int = 24) -> dict:
    eco = economic_calendar(hours_ahead)
    earn = earnings_calendar(2)
    news = rss_news()
    return {"ok": any([eco.get("ok"), earn.get("ok"), news.get("ok")]),
            "at": datetime.now().isoformat(timespec="seconds"),
            "economic": eco, "earnings": earn, "news": news,
            "alerts": build_alerts(eco, earn, news)}


# ---------------------------------------------------------------------------
#  แสดงผล
# ---------------------------------------------------------------------------

def print_report(c: dict) -> None:
    print("=" * 74)
    print(" ข่าวและปฏิทิน ".center(74, "="))
    print("=" * 74)
    print(f" เวลา {c['at']}")

    if c["alerts"]:
        print("\n━━ คำเตือน ━━")
        icon = {"high": "🔴", "medium": "🟡", "info": "🔵"}
        for a in c["alerts"]:
            print(f" {icon.get(a['level'],'•')} {a['text']}")
            print(f"    → {a['action']}")
    else:
        print("\n ไม่มีคำเตือนที่ต้องดำเนินการ")

    eco = c["economic"]
    print("\n━━ ปฏิทินเศรษฐกิจ ━━")
    if not eco.get("ok"):
        print("  ", eco.get("error"))
    else:
        for e in eco["events"][:12]:
            when = ("ผ่านไป" if e["in_minutes"] < 0 else "อีก") + \
                   f" {abs(e['in_minutes'])} นาที"
            flag = "🔴" if e["impact"] == "HIGH" else "  "
            fc = f" | คาด {e['forecast']} ก่อนหน้า {e['previous']}" if e["forecast"] else ""
            print(f" {flag} {e['local']} [{e['currency']}] {e['title']} ({when}){fc}")

    earn = c["earnings"]
    print("\n━━ ปฏิทินงบ (เฉพาะหุ้นน้ำหนักหนักใน Dow) ━━")
    if earn.get("dow_heavy"):
        for e in earn["dow_heavy"]:
            print(f"  {e['date']}  {e['symbol']:<6}{e['name'][:32]:<34}{e['time']}")
        print(f"  ⚠ {earn['warning']}")
    else:
        print("  ไม่มี (หรือดึงข้อมูลไม่ได้)")

    news = c["news"]
    print("\n━━ ข่าวที่เกี่ยวข้อง ━━")
    if news.get("ok"):
        if news.get("topic_counts"):
            print("  หมวดที่ข่าวหนาแน่น: " + ", ".join(
                f"{k}({v})" for k, v in news["topic_counts"].items()))
        for n in news["relevant"][:12]:
            ago = f"{n['minutes_ago']} นาทีก่อน" if n["minutes_ago"] is not None else ""
            print(f"  [{','.join(n['topics'])}] {n['title'][:80]}")
            print(f"      {n['source']} {ago}")
        if news.get("failed_feeds"):
            print("  (ดึงไม่ได้: " + ", ".join(news["failed_feeds"]) + ")")
    else:
        print("  ดึงข่าวไม่ได้")
    print("\n" + "=" * 74)
    print(" ข้อมูลประกอบการตัดสินใจ ไม่ใช่คำแนะนำการลงทุน")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--json", nargs="?", const=os.path.join(HERE, "news_context.json"),
                   default=None)
    p.add_argument("--hours", type=int, default=24)
    a = p.parse_args()
    c = fetch_news_calendar(a.hours)
    print_report(c)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(c, f, ensure_ascii=False, indent=2)
        print(f"\nบันทึก {a.json}")
    return 0 if c["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
