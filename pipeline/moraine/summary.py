"""Turn per-period lake measurements into a series and check it against published figures.

Pure pandas, so it runs and tests without Earth Engine.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

# A period counts only if at least this share of the measuring area was seen by enough scenes
MIN_COVERAGE = 0.95
# Autumn window: after the monsoon cloud, before the lake freezes. The end day is exclusive.
SEASON_START = (9, 1)
SEASON_END = (11, 16)

# A lake does not double for one autumn and shrink back: a period that differs from the median of
# the periods within this many years by more than this share is dropped as an outlier
NEIGHBOUR_YEARS = 4
OUTLIER_TOLERANCE = 0.30

MAIN = "water_t25_km2"
WIDE = "water_t15_km2"  # lower NDWI cut-off, so more pixels count as water
NARROW = "water_t35_km2"


def autumn_periods(event_date: str, first_year: int = 1984, last_year: int = 2026) -> list[dict]:
    """One autumn window per year; if the event falls inside an autumn, that autumn is split at it."""
    event = pd.Timestamp(event_date)
    periods = []
    for year in range(first_year, last_year + 1):
        start = pd.Timestamp(year, *SEASON_START)
        end = pd.Timestamp(year, *SEASON_END)
        if start < event < end:
            periods.append({"period": f"{year} before", "start": f"{start:%Y-%m-%d}", "end": f"{event:%Y-%m-%d}"})
            periods.append({"period": f"{year} after", "start": f"{event:%Y-%m-%d}", "end": f"{end:%Y-%m-%d}"})
        else:
            periods.append({"period": str(year), "start": f"{start:%Y-%m-%d}", "end": f"{end:%Y-%m-%d}"})
    return periods


def tidy(rows: list[dict] | pd.DataFrame) -> pd.DataFrame:
    """Add a mid-period date, coverage share and km² columns."""
    df = pd.DataFrame(rows).copy()
    start, end = pd.to_datetime(df["start"]), pd.to_datetime(df["end"])
    df["date"] = start + (end - start) / 2
    df["coverage"] = (df["covered_m2"] / df["aoi_m2"].where(df["aoi_m2"] > 0)).fillna(0.0)
    for col in [c for c in df.columns if c.startswith("water_t") and c.endswith("_m2")]:
        df[col[: -len("_m2")] + "_km2"] = df[col] / 1e6
    return df.sort_values(["date", "family"]).reset_index(drop=True)


def usable(df: pd.DataFrame, min_coverage: float = MIN_COVERAGE) -> pd.DataFrame:
    return df[df["coverage"] >= min_coverage]


def flag_outliers(series: pd.DataFrame, event_date: str) -> pd.Series:
    """True where a period differs too much from its neighbours on the same side of the event."""
    event = pd.Timestamp(event_date)
    window = pd.Timedelta(days=365.25 * NEIGHBOUR_YEARS)
    dates, values = series["date"], series[MAIN]
    flags = []
    for i, (when, value) in enumerate(zip(dates, values)):
        near = ((dates - when).abs() <= window) & ((dates < event) == (when < event))
        near.iloc[i] = False
        reference = values[near].median() if near.sum() >= 2 else None
        flags.append(bool(reference) and abs(value - reference) / reference > OUTLIER_TOLERANCE)
    return pd.Series(flags, index=series.index)


def best(df: pd.DataFrame, event_date: str) -> pd.DataFrame:
    """One value per period: Sentinel-2 (10 m) where usable, otherwise Landsat (30 m). Adds an outlier column."""
    good = usable(df).copy()
    good["rank"] = good["family"].map({"Sentinel-2": 0, "Landsat": 1})
    picked = good.sort_values(["date", "rank"]).drop_duplicates("period").drop(columns="rank")
    picked = picked.reset_index(drop=True)
    picked["outlier"] = flag_outliers(picked, event_date)
    return picked


def series(df: pd.DataFrame, event_date: str) -> pd.DataFrame:
    """The best value per period, outliers removed."""
    picked = best(df, event_date)
    return picked[~picked["outlier"]].reset_index(drop=True)


@dataclass
class Check:
    name: str
    role: str  # "gate" decides pass/fail; "compare" is reported only
    value: float | None
    low: float
    high: float
    expect: str
    detail: str

    @property
    def in_range(self) -> bool:
        return self.value is not None and self.low <= self.value <= self.high


def run_checks(df: pd.DataFrame, checks: list[dict], event_date: str) -> list[Check]:
    values = series(df, event_date).set_index("period")
    results = []
    for c in checks:
        value, detail = None, "no usable period"
        if "ratio" in c:
            top, bottom = c["ratio"]
            if top in values.index and bottom in values.index and values.loc[bottom, MAIN] > 0:
                value = float(values.loc[top, MAIN] / values.loc[bottom, MAIN])
                detail = f"{values.loc[top, MAIN]:.3f} / {values.loc[bottom, MAIN]:.3f} km2"
        else:
            found = values.loc[[p for p in c["periods"] if p in values.index]]
            if len(found):
                value = float(found[MAIN].median())
                detail = ", ".join(f"{p}: {r[MAIN]:.3f} ({r['family']})" for p, r in found.iterrows())
        results.append(Check(c["name"], c["role"], value, c["low"], c["high"], c["expect"], detail))
    return results
