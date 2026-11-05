"""
MADE - Multi-Timeframe Confluence Backtest
===========================================
เปรียบเทียบชุด timeframe  H1/M15/M5  กับ  H4/H1/M15
บน US30Cash#, US100Cash#, US500Cash#, GOLDm#  (XM Global MT5)

Indicators (ตั้งค่าเหมือนบนชาร์ต MT5):
  Stoch(10,3,3)  MACD(12,26,9 - signal แบบ SMA เหมือน MT5)  ATR(14)  ADX(14)  RSI(14)

กฎ (Pattern A: Pullback ต่อเทรนด์)  — ฝั่ง Sell เป็นกระจกเงา
  HTF (H1 หรือ H4)   : ADX >= ADX_TREND (หรือ >= ADX_TRANS และกำลังขึ้น), +DI > -DI,
                       MACD main > 0, RSI > 50, ไม่เข้าเมื่อ ADX > ADX_EXHAUST และหักหัวลง
  MTF (M15 หรือ H1)  : +DI > -DI และ RSI > 45   (ไม่สวน HTF)
  LTF (M5 หรือ M15)  : Stoch K ตัด D ขึ้น โดย K ต่ำสุดใน PULLBACK_LOOKBACK แท่งล่าสุด < STOCH_PULLBACK,
                       RSI อยู่ RSI_ZONE และกำลังขึ้น, MACD histogram กำลังขยายขึ้น
  เข้า : open ของแท่ง LTF ถัดไป     SL = SL_ATR x ATR(LTF)     TP = TP_ATR x ATR(LTF)
  ถ้า SL และ TP โดนในแท่งเดียวกัน นับเป็น SL (มองแบบระวัง)   หักค่า spread ทุกไม้

ทุกค่า HTF/MTF ใช้เฉพาะแท่งที่ "ปิดแล้ว" เท่านั้น (ไม่มี look-ahead)

แต่ละชุด timeframe ทดสอบ 2 แบบ:
  FULL      = ใช้กฎครบ
  NO_REGIME = ตัดเงื่อนไข ADX ของ HTF ออก  (ใช้ดูว่าฟิลเตอร์ sideway ช่วยได้จริงไหม)

วิธีรัน (บน root-think ที่เปิด MT5 ค้างไว้และ login แล้ว):
  pip install MetaTrader5 pandas numpy
  python made_mtf_backtest.py --days 180

ผลลัพธ์อยู่ในโฟลเดอร์ bt_output/
  summary.csv  trades.csv  report.md

ทดสอบด้วยข้อมูลจำลอง (เครื่องที่ไม่มี MT5):
  python made_mtf_backtest.py --synthetic
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

# ---------------------------------------------------------------- settings
SYMBOLS = ["US30Cash#", "US100Cash#", "US500Cash#", "GOLDm#"]

STACKS = {
    "H1/M15/M5": ("H1", "M15", "M5"),
    "H4/H1/M15": ("H4", "H1", "M15"),
}

TF_MINUTES = {"M5": 5, "M15": 15, "H1": 60, "H4": 240}

# กฎ — ปรับได้ตรงนี้
ADX_TREND = 25.0
ADX_TRANS = 20.0
ADX_EXHAUST = 45.0
STOCH_PULLBACK = 35.0      # K ต้องเคยย่อลงต่ำกว่านี้ (ฝั่ง sell: เคยขึ้นเกิน 100-ค่านี้)
PULLBACK_LOOKBACK = 6
RSI_ZONE = (40.0, 62.0)    # ฝั่ง sell ใช้ (38, 60)
SL_ATR = 1.2
TP_ATR = 1.8               # = 1.5R
MAX_HOLD_BARS = 48         # ปิดที่ราคา close เมื่อถือครบจำนวนแท่ง LTF นี้
WARMUP_BARS = 200


# ---------------------------------------------------------------- indicators
def _wilder(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(alpha=1.0 / n, adjust=False).mean()


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    h, l, c = d["high"], d["low"], d["close"]

    # Stochastic (10,3,3) แบบ MT5: slowing = SMA ของ numerator/denominator
    ll = l.rolling(10).min()
    hh = h.rolling(10).max()
    num = (c - ll).rolling(3).sum()
    den = (hh - ll).rolling(3).sum()
    d["stoch_k"] = 100 * num / den.replace(0, np.nan)
    d["stoch_d"] = d["stoch_k"].rolling(3).mean()

    # MACD (12,26,9) แบบ MT5: signal = SMA(9) ของ main
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    d["macd"] = ema12 - ema26
    d["macd_sig"] = d["macd"].rolling(9).mean()
    d["macd_hist"] = d["macd"] - d["macd_sig"]

    # ATR(14)
    prev_c = c.shift(1)
    tr = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    d["atr"] = _wilder(tr, 14)

    # ADX(14) + DI
    up = h.diff()
    dn = -l.diff()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    atr_w = _wilder(tr, 14)
    d["pdi"] = 100 * _wilder(pd.Series(plus_dm, index=d.index), 14) / atr_w
    d["mdi"] = 100 * _wilder(pd.Series(minus_dm, index=d.index), 14) / atr_w
    dx = 100 * (d["pdi"] - d["mdi"]).abs() / (d["pdi"] + d["mdi"]).replace(0, np.nan)
    d["adx"] = _wilder(dx.fillna(0), 14)

    # RSI(14)
    delta = c.diff()
    gain = _wilder(delta.clip(lower=0), 14)
    loss = _wilder(-delta.clip(upper=0), 14)
    d["rsi"] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    return d


# ---------------------------------------------------------------- data
def load_mt5(symbol: str, tf: str, days: int) -> tuple[pd.DataFrame, float]:
    import MetaTrader5 as mt5

    tf_map = {"M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
              "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4}
    if not mt5.symbol_select(symbol, True):
        raise RuntimeError(f"เลือก symbol {symbol} ไม่ได้: {mt5.last_error()}")
    info = mt5.symbol_info(symbol)
    end = datetime.now(timezone.utc) + timedelta(days=1)
    # ดึงเผื่อ warmup ของ TF ใหญ่
    start = end - timedelta(days=days + 60)
    rates = mt5.copy_rates_range(symbol, tf_map[tf], start, end)
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"ไม่มีข้อมูล {symbol} {tf}: {mt5.last_error()} "
                           f"(ลองเพิ่ม Tools > Options > Charts > Max bars in chart)")
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df = df.rename(columns={"tick_volume": "volume"})
    return df[["time", "open", "high", "low", "close", "volume", "spread"]], info.point


def synthetic(symbol: str, tf: str, days: int, seed: int) -> tuple[pd.DataFrame, float]:
    """ราคาจำลองแบบ regime-switching (มีทั้งช่วงเทรนด์และ sideway) สำหรับทดสอบโค้ด"""
    rng = np.random.default_rng(seed)
    n1 = (days + 60) * 24 * 60
    drift = np.repeat(rng.choice([-1, 0, 0, 1], size=n1 // 1440 + 1) * 0.00002, 1440)[:n1]
    ret = drift + rng.normal(0, 0.0004, n1)
    price = 4000 * np.exp(np.cumsum(ret))
    t = pd.date_range(end=datetime(2026, 10, 30), periods=n1, freq="1min")
    m1 = pd.DataFrame({"close": price}, index=t)
    rule = f"{TF_MINUTES[tf]}min"
    o = m1["close"].resample(rule).first()
    h = m1["close"].resample(rule).max()
    l = m1["close"].resample(rule).min()
    c = m1["close"].resample(rule).last()
    df = pd.DataFrame({"open": o, "high": h, "low": l, "close": c}).dropna()
    df["volume"] = 1000
    df["spread"] = 25
    df = df.reset_index().rename(columns={"index": "time"})
    return df, 0.01


# ---------------------------------------------------------------- backtest
@dataclass
class Trade:
    symbol: str
    stack: str
    variant: str
    side: str
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry: float
    exit: float
    r: float
    bars_held: int
    reason: str
    htf_adx: float


def align(ltf: pd.DataFrame, other: pd.DataFrame, tf: str, prefix: str) -> pd.DataFrame:
    """แนบค่า indicator ของ TF ใหญ่ที่ปิดแล้วล่าสุด เข้ากับแต่ละแท่ง LTF"""
    o = other.copy()
    o["close_time"] = o["time"] + pd.Timedelta(minutes=TF_MINUTES[tf])
    cols = ["adx", "pdi", "mdi", "macd", "rsi"]
    o["adx_prev"] = o["adx"].shift(1)
    o = o[["close_time"] + cols + ["adx_prev"]].rename(
        columns={k: f"{prefix}_{k}" for k in cols + ["adx_prev"]})
    left = ltf.copy()
    left["ltf_close_time"] = left["time"]  # ใช้ได้ตอน "เริ่ม" แท่ง LTF ถัดไป ดูด้านล่าง
    return pd.merge_asof(left.sort_values("time"), o.sort_values("close_time"),
                         left_on="ltf_close_time", right_on="close_time",
                         direction="backward").drop(columns=["close_time", "ltf_close_time"])


def signals(d: pd.DataFrame, use_regime: bool) -> tuple[np.ndarray, np.ndarray]:
    k, dd = d["stoch_k"], d["stoch_d"]
    cross_up = (k > dd) & (k.shift(1) <= dd.shift(1))
    cross_dn = (k < dd) & (k.shift(1) >= dd.shift(1))
    k_min = k.rolling(PULLBACK_LOOKBACK).min()
    k_max = k.rolling(PULLBACK_LOOKBACK).max()
    rsi, rsi_prev = d["rsi"], d["rsi"].shift(1)
    hist, hist_prev = d["macd_hist"], d["macd_hist"].shift(1)

    adx, adx_prev = d["h_adx"], d["h_adx_prev"]
    regime = (adx >= ADX_TREND) | ((adx >= ADX_TRANS) & (adx > adx_prev))
    exhausted = (adx > ADX_EXHAUST) & (adx < adx_prev)
    if not use_regime:
        regime = pd.Series(True, index=d.index)

    long_ = (regime & ~exhausted
             & (d["h_pdi"] > d["h_mdi"]) & (d["h_macd"] > 0) & (d["h_rsi"] > 50)
             & (d["m_pdi"] > d["m_mdi"]) & (d["m_rsi"] > 45)
             & cross_up & (k_min < STOCH_PULLBACK)
             & rsi.between(*RSI_ZONE) & (rsi > rsi_prev)
             & (hist > hist_prev))
    short = (regime & ~exhausted
             & (d["h_mdi"] > d["h_pdi"]) & (d["h_macd"] < 0) & (d["h_rsi"] < 50)
             & (d["m_mdi"] > d["m_pdi"]) & (d["m_rsi"] < 55)
             & cross_dn & (k_max > 100 - STOCH_PULLBACK)
             & rsi.between(100 - RSI_ZONE[1], 100 - RSI_ZONE[0]) & (rsi < rsi_prev)
             & (hist < hist_prev))
    return long_.fillna(False).to_numpy(), short.fillna(False).to_numpy()


def simulate(d: pd.DataFrame, point: float, symbol: str, stack: str,
             variant: str, start_time: pd.Timestamp) -> list[Trade]:
    long_sig, short_sig = signals(d, use_regime=(variant == "FULL"))
    o, h, l, c = (d[x].to_numpy() for x in ("open", "high", "low", "close"))
    atr = d["atr"].to_numpy()
    spread = d["spread"].to_numpy() * point
    times = d["time"].to_numpy()
    hadx = d["h_adx"].to_numpy()
    trades: list[Trade] = []
    i, n = WARMUP_BARS, len(d)
    while i < n - 2:
        if times[i] < np.datetime64(start_time) or not (long_sig[i] or short_sig[i]):
            i += 1
            continue
        side = "BUY" if long_sig[i] else "SELL"
        e = i + 1                         # เข้า open แท่งถัดไป
        risk = SL_ATR * atr[i]
        if not np.isfinite(risk) or risk <= 0:
            i += 1
            continue
        entry = o[e] + (spread[e] if side == "BUY" else 0.0)   # ซื้อที่ ask
        sl = entry - risk if side == "BUY" else entry + risk
        tp = entry + TP_ATR * atr[i] if side == "BUY" else entry - TP_ATR * atr[i]
        exit_px, reason, j = None, "TIME", e
        for j in range(e, min(e + MAX_HOLD_BARS, n)):
            if side == "BUY":
                hit_sl, hit_tp = l[j] <= sl, h[j] >= tp
            else:  # sell ปิดที่ ask -> บวก spread ให้ high/low
                hit_sl, hit_tp = h[j] + spread[j] >= sl, l[j] + spread[j] <= tp
            if hit_sl:
                exit_px, reason = sl, "SL"
                break
            if hit_tp:
                exit_px, reason = tp, "TP"
                break
        if exit_px is None:
            exit_px = c[j] + (spread[j] if side == "SELL" else 0.0)
        pnl = (exit_px - entry) if side == "BUY" else (entry - exit_px)
        trades.append(Trade(symbol, stack, variant, side, pd.Timestamp(times[e]),
                            pd.Timestamp(times[j]), entry, exit_px, pnl / risk,
                            j - e + 1, reason, float(hadx[i])))
        i = j + 1                         # ถือทีละไม้ต่อ symbol
    return trades


def md(df: pd.DataFrame) -> str:
    try:
        return df.to_markdown(index=False)
    except ImportError:  # ไม่มี tabulate
        return "```\n" + df.to_string(index=False) + "\n```"


def summarize(tr: pd.DataFrame, weeks: float) -> pd.DataFrame:
    def agg(g: pd.DataFrame) -> pd.Series:
        r = g["r"]
        eq = r.cumsum()
        dd = (eq - eq.cummax()).min() if len(r) else 0.0
        gp, gl = r[r > 0].sum(), -r[r < 0].sum()
        return pd.Series({
            "trades": len(r),
            "trades_per_week": round(len(r) / weeks, 2),
            "win_rate_%": round(100 * (r > 0).mean(), 1) if len(r) else np.nan,
            "expectancy_R": round(r.mean(), 3) if len(r) else np.nan,
            "total_R": round(r.sum(), 2),
            "profit_factor": round(gp / gl, 2) if gl > 0 else np.nan,
            "max_dd_R": round(dd, 2),
            "avg_hold_bars": round(g["bars_held"].mean(), 1) if len(r) else np.nan,
            "time_exit_%": round(100 * (g["reason"] == "TIME").mean(), 1) if len(r) else np.nan,
        })
    keys = ["stack", "variant", "symbol"]
    per_sym = tr.groupby(keys).apply(agg, include_groups=False).reset_index()
    total = tr.groupby(["stack", "variant"]).apply(agg, include_groups=False).reset_index()
    total["symbol"] = "ALL"
    return pd.concat([per_sym, total], ignore_index=True)


def sideway_share(frames: dict, days: int) -> pd.DataFrame:
    """สัดส่วนเวลาที่ HTF อยู่ในสภาพ sideway (ADX<20) / กำลังเปลี่ยน / เทรนด์"""
    rows = []
    for (sym, tf), df in frames.items():
        if tf not in ("H1", "H4"):
            continue
        a = df["adx"].iloc[-int(days * 24 * 60 / TF_MINUTES[tf] * 5 / 7):]
        rows.append({"symbol": sym, "htf": tf,
                     "sideway_%": round(100 * (a < ADX_TRANS).mean(), 1),
                     "transition_%": round(100 * a.between(ADX_TRANS, ADX_TREND).mean(), 1),
                     "trend_%": round(100 * (a >= ADX_TREND).mean(), 1)})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=180, help="ช่วง backtest ย้อนหลัง (วัน)")
    ap.add_argument("--synthetic", action="store_true", help="ทดสอบโค้ดด้วยข้อมูลจำลอง")
    ap.add_argument("--out", default="bt_output")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    if not args.synthetic:
        import MetaTrader5 as mt5
        if not mt5.initialize():
            raise SystemExit(f"เชื่อม MT5 ไม่ได้: {mt5.last_error()}")

    frames, points = {}, {}
    for si, sym in enumerate(SYMBOLS):
        for tf in TF_MINUTES:
            df, pt = (synthetic(sym, tf, args.days, si) if args.synthetic
                      else load_mt5(sym, tf, args.days))
            frames[(sym, tf)] = add_indicators(df)
            points[sym] = pt
            print(f"  {sym:<11} {tf:<4} {len(df):>7} bars  "
                  f"{df['time'].iloc[0]:%Y-%m-%d} → {df['time'].iloc[-1]:%Y-%m-%d}")

    all_trades: list[Trade] = []
    for sym in SYMBOLS:
        last = frames[(sym, "M5")]["time"].iloc[-1]
        start_time = last - pd.Timedelta(days=args.days)
        for stack, (htf, mtf, ltf) in STACKS.items():
            base = frames[(sym, ltf)]
            # เลื่อน 1 แท่ง: สัญญาณที่แท่ง i ใช้ค่า TF ใหญ่ที่ปิดก่อนแท่ง i ปิด
            d = base.copy()
            d["time_close"] = d["time"] + pd.Timedelta(minutes=TF_MINUTES[ltf])
            tmp = d.rename(columns={"time": "time_open"}).rename(columns={"time_close": "time"})
            tmp = align(tmp, frames[(sym, htf)], htf, "h")
            tmp = align(tmp, frames[(sym, mtf)], mtf, "m")
            tmp = tmp.rename(columns={"time": "time_close"}).rename(columns={"time_open": "time"})
            for variant in ("FULL", "NO_REGIME"):
                all_trades += simulate(tmp.reset_index(drop=True), points[sym], sym,
                                       stack, variant, start_time)

    tr = pd.DataFrame([t.__dict__ for t in all_trades])
    if tr.empty:
        raise SystemExit("ไม่มีไม้เกิดขึ้นเลย ลองเพิ่ม --days หรือผ่อนเงื่อนไข")
    weeks = args.days / 7
    summ = summarize(tr, weeks)
    side = sideway_share(frames, args.days)

    tr.to_csv(os.path.join(args.out, "trades.csv"), index=False)
    summ.to_csv(os.path.join(args.out, "summary.csv"), index=False)
    side.to_csv(os.path.join(args.out, "regime_share.csv"), index=False)

    with open(os.path.join(args.out, "report.md"), "w", encoding="utf-8") as f:
        f.write(f"# MTF Confluence Backtest ({args.days} วัน"
                f"{', ข้อมูลจำลอง' if args.synthetic else ''})\n\n")
        f.write(f"กฎ: ADX≥{ADX_TREND} (หรือ≥{ADX_TRANS}และขึ้น) | SL {SL_ATR}×ATR | "
                f"TP {TP_ATR}×ATR | ถือสูงสุด {MAX_HOLD_BARS} แท่ง LTF\n\n")
        f.write("## ภาพรวมทุก symbol\n\n")
        f.write(md(summ[summ["symbol"] == "ALL"]) + "\n\n")
        f.write("## แยกราย symbol\n\n")
        f.write(md(summ[summ["symbol"] != "ALL"]) + "\n\n")
        f.write("## สัดส่วนเวลาที่ TF ใหญ่เป็น sideway / เปลี่ยน / เทรนด์\n\n")
        f.write(md(side) + "\n")

    pd.set_option("display.width", 200)
    print("\n=== ภาพรวม ===")
    print(summ[summ["symbol"] == "ALL"].to_string(index=False))
    print("\n=== ราย symbol (FULL) ===")
    print(summ[(summ["symbol"] != "ALL") & (summ["variant"] == "FULL")].to_string(index=False))
    print("\n=== สัดส่วน regime ===")
    print(side.to_string(index=False))
    print(f"\nบันทึกผลไว้ที่ {os.path.abspath(args.out)}")


if __name__ == "__main__":
    main()
