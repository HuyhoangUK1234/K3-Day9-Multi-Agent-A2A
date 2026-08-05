"""Tool đọc dữ liệu, có ép scope theo từng agent.

Scope không nằm trong prompt mà nằm ở đây: agent xin bảng ngoài danh sách
DATA_SCOPE thì ScopedView ném ScopeViolation. Model 8B rất hay lờ lời dặn
trong prompt, chặn ở tầng tool thì nó không lờ được.

Mọi con số tiền do các hàm dưới đây tính bằng Decimal. LLM không tự cộng.
"""

from decimal import Decimal

from ..config import DATA_SCOPE
from ..data.loader import OlistData, parse_ts
from ..money import RECONCILE_TOLERANCE, ZERO, dec2


class ScopeViolation(RuntimeError):
    """Agent chạm vào bảng hoặc cột không thuộc quyền của nó."""


class ScopedView:
    """Cửa duy nhất để một agent chạm vào dữ liệu."""

    def __init__(self, data: OlistData, agent: str):
        self._data = data
        self._agent = agent
        self._scope = DATA_SCOPE.get(agent, {})

    def _check(self, table: str) -> set[str] | None:
        if table not in self._scope:
            raise ScopeViolation(f"{self._agent} không có quyền đọc bảng '{table}'")
        return self._scope[table]

    @staticmethod
    def _project(row: dict, columns: set[str] | None) -> dict:
        if columns is None:
            return dict(row)
        return {k: v for k, v in row.items() if k in columns}

    def order(self, order_id: str) -> dict | None:
        columns = self._check("orders")
        row = self._data.orders.get(order_id)
        return self._project(row, columns) if row else None

    def items(self, order_id: str) -> list[dict]:
        columns = self._check("order_items")
        return [self._project(r, columns) for r in self._data.items.get(order_id, [])]

    def payments(self, order_id: str) -> list[dict]:
        columns = self._check("order_payments")
        return [self._project(r, columns) for r in self._data.payments.get(order_id, [])]

    def seller_exists(self, seller_id: str) -> bool:
        self._check("sellers")
        return self._data.has_seller(seller_id)


# ---------------------------------------------------------------- Order & Seller


def order_seller_facts(view: ScopedView, order_id: str) -> dict:
    """Trạng thái đơn, các dòng hàng, seller và hạn bàn giao của từng dòng."""
    order = view.order(order_id)
    items = view.items(order_id)

    item_total = sum((r["price"] for r in items), ZERO)
    freight_total = sum((r["freight_value"] for r in items), ZERO)

    seller_ids: list[str] = []
    for row in items:
        if row["seller_id"] not in seller_ids:
            seller_ids.append(row["seller_id"])

    return {
        "order_id": order_id,
        "order_exists": order is not None,
        "order_status": order["order_status"] if order else None,
        "has_items": bool(items),
        "items": [
            {
                "order_item_id": r["order_item_id"],
                "seller_id": r["seller_id"],
                "shipping_limit_date": r["shipping_limit_date"],
                "price": r["price"],
                "freight_value": r["freight_value"],
            }
            for r in items
        ],
        "item_ids": [f"{order_id}:{r['order_item_id']}" for r in items],
        "seller_ids": seller_ids,
        "seller_ids_known": [s for s in seller_ids if view.seller_exists(s)],
        "item_total": dec2(item_total),
        "freight_total": dec2(freight_total),
    }


# ---------------------------------------------------------------------- Payment


def payment_facts(view: ScopedView, order_id: str) -> dict:
    """Đối soát tiền khách trả với tiền hàng cộng phí ship.

    payment_value là số tiền của TỪNG DÒNG thanh toán, không phải tiền mỗi kỳ
    trả góp — tuyệt đối không nhân với payment_installments.
    """
    payments = view.payments(order_id)
    items = view.items(order_id)

    payment_total = dec2(sum((r["payment_value"] for r in payments), ZERO))
    expected_total = dec2(
        sum((r["price"] for r in items), ZERO) + sum((r["freight_value"] for r in items), ZERO)
    )
    delta = dec2(payment_total - expected_total)

    return {
        "order_id": order_id,
        "payments": [
            {
                "payment_sequential": r["payment_sequential"],
                "payment_type": r["payment_type"],
                "payment_installments": r["payment_installments"],
                "payment_value": r["payment_value"],
            }
            for r in payments
        ],
        "payment_ids": [f"{order_id}:{r['payment_sequential']}" for r in payments],
        "payment_count": len(payments),
        "payment_total": payment_total,
        "expected_total": expected_total,
        "delta": delta,
        "is_split_payment": len(payments) >= 2,
        "reconciled": abs(delta) <= RECONCILE_TOLERANCE,
        "tolerance": RECONCILE_TOLERANCE,
    }


# --------------------------------------------------------------------- Delivery


def delivery_facts(view: ScopedView, order_id: str, handoff_items: list[dict] | None = None) -> dict:
    """So mốc giao thực tế với ngày hẹn, và mốc bàn giao với hạn của seller.

    handoff_items là dữ liệu Order & Seller Agent bàn giao sang (mỗi phần tử có
    seller_id và shipping_limit_date). Thiếu handoff thì đọc trong scope của
    chính mình để không kẹt case.
    """
    order = view.order(order_id)
    if order is None:
        return {
            "order_id": order_id,
            "order_exists": False,
            "order_status": None,
            "is_delivered": False,
            "is_late": False,
            "seller_handoff_late": False,
            "late_seller_ids": [],
            "cause_code": None,
        }

    items = handoff_items if handoff_items else view.items(order_id)

    delivered_customer = parse_ts(order.get("order_delivered_customer_date"))
    estimated = parse_ts(order.get("order_estimated_delivery_date"))
    delivered_carrier = parse_ts(order.get("order_delivered_carrier_date"))

    is_late = bool(delivered_customer and estimated and delivered_customer > estimated)

    late_seller_ids: list[str] = []
    if delivered_carrier:
        for row in items:
            limit = parse_ts(row.get("shipping_limit_date"))
            if limit and delivered_carrier > limit:
                seller_id = row.get("seller_id")
                if seller_id and seller_id not in late_seller_ids:
                    late_seller_ids.append(seller_id)

    seller_handoff_late = bool(late_seller_ids)

    if is_late and seller_handoff_late:
        cause_code = "SELLER_HANDOFF_AFTER_LIMIT"
    elif is_late:
        cause_code = "CARRIER_DELIVERED_AFTER_ESTIMATE"
    elif delivered_customer:
        cause_code = "DELIVERY_WITHIN_ESTIMATE"
    else:
        cause_code = None

    return {
        "order_id": order_id,
        "order_exists": True,
        "order_status": order.get("order_status"),
        "order_delivered_customer_date": order.get("order_delivered_customer_date"),
        "order_estimated_delivery_date": order.get("order_estimated_delivery_date"),
        "order_delivered_carrier_date": order.get("order_delivered_carrier_date"),
        "is_delivered": delivered_customer is not None,
        "is_late": is_late,
        "has_carrier_date": delivered_carrier is not None,
        "seller_handoff_late": seller_handoff_late,
        "late_seller_ids": late_seller_ids,
        "cause_code": cause_code,
    }


# --------------------------------------------------------------------- Verifier


def evidence_id_exists(data: OlistData, evidence_id: str, valid_cause_codes: set[str]) -> bool:
    """Một evidence ID chỉ hợp lệ khi dựng được từ CSV và đúng khuôn dạng."""
    parts = evidence_id.split(":")
    kind = parts[0]

    if kind == "order" and len(parts) == 2:
        return data.has_order(parts[1])
    if kind == "item" and len(parts) == 3:
        return data.has_item(parts[1], parts[2])
    if kind == "payment" and len(parts) == 3:
        return data.has_payment(parts[1], parts[2])
    if kind == "seller" and len(parts) == 2:
        return data.has_seller(parts[1])
    if kind == "policy" and len(parts) == 2:
        return parts[1] in valid_cause_codes
    return False


def jsonable(value):
    """Đổi Decimal thành float để đưa vào prompt, trace hoặc file JSON."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [jsonable(v) for v in value]
    return value
