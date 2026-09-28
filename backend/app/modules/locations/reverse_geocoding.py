"""Reverse-geocode stored coordinates to the district name supplied by Geoapify."""

from dataclasses import dataclass
from decimal import Decimal

import httpx

REVERSE_GEOCODE_URL = "https://api.geoapify.com/v1/geocode/reverse"


@dataclass(frozen=True)
class ReverseGeocodeResult:
    city: str | None
    district: str | None


class GeoapifyReverseGeocoder:
    """Synchronous Geoapify boundary; callers decide how to handle an unresolved lookup."""

    def __init__(
        self,
        api_key: str,
        *,
        timeout_seconds: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    def reverse_geocode(
        self, *, latitude: Decimal | float, longitude: Decimal | float
    ) -> ReverseGeocodeResult | None:
        params = {
            "lat": str(latitude),
            "lon": str(longitude),
            "lang": "ru",
            "format": "json",
            "apiKey": self._api_key,
        }
        try:
            with httpx.Client(timeout=self._timeout_seconds, transport=self._transport) as client:
                response = client.get(REVERSE_GEOCODE_URL, params=params)
        except httpx.HTTPError:
            return None
        if response.is_error:
            return None

        try:
            payload = response.json()
            results = payload.get("results") or []
            if not results:
                features = payload.get("features") or []
                results = [feature.get("properties", {}) for feature in features]
            if not results or not isinstance(results[0], dict):
                return None
            result = results[0]
        except (ValueError, TypeError, AttributeError):
            return None

        city = _first_text(result, "city", "town", "municipality")
        district = _first_text(result, "district", "city_district", "suburb")
        return ReverseGeocodeResult(city=city, district=district)


def _first_text(values: dict, *keys: str) -> str | None:
    for key in keys:
        value = values.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
