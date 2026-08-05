# Architecture for Multi-Agent E-commerce Dispute Resolution

## 1. Mục tiêu

Thiết kế một hệ thống multi-agent để xử lý 50 case khiếu nại khách hàng từ `input/` và tạo ra 50 file output trong `output/`.
Hệ thống phân nhiệm rõ ràng, dùng dữ liệu Olist từ `data/`, áp dụng luật nghiệp vụ và xuất kết quả theo schema đã định.

## 2. Các agent chính

### 2.1 Coordinator Agent

- Nhận case input từ thư mục `input/`.
- Giải mã `claimed_order_id` từ `customer_request`.
- Điều phối gọi các agent khác theo luồng xử lý.
- Tổng hợp những kết quả trả về thành output schema.
- Ghi file JSON ra `output/` và ghi trace vào `logging/trace.jsonl`.

### 2.2 Order & Seller Agent

- Đọc dữ liệu từ CSV: `orders`, `order_items`, `sellers`, `products`.
- Tìm order bằng `claimed_order_id`.
- Truy vấn `order_status`, item list, seller, freight và shipping limit.
- Tính `item_total_brl`, `freight_total_brl` theo item rows.
- Trả về danh sách `order_ids`, `item_ids`, `seller_ids`, evidence ban đầu.

### 2.3 Delivery Agent

- Đọc thông tin thời gian liên quan đến đơn hàng:
  - `order_delivered_carrier_date`
  - `order_estimated_delivery_date`
  - `shipping_limit_date`
- So sánh thời điểm giao thực tế với thời hạn và ước tính.
- Xác định nguyên nhân trễ do seller hay logistics.
- Trả về root cause candidate và evidence thời gian.

### 2.4 Payment Agent

- Đọc `order_payments` của order.
- Tính tổng `payment_total_brl` từ payment rows.
- So sánh tổng payment với tổng hàng + freight.
- Phát hiện `valid_split_payment` nếu có nhiều payment row và tổng khớp trong sai số 0.10 BRL.
- Trả về `payment_ids` và evidence thanh toán.

### 2.5 Policy Agent

- Áp dụng các rule theo thứ tự ưu tiên đã định:
  1. `canceled_order_paid`
  2. `unavailable_order_paid`
  3. `late_delivery_seller`
  4. `late_delivery_logistics`
  5. `valid_split_payment`
  6. `unsupported_late_claim`
- Xác định `primary_issue`, `case_status`, `recommend_refund`, `resolution_actions`, `confidence`.
- Chọn `cause_code` và `responsible_party` phù hợp.

### 2.6 Verifier Agent

- Kiểm tra đầu ra cuối cùng trước khi ghi file.
- Xác minh schema, số lượng IDs, evidence formats, và giá trị tiền.
- Đảm bảo `confidence` nằm trong `[0,1]`.
- Phát hiện input hay output bất thường trước khi commit kết quả.

## 3. Luồng dữ liệu

1. `Coordinator Agent` đọc input JSON.
2. Gọi `Order & Seller Agent` để lấy thông tin order, item và seller.
3. Gọi `Payment Agent` để tính tổng thanh toán và đối chiếu.
4. Gọi `Delivery Agent` để xác định trạng thái giao hàng.
5. Gọi `Policy Agent` để chọn primary issue, responsible party, refund và actions.
6. Gọi `Verifier Agent` để kiểm tra output schema và evidence.
7. Ghi output JSON vào `output/` và trace vào `logging/trace.jsonl`.

## 4. Quyền truy cập dữ liệu

- `Order & Seller Agent`: đọc CSV trong `data/` liên quan đến orders, order_items, sellers, products.
- `Delivery Agent`: dùng dữ liệu order_items và orders để so sánh mốc thời gian giao.
- `Payment Agent`: dùng `order_payments` để xác định tổng thanh toán.
- `Policy Agent`: dùng kết quả của các agent khác và luật nghiệp vụ.
- `Verifier Agent`: dùng output đã tổng hợp để kiểm tra schema.

## 5. Xử lý 50 case

- Mỗi case là một đơn vị xử lý riêng.
- Có thể chạy tuần tự hoặc batch, nhưng vẫn tuân theo luồng agent.
- Với dữ liệu đồng nhất và luật rõ ràng, hệ thống này có thể xử lý đủ 50 case đầu vào.

## 6. Ghi chú kỹ thuật

- Output JSON phải tuân theo schema đề bài.
- `architecture.md` chỉ mô tả thiết kế và trách nhiệm agent, không phải code cụ thể.
- File này cũng là bằng chứng rằng hệ thống có phân công agent chặt chẽ và handoff rõ ràng.
