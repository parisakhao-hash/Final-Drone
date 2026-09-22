# Drone SOS Backend

Backend ของโดรนกระจายสัญญาณ: เก็บข้อมูลการทำงานของโดรน, ค่าจาก Sensor และสถานะ Router
แล้วตรวจ **ระบบ SOS** (แบต / ใบพัด / อุณหภูมิ / Router) ส่งให้ Frontend และเก็บลง Amazon DynamoDB

```
User ──> QGroundControl ──> Drone ──> Backend ──> Frontend (เว็บ)
                              └──> กระจายสัญญาณ
```

## ความคืบหน้า

| ไฟล์ | หน้าที่ | สถานะ |
|---|---|---|
| `config.py` | ค่าตั้งค่าและเกณฑ์ SOS | ✅ เสร็จ |
| `alerts.py` | ระบบ SOS | ✅ เสร็จ |
| `telemetry.py` | รับค่าจากโดรน (QGroundControl / MAVLink) | รอทำ |
| `simulator.py` | โดรนจำลองสำหรับทดสอบ | รอทำ |
| `storage.py` | บันทึกข้อมูลลง DynamoDB | รอทำ |
| `setup_aws.py` | สร้างตาราง DynamoDB | รอทำ |
| `app.py` | ตัวหลัก + API ให้ Frontend | รอทำ |
| `console.py` | แสดงผลใน Terminal | รอทำ |

## ทดสอบระบบ SOS

```bash
python alerts.py
```
จะแสดงผลการตรวจ SOS จากค่าตัวอย่าง เช่น แบตต่ำ, ใบพัดไม่หมุน, ร้อนเกิน, Router ดับ, ขาดการเชื่อมต่อ

## ระบบ SOS

ระดับ: `NORMAL` < `WARNING` < `CRITICAL` < `SOS`  ปรับเกณฑ์ได้ใน `config.py` หรือไฟล์ `.env`

| หมวด | ตรวจอะไร |
|---|---|
| battery | แบต ≤ 30% WARNING, ≤ 20% CRITICAL, ≤ 10% SOS |
| propeller | ใบพัด/มอเตอร์ไม่หมุน (SOS), ทำงานไม่สมดุล (CRITICAL) |
| temperature | อุณหภูมิมอเตอร์, แบต, บอร์ด FC, Raspberry Pi, Router |
| router | Router กระจายสัญญาณไม่ทำงาน |
| connection | ขาดการเชื่อมต่อ (SOS), สัญญาณอ่อน |
| flight | ร่วงเร็วผิดปกติ, autopilot แจ้งเตือน, เซนเซอร์เสีย, GPS |
