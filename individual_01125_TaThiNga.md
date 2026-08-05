# Báo cáo vai trò cá nhân - Day 9: Multi Agent A2A

## 1. Thông tin cá nhân

| Thông tin | Nội dung |
| --- | --- |
| Họ và tên | Tạ Thị Nga |
| MSSV | 2A202601125 |
| Khóa/Lớp | K3 |
| Vai trò chính | Payment Agent |
| Ngày hoàn thành | 2026-08-05 |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable | File/hàm phụ trách | Input nhận vào | Output bàn giao | Trạng thái |
| --- | --- | --- | --- | --- |
| Payment Agent | `src/agents.py::payment_agent` | `case_id`, `OrderFacts`, `LLMClient` | `Handoff` cho Policy Agent | Hoàn thành |
| Logic tính tổng thanh toán | `src/data_store.py::OrderFacts.payment_total` | `payments` từ dataset | Số thực `payment_total` | Hoàn thành |
| Logic đối soát khoản tiền | `src/data_store.py::OrderFacts.payment_reconciles()` | Tổng thanh toán và tổng `item_total + freight_total` | Boolean `reconciles_within_0_10` | Hoàn thành |
| Trace và evidence cho payment | `logging/trace.jsonl`, output từ `payment_agent` | Thông tin thanh toán (payment rows) | `evidence_ids`, `missing`, `agent_view` | Hoàn thành |

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động | Thành viên/module được hỗ trợ | Kết quả |
| --- | --- | --- |
| Cung cấp biến thanh toán | Policy Agent | Đảm bảo Policy Agent nhận đúng cờ `payment_reconciles` để chạy rule `valid_split_payment`. |
| Ngăn ngừa LLM hallucination | Toàn bộ team | Đẩy toàn bộ tác vụ cộng trừ số thập phân về cho Python xử lý thay vì bắt LLM 8B tính toán. |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao | Cách xác minh |
| --- | --- | --- | --- |
| Tổng hợp và làm tròn payment | `src/data_store.py::OrderFacts.payment_total` | Tổng payment chuẩn 2 chữ số thập phân | Chạy logic test và xem payload trong trace |
| Tính toán dung sai 0.10 BRL | `src/data_store.py::OrderFacts.payment_reconciles` | Cờ đối soát `True/False` | Kiểm tra handoff của agent `payment` |
| Đóng gói kết quả cho Policy Agent | `src/agents.py::Handoff` | Packet gồm `facts`, `evidence_ids`, `missing`, `next_suggestion` | Output 50 case verify pass |
| Trích xuất Evidence IDs | `src/agents.py::payment_agent` | `payment:<order_id>:<sequential>` | Verifier không báo lỗi sai evidence format |

Artifact cụ thể của phần Payment Agent là các dòng trace có `"agent": "payment"` trong `logging/trace.jsonl`. Mỗi trace ghi lại kết quả đối soát thanh toán so với giá trị đơn hàng, danh sách các ID của payment row làm bằng chứng, các thông tin bị thiếu (nếu không có row payment nào), và gợi ý chuyển tiếp sang Policy Agent.

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Trong bài toán xử lý khiếu nại, một nguyên nhân phổ biến là khách hàng bị chia nhỏ thanh toán (split payment) hoặc có sai lệch về số tiền (vd: trả góp, phí vận chuyển). Payment Agent cần giải quyết:

1. Đơn hàng có bị chia thành nhiều dòng thanh toán hay không?
2. Tổng số tiền khách trả có khớp với tổng giá trị hàng (`price`) + phí vận chuyển (`freight_value`) với sai số cho phép 0.10 BRL hay không.

Kết quả này ảnh hưởng tới:
- `valid_split_payment`
- Góp phần giúp Policy Agent biết đơn đã trả tiền chưa để xét `canceled_order_paid` hoặc `unavailable_order_paid`.

### Cách triển khai

Tương tự các agent khác, Payment Agent nhận `OrderFacts` làm input. Điểm mấu chốt là **tuyệt đối không giao cho LLM làm toán**:
- `payment_total` tính bằng `sum(p.payment_value)` và dùng `round(..., 2)`.
- `payment_reconciles()` tính khoảng cách `abs(payment_total - expected) <= 0.10`.

Agent sẽ nhồi vào payload gửi cho LLM các biến số này, bao gồm cả `expected_total` và mảng thông tin từng dòng payment (tối đa 5 dòng). LLM chỉ đóng vai trò phân tích xem với những fact như vậy, thanh toán có được "reconciled" (đối soát khớp) hay không.

Nếu đơn hàng không có dòng payment nào, hệ thống tự động ghi `"order has no payment rows"` vào mảng `missing` để báo cho Policy Agent biết.

### Input, output và contract

| Thành phần | Mô tả |
| --- | --- |
| Input | `case_id`, `LLMClient`, `OrderFacts` của order được claim |
| Output | `Handoff` từ Payment Agent sang Policy Agent |
| Module phụ thuộc | `src.data_store.OrderFacts`, `src.llm.LLMClient`, `src.agents.Handoff` |
| Module sử dụng output | `src.agents.policy_agent`, `src.policy.decide` |
| Điều kiện lỗi cần xử lý | Order không có thanh toán, sai số thập phân khi cộng float |

Contract output của Payment Agent:

```json
{
  "agent": "payment",
  "ticket_id": "EC_001",
  "question": "Do the payment rows reconcile against item + freight?",
  "facts": {
    "order_id": "...",
    "payment_rows": [...],
    "payment_total": 115.50,
    "item_total": 100.50,
    "freight_total": 15.00,
    "expected_total": 115.50,
    "reconciles_within_0_10": true,
    "agent_view": true
  },
  "evidence_ids": ["payment:<order_id>:1"],
  "missing": [],
  "next_suggestion": "hand to policy agent"
}
```

### Cách xác minh

```bash
python run.py --no-llm --limit 3
python run.py
```

- Kết quả mong đợi: `Handoff` ghi nhận `agent_view` là boolean chính xác so với `reconciles_within_0_10`. Tiền luôn chuẩn 2 chữ số thập phân.
- Kết quả thực tế: `output` pass toàn bộ Verifier liên quan đến schema tài chính.

## 5. Một quyết định kỹ thuật quan trọng

- Bối cảnh: Việc so khớp tiền lẻ bằng Python sinh ra những sai số dấu phẩy động (float precision), ví dụ `10.100000000000001 != 10.10`. Thêm vào đó, LLM cực kỳ yếu trong việc tự cộng dồn mảng các payment rows.
- Các phương án đã cân nhắc: Để LLM tự nhẩm tính và trả ra tổng số tiền; hoặc ép kiểu số thập phân cố định và tính toàn bộ bằng Python, LLM chỉ review.
- Phương án đã chọn: Tính bằng Python `abs(payment_total - expected) <= tolerance` và làm tròn số ở mọi property `_total`. Đẩy kết quả boolean cho LLM.
- Lý do: Loại bỏ hoàn toàn 100% tỷ lệ LLM cộng sai hoặc sinh ra số ảo. Agent trở thành một rào chắn an toàn, tuân thủ đúng kiến trúc Deterministic-Core.
- Bằng chứng quyết định phù hợp: Pass 100% auto-grader về độ chính xác số học `financial_resolution`.

## 6. Một lỗi hoặc blocker đã xử lý

- Triệu chứng/lỗi nguyên văn: LLM đôi khi bịa (hallucinate) ra `payment_id` không có thực khi được yêu cầu cung cấp evidence cho output JSON.
- Lệnh hoặc bước tái hiện: Chạy qua 50 case, xem mảng `evidence_ids` ở verifier bị lỗi.
- Nguyên nhân gốc: LLM không có công cụ tra cứu ngược lại CSV một cách chính xác tuyệt đối đối với các ID dài ngoằng.
- Cách xử lý: Evidence ID được extract trực tiếp bằng list comprehension của Python: `evidence = [f"payment:{facts.order_id}:{p.payment_sequential}" for p in facts.payments[:5]]` ngay trong class Payment Agent thay vì bắt LLM generate.
- Cách xác minh sau khi sửa: Verifier hoàn toàn không còn bắt được lỗi ID bịa.
- Điều học được: Đừng bao giờ tin tưởng giao cho LLM tự sinh ra định danh (IDs) hoặc con số (Numbers) nếu hệ thống hoàn toàn có thể trích xuất nó bằng hardcode/logic thông thường.

## 7. Hiểu biết về luồng end-to-end

1. Input được lấy từ `input/EC_###.json`, `Coordinator` phân giải mã đơn hàng. `DataStore` truy xuất Olist CSV và đóng gói thành `OrderFacts`.
2. Dữ liệu được đưa vào 3 Domain Agents: Order & Seller, Payment, và Delivery. Mỗi agent nhận fact chuyên môn, thực hiện phân tích và format output bằng `Handoff`.
3. Policy Agent nhận toàn bộ Handoff từ 3 agent trên, kết hợp với deterministic engine trong `policy.py` để ra quyết định dựa theo độ ưu tiên của 6 rules.
4. Output cuối cùng được format theo đúng chuẩn schema nộp bài (gồm financial resolution, cause code) bởi `build_output` (nằm trong `schema.py`).
5. Verifier (chạy nội bộ trong code) đảm bảo output không sai schema hoặc có evidence hallucination. 
6. File được xuất ra `output/` sẵn sàng cho nén ZIP.

## 8. Cam kết của thành viên

- [x] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [x] Tôi không ghi "đã chạy thành công" cho phần chưa được kiểm chứng.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Tạ Thị Nga  
**Ngày xác nhận:** 2026-08-05
