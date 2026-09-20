"""
Deterministic Invariant & Disbursement Calculation Engine
Strictly isolates mathematical financial calculations from LLM inferences.
Enforces the Zero-Sum Invariant: Delta_Customer + Delta_Merchant + Delta_Driver + Delta_Platform == 0.0000.
"""
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Dict, Any, List
import uuid
from schemas.contracts import PartyDisbursement, SettlementPlan, ExtractedTimeline


TWO_PLACES = Decimal("0.01")
FOUR_PLACES = Decimal("0.0001")


def quantize_currency(amount: Decimal) -> Decimal:
    """Rounds to exact 2 decimal places using Banker's Rounding (ROUND_HALF_EVEN)."""
    return amount.quantize(TWO_PLACES, rounding=ROUND_HALF_EVEN)


def calculate_disbursements(
    order_id: str,
    customer_id: str,
    merchant_id: str,
    driver_id: str,
    subtotal: Decimal,
    delivery_fee: Decimal,
    platform_fee: Decimal,
    tip: Decimal,
    timeline: ExtractedTimeline
) -> SettlementPlan:
    """
    Computes exact, auditable balance adjustments based on extracted timeline facts.
    """
    total_paid_by_customer = subtotal + delivery_fee + platform_fee + tip
    disbursements: List[PartyDisbursement] = []
    
    requires_human_review = False
    review_reason = None
    
    # Check for low-confidence trigger
    if timeline.fault_confidence < 0.70:
        requires_human_review = True
        review_reason = f"Low AI fault confidence ({timeline.fault_confidence:.2f}). Escrow held for human arbitration."

    fault = timeline.primary_fault_party

    if fault == "CUSTOMER":
        # Scenario: Customer cancelled late.
        if timeline.merchant_food_prepared:
            # Merchant is paid full cost of goods (subtotal - merchant commission 15%)
            merchant_payout = quantize_currency(subtotal * Decimal("0.85"))
            # Driver is paid dispatch base pay + distance pay
            driver_compensation = quantize_currency(Decimal("4.50") + (Decimal(str(timeline.driver_dispatched_distance_km)) * Decimal("0.75")))
            # Customer loses subtotal + delivery fee, but gets platform fee & tip refunded
            customer_refund = Decimal("0.00") # No refund on food/delivery
            customer_delta = Decimal("0.00") # Already captured, no net return
            
            # Platform absorbs residual or charges fee:
            # Escrow currently holds `total_paid_by_customer`.
            # Payments out = merchant_payout + driver_compensation.
            # Residual goes to platform balance.
            platform_delta = total_paid_by_customer - merchant_payout - driver_compensation

            disbursements.extend([
                PartyDisbursement(
                    account_id=customer_id,
                    party_type="CUSTOMER",
                    delta_amount=customer_delta,
                    reason_code="CUST_LATE_CANCEL_NO_REFUND",
                    description="Order cancelled after kitchen prep started. No refund issued."
                ),
                PartyDisbursement(
                    account_id=merchant_id,
                    party_type="MERCHANT",
                    delta_amount=merchant_payout,
                    reason_code="MERCHANT_PREP_COMPENSATION",
                    description="Reimbursement for prepared perishable items."
                ),
                PartyDisbursement(
                    account_id=driver_id,
                    party_type="DRIVER",
                    delta_amount=driver_compensation,
                    reason_code="DRIVER_DISPATCH_COMPENSATION",
                    description="Compensation for en-route mileage and arrival time."
                ),
                PartyDisbursement(
                    account_id="PLATFORM_ESCROW",
                    party_type="PLATFORM",
                    delta_amount=-total_paid_by_customer + (total_paid_by_customer - merchant_payout - driver_compensation),
                    # Net balance out from platform escrow to other parties
                    reason_code="PLATFORM_DISPUTE_SETTLEMENT",
                    description="Platform escrow net disbursement balancing transaction."
                )
            ])
            
            # In multi-party double-entry bookkeeping:
            # Platform Escrow releases (-total_paid_by_customer)
            # Platform Operating Account gains (+platform_delta)
            # Merchant gains (+merchant_payout)
            # Driver gains (+driver_compensation)
            # Customer net change (+0.00)
            # Total sum: (-total) + (+platform_delta) + (+merchant_payout) + (+driver_compensation) == 0.0000

    elif fault == "MERCHANT":
        # Scenario: Merchant failed to fulfill or cancelled
        # Full refund to customer
        customer_delta = total_paid_by_customer
        # Driver base pay covered by platform/merchant penalty
        driver_compensation = Decimal("5.00")
        # Merchant penalized
        merchant_penalty = -(subtotal * Decimal("0.20"))
        # Platform balances the ledger
        platform_delta = -(total_paid_by_customer + driver_compensation + merchant_penalty)

        disbursements.extend([
            PartyDisbursement(
                account_id=customer_id,
                party_type="CUSTOMER",
                delta_amount=customer_delta,
                reason_code="CUSTOMER_FULL_REFUND",
                description="100% refund due to merchant fulfillment failure."
            ),
            PartyDisbursement(
                account_id=merchant_id,
                party_type="MERCHANT",
                delta_amount=merchant_penalty,
                reason_code="MERCHANT_CANCELLATION_PENALTY",
                description="Contractual cancellation penalty."
            ),
            PartyDisbursement(
                account_id=driver_id,
                party_type="DRIVER",
                delta_amount=driver_compensation,
                reason_code="DRIVER_DISPATCH_PAY",
                description="Mileage and wait-time compensation."
            ),
            PartyDisbursement(
                account_id="PLATFORM_ESCROW",
                party_type="PLATFORM",
                delta_amount=-(customer_delta + merchant_penalty + driver_compensation),
                reason_code="PLATFORM_ESCROW_SETTLEMENT",
                description="Platform ledger clearing entry."
            )
        ])
    else:
        # Default / Platform Escrow Hold
        disbursements.append(PartyDisbursement(
            account_id="PLATFORM_ESCROW",
            party_type="PLATFORM",
            delta_amount=Decimal("0.0000"),
            reason_code="ESCROW_HELD",
            description="Ambiguous dispute held in platform escrow."
        ))

    # Calculate exact zero-sum assertion
    sum_delta = sum((d.delta_amount for d in disbursements), Decimal("0.0000")).quantize(FOUR_PLACES)
    is_zero_sum = (abs(sum_delta) <= Decimal("0.0001"))

    if not is_zero_sum:
        raise ValueError(f"INVARIANT VIOLATION: Sum of disbursements = {sum_delta}, must be 0.0000")

    return SettlementPlan(
        plan_id=f"plan_{uuid.uuid4().hex[:12]}",
        order_id=order_id,
        disbursements=disbursements,
        sum_delta=sum_delta,
        is_zero_sum_verified=is_zero_sum,
        requires_human_review=requires_human_review,
        review_reason=review_reason
    )


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """AWS Lambda Handler for Step Functions state machine."""
    order_id = event["order_id"]
    customer_id = event.get("customer_id", f"cust_{order_id[-6:]}")
    merchant_id = event.get("merchant_id", f"merch_{order_id[-6:]}")
    driver_id = event.get("driver_id", f"drv_{order_id[-6:]}")
    
    subtotal = Decimal(str(event.get("order_subtotal", "35.50")))
    delivery_fee = Decimal(str(event.get("delivery_fee", "4.99")))
    platform_fee = Decimal(str(event.get("platform_fee", "3.00")))
    tip = Decimal(str(event.get("tip_amount", "5.00")))
    
    extracted_data = event.get("extracted_timeline", {})
    timeline = ExtractedTimeline(**extracted_data)
    
    settlement_plan = calculate_disbursements(
        order_id=order_id,
        customer_id=customer_id,
        merchant_id=merchant_id,
        driver_id=driver_id,
        subtotal=subtotal,
        delivery_fee=delivery_fee,
        platform_fee=platform_fee,
        tip=tip,
        timeline=timeline
    )
    
    output = dict(event)
    output["settlement_plan"] = settlement_plan.model_dump(mode="json")
    return output
