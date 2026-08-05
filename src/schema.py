"""Kiểm tra output trước khi ghi file. Trả về danh sách lỗi, rỗng nghĩa là đạt.

Đây là phần kiểm bằng code của Verifier Agent. Lỗi ở đây chặn file xấu ra
ngoài; sai schema là hard gate, case đó mất trắng điểm.
"""

from .config import (
    MAX_ACTIONS,
    MAX_ENTITY_IDS,
    MAX_EVIDENCE,
    MAX_RESPONSIBLE_PARTIES,
    MAX_ROOT_CAUSES,
)
from .data.loader import OlistData
from .money import ZERO, f2
from .policy.rules import ISSUE_SPEC, PRIMARY_ISSUES, ROOT_CAUSE_CODES
from .tools.scoped import evidence_id_exists

MONEY_KEYS = ("item_total_brl", "freight_total_brl", "payment_total_brl", "recommended_refund_brl")


def validate(output: dict, data: OlistData, facts: dict | None = None) -> list[str]:
    problems: list[str] = []

    # 1. Cấu trúc và kiểu dữ liệu
    for key in ("case_id", "assessment", "affected_entities", "root_cause_analysis",
                "evidence_ids", "financial_resolution", "resolution_actions"):
        if key not in output:
            problems.append(f"thiếu khóa '{key}'")
    if problems:
        return problems

    assessment = output["assessment"]
    for key in ("primary_issue", "case_status", "confidence"):
        if key not in assessment:
            problems.append(f"assessment thiếu '{key}'")
    if problems:
        return problems

    if assessment["primary_issue"] not in PRIMARY_ISSUES:
        problems.append(f"primary_issue lạ: {assessment['primary_issue']}")
    if assessment["case_status"] not in ("action_required", "no_action"):
        problems.append(f"case_status lạ: {assessment['case_status']}")
    if not isinstance(assessment["confidence"], (int, float)) or not 0 <= assessment["confidence"] <= 1:
        problems.append("confidence phải là số trong [0, 1]")

    # 2. Giới hạn số lượng
    entities = output["affected_entities"]
    for key in ("order_ids", "item_ids", "seller_ids", "payment_ids"):
        values = entities.get(key)
        if not isinstance(values, list):
            problems.append(f"affected_entities.{key} phải là list")
        elif len(values) > MAX_ENTITY_IDS:
            problems.append(f"affected_entities.{key} vượt {MAX_ENTITY_IDS} phần tử")

    rca = output["root_cause_analysis"]
    if len(rca.get("ranked_causes", [])) > MAX_ROOT_CAUSES:
        problems.append(f"ranked_causes vượt {MAX_ROOT_CAUSES}")
    if len(rca.get("responsible_parties", [])) > MAX_RESPONSIBLE_PARTIES:
        problems.append(f"responsible_parties vượt {MAX_RESPONSIBLE_PARTIES}")
    if len(output["evidence_ids"]) > MAX_EVIDENCE:
        problems.append(f"evidence_ids vượt {MAX_EVIDENCE}")
    if len(output["resolution_actions"]) > MAX_ACTIONS:
        problems.append(f"resolution_actions vượt {MAX_ACTIONS}")

    # 3. Root cause hợp lệ
    for cause in rca.get("ranked_causes", []):
        if cause.get("cause_code") not in ROOT_CAUSE_CODES:
            problems.append(f"cause_code lạ: {cause.get('cause_code')}")
    for party in rca.get("responsible_parties", []):
        if party.get("party_type") not in ("seller", "platform", "logistics_provider"):
            problems.append(f"party_type lạ: {party.get('party_type')}")
        if not party.get("party_id"):
            problems.append("responsible_party thiếu party_id")

    # 4. Evidence phải dựng được từ CSV
    for evidence_id in output["evidence_ids"]:
        if not evidence_id_exists(data, evidence_id, ROOT_CAUSE_CODES):
            problems.append(f"evidence không dựng được từ dữ liệu: {evidence_id}")

    # 5. Tiền: đúng kiểu, đúng 2 chữ số, và khớp với số Python tính lại
    finance = output["financial_resolution"]
    if finance.get("currency") != "BRL":
        problems.append("currency phải là BRL")
    for key in MONEY_KEYS:
        value = finance.get(key)
        if not isinstance(value, (int, float)):
            problems.append(f"{key} phải là số")
        elif round(float(value), 2) != float(value):
            problems.append(f"{key} phải làm tròn 2 chữ số thập phân")

    if facts is not None and not problems:
        expected = {
            "item_total_brl": f2(facts.get("item_total", ZERO)),
            "freight_total_brl": f2(facts.get("freight_total", ZERO)),
            "payment_total_brl": f2(facts.get("payment_total", ZERO)),
        }
        for key, want in expected.items():
            got = float(finance.get(key, 0.0))
            if abs(got - want) > 0.005:
                problems.append(f"{key} lệch số tính lại: output={got} tool={want}")

    # 6. Nhất quán giữa các phần
    refund = float(finance.get("recommended_refund_brl", 0.0))
    if refund > 0 and assessment["case_status"] != "action_required":
        problems.append("có refund nhưng case_status không phải action_required")
    if refund == 0 and assessment["case_status"] != "no_action":
        problems.append("refund bằng 0 nhưng case_status không phải no_action")

    issue = assessment["primary_issue"]
    if issue in ISSUE_SPEC:
        want_cause, want_action = ISSUE_SPEC[issue]
        causes = [c.get("cause_code") for c in rca.get("ranked_causes", [])]
        if want_cause not in causes:
            problems.append(f"primary_issue {issue} phải kèm cause_code {want_cause}")
        if want_action not in output["resolution_actions"]:
            problems.append(f"primary_issue {issue} phải kèm action {want_action}")
        if issue == "late_delivery_seller":
            if not any(p.get("party_type") == "seller" for p in rca.get("responsible_parties", [])):
                problems.append("late_delivery_seller phải có responsible party là seller")
        if issue == "late_delivery_logistics":
            if not any(p.get("party_id") == "LOGISTICS_PROVIDER" for p in rca.get("responsible_parties", [])):
                problems.append("late_delivery_logistics phải quy trách nhiệm LOGISTICS_PROVIDER")
        if issue in ("canceled_order_paid", "unavailable_order_paid"):
            if not any(p.get("party_id") == "OLIST_PLATFORM" for p in rca.get("responsible_parties", [])):
                problems.append(f"{issue} phải quy trách nhiệm OLIST_PLATFORM")

    return problems
