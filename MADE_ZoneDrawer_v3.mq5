//+------------------------------------------------------------------+
//|                                              MADE_ZoneDrawer.mq5 |
//|  วาดโซนรอเข้าเทรดที่คำนวณจาก MADE (Python) ลงบนกราฟ MT5           |
//|  v2.00 : เพิ่มตัวบอกสถานะสด จากราคา Bid/Ask เทียบกับแต่ละโซน       |
//|  v2.10 : เส้นรอเข้าเป็นเส้นประสีตามฝั่งโซน, เส้น Limit กฎข้อ 2,      |
//|  v3.00 : ตัวกรองเทรนด์เลือกได้ (H4 EMA20 ชัน / H1 EMA20-50 / ทั้งคู่) |
//|          สถานะ UNCLEAR เมื่อ H4 กับ H1 ไม่ตรงกัน                     |
//|          เส้น Bid/Ask realtime พร้อมระยะถึงจุดเข้า BUY/SELL เป็น ATR  |
//|          ค่าอยู่บนเส้น อัปเดตทุก tick                                |
//|  v3.01 : สีตัวหนังสือบนเส้น Bid/Ask ปรับได้ (ค่าเริ่มต้นสีขาว)        |
//|          Alert เปิด/ปิดได้ทั้งใน Inputs และปุ่มบนกราฟ                |
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
#property version   "3.01"
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
input bool   DrawGuideLine   = true;              // เส้นประจากราคาปัจจุบันไปโซนที่ใกล้สุด (สีตามฝั่งโซน)
input int    GuideWidth      = 1;                 // ความหนาเส้นประ

input group  "กฎจากการวิเคราะห์ประวัติเทรด"
input bool   UseRuleFilter   = true;              // แสดงคำเตือนกฎข้อ 1-2

enum ENUM_TREND_MODE
  {
   TREND_H4_SLOPE = 0,   // H4 EMA20 ชันขึ้น/ลง
   TREND_H1_2050  = 1,   // H1 EMA20 เทียบ EMA50 (แบบ v2)
   TREND_BOTH     = 2    // ทั้งคู่ต้องตรงกัน ไม่ตรง = UNCLEAR (แนะนำ)
  };
input ENUM_TREND_MODE TrendMode = TREND_BOTH;     // ตัวกรองเทรนด์
input int    H4SlopeBars     = 3;                 // ความชัน H4 EMA20 เทียบกับกี่แท่ง H4 ก่อน
input double ChaseAtr        = 0.5;               // กฎ 1: สวนเทรนด์ H1 และห่าง EMA20 เกินนี้ = ห้ามเข้า
input double PullbackAtr     = 0.3;               // กฎ 2: ตามเทรนด์แต่ห่างเกินนี้ = รอ Limit ที่ EMA20 +/- ค่านี้
input bool   DrawLimitLine   = true;              // วาดเส้นประแนวนอนที่ราคา Limit ของกฎ 2 (สี BUY/SELL)

input group  "Alert (เปิด/ปิดได้ที่ปุ่มบนกราฟด้วย)"
input bool   EnableAlerts    = false;             // เปิด Alert ตอนเริ่ม
input bool   AlertOnNear     = true;              // แจ้งเมื่อโซนเปลี่ยนเป็น NEAR
input bool   AlertOnEntry    = true;              // แจ้งเมื่อราคาเข้าโซน (ENTRY)
input bool   AlertOnSwept    = true;              // แจ้งเมื่อกวาดแนว PDH/PDL (SWEPT)
input bool   AlertOnMissed   = false;             // แจ้งเมื่อเลยจุดเข้าไปแล้ว (MISSED)
input bool   AlertOnBroken   = false;             // แจ้งเมื่อโซนเสีย (BROKEN)
input bool   AlertOnRuleOK   = true;              // แจ้งเมื่อ BUY/SELL ผ่านกฎ (เช่น ราคาย่อถึงเส้น Limit)
input bool   AlertPopup      = true;              // หน้าต่าง Alert ใน MT5
input bool   AlertPush       = false;             // ส่ง Push ไปมือถือ (ตั้ง MetaQuotes ID ใน Tools > Options > Notifications)
input bool   AlertSound      = false;             // เล่นเสียงอย่างเดียว (ใช้แทน popup ได้)
input string AlertSoundFile  = "alert.wav";       // ไฟล์เสียงในโฟลเดอร์ Sounds ของ MT5
input int    AlertCooldownSec = 300;              // แจ้งซ้ำของโซนเดิมได้หลังกี่วินาที

input group  "เส้น Bid/Ask realtime"
input bool   ShowRtLines     = true;              // แสดงเส้น Bid/Ask พร้อมระยะถึงจุดเข้า
input ENUM_LINE_STYLE RtStyle = STYLE_SOLID;      // รูปแบบเส้น (เส้นรอเข้าเป็นเส้นประ)
input int    RtFontSize      = 9;                 // ขนาดตัวอักษรบนเส้น
input color  RtAskTextColor  = clrWhite;          // สีตัวหนังสือบนเส้น Ask
input color  RtBidTextColor  = clrWhite;          // สีตัวหนังสือบนเส้น Bid

#define PREFIX "MADE_"
#define MAXZ   64

// ---- โซนที่อ่านจากไฟล์ ----
int     g_n = 0;
string  g_kind[MAXZ], g_side[MAXZ], g_str[MAXZ], g_trig[MAXZ];
double  g_low[MAXZ], g_high[MAXZ], g_fdist[MAXZ];

int     h_atr = INVALID_HANDLE, h_e20 = INVALID_HANDLE, h_h1f = INVALID_HANDLE, h_h1s = INVALID_HANDLE, h_h4 = INVALID_HANDLE;

// ---- ค่าที่คำนวณรอบล่าสุด ให้เส้น realtime ใช้ทุก tick ----
string  g_stZ[MAXZ];
string  g_stB = "", g_stS = "";
double  g_limB = 0, g_limS = 0, g_e20 = 0;
int     g_trend = 0;
ulong   g_lastLiveMs = 0;

// ---- สถานะ Alert ----
bool     g_alertsOn = false;
#define  MAXA 256
int      g_an = 0;
string   g_akey[MAXA], g_ast[MAXA];
datetime g_at[MAXA];
#define  BTN "MADE_btnAlert"

//+------------------------------------------------------------------+
int OnInit()
  {
   h_atr = iATR(_Symbol, AtrTf, AtrPeriod);
   h_e20 = iMA(_Symbol, PERIOD_M15, 20, 0, MODE_EMA, PRICE_CLOSE);
   h_h1f = iMA(_Symbol, PERIOD_H1, 20, 0, MODE_EMA, PRICE_CLOSE);
   h_h1s = iMA(_Symbol, PERIOD_H1, 50, 0, MODE_EMA, PRICE_CLOSE);
   h_h4  = iMA(_Symbol, PERIOD_H4, 20, 0, MODE_EMA, PRICE_CLOSE);
   g_alertsOn = EnableAlerts;
   DrawAlertButton();
   EventSetTimer(MathMax(1, RefreshSeconds));
   LoadAndDraw();
   UpdateLive();
   UpdateLines();
   return(INIT_SUCCEEDED);
  }
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   EventKillTimer();
   ClearObjects(PREFIX);
   ObjectDelete(0, BTN);
   Comment("");
   for(int i = 0; i < 5; i++)
     {
      int h = (i == 0 ? h_atr : i == 1 ? h_e20 : i == 2 ? h_h1f : i == 3 ? h_h1s : h_h4);
      if(h != INVALID_HANDLE) IndicatorRelease(h);
     }
   ChartRedraw();
  }
//+------------------------------------------------------------------+
void OnChartEvent(const int id, const long &lparam, const double &dparam, const string &sparam)
  {
   if(id == CHARTEVENT_CHART_CHANGE) { UpdateLines(); ChartRedraw(); return; }
   if(id == CHARTEVENT_OBJECT_CLICK && sparam == BTN)
     {
      g_alertsOn = !g_alertsOn;
      ObjectSetInteger(0, BTN, OBJPROP_STATE, false);
      DrawAlertButton();
      ChartRedraw();
     }
  }
//+------------------------------------------------------------------+
void DrawAlertButton()
  {
   if(ObjectFind(0, BTN) < 0)
     {
      ObjectCreate(0, BTN, OBJ_BUTTON, 0, 0, 0);
      ObjectSetInteger(0, BTN, OBJPROP_CORNER, CORNER_RIGHT_UPPER);
      ObjectSetInteger(0, BTN, OBJPROP_XDISTANCE, 120);
      ObjectSetInteger(0, BTN, OBJPROP_YDISTANCE, 24);
      ObjectSetInteger(0, BTN, OBJPROP_XSIZE, 110);
      ObjectSetInteger(0, BTN, OBJPROP_YSIZE, 22);
      ObjectSetInteger(0, BTN, OBJPROP_FONTSIZE, 9);
      ObjectSetString(0, BTN, OBJPROP_FONT, "Consolas");
      ObjectSetInteger(0, BTN, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, BTN, OBJPROP_HIDDEN, true);
     }
   ObjectSetString(0, BTN, OBJPROP_TEXT, g_alertsOn ? "Alerts: ON" : "Alerts: OFF");
   ObjectSetInteger(0, BTN, OBJPROP_BGCOLOR, g_alertsOn ? clrSeaGreen : clrDimGray);
   ObjectSetInteger(0, BTN, OBJPROP_COLOR, clrWhite);
   ObjectSetInteger(0, BTN, OBJPROP_STATE, false);
  }
//+------------------------------------------------------------------+
//| จำสถานะล่าสุดของแต่ละ key แล้วแจ้งเมื่อเปลี่ยนเป็นสถานะที่เปิดไว้      |
//| ครั้งแรกที่เห็น key จะจำไว้เฉย ๆ ไม่แจ้ง (กันแจ้งรัวตอนเปิด EA)      |
//+------------------------------------------------------------------+
void CheckAlert(const string key, const string status, const bool wanted, const string msg)
  {
   int k = -1;
   for(int i = 0; i < g_an; i++) if(g_akey[i] == key) { k = i; break; }
   if(k < 0)
     {
      if(g_an >= MAXA) { g_an = 0; }                  // เต็มแล้ว เริ่มจำใหม่
      g_akey[g_an] = key; g_ast[g_an] = status; g_at[g_an] = 0; g_an++;
      return;
     }
   if(g_ast[k] == status) return;
   g_ast[k] = status;
   if(!g_alertsOn || !wanted) return;
   if(TimeCurrent() - g_at[k] < AlertCooldownSec) return;
   g_at[k] = TimeCurrent();
   string text = "MADE " + _Symbol + " | " + msg;
   if(AlertPopup) Alert(text);
   else if(AlertSound) PlaySound(AlertSoundFile);
   if(AlertPush) SendNotification(text);
   Print(text);
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
   UpdateLines();                               // เส้น Bid/Ask อัปเดตทุก tick
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
      ds[i] = dd; cs[i] = cc; g_stZ[i] = st[i];
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

   // ---- Alert ของโซน ----
   for(int i = 0; i < g_n; i++)
     {
      string key = g_side[i] + "|" + g_kind[i] + "|" + DoubleToString(g_low[i], _Digits) + "|" + DoubleToString(g_high[i], _Digits);
      bool want = (st[i] == "NEAR" && AlertOnNear) || (st[i] == "ENTRY" && AlertOnEntry) || (st[i] == "SWEPT" && AlertOnSwept)
                  || (st[i] == "MISSED" && AlertOnMissed) || (st[i] == "BROKEN" && AlertOnBroken);
      CheckAlert(key, st[i], want, StringFormat("%s %s %s-%s : %s", g_side[i], g_kind[i],
                 DoubleToString(g_low[i], _Digits), DoubleToString(g_high[i], _Digits), StatusText(st[i], ds[i], atr)));
     }

   // ---- เส้นประไปโซนที่ใกล้ที่สุดที่ยังรอเข้าได้ (สีตามฝั่งโซน) ----
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
         ObjectSetInteger(0, gl, OBJPROP_RAY_RIGHT, false);
         ObjectSetInteger(0, gl, OBJPROP_SELECTABLE, false);
         ObjectSetInteger(0, gl, OBJPROP_HIDDEN, true);
        }
      ObjectMove(0, gl, 0, t, from);
      ObjectMove(0, gl, 1, t, to);
      ObjectSetInteger(0, gl, OBJPROP_STYLE, STYLE_DASH);
      ObjectSetInteger(0, gl, OBJPROP_WIDTH, GuideWidth);
      ObjectSetInteger(0, gl, OBJPROP_COLOR, isBuy ? BuyColor : SellColor);
      ObjectSetString(0, gl, OBJPROP_TOOLTIP, StatusText(st[i], ds[i], atr));
     }
   else if(ObjectFind(0, gl) >= 0) ObjectDelete(0, gl);

   // ---- เทรนด์ + กฎข้อ 1-2 ----
   bool   haveRule = false;
   int    trend = 0, tH4 = 0, tH1 = 0;
   double e20 = 0, limB = 0, limS = 0;
   string vb = "", vs = "", stB = "", stS = "", trTxt = "";
   color  cb = clrSilver, cv = clrSilver;
   if(UseRuleFilter && atr > 0)
     {
      double hf = Buf(h_h1f, 1), hs = Buf(h_h1s, 1);
      double h4a = Buf(h_h4, 1), h4b = Buf(h_h4, 1 + MathMax(1, H4SlopeBars));
      e20 = Buf(h_e20, 1);                                   // ใช้แท่งที่ปิดแล้วทั้งหมด
      if(e20 > 0 && hf > 0 && hs > 0 && h4a > 0 && h4b > 0)
        {
         haveRule = true;
         tH1 = (hf > hs) ? 1 : (hf < hs) ? -1 : 0;
         tH4 = (h4a > h4b) ? 1 : (h4a < h4b) ? -1 : 0;
         if(TrendMode == TREND_H4_SLOPE)     trend = tH4;
         else if(TrendMode == TREND_H1_2050) trend = tH1;
         else                                trend = (tH4 == tH1) ? tH4 : 0;
         string n4 = (tH4 > 0) ? "UP" : (tH4 < 0) ? "DOWN" : "FLAT";
         string n1 = (tH1 > 0) ? "UP" : (tH1 < 0) ? "DOWN" : "FLAT";
         string nt = (trend > 0) ? "UP" : (trend < 0) ? "DOWN" : "UNCLEAR";
         trTxt = (TrendMode == TREND_H4_SLOPE) ? "Trend (H4 EMA20 slope) " + n4
               : (TrendMode == TREND_H1_2050)  ? "Trend (H1 EMA20/50) " + n1
               : "Trend H4 slope " + n4 + " + H1 20/50 " + n1 + " => " + nt;
         double dB = (ask - e20) / atr, dS = (e20 - bid) / atr;   // + = ไล่ราคาไปทางทิศนั้น
         limB = e20 + PullbackAtr * atr; limS = e20 - PullbackAtr * atr;
         // BUY
         if(trend == 0 && TrendMode == TREND_BOTH)
           {
            if(dB > ChaseAtr) { stB = "NO";      vb = "BUY : NO  - trend unclear + chasing"; cb = clrTomato; }
            else              { stB = "UNCLEAR"; vb = "BUY : UNCLEAR - H4/H1 disagree: reduce lot or skip"; cb = clrGoldenrod; }
           }
         else if(trend < 0 && dB > ChaseAtr) { stB = "NO";   vb = "BUY : NO  - rule 1 (against trend + chasing)"; cb = clrTomato; }
         else if(dB > PullbackAtr)           { stB = "WAIT"; vb = "BUY : WAIT - rule 2 limit at " + DoubleToString(limB, _Digits)
                                                 + StringFormat(" (%.2f away)", ask - limB); cb = clrOrange; }
         else                                { stB = "OK";   vb = (trend < 0) ? "BUY : OK by rules, but against trend" : "BUY : OK by rules (near EMA20)"; cb = (trend < 0) ? clrKhaki : clrLimeGreen; }
         // SELL
         if(trend == 0 && TrendMode == TREND_BOTH)
           {
            if(dS > ChaseAtr) { stS = "NO";      vs = "SELL: NO  - trend unclear + chasing"; cv = clrTomato; }
            else              { stS = "UNCLEAR"; vs = "SELL: UNCLEAR - H4/H1 disagree: reduce lot or skip"; cv = clrGoldenrod; }
           }
         else if(trend > 0 && dS > ChaseAtr) { stS = "NO";   vs = "SELL: NO  - rule 1 (against trend + chasing)"; cv = clrTomato; }
         else if(dS > PullbackAtr)           { stS = "WAIT"; vs = "SELL: WAIT - rule 2 limit at " + DoubleToString(limS, _Digits)
                                                 + StringFormat(" (%.2f away)", bid - limS); cv = clrOrange; }
         else                                { stS = "OK";   vs = (trend > 0) ? "SELL: OK by rules, but against trend" : "SELL: OK by rules (near EMA20)"; cv = (trend > 0) ? clrKhaki : clrLimeGreen; }
         CheckAlert("RULE|BUY", stB, AlertOnRuleOK && stB == "OK", vb + " | Ask " + DoubleToString(ask, _Digits));
         CheckAlert("RULE|SELL", stS, AlertOnRuleOK && stS == "OK", vs + " | Bid " + DoubleToString(bid, _Digits));
        }
     }
   g_stB = stB; g_stS = stS; g_limB = limB; g_limS = limS; g_e20 = e20; g_trend = trend;

   // ---- เส้นประ Limit ของกฎข้อ 2 (แสดงเฉพาะตอนที่ต้องรอ) ----
   for(int s2 = 0; s2 < 2; s2++)
     {
      bool isBuy = (s2 == 0);
      string ln = PREFIX + (isBuy ? "limBuy" : "limSell");
      bool show = DrawLimitLine && haveRule && (isBuy ? stB == "WAIT" : stS == "WAIT");
      if(!show) { if(ObjectFind(0, ln) >= 0) ObjectDelete(0, ln); continue; }
      double px = isBuy ? limB : limS;
      if(ObjectFind(0, ln) < 0)
        {
         ObjectCreate(0, ln, OBJ_HLINE, 0, 0, px);
         ObjectSetInteger(0, ln, OBJPROP_SELECTABLE, false);
         ObjectSetInteger(0, ln, OBJPROP_HIDDEN, true);
         ObjectSetInteger(0, ln, OBJPROP_BACK, true);
        }
      ObjectSetDouble(0, ln, OBJPROP_PRICE, px);
      ObjectSetInteger(0, ln, OBJPROP_STYLE, STYLE_DASH);
      ObjectSetInteger(0, ln, OBJPROP_WIDTH, GuideWidth);
      ObjectSetInteger(0, ln, OBJPROP_COLOR, isBuy ? BuyColor : SellColor);
      ObjectSetString(0, ln, OBJPROP_TOOLTIP, (isBuy ? "BUY" : "SELL") + string(" wait: rule 2 limit ") + DoubleToString(px, _Digits));
     }

   if(!ShowPanel) { ChartRedraw(); return; }

   // ---- ตารางสถานะ ----
   ClearObjects(PREFIX + "P");
   int row = 0;
   SetLabel(PREFIX + "P_h0", row++, StringFormat("MADE Zones  %s  Bid %s  Ask %s  Spread %d pts  ATR(%s) %s",
            _Symbol, DoubleToString(bid, _Digits), DoubleToString(ask, _Digits),
            (int)MathRound((ask - bid) / _Point), EnumToString(AtrTf), DoubleToString(atr, _Digits)), clrWhite, true);
   if(haveRule)
     {
      SetLabel(PREFIX + "P_h1", row++, trTxt, trend == 0 ? clrGoldenrod : clrSilver);
      SetLabel(PREFIX + "P_h2", row++, StringFormat("M15 EMA20 %s | price vs EMA20 %+.2f ATR",
               DoubleToString(e20, _Digits), (bid - e20) / atr), clrSilver);
      SetLabel(PREFIX + "P_rb", row++, vb, cb);
      SetLabel(PREFIX + "P_rs", row++, vs, cv);
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
   SetLabel(PREFIX + "P_ft", row++, "BUY zones use Ask, SELL zones use Bid | alerts " + (g_alertsOn ? "ON" : "OFF")
            + " | updated " + TimeToString(TimeLocal(), TIME_SECONDS), clrDimGray);
   ChartRedraw();
  }
//+------------------------------------------------------------------+
//+------------------------------------------------------------------+
//| เส้น Bid/Ask realtime: ระยะจากราคาที่เข้าได้จริงถึงจุดเข้าที่ใกล้สุด   |
//| BUY ใช้ Ask วัดถึงโซน BUY ที่ยังรอได้ (ENTRY/NEAR/WAIT) หรือ Limit กฎ 2 |
//| SELL ใช้ Bid วัดถึงโซน SELL ที่ยังรอได้ หรือ Limit กฎ 2                |
//+------------------------------------------------------------------+
string RtText(const bool isBuy, const double px, const double atr)
  {
   string side = isBuy ? "BUY" : "SELL";
   string head = (isBuy ? "ASK " : "BID ") + DoubleToString(px, _Digits);
   double best = -1, bestPx = 0; string bestName = "";
   for(int i = 0; i < g_n; i++)
     {
      if(g_side[i] != side) continue;
      if(g_stZ[i] != "ENTRY" && g_stZ[i] != "NEAR" && g_stZ[i] != "WAIT") continue;
      double d, edge = isBuy ? g_high[i] : g_low[i];
      if(px >= g_low[i] && px <= g_high[i]) d = 0;
      else d = isBuy ? px - g_high[i] : g_low[i] - px;
      if(d < 0) continue;
      if(best < 0 || d < best) { best = d; bestPx = edge; bestName = g_kind[i]; }
     }
   string st = isBuy ? g_stB : g_stS;
   if(st == "WAIT")
     {
      double lim = isBuy ? g_limB : g_limS;
      double d = isBuy ? px - lim : lim - px;
      if(d >= 0 && (best < 0 || d < best)) { best = d; bestPx = lim; bestName = "rule2 limit"; }
     }
   string tgt;
   if(best < 0)       tgt = "no " + side + " entry pending";
   else if(best == 0) tgt = "IN " + side + " ZONE " + bestName;
   else               tgt = StringFormat("%s %s %s: %s = %s ATR", side, bestName, DoubleToString(bestPx, _Digits),
                                         DoubleToString(best, _Digits), atr > 0 ? DoubleToString(best / atr, 2) : "-");
   string ema = (g_e20 > 0 && atr > 0) ? StringFormat(" | EMA20 %+.2f ATR", (px - g_e20) / atr) : "";
   string rule = (st != "") ? " | rule " + st : "";
   return head + " | " + tgt + ema + rule;
  }
//+------------------------------------------------------------------+
void RtLine(const string nm, const double px, const color col, const color tcol, const string text, const bool above)
  {
   if(ObjectFind(0, nm) < 0)
     {
      ObjectCreate(0, nm, OBJ_HLINE, 0, 0, px);
      ObjectSetInteger(0, nm, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, nm, OBJPROP_HIDDEN, true);
      ObjectSetInteger(0, nm, OBJPROP_BACK, false);
     }
   ObjectSetDouble(0, nm, OBJPROP_PRICE, px);
   ObjectSetInteger(0, nm, OBJPROP_COLOR, col);
   ObjectSetInteger(0, nm, OBJPROP_STYLE, RtStyle);
   ObjectSetInteger(0, nm, OBJPROP_WIDTH, 1);
   ObjectSetString(0, nm, OBJPROP_TOOLTIP, text);
   // ข้อความวางบนเส้นด้วยพิกัดจอ จึงเห็นเสมอแม้ไม่ได้เปิด chart shift
   string tx = nm + "T";
   int x = 0, y = 0;
   if(!ChartTimePriceToXY(0, 0, TimeCurrent(), px, x, y)) return;
   int w = (int)ChartGetInteger(0, CHART_WIDTH_IN_PIXELS);
   if(ObjectFind(0, tx) < 0)
     {
      ObjectCreate(0, tx, OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(0, tx, OBJPROP_CORNER, CORNER_LEFT_UPPER);
      ObjectSetInteger(0, tx, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, tx, OBJPROP_HIDDEN, true);
      ObjectSetString(0, tx, OBJPROP_FONT, "Consolas");
     }
   ObjectSetInteger(0, tx, OBJPROP_FONTSIZE, RtFontSize);
   ObjectSetInteger(0, tx, OBJPROP_ANCHOR, above ? ANCHOR_RIGHT_LOWER : ANCHOR_RIGHT_UPPER);
   ObjectSetInteger(0, tx, OBJPROP_XDISTANCE, MathMax(10, w - 70));
   ObjectSetInteger(0, tx, OBJPROP_YDISTANCE, above ? y - 1 : y + 1);
   ObjectSetInteger(0, tx, OBJPROP_COLOR, tcol);
   ObjectSetString(0, tx, OBJPROP_TEXT, text);
  }
//+------------------------------------------------------------------+
void UpdateLines()
  {
   if(!ShowRtLines)
     {
      ObjectDelete(0, PREFIX + "rtAsk"); ObjectDelete(0, PREFIX + "rtAskT");
      ObjectDelete(0, PREFIX + "rtBid"); ObjectDelete(0, PREFIX + "rtBidT");
      return;
     }
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   if(bid <= 0 || ask <= 0) return;
   double atr = Buf(h_atr, 0);
   RtLine(PREFIX + "rtAsk", ask, BuyColor,  RtAskTextColor, RtText(true,  ask, atr), true);    // ข้อความ Ask อยู่เหนือเส้น
   RtLine(PREFIX + "rtBid", bid, SellColor, RtBidTextColor, RtText(false, bid, atr), false);   // ข้อความ Bid อยู่ใต้เส้น
   ChartRedraw();
  }
//+------------------------------------------------------------------+
