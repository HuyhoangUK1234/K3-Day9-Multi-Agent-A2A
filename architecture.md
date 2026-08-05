# Architecture — K3 Day 9 Multi-Agent A2A

Cohort **K3**, policy **EC_POLICY_V1**. Six agents investigate 50 e-commerce
dispute tickets against the Olist dataset and produce one grounded JSON ruling
per ticket.

## 1. Agent map

```
                    input/EC_###.json
                            |
                    +---------------+
                    |  Coordinator  |   resolves claimed_order_id -> OrderFacts
                    +---------------+   dispatches, then assembles
                       /    |     \
                      /     |      \
        +-------------+ +---------+ +----------+
        | Order &     | | Payment | | Delivery |
        | Seller      | |         | |          |
        +-------------+ +---------+ +----------+
                      \     |      /
                       \    |     /            3 handoff packets
                    +---------------+
                    | Policy Agent  |   applies EC_POLICY_V1 priority order
                    +---------------+
                            |
                    +---------------+
                    |   Verifier    |   schema + evidence + arithmetic gate
                    +---------------+
                            |
                    output/EC_###.json
```

## 2. Roles, data access and authority

| Agent          | Reads                                     | Decides                                                  | Cannot touch                   |
| -------------- | ----------------------------------------- | -------------------------------------------------------- | ------------------------------ |
| Coordinator    | `input/`, `orders`                    | which agents run, final assembly                         | policy outcome                 |
| Order & Seller | `orders`, `order_items`, `sellers`  | order state, which seller missed its handoff limit       | payments, delivery verdict     |
| Payment        | `order_payments`, `order_items`       | whether payments reconcile against item + freight        | delivery dates, policy outcome |
| Delivery       | `orders`, `order_items`               | delivered-after-estimate, carrier-vs-shipping-limit      | money amounts                  |
| Policy         | the three handoff packets + derived facts | `primary_issue`, root cause, responsible party, refund | raw CSV access                 |
| Verifier       | assembled JSON,`DataStore`              | pass / fail before the file is written                   | changing the ruling            |

Each domain agent sees only its slice. The Policy Agent never reads CSVs
directly — it works from what upstream handed it, which is what makes the
handoff meaningful rather than decorative.

## 3. Handoff packet

Every agent-to-agent message carries the five fields the Codelab requires
(`src/agents.py`, `Handoff`):

```json
{
  "agent": "order_seller",
  "ticket_id": "EC_001",
  "question": "Did any seller hand off after its shipping limit?",
  "facts": {"order_status": "delivered", "sellers_past_limit": ["f7496d..."]},
  "evidence_ids": ["order:e2a03c...", "item:e2a03c...:1", "seller:f7496d..."],
  "missing": [],
  "next_suggestion": "hand to policy agent"
}
```

`missing` is the honest channel: an agent that cannot establish a fact says so
instead of inventing one. Every packet is appended to `logging/trace.jsonl`.

## 4. Division of labour: who computes what

Python owns every **fact**; the LLM owns every **interpretation**.

- Joins, date comparisons, sums and rounding are deterministic Python
  (`src/data_store.py`, `src/policy.py`). A model at or under 10B parameters is
  not reliable at arithmetic or date ordering, and a single wrong subtraction
  flips the responsible party.
- The LLM agents read the derived facts, state what they conclude, flag gaps and
  address the next agent. The Policy Agent additionally names the rule it thinks
  fired.
- **The deterministic engine is authoritative.** When the Policy Agent's LLM
  answer disagrees, the deterministic answer still ships and the disagreement is
  recorded in the trace and shaves the reported `confidence`. The model can
  express doubt; it cannot overrule evidence.

## 5. Grounding rules

Only five evidence shapes are constructible from the data, and the Verifier
re-checks each one against the loaded CSVs before the file is written:

```
order:<order_id>
item:<order_id>:<order_item_id>
payment:<order_id>:<payment_sequential>
seller:<seller_id>
policy:<root_cause_code>
```

Olist has no refund ledger, transaction ID or per-item tracking checkpoint, so
no evidence of those kinds is ever emitted. `affected_entities.item_ids` and
`payment_ids` deliberately carry **no prefix** while `evidence_ids` do — two
conventions that live side by side in the schema.

The customer message is treated as a **lead, not a fact**. 25 of the 50 tickets
claim late delivery, but only 16 orders were actually delivered after the
estimate; the other 9 resolve to `unsupported_late_claim`. Every ruling is
re-derived from `claimed_order_id` against the CSVs.

## 6. Policy application order

`EC_POLICY_V1` is priority-ordered — the first matching rule wins even when a
later one also matches (a canceled order that was also delivered late is
`canceled_order_paid`, never `late_delivery_*`):

1. `canceled_order_paid` → platform / `OLIST_PLATFORM`, refund = payment total
2. `unavailable_order_paid` → platform / `OLIST_PLATFORM`, refund = payment total
3. `late_delivery_seller` → seller, refund = freight total
4. `late_delivery_logistics` → `LOGISTICS_PROVIDER`, refund = freight total
5. `valid_split_payment` → no party, refund 0
6. `unsupported_late_claim` → no party, refund 0 (also the safe fallback)

Seller vs logistics turns on `order_delivered_carrier_date` against that
seller's `shipping_limit_date` — not on the customer delivery timestamp.

## 7. Verifier gate

`src/schema.py::verify` blocks a file that has any of:

- `primary_issue`, `cause_code`, `action` or `case_status` outside the enums
- `confidence` outside `[0, 1]`
- an evidence or entity ID absent from the CSVs, or a malformed one
- a prefixed ID leaking into `affected_entities`
- more than 5 entity IDs, 10 evidence, 3 causes, 3 parties or 5 actions
- money not rounded to 2 decimals
- `case_status` disagreeing with `recommended_refund_brl`

Failures are reported per case and counted at the end of the run; the ruling is
fixed at its cause, never patched by hand.

## 8. Reliability

- **Disk cache** keyed by `(model, messages)` — a re-run after a fix only pays
  for what changed.
- **Retry with exponential backoff**, extra delay on HTTP 429.
- **LLM failure is non-fatal.** If the provider is unreachable the deterministic
  engine still produces a correct, fully-evidenced ruling; only `confidence`
  and the trace narrative are affected.
- `logging/trace.jsonl` is truncated on every run, so it always holds the latest
  run only.

## 9. Models

All agents share one model, at or under 10B parameters. Selected after
benchmarking on this machine (RTX 5060 Laptop, 8 GB VRAM):

| Provider          | Model                    | Params | Measured    | Role             |
| ----------------- | ------------------------ | -----: | ----------- | ---------------- |
| Groq              | `llama-3.1-8b-instant` |     8B | 0.65 s/call | primary          |
| LM Studio (local) | `qwen/qwen3-1.7b`      |   1.7B | 24.7 tok/s  | offline fallback |
| Mistral           | `ministral-3-8b-25-12` |     8B | —          | API fallback     |

`google/gemma-4-e4b` (7.5B) was benchmarked and rejected: the locally available
Q6_K build is 7.21 GB and does not fit in 7.96 GB of VRAM alongside the KV
cache, so it partially offloads to CPU and drops to 2.8 tok/s.

Model names are declared in `src/config.py` and mirrored into
`logging/metadata.json`. Credentials live only in `.env`, which is gitignored.

## 10. Run

```bash
python run.py                # all 50 cases through the full agent team
python run.py --limit 3      # smoke test
python run.py --no-llm       # deterministic only, no network
```

**Diff giữa hai bộ output cho ra đúng hai chỗ lệch, không hơn:**

Tớ so từng trường của 50 case. 10 trong 12 trường trùng khít — primary_issue, case_status, cả 4 danh sách entity, root cause, responsible parties, actions, cả 4 con số tiền. Nghĩa là bảng luật và phần tính toán của `tien` vốn đã đúng. Chỉ lệch:

1. **`confidence`: 0.95 với 1.0** ở cả 50 case.
2. **`evidence_ids`: thừa 34 ID `seller:`** — đúng 34 case mà seller không có lỗi (50 trừ 8 case seller bàn giao muộn, trừ 8 đơn `unavailable` vốn không có seller nào).

Ngoài ra 16 case chỉ khác thứ tự evidence (bản 100 điểm đặt `policy:` ngay sau `order:`), tập ID giống hệt.

**Điều này lật ngược một giả định của tớ.** Tớ đã nghĩ evidence chấm theo độ phủ nên nhồi càng nhiều ID hợp lệ càng tốt. Sai. Hai trường mang ID được chấm ngược nhau:

* `affected_entities` chấm theo **độ phủ** — nên `seller_ids` vẫn phải liệt kê đủ seller của đơn, kể cả khi seller không có lỗi.
* `evidence_ids` chấm theo **độ chính xác** — ID có thật trong CSV nhưng kết luận không dựa vào nó vẫn bị trừ. README mục 5 chỉ nói ID không tồn tại hoặc sai định dạng mới bị tính false positive, nhưng thực tế thang chấm khắt khe hơn thế.

Và `confidence` được thưởng thẳng chứ không phạt việc khai chắc chắn — nên khai đủ 1.0 khi dữ liệu đủ.
