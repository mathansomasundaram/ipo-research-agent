from src.collectors.financials import FinancialExtractor
from src.models import RHPSection


def test_financial_extractor_parses_simple_three_year_table():
    text = """
    Restated Financial Information
    (Rs. in crore)
    Particulars FY2024 FY2025 FY2026
    Revenue from operations 100 120 150
    EBITDA 20 24 33
    Profit for the year 10 13 18
    Net cash generated from operating activities 8 12 16
    Total borrowings 70 60 45
    Total equity 80 95 120
    """
    section = RHPSection(
        id="RHP-001#financial_information",
        title="Financial Information",
        text=text,
    )

    periods, warnings = FinancialExtractor().extract([section])

    assert [period.period for period in periods] == ["FY24", "FY25", "FY26"]
    assert periods[-1].revenue_cr == 150
    assert periods[-1].pat_cr == 18
    assert periods[-1].operating_cash_flow_cr == 16
    assert warnings == []
