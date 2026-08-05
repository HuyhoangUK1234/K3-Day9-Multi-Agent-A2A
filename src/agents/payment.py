"""Payment Agent — đối soát tiền khách trả với tiền hàng cộng phí ship."""

from ..bus import EVIDENCE_BUNDLE, Envelope
from ..tools.scoped import payment_facts
from .base import BaseAgent

SYSTEM = (
    "Bạn là Payment Agent. Bạn không tự cộng tiền: mọi tổng tiền đã được tính sẵn "
    "trong fact. payment_value là số tiền của từng dòng thanh toán, KHÔNG phải tiền "
    "mỗi kỳ trả góp, tuyệt đối không nhân với payment_installments. "
    "Luôn trả về đúng một object JSON."
)


class PaymentAgent(BaseAgent):
    name = "payment_agent"
    system_prompt = SYSTEM

    def run(self, case_id: str, order_id: str) -> Envelope:
        facts = payment_facts(self.view, order_id)

        prompt = (
            "Fact thanh toán:\n"
            f"{self.compact(facts, ('order_id', 'payments', 'payment_count', 'payment_total', 'expected_total', 'delta', 'tolerance'))}\n\n"
            "expected_total là tổng price cộng freight_value của đơn. "
            "delta = payment_total - expected_total. Coi là khớp khi |delta| <= tolerance.\n"
            "Trả về JSON với đúng các khóa sau:\n"
            '{"is_split_payment": true/false, "reconciled": true/false, "note": "một câu ngắn"}'
        )
        judgment = self.ask_json(case_id, prompt, ("is_split_payment", "reconciled"))

        disagreement = None
        if judgment:
            if bool(judgment.get("is_split_payment")) != facts["is_split_payment"]:
                disagreement = "is_split_payment lệch fact"
            if bool(judgment.get("reconciled")) != facts["reconciled"]:
                disagreement = (disagreement or "") + " reconciled lệch fact"

        if disagreement:
            self.tracer.write(
                case_id=case_id, agent=self.name, event="disagreement", detail=disagreement.strip()
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
