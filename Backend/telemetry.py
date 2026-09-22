"""telemetry.py — รับค่าจากโดรน (รอทำ)

หน้าที่:
- MockSource: ใช้ค่าจำลองตอนยังไม่มีโดรน
- MavlinkSource: อ่านค่าจริงจาก QGroundControl (MAVLink) เช่น แบต, GPS, มอเตอร์, อุณหภูมิ
- อ่านสถานะ Router และอุณหภูมิ Raspberry Pi
"""
# TODO
