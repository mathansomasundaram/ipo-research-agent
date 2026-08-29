from __future__ import annotations

import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML

from .errors import PDFGenerationError
from .models import IPOAnalysis, IPOEvidence
from .utils import slugify


SECTION_ORDER = {
    "company snapshot": 10,
    "what does the company actually do?": 20,
    "where does the money actually come from?": 30,
    "major customers": 40,
    "ipo details": 50,
    "where is the ipo money going?": 60,
    "who is selling and why?": 70,
    "financial health": 80,
    "is the profit real cash?": 90,
    "business quality": 100,
    "management & promoters": 110,
    "recent problems or important developments": 120,
    "future plans": 130,
    "competition": 140,
    "valuation": 150,
    "important red flags": 160,
    "top risks": 170,
    "current market sentiment": 180,
}
LOGGER = logging.getLogger(__name__)


class PDFReportGenerator:
    def __init__(self, template_path: Path, report_dir: Path) -> None:
        self.template_path = template_path
        self.report_dir = report_dir
        self.environment = Environment(
            loader=FileSystemLoader(str(template_path.parent)),
            autoescape=select_autoescape(["html", "xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def generate(self, analysis: IPOAnalysis, evidence: IPOEvidence) -> Path:
        self.report_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{evidence.target_market_day.isoformat()}_{slugify(analysis.company_name)}.pdf"
        output_path = self.report_dir / filename

        try:
            template = self.environment.get_template(self.template_path.name)
            sections = sorted(
                analysis.sections,
                key=lambda section: SECTION_ORDER.get(section.title.strip().lower(), 999),
            )
            LOGGER.info(
                "PDF render started: company=%s, sections=%s, sources=%s, rhp_sections=%s, output=%s",
                analysis.company_name,
                len(sections),
                len(evidence.sources),
                len(evidence.rhp_sections),
                output_path,
            )
            html = template.render(
                analysis=analysis,
                evidence=evidence,
                sections=sections,
                source_map={source.id: source for source in evidence.sources},
                data_gaps=self._data_gaps(evidence, analysis),
            )
            HTML(string=html, base_url=str(self.template_path.parent)).write_pdf(str(output_path))
        except Exception as exc:
            raise PDFGenerationError(f"Failed to generate PDF: {exc}") from exc

        self._sanity_check(output_path, analysis.company_name, analysis.verdict.value)
        LOGGER.info("PDF render done: output=%s, size_bytes=%s", output_path, output_path.stat().st_size)
        return output_path

    @staticmethod
    def _sanity_check(path: Path, company_name: str, verdict: str) -> None:
        if not path.exists() or path.stat().st_size < 5_000:
            raise PDFGenerationError("Generated PDF is missing or unexpectedly small")
        content = path.read_bytes()
        if not content.startswith(b"%PDF"):
            raise PDFGenerationError("Generated report does not have a PDF signature")
        # Text-level semantic checks are covered by template input validation. The
        # rendered PDF is additionally visual-QA'd in the test/sample workflow.
        if not company_name or not verdict:
            raise PDFGenerationError("Report metadata was unexpectedly empty")

    @staticmethod
    def _data_gaps(evidence: IPOEvidence, analysis: IPOAnalysis) -> list[str]:
        labels: list[str] = []
        items = [*evidence.data_gaps, *analysis.data_gaps]
        for item in items:
            label = item.strip()
            if label and label not in labels:
                labels.append(label)
        return labels
