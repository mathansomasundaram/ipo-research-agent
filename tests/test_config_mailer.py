from datetime import date
from pathlib import Path

from src.config import Settings
from src.mailer import FailedIPO, GmailMailer, SuccessfulReport
from src.models import Confidence, IPOAnalysis, IPORecord, Scorecard, Verdict


def _analysis() -> IPOAnalysis:
    return IPOAnalysis(
        company_name="ABC Limited",
        verdict=Verdict.DEEP_ANALYSE,
        confidence=Confidence.HIGH,
        verdict_reasons=["Strong business, but valuation needs attention."],
        scorecard=Scorecard(
            business_quality="Strong",
            financial_health="Good",
            management="Good",
            growth_visibility="Good",
            ipo_structure="Mixed",
            valuation="Expensive",
            market_sentiment="Neutral",
            overall_risk="Moderate",
        ),
        biggest_reason_to_consider="Good operating performance.",
        biggest_reason_to_be_careful="Valuation.",
        what_could_change_verdict="A lower effective valuation.",
        sections=[],
        red_flags=[],
        risks=[],
        pros=["Growth"],
        cons=["Valuation"],
        data_gaps=[],
        final_summary="Worth deeper analysis.",
    )


def test_settings_parse_multiple_report_and_failure_recipients(monkeypatch):
    monkeypatch.setenv("EMAIL_TO", "one@example.com, two@example.com")
    monkeypatch.setenv("FAILURE_TO", "ops1@example.com,ops2@example.com")

    settings = Settings.from_env()

    assert settings.email_to == ("one@example.com", "two@example.com")
    assert settings.failure_to == ("ops1@example.com", "ops2@example.com")


def test_daily_email_body_mentions_successes_and_failures(tmp_path: Path):
    ipo_ok = IPORecord(
        name="ABC Limited",
        open_date=date(2026, 9, 1),
        provider="test",
        provider_id="abc",
    )
    ipo_failed = IPORecord(
        name="XYZ Limited",
        open_date=date(2026, 9, 1),
        provider="test",
        provider_id="xyz",
    )
    report = tmp_path / "abc.pdf"
    report.write_bytes(b"%PDF-test")

    successes = [
        SuccessfulReport(
            ipo=ipo_ok,
            analysis=_analysis(),
            pdf_path=report,
            evidence_hash="hash",
        )
    ]
    failures = [FailedIPO(ipo=ipo_failed, stage="RHP_EXTRACTION", error="RHP unavailable")]

    body = GmailMailer._daily_body(date(2026, 9, 1), successes, failures)

    assert "ABC Limited: DEEP ANALYSE" in body
    assert "XYZ Limited | stage=RHP_EXTRACTION | RHP unavailable" in body
    assert "Detailed PDF reports are attached." in body
