"""Mock ค่าที่ระบบ SOS ใช้: สถานะโดรน, Sensor, Router (ตัวเลขอย่างเดียว)

รัน:  python mock_sos.py
กด Ctrl+C เพื่อออก
"""
import random
import time

INTERVAL = 1  # วินาที

state = {"battery": 100.0}


def around(center, spread, digits=1):
    """สุ่มค่ารอบๆ center"""
    return round(random.uniform(center - spread, center + spread), digits)


def get_mock_data():
    state["battery"] = max(0.0, state["battery"] - 0.2)
    if state["battery"] == 0:
        state["battery"] = 100.0

    return {
        "drone": {
            "battery_pct": round(state["battery"], 1),
            "voltage_v": round(13.2 + 3.6 * state["battery"] / 100, 2),
            "current_a": around(16, 2),
            "altitude_m": around(80, 1.5),
            "speed_ms": around(8, 0.5),
            "climb_ms": around(0, 0.3),
            "heading_deg": random.randint(0, 359),
            "gps_sats": random.randint(9, 14),
            "signal_pct": random.randint(65, 98),
            "lat": around(13.7563, 0.001, 6),
            "lon": around(100.5018, 0.001, 6),
        },
        "sensor": {
            "motor_rpm": [random.randint(9500, 10500) for _ in range(4)],
            "motor_output_pct": [random.randint(50, 60) for _ in range(4)],
            "motor_temp_c": [around(55, 5) for _ in range(4)],
            "battery_temp_c": around(36, 3),
            "board_temp_c": around(42, 2),
            "pi_cpu_temp_c": around(52, 4),
        },
        "router": {
            "online": 1,                     # 1 = ทำงาน, 0 = ไม่ทำงาน
            "clients": random.randint(8, 40),
            "throughput_mbps": around(50, 20),
            "signal_dbm": random.randint(-75, -45),
            "temp_c": around(48, 5),
        },
    }


def show(data):
    d, s, r = data["drone"], data["sensor"], data["router"]
    lines = [
        f"เวลา {time.strftime('%H:%M:%S')}",
        "",
        "[Drone]",
        f"  battery        {d['battery_pct']} %",
        f"  voltage        {d['voltage_v']} V",
        f"  current        {d['current_a']} A",
        f"  altitude       {d['altitude_m']} m",
        f"  speed          {d['speed_ms']} m/s",
        f"  climb          {d['climb_ms']} m/s",
        f"  heading        {d['heading_deg']} °",
        f"  gps            {d['gps_sats']} sats",
        f"  signal         {d['signal_pct']} %",
        f"  lat, lon       {d['lat']}, {d['lon']}",
        "",
        "[Sensor]",
        f"  motor rpm      {s['motor_rpm']}",
        f"  motor output   {s['motor_output_pct']} %",
        f"  motor temp     {s['motor_temp_c']} °C",
        f"  battery temp   {s['battery_temp_c']} °C",
        f"  board temp     {s['board_temp_c']} °C",
        f"  pi cpu temp    {s['pi_cpu_temp_c']} °C",
        "",
        "[Router]",
        f"  online         {r['online']}",
        f"  clients        {r['clients']}",
        f"  throughput     {r['throughput_mbps']} Mbps",
        f"  signal         {r['signal_dbm']} dBm",
        f"  temp           {r['temp_c']} °C",
        "",
        "Ctrl+C เพื่อออก",
    ]
    # ล้างจอแล้วพิมพ์ใหม่ ให้ค่าอัปเดตอยู่ที่เดิม
    print("\033[H\033[J" + "\n".join(lines), flush=True)


if __name__ == "__main__":
    try:
        while True:
            show(get_mock_data())
            time.sleep(INTERVAL)
    except KeyboardInterrupt:
        print()
