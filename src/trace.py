"""Ghi logging/trace.jsonl — mỗi lời gọi LLM và mỗi lần handoff là một dòng.

Mở bằng mode "w" ở đầu mỗi lượt chạy để file chỉ chứa lượt chạy mới nhất,
đúng yêu cầu "không append" của README.
"""

import json
import threading
import time
from pathlib import Path


class Tracer:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._fh = open(self.path, "w", encoding="utf-8")

    def write(self, **fields) -> None:
        record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())}
        record.update(fields)
        line = json.dumps(record, ensure_ascii=False)
        with self._lock:
            self._fh.write(line + "\n")
            self._fh.flush()

    def close(self) -> None:
        with self._lock:
            self._fh.close()
