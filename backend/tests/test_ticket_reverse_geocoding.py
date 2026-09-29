"""Reverse geocoding used to resolve ticket service areas."""

import unittest
from urllib.parse import parse_qs, urlparse

import httpx

from app.modules.locations.reverse_geocoding import GeoapifyReverseGeocoder


class GeoapifyReverseGeocoderTests(unittest.TestCase):
    def test_reverse_lookup_uses_latitude_and_longitude_and_returns_district(self):
        seen = []

        def respond(request):
            seen.append(request)
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "city": "Москва",
                            "district": "Кузьминки",
                            "suburb": "Кузьминки",
                        }
                    ]
                },
            )

        geocoder = GeoapifyReverseGeocoder("test-key", transport=httpx.MockTransport(respond))

        result = geocoder.reverse_geocode(latitude=55.700654, longitude=37.759714)

        self.assertEqual(result.city, "Москва")
        self.assertEqual(result.district, "Кузьминки")
        query = parse_qs(urlparse(str(seen[0].url)).query)
        self.assertEqual(query["lat"], ["55.700654"])
        self.assertEqual(query["lon"], ["37.759714"])
        self.assertEqual(query["apiKey"], ["test-key"])

    def test_reverse_lookup_keeps_missing_district_unresolved(self):
        geocoder = GeoapifyReverseGeocoder(
            "test-key",
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json={"results": [{"city": "Москва"}]})
            ),
        )

        result = geocoder.reverse_geocode(latitude=55.700654, longitude=37.759714)

        self.assertEqual(result.city, "Москва")
        self.assertIsNone(result.district)

    def test_reverse_lookup_returns_none_for_not_found_and_upstream_failure(self):
        for response in (
            httpx.Response(200, json={"results": []}),
            httpx.Response(503),
        ):
            with self.subTest(status=response.status_code):
                geocoder = GeoapifyReverseGeocoder(
                    "test-key", transport=httpx.MockTransport(lambda _, response=response: response)
                )
                self.assertIsNone(geocoder.reverse_geocode(latitude=55.700654, longitude=37.759714))


if __name__ == "__main__":
    unittest.main()
