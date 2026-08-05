"""Gộp ba evidence bundle thành một fact sheet phẳng cho Policy Agent.

Tách khỏi coordinator để rule engine dùng lại được mà không phải nạp tầng LLM.
"""


def merge(order: dict, payment: dict, delivery: dict) -> dict:
    sheet = dict(order)
    sheet.update(
        {
            "payments": payment.get("payments", []),
            "payment_ids": payment.get("payment_ids", []),
            "payment_count": payment.get("payment_count", 0),
            "payment_total": payment.get("payment_total"),
            "expected_total": payment.get("expected_total"),
            "delta": payment.get("delta"),
            "is_split_payment": payment.get("is_split_payment", False),
            "reconciled": payment.get("reconciled", False),
            "is_late": delivery.get("is_late", False),
            "is_delivered": delivery.get("is_delivered", False),
            "seller_handoff_late": delivery.get("seller_handoff_late", False),
            "late_seller_ids": delivery.get("late_seller_ids", []),
            "delivery_cause_code": delivery.get("cause_code"),
            "order_delivered_customer_date": delivery.get("order_delivered_customer_date"),
            "order_estimated_delivery_date": delivery.get("order_estimated_delivery_date"),
            "order_delivered_carrier_date": delivery.get("order_delivered_carrier_date"),
        }
    )
    if not sheet.get("order_status"):
        sheet["order_status"] = delivery.get("order_status")
    return sheet
