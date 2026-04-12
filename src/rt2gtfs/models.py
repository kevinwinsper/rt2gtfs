from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class VehicleObservation:
    """Container for one matched vehicle observation."""

    trip_id: str | None = None
    route_id: object = None
    lat: float | None = None
    lon: float | None = None
    bearing: float | None = None
    timestamp: int | float | None = None
    timestamp_dt: datetime | None = None
    vehicle_id: str | None = None
    nearest_stop_id: str | None = None
    nearest_stop_distance_m: float | None = None
    same_day_timetable: int | None = None
    timetable_date: str | int | None = None
