from datetime import date, datetime, timezone
from pathlib import Path

from src.models import (
    Confidence,
    IPOAnalysis,
    IPOEvidence,
    IPORecord,
    ReportSection,
    Scorecard,
    SourceConfidence,
    SourceRef,
    Verdict,
)
from src.pdf_report import PDFReportGenerator


def test_pdf_report_is_generated(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    evidence = IPOEvidence(
        as_of=datetime(2026, 8, 28, tzinfo=timezone.utc),
        target_market_day=date(2026, 9, 1),
        ipo=IPORecord(
            provider="test",
            provider_id="abc",
            name="ABC Limited",
            open_date=date(2026, 9, 1),
            close_date=date(2026, 9, 3),
            price_min=100,
            price_max=110,
            issue_size_cr=750,
        ),
        sources=[
            SourceRef(
                id="RHP-001",
                source_type="RHP",
                title="ABC Limited RHP",
                confidence=SourceConfidence.HIGH,
            )
        ],
    )
    analysis = IPOAnalysis(
        company_name="ABC Limited",
        verdict=Verdict.DEEP_ANALYSE,
        confidence=Confidence.HIGH,
        verdict_reasons=[
            "Revenue growth is healthy.",
            "Cash conversion requires attention.",
            "Valuation leaves limited room for error.",
        ],
        scorecard=Scorecard(
            business_quality="Strong",
            financial_health="Mixed",
            management="Good",
            growth_visibility="Strong",
            ipo_structure="Average",
            valuation="Expensive",
            market_sentiment="Positive",
            overall_risk="Moderate Risk",
        ),
        biggest_reason_to_consider="A growing core business with visible demand.",
        biggest_reason_to_be_careful="Reported profit is converting to cash less efficiently.",
        what_could_change_verdict="A more reasonable valuation or stronger cash conversion.",
        sections=[
            ReportSection(
                title="Company Snapshot",
                summary="ABC manufactures specialized industrial components for Indian customers.",
                key_points=["The core manufacturing division drives most revenue."],
                evidence_ids=["RHP-001"],
            ),
            ReportSection(
                title="Financial Health",
                summary="Revenue and profit are growing, but cash flow quality is mixed.",
                key_points=["Margins improved in the latest year."],
                evidence_ids=["RHP-001"],
            ),
        ],
        pros=["Growing revenue", "Manageable debt"],
        cons=["Customer concentration", "Expensive valuation"],
        data_gaps=["Exact OFS motivation was not disclosed."],
        final_summary="The company has a credible core business, but valuation and cash conversion justify deeper analysis before applying.",
    )

    output = PDFReportGenerator(root / "templates" / "report.html", tmp_path).generate(
        analysis, evidence
    )

    assert output.exists()
    assert output.stat().st_size > 5000
    assert output.read_bytes().startswith(b"%PDF")
