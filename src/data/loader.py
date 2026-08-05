"""Đọc CSV Olist một lần vào bộ nhớ và dựng index tra cứu theo order_id.

Chỉ 4 bảng được nạp: orders, order_items, order_payments, sellers.
products / order_reviews / geolocation không tham gia 6 nhánh nghiệp vụ nên
không nạp — đọc thừa chỉ tốn RAM và tăng nguy cơ agent bịa bằng chứng.
"""

import csv
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..money import to_dec

TS_FORMAT = "%Y-%m-%d %H:%M:%S"


def parse_ts(value: str | None) -> datetime | None:
    """Đổi chuỗi timestamp trong CSV thành datetime. Ô rỗng trả về None.

    So sánh nguyên trạng theo giá trị trong CSV, không đổi múi giờ.
    """
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, TS_FORMAT)
    except ValueError:
        return None


@dataclass
class OlistData:
    orders: dict[str, dict] = field(default_factory=dict)
    items: dict[str, list[dict]] = field(default_factory=dict)
    payments: dict[str, list[dict]] = field(default_factory=dict)
    seller_ids: set[str] = field(default_factory=set)

    def has_order(self, order_id: str) -> bool:
        return order_id in self.orders

    def has_item(self, order_id: str, order_item_id: str) -> bool:
        return any(str(row["order_item_id"]) == str(order_item_id) for row in self.items.get(order_id, []))

    def has_payment(self, order_id: str, sequential: str) -> bool:
        return any(str(row["payment_sequential"]) == str(sequential) for row in self.payments.get(order_id, []))

    def has_seller(self, seller_id: str) -> bool:
        return seller_id in self.seller_ids


def _read_rows(path: Path):
    with open(path, "r", encoding="utf-8", newline="") as fh:
        yield from csv.DictReader(fh)


def load(data_dir: Path, needed_order_ids: set[str] | None = None) -> OlistData:
    """Nạp dữ liệu. Truyền needed_order_ids để chỉ giữ các order của 50 case."""
    data = OlistData()

    for row in _read_rows(data_dir / "olist_orders_dataset.csv"):
        order_id = row["order_id"]
        if needed_order_ids is not None and order_id not in needed_order_ids:
            continue
        data.orders[order_id] = row

    for row in _read_rows(data_dir / "olist_order_items_dataset.csv"):
        order_id = row["order_id"]
        if needed_order_ids is not None and order_id not in needed_order_ids:
            continue
        data.items.setdefault(order_id, []).append(
            {
                "order_id": order_id,
                "order_item_id": int(row["order_item_id"]),
                "product_id": row["product_id"],
                "seller_id": row["seller_id"],
                "shipping_limit_date": row["shipping_limit_date"],
                "price": to_dec(row["price"]),
                "freight_value": to_dec(row["freight_value"]),
            }
        )

    for row in _read_rows(data_dir / "olist_order_payments_dataset.csv"):
        order_id = row["order_id"]
        if needed_order_ids is not None and order_id not in needed_order_ids:
            continue
        data.payments.setdefault(order_id, []).append(
            {
                "order_id": order_id,
                "payment_sequential": int(row["payment_sequential"]),
                "payment_type": row["payment_type"],
                "payment_installments": int(row["payment_installments"] or 0),
                "payment_value": to_dec(row["payment_value"]),
            }
        )

    for row in _read_rows(data_dir / "olist_sellers_dataset.csv"):
        data.seller_ids.add(row["seller_id"])

    for rows in data.items.values():
        rows.sort(key=lambda r: r["order_item_id"])
    for rows in data.payments.values():
        rows.sort(key=lambda r: r["payment_sequential"])

    return data
