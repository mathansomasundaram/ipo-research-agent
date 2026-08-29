from datetime import date

from src.calculations import calculate_metrics
from src.models import FinancialPeriod, IPORecord


def test_financial_metrics_are_deterministic():
    ipo = IPORecord(
        provider="test",
        provider_id="abc",
        name="ABC Limited",
        open_date=date(2026, 9, 1),
        price_max=200,
        lot_size=75,
        issue_size_cr=1000,
        fresh_issue_cr=600,
        ofs_cr=400,
    )
    financials = [
        FinancialPeriod(period="FY24", revenue_cr=100, pat_cr=10),
        FinancialPeriod(period="FY25", revenue_cr=120, pat_cr=12),
        FinancialPeriod(
            period="FY26",
            revenue_cr=144,
            ebitda_cr=28.8,
            pat_cr=18,
            operating_cash_flow_cr=15,
            debt_cr=50,
            equity_cr=100,
        ),
    ]

    metrics = calculate_metrics(ipo, financials)

    assert metrics.revenue_cagr_pct == 20.0
    assert metrics.latest_ebitda_margin_pct == 20.0
    assert metrics.latest_cfo_pat_ratio == 0.83
    assert metrics.latest_debt_equity_ratio == 0.5
    assert metrics.fresh_issue_pct == 60.0
    assert metrics.ofs_pct == 40.0
    assert metrics.minimum_investment_rupees == 15000
