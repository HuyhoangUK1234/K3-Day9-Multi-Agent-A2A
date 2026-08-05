"""EC_POLICY_V1 as a deterministic function.

The six rules in README section 4 are priority-ordered: the first rule whose
condition holds wins, even if a later rule would also match. A canceled order
that was ALSO delivered late is canceled_order_paid, not late_delivery_*.

Money is rounded to 2 decimals everywhere.
"""

from dataclasses import dataclass

from .data_store import OrderFacts

PLATFORM_PARTY_ID = "OLIST_PLATFORM"
LOGISTICS_PARTY_ID = "LOGISTICS_PROVIDER"

SPLIT_PAYMENT_TOLERANCE = 0.10


@dataclass
class PolicyDecision:
    primary_issue: str
    cause_code: str
    party_type: str | None
    party_id: str | None
    refund_brl: float
    action: str
    late_seller_ids: list[str]

    @property
    def case_status(self) -> str:
        # action_required means money moves; otherwise we only explain or reject.
        return "action_required" if self.refund_brl > 0 else "no_action"


def decide(facts: OrderFacts) -> PolicyDecision:
    payment_total = facts.payment_total
    freight_total = facts.freight_total

    # 1. canceled with money taken
    if facts.order_status == "canceled" and payment_total > 0:
        return PolicyDecision(
            primary_issue="canceled_order_paid",
            cause_code="ORDER_CANCELED_AFTER_PAYMENT",
            party_type="platform",
            party_id=PLATFORM_PARTY_ID,
            refund_brl=payment_total,
            action="issue_full_refund",
            late_seller_ids=[],
        )

    # 2. unavailable with money taken
    if facts.order_status == "unavailable" and payment_total > 0:
        return PolicyDecision(
            primary_issue="unavailable_order_paid",
            cause_code="ORDER_UNAVAILABLE_AFTER_PAYMENT",
            party_type="platform",
            party_id=PLATFORM_PARTY_ID,
            refund_brl=payment_total,
            action="issue_full_refund",
            late_seller_ids=[],
        )

    if facts.delivered_late:
        late_sellers = facts.late_sellers()
        # 3. late because the seller missed the carrier handoff deadline
        if late_sellers:
            return PolicyDecision(
                primary_issue="late_delivery_seller",
                cause_code="SELLER_HANDOFF_AFTER_LIMIT",
                party_type="seller",
                party_id=late_sellers[0],
                refund_brl=freight_total,
                action="refund_freight",
                late_seller_ids=late_sellers,
            )
        # 4. seller handed off on time, so the carrier owns the delay
        return PolicyDecision(
            primary_issue="late_delivery_logistics",
            cause_code="CARRIER_DELIVERED_AFTER_ESTIMATE",
            party_type="logistics_provider",
            party_id=LOGISTICS_PARTY_ID,
            refund_brl=freight_total,
            action="refund_freight",
            late_seller_ids=[],
        )

    # 5. multiple payment rows that reconcile against item + freight
    if len(facts.payments) >= 2 and facts.payment_reconciles(SPLIT_PAYMENT_TOLERANCE):
        return PolicyDecision(
            primary_issue="valid_split_payment",
            cause_code="MULTIPLE_PAYMENTS_RECONCILED",
            party_type=None,
            party_id=None,
            refund_brl=0.0,
            action="explain_valid_split_payment",
            late_seller_ids=[],
        )

    # 6. delivered within the estimate and the money adds up — claim rejected.
    # Also the safe fallback: no rule matched, so no refund is owed.
    return PolicyDecision(
        primary_issue="unsupported_late_claim",
        cause_code="DELIVERY_WITHIN_ESTIMATE",
        party_type=None,
        party_id=None,
        refund_brl=0.0,
        action="reject_late_refund",
        late_seller_ids=[],
    )
