from __future__ import annotations

import logging
import time
from typing import Any

import requests


LOGGER = logging.getLogger(__name__)
TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}


class HttpClient:
    """Small requests wrapper with bounded retry for transient failures."""

    def __init__(self, timeout_seconds: int = 25, retries: int = 3) -> None:
        self.timeout_seconds = timeout_seconds
        self.retries = max(1, retries)
        self.session = requests.Session()

    def request(
        self,
        method: str,
        url: str,
        *,
        retry_statuses: set[int] | None = None,
        **kwargs: Any,
    ) -> requests.Response:
        retry_statuses = retry_statuses or TRANSIENT_STATUS_CODES
        last_error: Exception | None = None

        for attempt in range(1, self.retries + 1):
            try:
                response = self.session.request(
                    method,
                    url,
                    timeout=self.timeout_seconds,
                    **kwargs,
                )
                if response.status_code not in retry_statuses:
                    return response

                if attempt == self.retries:
                    return response

                wait_seconds = self._retry_delay(response, attempt)
                LOGGER.warning(
                    "Transient HTTP %s from %s; retrying in %.1fs (%s/%s)",
                    response.status_code,
                    url,
                    wait_seconds,
                    attempt,
                    self.retries,
                )
                time.sleep(wait_seconds)
            except requests.RequestException as exc:
                last_error = exc
                if attempt == self.retries:
                    raise
                wait_seconds = min(2 ** (attempt - 1), 8)
                LOGGER.warning(
                    "Request error for %s: %s; retrying in %ss (%s/%s)",
                    url,
                    exc,
                    wait_seconds,
                    attempt,
                    self.retries,
                )
                time.sleep(wait_seconds)

        if last_error:
            raise last_error
        raise RuntimeError("HTTP retry loop exited unexpectedly")

    def get_json(self, url: str, **kwargs: Any) -> Any:
        response = self.request("GET", url, **kwargs)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _retry_delay(response: requests.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return min(float(retry_after), 60.0)
            except ValueError:
                pass
        return float(min(2 ** (attempt - 1), 8))
