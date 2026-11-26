"""P0 spike: real Teesta terrain for the web viewer, cut from Earth Engine.

    .venv\\Scripts\\python pipeline\\scripts\\p0_terrain.py --project YOUR-CLOUD-PROJECT

Traces the river from South Lhonak lake down to Chungthang on MERIT Hydro's flow directions, keeps
the Copernicus GLO-30 elevation within 5 km of that path, and writes it for the browser to
web/public/data/teesta/terrain/: height30.u16, height60.u16, height120.u16 (Uint16, little-endian,
row 0 at the north), corridor.u8 (distance to the river path in 25 m steps) and manifest.json.
A shaded-relief preview goes to pipeline/out/p0_terrain/preview.png. Exits 0 only if the
elevation checks and the size budget pass.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
from pathlib import Path

import numpy as np

PIPELINE = Path(__file__).resolve().parents[1]
REPO = PIPELINE.parent
sys.path.insert(0, str(PIPELINE))

from moraine import terrain  # noqa: E402

VALLEY = {
    "id": "teesta",
    "name": "Teesta valley: South Lhonak lake to Chungthang",
    "start": {"name": "South Lhonak lake", "lon": 88.191, "lat": 27.913},
    "end": {"name": "Chungthang", "lon": 88.6457, "lat": 27.6045},
    "search": (88.05, 27.45, 88.80, 28.05),  # west, south, east, north (degrees) for tracing the river
    "half_width_m": 5000.0,
    "past_end_m": 2000.0,  # keep the river this far beyond the town
}
CELL = 30.0
BUDGET_BYTES = 3_000_000  # the plan's terrain/height budget, all three levels, as served (gzip)
CHECKS = [
    # (what, low, high, how it is measured)
    ("South Lhonak lake surface", 5100, 5300, "median elevation within 300 m of the lake point"),
    ("Teesta at Chungthang", 1400, 1900, "lowest elevation within 1 km of the town"),
]


def trace_river(directions, x0, y0):
    step = terrain.MERIT_STEP
    s, e = VALLEY["start"], VALLEY["end"]
    start = (int((y0 - s["lat"]) / step), int((s["lon"] - x0) / step))
    cells = terrain.trace_downhill(directions, start)
    lonlat = np.array([(x0 + (c + 0.5) * step, y0 - (r + 0.5) * step) for r, c in cells])
    # Cut the path a little past the point nearest the town
    km = np.hypot((lonlat[:, 0] - e["lon"]) * 111.32 * np.cos(np.radians(e["lat"])), (lonlat[:, 1] - e["lat"]) * 110.57)
    nearest = int(np.argmin(km))
    if km[nearest] > 1.0:
        sys.exit(f"The traced river passes {km[nearest]:.1f} km from {e['name']}; check the start point or search box.")
    steps = np.hypot(np.diff(lonlat[:, 0]) * 111.32 * np.cos(np.radians(e["lat"])), np.diff(lonlat[:, 1]) * 110.57)
    along = np.concatenate([[0], np.cumsum(steps)])
    keep = along <= along[nearest] + VALLEY["past_end_m"] / 1000
    return lonlat[keep], float(along[nearest]), float(km[nearest])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", default=os.environ.get("EE_PROJECT"),
                        help="Google Cloud project registered for Earth Engine")
    parser.add_argument("--out", type=Path, default=REPO / "web" / "public" / "data" / VALLEY["id"] / "terrain")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    preview_dir = PIPELINE / "out" / "p0_terrain"
    preview_dir.mkdir(parents=True, exist_ok=True)

    import ee

    try:
        ee.Initialize(project=args.project)
    except Exception as exc:  # the client raises plain Exceptions for missing sign-in or project access
        sys.exit(f"Earth Engine would not start: {exc}\nSee pipeline/README.md for sign-in and project setup.")

    print("Tracing the river on MERIT Hydro flow directions ...", flush=True)
    directions, x0, y0 = terrain.merit_directions(*VALLEY["search"])
    river, river_km, miss_km = trace_river(directions, x0, y0)
    print(f"  {len(river)} steps, {river_km:.1f} km from the lake to {VALLEY['end']['name']} "
          f"(passes {1000 * miss_km:.0f} m from the town point)")

    places = [VALLEY["start"], VALLEY["end"]]
    utm = terrain.to_utm([tuple(p) for p in river] + [(p["lon"], p["lat"]) for p in places])
    river_utm, places_utm = utm[: len(river)], utm[len(river):]

    hw, block = VALLEY["half_width_m"], 4 * CELL
    left = np.floor((river_utm[:, 0].min() - hw) / block) * block
    right = np.ceil((river_utm[:, 0].max() + hw) / block) * block
    bottom = np.floor((river_utm[:, 1].min() - hw) / block) * block
    top = np.ceil((river_utm[:, 1].max() + hw) / block) * block
    width, height = int((right - left) / CELL), int((top - bottom) / CELL)
    print(f"Fetching GLO-30 on a {width} x {height} grid of {CELL:g} m cells ({width * CELL / 1000:.1f} x "
          f"{height * CELL / 1000:.1f} km, UTM 45N) ...", flush=True)
    dem = terrain.glo30_utm(left, top, width, height, CELL)

    xs = left + (np.arange(width) + 0.5) * CELL
    ys = top - (np.arange(height) + 0.5) * CELL
    line = river_utm[::3] if len(river_utm) > 3 else river_utm
    dist = terrain.distance_to_polyline(xs[None, :], ys[:, None], np.vstack([line, river_utm[-1:]]))
    h30 = np.where(dist <= hw, dem, np.nan)
    levels = {30: h30, 60: terrain.block_mean(h30, 2), 120: terrain.block_mean(h30, 4)}
    offset = float(np.floor(np.nanmin(h30)))

    # Checks against known elevations
    results = []
    lake_x, lake_y = places_utm[0]
    town_x, town_y = places_utm[1]
    near_lake = np.hypot(xs[None, :] - lake_x, ys[:, None] - lake_y) <= 300
    near_town = np.hypot(xs[None, :] - town_x, ys[:, None] - town_y) <= 1000
    values = [float(np.nanmedian(dem[near_lake])), float(np.nanmin(dem[near_town]))]
    for (what, low, high, how), value in zip(CHECKS, values):
        results.append((what, value, low, high, how))

    files, served = {}, 0
    for size, grid in levels.items():
        data = terrain.encode(grid, offset)
        name = f"height{size}.u16"
        raw = data.tobytes()
        (args.out / name).write_bytes(raw)
        files[name] = (len(raw), len(gzip.compress(raw, 9)), grid.shape)
        served += files[name][1]
    corridor = np.where(dist <= hw, np.minimum(np.round(dist / 25), 254), 255).astype(np.uint8)
    (args.out / "corridor.u8").write_bytes(corridor.tobytes())
    files["corridor.u8"] = (corridor.nbytes, len(gzip.compress(corridor.tobytes(), 9)), corridor.shape)

    def grid_xy(x, y):  # UTM metres to 30 m grid coordinates (column, row); cell centres sit at +0.5
        return [round((x - left) / CELL, 2), round((top - y) / CELL, 2)]

    manifest = {
        "valley": VALLEY["name"],
        "crs": terrain.UTM_45N,
        "origin": {"x": left, "y": top, "note": "UTM metres of the grid's top-left (north-west) corner"},
        "offset_m": offset,
        "scale_m": terrain.SCALE,
        "nodata": terrain.NODATA,
        "levels": [{"file": f"height{s}.u16", "cell_m": float(s), "width": g.shape[1], "height": g.shape[0]}
                   for s, g in levels.items()],
        "corridor": {"file": "corridor.u8", "step_m": 25, "outside": 255, "half_width_m": hw},
        "river": {"grid": [grid_xy(x, y) for x, y in river_utm[::2]], "length_km": round(river_km, 1)},
        "places": [{"name": p["name"], "grid": grid_xy(x, y)} for p, (x, y) in zip(places, places_utm)],
        "sources": ["Copernicus GLO-30 DEM, 2024 edition (ESA), via Google Earth Engine COPERNICUS/DEM/GLO30_2024_1",
                    "MERIT Hydro v1.0.1 flow directions (Yamazaki et al. 2019), via Earth Engine"],
    }
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=1))

    preview(levels[30], river_utm, places_utm, left, top, preview_dir / "preview.png")

    print(f"\nCorridor: {int(np.isfinite(h30).sum()):,} cells of {CELL:g} m "
          f"({np.isfinite(h30).sum() * CELL * CELL / 1e6:.0f} km2), elevations {offset:.0f}-{np.nanmax(h30):.0f} m")
    print(f"  {'file':<14} {'raw':>9} {'gzip':>9}  grid")
    for name, (raw, gz, shape) in files.items():
        print(f"  {name:<14} {raw / 1e6:>7.2f}MB {gz / 1e6:>7.2f}MB  {shape[1]} x {shape[0]}")

    print("\nChecks:")
    passed = 0
    for what, value, low, high, how in results:
        ok = low <= value <= high
        passed += ok
        print(f"  {'PASS' if ok else 'FAIL'}  {what}: {value:.0f} m  (expected {low}-{high} m; {how})")
    ok = served <= BUDGET_BYTES
    passed += ok
    print(f"  {'PASS' if ok else 'FAIL'}  Height files as served (gzip): {served / 1e6:.2f} MB  "
          f"(budget {BUDGET_BYTES / 1e6:.0f} MB for all three levels)")
    total = len(results) + 1
    print(f"\n{passed} of {total} checks passed. Files: {args.out}  Preview: {preview_dir / 'preview.png'}")
    return 0 if passed == total else 1


def preview(h30, river_utm, places_utm, left, top, path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    shade = terrain.hillshade(h30, CELL)
    rgba = plt.get_cmap("gray")(0.25 + 0.75 * shade)
    rgba[np.isnan(h30)] = (0.99, 0.99, 0.98, 1)
    fig, ax = plt.subplots(figsize=(9, 9 * h30.shape[0] / h30.shape[1]), dpi=130)
    ax.imshow(rgba, extent=(0, h30.shape[1], h30.shape[0], 0))
    ax.plot((river_utm[:, 0] - left) / CELL, (top - river_utm[:, 1]) / CELL, color="#2a78d6", linewidth=1.6)
    for (x, y), place in zip(places_utm, (VALLEY["start"], VALLEY["end"])):
        ax.plot((x - left) / CELL, (top - y) / CELL, "o", color="#eb6834", markersize=6)
        ax.annotate(place["name"], ((x - left) / CELL, (top - y) / CELL), xytext=(8, 6), textcoords="offset points",
                    fontsize=9, color="#0b0b0b")
    ax.set_axis_off()
    ax.set_title(f"{VALLEY['name']}: GLO-30 within {VALLEY['half_width_m'] / 1000:g} km of the river (north up)",
                 loc="left", fontsize=10)
    fig.tight_layout()
    fig.savefig(path, facecolor="#fcfcfb")
    plt.close(fig)


if __name__ == "__main__":
    sys.exit(main())
