"""Turn per-scene lake measurements into a yearly series and check it against published figures.

Pure pandas, so it runs and tests without Earth Engine.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

# A scene counts only if this share of the measuring area is cloud-free and inside the image
MIN_VALID_FRACTION = 0.95
# Yearly figures use 1 Sep to 15 Nov: after the monsoon cloud, before the lake freezes
SEASON_START = (9, 1)
SEASON_END = (11, 15)

MAIN = "water_t25_km2"
WIDE = "water_t15_km2"  # lower NDWI cut-off, so more pixels count as water
NARROW = "water_t35_km2"


def tidy(rows: list[dict] | pd.DataFrame) -> pd.DataFrame:
    """Add dates, km² columns and a usable-share column; keep one scene per sensor family per day."""
    df = pd.DataFrame(rows).copy()
    df["date"] = pd.to_datetime(df["time_ms"], unit="ms").dt.normalize()
    df["valid_fraction"] = df["valid_m2"] / df["aoi_m2"]
    for col in [c for c in df.columns if c.startswith("water_t") and c.endswith("_m2")]:
        df[col[: -len("_m2")] + "_km2"] = df[col] / 1e6
    df["family"] = df["sensor"].map(lambda s: "Sentinel-2" if str(s).startswith("Sentinel") else "Landsat")
    # Overlapping tiles or paths can give two images of the same day; keep the clearer one
    df = df.sort_values("valid_fraction", ascending=False).drop_duplicates(["family", "date"])
    return df.sort_values("date").reset_index(drop=True)


def clear(df: pd.DataFrame, min_valid: float = MIN_VALID_FRACTION) -> pd.DataFrame:
    return df[df["valid_fraction"] >= min_valid]


def in_season(dates: pd.Series) -> pd.Series:
    month_day = dates.dt.month * 100 + dates.dt.day
    start = SEASON_START[0] * 100 + SEASON_START[1]
    end = SEASON_END[0] * 100 + SEASON_END[1]
    return (month_day >= start) & (month_day <= end)


def yearly(df: pd.DataFrame, event_date: str) -> pd.DataFrame:
    """Median area of the clear autumn scenes in each year. The event year is split at the event date."""
    good = clear(df)
    good = good[in_season(good["date"])].copy()
    event = pd.Timestamp(event_date)
    period = good["date"].dt.year.astype(str)
    event_year = good["date"].dt.year == event.year
    period[event_year & (good["date"] < event)] = f"{event.year} before"
    period[event_year & (good["date"] >= event)] = f"{event.year} after"
    good["period"] = period
    out = good.groupby("period").agg(
        date=("date", "median"),
        scenes=("date", "size"),
        area_km2=(MAIN, "median"),
        area_wide_km2=(WIDE, "median"),
        area_narrow_km2=(NARROW, "median"),
        sensors=("family", lambda s: " + ".join(sorted(set(s)))),
    )
    return out.sort_values("date").reset_index()


@dataclass
class Check:
    name: str
    value_km2: float | None
    low: float
    high: float
    expect: str
    detail: str

    @property
    def passed(self) -> bool:
        return self.value_km2 is not None and self.low <= self.value_km2 <= self.high


def run_checks(df: pd.DataFrame, checks: list[dict]) -> list[Check]:
    good = clear(df)
    results = []
    for c in checks:
        start, end = (pd.Timestamp(d) for d in c["window"])
        window = good[(good["date"] >= start) & (good["date"] <= end)]
        if c["pick"] == "median":
            window = window[in_season(window["date"])]
        value, detail = None, "no clear scene in the window"
        if len(window):
            if c["pick"] == "last":
                row = window.iloc[-1]
                value, detail = row[MAIN], f"{row['sensor']}, {row['date']:%d %b %Y}"
            elif c["pick"] == "first":
                row = window.iloc[0]
                value, detail = row[MAIN], f"{row['sensor']}, {row['date']:%d %b %Y}"
            else:
                value, detail = float(window[MAIN].median()), f"median of {len(window)} scenes"
        results.append(Check(c["name"], value, c["low"], c["high"], c["expect"], detail))
    return results
