
# Functions in this script are adapted from code developed by Luke Strange & Stuart Lowe:
# https://github.com/open-innovations/bus-tracking
# Modifications have been made to fit this project.

from __future__ import annotations

import numpy as np
import pandas as pd


def interpolate_missing_times(row: pd.Series, extrapolate: bool = False):
    observed_now = row["timestamp"]
    if pd.notna(observed_now):
        return observed_now

    scheduled_now = row["unix_arrival_time"]
    observed_prev = row["observed_prev"]
    observed_next = row["observed_next"]
    scheduled_prev_anchor = row["scheduled_prev_anchor"]
    scheduled_next_anchor = row["scheduled_next_anchor"]

    if (
        pd.notna(scheduled_now)
        and pd.notna(observed_prev)
        and pd.notna(observed_next)
        and pd.notna(scheduled_prev_anchor)
        and pd.notna(scheduled_next_anchor)
    ):
        span = scheduled_next_anchor - scheduled_prev_anchor
        if span == 0:
            return np.nan
        fraction = (scheduled_now - scheduled_prev_anchor) / span
        return round(observed_prev + fraction * (observed_next - observed_prev), 0)

    if extrapolate:
        if (
            pd.isna(observed_prev)
            and pd.notna(observed_next)
            and pd.notna(scheduled_prev_anchor)
            and pd.notna(scheduled_next_anchor)
        ):
            return round(row["unix_departure_time"] + (observed_next - scheduled_next_anchor), 0)

        if (
            pd.isna(observed_next)
            and pd.notna(observed_prev)
            and pd.notna(row["unix_arrival_time"])
            and pd.notna(scheduled_prev_anchor)
        ):
            return round(row["unix_arrival_time"] + (observed_prev - scheduled_prev_anchor), 0)

    return np.nan


def fill_real_time(group: pd.DataFrame, extrapolate: bool = False) -> pd.DataFrame:
    group = group.copy()
    group["segment"] = group["timestamp"].notna().cumsum()
    group["scheduled_prev_anchor"] = group.groupby("segment")["unix_arrival_time"].transform("first")

    next_anchor = group.groupby("segment")["unix_arrival_time"].first().shift(-1)
    group["scheduled_next_anchor"] = group["segment"].map(next_anchor)
    if not group.empty:
        group["scheduled_next_anchor"] = group["scheduled_next_anchor"].fillna(group["unix_arrival_time"].iloc[-1])

    group["observed_prev"] = group["timestamp"].shift(1).ffill()
    group["observed_next"] = group["timestamp"].shift(-1).bfill()

    group["interpolated_time"] = group.apply(
        lambda row: interpolate_missing_times(row, extrapolate=extrapolate),
        axis=1,
    )
    return group
