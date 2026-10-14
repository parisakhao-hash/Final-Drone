"""โดรนจำลอง (mock) ใช้ตอนยังไม่ได้ต่อโดรนจริง

ลำดับการบิน: ยืนพื้น -> ขึ้นบิน -> บินวนรอบจุด home -> แบตต่ำกลับฐาน/ลงจอด -> ชาร์จแบตแล้ววนใหม่
scenario:
  normal   ไม่มีเหตุการณ์ผิดปกติ
  random   สุ่มเหตุการณ์ (มอเตอร์/ใบพัด, ความร้อน, router, GPS, สัญญาณ ...)
  lowbat   แบตหมดเร็ว
  linkloss ขาดการเชื่อมต่อเป็นช่วงๆ
  motor    มอเตอร์/ใบพัดเสียเป็นช่วงๆ
  overheat อุณหภูมิสูงเป็นช่วงๆ
  router   router กระจายสัญญาณดับเป็นช่วงๆ
"""
import math
import random

HOME_LAT = 13.7563   # กรุงเทพฯ เปลี่ยนเป็นพิกัดสนามจริงได้
HOME_LON = 100.5018
CRUISE_ALT = 80.0
ORBIT_RADIUS = 150.0
CRUISE_SPEED = 8.0
MOTOR_COUNT = 4

SCENARIOS = ["normal", "random", "lowbat", "linkloss", "motor", "overheat", "router"]

# ชื่อโหมดแบบ ArduCopter ให้ตรงกับที่อ่านได้จาก MAVLink จริง
FLIGHT_MODES = {"IDLE": "STABILIZE", "TAKEOFF": "GUIDED", "MISSION": "AUTO",
                "RTL": "RTL", "LAND": "LAND"}

RANDOM_EVENTS = ["gps_degraded", "weak_signal", "motor_fail", "motor_overheat",
                 "battery_overheat", "router_offline", "router_overheat"]
SCENARIO_EVENTS = {
    "linkloss": ["link_lost"],
    "motor": ["motor_fail"],
    "overheat": ["motor_overheat", "battery_overheat", "router_overheat"],
    "router": ["router_offline"],
}


class DroneSimulator:
    def __init__(self, scenario="random", home=(HOME_LAT, HOME_LON)):
        self.scenario = scenario
        self.home_lat, self.home_lon = home
        self.phase = "IDLE"          # IDLE, TAKEOFF, MISSION, RTL, LAND
        self.phase_t = 0.0
        self.alt = 0.0
        self.climb = 0.0
        self.angle = 0.0             # มุมบนวงโคจร
        self.dist = 0.0              # ระยะจาก home
        self.battery = 100.0
        self.drain = 1.0 if scenario == "lowbat" else 0.25   # % ต่อวินาทีตอนบิน
        self.event = None
        self.event_left = 0.0
        self.link_up = True
        self.router_clients = 0

    # ---------- เหตุการณ์ผิดปกติ ----------
    def _update_events(self, dt):
        if self.event:
            self.event_left -= dt
            if self.event_left <= 0:
                self.event = None
            return
        if self.phase != "MISSION":
            return
        choices = RANDOM_EVENTS if self.scenario == "random" else SCENARIO_EVENTS.get(self.scenario)
        rate = 0.02 if self.scenario == "random" else 0.04
        if choices and random.random() < rate * dt:
            self.event = random.choice(choices)
            self.event_left = random.uniform(8, 15)

    # ---------- การบิน ----------
    def _update_flight(self, dt):
        self.phase_t += dt
        target_climb = 0.0
        if self.phase == "IDLE":
            self.battery = min(100.0, self.battery + 5 * dt)     # ชาร์จ
            if self.phase_t > 5 and self.battery >= 100:
                self._set_phase("TAKEOFF")
        elif self.phase == "TAKEOFF":
            target_climb = 3.0
            self.dist = min(ORBIT_RADIUS, self.dist + CRUISE_SPEED * 0.5 * dt)
            if self.alt >= CRUISE_ALT:
                self._set_phase("MISSION")
        elif self.phase == "MISSION":
            self.angle += (CRUISE_SPEED / ORBIT_RADIUS) * dt
            if self.event == "motor_fail":
                target_climb = -2.0         # มอเตอร์ดับ 1 ตัว เสียระดับ
            elif self.alt < CRUISE_ALT - 1:
                target_climb = 2.0
            if self.battery <= 35:          # กลับฐานก่อนแบตหมด
                self._set_phase("RTL")
        elif self.phase == "RTL":
            self.dist = max(0.0, self.dist - CRUISE_SPEED * dt)
            if self.dist <= 0:
                self._set_phase("LAND")
        elif self.phase == "LAND":
            target_climb = -3.0
            if self.alt <= 0:
                self.alt = 0.0
                self._set_phase("IDLE")

        self.climb = target_climb
        self.alt = max(0.0, self.alt + self.climb * dt)
        if self.phase != "IDLE":
            self.battery = max(0.0, self.battery - self.drain * dt)

    def _set_phase(self, phase):
        self.phase, self.phase_t = phase, 0.0

    def step(self, dt=1.0):
        """เดินเวลาไป dt วินาที แล้วคืนสถานะโดรน (ชื่อฟิลด์เดียวกับที่อ่านจาก MAVLink)"""
        self._update_events(dt)
        self._update_flight(dt)
        self.link_up = self.event != "link_lost"
        return self.state()

    # ---------- ค่าจากเซนเซอร์ ----------
    def _motors(self, armed):
        motors = []
        for i in range(MOTOR_COUNT):
            failed = self.event == "motor_fail" and i == 2
            if not armed:
                rpm, output = 0, 0
            elif failed:
                rpm, output = 0, 100          # FC สั่งเต็มที่แต่มอเตอร์ไม่หมุน
            else:
                output = random.randint(48, 60) + (8 if self.event == "motor_fail" else 0)
                rpm = int(output * 180 + random.randint(-150, 150))
            hot = self.event == "motor_overheat" and i == 0
            temp = random.uniform(85, 95) if hot else (random.uniform(45, 65) if armed else 32.0)
            motors.append({"id": i + 1, "rpm": rpm, "output": output, "temperature_c": round(temp, 1)})
        return motors

    def state(self):
        armed = self.phase != "IDLE"
        north = self.dist * math.cos(self.angle)
        east = self.dist * math.sin(self.angle)
        lat = self.home_lat + north / 111_320
        lon = self.home_lon + east / (111_320 * math.cos(math.radians(self.home_lat)))
        heading = (math.degrees(self.angle) + 90) % 360
        speed = {"MISSION": CRUISE_SPEED, "RTL": CRUISE_SPEED, "TAKEOFF": 2.0}.get(self.phase, 0.0)

        gps_bad = self.event == "gps_degraded"
        signal = random.randint(25, 38) if self.event == "weak_signal" else random.randint(65, 98)
        bat_temp = random.uniform(56, 62) if self.event == "battery_overheat" else \
            (random.uniform(32, 40) if armed else 30.0)

        return {
            "armed": armed,
            "flight_mode": FLIGHT_MODES[self.phase],
            "system_status": "ACTIVE" if armed else "STANDBY",
            "battery": round(self.battery, 1),
            "voltage": round(13.2 + 3.6 * (self.battery / 100), 2),   # แบต 4S: 13.2V - 16.8V
            "current": round(random.uniform(14, 20) if armed else 0.4, 1),
            "gps": random.randint(3, 5) if gps_bad else random.randint(9, 14),
            "gps_fix": 2 if gps_bad else 3,
            "lat": round(lat, 7),
            "lon": round(lon, 7),
            "altitude": round(self.alt, 2),
            "speed": round(speed + random.uniform(-0.3, 0.3) if speed else 0.0, 2),
            "climb": round(self.climb, 2),
            "heading": round(heading),
            "signal": signal,
            "failing_sensors": [],
            "motors": self._motors(armed),
            "temperature": {
                "battery_c": round(bat_temp, 1),
                "board_c": round(random.uniform(38, 45), 1),
            },
        }

    def router_state(self, airborne=None):
        """สถานะ router กระจายสัญญาณ (ไม่ได้มาจาก MAVLink)
        airborne: ส่งเข้ามาเองได้ ตอนใช้คู่กับโดรนจริง"""
        if airborne is None:
            airborne = self.phase != "IDLE"
        online = self.event != "router_offline"
        target = random.randint(8, 40) if (airborne and online) else 0
        self.router_clients += max(-3, min(3, target - self.router_clients))
        temp = random.uniform(76, 82) if self.event == "router_overheat" else random.uniform(42, 55)
        return {
            "online": online,
            "clients": self.router_clients if online else 0,
            "throughput_mbps": round(random.uniform(20, 80), 1) if online and airborne else 0.0,
            "signal_dbm": random.randint(-75, -45) if online else None,
            "temperature_c": round(temp, 1),
        }
