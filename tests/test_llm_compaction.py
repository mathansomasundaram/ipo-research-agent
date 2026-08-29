from datetime import date, datetime, timezone

from src.llm import OpenRouterAnalyst
from src.models import IPOEvidence, IPORecord, NewsEvent, RHPSection


def test_compact_evidence_preserves_structured_financial_data():
    evidence = IPOEvidence(
        as_of=datetime(2026, 8, 19, tzinfo=timezone.utc),
        target_market_day=date(2026, 8, 20),
        ipo=IPORecord(
            provider="test",
            provider_id="tempsens",
            name="Tempsens Instruments (India) Limited",
            open_date=date(2026, 8, 20),
        ),
        rhp_sections=[
            RHPSection(
                id=f"RHP-001#section_{index}",
                title=f"Section {index}",
                text="x" * 5000,
            )
            for index in range(10)
        ],
        news_events=[
            NewsEvent(
                id=f"EVENT-{index}",
                event_type="GENERAL_COMPANY_NEWS",
                title=f"News {index}",
                summary="y" * 1000,
                materiality="LOW",
                score=1,
            )
            for index in range(7)
        ],
    )

    compact = OpenRouterAnalyst._compact_evidence(evidence)

    assert len(compact.rhp_sections) == 8
    assert all(len(section.text) == 2500 for section in compact.rhp_sections)
    assert len(compact.news_events) == 5
    assert all(len(event.summary or "") == 500 for event in compact.news_events)
    assert compact.ipo.name == evidence.ipo.name
