"""เก็บ telemetry และประวัติ alert ลงฐานข้อมูล

- SQLiteStore   : ไฟล์ในเครื่อง ใช้ตอนพัฒนา/ทดสอบ
- DynamoDBStore : Amazon DynamoDB (สร้างตารางด้วย python setup_aws.py)

ทั้งสองแบบใช้ key เดียวกัน: drone_id (partition) + ts (sort, ISO-8601 UTC)
การเขียนทำใน thread แยก (AsyncWriter) ถ้า DB ช้า/หลุด ระบบเฝ้าดูโดรนยังทำงานต่อได้
"""
import json
import logging
import queue
import sqlite3
import threading
import time
from decimal import Decimal

import config

log = logging.getLogger(__name__)


class SQLiteStore:
    def __init__(self, path=config.SQLITE_PATH):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        with self.lock:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS telemetry (
                    drone_id TEXT, ts TEXT, data TEXT, PRIMARY KEY (drone_id, ts));
                CREATE TABLE IF NOT EXISTS alerts (
                    drone_id TEXT, ts TEXT, code TEXT, level TEXT, state TEXT,
                    message TEXT, data TEXT, PRIMARY KEY (drone_id, ts, code));
            """)
        log.info("บันทึกข้อมูลลง SQLite: %s", path)

    def save_telemetry(self, d):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO telemetry VALUES (?,?,?)",
                            (d["drone_id"], d["timestamp"], json.dumps(d, ensure_ascii=False)))
            self.db.commit()

    def save_alert(self, e):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO alerts VALUES (?,?,?,?,?,?,?)",
                            (e["drone_id"], e["timestamp"], e["code"], e["level"], e["state"],
                             e["message"], json.dumps(e, ensure_ascii=False)))
            self.db.commit()

    def _recent(self, table, drone_id, limit):
        with self.lock:
            rows = self.db.execute(
                f"SELECT data FROM {table} WHERE drone_id=? ORDER BY ts DESC LIMIT ?",
                (drone_id, limit)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def recent_telemetry(self, drone_id, limit=100):
        return self._recent("telemetry", drone_id, limit)

    def recent_alerts(self, drone_id, limit=50):
        return self._recent("alerts", drone_id, limit)


def _to_dynamo(d):
    # DynamoDB ไม่รับ float ต้องเป็น Decimal
    return json.loads(json.dumps(d, ensure_ascii=False), parse_float=Decimal)


def _from_dynamo(obj):
    if isinstance(obj, list):
        return [_from_dynamo(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _from_dynamo(v) for k, v in obj.items()}
    if isinstance(obj, Decimal):
        return int(obj) if obj == obj.to_integral_value() else float(obj)
    return obj


class DynamoDBStore:
    def __init__(self):
        import boto3
        ddb = boto3.resource("dynamodb", region_name=config.AWS_REGION)
        self.telemetry = ddb.Table(config.DDB_TELEMETRY_TABLE)
        self.alerts = ddb.Table(config.DDB_ALERT_TABLE)
        self.telemetry.load()        # เช็คว่ามีตาราง/สิทธิ์ ตั้งแต่ตอนเริ่ม
        self.alerts.load()
        log.info("บันทึกข้อมูลลง DynamoDB (%s): %s, %s", config.AWS_REGION,
                 config.DDB_TELEMETRY_TABLE, config.DDB_ALERT_TABLE)

    def save_telemetry(self, d):
        item = _to_dynamo(d)
        item["ts"] = d["timestamp"]
        if config.DDB_TTL_DAYS > 0:
            item["expires_at"] = int(time.time()) + config.DDB_TTL_DAYS * 86400
        self.telemetry.put_item(Item=item)

    def save_alert(self, e):
        item = _to_dynamo(e)
        # alert หลายตัวอาจเกิดในเวลาเดียวกัน -> ต่อ code ท้าย sort key กันชนกัน
        item["ts"] = f'{e["timestamp"]}#{e["code"]}'
        self.alerts.put_item(Item=item)

    def _recent(self, table, drone_id, limit):
        from boto3.dynamodb.conditions import Key
        resp = table.query(KeyConditionExpression=Key("drone_id").eq(drone_id),
                           ScanIndexForward=False, Limit=limit)
        return _from_dynamo(resp["Items"])

    def recent_telemetry(self, drone_id, limit=100):
        return self._recent(self.telemetry, drone_id, limit)

    def recent_alerts(self, drone_id, limit=50):
        return self._recent(self.alerts, drone_id, limit)


class AsyncWriter:
    """ต่อคิวงานเขียน DB แล้วเขียนใน background thread"""

    def __init__(self, store, maxsize=1000):
        self.store = store
        self.q = queue.Queue(maxsize=maxsize)
        threading.Thread(target=self._run, name="db-writer", daemon=True).start()

    def put(self, method, item):
        try:
            self.q.put_nowait((method, item))
        except queue.Full:
            log.warning("คิว DB เต็ม ทิ้งข้อมูล %s", method)

    def _run(self):
        while True:
            method, item = self.q.get()
            try:
                getattr(self.store, method)(item)
            except Exception as exc:
                log.error("เขียน DB ไม่สำเร็จ (%s): %s", method, exc)


def make_store(kind=config.STORAGE):
    if kind == "dynamodb":
        return DynamoDBStore()
    if kind == "sqlite":
        return SQLiteStore()
    raise ValueError(f"STORAGE ไม่รู้จัก: {kind!r} (ใช้ sqlite หรือ dynamodb)")
