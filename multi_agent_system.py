import csv
import json
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

MODEL_NAME = "gpt-4o-mini"
MODEL_PARAMETER_SIZE = "<=10B"
POLICY_VERSION_SUPPORTED = "EC_POLICY_V1"

DATA_DIR = Path("data")
INPUT_DIR = Path("input")
OUTPUT_DIR = Path("output")
LOG_DIR = Path("logging")
TRACE_FILE = LOG_DIR / "trace.jsonl"
METADATA_FILE = LOG_DIR / "metadata.json"


def round_brl(value: float) -> float:
    return float(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def parse_iso(date_text: Optional[str]) -> Optional[datetime]:
    if not date_text:
        return None
    try:
        return datetime.fromisoformat(date_text)
    except ValueError:
        return None


@dataclass
class OrderRecord:
    order_id: str
    customer_id: str
    order_status: str
    order_purchase_timestamp: str
    order_approved_at: str
    order_delivered_carrier_date: Optional[str]
    order_delivered_customer_date: Optional[str]
    order_estimated_delivery_date: Optional[str]


@dataclass
class ItemRecord:
    order_id: str
    order_item_id: str
    product_id: str
    seller_id: str
    shipping_limit_date: Optional[str]
    price: float
    freight_value: float


@dataclass
class PaymentRecord:
    order_id: str
    payment_sequential: str
    payment_type: str
    payment_installments: str
    payment_value: float


@dataclass
class CaseInput:
    case_id: str
    opened_at: str
    customer_language: str
    customer_message: str
    claimed_order_id: str
    policy_version: str


class OlistDataLoader:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.orders: Dict[str, OrderRecord] = {}
        self.items_by_order: Dict[str, List[ItemRecord]] = defaultdict(list)
        self.payments_by_order: Dict[str, List[PaymentRecord]] = defaultdict(list)
        self._load_all()

    def _load_all(self) -> None:
        self._load_orders()
        self._load_order_items()
        self._load_payments()

    def _load_orders(self) -> None:
        path = self.data_dir / "olist_orders_dataset.csv"
        with path.open(encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                self.orders[row["order_id"]] = OrderRecord(
                    order_id=row["order_id"],
                    customer_id=row["customer_id"],
                    order_status=row["order_status"],
                    order_purchase_timestamp=row["order_purchase_timestamp"],
                    order_approved_at=row["order_approved_at"],
                    order_delivered_carrier_date=row.get("order_delivered_carrier_date"),
                    order_delivered_customer_date=row.get("order_delivered_customer_date"),
                    order_estimated_delivery_date=row.get("order_estimated_delivery_date"),
                )

    def _load_order_items(self) -> None:
        path = self.data_dir / "olist_order_items_dataset.csv"
        with path.open(encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                self.items_by_order[row["order_id"]].append(
                    ItemRecord(
                        order_id=row["order_id"],
                        order_item_id=row["order_item_id"],
                        product_id=row["product_id"],
                        seller_id=row["seller_id"],
                        shipping_limit_date=row.get("shipping_limit_date"),
                        price=float(row["price"] or 0.0),
                        freight_value=float(row["freight_value"] or 0.0),
                    )
                )

    def _load_payments(self) -> None:
        path = self.data_dir / "olist_order_payments_dataset.csv"
        with path.open(encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                self.payments_by_order[row["order_id"]].append(
                    PaymentRecord(
                        order_id=row["order_id"],
                        payment_sequential=row["payment_sequential"],
                        payment_type=row["payment_type"],
                        payment_installments=row["payment_installments"],
                        payment_value=float(row["payment_value"] or 0.0),
                    )
                )


class OrderSellerAgent:
    def __init__(self, loader: OlistDataLoader):
        self.loader = loader

    def analyze(self, claimed_order_id: str) -> Dict[str, Any]:
        order = self.loader.orders.get(claimed_order_id)
        items = self.loader.items_by_order.get(claimed_order_id, [])
        order_ids = [claimed_order_id] if order else []
        item_ids = [f"{claimed_order_id}:{item.order_item_id}" for item in items][:5]
        seller_ids = list({item.seller_id for item in items})[:5]
        item_total = round_brl(sum(item.price for item in items))
        freight_total = round_brl(sum(item.freight_value for item in items))
        seller_evidence = [f"seller:{seller_id}" for seller_id in seller_ids]
        item_evidence = [f"item:{claimed_order_id}:{item.order_item_id}" for item in items[:5]]

        return {
            "order": order,
            "items": items,
            "order_ids": order_ids,
            "item_ids": item_ids,
            "seller_ids": seller_ids,
            "item_total_brl": item_total,
            "freight_total_brl": freight_total,
            "seller_evidence": seller_evidence,
            "item_evidence": item_evidence,
        }


class DeliveryAgent:
    def analyze(self, order: Optional[OrderRecord], items: List[ItemRecord]) -> Dict[str, Any]:
        if not order or not items:
            return {
                "delivery_status": "missing_data",
                "delivery_evidence": [],
                "root_cause": None,
                "root_cause_code": None,
                "responsible": None,
            }

        delivered_carrier = parse_iso(order.order_delivered_carrier_date)
        estimated = parse_iso(order.order_estimated_delivery_date)
        item_late_sellers = []
        delivery_evidence = [f"order:{order.order_id}"]

        for item in items:
            shipping_limit = parse_iso(item.shipping_limit_date)
            if delivered_carrier and shipping_limit and delivered_carrier > shipping_limit:
                item_late_sellers.append(item.seller_id)
                delivery_evidence.append(f"item:{item.order_id}:{item.order_item_id}")

        if item_late_sellers:
            seller_id = item_late_sellers[0]
            return {
                "delivery_status": "late_delivery_seller",
                "delivery_evidence": delivery_evidence,
                "root_cause": "SELLER_HANDOFF_AFTER_LIMIT",
                "root_cause_code": "SELLER_HANDOFF_AFTER_LIMIT",
                "responsible": {"party_type": "seller", "party_id": seller_id},
            }

        if delivered_carrier and estimated and delivered_carrier > estimated:
            return {
                "delivery_status": "late_delivery_logistics",
                "delivery_evidence": delivery_evidence,
                "root_cause": "CARRIER_DELIVERED_AFTER_ESTIMATE",
                "root_cause_code": "CARRIER_DELIVERED_AFTER_ESTIMATE",
                "responsible": {"party_type": "logistics_provider", "party_id": "LOGISTICS_PROVIDER"},
            }

        return {
            "delivery_status": "within_estimate",
            "delivery_evidence": delivery_evidence,
            "root_cause": "DELIVERY_WITHIN_ESTIMATE",
            "root_cause_code": "DELIVERY_WITHIN_ESTIMATE",
            "responsible": None,
        }


class PaymentAgent:
    def __init__(self, loader: OlistDataLoader):
        self.loader = loader

    def analyze(self, order_id: str, item_total: float, freight_total: float) -> Dict[str, Any]:
        payments = self.loader.payments_by_order.get(order_id, [])
        payment_ids = [f"{order_id}:{payment.payment_sequential}" for payment in payments][:5]
        payment_total = round_brl(sum(payment.payment_value for payment in payments))
        reconciled = abs(payment_total - (item_total + freight_total)) <= 0.10
        payment_evidence = [f"payment:{order_id}:{payment.payment_sequential}" for payment in payments[:5]]

        return {
            "payments": payments,
            "payment_ids": payment_ids,
            "payment_total_brl": payment_total,
            "valid_split_payment": len(payments) >= 2 and reconciled,
            "payment_evidence": payment_evidence,
        }


class PolicyAgent:
    def decide(self, order: Optional[OrderRecord], item_total: float, freight_total: float, payment_total: float, delivery_info: Dict[str, Any], payment_info: Dict[str, Any]) -> Dict[str, Any]:
        if not order:
            return self._unsupported_case(item_total, freight_total, payment_total)

        if order.order_status == "canceled" and payment_total > 0:
            return self._build_result(
                primary_issue="canceled_order_paid",
                case_status="action_required",
                recommended_refund=payment_total,
                resolution_actions=["issue_full_refund"],
                cause_code="ORDER_CANCELED_AFTER_PAYMENT",
                responsible_parties=[{"party_type": "platform", "party_id": "OLIST_PLATFORM"}],
                evidence=[f"order:{order.order_id}", "policy:ORDER_CANCELED_AFTER_PAYMENT"],
                confidence=0.95,
                item_total=item_total,
                freight_total=freight_total,
                payment_total=payment_total,
            )

        if order.order_status == "unavailable" and payment_total > 0:
            return self._build_result(
                primary_issue="unavailable_order_paid",
                case_status="action_required",
                recommended_refund=payment_total,
                resolution_actions=["issue_full_refund"],
                cause_code="ORDER_UNAVAILABLE_AFTER_PAYMENT",
                responsible_parties=[{"party_type": "platform", "party_id": "OLIST_PLATFORM"}],
                evidence=[f"order:{order.order_id}", "policy:ORDER_UNAVAILABLE_AFTER_PAYMENT"],
                confidence=0.95,
                item_total=item_total,
                freight_total=freight_total,
                payment_total=payment_total,
            )

        if delivery_info["delivery_status"] == "late_delivery_seller":
            return self._build_result(
                primary_issue="late_delivery_seller",
                case_status="action_required",
                recommended_refund=round_brl(freight_total),
                resolution_actions=["refund_freight"],
                cause_code=delivery_info["root_cause_code"],
                responsible_parties=[delivery_info["responsible"]],
                evidence=delivery_info["delivery_evidence"] + [f"policy:{delivery_info['root_cause_code']}"],
                confidence=0.92,
                item_total=item_total,
                freight_total=freight_total,
                payment_total=payment_total,
            )

        if delivery_info["delivery_status"] == "late_delivery_logistics":
            return self._build_result(
                primary_issue="late_delivery_logistics",
                case_status="action_required",
                recommended_refund=round_brl(freight_total),
                resolution_actions=["refund_freight"],
                cause_code=delivery_info["root_cause_code"],
                responsible_parties=[delivery_info["responsible"]],
                evidence=delivery_info["delivery_evidence"] + [f"policy:{delivery_info['root_cause_code']}"],
                confidence=0.92,
                item_total=item_total,
                freight_total=freight_total,
                payment_total=payment_total,
            )

        if payment_info["valid_split_payment"]:
            return self._build_result(
                primary_issue="valid_split_payment",
                case_status="no_action",
                recommended_refund=0.0,
                resolution_actions=["explain_valid_split_payment"],
                cause_code="MULTIPLE_PAYMENTS_RECONCILED",
                responsible_parties=[],
                evidence=payment_info["payment_evidence"] + ["policy:MULTIPLE_PAYMENTS_RECONCILED"],
                confidence=0.90,
                item_total=item_total,
                freight_total=freight_total,
                payment_total=payment_total,
            )

        return self._build_result(
            primary_issue="unsupported_late_claim",
            case_status="no_action",
            recommended_refund=0.0,
            resolution_actions=["reject_late_refund"],
            cause_code="DELIVERY_WITHIN_ESTIMATE",
            responsible_parties=[],
            evidence=[f"order:{order.order_id}", "policy:DELIVERY_WITHIN_ESTIMATE"],
            confidence=0.85,
            item_total=item_total,
            freight_total=freight_total,
            payment_total=payment_total,
        )

    def _unsupported_case(self, item_total: float, freight_total: float, payment_total: float) -> Dict[str, Any]:
        return self._build_result(
            primary_issue="unsupported_late_claim",
            case_status="no_action",
            recommended_refund=0.0,
            resolution_actions=["reject_late_refund"],
            cause_code="DELIVERY_WITHIN_ESTIMATE",
            responsible_parties=[],
            evidence=["policy:DELIVERY_WITHIN_ESTIMATE"],
            confidence=0.70,
            item_total=item_total,
            freight_total=freight_total,
            payment_total=payment_total,
        )

    def _build_result(
        self,
        primary_issue: str,
        case_status: str,
        recommended_refund: float,
        resolution_actions: List[str],
        cause_code: str,
        responsible_parties: List[Dict[str, str]],
        evidence: List[str],
        confidence: float,
        item_total: float,
        freight_total: float,
        payment_total: float,
    ) -> Dict[str, Any]:
        return {
            "assessment": {
                "primary_issue": primary_issue,
                "case_status": case_status,
                "confidence": round_brl(confidence),
            },
            "root_cause_analysis": {
                "ranked_causes": [{"cause_code": cause_code, "rank": 1}],
                "responsible_parties": responsible_parties[:3],
            },
            "evidence_ids": evidence[:10],
            "financial_resolution": {
                "currency": "BRL",
                "item_total_brl": round_brl(item_total),
                "freight_total_brl": round_brl(freight_total),
                "payment_total_brl": round_brl(payment_total),
                "recommended_refund_brl": round_brl(recommended_refund),
            },
            "resolution_actions": resolution_actions[:5],
        }


class VerifierAgent:
    def verify(self, output_payload: Dict[str, Any]) -> None:
        assert output_payload["assessment"]["case_status"] in {"action_required", "no_action"}
        assert 0.0 <= output_payload["assessment"]["confidence"] <= 1.0
        assert len(output_payload["evidence_ids"]) <= 10
        assert len(output_payload["root_cause_analysis"]["ranked_causes"]) <= 3
        assert len(output_payload["root_cause_analysis"]["responsible_parties"]) <= 3
        assert len(output_payload["resolution_actions"]) <= 5

        for evidence_id in output_payload["evidence_ids"]:
            assert evidence_id.startswith(("order:", "item:", "payment:", "seller:", "policy:"))


class CoordinatorAgent:
    def __init__(self, data_loader: OlistDataLoader):
        self.data_loader = data_loader
        self.order_agent = OrderSellerAgent(data_loader)
        self.delivery_agent = DeliveryAgent()
        self.payment_agent = PaymentAgent(data_loader)
        self.policy_agent = PolicyAgent()
        self.verifier = VerifierAgent()

    def process_case(self, case_input: CaseInput) -> Dict[str, Any]:
        order_context = self.order_agent.analyze(case_input.claimed_order_id)
        order = order_context["order"]
        items = order_context["items"]
        payment_context = self.payment_agent.analyze(
            case_input.claimed_order_id,
            order_context["item_total_brl"],
            order_context["freight_total_brl"],
        )
        delivery_context = self.delivery_agent.analyze(order, items)

        policy_result = self.policy_agent.decide(
            order,
            order_context["item_total_brl"],
            order_context["freight_total_brl"],
            payment_context["payment_total_brl"],
            delivery_context,
            payment_context,
        )

        output_payload = {
            "case_id": case_input.case_id,
            "assessment": policy_result["assessment"],
            "affected_entities": {
                "order_ids": order_context["order_ids"],
                "item_ids": order_context["item_ids"],
                "seller_ids": order_context["seller_ids"],
                "payment_ids": payment_context["payment_ids"],
            },
            "root_cause_analysis": policy_result["root_cause_analysis"],
            "evidence_ids": policy_result["evidence_ids"],
            "financial_resolution": policy_result["financial_resolution"],
            "resolution_actions": policy_result["resolution_actions"],
        }

        self.verifier.verify(output_payload)
        return output_payload

    def load_case_input(self, path: Path) -> CaseInput:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        customer_request = data["customer_request"]
        return CaseInput(
            case_id=data["case_id"],
            opened_at=data["opened_at"],
            customer_language=customer_request["language"],
            customer_message=customer_request["message"],
            claimed_order_id=customer_request["claimed_order_id"],
            policy_version=data.get("policy_version", ""),
        )

    def run_all(self) -> None:
        OUTPUT_DIR.mkdir(exist_ok=True)
        LOG_DIR.mkdir(exist_ok=True)
        self._write_metadata()

        with TRACE_FILE.open("w", encoding="utf-8") as trace_fh:
            for path in sorted(INPUT_DIR.glob("EC_*.json")):
                case_input = self.load_case_input(path)
                output_payload = self.process_case(case_input)
                out_path = OUTPUT_DIR / path.name
                with out_path.open("w", encoding="utf-8") as out_fh:
                    json.dump(output_payload, out_fh, ensure_ascii=False, indent=2)
                trace_fh.write(json.dumps({"case_id": case_input.case_id, "status": "processed", "output_file": str(out_path)}) + "\n")

    def _write_metadata(self) -> None:
        metadata = {
            "model_name": MODEL_NAME,
            "model_parameter_size": MODEL_PARAMETER_SIZE,
            "framework": "python",
            "runtime": "local",
            "policy_version": POLICY_VERSION_SUPPORTED,
        }
        with METADATA_FILE.open("w", encoding="utf-8") as fh:
            json.dump(metadata, fh, ensure_ascii=False, indent=2)


def load_api_credentials() -> Tuple[Optional[str], Optional[str]]:
    api_key = os.getenv("API_KEY")
    api_secret = os.getenv("API_SECRET")
    return api_key, api_secret


def main() -> None:
    api_key, api_secret = load_api_credentials()
    if not api_key or not api_secret:
        print("WARNING: API_KEY and/or API_SECRET not set in environment. This script runs locally without external model calls.")

    data_loader = OlistDataLoader(DATA_DIR)
    coordinator = CoordinatorAgent(data_loader)
    coordinator.run_all()
    print(f"Processed inputs from {INPUT_DIR} into {OUTPUT_DIR}.")
    print(f"Trace written to {TRACE_FILE} and metadata written to {METADATA_FILE}.")


if __name__ == "__main__":
    main()
