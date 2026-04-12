import pytest
import pandas as pd

from rt2gtfs.time_utils import (
    calculate_time_diff,
    generate_date_range,
    gtfs_to_unix_timestamp,
    unix_to_gtfs_timestamp,
)


class TestGenerateDateRange:
    def test_generate_date_range_all(self):
        assert generate_date_range("20250901", "20250903") == [
            "20250901",
            "20250902",
            "20250903",
        ]

    def test_generate_date_range_single_day(self):
        assert generate_date_range("20250902", "20250902") == ["20250902"]

    def test_generate_date_range_reverse(self):
        assert generate_date_range("20250901", "20250903", reverse=True) == [
            "20250903",
            "20250902",
            "20250901",
        ]

    def test_generate_date_range_weekday(self):
        # 2025-09-01 to 2025-09-07 is Mon to Sun
        assert generate_date_range("20250901", "20250907", mode="weekday") == [
            "20250901",
            "20250902",
            "20250903",
            "20250904",
            "20250905",
        ]

    def test_generate_date_range_weekend(self):
        assert generate_date_range("20250901", "20250907", mode="weekend") == [
            "20250906",
            "20250907",
        ]

    def test_generate_date_range_saturday(self):
        assert generate_date_range("20250901", "20250907", mode="saturday") == [
            "20250906",
        ]

    def test_generate_date_range_mode_case_insensitive(self):
        assert generate_date_range("20250901", "20250907", mode="WEEKDAY") == [
            "20250901",
            "20250902",
            "20250903",
            "20250904",
            "20250905",
        ]

    def test_generate_date_range_raises_for_end_before_start(self):
        with pytest.raises(ValueError, match="end_date must be on or after start_date"):
            generate_date_range("20250903", "20250901")

    def test_generate_date_range_raises_for_invalid_mode(self):
        with pytest.raises(ValueError, match="mode must be one of"):
            generate_date_range("20250901", "20250903", mode="monthly")


class TestGtfsToUnixTimestamp:
    def test_gtfs_to_unix_timestamp_after_midnight(self):
        ts1 = gtfs_to_unix_timestamp("23:00:00", "20250902")
        ts2 = gtfs_to_unix_timestamp("25:00:00", "20250902")
        assert ts2 > ts1

    def test_gtfs_to_unix_timestamp_one_hour_difference(self):
        ts1 = gtfs_to_unix_timestamp("10:00:00", "20250902")
        ts2 = gtfs_to_unix_timestamp("11:00:00", "20250902")
        assert ts2 - ts1 == 3600

    def test_gtfs_to_unix_timestamp_24_plus_time(self):
        ts1 = gtfs_to_unix_timestamp("24:00:00", "20250902")
        ts2 = gtfs_to_unix_timestamp("26:30:00", "20250902")
        assert ts2 - ts1 == 9000  # 2.5 hours

    def test_gtfs_to_unix_timestamp_invalid_time_string(self):
        with pytest.raises(ValueError):
            gtfs_to_unix_timestamp("not-a-time", "20250902")


class TestCalculateTimeDiff:
    def test_calculate_time_diff_winter_london(self):
        assert calculate_time_diff("20250115", "Europe/London") == 0

    def test_calculate_time_diff_summer_london(self):
        assert calculate_time_diff("20250715", "Europe/London") == 1


class TestUnixToGtfsTimestamp:
    def test_unix_to_gtfs_timestamp_same_day(self):
        ts = gtfs_to_unix_timestamp("10:15:30", "20250902")
        result = unix_to_gtfs_timestamp([ts], "20250902", time_diff=calculate_time_diff("20250902"))
        assert result.tolist() == ["10:15:30"]

    def test_unix_to_gtfs_timestamp_after_midnight_gtfs_format(self):
        ts = gtfs_to_unix_timestamp("25:10:05", "20250902")
        result = unix_to_gtfs_timestamp([ts], "20250902", time_diff=calculate_time_diff("20250902"))
        assert result.tolist() == ["25:10:05"]

    def test_unix_to_gtfs_timestamp_multiple_values(self):
        ts1 = gtfs_to_unix_timestamp("08:00:00", "20250902")
        ts2 = gtfs_to_unix_timestamp("09:30:15", "20250902")
        result = unix_to_gtfs_timestamp(
            [ts1, ts2],
            "20250902",
            time_diff=calculate_time_diff("20250902"),
        )
        assert result.tolist() == ["08:00:00", "09:30:15"]

    def test_unix_to_gtfs_timestamp_round_trip(self):
        original = ["00:00:00", "12:34:56", "24:05:00", "27:15:30"]
        unix_values = [gtfs_to_unix_timestamp(t, "20250902") for t in original]
        converted = unix_to_gtfs_timestamp(
            unix_values,
            "20250902",
            time_diff=calculate_time_diff("20250902"),
        )
        assert converted.tolist() == original

    def test_unix_to_gtfs_timestamp_accepts_series_input(self):
        times = ["07:00:00", "08:45:00"]
        unix_values = pd.Series([gtfs_to_unix_timestamp(t, "20250902") for t in times])
        result = unix_to_gtfs_timestamp(
            unix_values,
            "20250902",
            time_diff=calculate_time_diff("20250902"),
        )
        assert result.tolist() == times