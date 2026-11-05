# MADE — Multi-Asset Decision Engine

ระบบสนับสนุนการตัดสินใจเทรดหลายสินทรัพย์
ไม่ส่งคำสั่งเทรด ทำหน้าที่วิเคราะห์และเสนอแนะอย่างเดียว

## ไฟล์ในระบบ

| ไฟล์ | หน้าที่ | จำเป็น |
|---|---|---|
| `made_gui.py` | Dashboard — รันไฟล์นี้ | ✅ |
| `multi_asset_decision_engine.py` | เครื่องวิเคราะห์ (regime, ranking, zone, lot) | ✅ |
| `webull_market.py` | บริบทตลาดจาก Webull (breadth, sector, cross-asset) | ไม่บังคับ |
| `webull_config.json` | key ของ Webull — **ห้ามแชร์** | คู่กับตัวบน |
| `news_calendar.py` | ข่าว + ปฏิทินเศรษฐกิจ/งบ (ฟรี) | ไม่บังคับ |
| `MADE_ZoneDrawer.mq5` | EA วาดโซนบนกราฟ MT5 (วางใน MQL5\Experts) | ไม่บังคับ |

## ติดตั้งบนเครื่องใหม่ (ผ่าน GitHub)

ต้องมี Windows, Python 3.10–3.12 (ติ๊ก "Add to PATH" และ "tcl/tk"), Git และ MT5

```cmd
git clone https://github.com/<user>/<repo>.git
cd <repo>
SETUP.bat
```

`SETUP.bat` จะสร้าง `.venv`, ติดตั้งไลบรารีจาก `requirements.txt` และสร้าง
`webull_config.json` จากแม่แบบ ให้เปิดแล้วใส่ key ของ Webull เอง
(ไฟล์นี้ถูก gitignore ไม่ขึ้น repo) จากนั้นดับเบิลคลิก `MADE.bat`

อัปเดตเวอร์ชันบนเครื่องอื่น: `git pull`

ตรวจระบบ: `CHECK.bat`

## วิธีรัน

```cmd
MADE.bat
```

หรือรันตรง ๆ: `python made_gui.py`

เงื่อนไข: เปิด MT5 ค้างไว้ login แล้ว และเปิด symbol ครบ 6 ตัวใน Market Watch
(GOLDm#, USDX-DEC26, BRENTCash#, US30Cash#, US100Cash#, US500Cash#)

## แก้ปัญหา

| อาการ | สาเหตุ / วิธีแก้ |
|---|---|
| แท็บว่าง | ดูข้อความในแท็บนั้น จะบอก path ที่ระบบไปหาไฟล์ |
| "engine เป็นเวอร์ชันเก่า" | คัดลอก multi_asset_decision_engine.py ตัวล่าสุดมาทับ |
| แท็บกราฟว่าง | engine เก่า (ไม่มี CFG['chart_bars']) |
| Webull ขึ้น TOO_MANY_REQUESTS | เพิ่มรอบอัปเดตเป็น 30 นาที หรือ set WEBULL_MIN_INTERVAL=0.6 |
| webull_data_sdk.log โตเร็ว | เวอร์ชันใหม่ปิด log ของ SDK แล้ว ถ้ายังโตให้ล้างไฟล์ทิ้ง |

## ตัวแปรปรับได้ (environment variable)

```cmd
set WEBULL_MIN_INTERVAL=0.6     หน่วงระหว่าง request (วินาที)
set WEBULL_MAX_REQUESTS=90      งบ request ต่อรอบ
set DOW_DIVISOR=0.1627          ตัวหารดัชนี Dow
```

## ข้อควรทราบ

- เครื่องมือนี้เป็นข้อมูลประกอบการตัดสินใจ **ไม่ใช่คำแนะนำการลงทุน**
- โซนทั้งหมดต้องรอแท่งยืนยันก่อนเข้าเสมอ การเข้าทันทีที่ราคาแตะโซนคือการเดา
- lot ที่ระบบคำนวณจะถูก VETO ถ้าความเสี่ยงเกินงบที่ตั้งไว้

## บันทึกการแก้ 14 ต.ค. — ลดจำนวน request ของ Webull

`webull_market.py` เปลี่ยนจาก `get_history_bar` (ตัวละ 1 request) มาใช้
`get_batch_history_bar` (ก้อนละ 50 ตัว) ตาม sample ของ SDK ที่ระบุว่า
endpoint เดิม `/market-data/stocks/bars/get` ปิดไปแล้ว

| | ก่อน | หลัง |
|---|---|---|
| 55 symbol ต่อรอบ | 55 request | 2 request |
| กรณีไม่ได้สมัคร market data | 3 request จึงหยุด | 1 request |
| ทางสำรองตัวที่ batch ไม่คืนมา | — | ไม่เกิน 6 ตัว |

ค่าคงที่ปรับได้ที่หัวคลาส `Webull`: `BATCH_MAX`, `BAR_COUNT`, `FALLBACK_MAX`
