from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from ..models import FinancialPeriod, RHPSection
from ..utils import parse_float


YEAR_RE = re.compile(r"(?:FY\s*)?(20\d{2})", re.IGNORECASE)
NUMBER_RE = re.compile(r"-?\(?\d[\d,]*(?:\.\d+)?\)?")


@dataclass(frozen=True)
class MetricPattern:
    field: str
    patterns: tuple[str, ...]


METRICS: tuple[MetricPattern, ...] = (
    MetricPattern("revenue_cr", ("revenue from operations", "revenue from operation", "total income")),
    MetricPattern("ebitda_cr", ("ebitda",)),
    MetricPattern("pat_cr", ("profit for the year", "profit after tax", "net profit after tax")),
    MetricPattern(
        "operating_cash_flow_cr",
        (
            "net cash generated from operating activities",
            "net cash from operating activities",
            "cash flow from operating activities",
        ),
    ),
    MetricPattern("debt_cr", ("total borrowings", "total borrowing")),
    MetricPattern("equity_cr", ("total equity", "net worth")),
    MetricPattern("receivables_cr", ("trade receivables", "trade receivable")),
    MetricPattern("inventory_cr", ("inventories", "inventory")),
)


class FinancialExtractor:
    """Best-effort deterministic extraction from the selected RHP financial text.

    It intentionally returns an empty list when the layout is ambiguous instead of
    forcing numbers into the wrong periods. The LLM still receives the original
    financial section as evidence.
    """

    def extract(self, sections: list[RHPSection]) -> tuple[list[FinancialPeriod], list[str]]:
        section = next((item for item in sections if item.id.endswith("#financial_information")), None)
        if section is None:
            return [], ["Structured financial extraction unavailable: financial section not located."]

        lines = [self._clean_line(line) for line in section.text.splitlines() if line.strip()]
        years, header_index = self._find_year_header(lines)
        if len(years) < 3:
            return [], ["Structured financial extraction skipped: fiscal-year header was ambiguous."]

        unit_multiplier = self._unit_to_crore_multiplier(lines, header_index)
        values_by_metric: dict[str, list[float | None]] = {}
        warnings: list[str] = []

        for metric in METRICS:
            values = self._find_metric_values(lines, metric.patterns, len(years), header_index)
            if values:
                values_by_metric[metric.field] = [
                    value * unit_multiplier if value is not None else None for value in values
                ]

        if "revenue_cr" not in values_by_metric or "pat_cr" not in values_by_metric:
            return [], [
                "Structured financial extraction skipped because core Revenue/PAT rows could not be mapped confidently."
            ]

        periods: list[FinancialPeriod] = []
        for index, year in enumerate(years):
            kwargs = {
                field: values[index] if index < len(values) else None
                for field, values in values_by_metric.items()
            }
            periods.append(FinancialPeriod(period=f"FY{str(year)[-2:]}", **kwargs))

        if unit_multiplier != 1.0:
            warnings.append(
                f"Financial table values were normalized to ₹ crore using multiplier {unit_multiplier}."
            )
        return periods, warnings

    @staticmethod
    def _find_year_header(lines: list[str]) -> tuple[list[int], int]:
        best: tuple[list[int], int] = ([], 0)
        for index, line in enumerate(lines[:500]):
            years = [int(match) for match in YEAR_RE.findall(line)]
            years = _unique_preserving_order(years)
            if len(years) >= 3 and len(years) > len(best[0]):
                best = (years[:4], index)
        return best

    @staticmethod
    def _unit_to_crore_multiplier(lines: list[str], header_index: int) -> float:
        window = " ".join(lines[max(0, header_index - 60) : header_index + 120]).lower()
        section_intro = " ".join(lines).lower()
        unit_text = f"{window} {section_intro}"
        if (
            "in million" in unit_text
            or "₹ in million" in unit_text
            or "rs. in million" in unit_text
            or "rs in million" in unit_text
        ):
            return 0.1
        if "in lakh" in unit_text or "in lakhs" in unit_text:
            return 0.01
        if "in crore" in unit_text or "in crores" in unit_text:
            return 1.0
        # Many Indian RHP summary tables are in ₹ million. Without a clear unit,
        # do not silently convert; leave the values as-is and let the data gap be visible.
        return 1.0

    def _find_metric_values(
        self,
        lines: list[str],
        patterns: Iterable[str],
        year_count: int,
        header_index: int,
    ) -> list[float | None] | None:
        candidates: list[tuple[int, list[float | None]]] = []
        lower_patterns = tuple(pattern.lower() for pattern in patterns)

        for index, line in enumerate(lines):
            lower = line.lower()
            if not any(pattern in lower for pattern in lower_patterns):
                continue

            numbers = self._extract_numbers(line)
            if len(numbers) < year_count:
                combined = " ".join(lines[index : min(index + 3, len(lines))])
                numbers = self._extract_numbers(combined)
            if len(numbers) < year_count:
                continue

            # Prefer rows after the detected year header and rows with exactly the
            # expected number of period values.
            score = 0
            if index >= header_index:
                score += 3
            if len(numbers) == year_count:
                score += 2
            candidates.append((score, numbers[-year_count:]))

        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    @staticmethod
    def _extract_numbers(text: str) -> list[float | None]:
        values: list[float | None] = []
        for token in NUMBER_RE.findall(text):
            negative = token.startswith("(") and token.endswith(")")
            cleaned = token.strip("()").replace(",", "")
            value = parse_float(cleaned)
            if value is not None and negative:
                value = -value
            if value is not None:
                values.append(value)
        return values

    @staticmethod
    def _clean_line(line: str) -> str:
        return re.sub(r"\s+", " ", line).strip()


def _unique_preserving_order(values: list[int]) -> list[int]:
    result: list[int] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result
