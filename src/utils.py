from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path
from typing import Any


IST_TIMEZONE = "Asia/Kolkata"


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_value).strip("-").lower()
    return slug or "ipo"


def normalize_company_name(value: str) -> str:
    text = value.lower()
    replacements = {
        "limited": "",
        "ltd": "",
        "private": "",
        "pvt": "",
        "the": "",
        "ipo": "",
    }
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    words = [word for word in text.split() if word not in replacements]
    return " ".join(words)


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def sha256_json(data: Any) -> str:
    return hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest()


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None

    formats = (
        "%Y-%m-%d",
        "%d-%b-%Y",
        "%d-%B-%Y",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%d %b %Y",
        "%d %B %Y",
    )
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text or text.lower() in {"na", "n/a", "null", "none", "-", "--"}:
        return None
    cleaned = re.sub(r"[^0-9.\-]", "", text.replace(",", ""))
    if cleaned in {"", "-", ".", "-."}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_crore(value: Any) -> float | None:
    """Parse values such as '₹1,250 Cr' into crore units."""
    return parse_float(value)


def parse_price_band(value: Any) -> tuple[float | None, float | None]:
    if value is None:
        return None, None
    if isinstance(value, (int, float)):
        number = float(value)
        return number, number
    numbers = re.findall(r"\d+(?:\.\d+)?", str(value).replace(",", ""))
    if not numbers:
        return None, None
    if len(numbers) == 1:
        number = float(numbers[0])
        return number, number
    return float(numbers[0]), float(numbers[1])
