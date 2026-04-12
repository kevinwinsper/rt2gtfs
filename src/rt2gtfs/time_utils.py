
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytz


def generate_date_range(start_date, end_date, mode: str = "all", reverse: bool = False) -> list[str]:
    """Return dates in YYYYMMDD format between two endpoints, inclusive."""
    start = datetime.strptime(str(start_date), "%Y%m%d")
    end = datetime.strptime(str(end_date), "%Y%m%d")
    if end < start:
        raise ValueError("end_date must be on or after start_date")

    mode = mode.lower()
    allowed = {"all", "weekday", "weekend", "saturday"}
    if mode not in allowed:
        raise ValueError(f"mode must be one of {sorted(allowed)}")

    dates: list[str] = []
    current = start
    while current <= end:
        weekday = current.weekday()
        keep = (
            mode == "all"
            or (mode == "weekday" and weekday < 5)
            or (mode == "weekend" and weekday >= 5)
            or (mode == "saturday" and weekday == 5)
        )
        if keep:
            dates.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)

    return dates[::-1] if reverse else dates


def gtfs_to_unix_timestamp(
    time_str: str,
    service_date: str,
    geo: str = "Europe/London",
) -> int:
    """
    Convert a GTFS time string (which may exceed 24:00:00) on a service date
    into a Unix timestamp in UTC.

    Parameters
    ----------
    time_str : str
        GTFS time, e.g. "23:15:00" or "25:10:00".
    service_date : str
        Service date in YYYYMMDD format.
    geo : str
        Timezone name, default is Europe/London.

    Returns
    -------
    int
        Unix timestamp.
    """
    hours, minutes, seconds = map(int, time_str.split(":"))
    total_seconds = hours * 3600 + minutes * 60 + seconds

    base_date = datetime.strptime(str(service_date), "%Y%m%d")
    local_tz = pytz.timezone(geo)

    local_dt = local_tz.localize(base_date) + timedelta(seconds=total_seconds)
    return int(local_dt.timestamp())


def calculate_time_diff(date: str, geo: str = "Europe/London") -> int:
    """Return the UTC offset, in whole hours, for a timezone on a given date."""
    naive = datetime.strptime(str(date), "%Y%m%d")
    timezone = pytz.timezone(geo)
    localized = timezone.localize(naive)
    return int(localized.utcoffset().total_seconds() // 3600)


def unix_to_gtfs_timestamp(unix_timestamps, date, time_diff: int | None = 0):
    """Convert Unix timestamps to GTFS HH:MM:SS strings."""
    service_day = pd.Timestamp(datetime.strptime(str(date), "%Y%m%d")).normalize()
    timestamps = pd.to_datetime(pd.Series(unix_timestamps), unit="s", utc=True).dt.tz_convert(None)
    offset_hours = 0 if time_diff in (None, False) else int(time_diff)
    shifted = timestamps + pd.to_timedelta(offset_hours, unit="h")

    seconds_since_service_day = (shifted - service_day).dt.total_seconds().round().astype("Int64")
    hours = seconds_since_service_day // 3600
    minutes = (seconds_since_service_day % 3600) // 60
    seconds = seconds_since_service_day % 60

    return (
        hours.astype(str).str.zfill(2)
        + ":"
        + minutes.astype(str).str.zfill(2)
        + ":"
        + seconds.astype(str).str.zfill(2)
    )
