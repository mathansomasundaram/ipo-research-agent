from datetime import datetime, timedelta, timezone

from src.collectors.news import (
    classify_event,
    materiality_from_score,
    prioritize_events,
)
from src.models import NewsEvent


def event(title: str, event_type: str, score: int, days_ago: int = 1) -> NewsEvent:
    now = datetime(2026, 8, 28, tzinfo=timezone.utc)
    return NewsEvent(
        id=title,
        event_type=event_type,
        published_at=now - timedelta(days=days_ago),
        title=title,
        materiality=materiality_from_score(score),
        score=score,
    )


def test_governance_event_scores_higher_than_generic_news():
    governance_type, governance_score = classify_event(
        "Company CFO resigns after auditor raises concerns", "SEBI review mentioned"
    )
    generic_type, generic_score = classify_event("Company announces IPO price band", "")

    assert governance_type == "REGULATORY_GOVERNANCE"
    assert governance_score > generic_score
    assert generic_type == "GENERAL_COMPANY_NEWS"


def test_prioritization_deduplicates_similar_headlines_and_caps_types():
    events = [
        event("ABC CFO resigns from company", "MANAGEMENT_CHANGE", 8),
        event("ABC company CFO resigns", "MANAGEMENT_CHANGE", 7),
        event("ABC appoints new CEO", "MANAGEMENT_CHANGE", 6),
        event("ABC appoints new CFO", "MANAGEMENT_CHANGE", 5),
        event("ABC wins large contract", "CUSTOMER_CONTRACT", 7),
    ]

    selected = prioritize_events(events, max_events=10)

    assert len([item for item in selected if item.event_type == "MANAGEMENT_CHANGE"]) <= 3
    assert any(item.event_type == "CUSTOMER_CONTRACT" for item in selected)
