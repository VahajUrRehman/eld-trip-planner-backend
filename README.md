# Trip HOS/ELD Planner — Django backend

Receives a trip from the React `TripForm` (`currentLocation`, `pickupLocation`,
`dropoffLocation`, `cycleUsedHours`), geocodes the three stops, gets a driving
route between them, then runs an FMCSA Hours-of-Service simulation to produce
day-by-day ELD log segments (driving / on-duty / off-duty / breaks / fuel stops).

## Project layout

```
trip_backend/
├── manage.py
├── requirements.txt
├── config/            # Django project (settings, urls)
└── trips/
    ├── serializers.py # validates the incoming JSON
    ├── views.py       # POST /api/trip/plan/
    ├── urls.py
    └── services/
        ├── geocoding.py  # OpenStreetMap Nominatim (free, no API key)
        ├── routing.py    # OSRM public demo server (free, no API key)
        └── hos.py        # the actual HOS/ELD rules simulator
```

No API keys are required to run this as-is — geocoding and routing use free
public services. For production use, swap `services/routing.py` /
`services/geocoding.py` for a paid provider (Google, Mapbox, ORS) if you need
higher rate limits or reliability guarantees.

## Running it on Windows (first time)

Open **Command Prompt** or **PowerShell**, `cd` into the project folder, then:

```bat
:: 1. Create a virtual environment (only needed once)
python -m venv venv

:: 2. Activate it (do this every time you open a new terminal)
venv\Scripts\activate

:: 3. Install dependencies
pip install -r requirements.txt

:: 4. Create the database tables (Django's own, for admin/sessions — the app
::    itself doesn't store trips in the DB, but this step is still required)
python manage.py migrate

:: 5. (Optional) create an admin login
python manage.py createsuperuser

:: 6. Run the dev server
python manage.py runserver
```

The API is now live at `http://127.0.0.1:8000/api/trip/plan/`.

Next time, you only need steps 2 and 6:
```bat
venv\Scripts\activate
python manage.py runserver
```

> If `python` isn't recognized, try `py` instead (`py -m venv venv`, then
> `py manage.py runserver`), or make sure "Add Python to PATH" was checked
> when you installed Python.

## Running it on macOS/Linux

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

## Calling it from the React frontend

Your `App.tsx` `handleSubmit` becomes:

```tsx
async function handleSubmit(data: TripFormData) {
  const res = await fetch("http://127.0.0.1:8000/api/trip/plan/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
  if (!res.ok) {
    const err = await res.json()
    console.error(err)
    return
  }
  const plan = await res.json()
  console.log(plan) // { route, trip_start, trip_end, warnings, daily_logs, ... }
}
```

`django-cors-headers` is already configured to allow `localhost:5173` (Vite)
and `localhost:3000` (CRA) — add your dev port to `CORS_ALLOWED_ORIGINS` in
`config/settings.py` if it's different.

## Response shape

```jsonc
{
  "route": {
    "total_distance_miles": 2300.4,
    "total_duration_hours": 38.1,
    "geometry": { "type": "LineString", "coordinates": [[lon, lat], ...] },
    "stops": [
      { "label": "Current", "lat": 41.87, "lon": -87.62, "display_name": "Chicago, IL, USA" },
      ...
    ]
  },
  "trip_start": "2026-07-23T06:00:00",
  "trip_end": "2026-07-26T06:30:00",
  "needs_34hr_restart": false,
  "warnings": [],
  "daily_logs": [
    {
      "date": "2026-07-23",
      "segments": [
        { "status": "driving", "start": "...", "end": "...", "duration_hours": 8.0, "label": "Driving: Current → Pickup" },
        ...
      ],
      "totals_hours": { "off_duty": 7.0, "sleeper_berth": 0.0, "driving": 11.0, "on_duty_not_driving": 0.0 }
    },
    ...
  ]
}
```

Each `daily_logs` entry maps naturally onto an ELD-style 24-hour grid (4 rows:
off duty / sleeper berth / driving / on-duty-not-driving) if you want to
render it that way on the frontend.

## HOS rules implemented (`trips/services/hos.py`)

- 11-hour driving limit per shift
- 14-hour on-duty window per shift (doesn't pause for breaks)
- 30-minute break required after 8 cumulative hours of driving
- 10 consecutive hours off duty to start a new shift
- 70-hour / 8-day cycle limit, with an automatic 34-hour restart inserted if hit
- 1 hour on-duty time assumed for pickup and 1 hour for drop-off
- A fuel stop every 1,000 miles (30 min, on-duty not driving)

This is a simplified, rule-faithful simulation it doesn't model adverse
driving conditions, sleeper-berth split-duty provisions, or multi-driver
teams. Easy to extend in `hos.py` if you need those.
