"""
Free driving-route lookups via the public OSRM demo server.
Good for development. For production, self-host OSRM or swap in a
commercial provider (Mapbox, Google, ORS) behind the same interface.
"""
import requests

OSRM_BASE_URL = "https://router.project-osrm.org"


class RoutingError(Exception):
    pass


def route_multi_stop(coords: list[tuple[float, float]]) -> dict:
    """
    coords: list of (lat, lon) in visiting order, e.g. [current, pickup, dropoff].
    Returns per-leg distance/duration plus the full route geometry.
    """
    coord_str = ";".join(f"{lon},{lat}" for lat, lon in coords)
    url = f"{OSRM_BASE_URL}/route/v1/driving/{coord_str}"
    resp = requests.get(
        url,
        params={"overview": "full", "geometries": "geojson", "steps": "false"},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    if data.get("code") != "Ok" or not data.get("routes"):
        raise RoutingError(f"OSRM could not compute a route ({data.get('code', 'unknown error')})")

    route = data["routes"][0]
    legs = []
    for leg in route["legs"]:
        legs.append({
            "distance_miles": leg["distance"] / 1609.34,
            "duration_hours": leg["duration"] / 3600,
        })

    return {
        "legs": legs,
        "total_distance_miles": route["distance"] / 1609.34,
        "total_duration_hours": route["duration"] / 3600,
        "geometry": route["geometry"],  # GeoJSON LineString {type, coordinates: [[lon,lat],...]}
    }
