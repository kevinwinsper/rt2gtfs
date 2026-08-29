from unittest.mock import Mock

import pandas as pd

from rt2gtfs.config import MatchingConfig
from rt2gtfs.pipeline import (
    _load_realtime_observations,
    _merge_matches_with_schedule_data,
    _write_observed_gtfs,
)
from rt2gtfs.time_utils import gtfs_to_unix_timestamp


def test_load_realtime_observations_keeps_next_day_for_service_date(tmp_path):
    service_date = "20260722"
    observations = pd.DataFrame([{
        "start_date": service_date,
        "trip_id": "overnight-trip",
        "route_id": "route-1",
        "timestamp": gtfs_to_unix_timestamp("26:00:00", service_date),
    }])
    observations.to_csv(tmp_path / f"rt_{service_date}.csv", index=False)
    config = MatchingConfig(gtfs_dir=tmp_path, rt_dir=tmp_path, result_dir=tmp_path)

    result = _load_realtime_observations(service_date, config, Mock(), Mock())

    assert result["trip_id"].tolist() == ["overnight-trip"]
    assert result["timestamp_dt"].dt.strftime("%Y%m%d %H:%M:%S").tolist() == [
        "20260723 02:00:00"
    ]


def test_load_realtime_observations_does_not_trust_supplier_start_date(tmp_path):
    service_date = "20260722"
    observations = pd.DataFrame([{
        "start_date": "20260723",
        "trip_id": "next-day-trip",
        "route_id": "route-1",
        "timestamp": gtfs_to_unix_timestamp("26:00:00", service_date),
    }])
    observations.to_csv(tmp_path / f"rt_{service_date}.csv", index=False)
    config = MatchingConfig(gtfs_dir=tmp_path, rt_dir=tmp_path, result_dir=tmp_path)

    result = _load_realtime_observations(service_date, config, Mock(), Mock())

    assert result["trip_id"].tolist() == ["next-day-trip"]


def _merge_single_match(tmp_path, static_time: str):
    service_date = "20260722"
    timestamp = gtfs_to_unix_timestamp("24:02:00", service_date)
    matching_df = pd.DataFrame([{
        "trip_id": "trip-1",
        "route_id": "route-1",
        "nearest_stop_id": "stop-1",
        "distance": 10.0,
        "timestamp": timestamp,
        "timestamp_dt": pd.to_datetime(timestamp, unit="s", utc=True).tz_convert("Europe/London"),
        "vehicle_id": "vehicle-1",
    }])
    scheduled_gtfs = {"stop_times": pd.DataFrame([{
        "trip_id": "trip-1",
        "stop_id": "stop-1",
        "stop_sequence": 1,
        "arrival_time": static_time,
        "departure_time": static_time,
    }])}
    config = MatchingConfig(
        gtfs_dir=tmp_path,
        rt_dir=tmp_path,
        result_dir=tmp_path,
        output_stop_level_delay=False,
    )
    result = _merge_matches_with_schedule_data(
        service_date, matching_df, scheduled_gtfs, config, Mock(), Mock()
    )
    return result, timestamp


def test_merge_shifts_early_static_time_for_next_day_observation(tmp_path):
    result, timestamp = _merge_single_match(tmp_path, "00:02:00")

    assert result["schedule_day_shift"].tolist() == [1]
    assert result["unix_arrival_time"].tolist() == [timestamp]
    assert result["delay"].tolist() == [0]


def test_merge_does_not_shift_already_extended_static_time(tmp_path):
    result, timestamp = _merge_single_match(tmp_path, "24:02:00")

    assert result["schedule_day_shift"].tolist() == [0]
    assert result["unix_arrival_time"].tolist() == [timestamp]


def test_write_observed_gtfs_creates_matched_and_unmatched_variants(tmp_path, monkeypatch):
    calls = []

    def fake_create_observed_timetable(*args, **kwargs):
        calls.append({"observed_gtfs_dir": args[3], **kwargs})
        return kwargs["include_unmatched_trips"]

    monkeypatch.setattr(
        "rt2gtfs.pipeline.create_observed_timetable",
        fake_create_observed_timetable,
    )
    config = MatchingConfig(
        gtfs_dir=tmp_path,
        rt_dir=tmp_path,
        result_dir=tmp_path,
        include_unmatched_trips=True,
    )

    result = _write_observed_gtfs("20260722", {}, pd.DataFrame(), config, Mock())

    assert result == (False, True)
    assert len(calls) == 2
    assert calls[0]["include_unmatched_trips"] is False
    assert calls[0].get("output_zip_name") is None
    assert calls[1]["include_unmatched_trips"] is True
    assert calls[1]["output_zip_name"] == "england_20260722_with_unmatched.zip"
    assert str(calls[0]["observed_gtfs_dir"]).endswith("/england/20260722")
    assert str(calls[1]["observed_gtfs_dir"]).endswith("/england/20260722_with_unmatched")
