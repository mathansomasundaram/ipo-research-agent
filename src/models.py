from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Verdict(str, Enum):
    APPLY = "APPLY"
    DEEP_ANALYSE = "DEEP ANALYSE"
    IGNORE = "IGNORE"


class Confidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ConcernLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class SourceConfidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class SourceRef(StrictModel):
    id: str
    source_type: str
    title: str
    url: str | None = None
    published_at: str | None = None
    confidence: SourceConfidence


class SubscriptionData(StrictModel):
    qib: float | None = None
    nii: float | None = None
    retail: float | None = None
    total: float | None = None
    updated_at: str | None = None


class GMPData(StrictModel):
    price: float | None = None
    percentage: float | None = None
    updated_at: str | None = None


class IPORecord(StrictModel):
    provider: str
    provider_id: str
    name: str
    symbol: str | None = None
    issue_type: str = "mainboard"
    industry: str | None = None
    status: str | None = None

    open_date: date
    close_date: date | None = None
    allotment_date: date | None = None
    listing_date: date | None = None

    price_min: float | None = None
    price_max: float | None = None
    issue_price: float | None = None
    face_value: float | None = None
    lot_size: int | None = None
    issue_size_cr: float | None = None
    fresh_issue_cr: float | None = None
    ofs_cr: float | None = None
    sale_type: str | None = None

    exchanges: list[str] = Field(default_factory=list)
    registrar: str | None = None
    subscription: SubscriptionData = Field(default_factory=SubscriptionData)
    gmp: GMPData = Field(default_factory=GMPData)
    prospectus_urls: list[str] = Field(default_factory=list)
    raw_data: dict[str, Any] = Field(default_factory=dict)

    @property
    def stable_id(self) -> str:
        from .utils import slugify

        return f"{slugify(self.name)}_{self.open_date.isoformat()}"


class ExchangeVerification(StrictModel):
    verified: bool
    exchange: str = "NSE"
    matched_name: str | None = None
    symbol: str | None = None
    open_date: date | None = None
    close_date: date | None = None
    source_url: str | None = None
    warning: str | None = None
    raw_data: dict[str, Any] = Field(default_factory=dict)


class RHPSection(StrictModel):
    id: str
    title: str
    text: str
    start_page: int | None = None
    end_page: int | None = None


class FinancialPeriod(StrictModel):
    period: str
    revenue_cr: float | None = None
    ebitda_cr: float | None = None
    pat_cr: float | None = None
    operating_cash_flow_cr: float | None = None
    debt_cr: float | None = None
    equity_cr: float | None = None
    receivables_cr: float | None = None
    inventory_cr: float | None = None


class CalculatedMetrics(StrictModel):
    revenue_cagr_pct: float | None = None
    pat_cagr_pct: float | None = None
    latest_ebitda_margin_pct: float | None = None
    latest_pat_margin_pct: float | None = None
    latest_cfo_pat_ratio: float | None = None
    latest_debt_equity_ratio: float | None = None
    fresh_issue_pct: float | None = None
    ofs_pct: float | None = None
    minimum_investment_rupees: float | None = None


class NewsEvent(StrictModel):
    id: str
    event_type: str
    published_at: datetime | None = None
    title: str
    summary: str | None = None
    source_name: str | None = None
    source_url: str | None = None
    materiality: str
    score: int
    source_ids: list[str] = Field(default_factory=list)


class IPOEvidence(StrictModel):
    as_of: datetime
    target_market_day: date
    ipo: IPORecord
    exchange_verification: ExchangeVerification | None = None
    financials: list[FinancialPeriod] = Field(default_factory=list)
    calculated_metrics: CalculatedMetrics = Field(default_factory=CalculatedMetrics)
    rhp_sections: list[RHPSection] = Field(default_factory=list)
    news_events: list[NewsEvent] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class Scorecard(StrictModel):
    business_quality: str
    financial_health: str
    management: str
    growth_visibility: str
    ipo_structure: str
    valuation: str
    market_sentiment: str
    overall_risk: str


class ReportSection(StrictModel):
    title: str
    summary: str
    key_points: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class RedFlag(StrictModel):
    issue: str
    evidence: str
    why_it_matters: str
    concern_level: ConcernLevel
    evidence_ids: list[str] = Field(default_factory=list)


class RiskItem(StrictModel):
    title: str
    explanation: str
    concern_level: ConcernLevel
    evidence_ids: list[str] = Field(default_factory=list)


class IPOAnalysis(StrictModel):
    company_name: str
    verdict: Verdict
    confidence: Confidence
    verdict_reasons: list[str] = Field(min_length=1, max_length=5)
    scorecard: Scorecard
    biggest_reason_to_consider: str
    biggest_reason_to_be_careful: str
    what_could_change_verdict: str
    sections: list[ReportSection] = Field(default_factory=list)
    red_flags: list[RedFlag] = Field(default_factory=list)
    risks: list[RiskItem] = Field(default_factory=list)
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)
    final_summary: str

    @field_validator("verdict_reasons")
    @classmethod
    def clean_reasons(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item.strip()]
        if not cleaned:
            raise ValueError("At least one verdict reason is required")
        return cleaned[:5]
