
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import math
import time

import pandas as pd

from .logging_utils import get_logger, get_stats_logger
from .models import VehicleObservation


def haversine(lat1, lon1, lat2, lon2) -> float:
    """Great-circle distance in kilometres between two points."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    arc = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return round(6371.0088 * arc, 5)


def _find_candidate_stops(
    trip_id: str,
    lat: float,
    lon: float,
    trip_to_stops: dict[str, list[str]],
    stop_lookup: dict[str, dict[str, float]],
    radius_m: float,
) -> list[tuple[str, float]]:
    stop_ids = trip_to_stops.get(trip_id)
    if not stop_ids:
        return []

    lat_window = radius_m / 111_000.0
    lon_window = radius_m / (111_000.0 * math.cos(math.radians(lat))) if abs(lat) < 89.999 else radius_m / 111_000.0

    matches: list[tuple[str, float]] = []
    for stop_id in stop_ids:
        stop = stop_lookup.get(stop_id)
        if stop is None:
            continue
        stop_lat = float(stop["stop_lat"])
        stop_lon = float(stop["stop_lon"])
        if abs(stop_lat - lat) > lat_window or abs(stop_lon - lon) > lon_window:
            continue
        distance_km = haversine(lat, lon, stop_lat, stop_lon)
        matches.append((stop_id, distance_km * 1000.0))

    matches.sort(key=lambda item: item[1])
    return matches


def inspect_rt_data(
    date_to_match,
    rt_df,
    trip_to_stops,
    stop_lookup,
    all_trip_to_stops,
    all_stop_lookup,
    trip_to_date,
    result_dir,
    radius_m: float = 300,
    check_extra_dates: bool = False,
    logger=None,
    stats_logger=None,
):
    """Match vehicle observations to the nearest stop on their trip pattern."""
    logger = logger or get_logger(__name__)
    date_to_match = str(date_to_match)
    result_dir = Path(result_dir)
    records: list[VehicleObservation] = []
    diff_day_matching = 0
    no_matching = 0
    out_of_bound = 0
    t0 = time.time()

    total = len(rt_df)
    for n, (_, row) in enumerate(rt_df.iterrows(), start=1):
        observation = VehicleObservation(
            trip_id=row["trip_id"],
            route_id=row["route_id"],
            lat=round(float(row["latitude"]), 6),
            lon=round(float(row["longitude"]), 6),
            bearing=row.get("bearing"),
            timestamp=row["timestamp"],
            timestamp_dt=row["timestamp_dt"],
            vehicle_id=row["vehicle_id"],
        )

        same_day_candidates = _find_candidate_stops(
            trip_id=observation.trip_id,
            lat=observation.lat,
            lon=observation.lon,
            trip_to_stops=trip_to_stops,
            stop_lookup=stop_lookup,
            radius_m=radius_m,
        )

        chosen_source_date = date_to_match
        same_day_flag = 1
        candidates = same_day_candidates

        if not candidates and check_extra_dates:
            candidates = _find_candidate_stops(
                trip_id=observation.trip_id,
                lat=observation.lat,
                lon=observation.lon,
                trip_to_stops=all_trip_to_stops,
                stop_lookup=all_stop_lookup,
                radius_m=radius_m,
            )
            if candidates:
                chosen_source_date = trip_to_date[observation.trip_id]
                same_day_flag = 0

        if not candidates:
            no_matching += 1
            continue

        nearest_stop_id, nearest_distance_m = candidates[0]
        if nearest_distance_m >= radius_m:
            out_of_bound += 1
            no_matching += 1
            continue

        observation.nearest_stop_id = nearest_stop_id
        observation.nearest_stop_distance_m = nearest_distance_m
        observation.same_day_timetable = same_day_flag
        observation.timetable_date = chosen_source_date
        records.append(observation)

        if same_day_flag == 0:
            diff_day_matching += 1

        if n % 500_000 == 0:
            elapsed = round(time.time() - t0, 3)
            logger.info("%s: Time spent: %s s", date_to_match, elapsed)
            logger.info("%s: %s of %s observations processed", date_to_match, n, total)
            if check_extra_dates:
                logger.info("%s: %s different-day matches found", date_to_match, diff_day_matching)

    logger.info("%s: Number of matches: %s", date_to_match, len(records))
    logger.info("%s: Number of different-day matches: %s", date_to_match, diff_day_matching)
    logger.info("%s: Number of no matches: %s", date_to_match, no_matching)
    logger.info("%s: Number of out of bounds: %s", date_to_match, out_of_bound)
    logger.info("%s: Finished matching (PID: %s)", date_to_match, __import__('os').getpid())

    matching = pd.DataFrame(
        {
            "trip_id": [record.trip_id for record in records],
            "vehicle_id": [record.vehicle_id for record in records],
            "route_id": [record.route_id for record in records],
            "timestamp": [record.timestamp for record in records],
            'timestamp_dt': [record.timestamp_dt for record in records],
            "nearest_stop_id": [record.nearest_stop_id for record in records],
            "distance": [record.nearest_stop_distance_m for record in records],
            "same_day_timetable": [record.same_day_timetable for record in records],
            "timetable_date": [record.timetable_date for record in records],
        }
    )

    timetable_dates = matching["timetable_date"].dropna().astype(str).unique().tolist() if not matching.empty else []

    if check_extra_dates and not matching.empty:
        details = (
            matching["timetable_date"]
            .value_counts(dropna=False)
            .rename_axis("timetable_date")
            .reset_index(name="count")
        )
        logger.info(
                "%s: Matching details by timetable_date:\n%s",
                date_to_match,
                details.to_string(index=False)
        )
        details["percentage"] = (details["count"] / details["count"].sum() * 100).round(2)
        output_dir = result_dir / "matching_stats"
        output_dir.mkdir(parents=True, exist_ok=True)
        details.to_csv(output_dir / f"matching_details_{date_to_match}.csv", index=False)

        if stats_logger:
            stats_logger.info(
                "%s: Matching details by timetable_date:\n%s \n",
                date_to_match,
                details.to_string(index=False)
            )

    return matching, timetable_dates
