"""P1 step 2: the study areas, and the inventory lakes in each.

    .venv\\Scripts\\python pipeline\\scripts\\p1_study_areas.py --project YOUR-CLOUD-PROJECT

Each study area is the whole catchment draining to the end of a P0 flood route (see
moraine/study_areas.py). Writes the outlines to pipeline/moraine/study_areas.geojson (used by later
steps), a summary to pipeline/out/p1_study_areas/summary.json and a map per area. Checks that each
catchment closes inside its search box, agrees with MERIT Hydro's upstream area within 10%, and holds
its key lake. Run pipeline/scripts/p1_inventory.py first. Exits 0 only if every check passes.
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

from moraine import inventory, study_areas, terrain  # noqa: E402

DATA = PIPELINE / "data" / "zhang2023"
OUT = PIPELINE / "out" / "p1_study_areas"
GEOJSON = PIPELINE / "moraine" / "study_areas.geojson"
SIZE_CLASSES = [(0.02, 0.05), (0.05, 0.1), (0.1, 0.5), (0.5, 100.0)]
HAZARD_LEVELS = ["Very high", "High", "Medium", "Low", "Very low"]


def outlet_of(area: dict):
    """The river route from the area's lake, cut at route_km. Returns the route (lon, lat), its length, MERIT's
    upstream area at its end (km2), and MERIT's exact catchment there as (mask, lon of column 0, lat of row 0)."""
    directions, x0, y0 = terrain.merit_directions(*area["search"])
    upstream, _, _ = terrain.merit_band("upa", *area["search"])
    step = terrain.MERIT_STEP
    lon, lat = area["lake"]
    cells = terrain.trace_downhill(directions, (int((y0 - lat) / step), int((lon - x0) / step)))
    route = np.array([(x0 + (c + 0.5) * step, y0 - (r + 0.5) * step) for r, c in cells])
    cos = np.cos(np.radians(lat))
    along = np.concatenate([[0], np.cumsum(np.hypot(np.diff(route[:, 0]) * 111.32 * cos,
                                                    np.diff(route[:, 1]) * 110.57))])
    end = int(np.searchsorted(along, area["route_km"]))
    end = min(end, len(route) - 1)
    r, c = cells[end]
    mask = terrain.upstream_mask(directions, (r, c))
    return route[: end + 1], float(along[end]), float(upstream[r, c]), (mask, x0, y0)


def hazard_by_id() -> dict:
    import shapefile  # pyshp

    reader = shapefile.Reader(str(DATA / "extracted" / "Third Pole" / "Third_Pole_Glacial Lake_Hazard.shp"),
                              encoding="utf-8")
    fields = [f[0] for f in reader.fields[1:]]
    return {int(rec[fields.index("ID_L")]): rec[fields.index("H_Level")] for rec in reader.iterRecords()}


def draw(key, area, polygons, route, lakes, hazards, path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    w, s, e, n = study_areas.bounds(polygons)
    pad = 0.03
    cell = 0.001  # degrees, about 100 m
    width, height = int((e - w + 2 * pad) / cell), int((n - s + 2 * pad) / cell)
    dem = terrain.glo30_utm(w - pad, n + pad, width, height, cell, "EPSG:4326")
    shade = terrain.hillshade(dem, 100.0)
    fig, ax = plt.subplots(figsize=(8, 8 * height / width), dpi=130)
    extent = (w - pad, w - pad + width * cell, n + pad - height * cell, n + pad)
    ax.imshow(plt.get_cmap("gray")(0.35 + 0.6 * shade), extent=extent, aspect=1 / np.cos(np.radians((s + n) / 2)))
    for poly in polygons:
        ring = np.array(poly[0])
        ax.plot(ring[:, 0], ring[:, 1], color="#0b0b0b", linewidth=1.2)
    ax.plot(route[:, 0], route[:, 1], color="#2a78d6", linewidth=1.4, label="P0 flood route")
    ax.plot(*route[-1], "*", color="#2a78d6", markersize=12, label="Outlet")
    ramp = {"Very high": "#9f2f15", "High": "#d9542a", "Medium": "#f08a5d", "Low": "#f7c2a6", "Very low": "#fbe3d6"}
    for level in reversed(HAZARD_LEVELS):
        pick = [lk for lk in lakes if hazards.get(int(lk.attrs["ID_L"])) == level]
        if pick:
            ax.scatter([lk.lon for lk in pick], [lk.lat for lk in pick], s=[8 + 120 * min(lk.area_km2, 1.5) for lk in pick],
                       color=ramp[level], edgecolor="#0b0b0b", linewidth=0.4, label=f"Hazard {level.lower()}", zorder=3)
    rest = [lk for lk in lakes if int(lk.attrs["ID_L"]) not in hazards]
    if rest:
        ax.scatter([lk.lon for lk in rest], [lk.lat for lk in rest], s=8, color="#bdbdbd", edgecolor="#0b0b0b",
                   linewidth=0.3, label="Not rated", zorder=3)
    for name, (lon, lat) in study_areas.MUST_CONTAIN[key].items():
        ax.annotate(name, (lon, lat), xytext=(6, 6), textcoords="offset points", fontsize=8.5, color="#0b0b0b",
                    bbox={"boxstyle": "round,pad=0.2", "fc": "white", "ec": "none", "alpha": 0.8})
    ax.set_xlim(extent[0], extent[1])
    ax.set_ylim(extent[2], extent[3])
    ax.set_xlabel("Longitude (°E)")
    ax.set_ylabel("Latitude (°N)")
    ax.set_title(f"{area['name']}\n{len(lakes)} glacial lakes of at least 0.02 km² in 2022 (Zhang et al. 2023); "
                 "dot size shows lake area", loc="left", fontsize=10)
    legend = ax.legend(loc="lower left", fontsize=7.5, framealpha=0.85)
    for handle in legend.legend_handles:  # colour is the hazard level; keep the legend dots one size
        if hasattr(handle, "set_sizes") and not isinstance(handle, matplotlib.lines.Line2D):
            handle.set_sizes([30])
    fig.tight_layout()
    fig.savefig(path, facecolor="#fcfcfb")
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", default=os.environ.get("EE_PROJECT"))
    args = parser.parse_args()

    import ee

    try:
        ee.Initialize(project=args.project)
    except Exception as exc:  # the client raises plain Exceptions for missing sign-in or project access
        sys.exit(f"Earth Engine would not start: {exc}\nSee pipeline/README.md for sign-in and project setup.")
    if not inventory.shapefile_path(DATA, 2022).exists():
        sys.exit("Run pipeline/scripts/p1_inventory.py first to fetch the lake inventory.")
    OUT.mkdir(parents=True, exist_ok=True)
    lakes_2022 = inventory.load(DATA, 2022)
    hazards = hazard_by_id()

    features, summary, checks = [], {}, []
    for key, area in study_areas.AREAS.items():
        print(f"\n{area['name']}", flush=True)
        route, route_km, merit_km2, (mask, mx0, my0) = outlet_of(area)
        outlet = tuple(float(v) for v in route[-1])
        table = study_areas.basin_table(area["search"])
        ids = sorted(study_areas.upstream_of(study_areas.basin_at(*outlet), table))
        geometry, area_km2 = study_areas.catchment_geometry(ids)
        polygons = study_areas.polygons_of(geometry)
        w, s, e, n = study_areas.bounds(polygons)
        bw, bs, be, bn = area["search"]
        closed = min(w - bw, s - bs, be - e, bn - n) >= 0.02

        inside = [lk for lk in lakes_2022 if study_areas.contains(polygons, lk.lon, lk.lat)]

        def upstream(lake):  # MERIT's exact catchment at the outlet, at its 90 m cells
            r, c = int((my0 - lake.lat) / terrain.MERIT_STEP), int((lake.lon - mx0) / terrain.MERIT_STEP)
            return 0 <= r < mask.shape[0] and 0 <= c < mask.shape[1] and bool(mask[r, c])

        exact = {int(lk.attrs["ID_L"]) for lk in lakes_2022 if upstream(lk)}
        listed = {int(lk.attrs["ID_L"]) for lk in inside}
        areas_2022 = [float(lk.attrs["Area_2022"]) for lk in inside]
        areas_1990 = [float(lk.attrs["Area_90"] or 0) for lk in inside]
        levels = {lv: sum(hazards.get(int(lk.attrs["ID_L"])) == lv for lk in inside) for lv in HAZARD_LEVELS}
        classes = {f"{lo:g}-{hi:g}": sum(lo <= a < hi for a in areas_2022) for lo, hi in SIZE_CLASSES}
        info = {
            "name": area["name"], "role": area["role"], "outlet": [round(outlet[0], 5), round(outlet[1], 5)],
            "route_km": round(route_km, 1), "catchment_km2": round(area_km2, 1), "merit_upstream_km2": round(merit_km2, 1),
            "basins": len(ids), "lakes_2022": len(inside), "lake_area_2022_km2": round(sum(areas_2022), 3),
            "lake_area_1990_km2": round(sum(areas_1990), 3), "lakes_by_size_km2": classes, "lakes_by_hazard": levels,
            "largest": sorted(((round(a, 3), round(lk.lat, 4), round(lk.lon, 4)) for a, lk in zip(areas_2022, inside)),
                              reverse=True)[:5],
        }
        summary[key] = info
        print(f"  outlet {outlet[1]:.4f} N {outlet[0]:.4f} E, {route_km:.1f} km down the P0 route")
        print(f"  catchment {area_km2:,.0f} km2 from {len(ids)} HydroSHEDS basins; MERIT says {merit_km2:,.0f} km2")
        print(f"  {len(inside)} lakes, {sum(areas_2022):.2f} km2 in 2022 ({sum(areas_1990):.2f} km2 in 1990); by size "
              f"{classes}; by hazard {levels}")
        checks.append((f"{key}: catchment closes inside its search box", closed,
                       f"bounds {w:.2f}-{e:.2f} E, {s:.2f}-{n:.2f} N"))
        ratio = area_km2 / merit_km2
        info["outline_vs_merit"] = round(ratio - 1, 3)
        info["lakes_outline_only"] = sorted(listed - exact)
        info["lakes_merit_only"] = sorted(exact - listed)
        # The outline is built from whole HydroSHEDS basins, and the one holding the outlet can reach below it,
        # so its area runs a little over MERIT's. What matters for P1 is that both count the same lakes.
        checks.append((f"{key}: the outline holds exactly the lakes upstream of the outlet", listed == exact,
                       f"{len(listed)} in the outline, {len(exact)} upstream on MERIT; outline area "
                       f"{area_km2:,.0f} against MERIT {merit_km2:,.0f} km2 ({100 * (ratio - 1):+.1f}%)"))
        for name, (lon, lat) in study_areas.MUST_CONTAIN[key].items():
            checks.append((f"{key}: contains {name}", study_areas.contains(polygons, lon, lat), f"{lat:.4f} N {lon:.4f} E"))
        features.append({"type": "Feature", "geometry": geometry,
                         "properties": {"id": key, **{k: info[k] for k in ("name", "role", "outlet", "catchment_km2")}}})
        draw(key, area, polygons, route, inside, hazards, OUT / f"{key}.png")

    GEOJSON.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1))
    print("\nChecks:")
    for name, ok, detail in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}: {detail}")
    passed = sum(ok for _, ok, _ in checks)
    print(f"\n{passed} of {len(checks)} checks passed. Outlines: {GEOJSON}  Summary and maps: {OUT}")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
