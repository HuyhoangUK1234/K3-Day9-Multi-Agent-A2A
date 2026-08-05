# Báo cáo vai trò cá nhân - Day 9: Multi Agent A2A

## 1. Thông tin cá nhân

| Thông tin         | Nội dung            |
| ------------------ | -------------------- |
| Họ và tên       | Trần Thị Thanh Tâ |
| MSSV               | 2A202601267          |
| Khóa/Lớp         | K3                   |
| Vai trò chính    | Order & Seller Agent |
| Ngày hoàn thành | 2026/08/05           |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable                 | File/hàm phụ trách                 | Input nhận vào                         | Output bàn giao                                              | Trạng thái |
| ---------------------------------- | ------------------------------------- | ---------------------------------------- | ------------------------------------------------------------- | ------------ |
| Order & Seller Agent               | `src/agents.py::order_seller_agent` | `OrderFacts` từ `src/data_store.py` | `Handoff` cho Policy Agent                                  | Hoàn thành |
| Evidence & missing field reporting | `src/agents.py::order_seller_agent` | verified order facts                     | `facts`, `missing`, `evidence_ids`, `next_suggestion` | Hoàn thành |

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động                               | Thành viên/module được hỗ trợ | Kết quả                                                                                                               |
| ------------------------------------------ | ------------------------------------ | ----------------------------------------------------------------------------------------------------------------------- |
| Đồng bộ hợp đồng handoff với Policy | `src/agents.py::policy_agent`      | Đảm bảo`order_seller_agent` trả `agent_view` và evidence phù hợp để Policy Agent quyết định chính xác |
| Ghi trace test end-to-end                  | `run.py`                           | Trace đầy đủ 50 case trong`logging/trace.jsonl`                                                                   |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện                                  | File/hàm/artifact liên quan         | Kết quả bàn giao                                                                                | Cách xác minh                                                      |
| ------------------------------------------------------------ | ------------------------------------- | -------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| Phân tích trạng thái order và seller handoff thời hạn | `src/agents.py::order_seller_agent` | `Handoff` JSON cho Policy Agent với `seller_handoff`, `missing`                             | Kiểm tra`logging/trace.jsonl`, mỗi case có handoff order_seller |
| Tạo evidence ID đúng định dạng cho order/item/seller   | `src/agents.py::order_seller_agent` | `evidence_ids` chứa `order:<order_id>`, `item:<order_id>:<item_id>`, `seller:<seller_id>` | Kiểm tra output case và`schema.py::verify` pass                  |

Order & Seller Agent tạo ra bộ handoff facts cho Policy Agent, gồm trạng thái order, danh sách seller, và thông tin seller có bàn giao trễ. Artifact này được ghi vào `logging/trace.jsonl` và là input trực tiếp cho quyết định chính sách.

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Order & Seller Agent phải xác định đúng các sự thật về đơn hàng và seller dựa trên dữ liệu đã join từ CSV. Nhiệm vụ của tôi là không để LLM tự suy diễn thêm, chỉ cho nó xử lý dữ liệu đã có, và báo missing nếu dữ liệu thiếu.

### Cách triển khai

Tôi triển khai `order_seller_agent` trong `src/agents.py` với workflow sau:

- Nhận `OrderFacts` từ `DataStore` khi coordinator dispatch một case.
- Tính `late_sellers` dựa trên `facts.late_sellers()` và thông tin từng item trong `facts.items`.
- Chuẩn bị payload JSON chứa `order_id`, `order_status`, `item_count`, `seller_ids`, `shipping_limits` và danh sách seller quá hạn.
- Gọi LLM với `ORDER_SYSTEM` prompt để cho agent xác nhận trạng thái đơn và seller handoff.
- Kết hợp kết quả trả về với kiểm tra dữ liệu cứng: nếu order không tồn tại, nếu order không có item, nếu thiếu `order_delivered_carrier_date` thì đánh dấu `missing`.
- Tạo `evidence_ids` chỉ từ các ID có thể dựng được trực tiếp: order, item, seller.

### Input, output và contract

| Thành phần                   | Mô tả                                                                                            |
| ------------------------------ | -------------------------------------------------------------------------------------------------- |
| Input                          | `OrderFacts` từ `src/data_store.py`, bao gồm order, item, payment, delivery dates            |
| Output                         | `Handoff` object với `facts`, `evidence_ids`, `missing`, `next_suggestion`, `llm_raw` |
| Module phụ thuộc             | `src/data_store.py::OrderFacts`, `src/llm.py::LLMClient`, `src/llm.py::parse_json_object`    |
| Module sử dụng output        | `src/agents.py::policy_agent`, `run.py::run_case`, `src/schema.py::build_output`             |
| Điều kiện lỗi cần xử lý | order không tìm thấy, không có item row, thiếu`order_delivered_carrier_date`               |

### Cách xác minh

```bash
python run.py --limit 1
```

- **Kết quả mong đợi:** `order_seller` handoff được ghi trong `logging/trace.jsonl` và `output/EC_001.json` có evidence ID hợp lệ.
- **Kết quả thực tế:** Case chạy thành công, trace chứa handoff `agent: "order_seller"`, `evidence_ids` và `missing` đúng theo dữ liệu.
- **Artifact/log:** `logging/trace.jsonl`, `output/EC_001.json`.

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Cần quyết định cách xử lý khi agent LLM trả về kết quả khác với dữ liệu đã xác thực.
- **Các phương án đã cân nhắc:** (1) tin LLM hoàn toàn và dùng output của nó, (2) dùng LLM chỉ để diễn giải và dựa vào dữ liệu Python để kiểm chứng.
- **Phương án đã chọn:** Dùng LLM chỉ như một lớp giải thích, còn logic chính xác vẫn dựa trên `OrderFacts` và `late_sellers()` của Python.
- **Lý do:** Giữ đúng nguyên tắc không để LLM tự tạo ID hoặc phán đoán khi dữ liệu chưa đủ, giảm rủi ro evidence false positive và đảm bảo trace có thể kiểm chứng.
- **Bằng chứng quyết định phù hợp:** `order_seller_agent` tạo `missing` nếu thiếu dữ liệu, và output `policy_agent`/`verify` vẫn pass khi trace chỉ ra dữ liệu rõ ràng.

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng/lỗi nguyên văn:** Output `order_seller` thiếu `order_id` trong `evidence_ids` hoặc bao gồm seller ID không tồn tại.
- **Lệnh hoặc bước tái hiện:** Chạy `python run.py --limit 1` trên case có order tồn tại.
- **Nguyên nhân gốc:** `order_seller_agent` ban đầu dùng list `facts.seller_ids` mà không lọc đúng seller chịu trách nhiệm, nên có thể sinh evidence seller không liên quan.
- **Cách xử lý:** Sửa `evidence_ids` để chỉ dùng seller từ `late_sellers` nếu có, hoặc tối đa 3 seller hợp lệ. Đồng thời sử dụng `facts.exists` để tránh nộp `order:` khi order không tồn tại.
- **Cách xác minh sau khi sửa:** Chạy lại `python run.py --limit 1`, kiểm tra `order_seller` handoff và `schema.py::verify` pass.
- **Điều học được:** Luôn tách rõ ràng giữa dữ liệu đã xác thực trong Python và thông tin diễn giải do LLM trả về.

## 7. Hiểu biết về luồng end-to-end

Tôi hiểu rằng pipeline của repo này chạy như sau:

- `run.py` là coordinator nhận input case và gọi `DataStore` để lấy facts chuẩn.
- `order_seller_agent`, `payment_agent`, `delivery_agent` lần lượt điều tra từng domain và tạo handoff facts.
- `policy_agent` dùng các tính toán deterministic và upstream handoff để chọn rule EC_POLICY_V1 phù hợp.
- `build_output` tạo JSON output theo schema, `verify` kiểm tra evidence ID và giá trị tiền.
- `logging/trace.jsonl` ghi lại luồng handoff của 50 case, chỉ giữ run mới nhất.

## 8. Cam kết của thành viên

- [X] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [X] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [X] Tôi không ghi “đã chạy thành công” cho phần chưa được kiểm chứng.
- [X] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [X] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Trần Thị Thanh Tâm
**Ngày xác nhận:** 2026-08-05
