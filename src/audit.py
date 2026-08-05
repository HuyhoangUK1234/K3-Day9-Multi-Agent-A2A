"""Soi bộ case đầu vào để lộ ra các tình huống bẫy trước khi nộp.

Chạy: python -m src.main --audit
Không gọi LLM. Mục đích là để mắt người nhìn thấy case nào bất thường, chứ
không thay thế tests/test_traps.py.
"""

from .data.loader import OlistData
from .factsheet import merge
from .policy import rules
from .tools.scoped import ScopedView, delivery_facts, order_seller_facts, payment_facts


def audit(cases: list[dict], data: OlistData) -> None:
    view = ScopedView(data, "rule_engine")
    flagged: list[tuple[str, str, list[str]]] = []
    issues: dict[str, int] = {}

    for case in cases:
        case_id = case["case_id"]
        order_id = case["customer_request"]["claimed_order_id"]

        order = order_seller_facts(view, order_id)
        payment = payment_facts(view, order_id)
        delivery = delivery_facts(view, order_id, order["items"])
        facts = merge(order, payment, delivery)
        verdict = rules.evaluate(facts)
        issues[verdict["primary_issue"]] = issues.get(verdict["primary_issue"], 0) + 1

        marks = []
        if not facts["order_exists"]:
            marks.append("ORDER KHÔNG CÓ TRONG CSV")
        if not facts["has_items"]:
            marks.append("KHÔNG CÓ DÒNG HÀNG (item/seller rỗng, tổng 0.0)")
        if len(facts["seller_ids"]) > 1:
            marks.append(f"NHIỀU SELLER ({len(facts['seller_ids'])})")
        if 0 < len(facts["late_seller_ids"]) < len(facts["seller_ids"]):
            marks.append("CHỈ MỘT PHẦN SELLER BÀN GIAO MUỘN")
        if facts["order_status"] in ("canceled", "unavailable") and facts["seller_handoff_late"]:
            marks.append("ĐƠN HỦY MÀ SELLER CŨNG BÀN GIAO MUỘN (thứ tự ưu tiên phải đúng)")
        if facts["payment_count"] >= 2 and facts["is_late"]:
            marks.append("VỪA SPLIT PAYMENT VỪA GIAO TRỄ")
        if len(facts["items"]) > 5 or facts["payment_count"] > 5:
            marks.append("VƯỢT 5 ID, PHẢI CẮT BỚT ENTITY")

        margin = _handoff_margin_hours(order, delivery)
        if margin is not None and 0 < margin <= 24:
            marks.append(f"SELLER CHỈ MUỘN {margin:.1f} GIỜ (so theo ngày là mất case)")

        if marks:
            flagged.append((case_id, verdict["primary_issue"], marks))

    print("\n=== Phân bố kết luận ===")
    for issue, count in sorted(issues.items(), key=lambda kv: -kv[1]):
        print(f"  {count:2d}  {issue}")

    print(f"\n=== {len(flagged)} case cần để mắt ===")
    for case_id, issue, marks in flagged:
        print(f"  {case_id} [{issue}]")
        for mark in marks:
            print(f"        - {mark}")
    if not flagged:
        print("  không có case nào bất thường")


def _handoff_margin_hours(order: dict, delivery: dict) -> float | None:
    """Seller bàn giao muộn bao nhiêu giờ so với hạn sớm nhất của đơn."""
    from .data.loader import parse_ts

    carrier = parse_ts(delivery.get("order_delivered_carrier_date"))
    limits = [parse_ts(r["shipping_limit_date"]) for r in order.get("items", [])]
    limits = [t for t in limits if t]
    if not carrier or not limits:
        return None
    return (carrier - min(limits)).total_seconds() / 3600
