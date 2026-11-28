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


def _style(ax, c):
    ax.set_facecolor(c["surface"])
    ax.grid(axis="y", color=c["grid"], linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(c["axis"])
    ax.tick_params(colors=c["muted"], labelcolor=c["ink2"])


def plot_dam_break(run: dict, refinement: list[tuple[float, float]], t_end: float, h0: float, path: Path) -> None:
    """Left: depth along the channel against Ritter's exact solution. Right: error against cell size."""
    c = COLORS
    plt.rcParams["font.family"] = ["Segoe UI", "DejaVu Sans"]
    fig, (left, right) = plt.subplots(1, 2, figsize=(11, 4.8), dpi=150, gridspec_kw={"width_ratios": [1.7, 1]})
    fig.patch.set_facecolor(c["surface"])
    for ax in (left, right):
        _style(ax, c)

    x, h, exact = run["x"], run["h"], run["exact"]
    shown = (x > -350) & (x < 520)
    left.plot([-350, 0, 0, 520], [h0, h0, 0, 0], color=c["muted"], linewidth=1, linestyle=(0, (4, 3)),
              label="Before the dam fails", zorder=1)
    left.plot(x[shown], exact[shown], color=c["ink"], linewidth=2, label="Exact solution (Ritter 1892)", zorder=2)
    left.scatter(x[shown], h[shown], s=14, color=c["Landsat"], edgecolor=c["surface"], linewidth=0.6,
                 label=f"Solver, {x[1] - x[0]:g} m cells", zorder=3)
    left.set_xlim(-350, 520)
    left.set_ylim(0, h0 * 1.08)
    left.set_xlabel("Distance from the dam (m)", color=c["ink2"])
    left.set_ylabel("Water depth (m)", color=c["ink2"])
    left.set_title(f"Depth {t_end:g} s after the dam fails", loc="left", fontsize=12, fontweight="bold",
                   color=c["ink"], pad=12)
    legend = left.legend(loc="upper right", frameon=False, fontsize=8.5)
    for text in legend.get_texts():
        text.set_color(c["ink2"])

    sizes = [r[0] for r in refinement]
    errors = [100 * r[1] for r in refinement]
    right.plot(sizes, [errors[0] * s / sizes[0] for s in sizes], color=c["muted"], linewidth=1,
               linestyle=(0, (4, 3)), label="Halving with the cell size", zorder=1)
    right.plot(sizes, errors, color=c["Landsat"], linewidth=2, marker="o", markersize=6,
               markeredgecolor=c["surface"], markeredgewidth=1.2, label="Solver", zorder=2)
    for i, (s, e) in enumerate(zip(sizes, errors)):
        first = i == 0  # the first point sits on the axis, so its label goes to the right
        right.annotate(f"{e:.2f}%", (s, e), xytext=(8, 4) if first else (-8, -4), textcoords="offset points",
                       ha="left" if first else "right", va="bottom" if first else "top", fontsize=8,
                       color=c["ink2"])
    right.set_xscale("log")
    right.set_yscale("log")
    right.invert_xaxis()
    right.set_xticks(sizes, [f"{s:g}" for s in sizes])
    right.minorticks_off()
    right.set_ylim(min(errors) * 0.6, max(errors) * 1.5)
    right.set_yticks([0.25, 0.5, 1, 2], ["0.25%", "0.5%", "1%", "2%"])
    legend = right.legend(loc="upper right", frameon=False, fontsize=8.5)
    for text in legend.get_texts():
        text.set_color(c["ink2"])
    right.set_xlabel("Cell size (m), finer to the right", color=c["ink2"])
    right.set_ylabel("Depth error", color=c["ink2"])
    right.set_title("Error shrinks with finer cells", loc="left", fontsize=12, fontweight="bold", color=c["ink"],
                    pad=12)

    note = (f"Kurganov-Petrova scheme in PyTorch, float64. A dam holding {h0:g} m of water fails instantly onto a dry, "
            "flat, frictionless bed. Depth error: total difference from the exact\nsolution as a share of the water "
            "in the moving wave.")
    fig.text(0.01, 0.015, note, fontsize=7.2, color=c["muted"], linespacing=1.4)
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    fig.savefig(path, facecolor=c["surface"])
    plt.close(fig)


def plot_baseline(summary: dict, variant: str, label: str, names: dict, path: Path) -> None:
    """One panel per study area: mapped lake area every autumn against the inventory's totals."""
    c = COLORS
    plt.rcParams["font.family"] = ["Segoe UI", "DejaVu Sans"]
    keys = list(summary)
    fig, axes = plt.subplots(1, len(keys), figsize=(4.2 * len(keys), 4.2), dpi=150, sharey=False)
    fig.patch.set_facecolor(c["surface"])
    for ax, key in zip(axes, keys):
        _style(ax, c)
        rows = [r for r in summary[key] if variant in r["variants"]]
        years = [r["year"] for r in rows]
        total = [r["variants"][variant]["total"]["km2"] for r in rows]
        ax.plot(years, total, color=c["Landsat"], linewidth=2, marker="o", markersize=5,
                markeredgecolor=c["surface"], label="Mapped, all water patches ≥ 0.02 km²", zorder=2)
        scored = [r for r in rows if "found" in r["variants"][variant]]
        ax.scatter([r["year"] for r in scored], [r["variants"][variant]["truth_km2"] for r in scored], marker="D",
                   s=40, facecolor=c["surface"], edgecolor=c["ink"], linewidth=1.3, label="Inventory lakes", zorder=3)
        ax.scatter([r["year"] for r in scored], [r["variants"][variant]["mapped_km2"] for r in scored], marker="o",
                   s=30, facecolor="none", edgecolor=c["Sentinel-2"], linewidth=1.4,
                   label="Mapped, at inventory lakes", zorder=3)
        for r in scored:
            e = r["variants"][variant]
            ax.annotate(f"{e['found']}/{e['seen']} found", (r["year"], e["mapped_km2"]), xytext=(0, -9),
                        textcoords="offset points", ha="center", va="top", fontsize=7.5, color=c["ink2"])
        ax.set_ylim(0, max(total + [r["variants"][variant]["truth_km2"] for r in scored]) * 1.25)
        ax.set_xticks(years if len(years) <= 5 else list(range(min(years), max(years) + 1, 2)))
        ax.set_xlim(min(years) - 0.7, max(years) + 0.7)  # room for the labels at either end
        ax.set_title(names[key], loc="left", fontsize=10.5, fontweight="bold", color=c["ink"])
        ax.set_ylabel("Lake area (km²)", color=c["ink2"])
    legend = axes[0].legend(loc="lower left", frameon=False, fontsize=7.5)
    for text in legend.get_texts():
        text.set_color(c["ink2"])
    fig.text(0.01, 0.015, f"Sentinel-2 autumn composites (1 Sep-15 Nov), rule: {label}. Labels show inventory "
             "lakes found (overlap at least 0.5) out of those seen by 3+ scenes. Inventory: Zhang et al. (2023).",
             fontsize=7.2, color=c["muted"])
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(path, facecolor=c["surface"])
    plt.close(fig)


CATEGORY_NAMES = {"ice": "Ice", "shadow": "Shadow", "thin_cloud": "Thin cloud", "silty": "Silty", "clear": "Clear"}


def plot_unet(history: dict, kept_epoch: int, medians: dict, path: Path) -> None:
    """Left: the U-Net's validation score after each pass, against the baseline's. Right: median score per
    category, baseline against U-Net. `medians` is {category: (baseline, unet)}."""
    c = COLORS
    unet_c, base_c = c["Landsat"], c["Sentinel-2"]
    plt.rcParams["font.family"] = ["Segoe UI", "DejaVu Sans"]
    fig, (left, right) = plt.subplots(1, 2, figsize=(11.5, 4.4), dpi=150, gridspec_kw={"width_ratios": [1.35, 1]})
    fig.patch.set_facecolor(c["surface"])

    _style(left, c)
    epochs = [e["epoch"] for e in history["epochs"]]
    scores = [e["mean_iou"] for e in history["epochs"]]
    every = [v for vals in history["baseline"].values() for v in vals]
    baseline = sum(every) / len(every)
    left.axhline(baseline, color=base_c, linewidth=2, linestyle=(0, (4, 3)), zorder=2)
    left.text(epochs[-1], baseline - 0.035, f"Baseline (NDWI rule) {baseline:.2f}", ha="right", va="top", fontsize=8,
              color=c["ink2"])
    left.plot(epochs, scores, color=unet_c, linewidth=2, marker="o", markersize=4.5, markeredgecolor=c["surface"],
              zorder=3)
    best = scores[epochs.index(kept_epoch)]
    left.scatter([kept_epoch], [best], s=90, facecolor="none", edgecolor=c["ink"], linewidth=1.3, zorder=4)
    left.annotate(f"Kept: pass {kept_epoch}, {best:.2f}", (kept_epoch, best), xytext=(0, 14), textcoords="offset points",
                  ha="center", fontsize=8, color=c["ink"])
    left.text(epochs[0], scores[0] + 0.04, "U-Net", fontsize=8.5, color=c["ink2"], ha="left")
    left.set_ylim(0, 1)
    left.set_xlim(0.5, epochs[-1] + 0.5)
    left.set_xlabel("Training pass (epoch)", color=c["ink2"])
    left.set_ylabel("Mean overlap, 49 validation cases", color=c["ink2"])
    left.set_title("Validation score while training", loc="left", fontsize=10.5, fontweight="bold", color=c["ink"])

    _style(right, c)
    right.grid(axis="y", visible=False)
    right.grid(axis="x", color=c["grid"], linewidth=0.8)
    names = list(medians)
    ys = list(range(len(names)))[::-1]
    for y, name in zip(ys, names):
        b, u = medians[name]
        right.plot([b, u], [y, y], color=c["axis"], linewidth=2, zorder=1, solid_capstyle="round")
        right.scatter([b], [y], s=64, color=base_c, edgecolor=c["surface"], linewidth=2, zorder=3)
        right.scatter([u], [y], s=64, color=unet_c, edgecolor=c["surface"], linewidth=2, zorder=3)
    top_b, top_u = medians[names[0]]
    right.annotate("Baseline", (top_b, ys[0]), xytext=(0, 9), textcoords="offset points", ha="center", fontsize=8,
                   color=c["ink2"])
    right.annotate("U-Net", (top_u, ys[0]), xytext=(0, 9), textcoords="offset points", ha="center", fontsize=8,
                   color=c["ink2"])
    right.set_yticks(ys, [CATEGORY_NAMES.get(n, n) for n in names])
    right.set_xlim(-0.03, 1.03)
    right.set_ylim(-0.6, len(names) - 0.4)
    right.set_xlabel("Median overlap", color=c["ink2"])
    right.set_title("By condition, kept model", loc="left", fontsize=10.5, fontweight="bold", color=c["ink"])
    handles = [plt.Line2D([], [], marker="o", linestyle="", color=col, markersize=7, label=lab)
               for col, lab in ((unet_c, "U-Net"), (base_c, "Baseline (NDWI rule)"))]
    legend = right.legend(handles=handles, loc="lower left", frameon=False, fontsize=7.5)
    for text in legend.get_texts():
        text.set_color(c["ink2"])
    fig.text(0.01, 0.015, "Validation cases: Bhote Koshi and Khumbu, never trained on. Overlap with every inventory lake "
             "within 500 m of the case lake. The North Sikkim test cases are untouched until step 6.",
             fontsize=7.2, color=c["muted"])
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(path, facecolor=c["surface"])
    plt.close(fig)


def plot_tiles(panels: list[tuple], title: str, path: Path, columns: int = 7) -> None:
    """True-colour case tiles in a grid: each panel is (tile, lake map or None, caption). A lake map is shaded
    magenta; the case's own lake is outlined in cyan and other inventory lakes in yellow."""
    import numpy as np

    from . import tiles

    rows = (len(panels) + columns - 1) // columns
    fig, axes = plt.subplots(rows, columns, figsize=(2.3 * columns, 2.55 * rows + 0.5), dpi=110, squeeze=False)
    for ax in axes.ravel():
        ax.axis("off")
    for ax, (tile, mapped, caption) in zip(axes.ravel(), panels):
        ax.imshow(tiles.rgb(tile))
        if mapped is not None:
            ax.imshow(np.ma.masked_where(~mapped, mapped), cmap="cool", alpha=0.45, vmin=0, vmax=1)
        ax.contour(tile["label"], levels=[0.5], colors="#ffd60a", linewidths=0.6)
        ax.contour(tile["lake"], levels=[0.5], colors="#00e5ff", linewidths=1.0)
        ax.set_title(caption, fontsize=7)
    fig.suptitle(title, fontsize=10, x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(path, facecolor="white", **({"pil_kwargs": {"quality": 85}} if path.suffix == ".jpg" else {}))
    plt.close(fig)


def plot_gate(rows: list[dict], better: str, path: Path) -> None:
    """Left: every test case, the better rule's overlap against the U-Net's (above the diagonal, the U-Net
    wins). Right: median overlap per condition."""
    import statistics

    c = COLORS
    unet_c, base_c = c["Landsat"], c["Sentinel-2"]
    plt.rcParams["font.family"] = ["Segoe UI", "DejaVu Sans"]
    fig, (left, right) = plt.subplots(1, 2, figsize=(11.5, 4.9), dpi=150, gridspec_kw={"width_ratios": [1, 1.1]})
    fig.patch.set_facecolor(c["surface"])

    _style(left, c)
    left.grid(axis="x", color=c["grid"], linewidth=0.8)
    left.plot([0, 1], [0, 1], color=c["axis"], linewidth=1.2, zorder=1)
    hard = [r for r in rows if r["category"] != "clear"]
    clear = [r for r in rows if r["category"] == "clear"]
    left.scatter([r[better]["iou"] for r in hard], [r["unet"]["iou"] for r in hard], s=42, color=unet_c,
                 edgecolor=c["surface"], linewidth=1.5, zorder=3, label=f"Hard cases ({len(hard)})")
    left.scatter([r[better]["iou"] for r in clear], [r["unet"]["iou"] for r in clear], s=42, facecolor="none",
                 edgecolor=c["muted"], linewidth=1.3, zorder=2, label=f"Clear controls ({len(clear)})")
    left.set_xlim(-0.03, 1.03)
    left.set_ylim(-0.03, 1.03)
    left.set_aspect("equal")
    left.set_xlabel("Overlap, baseline rule", color=c["ink2"])
    left.set_ylabel("Overlap, U-Net (above the line: U-Net better)", color=c["ink2"])
    left.set_title("Each North Sikkim test case", loc="left", fontsize=10.5, fontweight="bold", color=c["ink"])
    legend = left.legend(loc="lower right", bbox_to_anchor=(1, 0.1), frameon=False, fontsize=7.5)
    for text in legend.get_texts():
        text.set_color(c["ink2"])

    _style(right, c)
    right.grid(axis="y", visible=False)
    right.grid(axis="x", color=c["grid"], linewidth=0.8)
    names = [n for n in CATEGORY_NAMES if any(r["category"] == n for r in rows)]
    ys = list(range(len(names)))[::-1]
    for y, name in zip(ys, names):
        group = [r for r in rows if r["category"] == name]
        b = statistics.median(r[better]["iou"] for r in group)
        u = statistics.median(r["unet"]["iou"] for r in group)
        right.plot([b, u], [y, y], color=c["axis"], linewidth=2, zorder=1, solid_capstyle="round")
        right.scatter([b], [y], s=64, color=base_c, edgecolor=c["surface"], linewidth=2, zorder=3)
        right.scatter([u], [y], s=64, color=unet_c, edgecolor=c["surface"], linewidth=2, zorder=3)
    right.set_yticks(ys, [f"{CATEGORY_NAMES[n]} ({sum(r['category'] == n for r in rows)})" for n in names])
    right.set_xlim(-0.03, 1.03)
    right.set_ylim(-0.6, len(names) - 0.4)
    right.set_xlabel("Median overlap", color=c["ink2"])
    right.set_title("By condition", loc="left", fontsize=10.5, fontweight="bold", color=c["ink"])
    handles = [plt.Line2D([], [], marker="o", linestyle="", color=col, markersize=7, label=lab)
               for col, lab in ((unet_c, "U-Net"), (base_c, "Baseline rule"))]
    legend = right.legend(handles=handles, loc="lower left", frameon=False, fontsize=7.5)
    for text in legend.get_texts():
        text.set_color(c["ink2"])
    fig.text(0.01, 0.015, "Overlap with every inventory lake within 500 m of the case lake; water mapped where there is "
             "no lake counts against. Cases: P1 step 4, never used in training or tuning.", fontsize=7.2,
             color=c["muted"])
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(path, facecolor=c["surface"])
    plt.close(fig)


AREA_NAMES = {"sikkim": "North Sikkim", "bhote_koshi": "Bhote Koshi / Poiqu", "khumbu": "Khumbu"}


def plot_growth(series: list[dict], south_lhonak: dict, outburst: str, path: Path) -> None:
    """Total lake area per study area each autumn (lakes mapped every autumn and listed in every inventory
    year, so the two totals cover the same lakes), and South Lhonak alone with its 2023 scenes either side of
    the outburst. Inventory areas are black diamonds."""
    import datetime

    c = COLORS
    unet_c, after_c = c["Landsat"], c["Sentinel-2"]
    plt.rcParams["font.family"] = ["Segoe UI", "DejaVu Sans"]
    fig, axes = plt.subplots(1, 4, figsize=(15, 4.2), dpi=150)
    fig.patch.set_facecolor(c["surface"])
    years = sorted({int(y) for s in series for y in s["autumns"]})
    for ax, key in zip(axes[:3], AREA_NAMES):
        _style(ax, c)
        lakes = [s for s in series if s["area"] == key]
        inv = [2018, 2020, 2022]
        full = [s for s in lakes if all(y in s["autumns"] or str(y) in s["autumns"] for y in years)
                and all(y in s["listed_km2"] or str(y) in s["listed_km2"] for y in inv)]
        get = lambda s, y: s["autumns"].get(y, s["autumns"].get(str(y)))
        ax.plot(years, [sum(get(s, y)["km2"] for s in full) for y in years], color=unet_c, linewidth=2, marker="o",
                markersize=4.5, markeredgecolor=c["surface"], zorder=2, label="U-Net, each autumn")
        listed = [sum(s["listed_km2"].get(y, s["listed_km2"].get(str(y))) for s in full) for y in inv]
        ax.scatter(inv, listed, marker="D", s=36, facecolor=c["surface"], edgecolor=c["ink"], linewidth=1.3, zorder=3,
                   label="Inventory")
        top = max(listed + [sum(get(s, y)["km2"] for s in full) for y in years])
        ax.set_ylim(0, top * 1.2)
        ax.set_xticks(years[::2])
        ax.set_title(f"{AREA_NAMES[key]}\n{len(full)} of {len(lakes)} lakes, mapped every autumn", loc="left",
                     fontsize=9.5, fontweight="bold", color=c["ink"])
        ax.set_ylabel("Total lake area (km²)", color=c["ink2"])
    legend = axes[0].legend(loc="lower left", frameon=False, fontsize=7.5)
    for text in legend.get_texts():
        text.set_color(c["ink2"])

    ax = axes[3]
    _style(ax, c)
    sl = south_lhonak
    get = lambda y: sl["autumns"].get(y, sl["autumns"].get(str(y)))
    have = [y for y in years if get(y)]
    ax.plot(have, [get(y)["km2"] for y in have], color=unet_c, linewidth=2, marker="o", markersize=4.5,
            markeredgecolor=c["surface"], zorder=2)
    burst = datetime.date.fromisoformat(outburst)
    frac = lambda d: d.year + (d.timetuple().tm_yday - 0.5) / 365.25
    scenes = get(2023)["scenes"] if get(2023) else []
    for s in scenes:
        d = datetime.date.fromisoformat(s["date"])
        ax.scatter([frac(d)], [s["km2"]], s=22, zorder=3, linewidth=1.1,
                   facecolor=after_c if d >= burst else "none", edgecolor=after_c if d >= burst else c["muted"])
    ax.axvline(frac(burst), color=c["axis"], linewidth=1, zorder=1)
    ax.text(frac(burst) + 0.1, 0.12, "Outburst\n4 Oct 2023", fontsize=7.5, color=c["ink2"], transform=ax.get_xaxis_transform())
    inv = [2018, 2020, 2022]
    ax.scatter(inv, [sl["listed_km2"].get(y, sl["listed_km2"].get(str(y))) for y in inv], marker="D", s=36,
               facecolor=c["surface"], edgecolor=c["ink"], linewidth=1.3, zorder=4)
    ax.set_ylim(0, max([get(y)["km2"] for y in have] + [s["km2"] for s in scenes]) * 1.2)
    ax.set_xticks(years[::2])
    ax.set_title("South Lhonak\nautumns, and each 2023 scene", loc="left", fontsize=9.5, fontweight="bold",
                 color=c["ink"])
    ax.set_ylabel("Lake area (km²)", color=c["ink2"])
    fig.text(0.01, 0.015, "U-Net (P1 step 5) on the clearest Sentinel-2 scenes of 1 Sep-15 Nov; an autumn is the median "
             "of up to three scenes' lake probability. Totals: lakes mapped every autumn and listed in 2018, 2020 and "
             "2022. 2023 scenes: hollow before the outburst, filled after. Inventory: Zhang et al. (2023).",
             fontsize=7.2, color=c["muted"])
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(path, facecolor=c["surface"])
    plt.close(fig)
