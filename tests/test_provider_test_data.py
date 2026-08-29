from datetime import date

from src.providers.test_data import TestDataProvider


def test_test_data_provider_returns_tempsens_for_august_20():
    provider = TestDataProvider()

    records = provider.get_ipos_opening_on(date(2026, 8, 20))

    assert [record.name for record in records] == ["Tempsens Instruments (India) Limited"]


def test_test_data_provider_does_not_return_tempsens_for_other_dates():
    provider = TestDataProvider()

    records = provider.get_ipos_opening_on(date(2026, 8, 21))

    assert records == []
