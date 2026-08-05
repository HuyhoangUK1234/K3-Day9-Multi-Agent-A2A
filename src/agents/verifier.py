"""Verifier Agent — chốt chặn cuối trước khi ghi file.

Hai lớp kiểm: schema.validate() bằng code là lớp có quyền quyết định, LLM là
lớp đọc lại độc lập. LLM bắt lỗi mà code không thấy thì không chặn file, nhưng
hạ confidence và ghi vào trace để người chấm thấy có kiểm chứng thật.
"""

from ..bus import VERIFICATION_RESULT, Envelope
from ..schema import validate
from .base import BaseAgent

SYSTEM = (
    "Bạn là Verifier Agent. Việc của bạn là soi lỗi, không phải khen. "
    "Luôn trả về đúng một object JSON."
)


class VerifierAgent(BaseAgent):
    name = "verifier_agent"
    system_prompt = SYSTEM

    def run(self, case_id: str, output: dict, fact_sheet: dict) -> Envelope:
        problems = validate(output, self.data, fact_sheet)

        prompt = (
            "Output đề xuất:\n"
            f"{self.compact(output, tuple(output.keys()))}\n\n"
            "Fact đã kiểm chứng:\n"
            f"{self.compact(fact_sheet, ('order_status', 'item_total', 'freight_total', 'payment_total', 'is_late', 'seller_handoff_late', 'payment_count', 'reconciled'))}\n\n"
            "Kiểm: (a) tiền trong financial_resolution khớp fact, "
            "(b) case_status là action_required khi và chỉ khi recommended_refund_brl > 0, "
            "(c) resolution_actions và responsible_parties khớp primary_issue, "
            "(d) không có ID nào ngoài dữ liệu.\n"
            "Trả về JSON với đúng các khóa sau:\n"
            '{"accept": true/false, "problems": ["..."]}'
        )
        judgment = self.ask_json(case_id, prompt, ("accept",))

        llm_objection = bool(judgment) and not judgment.get("accept")
        if llm_objection:
            self.tracer.write(
                case_id=case_id,
                agent=self.name,
                event="llm_objection",
                detail=judgment.get("problems", []),
            )

        return Envelope(
            case_id=case_id,
            sender=self.name,
            recipient="coordinator",
            type=VERIFICATION_RESULT,
            payload={
                "accepted": not problems,
                "problems": problems,
                "llm_objection": llm_objection,
                "llm_problems": (judgment or {}).get("problems", []),
            },
            confidence=1.0 if not problems else 0.0,
        )
