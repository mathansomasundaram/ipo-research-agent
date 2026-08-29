from src.providers.ipo_guru import IPOGuruProvider


class DummyHTTP:
    pass


def test_ipoguru_mapping():
    provider = IPOGuruProvider("key", DummyHTTP())  # type: ignore[arg-type]
    item = {
        "name": "Example Limited",
        "type": "Mainboard",
        "open_date": "2026-09-01",
        "close_date": "2026-09-03",
        "price_band": "163-172",
        "issue_price": "172",
        "lot_size": "80",
        "issue_size": "₹740 Cr",
        "listing_on": "BSE, NSE",
        "subscription": {"qib": "3.65", "total": "1.99"},
        "gmp": {"price": "10", "percentage": "6"},
    }

    record = provider._map_item(item)

    assert record is not None
    assert record.issue_type == "mainboard"
    assert record.price_min == 163
    assert record.price_max == 172
    assert record.issue_size_cr == 740
    assert record.lot_size == 80
    assert record.gmp.price == 10
    assert record.exchanges == ["BSE", "NSE"]
