"""Tiền tệ dùng Decimal, không dùng float, để tổng tiền không bị lệch số lẻ."""

from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("0.01")
ZERO = Decimal("0.00")

# Ngưỡng lệch cho phép khi đối soát payment với item + freight (BRL).
RECONCILE_TOLERANCE = Decimal("0.10")


def to_dec(value) -> Decimal:
    """Đọc một ô CSV thành Decimal. Ô rỗng hoặc hỏng trả về 0.00."""
    if value is None:
        return ZERO
    text = str(value).strip()
    if not text:
        return ZERO
    try:
        return Decimal(text)
    except Exception:
        return ZERO


def dec2(value: Decimal) -> Decimal:
    """Làm tròn 2 chữ số thập phân theo lối thông thường (0.005 lên 0.01)."""
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def f2(value) -> float:
    """Số tiền dạng float 2 chữ số, đúng khuôn để ghi vào JSON output."""
    return float(dec2(to_dec(value) if not isinstance(value, Decimal) else value))
