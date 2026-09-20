"""
OmniSettlement Data Contracts & Pydantic Models
Enforces strict schema constraints for all data passing through the event pipeline.
"""
from decimal import Decimal
from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator


class DisputeReason(str, Enum):
    CUSTOMER_CANCELLED_LATE = "CUSTOMER_CANCELLED_LATE"
    MERCHANT_UNABLE_TO_FULFILL = "MERCHANT_UNABLE_TO_FULFILL"
    DRIVER_ACCIDENT_OR_DELAY = "DRIVER_ACCIDENT_OR_DELAY"
    WRONG_ITEMS_DELIVERED = "WRONG_ITEMS_DELIVERED"
    ADDRESS_UNREACHABLE = "ADDRESS_UNREACHABLE"
    FRAUDULENT_ORDER = "FRAUDULENT_ORDER"


class WebhookPayload(BaseModel):
    """Raw incoming webhook payload from API Gateway."""
    event_id: str = Field(..., description="Unique event ID for tracing")
    idempotency_key: str = Field(..., description="Client-provided idempotency key")
    order_id: str = Field(..., description="Order identifier")
    timestamp_utc: str = Field(..., description="ISO 8601 UTC timestamp")
    reason: DisputeReason
    customer_id: str
    merchant_id: str
    driver_id: str
    order_subtotal: Decimal = Field(..., description="Base subtotal amount in USD")
    delivery_fee: Decimal = Field(..., description="Delivery fee paid by customer")
    platform_fee: Decimal = Field(..., description="Platform commission fee")
    tip_amount: Decimal = Field(default=Decimal("0.00"), description="Driver tip amount")
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @property
    def total_order_value(self) -> Decimal:
        return self.order_subtotal + self.delivery_fee + self.platform_fee + self.tip_amount


class IngestionResponse(BaseModel):
    status: str
    event_id: str
    idempotency_key: str
    message: str
    sqs_message_id: Optional[str] = None


class TimelineEventType(str, Enum):
    ORDER_PLACED = "ORDER_PLACED"
    MERCHANT_ACCEPTED = "MERCHANT_ACCEPTED"
    MERCHANT_PREP_STARTED = "MERCHANT_PREP_STARTED"
    MERCHANT_PREP_COMPLETED = "MERCHANT_PREP_COMPLETED"
    DRIVER_ASSIGNED = "DRIVER_ASSIGNED"
    DRIVER_ARRIVED_AT_STORE = "DRIVER_ARRIVED_AT_STORE"
    DRIVER_PICKED_UP = "DRIVER_PICKED_UP"
    CUSTOMER_CANCELLATION_REQUESTED = "CUSTOMER_CANCELLATION_REQUESTED"
    DRIVER_REPORTED_ISSUE = "DRIVER_REPORTED_ISSUE"


class TimelineEvent(BaseModel):
    timestamp_utc: str
    event_type: TimelineEventType
    actor: str
    evidence_source: str
    details: str


class ExtractedTimeline(BaseModel):
    """Structured output expected from Bedrock agent reasoning."""
    order_id: str
    primary_fault_party: str = Field(..., description="CUSTOMER | MERCHANT | DRIVER | PLATFORM | FORCE_MAJEURE")
    fault_confidence: float = Field(..., ge=0.0, le=1.0)
    merchant_food_prepared: bool
    driver_dispatched_distance_km: float = Field(default=0.0)
    timeline: List[TimelineEvent]
    citations: List[str] = Field(default_factory=list, description="Exact offsets or log snippet IDs")
    reasoning_summary: str

    @field_validator("fault_confidence")
    def validate_confidence(cls, v: float) -> float:
        if v < 0.0 or v > 1.0:
            raise ValueError("Confidence must be between 0.0 and 1.0")
        return v


class PartyDisbursement(BaseModel):
    account_id: str
    party_type: str = Field(..., description="CUSTOMER | MERCHANT | DRIVER | PLATFORM")
    delta_amount: Decimal = Field(..., description="Signed decimal adjustment in USD. Negative = debit/refund, Positive = credit/payout")
    reason_code: str
    description: str


class SettlementPlan(BaseModel):
    """Deterministic output from the invariant engine."""
    plan_id: str
    order_id: str
    disbursements: List[PartyDisbursement]
    sum_delta: Decimal = Field(..., description="Must strictly equal Decimal('0.0000')")
    is_zero_sum_verified: bool
    requires_human_review: bool
    review_reason: Optional[str] = None

    @field_validator("sum_delta")
    def validate_zero_sum(cls, v: Decimal) -> Decimal:
        if abs(v) > Decimal("0.0001"):
            raise ValueError(f"CRITICAL INVARIANT VIOLATION: Sum of disbursements ({v}) does not equal 0.0000")
        return v
