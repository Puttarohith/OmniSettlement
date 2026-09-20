"""
Unit Tests for Deterministic Invariant Engine
Tests precision, zero-sum invariant assertions, Banker's rounding, and multi-party policy balance.
"""
from decimal import Decimal
import pytest
from schemas.contracts import ExtractedTimeline, TimelineEvent, TimelineEventType
from services.invariant_engine import calculate_disbursements, quantize_currency


def test_quantize_currency_bankers_rounding():
    """Verify standard Banker's Rounding (ROUND_HALF_EVEN)."""
    assert quantize_currency(Decimal("10.005")) == Decimal("10.00")
    assert quantize_currency(Decimal("10.015")) == Decimal("10.02")
    assert quantize_currency(Decimal("10.025")) == Decimal("10.02")
    assert quantize_currency(Decimal("10.035")) == Decimal("10.04")


def test_customer_late_cancellation_zero_sum():
    """Verify customer late cancel generates strictly zero-sum ledger adjustment."""
    timeline = ExtractedTimeline(
        order_id="ord_test_001",
        primary_fault_party="CUSTOMER",
        fault_confidence=0.95,
        merchant_food_prepared=True,
        driver_dispatched_distance_km=3.5,
        timeline=[
            TimelineEvent(
                timestamp_utc="2026-09-18T18:00:00Z",
                event_type=TimelineEventType.ORDER_PLACED,
                actor="CUSTOMER",
                evidence_source="DATABASE",
                details="Order submitted"
            )
        ],
        citations=["pos:ticket_printed"],
        reasoning_summary="Customer cancelled after food prepared."
    )

    plan = calculate_disbursements(
        order_id="ord_test_001",
        customer_id="cust_101",
        merchant_id="merch_202",
        driver_id="drv_303",
        subtotal=Decimal("45.00"),
        delivery_fee=Decimal("5.99"),
        platform_fee=Decimal("3.50"),
        tip=Decimal("6.00"),
        timeline=timeline
    )

    assert plan.is_zero_sum_verified is True
    assert plan.sum_delta == Decimal("0.0000")
    assert plan.requires_human_review is False

    # Check merchant received 85% of subtotal = $38.25
    merchant_disbursement = next(d for d in plan.disbursements if d.party_type == "MERCHANT")
    assert merchant_disbursement.delta_amount == Decimal("38.25")

    # Check driver received base $4.50 + 3.5 * $0.75 = $7.12
    driver_disbursement = next(d for d in plan.disbursements if d.party_type == "DRIVER")
    assert driver_disbursement.delta_amount == Decimal("7.12")


def test_merchant_failure_zero_sum():
    """Verify merchant fulfillment failure yields 100% customer refund and balanced platform escrow."""
    timeline = ExtractedTimeline(
        order_id="ord_test_002",
        primary_fault_party="MERCHANT",
        fault_confidence=0.98,
        merchant_food_prepared=False,
        driver_dispatched_distance_km=1.2,
        timeline=[],
        citations=["pos:rejected"],
        reasoning_summary="Merchant kitchen out of ingredients."
    )

    plan = calculate_disbursements(
        order_id="ord_test_002",
        customer_id="cust_101",
        merchant_id="merch_202",
        driver_id="drv_303",
        subtotal=Decimal("30.00"),
        delivery_fee=Decimal("4.00"),
        platform_fee=Decimal("2.50"),
        tip=Decimal("4.00"),
        timeline=timeline
    )

    assert plan.is_zero_sum_verified is True
    assert plan.sum_delta == Decimal("0.0000")

    # Customer gets full order value refunded ($40.50)
    customer_d = next(d for d in plan.disbursements if d.party_type == "CUSTOMER")
    assert customer_d.delta_amount == Decimal("40.50")


def test_low_confidence_triggers_human_review():
    """Verify confidence below 0.70 holds escrow for human arbitration."""
    timeline = ExtractedTimeline(
        order_id="ord_test_003",
        primary_fault_party="CUSTOMER",
        fault_confidence=0.55,  # Low confidence
        merchant_food_prepared=False,
        driver_dispatched_distance_km=0.0,
        timeline=[],
        citations=[],
        reasoning_summary="Conflicting telemetry timestamps."
    )

    plan = calculate_disbursements(
        order_id="ord_test_003",
        customer_id="cust_101",
        merchant_id="merch_202",
        driver_id="drv_303",
        subtotal=Decimal("20.00"),
        delivery_fee=Decimal("3.00"),
        platform_fee=Decimal("2.00"),
        tip=Decimal("0.00"),
        timeline=timeline
    )

    assert plan.requires_human_review is True
    assert "Low AI fault confidence" in (plan.review_reason or "")
    assert plan.is_zero_sum_verified is True
