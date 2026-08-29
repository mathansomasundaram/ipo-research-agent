from __future__ import annotations

from ..config import Settings
from ..errors import ConfigurationError
from ..http_client import HttpClient
from .base import IPOProvider
from .ipo_guru import IPOGuruProvider
from .nse import NSEClient, NSEProvider
from .test_data import TestDataProvider
from .upstox import UpstoxProvider


def build_ipo_provider(settings: Settings, http: HttpClient) -> IPOProvider:
    provider = settings.ipo_provider

    if provider == "auto":
        if settings.ipo_guru_api_key:
            return IPOGuruProvider(settings.ipo_guru_api_key, http)
        return NSEProvider(NSEClient(http))

    if provider == "ipo_guru":
        if not settings.ipo_guru_api_key:
            raise ConfigurationError("IPO_PROVIDER=ipo_guru requires IPO_GURU_API_KEY")
        return IPOGuruProvider(settings.ipo_guru_api_key, http)

    if provider == "upstox":
        if not settings.upstox_access_token:
            raise ConfigurationError("IPO_PROVIDER=upstox requires UPSTOX_ACCESS_TOKEN")
        return UpstoxProvider(settings.upstox_access_token, http)

    if provider == "nse":
        return NSEProvider(NSEClient(http))

    if provider == "test_data":
        return TestDataProvider()

    raise ConfigurationError(
        f"Unsupported IPO_PROVIDER={provider!r}. Use auto, ipo_guru, upstox, nse, or test_data."
    )
