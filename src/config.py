from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigurationError


ROOT_DIR = Path(__file__).resolve().parents[1]


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name, default)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _env_int(name: str, default: int) -> int:
    value = _env(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer, got: {value}") from exc


def _env_optional_int(name: str, default: int | None = None) -> int | None:
    value = _env(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer, got: {value}") from exc


def _env_float(name: str, default: float) -> float:
    value = _env(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a number, got: {value}") from exc


def _env_bool(name: str, default: bool) -> bool:
    value = _env(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class Settings:
    ipo_provider: str
    ipo_guru_api_key: str | None
    upstox_access_token: str | None

    openrouter_api_key: str | None
    openrouter_model: str
    openrouter_temperature: float
    openrouter_max_tokens: int
    openrouter_reasoning_effort: str | None
    openrouter_reasoning_max_tokens: int | None

    email_from: str | None
    email_to: tuple[str, ...]
    failure_to: tuple[str, ...]
    email_app_password: str | None
    smtp_host: str
    smtp_port: int

    processed_retention_days: int
    artifact_retention_days: int
    news_lookback_days: int
    news_max_events: int
    request_timeout_seconds: int
    request_retries: int
    dry_run: bool

    data_dir: Path
    report_dir: Path
    cache_dir: Path
    prompt_path: Path
    template_path: Path

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            ipo_provider=(_env("IPO_PROVIDER", "auto") or "auto").lower(),
            ipo_guru_api_key=_env("IPO_GURU_API_KEY"),
            upstox_access_token=_env("UPSTOX_ACCESS_TOKEN"),
            openrouter_api_key=_env("OPENROUTER_API_KEY"),
            openrouter_model=_env("OPENROUTER_MODEL", "openrouter/free") or "openrouter/free",
            openrouter_temperature=_env_float("OPENROUTER_TEMPERATURE", 0.1),
            openrouter_max_tokens=_env_int("OPENROUTER_MAX_TOKENS", 8000),
            openrouter_reasoning_effort=_env("OPENROUTER_REASONING_EFFORT", "low"),
            openrouter_reasoning_max_tokens=_env_optional_int("OPENROUTER_REASONING_MAX_TOKENS", 1024),
            email_from=_env("EMAIL_FROM"),
            email_to=_parse_recipients(_env("EMAIL_TO")),
            failure_to=_parse_recipients(_env("FAILURE_TO")),
            email_app_password=_env("EMAIL_APP_PASSWORD"),
            smtp_host=_env("SMTP_HOST", "smtp.gmail.com") or "smtp.gmail.com",
            smtp_port=_env_int("SMTP_PORT", 465),
            processed_retention_days=_env_int("PROCESSED_RETENTION_DAYS", 15),
            artifact_retention_days=_env_int("ARTIFACT_RETENTION_DAYS", 15),
            news_lookback_days=_env_int("NEWS_LOOKBACK_DAYS", 730),
            news_max_events=_env_int("NEWS_MAX_EVENTS", 10),
            request_timeout_seconds=_env_int("REQUEST_TIMEOUT_SECONDS", 25),
            request_retries=_env_int("REQUEST_RETRIES", 3),
            dry_run=_env_bool("DRY_RUN", False),
            data_dir=Path(_env("DATA_DIR", str(ROOT_DIR / "data")) or ROOT_DIR / "data"),
            report_dir=Path(_env("REPORT_DIR", str(ROOT_DIR / "reports")) or ROOT_DIR / "reports"),
            cache_dir=Path(_env("CACHE_DIR", str(ROOT_DIR / ".cache")) or ROOT_DIR / ".cache"),
            prompt_path=Path(_env("PROMPT_PATH", str(ROOT_DIR / "prompts" / "ipo_analyst.md")) or ROOT_DIR / "prompts" / "ipo_analyst.md"),
            template_path=Path(_env("REPORT_TEMPLATE_PATH", str(ROOT_DIR / "templates" / "report.html")) or ROOT_DIR / "templates" / "report.html"),
        )

    def validate_for_live_run(self) -> None:
        missing: list[str] = []

        if self.ipo_provider == "ipo_guru" and not self.ipo_guru_api_key:
            missing.append("IPO_GURU_API_KEY")
        if self.ipo_provider == "upstox" and not self.upstox_access_token:
            missing.append("UPSTOX_ACCESS_TOKEN")
        if not self.openrouter_api_key:
            missing.append("OPENROUTER_API_KEY")

        if not self.dry_run:
            if not self.email_from:
                missing.append("EMAIL_FROM")
            if not self.email_app_password:
                missing.append("EMAIL_APP_PASSWORD")
            if not self.email_to:
                missing.append("EMAIL_TO")
            if not self.failure_to:
                missing.append("FAILURE_TO")

        if not self.prompt_path.exists():
            missing.append(f"PROMPT_PATH({self.prompt_path})")
        if not self.template_path.exists():
            missing.append(f"REPORT_TEMPLATE_PATH({self.template_path})")

        if missing:
            raise ConfigurationError(
                "Missing required configuration: " + ", ".join(sorted(set(missing)))
            )


def _parse_recipients(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(part.strip() for part in value.split(",") if part.strip())
