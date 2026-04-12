
from __future__ import annotations

from functools import partial
from pathlib import Path
import multiprocessing
import os
from collections.abc import Sequence

import pandas as pd

from .config import MatchingConfig
from .gtfs_utils import create_lookups, create_lookups_with_time_window, create_observed_timetable, load_full_gtfs, load_multiple_gtfs
from .interpolation import fill_real_time
from .logging_utils import get_logger, get_stats_logger
from .matching import inspect_rt_data
from .time_utils import gtfs_to_unix_timestamp, calculate_time_diff, unix_to_gtfs_timestamp


def _build_lookup_tables(date_to_match: str, config: MatchingConfig, logger):
    trip_to_stop_lookup, stop_to_stoploc_lookup = create_lookups(
        date_to_match,
        config.gtfs_dir,
        gtfs_filename_template=config.gtfs_filename_template,
        use_naptan=config.use_naptan,
        naptan_path=config.naptan_path,
        logger=logger,
    )

    if config.check_extra_dates:
        logger.info("%s: Creating dictionaries across dates", date_to_match)
        all_trip_to_stop_lookup, all_stop_to_stoploc_lookup, trip_source_dates, _ = create_lookups_with_time_window(
            date_to_match,
            config.gtfs_dir,
            time_window_days=config.time_window_days,
            extra_dates=config.extra_dates,
            gtfs_filename_template=config.gtfs_filename_template,
            use_naptan=config.use_naptan,
            naptan_path=config.naptan_path,
            logger=logger,
        )
    else:
        all_trip_to_stop_lookup, all_stop_to_stoploc_lookup, trip_source_dates = {}, {}, {}

    logger.info("%s: Finished creating dictionaries", date_to_match)
    return trip_to_stop_lookup, stop_to_stoploc_lookup, all_trip_to_stop_lookup, all_stop_to_stoploc_lookup, trip_source_dates


def _load_realtime_observations(
        date_to_match: str,
        config: MatchingConfig,
        logger,
        stats_logger) -> pd.DataFrame:
    rt_df = pd.read_csv(
        config.rt_dir / config.rt_csv_filename_template.format(date=date_to_match),
        dtype={"start_date": str},
        low_memory=False,
    )

    if rt_df.empty:
        logger.warning("%s: Realtime CSV is empty", date_to_match)
        return rt_df

    # Convert Unix timestamp to timezone-aware local datetime
    rt_df["timestamp_dt"] = (
        pd.to_datetime(rt_df["timestamp"], unit="s", utc=True)
        .dt.tz_convert(config.time_zone)
    )

    clean_rt_df = rt_df[
        (rt_df.start_date == date_to_match) & (rt_df.timestamp_dt.dt.date == pd.to_datetime(date_to_match).date()) & (rt_df.trip_id.notna())
    ].copy()

    pct = round(len(clean_rt_df) * 100 / len(rt_df), 3) if len(rt_df) else 0.0
    logger.info("%s: Percentage of location data with matchable trip_id: %s %%", date_to_match, pct)
    stats_logger.info("%s: Percentage of location data with matchable trip_id: %s %% \n", date_to_match, pct)

    filtered_rt_df = clean_rt_df.copy()
    if config.matching_periods:
        time_mask = pd.Series(False, index=clean_rt_df.index)
        for start_time, end_time in config.matching_periods:
            start_ts = gtfs_to_unix_timestamp(start_time, date_to_match, geo=config.time_zone)
            end_ts = gtfs_to_unix_timestamp(end_time, date_to_match, geo=config.time_zone)
            time_mask |= clean_rt_df["timestamp"].between(start_ts, end_ts)
        filtered_rt_df = clean_rt_df[time_mask].copy()
    pct2 = round(len(filtered_rt_df) * 100 / len(clean_rt_df), 3) if len(clean_rt_df) else 0.0
    logger.info("%s: Percentage of location data within the specified time period(s): %s %%", date_to_match, pct2)
    stats_logger.info("%s: Percentage of location data within the specified time period(s): %s %% \n", date_to_match, pct2)

    return filtered_rt_df


def _load_scheduled_gtfs(
    date_to_match: str,
    config: MatchingConfig,
    timetable_dates: list[str] | None = None,
) -> dict:
    if config.check_extra_dates:
        if not timetable_dates:
            raise ValueError("timetable_dates must be provided when check_extra_dates=True")

        agencies, routes, trips, stops, stop_times, calendar, calendar_dates, feed_info, shapes = load_multiple_gtfs(
            gtfs_dir=config.gtfs_dir,
            dates=timetable_dates,
            gtfs_filename_template=config.gtfs_filename_template,
            priority_date=date_to_match,
        )
    else:
        agencies, routes, trips, stops, stop_times, calendar, calendar_dates, feed_info, shapes = load_full_gtfs(
            gtfs_dir=config.gtfs_dir,
            date_to_match=date_to_match,
            gtfs_filename_template=config.gtfs_filename_template,
            include=["feed_info.txt", "shapes.txt"],
        )

    return {
        "agencies": agencies,
        "routes": routes,
        "trips": trips,
        "stops": stops,
        "stop_times": stop_times,
        "calendar": calendar,
        "calendar_dates": calendar_dates,
        "feed_info": feed_info,
        "shapes": shapes,
    }


def _merge_matches_with_schedule_data(
    date_to_match: str,
    matching_df: pd.DataFrame,
    scheduled_gtfs: dict,
    config: MatchingConfig,
    logger,
    stats_logger,
) -> pd.DataFrame:
    stop_times = scheduled_gtfs["stop_times"]
    
    matching_df_min = matching_df.loc[
        matching_df.groupby(['trip_id', 'route_id', 'nearest_stop_id'])['distance'].idxmin()
    ].sort_index()

    # Convert route_id to int64
    # TO_DO: Ideally when reading GTFS data types should be specified
    matching_df_min["route_id"] = matching_df_min["route_id"].astype("Int64")

    matching_df_min.rename(columns={'nearest_stop_id': 'stop_id'}, inplace=True)

    complete_stop_time_data = stop_times.merge(matching_df_min, on=['trip_id', 'stop_id'], how='left')
    complete_stop_time_data.sort_values(by=["trip_id", "stop_sequence"], ascending=True, inplace=True)
    complete_stop_time_data = complete_stop_time_data.groupby(["trip_id"]).filter(
        lambda group: group["timestamp"].notna().any()
    )

    complete_stop_time_data["unix_arrival_time"] = complete_stop_time_data["arrival_time"].apply(
        lambda value: gtfs_to_unix_timestamp(value, date_to_match, geo=config.time_zone)
    )
    complete_stop_time_data["unix_departure_time"] = complete_stop_time_data["departure_time"].apply(
        lambda value: gtfs_to_unix_timestamp(value, date_to_match, geo=config.time_zone)
    )
    complete_stop_time_data["delay_abs"] = (
        complete_stop_time_data["timestamp"] - complete_stop_time_data["unix_arrival_time"]
    ).abs()
    complete_stop_time_data["delay_abs_min"] = round(complete_stop_time_data["delay_abs"] / 60, 2)
    complete_stop_time_data["delay"] = complete_stop_time_data["timestamp"] - complete_stop_time_data["unix_arrival_time"]
    complete_stop_time_data["delay_min"] = round(complete_stop_time_data["delay"] / 60, 2)

    if config.output_stop_level_delay:
        stats_dir = config.result_dir / "matching_stats"
        stats_dir.mkdir(parents=True, exist_ok=True)
        complete_stop_time_data.to_csv(stats_dir / f"delay_details_{date_to_match}.csv", index=False)
    logger.info("%s: Average time of delay (abs): %s minutes", date_to_match, round(complete_stop_time_data["delay_abs"].mean() / 60, 2))
    stats_logger.info("%s: Average time of delay (abs): %s minutes \n", date_to_match, round(complete_stop_time_data["delay_abs"].mean() / 60, 2))
    logger.info("%s: Average time of delay: %s minutes", date_to_match, round(complete_stop_time_data["delay"].mean() / 60, 2))
    stats_logger.info("%s: Average time of delay: %s minutes \n", date_to_match, round(complete_stop_time_data["delay"].mean() / 60, 2))

    return complete_stop_time_data


def _clean_timestamp_anomalies(complete_stop_time_data: pd.DataFrame) -> pd.DataFrame:
    complete_stop_time_data = complete_stop_time_data.copy()

    # drop timestamps anomolies
    # Per-trip robust threshold: median + 1*MAD (or pick a fixed threshold if you prefer)
    def trip_threshold(series):
        med = series.median()
        mad = (series - med).abs().median()
        return med + 1 * mad

    complete_stop_time_data["delta_thresh"] = complete_stop_time_data.groupby("trip_id")["delay_abs"].transform(trip_threshold)
    # Flag timestamps that are implausible given the schedule
    bad_vs_schedule = complete_stop_time_data["delay_abs"] > complete_stop_time_data["delta_thresh"]
    # Set offending rows to NA in all related columns
    cols_to_null = ["timestamp", "timestamp_dt"]
    existing_cols_to_null = [col for col in cols_to_null if col in complete_stop_time_data.columns]
    # Drop those timestamps first
    complete_stop_time_data.loc[bad_vs_schedule, existing_cols_to_null] = pd.NA

    # check that timestamps are not decreasing as stop sequence increases
    # Compute previous cumulative maximum timestamp per trip
    prev_cummax = complete_stop_time_data.groupby("trip_id")["timestamp"].transform(lambda s: s.ffill().cummax().shift(1))
    # Find violations: when current timestamp < any earlier timestamp in same trip
    violation = complete_stop_time_data["timestamp"] < prev_cummax
    complete_stop_time_data.loc[violation.fillna(False), existing_cols_to_null] = pd.NA
    return complete_stop_time_data


def _interpolate_stop_times(
    date_to_match: str,
    stop_time_data: pd.DataFrame,
    config: MatchingConfig,
    logger,
) -> pd.DataFrame:
    logger.info("%s: Applying interpolation", date_to_match)

    if stop_time_data.empty:
        logger.info("%s: No stop time data available for interpolation", date_to_match)
        return stop_time_data.copy()
    
    interpolated_parts = []
    for _, group in stop_time_data.groupby("trip_id", sort=False):
        interpolated_group = fill_real_time(
            group,
            extrapolate=config.extrapolate_stop_times,
        )
        interpolated_parts.append(interpolated_group)

    interpolated = pd.concat(interpolated_parts, ignore_index=False)

    logger.info("%s: Finished interpolation", date_to_match)
    return interpolated


def _finalize_observed_timetable(date_to_match: str, interpolated_data: pd.DataFrame, config: MatchingConfig) -> pd.DataFrame:
    interpolated_data = interpolated_data.copy()
    hours = interpolated_data["arrival_time"].str.extract(r"^(\d+):")[0].astype(int)
    interpolated_data = interpolated_data[hours < (config.max_valid_gtfs_hour + 1)]

    interpolated_data["final_arrival_time"] = interpolated_data["timestamp"].combine_first(interpolated_data["interpolated_time"])
    interpolated_data["final_departure_time"] = interpolated_data["timestamp"].combine_first(interpolated_data["interpolated_time"])
    interpolated_data["interpolated"] = interpolated_data.apply(
        lambda row: "0" if pd.notna(row["timestamp"]) else ("1" if pd.notna(row["interpolated_time"]) else None),
        axis=1,
    )
    interpolated_data = interpolated_data[
        interpolated_data.final_arrival_time.notna() & interpolated_data.final_departure_time.notna()
    ]

    time_diff = int(calculate_time_diff(str(date_to_match), geo=config.time_zone))
    interpolated_data["final_gtfs_arrival_time"] = unix_to_gtfs_timestamp(interpolated_data["final_arrival_time"], date_to_match, time_diff=time_diff)
    interpolated_data["final_gtfs_departure_time"] = unix_to_gtfs_timestamp(interpolated_data["final_departure_time"], date_to_match, time_diff=time_diff)
    interpolated_data["arrival_time"] = interpolated_data["final_gtfs_arrival_time"]
    interpolated_data["departure_time"] = interpolated_data["final_gtfs_departure_time"]

    stop_counts = interpolated_data.groupby("trip_id")["stop_id"].count()
    trip_ids_with_one_stop = stop_counts[stop_counts == 1].index.to_list()
    interpolated_data = interpolated_data[~interpolated_data.trip_id.isin(trip_ids_with_one_stop)]
    interpolated_data.sort_values(by=["trip_id", "stop_sequence"], ascending=True, inplace=True)
    interpolated_data = interpolated_data.drop_duplicates(
        subset=["trip_id", "stop_id", "arrival_time", "departure_time", "shape_dist_traveled"],
        keep="first",
    )

    columns = [
        "trip_id", "vehicle_id", "arrival_time", "departure_time", "stop_id", "stop_sequence",
        "stop_headsign", "pickup_type", "drop_off_type", "shape_dist_traveled", "timepoint", "route_id",
    ]
    if config.include_interpolated_column:
        columns.append("interpolated")
    existing_columns = [column for column in columns if column in interpolated_data.columns]
    return interpolated_data.loc[:, existing_columns].copy()


def _write_observed_gtfs(date_to_match: str, scheduled_gtfs: dict, realtime_timetable: pd.DataFrame, config: MatchingConfig, logger):
    observed_gtfs_dir = config.result_dir / config.timetable_region / date_to_match
    observed_gtfs_dir.mkdir(parents=True, exist_ok=True)
    return create_observed_timetable(
        scheduled_gtfs,
        realtime_timetable,
        config.result_dir,
        observed_gtfs_dir,
        config.timetable_region,
        date_to_match,
        interpolation_flag=config.include_interpolated_column,
        logger=logger,
    )


def _build_config(
    config: MatchingConfig | None = None,
    **kwargs,
) -> MatchingConfig:
    """
    Return a MatchingConfig either from an existing config object
    or by constructing one from keyword arguments.
    """
    if config is not None:
        if kwargs:
            unexpected = ", ".join(kwargs.keys())
            raise ValueError(
                f"Provide either 'config' or individual keyword arguments, not both. "
                f"Got extra arguments: {unexpected}"
            )
        return config

    try:
        return MatchingConfig(**kwargs)
    except TypeError as e:
        raise TypeError(
            "Could not construct MatchingConfig from the supplied keyword arguments. "
            "Please provide either a valid 'config' or the required config fields."
        ) from e
    

def _prepare_config(
        date_to_match: str | int,
        config: MatchingConfig) -> tuple[MatchingConfig, object, object]:
    normalized = config.normalized()
    normalized.result_dir.mkdir(parents=True, exist_ok=True)
    log_file = normalized.result_dir / normalized.log_file_name.format(date=date_to_match)
    logger = get_logger("rt2gtfs", level=normalized.log_level, log_to_file=normalized.log_to_file, log_file=log_file)

    stats_dir = normalized.result_dir / "matching_stats"
    stats_dir.mkdir(parents=True, exist_ok=True)
    stats_log_file = stats_dir / normalized.stats_file_name.format(date=date_to_match)
    stats_logger = get_stats_logger(f"stats_logger.{date_to_match}", stats_log_file)
    return normalized, logger, stats_logger


def _construct_observed_gtfs_single(date_to_match: str | int, config: MatchingConfig):
    config, logger, stats_logger = _prepare_config(date_to_match, config)

    date_to_match = str(date_to_match)
    logger.info("%s: Starting processing (PID: %s)", date_to_match, os.getpid())

    try:
        trip_to_stop_lookup, stop_to_stoploc_lookup, all_trip_to_stop_lookup, all_stop_to_stoploc_lookup, trip_source_dates = _build_lookup_tables(
            date_to_match, config, logger
        )
        filtered_rt_df = _load_realtime_observations(date_to_match, config, logger, stats_logger)

        matching_df, timetable_dates = inspect_rt_data(
            date_to_match,
            filtered_rt_df,
            trip_to_stop_lookup,
            stop_to_stoploc_lookup,
            all_trip_to_stop_lookup,
            all_stop_to_stoploc_lookup,
            trip_source_dates,
            result_dir=config.result_dir,
            radius_m=config.search_radius_m,
            check_extra_dates=config.check_extra_dates,
            logger=logger,
            stats_logger=stats_logger,
        )

        scheduled_gtfs = _load_scheduled_gtfs(date_to_match, config, timetable_dates)

        complete_stop_time_data = _merge_matches_with_schedule_data(
            date_to_match, matching_df, scheduled_gtfs, config, logger, stats_logger
        )

        complete_stop_time_data = _clean_timestamp_anomalies(complete_stop_time_data)

        interpolated_data = _interpolate_stop_times(
            date_to_match, complete_stop_time_data, config, logger
        )

        realtime_timetable = _finalize_observed_timetable(
            date_to_match, interpolated_data, config
        )

        _write_observed_gtfs(
            date_to_match, scheduled_gtfs, realtime_timetable, config, logger
        )

        logger.info("%s: Finished creating timetable", date_to_match)
        return None

    except Exception:
        logger.exception("%s: Failed while processing", date_to_match)
        return None


def construct_observed_gtfs(
    date_to_match: str | int | Sequence[str | int],
    config: MatchingConfig | None = None,
    workers: int | None = None,
    **config_kwargs,
):
    """
    Construct observed GTFS for one date or multiple dates.

    You can call this in two ways:

    1. With a MatchingConfig:
        construct_observed_gtfs("20250902", config=my_config)

    2. With direct keyword arguments for MatchingConfig:
        construct_observed_gtfs(
            "20250902",
            gtfs_dir="...",
            rt_dir="...",
            result_dir="...",
            search_radius_m=200,
            check_extra_dates=True,
        )

    Parameters
    ----------
    date_to_match
        A single date (e.g. "20250902") or a sequence of dates.
    config
        Matching configuration. Optional if config fields are supplied directly.
    workers
        Number of worker processes to use when multiple dates are provided.
        If None, defaults to min(8, cpu_count()).
    **config_kwargs
        Keyword arguments used to construct MatchingConfig when `config` is not provided.

    Returns
    -------
    pandas.DataFrame | list[pandas.DataFrame | None] | None
        For a single date, returns one timetable DataFrame or None on failure.
        For multiple dates, returns a list of results in the same order as input.
    """
    config = _build_config(config=config, **config_kwargs)

    # Single-date case
    if isinstance(date_to_match, (str, int)):
        return _construct_observed_gtfs_single(date_to_match, config=config)

    # Multi-date case
    dates = [str(d) for d in date_to_match]
    if not dates:
        return []

    workers = workers or config.n_workers or min(8, multiprocessing.cpu_count())

    # Avoid multiprocessing overhead if only one date
    if len(dates) == 1:
        return [_construct_observed_gtfs_single(dates[0], config=config)]

    worker_func = partial(_construct_observed_gtfs_single, config=config)

    with multiprocessing.Pool(processes=workers) as pool:
        return pool.map(worker_func, dates)