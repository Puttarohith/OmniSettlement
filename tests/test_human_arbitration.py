"""
Unit Tests for Human-in-the-Loop Dispute Arbitration Service
"""
from decimal import Decimal
import pytest
from services.human_arbitration import apply_human_arbitration_decision


def test_split_fault_50_50_zero_sum():
    plan = apply_human_arbitration_decision(
        order_id="ord_arb_001",
        decision_type="SPLIT_FAULT_50_50",
        customer_id="cust_4401",
        merchant_id="merch_8812",
        driver_id="drv_9934",
        total_order_value=Decimal("80.00"),
        reviewer_notes="Test courtesy split"
    )
    assert plan.is_zero_sum_verified is True
    assert plan.sum_delta == Decimal("0.0000")
    assert plan.requires_human_review is False
    
    # Check customer received 50% refund = $40.00
    cust_d = next(d for d in plan.disbursements if d.party_type == "CUSTOMER")
    assert cust_d.delta_amount == Decimal("40.00")


def test_rule_for_customer_zero_sum():
    plan = apply_human_arbitration_decision(
        order_id="ord_arb_002",
        decision_type="RULE_FOR_CUSTOMER",
        customer_id="cust_4401",
        merchant_id="merch_8812",
        driver_id="drv_9934",
        total_order_value=Decimal("60.00"),
        reviewer_notes="Merchant admitted package damaged"
    )
    assert plan.is_zero_sum_verified is True
    assert plan.sum_delta == Decimal("0.0000")
    
    cust_d = next(d for d in plan.disbursements if d.party_type == "CUSTOMER")
    assert cust_d.delta_amount == Decimal("60.00")
