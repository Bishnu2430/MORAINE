"""P0: one-page data checks for the three test events (Gongbatongsha 2016, Thame 2024, Kedarnath 2013).

    .venv\\Scripts\\python pipeline\\scripts\\p0_events.py --project YOUR-CLOUD-PROJECT [--event thame]

For each event, on Earth Engine: finds or outlines the lake and measures it in the autumns before
and after, traces the flood route downhill on MERIT Hydro, cuts the GLO-30 corridor around it, reads
GLO-30's water mask at the lake, lists clear Sentinel-2 and Landsat scenes either side of the date,
and sums GPM IMERG rain over the days before. Writes pipeline/out/p0_events/<event>/checks.json and
map.png, and prints the checks. Exits 0 only if every check passes.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

PIPELINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PIPELINE))

from moraine import events, lakes, summary, terrain  # noqa: E402

CELL = 30.0


def autumn(year: int) -> dict:
    return {"period": str(year), "start": f"{year}-09-01", "end": f"{year}-11-16"}


def lake_areas(aoi, year: int) -> dict:
    """Best water area (km2, NDWI > 0.25) in the autumns before and after an event in `year`."""
    rows = summary.tidy(lakes.measure_periods(aoi, [autumn(year - 1), autumn(year)], progress=lambda s: None))
    good = summary.usable(rows)
    out = {}
    for period in (str(year - 1), str(year)):
        picks = good[good["period"] == period]
        if len(picks):
            pick = picks[picks["family"] == "Sentinel-2"] if (picks["family"] == "Sentinel-2").any() else picks
            row = pick.iloc[0]
            out[period] = {"km2": round(float(row[summary.MAIN]), 4), "family": row["family"],
                           "band_km2": [round(float(row[summary.NARROW]), 4), round(float(row[summary.WIDE]), 4)]}
        else:
            out[period] = None
    return out


def trace(event: dict, lake: dict):
    directions, x0, y0 = terrain.merit_directions(*event["search"])
    step = terrain.MERIT_STEP
    start = (int((y0 - lake["lat"]) / step), int((lake["lon"] - x0) / step))
    cells = terrain.trace_downhill(directions, start)
    lonlat = np.array([(x0 + (c + 0.5) * step, y0 - (r + 0.5) * step) for r, c in cells])
    if event.get("run_start"):
        # Upstream area along the route; joining a much larger river shows as a jump
        upstream, _, _ = terrain.merit_band("upa", *event["search"])
        event = {**event, "_upstream_km2": np.array([upstream[r, c] for r, c in cells])}
    cos = np.cos(np.radians(lake["lat"]))
    steps = np.hypot(np.diff(lonlat[:, 0]) * 111.32 * cos, np.diff(lonlat[:, 1]) * 110.57)
    along = np.concatenate([[0], np.cumsum(steps)])
    keep = along <= event["length_km"]
    lonlat, along = lonlat[keep], along[keep]
    if "_upstream_km2" in event:
        area = event["_upstream_km2"][: len(lonlat)]
        within = np.nonzero(along <= event["run_start"]["search_km"])[0][1:]
        jump = within[int(np.argmax(area[within] / np.maximum(area[within - 1], 1e-6)))]
        event["run_start"]["found"] = {"index": int(jump), "upstream_km2": [float(area[jump - 1]), float(area[jump])]}
    passes = []
    for place in event["places"]:
        km = np.hypot((lonlat[:, 0] - place["lon"]) * 111.32 * cos, (lonlat[:, 1] - place["lat"]) * 110.57)
        i = int(np.argmin(km))
        passes.append({"name": place["name"], "miss_m": round(1000 * float(km[i])), "along_km": round(float(along[i]), 1)})
    return lonlat, along, passes


def corridor(event: dict, lonlat: np.ndarray, points: list[tuple[float, float]]):
    crs, hw, block = event["crs"], event["half_width_m"], 4 * CELL
    utm = terrain.to_utm([tuple(p) for p in lonlat] + points, crs)
    line, marks = utm[: len(lonlat)], utm[len(lonlat):]
    left = np.floor((line[:, 0].min() - hw) / block) * block
    right = np.ceil((line[:, 0].max() + hw) / block) * block
    bottom = np.floor((line[:, 1].min() - hw) / block) * block
    top = np.ceil((line[:, 1].max() + hw) / block) * block
    width, height = int((right - left) / CELL), int((top - bottom) / CELL)
    dem = terrain.glo30_utm(left, top, width, height, CELL, crs)
    xs = left + (np.arange(width) + 0.5) * CELL
    ys = top - (np.arange(height) + 0.5) * CELL
    dist = terrain.distance_to_polyline(xs[None, :], ys[:, None], line)
    inside = dist <= hw
    heights = np.where(inside, dem, np.nan)
    elevations = []
    for x, y in marks:
        near = np.hypot(xs[None, :] - x, ys[:, None] - y) <= 100
        elevations.append(round(float(np.nanmedian(dem[near])), 0))
    return {
        "grid": [width, height],
        "cells": int(inside.sum()),
        "km2": round(float(inside.sum()) * CELL * CELL / 1e6, 1),
        "valid_share": round(float(np.isfinite(dem[inside]).mean()), 5),
        "elevation_m": [round(float(np.nanmin(heights)), 0), round(float(np.nanmax(heights)), 0)],
        "point_elevations_m": elevations,
    }, heights, line, marks, (left, top)


def draw_map(event, heights, line, marks, names, origin, path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    left, top = origin
    shade = terrain.hillshade(heights, CELL)
    rgba = plt.get_cmap("gray")(0.25 + 0.75 * shade)
    rgba[np.isnan(heights)] = (0.99, 0.99, 0.98, 1)
    fig, ax = plt.subplots(figsize=(7, 7 * heights.shape[0] / heights.shape[1]), dpi=130)
    ax.imshow(rgba, extent=(0, heights.shape[1], heights.shape[0], 0))
    ax.plot((line[:, 0] - left) / CELL, (top - line[:, 1]) / CELL, color="#2a78d6", linewidth=1.6)
    for (x, y), name in zip(marks, names):
        ax.plot((x - left) / CELL, (top - y) / CELL, "o", color="#eb6834", markersize=6)
        start = name.startswith("Run starts")  # labelled to the left so it clears the lake's label
        ax.annotate(name, ((x - left) / CELL, (top - y) / CELL), xytext=(-10, -4) if start else (8, 6),
                    textcoords="offset points", ha="right" if start else "left", va="top" if start else "baseline",
                    fontsize=9, color="#0b0b0b")
    ax.set_axis_off()
    ax.set_title(f"{event['name']}: flood route and GLO-30 within {event['half_width_m'] / 1000:g} km (north up)",
                 loc="left", fontsize=10)
    fig.tight_layout()
    fig.savefig(path, facecolor="#fcfcfb")
    plt.close(fig)


def check_event(key: str, event: dict, out: Path) -> list[tuple[str, bool, str]]:
    import ee

    year = int(event["date"][:4])
    print(f"\n{event['name']} ({event['when']})", flush=True)
    result: dict = {"event": event["name"], "date": event["date"], "published": event["published"]}

    # The lake
    aoi = None
    if event["lake_method"] == "drained":
        found = events.drained_lake(event["lake_search"], (f"{year - 1}-09-01", f"{year - 1}-11-16"),
                                    (f"{year}-09-01", f"{year}-11-16"))
        lake = {"name": "Drained lake", "lon": round(found["lon"], 5), "lat": round(found["lat"], 5)}
        aoi = found["geometry"].buffer(100)
        result["drained_lake"] = {k: found[k] for k in ("lon", "lat", "before_m2", "after_m2")}
        print(f"  lake found at {lake['lat']:.4f} N, {lake['lon']:.4f} E: {found['before_m2'] / 1e6:.3f} km2 "
              f"of water in autumn {year - 1}, {found['after_m2'] / 1e6:.3f} km2 in autumn {year}")
    else:
        lake = event["lake"]
        if event["lake_method"] == "jrc":
            try:
                aoi = lakes.lake_aoi(lake["lon"], lake["lat"], margin_m=60, search_m=300)
            except Exception:  # Earth Engine wraps "no polygon found" in its own exception types
                aoi = ee.Geometry.Point([lake["lon"], lake["lat"]]).buffer(200)
                result["aoi_note"] = "no JRC water outline within 300 m; measured within 200 m of the point"
    result["lake"] = lake
    if aoi is not None:
        result["lake_area"] = lake_areas(aoi, year)
        print(f"  lake area (autumn before / after): {result['lake_area']}")
    result["water_mask_code"] = events.water_mask_code(lake["lon"], lake["lat"])

    # The route and the corridor
    lonlat, along, passes = trace(event, lake)
    length = float(along[-1])
    result["route"] = {"length_km": round(length, 1), "passes": passes}
    print(f"  route: {length:.1f} km traced; " + ", ".join(f"passes {p['miss_m']} m from {p['name']} at km "
                                                             f"{p['along_km']}" for p in passes))
    points = [(lake["lon"], lake["lat"])] + [(p["lon"], p["lat"]) for p in event["places"]]
    names = [lake["name"]] + [p["name"] for p in event["places"]]
    start = event.get("run_start")
    if start:
        i = start["found"]["index"]
        points.append((float(lonlat[i, 0]), float(lonlat[i, 1])))
        names.append(start["name"])
    info, heights, line, marks, origin = corridor(event, lonlat, points)
    result["corridor"] = info
    if start:
        lon, lat = points[-1]
        before_km2, after_km2 = start["found"]["upstream_km2"]
        result["run_start"] = {"name": start["name"], "along_km": round(float(along[i]), 2), "lon": round(lon, 5),
                               "lat": round(lat, 5), "elevation_m": info["point_elevations_m"][-1],
                               "upstream_km2": [round(before_km2, 1), round(after_km2, 1)]}
        print(f"  run starts {along[i]:.1f} km down the route at {lat:.4f} N, {lon:.4f} E, "
              f"{info['point_elevations_m'][-1]:.0f} m, where upstream area jumps {before_km2:.0f} -> "
              f"{after_km2:.0f} km2")
    print(f"  corridor: {info['km2']} km2, {info['cells']:,} cells of 30 m, {info['elevation_m'][0]:.0f}-"
          f"{info['elevation_m'][1]:.0f} m; lake and places at {info['point_elevations_m']} m")
    draw_map(event, heights, line, marks, names, origin, out / "map.png")

    # Imagery and rain
    region = ee.Geometry.LineString([list(p) for p in lonlat[:: max(1, len(lonlat) // 200)]]).buffer(1000)
    result["clear_scenes"] = events.clear_scenes(region, event["date"])
    for family, sets in result["clear_scenes"].items():
        print(f"  clear {family} scenes within {events.IMAGERY_WINDOW_DAYS} days: {len(sets['before'])} before "
              f"(last {sets['before'][-1] if sets['before'] else '-'}), {len(sets['after'])} after "
              f"(first {sets['after'][0] if sets['after'] else '-'})")
    result["rain"] = events.rain_total(region, *event["rain"])
    print(f"  GPM IMERG rain {event['rain'][0]} to {event['rain'][1]} (end excluded): "
          f"{result['rain']['mean_mm']:.0f} mm mean over the route, {result['rain']['max_mm']:.0f} mm wettest cell")
    (out / "checks.json").write_text(json.dumps(result, indent=1))

    checks = [
        ("Flood route traced", length >= 0.95 * event["length_km"] and all(p["miss_m"] <= 1000 for p in passes),
         f"{length:.1f} of {event['length_km']:g} km" + "".join(f"; {p['miss_m']} m from {p['name']}" for p in passes)),
        ("Elevation covers the corridor", info["valid_share"] >= 0.999, f"{100 * info['valid_share']:.2f}% of cells"),
        ("Clear imagery after the event", any(s["after"] for s in result["clear_scenes"].values()),
         "first " + ", ".join(f"{f} {s['after'][0]}" for f, s in result["clear_scenes"].items() if s["after"])),
        ("Rain record complete", result["rain"]["half_hours"] >= 48 * 7,
         f"{result['rain']['half_hours']} half-hours"),
    ]
    if aoi is not None:
        before = result["lake_area"].get(str(year - 1))
        checks.append(("Lake measured before the event", before is not None and before["km2"] > 0,
                       f"{before['km2']} km2 ({before['family']})" if before else "no clear autumn composite"))
    else:
        result["lake_note"] = event["lake_note"]
        print(f"  INFO  Lake size: {event['lake_note']}")
    (out / "checks.json").write_text(json.dumps(result, indent=1))
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", default=os.environ.get("EE_PROJECT"))
    parser.add_argument("--event", choices=sorted(events.EVENTS), action="append")
    args = parser.parse_args()

    import ee

    try:
        ee.Initialize(project=args.project)
    except Exception as exc:  # the client raises plain Exceptions for missing sign-in or project access
        sys.exit(f"Earth Engine would not start: {exc}\nSee pipeline/README.md for sign-in and project setup.")

    total, passed = 0, 0
    for key in args.event or list(events.EVENTS):
        out = PIPELINE / "out" / "p0_events" / key
        out.mkdir(parents=True, exist_ok=True)
        for name, ok, detail in check_event(key, events.EVENTS[key], out):
            total += 1
            passed += ok
            print(f"  {'PASS' if ok else 'FAIL'}  {name}: {detail}")
    print(f"\n{passed} of {total} checks passed. Details: {PIPELINE / 'out' / 'p0_events'}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
