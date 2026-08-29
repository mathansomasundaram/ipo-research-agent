from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .errors import MarketCalendarError
from .providers.nse import NSEClient
from .utils import parse_date, read_json, write_json


LOGGER = logging.getLogger(__name__)
CACHE_MAX_AGE_DAYS = 7


class NSEMarketCalendar:
    """Capital-market trading calendar using the NSE holiday master endpoint."""

    def __init__(self, nse: NSEClient, data_dir: Path) -> None:
        self.nse = nse
        self.data_dir = data_dir
        self._memory_cache: dict[int, set[date]] = {}

    def next_market_day(self, after: date) -> date:
        candidate = after + timedelta(days=1)
        for _ in range(15):
            if candidate.weekday() >= 5:
                candidate += timedelta(days=1)
                continue
            holidays = self.holidays_for_year(candidate.year)
            if candidate not in holidays:
                return candidate
            candidate += timedelta(days=1)
        raise MarketCalendarError(
            f"Could not determine the next market day within 15 days after {after}"
        )

    def holidays_for_year(self, year: int) -> set[date]:
        if year in self._memory_cache:
            return self._memory_cache[year]

        cache_path = self.data_dir / f"nse_holidays_{year}.json"
        cached = read_json(cache_path, default=None)

        if cached and self._cache_is_fresh(cached):
            holidays = self._dates_from_cache(cached, year)
            if holidays:
                self._memory_cache[year] = holidays
                return holidays

        try:
            payload = self.nse.get_json("/api/holiday-master", params={"type": "trading"})
            holidays = self._extract_cm_holidays(payload, year)
            if not holidays:
                raise MarketCalendarError(
                    f"NSE holiday response did not contain Capital Market holidays for {year}"
                )
            write_json(
                cache_path,
                {
                    "year": year,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "holidays": sorted(day.isoformat() for day in holidays),
                },
            )
            self._memory_cache[year] = holidays
            return holidays
        except Exception as exc:
            if cached:
                holidays = self._dates_from_cache(cached, year)
                if holidays:
                    LOGGER.warning(
                        "NSE holiday refresh failed; using cached %s calendar: %s",
                        year,
                        exc,
                    )
                    self._memory_cache[year] = holidays
                    return holidays
            raise MarketCalendarError(f"Failed to load NSE holidays for {year}: {exc}") from exc

    @staticmethod
    def _cache_is_fresh(cached: dict[str, Any]) -> bool:
        fetched_at = cached.get("fetched_at")
        if not fetched_at:
            return False
        try:
            timestamp = datetime.fromisoformat(str(fetched_at).replace("Z", "+00:00"))
        except ValueError:
            return False
        age = datetime.now(timezone.utc) - timestamp.astimezone(timezone.utc)
        return age <= timedelta(days=CACHE_MAX_AGE_DAYS)

    @staticmethod
    def _dates_from_cache(cached: dict[str, Any], year: int) -> set[date]:
        result: set[date] = set()
        for value in cached.get("holidays", []):
            parsed = parse_date(value)
            if parsed and parsed.year == year:
                result.add(parsed)
        return result

    @staticmethod
    def _extract_cm_holidays(payload: Any, year: int) -> set[date]:
        if not isinstance(payload, dict):
            return set()

        rows = payload.get("CM")
        if not isinstance(rows, list):
            # Capital Market is CM. This fallback keeps the parser resilient if NSE
            # changes the response wrapper but still returns tradingDate rows.
            rows = []
            for value in payload.values():
                if isinstance(value, list) and value and isinstance(value[0], dict):
                    if any("tradingDate" in item for item in value if isinstance(item, dict)):
                        rows = value
                        break

        holidays: set[date] = set()
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            parsed = parse_date(row.get("tradingDate") or row.get("date"))
            if parsed and parsed.year == year:
                holidays.add(parsed)
        return holidays
