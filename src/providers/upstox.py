from __future__ import annotations

from typing import Any

from ..errors import DiscoveryError
from ..http_client import HttpClient
from ..models import IPORecord, SubscriptionData
from ..utils import parse_date, parse_float
from .base import IPOProvider


class UpstoxProvider(IPOProvider):
    name = "upstox"
    list_url = "https://api.upstox.com/v2/ipos"

    def __init__(self, access_token: str, http: HttpClient) -> None:
        self.access_token = access_token
        self.http = http

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.access_token}",
        }

    def get_upcoming_ipos(self, include_sme: bool = False) -> list[IPORecord]:
        page = 1
        records: list[IPORecord] = []
        issue_type = "sme" if include_sme else "regular"

        while True:
            try:
                payload = self.http.get_json(
                    self.list_url,
                    params={
                        "status": "upcoming",
                        "issue_type": issue_type,
                        "page_number": page,
                        "records": 30,
                    },
                    headers=self.headers,
                )
            except Exception as exc:
                raise DiscoveryError(f"Upstox discovery failed: {exc}") from exc

            if payload.get("status") != "success":
                raise DiscoveryError(f"Upstox returned an unsuccessful response: {payload}")

            for item in payload.get("data", []):
                mapped = self._map_item(item)
                if mapped:
                    records.append(mapped)

            page_meta = payload.get("meta_data", {}).get("page", {})
            total_pages = int(page_meta.get("total_pages") or 1)
            if page >= total_pages:
                break
            page += 1

        return records

    def _map_item(self, item: dict[str, Any]) -> IPORecord | None:
        open_date = parse_date(item.get("bidding_start_date"))
        if open_date is None:
            return None

        provider_id = str(item.get("id") or "").strip()
        name = str(item.get("name") or "").strip()
        if not provider_id or not name:
            return None

        details = self._get_details(provider_id)
        combined = {**item, **details}
        prospectus_urls = _extract_urls(combined)

        subscription = combined.get("subscription") or combined.get("subscriptions") or {}
        if not isinstance(subscription, dict):
            subscription = {}

        return IPORecord(
            provider=self.name,
            provider_id=provider_id,
            name=name,
            symbol=combined.get("symbol"),
            issue_type="sme" if combined.get("issue_type") == "sme" else "mainboard",
            industry=combined.get("industry"),
            status=combined.get("status"),
            open_date=open_date,
            close_date=parse_date(combined.get("bidding_end_date")),
            price_min=parse_float(combined.get("minimum_price")),
            price_max=parse_float(combined.get("maximum_price")),
            issue_size_cr=parse_float(combined.get("issue_size")),
            lot_size=int(parse_float(combined.get("lot_size")) or 0) or None,
            registrar=_nested_text(combined, "registrar", "name"),
            subscription=SubscriptionData(
                qib=parse_float(subscription.get("qib")),
                nii=parse_float(subscription.get("nii")),
                retail=parse_float(subscription.get("retail")),
                total=parse_float(combined.get("total_subscription") or subscription.get("total")),
                updated_at=subscription.get("updated_at"),
            ),
            prospectus_urls=prospectus_urls,
            raw_data=combined,
        )

    def _get_details(self, provider_id: str) -> dict[str, Any]:
        url = f"{self.list_url}/{provider_id}"
        payload = self.http.get_json(url, headers=self.headers)
        if payload.get("status") != "success":
            return {}
        data = payload.get("data") or {}
        return data if isinstance(data, dict) else {}


def _extract_urls(value: Any) -> list[str]:
    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)
        elif isinstance(node, str):
            lower = node.lower()
            if node.startswith("http") and any(token in lower for token in ("rhp", "drhp", "prospectus", ".pdf", ".zip")):
                found.append(node)

    walk(value)
    return list(dict.fromkeys(found))


def _nested_text(data: dict[str, Any], key: str, nested_key: str) -> str | None:
    value = data.get(key)
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        nested = value.get(nested_key)
        return str(nested) if nested else None
    return None
