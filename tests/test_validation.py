from datetime import date, datetime, timezone

import pytest

from src.errors import EvidenceValidationError
from src.models import (
    Confidence,
    IPOAnalysis,
    IPOEvidence,
    IPORecord,
    Scorecard,
    Verdict,
)
from src.validation import AnalysisValidator


def test_low_confidence_apply_is_rejected():
    evidence = IPOEvidence(
        as_of=datetime(2026, 8, 28, tzinfo=timezone.utc),
        target_market_day=date(2026, 9, 1),
        ipo=IPORecord(
            provider="test",
            provider_id="abc",
            name="ABC Limited",
            open_date=date(2026, 9, 1),
            price_max=100,
            issue_size_cr=100,
        ),
    )
    analysis = IPOAnalysis(
        company_name="ABC Limited",
        verdict=Verdict.APPLY,
        confidence=Confidence.LOW,
        verdict_reasons=["Reason"],
        scorecard=Scorecard(
            business_quality="Good",
            financial_health="Good",
            management="Good",
            growth_visibility="Good",
            ipo_structure="Good",
            valuation="Reasonable",
            market_sentiment="Neutral",
            overall_risk="Moderate Risk",
        ),
        biggest_reason_to_consider="Reason",
        biggest_reason_to_be_careful="Risk",
        what_could_change_verdict="More data",
        final_summary="Summary",
    )

    with pytest.raises(EvidenceValidationError):
        AnalysisValidator().validate(analysis, evidence)
