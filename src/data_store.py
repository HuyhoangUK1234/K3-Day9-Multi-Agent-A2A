"""Deterministic access layer over the nine Olist CSVs.

Stdlib only — no pandas — so the project runs without installing anything.
Every fact an agent is allowed to reason about comes from here; nothing is
inferred and nothing is invented.
"""

import csv
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .config import DATA_DIR

# Timestamps are compared verbatim as they appear in the CSV. README section 2
# is explicit that no timezone conversion is applied.
_TS_FORMAT = "%Y-%m-%d %H:%M:%S"


def _parse_ts(value: str | None) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return datetime.strptime(value, _TS_FORMAT)
    except ValueError:
        try:
            return datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            return None


def _money(value: str | None) -> float:
    try:
        return float((value or "0").strip() or 0.0)
    except ValueError:
        return 0.0


def _read(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


@dataclass
class Item:
    order_id: str
    order_item_id: int
    product_id: str
    seller_id: str
    shipping_limit_date: datetime | None
    price: float
    freight_value: float


@dataclass
class Payment:
    order_id: str
    payment_sequential: int
    payment_type: str
    payment_installments: int
    payment_value: float


@dataclass
class OrderFacts:
    """Everything the agents are permitted to see about one order."""

    order_id: str
    exists: bool
    customer_id: str = ""
    order_status: str = ""
    purchased_at: datetime | None = None
    approved_at: datetime | None = None
    delivered_carrier_at: datetime | None = None
    delivered_customer_at: datetime | None = None
    estimated_delivery_at: datetime | None = None
    items: list[Item] = field(default_factory=list)
    payments: list[Payment] = field(default_factory=list)

    # --- derived money, always rounded to 2dp (README section 4) ---------
    # float() matters: sum([]) returns int 0, which would serialise as "0"
    # instead of the "0.0" README section 6 asks for on item-less orders.
    @property
    def item_total(self) -> float:
        return round(float(sum(i.price for i in self.items)), 2)

    @property
    def freight_total(self) -> float:
        return round(float(sum(i.freight_value for i in self.items)), 2)

    @property
    def payment_total(self) -> float:
        # payment_value is the amount of one payment row, not per installment.
        return round(float(sum(p.payment_value for p in self.payments)), 2)

    @property
    def seller_ids(self) -> list[str]:
        seen: list[str] = []
        for item in self.items:
            if item.seller_id and item.seller_id not in seen:
                seen.append(item.seller_id)
        return seen

    @property
    def delivered_late(self) -> bool:
        if not self.delivered_customer_at or not self.estimated_delivery_at:
            return False
        return self.delivered_customer_at > self.estimated_delivery_at

    def late_sellers(self) -> list[str]:
        """Sellers whose shipping_limit_date was missed at carrier handoff.

        README section 4: a seller handed off late when
        order_delivered_carrier_date > that seller's item shipping_limit_date.
        """
        if not self.delivered_carrier_at:
            return []
        late: list[str] = []
        for item in self.items:
            if item.shipping_limit_date is None:
                continue
            if self.delivered_carrier_at > item.shipping_limit_date and item.seller_id not in late:
                late.append(item.seller_id)
        return late

    def payment_reconciles(self, tolerance: float = 0.10) -> bool:
        expected = round(self.item_total + self.freight_total, 2)
        return abs(self.payment_total - expected) <= tolerance


class DataStore:
    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir or DATA_DIR
        self._orders: dict[str, dict[str, str]] = {}
        self._items: dict[str, list[Item]] = {}
        self._payments: dict[str, list[Payment]] = {}
        self._seller_ids: set[str] = set()
        self._loaded = False

    def load(self) -> "DataStore":
        if self._loaded:
            return self

        for row in _read(self.data_dir / "olist_orders_dataset.csv"):
            self._orders[row["order_id"]] = row

        for row in _read(self.data_dir / "olist_order_items_dataset.csv"):
            item = Item(
                order_id=row["order_id"],
                order_item_id=int(row["order_item_id"]),
                product_id=row["product_id"],
                seller_id=row["seller_id"],
                shipping_limit_date=_parse_ts(row["shipping_limit_date"]),
                price=_money(row["price"]),
                freight_value=_money(row["freight_value"]),
            )
            self._items.setdefault(item.order_id, []).append(item)

        for row in _read(self.data_dir / "olist_order_payments_dataset.csv"):
            payment = Payment(
                order_id=row["order_id"],
                payment_sequential=int(row["payment_sequential"]),
                payment_type=row["payment_type"],
                payment_installments=int(row["payment_installments"] or 0),
                payment_value=_money(row["payment_value"]),
            )
            self._payments.setdefault(payment.order_id, []).append(payment)

        for row in _read(self.data_dir / "olist_sellers_dataset.csv"):
            self._seller_ids.add(row["seller_id"])

        for bucket in self._items.values():
            bucket.sort(key=lambda i: i.order_item_id)
        for bucket in self._payments.values():
            bucket.sort(key=lambda p: p.payment_sequential)

        self._loaded = True
        return self

    def get_order_facts(self, order_id: str) -> OrderFacts:
        self.load()
        row = self._orders.get(order_id)
        if row is None:
            return OrderFacts(order_id=order_id, exists=False)
        return OrderFacts(
            order_id=order_id,
            exists=True,
            customer_id=row.get("customer_id", ""),
            order_status=row.get("order_status", "").strip().lower(),
            purchased_at=_parse_ts(row.get("order_purchase_timestamp")),
            approved_at=_parse_ts(row.get("order_approved_at")),
            delivered_carrier_at=_parse_ts(row.get("order_delivered_carrier_date")),
            delivered_customer_at=_parse_ts(row.get("order_delivered_customer_date")),
            estimated_delivery_at=_parse_ts(row.get("order_estimated_delivery_date")),
            items=list(self._items.get(order_id, [])),
            payments=list(self._payments.get(order_id, [])),
        )

    # --- membership checks used by the verifier to reject invented IDs ---
    def order_exists(self, order_id: str) -> bool:
        self.load()
        return order_id in self._orders

    def seller_exists(self, seller_id: str) -> bool:
        self.load()
        return seller_id in self._seller_ids

    def item_exists(self, order_id: str, order_item_id: int) -> bool:
        self.load()
        return any(i.order_item_id == order_item_id for i in self._items.get(order_id, []))

    def payment_exists(self, order_id: str, sequential: int) -> bool:
        self.load()
        return any(p.payment_sequential == sequential for p in self._payments.get(order_id, []))
