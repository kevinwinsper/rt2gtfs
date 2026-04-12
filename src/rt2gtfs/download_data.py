
from __future__ import annotations

import time
import zipfile
from pathlib import Path
from datetime import datetime

import requests
from bods_client.client import BODSClient
from bods_client.models import APIError, BoundingBox, GTFSRTParams
from google.transit import gtfs_realtime_pb2

from .logging_utils import get_logger


DEFAULT_UK_BOUNDING_BOX = BoundingBox(
    min_longitude=-8.6,
    min_latitude=49.9,
    max_longitude=1.8,
    max_latitude=60.9,
)

FULL_GTFSRT_URL = "https://data.bus-data.dft.gov.uk/avl/download/gtfsrt"
FULL_GTFS_URL = "https://data.bus-data.dft.gov.uk/timetable/download/gtfs-file/all/"

def make_bounding_box(
    min_longitude: float,
    min_latitude: float,
    max_longitude: float,
    max_latitude: float,
) -> BoundingBox:
    """
    Create a BODS BoundingBox object from coordinate bounds.
    """
    return BoundingBox(
        min_longitude=min_longitude,
        min_latitude=min_latitude,
        max_longitude=max_longitude,
        max_latitude=max_latitude,
    )


def _current_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")

def _current_date() -> str:
    return datetime.now().strftime("%Y%m%d")


def _fetch_gtfsrt_data(
    api_key: str,
    bounding_box: BoundingBox,
    logger,
) -> gtfs_realtime_pb2.FeedMessage | APIError | None:
    bods = BODSClient(api_key=api_key)
    params = GTFSRTParams(bounding_box=bounding_box)

    try:
        return bods.get_gtfs_rt_data_feed(params=params)
    except requests.exceptions.RequestException:
        logger.exception("Failed to fetch GTFS-RT data from BODS")
        return None


def _save_gtfsrt_data(
    msg: gtfs_realtime_pb2.FeedMessage,
    output_dir: Path,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = _current_timestamp()
    zip_path = output_dir / f"{timestamp}.zip"

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zipf:
        zipf.writestr(f"{timestamp}.bin", msg.SerializeToString())

    return zip_path


def download_custom_gtfsrt(
    api_key: str,
    output_dir: str | Path,
    bounding_box: BoundingBox | None = None,
    logger=None,
) -> Path | None:
    logger = logger or get_logger(__name__)
    output_dir = Path(output_dir)
    bounding_box = bounding_box or DEFAULT_UK_BOUNDING_BOX

    msg = _fetch_gtfsrt_data(
        api_key=api_key,
        bounding_box=bounding_box,
        logger=logger,
    )

    if (
        msg is not None
        and not isinstance(msg, APIError)
        and isinstance(msg, gtfs_realtime_pb2.FeedMessage)
    ):
        saved_path = _save_gtfsrt_data(msg, output_dir)
        logger.info("Saved GTFS-RT feed to %s", saved_path)
        return saved_path

    logger.warning("Failed to download valid GTFS-RT feed")
    return None


def download_custom_gtfsrt_continuously(
    api_key: str,
    output_dir: str | Path,
    interval_seconds: int = 25,
    retry_interval_seconds: int = 1,
    bounding_box: BoundingBox | None = None,
    logger=None,
) -> None:
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be > 0")
    if retry_interval_seconds <= 0:
        raise ValueError("retry_interval_seconds must be > 0")

    logger = logger or get_logger(__name__)
    output_dir = Path(output_dir)
    bounding_box = bounding_box or DEFAULT_UK_BOUNDING_BOX

    logger.info("Starting GTFS-RT download loop")
    logger.info("Output directory: %s", output_dir.resolve())

    try:
        while True:
            saved_path = download_custom_gtfsrt(
                api_key=api_key,
                output_dir=output_dir,
                bounding_box=bounding_box,
                logger=logger,
            )

            if saved_path is not None:
                time.sleep(interval_seconds)
            else:
                logger.warning(
                    "Download failed. Retrying in %s second(s)",
                    retry_interval_seconds,
                )
                time.sleep(retry_interval_seconds)

    except KeyboardInterrupt:
        logger.info("Download loop stopped by user")


def _download_file_from_url(
    url: str,
    output_dir: Path,
    logger,
    filename: str | None = None,
    request_timeout: int = 30,
) -> Path | None:
    """
    Download a file once from a URL and save it locally.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    if filename is None:
        filename = f"{_current_timestamp()}.zip"

    save_path = output_dir / filename

    try:
        response = requests.get(url, timeout=request_timeout)
        response.raise_for_status()

        with open(save_path, "wb") as f:
            f.write(response.content)

        logger.info("Downloaded file to %s", save_path)
        return save_path

    except requests.exceptions.RequestException:
        logger.exception("Failed to download file from %s", url)
        return None


def _download_file_continuously(
    url: str,
    output_dir: Path,
    logger,
    interval_seconds: int,
    filename_func=None,
    request_timeout: int = 30,
    retry_interval_seconds: int = 1,
) -> list[Path]:
    
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be > 0")
    if request_timeout <= 0:
        raise ValueError("request_timeout must be > 0")

    downloaded_files: list[Path] = []

    logger.info(
        "Starting continuous download from %s every %s seconds",
        url,
        interval_seconds,
    )

    try:
        while True:
            filename = filename_func() if filename_func is not None else None

            result = _download_file_from_url(
                url=url,
                output_dir=output_dir,
                logger=logger,
                filename=filename,
                request_timeout=request_timeout,
            )

            if result is not None:
                downloaded_files.append(result)
                time.sleep(interval_seconds)
            else:
                logger.warning(
                    "Download failed. Retrying in %s second(s)",
                    retry_interval_seconds,
                )
                time.sleep(retry_interval_seconds)

    except KeyboardInterrupt:
        logger.info("Continuous download stopped by user")

    return downloaded_files


def download_gtfsrt_bulk(
    output_dir: str | Path,
    url: str = FULL_GTFSRT_URL,
    continuous: bool = False,
    interval_seconds: int = 30,
    request_timeout: int = 25,
    logger=None,
) -> Path | list[Path] | None:
    """
    Download the full UK GTFS-RT zip feed.

    Parameters
    ----------
    output_dir : str | Path
        Directory where files will be saved.
    url : str
        Download URL.
    continuous : bool, default False
        If True, keep downloading repeatedly at a fixed interval until interrupted.
        If False, download once only.
    interval_seconds : int, default 30
        Interval between downloads when continuous=True.
    request_timeout : int, default 25
        Timeout for each HTTP request.

    Returns
    -------
    Path | list[Path] | None
        One saved file path for one-off mode, a list of saved paths for continuous mode,
        or None if the one-off download fails.
    """
    logger = logger or get_logger(__name__)
    output_dir = Path(output_dir)

    if continuous:
        return _download_file_continuously(
            url=url,
            output_dir=output_dir,
            logger=logger,
            interval_seconds=interval_seconds,
            filename_func=lambda: f"{_current_timestamp()}.zip",
            request_timeout=request_timeout,
        )

    return _download_file_from_url(
        url=url,
        output_dir=output_dir,
        logger=logger,
        filename=f"{_current_timestamp()}.zip",
        request_timeout=request_timeout,
    )


def download_gtfs_bulk(
    output_dir: str | Path,
    url: str = FULL_GTFS_URL,
    continuous: bool = False,
    interval_seconds: int = 86400,
    request_timeout: int = 25,
    logger=None,
) -> Path | list[Path] | None:
    """
    Download the full UK GTFS zip feed.

    Parameters
    ----------
    output_dir : str | Path
        Directory where files will be saved.
    url : str
        Download URL.
    continuous : bool, default False
        If True, keep downloading repeatedly at a fixed interval until interrupted.
        If False, download once only.
    interval_seconds : int, default 86400
        Interval between downloads when continuous=True.
    request_timeout : int, default 25
        Timeout for each HTTP request.

    Returns
    -------
    Path | list[Path] | None
        One saved file path for one-off mode, a list of saved paths for continuous mode,
        or None if the one-off download fails.
    """
    logger = logger or get_logger(__name__)
    output_dir = Path(output_dir)

    if continuous:
        return _download_file_continuously(
            url=url,
            output_dir=output_dir,
            logger=logger,
            interval_seconds=interval_seconds,
            filename_func=lambda: f"itm_all_gtfs_{_current_date()}.zip",
            request_timeout=request_timeout,
        )

    return _download_file_from_url(
        url=url,
        output_dir=output_dir,
        logger=logger,
        filename=f"itm_all_gtfs_{_current_date()}.zip",
        request_timeout=request_timeout,
    )