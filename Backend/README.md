# Drone SOS Backend

Backend ของโดรนกระจายสัญญาณ: เก็บข้อมูลการทำงานของโดรน + ค่าจาก sensor + สถานะ router
แล้วตรวจ **ระบบ SOS** (แบต / ใบพัด / อุณหภูมิ / router) เก็บลง **Amazon DynamoDB** และส่งให้ **Frontend**

```
User ──> QGroundControl ──> Drone ──> Backend (โค้ดนี้, Raspberry Pi 4) ──> Frontend (เว็บ)
                              │         ├─ อ่านค่าโดรน + sensor + router   (telemetry.py)
                              │         ├─ ระบบ SOS                          (alerts.py)
                              │         ├─ เก็บข้อมูล DynamoDB / SQLite      (storage.py)
                              │         └─ API: Socket.IO + REST             (app.py)
                              └──> กระจายสัญญาณ (router)
```

Backend **อ่านข้อมูลอย่างเดียว** ไม่สั่งโดรน การสั่ง RTL/Land ทำผ่าน QGC (`safe_mode: true` เป็นคำแนะนำ)

## ไฟล์

| ไฟล์ | หน้าที่ |
|---|---|
| `app.py` | ตัวหลัก: อ่านค่า → ตรวจ SOS → บันทึก DB → ส่ง Frontend |
| `console.py` | รัน backend เหมือน `app.py` + แสดงค่าแบบ real-time ใน Terminal |
| `alerts.py` | ระบบ SOS (กฎทั้งหมดอยู่ที่นี่) |
| `telemetry.py` | อ่านค่า: `MockSource` (จำลอง) / `MavlinkSource` (โดรนจริง) |
| `simulator.py` | โดรนจำลอง ใช้ตอนยังไม่ได้ต่อโดรน |
| `storage.py` | บันทึกลง SQLite (ทดสอบ) หรือ DynamoDB |
| `setup_aws.py` | สร้างตาราง DynamoDB (รันครั้งเดียว) |
| `config.py` / `.env.example` | ค่าตั้งค่าและเกณฑ์ SOS ทั้งหมด |

## ติดตั้ง (Raspberry Pi 4)

```bash
sudo apt install python3-venv python3-dev gcc
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## รัน

```bash
python console.py                      # ดูค่าใน Terminal (ใช้ค่าจำลอง)
python console.py --scenario motor     # ทดสอบใบพัด/มอเตอร์เสีย
python console.py --source mavlink     # ค่าจริงจากโดรน
python app.py                          # รันแบบไม่มีหน้าจอ (ใช้ตอนติดตั้งจริง)
```
scenario: `normal`, `random`, `lowbat`, `linkloss`, `motor`, `overheat`, `router`

### ต่อโดรนจริง (เลือกแบบใดแบบหนึ่งใน `.env`)

- **Pi ต่อสายกับ flight controller** (Pi อยู่บนโดรน): เปิด UART ด้วย `sudo raspi-config` แล้วตั้ง
  `MAVLINK_URL=/dev/serial0` และ `MAVLINK_BAUD` ให้ตรงกับ FC (ArduPilot: `SERIALx_PROTOCOL=2`, `SERIALx_BAUD`)
- **รับจาก QGroundControl**: QGC → Application Settings → MAVLink → เปิด MAVLink forwarding ไปที่ `<IP ของ Pi>:14445`
  แล้วตั้ง `MAVLINK_URL=udpin:0.0.0.0:14445`

แล้วตั้ง `DATA_SOURCE=mavlink`

## ระบบ SOS

ระดับ: `NORMAL` < `WARNING` < `CRITICAL` (safe_mode) < `SOS`  ปรับเกณฑ์ได้ใน `.env`

| หมวด | code | ระดับ | เงื่อนไข |
|---|---|---|---|
| **battery** | `BATTERY` | WARNING / CRITICAL / SOS | ≤ 30% / ≤ 20% / ≤ 10% |
| **propeller** | `MOTOR_STOPPED` | SOS | มอเตอร์ rpm = 0 ขณะตัวอื่นหมุน (ต้องมี ESC telemetry) |
| | `MOTOR_IMBALANCE` | CRITICAL | คำสั่งมอเตอร์ต่างกันเกิน 35% (FC กำลังชดเชยใบพัดที่มีปัญหา) |
| **temperature** | `TEMP_MOTOR` | WARNING / CRITICAL | ≥ 80 / ≥ 100 °C |
| | `TEMP_BATTERY` | WARNING / CRITICAL | ≥ 45 / ≥ 55 °C |
| | `TEMP_BOARD` | WARNING / CRITICAL | ≥ 60 / ≥ 75 °C |
| | `TEMP_PI_CPU` | WARNING / CRITICAL | ≥ 70 / ≥ 80 °C |
| | `TEMP_ROUTER` | WARNING / CRITICAL | ≥ 70 / ≥ 85 °C |
| **router** | `ROUTER_OFFLINE` | CRITICAL (บิน) / WARNING (พื้น) | router ไม่ทำงาน |
| **connection** | `LINK_LOST` | SOS | ไม่มี heartbeat จากโดรนเกิน 5 วินาที |
| | `SIGNAL` | WARNING / CRITICAL | สัญญาณควบคุม < 40% / < 20% |
| | `NO_DATA` | WARNING | ยังไม่เคยได้รับข้อมูล |
| **flight** | `FREEFALL` | SOS | ร่วงเร็วกว่า 5 m/s |
| | `SYSTEM` | CRITICAL / SOS | autopilot แจ้ง CRITICAL / EMERGENCY |
| | `SENSOR` / `AUTOPILOT_MSG` | CRITICAL | เซนเซอร์ใน FC เสีย / ข้อความเตือนจาก autopilot |
| | `GPS` | WARNING | ดาวเทียม < 6 หรือไม่มี 3D fix |

alert ค้างไว้ 5 วินาทีหลังเงื่อนไขหาย (`ALERT_HOLD`) กันแจ้งเตือนรัว

**ค่ามาจากไหน (โดรนจริง)**

| ค่า | MAVLink message |
|---|---|
| แบต, แรงดัน, กระแส, เซนเซอร์เสีย | `SYS_STATUS` |
| อุณหภูมิแบต | `BATTERY_STATUS` |
| อุณหภูมิบอร์ด FC | `SCALED_PRESSURE` |
| คำสั่งมอเตอร์ (%) | `SERVO_OUTPUT_RAW` |
| rpm + อุณหภูมิมอเตอร์ | `ESC_TELEMETRY_1_TO_4` (เฉพาะ ESC ที่ส่ง telemetry ได้ เช่น BLHeli32/DShot) |
| อุณหภูมิ Pi | `/sys/class/thermal/thermal_zone0/temp` (อ่านจาก Pi โดยตรง) |
| router | **ยังเป็นค่าจำลอง**: ใส่โค้ดอ่านของจริงที่ `read_router_status()` ใน `telemetry.py` |

## เก็บลง Amazon DynamoDB

1. สร้าง IAM user สิทธิ์ `dynamodb:CreateTable, DescribeTable, UpdateTimeToLive, PutItem, Query`
2. `aws configure` หรือใส่ key ใน `.env` (**ห้าม commit `.env`**)
3. `python setup_aws.py` สร้างตาราง `drone_telemetry` และ `drone_alerts`
4. ตั้ง `STORAGE=dynamodb`

key: `drone_id` (partition) + `ts` (sort, ISO-8601 UTC) ข้อมูลบันทึกทุก 2 วินาที (`STORE_INTERVAL`)
ลบอัตโนมัติหลัง 30 วัน (`DDB_TTL_DAYS`) ส่วน alert บันทึกเฉพาะตอนเกิด/หาย

## API สำหรับ Frontend

Socket.IO ที่ `http://<IP ของ Pi>:5000`

```js
const socket = io("http://192.168.1.10:5000");
socket.on("drone_data", d => { /* ทุก 1 วินาที */ });
socket.on("drone_alert", e => { /* alert เกิด (RAISED) / หาย (RESOLVED) */ });
```

**`drone_data`**
```jsonc
{
  "drone_id": "relay-drone-01", "source": "mavlink",
  "timestamp": "2026-09-22T18:30:36.271+00:00", "time": "01:30:36",
  "connected": true, "heartbeat_age": 0.3,
  "armed": true, "flight_mode": "AUTO", "system_status": "ACTIVE",
  "battery": 72, "voltage": 15.8, "current": 16.0,
  "gps": 12, "gps_fix": 3, "lat": 13.7563, "lon": 100.5018,
  "altitude": 80.0, "speed": 8.0, "climb": 0.0, "heading": 90, "signal": 95,
  "motors": [
    { "id": 1, "rpm": 9800, "output": 55, "temperature_c": 55 },
    { "id": 3, "rpm": 0, "output": 100, "temperature_c": 88 }  // ...ครบ 4 ตัว
  ],
  "temperature": { "battery_c": 48.0, "board_c": 42.1, "pi_cpu_c": 51.2 },
  "router": { "online": true, "clients": 23, "throughput_mbps": 68.7, "signal_dbm": -47, "temperature_c": 50.1 },
  "failing_sensors": [], "status_texts": [],

  // ผลจากระบบ SOS
  "level": "SOS", "sos": true, "safe_mode": true, "status": "ABNORMAL",
  "sos_status": { "connection": "NORMAL", "battery": "NORMAL", "propeller": "SOS",
                  "temperature": "WARNING", "router": "NORMAL", "flight": "NORMAL" },
  "alerts": [
    { "category": "propeller", "code": "MOTOR_STOPPED", "level": "SOS", "message": "ใบพัด/มอเตอร์ M3 ไม่หมุน" }
  ]
}
```
ค่าที่ยังไม่รู้เป็น `null` และ `motors` เป็น `[]` ถ้า FC ไม่ส่งข้อมูลมอเตอร์

**`drone_alert`**: `{category, code, level, message, state: "RAISED"|"RESOLVED", drone_id, timestamp, lat, lon, altitude, battery}`

**REST** (เปิด CORS แล้ว)

| endpoint | คืนค่า |
|---|---|
| `GET /api/status` | `drone_data` ล่าสุด |
| `GET /api/telemetry?limit=100` | ประวัติจาก DB (ใหม่สุดก่อน) |
| `GET /api/alerts?limit=50` | ประวัติ alert (ใหม่สุดก่อน) |
| `GET /api/health` | สถานะ backend |
