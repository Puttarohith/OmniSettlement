"""
OmniSettlement Production Ingestion Service
Handles real-time HMAC-SHA256 signature validation, DynamoDB conditional idempotency, and SQS FIFO enqueueing.
"""
import os
import json
import hmac
import hashlib
import time
from typing import Dict, Any
import boto3
from botocore.exceptions import ClientError
from schemas.contracts import WebhookPayload, IngestionResponse


IDEMPOTENCY_TABLE = os.environ.get("IDEMPOTENCY_TABLE", "IdempotencyAndState")
SQS_QUEUE_URL = os.environ.get("SQS_QUEUE_URL", "")
HMAC_SECRET = os.environ.get("WEBHOOK_HMAC_SECRET", "")


def verify_hmac_signature(payload_bytes: bytes, signature_header: str, secret: str) -> bool:
    """Verifies HMAC-SHA256 signature against incoming webhooks."""
    if not signature_header or not secret:
        return False
    expected_sig = hmac.new(
        secret.encode("utf-8"),
        payload_bytes,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(f"sha256={expected_sig}", signature_header)


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Production AWS Lambda Handler for API Gateway Webhook Ingestion.
    """
    dynamodb = boto3.resource("dynamodb")
    sqs = boto3.client("sqs")
    
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    body_str = event.get("body", "{}")
    signature = headers.get("x-signature-sha256", "")
    
    # 1. Enforce HMAC Signature if secret is configured
    if HMAC_SECRET:
        if not verify_hmac_signature(body_str.encode("utf-8"), signature, HMAC_SECRET):
            return {
                "statusCode": 401,
                "body": json.dumps({"error": "UNAUTHORIZED", "message": "HMAC signature verification failed"})
            }
            
    # 2. Parse and strictly validate payload against Pydantic schema
    try:
        data = json.loads(body_str)
        payload = WebhookPayload(**data)
    except Exception as e:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "SCHEMA_VALIDATION_ERROR", "details": str(e)})
        }
        
    idempotency_table = dynamodb.Table(IDEMPOTENCY_TABLE)
    now_ts = int(time.time())
    ttl_ts = now_ts + (86400 * 30) # 30-day state retention
    
    # 3. Distributed Idempotency Lock via DynamoDB Conditional Put
    try:
        idempotency_table.put_item(
            Item={
                "idempotency_key": payload.idempotency_key,
                "event_id": payload.event_id,
                "order_id": payload.order_id,
                "status": "PROCESSING",
                "created_at": now_ts,
                "expires_at": ttl_ts,
                "payload": data
            },
            ConditionExpression="attribute_not_exists(idempotency_key)"
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return {
                "statusCode": 200,
                "body": json.dumps({
                    "status": "DUPLICATE_IGNORED",
                    "idempotency_key": payload.idempotency_key,
                    "message": "Event already ingested. Exactly-once idempotency applied."
                })
            }
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "DATABASE_ERROR", "details": str(e)})
        }
        
    # 4. Enqueue into SQS FIFO (Partitioned by order_id)
    try:
        sqs_response = sqs.send_message(
            QueueUrl=SQS_QUEUE_URL,
            MessageBody=json.dumps(payload.model_dump(mode="json")),
            MessageGroupId=payload.order_id,
            MessageDeduplicationId=payload.idempotency_key
        )
        message_id = sqs_response.get("MessageId")
    except Exception as e:
        idempotency_table.update_item(
            Key={"idempotency_key": payload.idempotency_key},
            UpdateExpression="SET #st = :failed",
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={":failed": "FAILED_ENQUEUE"}
        )
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "QUEUE_DISPATCH_ERROR", "details": str(e)})
        }
        
    response = IngestionResponse(
        status="ACCEPTED",
        event_id=payload.event_id,
        idempotency_key=payload.idempotency_key,
        message="Event successfully verified and queued for saga execution.",
        sqs_message_id=message_id
    )
    
    return {
        "statusCode": 202,
        "body": json.dumps(response.model_dump())
    }
