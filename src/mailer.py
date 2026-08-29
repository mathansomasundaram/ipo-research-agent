from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Iterable

from .errors import EmailError
from .models import IPOAnalysis, IPORecord


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class SuccessfulReport:
    ipo: IPORecord
    analysis: IPOAnalysis
    pdf_path: Path
    evidence_hash: str


@dataclass(frozen=True)
class FailedIPO:
    ipo: IPORecord | None
    stage: str
    error: str


class GmailMailer:
    def __init__(
        self,
        sender: str,
        app_password: str,
        smtp_host: str = "smtp.gmail.com",
        smtp_port: int = 465,
    ) -> None:
        self.sender = sender
        self.app_password = app_password
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port

    def send_daily_summary(
        self,
        recipients: Iterable[str],
        target_market_day,
        successes: list[SuccessfulReport],
        failures: list[FailedIPO],
    ) -> None:
        recipients = list(recipients)
        if not recipients:
            raise EmailError("EMAIL_TO is empty")

        subject = self._daily_subject(target_market_day, successes, failures)
        body = self._daily_body(target_market_day, successes, failures)
        message = self._message(recipients, subject, body)
        LOGGER.info(
            "Preparing daily email: recipients=%s, successes=%s, failures=%s, subject=%s",
            len(recipients),
            len(successes),
            len(failures),
            subject,
        )

        for success in successes:
            pdf_bytes = success.pdf_path.read_bytes()
            LOGGER.info("Attaching PDF: file=%s, size_bytes=%s", success.pdf_path.name, len(pdf_bytes))
            message.add_attachment(
                pdf_bytes,
                maintype="application",
                subtype="pdf",
                filename=success.pdf_path.name,
            )
        self._send(message)

    def send_failure_alert(
        self,
        recipients: Iterable[str],
        subject: str,
        body: str,
    ) -> None:
        recipients = list(recipients)
        if not recipients:
            LOGGER.error("FAILURE_TO is empty; failure alert could not be sent: %s", body)
            return
        LOGGER.info("Preparing failure alert email: recipients=%s, subject=%s", len(recipients), subject)
        self._send(self._message(recipients, subject, body))

    def _send(self, message: EmailMessage) -> None:
        try:
            LOGGER.info("SMTP send started: host=%s, port=%s", self.smtp_host, self.smtp_port)
            with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=30) as server:
                server.login(self.sender, self.app_password)
                server.send_message(message)
            LOGGER.info("SMTP send completed")
        except Exception as exc:
            raise EmailError(f"SMTP delivery failed: {exc}") from exc

    def _message(self, recipients: list[str], subject: str, body: str) -> EmailMessage:
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = ", ".join(recipients)
        message["Subject"] = subject
        message.set_content(body)
        return message

    @staticmethod
    def _daily_subject(target_market_day, successes: list[SuccessfulReport], failures: list[FailedIPO]) -> str:
        total = len(successes) + len(failures)
        noun = "IPO" if total == 1 else "IPOs"
        return f"{total} {noun} for {target_market_day.isoformat()} - IPO Analysis"

    @staticmethod
    def _daily_body(target_market_day, successes: list[SuccessfulReport], failures: list[FailedIPO]) -> str:
        lines = [
            f"IPO analysis for next market day: {target_market_day.isoformat()}",
            "",
        ]
        if successes:
            lines.append("Successfully analysed:")
            for item in successes:
                lines.append(
                    f"- {item.ipo.name}: {item.analysis.verdict.value} "
                    f"(confidence {item.analysis.confidence.value})"
                )
            lines.append("")

        if failures:
            lines.append("Could not analyse:")
            for failure in failures:
                name = failure.ipo.name if failure.ipo else "Pipeline"
                lines.append(f"- {name} | stage={failure.stage} | {failure.error}")
            lines.append("")

        if successes:
            lines.append("Detailed PDF reports are attached.")
        lines.extend(
            [
                "",
                "This is research synthesis for educational purposes, not personalized investment advice.",
            ]
        )
        return "\n".join(lines)
