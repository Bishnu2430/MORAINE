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

# Published values that get a written label, with the label's offset in points; the rest are markers only
LABELLED = {"28 Sep 2023": (-8, 14), "4 Oct 2023": (-10, 0)}


def plot_area(df: pd.DataFrame, by_year: pd.DataFrame, lake: dict, path: Path) -> None:
    c = COLORS
    plt.rcParams["font.family"] = ["Segoe UI", "DejaVu Sans"]
    fig, ax = plt.subplots(figsize=(10, 5.4), dpi=150)
    fig.patch.set_facecolor(c["surface"])
    ax.set_facecolor(c["surface"])

    ax.fill_between(
        by_year["date"], by_year["area_narrow_km2"], by_year["area_wide_km2"],
        color=c["band"], linewidth=0, label="NDWI cut-off 0.15 to 0.35", zorder=1,
    )
    ax.plot(by_year["date"], by_year["area_km2"], color=c["ink"], linewidth=2,
            label="Autumn median, NDWI > 0.25", zorder=2)

    good = summary.clear(df)
    good = good[summary.in_season(good["date"])]
    for family in ("Landsat", "Sentinel-2"):
        rows = good[good["family"] == family]
        if len(rows):
            ax.scatter(rows["date"], rows[summary.MAIN], s=24, color=c[family], edgecolor=c["surface"],
                       linewidth=0.9, label=f"{family} scene", zorder=3)

    published = pd.DataFrame(lake["published"], columns=["date", "area", "label", "source"])
    published["date"] = pd.to_datetime(published["date"])
    ax.scatter(published["date"], published["area"], s=44, marker="D", facecolor=c["surface"],
               edgecolor=c["ink"], linewidth=1.3, label="Published value", zorder=4)
    for _, p in published[published["label"].isin(LABELLED)].iterrows():
        dx, dy = LABELLED[p["label"]]
        ax.annotate(f"{p['label']}: {p['area']:.2f}", (p["date"], p["area"]), xytext=(dx, dy),
                    textcoords="offset points", ha="right", va="bottom" if dy > 0 else "center",
                    fontsize=8.5, color=c["ink2"])

    event = pd.Timestamp(lake["event_date"])
    ax.axvline(event, color=c["muted"], linewidth=1, linestyle=(0, (4, 3)), zorder=0)
    ax.text(event, 1.0, " Outburst\n 4 Oct 2023", transform=ax.get_xaxis_transform(), va="top",
            ha="left", fontsize=8.5, color=c["ink2"])

    top = max(good[summary.WIDE].max() if len(good) else 0, published["area"].max())
    ax.set_ylim(0, top * 1.15)
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
                 fontweight="semibold", color=c["ink"], pad=14)
    legend = ax.legend(loc="upper left", frameon=False, fontsize=8.5)
    for text in legend.get_texts():
        text.set_color(c["ink2"])

    fig.text(0.01, 0.012,
             "Clear scenes only: at least 95% of the measuring area cloud-free, 1 Sep to 15 Nov. "
             "Landsat 5-9 and Sentinel-2 via Google Earth Engine. Year-only published values sit in mid-October.",
             fontsize=7.5, color=c["muted"])
    fig.tight_layout(rect=(0, 0.035, 1, 1))
    fig.savefig(path, facecolor=c["surface"])
    plt.close(fig)
