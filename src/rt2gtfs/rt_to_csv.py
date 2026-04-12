
from __future__ import annotations

from itertools import chain
from multiprocessing import Pool
from pathlib import Path
import os
import zipfile
from collections.abc import Sequence

import pandas as pd

from .config import MatchingConfig
from .logging_utils import get_logger


def _rt_filepaths_to_list(directory: Path, date_str: str, file_extension: str = ".bin") -> list[Path]:
    filepaths: list[Path] = []
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(file_extension) and date_str in file:
                filepaths.append(Path(root) / file)
    return sorted(filepaths)


def _process_rt_file(filepath: Path) -> list[dict]:
    from google.transit import gtfs_realtime_pb2

    entities: list[dict] = []
    feed = gtfs_realtime_pb2.FeedMessage()

    with open(filepath, "rb") as file_obj:
        feed.ParseFromString(file_obj.read())

    for entity in feed.entity:
        if not entity.HasField("vehicle"):
            continue

        vehicle = entity.vehicle
        entities.append(
            {
                "trip_id": vehicle.trip.trip_id or None,
                "start_time": vehicle.trip.start_time or None,
                "start_date": vehicle.trip.start_date or None,
                "schedule_relationship": int(vehicle.trip.schedule_relationship)
                if vehicle.trip.HasField("schedule_relationship")
                else None,
                "route_id": vehicle.trip.route_id or None,
                "latitude": vehicle.position.latitude if vehicle.HasField("position") else None,
                "longitude": vehicle.position.longitude if vehicle.HasField("position") else None,
                "bearing": vehicle.position.bearing if vehicle.HasField("position") else None,
                "stop_sequence": vehicle.current_stop_sequence
                if vehicle.HasField("current_stop_sequence")
                else None,
                "status": int(vehicle.current_status)
                if vehicle.HasField("current_status")
                else None,
                "timestamp": int(vehicle.timestamp) if vehicle.HasField("timestamp") else None,
                "vehicle_id": vehicle.vehicle.id if vehicle.HasField("vehicle") else None,
            }
        )

    return entities


def _safe_process_rt_file(args: tuple[Path, str]) -> list[dict]:
    filepath, logger_name = args
    logger = get_logger(logger_name)
    try:
        return _process_rt_file(filepath)
    except Exception as exc:
        logger.warning("Failed to process %s: %s", filepath, exc)
        return []


def _unzip_rt_dir(rt_dir: Path, logger=None) -> None:
    logger = logger or get_logger(__name__)

    bad_files = 0
    total_files = 0

    for zip_path in rt_dir.iterdir():
        if zip_path.suffix.lower() != ".zip":
            continue

        total_files += 1

        if not zipfile.is_zipfile(zip_path):
            bad_files += 1
            logger.warning("Skipping bad file: %s (not a valid zip)", zip_path.name)
            continue

        try:
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                extracted_files = zip_ref.namelist()
                zip_ref.extractall(rt_dir)

            if len(extracted_files) == 1:
                original_file = rt_dir / extracted_files[0]
                new_path = rt_dir / f"{zip_path.stem}.bin"
                if original_file.exists() and original_file != new_path:
                    new_path.parent.mkdir(parents=True, exist_ok=True)
                    original_file.rename(new_path)
                    logger.info("Extracted %s and renamed to %s", zip_path.name, new_path.name)
            else:
                logger.warning("%s contains multiple files, skipping rename", zip_path.name)
        except Exception as exc:
            bad_files += 1
            logger.warning("Error processing %s: %s", zip_path.name, exc)

    logger.info(
        "Finished unzip step: %s processed successfully, %s bad files skipped",
        total_files - bad_files,
        bad_files,
    )


def _remove_duplicate_rt_observations(df: pd.DataFrame, logger=None) -> pd.DataFrame:
    logger = logger or get_logger(__name__)

    if df.empty:
        return df

    df = df.sort_values(by=["vehicle_id", "timestamp", "trip_id"], ascending=True).copy()
    total_before = len(df)
    df = df.drop_duplicates(
        subset=["longitude", "latitude", "timestamp", "vehicle_id", "trip_id"],
        keep="first",
    ).copy()
    total_after = len(df)
    fraction_duplicated = 1 - (total_after / total_before) if total_before else 0.0

    logger.info(
        "Removed duplicate RT observations: %s of %s rows removed (%.4f)",
        total_before - total_after,
        total_before,
        fraction_duplicated,
    )
    return df


def _convert_rt_to_csv_single(date: str | int, config: MatchingConfig) -> Path | None:
    normalized = config.normalized()
    date = str(date)

    log_file = normalized.rt_dir / normalized.log_file_name.format(date=date)
    logger = get_logger(
        name="rt2gtfs.rt_to_csv",
        level=normalized.log_level,
        log_to_file=normalized.log_to_file,
        log_file=log_file,
    )

    rt_date_dir = normalized.rt_dir / normalized.rt_foldername_template.format(date=date)
    output_csv = normalized.rt_dir / normalized.output_rt_csv_dirname / normalized.rt_csv_filename_template.format(date=date)

    logger.info("%s: Starting RT to CSV conversion", date)

    if not rt_date_dir.exists():
        logger.warning("%s: Input folder does not exist: %s", date, rt_date_dir)
        return None

    if normalized.unzip_rt:
        _unzip_rt_dir(rt_date_dir, logger=logger)

    filepaths = _rt_filepaths_to_list(rt_date_dir, date, normalized.rt_file_extension)
    logger.info("%s: Found %s RT files", date, len(filepaths))

    if not filepaths:
        logger.warning("%s: No RT files found", date)
        return None

    n_workers = max(1, int(normalized.n_workers))
    with Pool(processes=n_workers) as pool:
        results = pool.map(_safe_process_rt_file, [(path, logger.name) for path in filepaths])

    all_entities = list(chain.from_iterable(results))
    logger.info("%s: Collected %s raw vehicle entities", date, len(all_entities))

    if not all_entities:
        logger.warning("%s: No entities found; CSV not written", date)
        return None

    df = pd.DataFrame(all_entities)
    if normalized.deduplicate_rt:
        df = _remove_duplicate_rt_observations(df, logger=logger)

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_csv, index=False)
    logger.info("%s: Finished writing CSV to %s", date, output_csv)
    return output_csv


def convert_rt_to_csv(dates: str | int | Sequence[str | int], config: MatchingConfig) -> Path | None | list[Path]:
    if isinstance(dates, (str, int)):
        return _convert_rt_to_csv_single(dates, config)

    dates = [str(d) for d in dates]
    if not dates:
        return []

    outputs: list[Path] = []
    for date in dates:
        output = _convert_rt_to_csv_single(date, config)
        if output is not None:
            outputs.append(output)
    return outputs
