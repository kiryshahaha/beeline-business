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
                            "city": "Санкт-Петербург",
                            "district": "Невский район",
                            "suburb": "Невский район",
                        }
                    ]
                },
            )

        geocoder = GeoapifyReverseGeocoder("test-key", transport=httpx.MockTransport(respond))

        result = geocoder.reverse_geocode(latitude=59.94, longitude=30.32)

        self.assertEqual(result.city, "Санкт-Петербург")
        self.assertEqual(result.district, "Невский район")
        query = parse_qs(urlparse(str(seen[0].url)).query)
        self.assertEqual(query["lat"], ["59.94"])
        self.assertEqual(query["lon"], ["30.32"])
        self.assertEqual(query["apiKey"], ["test-key"])

    def test_reverse_lookup_keeps_missing_district_unresolved(self):
        geocoder = GeoapifyReverseGeocoder(
            "test-key",
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json={"results": [{"city": "Санкт-Петербург"}]})
            ),
        )

        result = geocoder.reverse_geocode(latitude=59.94, longitude=30.32)

        self.assertEqual(result.city, "Санкт-Петербург")
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
                self.assertIsNone(geocoder.reverse_geocode(latitude=59.94, longitude=30.32))


if __name__ == "__main__":
    unittest.main()
