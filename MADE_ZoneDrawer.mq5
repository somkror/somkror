//+------------------------------------------------------------------+
//|                                              MADE_ZoneDrawer.mq5 |
//|  วาดโซนรอเข้าเทรดที่คำนวณจาก MADE (Python) ลงบนกราฟ MT5           |
//|  v2.00 : เพิ่มตัวบอกสถานะสด จากราคา Bid/Ask เทียบกับแต่ละโซน       |
//|          ENTRY / NEAR / WAIT / MISSED / BROKEN + ระยะห่าง           |
//|          และตัวกรองกฎข้อ 1-2 จากการวิเคราะห์ประวัติเทรด 3 เดือน     |
//|                                                                  |
//|  วิธีใช้                                                          |
//|   1. วางไฟล์นี้ที่  MQL5\Experts\MADE_ZoneDrawer.mq5              |
//|   2. ใน MetaEditor กด F7 เพื่อ compile                            |
//|   3. ลาก EA ลงบนกราฟของ symbol ที่ต้องการ (ลงได้หลายกราฟพร้อมกัน) |
//|   4. ไม่ต้องเปิด Algo Trading เพราะ EA นี้ไม่ส่งคำสั่ง              |
//|                                                                  |
//|  EA นี้อ่านอย่างเดียว ไม่เปิด/ปิดออเดอร์ใด ๆ ทั้งสิ้น              |
//|                                                                  |
//|  ราคาที่ใช้วัด:  โซน BUY ใช้ Ask (ราคาที่ซื้อได้จริง)               |
//|                 โซน SELL ใช้ Bid (ราคาที่ขายได้จริง)                |
//|                                                                  |
//|  สถานะของแต่ละโซน                                                 |
//|   ENTRY  = ราคาอยู่ในโซนแล้ว (รอแท่งยืนยันตาม trigger ของโซน)       |
//|   NEAR   = กำลังเข้าใกล้ ห่างไม่เกิน NearAtr                         |
//|   WAIT   = ยังห่าง รอราคาวิ่งมาหาโซน                                |
//|   MISSED = ราคาเคยแตะโซนภายใน TouchLookback แท่ง แล้ววิ่งออกไปทาง   |
//|            ที่ควรจะได้กำไร  = เลยจุดเข้าไปแล้ว อย่าไล่ราคา           |
//|   SWEPT  = (เฉพาะโซน LIQ ของ PDH/PDL) ราคาทะลุแนวไปกวาด stop แล้ว   |
//|            รอปิดแท่งกลับเข้ามาตาม trigger                          |
//|   BROKEN = ราคาทะลุโซนไปฝั่งที่ผิด (BUY หลุดใต้โซน / SELL ทะลุเหนือ) |
//|            โซนเสีย ไม่ควรเข้า                                       |
//+------------------------------------------------------------------+
#property copyright "MADE"
#property version   "2.00"
#property strict

input string FileName        = "made_zones.csv";  // ไฟล์ที่ Python เขียน (ใน Common\Files)
input int    RefreshSeconds  = 10;                // อ่านไฟล์ซ้ำทุกกี่วินาที
input int    ExtendBars      = 30;                // ลากกล่องไปทางขวากี่แท่ง
input int    HistoryBars     = 60;                // กล่องเริ่มจากกี่แท่งย้อนหลัง
input color  BuyColor        = clrSeaGreen;       // สีโซนฝั่ง BUY
input color  SellColor       = clrIndianRed;      // สีโซนฝั่ง SELL
input bool   ShowLabels      = true;              // แสดงข้อความกำกับโซน
input bool   OnlyNearZones   = false;             // แสดงเฉพาะโซนที่ใกล้ (<= NearAtrLimit)
input double NearAtrLimit    = 2.0;               // ใช้กับ OnlyNearZones

input group  "สถานะสด (Bid/Ask)"
input ENUM_TIMEFRAMES AtrTf  = PERIOD_M15;        // timeframe ของ ATR ที่ใช้วัดระยะ
input int    AtrPeriod       = 14;                // ATR period
input double NearAtr         = 0.5;               // ห่างไม่เกินกี่ ATR = NEAR
input int    TouchLookback   = 8;                 // แท่ง (AtrTf) ย้อนหลังที่ใช้ดูว่าเคยแตะโซน
input bool   ShowPanel       = true;              // แสดงตารางสถานะมุมจอ
input ENUM_BASE_CORNER PanelCorner = CORNER_LEFT_UPPER; // มุมของตาราง
input int    PanelX          = 10;
input int    PanelY          = 24;
input int    PanelFontSize   = 9;
input bool   DrawGuideLine   = true;              // เส้นประจากราคาปัจจุบันไปโซนที่ใกล้สุด

input group  "กฎจากการวิเคราะห์ประวัติเทรด"
input bool   UseRuleFilter   = true;              // แสดงคำเตือนกฎข้อ 1-2
input double ChaseAtr        = 0.5;               // กฎ 1: สวนเทรนด์ H1 และห่าง EMA20 เกินนี้ = ห้ามเข้า
input double PullbackAtr     = 0.3;               // กฎ 2: ตามเทรนด์แต่ห่างเกินนี้ = รอ Limit ที่ EMA20 +/- ค่านี้

#define PREFIX "MADE_"
#define MAXZ   64

// ---- โซนที่อ่านจากไฟล์ ----
int     g_n = 0;
string  g_kind[MAXZ], g_side[MAXZ], g_str[MAXZ], g_trig[MAXZ];
double  g_low[MAXZ], g_high[MAXZ], g_fdist[MAXZ];

int     h_atr = INVALID_HANDLE, h_e20 = INVALID_HANDLE, h_h1f = INVALID_HANDLE, h_h1s = INVALID_HANDLE;
ulong   g_lastLiveMs = 0;

//+------------------------------------------------------------------+
int OnInit()
  {
   h_atr = iATR(_Symbol, AtrTf, AtrPeriod);
   h_e20 = iMA(_Symbol, PERIOD_M15, 20, 0, MODE_EMA, PRICE_CLOSE);
   h_h1f = iMA(_Symbol, PERIOD_H1, 20, 0, MODE_EMA, PRICE_CLOSE);
   h_h1s = iMA(_Symbol, PERIOD_H1, 50, 0, MODE_EMA, PRICE_CLOSE);
   EventSetTimer(MathMax(1, RefreshSeconds));
   LoadAndDraw();
   UpdateLive();
   return(INIT_SUCCEEDED);
  }
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   EventKillTimer();
   ClearObjects(PREFIX);
   Comment("");
   for(int i = 0; i < 4; i++)
     {
      int h = (i == 0 ? h_atr : i == 1 ? h_e20 : i == 2 ? h_h1f : h_h1s);
      if(h != INVALID_HANDLE) IndicatorRelease(h);
     }
   ChartRedraw();
  }
//+------------------------------------------------------------------+
void OnTimer()
  {
   LoadAndDraw();
   UpdateLive();
  }
//+------------------------------------------------------------------+
void OnTick()
  {
   ulong now = GetTickCount64();
   if(now - g_lastLiveMs < 300) return;        // ไม่ต้องวาดถี่เกิน ~3 ครั้ง/วินาที
   g_lastLiveMs = now;
   UpdateLive();
  }
//+------------------------------------------------------------------+
void ClearObjects(const string pre)
  {
   for(int i = ObjectsTotal(0, -1, -1) - 1; i >= 0; i--)
     {
      string nm = ObjectName(0, i, -1, -1);
      if(StringFind(nm, pre) == 0)
         ObjectDelete(0, nm);
     }
  }
//+------------------------------------------------------------------+
double Buf(const int handle, const int shift = 0)
  {
   if(handle == INVALID_HANDLE) return 0.0;
   double b[];
   if(CopyBuffer(handle, 0, shift, 1, b) != 1) return 0.0;
   return b[0];
  }
//+------------------------------------------------------------------+
//| อ่าน CSV เก็บโซนของ symbol นี้ แล้ววาดกล่อง                         |
//+------------------------------------------------------------------+
void LoadAndDraw()
  {
   int h = FileOpen(FileName, FILE_READ | FILE_CSV | FILE_ANSI | FILE_COMMON, ',');
   if(h == INVALID_HANDLE)
     {
      Comment("MADE: cannot open file -> Common\\Files\\", FileName,
              "  (error ", GetLastError(), ")");
      return;
     }
   Comment("");
   g_n = 0;
   bool header = true;
   while(!FileIsEnding(h) && g_n < MAXZ)
     {
      string f_sym  = FileReadString(h);
      if(FileIsLineEnding(h) && StringLen(f_sym) == 0) continue;
      string f_kind = FileReadString(h);
      string f_side = FileReadString(h);
      double f_low  = StringToDouble(FileReadString(h));
      double f_high = StringToDouble(FileReadString(h));
      double f_dist = StringToDouble(FileReadString(h));
      string f_str  = FileReadString(h);
      string f_trig = FileReadString(h);
      if(header) { header = false; continue; }
      if(f_sym != _Symbol) continue;
      if(f_low <= 0 || f_high <= 0) continue;
      if(OnlyNearZones && f_dist > NearAtrLimit) continue;
      g_kind[g_n] = f_kind; g_side[g_n] = f_side; g_low[g_n] = MathMin(f_low, f_high);
      g_high[g_n] = MathMax(f_low, f_high); g_fdist[g_n] = f_dist; g_str[g_n] = f_str; g_trig[g_n] = f_trig;
      g_n++;
     }
   FileClose(h);

   ClearObjects(PREFIX + "Z");
   datetime t_left  = iTime(_Symbol, PERIOD_CURRENT, MathMin(HistoryBars, Bars(_Symbol, PERIOD_CURRENT) - 1));
   datetime t_right = TimeCurrent() + (datetime)(ExtendBars * PeriodSeconds(PERIOD_CURRENT));
   for(int i = 0; i < g_n; i++)
     {
      bool  isBuy = (g_side[i] == "BUY");
      color col   = isBuy ? BuyColor : SellColor;
      string rc = PREFIX + "Z" + IntegerToString(i) + "_box";
      if(ObjectCreate(0, rc, OBJ_RECTANGLE, 0, t_left, g_low[i], t_right, g_high[i]))
        {
         ObjectSetInteger(0, rc, OBJPROP_COLOR, col);
         ObjectSetInteger(0, rc, OBJPROP_FILL, true);
         ObjectSetInteger(0, rc, OBJPROP_BACK, true);
         ObjectSetInteger(0, rc, OBJPROP_SELECTABLE, false);
         ObjectSetInteger(0, rc, OBJPROP_HIDDEN, true);
        }
      if(ShowLabels)
        {
         string tx = PREFIX + "Z" + IntegerToString(i) + "_txt";
         if(ObjectCreate(0, tx, OBJ_TEXT, 0, t_right, isBuy ? g_low[i] : g_high[i]))
           {
            ObjectSetString(0, tx, OBJPROP_TOOLTIP, g_trig[i]);
            ObjectSetInteger(0, tx, OBJPROP_COLOR, col);
            ObjectSetInteger(0, tx, OBJPROP_FONTSIZE, 8);
            ObjectSetInteger(0, tx, OBJPROP_ANCHOR, isBuy ? ANCHOR_RIGHT_UPPER : ANCHOR_RIGHT_LOWER);
            ObjectSetInteger(0, tx, OBJPROP_SELECTABLE, false);
            ObjectSetInteger(0, tx, OBJPROP_HIDDEN, true);
           }
        }
     }
   ChartRedraw();
  }
//+------------------------------------------------------------------+
//| ราคาเคยแตะโซนภายใน TouchLookback แท่งล่าสุดหรือไม่                  |
//+------------------------------------------------------------------+
bool TouchedRecently(const double lo, const double hi)
  {
   double hh[], ll[];
   int n = MathMax(1, TouchLookback);
   if(CopyHigh(_Symbol, AtrTf, 0, n, hh) != n) return false;
   if(CopyLow(_Symbol, AtrTf, 0, n, ll) != n) return false;
   for(int k = 0; k < n; k++)
      if(ll[k] <= hi && hh[k] >= lo) return true;
   return false;
  }
//+------------------------------------------------------------------+
//| สถานะของโซน: คืนชื่อสถานะ, ระยะ (ราคา, + = ยังต้องวิ่งไปหา /      |
//| - = เลย/ทะลุไปแล้ว) และสี                                            |
//+------------------------------------------------------------------+
string ZoneStatus(const int i, const double bid, const double ask, const double atr,
                  double &dist, color &col)
  {
   bool isBuy = (g_side[i] == "BUY");
   double px  = isBuy ? ask : bid;
   double lo  = g_low[i], hi = g_high[i];
   if(px >= lo && px <= hi) { dist = 0; col = clrGold; return "ENTRY"; }
   if(isBuy)
     {
      if(px > hi)                                       // อยู่เหนือโซน: รอราคาย่อลงมา หรือเลยไปแล้ว
        {
         dist = px - hi;
         if(TouchedRecently(lo, hi)) { col = clrDarkGray; return "MISSED"; }
         col = (atr > 0 && dist <= NearAtr * atr) ? clrDeepSkyBlue : clrSilver;
         return (atr > 0 && dist <= NearAtr * atr) ? "NEAR" : "WAIT";
        }
      dist = lo - px;
      // โซน liquidity (PDL) : การหลุดลงไปคือการกวาด stop ซึ่งเป็นจังหวะที่รออยู่ ไม่ใช่โซนเสีย
      if(StringFind(g_kind[i], "LIQ") == 0) { col = clrOrange; return "SWEPT"; }
      col = clrTomato; return "BROKEN";  // หลุดใต้โซน BUY
     }
   else
     {
      if(px < lo)
        {
         dist = lo - px;
         if(TouchedRecently(lo, hi)) { col = clrDarkGray; return "MISSED"; }
         col = (atr > 0 && dist <= NearAtr * atr) ? clrDeepSkyBlue : clrSilver;
         return (atr > 0 && dist <= NearAtr * atr) ? "NEAR" : "WAIT";
        }
      dist = px - hi;
      if(StringFind(g_kind[i], "LIQ") == 0) { col = clrOrange; return "SWEPT"; }
      col = clrTomato; return "BROKEN";  // ทะลุเหนือโซน SELL
     }
  }
//+------------------------------------------------------------------+
string StatusText(const string st, const double dist, const double atr)
  {
   string d = DoubleToString(dist, _Digits);
   string a = (atr > 0) ? StringFormat("%.2f ATR", dist / atr) : "-";
   string p = IntegerToString((int)MathRound(dist / _Point)) + " pts";
   if(st == "ENTRY")  return "ENTRY: price in zone - wait for trigger candle";
   if(st == "NEAR")   return "NEAR: " + d + " to go (" + a + ", " + p + ")";
   if(st == "WAIT")   return "WAIT: " + d + " away (" + a + ", " + p + ")";
   if(st == "SWEPT")  return "SWEPT: " + d + " beyond level (" + a + ") - wait for close back inside";
   if(st == "MISSED") return "MISSED: " + d + " past zone (" + a + ") - do not chase";
   return "BROKEN: " + d + " through zone (" + a + ") - zone invalid";
  }
//+------------------------------------------------------------------+
void SetLabel(const string nm, const int row, const string text, const color col, const bool bold = false)
  {
   if(ObjectFind(0, nm) < 0)
     {
      ObjectCreate(0, nm, OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(0, nm, OBJPROP_CORNER, PanelCorner);
      ObjectSetInteger(0, nm, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, nm, OBJPROP_HIDDEN, true);
      ObjectSetInteger(0, nm, OBJPROP_BACK, false);
      bool right = (PanelCorner == CORNER_RIGHT_UPPER || PanelCorner == CORNER_RIGHT_LOWER);
      bool lower = (PanelCorner == CORNER_LEFT_LOWER || PanelCorner == CORNER_RIGHT_LOWER);
      ObjectSetInteger(0, nm, OBJPROP_ANCHOR, right ? (lower ? ANCHOR_RIGHT_LOWER : ANCHOR_RIGHT_UPPER)
                                                    : (lower ? ANCHOR_LEFT_LOWER : ANCHOR_LEFT_UPPER));
     }
   ObjectSetInteger(0, nm, OBJPROP_XDISTANCE, PanelX);
   ObjectSetInteger(0, nm, OBJPROP_YDISTANCE, PanelY + row * (PanelFontSize + 7));
   ObjectSetString(0, nm, OBJPROP_FONT, "Consolas");
   ObjectSetInteger(0, nm, OBJPROP_FONTSIZE, PanelFontSize);
   ObjectSetInteger(0, nm, OBJPROP_COLOR, col);
   ObjectSetString(0, nm, OBJPROP_TEXT, text);
  }
//+------------------------------------------------------------------+
//| อัปเดตสถานะสดทุก tick (ไม่อ่านไฟล์ใหม่)                              |
//+------------------------------------------------------------------+
void UpdateLive()
  {
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   if(bid <= 0 || ask <= 0) return;
   double atr = Buf(h_atr, 0);

   string st[MAXZ]; double ds[MAXZ]; color cs[MAXZ]; int ord[MAXZ];
   for(int i = 0; i < g_n; i++)
     {
      double dd = 0; color cc = clrSilver;
      st[i] = ZoneStatus(i, bid, ask, atr, dd, cc);
      ds[i] = dd; cs[i] = cc;
      ord[i] = i;
      if(ShowLabels)
        {
         string tx = PREFIX + "Z" + IntegerToString(i) + "_txt";
         if(ObjectFind(0, tx) >= 0)
           {
            string mark = (st[i] == "ENTRY") ? ">> " : "";
            ObjectSetString(0, tx, OBJPROP_TEXT, StringFormat("%s%s %s %s | %s", mark, g_side[i], g_kind[i],
                            g_str[i], StatusText(st[i], ds[i], atr)));
            ObjectSetInteger(0, tx, OBJPROP_COLOR, (st[i] == "ENTRY" || st[i] == "NEAR") ? cs[i]
                             : (g_side[i] == "BUY" ? BuyColor : SellColor));
           }
         string rc = PREFIX + "Z" + IntegerToString(i) + "_box";
         if(ObjectFind(0, rc) >= 0)
            ObjectSetInteger(0, rc, OBJPROP_WIDTH, (st[i] == "ENTRY" || st[i] == "NEAR") ? 3 : 1);
        }
     }
   // เรียง: ENTRY ก่อน แล้ว NEAR, WAIT ตามระยะใกล้-ไกล, MISSED/BROKEN ไว้ท้าย
   for(int a = 0; a < g_n - 1; a++)
      for(int b = a + 1; b < g_n; b++)
        {
         int x = ord[a], y = ord[b];
         int rx = (st[x] == "ENTRY") ? 0 : (st[x] == "SWEPT" || st[x] == "NEAR") ? 1 : (st[x] == "WAIT") ? 2 : 3;
         int ry = (st[y] == "ENTRY") ? 0 : (st[y] == "SWEPT" || st[y] == "NEAR") ? 1 : (st[y] == "WAIT") ? 2 : 3;
         if(ry < rx || (ry == rx && ds[y] < ds[x])) { ord[a] = y; ord[b] = x; }
        }

   // ---- เส้นประไปโซนที่ใกล้ที่สุดที่ยังรอเข้าได้ ----
   string gl = PREFIX + "guide";
   if(DrawGuideLine && g_n > 0 && (st[ord[0]] == "NEAR" || st[ord[0]] == "WAIT"))
     {
      int i = ord[0];
      bool isBuy = (g_side[i] == "BUY");
      double from = isBuy ? ask : bid, to = isBuy ? g_high[i] : g_low[i];
      datetime t = TimeCurrent() + (datetime)(3 * PeriodSeconds(PERIOD_CURRENT));
      if(ObjectFind(0, gl) < 0)
        {
         ObjectCreate(0, gl, OBJ_TREND, 0, t, from, t, to);
         ObjectSetInteger(0, gl, OBJPROP_STYLE, STYLE_DOT);
         ObjectSetInteger(0, gl, OBJPROP_RAY_RIGHT, false);
         ObjectSetInteger(0, gl, OBJPROP_SELECTABLE, false);
         ObjectSetInteger(0, gl, OBJPROP_HIDDEN, true);
        }
      ObjectMove(0, gl, 0, t, from);
      ObjectMove(0, gl, 1, t, to);
      ObjectSetInteger(0, gl, OBJPROP_COLOR, cs[i]);
      ObjectSetString(0, gl, OBJPROP_TOOLTIP, StatusText(st[i], ds[i], atr));
     }
   else if(ObjectFind(0, gl) >= 0) ObjectDelete(0, gl);

   if(!ShowPanel) { ChartRedraw(); return; }

   // ---- ตารางสถานะ ----
   ClearObjects(PREFIX + "P");
   int row = 0;
   SetLabel(PREFIX + "P_h0", row++, StringFormat("MADE Zones  %s  Bid %s  Ask %s  Spread %d pts  ATR(%s) %s",
            _Symbol, DoubleToString(bid, _Digits), DoubleToString(ask, _Digits),
            (int)MathRound((ask - bid) / _Point), EnumToString(AtrTf), DoubleToString(atr, _Digits)), clrWhite, true);

   if(UseRuleFilter && atr > 0)
     {
      double e20 = Buf(h_e20, 1), hf = Buf(h_h1f, 1), hs = Buf(h_h1s, 1);   // แท่งที่ปิดแล้ว
      if(e20 > 0 && hf > 0 && hs > 0)
        {
         int trend = (hf > hs) ? 1 : (hf < hs) ? -1 : 0;
         double dB = (ask - e20) / atr, dS = (e20 - bid) / atr;   // + = ไล่ราคาไปทางทิศนั้น
         string tr = (trend > 0) ? "UP" : (trend < 0) ? "DOWN" : "FLAT";
         SetLabel(PREFIX + "P_h1", row++, StringFormat("H1 trend %s | M15 EMA20 %s | price vs EMA20 %+.2f ATR",
                  tr, DoubleToString(e20, _Digits), (bid - e20) / atr), clrSilver);
         // BUY
         string vb; color cb;
         if(trend < 0 && dB > ChaseAtr)      { vb = "BUY : NO  - rule 1 (against H1 + chasing)"; cb = clrTomato; }
         else if(dB > PullbackAtr)           { vb = "BUY : WAIT - rule 2 limit at " + DoubleToString(e20 + PullbackAtr * atr, _Digits)
                                                 + StringFormat(" (%.2f away)", ask - (e20 + PullbackAtr * atr)); cb = clrOrange; }
         else                                { vb = (trend < 0) ? "BUY : OK by rules, but against H1 trend" : "BUY : OK by rules (near EMA20)"; cb = (trend < 0) ? clrKhaki : clrLimeGreen; }
         SetLabel(PREFIX + "P_rb", row++, vb, cb);
         // SELL
         string vs; color cv;
         if(trend > 0 && dS > ChaseAtr)      { vs = "SELL: NO  - rule 1 (against H1 + chasing)"; cv = clrTomato; }
         else if(dS > PullbackAtr)           { vs = "SELL: WAIT - rule 2 limit at " + DoubleToString(e20 - PullbackAtr * atr, _Digits)
                                                 + StringFormat(" (%.2f away)", (e20 - PullbackAtr * atr) - bid); cv = clrOrange; }
         else                                { vs = (trend > 0) ? "SELL: OK by rules, but against H1 trend" : "SELL: OK by rules (near EMA20)"; cv = (trend > 0) ? clrKhaki : clrLimeGreen; }
         SetLabel(PREFIX + "P_rs", row++, vs, cv);
        }
     }

   if(g_n == 0)
      SetLabel(PREFIX + "P_none", row++, "No zones for " + _Symbol + " in " + FileName, clrSilver);
   for(int k = 0; k < g_n; k++)
     {
      int i = ord[k];
      string line = StringFormat("%-6s %-4s %-9s %s-%s  %s", st[i], g_side[i], g_kind[i],
                                 DoubleToString(g_low[i], _Digits), DoubleToString(g_high[i], _Digits),
                                 StatusText(st[i], ds[i], atr));
      SetLabel(PREFIX + "P_z" + IntegerToString(k), row++, line, cs[i], st[i] == "ENTRY");
     }
   SetLabel(PREFIX + "P_ft", row++, "BUY zones use Ask, SELL zones use Bid | updated " + TimeToString(TimeLocal(), TIME_SECONDS), clrDimGray);
   ChartRedraw();
  }
//+------------------------------------------------------------------+
