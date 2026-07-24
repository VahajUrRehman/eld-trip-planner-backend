from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .serializers import TripRequestSerializer
from .services.geocoding import geocode, GeocodingError
from .services.routing import route_multi_stop, RoutingError
from .services.hos import simulate, segments_to_daily_logs, Leg


class PlanTripView(APIView):
    """
    POST /api/trip/plan/

    Body (matches TripFormData from the React form):
    {
        "currentLocation": "Chicago, IL",
        "pickupLocation": "Dallas, TX",
        "dropoffLocation": "Los Angeles, CA",
        "cycleUsedHours": 20
    }

    Response:
    {
        "route": {
            "total_distance_miles": ...,
            "total_duration_hours": ...,
            "geometry": {...GeoJSON LineString...},
            "stops": [{"label": "Current", "lat": .., "lon": .., "display_name": ".."}, ...]
        },
        "trip_start": "...", "trip_end": "...",
        "needs_34hr_restart": false,
        "warnings": [...],
        "daily_logs": [
            {"date": "2026-07-23", "segments": [...], "totals_hours": {...}}, ...
        ]
    }
    """

    def post(self, request):
        serializer = TripRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        stop_labels = ["Current", "Pickup", "Dropoff"]
        stop_names = [data["currentLocation"], data["pickupLocation"], data["dropoffLocation"]]

        # 1. Geocode all three stops
        try:
            geocoded = [geocode(name) for name in stop_names]
        except GeocodingError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        # 2. Get driving route + per-leg distance/duration
        coords = [(g["lat"], g["lon"]) for g in geocoded]
        try:
            route = route_multi_stop(coords)
        except RoutingError as e:
            return Response({"error": str(e)}, status=status.HTTP_502_BAD_GATEWAY)

        # 3. Build Leg objects for the HOS simulator
        legs = [
            Leg(
                from_label=stop_labels[i],
                to_label=stop_labels[i + 1],
                distance_miles=route["legs"][i]["distance_miles"],
                duration_hours=route["legs"][i]["duration_hours"],
            )
            for i in range(len(route["legs"]))
        ]

        # 4. Run the HOS/ELD simulation
        sim = simulate(legs=legs, cycle_hours_already_used=data["cycleUsedHours"])
        daily_logs = segments_to_daily_logs(sim.segments)

        return Response({
            "route": {
                "total_distance_miles": round(route["total_distance_miles"], 1),
                "total_duration_hours": round(route["total_duration_hours"], 2),
                "geometry": route["geometry"],
                "stops": [
                    {"label": label, **g}
                    for label, g in zip(stop_labels, geocoded)
                ],
            },
            "trip_start": sim.segments[0].start.isoformat() if sim.segments else None,
            "trip_end": sim.trip_end.isoformat() if sim.trip_end else None,
            "needs_34hr_restart": sim.needs_34hr_restart,
            "warnings": sim.warnings,
            "daily_logs": daily_logs,
        })
