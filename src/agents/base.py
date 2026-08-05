"""Vòng đời chung của một agent: nhận việc, gọi LLM, trả envelope.

Điểm quan trọng: LLM luôn được đưa fact đã tính sẵn và chỉ được phép chọn
trong tập giá trị cho trước. Sau khi LLM trả lời, agent đối chiếu lại với fact.
LLM lệch thì lấy fact và ghi cờ disagreement vào trace — đây là chỗ "kiểm chứng
giữa các agent" trở thành thật chứ không phải khẩu hiệu.
"""

import json

from ..config import LLM_RETRIES
from ..data.loader import OlistData
from ..llm import LLMClient, parse_json_loose
from ..tools.scoped import ScopedView, jsonable


class BaseAgent:
    name = "base"
    system_prompt = ""

    def __init__(self, data: OlistData, llm: LLMClient, tracer):
        self.data = data
        self.llm = llm
        self.tracer = tracer
        self.view = ScopedView(data, self.name)

    # ------------------------------------------------------------------ helpers
    def ask_json(self, case_id: str, user_prompt: str, required_keys: tuple[str, ...]) -> dict | None:
        """Gọi LLM và ép câu trả lời về JSON có đủ các khóa cần thiết.

        Trả về None nếu sau LLM_RETRIES lần vẫn không lấy được JSON dùng được —
        khi đó agent rơi về fact thuần, case vẫn chạy tiếp.
        """
        prompt = user_prompt
        for attempt in range(LLM_RETRIES + 1):
            try:
                response = self.llm.chat(self.name, self.system_prompt, prompt)
            except Exception as exc:
                self.tracer.write(
                    case_id=case_id, agent=self.name, event="llm_error", error=str(exc)
                )
                return None

            self.tracer.write(
                case_id=case_id,
                agent=self.name,
                event="llm_call",
                provider=response["provider"],
                model=response["model"],
                attempt=attempt + 1,
                prompt_tokens=response["prompt_tokens"],
                completion_tokens=response["completion_tokens"],
                latency_ms=response["latency_ms"],
            )

            try:
                parsed = parse_json_loose(response["text"])
                missing = [k for k in required_keys if k not in parsed]
                if missing:
                    raise ValueError(f"thiếu khóa {missing}")
                return parsed
            except Exception as exc:
                self.tracer.write(
                    case_id=case_id, agent=self.name, event="bad_json", error=str(exc)
                )
                prompt = (
                    f"{user_prompt}\n\nCâu trả lời trước bị lỗi: {exc}. "
                    f"Chỉ trả về đúng một object JSON, không kèm chữ nào khác."
                )
        return None

    @staticmethod
    def compact(facts: dict, keys: tuple[str, ...]) -> str:
        """Rút gọn fact trước khi đưa vào prompt để tiết kiệm token."""
        subset = {k: facts.get(k) for k in keys if k in facts}
        return json.dumps(jsonable(subset), ensure_ascii=False)
