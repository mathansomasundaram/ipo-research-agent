from __future__ import annotations

from math import isfinite

from .models import CalculatedMetrics, FinancialPeriod, IPORecord


def calculate_metrics(ipo: IPORecord, financials: list[FinancialPeriod]) -> CalculatedMetrics:
    latest = financials[-1] if financials else None
    oldest = financials[0] if len(financials) >= 2 else None
    periods = max(len(financials) - 1, 0)

    return CalculatedMetrics(
        revenue_cagr_pct=_cagr(oldest.revenue_cr if oldest else None, latest.revenue_cr if latest else None, periods),
        pat_cagr_pct=_cagr(oldest.pat_cr if oldest else None, latest.pat_cr if latest else None, periods),
        latest_ebitda_margin_pct=_ratio_pct(latest.ebitda_cr if latest else None, latest.revenue_cr if latest else None),
        latest_pat_margin_pct=_ratio_pct(latest.pat_cr if latest else None, latest.revenue_cr if latest else None),
        latest_cfo_pat_ratio=_ratio(latest.operating_cash_flow_cr if latest else None, latest.pat_cr if latest else None),
        latest_debt_equity_ratio=_ratio(latest.debt_cr if latest else None, latest.equity_cr if latest else None),
        fresh_issue_pct=_issue_mix_pct(ipo.fresh_issue_cr, ipo.issue_size_cr),
        ofs_pct=_issue_mix_pct(ipo.ofs_cr, ipo.issue_size_cr),
        minimum_investment_rupees=_minimum_investment(ipo),
    )


def _cagr(start: float | None, end: float | None, periods: int) -> float | None:
    if start is None or end is None or periods <= 0 or start <= 0 or end < 0:
        return None
    value = ((end / start) ** (1 / periods) - 1) * 100
    return round(value, 2) if isfinite(value) else None


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    value = numerator / denominator
    return round(value, 2) if isfinite(value) else None


def _ratio_pct(numerator: float | None, denominator: float | None) -> float | None:
    ratio = _ratio(numerator, denominator)
    return round(ratio * 100, 2) if ratio is not None else None


def _issue_mix_pct(component: float | None, total: float | None) -> float | None:
    return _ratio_pct(component, total)


def _minimum_investment(ipo: IPORecord) -> float | None:
    price = ipo.price_max or ipo.issue_price
    if price is None or ipo.lot_size is None:
        return None
    return round(price * ipo.lot_size, 2)
