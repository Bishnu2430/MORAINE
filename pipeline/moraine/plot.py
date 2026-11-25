"""Static chart of a lake's area over time, for checking a run by eye."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from . import summary  # noqa: E402

# Light chart surface, ink and the first two categorical slots of the reference data-viz palette
COLORS = {
    "surface": "#fcfcfb",
    "ink": "#0b0b0b",
    "ink2": "#52514e",
    "muted": "#898781",
    "grid": "#e1e0d9",
    "axis": "#c3c2b7",
    "band": "#ebeae4",
    "Landsat": "#2a78d6",
    "Sentinel-2": "#eb6834",
}


def plot_area(df: pd.DataFrame, lake: dict, path: Path) -> None:
    c = COLORS
    plt.rcParams["font.family"] = ["Segoe UI", "DejaVu Sans"]
    fig, ax = plt.subplots(figsize=(10, 5.4), dpi=150)
    fig.patch.set_facecolor(c["surface"])
    ax.set_facecolor(c["surface"])

    # Break the line where more than ~18 months are missing, so a gap never reads as a gradual change
    picked = summary.best(df, lake["event_date"])
    series = picked[~picked["outlier"]].set_index("date")[[summary.MAIN, summary.WIDE, summary.NARROW]]
    gap_ends = series.index[series.index.to_series().diff() > pd.Timedelta(days=548)]
    breaks = pd.DataFrame(index=gap_ends - pd.Timedelta(days=1), columns=series.columns, dtype=float)
    series = pd.concat([series, breaks]).sort_index()
    ax.fill_between(series.index, series[summary.NARROW], series[summary.WIDE], color=c["band"], linewidth=0,
                    label="NDWI cut-off 0.15 to 0.35", zorder=1)
    ax.plot(series.index, series[summary.MAIN], color=c["ink"], linewidth=2,
            label="Best estimate (Sentinel-2 where available)", zorder=2)

    # A point is drawn as dropped if it is the best value and an outlier, or if it is the unused
    # sensor's value for a period and differs from the chosen value by more than the outlier tolerance
    good = summary.usable(df).reset_index(drop=True)
    chosen = picked.set_index("period")
    dropped = []
    for _, row in good.iterrows():
        pick = chosen.loc[row["period"]]
        if pick["family"] == row["family"]:
            dropped.append(bool(pick["outlier"]))
        else:
            dropped.append(abs(row[summary.MAIN] - pick[summary.MAIN]) > summary.OUTLIER_TOLERANCE * pick[summary.MAIN])
    dropped = pd.Series(dropped, index=good.index, dtype=bool)
    for family in ("Landsat", "Sentinel-2"):
        rows = good[(good["family"] == family) & ~dropped]
        if len(rows):
            ax.scatter(rows["date"], rows[summary.MAIN], s=28, color=c[family], edgecolor=c["surface"],
                       linewidth=0.9, label=f"{family} autumn composite", zorder=3)
    outliers = good[dropped]
    if len(outliers):
        ax.scatter(outliers["date"], outliers[summary.MAIN], s=28, facecolor="none", edgecolor=c["muted"],
                   linewidth=1.2, label="Dropped as outlier", zorder=3)

    published = lake["published"]
    if published:
        ax.scatter([pd.Timestamp(p["date"]) for p in published], [p["area_km2"] for p in published], s=44,
                   marker="D", facecolor=c["surface"], edgecolor=c["ink"], linewidth=1.3,
                   label="Published value", zorder=4)
    for p in published:
        if "note" in p:
            dx, dy = p["note"]
            ax.annotate(f"{p['label']}: {p['area_km2']:.2f}", (pd.Timestamp(p["date"]), p["area_km2"]),
                        xytext=(dx, dy), textcoords="offset points", ha="right",
                        va="bottom" if dy > 0 else "center", fontsize=8.5, color=c["ink2"])

    event = pd.Timestamp(lake["event_date"])
    ax.axvline(event, color=c["muted"], linewidth=1, linestyle=(0, (4, 3)), zorder=0)
    ax.text(event, 1.0, f" Outburst\n {lake['event_label']}", transform=ax.get_xaxis_transform(), va="top",
            ha="left", fontsize=8.5, color=c["ink2"])

    highs = [good[summary.WIDE].max() if len(good) else 0] + [p["area_km2"] for p in published]
    ax.set_ylim(0, max(max(highs), 0.01) * 1.15)
    ax.set_ylabel("Lake area (km²)", color=c["ink2"])
    ax.xaxis.set_major_locator(mdates.YearLocator(5))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.grid(axis="y", color=c["grid"], linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(c["axis"])
    ax.tick_params(colors=c["muted"], labelcolor=c["ink2"])

    ax.set_title(f"{lake['name']} lake area, autumn of each year", loc="left", fontsize=13,
                 fontweight="bold", color=c["ink"], pad=14)
    legend = ax.legend(loc="upper left", frameon=False, fontsize=8.5)
    for text in legend.get_texts():
        text.set_color(c["ink2"])

    note = ("Each point: 80th-percentile NDWI composite of 1 Sep-15 Nov scenes, kept where at least 95% of the "
            "measuring area was seen 3+ times.\nLandsat 5-9 and Sentinel-2 via Google Earth Engine.")
    if published:
        note += " Year-only published values sit in mid-October."
    fig.text(0.01, 0.012, note, fontsize=7.2, color=c["muted"], linespacing=1.4)
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(path, facecolor=c["surface"])
    plt.close(fig)
