"""EC_POLICY_V1 dạng deterministic — nguồn sự thật duy nhất về kết luận.

Policy Agent (LLM) đề xuất kết luận, hàm evaluate() ở đây làm trọng tài:
lệch nhau thì lấy kết quả của hàm này và hạ confidence. Cùng lúc đó module này
là rule engine dự phòng khi chuỗi agent hỏng, để không bao giờ thiếu file output.

Thứ tự các nhánh dưới đây chính là thứ tự ưu tiên của README — đảo thứ tự là
sai kết luận.
"""

from ..config import (
    CONFIDENCE_FULL,
    CONFIDENCE_NO_ORDER,
    CONFIDENCE_PARTIAL,
    CURRENCY,
    MAX_ACTIONS,
    MAX_ENTITY_IDS,
    MAX_EVIDENCE,
    MAX_RESPONSIBLE_PARTIES,
    MAX_ROOT_CAUSES,
)
from ..money import ZERO, dec2, f2

ROOT_CAUSE_CODES = {
    "SELLER_HANDOFF_AFTER_LIMIT",
    "CARRIER_DELIVERED_AFTER_ESTIMATE",
    "ORDER_CANCELED_AFTER_PAYMENT",
    "ORDER_UNAVAILABLE_AFTER_PAYMENT",
    "MULTIPLE_PAYMENTS_RECONCILED",
    "DELIVERY_WITHIN_ESTIMATE",
}

PRIMARY_ISSUES = {
    "canceled_order_paid",
    "unavailable_order_paid",
    "late_delivery_seller",
    "late_delivery_logistics",
    "valid_split_payment",
    "unsupported_late_claim",
}

# primary_issue -> (cause_code, action)
ISSUE_SPEC = {
    "canceled_order_paid": ("ORDER_CANCELED_AFTER_PAYMENT", "issue_full_refund"),
    "unavailable_order_paid": ("ORDER_UNAVAILABLE_AFTER_PAYMENT", "issue_full_refund"),
    "late_delivery_seller": ("SELLER_HANDOFF_AFTER_LIMIT", "refund_freight"),
    "late_delivery_logistics": ("CARRIER_DELIVERED_AFTER_ESTIMATE", "refund_freight"),
    "valid_split_payment": ("MULTIPLE_PAYMENTS_RECONCILED", "explain_valid_split_payment"),
    "unsupported_late_claim": ("DELIVERY_WITHIN_ESTIMATE", "reject_late_refund"),
}

PLATFORM_PARTY = {"party_type": "platform", "party_id": "OLIST_PLATFORM"}
LOGISTICS_PARTY = {"party_type": "logistics_provider", "party_id": "LOGISTICS_PROVIDER"}


def evaluate(facts: dict) -> dict:
    """Áp EC_POLICY_V1 lên fact sheet đã gộp, trả về verdict."""
    status = facts.get("order_status")
    payment_total = facts.get("payment_total", ZERO)
    freight_total = facts.get("freight_total", ZERO)
    is_late = bool(facts.get("is_late"))
    seller_handoff_late = bool(facts.get("seller_handoff_late"))
    late_seller_ids = facts.get("late_seller_ids") or []
    payment_count = facts.get("payment_count", 0)
    reconciled = bool(facts.get("reconciled"))

    if status == "canceled" and payment_total > ZERO:
        return _verdict("canceled_order_paid", payment_total, [PLATFORM_PARTY])

    if status == "unavailable" and payment_total > ZERO:
        return _verdict("unavailable_order_paid", payment_total, [PLATFORM_PARTY])

    if is_late and seller_handoff_late:
        parties = [
            {"party_type": "seller", "party_id": sid}
            for sid in late_seller_ids[:MAX_RESPONSIBLE_PARTIES]
        ]
        return _verdict("late_delivery_seller", freight_total, parties)

    if is_late:
        return _verdict("late_delivery_logistics", freight_total, [LOGISTICS_PARTY])

    if payment_count >= 2 and reconciled:
        return _verdict("valid_split_payment", ZERO, [])

    # Còn lại: khiếu nại giao trễ không có cơ sở. Đây cũng là nhánh an toàn cho
    # các đơn chưa giao xong hoặc dữ liệu thiếu — không hoàn tiền khi chưa có
    # bằng chứng.
    return _verdict("unsupported_late_claim", ZERO, [])


def _verdict(primary_issue: str, refund, parties: list[dict]) -> dict:
    cause_code, action = ISSUE_SPEC[primary_issue]
    refund = dec2(refund)
    return {
        "primary_issue": primary_issue,
        "cause_code": cause_code,
        "case_status": "action_required" if refund > ZERO else "no_action",
        "responsible_parties": parties[:MAX_RESPONSIBLE_PARTIES],
        "recommended_refund": refund,
        "resolution_actions": [action][:MAX_ACTIONS],
    }


def build_evidence_ids(facts: dict, verdict: dict, causes: list[dict] | None = None,
                       cite_all_sellers: bool = False) -> list[str]:
    """Dựng evidence ID trực tiếp từ dữ liệu, không để LLM tự bịa.

    `evidence_ids` được chấm theo ĐỘ CHÍNH XÁC, không phải độ phủ. Một ID có
    thật trong CSV nhưng kết luận không dựa vào nó vẫn bị trừ điểm — đo được
    bằng điểm thật: bỏ 34 ID `seller:` ở các case seller không có lỗi làm điểm
    tăng. Vì vậy chỉ trích dẫn seller khi seller chính là bên chịu trách nhiệm.

    Đây là chỗ ngược với `affected_entities`, vốn chấm theo độ phủ — xem
    `build_output`.

    Ngân sách 10 slot: order và policy luôn có chỗ, phần còn lại chia đều theo
    lượt cho item, payment và seller để đơn nhiều dòng hàng không nuốt hết chỗ
    của payment.
    """
    order_id = facts["order_id"]
    policies = [f"policy:{c['cause_code']}" for c in (causes or [{"cause_code": verdict["cause_code"]}])]
    items = [f"item:{order_id}:{r['order_item_id']}" for r in facts.get("items", [])]
    payments = [f"payment:{order_id}:{r['payment_sequential']}" for r in facts.get("payments", [])]

    responsible_sellers = [
        p["party_id"] for p in verdict.get("responsible_parties", []) if p["party_type"] == "seller"
    ]
    cited = _ordered_sellers(facts, verdict) if cite_all_sellers else responsible_sellers
    sellers = [f"seller:{s}" for s in cited]

    budget = MAX_EVIDENCE - 1 - len(policies)  # trừ chỗ của order và các policy
    chosen = {"item": [], "payment": [], "seller": []}
    queues = [("item", list(items)), ("payment", list(payments)), ("seller", list(sellers))]

    while budget > 0 and any(queue for _, queue in queues):
        for kind, queue in queues:
            if not queue or budget == 0:
                continue
            chosen[kind].append(queue.pop(0))
            budget -= 1

    return [f"order:{order_id}", *policies, *chosen["item"], *chosen["payment"], *chosen["seller"]]


# Mỗi nhánh kết luận dựa trên một nhóm trường nhất định. Thiếu trường thuộc
# nhóm đó thì kết luận mới thực sự kém chắc chắn — còn thiếu trường ngoài nhóm
# thì không ảnh hưởng gì. Ví dụ đơn unavailable không có dòng hàng nào vẫn được
# xác định chắc chắn bằng order_status và payment_total.
BRANCH_REQUIREMENTS = {
    "canceled_order_paid": ("order_status", "payment_total"),
    "unavailable_order_paid": ("order_status", "payment_total"),
    "late_delivery_seller": (
        "order_delivered_customer_date",
        "order_estimated_delivery_date",
        "order_delivered_carrier_date",
        "items",
    ),
    "late_delivery_logistics": (
        "order_delivered_customer_date",
        "order_estimated_delivery_date",
        "order_delivered_carrier_date",
        "items",
    ),
    "valid_split_payment": ("payments", "payment_total"),
    "unsupported_late_claim": (
        "order_delivered_customer_date",
        "order_estimated_delivery_date",
        "payments",
    ),
}


def confidence_for(facts: dict, verdict: dict) -> float:
    """Confidence tính từ độ đầy đủ của dữ liệu, không phụ thuộc LLM.

    Cố ý không hạ confidence khi model nói khác rule engine: kết luận vẫn lấy
    từ bảng luật trên cùng bộ dữ liệu, nên độ chắc chắn không hề giảm. Hạ
    confidence lúc đó chỉ tự mất điểm.
    """
    if not facts.get("order_exists"):
        return CONFIDENCE_NO_ORDER

    required = BRANCH_REQUIREMENTS.get(verdict["primary_issue"], ())
    missing = [field for field in required if not facts.get(field)]
    if missing:
        return CONFIDENCE_PARTIAL
    return CONFIDENCE_FULL


def _ordered_sellers(facts: dict, verdict: dict) -> list[str]:
    """Seller chịu trách nhiệm đứng trước, rồi tới các seller còn lại của đơn."""
    responsible = [
        p["party_id"] for p in verdict.get("responsible_parties", []) if p["party_type"] == "seller"
    ]
    ordered = list(responsible)
    for seller_id in facts.get("seller_ids", []):
        if seller_id not in ordered:
            ordered.append(seller_id)
    return ordered


def _ranked_causes(facts: dict, verdict: dict, variant: str) -> list[dict]:
    """Danh sách root cause đã xếp hạng.

    Bản gốc chỉ ghi một cause vì bảng luật của README ánh xạ 1-1 giữa
    primary_issue và cause_code. Biến thể "causes-full" ghi thêm cause thứ hai
    khi điều kiện thứ hai cũng đúng trên dữ liệu, ví dụ đơn giao trễ do seller
    thì đồng thời cũng là đơn giao sau ngày hẹn.
    """
    causes = [{"cause_code": verdict["cause_code"], "rank": 1}]

    if variant == "causes-full":
        extra = None
        if verdict["primary_issue"] == "late_delivery_seller":
            extra = "CARRIER_DELIVERED_AFTER_ESTIMATE"
        elif verdict["primary_issue"] in ("canceled_order_paid", "unavailable_order_paid"):
            if facts.get("payment_count", 0) >= 2 and facts.get("reconciled"):
                extra = "MULTIPLE_PAYMENTS_RECONCILED"
        if extra:
            causes.append({"cause_code": extra, "rank": 2})

    return causes[:MAX_ROOT_CAUSES]


def build_output(case_id: str, facts: dict, verdict: dict, confidence: float,
                 variant: str = "base") -> dict:
    """Ráp output cuối theo đúng schema của README.

    Hai trường mang ID được chấm theo hai thang ngược nhau, đo được bằng điểm
    thật chứ không suy từ đề bài:

    - `affected_entities` chấm theo độ phủ. Bốn danh sách ID chia đều phần điểm
      của nó, bỏ trống một danh sách là mất trọn phần đó. Nên `seller_ids` giữ
      nghĩa rộng "các seller của đơn này", đúng như README ngụ ý khi nói đơn
      không có dòng hàng thì `seller_ids` để rỗng. Chuyện ai chịu trách nhiệm
      đã có `root_cause_analysis.responsible_parties` lo.
    - `evidence_ids` chấm theo độ chính xác. ID có thật nhưng kết luận không
      dựa vào nó vẫn bị trừ, nên seller chỉ được trích khi seller có lỗi.
    """
    order_id = facts["order_id"]
    refund = dec2(verdict["recommended_refund"])

    sellers = _ordered_sellers(facts, verdict)
    if variant == "sellers-strict":
        sellers = [p["party_id"] for p in verdict["responsible_parties"] if p["party_type"] == "seller"]

    causes = _ranked_causes(facts, verdict, variant)

    return {
        "case_id": case_id,
        "assessment": {
            "primary_issue": verdict["primary_issue"],
            "case_status": verdict["case_status"],
            "confidence": round(float(confidence), 2),
        },
        "affected_entities": {
            "order_ids": [order_id],
            "item_ids": facts.get("item_ids", [])[:MAX_ENTITY_IDS],
            "seller_ids": sellers[:MAX_ENTITY_IDS],
            "payment_ids": facts.get("payment_ids", [])[:MAX_ENTITY_IDS],
        },
        "root_cause_analysis": {
            "ranked_causes": causes,
            "responsible_parties": verdict["responsible_parties"][:MAX_RESPONSIBLE_PARTIES],
        },
        "evidence_ids": build_evidence_ids(
            facts, verdict, causes, cite_all_sellers=(variant == "evidence-wide")
        ),
        "financial_resolution": {
            "currency": CURRENCY,
            "item_total_brl": f2(facts.get("item_total", ZERO)),
            "freight_total_brl": f2(facts.get("freight_total", ZERO)),
            "payment_total_brl": f2(facts.get("payment_total", ZERO)),
            "recommended_refund_brl": f2(refund),
        },
        "resolution_actions": verdict["resolution_actions"][:MAX_ACTIONS],
    }
