from __future__ import annotations

from typing import Any

from ..errors import DiscoveryError
from ..http_client import HttpClient
from ..models import GMPData, IPORecord, SubscriptionData
from ..utils import parse_crore, parse_date, parse_float, parse_price_band, slugify
from .base import IPOProvider


class IPOGuruProvider(IPOProvider):
    name = "ipo_guru"
    base_url = "https://www.ipoguru.in/api/v1/ipos"

    def __init__(self, api_key: str, http: HttpClient) -> None:
        self.api_key = api_key
        self.http = http

    def get_upcoming_ipos(self, include_sme: bool = False) -> list[IPORecord]:
        params = {
            "type": "sme" if include_sme else "mainboard",
            "status": "upcoming",
        }
        try:
            payload = self.http.get_json(
                self.base_url,
                params=params,
                headers={"X-API-KEY": self.api_key, "Accept": "application/json"},
            )
        except Exception as exc:
            raise DiscoveryError(f"IPO Guru discovery failed: {exc}") from exc

        if not payload.get("success", False):
            raise DiscoveryError(f"IPO Guru returned an unsuccessful response: {payload}")

        records: list[IPORecord] = []
        for item in payload.get("data", []):
            record = self._map_item(item)
            if record:
                records.append(record)
        return records

    def _map_item(self, item: dict[str, Any]) -> IPORecord | None:
        open_date = parse_date(item.get("open_date"))
        if open_date is None:
            return None

        price_min, price_max = parse_price_band(item.get("price_band"))
        listing_on = str(item.get("listing_on") or "")
        exchanges = [part.strip().upper() for part in listing_on.split(",") if part.strip()]
        subscription = item.get("subscription") or {}
        gmp = item.get("gmp") or {}
        name = str(item.get("name") or "").strip()
        if not name:
            return None

        return IPORecord(
            provider=self.name,
            provider_id=slugify(name),
            name=name,
            issue_type="sme" if str(item.get("type", "")).lower() == "sme" else "mainboard",
            status=str(item.get("status") or "upcoming").lower(),
            open_date=open_date,
            close_date=parse_date(item.get("close_date")),
            allotment_date=parse_date(item.get("allotment_date")),
            listing_date=parse_date(item.get("listing_date")),
            price_min=price_min,
            price_max=price_max,
            issue_price=parse_float(item.get("issue_price")),
            face_value=parse_float(item.get("face_value")),
            lot_size=int(parse_float(item.get("lot_size")) or 0) or None,
            issue_size_cr=parse_crore(item.get("issue_size")),
            sale_type=item.get("sale_type"),
            exchanges=exchanges,
            registrar=item.get("registrar"),
            subscription=SubscriptionData(
                qib=parse_float(subscription.get("qib")),
                nii=parse_float(subscription.get("nii")),
                retail=parse_float(subscription.get("retail")),
                total=parse_float(subscription.get("total")),
                updated_at=subscription.get("updated_at"),
            ),
            gmp=GMPData(
                price=parse_float(gmp.get("price")),
                percentage=parse_float(gmp.get("percentage")),
                updated_at=gmp.get("updated_at"),
            ),
            raw_data=item,
        )
