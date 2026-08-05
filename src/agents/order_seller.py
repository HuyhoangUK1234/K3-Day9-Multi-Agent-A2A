"""Order & Seller Agent — trạng thái đơn, dòng hàng, seller, hạn bàn giao."""

from ..bus import EVIDENCE_BUNDLE, Envelope
from ..tools.scoped import order_seller_facts
from .base import BaseAgent

SYSTEM = (
    "Bạn là Order & Seller Agent của một sàn thương mại điện tử. "
    "Bạn chỉ được kết luận dựa trên fact được đưa, không suy diễn thêm sự kiện. "
    "Luôn trả về đúng một object JSON."
)


class OrderSellerAgent(BaseAgent):
    name = "order_seller_agent"
    system_prompt = SYSTEM

    def run(self, case_id: str, order_id: str) -> Envelope:
        facts = order_seller_facts(self.view, order_id)

        prompt = (
            "Fact của đơn hàng:\n"
            f"{self.compact(facts, ('order_id', 'order_exists', 'order_status', 'has_items', 'items', 'item_total', 'freight_total', 'seller_ids'))}\n\n"
            "Trả về JSON với đúng các khóa sau:\n"
            '{"status_class": "canceled|unavailable|delivered|other|missing", '
            '"seller_ids": [danh sách seller_id lấy nguyên văn từ fact], '
            '"note": "một câu ngắn"}'
        )
        judgment = self.ask_json(case_id, prompt, ("status_class", "seller_ids"))

        disagreement = None
        if judgment:
            expected_class = _status_class(facts)
            if judgment.get("status_class") != expected_class:
                disagreement = f"status_class LLM={judgment.get('status_class')} fact={expected_class}"
            unknown = [s for s in judgment.get("seller_ids", []) if s not in facts["seller_ids"]]
            if unknown:
                disagreement = (disagreement or "") + f" seller lạ={unknown}"

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


def _status_class(facts: dict) -> str:
    if not facts["order_exists"]:
        return "missing"
    status = facts["order_status"]
    if status in ("canceled", "unavailable", "delivered"):
        return status
    return "other"
