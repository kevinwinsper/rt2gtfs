
from __future__ import annotations

import argparse
from pathlib import Path

from .config import MatchingConfig
from .pipeline import construct_observed_gtfs
from .rt_to_csv import convert_rt_to_csv
from .time_utils import generate_date_range


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create observed GTFS timetables from RT vehicle positions.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    observed_parser = subparsers.add_parser("observed-gtfs", help="Create observed GTFS outputs")
    observed_parser.add_argument("--start-date", required=True, help="Start date in YYYYMMDD format")
    observed_parser.add_argument("--end-date", required=True, help="End date in YYYYMMDD format")
    observed_parser.add_argument("--gtfs-dir", required=True)
    observed_parser.add_argument("--rt-dir", required=True)
    observed_parser.add_argument("--result-dir", required=True)
    observed_parser.add_argument("--timetable-region", default="england")
    observed_parser.add_argument("--gtfs-filename-template", default="itm_all_gtfs_{date}")
    observed_parser.add_argument("--rt-csv-filename-template", default="rt_{date}.csv")
    observed_parser.add_argument("--use-naptan", action="store_true")
    observed_parser.add_argument("--naptan-path")
    observed_parser.add_argument("--check-extra-dates", action="store_true")
    observed_parser.add_argument("--time-window-days", type=int, default=7)
    observed_parser.add_argument("--search-radius-m", type=int, default=300)
    observed_parser.add_argument("--no-delay-stats", action="store_true")
    observed_parser.add_argument("--no-extrapolation", action="store_true")
    observed_parser.add_argument("--time-zone", default="Europe/London")
    observed_parser.add_argument("--exclude-interpolated-column", action="store_true")
    observed_parser.add_argument("--max-valid-gtfs-hour", type=int, default=28)
    observed_parser.add_argument("--workers", type=int, default=None)
    observed_parser.add_argument("--log-level", default="INFO")
    observed_parser.add_argument("--log-to-file", action="store_true")
    observed_parser.add_argument(
        "--matching-period",
        action="append",
        nargs=2,
        metavar=("START", "END"),
        help="Optional time window; can be provided more than once",
    )

    rt_csv_parser = subparsers.add_parser("rt-to-csv", help="Convert raw RT protobuf files to CSV")
    rt_csv_parser.add_argument("--start-date", required=True, help="Start date in YYYYMMDD format")
    rt_csv_parser.add_argument("--end-date", required=True, help="End date in YYYYMMDD format")
    rt_csv_parser.add_argument("--rt-dir", required=True)
    rt_csv_parser.add_argument("--result-dir", required=True)
    rt_csv_parser.add_argument("--workers", type=int, default=8)
    rt_csv_parser.add_argument("--no-unzip-rt", action="store_true")
    rt_csv_parser.add_argument("--no-deduplicate-rt", action="store_true")
    rt_csv_parser.add_argument("--output-rt-csv-dirname", default="csv")
    rt_csv_parser.add_argument("--rt-csv-filename-template", default="rt_{date}.csv")
    rt_csv_parser.add_argument("--rt-file-extension", default=".bin")
    rt_csv_parser.add_argument("--log-level", default="INFO")
    rt_csv_parser.add_argument("--log-to-file", action="store_true")

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "observed-gtfs":
        config = MatchingConfig(
            gtfs_dir=Path(args.gtfs_dir),
            rt_dir=Path(args.rt_dir),
            result_dir=Path(args.result_dir),
            timetable_region=args.timetable_region,
            gtfs_filename_template=args.gtfs_filename_template,
            rt_csv_filename_template=args.rt_csv_filename_template,
            naptan_path=Path(args.naptan_path) if args.naptan_path else None,
            use_naptan=args.use_naptan,
            check_extra_dates=args.check_extra_dates,
            time_window_days=args.time_window_days,
            matching_periods=args.matching_period,
            search_radius_m=args.search_radius_m,
            output_stop_level_delay=not args.no_delay_stats,
            extrapolate_stop_times=not args.no_extrapolation,
            time_zone=args.time_zone,
            include_interpolated_column=not args.exclude_interpolated_column,
            max_valid_gtfs_hour=args.max_valid_gtfs_hour,
            n_workers=args.workers or 8,
            log_to_file=args.log_to_file,
            log_level=args.log_level,
        )
        dates = generate_date_range(args.start_date, args.end_date)
        construct_observed_gtfs(dates, config, workers=args.workers)
        return

    if args.command == "rt-to-csv":
        config = MatchingConfig(
            gtfs_dir=Path("."),
            rt_dir=Path(args.rt_dir),
            result_dir=Path(args.result_dir),
            rt_csv_filename_template=args.rt_csv_filename_template,
            n_workers=args.workers,
            unzip_rt=not args.no_unzip_rt,
            deduplicate_rt=not args.no_deduplicate_rt,
            output_rt_csv_dirname=args.output_rt_csv_dirname,
            rt_file_extension=args.rt_file_extension,
            log_to_file=args.log_to_file,
            log_level=args.log_level,
        )
        dates = generate_date_range(args.start_date, args.end_date)
        convert_rt_to_csv(dates, config)
        return


if __name__ == "__main__":
    main()
