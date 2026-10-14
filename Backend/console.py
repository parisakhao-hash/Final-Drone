"""รัน Backend พร้อมแสดงค่าโดรนแบบ real-time ใน Terminal
(ทำงานเหมือน app.py ทุกอย่าง: ตรวจ SOS, บันทึก DB, เปิด API ให้ Frontend + แสดงผลบนจอ)

รัน:
  python console.py                      # ค่าจำลอง (mock)
  python console.py --scenario motor     # mock: normal/random/lowbat/linkloss/motor/overheat/router
  python console.py --source mavlink     # ค่าจริงจากโดรน
กด Ctrl+C เพื่อออก (log ของระบบอยู่ใน console.log)
"""
import collections
import logging
import sys
import unicodedata

import config
from app import parse_args, start_backend

RESET, BOLD, DIM = "\033[0m", "\033[1m", "\033[2m"
COLOR = {"NORMAL": "\033[32m", "WARNING": "\033[33m", "CRITICAL": "\033[31m", "SOS": "\033[35m"}
GREEN, YELLOW, RED = COLOR["NORMAL"], COLOR["WARNING"], COLOR["CRITICAL"]
WIDTH = 72
CATEGORY_NAMES = {"connection": "เชื่อมต่อ", "battery": "แบต", "propeller": "ใบพัด",
                  "temperature": "อุณหภูมิ", "router": "Router", "flight": "การบิน"}


def dwidth(s):
    """ความกว้างบนจอ (สระ/วรรณยุกต์ไทยไม่กินที่)"""
    return sum(0 if unicodedata.category(c) in ("Mn", "Me") else 1 for c in s)


def pad(s, width):
    return s + " " * max(0, width - dwidth(s))


def fmt(v, unit="", digits=None):
    if v is None:
        return "-"
    if isinstance(v, bool):
        return "YES" if v else "NO"
    if digits is not None:
        v = f"{v:.{digits}f}"
    return f"{v}{unit}"


def bar(pct, warn, crit, size=20):
    if pct is None:
        return DIM + "·" * size + RESET + "    -"
    pct = max(0, min(100, pct))
    color = GREEN if pct > warn else YELLOW if pct > crit else RED
    n = round(pct / 100 * size)
    return f"{color}{'█' * n}{RESET}{DIM}{'░' * (size - n)}{RESET} {pct:>3.0f}%"


def row(*cells):
    """cells = [(label, value), ...] แสดงเป็นคอลัมน์"""
    col = WIDTH // len(cells)
    return "".join(pad(f"  {DIM}{pad(label, 10)}{RESET}{value}", col + len(DIM) + len(RESET))
                   for label, value in cells)


def colored(level, text):
    return f"{COLOR[level]}{text}{RESET}"


def render(d, log_lines):
    level = d["level"]
    link = colored("NORMAL", "● CONNECTED") if d["connected"] else colored("CRITICAL", "● DISCONNECTED")
    router = d.get("router") or {}
    temps = d.get("temperature") or {}
    motors = d.get("motors") or []
    out = [
        f"{BOLD}{'═' * WIDTH}{RESET}",
        f"{BOLD} DRONE SOS BACKEND · {d['drone_id']} · {d['source'].upper()}"
        f"   {DIM}API :{config.PORT} · DB {config.STORAGE}{RESET}",
        f"{BOLD}{'═' * WIDTH}{RESET}",
        f"  {d['time']}   {link}   {COLOR[level]}{BOLD}[ {level} ]{RESET}"
        + (f"   {RED}{BOLD}⚠ SAFE MODE{RESET}" if d["safe_mode"] else ""),
        "  " + "  ".join(colored(lv, f"■ {CATEGORY_NAMES[c]}") for c, lv in d["sos_status"].items()),
        "",
        f"{BOLD} การบิน{RESET}",
        row(("Mode", fmt(d["flight_mode"])), ("Armed", fmt(d["armed"])), ("GPS", fmt(d["gps"], " ดวง"))),
        row(("ความสูง", fmt(d["altitude"], " m", 1)), ("ความเร็ว", fmt(d["speed"], " m/s", 1)),
            ("ไต่/ร่วง", fmt(d["climb"], " m/s", 1))),
        row(("Lat", fmt(d["lat"], "", 6)), ("Lon", fmt(d["lon"], "", 6))),
        "",
        f"{BOLD} แบตเตอรี่ / สัญญาณ{RESET}",
        f"  {DIM}แบตเตอรี่ {RESET} {bar(d['battery'], config.BATTERY_WARN, config.BATTERY_LIMIT)}"
        f"   {fmt(d['voltage'], ' V', 2)}  {fmt(d['current'], ' A', 1)}",
        f"  {DIM}สัญญาณ    {RESET} {bar(d['signal'], config.SIGNAL_MIN, config.SIGNAL_CRITICAL)}",
        "",
        f"{BOLD} ใบพัด / มอเตอร์{RESET}",
    ]
    if motors:
        cells = [(f"M{mo['id']}", f"{fmt(mo['rpm'])} rpm  {fmt(mo['output'], '%')}  "
                                  f"{fmt(mo['temperature_c'], '°C')}") for mo in motors]
        out += [row(*cells[i:i + 2]) for i in range(0, len(cells), 2)]
    else:
        out.append(f"  {DIM}- (ยังไม่มีข้อมูลมอเตอร์){RESET}")
    motor_temps = [mo["temperature_c"] for mo in motors if mo.get("temperature_c") is not None]
    out += [
        "",
        f"{BOLD} อุณหภูมิ (°C){RESET}",
        row(("มอเตอร์", fmt(max(motor_temps) if motor_temps else None)),
            ("แบตเตอรี่", fmt(temps.get("battery_c"))), ("บอร์ด FC", fmt(temps.get("board_c")))),
        row(("Pi CPU", fmt(temps.get("pi_cpu_c"))), ("Router", fmt(router.get("temperature_c")))),
        "",
        f"{BOLD} Router กระจายสัญญาณ{RESET}" + (f" {DIM}(mock){RESET}" if d["source"] == "mavlink" else ""),
        row(("Online", fmt(router.get("online"))), ("ผู้ใช้", fmt(router.get("clients"), " คน")),
            ("Speed", fmt(router.get("throughput_mbps"), " Mbps"))),
        "",
        f"{BOLD} แจ้งเตือนตอนนี้{RESET}",
    ]
    if d["alerts"]:
        out += [f"  {colored(a['level'], '■ [' + a['level'] + ']')} {a['message']}" for a in d["alerts"]]
    else:
        out.append(f"  {GREEN}✓ ปกติ{RESET}")
    out += ["", f"{BOLD} ประวัติ{RESET}"]
    out += list(log_lines) or [f"  {DIM}-{RESET}"]
    out += [f"{BOLD}{'─' * WIDTH}{RESET}", f"{DIM}  Ctrl+C เพื่อออก · log อยู่ใน console.log{RESET}"]
    # \033[H = กลับมุมบนซ้าย, \033[K = ลบท้ายบรรทัด, \033[J = ลบที่เหลือ (จอไม่กระพริบ)
    sys.stdout.write("\033[H" + "\n".join(line + "\033[K" for line in out) + "\033[J")
    sys.stdout.flush()


def main():
    # log จะทำให้จอเลื่อน -> เก็บลงไฟล์แทน
    logging.basicConfig(filename="console.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    import flask.cli
    flask.cli.show_server_banner = lambda *a, **k: None

    args = parse_args("Drone SOS backend (terminal)")
    log_lines = collections.deque(maxlen=6)

    def on_update(d, events):
        for e in events:
            mark = "▲" if e["state"] == "RAISED" else "✓"
            color = COLOR[e["level"]] if e["state"] == "RAISED" else DIM
            log_lines.appendleft(f"  {color}{d['time']} {mark} [{e['level']}] {e['message']}{RESET}")
        render(d, log_lines)

    sys.stdout.write("\033[?25l\033[2J")      # ซ่อน cursor, ล้างจอ
    try:
        start_backend(args, on_update)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\033[?25h\n")      # คืน cursor


if __name__ == "__main__":
    main()
