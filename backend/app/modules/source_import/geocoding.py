"""Coordinates for source addresses: Geoapify Geocoding or a dispatcher's manual review.

Only a confident building-level answer is written to the location. A weaker answer is
kept as a candidate for review: planning never routes to an unconfirmed point.
"""

from dataclasses import dataclass
from decimal import Decimal

import httpx

GEOCODE_URL = "https://api.geoapify.com/v1/geocode/search"
MIN_CONFIDENCE = Decimal("0.8")
PRECISE_TYPES = frozenset({"building", "amenity"})
MAX_ADDRESSES = 300


@dataclass(frozen=True)
class GeocodeResult:
    status: str  # geocoded | ambiguous | unresolved
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    confidence: Decimal | None = None
    error: str | None = None


class GeoapifyGeocoder:
    """Synchronous client; called before the import transaction starts."""

    def __init__(
        self,
        api_key: str,
        *,
        timeout_seconds: float = 10.0,
        url: str = GEOCODE_URL,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._timeout = timeout_seconds
        self._url = url
        self._transport = transport

    def geocode(self, addresses: list[str]) -> dict[str, GeocodeResult]:
        results: dict[str, GeocodeResult] = {}
        with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
            for text in addresses:
                results[text] = self._one(client, text)
        return results

    def _one(self, client: httpx.Client, text: str) -> GeocodeResult:
        params = {
            "text": text,
            "lang": "ru",
            "filter": "countrycode:ru",
            "format": "json",
            "limit": 1,
            "apiKey": self._api_key,
        }
        try:
            response = client.get(self._url, params=params)
        except httpx.HTTPError:
            return GeocodeResult("unresolved", error="geocoder_unavailable")
        if response.is_error:
            return GeocodeResult("unresolved", error=f"geocoder_http_{response.status_code}")
        try:
            results = response.json().get("results") or []
            if not results:
                return GeocodeResult("unresolved", error="not_found")
            best = results[0]
            latitude = Decimal(str(best["lat"])).quantize(Decimal("0.000001"))
            longitude = Decimal(str(best["lon"])).quantize(Decimal("0.000001"))
            confidence = Decimal(str(best.get("rank", {}).get("confidence", 0))).quantize(
                Decimal("0.001")
            )
        except (ValueError, KeyError, TypeError, ArithmeticError):
            return GeocodeResult("unresolved", error="geocoder_malformed")
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            return GeocodeResult("unresolved", error="geocoder_malformed")
        confident = confidence >= MIN_CONFIDENCE and best.get("result_type") in PRECISE_TYPES
        return GeocodeResult(
            "geocoded" if confident else "ambiguous",
            latitude,
            longitude,
            min(confidence, Decimal(1)),
        )
