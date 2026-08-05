"""Client LLM dùng chung cho OpenAI và Groq.

Groq nói được giao thức OpenAI nên chỉ cần đổi base_url. Mỗi model có một
token bucket riêng vì hạn mức của Groq tính theo từng model — chạy hai model
khác nhau trên cùng một key thì cộng được băng thông.
"""

import json
import os
import random
import re
import threading
import time

from openai import OpenAI

from .config import LLM_TIMEOUT_S, MODEL_REGISTRY, ModelSpec


class LLMError(RuntimeError):
    pass


class _RateLimiter:
    """Giãn cách các lời gọi cùng model để không đụng trần requests/phút."""

    def __init__(self, rpm: int):
        self.min_interval = 60.0 / max(rpm, 1)
        self._lock = threading.Lock()
        self._next_at = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            if now < self._next_at:
                delay = self._next_at - now
            else:
                delay = 0.0
            self._next_at = max(now, self._next_at) + self.min_interval
        if delay > 0:
            time.sleep(delay)


class LLMClient:
    def __init__(self):
        self._clients: dict[str, OpenAI] = {}
        self._limiters: dict[str, _RateLimiter] = {}
        self._lock = threading.Lock()

    def _client(self, spec: ModelSpec) -> OpenAI:
        cache_key = f"{spec.provider}:{spec.key_env}"
        with self._lock:
            if cache_key not in self._clients:
                api_key = os.getenv(spec.key_env)
                if not api_key:
                    raise LLMError(f"thiếu biến môi trường {spec.key_env}")
                self._clients[cache_key] = OpenAI(
                    api_key=api_key, base_url=spec.base_url, timeout=LLM_TIMEOUT_S
                )
            return self._clients[cache_key]

    def _limiter(self, spec: ModelSpec) -> _RateLimiter:
        with self._lock:
            if spec.model not in self._limiters:
                self._limiters[spec.model] = _RateLimiter(spec.rpm)
            return self._limiters[spec.model]

    def chat(self, agent: str, system: str, user: str) -> dict:
        """Gọi model của một agent, trả về dict gồm text và số token đã dùng."""
        spec = MODEL_REGISTRY[agent]
        client = self._client(spec)
        limiter = self._limiter(spec)

        if spec.supports_system_role:
            messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        else:
            # Gemma không có system role: gộp chỉ dẫn vào ngay đầu message người dùng.
            messages = [{"role": "user", "content": f"{system}\n\n---\n\n{user}"}]

        kwargs = {
            "model": spec.model,
            "messages": messages,
            "temperature": spec.temperature,
            "max_tokens": spec.max_tokens,
        }
        if spec.supports_json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        last_error = None
        for attempt in range(5):
            limiter.wait()
            started = time.monotonic()
            try:
                response = client.chat.completions.create(**kwargs)
                usage = response.usage
                return {
                    "text": response.choices[0].message.content or "",
                    "model": spec.model,
                    "provider": spec.provider,
                    "prompt_tokens": getattr(usage, "prompt_tokens", 0),
                    "completion_tokens": getattr(usage, "completion_tokens", 0),
                    "latency_ms": int((time.monotonic() - started) * 1000),
                }
            except Exception as exc:  # rate limit, timeout, lỗi mạng
                last_error = exc
                sleep_s = min(2 ** attempt, 16) + random.uniform(0, 1)
                time.sleep(sleep_s)

        raise LLMError(f"{spec.provider}/{spec.model} thất bại sau 5 lần: {last_error}")


_JSON_BLOCK = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def parse_json_loose(text: str) -> dict:
    """Bóc JSON từ câu trả lời của model.

    Model nhỏ hay bọc JSON trong ```json hoặc kèm lời dẫn, nên không dùng
    json.loads thẳng được.
    """
    if not text:
        raise ValueError("model trả về rỗng")

    candidate = text.strip()
    match = _JSON_BLOCK.search(candidate)
    if match:
        candidate = match.group(1).strip()

    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    start = candidate.find("{")
    if start == -1:
        raise ValueError("không tìm thấy JSON trong câu trả lời")

    depth = 0
    for index in range(start, len(candidate)):
        char = candidate[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return json.loads(candidate[start : index + 1])

    raise ValueError("JSON không đóng ngoặc")
