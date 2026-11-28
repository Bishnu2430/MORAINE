"""P1 step 7a: every inventory lake's area each autumn 2017-2025, mapped with the U-Net.

    .venv\\Scripts\\python pipeline\\scripts\\p1_growth.py --project YOUR-CLOUD-PROJECT

1. Flags (Earth Engine): cloud near and over every inventory lake of the three study areas, for every
   Sentinel-2 scene of 1 Sep-31 Dec, 2017-2025 (moraine/hard_cases.py; cached in
   pipeline/out/p1_growth/stats/). About 30 minutes.
2. Maps (Earth Engine and the U-Net, pipeline/data/p1_unet/model.pt): for each lake and autumn, its
   scenes up to 15 November best first (moraine/growth.py) are fetched as tiles round the lake until
   three lie wholly inside the swath, and those are mapped. Lake probabilities are saved per lake and
   autumn in pipeline/data/p1_growth/ (not in git), with the scenes tried, so a rerun resumes. About an
   hour.
3. Areas and the checks fixed in docs/p1/plan.md (step 7a). Writes docs/p1/growth.json and
   docs/p1/growth.png.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PIPELINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PIPELINE))
sys.path.insert(0, str(PIPELINE / "scripts"))

import numpy as np  # noqa: E402

from moraine import growth, inventory, plot, study_areas, terrain, tiles, unet, watch  # noqa: E402

DATA = PIPELINE / "data" / "zhang2023"
OUT = PIPELINE / "out" / "p1_growth"
MAPS = PIPELINE / "data" / "p1_growth"
DOCS = PIPELINE.parent / "docs" / "p1"
AREAS = ("sikkim", "bhote_koshi", "khumbu")
SOUTH_LHONAK = (88.191, 27.913)
OUTBURST = "2023-10-04"  # South Lhonak burst late on 3 October 2023
WORKERS = 4


def lakes_by_area(by_year: dict) -> dict:
    """{area: (geometry, [lake dicts])}: every lake of the 2022 file inside the area, with its outlines
    from each inventory year (paired by inventory.match)."""
    pairs = {y: inventory.match(by_year[y], by_year[2022], y, rounded=True) for y in inventory.YEARS[:-1]}
    outlines = json.loads((PIPELINE / "moraine" / "study_areas.geojson").read_text())
    out = {}
    for key in AREAS:
        feature = next(f for f in outlines["features"] if f["properties"]["id"] == key)
        polygons = study_areas.polygons_of(feature["geometry"])
        lakes = []
        for lake in by_year[2022]:
            if not study_areas.contains(polygons, lake.lon, lake.lat):
                continue
            i22 = lake.attrs["index"]
            years = {2022: lake} | {y: by_year[y][pairs[y][i22]] for y in pairs if i22 in pairs[y]}
            lakes.append({"i22": i22, "lon": lake.lon, "lat": lake.lat, "outlines": years,
                          "listed_km2": {y: round(lk.area_km2, 5) for y, lk in years.items()}})
        out[key] = (feature["geometry"], lakes)
    return out


def tile_image(scene: str, lakes_near: list[dict]):
    import ee

    painted = []
    for lake in lakes_near:
        for outline in lake["outlines"].values():
            painted.append(ee.Feature(ee.Geometry.Polygon([[list(p) for p in ring] for ring in outline.rings], None,
                                                          False), {"v": lake["i22"] + 1}))
    ids = ee.Image(0).paint(ee.FeatureCollection(painted), "v").rename("ids").toUint16()
    bands = ee.Image(f"{watch.S2_L1C}/{scene}").select(list(unet.BANDS)).toUint16()
    slope = watch.slope_deg().multiply(100).round().rename("slope_x100").toUint16()
    return ee.Image.cat(bands, slope, ids)


def fetch(scene: str, lakes_near: list[dict], box: tuple) -> dict:
    import ee

    x0, y_top, size = box
    for attempt in range(3):
        try:
            data = ee.data.computePixels({
                "expression": tile_image(scene, lakes_near), "fileFormat": "NUMPY_NDARRAY",
                "grid": {"dimensions": {"width": size, "height": size},
                         "affineTransform": {"scaleX": tiles.CELL, "shearX": 0, "translateX": x0,
                                             "shearY": 0, "scaleY": -tiles.CELL, "translateY": y_top},
                         "crsCode": "EPSG:32645"}})
            return {name: data[name] for name in data.dtype.names}
        except Exception as exc:  # Earth Engine timeouts and quota errors: wait and retry
            error = exc
            time.sleep(15 * (attempt + 1))
    raise error


def whole(data: dict) -> bool:
    """The scene covers the whole tile in every band (no empty cells off the edge of the swath; the
    bands' edges differ by a few cells)."""
    return all(bool((data[b] > 0).all()) for b in unet.BANDS)


def done(path: Path, ranked: list[dict], want: int) -> bool:
    """A saved map tried exactly the scenes the current ranking would (growth.take, replayed with the
    saved outcome of each scene tried)."""
    if not path.exists():
        return False
    try:
        with np.load(path) as saved:
            if "tried" not in saved.files:  # saved before tiles were checked for the swath edge
                return False
            tried, kept = [str(s) for s in saved["tried"]], {str(s) for s in saved["scenes"]}
            saved["probs"]  # a file cut short (say by a shutdown mid-write) fails here
    except Exception:  # unreadable: map it again
        return False
    _, replay = growth.take(ranked, want, lambda r: r["scene"] in kept)
    return [r["scene"] for r in replay] == tried


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", default=os.environ.get("EE_PROJECT"))
    parser.add_argument("--area", choices=AREAS, action="append")
    args = parser.parse_args()

    import ee
    import p1_hard_cases

    try:
        ee.Initialize(project=args.project)
    except Exception as exc:  # the client raises plain Exceptions for missing sign-in or project access
        sys.exit(f"Earth Engine would not start: {exc}\nSee pipeline/README.md for sign-in and project setup.")
    (OUT / "stats").mkdir(parents=True, exist_ok=True)
    MAPS.mkdir(parents=True, exist_ok=True)
    by_year = {year: inventory.load(DATA, year) for year in inventory.YEARS}
    areas = {k: v for k, v in lakes_by_area(by_year).items() if k in (args.area or AREAS)}
    model, _ = unet.load(PIPELINE / "data" / "p1_unet" / "model.pt")

    # 1. Flags for every lake and scene, 2017-2025
    rows = {}
    for key, (geometry, lakes) in areas.items():
        lakes22 = [by_year[2022][lake["i22"]] for lake in lakes]
        area = {"geometry": geometry, "lakes": {y: lakes22 for y in growth.YEARS}}
        for year in growth.YEARS:
            got = p1_hard_cases.measure(key, area, year, OUT / "stats")
            if got is None:
                print(f"Flags incomplete for {key} {year}; rerun to finish")
                return 1
            for r in got:
                rows.setdefault((r["id"], year), []).append(r)
    print(f"1. Flags: {sum(len(v) for v in rows.values()):,} lake-scenes", flush=True)

    # 2. Scenes, tiles and U-Net maps per lake and autumn
    every = [lake for _, lakes in areas.values() for lake in lakes]
    corners = [(lk.bbox[i], lk.bbox[j]) for lake in every for lk in lake["outlines"].values() for i, j in ((0, 1), (2, 3))]
    utm = iter(terrain.to_utm(corners).tolist())
    for lake in every:
        points = [next(utm) for lk in lake["outlines"].values() for _ in range(2)]
        lake["box"] = growth.tile_box([p[0] for p in points], [p[1] for p in points])
    south_lhonak = min(every, key=lambda lk: (lk["lon"] - SOUTH_LHONAK[0]) ** 2 + (lk["lat"] - SOUTH_LHONAK[1]) ** 2)
    jobs, plan = [], {}
    for lake in every:
        near = [o for o in every if abs(o["lon"] - lake["lon"]) < 0.08 and abs(o["lat"] - lake["lat"]) < 0.08]
        for year in growth.YEARS:
            ranked = growth.candidates(rows.get((lake["i22"], year), []), year)
            many = lake is south_lhonak and year == 2023  # every usable scene, to see the outburst
            want = len(ranked) if many else growth.PER_AUTUMN
            path = MAPS / f"{lake['i22']}_{year}.npz"
            plan[lake["i22"], year] = (path, ranked, want)
            if ranked and not done(path, ranked, want):
                jobs.append((lake, year, ranked, want, near, path))
    print(f"2. Maps: {len(jobs)} lake-autumns to map", flush=True)

    def fetch_job(job):
        lake, year, ranked, want, near, _ = job
        datas = {}

        def fetched_whole(r):
            data = fetch(r["scene"], near, lake["box"])
            if whole(data):
                datas[r["scene"]] = data
                return True
            return False

        try:
            kept, tried = growth.take(ranked, want, fetched_whole)
            return [(r, datas[r["scene"]]) for r in kept], [r["scene"] for r in tried]
        except Exception as exc:  # skipped now, retried on the next run
            print(f"  {lake['i22']} {year}: fetch failed, will retry next run: {str(exc)[:100]}", flush=True)
            return None

    start, failed, cut = time.time(), 0, 0
    with ThreadPoolExecutor(WORKERS) as pool:  # workers fetch; this thread runs the U-Net
        for n, (job, got) in enumerate(zip(jobs, pool.map(fetch_job, jobs)), 1):
            lake, year, ranked, want, near, path = job
            if got is None:
                failed += 1
                continue
            kept, tried = got
            cut += len(tried) - len(kept)
            size = lake["box"][2]
            probs = [np.round(unet.predict(model, np.stack([d[b] for b in unet.RAW])) * 255).astype(np.uint8)
                     for _, d in kept]
            np.savez_compressed(path, probs=np.stack(probs) if probs else np.zeros((0, size, size), np.uint8),
                                ids=kept[0][1]["ids"].astype(np.uint16) if kept else np.zeros((size, size), np.uint16),
                                scenes=np.array([r["scene"] for r, _ in kept], dtype=str),
                                dates=np.array([r["date"] for r, _ in kept], dtype=str),
                                tiers=np.array([r["tier"] for r, _ in kept], dtype=np.int64), tried=np.array(tried))
            if n % 50 == 0 or n == len(jobs):
                print(f"  {n}/{len(jobs)} lake-autumns, {cut} scenes cut by the swath edge so far, "
                      f"{time.time() - start:.0f} s", flush=True)
    if failed:
        print(f"{failed} lake-autumns failed to fetch; rerun to finish them")
        return 1

    # 3. Areas and checks
    series = []
    for key, (_, lakes) in areas.items():
        for lake in lakes:
            entry = {"area": key, "i22": lake["i22"], "lon": round(lake["lon"], 5), "lat": round(lake["lat"], 5),
                     "listed_km2": lake["listed_km2"], "autumns": {}}
            for year in growth.YEARS:
                path, ranked, want = plan[lake["i22"], year]
                if not ranked or not done(path, ranked, want):  # no usable scene (a map left by an older ranking)
                    continue
                with np.load(path) as saved:
                    if len(saved["scenes"]) == 0:  # every usable scene was cut by the swath edge
                        continue
                    probs, ids = saved["probs"].astype(np.float32) / 255, saved["ids"]
                    scenes = [{"date": str(d), "tier": int(t), "km2": round(growth.lake_area(p, ids, lake["i22"] + 1), 5)}
                              for d, t, p in zip(saved["dates"], saved["tiers"], probs)]
                    best = probs[np.argsort([s["tier"] for s in scenes], kind="stable")[:growth.PER_AUTUMN]]
                    autumn = growth.lake_area(np.median(best, axis=0), ids, lake["i22"] + 1)
                entry["autumns"][year] = {"km2": round(autumn, 5), "scenes": scenes}
            series.append(entry)

    total = len(series) * len(growth.YEARS)
    mapped = sum(len(s["autumns"]) for s in series)
    ratios = [s["autumns"][y]["km2"] / s["listed_km2"][y] for s in series for y in inventory.YEARS
              if s["listed_km2"].get(y, 0) >= 0.02 and y in s["autumns"]]
    totals = {}
    for key in areas:
        for y in inventory.YEARS:
            group = [s for s in series if s["area"] == key and s["listed_km2"].get(y, 0) >= 0.02 and y in s["autumns"]]
            totals[f"{key} {y}"] = (sum(s["autumns"][y]["km2"] for s in group), sum(s["listed_km2"][y] for s in group))
    sl = next(s for s in series if s["i22"] == south_lhonak["i22"])
    sl_gaps = {y: sl["autumns"][y]["km2"] / sl["listed_km2"][y] - 1 for y in inventory.YEARS if y in sl["autumns"]}
    sl_2023 = sl["autumns"].get(2023, {}).get("scenes", [])
    before = [s["km2"] for s in sl_2023 if s["date"] < OUTBURST]
    after = [s["km2"] for s in sl_2023 if s["date"] >= OUTBURST]
    drop = statistics.median(before) - statistics.median(after) if before and after else None
    checks = [
        ("lake-autumns with a usable scene, at least 90%", mapped >= 0.9 * total, f"{mapped} of {total}"),
        ("inventory years: median mapped/listed area within 10% of 1", abs(statistics.median(ratios) - 1) <= 0.10,
         f"median {statistics.median(ratios):.3f} over {len(ratios)} lake-years"),
        ("inventory years: every study area's total within 10%", all(abs(m / l - 1) <= 0.10 for m, l in totals.values()),
         ", ".join(f"{k} {100 * (m / l - 1):+.0f}%" for k, (m, l) in totals.items())),
        ("South Lhonak within 5% of the inventory in 2018, 2020 and 2022",
         len(sl_gaps) == 3 and all(abs(g) <= 0.05 for g in sl_gaps.values()),
         ", ".join(f"{y} {100 * g:+.1f}%" for y, g in sl_gaps.items())),
        ("South Lhonak 2023: median area after the outburst at least 0.15 km2 below before",
         drop is not None and drop >= 0.15,
         f"{len(before)} scenes before, {len(after)} after; drop {drop:.3f} km2" if drop is not None else "missing scenes"),
    ]
    result = {"checks": [{"name": n, "passed": ok, "detail": d} for n, ok, d in checks],
              "totals_inventory_years": {k: {"mapped_km2": round(m, 3), "listed_km2": round(l, 3)}
                                         for k, (m, l) in totals.items()},
              "south_lhonak_i22": south_lhonak["i22"], "lakes": series}
    (DOCS / "growth.json").write_text(json.dumps(result, indent=1))
    plot.plot_growth(series, sl, OUTBURST, DOCS / "growth.png")
    print("\n3. Areas. Checks:")
    for name, ok, detail in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}: {detail}")
    passed = sum(ok for _, ok, _ in checks)
    print(f"\n{passed} of {len(checks)} checks passed. Details: {DOCS / 'growth.json'}")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
