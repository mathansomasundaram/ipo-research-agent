from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import xml.etree.ElementTree as ET

from ..http_client import HttpClient
from ..models import NewsEvent, SourceConfidence, SourceRef
from ..utils import slugify


LOGGER = logging.getLogger(__name__)
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"


EVENT_RULES: tuple[tuple[str, tuple[str, ...], int], ...] = (
    (
        "REGULATORY_GOVERNANCE",
        (
            "sebi", "regulator", "regulatory action", "penalty", "fraud", "probe",
            "investigation", "governance", "auditor resign", "qualified opinion",
            "default", "insolvency", "criminal", "scam",
        ),
        5,
    ),
    (
        "MANAGEMENT_CHANGE",
        (
            "ceo resign", "cfo resign", "md resign", "director resign", "management change",
            "chief financial officer", "chief executive officer", "appoints ceo", "appoints cfo",
        ),
        4,
    ),
    (
        "CUSTOMER_CONTRACT",
        (
            "customer loss", "loses customer", "contract cancelled", "order cancelled",
            "wins order", "order win", "contract win", "major customer", "customer added",
        ),
        4,
    ),
    (
        "OPERATIONS",
        (
            "plant shutdown", "factory shutdown", "fire", "accident", "production halt",
            "capacity expansion", "new plant", "commercial production", "commissioned",
        ),
        4,
    ),
    (
        "CAPITAL_DEBT",
        (
            "debt", "rating downgrade", "rating upgrade", "credit rating", "fund raise",
            "borrowing", "repayment", "refinancing",
        ),
        3,
    ),
    (
        "STRATEGIC_GROWTH",
        (
            "acquisition", "merger", "partnership", "joint venture", "export expansion",
            "product launch", "geographic expansion", "approval", "license",
        ),
        3,
    ),
)

GENERIC_NOISE = (
    "should you subscribe",
    "ipo review",
    "ipo gmp",
    "grey market premium",
    "ipo buzz",
    "price band announced",
    "lot size",
    "ipo opens",
    "ipo closes",
)

TRUSTED_NEWS_SOURCES = {
    "reuters",
    "the economic times",
    "business standard",
    "mint",
    "moneycontrol",
    "cnbc-tv18",
    "the hindu businessline",
    "financial express",
}


class GoogleNewsCollector:
    def __init__(self, http: HttpClient, lookback_days: int, max_events: int) -> None:
        self.http = http
        self.lookback_days = lookback_days
        self.max_events = max_events

    def collect(self, company_name: str, now: datetime) -> tuple[list[NewsEvent], list[SourceRef]]:
        raw_entries: list[dict] = []
        for query in self._queries(company_name):
            try:
                raw_entries.extend(self._fetch(query))
            except Exception as exc:
                LOGGER.warning("News query failed for %s: %s", company_name, exc)

        events: list[NewsEvent] = []
        sources: list[SourceRef] = []
        cutoff = now.astimezone(timezone.utc) - timedelta(days=self.lookback_days)

        for index, entry in enumerate(raw_entries):
            published = _parse_published(entry)
            if published and published.astimezone(timezone.utc) < cutoff:
                continue

            title = html.unescape(str(entry.get("title") or "")).strip()
            if not title:
                continue
            summary = _strip_html(str(entry.get("summary") or ""))
            source_name = _entry_source_name(entry)
            link = str(entry.get("link") or "") or None
            event_type, base_score = classify_event(title, summary)
            score = base_score + recency_score(published, now) + source_score(source_name)
            score -= noise_penalty(title)
            materiality = materiality_from_score(score)
            source_id = f"NEWS-{slugify(company_name)[:18]}-{index + 1:03d}"

            sources.append(
                SourceRef(
                    id=source_id,
                    source_type="NEWS_HEADLINE",
                    title=title,
                    url=link,
                    published_at=published.isoformat() if published else None,
                    confidence=(
                        SourceConfidence.MEDIUM
                        if source_score(source_name) > 0
                        else SourceConfidence.LOW
                    ),
                )
            )
            events.append(
                NewsEvent(
                    id=f"EVENT-{index + 1:03d}",
                    event_type=event_type,
                    published_at=published,
                    title=title,
                    summary=summary or None,
                    source_name=source_name,
                    source_url=link,
                    materiality=materiality,
                    score=score,
                    source_ids=[source_id],
                )
            )

        selected = prioritize_events(events, self.max_events)
        selected_source_ids = {source_id for event in selected for source_id in event.source_ids}
        selected_sources = [source for source in sources if source.id in selected_source_ids]
        return selected, selected_sources

    def _fetch(self, query: str) -> list[dict]:
        url = f"{GOOGLE_NEWS_RSS}?q={quote_plus(query)}&hl=en-IN&gl=IN&ceid=IN:en"
        response = self.http.request("GET", url, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        root = ET.fromstring(response.content)
        entries: list[dict] = []
        for item in root.findall("./channel/item"):
            source_element = item.find("source")
            entries.append(
                {
                    "title": _element_text(item, "title"),
                    "link": _element_text(item, "link"),
                    "summary": _element_text(item, "description"),
                    "published": _element_text(item, "pubDate"),
                    "source": {
                        "title": source_element.text.strip()
                        if source_element is not None and source_element.text
                        else None
                    },
                }
            )
        return entries

    def _queries(self, company_name: str) -> tuple[str, ...]:
        years = max(1, round(self.lookback_days / 365))
        company = f'"{company_name}"'
        return (
            f"{company} when:{years}y",
            f"{company} (SEBI OR resignation OR auditor OR fraud OR litigation OR default) when:{years}y",
            f"{company} (contract OR order OR expansion OR acquisition OR partnership OR plant) when:{years}y",
        )


def classify_event(title: str, summary: str | None) -> tuple[str, int]:
    text = f"{title} {summary or ''}".lower()
    best_type = "GENERAL_COMPANY_NEWS"
    best_score = 1
    for event_type, keywords, score in EVENT_RULES:
        if any(keyword in text for keyword in keywords) and score > best_score:
            best_type = event_type
            best_score = score
    return best_type, best_score


def recency_score(published: datetime | None, now: datetime) -> int:
    if not published:
        return 0
    age = now.astimezone(timezone.utc) - published.astimezone(timezone.utc)
    if age <= timedelta(days=90):
        return 2
    if age <= timedelta(days=365):
        return 1
    return 0


def source_score(source_name: str | None) -> int:
    if not source_name:
        return 0
    lower = source_name.lower()
    return 2 if any(source in lower for source in TRUSTED_NEWS_SOURCES) else 0


def noise_penalty(title: str) -> int:
    lower = title.lower()
    return 3 if any(noise in lower for noise in GENERIC_NOISE) else 0


def materiality_from_score(score: int) -> str:
    if score >= 8:
        return "VERY HIGH"
    if score >= 5:
        return "HIGH"
    if score >= 3:
        return "MEDIUM"
    return "LOW"


def prioritize_events(events: list[NewsEvent], max_events: int) -> list[NewsEvent]:
    """Deduplicate, cap repeated event types, and keep the highest materiality items."""
    selected: list[NewsEvent] = []
    type_counts: dict[str, int] = {}

    for event in sorted(events, key=lambda item: (item.score, item.published_at or datetime.min.replace(tzinfo=timezone.utc)), reverse=True):
        if event.score <= 0:
            continue
        if any(_similar_titles(event.title, existing.title) for existing in selected):
            continue
        if type_counts.get(event.event_type, 0) >= 3:
            continue
        selected.append(event)
        type_counts[event.event_type] = type_counts.get(event.event_type, 0) + 1
        if len(selected) >= max_events:
            break
    return selected


def _similar_titles(left: str, right: str) -> bool:
    clean_left = _normalize_title(left)
    clean_right = _normalize_title(right)
    return SequenceMatcher(None, clean_left, clean_right).ratio() >= 0.82


def _normalize_title(value: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", value.lower()).strip()


def _parse_published(entry: dict) -> datetime | None:
    value = entry.get("published") or entry.get("updated")
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except (TypeError, ValueError):
        return None


def _entry_source_name(entry: dict) -> str | None:
    source = entry.get("source")
    if isinstance(source, dict):
        title = source.get("title")
        return str(title) if title else None
    return None


def _strip_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _element_text(item: ET.Element, tag: str) -> str | None:
    element = item.find(tag)
    if element is None or element.text is None:
        return None
    return element.text.strip()
