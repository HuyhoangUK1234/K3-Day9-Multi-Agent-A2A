"""Chạy toàn bộ 50 case và ghi output.

    python -m src.main                # chạy đầy đủ 6 agent
    python -m src.main --offline      # chỉ rule engine, không gọi LLM, không tốn quota
    python -m src.main --cases EC_001 EC_002

--offline dùng để kiểm tra đường ống và schema trước khi đốt quota API.
"""

import argparse
import json
import platform
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .config import (
    CASE_WORKERS,
    DATA_DIR,
    INPUT_DIR,
    METADATA_PATH,
    MODEL_REGISTRY,
    OUTPUT_DIR,
    TRACE_PATH,
    VARIANTS,
)
from .data import loader
from .factsheet import merge
from .policy import rules
from .schema import validate
from .tools.scoped import ScopedView, delivery_facts, order_seller_facts, payment_facts
from .trace import Tracer


def read_cases(input_dir: Path, only: list[str] | None) -> list[dict]:
    cases = []
    for path in sorted(input_dir.glob("EC_*.json")):
        if only and path.stem not in only:
            continue
        with open(path, "r", encoding="utf-8") as fh:
            cases.append(json.load(fh))
    return cases


def write_output(output_dir: Path, case_id: str, payload: dict) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{case_id}.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def run_offline(case: dict, data, tracer: Tracer, variant: str = "base") -> dict:
    """Đường ống rule engine thuần, không gọi LLM."""
    case_id = case["case_id"]
    order_id = case["customer_request"]["claimed_order_id"]
    view = ScopedView(data, "rule_engine")

    order = order_seller_facts(view, order_id)
    payment = payment_facts(view, order_id)
    delivery = delivery_facts(view, order_id, order.get("items"))

    facts = merge(order, payment, delivery)
    verdict = rules.evaluate(facts)
    output = rules.build_output(
        case_id, facts, verdict, rules.confidence_for(facts, verdict), variant
    )

    tracer.write(
        case_id=case_id,
        agent="rule_engine",
        event="case_done",
        primary_issue=verdict["primary_issue"],
        refund=output["financial_resolution"]["recommended_refund_brl"],
    )
    return output, facts


def write_metadata(runtime_s: float, case_count: int, offline: bool) -> None:
    models = []
    for agent, spec in MODEL_REGISTRY.items():
        models.append(
            {
                "agent": agent,
                "provider": spec.provider,
                "model": spec.model,
                "parameter_size": spec.param_size,
                "temperature": spec.temperature,
            }
        )
    metadata = {
        "system": "K3 Day 09 - Multi-Agent E-commerce Dispute Resolution",
        "policy_version": "EC_POLICY_V1",
        "framework": "Python thuần, orchestrator tự viết, OpenAI SDK làm client cho cả OpenAI và Groq",
        "agents": models,
        "runtime": {
            "python": platform.python_version(),
            "os": f"{platform.system()} {platform.release()}",
            "cases": case_count,
            "wall_clock_seconds": round(runtime_s, 1),
            "mode": "offline_rule_engine" if offline else "multi_agent",
        },
    }
    METADATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(METADATA_PATH, "w", encoding="utf-8") as fh:
        json.dump(metadata, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def main() -> int:
    # Console Windows mặc định là cp1252, in tiếng Việt vào đó là crash cả lượt
    # chạy. Ép UTF-8 để log không bao giờ giết được job.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(INPUT_DIR))
    parser.add_argument("--output", default=str(OUTPUT_DIR))
    parser.add_argument("--trace", default=str(TRACE_PATH))
    parser.add_argument("--offline", action="store_true", help="chỉ chạy rule engine, không gọi LLM")
    parser.add_argument("--audit", action="store_true", help="soi case bẫy, không ghi output")
    parser.add_argument("--cases", nargs="*", help="chạy riêng vài case, ví dụ EC_001")
    parser.add_argument(
        "--variant",
        default="base",
        choices=sorted(VARIANTS),
        help="cách diễn giải luật, dùng để A/B: " + " | ".join(f"{k}={v}" for k, v in VARIANTS.items()),
    )
    args = parser.parse_args()

    if args.audit:
        args.offline = True

    if not args.offline:
        # Chỉ cần .env và thư viện openai khi thực sự gọi LLM, để chế độ
        # --offline chạy được ngay cả khi chưa cài dependency.
        from dotenv import load_dotenv

        load_dotenv()

    input_dir = Path(args.input)
    output_dir = Path(args.output)
    cases = read_cases(input_dir, args.cases)
    if not cases:
        print(f"Không tìm thấy case nào trong {input_dir}")
        return 1

    needed = {c["customer_request"]["claimed_order_id"] for c in cases}
    started = time.monotonic()
    data = loader.load(DATA_DIR, needed_order_ids=needed)
    print(f"Đã nạp dữ liệu cho {len(data.orders)}/{len(needed)} order trong {time.monotonic() - started:.1f}s")

    if args.audit:
        from .audit import audit

        audit(cases, data)
        return 0

    tracer = Tracer(Path(args.trace))
    summary: dict[str, int] = {}
    invalid: list[str] = []

    try:
        if args.offline:
            for case in cases:
                output, facts = run_offline(case, data, tracer, args.variant)
                problems = validate(output, data, facts)
                if problems:
                    invalid.append(f"{case['case_id']}: {problems}")
                write_output(output_dir, case["case_id"], output)
                issue = output["assessment"]["primary_issue"]
                summary[issue] = summary.get(issue, 0) + 1
        else:
            from .agents.coordinator import Coordinator
            from .llm import LLMClient

            llm = LLMClient()
            coordinator = Coordinator(data, llm, tracer, variant=args.variant)

            def handle(case: dict) -> dict:
                try:
                    return coordinator.run_case(case)
                except Exception as exc:  # không để một case làm hỏng cả lượt chạy
                    tracer.write(case_id=case["case_id"], agent="main", event="case_crashed", error=str(exc))
                    output, _ = run_offline(case, data, tracer, args.variant)
                    return output

            with ThreadPoolExecutor(max_workers=CASE_WORKERS) as pool:
                results = list(pool.map(handle, cases))

            for case, output in zip(cases, results):
                problems = validate(output, data, None)
                if problems:
                    invalid.append(f"{case['case_id']}: {problems}")
                write_output(output_dir, case["case_id"], output)
                issue = output["assessment"]["primary_issue"]
                summary[issue] = summary.get(issue, 0) + 1
    finally:
        tracer.close()

    runtime_s = time.monotonic() - started
    write_metadata(runtime_s, len(cases), args.offline)

    print(f"\nXong {len(cases)} case trong {runtime_s:.1f}s")
    for issue, count in sorted(summary.items(), key=lambda kv: -kv[1]):
        print(f"  {issue}: {count}")
    if invalid:
        print(f"\n{len(invalid)} case KHÔNG đạt schema:")
        for line in invalid:
            print(f"  {line}")
        return 1
    print("\nTất cả output đạt schema.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
