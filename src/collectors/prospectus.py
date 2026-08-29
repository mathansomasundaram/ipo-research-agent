from __future__ import annotations

import io
import logging
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from ..errors import ProspectusError
from ..http_client import HttpClient
from ..models import IPORecord, RHPSection, SourceConfidence, SourceRef
from ..utils import slugify


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProspectusDocument:
    path: Path
    source: SourceRef


@dataclass(frozen=True)
class SectionSpec:
    key: str
    title: str
    headings: tuple[str, ...]
    max_pages: int
    max_chars: int


SECTION_SPECS: tuple[SectionSpec, ...] = (
    SectionSpec("risk_factors", "Risk Factors", (r"^RISK FACTORS$",), 35, 14000),
    SectionSpec("objects_of_issue", "Objects of the Issue", (r"^OBJECTS OF THE (?:ISSUE|OFFER)$",), 20, 9000),
    SectionSpec("industry", "Industry Overview", (r"^(?:OUR )?INDUSTRY(?: OVERVIEW)?$",), 18, 9000),
    SectionSpec("business", "Our Business", (r"^OUR BUSINESS$", r"^BUSINESS OVERVIEW$"), 30, 18000),
    SectionSpec(
        "financial_information",
        "Financial Information",
        (
            r"^SECTION V: FINANCIAL INFORMATION$",
            r"^RESTATED CONSOLIDATED FINANCIAL INFORMATION$",
        ),
        120,
        90000,
    ),
    SectionSpec("capital_structure", "Capital Structure", (r"^CAPITAL STRUCTURE$",), 18, 7000),
    SectionSpec("basis_for_offer_price", "Basis for Offer Price", (r"^BASIS FOR (?:OFFER|ISSUE) PRICE$",), 20, 10000),
    SectionSpec("management", "Management", (r"^OUR MANAGEMENT$", r"^BOARD OF DIRECTORS$"), 25, 9000),
    SectionSpec("promoters", "Promoters", (r"^OUR PROMOTERS(?: AND PROMOTER GROUP)?$",), 20, 7000),
    SectionSpec("litigation", "Outstanding Litigation and Material Developments", (r"^OUTSTANDING LITIGATION.*", r"^MATERIAL DEVELOPMENTS$"), 30, 10000),
    SectionSpec("related_party", "Related Party Transactions", (r"^RELATED PARTY TRANSACTIONS$",), 15, 6000),
    SectionSpec("indebtedness", "Outstanding Indebtedness", (r"^OUTSTANDING INDEBTEDNESS$",), 15, 6000),
)


class ProspectusCollector:
    def __init__(self, http: HttpClient, cache_dir: Path) -> None:
        self.http = http
        self.cache_dir = cache_dir

    def collect(self, ipo: IPORecord, verification_raw: dict[str, Any] | None = None) -> ProspectusDocument:
        cache_path = self.cache_dir / ipo.stable_id / "rhp.pdf"
        source_meta = self.cache_dir / ipo.stable_id / "rhp_source.txt"
        if cache_path.exists() and cache_path.stat().st_size > 10_000:
            source_url = source_meta.read_text(encoding="utf-8").strip() if source_meta.exists() else None
            return ProspectusDocument(
                path=cache_path,
                source=SourceRef(
                    id="RHP-001",
                    source_type="RHP",
                    title=f"{ipo.name} Red Herring Prospectus",
                    url=source_url,
                    confidence=SourceConfidence.HIGH,
                ),
            )

        candidates = self._candidate_urls(ipo, verification_raw or {})
        if not candidates:
            raise ProspectusError(
                "No prospectus URL or NSE symbol was available to locate the RHP."
            )

        errors: list[str] = []
        for url in candidates:
            try:
                pdf_bytes = self._download_pdf(url)
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_bytes(pdf_bytes)
                source_meta.write_text(url, encoding="utf-8")
                return ProspectusDocument(
                    path=cache_path,
                    source=SourceRef(
                        id="RHP-001",
                        source_type="RHP",
                        title=f"{ipo.name} Red Herring Prospectus",
                        url=url,
                        confidence=SourceConfidence.HIGH,
                    ),
                )
            except Exception as exc:
                LOGGER.info("Prospectus candidate failed for %s: %s", url, exc)
                errors.append(f"{url}: {exc}")

        raise ProspectusError(
            "Unable to download a usable RHP/DRHP from official/provider candidates. "
            + " | ".join(errors[-3:])
        )

    def _candidate_urls(self, ipo: IPORecord, verification_raw: dict[str, Any]) -> list[str]:
        urls = list(ipo.prospectus_urls)
        urls.extend(_extract_urls(verification_raw))

        symbol = ipo.symbol or _find_symbol(verification_raw)
        if symbol:
            clean_symbol = re.sub(r"[^A-Za-z0-9]", "", str(symbol)).upper()
            archive = "https://nsearchives.nseindia.com/content/ipo"
            urls.extend(
                [
                    f"{archive}/RHP_{clean_symbol}.zip",
                    f"{archive}/RHP_{clean_symbol}.pdf",
                    f"{archive}/DRHP_{clean_symbol}.zip",
                ]
            )

        # Prefer RHP over DRHP and official NSE/SEBI links over generic provider links.
        unique = list(dict.fromkeys(urls))
        return sorted(unique, key=_url_priority)

    def _download_pdf(self, url: str) -> bytes:
        response = self.http.request(
            "GET",
            url,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/pdf,application/zip,*/*"},
        )
        response.raise_for_status()
        content = response.content
        content_type = (response.headers.get("Content-Type") or "").lower()

        if content.startswith(b"%PDF") or "application/pdf" in content_type:
            _validate_pdf(content)
            return content

        if content.startswith(b"PK") or "zip" in content_type or url.lower().endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                pdf_names = [name for name in archive.namelist() if name.lower().endswith(".pdf")]
                if not pdf_names:
                    raise ProspectusError("ZIP did not contain a PDF")
                pdf_names.sort(
                    key=lambda name: (
                        "rhp" not in name.lower(),
                        "drhp" in name.lower(),
                        -archive.getinfo(name).file_size,
                    )
                )
                pdf_bytes = archive.read(pdf_names[0])
                _validate_pdf(pdf_bytes)
                return pdf_bytes

        raise ProspectusError(f"Downloaded content was not a PDF or ZIP ({content_type})")


class RHPSectionExtractor:
    """Extract only decision-relevant prospectus sections to control LLM context."""

    def extract(self, pdf_path: Path) -> list[RHPSection]:
        reader = PdfReader(str(pdf_path))
        page_texts = [(page.extract_text() or "").replace("\x00", " ") for page in reader.pages]
        starts = self._find_section_starts(page_texts)
        sections: list[RHPSection] = []

        ordered_starts = sorted((page, key) for key, page in starts.items())
        for spec in SECTION_SPECS:
            start = starts.get(spec.key)
            if start is None:
                fallback_pages = self._fallback_pages(page_texts, spec)
                if not fallback_pages:
                    continue
                text = "\n\n".join(page_texts[index] for index in fallback_pages)
                text = _compact_text(text)[: spec.max_chars]
                sections.append(
                    RHPSection(
                        id=f"RHP-001#{spec.key}",
                        title=spec.title,
                        text=text,
                        start_page=fallback_pages[0] + 1,
                        end_page=fallback_pages[-1] + 1,
                    )
                )
                continue

            next_start = min(
                (page for page, key in ordered_starts if page > start and key != spec.key),
                default=start + spec.max_pages,
            )
            end = min(start + spec.max_pages, next_start, len(page_texts))
            text = "\n\n".join(page_texts[start:end])
            text = _compact_text(text)[: spec.max_chars]
            if len(text) < 300:
                continue
            sections.append(
                RHPSection(
                    id=f"RHP-001#{spec.key}",
                    title=spec.title,
                    text=text,
                    start_page=start + 1,
                    end_page=end,
                )
            )
        return sections

    def _find_section_starts(self, pages: list[str]) -> dict[str, int]:
        candidates: dict[str, list[int]] = {spec.key: [] for spec in SECTION_SPECS}
        compiled = {
            spec.key: [re.compile(pattern, re.IGNORECASE) for pattern in spec.headings]
            for spec in SECTION_SPECS
        }

        for page_index, text in enumerate(pages):
            if page_index < 5:
                continue
            matched_keys: set[str] = set()
            lines = [_normalize_heading(line) for line in text.splitlines()]
            for spec in SECTION_SPECS:
                for line in lines:
                    if len(line) > 140:
                        continue
                    if spec.key == "financial_information" and page_index < 100:
                        continue
                    if any(pattern.match(line) for pattern in compiled[spec.key]):
                        matched_keys.add(spec.key)
                        break
            # A page matching many headings is usually the table of contents.
            if len(matched_keys) >= 4:
                continue
            for key in matched_keys:
                candidates[key].append(page_index)

        return {key: values[0] for key, values in candidates.items() if values}

    @staticmethod
    def _fallback_pages(pages: list[str], spec: SectionSpec) -> list[int]:
        tokens = {
            "risk_factors": ("risk factor", "material risk"),
            "objects_of_issue": ("objects of the offer", "objects of the issue", "use of proceeds"),
            "industry": ("industry overview", "market size"),
            "business": ("our business", "customers", "revenue from operations"),
            "financial_information": ("restated financial", "revenue from operations", "profit for the year"),
            "capital_structure": ("capital structure", "pre-offer", "post-offer"),
            "basis_for_offer_price": ("basis for offer price", "peer group", "price earnings"),
            "management": ("board of directors", "key managerial personnel"),
            "promoters": ("our promoters", "promoter group"),
            "litigation": ("outstanding litigation", "criminal proceedings", "tax proceedings"),
            "related_party": ("related party transactions",),
            "indebtedness": ("outstanding indebtedness", "borrowings"),
        }.get(spec.key, ())
        scored: list[tuple[int, int]] = []
        for index, text in enumerate(pages[5:], start=5):
            lower = text.lower()
            score = sum(lower.count(token) for token in tokens)
            if score:
                scored.append((score, index))
        if not scored:
            return []
        scored.sort(reverse=True)
        center = scored[0][1]
        start = max(5, center - 1)
        end = min(len(pages), center + min(4, spec.max_pages))
        return list(range(start, end))


def _extract_urls(value: Any) -> list[str]:
    urls: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)
        elif isinstance(node, str) and node.startswith("http"):
            lower = node.lower()
            if any(token in lower for token in ("rhp", "drhp", "prospectus", ".pdf", ".zip")):
                urls.append(node)

    walk(value)
    return list(dict.fromkeys(urls))


def _find_symbol(data: dict[str, Any]) -> str | None:
    for key in ("symbol", "nseSymbol", "ticker"):
        value = data.get(key)
        if value:
            return str(value)
    return None


def _url_priority(url: str) -> tuple[int, int]:
    lower = url.lower()
    official = 0 if any(domain in lower for domain in ("nseindia", "sebi.gov.in", "bseindia")) else 1
    document = 0 if "rhp" in lower and "drhp" not in lower else 1
    return official, document


def _validate_pdf(content: bytes) -> None:
    if not content.startswith(b"%PDF"):
        raise ProspectusError("Content does not start with a PDF signature")
    try:
        reader = PdfReader(io.BytesIO(content))
        if len(reader.pages) < 5:
            raise ProspectusError("Prospectus PDF appears too short")
    except Exception as exc:
        if isinstance(exc, ProspectusError):
            raise
        raise ProspectusError(f"PDF validation failed: {exc}") from exc


def _normalize_heading(line: str) -> str:
    return re.sub(r"\s+", " ", line.strip(" -:\t")).strip()


def _compact_text(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
