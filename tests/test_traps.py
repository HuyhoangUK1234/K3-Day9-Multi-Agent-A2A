"""Khóa lại các bẫy đã tìm thấy trong bộ 50 case.

Chạy: python -m tests.test_traps
Không cần pytest. In ra dòng nào FAIL là chỗ đó vỡ.

Ba nhóm bẫy đã xác định trong dữ liệu thật:
  A. Đơn canceled nhưng seller cũng bàn giao muộn  -> phải ra canceled_order_paid
  B. Seller muộn chỉ vài giờ, cùng ngày lịch        -> phải ra late_delivery_seller
  C. Đơn unavailable không có dòng hàng nào         -> entity rỗng, tổng 0.0
"""

import json
import sys
from decimal import Decimal

from src.config import DATA_DIR, INPUT_DIR, MAX_EVIDENCE
from src.data import loader
from src.factsheet import merge
from src.policy import rules
from src.schema import validate
from src.tools.scoped import ScopedView, delivery_facts, order_seller_facts, payment_facts

FAILURES: list[str] = []

# Console Windows mặc định cp1252, in tiếng Việt vào đó là crash giữa chừng.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name} {detail}")
        FAILURES.append(name)


def facts(**overrides) -> dict:
    """Fact sheet tối thiểu, ghi đè từng trường để dựng tình huống."""
    base = {
        "order_id": "o1",
        "order_exists": True,
        "order_status": "delivered",
        "has_items": True,
        "items": [{"order_item_id": 1, "seller_id": "s1", "price": Decimal("100.00"),
                   "freight_value": Decimal("10.00"), "shipping_limit_date": "2018-01-01 00:00:00"}],
        "item_ids": ["o1:1"],
        "seller_ids": ["s1"],
        "item_total": Decimal("100.00"),
        "freight_total": Decimal("10.00"),
        "payments": [{"payment_sequential": 1, "payment_type": "credit_card",
                      "payment_installments": 1, "payment_value": Decimal("110.00")}],
        "payment_ids": ["o1:1"],
        "payment_count": 1,
        "payment_total": Decimal("110.00"),
        "expected_total": Decimal("110.00"),
        "delta": Decimal("0.00"),
        "is_split_payment": False,
        "reconciled": True,
        "is_late": False,
        "is_delivered": True,
        "seller_handoff_late": False,
        "late_seller_ids": [],
        "order_delivered_customer_date": "2018-01-05 10:00:00",
        "order_estimated_delivery_date": "2018-01-10 00:00:00",
        "order_delivered_carrier_date": "2017-12-30 10:00:00",
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------- thứ tự ưu tiên
def test_priority():
    print("\n[1] Thứ tự ưu tiên của bảng luật")

    # Bẫy A: đơn canceled mà seller cũng bàn giao muộn.
    v = rules.evaluate(facts(order_status="canceled", is_late=True,
                             seller_handoff_late=True, late_seller_ids=["s1"]))
    check("canceled thắng late_delivery_seller", v["primary_issue"] == "canceled_order_paid", v["primary_issue"])
    check("canceled hoàn toàn bộ payment", v["recommended_refund"] == Decimal("110.00"), str(v["recommended_refund"]))
    check("canceled quy trách nhiệm platform",
          v["responsible_parties"] == [{"party_type": "platform", "party_id": "OLIST_PLATFORM"}])

    v = rules.evaluate(facts(order_status="unavailable", is_late=True, seller_handoff_late=True))
    check("unavailable thắng late", v["primary_issue"] == "unavailable_order_paid", v["primary_issue"])

    # Đơn canceled nhưng KHÔNG có tiền -> không rơi vào nhánh 1.
    v = rules.evaluate(facts(order_status="canceled", payment_total=Decimal("0.00"),
                             payments=[], payment_count=0))
    check("canceled không thu tiền thì không hoàn", v["recommended_refund"] == Decimal("0.00"))

    # Trễ thắng split payment.
    v = rules.evaluate(facts(is_late=True, payment_count=2, reconciled=True, is_split_payment=True))
    check("late thắng valid_split_payment", v["primary_issue"] == "late_delivery_logistics", v["primary_issue"])


# ------------------------------------------------------------- ranh giới giờ phút
def test_time_boundary():
    print("\n[2] Ranh giới thời gian (bẫy B)")

    data = loader.load(DATA_DIR, None)
    view = ScopedView(data, "rule_engine")

    # Bẫy B thật trong dữ liệu: bàn giao muộn 3.5h nhưng CÙNG NGÀY LỊCH.
    # So sánh theo ngày thay vì theo giây là mất case này.
    for case_id, order_id in [
        ("EC_033", None), ("EC_034", None), ("EC_037", None), ("EC_044", None),
    ]:
        payload = json.load(open(INPUT_DIR / f"{case_id}.json", encoding="utf-8"))
        order_id = payload["customer_request"]["claimed_order_id"]
        o = order_seller_facts(view, order_id)
        d = delivery_facts(view, order_id, o["items"])
        carrier = d["order_delivered_carrier_date"][:10]
        limit = o["items"][0]["shipping_limit_date"][:10]
        check(f"{case_id} bàn giao muộn dù cùng ngày lịch ({carrier} vs {limit})",
              d["seller_handoff_late"] is True and carrier == limit)

    # Bằng đúng từng giây thì KHÔNG tính là muộn.
    f = facts(is_late=True, seller_handoff_late=False, late_seller_ids=[])
    v = rules.evaluate(f)
    check("bàn giao đúng hạn -> lỗi vận chuyển", v["primary_issue"] == "late_delivery_logistics")
    check("lỗi vận chuyển hoàn đúng phí ship", v["recommended_refund"] == Decimal("10.00"))

    v = rules.evaluate(facts(is_late=True, seller_handoff_late=True, late_seller_ids=["s1"]))
    check("bàn giao muộn -> lỗi seller", v["primary_issue"] == "late_delivery_seller")
    check("lỗi seller quy đúng seller_id",
          v["responsible_parties"] == [{"party_type": "seller", "party_id": "s1"}])


# --------------------------------------------------------------- đơn không có item
def test_no_items():
    print("\n[3] Đơn không có dòng hàng (bẫy C)")

    f = facts(order_status="unavailable", has_items=False, items=[], item_ids=[], seller_ids=[],
              item_total=Decimal("0.00"), freight_total=Decimal("0.00"),
              expected_total=Decimal("0.00"), delta=Decimal("110.00"), reconciled=False,
              is_delivered=False, order_delivered_customer_date=None,
              order_delivered_carrier_date=None)
    v = rules.evaluate(f)
    out = rules.build_output("EC_TEST", f, v, rules.confidence_for(f, v))

    check("vẫn ra unavailable_order_paid", v["primary_issue"] == "unavailable_order_paid")
    check("hoàn toàn bộ payment", out["financial_resolution"]["recommended_refund_brl"] == 110.0)
    check("item_ids rỗng", out["affected_entities"]["item_ids"] == [])
    check("seller_ids rỗng", out["affected_entities"]["seller_ids"] == [])
    check("item_total = 0.0", out["financial_resolution"]["item_total_brl"] == 0.0)
    check("freight_total = 0.0", out["financial_resolution"]["freight_total_brl"] == 0.0)
    check("confidence không bị hạ vì thiếu item",
          out["assessment"]["confidence"] == 1.0, str(out["assessment"]["confidence"]))


# ------------------------------------------------------------------ đối soát tiền
def test_money():
    print("\n[4] Đối soát tiền")

    # Lệch 0.09 vẫn coi là khớp, lệch 0.11 thì không.
    from src.money import RECONCILE_TOLERANCE
    check("ngưỡng đối soát đúng 0.10 BRL", RECONCILE_TOLERANCE == Decimal("0.10"))

    f = facts(payment_count=2, is_split_payment=True, reconciled=True,
              payments=[{"payment_sequential": 1, "payment_type": "voucher",
                         "payment_installments": 1, "payment_value": Decimal("10.00")},
                        {"payment_sequential": 2, "payment_type": "credit_card",
                         "payment_installments": 6, "payment_value": Decimal("100.00")}],
              payment_ids=["o1:1", "o1:2"])
    v = rules.evaluate(f)
    check("split khớp -> valid_split_payment", v["primary_issue"] == "valid_split_payment")
    check("split không hoàn tiền", v["recommended_refund"] == Decimal("0.00"))
    check("split là no_action", v["case_status"] == "no_action")

    out = rules.build_output("EC_TEST", f, v, 0.95)
    check("payment_total không nhân với installments",
          out["financial_resolution"]["payment_total_brl"] == 110.0,
          str(out["financial_resolution"]["payment_total_brl"]))

    # Nhiều item phải cộng hết, không lấy mỗi dòng đầu.
    f = facts(items=[{"order_item_id": i, "seller_id": "s1", "price": Decimal("50.00"),
                      "freight_value": Decimal("7.00"), "shipping_limit_date": "2018-01-01 00:00:00"}
                     for i in (1, 2, 3)],
              item_ids=["o1:1", "o1:2", "o1:3"],
              item_total=Decimal("150.00"), freight_total=Decimal("21.00"),
              is_late=True, seller_handoff_late=True, late_seller_ids=["s1"])
    v = rules.evaluate(f)
    check("hoàn phí ship của TẤT CẢ item", v["recommended_refund"] == Decimal("21.00"),
          str(v["recommended_refund"]))


# ------------------------------------------------------------------- evidence ID
def test_evidence():
    print("\n[5] Evidence ID")

    many = facts(items=[{"order_item_id": i, "seller_id": f"s{i}", "price": Decimal("10.00"),
                         "freight_value": Decimal("1.00"), "shipping_limit_date": "2018-01-01 00:00:00"}
                        for i in range(1, 7)],
                 item_ids=[f"o1:{i}" for i in range(1, 7)],
                 seller_ids=[f"s{i}" for i in range(1, 7)],
                 payments=[{"payment_sequential": i, "payment_type": "credit_card",
                            "payment_installments": 1, "payment_value": Decimal("10.00")}
                           for i in range(1, 6)],
                 payment_ids=[f"o1:{i}" for i in range(1, 6)],
                 payment_count=5)
    v = rules.evaluate(many)
    evidence = rules.build_evidence_ids(many, v)

    check("không vượt 10 evidence", len(evidence) <= MAX_EVIDENCE, str(len(evidence)))
    check("order đứng đầu", evidence[0].startswith("order:"))
    check("policy đứng ngay sau order", evidence[1].startswith("policy:"))
    check("đơn nhiều dòng vẫn có cả item lẫn payment",
          all(any(e.startswith(k) for e in evidence) for k in ("item:", "payment:")),
          str(evidence))

    # evidence_ids chấm theo độ chính xác: seller không có lỗi thì không trích.
    check("không trích seller khi seller không chịu trách nhiệm",
          not any(e.startswith("seller:") for e in evidence), str(evidence))

    late = facts(is_late=True, seller_handoff_late=True, late_seller_ids=["s1"])
    v_late = rules.evaluate(late)
    ev_late = rules.build_evidence_ids(late, v_late)
    check("có trích seller khi seller bàn giao muộn",
          "seller:s1" in ev_late, str(ev_late))

    # affected_entities chấm theo độ phủ: seller_ids vẫn liệt kê đủ.
    out = rules.build_output("EC_TEST", many, v, 1.0)
    check("seller_ids vẫn liệt kê dù seller không có lỗi",
          out["affected_entities"]["seller_ids"] != [], str(out["affected_entities"]["seller_ids"]))
    for key in ("item_ids", "seller_ids", "payment_ids"):
        check(f"{key} không vượt 5", len(out["affected_entities"][key]) <= 5)


# ------------------------------------------------------- chạy thật trên 50 case
def test_real_dataset():
    print("\n[6] Chạy thật trên 50 case")

    cases = [json.load(open(p, encoding="utf-8")) for p in sorted(INPUT_DIR.glob("EC_*.json"))]
    check("đủ 50 case đầu vào", len(cases) == 50, str(len(cases)))

    needed = {c["customer_request"]["claimed_order_id"] for c in cases}
    data = loader.load(DATA_DIR, needed)
    view = ScopedView(data, "rule_engine")

    issues, bad_schema, low_conf = {}, [], []
    for case in cases:
        oid = case["customer_request"]["claimed_order_id"]
        o = order_seller_facts(view, oid)
        p = payment_facts(view, oid)
        d = delivery_facts(view, oid, o["items"])
        f = merge(o, p, d)
        v = rules.evaluate(f)
        out = rules.build_output(case["case_id"], f, v, rules.confidence_for(f, v))

        problems = validate(out, data, f)
        if problems:
            bad_schema.append(f"{case['case_id']}: {problems}")
        if out["assessment"]["confidence"] < 1.0:
            low_conf.append(f"{case['case_id']}={out['assessment']['confidence']}")
        issues[v["primary_issue"]] = issues.get(v["primary_issue"], 0) + 1

    check("mọi output đạt schema", not bad_schema, "; ".join(bad_schema[:3]))
    check("phủ đủ 6 nhánh nghiệp vụ", len(issues) == 6, str(issues))
    check("tổng đúng 50 case", sum(issues.values()) == 50, str(sum(issues.values())))
    check("cả 50 case đều confidence 1.0", not low_conf, ", ".join(low_conf))

    # Nhóm câu khiếu nại phải khớp nhóm kết luận: 25 case than trễ, 16 case
    # than đã trả tiền mà đơn không hoàn tất, 9 case sợ bị thu trùng.
    late_family = issues.get("late_delivery_seller", 0) + issues.get("late_delivery_logistics", 0) + issues.get("unsupported_late_claim", 0)
    paid_family = issues.get("canceled_order_paid", 0) + issues.get("unavailable_order_paid", 0)
    check("25 case thuộc nhóm giao trễ", late_family == 25, str(late_family))
    check("16 case thuộc nhóm đã trả tiền mà đơn không hoàn tất", paid_family == 16, str(paid_family))
    check("9 case thuộc nhóm nhiều dòng thanh toán", issues.get("valid_split_payment", 0) == 9)


def main() -> int:
    test_priority()
    test_time_boundary()
    test_no_items()
    test_money()
    test_evidence()
    test_real_dataset()

    print("\n" + "=" * 60)
    if FAILURES:
        print(f"{len(FAILURES)} kiểm tra THẤT BẠI:")
        for name in FAILURES:
            print(f"  - {name}")
        return 1
    print("Toàn bộ kiểm tra đạt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
