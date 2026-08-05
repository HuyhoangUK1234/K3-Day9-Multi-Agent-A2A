"""Delivery Agent — trễ hay không, và nếu trễ thì lỗi seller hay lỗi vận chuyển.

Agent này nhận handoff từ Order & Seller Agent: danh sách item kèm seller_id và
shipping_limit_date. Đây là cạnh phụ thuộc duy nhất giữa ba agent domain.
"""

from ..bus import EVIDENCE_BUNDLE, Envelope
from ..tools.scoped import delivery_facts
from .base import BaseAgent

SYSTEM = (
    "Bạn là Delivery Agent. Chỉ so sánh các mốc thời gian được đưa, không đổi múi giờ, "
    "không suy diễn tracking checkpoint không tồn tại. "
    "Luôn trả về đúng một object JSON."
)

VALID_CAUSES = {"SELLER_HANDOFF_AFTER_LIMIT", "CARRIER_DELIVERED_AFTER_ESTIMATE", "DELIVERY_WITHIN_ESTIMATE"}


class DeliveryAgent(BaseAgent):
    name = "delivery_agent"
    system_prompt = SYSTEM

    def run(self, case_id: str, order_id: str, handoff_items: list[dict] | None = None) -> Envelope:
        facts = delivery_facts(self.view, order_id, handoff_items)

        prompt = (
            "Fact giao hàng:\n"
            f"{self.compact(facts, ('order_id', 'order_status', 'order_delivered_customer_date', 'order_estimated_delivery_date', 'order_delivered_carrier_date', 'is_late', 'seller_handoff_late', 'late_seller_ids'))}\n\n"
            "Quy tắc:\n"
            "- Giao sau ngày hẹn VÀ seller bàn giao sau shipping_limit_date -> SELLER_HANDOFF_AFTER_LIMIT\n"
            "- Giao sau ngày hẹn VÀ seller bàn giao đúng hạn -> CARRIER_DELIVERED_AFTER_ESTIMATE\n"
            "- Giao không muộn hơn ngày hẹn -> DELIVERY_WITHIN_ESTIMATE\n"
            "Trả về JSON với đúng các khóa sau:\n"
            '{"cause_code": "một trong ba mã trên hoặc null", "responsible": "seller|logistics_provider|none", "note": "một câu ngắn"}'
        )
        judgment = self.ask_json(case_id, prompt, ("cause_code",))

        disagreement = None
        if judgment:
            llm_cause = judgment.get("cause_code")
            if llm_cause not in VALID_CAUSES and llm_cause is not None:
                disagreement = f"cause_code lạ: {llm_cause}"
            elif llm_cause != facts["cause_code"]:
                disagreement = f"cause_code LLM={llm_cause} fact={facts['cause_code']}"

        if disagreement:
            self.tracer.write(
                case_id=case_id, agent=self.name, event="disagreement", detail=disagreement
            )

        facts["llm_note"] = (judgment or {}).get("note", "")
        facts["llm_ok"] = judgment is not None and not disagreement

        return Envelope(
            case_id=case_id,
            sender=self.name,
            recipient="coordinator",
            type=EVIDENCE_BUNDLE,
            payload=facts,
            confidence=0.95 if facts["llm_ok"] else 0.7,
        )
