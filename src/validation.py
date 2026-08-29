from __future__ import annotations

from .errors import EvidenceValidationError
from .models import Confidence, IPOAnalysis, IPOEvidence, Verdict


class EvidenceValidator:
    """Hard gate before spending an LLM call."""

    def validate(self, evidence: IPOEvidence) -> None:
        missing: list[str] = []
        ipo = evidence.ipo

        if not ipo.name:
            missing.append("company name")
        if ipo.open_date != evidence.target_market_day:
            missing.append("opening date does not match target market day")
        if ipo.price_max is None and ipo.issue_price is None:
            missing.append("price band / issue price")
        if ipo.issue_size_cr is None:
            missing.append("issue size")
        if not evidence.rhp_sections:
            missing.append("RHP/DRHP evidence")
        else:
            section_ids = {section.id.split("#")[-1] for section in evidence.rhp_sections}
            if "business" not in section_ids:
                missing.append("RHP business section")
            if "financial_information" not in section_ids:
                missing.append("RHP financial information section")
            if "risk_factors" not in section_ids:
                missing.append("RHP risk factors section")

        if missing:
            raise EvidenceValidationError(
                "Critical evidence is missing: " + ", ".join(missing)
            )


class AnalysisValidator:
    """Small deterministic sanity layer; it does not replace analyst reasoning."""

    def validate(self, analysis: IPOAnalysis, evidence: IPOEvidence) -> None:
        errors: list[str] = []

        if analysis.verdict == Verdict.APPLY and analysis.confidence == Confidence.LOW:
            errors.append("LOW-confidence analysis cannot automatically return APPLY")

        if analysis.verdict == Verdict.APPLY and evidence.data_gaps:
            critical_gaps = [gap for gap in evidence.data_gaps if "financial" in gap.lower()]
            if critical_gaps:
                errors.append("APPLY is not allowed while core financial evidence remains a data gap")

        valuation_text = " ".join(
            [analysis.scorecard.valuation]
            + [section.summary for section in analysis.sections if "valuation" in section.title.lower()]
        ).lower()
        if "reasonable" in valuation_text and evidence.ipo.price_max is None:
            errors.append("Valuation cannot be labelled reasonable without an IPO price")

        known_evidence_ids = {source.id for source in evidence.sources}
        known_evidence_ids.update(section.id for section in evidence.rhp_sections)
        for section in analysis.sections:
            unknown = set(section.evidence_ids) - known_evidence_ids
            if unknown:
                errors.append(
                    f"Section {section.title!r} cites unknown evidence IDs: {sorted(unknown)}"
                )
        for risk in analysis.risks:
            unknown = set(risk.evidence_ids) - known_evidence_ids
            if unknown:
                errors.append(f"Risk {risk.title!r} cites unknown evidence IDs: {sorted(unknown)}")
        for flag in analysis.red_flags:
            unknown = set(flag.evidence_ids) - known_evidence_ids
            if unknown:
                errors.append(f"Red flag {flag.issue!r} cites unknown evidence IDs: {sorted(unknown)}")

        if errors:
            raise EvidenceValidationError("Analysis validation failed: " + " | ".join(errors))
