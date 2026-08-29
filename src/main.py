from __future__ import annotations

import argparse
from contextlib import contextmanager
import logging
import sys
from time import perf_counter
from datetime import date, datetime, time
from typing import Iterator
from zoneinfo import ZoneInfo

from .collectors.financials import FinancialExtractor
from .collectors.news import GoogleNewsCollector
from .collectors.prospectus import ProspectusCollector, RHPSectionExtractor
from .config import Settings
from .errors import IPOAgentError
from .evidence import EvidenceCollector
from .exchange_verifier import NSEIPOVerifier
from .http_client import HttpClient
from .llm import OpenRouterAnalyst
from .mailer import FailedIPO, GmailMailer, SuccessfulReport
from .market_calendar import NSEMarketCalendar
from .pdf_report import PDFReportGenerator
from .providers.factory import build_ipo_provider
from .providers.nse import NSEClient
from .state import ProcessedIPOStore
from .utils import sha256_json
from .validation import AnalysisValidator, EvidenceValidator


LOGGER = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")


def run(today_override: date | None = None, force_dry_run: bool = False) -> int:
    LOGGER.info("Pipeline started")
    settings = Settings.from_env()
    if force_dry_run:
        settings = Settings(**{**settings.__dict__, "dry_run": True})
    settings.validate_for_live_run()
    LOGGER.info(
        "Configuration loaded: provider=%s, dry_run=%s, model=%s, max_tokens=%s, news_lookback_days=%s, news_max_events=%s",
        settings.ipo_provider,
        settings.dry_run,
        settings.openrouter_model,
        settings.openrouter_max_tokens,
        settings.news_lookback_days,
        settings.news_max_events,
    )

    now = _run_time(today_override)
    LOGGER.info("Run timestamp: %s; today_override=%s", now.isoformat(), today_override)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.report_dir.mkdir(parents=True, exist_ok=True)
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    LOGGER.info(
        "Runtime directories ready: data_dir=%s, report_dir=%s, cache_dir=%s",
        settings.data_dir,
        settings.report_dir,
        settings.cache_dir,
    )

    state = ProcessedIPOStore(
        settings.data_dir / "processed_ipos.json",
        retention_days=settings.processed_retention_days,
    )
    with timed_step("state cleanup"):
        removed = state.cleanup(now)
    if removed:
        LOGGER.info("Removed %s processed IPO records older than %s days", removed, settings.processed_retention_days)

    http = HttpClient(
        timeout_seconds=settings.request_timeout_seconds,
        retries=settings.request_retries,
    )
    nse = NSEClient(http)
    calendar = NSEMarketCalendar(nse, settings.data_dir)
    with timed_step("market calendar"):
        target_market_day = calendar.next_market_day(now.date())
    LOGGER.info("Next NSE market day is %s", target_market_day)

    provider = build_ipo_provider(settings, http)
    LOGGER.info("Using IPO provider: %s", provider.name)
    with timed_step(f"IPO discovery for {target_market_day}"):
        candidates = provider.get_ipos_opening_on(target_market_day, include_sme=False)
    LOGGER.info("IPO discovery found %s mainboard candidate(s)", len(candidates))

    if not candidates:
        LOGGER.info("No mainboard IPO opens on %s. No email will be sent.", target_market_day)
        LOGGER.info("Pipeline completed: successes=0, failures=0")
        return 0

    mailer = _build_mailer(settings)
    evidence_collector = EvidenceCollector(
        verifier=NSEIPOVerifier(nse),
        prospectus_collector=ProspectusCollector(http, settings.cache_dir),
        section_extractor=RHPSectionExtractor(),
        financial_extractor=FinancialExtractor(),
        news_collector=GoogleNewsCollector(
            http,
            lookback_days=settings.news_lookback_days,
            max_events=settings.news_max_events,
        ),
    )
    analyst = OpenRouterAnalyst(
        http=http,
        api_key=settings.openrouter_api_key or "",
        model=settings.openrouter_model,
        prompt_path=settings.prompt_path,
        temperature=settings.openrouter_temperature,
        max_tokens=settings.openrouter_max_tokens,
        reasoning_effort=settings.openrouter_reasoning_effort,
        reasoning_max_tokens=settings.openrouter_reasoning_max_tokens,
    )
    pdf_generator = PDFReportGenerator(settings.template_path, settings.report_dir)
    evidence_validator = EvidenceValidator()
    analysis_validator = AnalysisValidator()

    successes: list[SuccessfulReport] = []
    failures: list[FailedIPO] = []

    for ipo in candidates:
        if state.should_skip(ipo.stable_id):
            LOGGER.info("Skipping %s because it was already emailed", ipo.name)
            continue

        LOGGER.info("Processing IPO: name=%s, stable_id=%s, provider_id=%s", ipo.name, ipo.stable_id, ipo.provider_id)
        stage = "EVIDENCE_COLLECTION"
        try:
            with timed_step(f"{ipo.name} | {stage}"):
                evidence = evidence_collector.collect(ipo, target_market_day, now)
            LOGGER.info(
                "%s evidence collected: sources=%s, rhp_sections=%s, financial_rows=%s, news_events=%s, data_gaps=%s, warnings=%s",
                ipo.name,
                len(evidence.sources),
                len(evidence.rhp_sections),
                len(evidence.financials),
                len(evidence.news_events),
                len(evidence.data_gaps),
                len(evidence.warnings),
            )
            stage = "EVIDENCE_VALIDATION"
            with timed_step(f"{ipo.name} | {stage}"):
                evidence_validator.validate(evidence)

            evidence_hash = sha256_json(evidence.model_dump(mode="json"))
            LOGGER.info("%s evidence hash: %s", ipo.name, evidence_hash)
            stage = "LLM_ANALYSIS"
            with timed_step(f"{ipo.name} | {stage}"):
                analysis = analyst.analyze(evidence)
            LOGGER.info(
                "%s LLM analysis complete: verdict=%s, confidence=%s, sections=%s, risks=%s, red_flags=%s",
                ipo.name,
                analysis.verdict.value,
                analysis.confidence.value,
                len(analysis.sections),
                len(analysis.risks),
                len(analysis.red_flags),
            )
            stage = "ANALYSIS_VALIDATION"
            with timed_step(f"{ipo.name} | {stage}"):
                analysis_validator.validate(analysis, evidence)

            stage = "PDF_GENERATION"
            with timed_step(f"{ipo.name} | {stage}"):
                pdf_path = pdf_generator.generate(analysis, evidence)
            LOGGER.info("%s PDF generated: %s", ipo.name, pdf_path)
            successes.append(
                SuccessfulReport(
                    ipo=evidence.ipo,
                    analysis=analysis,
                    pdf_path=pdf_path,
                    evidence_hash=evidence_hash,
                )
            )
        except Exception as exc:
            LOGGER.exception("%s failed at %s", ipo.name, stage)
            failure = FailedIPO(ipo=ipo, stage=stage, error=_short_error(exc))
            failures.append(failure)
            if not settings.dry_run:
                with timed_step(f"{ipo.name} | STATE_MARK_FAILED"):
                    state.mark(
                        ipo.stable_id,
                        "FAILED",
                        now,
                        stage=stage,
                        error=_short_error(exc),
                    )

    if settings.dry_run:
        _print_dry_run_summary(target_market_day, successes, failures)
        LOGGER.info("Pipeline completed: dry_run=true, successes=%s, failures=%s", len(successes), len(failures))
        return 0 if successes else 1

    if not successes and not failures:
        LOGGER.info("All matching IPOs were already processed. No email will be sent.")
        return 0

    try:
        with timed_step("daily email delivery"):
            mailer.send_daily_summary(
                settings.email_to,
                target_market_day,
                successes,
                failures,
            )
        LOGGER.info("Daily summary email sent: recipients=%s, attachments=%s", len(settings.email_to), len(successes))
    except Exception as exc:
        _safe_failure_alert(
            mailer,
            settings.failure_to,
            "IPO Agent: daily email delivery failed",
            f"Target market day: {target_market_day}\nError: {_short_error(exc)}",
        )
        raise

    for success in successes:
        with timed_step(f"{success.ipo.name} | STATE_MARK_EMAIL_SENT"):
            state.mark(
                success.ipo.stable_id,
                "EMAIL_SENT",
                now,
                verdict=success.analysis.verdict.value,
                confidence=success.analysis.confidence.value,
                evidence_hash=success.evidence_hash,
                report_file=success.pdf_path.name,
            )

    if failures:
        failure_body = _failure_body(target_market_day, failures)
        with timed_step("failure alert delivery"):
            _safe_failure_alert(
                mailer,
                settings.failure_to,
                f"IPO Agent: {len(failures)} IPO processing failure(s)",
                failure_body,
            )

    # Partial failures do not fail the workflow because successful reports were
    # still delivered. If every IPO failed, mark the workflow failed after alerts.
    LOGGER.info("Pipeline completed: successes=%s, failures=%s", len(successes), len(failures))
    return 0 if successes else 1


@contextmanager
def timed_step(name: str) -> Iterator[None]:
    start = perf_counter()
    LOGGER.info("START %s", name)
    try:
        yield
    except Exception:
        LOGGER.exception("FAILED %s after %.2fs", name, perf_counter() - start)
        raise
    LOGGER.info("DONE %s in %.2fs", name, perf_counter() - start)


def _build_mailer(settings: Settings) -> GmailMailer:
    return GmailMailer(
        sender=settings.email_from or "",
        app_password=settings.email_app_password or "",
        smtp_host=settings.smtp_host,
        smtp_port=settings.smtp_port,
    )


def _run_time(today_override: date | None) -> datetime:
    if today_override is None:
        return datetime.now(IST)
    return datetime.combine(today_override, time(hour=18), tzinfo=IST)


def _short_error(exc: Exception) -> str:
    text = str(exc).replace("\n", " ").strip()
    return text[:700] or exc.__class__.__name__


def _failure_body(target_market_day: date, failures: list[FailedIPO]) -> str:
    lines = [f"Target market day: {target_market_day}", ""]
    for failure in failures:
        name = failure.ipo.name if failure.ipo else "Pipeline"
        lines.append(f"{name}\nStage: {failure.stage}\nError: {failure.error}\n")
    return "\n".join(lines)


def _safe_failure_alert(
    mailer: GmailMailer,
    recipients: tuple[str, ...],
    subject: str,
    body: str,
) -> None:
    try:
        mailer.send_failure_alert(recipients, subject, body)
    except Exception:
        LOGGER.exception("Failure alert could not be delivered")


def _print_dry_run_summary(
    target_market_day: date,
    successes: list[SuccessfulReport],
    failures: list[FailedIPO],
) -> None:
    print(f"Dry run for market day {target_market_day}")
    for success in successes:
        print(f"OK   {success.ipo.name}: {success.analysis.verdict.value} -> {success.pdf_path}")
    for failure in failures:
        name = failure.ipo.name if failure.ipo else "Pipeline"
        print(f"FAIL {name}: {failure.stage}: {failure.error}")



def _notify_top_level_failure(exc: Exception) -> None:
    """Best-effort failure notification for calendar/discovery/config/runtime failures."""
    try:
        settings = Settings.from_env()
        if settings.dry_run:
            return
        if not (settings.email_from and settings.email_app_password and settings.failure_to):
            return
        mailer = _build_mailer(settings)
        mailer.send_failure_alert(
            settings.failure_to,
            "IPO Agent: pipeline failure",
            f"The daily IPO pipeline failed before completion.\n\nError: {_short_error(exc)}",
        )
    except Exception:
        LOGGER.exception("Top-level failure alert could not be delivered")

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Daily Indian IPO research agent")
    parser.add_argument(
        "--today",
        help="Override today's IST date for testing (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate reports but do not send email or persist successful state",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    args = parse_args(argv)
    today_override = date.fromisoformat(args.today) if args.today else None

    try:
        return run(today_override=today_override, force_dry_run=args.dry_run)
    except IPOAgentError as exc:
        LOGGER.error("Pipeline failed: %s", exc)
        _notify_top_level_failure(exc)
        return 1
    except Exception as exc:
        LOGGER.exception("Unexpected pipeline failure")
        _notify_top_level_failure(exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
