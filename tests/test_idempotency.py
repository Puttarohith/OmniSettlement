"""
Unit Tests for Ingestion HMAC and Idempotency
"""
import json
import hmac
import hashlib
from schemas.contracts import WebhookPayload, DisputeReason
from services.ingestion import verify_hmac_signature


def test_hmac_signature_verification():
    secret = "secret-key-123"
    payload = b'{"event_id":"evt_1","order_id":"ord_1"}'
    valid_sig = "sha256=" + hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    
    assert verify_hmac_signature(payload, valid_sig, secret) is True
    assert verify_hmac_signature(payload, "sha256=invalidhash", secret) is False
    assert verify_hmac_signature(payload, "", secret) is False


def test_webhook_payload_validation():
    data = {
        "event_id": "evt_test_100",
        "idempotency_key": "idemp_test_abc",
        "order_id": "ord_999",
        "timestamp_utc": "2026-09-18T18:30:00Z",
        "reason": "CUSTOMER_CANCELLED_LATE",
        "customer_id": "cust_1",
        "merchant_id": "merch_1",
        "driver_id": "drv_1",
        "order_subtotal": "28.50",
        "delivery_fee": "3.99",
        "platform_fee": "2.50",
        "tip_amount": "4.00"
    }
    payload = WebhookPayload(**data)
    assert payload.total_order_value == payload.order_subtotal + payload.delivery_fee + payload.platform_fee + payload.tip_amount
