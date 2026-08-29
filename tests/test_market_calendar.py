from datetime import date
from pathlib import Path

from src.market_calendar import NSEMarketCalendar


class DummyNSE:
    pass


def test_next_market_day_skips_weekend_and_holiday(tmp_path: Path):
    calendar = NSEMarketCalendar(DummyNSE(), tmp_path)  # type: ignore[arg-type]
    calendar.holidays_for_year = lambda year: {date(2026, 8, 31)}  # type: ignore[method-assign]

    # Friday 28 Aug -> weekend -> Monday holiday -> Tuesday 1 Sep.
    assert calendar.next_market_day(date(2026, 8, 28)) == date(2026, 9, 1)
