from __future__ import annotations

import logging
from datetime import datetime

from .calculations import calculate_metrics
from .collectors.financials import FinancialExtractor
from .collectors.news import GoogleNewsCollector
from .collectors.prospectus import ProspectusCollector, RHPSectionExtractor
from .exchange_verifier import NSEIPOVerifier
from .models import IPOEvidence, IPORecord, SourceConfidence, SourceRef


LOGGER = logging.getLogger(__name__)


class EvidenceCollector:
    def __init__(
        self,
        verifier: NSEIPOVerifier,
        prospectus_collector: ProspectusCollector,
        section_extractor: RHPSectionExtractor,
        financial_extractor: FinancialExtractor,
        news_collector: GoogleNewsCollector,
    ) -> None:
        self.verifier = verifier
        self.prospectus_collector = prospectus_collector
        self.section_extractor = section_extractor
        self.financial_extractor = financial_extractor
        self.news_collector = news_collector

    def collect(self, ipo: IPORecord, target_market_day, now: datetime) -> IPOEvidence:
        sources: list[SourceRef] = []
        warnings: list[str] = []
        data_gaps: list[str] = []

        LOGGER.info("%s evidence step: NSE verification started", ipo.name)
        verification = self.verifier.verify(ipo)
        LOGGER.info(
            "%s evidence step: NSE verification done verified=%s, symbol=%s, warning=%s",
            ipo.name,
            verification.verified,
            verification.symbol,
            bool(verification.warning),
        )
        if verification.warning:
            warnings.append(verification.warning)
        if verification.symbol and not ipo.symbol:
            ipo = ipo.model_copy(update={"symbol": verification.symbol})
        if verification.open_date and verification.open_date != ipo.open_date:
            warnings.append(
                f"Provider/NSE opening-date conflict: provider={ipo.open_date}, NSE={verification.open_date}."
            )
        if verification.source_url:
            sources.append(
                SourceRef(
                    id="NSE-IPO-001",
                    source_type="NSE_IPO_DATA",
                    title="NSE IPO upcoming/current issue data",
                    url=verification.source_url,
                    confidence=SourceConfidence.HIGH,
                )
            )

        LOGGER.info("%s evidence step: prospectus collection started", ipo.name)
        prospectus = self.prospectus_collector.collect(ipo, verification.raw_data)
        sources.append(prospectus.source)
        LOGGER.info(
            "%s evidence step: prospectus collected path=%s, source_url=%s",
            ipo.name,
            prospectus.path,
            prospectus.source.url,
        )
        LOGGER.info("%s evidence step: RHP section extraction started", ipo.name)
        sections = self.section_extractor.extract(prospectus.path)
        LOGGER.info("%s evidence step: RHP section extraction done count=%s", ipo.name, len(sections))
        if len(sections) < 3:
            warnings.append(
                f"Only {len(sections)} relevant RHP sections were extracted; report confidence may be reduced."
            )

        LOGGER.info("%s evidence step: financial extraction started", ipo.name)
        financials, financial_warnings = self.financial_extractor.extract(sections)
        LOGGER.info(
            "%s evidence step: financial extraction done rows=%s, warnings=%s",
            ipo.name,
            len(financials),
            len(financial_warnings),
        )
        warnings.extend(financial_warnings)
        if not financials:
            data_gaps.append(
                "Structured financial table extraction was not reliable; the LLM must reason from the extracted RHP financial text."
            )

        try:
            LOGGER.info("%s evidence step: news collection started", ipo.name)
            news_events, news_sources = self.news_collector.collect(ipo.name, now)
            LOGGER.info(
                "%s evidence step: news collection done events=%s, sources=%s",
                ipo.name,
                len(news_events),
                len(news_sources),
            )
            sources.extend(news_sources)
            if not news_events:
                data_gaps.append("No material recent news event survived deterministic filtering.")
        except Exception as exc:
            LOGGER.warning("News collection failed for %s: %s", ipo.name, exc)
            news_events = []
            data_gaps.append(f"Recent news collection unavailable: {exc}")

        # IPO Guru is a low-confidence source for GMP by design; preserve it as
        # time-sensitive market context, never as the basis for the verdict.
        if ipo.provider == "ipo_guru":
            sources.append(
                SourceRef(
                    id="IPO-GURU-001",
                    source_type="IPO_AGGREGATOR",
                    title="IPO Guru IPO/GMP data",
                    url="https://www.ipoguru.in/ipo-gmp-details-developer-api",
                    published_at=ipo.gmp.updated_at or ipo.subscription.updated_at,
                    confidence=SourceConfidence.LOW,
                )
            )

        metrics = calculate_metrics(ipo, financials)
        return IPOEvidence(
            as_of=now,
            target_market_day=target_market_day,
            ipo=ipo,
            exchange_verification=verification,
            financials=financials,
            calculated_metrics=metrics,
            rhp_sections=sections,
            news_events=news_events,
            sources=_dedupe_sources(sources),
            data_gaps=data_gaps,
            warnings=warnings,
        )


def _dedupe_sources(sources: list[SourceRef]) -> list[SourceRef]:
    result: list[SourceRef] = []
    seen: set[str] = set()
    for source in sources:
        if source.id in seen:
            continue
        seen.add(source.id)
        result.append(source)
    return result
