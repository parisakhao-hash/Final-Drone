"""Backend ระบบ SOS โดรนกระจายสัญญาณ
รับค่าจากโดรน (mock หรือของจริง) -> ตรวจ SOS -> เก็บลง DB -> ส่งให้ Frontend

รัน:  python app.py                      (ค่าจาก .env)
      python app.py --scenario motor     (mock: ทดสอบใบพัด/มอเตอร์เสีย)
      python app.py --source mavlink     (ค่าจริงจากโดรน)

ให้ Frontend เชื่อม:
  Socket.IO event "drone_data"  : สถานะโดรนทุก PUBLISH_INTERVAL วินาที
  Socket.IO event "drone_alert" : ตอน alert เกิดใหม่ (RAISED) / หายไป (RESOLVED)
  GET /api/status               : สถานะล่าสุด
  GET /api/telemetry?limit=100  : ประวัติจาก DB
  GET /api/alerts?limit=50      : ประวัติ alert จาก DB
  GET /api/health               : สถานะ backend
"""
import argparse
import datetime
import logging
import time

from flask import Flask, jsonify, request
from flask_socketio import SocketIO

import config
from alerts import AlertEngine
from simulator import SCENARIOS
from storage import AsyncWriter, make_store
from telemetry import make_source

log = logging.getLogger("backend")

app = Flask(__name__)
app.json.ensure_ascii = False
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

state = {"latest": None, "store": None, "writer": None}


@app.after_request
def allow_cors(resp):
    # ให้ Frontend ที่รันคนละ port / คนละเครื่องเรียก API ได้
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


@app.route("/")
def index():
    return jsonify({"service": "drone-sos-backend",
                    "endpoints": ["/api/status", "/api/telemetry", "/api/alerts", "/api/health"],
                    "socketio_events": ["drone_data", "drone_alert"]})


@app.route("/api/status")
def api_status():
    return jsonify(state["latest"] or {})


@app.route("/api/telemetry")
def api_telemetry():
    limit = min(int(request.args.get("limit", 100)), 1000)
    return jsonify(state["store"].recent_telemetry(config.DRONE_ID, limit))


@app.route("/api/alerts")
def api_alerts():
    limit = min(int(request.args.get("limit", 50)), 500)
    return jsonify(state["store"].recent_alerts(config.DRONE_ID, limit))


@app.route("/api/health")
def api_health():
    latest = state["latest"] or {}
    return jsonify({
        "source": config.DATA_SOURCE,
        "storage": config.STORAGE,
        "drone_connected": latest.get("connected", False),
        "db_queue": state["writer"].q.qsize() if state["writer"] else None,
    })


def monitor_loop(source, writer, on_update=None):
    """วนอ่านค่า -> ตรวจ SOS -> ส่ง Frontend -> บันทึก DB
    on_update(d, events): callback เพิ่มเติม (console.py ใช้แสดงผลบนจอ)"""
    engine = AlertEngine()
    last_store = 0.0
    while True:
        now = datetime.datetime.now(datetime.timezone.utc)
        d = source.snapshot()
        d["drone_id"] = config.DRONE_ID
        d["source"] = source.name
        d["timestamp"] = now.isoformat(timespec="milliseconds")
        d["time"] = now.astimezone().strftime("%H:%M:%S")

        events = engine.process(d)
        state["latest"] = d
        socketio.emit("drone_data", d)

        for e in events:
            e.update(drone_id=d["drone_id"], timestamp=d["timestamp"],
                     lat=d.get("lat"), lon=d.get("lon"),
                     altitude=d.get("altitude"), battery=d.get("battery"))
            log.log(logging.WARNING if e["state"] == "RAISED" else logging.INFO,
                    "%s %s %s: %s", e["state"], e["level"], e["code"], e["message"])
            socketio.emit("drone_alert", e)
            writer.put("save_alert", e)

        # บันทึกตามรอบ STORE_INTERVAL แต่ถ้ามี alert เปลี่ยนให้บันทึกทันที
        mono = time.monotonic()
        if events or mono - last_store >= config.STORE_INTERVAL:
            writer.put("save_telemetry", d)
            last_store = mono

        if on_update:
            on_update(d, events)
        socketio.sleep(config.PUBLISH_INTERVAL)


def parse_args(description):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--source", choices=["mock", "mavlink"], default=config.DATA_SOURCE)
    parser.add_argument("--storage", choices=["sqlite", "dynamodb"], default=config.STORAGE)
    parser.add_argument("--scenario", default="random", choices=SCENARIOS,
                        help="ใช้กับ --source mock เท่านั้น")
    args = parser.parse_args()
    config.DATA_SOURCE, config.STORAGE = args.source, args.storage
    return args


def start_backend(args, on_update=None):
    """เริ่ม DB + แหล่งข้อมูล + loop ตรวจ SOS แล้วเปิด API (บล็อกจนกด Ctrl+C)"""
    store = make_store(args.storage)
    writer = AsyncWriter(store)
    source = make_source(args.source, args.scenario)
    source.start()
    state.update(store=store, writer=writer)
    socketio.start_background_task(monitor_loop, source, writer, on_update)
    socketio.run(app, host=config.HOST, port=config.PORT, debug=False,
                 allow_unsafe_werkzeug=True, log_output=False)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = parse_args("Drone SOS backend")
    print("================================")
    print(" DRONE SOS BACKEND")
    print(f" source  : {args.source}" + (f" ({config.MAVLINK_URL})" if args.source == "mavlink" else ""))
    print(f" storage : {args.storage}")
    print(f" API     : http://localhost:{config.PORT}")
    print("================================")
    start_backend(args)


if __name__ == "__main__":
    main()
