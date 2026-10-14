"""ค่าตั้งค่าทั้งหมด อ่านจาก environment / ไฟล์ .env"""
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _env(name, default):
    return os.getenv(name, default)


def _float(name, default):
    return float(os.getenv(name, default))


# ---------- แหล่งข้อมูล ----------
# mock    = ข้อมูลจำลอง
# mavlink = ข้อมูลจริงจากโดรน
DATA_SOURCE = _env("DATA_SOURCE", "mock")
# รับจาก QGC forwarding: udpin:0.0.0.0:14445
# Pi ต่อสาย UART กับ flight controller: /dev/serial0 (baud ตามที่ตั้งใน FC เช่น 57600 / 921600)
MAVLINK_URL = _env("MAVLINK_URL", "udpin:0.0.0.0:14445")
MAVLINK_BAUD = int(_env("MAVLINK_BAUD", "57600"))
DRONE_ID = _env("DRONE_ID", "relay-drone-01")
HEARTBEAT_TIMEOUT = _float("HEARTBEAT_TIMEOUT", "5")   # วินาที ไม่มี heartbeat = ขาดการเชื่อมต่อ
PUBLISH_INTERVAL = _float("PUBLISH_INTERVAL", "1")     # อัปเดตข้อมูลทุกกี่วินาที

# ---------- เกณฑ์ระบบ SOS ----------
# แบตเตอรี่ (%)
BATTERY_WARN = _float("BATTERY_WARN", "30")
BATTERY_LIMIT = _float("BATTERY_LIMIT", "20")      # CRITICAL + safe_mode
BATTERY_SOS = _float("BATTERY_SOS", "10")
# ใบพัด / มอเตอร์
MOTOR_IMBALANCE = _float("MOTOR_IMBALANCE", "35")  # % ต่างกันระหว่างมอเตอร์ที่มากสุด-น้อยสุด
# อุณหภูมิ (°C) — WARNING / CRITICAL
TEMP_LIMITS = {
    "motor_c":   (_float("MOTOR_TEMP_WARN", "80"), _float("MOTOR_TEMP_MAX", "100")),
    "battery_c": (_float("BATTERY_TEMP_WARN", "45"), _float("BATTERY_TEMP_MAX", "55")),
    "board_c":   (_float("BOARD_TEMP_WARN", "60"), _float("BOARD_TEMP_MAX", "75")),
    "pi_cpu_c":  (_float("PI_TEMP_WARN", "70"), _float("PI_TEMP_MAX", "80")),   # Pi เริ่มลดความเร็วที่ 80
    "router_c":  (_float("ROUTER_TEMP_WARN", "70"), _float("ROUTER_TEMP_MAX", "85")),
}
# อื่นๆ
GPS_MIN = _float("GPS_MIN", "6")                    # จำนวนดาวเทียมขั้นต่ำ
SIGNAL_MIN = _float("SIGNAL_MIN", "40")             # % คุณภาพลิงก์ขั้นต่ำ
SIGNAL_CRITICAL = _float("SIGNAL_CRITICAL", "20")
FALL_RATE_SOS = _float("FALL_RATE_SOS", "-5")       # m/s ร่วงเร็วกว่านี้ขณะ armed = SOS
ALERT_HOLD = _float("ALERT_HOLD", "5")              # alert ต้องหายไปนานกี่วินาทีถึงจะถือว่า RESOLVED

# ---------- ฐานข้อมูล ----------
# sqlite   = เก็บในเครื่อง (ทดสอบโดยไม่ต้องมีบัญชี AWS)
# dynamodb = Amazon DynamoDB
STORAGE = _env("STORAGE", "sqlite")
STORE_INTERVAL = _float("STORE_INTERVAL", "2")      # บันทึกข้อมูลทุกกี่วินาที
SQLITE_PATH = _env("SQLITE_PATH", "drone_data.db")
AWS_REGION = _env("AWS_REGION", "ap-southeast-1")   # Singapore ใกล้ไทยสุด
DDB_TELEMETRY_TABLE = _env("DDB_TELEMETRY_TABLE", "drone_telemetry")
DDB_ALERT_TABLE = _env("DDB_ALERT_TABLE", "drone_alerts")
DDB_TTL_DAYS = int(_env("DDB_TTL_DAYS", "30"))      # ลบข้อมูลเก่าอัตโนมัติ (0 = ไม่ลบ)

# ---------- API ----------
HOST = _env("HOST", "0.0.0.0")
PORT = int(_env("PORT", "5000"))


