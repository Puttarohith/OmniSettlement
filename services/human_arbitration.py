"""
OmniSettlement Human Arbitration & Dispute Escalation Service
Handles human reviewer decisions on escrow-held disputes, verifying zero-sum balances before ledger commit.
"""
from decimal import Decimal
from typing import Dict, Any
from schemas.contracts import SettlementPlan, PartyDisbursement


def apply_human_arbitration_decision(
    order_id: str,
    decision_type: str,
    customer_id: str,
    merchant_id: str,
    driver_id: str,
    total_order_value: Decimal,
    reviewer_notes: str = ""
) -> SettlementPlan:
    """
    Constructs an auditable, zero-sum settlement plan based on human adjudicator ruling.
    """
    disbursements = []

    if decision_type == "SPLIT_FAULT_50_50":
        # Split loss equally between Platform and Merchant; refund 50% to customer
        half_val = (total_order_value * Decimal("0.50")).quantize(Decimal("0.01"))
        driver_pay = Decimal("5.00")
        
        disbursements.extend([
            PartyDisbursement(
                account_id=customer_id,
                party_type="CUSTOMER",
                delta_amount=half_val,
                reason_code="ARBITRATION_50_PERCENT_REFUND",
                description="Human arbitration: 50% courtesy refund."
            ),
            PartyDisbursement(
                account_id=merchant_id,
                party_type="MERCHANT",
                delta_amount=half_val - driver_pay,
                reason_code="ARBITRATION_MERCHANT_SETTLEMENT",
                description="Human arbitration: Partial payout minus driver coverage."
            ),
            PartyDisbursement(
                account_id=driver_id,
                party_type="DRIVER",
                delta_amount=driver_pay,
                reason_code="ARBITRATION_DRIVER_BASE_PAY",
                description="Human arbitration: Driver dispatch pay."
            ),
            PartyDisbursement(
                account_id="PLATFORM_ESCROW",
                party_type="PLATFORM",
                delta_amount=-total_order_value,
                reason_code="ARBITRATION_ESCROW_RELEASE",
                description=f"Human arbitration approved release. Reviewer notes: {reviewer_notes}"
            )
        ])

    elif decision_type == "RULE_FOR_CUSTOMER":
        # Full customer refund
        driver_pay = Decimal("4.50")
        disbursements.extend([
            PartyDisbursement(
                account_id=customer_id,
                party_type="CUSTOMER",
                delta_amount=total_order_value,
                reason_code="ARBITRATION_FULL_REFUND",
                description="Adjudicated in favor of customer."
            ),
            PartyDisbursement(
                account_id=merchant_id,
                party_type="MERCHANT",
                delta_amount=Decimal("0.00"),
                reason_code="ARBITRATION_MERCHANT_NO_PAY",
                description="Adjudicated: Merchant at fault."
            ),
            PartyDisbursement(
                account_id=driver_id,
                party_type="DRIVER",
                delta_amount=driver_pay,
                reason_code="ARBITRATION_DRIVER_PAY",
                description="Driver base compensation covered by platform."
            ),
            PartyDisbursement(
                account_id="PLATFORM_ESCROW",
                party_type="PLATFORM",
                delta_amount=-(total_order_value + driver_pay),
                reason_code="ARBITRATION_PLATFORM_ABSORB",
                description="Platform absorbed driver fee."
            )
        ])

    else:
        # Default: RULE_FOR_MERCHANT
        merchant_payout = (total_order_value * Decimal("0.85")).quantize(Decimal("0.01"))
        driver_pay = Decimal("5.00")
        disbursements.extend([
            PartyDisbursement(
                account_id=customer_id,
                party_type="CUSTOMER",
                delta_amount=Decimal("0.00"),
                reason_code="ARBITRATION_NO_REFUND",
                description="Adjudicated in favor of merchant."
            ),
            PartyDisbursement(
                account_id=merchant_id,
                party_type="MERCHANT",
                delta_amount=merchant_payout,
                reason_code="ARBITRATION_MERCHANT_PAYOUT",
                description="Full merchant fulfillment payout."
            ),
            PartyDisbursement(
                account_id=driver_id,
                party_type="DRIVER",
                delta_amount=driver_pay,
                reason_code="ARBITRATION_DRIVER_PAYOUT",
                description="Driver completed delivery attempt."
            ),
            PartyDisbursement(
                account_id="PLATFORM_ESCROW",
                party_type="PLATFORM",
                delta_amount=-(merchant_payout + driver_pay),
                reason_code="ARBITRATION_ESCROW_RELEASE",
                description="Escrow balance released to merchant & driver."
            )
        ])

    sum_delta = sum((d.delta_amount for d in disbursements), Decimal("0.0000")).quantize(Decimal("0.0001"))
    if abs(sum_delta) > Decimal("0.0001"):
        raise ValueError(f"CRITICAL: Human arbitration disbursement violation. Sum = {sum_delta}")

    return SettlementPlan(
        plan_id=f"plan_arb_{order_id[-6:]}",
        order_id=order_id,
        disbursements=disbursements,
        sum_delta=sum_delta,
        is_zero_sum_verified=True,
        requires_human_review=False,
        review_reason=f"Resolved via Human Adjudication ({decision_type})"
    )
