"""
Unit Tests for Bedrock Extractor Schema Compliance and Anti-Hallucination Guardrails
"""
from schemas.contracts import ExtractedTimeline, TimelineEvent, TimelineEventType
from services.bedrock_extractor import fallback_deterministic_extractor


def test_fallback_extractor_customer_late_cancel():
    evidence_packet = {
        "order_id": "ord_eval_01",
        "telemetry": {
            "merchant_pos_events": [
                {"timestamp": "2026-09-18T18:05:00Z", "event": "KITCHEN_MARKED_PREPARED"}
            ],
            "chat_logs": [
                {"timestamp": "2026-09-18T18:15:00Z", "sender": "CUSTOMER", "text": "Cancel the order please"}
            ]
        }
    }
    extracted = fallback_deterministic_extractor(evidence_packet)
    assert isinstance(extracted, ExtractedTimeline)
    assert extracted.primary_fault_party == "CUSTOMER"
    assert extracted.merchant_food_prepared is True
    assert extracted.fault_confidence >= 0.90
    assert len(extracted.timeline) >= 2


def test_fallback_extractor_merchant_fault():
    evidence_packet = {
        "order_id": "ord_eval_02",
        "telemetry": {
            "merchant_pos_events": [],
            "chat_logs": [
                {"timestamp": "2026-09-18T18:15:00Z", "sender": "MERCHANT", "text": "We cannot fulfill"}
            ]
        }
    }
    extracted = fallback_deterministic_extractor(evidence_packet)
    assert extracted.primary_fault_party == "MERCHANT"
    assert extracted.merchant_food_prepared is False
