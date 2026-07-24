"""
Hours-of-Service (HOS) and ELD log simulator.

Implements the FMCSA property-carrying driver rules (70hrs/8days cycle):
  - 11-hour driving limit per shift
  - 14-hour on-duty window per shift (doesn't pause for breaks)
  - 30-minute break required after 8 cumulative hours of driving
  - 10 consecutive hours off duty required to start a new shift
  - 70-hour / 8-day cycle limit (34-hour restart clears it)
  - 1 hour on-duty (not driving) assumed for pickup and 1 hour for drop-off
  - A fuel stop every FUEL_STOP_MILES miles (on-duty, not driving)

This is a simplified but rule-faithful simulation intended as a solid
starting point — it does not model adverse driving conditions, sleeper
berth split-duty provisions, or multi-driver teams.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum


class DutyStatus(str, Enum):
    OFF_DUTY = "off_duty"
    SLEEPER = "sleeper_berth"
    DRIVING = "driving"
    ON_DUTY = "on_duty_not_driving"


# --- Rule constants (hours unless noted) ---
MAX_DRIVING_HOURS_PER_SHIFT = 11
MAX_ON_DUTY_WINDOW_HOURS = 14
MIN_OFF_DUTY_RESET_HOURS = 10
BREAK_REQUIRED_AFTER_DRIVING_HOURS = 8
BREAK_DURATION_HOURS = 0.5
CYCLE_LIMIT_HOURS = 70
CYCLE_RESTART_HOURS = 34
PICKUP_DROPOFF_DUTY_HOURS = 1
FUEL_STOP_EVERY_MILES = 1000
FUEL_STOP_DURATION_HOURS = 0.5
AVG_DRIVING_SPEED_MPH_FALLBACK = 55


@dataclass
class Segment:
    status: DutyStatus
    start: datetime
    end: datetime
    label: str = ""

    @property
    def hours(self) -> float:
        return (self.end - self.start).total_seconds() / 3600

    def to_dict(self):
        return {
            "status": self.status.value,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "duration_hours": round(self.hours, 2),
            "label": self.label,
        }


@dataclass
class Leg:
    """A driving leg between two named stops."""
    from_label: str
    to_label: str
    distance_miles: float
    duration_hours: float  # pure driving time at road speed, before HOS breaks


@dataclass
class SimResult:
    segments: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    total_distance_miles: float = 0
    total_driving_hours: float = 0
    trip_end: datetime = None
    needs_34hr_restart: bool = False


def simulate(
    legs: list[Leg],
    cycle_hours_already_used: float,
    trip_start: datetime | None = None,
) -> SimResult:
    """
    Walk through the legs, inserting breaks / off-duty resets / fuel stops /
    pickup & drop-off duty time according to FMCSA HOS rules, and return a
    day-by-day timeline of duty-status segments.
    """
    if trip_start is None:
        trip_start = datetime.now().replace(minute=0, second=0, microsecond=0)

    now = trip_start
    result = SimResult()

    # Rolling counters
    hours_driven_in_shift = 0.0
    hours_in_duty_window = 0.0
    hours_since_break = 0.0
    cycle_hours_used = cycle_hours_already_used
    miles_since_fuel = 0.0

    def add_segment(status: DutyStatus, duration_hours: float, label: str):
        nonlocal now
        if duration_hours <= 0:
            return
        seg = Segment(status=status, start=now, end=now + timedelta(hours=duration_hours), label=label)
        result.segments.append(seg)
        now = seg.end

    def start_new_shift_if_needed():
        # If we're at the very start (no on-duty segment opened yet this shift)
        nonlocal hours_in_duty_window
        pass  # window starts accruing the moment any on-duty/driving segment begins

    n_legs = len(legs)
    for leg_index, leg in enumerate(legs):
        remaining_leg_hours = leg.duration_hours
        remaining_leg_miles = leg.distance_miles
        result.total_distance_miles += leg.distance_miles
        result.total_driving_hours += leg.duration_hours

        while remaining_leg_hours > 1e-6:
            # 1) Cycle limit hit -> mandatory 34-hour restart
            if cycle_hours_used >= CYCLE_LIMIT_HOURS - 1e-6:
                add_segment(DutyStatus.OFF_DUTY, CYCLE_RESTART_HOURS, "34-hour restart (70-hr/8-day cycle reached)")
                result.warnings.append(
                    f"70-hour/8-day cycle limit reached before finishing '{leg.from_label} → {leg.to_label}'. "
                    "Inserted a mandatory 34-hour restart."
                )
                result.needs_34hr_restart = True
                cycle_hours_used = 0
                hours_driven_in_shift = 0
                hours_in_duty_window = 0
                hours_since_break = 0
                continue

            # 2) 30-min break required after 8 cumulative hours driving
            if hours_since_break >= BREAK_REQUIRED_AFTER_DRIVING_HOURS - 1e-6:
                add_segment(DutyStatus.OFF_DUTY, BREAK_DURATION_HOURS, "Required 30-minute break")
                hours_in_duty_window += BREAK_DURATION_HOURS
                hours_since_break = 0
                continue

            # 3) Shift limits (11-hr driving or 14-hr window) -> 10-hr off-duty reset
            if hours_driven_in_shift >= MAX_DRIVING_HOURS_PER_SHIFT - 1e-6 or \
               hours_in_duty_window >= MAX_ON_DUTY_WINDOW_HOURS - 1e-6:
                add_segment(DutyStatus.OFF_DUTY, MIN_OFF_DUTY_RESET_HOURS, "10-hour off-duty reset")
                hours_driven_in_shift = 0
                hours_in_duty_window = 0
                hours_since_break = 0
                continue

            # 4) Fuel stop every FUEL_STOP_EVERY_MILES miles
            if miles_since_fuel >= FUEL_STOP_EVERY_MILES - 1e-6:
                add_segment(DutyStatus.ON_DUTY, FUEL_STOP_DURATION_HOURS, "Fuel stop")
                hours_in_duty_window += FUEL_STOP_DURATION_HOURS
                cycle_hours_used += FUEL_STOP_DURATION_HOURS
                miles_since_fuel = 0
                continue

            # 5) Drive — figure out the largest safe chunk before hitting any limit
            miles_per_hour = leg.distance_miles / leg.duration_hours if leg.duration_hours > 0 else AVG_DRIVING_SPEED_MPH_FALLBACK
            miles_to_next_fuel_stop = FUEL_STOP_EVERY_MILES - miles_since_fuel
            hours_to_next_fuel_stop = miles_to_next_fuel_stop / miles_per_hour if miles_per_hour > 0 else remaining_leg_hours

            drive_chunk = min(
                remaining_leg_hours,
                BREAK_REQUIRED_AFTER_DRIVING_HOURS - hours_since_break,
                MAX_DRIVING_HOURS_PER_SHIFT - hours_driven_in_shift,
                MAX_ON_DUTY_WINDOW_HOURS - hours_in_duty_window,
                hours_to_next_fuel_stop,
            )
            drive_chunk = max(drive_chunk, 0.0)
            if drive_chunk <= 1e-6:
                # Safety valve: shouldn't normally happen, but avoid infinite loop
                drive_chunk = min(remaining_leg_hours, 0.1)

            add_segment(DutyStatus.DRIVING, drive_chunk, f"Driving: {leg.from_label} → {leg.to_label}")
            hours_driven_in_shift += drive_chunk
            hours_in_duty_window += drive_chunk
            hours_since_break += drive_chunk
            cycle_hours_used += drive_chunk
            miles_driven_chunk = drive_chunk * miles_per_hour
            miles_since_fuel += miles_driven_chunk
            remaining_leg_hours -= drive_chunk
            remaining_leg_miles -= miles_driven_chunk

        # End of leg: pickup / drop-off duty time (not driving)
        is_final_leg = leg_index == n_legs - 1
        stop_label = "Drop-off" if is_final_leg else "Pickup"

        # Make sure adding this duty time doesn't itself blow the 14-hr window;
        # if it would, take the 10-hr reset first.
        if hours_in_duty_window + PICKUP_DROPOFF_DUTY_HOURS > MAX_ON_DUTY_WINDOW_HOURS + 1e-6:
            add_segment(DutyStatus.OFF_DUTY, MIN_OFF_DUTY_RESET_HOURS, "10-hour off-duty reset")
            hours_driven_in_shift = 0
            hours_in_duty_window = 0
            hours_since_break = 0

        add_segment(DutyStatus.ON_DUTY, PICKUP_DROPOFF_DUTY_HOURS, f"{stop_label} at {leg.to_label}")
        hours_in_duty_window += PICKUP_DROPOFF_DUTY_HOURS
        cycle_hours_used += PICKUP_DROPOFF_DUTY_HOURS

    result.trip_end = now
    return result


def segments_to_daily_logs(segments: list[Segment]) -> list[dict]:
    """
    Split segments across midnight boundaries and group into one ELD-style
    grid per calendar day, each with totals per duty status.
    """
    days: dict[str, list[Segment]] = {}

    for seg in segments:
        cursor = seg.start
        seg_end = seg.end
        while cursor < seg_end:
            day_key = cursor.date().isoformat()
            next_midnight = datetime.combine(cursor.date() + timedelta(days=1), datetime.min.time())
            chunk_end = min(seg_end, next_midnight)
            piece = Segment(status=seg.status, start=cursor, end=chunk_end, label=seg.label)
            days.setdefault(day_key, []).append(piece)
            cursor = chunk_end

    daily_logs = []
    for day_key in sorted(days.keys()):
        day_segments = days[day_key]
        totals = {status.value: 0.0 for status in DutyStatus}
        for piece in day_segments:
            totals[piece.status.value] += piece.hours
        daily_logs.append({
            "date": day_key,
            "segments": [p.to_dict() for p in day_segments],
            "totals_hours": {k: round(v, 2) for k, v in totals.items()},
        })
    return daily_logs
