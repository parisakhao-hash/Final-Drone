"""สร้างตาราง DynamoDB ที่ระบบใช้ (รันครั้งเดียว)

ต้องตั้งค่า AWS credentials ก่อน เช่น `aws configure` หรือ AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
รัน: python setup_aws.py
"""
import boto3

import config


def create_table(client, name):
    try:
        client.create_table(
            TableName=name,
            KeySchema=[{"AttributeName": "drone_id", "KeyType": "HASH"},
                       {"AttributeName": "ts", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "drone_id", "AttributeType": "S"},
                                  {"AttributeName": "ts", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        print(f"กำลังสร้างตาราง {name} ...")
        client.get_waiter("table_exists").wait(TableName=name)
        print(f"สร้างตาราง {name} แล้ว")
    except client.exceptions.ResourceInUseException:
        print(f"มีตาราง {name} อยู่แล้ว")


def main():
    client = boto3.client("dynamodb", region_name=config.AWS_REGION)
    create_table(client, config.DDB_TELEMETRY_TABLE)
    create_table(client, config.DDB_ALERT_TABLE)
    if config.DDB_TTL_DAYS > 0:
        try:
            client.update_time_to_live(
                TableName=config.DDB_TELEMETRY_TABLE,
                TimeToLiveSpecification={"Enabled": True, "AttributeName": "expires_at"})
            print(f"เปิด TTL: telemetry เก่ากว่า {config.DDB_TTL_DAYS} วันจะถูกลบอัตโนมัติ")
        except client.exceptions.ClientError as exc:
            if "already enabled" not in str(exc):
                raise


if __name__ == "__main__":
    main()
