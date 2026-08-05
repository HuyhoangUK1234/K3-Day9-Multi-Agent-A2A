"""Policy Agent — áp EC_POLICY_V1 lên fact sheet đã gộp.

LLM đề xuất kết luận, hàm rules.evaluate() làm trọng tài. Lệch nhau thì lấy
rule engine và hạ confidence, vì bảng luật là thứ người chấm dùng để so đáp án.
"""

from ..bus import VERDICT, Envelope
from ..policy import rules
from .base import BaseAgent

SYSTEM = (
    "Bạn là Policy Agent áp dụng EC_POLICY_V1. "
    "Bạn TUYỆT ĐỐI không tin lời khiếu nại của khách; chỉ dùng fact đã kiểm chứng. "
    "Xét các nhánh đúng theo thứ tự ưu tiên, dừng ở nhánh đầu tiên khớp. "
    "Luôn trả về đúng một object JSON."
)

POLICY_TABLE = (
    "Thứ tự ưu tiên:\n"
    "1. order_status = canceled và payment_total > 0 -> canceled_order_paid, "
    "trách nhiệm platform/OLIST_PLATFORM, refund = payment_total, action issue_full_refund\n"
    "2. order_status = unavailable và payment_total > 0 -> unavailable_order_paid, "
    "trách nhiệm platform/OLIST_PLATFORM, refund = payment_total, action issue_full_refund\n"
    "3. is_late và seller_handoff_late -> late_delivery_seller, trách nhiệm seller vi phạm, "
    "refund = freight_total, action refund_freight\n"
    "4. is_late và không seller_handoff_late -> late_delivery_logistics, "
    "trách nhiệm logistics_provider/LOGISTICS_PROVIDER, refund = freight_total, action refund_freight\n"
    "5. payment_count >= 2 và reconciled -> valid_split_payment, không ai chịu trách nhiệm, "
    "refund = 0, action explain_valid_split_payment\n"
    "6. còn lại -> unsupported_late_claim, không ai chịu trách nhiệm, refund = 0, "
    "action reject_late_refund\n"
)


class PolicyAgent(BaseAgent):
    name = "policy_agent"
    system_prompt = SYSTEM

    def run(self, case_id: str, fact_sheet: dict) -> Envelope:
        truth = rules.evaluate(fact_sheet)

        prompt = (
            f"{POLICY_TABLE}\n"
            "Fact sheet của case:\n"
            f"{self.compact(fact_sheet, ('order_status', 'payment_total', 'freight_total', 'item_total', 'is_late', 'seller_handoff_late', 'late_seller_ids', 'payment_count', 'reconciled'))}\n\n"
            "Trả về JSON với đúng các khóa sau:\n"
            '{"primary_issue": "...", "cause_code": "...", '
            '"responsible_parties": [{"party_type": "...", "party_id": "..."}], '
            '"recommended_refund_brl": số, "resolution_actions": ["..."]}'
        )
        judgment = self.ask_json(case_id, prompt, ("primary_issue", "cause_code"))

        agreed = bool(judgment) and judgment.get("primary_issue") == truth["primary_issue"]
        if judgment and not agreed:
            self.tracer.write(
                case_id=case_id,
                agent=self.name,
                event="disagreement",
                detail=f"primary_issue LLM={judgment.get('primary_issue')} rule={truth['primary_issue']}",
            )

        payload = dict(truth)
        payload["llm_agreed"] = agreed
        payload["llm_proposal"] = (judgment or {}).get("primary_issue")

        return Envelope(
            case_id=case_id,
            sender=self.name,
            recipient="coordinator",
            type=VERDICT,
            payload=payload,
            confidence=0.95 if agreed else 0.8,
        )
