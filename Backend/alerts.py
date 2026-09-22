"""ระบบ SOS

ระดับ: NORMAL < WARNING < CRITICAL < SOS
- WARNING  ควรเฝ้าดู
- CRITICAL ควรพาโดรนกลับ (safe_mode = True)
- SOS      เหตุฉุกเฉิน ต้องจัดการทันที

หมวด (sos_status): connection, battery, propeller, temperature, router, flight

ระบบนี้ "แจ้งเตือน" เท่านั้น ไม่ได้สั่งโดรนเอง การสั่ง RTL/Land ยังทำผ่าน QGC
"""
import time

import config

LEVELS = {"NORMAL": 0, "WARNING": 1, "CRITICAL": 2, "SOS": 3}
CATEGORIES = ["connection", "battery", "propeller", "temperature", "router", "flight"]
TEMP_NAMES = {"motor_c": "มอเตอร์", "battery_c": "แบตเตอรี่", "board_c": "บอร์ดควบคุม",
              "pi_cpu_c": "Raspberry Pi ", "router_c": "Router "}   # เว้นวรรคหลังชื่ออังกฤษ


def _alert(category, code, level, message):
    return {"category": category, "code": code, "level": level, "message": message}


def _check_battery(d):
    bat = d.get("battery")
    if bat is None:
        return []
    if bat <= config.BATTERY_SOS:
        return [_alert("battery", "BATTERY", "SOS", f"แบตเตอรี่วิกฤต {bat}%")]
    if bat <= config.BATTERY_LIMIT:
        return [_alert("battery", "BATTERY", "CRITICAL", f"แบตเตอรี่ต่ำ {bat}%")]
    if bat <= config.BATTERY_WARN:
        return [_alert("battery", "BATTERY", "WARNING", f"แบตเตอรี่เหลือน้อย {bat}%")]
    return []


def _check_propeller(d):
    motors = d.get("motors") or []
    if not d.get("armed") or not motors:
        return []
    # มี ESC telemetry: มอเตอร์ตัวไหน rpm = 0 ขณะที่ตัวอื่นหมุน = ใบพัด/มอเตอร์หยุด
    spinning = [mo for mo in motors if mo.get("rpm")]
    stopped = [mo for mo in motors if mo.get("rpm") == 0]
    if spinning and stopped:
        ids = ", ".join(f"M{mo['id']}" for mo in stopped)
        return [_alert("propeller", "MOTOR_STOPPED", "SOS", f"ใบพัด/มอเตอร์ {ids} ไม่หมุน")]
    # ไม่มี rpm: ดูจากคำสั่งที่ FC ส่งให้มอเตอร์ ถ้าต่างกันมาก = FC พยายามชดเชยตัวที่มีปัญหา
    outputs = [mo["output"] for mo in motors if mo.get("output") is not None]
    if len(outputs) >= 2 and max(outputs) - min(outputs) > config.MOTOR_IMBALANCE:
        worst = max(motors, key=lambda mo: mo.get("output") or 0)
        return [_alert("propeller", "MOTOR_IMBALANCE", "CRITICAL",
                       f"ใบพัด/มอเตอร์ทำงานไม่สมดุล (M{worst['id']} {worst['output']}%)")]
    return []


def _check_temperature(d):
    temps = dict(d.get("temperature") or {})
    motor_temps = [mo["temperature_c"] for mo in d.get("motors") or [] if mo.get("temperature_c")]
    if motor_temps:
        temps["motor_c"] = max(motor_temps)
    temps["router_c"] = (d.get("router") or {}).get("temperature_c")

    alerts = []
    for key, (warn, crit) in config.TEMP_LIMITS.items():
        t = temps.get(key)
        if t is None:
            continue
        code = "TEMP_" + key[:-2].upper()          # motor_c -> TEMP_MOTOR
        if t >= crit:
            alerts.append(_alert("temperature", code, "CRITICAL",
                                 f"{TEMP_NAMES[key]}ร้อนเกินกำหนด {t}°C"))
        elif t >= warn:
            alerts.append(_alert("temperature", code, "WARNING", f"{TEMP_NAMES[key]}ร้อน {t}°C"))
    return alerts


def _check_router(d):
    router = d.get("router") or {}
    if router.get("online") is False:
        level = "CRITICAL" if d.get("armed") else "WARNING"
        return [_alert("router", "ROUTER_OFFLINE", level, "Router กระจายสัญญาณไม่ทำงาน")]
    return []


def _check_flight(d):
    alerts = []
    climb, alt = d.get("climb"), d.get("altitude")
    if d.get("armed") and climb is not None and alt is not None \
            and climb <= config.FALL_RATE_SOS and alt > 2:
        alerts.append(_alert("flight", "FREEFALL", "SOS", f"โดรนร่วงเร็วผิดปกติ {climb} m/s"))

    status = d.get("system_status")
    if status == "EMERGENCY":
        alerts.append(_alert("flight", "SYSTEM", "SOS", "Autopilot แจ้งสถานะฉุกเฉิน (EMERGENCY)"))
    elif status == "CRITICAL":
        alerts.append(_alert("flight", "SYSTEM", "CRITICAL", "Autopilot แจ้งสถานะวิกฤต (CRITICAL)"))

    if d.get("failing_sensors"):
        alerts.append(_alert("flight", "SENSOR", "CRITICAL",
                             "เซนเซอร์ผิดปกติ: " + ", ".join(d["failing_sensors"])))
    for text in d.get("status_texts", []):
        alerts.append(_alert("flight", "AUTOPILOT_MSG", "CRITICAL", f"Autopilot: {text}"))

    sats, fix = d.get("gps"), d.get("gps_fix")
    if (sats is not None and sats < config.GPS_MIN) or (fix is not None and fix < 3):
        alerts.append(_alert("flight", "GPS", "WARNING", f"GPS ต่ำกว่ากำหนด ({sats} ดวง, fix={fix})"))

    sig = d.get("signal")
    if sig is not None:
        if sig < config.SIGNAL_CRITICAL:
            alerts.append(_alert("connection", "SIGNAL", "CRITICAL", f"สัญญาณควบคุมอ่อนมาก {sig}%"))
        elif sig < config.SIGNAL_MIN:
            alerts.append(_alert("connection", "SIGNAL", "WARNING", f"สัญญาณควบคุมอ่อน {sig}%"))
    return alerts


def evaluate(d, ever_connected):
    """คืน list ของ alert ที่เกิดขึ้นตอนนี้ จาก snapshot d"""
    if not d["connected"]:
        if ever_connected:
            return [_alert("connection", "LINK_LOST", "SOS", "ขาดการเชื่อมต่อกับโดรน")]
        return [_alert("connection", "NO_DATA", "WARNING", "ยังไม่ได้รับข้อมูลจากโดรน")]
    return (_check_battery(d) + _check_propeller(d) + _check_temperature(d)
            + _check_router(d) + _check_flight(d))


def _level_name(value):
    return next(k for k, v in LEVELS.items() if v == value)


class AlertEngine:
    """ประเมิน snapshot แล้วบอกว่ามี alert ไหน "เกิดใหม่" (RAISED) หรือ "หายไป" (RESOLVED)
    เพื่อบันทึก/แจ้งเตือนเฉพาะตอนเปลี่ยนสถานะ ไม่ใช่ทุกวินาที"""

    def __init__(self, hold=config.ALERT_HOLD):
        self.hold = hold
        self.active = {}           # key -> alert
        self.last_seen = {}        # key -> เวลาที่เจอล่าสุด
        self.ever_connected = False

    def process(self, d, now=None):
        """เติมฟิลด์สถานะ SOS ลงใน d แล้วคืน list ของ event"""
        now = time.monotonic() if now is None else now
        self.ever_connected |= d["connected"]
        # key รวม message ของ AUTOPILOT_MSG เพราะอาจมีหลายข้อความพร้อมกัน
        current = {(a["code"], a["message"] if a["code"] == "AUTOPILOT_MSG" else ""): a
                   for a in evaluate(d, self.ever_connected)}

        events = []
        for key, a in current.items():
            old = self.active.get(key)
            if old is None or old["level"] != a["level"]:
                events.append({**a, "state": "RAISED"})
            self.active[key] = a
            self.last_seen[key] = now
        # ค้าง alert ไว้ self.hold วินาที กันค่าแกว่งรอบเกณฑ์แล้วแจ้งเตือนรัวๆ
        for key in list(self.active):
            if key not in current and now - self.last_seen[key] >= self.hold:
                events.append({**self.active.pop(key), "state": "RESOLVED"})
                del self.last_seen[key]

        alerts = list(self.active.values())
        top = max((LEVELS[a["level"]] for a in alerts), default=0)
        d["level"] = _level_name(top)
        d["sos"] = top == LEVELS["SOS"]
        d["safe_mode"] = top >= LEVELS["CRITICAL"]
        d["status"] = "NORMAL" if not alerts else "ABNORMAL"
        d["alerts"] = alerts
        d["sos_status"] = {
            c: _level_name(max((LEVELS[a["level"]] for a in alerts if a["category"] == c), default=0))
            for c in CATEGORIES
        }
        return events


# ---------- ทดสอบ: python alerts.py ----------
if __name__ == "__main__":
    normal = {
        "connected": True, "armed": True, "battery": 80, "gps": 12, "gps_fix": 3, "signal": 90,
        "altitude": 80, "climb": 0.0, "system_status": "ACTIVE",
        "motors": [{"id": i, "rpm": 9800, "output": 55, "temperature_c": 55} for i in range(1, 5)],
        "temperature": {"battery_c": 35, "board_c": 42, "pi_cpu_c": 50},
        "router": {"online": True, "temperature_c": 48},
    }
    stopped_motor = [{"id": i, "rpm": 0 if i == 3 else 9800, "output": 100 if i == 3 else 60,
                      "temperature_c": 55} for i in range(1, 5)]
    cases = {
        "ปกติ": {},
        "แบตต่ำ": {"battery": 18},
        "แบตวิกฤต": {"battery": 8},
        "ใบพัด M3 ไม่หมุน": {"motors": stopped_motor},
        "มอเตอร์ร้อน": {"motors": [{**mo, "temperature_c": 92} for mo in normal["motors"]]},
        "แบตร้อน": {"temperature": {**normal["temperature"], "battery_c": 57}},
        "Router ดับ": {"router": {"online": False, "temperature_c": 48}},
        "Router ร้อน": {"router": {"online": True, "temperature_c": 78}},
        "ขาดการเชื่อมต่อ": {"connected": False},
    }
    for name, change in cases.items():
        d = {**normal, **change}
        engine = AlertEngine()
        engine.ever_connected = True
        engine.process(d)
        print(f"[{d['level']:8}] {name}")
        for a in d["alerts"]:
            print(f"           - {a['category']}: {a['message']}")
