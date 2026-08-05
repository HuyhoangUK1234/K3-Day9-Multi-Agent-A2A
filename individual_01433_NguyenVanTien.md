# Member Role Report — Day 9: Multi Agent A2A

## 1. Thông tin cá nhân

| Thông tin       | Nội dung             |
| --------------- | -------------------- |
| Họ và tên       | Nguyễn Văn Tiến      |
| MSSV            | 01433                |
| Khóa/Lớp        | K3                   |
| Vai trò chính   | Policy Agent         |
| Ngày hoàn thành | 2026-08-05           |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable                  | File/hàm phụ trách                                      | Input nhận vào                                                     | Output bàn giao                                                | Trạng thái |
| ----------------------------------- | ------------------------------------------------------- | ------------------------------------------------------------------ | -------------------------------------------------------------- | ---------- |
| Policy Agent                        | `src/agents.py::policy_agent`                           | `OrderFacts` + 3 `Handoff` từ Order & Seller, Payment, Delivery     | `(Handoff, PolicyDecision, confidence)` cho Verifier            | Hoàn thành |
| Rule engine EC_POLICY_V1            | `src/policy.py::decide`                                 | `OrderFacts`                                                        | `PolicyDecision`: primary_issue, cause_code, party, refund, action | Hoàn thành |
| Hiệu chỉnh confidence               | `src/agents.py::_blocking_gaps`                          | `OrderFacts` + `PolicyDecision`                                     | Danh sách lỗ hổng dữ liệu thực sự cản trở nhánh luật vừa nổ    | Hoàn thành |
| Prompt và contract của Policy Agent | `src/agents.py::POLICY_SYSTEM`                          | —                                                                   | Bảng 6 luật xếp thứ tự ưu tiên + khuôn JSON bắt buộc            | Hoàn thành |
| Root cause phụ                      | `src/policy.py::true_causes`, `ranked_causes`           | `OrderFacts` + `PolicyDecision`                                     | Mọi cause_code đúng về mặt sự kiện, dùng cho chế độ `--causes ranked` | Hoàn thành |

Phần việc của tôi nằm ở khâu áp luật, tức là mắt xích giữa ba agent domain và Verifier. Ba agent phía trước bàn giao fact đã kiểm chứng; tôi quyết định luật nào nổ, ai chịu trách nhiệm, hoàn bao nhiêu tiền và mức tự tin là bao nhiêu. Verifier và `build_output` phụ thuộc trực tiếp vào `PolicyDecision` tôi trả về: `decision.cause_code` đi thẳng vào `evidence_ids` dưới dạng `policy:<cause_code>`, `decision.late_seller_ids` quyết định seller nào được trích dẫn làm bằng chứng, `decision.refund_brl` quyết định `case_status`.

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động                                                | Thành viên/module được hỗ trợ | Kết quả                                                                                                     |
| -------------------------------------------------------- | ----------------------------- | ----------------------------------------------------------------------------------------------------------- |
| Rà soát thứ tự ưu tiên trong prompt của các agent domain | `src/agents.py`               | Thống nhất một cách diễn đạt duy nhất về "muộn" giữa Delivery Agent và Policy Agent, tránh hai định nghĩa lệch nhau |
| Đọc trace để đối chiếu ý kiến LLM với rule engine        | `logging/trace.jsonl`          | Phát hiện model 8B không tạo ra nhánh `late_delivery_seller` lần nào trong 50 case                            |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện                                       | File/hàm/artifact liên quan                    | Kết quả bàn giao                                                                | Cách xác minh                                     |
| ------------------------------------------------------------ | ---------------------------------------------- | --------------------------------------------------------------------------------- | ------------------------------------------------- |
| Cài đặt 6 luật EC_POLICY_V1 theo đúng thứ tự ưu tiên      | `src/policy.py::decide`                        | 50/50 case ra đúng một `primary_issue`, phân bố 8/8/8/8/9/9 trên 6 nhánh          | `python run.py --no-llm` rồi đọc phần distribution |
| Tách quyền quyết định giữa rule engine và LLM               | `src/agents.py::policy_agent`                  | Kết luận luôn lấy từ `decide()`; ý kiến LLM ghi vào trace kèm cờ `agreement`      | `logging/trace.jsonl`, 50 dòng `agent="policy"`   |
| Hiệu chỉnh confidence theo độ đầy đủ bằng chứng             | `src/agents.py::_blocking_gaps`                 | 50/50 case đạt confidence 1.0, kể cả 8 đơn `unavailable` không có dòng hàng nào  | `output/EC_*.json`, trường `assessment.confidence` |
| Đảm bảo mọi kết luận qua được cổng kiểm                     | `src/policy.py` → `src/schema.py::verify`      | 50/50 case `passed: true`, không case nào bị hard gate                             | `logging/trace.jsonl`, 50 dòng `event="verify"`   |

Nêu một output cụ thể mà phần việc của tôi tạo ra hoặc giúp xác minh:

`logging/trace.jsonl` chứa 50 dòng handoff của Policy Agent, mỗi dòng ghi song song hai kết luận: `deterministic_issue` do `decide()` sinh ra và `llm_issue` do model đưa ra, kèm cờ `agreement`. Thống kê trên toàn bộ 50 case: model đồng ý 33 lần, lệch 17 lần. Trong 17 lần lệch, 8 lần là các case `late_delivery_seller` — model gọi tất cả thành `valid_split_payment`, và 9 lần là các case `valid_split_payment` — model gọi thành `unsupported_late_claim`. Tức là model 8B **không sinh ra nhánh `late_delivery_seller` một lần nào** trong 50 case, dù đây là nhánh chiếm 8 case. Toàn bộ 50 kết luận cuối vẫn đúng vì rule engine mới là bên có quyền quyết định.

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Ba agent phía trước chỉ trả lời được từng mảnh: đơn ở trạng thái gì, tiền có khớp không, giao có muộn không. Không mảnh nào tự nó là một phán quyết. Việc của Policy Agent là gộp các mảnh đó lại và trả lời bốn câu mà bài chấm hỏi: vấn đề chính là gì, ai chịu trách nhiệm, hoàn bao nhiêu, và mức tự tin bao nhiêu.

Khó ở hai chỗ. Thứ nhất, sáu luật của EC_POLICY_V1 **không loại trừ nhau** — một đơn có thể vừa bị hủy vừa giao muộn vừa có nhiều dòng thanh toán khớp, cả ba điều kiện cùng đúng. Ai xét sai thứ tự sẽ ra kết luận sai, hoàn sai tiền và đổ lỗi sai người. Thứ hai, ràng buộc của đề là model ≤10B, mà model cỡ đó không theo nổi một bảng luật xếp thứ tự.

### Cách triển khai

Tôi tách hẳn phần quyết định ra khỏi phần gọi model.

`decide()` trong `src/policy.py` là sáu nhánh `if` viết đúng theo thứ tự bảng luật, nhánh nào khớp trước thì `return` ngay. Cách viết này khiến thứ tự ưu tiên trở thành thuộc tính cấu trúc của hàm chứ không phải một quy ước phải nhớ: muốn phá thứ tự thì phải sửa vị trí khối lệnh, không thể vô tình phá bằng cách thêm một điều kiện.

Một chi tiết nhỏ nhưng cố ý: nhánh `canceled_order_paid` và `unavailable_order_paid` trả về `late_seller_ids=[]`. Đơn có thể đồng thời có seller bàn giao muộn, nhưng khi luật đơn hủy đã nổ thì thông tin seller muộn không còn liên quan, và xóa nó ngay tại nguồn giúp khâu ráp output phía sau không vô tình lôi seller vào danh sách chịu trách nhiệm.

`policy_agent()` trong `src/agents.py` chạy theo bốn bước:

1. Gọi `decide(facts)` lấy kết luận thật **trước khi** hỏi model. Thứ tự này quan trọng: model không bao giờ có cơ hội neo kết luận của hệ thống theo câu trả lời của nó.
2. Đóng gói fact đã tính sẵn — `payment_total`, `payment_reconciles`, `delivered_after_estimate`, `carrier_pickup_after_shipping_limit` — cộng với phần `upstream_findings` tóm tắt ý kiến và danh sách `missing` của ba agent trước, rồi gửi cho model kèm `POLICY_SYSTEM` là bảng 6 luật.
3. So `llm_issue` với `truth.primary_issue`, đặt cờ `agrees`, và nếu lệch thì ghi một dòng vào `missing` của gói handoff.
4. Tính confidence, đóng gói `Handoff` với `evidence_ids=[f"policy:{cause_code}"]` và trả về cả ba thứ cho Verifier.

Điểm cần nói rõ: **model không được đưa hai chuỗi thời gian để tự so.** Nó chỉ nhận hai giá trị boolean đã tính xong. Đây là lý do bốn case mà seller bàn giao muộn chỉ 3.5 đến 20.2 giờ, rơi vào cùng ngày lịch với hạn bàn giao, vẫn được kết luận đúng.

Phần confidence tôi thiết kế theo một nguyên tắc duy nhất: **confidence đo độ đầy đủ của bằng chứng, không đo mức đồng thuận của model.** Cụ thể trong `policy_agent`:

- Không tìm thấy order trong CSV thì trả 0.40, vì lúc đó không có gì để chứng minh cả.
- Còn lại thì gọi `_blocking_gaps()`; có lỗ hổng thì 0.80, không có thì 1.0.

`_blocking_gaps()` là hàm quan trọng nhất trong phần việc của tôi và nó **xét theo từng nhánh luật**, không xét chung. Một trường thiếu chỉ bị tính là lỗ hổng khi nó thực sự cản trở nhánh vừa nổ:

- Nhánh `canceled_order_paid` và `unavailable_order_paid` chỉ cần dòng thanh toán, vì tiền hoàn lấy theo `payment_total`. Thiếu dòng hàng **không** bị tính là lỗ hổng.
- Nhánh `late_delivery_*` cần đủ ba mốc thời gian và có dòng hàng, vì tiền hoàn lấy theo tổng phí ship.
- Nhánh `valid_split_payment` cần từ hai dòng thanh toán trở lên.
- Nhánh `unsupported_late_claim` cần đủ hai mốc giao hàng, vì thiếu chúng thì không chứng minh được khiếu nại là vô căn cứ.

Sự phân biệt này quyết định 8 case. Tám đơn `unavailable` trong bộ đề không có một dòng nào trong `order_items` — đó là hình dạng đúng của dữ liệu chứ không phải thiếu sót, nên chúng vẫn giữ confidence 1.0.

### Input, output và contract

| Thành phần              | Mô tả                                                                                                                                                       |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Input                   | `OrderFacts` (dataclass từ `src/data_store.py`) và `list[Handoff]` của ba agent domain; thêm tham số `confidence_mode` nhận `"max"` hoặc `"calibrated"`         |
| Output                  | Tuple `(Handoff, PolicyDecision, float)`. `PolicyDecision` gồm `primary_issue`, `cause_code`, `party_type`, `party_id`, `refund_brl`, `action`, `late_seller_ids` |
| Module phụ thuộc        | `src/data_store.py` cung cấp fact đã tính sẵn; `src/llm.py` cung cấp client và `parse_json_object`                                                              |
| Module sử dụng output   | `src/schema.py::build_output` ráp JSON cuối; `src/schema.py::verify` kiểm chéo; `run.py` ghi trace                                                              |
| Điều kiện lỗi cần xử lý | Order không có trong CSV; đơn không có dòng hàng; đơn không có dòng thanh toán; model trả về JSON hỏng hoặc rỗng; mạng chết hoàn toàn                          |

Về điều kiện lỗi cuối: `client.chat()` không bao giờ ném exception, mạng chết thì nó trả về một chuỗi JSON báo lỗi. `parse_json_object()` gặp chuỗi không parse được thì trả `{}`, và `parsed.get("primary_issue")` khi đó là `None`, tức là `agrees = False`. Kết quả: mạng chết thì Policy Agent vẫn ra đúng kết luận, chỉ mất phần ý kiến của model trong trace. Đây là hành vi cố ý, không phải may mắn.

### Cách xác minh

```bash
python run.py --no-llm
python run.py
python -c "import json;rows=[json.loads(l) for l in open('logging/trace.jsonl',encoding='utf-8')];pol=[r for r in rows if r.get('agent')=='policy'];print(sum(r['facts']['agreement'] for r in pol),'/',len(pol))"
```

- **Kết quả mong đợi:** Hai lệnh đầu ra cùng một bộ 50 output, phân bố 8/8/8/8/9/9 trên sáu nhánh, không case nào `VERIFY-FAIL`. Lệnh thứ ba cho thấy số lần model đồng ý với rule engine, và con số đó **không** ảnh hưởng tới output.
- **Kết quả thực tế:** 50/50 case qua Verifier. Phân bố: `unsupported_late_claim` 9, `valid_split_payment` 9, `late_delivery_seller` 8, `canceled_order_paid` 8, `unavailable_order_paid` 8, `late_delivery_logistics` 8. Model đồng ý 33/50. Chạy có LLM và chạy `--no-llm` cho ra output giống hệt nhau.
- **Artifact/log:** `output/EC_001.json` … `output/EC_050.json`, `logging/trace.jsonl` (300 dòng: 50 dispatch, 200 handoff, 50 verify), `logging/metadata.json`. Không file nào chứa key hay token.

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Đề bài bắt mỗi agent dùng model ≤10B và yêu cầu multi-agent thật, có handoff và kiểm chứng. Câu hỏi là ai được quyền chốt `primary_issue` — model hay code.
- **Các phương án đã cân nhắc:**
  1. Để LLM quyết, code chỉ kiểm khuôn dạng. Đúng tinh thần "agent tự chủ" nhất.
  2. Để LLM quyết, nhưng nếu lệch rule engine thì chạy lại prompt tối đa hai vòng, vẫn lệch thì lấy rule engine.
  3. Rule engine quyết luôn, LLM chạy song song như một lớp kiểm chứng độc lập, ý kiến lệch được ghi vào trace.
- **Phương án đã chọn:** Phương án 3.
- **Lý do:** Bảng luật EC_POLICY_V1 là một hàm thuần xác định — cùng một `OrderFacts` luôn phải ra cùng một kết luận. Đưa một model xác suất vào giữa một hàm xác định chỉ thêm phương sai chứ không thêm thông tin. Phương án 1 đánh cược toàn bộ điểm số vào khả năng đọc bảng luật của model 8B. Phương án 2 tốn gấp ba số lời gọi mà kết cục vẫn là lấy rule engine, chỉ khác là chậm hơn và đắt hơn. Phương án 3 giữ được yêu cầu multi-agent — vẫn có handoff thật, vẫn có agent phát biểu ý kiến độc lập và ý kiến đó được lưu lại kiểm chứng được — mà không để rủi ro của model chạm vào kết quả.
- **Bằng chứng quyết định phù hợp:** Trên 50 case, model `llama-3.1-8b-instant` chỉ đồng ý 33 lần. Đáng chú ý hơn con số tổng: nó gọi **cả 8** case `late_delivery_seller` thành `valid_split_payment`, trong đó có những đơn chỉ có đúng một dòng thanh toán — tức là nó chọn một luật mà điều kiện tiên quyết hiển nhiên không thỏa. Nó cũng gọi cả 9 case `valid_split_payment` thành `unsupported_late_claim`. Nếu chọn phương án 1, 17 trong 50 case sẽ sai `primary_issue`, kéo theo sai luôn root cause, responsible party và số tiền hoàn.

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng/lỗi nguyên văn:** Không phải lỗi crash mà là lỗi im lặng về điểm số. Bản đầu của tôi tính confidence theo công thức "LLM đồng ý thì cao, lệch thì hạ", đồng thời `_blocking_gaps` coi mọi trường rỗng là lỗ hổng. Hệ quả: 17 case bị hạ confidence vì model đoán sai, và thêm 8 đơn `unavailable` bị hạ vì "không có dòng hàng".
- **Lệnh hoặc bước tái hiện:**
  ```bash
  python run.py
  python -c "import json,glob;print(sorted({json.load(open(f,encoding='utf-8'))['assessment']['confidence'] for f in glob.glob('output/*.json')}))"
  ```
  Bản lỗi in ra nhiều mức confidence khác nhau thay vì một mức duy nhất.
- **Nguyên nhân gốc:** Tôi đã trộn hai đại lượng khác hẳn nhau vào cùng một con số. `confidence` trong schema là mức tin cậy vào **kết luận**, mà kết luận thì luôn được rule engine sinh ra từ CSV. Việc một model 8B có đọc nổi bảng luật hay không là thuộc tính của model, không phải thuộc tính của bằng chứng. Tương tự, đơn `unavailable` không có dòng hàng là hình dạng đúng của dữ liệu Olist, không phải dữ liệu bị khuyết — README mục 6 nói thẳng rằng trường hợp đó `item_ids` và `seller_ids` để rỗng, tức là đề bài coi đây là chuyện bình thường.
- **Cách xử lý:** Hai thay đổi. Một, bỏ hoàn toàn ảnh hưởng của `agrees` lên confidence; bất đồng chỉ được ghi vào `Handoff.missing` và vào trace. Hai, viết lại `_blocking_gaps()` thành hàm xét theo từng nhánh luật, mỗi nhánh chỉ khai báo đúng những trường mà nó dùng để ra quyết định.
- **Cách xác minh sau khi sửa:** Chạy lại hai lệnh trên, tập confidence thu hẹp về đúng một giá trị `[1.0]` cho cả 50 case, trong khi `logging/trace.jsonl` vẫn ghi đủ 17 lần bất đồng — nghĩa là thông tin không bị mất, chỉ bị tách khỏi chỗ nó không thuộc về.
- **Điều học được:** Một trường trong schema phải có đúng một định nghĩa, và định nghĩa đó phải trả lời được câu hỏi "đại lượng này đo cái gì". Khi tôi nhét thêm "mức đồng thuận của model" vào `confidence`, tôi đã tự trừ điểm cho những case mà hệ thống của mình làm đúng. Bài học rộng hơn: một thành phần yếu trong pipeline chỉ được phép làm giảm thông tin ghi lại được, không được phép làm giảm chất lượng đầu ra.

## 7. Hiểu biết về luồng end-to-end

> Bộ câu hỏi mẫu trong template gốc thuộc về một lab khác (Crossref, vector index, freshness monitoring). Tôi trả lời các câu tương ứng của Day 9.

1. Dữ liệu đi từ 9 file CSV của Olist đến một phán quyết JSON như thế nào?
2. Bộ 50 case và các mốc thời gian trong CSV dùng để xác định trách nhiệm ra sao?
3. Verifier khác Policy Agent ở điểm nào trong bài lab?
4. Vì sao lời khiếu nại của khách không được dùng làm căn cứ kết luận?
5. Một lượt chạy được xem là thành công dựa trên artifact và metric nào?

**Câu trả lời:**

**1.** `DataStore.load()` đọc bốn bảng cần dùng — `orders`, `order_items`, `order_payments`, `sellers` — bằng thư viện chuẩn và dựng index theo `order_id`. Với mỗi case, Coordinator lấy `claimed_order_id` từ file input rồi gọi `get_order_facts()`, nhận về một `OrderFacts` đã tính sẵn mọi đại lượng dẫn xuất: tổng tiền hàng, tổng phí ship, tổng thanh toán, danh sách seller, cờ giao muộn, danh sách seller bàn giao muộn. Ba agent domain nhận `OrderFacts` đó, mỗi agent nhìn phần của mình và trả về một gói `Handoff`. Policy Agent gộp lại và ra `PolicyDecision`. `build_output()` ráp thành JSON theo schema, `verify()` soi lại, rồi `run.py` ghi ra `output/EC_xxx.json`. Năm bảng còn lại của Olist không được nạp vì sáu nhánh nghiệp vụ không dùng tới chúng.

**2.** Trách nhiệm được xác định bằng hai phép so mốc thời gian, và hai phép này trả lời hai câu khác nhau. So `order_delivered_customer_date` với `order_estimated_delivery_date` cho biết đơn **có** muộn hay không. So `order_delivered_carrier_date` với `shipping_limit_date` của từng dòng hàng cho biết muộn **vì ai**: seller bàn giao sau hạn thì lỗi seller, bàn giao đúng hạn mà vẫn muộn thì lỗi bên vận chuyển. Cả hai phép so đều chạy trên đối tượng `datetime` đã parse tới từng giây, vì trong bộ 50 case có bốn đơn mà seller chỉ muộn từ 3.5 đến 20.2 giờ và rơi vào cùng ngày lịch với hạn bàn giao.

**3.** Policy Agent trả lời "kết luận là gì", Verifier trả lời "kết luận này có được phép ghi ra file không". Hai việc không được gộp làm một, vì bên ra quyết định không nên là bên tự chấm mình. Cụ thể Verifier kiểm những thứ Policy Agent không kiểm: mọi ID phải dựng được từ CSV, `affected_entities` không được mang tiền tố còn `evidence_ids` thì bắt buộc phải có, số lượng phần tử không vượt giới hạn, tiền làm tròn đúng hai chữ số, và `case_status` phải khớp với số tiền hoàn. Verifier cũng là code thuần chứ không gọi LLM, để một model yếu không thể mở cổng cho một file hỏng đi qua.

**4.** Vì lời khiếu nại là manh mối, không phải bằng chứng. Trong bộ 50 case, 25 case dùng chung một câu than "đơn hàng được giao trễ", nhưng đối chiếu CSV thì chỉ 16 đơn thực sự giao sau ngày hẹn — 9 case còn lại phải bị bác bỏ với số tiền hoàn bằng 0. Nếu hệ thống tin lời khách, nó sẽ hoàn tiền cho 9 case không đáng được hoàn và sai luôn cả `primary_issue` lẫn `resolution_actions`. Trong pipeline, `customer_request.message` chỉ được dùng đúng một lần ở Coordinator để lấy `claimed_order_id`, và không agent nào phía sau nhìn thấy nó.

**5.** Ba artifact và ba điều kiện. `output/` phải có đúng 50 file `EC_001.json` đến `EC_050.json`, tất cả qua `verify()` với `problems` rỗng — trace ghi 50 dòng `event="verify"` với `passed: true`. `logging/trace.jsonl` phải là của lượt chạy mới nhất, mở bằng mode `"w"` chứ không append, và chứa đủ 300 dòng cho 50 case gồm 50 dispatch, 200 handoff và 50 verify. `logging/metadata.json` phải khai đúng model, số tham số, provider, framework và runtime. Ngoài ra, một lượt chạy có LLM và một lượt `--no-llm` phải cho ra output giống hệt nhau; nếu khác nhau thì nghĩa là model đã lọt vào đường quyết định ở đâu đó.

## 8. Cam kết của thành viên

Đánh dấu sau khi tự kiểm tra:

- [x] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [x] Tôi không ghi "đã chạy thành công" cho phần chưa được kiểm chứng.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Nguyễn Văn Tiến
**Ngày xác nhận:** 2026-08-05
