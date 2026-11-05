//+------------------------------------------------------------------+
//|                                             MADE_ZoneTrader.mq5  |
//|  EA จาก MADE ZoneDrawer : เทรดโซน Liquidity (PDH/PDL) บน M15      |
//|                                                                  |
//|  จังหวะเข้า (ทุกครั้งที่แท่ง M15 ปิด)                             |
//|   BUY  : ภายใน N แท่งล่าสุด ราคาหลุดใต้ PDL (กวาด stop)            |
//|          แล้วแท่งที่ปิดล่าสุดปิดกลับขึ้นเหนือ PDL                   |
//|          + เทรนด์ H1 ขึ้น (EMA20 > EMA50 ของแท่ง H1 ที่ปิดแล้ว)      |
//|   SELL : กลับด้าน (ทะลุ PDH แล้วปิดกลับลงใต้ PDH + เทรนด์ H1 ลง)     |
//|   PDH/PDL = High/Low ของวันก่อนหน้า (เวลาเซิร์ฟเวอร์)               |
//|                                                                  |
//|  จุดออก                                                          |
//|   SL : หลังจุดต่ำสุด/สูงสุดของการกวาด + 0.1 ATR                     |
//|        (บังคับให้อยู่ระหว่าง 0.5 - 3.0 ATR M15)                      |
//|   TP : 2R  |  ออกตามเวลา : ครบ 32 แท่ง M15 (8 ชม.)                   |
//|                                                                  |
//|  ความเสี่ยง : 1% ของ balance ต่อไม้, ถือได้ 1 ไม้, ห้ามถัว             |
//|              วันละไม่เกิน 4 ไม้, แพ้ครบ 2 ไม้ในวันหยุดเทรดวันนั้น       |
//|              ขาดทุนรวมในวันถึง -3% หยุดเทรดวันนั้น                    |
//|                                                                  |
//|  Backtest (จำลองด้วย Python จากแท่ง M15 GOLDm# ม.ค. 2024-ต.ค. 2026,  |
//|  คิด spread จริงรายแท่ง + slippage 0.05):                          |
//|   ทั้งหมด 289 ไม้ (~8.7/เดือน) ชนะ 43% PF 1.22 +34.9R DD -14.5R       |
//|   ช่วง tuning (2024-01..2025-06)   PF 1.39 +29.7R                    |
//|   ช่วงทดสอบจริง (2025-07..2026-10) PF 1.06 +5.1R  DD -13.3R          |
//|   ถือเฉลี่ย 3 ชม. | ทุกปีเป็นบวก (2024 +16.6R, 2025 +6.0R, 2026 +12.3R) |
//|  ผลในอดีตไม่รับประกันอนาคต : ขอบที่เหลือในช่วงทดสอบจริงบางมาก          |
//|  ควรรันบัญชี demo / lot เล็กก่อน                                    |
//+------------------------------------------------------------------+
#property copyright "Fern for Fon (MADE)"
#property version   "1.00"
#property description "MADE ZoneTrader: PDH/PDL liquidity sweep & reclaim on M15 with H1 trend | SL beyond sweep, TP 2R, 8h time exit | 1% risk"

#include <Trade/Trade.mqh>

enum ENUM_ZT_TREND
  {
   ZT_H1_2050 = 0,   // H1 EMA20 เทียบ EMA50 (ค่าที่ tuning แล้ว)
   ZT_H4_SLOPE = 1,  // H4 EMA20 ชันขึ้น/ลง
   ZT_BOTH = 2       // ทั้งคู่ต้องตรงกัน
  };
enum ENUM_ACC_MODE
  {
   ACC_AUTO = 0,     // ตรวจเอง (USC = cent)
   ACC_CENT = 1,     // บัญชี cent
   ACC_STANDARD = 2  // บัญชีปกติ
  };

input group "=== สัญญาณ (ค่าที่ tuning แล้ว) ==="
input ENUM_ZT_TREND InpTrend      = ZT_H1_2050;   // ตัวกรองเทรนด์
input int           InpSweepBars  = 4;            // ดูการกวาด PDH/PDL ย้อนหลังกี่แท่ง M15
input int           InpATR        = 14;           // ATR (Wilder) บน M15
input int           InpSessStart  = 0;            // เริ่มรับสัญญาณ (ชม. เวลาเซิร์ฟเวอร์)
input int           InpSessEnd    = 24;           // หยุดรับสัญญาณ (ชม. เวลาเซิร์ฟเวอร์)
input group "=== จุดออก ==="
input double        InpSLBufATR   = 0.1;          // SL เผื่อหลังจุดกวาด (ATR)
input double        InpMinSLATR   = 0.5;          // SL แคบสุด (ATR)
input double        InpMaxSLATR   = 3.0;          // SL กว้างสุด (ATR)
input double        InpTP_R       = 2.0;          // TP (เท่าของ SL)
input int           InpTimeBars   = 32;           // ออกตามเวลา: ถือไม่เกินกี่แท่ง M15 (32 = 8 ชม.)
input double        InpBE_R       = 0.0;          // เลื่อน SL มาทุนเมื่อกำไรถึงกี่ R (0 = ปิด)
input group "=== ความเสี่ยง ==="
input ENUM_ACC_MODE InpAccMode    = ACC_AUTO;     // ชนิดบัญชี
input double        InpRiskPct    = 1.0;          // ความเสี่ยงต่อไม้ (% ของ balance)
input double        InpMaxRiskMinLot = 3.0;       // ยอมใช้ lot ขั้นต่ำถ้าเสี่ยงไม่เกิน %
input double        InpFixedLot   = 0.0;          // lot คงที่ (>0 = ไม่ใช้ % ความเสี่ยง)
input int           InpMaxTradesDay = 4;          // เข้าได้วันละกี่ไม้
input int           InpMaxLossDay = 2;            // แพ้ครบกี่ไม้ในวันแล้วหยุด
input double        InpDailyLossPct = 3.0;        // ขาดทุนรวมในวันถึงกี่ % แล้วหยุด (0 = ปิด)
input double        InpMaxSpread  = 0.60;         // spread สูงสุด (ราคา) 0 = ไม่เช็ค
input bool          InpAllowBuy   = true;
input bool          InpAllowSell  = true;
input group "=== อื่น ๆ ==="
input ulong         InpMagic      = 77300;        // Magic number
input int           InpDeviation  = 50;           // slippage สูงสุด (points)
input bool          InpShowPanel  = true;         // แสดงตาราง
input bool          InpDrawLevels = true;         // วาดเส้น PDH/PDL และเส้น SL/TP
input bool          InpDrawMadeZones = true;      // วาดโซนจาก MADE (made_zones.csv) ไว้ดูประกอบ
input string        InpZoneFile   = "made_zones.csv";
input int           InpPanelX     = 10;
input int           InpPanelY     = 24;
input bool          InpUseLocalClock = true;      // แสดงเวลาไทยจากนาฬิกาเครื่อง
input int           InpThaiOffset = 4;            // ถ้าไม่ใช้นาฬิกาเครื่อง: ไทย = เซิร์ฟเวอร์ + กี่ชม.

#define PFX "ZT_"
#define TF  PERIOD_M15

CTrade   trade;
int      hH1a = INVALID_HANDLE, hH1b = INVALID_HANDLE, hH4 = INVALID_HANDLE;
datetime g_lastBar = 0;
string   g_note = "waiting for next M15 close";
bool     g_cent = false, g_paused = false;
string   g_gvPause;
double   g_atr = 0, g_pdh = 0, g_pdl = 0;
int      g_trend = 0;

//+------------------------------------------------------------------+
int OnInit()
  {
   if(InpSweepBars < 1 || InpATR < 2 || InpTP_R <= 0 || InpRiskPct <= 0 || InpTimeBars < 1)
      return(INIT_PARAMETERS_INCORRECT);
   hH1a = iMA(_Symbol, PERIOD_H1, 20, 0, MODE_EMA, PRICE_CLOSE);
   hH1b = iMA(_Symbol, PERIOD_H1, 50, 0, MODE_EMA, PRICE_CLOSE);
   hH4  = iMA(_Symbol, PERIOD_H4, 20, 0, MODE_EMA, PRICE_CLOSE);
   if(hH1a == INVALID_HANDLE || hH1b == INVALID_HANDLE || hH4 == INVALID_HANDLE) return(INIT_FAILED);
   string cur = AccountInfoString(ACCOUNT_CURRENCY), cu = cur;
   StringToUpper(cu);
   if(InpAccMode == ACC_CENT) g_cent = true;
   else if(InpAccMode == ACC_STANDARD) g_cent = false;
   else g_cent = (cu == "USC" || StringFind(cu, "CENT") >= 0 || (StringLen(cur) == 3 && StringSubstr(cur, 2, 1) == "c"));
   g_gvPause = StringFormat("ZT_PAUSE_%s_%I64u", _Symbol, InpMagic);
   g_paused = GlobalVariableCheck(g_gvPause) && GlobalVariableGet(g_gvPause) > 0;
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(InpDeviation);
   trade.SetTypeFillingBySymbol(_Symbol);
   g_lastBar = iTime(_Symbol, TF, 0);                 // เริ่มทำงานจากแท่งที่ปิดถัดไป
   Refresh();
   EventSetTimer(5);
   PrintFormat("MADE ZoneTrader started: %s | risk %.2f%% | TP %.1fR | time exit %d bars | magic %I64u",
               _Symbol, InpRiskPct, InpTP_R, InpTimeBars, InpMagic);
   DrawAll();
   return(INIT_SUCCEEDED);
  }
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   EventKillTimer();
   IndicatorRelease(hH1a); IndicatorRelease(hH1b); IndicatorRelease(hH4);
   ObjectsDeleteAll(0, PFX);
   Comment("");
  }
//+------------------------------------------------------------------+
void OnTick()
  {
   ManagePosition();
   datetime t0 = iTime(_Symbol, TF, 0);
   if(t0 != 0 && t0 != g_lastBar)
     {
      g_lastBar = t0;
      OnNewBar();
     }
   static uint last = 0;
   if(GetTickCount() - last > 500) { last = GetTickCount(); DrawAll(); }
  }
void OnTimer() { ManagePosition(); DrawAll(); }
//+------------------------------------------------------------------+
void OnChartEvent(const int id, const long &lparam, const double &dparam, const string &sparam)
  {
   if(id == CHARTEVENT_OBJECT_CLICK && sparam == PFX + "BTN")
     {
      g_paused = !g_paused;
      GlobalVariableSet(g_gvPause, g_paused ? 1.0 : 0.0);
      g_note = g_paused ? "PAUSED (no new entries, open trade still managed)" : "RESUMED";
      Print(g_note);
      ObjectSetInteger(0, sparam, OBJPROP_STATE, false);
      DrawAll();
     }
  }

//==================================================================
//  ข้อมูล
//==================================================================
double WilderATR(const int shift)
  {
   MqlRates r[];
   ArraySetAsSeries(r, false);
   int n = CopyRates(_Symbol, TF, shift, 1000, r);
   if(n < InpATR + 2) return(0.0);
   double a = r[0].high - r[0].low, al = 1.0 / InpATR;
   for(int i = 1; i < n; i++)
     {
      double pc = r[i - 1].close;
      double tr = MathMax(r[i].high - r[i].low, MathMax(MathAbs(r[i].high - pc), MathAbs(r[i].low - pc)));
      a = al * tr + (1.0 - al) * a;
     }
   return(a);
  }
double Buf1(const int h, const int sh)
  {
   double v[];
   if(CopyBuffer(h, 0, sh, 1, v) != 1) return(0.0);
   return(v[0]);
  }
//--- เทรนด์จากแท่งที่ปิดแล้วเท่านั้น
int Trend()
  {
   double a = Buf1(hH1a, 1), b = Buf1(hH1b, 1);
   double c = Buf1(hH4, 1), p = Buf1(hH4, 4);
   if(a <= 0 || b <= 0 || c <= 0 || p <= 0) return(0);
   int t1 = (a > b) ? 1 : (a < b ? -1 : 0);
   int t4 = (c > p) ? 1 : (c < p ? -1 : 0);
   if(InpTrend == ZT_H1_2050) return(t1);
   if(InpTrend == ZT_H4_SLOPE) return(t4);
   return(t1 == t4 ? t1 : 0);
  }
//--- PDH/PDL ของวันก่อนหน้าแท่ง M15 ที่ shift
bool PrevDay(const int shift, double &pdh, double &pdl)
  {
   datetime tb = iTime(_Symbol, TF, shift);
   int d = iBarShift(_Symbol, PERIOD_D1, tb, false);
   if(d < 0) return(false);
   pdh = iHigh(_Symbol, PERIOD_D1, d + 1);
   pdl = iLow(_Symbol, PERIOD_D1, d + 1);
   return(pdh > 0 && pdl > 0);
  }
void Refresh()
  {
   double a = WilderATR(1); if(a > 0) g_atr = a;
   double ph, pl; if(PrevDay(1, ph, pl)) { g_pdh = ph; g_pdl = pl; }
   g_trend = Trend();
  }

//==================================================================
//  เงิน / lot
//==================================================================
double LossPerLot(const int dir, const double price, const double dist)
  {
   double pr = 0.0;
   ENUM_ORDER_TYPE ot = (dir > 0) ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   if(OrderCalcProfit(ot, _Symbol, 1.0, price, price - dir * dist, pr) && pr < 0) return(-pr);
   double tv = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE), ts = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   return(ts > 0 ? dist / ts * tv : 0.0);
  }
double LotFor(const int dir, const double price, const double dist, double &risk)
  {
   risk = 0;
   double lpl = LossPerLot(dir, price, dist);
   if(lpl <= 0) return(0);
   double bal = AccountInfoDouble(ACCOUNT_BALANCE);
   double st = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP), vmin = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN), vmax = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double lot;
   if(InpFixedLot > 0) lot = MathMax(vmin, MathFloor(InpFixedLot / st + 1e-9) * st);
   else
     {
      lot = MathFloor(bal * InpRiskPct / 100.0 / lpl / st + 1e-9) * st;
      if(lot < vmin)
        {
         if(vmin * lpl <= bal * InpMaxRiskMinLot / 100.0) lot = vmin;
         else return(0);
        }
     }
   lot = NormalizeDouble(MathMin(lot, vmax), 2);
   risk = lot * lpl;
   return(lot);
  }

//==================================================================
//  ตัวนับรายวัน / ไม้ที่ถืออยู่
//==================================================================
datetime DayStart()
  {
   MqlDateTime dt; TimeToStruct(TimeCurrent(), dt);
   dt.hour = 0; dt.min = 0; dt.sec = 0;
   return(StructToTime(dt));
  }
void TodayStats(int &entries, int &losses, double &pnl)
  {
   entries = 0; losses = 0; pnl = 0;
   if(!HistorySelect(DayStart(), TimeCurrent() + 60)) return;
   int n = HistoryDealsTotal();
   for(int i = 0; i < n; i++)
     {
      ulong tk = HistoryDealGetTicket(i);
      if(tk == 0) continue;
      if((ulong)HistoryDealGetInteger(tk, DEAL_MAGIC) != InpMagic || HistoryDealGetString(tk, DEAL_SYMBOL) != _Symbol) continue;
      long en = HistoryDealGetInteger(tk, DEAL_ENTRY);
      if(en == DEAL_ENTRY_IN) { entries++; continue; }
      if(en != DEAL_ENTRY_OUT && en != DEAL_ENTRY_OUT_BY && en != DEAL_ENTRY_INOUT) continue;
      double v = HistoryDealGetDouble(tk, DEAL_PROFIT) + HistoryDealGetDouble(tk, DEAL_SWAP) + HistoryDealGetDouble(tk, DEAL_COMMISSION) + HistoryDealGetDouble(tk, DEAL_FEE);
      pnl += v;
      if(v < 0) losses++;
     }
  }
bool MyPosition(ulong &tk)
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong t = PositionGetTicket(i);
      if(t == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) == _Symbol && (ulong)PositionGetInteger(POSITION_MAGIC) == InpMagic) { tk = t; return(true); }
     }
   return(false);
  }
string BlockReason()
  {
   int e, ls; double pnl;
   TodayStats(e, ls, pnl);
   double fl = 0; ulong tk;
   if(MyPosition(tk) && PositionSelectByTicket(tk)) fl = PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
   if(e >= InpMaxTradesDay) return(StringFormat("max %d trades today", InpMaxTradesDay));
   if(ls >= InpMaxLossDay) return(StringFormat("%d losses today - stop", ls));
   double bal = AccountInfoDouble(ACCOUNT_BALANCE);
   if(InpDailyLossPct > 0 && pnl + fl <= -bal * InpDailyLossPct / 100.0) return(StringFormat("daily loss -%.1f%% reached", InpDailyLossPct));
   return("");
  }

//==================================================================
//  ดูแลไม้ที่ถืออยู่: ออกตามเวลา + เลื่อน SL มาทุน
//==================================================================
void ManagePosition()
  {
   ulong tk;
   if(!MyPosition(tk) || !PositionSelectByTicket(tk)) return;
   datetime ot = (datetime)PositionGetInteger(POSITION_TIME);
   datetime entryBar = (datetime)((long)ot - (long)ot % PeriodSeconds(TF));
   datetime due = entryBar + (datetime)(InpTimeBars * PeriodSeconds(TF));
   if(TimeCurrent() >= due)
     {
      if(trade.PositionClose(tk)) g_note = StringFormat("time exit #%I64u after %d bars", tk, InpTimeBars);
      else g_note = StringFormat("time exit #%I64u failed %d", tk, trade.ResultRetcode());
      Print(g_note);
      return;
     }
   if(InpBE_R > 0)
     {
      bool buy = PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY;
      double op = PositionGetDouble(POSITION_PRICE_OPEN), sl = PositionGetDouble(POSITION_SL), tp = PositionGetDouble(POSITION_TP);
      double R = MathAbs(op - sl);
      if(R <= 0 || (buy && sl >= op) || (!buy && sl <= op)) return;
      double px = buy ? SymbolInfoDouble(_Symbol, SYMBOL_BID) : SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      if((buy && px - op >= InpBE_R * R) || (!buy && op - px >= InpBE_R * R))
         if(trade.PositionModify(tk, NormalizeDouble(op, _Digits), tp)) { g_note = "SL moved to breakeven"; Print(g_note); }
     }
  }

//==================================================================
//  สัญญาณเมื่อแท่ง M15 ปิด
//==================================================================
void Skip(const string side, const string why) { g_note = side + " skipped: " + why; Print(g_note); }

void OnNewBar()
  {
   Refresh();
   double atr = g_atr;
   double c1 = iClose(_Symbol, TF, 1);
   double pdh, pdl;
   if(atr <= 0 || c1 <= 0 || !PrevDay(1, pdh, pdl)) { g_note = "data not ready"; return; }
   // จุดต่ำสุด/สูงสุดของ N แท่งที่ปิดแล้วล่าสุด (รวมแท่งที่เพิ่งปิด)
   double lo = iLow(_Symbol, TF, iLowest(_Symbol, TF, MODE_LOW, InpSweepBars, 1));
   double hi = iHigh(_Symbol, TF, iHighest(_Symbol, TF, MODE_HIGH, InpSweepBars, 1));
   int hr; { MqlDateTime dt; TimeToStruct(iTime(_Symbol, TF, 1), dt); hr = dt.hour; }
   if(hr < InpSessStart || hr >= InpSessEnd) return;
   int sig = 0;
   if(lo < pdl && c1 > pdl && g_trend > 0) sig = 1;        // กวาด PDL แล้วปิดกลับขึ้น ในเทรนด์ขาขึ้น
   if(hi > pdh && c1 < pdh && g_trend < 0) sig = -1;       // กวาด PDH แล้วปิดกลับลง ในเทรนด์ขาลง
   if(sig == 0) return;
   string side = sig > 0 ? "BUY" : "SELL";
   if((sig > 0 && !InpAllowBuy) || (sig < 0 && !InpAllowSell)) { Skip(side, "direction disabled"); return; }
   ulong tk;
   if(MyPosition(tk)) return;                                // ถือได้ 1 ไม้ ไม่ถัว
   if(g_paused) { Skip(side, "paused"); return; }
   string blk = BlockReason();
   if(blk != "") { Skip(side, blk); return; }
   MqlTick tick;
   if(!SymbolInfoTick(_Symbol, tick)) return;
   if(InpMaxSpread > 0 && tick.ask - tick.bid > InpMaxSpread) { Skip(side, StringFormat("spread %.2f", tick.ask - tick.bid)); return; }

   double dist = (sig > 0 ? c1 - lo : hi - c1) + InpSLBufATR * atr;
   dist = MathMax(InpMinSLATR * atr, MathMin(dist, InpMaxSLATR * atr));
   double price = sig > 0 ? tick.ask : tick.bid;
   double sl = NormalizeDouble(price - sig * dist, _Digits);
   double tp = NormalizeDouble(price + sig * dist * InpTP_R, _Digits);
   double risk, lot = LotFor(sig, price, dist, risk);
   if(lot <= 0) { Skip(side, "balance too small for min lot"); return; }
   bool ok = sig > 0 ? trade.Buy(lot, _Symbol, price, sl, tp, "MADE ZT")
                     : trade.Sell(lot, _Symbol, price, sl, tp, "MADE ZT");
   if(ok && (trade.ResultRetcode() == TRADE_RETCODE_DONE || trade.ResultRetcode() == TRADE_RETCODE_PLACED))
      g_note = StringFormat("OPEN %s %.2f @ %.2f SL %.2f TP %.2f risk %.2f", side, lot, trade.ResultPrice(), sl, tp, risk);
   else
      g_note = StringFormat("%s failed %d %s", side, trade.ResultRetcode(), trade.ResultRetcodeDescription());
   Print(g_note);
  }

//==================================================================
//  แสดงผล
//==================================================================
datetime ToThai(const datetime srv)
  {
   long off = (long)InpThaiOffset * 3600;
   if(InpUseLocalClock) off = (long)MathRound((double)(TimeLocal() - TimeTradeServer()) / 1800.0) * 1800;
   return((datetime)(srv + off));
  }
void Label(const string nm, const int row, const string txt, const color col)
  {
   string n = PFX + nm;
   if(ObjectFind(0, n) < 0)
     {
      ObjectCreate(0, n, OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(0, n, OBJPROP_CORNER, CORNER_LEFT_UPPER);
      ObjectSetInteger(0, n, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, n, OBJPROP_HIDDEN, true);
      ObjectSetString(0, n, OBJPROP_FONT, "Consolas");
      ObjectSetInteger(0, n, OBJPROP_FONTSIZE, 9);
     }
   ObjectSetInteger(0, n, OBJPROP_XDISTANCE, InpPanelX);
   ObjectSetInteger(0, n, OBJPROP_YDISTANCE, InpPanelY + row * 16);
   ObjectSetInteger(0, n, OBJPROP_COLOR, col);
   ObjectSetString(0, n, OBJPROP_TEXT, txt);
  }
void HLine(const string nm, const double px, const color col, const ENUM_LINE_STYLE st, const string tip)
  {
   string n = PFX + nm;
   if(px <= 0) { ObjectDelete(0, n); return; }
   if(ObjectFind(0, n) < 0)
     {
      ObjectCreate(0, n, OBJ_HLINE, 0, 0, px);
      ObjectSetInteger(0, n, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, n, OBJPROP_HIDDEN, true);
      ObjectSetInteger(0, n, OBJPROP_BACK, true);
     }
   ObjectSetDouble(0, n, OBJPROP_PRICE, px);
   ObjectSetInteger(0, n, OBJPROP_COLOR, col);
   ObjectSetInteger(0, n, OBJPROP_STYLE, st);
   ObjectSetString(0, n, OBJPROP_TOOLTIP, tip);
  }
void VLine(const string nm, const datetime t, const color col, const string tip)
  {
   string n = PFX + nm;
   if(t <= 0) { ObjectDelete(0, n); return; }
   if(ObjectFind(0, n) < 0)
     {
      ObjectCreate(0, n, OBJ_VLINE, 0, t, 0);
      ObjectSetInteger(0, n, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, n, OBJPROP_HIDDEN, true);
      ObjectSetInteger(0, n, OBJPROP_BACK, true);
      ObjectSetInteger(0, n, OBJPROP_STYLE, STYLE_DASHDOT);
     }
   ObjectMove(0, n, 0, t, 0);
   ObjectSetInteger(0, n, OBJPROP_COLOR, col);
   ObjectSetString(0, n, OBJPROP_TOOLTIP, tip);
  }
//--- โซนจาก MADE (อ่านอย่างเดียว ไว้ดูประกอบ ไม่ใช้เป็นสัญญาณ)
void DrawMadeZones()
  {
   static datetime lastRead = 0;
   if(TimeCurrent() - lastRead < 15) return;
   lastRead = TimeCurrent();
   ObjectsDeleteAll(0, PFX + "Z");
   int h = FileOpen(InpZoneFile, FILE_READ | FILE_CSV | FILE_ANSI | FILE_COMMON, ',');
   if(h == INVALID_HANDLE) return;
   bool header = true; int k = 0;
   datetime tl = iTime(_Symbol, PERIOD_CURRENT, 60), tr = TimeCurrent() + 30 * PeriodSeconds(PERIOD_CURRENT);
   while(!FileIsEnding(h) && k < 40)
     {
      string s = FileReadString(h);
      if(FileIsLineEnding(h) && StringLen(s) == 0) continue;
      string kind = FileReadString(h), side = FileReadString(h);
      double lo = StringToDouble(FileReadString(h)), hi = StringToDouble(FileReadString(h));
      FileReadString(h); FileReadString(h); FileReadString(h);
      if(header) { header = false; continue; }
      if(s != _Symbol || lo <= 0 || hi <= 0) continue;
      string n = PFX + "Z" + IntegerToString(k++);
      if(ObjectCreate(0, n, OBJ_RECTANGLE, 0, tl, lo, tr, hi))
        {
         ObjectSetInteger(0, n, OBJPROP_COLOR, side == "BUY" ? C'20,70,45' : C'80,30,30');
         ObjectSetInteger(0, n, OBJPROP_FILL, true);
         ObjectSetInteger(0, n, OBJPROP_BACK, true);
         ObjectSetInteger(0, n, OBJPROP_SELECTABLE, false);
         ObjectSetInteger(0, n, OBJPROP_HIDDEN, true);
         ObjectSetString(0, n, OBJPROP_TOOLTIP, "MADE " + side + " " + kind);
        }
     }
   FileClose(h);
  }
void DrawAll()
  {
   if(MQLInfoInteger(MQL_TESTER) && !MQLInfoInteger(MQL_VISUAL_MODE)) return;
   if(g_atr <= 0) Refresh();
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID), ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   if(InpDrawMadeZones) DrawMadeZones();
   if(InpDrawLevels)
     {
      HLine("PDH", g_pdh, clrIndianRed, STYLE_DASH, "PDH (sweep up then close below = SELL setup in downtrend)");
      HLine("PDL", g_pdl, clrSeaGreen,  STYLE_DASH, "PDL (sweep down then close above = BUY setup in uptrend)");
     }
   ulong tk; bool hasPos = MyPosition(tk) && PositionSelectByTicket(tk);
   string posTxt = "POS none", posTxt2 = "";
   color  posCol = clrSilver;
   if(hasPos)
     {
      bool buy = PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY;
      double op = PositionGetDouble(POSITION_PRICE_OPEN), sl = PositionGetDouble(POSITION_SL), tp = PositionGetDouble(POSITION_TP);
      double pr = PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
      datetime ot = (datetime)PositionGetInteger(POSITION_TIME);
      datetime due = (datetime)((long)ot - (long)ot % PeriodSeconds(TF) + (long)InpTimeBars * PeriodSeconds(TF));
      double R = MathAbs(op - sl), now = buy ? bid : ask;
      posTxt = StringFormat("POS %s %.2f @ %s  P/L %+.2f (%+.2fR)", buy ? "BUY" : "SELL", PositionGetDouble(POSITION_VOLUME),
                            DoubleToString(op, _Digits), pr, R > 0 ? (buy ? now - op : op - now) / R : 0);
      posTxt2 = StringFormat("    SL %s  TP %s  exit by %s TH", DoubleToString(sl, _Digits), DoubleToString(tp, _Digits),
                             TimeToString(ToThai(due), TIME_MINUTES));
      posCol = pr >= 0 ? clrLimeGreen : clrTomato;
      if(InpDrawLevels) { HLine("SL", sl, clrOrangeRed, STYLE_DOT, "SL"); HLine("TP", tp, clrLimeGreen, STYLE_DOT, "TP"); VLine("EXIT", due, clrOrange, "time exit " + TimeToString(ToThai(due), TIME_MINUTES) + " TH"); }
     }
   else { ObjectDelete(0, PFX + "SL"); ObjectDelete(0, PFX + "TP"); ObjectDelete(0, PFX + "EXIT"); }
   if(!InpShowPanel) { ChartRedraw(); return; }
   int e, ls; double pnl; TodayStats(e, ls, pnl);
   string blk = BlockReason();
   string status = g_paused ? "PAUSED" : (blk != "" ? "BLOCKED: " + blk : (TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) && MQLInfoInteger(MQL_TRADE_ALLOWED) ? "RUNNING" : "ALGO OFF"));
   string tr = g_trend > 0 ? "UP -> BUY sweeps of PDL only" : (g_trend < 0 ? "DOWN -> SELL sweeps of PDH only" : "FLAT -> no trade");
   double a = g_atr;
   Label("L0", 0, "MADE ZoneTrader  PDH/PDL sweep & reclaim  (M15, hold <= " + IntegerToString(InpTimeBars * 15 / 60) + "h)", clrGold);
   Label("L1", 1, _Symbol + " | " + status, status == "RUNNING" ? clrLimeGreen : (g_paused ? clrOrange : clrTomato));
   Label("L2", 2, "Trend " + tr, g_trend > 0 ? clrLimeGreen : (g_trend < 0 ? clrTomato : clrSilver));
   Label("L3", 3, StringFormat("PDH %s (%+.2f ATR)   PDL %s (%+.2f ATR)", DoubleToString(g_pdh, _Digits), a > 0 ? (g_pdh - bid) / a : 0,
                               DoubleToString(g_pdl, _Digits), a > 0 ? (g_pdl - ask) / a : 0), clrSilver);
   Label("L4", 4, StringFormat("ATR(M15) %.2f  spread %.2f  today %d trades %d losses P/L %+.2f", a, ask - bid, e, ls, pnl), clrSilver);
   Label("L5", 5, posTxt, posCol);
   Label("L6", 6, posTxt2, clrSilver);
   Label("L7", 7, "Last: " + g_note, clrOrange);
   string bn = PFX + "BTN";
   if(ObjectFind(0, bn) < 0)
     {
      ObjectCreate(0, bn, OBJ_BUTTON, 0, 0, 0);
      ObjectSetInteger(0, bn, OBJPROP_CORNER, CORNER_LEFT_UPPER);
      ObjectSetInteger(0, bn, OBJPROP_XSIZE, 70); ObjectSetInteger(0, bn, OBJPROP_YSIZE, 18);
      ObjectSetInteger(0, bn, OBJPROP_SELECTABLE, false); ObjectSetInteger(0, bn, OBJPROP_HIDDEN, true);
      ObjectSetInteger(0, bn, OBJPROP_FONTSIZE, 8);
     }
   ObjectSetInteger(0, bn, OBJPROP_XDISTANCE, InpPanelX);
   ObjectSetInteger(0, bn, OBJPROP_YDISTANCE, InpPanelY + 8 * 16 + 4);
   ObjectSetString(0, bn, OBJPROP_TEXT, g_paused ? "RESUME" : "PAUSE");
   ObjectSetInteger(0, bn, OBJPROP_BGCOLOR, g_paused ? clrSeaGreen : C'180,83,9');
   ObjectSetInteger(0, bn, OBJPROP_COLOR, clrWhite);
   ChartRedraw();
  }
//+------------------------------------------------------------------+
