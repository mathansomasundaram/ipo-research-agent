from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

from .models import ExchangeVerification, IPORecord
from .providers.nse import NSEClient
from .utils import normalize_company_name, parse_date


class NSEIPOVerifier:
    source_url = "https://www.nseindia.com/market-data/all-upcoming-issues-ipo"

    def __init__(self, nse: NSEClient) -> None:
        self.nse = nse

    def verify(self, ipo: IPORecord) -> ExchangeVerification:
        try:
            upcoming = self.nse.get_json("/api/all-upcoming-issues", params={"category": "ipo"})
            current = self.nse.get_json("/api/ipo-current-issue")
            items = _as_list(upcoming) + _as_list(current)
        except Exception as exc:
            return ExchangeVerification(
                verified=False,
                source_url=self.source_url,
                warning=f"NSE verification unavailable: {exc}",
            )

        match = self._best_match(ipo, items)
        if not match:
            return ExchangeVerification(
                verified=False,
                source_url=self.source_url,
                warning="IPO was not matched in NSE upcoming/current issue data.",
            )

        matched_name = str(_first(match, "companyName", "company", "name", default=""))
        matched_open = parse_date(_first(match, "issueStartDate", "startDate", "openDate"))
        date_matches = matched_open is None or matched_open == ipo.open_date
        return ExchangeVerification(
            verified=date_matches,
            matched_name=matched_name or None,
            symbol=_first(match, "symbol", "nseSymbol"),
            open_date=matched_open,
            close_date=parse_date(_first(match, "issueEndDate", "endDate", "closeDate")),
            source_url=self.source_url,
            warning=None if date_matches else (
                f"NSE open date {matched_open} differs from provider date {ipo.open_date}."
            ),
            raw_data=match,
        )

    @staticmethod
    def _best_match(ipo: IPORecord, items: list[dict[str, Any]]) -> dict[str, Any] | None:
        target = normalize_company_name(ipo.name)
        best: tuple[float, dict[str, Any]] | None = None

        for item in items:
            name = _first(item, "companyName", "company", "name", "issuerName")
            if not name:
                continue
            candidate = normalize_company_name(str(name))
            if not candidate:
                continue
            score = SequenceMatcher(None, target, candidate).ratio()
            if target == candidate:
                score = 1.0
            if best is None or score > best[0]:
                best = (score, item)

        if best and best[0] >= 0.78:
            return best[1]
        return None


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
