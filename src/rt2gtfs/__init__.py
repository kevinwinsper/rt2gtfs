"""rt2gtfs public package API."""

from .config import MatchingConfig
from .pipeline import construct_observed_gtfs
from .time_utils import generate_date_range

__all__ = [
    "MatchingConfig",
    "generate_date_range",
    "construct_observed_gtfs",
    "convert_rt_to_csv",
]


def convert_rt_to_csv(*args, **kwargs):
    from .rt_to_csv import convert_rt_to_csv as _convert_rt_to_csv

    return _convert_rt_to_csv(*args, **kwargs)
