"""Message bus A2A: mọi trao đổi giữa agent đi qua một envelope thống nhất."""

import itertools
import time
from dataclasses import dataclass, field, asdict
from typing import Any

# Các loại tin nhắn hợp lệ trong hệ thống.
TASK_ASSIGNMENT = "task_assignment"
EVIDENCE_BUNDLE = "evidence_bundle"
VERDICT = "verdict"
VERIFICATION_RESULT = "verification_result"
REWORK_REQUEST = "rework_request"

_counter = itertools.count(1)


@dataclass
class Envelope:
    case_id: str
    sender: str
    recipient: str
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    msg_id: str = ""
    ts: float = field(default_factory=time.time)

    def __post_init__(self):
        if not self.msg_id:
            self.msg_id = f"{self.case_id}#{next(_counter)}"

    def to_trace(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("ts", None)
        return data
