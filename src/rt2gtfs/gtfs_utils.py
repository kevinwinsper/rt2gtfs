
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Sequence
import zipfile

import pandas as pd

from .logging_utils import get_logger


def get_naptan_ref(naptan_path: str | Path) -> pd.DataFrame:
    naptan_path = Path(naptan_path)
    bearing_lookup = {
        "N": 0, "NE": 45, "E": 90, "SE": 135,
        "S": 180, "SW": 225, "W": 270, "NW": 315,
    }
    naptan_ref = pd.read_csv(
        naptan_path,
        usecols=["ATCOCode", "CommonName", "Bearing"],
        low_memory=False,
    ).rename(columns={"ATCOCode": "stop_id", "CommonName": "stop_name"})
    naptan_ref["Bearing"] = naptan_ref["Bearing"].map(bearing_lookup)
    return naptan_ref


def load_partial_gtfs(gtfs_path: str | Path, logger=None):
    logger = logger or get_logger(__name__)
    gtfs_path = Path(gtfs_path)
    table_specs = {
        "stops.txt": ["stop_id", "stop_name", "stop_lat", "stop_lon"],
        "stop_times.txt": None,
        "trips.txt": ["trip_id", "route_id"],
    }

    loaded: dict[str, pd.DataFrame | None] = {name: None for name in table_specs}
    for filename, columns in table_specs.items():
        path = gtfs_path / filename
        if not path.exists():
            continue
        data = pd.read_csv(path, low_memory=False)
        loaded[filename] = data if columns is None else data.loc[:, columns].copy()
        logger.info("Loaded %s", filename)

    missing = [name for name, frame in loaded.items() if frame is None]
    if missing:
        raise FileNotFoundError(f"Missing required GTFS files in {gtfs_path}: {missing}")

    return loaded["stops.txt"], loaded["stop_times.txt"], loaded["trips.txt"]


def _unzip_gtfs(gtfs_dir: Path, date_to_match: str, gtfs_filename_template: str, logger=None) -> Path:
    logger = logger or get_logger(__name__)
    zip_path = gtfs_dir / f"{gtfs_filename_template.format(date=date_to_match)}.zip"
    extract_dir = gtfs_dir / gtfs_filename_template.format(date=date_to_match)

    if not extract_dir.exists():
        with zipfile.ZipFile(zip_path, "r") as archive:
            archive.extractall(extract_dir)
        logger.info("Unzipped %s to %s", zip_path.name, extract_dir)
    else:
        logger.info("Skipped unzipping; %s already exists", extract_dir)

    return extract_dir


def _make_trip_to_stop_lookup(trips: pd.DataFrame, stop_times: pd.DataFrame) -> dict[str, list[str]]:
    pairs = stop_times.loc[:, ["trip_id", "stop_id"]].merge(
        trips.loc[:, ["trip_id"]], on="trip_id", how="inner"
    )
    grouped = pairs.groupby("trip_id", sort=False)["stop_id"].agg(list)
    return grouped.to_dict()


def _make_stop_to_stoploc_lookup(
    stops: pd.DataFrame,
    stop_times: pd.DataFrame,
    naptan_reference: pd.DataFrame | None = None,
) -> dict[str, dict[str, float]]:
    used_stops = stop_times.loc[:, ["stop_id"]].drop_duplicates().merge(
        stops.loc[:, ["stop_id", "stop_lat", "stop_lon"]],
        on="stop_id",
        how="inner",
    )
    if naptan_reference is not None:
        used_stops = used_stops.merge(naptan_reference, on="stop_id", how="left")
        columns = ["stop_lat", "stop_lon", "Bearing"]
    else:
        columns = ["stop_lat", "stop_lon"]
    return used_stops.set_index("stop_id")[columns].to_dict(orient="index")


def create_lookups(
    date_to_match,
    gtfs_dir,
    gtfs_filename_template: str = "itm_all_gtfs_{date}",
    use_naptan: bool = False,
    naptan_path=None,
    logger=None,
):
    logger = logger or get_logger(__name__)
    date_to_match = str(date_to_match)
    gtfs_dir = Path(gtfs_dir)
    extracted_dir = _unzip_gtfs(gtfs_dir, date_to_match, gtfs_filename_template, logger=logger)
    stops, stop_times, trips = load_partial_gtfs(extracted_dir, logger=logger)

    naptan_reference = get_naptan_ref(naptan_path) if use_naptan else None
    trip_to_stop_lookup = _make_trip_to_stop_lookup(trips=trips, stop_times=stop_times)
    stop_to_stoploc_lookup = _make_stop_to_stoploc_lookup(stops=stops, stop_times=stop_times, naptan_reference=naptan_reference)
    return trip_to_stop_lookup, stop_to_stoploc_lookup


def create_lookups_with_time_window(
    date_to_match,
    gtfs_dir,
    time_window_days: int = 7,
    extra_dates: Sequence[str] | None = None,
    gtfs_filename_template: str = "itm_all_gtfs_{date}",
    use_naptan: bool = False,
    naptan_path=None,
    logger=None,
):
    logger = logger or get_logger(__name__)
    target = datetime.strptime(str(date_to_match), "%Y%m%d")
    tomorrow = (target + timedelta(days=1)).strftime("%Y%m%d")
    today = datetime.today()

    if extra_dates is None:
        extra_dates = []
        for offset in range(-time_window_days, time_window_days + 1):
            if offset == 0:
                continue
            candidate = target + timedelta(days=offset)
            if candidate <= today:
                extra_dates.append(candidate.strftime("%Y%m%d"))

    all_trip_to_stop_lookup: dict[str, list[str]] = {}
    all_stop_to_stoploc_lookup: dict[str, dict[str, float]] = {}
    trip_source_dates: dict[str, int] = {}
    stop_source_dates: dict[str, int] = {}
    trip_conflicts = 0
    stop_conflicts = 0

    for service_date in extra_dates:
        logger.info("%s: Loading GTFS data for %s", date_to_match, service_date)
        trip_lookup, stop_lookup = create_lookups(
            service_date,
            gtfs_dir,
            gtfs_filename_template=gtfs_filename_template,
            use_naptan=use_naptan,
            naptan_path=naptan_path,
            logger=logger,
        )

        for trip_id, stop_ids in trip_lookup.items():
            if trip_id not in all_trip_to_stop_lookup:
                all_trip_to_stop_lookup[trip_id] = stop_ids
                trip_source_dates[trip_id] = int(service_date)
                continue
            if all_trip_to_stop_lookup[trip_id] != stop_ids:
                current_source = trip_source_dates[trip_id]
                incoming_source = int(service_date)
                if current_source < incoming_source <= int(tomorrow):
                    all_trip_to_stop_lookup[trip_id] = stop_ids
                    trip_source_dates[trip_id] = incoming_source
                    trip_conflicts += 1

        for stop_id, stop_info in stop_lookup.items():
            if stop_id not in all_stop_to_stoploc_lookup:
                all_stop_to_stoploc_lookup[stop_id] = stop_info
                stop_source_dates[stop_id] = int(service_date)
                continue
            if int(service_date) > stop_source_dates[stop_id]:
                all_stop_to_stoploc_lookup[stop_id] = stop_info
                stop_source_dates[stop_id] = int(service_date)
                stop_conflicts += 1

    logger.info("%s: Finished creating cross-date dictionaries", date_to_match)
    logger.info("%s: Trip conflicts resolved by newer date: %s", date_to_match, trip_conflicts)
    logger.info("%s: Stop conflicts resolved by newer date: %s", date_to_match, stop_conflicts)
    return all_trip_to_stop_lookup, all_stop_to_stoploc_lookup, trip_source_dates, stop_source_dates


def load_full_gtfs(
    gtfs_dir: str | Path,
    date_to_match: str | int,
    gtfs_filename_template: str = "itm_all_gtfs_{date}",
    include: list[str] | None = None,
):
    gtfs_dir = Path(gtfs_dir)
    date_to_match = str(date_to_match)
    required = [
        "agency.txt",
        "routes.txt",
        "trips.txt",
        "stops.txt",
        "stop_times.txt",
        "calendar.txt",
        "calendar_dates.txt",
    ]
    if include:
        required.extend(include)

    zip_path = gtfs_dir / f"{gtfs_filename_template.format(date=date_to_match)}.zip"
    extract_dir = gtfs_dir / gtfs_filename_template.format(date=date_to_match)
    if not extract_dir.exists():
        with zipfile.ZipFile(zip_path, "r") as archive:
            archive.extractall(extract_dir)

    frames = []
    for name in required:
        file_path = extract_dir / name
        if not file_path.exists():
            raise FileNotFoundError(f"Expected GTFS file not found: {file_path}")
        frames.append(pd.read_csv(file_path, low_memory=False))
    return frames


def load_multiple_gtfs(
    gtfs_dir: str | Path,
    dates: list,
    gtfs_filename_template: str = "itm_all_gtfs_{date}",
    priority_date: str | None = None,
    logger=None,
):
    logger = logger or get_logger(__name__)
    component_names = [
        "agencies", "routes", "trips", "stops", "stop_times",
        "calendar", "calendar_dates", "feed_info", "shapes",
    ]
    collected = {name: [] for name in component_names}

    for date in dates:
        logger.info("%s: Loading GTFS for %s", priority_date, date)
        loaded = load_full_gtfs(
            gtfs_dir=gtfs_dir,
            date_to_match=date,
            gtfs_filename_template=gtfs_filename_template,
            include=["feed_info.txt", "shapes.txt"],
        )
        for name, df in zip(component_names, loaded):
            df = df.copy()
            df["source_date"] = str(date)
            collected[name].append(df)

    def concat_frames(frames):
        valid = [df for df in frames if df is not None and not df.empty]
        return pd.concat(valid, ignore_index=True) if valid else pd.DataFrame()

    combined = {name: concat_frames(frames) for name, frames in collected.items()}

    def dedupe_with_priority(df: pd.DataFrame, keys: list[str], keep_source_date: bool = False) -> pd.DataFrame:
        if df.empty:
            return df.copy()
        working = df.copy()
        if priority_date is not None:
            working["priority_flag"] = (working["source_date"] != str(priority_date)).astype(int)
            sort_cols = [*keys, "priority_flag", "source_date"]
        else:
            sort_cols = [*keys, "source_date"]
        working = working.sort_values(sort_cols).drop_duplicates(subset=keys, keep="first")
        if not keep_source_date:
            working = working.drop(columns=[c for c in ["priority_flag", "source_date"] if c in working.columns])
        return working

    def choose_stop_time_source(stop_times: pd.DataFrame) -> pd.Series | None:
        if stop_times.empty or priority_date is None:
            return None
        st = stop_times[["trip_id", "source_date"]].drop_duplicates().copy()
        st["source_date_dt"] = pd.to_datetime(st["source_date"], format="%Y%m%d", errors="coerce")
        priority_dt = pd.to_datetime(str(priority_date), format="%Y%m%d", errors="coerce")
        st["distance_days"] = (st["source_date_dt"] - priority_dt).abs().dt.days
        st["priority_flag"] = (st["source_date"] != str(priority_date)).astype(int)
        st = st.sort_values(["trip_id", "priority_flag", "distance_days", "source_date"])
        chosen = st.drop_duplicates(subset=["trip_id"], keep="first")
        return chosen.set_index("trip_id")["source_date"]

    agencies = dedupe_with_priority(combined["agencies"], ["agency_id"])
    routes = dedupe_with_priority(combined["routes"], ["route_id"])
    trips = dedupe_with_priority(combined["trips"], ["trip_id"], keep_source_date=True)
    stops = dedupe_with_priority(combined["stops"], ["stop_id"])
    calendar = dedupe_with_priority(combined["calendar"], ["service_id"])
    calendar_dates = dedupe_with_priority(combined["calendar_dates"], ["service_id", "date", "exception_type"])
    feed_info = dedupe_with_priority(combined["feed_info"], ["feed_publisher_name", "feed_version"])
    shapes = dedupe_with_priority(combined["shapes"], ["shape_id", "shape_pt_lat", "shape_pt_lon", "shape_pt_sequence"])

    trip_source_map = choose_stop_time_source(combined["stop_times"])
    if trip_source_map is not None and not combined["stop_times"].empty:
        stop_times = combined["stop_times"].merge(
            trip_source_map.rename("chosen_source_date"),
            left_on="trip_id",
            right_index=True,
            how="left",
        )
        stop_times = stop_times[stop_times["source_date"] == stop_times["chosen_source_date"]].copy()
        stop_times = stop_times.drop(columns=["chosen_source_date"])
    else:
        stop_times = combined["stop_times"].copy()

    if not trips.empty and "source_date" in trips.columns and not stop_times.empty and "source_date" in stop_times.columns:
        trips = trips[trips["trip_id"].isin(stop_times["trip_id"])].copy()
        trips = trips.sort_values(["trip_id", "source_date"]).drop_duplicates(subset=["trip_id"], keep="first")

    if "source_date" in stop_times.columns:
        stop_times = stop_times.sort_values(["trip_id", "stop_sequence", "source_date"])
        stop_times = stop_times.drop_duplicates(subset=["trip_id", "stop_sequence"], keep="first")
        stop_times = stop_times.drop(columns=["source_date"])
    if "source_date" in trips.columns:
        trips = trips.drop(columns=["source_date"])

    return agencies, routes, trips, stops, stop_times, calendar, calendar_dates, feed_info, shapes


def create_observed_timetable(
    scheduled_gtfs: dict,
    realtime_timetable: pd.DataFrame,
    result_dir: str | Path,
    observed_gtfs_dir: str | Path,
    timetable_region: str,
    date_to_match: str | int,
    interpolation_flag: bool = True,
    logger=None,
):
    logger = logger or get_logger(__name__)
    observed_gtfs_dir = Path(observed_gtfs_dir)
    result_dir = Path(result_dir)
    date_to_match = str(date_to_match)

    agencies = scheduled_gtfs["agencies"]
    routes = scheduled_gtfs["routes"]
    trips = scheduled_gtfs["trips"]
    stops = scheduled_gtfs["stops"]
    shapes = scheduled_gtfs["shapes"]
    feed_info = scheduled_gtfs["feed_info"]

    observed_gtfs_dir.mkdir(parents=True, exist_ok=True)

    real_route_ids = realtime_timetable["route_id"].dropna().unique()
    real_routes = routes[routes["route_id"].isin(real_route_ids)].drop_duplicates().copy()
    real_routes.to_csv(observed_gtfs_dir / "routes.txt", index=False)

    real_agency_ids = real_routes["agency_id"].dropna().unique()
    real_agencies = agencies[agencies["agency_id"].isin(real_agency_ids)].drop_duplicates().copy()
    real_agencies.to_csv(observed_gtfs_dir / "agency.txt", index=False)

    real_trip_ids = realtime_timetable["trip_id"].dropna().unique()
    real_trips = trips[trips["trip_id"].isin(real_trip_ids)].copy()
    if "shape_id" in real_trips.columns:
        real_trips = real_trips.sort_values(by=["shape_id"], ascending=False, na_position="last")
    real_trips = real_trips.drop_duplicates(subset=["trip_id"], keep="first")
    real_trips["service_id"] = 1
    real_trips.to_csv(observed_gtfs_dir / "trips.txt", index=False)

    real_shape_ids = real_trips["shape_id"].dropna().unique() if "shape_id" in real_trips.columns else []
    if "shape_id" in shapes.columns:
        real_shapes = shapes[shapes["shape_id"].isin(real_shape_ids)].drop_duplicates().copy()
    else:
        real_shapes = shapes.iloc[0:0].copy()
    real_shapes.to_csv(observed_gtfs_dir / "shapes.txt", index=False)

    weekday_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    target_date = datetime.strptime(date_to_match, "%Y%m%d")
    calendar_row = {
        "service_id": 1,
        **{day: int(index == target_date.weekday()) for index, day in enumerate(weekday_names)},
        "start_date": int(date_to_match),
        "end_date": int(date_to_match),
    }
    real_calendar = pd.DataFrame([calendar_row])
    real_calendar.to_csv(observed_gtfs_dir / "calendar.txt", index=False)

    stop_time_columns = [
        "trip_id", "vehicle_id", "arrival_time", "departure_time", "stop_id",
        "stop_sequence", "stop_headsign", "pickup_type", "drop_off_type",
        "shape_dist_traveled", "timepoint",
    ]
    if interpolation_flag and "interpolated" in realtime_timetable.columns:
        stop_time_columns.append("interpolated")

    existing_stop_time_columns = [col for col in stop_time_columns if col in realtime_timetable.columns]
    real_stop_times = (
        realtime_timetable[existing_stop_time_columns]
        .sort_values(["trip_id", "stop_sequence"])
        .drop_duplicates(subset=["trip_id", "stop_sequence"], keep="first")
        .copy()
    )
    real_stop_times.to_csv(observed_gtfs_dir / "stop_times.txt", index=False)

    real_stop_ids = realtime_timetable["stop_id"].dropna().unique()
    real_stops = stops[stops["stop_id"].isin(real_stop_ids)].copy()
    if "location_type" in real_stops.columns:
        real_stops["location_type"] = real_stops["location_type"].astype("Int64")
    if "parent_station" in real_stops.columns:
        real_stops = real_stops.drop(columns=["parent_station"])
    real_stops = real_stops.drop_duplicates()
    real_stops.to_csv(observed_gtfs_dir / "stops.txt", index=False)

    feed_info.copy().to_csv(observed_gtfs_dir / "feed_info.txt", index=False)

    zip_path = result_dir / timetable_region / f"{timetable_region}_{date_to_match}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file in observed_gtfs_dir.rglob("*"):
            if file.is_file():
                archive.write(file, file.relative_to(observed_gtfs_dir))

    logger.info("Zipped %s -> %s", observed_gtfs_dir, zip_path.name)
    return real_agencies, real_routes, real_trips, real_stops, real_stop_times, real_calendar, real_shapes
