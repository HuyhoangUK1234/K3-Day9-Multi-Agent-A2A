"""The agent team and the handoffs between them.

Division of labour: Python owns every fact, join, date comparison and money
calculation; the LLM agents interpret those facts, declare what they found,
flag what is missing, and hand the packet to the next agent. An 8B model is
not trusted to do arithmetic or to invent an ID.

Handoff packet (Codelab section 3 minimum):
    ticket_id, question, facts (with source IDs), missing, next_suggestion
"""

import json
from dataclasses import asdict, dataclass, field

from .data_store import OrderFacts
from .llm import LLMClient, parse_json_object
from .policy import PolicyDecision, decide


@dataclass
class Handoff:
    agent: str
    ticket_id: str
    question: str
    facts: dict = field(default_factory=dict)
    evidence_ids: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    next_suggestion: str = ""
    llm_raw: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _iso(value) -> str | None:
    return value.strftime("%Y-%m-%d %H:%M:%S") if value else None


# --------------------------------------------------------------------------
# Order & Seller Agent
# --------------------------------------------------------------------------
ORDER_SYSTEM = (
    "You are the Order & Seller Agent in an e-commerce dispute team. "
    "You receive verified order facts. Summarise the order state and whether any "
    "seller missed its carrier handoff deadline. Never invent IDs or dates. "
    'Reply ONLY with JSON: {"order_state":"...","seller_handoff":"on_time|late|unknown",'
    '"missing":[],"next_suggestion":"..."}'
)


def order_seller_agent(client: LLMClient, case_id: str, facts: OrderFacts) -> Handoff:
    late_sellers = facts.late_sellers()
    payload = {
        "order_id": facts.order_id,
        "found_in_dataset": facts.exists,
        "order_status": facts.order_status,
        "item_count": len(facts.items),
        "seller_ids": facts.seller_ids[:5],
        "delivered_carrier_date": _iso(facts.delivered_carrier_at),
        "shipping_limits": [
            {"order_item_id": i.order_item_id, "seller_id": i.seller_id,
             "shipping_limit_date": _iso(i.shipping_limit_date)}
            for i in facts.items[:5]
        ],
        "sellers_past_limit": late_sellers,
    }
    raw = client.chat(ORDER_SYSTEM, json.dumps(payload, ensure_ascii=False), max_tokens=200)
    parsed = parse_json_object(raw)

    missing: list[str] = []
    if not facts.exists:
        missing.append("order_id not present in olist_orders_dataset")
    if not facts.items:
        missing.append("order has no item rows")
    if facts.delivered_carrier_at is None:
        missing.append("order_delivered_carrier_date is empty")

    evidence = [f"order:{facts.order_id}"] if facts.exists else []
    evidence += [f"item:{facts.order_id}:{i.order_item_id}" for i in facts.items[:5]]
    evidence += [f"seller:{s}" for s in (late_sellers or facts.seller_ids)[:3]]

    return Handoff(
        agent="order_seller",
        ticket_id=case_id,
        question="What is the order state and did any seller hand off after its shipping limit?",
        facts={**payload, "agent_view": parsed.get("seller_handoff", "unknown")},
        evidence_ids=evidence,
        missing=missing + list(parsed.get("missing", []) or []),
        next_suggestion=parsed.get("next_suggestion", "hand to delivery agent"),
        llm_raw=raw,
    )


# --------------------------------------------------------------------------
# Payment Agent
# --------------------------------------------------------------------------
PAYMENT_SYSTEM = (
    "You are the Payment Agent. Reconcile the payment rows against item + freight totals. "
    "payment_value is the amount of ONE payment row, never a per-installment figure. "
    "Do not recompute the sums, they are given. Never invent a payment ID. "
    'Reply ONLY with JSON: {"reconciled":true|false,"split_payment":true|false,'
    '"missing":[],"next_suggestion":"..."}'
)


def payment_agent(client: LLMClient, case_id: str, facts: OrderFacts) -> Handoff:
    payload = {
        "order_id": facts.order_id,
        "payment_rows": [
            {"payment_sequential": p.payment_sequential, "payment_type": p.payment_type,
             "payment_value": p.payment_value}
            for p in facts.payments[:5]
        ],
        "payment_total": facts.payment_total,
        "item_total": facts.item_total,
        "freight_total": facts.freight_total,
        "expected_total": round(facts.item_total + facts.freight_total, 2),
        "reconciles_within_0_10": facts.payment_reconciles(),
    }
    raw = client.chat(PAYMENT_SYSTEM, json.dumps(payload, ensure_ascii=False), max_tokens=180)
    parsed = parse_json_object(raw)

    missing = [] if facts.payments else ["order has no payment rows"]
    evidence = [f"payment:{facts.order_id}:{p.payment_sequential}" for p in facts.payments[:5]]

    return Handoff(
        agent="payment",
        ticket_id=case_id,
        question="Do the payment rows reconcile against item + freight?",
        facts={**payload, "agent_view": parsed.get("reconciled")},
        evidence_ids=evidence,
        missing=missing + list(parsed.get("missing", []) or []),
        next_suggestion=parsed.get("next_suggestion", "hand to policy agent"),
        llm_raw=raw,
    )


# --------------------------------------------------------------------------
# Delivery Agent
# --------------------------------------------------------------------------
DELIVERY_SYSTEM = (
    "You are the Delivery Agent. Compare the actual delivery timestamp against the "
    "estimated delivery date. Timestamps are compared verbatim, no timezone conversion. "
    "The comparison result is given to you; explain it, do not recompute it. "
    'Reply ONLY with JSON: {"late":true|false,"blame":"seller|logistics_provider|none",'
    '"missing":[],"next_suggestion":"..."}'
)


def delivery_agent(client: LLMClient, case_id: str, facts: OrderFacts) -> Handoff:
    late_sellers = facts.late_sellers()
    payload = {
        "order_id": facts.order_id,
        "order_status": facts.order_status,
        "estimated_delivery_date": _iso(facts.estimated_delivery_at),
        "delivered_customer_date": _iso(facts.delivered_customer_at),
        "delivered_after_estimate": facts.delivered_late,
        "delivered_carrier_date": _iso(facts.delivered_carrier_at),
        "carrier_pickup_after_shipping_limit": bool(late_sellers),
    }
    raw = client.chat(DELIVERY_SYSTEM, json.dumps(payload, ensure_ascii=False), max_tokens=180)
    parsed = parse_json_object(raw)

    missing: list[str] = []
    if facts.delivered_customer_at is None:
        missing.append("order_delivered_customer_date is empty")
    if facts.estimated_delivery_at is None:
        missing.append("order_estimated_delivery_date is empty")

    return Handoff(
        agent="delivery",
        ticket_id=case_id,
        question="Was the order delivered after the estimate, and who caused the delay?",
        facts={**payload, "agent_view": parsed.get("blame", "none")},
        evidence_ids=[f"order:{facts.order_id}"] if facts.exists else [],
        missing=missing + list(parsed.get("missing", []) or []),
        next_suggestion=parsed.get("next_suggestion", "hand to policy agent"),
        llm_raw=raw,
    )


# --------------------------------------------------------------------------
# Policy Agent — LLM opinion, cross-checked against the deterministic engine
# --------------------------------------------------------------------------
POLICY_SYSTEM = (
    "You are the Policy Agent for EC_POLICY_V1. Rules are PRIORITY ORDERED; the first "
    "match wins even if a later rule also matches:\n"
    "1 canceled_order_paid: order_status=canceled AND payment_total>0\n"
    "2 unavailable_order_paid: order_status=unavailable AND payment_total>0\n"
    "3 late_delivery_seller: delivered after estimate AND carrier pickup after shipping_limit\n"
    "4 late_delivery_logistics: delivered after estimate AND carrier pickup not after shipping_limit\n"
    "5 valid_split_payment: 2+ payment rows AND payment total matches item+freight within 0.10\n"
    "6 unsupported_late_claim: delivered not after estimate AND payment matches\n"
    'Reply ONLY with JSON: {"primary_issue":"<one of the six>","confidence":0.0-1.0}'
)


def _blocking_gaps(facts: OrderFacts, decision: PolicyDecision) -> list[str]:
    """Missing fields that actually undermine the rule that fired.

    An unavailable order legitimately has no item rows — that is the expected
    shape of the data, not a gap, so it must not drag confidence down.
    """
    gaps: list[str] = []
    issue = decision.primary_issue

    if issue in {"canceled_order_paid", "unavailable_order_paid"}:
        if not facts.payments:
            gaps.append("no payment rows to size the refund")
    elif issue in {"late_delivery_seller", "late_delivery_logistics"}:
        if facts.delivered_customer_at is None:
            gaps.append("order_delivered_customer_date empty")
        if facts.estimated_delivery_at is None:
            gaps.append("order_estimated_delivery_date empty")
        if facts.delivered_carrier_at is None:
            gaps.append("order_delivered_carrier_date empty")
        if not facts.items:
            gaps.append("no item rows to size the freight refund")
    elif issue == "valid_split_payment":
        if len(facts.payments) < 2:
            gaps.append("fewer than 2 payment rows")
    elif issue == "unsupported_late_claim":
        if facts.delivered_customer_at is None or facts.estimated_delivery_at is None:
            gaps.append("delivery dates incomplete, cannot prove the claim is unsupported")

    return gaps


def policy_agent(
    client: LLMClient,
    case_id: str,
    facts: OrderFacts,
    upstream: list[Handoff],
) -> tuple[Handoff, PolicyDecision, float]:
    truth = decide(facts)

    payload = {
        "order_status": facts.order_status,
        "payment_total": facts.payment_total,
        "payment_row_count": len(facts.payments),
        "item_total": facts.item_total,
        "freight_total": facts.freight_total,
        "payment_reconciles": facts.payment_reconciles(),
        "delivered_after_estimate": facts.delivered_late,
        "carrier_pickup_after_shipping_limit": bool(facts.late_sellers()),
        "upstream_findings": [
            {"agent": h.agent, "view": h.facts.get("agent_view"), "missing": h.missing}
            for h in upstream
        ],
    }
    raw = client.chat(POLICY_SYSTEM, json.dumps(payload, ensure_ascii=False), max_tokens=120)
    parsed = parse_json_object(raw)
    llm_issue = parsed.get("primary_issue")

    # The deterministic engine is authoritative. The LLM's job is to agree or to
    # signal doubt; the disagreement is recorded in the trace but it does NOT
    # move confidence — an 8B model failing to follow a priority-ordered rule
    # table says nothing about how well the ruling is evidenced.
    #
    # Confidence therefore tracks evidence completeness only.
    agrees = llm_issue == truth.primary_issue

    if not facts.exists:
        # No order row means nothing can be evidenced at all.
        confidence = 0.40
    else:
        blocking = _blocking_gaps(facts, truth)
        confidence = 0.80 if blocking else 0.97

    handoff = Handoff(
        agent="policy",
        ticket_id=case_id,
        question="Which EC_POLICY_V1 rule fires first for this order?",
        facts={
            **payload,
            "deterministic_issue": truth.primary_issue,
            "llm_issue": llm_issue,
            "agreement": agrees,
        },
        evidence_ids=[f"policy:{truth.cause_code}"],
        missing=[] if agrees else ["llm disagreed with the deterministic policy engine"],
        next_suggestion="hand to verifier",
        llm_raw=raw,
    )
    return handoff, truth, confidence
