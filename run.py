"""Coordinator entry point: input/EC_*.json -> output/EC_*.json.

Flow per case:
    coordinator -> order_seller -> payment -> delivery -> policy -> verifier

trace.jsonl is TRUNCATED on every run (README section 8 asks for the latest run
only, never an append log).
"""

import argparse
import json
import platform
import sys
import time
from pathlib import Path

from src.agents import delivery_agent, order_seller_agent, payment_agent, policy_agent
from src.config import (
    COHORT,
    INPUT_DIR,
    LOG_DIR,
    OUTPUT_DIR,
    POLICY_VERSION,
    active_provider,
)
from src.data_store import DataStore
from src.llm import LLMClient
from src.schema import build_output, verify

TRACE_PATH = LOG_DIR / "trace.jsonl"
METADATA_PATH = LOG_DIR / "metadata.json"


def run_case(
    case_path: Path,
    store: DataStore,
    client: LLMClient,
    trace,
    precision: bool = False,
) -> tuple[dict, list[str]]:
    case = json.loads(case_path.read_text(encoding="utf-8"))
    case_id = case["case_id"]
    claimed_order_id = case.get("customer_request", {}).get("claimed_order_id", "")

    # Coordinator: the claim is a lead, not a fact. Everything is re-derived
    # from the CSVs before any conclusion is drawn.
    facts = store.get_order_facts(claimed_order_id)
    trace.write(json.dumps({
        "ticket_id": case_id,
        "agent": "coordinator",
        "event": "dispatch",
        "claimed_order_id": claimed_order_id,
        "order_found": facts.exists,
        "assigned_to": ["order_seller", "payment", "delivery"],
    }, ensure_ascii=False) + "\n")

    upstream = [
        order_seller_agent(client, case_id, facts),
        payment_agent(client, case_id, facts),
        delivery_agent(client, case_id, facts),
    ]
    for handoff in upstream:
        trace.write(json.dumps({"event": "handoff", **handoff.to_dict()}, ensure_ascii=False) + "\n")

    policy_handoff, decision, confidence = policy_agent(client, case_id, facts, upstream)
    trace.write(json.dumps({"event": "handoff", **policy_handoff.to_dict()}, ensure_ascii=False) + "\n")

    payload = build_output(case_id, facts, decision, confidence, precision=precision)
    problems = verify(payload, store)
    trace.write(json.dumps({
        "ticket_id": case_id,
        "agent": "verifier",
        "event": "verify",
        "passed": not problems,
        "problems": problems,
        "primary_issue": payload["assessment"]["primary_issue"],
        "recommended_refund_brl": payload["financial_resolution"]["recommended_refund_brl"],
    }, ensure_ascii=False) + "\n")

    return payload, problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="process only the first N cases")
    parser.add_argument("--no-llm", action="store_true", help="deterministic only, skip all LLM calls")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument(
        "--precision",
        action="store_true",
        help="report sellers only when the fired rule implicates them",
    )
    parser.add_argument("--out", type=Path, default=None, help="write rulings here instead of output/")
    args = parser.parse_args()

    out_dir = args.out or OUTPUT_DIR

    cases = sorted(INPUT_DIR.glob("EC_*.json"))
    if args.limit:
        cases = cases[: args.limit]
    if not cases:
        print("no input cases found in input/", file=sys.stderr)
        return 1

    started = time.time()
    store = DataStore().load()
    print(f"loaded CSVs in {time.time() - started:.1f}s")

    provider = active_provider()
    client = LLMClient(use_cache=not args.no_cache)
    if args.no_llm:
        client.chat = lambda *a, **k: ""  # type: ignore[method-assign]

    out_dir.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    failures: list[str] = []
    issue_counts: dict[str, int] = {}

    # "w" not "a": the trace holds the latest run only.
    with TRACE_PATH.open("w", encoding="utf-8") as trace:
        for index, case_path in enumerate(cases, start=1):
            payload, problems = run_case(case_path, store, client, trace, precision=args.precision)
            (out_dir / case_path.name).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            issue = payload["assessment"]["primary_issue"]
            issue_counts[issue] = issue_counts.get(issue, 0) + 1
            if problems:
                failures.append(f"{payload['case_id']}: {problems}")
            print(f"[{index}/{len(cases)}] {payload['case_id']} {issue} "
                  f"refund={payload['financial_resolution']['recommended_refund_brl']} "
                  f"{'OK' if not problems else 'VERIFY-FAIL'}")

    elapsed = round(time.time() - started, 1)
    METADATA_PATH.write_text(json.dumps({
        "cohort": COHORT,
        "starter_repo": "K3-Day9-Multi-Agent-A2A",
        "policy_version": POLICY_VERSION,
        "model": provider["model"],
        "parameter_size": provider["parameter_size"],
        "provider": provider["name"],
        "framework": "custom multi-agent orchestration (Python stdlib, OpenAI-compatible chat API)",
        "runtime": f"Python {platform.python_version()} on {platform.system()} {platform.release()}",
        "agents": ["coordinator", "order_seller", "payment", "delivery", "policy", "verifier"],
        "entity_reporting": "precision" if args.precision else "wide",
        "cases_processed": len(cases),
        "llm_calls": client.calls,
        "llm_cache_hits": client.cache_hits,
        "llm_failures": client.failures,
        "run_seconds": elapsed,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n--- distribution ---")
    for issue, count in sorted(issue_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {issue:26} {count}")
    print(f"\ncases={len(cases)} verify_failures={len(failures)} "
          f"llm_calls={client.calls} cache_hits={client.cache_hits} "
          f"llm_failures={client.failures} elapsed={elapsed}s")
    for failure in failures:
        print("  FAIL", failure)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
