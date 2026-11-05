#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
===============================================================================
 MADE Dashboard — Multi-Asset Decision Engine
===============================================================================
 โครงหน้าจอ
   (v2 หน้าจอเดียว — ออกแบบให้พอดีจอ Full HD 1920×1080 ตอน Maximize)
   แถบบน      แหล่งข้อมูล ความเสี่ยง รอบอัปเดต ปุ่มเริ่ม/หยุด + ตัวเลือก + นาฬิกา
   การ์ด KPI  สถานะ | REGIME | ความเสี่ยงตลาด | เตือน | แข็งสุด | อ่อนสุด | บัญชี
   แท็บ       แดชบอร์ด / บันทึก / Weekly Screener
   แดชบอร์ด   แถวบน  : กราฟ | ข้อเสนอแนะ (ไม้ที่แนะนำ) + โซนรอเข้า
              แถวล่าง: อันดับความแข็งแรง | ตลาดโดยรวม | ข่าว + ปฏิทิน
   แถบล่าง    สถานะ + บันทึกล่าสุด 1 บรรทัด + ปุ่มฟอนต์ + ไปแท็บบันทึก
   ทุกกล่องลากเส้นคั่นปรับขนาดได้ / ดับเบิลคลิกหัวกล่อง = ขยายเต็มแดชบอร์ด

 ต้องมีไฟล์เหล่านี้อยู่โฟลเดอร์เดียวกัน
   multi_asset_decision_engine.py          (บังคับ)
   webull_market.py + webull_config.json   (ถ้าต้องการบริบทตลาด)

 ปิดโปรแกรม = ปิด connection, ล้าง widget, ถอดโมดูล, gc แล้วคืน memory ให้ OS
===============================================================================
"""

from __future__ import annotations

import gc
import importlib.util
import os
import queue
import sys
import threading
from datetime import datetime, timedelta, timezone

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE_PATH = os.path.join(HERE, "multi_asset_decision_engine.py")
WEBULL_PATH = os.path.join(HERE, "webull_market.py")
NEWS_PATH = os.path.join(HERE, "news_calendar.py")

#: ฟังก์ชันที่ dashboard ต้องใช้จาก engine — ขาดแปลว่าไฟล์เก่า
REQUIRED = ("make_source", "analyze", "CFG", "ASSETS")

CLR = {"card": "#ffffff", "up": "#1b7f3b", "down": "#c62828", "warn": "#ef6c00",
       "muted": "#6b7280", "ink": "#111827", "accent": "#1565c0"}


def load_engine():
    spec = importlib.util.spec_from_file_location("made_engine", ENGINE_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["made_engine"] = mod
    spec.loader.exec_module(mod)
    if "chart_bars" not in getattr(mod, "CFG", {}):
        print("[MADE] เตือน: engine ไม่มี CFG['chart_bars'] — แท็บกราฟจะว่าง")
    missing = [n for n in REQUIRED if not hasattr(mod, n)]
    if missing:
        sys.modules.pop("made_engine", None)
        raise RuntimeError("ไฟล์ multi_asset_decision_engine.py เป็นเวอร์ชันเก่า\n"
                           f"ขาด: {', '.join(missing)}\n\nคัดลอกไฟล์ล่าสุดมาทับที่\n"
                           f"{ENGINE_PATH}")
    return mod


def rss_mb() -> float:
    try:
        with open(f"/proc/{os.getpid()}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
    except Exception:
        pass
    try:
        import ctypes
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t)]
        c = PMC(); c.cb = ctypes.sizeof(PMC)
        ctypes.windll.psapi.GetProcessMemoryInfo(
            ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(c), c.cb)
        return c.WorkingSetSize / (1024 * 1024)
    except Exception:
        return 0.0



# =============================================================================
#  นาฬิกาและเซสชันตลาด
#
#  แสดงเวลาไทย (UTC+7) และบอกว่าตลาดไหนเปิดอยู่
#  คำนวณ DST เอง ไม่พึ่ง zoneinfo เพราะบน Windows ต้องลง tzdata เพิ่ม
# =============================================================================

TH_MONTH = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
            "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
TH_DAY = ["จ.", "อ.", "พ.", "พฤ.", "ศ.", "ส.", "อา."]   # datetime.weekday() 0=จันทร์


def _nth_sunday(year: int, month: int, n: int) -> datetime:
    d = datetime(year, month, 1)
    return d + timedelta(days=(6 - d.weekday()) % 7 + 7 * (n - 1))


def _last_sunday(year: int, month: int) -> datetime:
    nxt = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
    d = nxt - timedelta(days=1)
    return d - timedelta(days=(d.weekday() + 1) % 7)


def us_dst(utc: datetime) -> bool:
    """สหรัฐฯ: อาทิตย์ที่ 2 ของมีนาคม ถึง อาทิตย์ที่ 1 ของพฤศจิกายน (2am ET)"""
    y = utc.year
    return _nth_sunday(y, 3, 2).replace(hour=7) <= utc < _nth_sunday(y, 11, 1).replace(hour=6)


def eu_dst(utc: datetime) -> bool:
    """ยุโรป: อาทิตย์สุดท้ายของมีนาคม ถึง อาทิตย์สุดท้ายของตุลาคม (01:00 UTC)"""
    y = utc.year
    return _last_sunday(y, 3).replace(hour=1) <= utc < _last_sunday(y, 10).replace(hour=1)


def market_sessions(utc: datetime):
    """
    คืนสถานะเซสชันตลาด โดยอิงเวลาไทย (UTC+7)
    ชั่วโมงเปิด-ปิดเป็นทศนิยม เช่น 20.5 = 20:30 น.
    """
    th = utc + timedelta(hours=7)
    usd, eud = us_dst(utc), eu_dst(utc)

    # เวลาไทยของแต่ละเซสชัน (ขยับตาม DST)
    specs = [
        ("หุ้นสหรัฐฯ", 20.5 if usd else 21.5, 27.0 if usd else 28.0),  # 9:30-16:00 ET
        ("ลอนดอน", 14.0 if eud else 15.0, 22.0 if eud else 23.0),      # 8:00-16:00 UK
        ("โตเกียว", 7.0, 15.0),                                         # 9:00-17:00 JST
    ]

    out = []
    now_h = th.hour + th.minute / 60 + th.second / 3600
    weekend = th.weekday() >= 5          # เสาร์-อาทิตย์

    for name, op, cl in specs:
        # เซสชันที่ข้ามเที่ยงคืนต้องเทียบสองช่วง
        if cl > 24:
            is_open = now_h >= op or now_h < (cl - 24)
            nxt = (cl - 24) if now_h < (cl - 24) else (op if now_h < op else cl - 24)
        else:
            is_open = op <= now_h < cl
            nxt = cl if is_open else op

        if weekend:
            is_open = False

        # เวลาที่เหลือจนถึงการเปลี่ยนสถานะครั้งถัดไป
        delta = (nxt - now_h) % 24
        out.append({"name": name, "open": is_open,
                    "hours_left": delta,
                    "label": ("ปิดใน" if is_open else "เปิดใน") +
                             f" {int(delta):d}:{int(delta % 1 * 60):02d}"})

    return {"th": th, "weekend": weekend, "us_dst": usd, "eu_dst": eud,
            "sessions": out,
            "open_now": [s["name"] for s in out if s["open"]]}


# =============================================================================
#  Worker — เธรดเดียว ทำงานเป็นรอบ สื่อสารกับ GUI ผ่าน queue เท่านั้น
# =============================================================================

class Worker(threading.Thread):
    def __init__(self, engine, cfg: dict, q: "queue.Queue", stop_event: threading.Event):
        super().__init__(daemon=True)
        self.E, self.cfg, self.q = engine, cfg, q
        self.stop_event = stop_event
        self.wake = threading.Event()      # ปลุกให้อัปเดตทันทีโดยไม่รอครบรอบ
        self.src = None

    def log(self, msg, level="info"):
        self.q.put(("log", (msg, level)))

    def run(self):
        E = self.E
        try:
            self.src, mode = E.make_source(self.cfg.get("data_dir"), self.cfg.get("mt5linux"))
            E.SRC = self.src
            self.log(f"แหล่งข้อมูล: {mode}")
            if not self.src.connect():
                self.log("เชื่อมต่อไม่สำเร็จ — ดูรายละเอียดในหน้าต่าง terminal", "error")
                self.q.put(("stopped", None))
                return
            self.log("เชื่อมต่อสำเร็จ", "ok")

            while not self.stop_event.is_set():
                self.one_cycle()
                if self.stop_event.is_set():
                    break
                mins = self.cfg["interval_min"]
                nxt = datetime.now() + timedelta(minutes=mins)
                self.q.put(("next", nxt))
                self.wake.clear()
                self.wake.wait(timeout=mins * 60)
        except Exception as e:
            self.log(f"เธรดล้มเหลว: {type(e).__name__}: {e}", "error")
        finally:
            self.cleanup()
            self.q.put(("stopped", None))

    def one_cycle(self):
        E = self.E
        self.q.put(("busy", True))
        try:
            acc = self.src.account()
            balance = float(acc.get("balance", 0.0)) if acc else 0.0
            self.q.put(("account", acc))
            result = E.analyze(balance, self.cfg["risk_percent"])
            self.q.put(("result", result))
            if result.get("error"):
                self.log(f"วิเคราะห์ไม่สำเร็จ: {result['error']}", "error")
            else:
                self.log(f"อัปเดตเสร็จ {result['at']:%H:%M:%S}", "ok")
            for w in result.get("warnings", []):
                self.log(w, "warn")

            if self.cfg.get("export_zones") and result.get("ranked"):
                path = E.export_zones_csv(result["ranked"])
                if path:
                    n = sum(len(st.zones) for st in result["ranked"])
                    self.log(f"ส่ง {n} โซนให้ MT5 ({os.path.basename(path)})")
                else:
                    self.log("หาโฟลเดอร์ Common/Files ของ MT5 ไม่เจอ", "warn")
        except Exception as e:
            self.log(f"รอบนี้ผิดพลาด: {type(e).__name__}: {e}", "error")

        if self.cfg.get("use_webull"):
            self.fetch_market()
        else:
            self.q.put(("market", {"ok": False,
                                   "error": "ปิดการใช้งานอยู่ — ติ๊ก 'บริบทตลาดจาก Webull'"}))
        if self.cfg.get("use_news"):
            self.fetch_news()
        else:
            self.q.put(("news", {"ok": False,
                                 "error": "ปิดการใช้งานอยู่ — ติ๊ก 'ข่าว + ปฏิทิน'"}))
        self.q.put(("busy", False))

    def fetch_news(self):
        """ข่าว/ปฏิทิน — แยก try ออกมา เน็ตล่มต้องไม่ล้มรอบวิเคราะห์"""
        try:
            if not os.path.exists(NEWS_PATH):
                msg = f"ไม่พบไฟล์ news_calendar.py ที่\n{NEWS_PATH}"
                self.q.put(("news", {"ok": False, "error": msg}))
                self.log("ไม่พบ news_calendar.py — ข้ามข่าว/ปฏิทิน", "warn")
                return
            spec = importlib.util.spec_from_file_location("news_calendar", NEWS_PATH)
            mod = importlib.util.module_from_spec(spec)
            sys.modules["news_calendar"] = mod
            spec.loader.exec_module(mod)
            ctx = mod.fetch_news_calendar(24)
            self.q.put(("news", ctx))
            highs = [a for a in ctx.get("alerts", []) if a["level"] == "high"]
            for a in highs:
                self.log(f"⚠ {a['text']}", "warn")
            if not ctx.get("ok"):
                self.log("ดึงข่าว/ปฏิทินไม่ได้", "warn")
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            self.q.put(("news", {"ok": False, "error": err}))
            self.log(f"ข่าว/ปฏิทินผิดพลาด: {err}", "warn")

    def fetch_market(self):
        """แยก try ออกมา — Webull ล่มต้องไม่ล้มรอบวิเคราะห์หลัก"""
        try:
            if not os.path.exists(WEBULL_PATH):
                msg = f"ไม่พบไฟล์ webull_market.py ที่\n{WEBULL_PATH}"
                self.q.put(("market", {"ok": False, "error": msg}))
                self.log("ไม่พบ webull_market.py — ข้ามบริบทตลาด", "warn")
                return
            spec = importlib.util.spec_from_file_location("webull_market", WEBULL_PATH)
            mod = importlib.util.module_from_spec(spec)
            sys.modules["webull_market"] = mod
            spec.loader.exec_module(mod)
            ctx = mod.fetch_market_context()
            self.q.put(("market", ctx))
            if ctx.get("ok"):
                r = ctx.get("risk", {})
                self.log(f"Webull: {r.get('label','-')} ({r.get('score','-')})", "ok")
            else:
                self.log(f"Webull: {ctx.get('error')}", "warn")
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            self.q.put(("market", {"ok": False, "error": err}))
            self.log(f"Webull ผิดพลาด: {err}", "warn")

    def cleanup(self):
        try:
            if self.src:
                self.src.close()
            if hasattr(self.src, "cache"):
                self.src.cache.clear()
        except Exception:
            pass
        self.src = None
        try:
            self.E.SRC = None
        except Exception:
            pass


# =============================================================================
#  การ์ด KPI
# =============================================================================

class Card(ttk.Frame):
    """กล่องตัวเลขเด่น: หัวข้อเล็ก + ค่าใหญ่ + คำอธิบายย่อย"""

    def __init__(self, parent, title: str, width: int = 180):
        super().__init__(parent, relief="solid", borderwidth=1, padding=(10, 6))
        self.lbl_title = ttk.Label(self, text=title, foreground=CLR["muted"])
        self.lbl_title.pack(anchor="w")
        self.lbl_value = ttk.Label(self, text="—", font=("TkDefaultFont", 14, "bold"))
        self.lbl_value.pack(anchor="w")
        self.lbl_sub = ttk.Label(self, text="", foreground=CLR["muted"], wraplength=width)
        self.lbl_sub.pack(anchor="w")

    def set(self, value: str, sub: str = "", color: str = None):
        self.lbl_value.configure(text=value, foreground=color or CLR["ink"])
        self.lbl_sub.configure(text=sub)

    def apply_font(self, fs: int):
        self.lbl_title.configure(font=("TkDefaultFont", max(7, fs - 1)))
        self.lbl_value.configure(font=("TkDefaultFont", fs + 4, "bold"))
        self.lbl_sub.configure(font=("TkDefaultFont", max(7, fs - 1)))


# =============================================================================
#  Dashboard
# =============================================================================

class App(tk.Tk):
    REFRESH_MS = 200

    def __init__(self):
        super().__init__()
        self.title("MADE — Multi-Asset Decision Engine")
        self.geometry("1920x1000+0+0")
        self.minsize(1280, 720)
        try:
            self.state("zoomed")          # Windows: เปิดแบบ Maximize เต็มจอ
        except tk.TclError:
            pass

        self.engine = None
        self.worker = None
        self.stop_event = None
        self.q: "queue.Queue" = queue.Queue()
        self.next_run = None
        self._last_ranked = None
        self._last_market = None
        self.font_size = tk.IntVar(value=10)
        self.style = ttk.Style(self)

        self._build()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(self.REFRESH_MS, self._pump)
        self._tick()
        self._apply_font()

    # ---------------- layout ----------------
    def _build(self):
        pad = dict(padx=8, pady=5)

        bar = ttk.Frame(self); bar.pack(fill="x", **pad)
        ttk.Label(bar, text="แหล่งข้อมูล").grid(row=0, column=0, sticky="w")
        self.src_mode = tk.StringVar(value="native")
        for i, (txt, val) in enumerate([("MT5 (Windows)", "native"),
                                        ("rpyc / Wine", "rpyc"),
                                        ("ไฟล์ JSON", "file")]):
            ttk.Radiobutton(bar, text=txt, value=val, variable=self.src_mode,
                            command=self._sync).grid(row=0, column=1 + i, sticky="w", padx=3)
        self.host_var = tk.StringVar(value="localhost:18812")
        self.host_entry = ttk.Entry(bar, textvariable=self.host_var, width=18)
        self.host_entry.grid(row=0, column=4, padx=6)
        self.dir_var = tk.StringVar()
        self.dir_entry = ttk.Entry(bar, textvariable=self.dir_var, width=22)
        self.dir_entry.grid(row=0, column=5)
        self.dir_btn = ttk.Button(bar, text="…", width=3, command=self._pick)
        self.dir_btn.grid(row=0, column=6, padx=(2, 10))

        ttk.Label(bar, text="เสี่ยง/ไม้ %").grid(row=0, column=7, sticky="e")
        self.risk_var = tk.DoubleVar(value=2.0)
        ttk.Spinbox(bar, from_=0.5, to=10, increment=0.5, width=5,
                    textvariable=self.risk_var).grid(row=0, column=8, padx=3)
        ttk.Label(bar, text="ทุก (นาที)").grid(row=0, column=9, sticky="e")
        self.interval_var = tk.IntVar(value=15)
        ttk.Spinbox(bar, from_=1, to=240, width=5,
                    textvariable=self.interval_var).grid(row=0, column=10, padx=3)

        self.btn_start = ttk.Button(bar, text="▶ เริ่ม", width=9, command=self.on_start)
        self.btn_start.grid(row=0, column=11, padx=(10, 2))
        self.btn_stop = ttk.Button(bar, text="■ หยุด", width=9,
                                   command=self.on_stop, state="disabled")
        self.btn_stop.grid(row=0, column=12, padx=2)
        self.btn_now = ttk.Button(bar, text="⟳ เดี๋ยวนี้", width=10,
                                  command=self.on_now, state="disabled")
        self.btn_now.grid(row=0, column=13, padx=2)

        # --- นาฬิกาเวลาไทย + สถานะเซสชันตลาด ---
        clk = ttk.Frame(bar, relief="solid", borderwidth=1, padding=(10, 2))
        clk.grid(row=0, column=14, rowspan=2, padx=(16, 0), sticky="e")
        bar.columnconfigure(14, weight=1)
        self.clock_time = ttk.Label(clk, text="--:--:--",
                                    font=("TkFixedFont", 17, "bold"))
        self.clock_time.pack(anchor="e")
        self.clock_date = ttk.Label(clk, text="เวลาไทย (UTC+7)",
                                    foreground=CLR["muted"])
        self.clock_date.pack(anchor="e")
        self.clock_sess = ttk.Label(clk, text="", foreground=CLR["muted"])
        self.clock_sess.pack(anchor="e")

        # ตัวเลือก — ย้ายขึ้นมาเป็นแถวที่ 2 ของแถบบน (นาฬิกาคร่อม 2 แถว) ประหยัดความสูง
        opt = ttk.Frame(bar); opt.grid(row=1, column=0, columnspan=14, sticky="w", pady=(4, 0))
        self.use_webull = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt, text="บริบทตลาดจาก Webull",
                        variable=self.use_webull).pack(side="left")
        self.use_news = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt, text="ข่าว + ปฏิทิน",
                        variable=self.use_news).pack(side="left", padx=12)
        self.export_zones = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt, text="ส่งโซนให้ MT5 วาด",
                        variable=self.export_zones).pack(side="left", padx=12)
        ttk.Label(opt, text="ลากเส้นคั่นปรับขนาด · ดับเบิลคลิกหัวกล่องเพื่อขยาย",
                  foreground=CLR["muted"]).pack(side="left", padx=14)

        cards = ttk.Frame(self); cards.pack(fill="x", padx=8, pady=(2, 4))
        self.cards = {}
        for key, title in [("state", "สถานะ"), ("regime", "REGIME"),
                           ("risk", "ความเสี่ยงตลาด"), ("alert", "เตือนล่วงหน้า"),
                           ("strong", "แข็งที่สุด"), ("weak", "อ่อนที่สุด"),
                           ("account", "บัญชี")]:
            c = Card(cards, title)
            c.pack(side="left", fill="x", expand=True, padx=3)
            self.cards[key] = c
        self.cards["state"].set("หยุดอยู่", "กดเริ่มเพื่อ monitor", CLR["muted"])

        # แถบล่าง ต้อง pack ก่อน notebook ไม่งั้นโดนดันหลุดจอตอนหน้าต่างเตี้ย
        sbar = ttk.Frame(self, relief="sunken", padding=(6, 2))
        sbar.pack(fill="x", side="bottom")
        self.status = ttk.Label(sbar, anchor="w",
                                text=f"พร้อมใช้งาน | หน่วยความจำ {rss_mb():.1f} MB")
        self.status.pack(side="left")
        ttk.Separator(sbar, orient="vertical").pack(side="left", fill="y", padx=8)
        self.last_log = ttk.Label(sbar, anchor="w", text="", foreground=CLR["muted"])
        self.last_log.pack(side="left", fill="x", expand=True)
        ttk.Button(sbar, text="ดูบันทึกทั้งหมด →", width=16,
                   command=lambda: self.nb.select(self.log_tab)).pack(side="right", padx=(6, 0))
        ttk.Button(sbar, text="A+", width=4,
                   command=lambda: self._bump(1)).pack(side="right", padx=2)
        ttk.Button(sbar, text="A−", width=4,
                   command=lambda: self._bump(-1)).pack(side="right", padx=2)

        nb = ttk.Notebook(self); nb.pack(fill="both", expand=True, padx=8, pady=(0, 4))
        self.nb = nb

        # ================= แท็บ 1: แดชบอร์ด (หน้าจอเดียว) =================
        dash = ttk.Frame(nb); nb.add(dash, text="  แดชบอร์ด  ")
        self.dash = dash
        self.vp = ttk.PanedWindow(dash, orient="vertical")
        self.vp.pack(fill="both", expand=True)
        self.top_pw = ttk.PanedWindow(self.vp, orient="horizontal")
        self.bot_pw = ttk.PanedWindow(self.vp, orient="horizontal")
        self.vp.add(self.top_pw, weight=3)
        self.vp.add(self.bot_pw, weight=2)

        # --- แถวบนซ้าย: กราฟ ---
        chart_fr = ttk.LabelFrame(self.top_pw, text="กราฟ")
        self.top_pw.add(chart_fr, weight=3)
        ctrl = ttk.Frame(chart_fr); ctrl.pack(fill="x", padx=5, pady=(3, 0))
        ttk.Label(ctrl, text="สินทรัพย์").pack(side="left")
        self.chart_sym = tk.StringVar()
        self.chart_cb = ttk.Combobox(ctrl, textvariable=self.chart_sym,
                                     state="readonly", width=12, values=[])
        self.chart_cb.pack(side="left", padx=6)
        self.chart_cb.bind("<<ComboboxSelected>>", lambda e: self._draw_chart())
        self.show_zone_boxes = tk.BooleanVar(value=True)
        ttk.Checkbutton(ctrl, text="แสดงโซน", variable=self.show_zone_boxes,
                        command=self._draw_chart).pack(side="left", padx=10)
        self.chart_info = ttk.Label(ctrl, text="", foreground=CLR["muted"])
        self.chart_info.pack(side="left", padx=8)
        self.canvas = tk.Canvas(chart_fr, bg="white", highlightthickness=0,
                                width=300, height=200)
        self.canvas.pack(fill="both", expand=True, padx=5, pady=5)
        self.canvas.bind("<Configure>", lambda e: self._draw_chart())

        # --- แถวบนขวา: ข้อเสนอแนะ (ไม้ที่แนะนำ + ด่าน) อยู่บน, โซนรอเข้าอยู่ล่าง ---
        self.right_pw = ttk.PanedWindow(self.top_pw, orient="vertical")
        self.top_pw.add(self.right_pw, weight=2)
        sig_fr, self.sig_text = self._pane(self.right_pw, "ข้อเสนอแนะ — ไม้ที่แนะนำ")
        self.right_pw.add(sig_fr, weight=1)
        zone_fr, self.zone_text = self._pane(self.right_pw, "โซนรอเข้า")
        self.right_pw.add(zone_fr, weight=1)
        self.zone_text.tag_configure("buy", foreground=CLR["up"])
        self.zone_text.tag_configure("sell", foreground=CLR["down"])
        self.zone_text.tag_configure("near", background="#fff8e1")

        # --- แถวล่าง 1: อันดับความแข็งแรง ---
        rank_fr = ttk.LabelFrame(self.bot_pw, text="อันดับความแข็งแรง")
        self.bot_pw.add(rank_fr, weight=1)
        cols = ("rank", "asset", "score", "price", "atr", "structure")
        heads = ("อันดับ", "สินทรัพย์", "คะแนน", "ราคา", "ATR", "โครงสร้าง")
        widths = (50, 80, 70, 100, 70, 180)
        self.tree = ttk.Treeview(rank_fr, columns=cols, show="headings", height=5)
        for c, h, w in zip(cols, heads, widths):
            self.tree.heading(c, text=h)
            self.tree.column(c, width=w, minwidth=40, stretch=True,
                             anchor="center" if c != "structure" else "w")
        sb = ttk.Scrollbar(rank_fr, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True, padx=5, pady=5)
        self.tree.tag_configure("strong", background="#e8f5e9")
        self.tree.tag_configure("weak", background="#ffebee")

        # --- แถวล่าง 2: ตลาดโดยรวม ---
        mkt_fr, self.mkt_text = self._pane(self.bot_pw, "ตลาดโดยรวม")
        self.bot_pw.add(mkt_fr, weight=1)
        for t, c in (("good", CLR["up"]), ("bad", CLR["down"]),
                     ("warn", CLR["warn"]), ("muted", CLR["muted"])):
            self.mkt_text.tag_configure(t, foreground=c)

        # --- แถวล่าง 3: ข่าว + ปฏิทิน ---
        news_fr, self.news_text = self._pane(self.bot_pw, "ข่าว + ปฏิทิน")
        self.bot_pw.add(news_fr, weight=1)
        for t, c in (("good", CLR["up"]), ("bad", CLR["down"]),
                     ("warn", CLR["warn"]), ("muted", CLR["muted"])):
            self.news_text.tag_configure(t, foreground=c)

        # ดับเบิลคลิกหัวกล่อง (หรือขอบกล่อง) = ขยายเต็มแดชบอร์ด / กดซ้ำเพื่อคืน
        self._max_panel = None
        self._panel_order = [chart_fr, sig_fr, zone_fr, rank_fr, mkt_fr, news_fr]
        for fr in self._panel_order:
            fr.bind("<Double-Button-1>", lambda e, f=fr: self._toggle_max(f))

        # ================= แท็บ 2: บันทึก =================
        log_fr, self.log_text = self._pane(nb, None)
        nb.add(log_fr, text="  บันทึก  ")
        self.log_tab = log_fr
        for t, c in (("ok", CLR["up"]), ("error", CLR["down"]), ("warn", CLR["warn"])):
            self.log_text.tag_configure(t, foreground=c)

        # ================= แท็บ 3: Weekly Screener =================
        scr_fr = ttk.Frame(nb); nb.add(scr_fr, text="  Weekly Screener  ")
        sctl = ttk.Frame(scr_fr); sctl.pack(fill="x", padx=5, pady=(5, 0))
        ttk.Label(sctl, text="ทุนหุ้น (USD)").pack(side="left")
        self.scr_capital = tk.StringVar(value=os.environ.get("MADE_STOCK_CAPITAL", "1000"))
        ttk.Entry(sctl, textvariable=self.scr_capital, width=9).pack(side="left", padx=(4, 12))
        ttk.Label(sctl, text="เสี่ยงต่อไม้ (%)").pack(side="left")
        self.scr_risk = tk.StringVar(value=os.environ.get("MADE_STOCK_RISK", "1.0"))
        ttk.Entry(sctl, textvariable=self.scr_risk, width=5).pack(side="left", padx=(4, 12))
        self.btn_scan = ttk.Button(sctl, text="🔍 สแกน", command=self.on_scan)
        self.btn_scan.pack(side="left")
        self.scr_info = ttk.Label(sctl, text="ใช้แท่งรายวัน — สแกนวันละครั้งหลังตลาดสหรัฐปิดก็พอ",
                                  foreground=CLR["muted"])
        self.scr_info.pack(side="left", padx=10)
        scr_body, self.scr_text = self._pane(scr_fr, None)
        scr_body.pack(fill="both", expand=True)
        for t, c in (("good", CLR["up"]), ("bad", CLR["down"]),
                     ("warn", CLR["warn"]), ("muted", CLR["muted"]), ("head", CLR["accent"])):
            self.scr_text.tag_configure(t, foreground=c)

        # กลับมาแท็บแดชบอร์ดแล้ววาดกราฟใหม่ (ตอนซ่อนอยู่ canvas อาจกว้าง 1 px)
        nb.bind("<<NotebookTabChanged>>", lambda e: self.after(60, self._draw_chart))
        # จัดสัดส่วนกล่องเริ่มต้นหลังหน้าต่างขึ้นจอแล้ว
        self.after(400, self._init_sashes)

        # ข้อความตั้งต้น ไม่ให้เห็นกล่องขาวเปล่า ๆ ก่อนรอบแรกมาถึง
        self._placeholder(self.sig_text, "กดปุ่ม ▶ เริ่ม เพื่อวิเคราะห์")
        self._placeholder(self.zone_text, "กดปุ่ม ▶ เริ่ม เพื่อคำนวณโซนรอเข้า")
        self._placeholder(self.mkt_text,
                          "รอข้อมูลจาก Webull...\n\n"
                          "ต้องมี webull_market.py และ webull_config.json "
                          "อยู่โฟลเดอร์เดียวกับไฟล์นี้\n"
                          "และติ๊ก 'บริบทตลาดจาก Webull' ไว้")
        self._placeholder(self.scr_text,
                          "กด 🔍 สแกน เพื่อคัดหุ้น swing รายสัปดาห์\n\n"
                          "ต้องมี weekly_screener.py + webull_market.py + webull_config.json\n"
                          "อยู่โฟลเดอร์เดียวกัน (ไม่ต้องกดเริ่ม monitor ก่อน)")
        self._placeholder(self.news_text,
                          "รอข้อมูลข่าวและปฏิทิน...\n\n"
                          "ต้องมี news_calendar.py อยู่โฟลเดอร์เดียวกับไฟล์นี้\n"
                          "และติ๊ก 'ข่าว + ปฏิทิน' ไว้")
        self._sync()

    def _placeholder(self, widget, msg: str):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("end", msg + "\n")
        widget.configure(state="disabled")

    def _pane(self, parent, title):
        fr = ttk.LabelFrame(parent, text=title) if title else ttk.Frame(parent)
        sb = ttk.Scrollbar(fr, orient="vertical")
        txt = tk.Text(fr, wrap="word", yscrollcommand=sb.set,
                      font=("TkFixedFont", 10), relief="flat", width=30, height=4)
        sb.configure(command=txt.yview)
        sb.pack(side="right", fill="y")
        txt.pack(fill="both", expand=True, padx=5, pady=5)
        txt.configure(state="disabled")
        return fr, txt

    def _init_sashes(self):
        """สัดส่วนเริ่มต้นตาม wireframe FHD: แถวบน ~62% / กราฟ ~64% / ล่างแบ่ง 3 เท่ากัน"""
        try:
            self.update_idletasks()
            H, W = self.vp.winfo_height(), self.vp.winfo_width()
            if H < 50 or W < 50:
                self.after(300, self._init_sashes); return
            self.vp.sashpos(0, int(H * 0.62))
            self.top_pw.sashpos(0, int(W * 0.64))
            self.right_pw.sashpos(0, int(self.right_pw.winfo_height() * 0.45))
            self.bot_pw.sashpos(0, int(W / 3))
            self.bot_pw.sashpos(1, int(W * 2 / 3))
        except tk.TclError:
            pass

    def _toggle_max(self, panel):
        """ขยายกล่องเดียวเต็มพื้นที่แดชบอร์ด / เรียกซ้ำเพื่อคืนเลย์เอาต์เดิม"""
        pws = (self.vp, self.top_pw, self.right_pw, self.bot_pw)
        try:
            self.update_idletasks()
            if self._max_panel is not None:          # คืนเลย์เอาต์เดิม
                saved = self._max_panel
                self._max_panel = None
                for pw, pos in zip(pws, saved):
                    for k, v in enumerate(pos):
                        pw.sashpos(k, v)
            else:
                self._max_panel = [[pw.sashpos(k) for k in range(len(pw.panes()) - 1)]
                                   for pw in pws]
                H, W = 10000, 10000                    # ดันเส้นคั่นไปสุดขอบ
                order = getattr(self, "_panel_order", [])
                idx = order.index(panel) if panel in order else 0
                plan = {0: ((0, H), (self.top_pw, 0, W)),
                        1: ((0, H), (self.top_pw, 0, 0), (self.right_pw, 0, H)),
                        2: ((0, H), (self.top_pw, 0, 0), (self.right_pw, 0, 0)),
                        3: ((0, 0), (self.bot_pw, 1, W), (self.bot_pw, 0, W)),
                        4: ((0, 0), (self.bot_pw, 1, W), (self.bot_pw, 0, 0)),
                        5: ((0, 0), (self.bot_pw, 0, 0), (self.bot_pw, 1, 0))}[idx]
                self.vp.sashpos(*plan[0])
                for pw, k, v in plan[1:]:
                    pw.sashpos(k, v)
        except tk.TclError:
            self._max_panel = None
        self.after(80, self._draw_chart)

    def _sync(self):
        m = self.src_mode.get()
        self.host_entry.configure(state="normal" if m == "rpyc" else "disabled")
        for w in (self.dir_entry, self.dir_btn):
            w.configure(state="normal" if m == "file" else "disabled")

    def _pick(self):
        d = filedialog.askdirectory(title="เลือกโฟลเดอร์ข้อมูล JSON")
        if d:
            self.dir_var.set(d)

    # ---------------- ฟอนต์ ----------------
    def _apply_font(self):
        try:
            fs = max(7, min(20, int(self.font_size.get())))
        except (tk.TclError, ValueError):
            return
        import tkinter.font as tkfont
        for n in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            try:
                tkfont.nametofont(n).configure(size=fs)
            except tk.TclError:
                pass
        self.style.configure("Treeview", rowheight=fs + 14, font=("TkDefaultFont", fs))
        self.style.configure("Treeview.Heading", font=("TkDefaultFont", fs, "bold"))
        for t in (self.sig_text, self.zone_text, self.mkt_text, self.news_text, self.scr_text):
            t.configure(font=("TkFixedFont", fs))
        self.log_text.configure(font=("TkFixedFont", max(7, fs - 1)))
        for c in self.cards.values():
            c.apply_font(fs)
        self.clock_time.configure(font=("TkFixedFont", fs + 7, "bold"))
        for w in (self.clock_date, self.clock_sess):
            w.configure(font=("TkDefaultFont", max(7, fs - 1)))

    def _bump(self, d):
        self.font_size.set(max(7, min(20, self.font_size.get() + d)))
        self._apply_font()

    # ---------------- ปุ่ม ----------------
    def on_start(self):
        if self.worker and self.worker.is_alive():
            return
        if self.engine is None:
            if not os.path.exists(ENGINE_PATH):
                messagebox.showerror("ไม่พบไฟล์", f"ต้องมี engine ที่\n{ENGINE_PATH}")
                return
            try:
                self.engine = load_engine()
            except RuntimeError as e:
                messagebox.showerror("ไฟล์ engine ไม่ตรงเวอร์ชัน", str(e))
                return
            except Exception as e:
                messagebox.showerror("โหลด engine ไม่ได้", f"{type(e).__name__}: {e}")
                return

        m = self.src_mode.get()
        cfg = {"data_dir": self.dir_var.get().strip() if m == "file" else None,
               "mt5linux": self.host_var.get().strip() if m == "rpyc" else None,
               "risk_percent": float(self.risk_var.get()),
               "interval_min": int(self.interval_var.get()),
               "export_zones": bool(self.export_zones.get()),
               "use_webull": bool(self.use_webull.get()),
               "use_news": bool(self.use_news.get())}
        if m == "file" and not cfg["data_dir"]:
            messagebox.showwarning("ยังไม่ได้เลือกโฟลเดอร์", "เลือกโฟลเดอร์ข้อมูลก่อนค่ะ")
            return

        self.stop_event = threading.Event()
        self.worker = Worker(self.engine, cfg, self.q, self.stop_event)
        self.worker.start()
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.btn_now.configure(state="normal")
        self.cards["state"].set("ทำงานอยู่", f"อัปเดตทุก {cfg['interval_min']} นาที", CLR["up"])
        self._log(f"เริ่ม monitor — ทุก {cfg['interval_min']} นาที", "ok")

    def on_stop(self):
        if self.stop_event:
            self.stop_event.set()
        if self.worker:
            self.worker.wake.set()
        self.btn_stop.configure(state="disabled")
        self.btn_now.configure(state="disabled")
        self._log("สั่งหยุด กำลังปิดการเชื่อมต่อ...")

    def on_now(self):
        if self.worker and self.stop_event and not self.stop_event.is_set():
            self._log("ขออัปเดตทันที")
            self.worker.wake.set()

    # ---------------- queue ----------------
    def _pump(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self._log(*payload)
                elif kind == "result":
                    self._render(payload)
                elif kind == "market":
                    self._render_market(payload)
                elif kind == "news":
                    self._render_news(payload)
                elif kind == "screener":
                    self._render_screener(payload)
                elif kind == "account":
                    self._render_account(payload)
                elif kind == "next":
                    self.next_run = payload
                elif kind == "busy":
                    self.status.configure(
                        text="กำลังดึงข้อมูลและวิเคราะห์..." if payload
                        else f"พร้อม | หน่วยความจำ {rss_mb():.1f} MB")
                elif kind == "stopped":
                    self._stopped()
        except queue.Empty:
            pass
        self.after(self.REFRESH_MS, self._pump)

    def _stopped(self):
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self.btn_now.configure(state="disabled")
        self.cards["state"].set("หยุดอยู่", "", CLR["muted"])
        self.next_run = None
        self.worker = None
        before = rss_mb(); gc.collect()
        self._log(f"หยุดแล้ว คืนหน่วยความจำ {before:.1f} → {rss_mb():.1f} MB", "ok")

    def _tick(self):
        self._update_clock()
        if self.next_run:
            left = (self.next_run - datetime.now()).total_seconds()
            self.cards["state"].lbl_sub.configure(
                text=f"รอบถัดไปอีก {int(left)//60:02d}:{int(left)%60:02d}"
                if left > 0 else "กำลังอัปเดต...")
        self.after(1000, self._tick)

    def _update_clock(self):
        """นาฬิกาเวลาไทยและสถานะเซสชัน — เรียกทุกวินาทีจาก _tick"""
        try:
            m = market_sessions(datetime.now(timezone.utc).replace(tzinfo=None))
        except Exception:
            return
        th = m["th"]
        self.clock_time.configure(text=f"{th:%H:%M:%S}")
        self.clock_date.configure(
            text=f"{TH_DAY[th.weekday()]} {th.day} {TH_MONTH[th.month-1]} "
                 f"{th.year + 543}  ·  UTC+7")

        if m["weekend"]:
            # สุดสัปดาห์ไม่ต้องนับถอยหลัง เพราะตลาดปิดยาวถึงเช้าวันจันทร์
            self.clock_sess.configure(text="ตลาดปิด (สุดสัปดาห์)", foreground=CLR["muted"])
            return

        opened = [x for x in m["sessions"] if x["open"]]
        if opened:
            soon = min(opened, key=lambda x: x["hours_left"])
            txt = "เปิด: " + ", ".join(x["name"] for x in opened) + f"  ({soon['label']})"
            col = CLR["up"]
        else:
            nxt = min(m["sessions"], key=lambda x: x["hours_left"])
            txt = f"ปิดทุกตลาด · {nxt['name']} {nxt['label']}"
            col = CLR["muted"]
        self.clock_sess.configure(text=txt, foreground=col)

    # ---------------- แสดงผล ----------------
    def _log(self, msg, level="info"):
        t = self.log_text
        t.configure(state="normal")
        t.insert("end", f"[{datetime.now():%H:%M:%S}] {msg}\n", level)
        if int(t.index("end-1c").split(".")[0]) > 500:
            t.delete("1.0", "200.0")
        t.see("end")
        t.configure(state="disabled")
        try:
            col = {"error": CLR["down"], "warn": CLR["warn"], "ok": CLR["up"]}.get(level, CLR["muted"])
            self.last_log.configure(text=f"[{datetime.now():%H:%M:%S}] {msg}"[:160], foreground=col)
        except (AttributeError, tk.TclError):
            pass

    def _render_account(self, acc):
        if not acc:
            self.cards["account"].set("—", "อ่านไม่ได้", CLR["warn"])
            return
        self.cards["account"].set(f"{float(acc.get('balance', 0)):,.2f}",
                                  f"{acc.get('login','')} {acc.get('currency','')}")

    def _render(self, r):
        reg = r.get("regime")
        if reg:
            self.cards["regime"].set(reg.label.split("/")[0].strip(), reg.narrative[:70])

        ranked = r.get("ranked", [])
        self.tree.delete(*self.tree.get_children())
        for i, s in enumerate(ranked, 1):
            tag = "strong" if i == 1 else ("weak" if i == len(ranked) else "")
            self.tree.insert("", "end", tags=(tag,), values=(
                i, s.alias, f"{s.score:+.2f}", f"{s.price:,.2f}",
                f"{s.atr:,.2f}", s.structure))
        if ranked:
            b, w = ranked[0], ranked[-1]
            self.cards["strong"].set(b.alias, f"{b.score:+.2f} | {b.structure}", CLR["up"])
            self.cards["weak"].set(w.alias, f"{w.score:+.2f} | {w.structure}", CLR["down"])

        t = self.sig_text
        t.configure(state="normal"); t.delete("1.0", "end")
        if r.get("error"):
            t.insert("end", f"❌ {r['error']}\n")
        elif r.get("no_trade"):
            t.insert("end", f"⛔ NO TRADE\n\nส่วนต่างคะแนน = {r['spread_score']} "
                            f"ต่ำกว่าเกณฑ์ {self.engine.CFG['score_spread_min']}\n"
                            "ไม่มีตัวไหนเด่นพอ การอยู่เฉยคือการตัดสินใจที่ถูกต้อง\n")
        else:
            t.insert("end", f"ส่วนต่างคะแนน = {r['spread_score']}\n\n")
            for sig in r.get("signals", []):
                icon = {"READY": "🟢", "WAIT_PULLBACK": "🟡",
                        "VETOED": "🔴"}.get(sig.status, "•")
                t.insert("end", f"{icon} {sig.side} {sig.alias} ({sig.symbol}) "
                                f"[{sig.status}]  คะแนน {sig.score:+.2f}\n")
                for reason in sig.reasons:
                    t.insert("end", f"   - {reason}\n")
                if sig.status != "VETOED":
                    t.insert("end", f"   โซนเข้า : {sig.entry_zone}\n"
                                    f"   SL      : {sig.stop_loss:,.2f}\n"
                                    f"   TP1/TP2 : {sig.tp1:,.2f} / {sig.tp2:,.2f}\n"
                                    f"   Lot     : {sig.lot} (เสี่ยง {sig.risk_usd:,.2f} USD)\n"
                                    f"   ยกเลิกเมื่อ: {sig.invalidation}\n")
                t.insert("end", "\n")
            t.insert("end", "⚠️ เครื่องมือสนับสนุนการตัดสินใจ ไม่ใช่คำแนะนำการลงทุน\n")
        t.configure(state="disabled")

        self._render_zones(r)
        self._last_ranked = ranked
        names = [s.alias for s in ranked]
        self.chart_cb.configure(values=names)
        if self.chart_sym.get() not in names and names:
            self.chart_sym.set(names[0])
        self._draw_chart()

    def _render_zones(self, r):
        KIND = {"DEMAND": "Order Block", "SUPPLY": "Order Block",
                "FVG_BULL": "Fair Value Gap", "FVG_BEAR": "Fair Value Gap",
                "LIQ_BUY": "Liquidity", "LIQ_SELL": "Liquidity"}
        t = self.zone_text
        t.configure(state="normal"); t.delete("1.0", "end")
        ranked = r.get("ranked", [])
        if not ranked:
            t.insert("end", "ยังไม่มีข้อมูล\n"); t.configure(state="disabled"); return
        t.insert("end", "โซนที่ควร 'รอ' ให้ราคาเข้ามาหา แทนการไล่ราคา\n\n")
        for st in ranked:
            t.insert("end", f"━━ {st.alias} {st.price:,.2f} ATR {st.atr:,.2f} "
                            f"คะแนน {st.score:+.2f} ━━\n")
            for z in st.zones or []:
                tag = "buy" if z.side == "BUY" else "sell"
                near = z.dist_atr <= 1.0
                mark = "◆" if z.dist_atr == 0 else ("▶" if near else " ")
                dist = "อยู่ในโซนแล้ว" if z.dist_atr == 0 else f"ห่าง {z.dist_atr:g} ATR"
                t.insert("end", f" {mark} [{z.side}] {KIND.get(z.kind, z.kind)} "
                                f"{z.low:,.2f}–{z.high:,.2f}  {dist}  แรง: {z.strength}\n",
                         (tag, "near") if near else (tag,))
                t.insert("end", f"      จุดสังเกต: {z.trigger}\n")
            t.insert("end", "\n")
        t.insert("end", "◆ อยู่ในโซนแล้ว   ▶ ใกล้ถึงใน 1 ATR\n"
                        "ทุกโซนต้องรอแท่งยืนยัน การเข้าทันทีที่แตะคือการเดา\n")
        t.configure(state="disabled")

    def _render_market(self, c):
        self._last_market = c
        t = self.mkt_text
        t.configure(state="normal"); t.delete("1.0", "end")
        if not c or not c.get("ok"):
            t.insert("end", "ยังไม่มีข้อมูลจาก Webull\n", "warn")
            t.insert("end", f"{(c or {}).get('error','')}\n\n", "muted")
            t.insert("end", "ตรวจสอบตามลำดับ\n"
                            "  1. มีไฟล์ webull_market.py และ webull_config.json "
                            "อยู่โฟลเดอร์เดียวกันหรือยัง\n"
                            "  2. ติ๊ก 'บริบทตลาดจาก Webull' ไว้หรือยัง\n"
                            "  3. ลองรัน  python webull_market.py  ดูว่าต่อ API ได้ไหม\n"
                            "  4. ดูรายละเอียดเพิ่มเติมที่แท็บ 'บันทึก'\n", "muted")
            self.cards["risk"].set("—", "ไม่มีข้อมูล", CLR["muted"])
            t.configure(state="disabled"); return

        r = c.get("risk", {})
        sc = r.get("score", 0)
        self.cards["risk"].set(
            f"{sc:+.1f}", r.get("label", ""),
            CLR["up"] if sc >= 1 else CLR["down"] if sc <= -1 else CLR["ink"])
        t.insert("end", f"ความเสี่ยงโดยรวม {sc:+.1f}  {r.get('label','')}\n")
        for w in r.get("reasons", [])[:12]:
            t.insert("end", f"   - {w}\n")

        pl = c.get("pulse", {})
        if pl.get("ok"):
            t.insert("end", "\n━━ ใครลากดัชนีวันนี้ (ถ่วงน้ำหนัก) ━━\n")
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
                t.insert("end", head + "\n", "good" if val > 0 else "bad" if val < 0 else ())
                if p["lifts"]:
                    t.insert("end", "      ดัน : " + ", ".join(fmt(x) for x in p["lifts"]) + "\n", "good")
                if p["drags"]:
                    t.insert("end", "      ลาก : " + ", ".join(fmt(x) for x in p["drags"]) + "\n", "bad")
            t.insert("end", "  (น้ำหนัก US100/US500 เป็นค่าประมาณ — US30 คิดจากราคาจริง)\n", "muted")

        k = c.get("core", {})
        if k.get("ok"):
            t.insert("end", "\n━━ 5 ตัวสำคัญ (Webull) ━━\n")
            t.insert("end", f"  {'':<6}{'':<18}{'1 วัน':>8}{'5 วัน':>9}{'20 วัน':>9}"
                            f"{'กรอบ20':>9}{'วอลุ่ม':>8}\n")
            for x in k["rows"]:
                _nm = x['name'] + " " * max(0, 18 - sum(
                    0 if __import__("unicodedata").category(ch) == "Mn" else 1
                    for ch in x['name']))
                t.insert("end", f"  {x['symbol']:<6}{_nm}{x['d1']:>7.2f}%"
                                f"{x['d5']:>8.2f}%{x['d20']:>8.2f}%{x['range_pos']:>8.0f}%"
                                f"{x['vol_ratio']:>7.2f}x\n",
                         "good" if x["d1"] > 0 else "bad")

        im = c.get("index_momentum", {})
        if im.get("ok"):
            t.insert("end", "\n━━ โมเมนตัมดัชนี (ETF ตัวแทน) ━━\n")
            t.insert("end", f"  {'':<9}{'1 วัน':>8}{'5 วัน':>9}{'20 วัน':>9}"
                            f"{'กรอบ20':>9}{'วอลุ่ม':>8}\n")
            for x in im["ranking"]:
                t.insert("end", f"  {x['name']:<9}{x['d1']:>7.2f}%{x['d5']:>8.2f}%"
                                f"{x['d20']:>8.2f}%{x['range_pos']:>8.0f}%"
                                f"{x['vol_ratio']:>7.2f}x\n",
                         "good" if x["d5"] > 0 else "bad")
            t.insert("end", f"  → {im['note']}\n")

        for name, b in c.get("breadth", {}).items():
            if not b.get("ok"):
                continue
            pts = f" | รวม {b['total_points']:+,.1f} จุด" if b.get("total_points") else ""
            gtag = ("bad" if b["grade"] in ("BROAD_DOWN", "DIVERGENT") else
                    "warn" if b["grade"] == "CONCENTRATED" else
                    "good" if b["grade"] == "BROAD_UP" else None)
            t.insert("end", f"\n━━ {name} ━━\n")
            t.insert("end", f"  ขึ้น {b['up']} / ลง {b['down']} จาก {b['counted']} | "
                            f"เฉลี่ย {b['avg_pct']:+.2f}%{pts}\n")
            t.insert("end", f"  {b['verdict']}\n", (gtag,) if gtag else ())
            t.insert("end", "  ฉุด : " + ", ".join(
                f"{x['symbol']} {x['pct']:+.2f}%" for x in b["drags"][:4]) + "\n", "bad")
            t.insert("end", "  หนุน: " + ", ".join(
                f"{x['symbol']} {x['pct']:+.2f}%" for x in b["lifts"][:4]) + "\n", "good")

        uv = c.get("unusual_volume", {})
        if uv.get("ok"):
            t.insert("end", "\n━━ ปริมาณผิดปกติ (ขยับพร้อมวอลุ่ม = ของจริง) ━━\n")
            for x in uv["rows"]:
                t.insert("end", f"  {x['symbol']:<6}{x['pct']:>7.2f}%  "
                                f"วอลุ่ม {x['vol_ratio']}x  {x['kind']}\n",
                         "good" if x["pct"] > 0 else "bad")

        ex = c.get("extremes", {})
        if ex.get("ok"):
            t.insert("end", "\n━━ ปลายกรอบ 20 วัน ━━\n")
            if ex.get("near_high"):
                t.insert("end", "  ใกล้สูงสุด: " + ", ".join(
                    f"{x['symbol']}({x['pos']}%)" for x in ex["near_high"]) + "\n", "good")
            if ex.get("near_low"):
                t.insert("end", "  ใกล้ต่ำสุด: " + ", ".join(
                    f"{x['symbol']}({x['pos']}%)" for x in ex["near_low"]) + "\n", "bad")

        s = c.get("sectors", {})
        if s.get("ok"):
            t.insert("end", f"\n━━ กลุ่มอุตสาหกรรม ━━ {s['mood']} (tilt {s['tilt']:+.2f})\n")
            for row in s["ranking"]:
                bar = "█" * min(18, int(abs(row["pct"]) * 8))
                t.insert("end", f"  {row['etf']:<5}{row['name']:<16}{row['pct']:>7.2f}%  "
                                f"{bar}\n", "good" if row["pct"] > 0 else "bad")

        x = c.get("cross", {})
        if x.get("ok"):
            t.insert("end", "\n━━ สินทรัพย์อ้างอิง ━━\n")
            for row in x["rows"]:
                t.insert("end", f"  {row['symbol']:<6}{row['name']:<18}"
                                f"{row['pct']:>7.2f}%\n",
                         "good" if row["pct"] > 0 else "bad")
            for sg in x.get("signals", []):
                t.insert("end", f"  ⚠ {sg}\n", "warn")

        t.insert("end", f"\nอัปเดต {c.get('at','')}\n")
        t.configure(state="disabled")

    def on_scan(self):
        """สแกนใน thread แยก — หน้าจอไม่ค้างระหว่างรอ Webull"""
        try:
            cap = float(self.scr_capital.get().replace(",", ""))
            risk = float(self.scr_risk.get())
        except ValueError:
            self._log("ทุนหรือ % ความเสี่ยงไม่ใช่ตัวเลข", "error"); return
        path = os.path.join(HERE, "weekly_screener.py")
        if not os.path.exists(path):
            self._render_screener({"ok": False, "error": f"ไม่พบ {path}"}); return
        self.btn_scan.configure(state="disabled")
        self.scr_info.configure(text="กำลังสแกน... (ประมาณ 3 request)")

        def job():
            try:
                spec = importlib.util.spec_from_file_location("weekly_screener", path)
                mod = importlib.util.module_from_spec(spec)
                sys.modules["weekly_screener"] = mod
                spec.loader.exec_module(mod)
                r = mod.run_screener(cap, risk)
                r["_lines"] = mod.format_report(r)
            except Exception as e:
                r = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            self.q.put(("screener", r))
        threading.Thread(target=job, daemon=True).start()

    def _render_screener(self, r):
        self.btn_scan.configure(state="normal")
        t = self.scr_text
        t.configure(state="normal"); t.delete("1.0", "end")
        lines = r.get("_lines") or [("สแกนไม่สำเร็จ: " + str(r.get("error")) + "\n", "bad")]
        for text, tag in lines:
            t.insert("end", text, (tag,) if tag else ())
        t.configure(state="disabled")
        n = len(r.get("picks", []))
        self.scr_info.configure(
            text=(f"สแกนเสร็จ {datetime.now():%H:%M} — ผ่าน {n} ตัว, รอจังหวะ "
                  f"{len(r.get('watch', []))} ตัว") if r.get("ok") else "สแกนไม่สำเร็จ")
        self._log(f"Weekly Screener: {'ผ่าน ' + str(n) + ' ตัว' if r.get('ok') else r.get('error')}",
                  "ok" if r.get("ok") else "warn")

    def _render_news(self, c):
        t = self.news_text
        t.configure(state="normal"); t.delete("1.0", "end")
        if not c or not c.get("ok"):
            t.insert("end", "ยังไม่มีข้อมูลข่าว/ปฏิทิน\n", "warn")
            t.insert("end", f"{(c or {}).get('error','')}\n\n", "muted")
            t.insert("end", "ตรวจสอบตามลำดับ\n"
                            "  1. มีไฟล์ news_calendar.py อยู่โฟลเดอร์เดียวกันหรือยัง\n"
                            "  2. ติ๊ก 'ข่าว + ปฏิทิน' ไว้หรือยัง\n"
                            "  3. ลองรัน  python news_calendar.py  ดูว่าดึงข้อมูลได้ไหม\n"
                            "  4. ดูรายละเอียดเพิ่มเติมที่แท็บ 'บันทึก'\n", "muted")
            self.cards["alert"].set("—", "ไม่มีข้อมูล", CLR["muted"])
            t.configure(state="disabled"); return

        alerts = c.get("alerts", [])
        highs = [a for a in alerts if a["level"] == "high"]
        if highs:
            self.cards["alert"].set(str(len(highs)), highs[0]["text"][:60], CLR["down"])
        elif alerts:
            self.cards["alert"].set("0", alerts[0]["text"][:60], CLR["warn"])
        else:
            self.cards["alert"].set("ปลอดโปร่ง", "ไม่มีเหตุการณ์สำคัญ", CLR["up"])

        if alerts:
            t.insert("end", "━━ คำเตือน ━━\n")
            icon = {"high": "🔴", "medium": "🟡", "info": "🔵"}
            for a in alerts:
                tag = ("bad" if a["level"] == "high" else
                       "warn" if a["level"] == "medium" else "muted")
                t.insert("end", f" {icon.get(a['level'],'•')} {a['text']}\n", tag)
                t.insert("end", f"      → {a['action']}\n")
            t.insert("end", "\n")

        eco = c.get("economic", {})
        t.insert("end", "━━ ปฏิทินเศรษฐกิจ ━━\n")
        if not eco.get("ok"):
            t.insert("end", f"  {eco.get('error','ดึงไม่ได้')}\n", "muted")
        else:
            for e in eco["events"][:14]:
                when = ("ผ่านไป " if e["in_minutes"] < 0 else "อีก ") + \
                       f"{abs(e['in_minutes'])} นาที"
                fc = (f"  คาด {e['forecast']} / ก่อนหน้า {e['previous']}"
                      if e.get("forecast") else "")
                t.insert("end", f"  {e['local']} [{e['currency']}] {e['title']} "
                                f"({when}){fc}\n",
                         "bad" if e["impact"] == "HIGH" else "muted")

        earn = c.get("earnings", {})
        t.insert("end", "\n━━ ปฏิทินงบ (หุ้นน้ำหนักหนักใน Dow) ━━\n")
        if earn.get("dow_heavy"):
            for e in earn["dow_heavy"]:
                t.insert("end", f"  {e['date']}  {e['symbol']:<6}"
                                f"{e['name'][:30]:<32}{e['time']}\n", "warn")
            t.insert("end", f"  ⚠ {earn['warning']}\n", "bad")
        else:
            t.insert("end", "  ไม่มี\n", "muted")

        news = c.get("news", {})
        t.insert("end", "\n━━ ข่าวที่เกี่ยวข้อง ━━\n")
        if news.get("topic_counts"):
            t.insert("end", "  หมวดที่หนาแน่น: " + ", ".join(
                f"{k}({v})" for k, v in news["topic_counts"].items()) + "\n")
        for n in news.get("relevant", [])[:15]:
            ago = f"{n['minutes_ago']} นาทีก่อน" if n.get("minutes_ago") is not None else ""
            t.insert("end", f"  [{','.join(n['topics'])}] {n['title'][:90]}\n")
            t.insert("end", f"      {n['source']} {ago}\n", "muted")
        if news.get("failed_feeds"):
            t.insert("end", "  (ดึงไม่ได้: " + ", ".join(news["failed_feeds"]) + ")\n",
                     "muted")
        t.insert("end", f"\nอัปเดต {c.get('at','')}\n")
        t.configure(state="disabled")

    # ---------------- กราฟ ----------------
    def _chart_state(self):
        if not self._last_ranked:
            return None
        want = self.chart_sym.get()
        for st in self._last_ranked:
            if st.alias == want:
                return st
        return self._last_ranked[0]

    def _draw_chart(self):
        c = self.canvas
        c.delete("all")
        st = self._chart_state()
        W, H = c.winfo_width(), c.winfo_height()

        if W < 80 or H < 60:
            return              # แท็บยังไม่ถูกแสดง เดี๋ยว Configure จะเรียกซ้ำเอง

        if st is None:
            c.create_text(W // 2, H // 2, fill=CLR["muted"],
                          text="ยังไม่มีข้อมูล — กดปุ่ม ▶ เริ่ม ก่อน")
            return
        if not getattr(st, "ohlc", None):
            c.create_text(W // 2, H // 2 - 10, fill=CLR["down"],
                          font=("TkDefaultFont", 10, "bold"),
                          text=f"{st.alias}: engine ไม่ได้ส่งข้อมูลแท่งเทียนมา")
            c.create_text(W // 2, H // 2 + 14, fill=CLR["muted"],
                          text="ไฟล์ multi_asset_decision_engine.py เป็นเวอร์ชันเก่า "
                               "— คัดลอกไฟล์ล่าสุดมาทับ")
            return
        PADL, PADR, PADT, PADB = 10, 78, 10, 20
        pw, ph = W - PADL - PADR, H - PADT - PADB
        bars = st.ohlc; n = len(bars)
        lo = min(b[3] for b in bars); hi = max(b[2] for b in bars)
        zones = [z for z in (st.zones or []) if self.show_zone_boxes.get()]
        for z in zones:
            if z.dist_atr <= 4:
                lo, hi = min(lo, z.low), max(hi, z.high)
        if hi <= lo:
            return
        pad = (hi - lo) * 0.04; lo, hi = lo - pad, hi + pad

        def Y(p):
            return PADT + ph * (hi - p) / (hi - lo)

        def X(i):
            return PADL + pw * (i + 0.5) / n

        for z in zones:
            if z.high < lo or z.low > hi:
                continue
            fill = "#e8f5e9" if z.side == "BUY" else "#fdecea"
            line = CLR["up"] if z.side == "BUY" else CLR["down"]
            y1, y2 = Y(min(z.high, hi)), Y(max(z.low, lo))
            c.create_rectangle(PADL, y1, W - PADR, y2, fill=fill, outline=line,
                               width=2 if z.dist_atr == 0 else 1)
            c.create_text(PADL + 4, y1 + 7, anchor="w", fill=line,
                          font=("TkDefaultFont", 7),
                          text=f"{z.side} {z.kind} ({z.dist_atr:g} ATR)")

        bw = max(1.0, pw / n * 0.62)
        for i, (_t, o, h, l, cl) in enumerate(bars):
            x = X(i); up = cl >= o
            col = CLR["up"] if up else CLR["down"]
            c.create_line(x, Y(h), x, Y(l), fill=col)
            y1, y2 = Y(max(o, cl)), Y(min(o, cl))
            if abs(y2 - y1) < 1:
                y2 = y1 + 1
            c.create_rectangle(x - bw / 2, y1, x + bw / 2, y2,
                               fill="white" if up else col, outline=col)

        if st.ema_series and len(st.ema_series) == n:
            pts = []
            for i, v in enumerate(st.ema_series):
                pts += [X(i), Y(v)]
            c.create_line(*pts, fill=CLR["accent"], width=1, smooth=True)

        yp = Y(st.price)
        c.create_line(PADL, yp, W - PADR, yp, fill=CLR["warn"], dash=(4, 3))
        c.create_text(W - PADR + 4, yp, anchor="w", fill=CLR["warn"],
                      font=("TkDefaultFont", 8, "bold"), text=f"{st.price:,.2f}")
        for k in range(5):
            pv = lo + (hi - lo) * k / 4; yy = Y(pv)
            c.create_line(W - PADR - 4, yy, W - PADR, yy, fill="#ccc")
            c.create_text(W - PADR + 4, yy, anchor="w", fill=CLR["muted"],
                          font=("TkDefaultFont", 7), text=f"{pv:,.2f}")
        c.create_text(PADL + 4, PADT + 4, anchor="nw", fill=CLR["ink"],
                      font=("TkDefaultFont", 9, "bold"),
                      text=f"{st.alias}  H1  {n} แท่ง")
        self.chart_info.configure(
            text=f"ATR {st.atr:,.2f} | คะแนน {st.score:+.2f} | {st.structure}")

    # ---------------- ปิดโปรแกรม ----------------
    def on_close(self):
        before = rss_mb()
        if self.worker and self.worker.is_alive():
            if not messagebox.askokcancel("ปิดโปรแกรม", "ระบบยังทำงานอยู่ ปิดเลยไหมคะ"):
                return
            self.stop_event.set(); self.worker.wake.set()
            self.worker.join(timeout=10)
        try:
            if self.engine is not None and getattr(self.engine, "SRC", None) is not None:
                try:
                    self.engine.SRC.close()
                except Exception:
                    pass
                self.engine.SRC = None
        except Exception:
            pass
        try:
            self.tree.delete(*self.tree.get_children())
            self.canvas.delete("all")
            for t in (self.sig_text, self.zone_text, self.mkt_text,
                      self.news_text, self.scr_text, self.log_text):
                t.configure(state="normal"); t.delete("1.0", "end")
        except Exception:
            pass
        self.worker = self.stop_event = self.engine = None
        self._last_ranked = self._last_market = None
        sys.modules.pop("made_engine", None)
        sys.modules.pop("webull_market", None)
        sys.modules.pop("news_calendar", None)
        gc.collect()
        try:
            import ctypes
            ctypes.CDLL("libc.so.6").malloc_trim(0)
        except Exception:
            pass
        print(f"[MADE] ปิดโปรแกรม — หน่วยความจำ {before:.1f} → {rss_mb():.1f} MB")
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
