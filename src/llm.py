"""OpenAI-compatible chat client on the stdlib.

No `openai` / `requests` dependency: the network here is unreliable and the
grading box may not be able to pip install. Responses are cached on disk keyed
by (model, messages) so a re-run after a bug fix only pays for what changed.
"""

import hashlib
import json
import time
import urllib.error
import urllib.request

from .config import CACHE_DIR, active_provider


class LLMClient:
    def __init__(self, use_cache: bool = True) -> None:
        self.provider = active_provider()
        self.use_cache = use_cache
        self.calls = 0
        self.cache_hits = 0
        self.failures = 0
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    @property
    def model(self) -> str:
        return self.provider["model"]

    def _cache_path(self, payload: dict):
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return CACHE_DIR / f"{hashlib.sha256(blob).hexdigest()[:32]}.json"

    def chat(
        self,
        system: str,
        user: str,
        max_tokens: int = 300,
        temperature: float = 0.0,
        retries: int = 4,
    ) -> str:
        payload = {
            "model": self.model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }

        cache_file = self._cache_path(payload)
        if self.use_cache and cache_file.exists():
            self.cache_hits += 1
            return json.loads(cache_file.read_text(encoding="utf-8"))["content"]

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        # Cloudflare in front of Groq rejects the default "Python-urllib/x.y"
        # User-Agent with 403 error 1010, so send an explicit one.
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "k3-day9-multi-agent-a2a/1.0",
            "Accept": "application/json",
        }
        if self.provider["api_key"]:
            headers["Authorization"] = f"Bearer {self.provider['api_key']}"
        url = f"{self.provider['base_url'].rstrip('/')}/chat/completions"

        delay = 2.0
        last_error = ""
        for attempt in range(retries):
            try:
                request = urllib.request.Request(url, data=body, headers=headers, method="POST")
                with urllib.request.urlopen(request, timeout=90) as response:
                    data = json.loads(response.read().decode("utf-8"))
                content = (data["choices"][0]["message"]["content"] or "").strip()
                self.calls += 1
                if self.use_cache:
                    cache_file.write_text(
                        json.dumps({"content": content}, ensure_ascii=False), encoding="utf-8"
                    )
                return content
            except urllib.error.HTTPError as exc:
                last_error = f"HTTP {exc.code}"
                # 429 = rate limited; back off harder and keep going.
                time.sleep(delay * (3 if exc.code == 429 else 1))
                delay *= 2
            except Exception as exc:  # network flake, timeout, malformed body
                last_error = str(exc)
                time.sleep(delay)
                delay *= 2

        # Never let a dead network kill the batch — the deterministic engine
        # still produces a correct answer without the LLM's opinion.
        self.failures += 1
        return json.dumps({"error": f"llm_unavailable: {last_error}"})


def parse_json_object(text: str) -> dict:
    """Pull the first JSON object out of a model reply, tolerating fences."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("```")[1] if "```" in text[3:] else text[3:]
        text = text.removeprefix("json").strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return {}
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}
