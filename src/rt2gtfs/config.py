
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class MatchingConfig:
    gtfs_dir: Path
    rt_dir: Path
    result_dir: Path
    timetable_region: str = "england"
    gtfs_filename_template: str = "itm_all_gtfs_{date}"
    rt_csv_filename_template: str = "rt_{date}.csv"
    rt_foldername_template: str = "{date}"
    naptan_path: Path | None = None
    use_naptan: bool = False
    check_extra_dates: bool = False
    time_window_days: int = 7
    extra_dates: list[str] | None = None
    matching_periods: list[tuple[str, str]] | None = None
    search_radius_m: int = 300
    output_stop_level_delay: bool = True
    extrapolate_stop_times: bool = True
    time_zone: str = "Europe/London"
    include_interpolated_column: bool = True
    max_valid_gtfs_hour: int = 28
    log_to_file: bool = False
    log_file_name: str = "{date}.log"
    stats_file_name: str = "stats_{date}.txt"
    n_workers: int = 8
    unzip_rt: bool = True
    output_rt_csv_dirname: str = "csv"
    deduplicate_rt: bool = True
    rt_file_extension: str = ".bin"
    log_level: str = "INFO"

    def normalized(self) -> "MatchingConfig":
        return MatchingConfig(
            gtfs_dir=Path(self.gtfs_dir).expanduser(),
            rt_dir=Path(self.rt_dir).expanduser(),
            result_dir=Path(self.result_dir).expanduser(),
            timetable_region=self.timetable_region,
            gtfs_filename_template=self.gtfs_filename_template,
            rt_csv_filename_template=self.rt_csv_filename_template,
            rt_foldername_template=self.rt_foldername_template,
            naptan_path=Path(self.naptan_path).expanduser() if self.naptan_path else None,
            use_naptan=self.use_naptan,
            check_extra_dates=self.check_extra_dates,
            time_window_days=self.time_window_days,
            extra_dates=list(self.extra_dates) if self.extra_dates else None,
            matching_periods=list(self.matching_periods) if self.matching_periods else None,
            search_radius_m=self.search_radius_m,
            output_stop_level_delay=self.output_stop_level_delay,
            extrapolate_stop_times=self.extrapolate_stop_times,
            time_zone=self.time_zone,
            include_interpolated_column=self.include_interpolated_column,
            max_valid_gtfs_hour=self.max_valid_gtfs_hour,
            log_to_file=self.log_to_file,
            log_file_name=self.log_file_name,
            stats_file_name=self.stats_file_name,
            n_workers=self.n_workers,
            unzip_rt=self.unzip_rt,
            output_rt_csv_dirname=self.output_rt_csv_dirname,
            deduplicate_rt=self.deduplicate_rt,
            rt_file_extension=self.rt_file_extension,
            log_level=self.log_level,
        )
