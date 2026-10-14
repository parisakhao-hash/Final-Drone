"""แหล่งข้อมูลของโดรน

ทุก source มีเมธอด start() และ snapshot() ที่คืน dict รูปแบบเดียวกัน
ส่วน SOS / ฐานข้อมูล / API จึงไม่ต้องรู้ว่าข้อมูลมาจาก mock หรือโดรนจริง
"""
import collections
import logging
import os
import threading
import time

import config
from simulator import MOTOR_COUNT, DroneSimulator

log = logging.getLogger(__name__)

# ค่าเริ่มต้นตอนยังไม่ได้รับข้อมูล (None = ยังไม่รู้ค่า)
EMPTY_VEHICLE = {
    "armed": False, "flight_mode": None, "system_status": None,
    "battery": None, "voltage": None, "current": None,
    "gps": None, "gps_fix": None, "lat": None, "lon": None,
    "altitude": None, "speed": None, "climb": None, "heading": None, "signal": None,
    "failing_sensors": [], "status_texts": [], "motors": [], "temperature": {},
}

PI_THERMAL = "/sys/class/thermal/thermal_zone0/temp"


def read_pi_temperature():
    """อุณหภูมิ CPU ของ Raspberry Pi (บนเครื่องอื่นที่ไม่มีไฟล์นี้จะได้ None)"""
    try:
        with open(PI_THERMAL) as f:
            return round(int(f.read()) / 1000, 1)
    except (OSError, ValueError):
        return None


class MockSource:
    """ข้อมูลจำลอง ใช้ทดสอบระบบโดยไม่ต้องมีโดรน"""

    name = "mock"

    def __init__(self, scenario="random"):
        self.sim = DroneSimulator(scenario)
        self._last = time.monotonic()

    def start(self):
        log.info("ใช้ข้อมูลจำลอง (scenario=%s)", self.sim.scenario)

    def snapshot(self):
        now = time.monotonic()
        vehicle = self.sim.step(now - self._last)
        self._last = now
        d = {**EMPTY_VEHICLE, **vehicle,
             "connected": self.sim.link_up,
             "heartbeat_age": 0.0 if self.sim.link_up else None,
             "router": self.sim.router_state()}
        d["temperature"] = {**d["temperature"], "pi_cpu_c": read_pi_temperature()}
        return d


class MavlinkSource:
    """อ่าน MAVLink จากโดรน (อ่านอย่างเดียว ไม่ส่งคำสั่งไปที่โดรน)

    MAVLINK_URL:
      udpin:0.0.0.0:14445  รับจาก QGroundControl (MAVLink forwarding)
      /dev/serial0         Pi ต่อสาย UART กับ flight controller โดยตรง (ตั้ง MAVLINK_BAUD ด้วย)
    """

    name = "mavlink"

    def __init__(self, url=config.MAVLINK_URL, baud=config.MAVLINK_BAUD):
        self.url, self.baud = url, baud
        self.vehicle = dict(EMPTY_VEHICLE)
        self.vehicle["temperature"] = {}
        self.motors = [{"id": i + 1, "rpm": None, "output": None, "temperature_c": None}
                       for i in range(MOTOR_COUNT)]
        self.motors_seen = False
        self.sysid = None                      # ล็อกกับโดรนตัวแรกที่เจอ
        self.last_heartbeat = None
        self.status_texts = collections.deque(maxlen=10)
        self._lock = threading.Lock()
        # router ยังไม่ได้ต่อของจริง -> จำลองไปก่อน (ดู read_router_status)
        self._router_mock = DroneSimulator("normal")

    def start(self):
        threading.Thread(target=self._run, name="mavlink-reader", daemon=True).start()

    def _run(self):
        # ต้องใช้ MAVLink 2 ไม่งั้น pymavlink ไม่รู้จักข้อความเลข > 255 เช่น ESC_TELEMETRY_1_TO_4
        os.environ.setdefault("MAVLINK20", "1")
        from pymavlink import mavutil
        self.mavutil = mavutil
        while True:
            try:
                log.info("รอ MAVLink ที่ %s ...", self.url)
                conn = mavutil.mavlink_connection(self.url, baud=self.baud, source_system=254)
                while True:
                    msg = conn.recv_match(blocking=True, timeout=1)
                    if msg is not None:
                        self._handle(msg)
            except Exception:
                log.exception("MAVLink connection error, ลองใหม่ใน 3 วินาที")
                time.sleep(3)

    def _handle(self, msg):
        m = self.mavutil.mavlink
        mtype = msg.get_type()
        if mtype == "BAD_DATA":
            return

        if mtype == "HEARTBEAT":
            # ข้าม heartbeat ของ QGC เอง / อุปกรณ์ที่ไม่ใช่ autopilot
            if msg.type == m.MAV_TYPE_GCS or msg.autopilot == m.MAV_AUTOPILOT_INVALID:
                return
            if self.sysid is None:
                self.sysid = msg.get_srcSystem()
                log.info("เจอโดรน sysid=%s", self.sysid)
        # RADIO_STATUS มาจากวิทยุ telemetry (SiK ใช้ sysid 51) ไม่ใช่ตัวโดรน
        if msg.get_srcSystem() != self.sysid and mtype != "RADIO_STATUS":
            return

        with self._lock:
            v = self.vehicle
            if mtype == "HEARTBEAT":
                self.last_heartbeat = time.monotonic()
                v["armed"] = bool(msg.base_mode & m.MAV_MODE_FLAG_SAFETY_ARMED)
                v["flight_mode"] = self.mavutil.mode_string_v10(msg)
                state = m.enums["MAV_STATE"].get(msg.system_status)
                v["system_status"] = state.name.replace("MAV_STATE_", "") if state else None

            elif mtype == "SYS_STATUS":
                if msg.voltage_battery != 65535:
                    v["voltage"] = round(msg.voltage_battery / 1000, 2)
                if msg.current_battery >= 0:
                    v["current"] = round(msg.current_battery / 100, 1)
                if msg.battery_remaining >= 0:
                    v["battery"] = msg.battery_remaining
                bad = (msg.onboard_control_sensors_present
                       & msg.onboard_control_sensors_enabled
                       & ~msg.onboard_control_sensors_health)
                v["failing_sensors"] = self._sensor_names(bad)
                if v.get("_signal_from_radio") is None:
                    # ไม่มี RADIO_STATUS -> ประเมินคุณภาพลิงก์จากอัตราแพ็กเก็ตหาย
                    v["signal"] = round(100 - msg.drop_rate_comm / 100)

            elif mtype == "BATTERY_STATUS":
                if msg.temperature != 32767:
                    v["temperature"]["battery_c"] = round(msg.temperature / 100, 1)

            elif mtype == "SCALED_PRESSURE":
                v["temperature"]["board_c"] = round(msg.temperature / 100, 1)

            elif mtype == "GPS_RAW_INT":
                v["gps"] = msg.satellites_visible if msg.satellites_visible != 255 else None
                v["gps_fix"] = msg.fix_type

            elif mtype == "GLOBAL_POSITION_INT":
                v["lat"] = msg.lat / 1e7
                v["lon"] = msg.lon / 1e7
                v["altitude"] = round(msg.relative_alt / 1000, 2)
                v["climb"] = round(-msg.vz / 100, 2)
                if msg.hdg != 65535:
                    v["heading"] = round(msg.hdg / 100)

            elif mtype == "VFR_HUD":
                v["speed"] = round(msg.groundspeed, 2)

            elif mtype == "SERVO_OUTPUT_RAW":
                # คำสั่งที่ FC ส่งให้มอเตอร์ 1-4 (PWM 1000-2000 -> 0-100%)
                self.motors_seen = True
                for i, motor in enumerate(self.motors):
                    pwm = getattr(msg, f"servo{i + 1}_raw")
                    motor["output"] = max(0, min(100, round((pwm - 1000) / 10))) if pwm else None

            elif mtype == "ESC_TELEMETRY_1_TO_4":
                # มีเฉพาะ ESC ที่ส่ง telemetry ได้ (BLHeli32 / DShot) บอกรอบหมุนและอุณหภูมิจริง
                self.motors_seen = True
                for i, motor in enumerate(self.motors):
                    motor["rpm"] = msg.rpm[i]
                    motor["temperature_c"] = msg.temperature[i]

            elif mtype == "RADIO_STATUS":
                if msg.rssi != 255:
                    v["_signal_from_radio"] = True
                    v["signal"] = round(msg.rssi / 254 * 100)

            elif mtype == "STATUSTEXT":
                # เก็บเฉพาะข้อความระดับ CRITICAL ขึ้นไป (EMERGENCY=0, ALERT=1, CRITICAL=2)
                if msg.severity <= m.MAV_SEVERITY_CRITICAL:
                    self.status_texts.append((time.monotonic(), msg.text))

    def _sensor_names(self, bits):
        names = []
        for value, entry in self.mavutil.mavlink.enums["MAV_SYS_STATUS_SENSOR"].items():
            if value and bits & value and (value & (value - 1)) == 0:
                names.append(entry.name.replace("MAV_SYS_STATUS_SENSOR_", ""))
        return names

    def read_router_status(self, airborne):
        # TODO: เปลี่ยนเป็นอ่านจาก router จริง เช่น API ของ router, หรือถ้า Pi เป็น hotspot เอง
        #       อ่านจาก `iw dev wlan0 station dump` / /proc/net/dev
        return self._router_mock.router_state(airborne=airborne)

    def snapshot(self):
        with self._lock:
            v = {k: val for k, val in self.vehicle.items() if not k.startswith("_")}
            v["temperature"] = dict(self.vehicle["temperature"])
            v["motors"] = [dict(mo) for mo in self.motors] if self.motors_seen else []
            now = time.monotonic()
            # ข้อความเดียวกันซ้ำกันใน 30 วินาทีนับครั้งเดียว
            v["status_texts"] = list(dict.fromkeys(t for ts, t in self.status_texts if now - ts < 30))
        age = None if self.last_heartbeat is None else now - self.last_heartbeat
        v["connected"] = age is not None and age < config.HEARTBEAT_TIMEOUT
        v["heartbeat_age"] = None if age is None else round(age, 1)
        v["router"] = self.read_router_status(v["armed"])
        v["temperature"]["pi_cpu_c"] = read_pi_temperature()
        return v


def make_source(kind=config.DATA_SOURCE, scenario="random"):
    if kind == "mavlink":
        return MavlinkSource()
    if kind == "mock":
        return MockSource(scenario)
    raise ValueError(f"DATA_SOURCE ไม่รู้จัก: {kind!r} (ใช้ mock หรือ mavlink)")
