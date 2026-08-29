from __future__ import annotations

import logging
from typing import Any

from ..errors import DiscoveryError
from ..http_client import HttpClient
from ..models import IPORecord
from ..utils import parse_date, parse_float, parse_price_band, slugify
from .base import IPOProvider


LOGGER = logging.getLogger(__name__)


class NSEClient:
    base_url = "https://www.nseindia.com"

    def __init__(self, http: HttpClient) -> None:
        self.http = http
        self._warmed = False

    @property
    def headers(self) -> dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"
            ),
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": f"{self.base_url}/market-data/all-upcoming-issues-ipo",
        }

    def warm(self) -> None:
        if self._warmed:
            return
        try:
            response = self.http.request("GET", self.base_url, headers=self.headers)
            response.raise_for_status()
        except Exception as exc:
            LOGGER.warning("NSE warm-up request failed; trying API endpoint directly: %s", exc)
        self._warmed = True

    def get_json(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        self.warm()
        url = f"{self.base_url}{path}"
        response = self.http.request("GET", url, params=params, headers=self.headers)
        if response.status_code in {401, 403}:
            self._warmed = False
            self.warm()
            response = self.http.request("GET", url, params=params, headers=self.headers)
        response.raise_for_status()
        return response.json()


class NSEProvider(IPOProvider):
    """No-key provider using NSE's public website JSON endpoints.

    The endpoint is public-facing but undocumented, so it is kept behind the same
    provider interface as the documented alternatives and can be swapped out.
    """

    name = "nse"

    def __init__(self, nse: NSEClient) -> None:
        self.nse = nse

    def get_upcoming_ipos(self, include_sme: bool = False) -> list[IPORecord]:
        try:
            payload = self.nse.get_json("/api/all-upcoming-issues", params={"category": "ipo"})
        except Exception as exc:
            raise DiscoveryError(f"NSE discovery failed: {exc}") from exc

        items = _as_list(payload)
        records: list[IPORecord] = []
        for item in items:
            record = self._map_item(item)
            if not record:
                continue
            if not include_sme and record.issue_type == "sme":
                continue
            records.append(record)
        return records

    def _map_item(self, item: dict[str, Any]) -> IPORecord | None:
        name = _first(item, "companyName", "company", "name", "issuerName")
        open_date = parse_date(_first(item, "issueStartDate", "startDate", "openDate"))
        if not name or open_date is None:
            return None

        issue_type_text = str(
            _first(item, "issueType", "series", "category", "securityType", default="")
        ).lower()
        issue_type = "sme" if "sme" in issue_type_text else "mainboard"
        price_min, price_max = parse_price_band(
            _first(item, "priceBand", "issuePrice", "priceRange")
        )

        return IPORecord(
            provider=self.name,
            provider_id=str(_first(item, "symbol", "id", default=slugify(str(name)))),
            name=str(name),
            symbol=_first(item, "symbol", "nseSymbol"),
            issue_type=issue_type,
            industry=_first(item, "industry", "sector"),
            status="upcoming",
            open_date=open_date,
            close_date=parse_date(_first(item, "issueEndDate", "endDate", "closeDate")),
            price_min=price_min,
            price_max=price_max,
            issue_size_cr=parse_float(_first(item, "issueSize", "issueSizeCr")),
            lot_size=int(parse_float(_first(item, "lotSize", "marketLot")) or 0) or None,
            prospectus_urls=_extract_urls(item),
            raw_data=item,
        )


def _first(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return default


def _as_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("data", "records", "upcoming", "issues"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _extract_urls(value: Any) -> list[str]:
    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)
        elif isinstance(node, str) and node.startswith("http"):
            lower = node.lower()
            if any(token in lower for token in ("rhp", "drhp", "prospectus", ".pdf", ".zip")):
                found.append(node)

    walk(value)
    return list(dict.fromkeys(found))
