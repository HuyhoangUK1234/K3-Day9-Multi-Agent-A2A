# Member Role Report — Day 9: Multi Agent A2A

## 1. Thông tin cá nhân

| Thông tin       | Nội dung                           |
| --------------- | ---------------------------------- |
| Họ và tên       | Nguyễn Duy Hải Bằng                |
| MSSV            | 2A202601225                        |
| Khóa/Lớp        | K3                                 |
| Vai trò chính   | Coordinator Agent & Verifier Agent |
| Ngày hoàn thành | 2026-08-05                         |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable | File/hàm phụ trách                | Input nhận vào                                | Output bàn giao                                                                       | Trạng thái |
| ------------------ | --------------------------------- | --------------------------------------------- | ------------------------------------------------------------------------------------- | ---------- |
| Coordinator Agent  | `run.py::run_case`, `run.py::main` | 50 file `input/EC_*.json`                     | 50 file `output/EC_*.json`, `logging/trace.jsonl` (300 dòng), `logging/metadata.json` | Hoàn thành |
| Verifier Agent     | `src/schema.py::verify`           | dict JSON đã lắp + `DataStore`                | Danh sách lỗi; rỗng = an toàn ghi file                                                | Hoàn thành |
| Đóng gói bài nộp   | `make_zip.py`                     | thư mục `output/`                             | `output.zip` đã tự kiểm                                                               | Hoàn thành |
| Cấu hình runtime   | `src/config.py`                   | biến môi trường từ `.env`                     | Provider đang dùng, hằng số giới hạn schema                                           | Hoàn thành |

Coordinator nhận sự thật đã tính sẵn từ module `data_store` (không phải phần tôi viết) và quyết định từ module `policy` (cũng không phải phần tôi viết). Tôi sở hữu phần điều phối giữa chúng, và phần kiểm chứng đầu ra trước khi ghi file. Người phụ trách `policy.py` và `data_store.py` phụ thuộc vào trace tôi ghi để debug; người phụ trách `agents.py` phụ thuộc vào thứ tự gọi và định dạng gói handoff mà Coordinator quy định.

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động                        | Thành viên/module được hỗ trợ | Kết quả                                                                                                                                                                                             |
| -------------------------------- | ----------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Debug lỗi mạng chặn toàn bộ LLM  | `src/llm.py`                  | Xác định Groq trả `HTTP 403 error code 1010` do Cloudflare chặn User-Agent mặc định `Python-urllib/3.13`. Trước khi sửa: 12/12 call thất bại. Sau khi thêm header `User-Agent` rõ ràng: 0 thất bại |
| Đo cấu trúc chấm điểm            | toàn nhóm                     | Thiết kế 6 lượt nộp, mỗi lượt đổi đúng một biến, để tách được nguyên nhân từng thay đổi. Kết quả nâng điểm từ 93.7705 lên 100.0000                                                                 |
| Viết `architecture.md`           | toàn nhóm                     | Sơ đồ 6 agent, bảng quyền truy cập dữ liệu, định dạng handoff, ranh giới Python-vs-LLM                                                                                                             |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện          | File/hàm/artifact liên quan                 | Kết quả bàn giao                              | Cách xác minh                                          |
| ------------------------------ | ------------------------------------------- | --------------------------------------------- | ------------------------------------------------------ |
| Điều phối 50 case qua 6 agent  | `run.py::run_case`                          | 50 JSON đúng schema, 300 dòng trace           | `python run.py` → `cases=50 verify_failures=0`         |
| Chặn output sai trước khi ghi  | `src/schema.py::verify`                     | 7 tầng kiểm, trả danh sách lỗi                | Chạy 50 case ở 5 cấu hình khác nhau, đều `verify_failures=0` |
| Ghi trace không append         | `run.py` dòng 140, `TRACE_PATH.open("w")`   | `trace.jsonl` luôn chỉ chứa lượt mới nhất     | Chạy 2 lần liên tiếp, đếm dòng vẫn đúng 300            |
| Đóng gói bài nộp có tự kiểm    | `make_zip.py`                               | `output.zip` 28.5 KB, 50 entry                | `python make_zip.py` → exit 0, in `all parse : True`   |
| Ghi metadata tự động           | `run.py::main`                              | `logging/metadata.json`                       | Đọc file, kiểm đủ cohort, policy version, model, parameter size, runtime |

Một output cụ thể mà phần việc của tôi tạo ra hoặc giúp xác minh:

`logging/trace.jsonl` — 300 dòng, đúng 6 dòng mỗi case theo trình tự `coordinator dispatch` → 3 gói `handoff` từ agent domain → 1 gói `handoff` từ policy → `verifier verify`. Đây là artifact chứng minh handoff giữa các agent có thật, không phải chỉ đặt tên nhiều agent rồi xử lý trong một prompt (điều README mục 7 nói rõ là không có điểm). Ví dụ 6 dòng của case `EC_001` cho thấy Order & Seller Agent báo `sellers_past_limit: ["f7496d65..."]`, Delivery Agent báo `delivered_after_estimate: true`, và Policy Agent nhận cả hai rồi kết luận `late_delivery_seller`.

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Hai vấn đề tách biệt.

**Coordinator:** hệ thống có 6 agent, mỗi agent chỉ được thấy một phần dữ liệu. Cần một chỗ nhận case, tra dữ liệu một lần, phân phát cho đúng agent, thu kết quả, và ghi lại toàn bộ quá trình để kiểm chứng được. Nếu để mỗi agent tự tra CSV thì không còn nguồn sự thật duy nhất và các agent có thể kết luận lệch nhau.

**Verifier:** đầu ra là 50 file JSON được chấm tự động, có hard gate cho 0 điểm. Model dùng cho các agent chỉ 8B tham số, rất dễ sinh ID nghe hợp lý nhưng không tồn tại trong dữ liệu. Cần một cửa chặn cuối kiểm tra đầu ra trước khi ghi ra đĩa.

### Cách triển khai

**Coordinator** (`run.py::run_case`) thực hiện 4 bước theo thứ tự cố định:

1. Đọc case JSON, lấy `claimed_order_id` từ lời khai khách.
2. Gọi `store.get_order_facts(claimed_order_id)` để dựng lại toàn bộ sự thật từ CSV. Đây là điểm thiết kế then chốt: lời khai của khách chỉ được dùng làm manh mối tra cứu, không có nội dung nào khác từ khách được truyền tới chỗ có quyền quyết định. Nhờ vậy 9 case khách kêu giao trễ nhưng dữ liệu cho thấy giao đúng hạn được xử đúng thành `unsupported_late_claim`.
3. Gọi tuần tự 3 agent domain, thu 3 gói handoff, chuyển cho Policy Agent. Policy Agent không được truy cập `DataStore`, chỉ làm việc trên handoff nhận được.
4. Gọi `build_output`, đưa qua `verify`, ghi file và 6 dòng trace.

Vòng lặp chính nạp CSV **một lần** trước khi lặp (khoảng 3 giây cho 320 nghìn dòng), không nạp lại mỗi case.

**Verifier** (`src/schema.py::verify`) kiểm 7 tầng, thu thập toàn bộ lỗi thay vì dừng ở lỗi đầu tiên:

1. Enum — `primary_issue`, `case_status`, `cause_code`, `action` phải thuộc tập hợp lệ; `confidence` trong `[0, 1]`.
2. Giới hạn số lượng — tối đa 5 ID mỗi entity set, 10 evidence, 3 root cause, 3 responsible party, 5 action. Vượt là hard gate.
3. ID có thật — tra ngược từng `order_id`, `seller_id`, `item_id`, `payment_id` vào CSV đã nạp.
4. Quy ước tiền tố — `affected_entities` dùng ID **không** tiền tố (`abc123:1`), `evidence_ids` dùng ID **có** tiền tố (`item:abc123:1`). Bắt trường hợp lẫn lộn giữa hai chỗ.
5. Định dạng evidence — regex cho từng dạng, cộng nhánh `else` chặn mọi tiền tố lạ. Đây là chỗ chặn ID bịa như `refund:xxx` hay `tracking:yyy` (Olist không có hai loại dữ liệu này).
6. Tiền — đúng đơn vị BRL, kiểu số, đã làm tròn 2 chữ số (kiểm bằng `round(v, 2) == v`).
7. Nhất quán chéo — `case_status` phải khớp với `recommended_refund_brl`. Refund lớn hơn 0 thì phải là `action_required`, ngược lại là `no_action`. Hai trường này sinh ở hai chỗ khác nhau trong code nên kiểm từng trường riêng lẻ không phát hiện được mâu thuẫn.

### Input, output và contract

| Thành phần              | Mô tả                                                                                                                                                                                                                                                                                                                                 |
| ----------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Input                   | Coordinator: `input/EC_*.json` gồm `case_id`, `customer_request.claimed_order_id`, `policy_version`. Verifier: dict payload đã lắp + instance `DataStore` đã nạp CSV                                                                                                                                                                 |
| Output                  | Coordinator: 50 file `output/EC_*.json`, `trace.jsonl`, `metadata.json`, mã thoát 0 hoặc 1. Verifier: `list[str]` các lỗi; rỗng nghĩa là an toàn                                                                                                                                                                                     |
| Module phụ thuộc        | `src/data_store.py` (nguồn sự thật), `src/policy.py` (quyết định), `src/agents.py` (4 agent LLM), `src/llm.py` (client), `src/config.py` (hằng số giới hạn)                                                                                                                                                                          |
| Module sử dụng output   | `make_zip.py` đọc `output/`; toàn nhóm đọc `trace.jsonl` để debug                                                                                                                                                                                                                                                                    |
| Điều kiện lỗi cần xử lý | Input thiếu trường (dùng `.get()` lồng nhau thay vì truy cập trực tiếp, tránh `KeyError` làm chết cả batch); `claimed_order_id` không có trong CSV (`facts.exists = False`, trace ghi `order_found: false`, entity set để rỗng); LLM không gọi được (engine deterministic vẫn ra kết quả đúng, chỉ mất phần diễn giải trong trace) |

### Cách xác minh

```bash
# Chạy đầy đủ 50 case
python run.py

# Chứng minh LLM không tham gia vào quyết định:
# chạy lại không gọi LLM, output phải giống hệt
python run.py --no-llm --out output_nollm

# Đóng gói và tự kiểm archive
python make_zip.py

# Kiểm trace không append: chạy 2 lần, đếm dòng
python run.py && wc -l logging/trace.jsonl
python run.py && wc -l logging/trace.jsonl
```

- **Kết quả mong đợi:** 50 case, 0 verify failure, trace đúng 300 dòng ở cả hai lần chạy, zip đúng 50 entry và mọi entry parse được JSON.
- **Kết quả thực tế:** `cases=50 verify_failures=0 llm_calls=0 cache_hits=200 llm_failures=0 elapsed=1.4s`. `make_zip.py` in `entries : 50`, `first/last: output/EC_001.json / output/EC_050.json`, `all parse : True`, exit 0. Trace 300 dòng ở cả hai lần chạy. Output của `--no-llm` giống hệt output thường, xác nhận LLM không tham gia quyết định.
- **Artifact/log:** `logging/trace.jsonl`, `logging/metadata.json`, `output/EC_001.json` đến `EC_050.json`. Không chứa secret; API key nằm trong `.env` và đã được `.gitignore` chặn.

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Verifier phát hiện lỗi trong output thì nên làm gì? Có nên tự động sửa cho hợp lệ, hay chỉ báo cáo?

- **Các phương án đã cân nhắc:**
  1. Verifier tự sửa: cắt bớt ID khi vượt giới hạn, loại bỏ ID không tồn tại, ép `case_status` cho khớp refund. Ưu điểm là không bao giờ ghi ra file sai schema.
  2. Verifier chỉ báo cáo, trả danh sách lỗi, vẫn ghi file ra để xem được nó sai gì, đồng thời đếm vào `failures` và cho `run.py` thoát mã 1.

- **Phương án đã chọn:** phương án 2.

- **Lý do:** phương án 1 che mất lỗi hệ thống. Nếu Policy Engine sinh ra `case_status` mâu thuẫn với refund mà Verifier lặng lẽ sửa, ta sẽ có file hợp lệ nhưng bug trong `policy.py` vẫn còn và sẽ tái diễn ở dữ liệu khác. Codelab mục 5 nói rõ nguyên tắc này: khi một ticket lỗi thì sửa nguyên nhân ở agent hoặc router rồi chạy lại, không sửa tay kết luận. Verifier tự sửa chính là "sửa tay kết luận" được tự động hóa. Đánh đổi là ta có thể ghi ra file sai, nhưng mã thoát khác 0 và dòng `VERIFY-FAIL` in ra màn hình đảm bảo không ai nộp nhầm mà không biết.

- **Bằng chứng quyết định phù hợp:** trong suốt quá trình phát triển, hệ thống chạy ở 5 cấu hình khác nhau (`wide`, `evidence`, `strict`, `minimal`, `ranked`) trên cả 50 case. Mỗi lần đổi cấu hình, Verifier xác nhận `verify_failures=0` trước khi nộp. Nhờ có lưới an toàn này mà nhóm dám thay đổi cách trình bày output liên tục để dò cấu trúc chấm điểm, mà không lo phá schema.

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng/lỗi nguyên văn:** file zip đóng gói xong, giải nén trên Windows nhìn bình thường, nhưng kiểm tra danh sách entry thì thấy:

  ```
  first: output\EC_001.json
  last : output\EC_050.json
  exact match EC_001..EC_050 with forward slashes: False
  ```

- **Lệnh hoặc bước tái hiện:**

  ```powershell
  [System.IO.Compression.ZipFile]::CreateFromDirectory($root, $zip, ..., $false)
  ```

- **Nguyên nhân gốc:** chuẩn ZIP (PKWARE APPNOTE 4.4.17.1) quy định tên entry phải dùng dấu gạch chéo xuôi `/`. Công cụ zip của Windows và `System.IO.Compression` trong .NET Framework ghi bằng dấu gạch ngược `\`. Trên Windows các trình giải nén tự bỏ qua, nhưng grader chạy trên Linux sẽ thấy **một file duy nhất mang tên literal `output\EC_001.json`** thay vì một thư mục `output/` chứa 50 file. Nộp bài kiểu này sẽ hỏng mà không có thông báo lỗi nào cho biết tại sao.

  Trước đó còn một lỗi liên quan: lần đóng gói đầu tiên, tên thư mục staging tạm bị lọt vào đường dẫn entry, thành `ec_submission\output\EC_001.json`.

- **Cách xử lý:** viết `make_zip.py` dùng `zipfile` của Python — thư viện này luôn ghi dấu `/` đúng chuẩn. Không nén cả thư mục mà duyệt đúng 50 tên file mong đợi và gán `arcname="output/{name}"` tường minh. Cách này cũng loại luôn `output/.gitkeep` (file được git theo dõi nhưng README mục 8 cấm có mặt trong zip).

- **Cách xác minh sau khi sửa:** script mở lại archive vừa tạo và kiểm 4 điều, sai bất kỳ điều nào thì `exit 1`:

  ```
  entries      : 50
  first / last : output/EC_001.json / output/EC_050.json
  exact set    : True
  backslashes  : 0
  non-json     : none
  corrupt      : none
  all parse    : True
  ```

- **Điều học được:** một artifact nộp bài cũng cần được kiểm chứng như code, không phải "nén xong là xong". Lỗi này thuộc loại nguy hiểm nhất vì nó hoàn toàn im lặng trên máy mình và chỉ bộc lộ trên môi trường của người chấm. Bài học chung: khi tạo file cho một hệ thống khác đọc, phải kiểm bằng cách đọc lại chính file đó, chứ không tin vào việc thao tác tạo file đã chạy không báo lỗi.

## 7. Hiểu biết về luồng end-to-end

> Ghi chú: Section 7 trong template gốc hỏi về Crossref, vector index, ground-truth document IDs và freshness monitoring. Những khái niệm này thuộc lab RAG, không có trong Day 9 Multi-Agent A2A. Tôi đã thay bằng câu hỏi tương ứng của bài lab này.

1. Dữ liệu đi từ file CSV đến một ruling JSON như thế nào?
2. Bằng chứng nào chứng minh handoff giữa các agent là có thật?
3. Vì sao logic nghiệp vụ do Python quyết định chứ không do LLM?
4. Verifier khác một trình kiểm schema thông thường ở điểm nào?
5. Dựa vào artifact và chỉ số nào để kết luận một lượt chạy là thành công?

**Câu trả lời:**

**1.** `DataStore` nạp 4 trong 9 file CSV vào bộ nhớ một lần khi khởi động (`orders`, `order_items`, `order_payments`, `sellers`; năm file còn lại không luật nào đọc tới). Coordinator đọc `input/EC_001.json`, lấy `claimed_order_id`, gọi `get_order_facts()` để dựng đối tượng `OrderFacts` chứa mọi sự thật đã tính sẵn: trạng thái đơn, bốn mốc thời gian, danh sách món, danh sách payment, và các giá trị dẫn xuất như `item_total`, `freight_total`, `payment_total`, `delivered_late`, `late_sellers()`. Ba agent domain mỗi agent nhìn một lát cắt của `OrderFacts` và trả về gói handoff. Policy Agent nhận ba gói handoff, còn `policy.py::decide()` áp 6 luật theo thứ tự ưu tiên trên `OrderFacts` để ra `PolicyDecision`. `build_output` lắp thành dict JSON, `verify` kiểm, Coordinator ghi ra `output/EC_001.json`.

**2.** File `logging/trace.jsonl`, 300 dòng cho 50 case, đúng 6 dòng mỗi case. Mỗi dòng handoff chứa 5 trường: agent nào, ticket nào, câu hỏi agent đó phải trả lời, các fact tìm được kèm ID nguồn, danh sách điều còn thiếu, và đề xuất cho agent tiếp theo. Bằng chứng mạnh nhất nằm ở chỗ Policy Agent **không được truyền `DataStore`** — nó chỉ nhận ba gói handoff. Nếu handoff chỉ là trang trí thì Policy Agent đã không có dữ liệu để làm việc. Đây là điều README mục 7 yêu cầu khi nói không có điểm cho việc đặt tên nhiều agent nhưng toàn bộ xử lý nằm trong một prompt duy nhất.

**3.** Đề giới hạn mỗi agent dùng model tối đa 10B tham số. Một model 8B không đáng tin khi so sánh ngày tháng hoặc cộng tiền, mà trong bài này một phép so sai là đổi luôn bên chịu trách nhiệm: phân biệt `late_delivery_seller` với `late_delivery_logistics` phụ thuộc hoàn toàn vào việc `order_delivered_carrier_date` có lớn hơn `shipping_limit_date` hay không. Nên Python sở hữu mọi phép join, so sánh thời gian, cộng tiền và làm tròn; LLM chỉ diễn giải các sự thật đó, nêu điều còn thiếu và bàn giao. Policy Agent LLM vẫn đưa ra ý kiến về issue, nhưng nếu lệch với engine deterministic thì engine thắng và bất đồng được ghi vào trace. Bằng chứng cho thiết kế này: qua 6 lượt nộp với 5 cấu hình khác nhau, `primary_issue`, `financial_resolution` và `resolution_actions` giống hệt nhau từng byte và không sai case nào. Có thể kiểm lại bằng `python run.py --no-llm` — tắt hoàn toàn LLM mà output không đổi.

**4.** Trình kiểm schema chỉ nhìn hình dạng: có đủ trường không, kiểu dữ liệu đúng không. Verifier ở đây làm thêm hai việc mà kiểm schema không làm được. Thứ nhất, nó **tra ngược từng ID vào CSV gốc** thông qua `DataStore`, nên một `seller_id` đúng định dạng 32 ký tự hex nhưng không tồn tại vẫn bị chặn. Thứ hai, nó kiểm **quan hệ chéo giữa các trường**: `case_status` phải nhất quán với `recommended_refund_brl`, mà hai trường này sinh ở hai chỗ khác nhau trong code nên kiểm từng trường riêng lẻ không bao giờ phát hiện được mâu thuẫn.

**5.** Ba artifact và một chỉ số. `output/` phải có đúng 50 file JSON tên khớp input. `logging/trace.jsonl` phải có 300 dòng thể hiện đủ 6 vai. `logging/metadata.json` phải ghi đúng model, số tham số, cohort và policy version. Chỉ số quyết định là `verify_failures=0` in ra cuối mỗi lượt chạy, cộng với mã thoát 0. Cuối cùng, `make_zip.py` phải chạy thành công và in `all parse : True` — nghĩa là archive nộp bài có đúng 50 entry, tên entry dùng dấu gạch chéo xuôi, không entry nào hỏng và mọi entry đều parse được JSON.

## 8. Cam kết của thành viên

Đánh dấu sau khi tự kiểm tra:

- [x] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [x] Tôi không ghi "đã chạy thành công" cho phần chưa được kiểm chứng.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Nguyễn Duy Hải Bằng
**Ngày xác nhận:** 2026-08-05
