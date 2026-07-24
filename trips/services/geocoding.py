"""
Geocoding via LocationIQ (OpenStreetMap-based, free tier: 5,000 req/day).
Avoids the IP-level 403 blocks that Nominatim's public instance imposes
on shared/dev IPs, which is why this replaces the raw Nominatim call.

Sign up for a free key at https://locationiq.com/
"""
import requests
from django.conf import settings

LOCATIONIQ_URL = "https://us1.locationiq.com/v1/search"

_cache: dict[str, dict] = {}


class GeocodingError(Exception):
    pass


def geocode(place_name: str) -> dict:
    """Return {'lat': float, 'lon': float, 'display_name': str} for a place name."""
    key = place_name.strip().lower()
    if key in _cache:
        return _cache[key]

    if not settings.LOCATIONIQ_API_KEY:
        raise GeocodingError(
            "LOCATIONIQ_API_KEY is not set. Get a free key at https://locationiq.com/"
        )

    try:
        resp = requests.get(
            LOCATIONIQ_URL,
            params={
                "key": settings.LOCATIONIQ_API_KEY,
                "q": place_name,
                "format": "json",
                "limit": 1,
            },
            timeout=10,
        )
    except requests.RequestException as e:
        raise GeocodingError(f"Network error while geocoding '{place_name}': {e}") from e

    if resp.status_code == 404:
        # LocationIQ returns 404 when no results are found, not an error
        raise GeocodingError(f"Could not find a location matching '{place_name}'")

    try:
        resp.raise_for_status()
    except requests.HTTPError as e:
        raise GeocodingError(
            f"Geocoding service error while looking up '{place_name}': {e}"
        ) from e

    results = resp.json()
    if not results:
        raise GeocodingError(f"Could not find a location matching '{place_name}'")

    top = results[0]
    result = {
        "lat": float(top["lat"]),
        "lon": float(top["lon"]),
        "display_name": top.get("display_name", place_name),
    }
    _cache[key] = result
    return result