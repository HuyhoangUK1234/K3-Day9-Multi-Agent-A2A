# Báo cáo vai trò cá nhân - Day 9: Multi Agent A2A

## 1. Thông tin cá nhân

| Thông tin | Nội dung |
| --- | --- |
| Họ và tên | Huỳnh Hoàng Việt |
| MSSV | 2A202601105 |
| Khóa/Lớp | K3 |
| Vai trò chính | Delivery Agent |
| Ngày hoàn thành | 2026-08-05 |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable | File/hàm phụ trách | Input nhận vào | Output bàn giao | Trạng thái |
| --- | --- | --- | --- | --- |
| Delivery Agent | `src/agents.py::delivery_agent` | `case_id`, `OrderFacts`, `LLMClient` | `Handoff` cho Policy Agent | Hoàn thành |
| Logic xác định giao trễ | `src/data_store.py::OrderFacts.delivered_late` | `order_delivered_customer_date`, `order_estimated_delivery_date` | Boolean `delivered_after_estimate` | Hoàn thành |
| Logic hỗ trợ phân biệt seller/logistics | `src/data_store.py::OrderFacts.late_sellers()` | `order_delivered_carrier_date`, `shipping_limit_date` của từng item | Danh sách seller bàn giao trễ | Hoàn thành |
| Trace và evidence cho delivery | `logging/trace.jsonl`, output từ `delivery_agent` | Thông tin đơn hàng đã được join | `evidence_ids`, `missing`, `agent_view` | Hoàn thành |

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động | Thành viên/module được hỗ trợ | Kết quả |
| --- | --- | --- |
| Đồng bộ contract handoff | Policy Agent, Verifier | Delivery Agent trả về đúng cấu trúc `Handoff`, giúp Policy Agent áp dụng đúng rule `late_delivery_seller`, `late_delivery_logistics`, hoặc `unsupported_late_claim`. |
| Kiểm tra dữ liệu thiếu | Policy Agent | Nếu thiếu `order_delivered_customer_date` hoặc `order_estimated_delivery_date`, Delivery Agent đưa vào trường `missing` thay vì tự suy diễn. |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao | Cách xác minh |
| --- | --- | --- | --- |
| Xác định đơn có giao sau ngày dự kiến hay không | `src/data_store.py::OrderFacts.delivered_late` | Giá trị `delivered_after_estimate` trong handoff | Chạy `python run.py --no-llm --limit 3` và xem `logging/trace.jsonl` |
| Xác định tín hiệu phân biệt lỗi seller/logistics | `src/data_store.py::OrderFacts.late_sellers()` và `src/agents.py::delivery_agent` | Giá trị `carrier_pickup_after_shipping_limit` | Kiểm tra handoff của agent `delivery` trong trace |
| Đóng gói kết quả cho Policy Agent | `src/agents.py::Handoff` | Packet gồm `facts`, `evidence_ids`, `missing`, `next_suggestion` | Output 50 case verify pass |
| Đảm bảo không tạo bằng chứng không có trong CSV | `src/agents.py::delivery_agent`, `src/schema.py::verify` | Evidence delivery chỉ dùng `order:<order_id>` khi order tồn tại | Verifier không báo lỗi evidence |

Artifact cụ thể của phần Delivery Agent là các dòng trace có `"agent": "delivery"` trong `logging/trace.jsonl`. Mỗi trace ghi lại kết quả so sánh ngày giao thực tế với ngày giao dự kiến, thông tin carrier pickup có quá shipping limit hay không, các trường dữ liệu bị thiếu nếu có, và gợi ý chuyển tiếp sang Policy Agent.

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Trong bài toán dispute resolution, nội dung khách hàng gửi lên chỉ được xem là một đầu mối. Delivery Agent cần kiểm tra bằng dữ liệu thật trong Olist để trả lời hai câu hỏi:

1. Đơn hàng có giao trễ so với ngày giao dự kiến hay không.
2. Nếu giao trễ, tín hiệu delivery có cho thấy seller bàn giao cho carrier quá hạn hay không, để Policy Agent phân biệt giữa lỗi seller và lỗi logistics.

Kết quả này ảnh hưởng trực tiếp đến các rule:

- `late_delivery_seller`
- `late_delivery_logistics`
- `unsupported_late_claim`

### Cách triển khai

Delivery Agent nhận một object `OrderFacts` đã được `DataStore` tạo từ các file CSV. Các phép tính quan trọng không để LLM tự tính mà được Python tính sẵn:

- `OrderFacts.delivered_late`: trả về `True` khi `order_delivered_customer_date > order_estimated_delivery_date`.
- `OrderFacts.late_sellers()`: trả về danh sách seller có `order_delivered_carrier_date > shipping_limit_date`.

Trong `delivery_agent`, các giá trị này được đóng gói vào `payload` gồm:

- `order_id`
- `order_status`
- `estimated_delivery_date`
- `delivered_customer_date`
- `delivered_after_estimate`
- `delivered_carrier_date`
- `carrier_pickup_after_shipping_limit`

LLM chỉ nhận các fact đã tính sẵn để diễn giải góc nhìn `agent_view`, ví dụ `seller`, `logistics_provider`, hoặc `none`. Nếu model trả lời sai hoặc không trả lời, pipeline vẫn không bị dừng vì Policy Agent và deterministic policy engine vẫn dựa trên fact từ Python.

Delivery Agent cũng xử lý missing data một cách rõ ràng:

- Nếu thiếu `order_delivered_customer_date`, thêm `"order_delivered_customer_date is empty"` vào `missing`.
- Nếu thiếu `order_estimated_delivery_date`, thêm `"order_estimated_delivery_date is empty"` vào `missing`.

Agent không tự tạo tracking checkpoint, refund ledger hay transaction ID vì các bảng này không tồn tại trong Olist dataset.

### Input, output và contract

| Thành phần | Mô tả |
| --- | --- |
| Input | `case_id`, `LLMClient`, `OrderFacts` của order được claim |
| Output | `Handoff` từ Delivery Agent sang Policy Agent |
| Module phụ thuộc | `src.data_store.OrderFacts`, `src.llm.LLMClient`, `src.agents.Handoff` |
| Module sử dụng output | `src.agents.policy_agent`, `src.policy.decide`, `src.schema.build_output` |
| Điều kiện lỗi cần xử lý | Order không tồn tại, thiếu ngày giao cho khách, thiếu ngày giao dự kiến, thiếu ngày carrier nhận hàng |

Contract output của Delivery Agent:

```json
{
  "agent": "delivery",
  "ticket_id": "EC_001",
  "question": "Was the order delivered after the estimate, and who caused the delay?",
  "facts": {
    "order_id": "...",
    "order_status": "delivered",
    "estimated_delivery_date": "...",
    "delivered_customer_date": "...",
    "delivered_after_estimate": true,
    "delivered_carrier_date": "...",
    "carrier_pickup_after_shipping_limit": true,
    "agent_view": "seller"
  },
  "evidence_ids": ["order:<order_id>"],
  "missing": [],
  "next_suggestion": "hand to policy agent"
}
```

### Cách xác minh

```bash
python run.py --no-llm --limit 3
python run.py --no-llm
```

- Kết quả mong đợi: Mỗi case tạo được output JSON đúng schema, có primary issue và refund phù hợp với policy.
- Kết quả thực tế: Lần chạy gần nhất trong `logging/metadata.json` ghi nhận `cases_processed = 50`, `llm_failures = 0`, `run_seconds = 1.4`.
- Artifact/log: `logging/trace.jsonl`, `logging/metadata.json`, các file trong `output/EC_001.json` đến `output/EC_050.json`.

## 5. Một quyết định kỹ thuật quan trọng

- Bối cảnh: Delivery Agent phải so sánh các timestamp để xác định giao trễ, trong khi LLM nhỏ hơn hoặc bằng 10B parameters không ổn định khi tính toán ngày tháng.
- Các phương án đã cân nhắc: Để LLM đọc timestamp và tự kết luận giao trễ; hoặc để Python tính sẵn các boolean, LLM chỉ diễn giải kết quả.
- Phương án đã chọn: Dùng Python deterministic để tính `delivered_late` và `late_sellers()`, sau đó Delivery Agent chỉ đóng gói và giải thích fact.
- Lý do: Cách này giảm lỗi so sánh ngày tháng, tăng khả năng lặp lại kết quả, và tránh việc model tạo ra bằng chứng không có trong CSV.
- Bằng chứng quyết định phù hợp: `schema.verify` pass cho output, trace ghi đầy đủ handoff, và metadata cho thấy 50 case đã được xử lý.

## 6. Một lỗi hoặc blocker đã xử lý

- Triệu chứng/lỗi nguyên văn: Một số đơn hàng không có đầy đủ timestamp delivery, đặc biệt các trường `order_delivered_customer_date` hoặc `order_delivered_carrier_date` có thể rỗng.
- Lệnh hoặc bước tái hiện: Chạy pipeline trên toàn bộ input bằng `python run.py --no-llm` và kiểm tra handoff của Delivery Agent trong `logging/trace.jsonl`.
- Nguyên nhân gốc: Olist dataset có nhiều trạng thái đơn hàng khác nhau như `canceled`, `unavailable`, hoặc đơn chưa có đủ mốc giao hàng.
- Cách xử lý: Delivery Agent không suy diễn ngày thiếu. Agent ghi rõ các trường thiếu vào `missing`; `delivered_late` trả về `False` khi không đủ ngày cần so sánh.
- Cách xác minh sau khi sửa: Verifier không báo lỗi schema/evidence; Policy Agent vẫn có thể xử lý bằng các rule ưu tiên như `canceled_order_paid` và `unavailable_order_paid`.
- Điều học được: Trong bài toán multi-agent, việc nói rõ "không đủ dữ liệu" quan trọng ngang với việc đưa ra kết luận, vì nó giúp agent sau không đưa ra quyết định dựa trên giả định sai.

## 7. Hiểu biết về luồng end-to-end

1. Input case nằm trong `input/EC_###.json`. Coordinator đọc `claimed_order_id`, sau đó `DataStore` lấy thông tin từ các CSV Olist và tạo `OrderFacts`.
2. Ba domain agent chạy song song về mặt logic: Order & Seller Agent kiểm tra trạng thái đơn và seller handoff, Payment Agent đối soát tiền, Delivery Agent kiểm tra giao hàng trễ và tín hiệu seller/logistics.
3. Mỗi domain agent trả về một `Handoff` gồm facts, evidence, missing fields và gợi ý agent tiếp theo. Các handoff này được ghi vào `logging/trace.jsonl`.
4. Policy Agent nhận các handoff và fact đã tính sẵn, sau đó áp dụng `EC_POLICY_V1` theo thứ tự ưu tiên. Nếu một rule trước đã match, các rule sau không được override.
5. `build_output` lập JSON theo schema nộp bài, gồm assessment, affected entities, root cause, evidence IDs, financial resolution và resolution actions.
6. Verifier kiểm tra output trước khi ghi file: enum hợp lệ, evidence tồn tại trong CSV, tiền làm tròn 2 chữ số, giới hạn số lượng ID, và `case_status` khớp với refund.
7. Kết quả cuối cùng nằm trong `output/EC_001.json` đến `output/EC_050.json`. Folder `output/` là artifact chính để nén zip nộp bài.

## 8. Cam kết của thành viên

- [x] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [x] Tôi không ghi "đã chạy thành công" cho phần chưa được kiểm chứng.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Huỳnh Hoàng Việt  
**Ngày xác nhận:** 2026-08-05
