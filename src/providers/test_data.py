from __future__ import annotations

from datetime import date

from ..models import IPORecord
from .base import IPOProvider


class TestDataProvider(IPOProvider):
    """Built-in IPO records for local end-to-end pipeline testing."""

    name = "test_data"

    def get_upcoming_ipos(self, include_sme: bool = False) -> list[IPORecord]:
        return [
            IPORecord(
                provider=self.name,
                provider_id="tempsens-2026-08-20",
                name="Tempsens Instruments (India) Limited",
                symbol="TEMPSENS",
                issue_type="mainboard",
                industry="Thermal engineering and specialised cables",
                status="upcoming",
                open_date=date(2026, 8, 20),
                close_date=date(2026, 8, 24),
                listing_date=date(2026, 8, 28),
                price_min=285,
                price_max=300,
                face_value=4,
                lot_size=50,
                issue_size_cr=650,
                fresh_issue_cr=95,
                ofs_cr=555,
                sale_type="Fresh Issue-cum-Offer for Sale",
                exchanges=["BSE", "NSE"],
                registrar="KFin Technologies Limited",
                prospectus_urls=[
                    "https://nsearchives.nseindia.com/corporate/TempsensInstruments(India)Limited_RHP.zip",
                    "https://nsearchives.nseindia.com/corporate/Registration_29092025235356_TIPLDRHP.pdf",
                ],
                raw_data={
                    "test_data_note": (
                        "Built-in record for testing the 2026-08-19 run after "
                        "live upcoming feeds no longer include this IPO."
                    )
                },
            )
        ]
