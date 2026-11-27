"""P1 step 4: the hard-case set.

    .venv\\Scripts\\python pipeline\\scripts\\p1_hard_cases.py --project YOUR-CLOUD-PROJECT

1. Flags (Earth Engine): for every inventory lake of at least 0.02 km2 in the three study areas, and
   every Sentinel-2 scene of 1 Sep-31 Dec in each inventory year, measures cloud, terrain shadow,
   ice and water brightness inside the lake outline (moraine/hard_cases.py). Each area-year is
   cached in pipeline/out/p1_hard_cases/stats/, stamped with a fingerprint of hard_cases.py and the
   lake list. About 12 minutes.
2. Candidates: per area and category (ice, shadow, thin cloud, silty, and clear as a control), the
   lake-scenes that show the condition most strongly, one per physical lake.
3. Tiles (Earth Engine): each candidate as a 256 x 256 tile of 10 m cells (moraine/tiles.py), saved
   in pipeline/data/p1_hard_cases/ (not in git). A few minutes.
4. Contact sheets for the visual check, in pipeline/out/p1_hard_cases/sheets/. Cases that fail the
   check are listed in docs/p1/hard-case-review.json with the reason; the rest are kept in order.
5. Both baseline rules on every kept case, and the checks.

North Sikkim's cases are the test set for step 6 and are not to be used for training or tuning.
Bhote Koshi and Khumbu's are a validation set that step 5 may tune against.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
import sys
import time
from pathlib import Path

PIPELINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PIPELINE))

import numpy as np  # noqa: E402

from moraine import hard_cases, inventory, study_areas, terrain, tiles, watch  # noqa: E402

DATA = PIPELINE / "data" / "zhang2023"
OUT = PIPELINE / "out" / "p1_hard_cases"
TILES = PIPELINE / "data" / "p1_hard_cases"
DOCS = PIPELINE.parent / "docs" / "p1"
REVIEW = DOCS / "hard-case-review.json"
AREAS = ("sikkim", "bhote_koshi", "khumbu")
SPLIT = {"sikkim": "test", "bhote_koshi": "validation", "khumbu": "validation"}
CANDIDATES = {"sikkim": 20, "bhote_koshi": 10, "khumbu": 10}  # per category, before the visual check
KEEP = {"sikkim": 10, "bhote_koshi": 5, "khumbu": 5}  # per category, after it
MIN_KEPT_TEST = 8
MIN_KM2 = 0.02
CHUNK = 6  # scenes per request: about 600 lake-scenes, well inside Earth Engine's limits
# Fingerprint of the code that produces the flags, so the cache survives edits to the rest of the module
CODE = hashlib.sha1("".join(
    [inspect.getsource(f) for f in (hard_cases.scenes, hard_cases.conditions, hard_cases.neighbourhood,
                                     hard_cases.measure)]
    + [repr((hard_cases.SEASON, hard_cases.SCENE_CLOUD, hard_cases.SHADOW_REACH_PX, hard_cases.NEAR_M,
             hard_cases.CLOUDY, watch.SCALE))]
).encode()).hexdigest()[:12]


def lakes_by_area(by_year: dict) -> dict:
    """{area: {year: lakes of at least 0.02 km2 that year, from that year's own file}}."""
    outlines = json.loads((PIPELINE / "moraine" / "study_areas.geojson").read_text())
    out = {}
    for key in AREAS:
        feature = next(f for f in outlines["features"] if f["properties"]["id"] == key)
        polygons = study_areas.polygons_of(feature["geometry"])
        out[key] = {"geometry": feature["geometry"],
                    "lakes": {year: [lk for lk in lakes if lk.area_km2 >= MIN_KM2
                                     and study_areas.contains(polygons, lk.lon, lk.lat)]
                              for year, lakes in by_year.items()}}
    return out


def measure(key: str, area: dict, year: int, cache: Path) -> list[dict] | None:
    import ee

    lakes = area["lakes"][year]
    ids = sorted(int(lk.attrs["index"]) for lk in lakes)
    path = cache / f"{key}_{year}.json"
    if path.exists():
        saved = json.loads(path.read_text())
        if saved["code"] == CODE and saved["lake_ids"] == ids:
            return saved["rows"]
    region = ee.Geometry(area["geometry"])
    start = time.time()
    scene_ids = hard_cases.scenes(region, year).aggregate_array("system:index").getInfo()
    rows = []
    for i in range(0, len(scene_ids), CHUNK):
        for attempt in range(3):
            try:
                rows += hard_cases.measure(lakes, scene_ids[i:i + CHUNK], region, year)
                break
            except Exception as exc:  # Earth Engine timeouts and quota errors: wait and retry
                print(f"  {key} {year} scenes {i}-{i + CHUNK}: attempt {attempt + 1} failed: {exc}", flush=True)
                time.sleep(30)
        else:
            print(f"  {key} {year}: giving up, nothing cached", flush=True)
            return None
    path.write_text(json.dumps({"code": CODE, "lake_ids": ids, "scenes": len(scene_ids), "rows": rows}))
    print(f"{key} {year}: {len(scene_ids)} scenes, {len(rows)} lake-scenes, {time.time() - start:.0f} s", flush=True)
    return rows


def candidates(rows: dict, by_year: dict) -> list[dict]:
    """Stage 2: the candidate cases, in order, with ids like sikkim-shadow-03."""
    same_lake = {(2022, lk.attrs["index"]): lk.attrs["index"] for lk in by_year[2022]}
    for year in inventory.YEARS[:-1]:
        same_lake.update({(year, i): i22 for i22, i in inventory.match(by_year[year], by_year[2022], year).items()})
    cases = []
    for key in AREAS:
        everything = [r for year in inventory.YEARS for r in rows[key][year]]
        for category, picked in hard_cases.choose(everything, same_lake, CANDIDATES[key]).items():
            for n, r in enumerate(picked, 1):
                lake = by_year[r["year"]][r["id"]]
                cases.append({"case": f"{key}-{category}-{n:02d}", "area": key, "split": SPLIT[key],
                              "category": category, "year": r["year"], "lake_index": r["id"],
                              "lake_2022": same_lake.get((r["year"], r["id"])), "lon": round(lake.lon, 5),
                              "lat": round(lake.lat, 5), "lake_km2": round(lake.area_km2, 4), "date": r["date"],
                              "scene": r["scene"], **{f: round(r[f], 3) for f in hard_cases.FIELDS},
                              "red_rise": None if r["red_rise"] is None else round(r["red_rise"], 3)})
    return cases


def export(cases: list[dict], by_year: dict) -> None:
    """Stage 3: one .npz tile per case, skipping tiles already saved."""
    TILES.mkdir(parents=True, exist_ok=True)
    todo = [c for c in cases if not tile_matches(c)]
    if not todo:
        return
    centres = terrain.to_utm([(c["lon"], c["lat"]) for c in todo])
    half = tiles.SIZE * tiles.CELL / 2
    for case, (cx, cy) in zip(todo, centres):
        lakes = by_year[case["year"]]
        lake = lakes[case["lake_index"]]
        near = [lk for lk in lakes if abs(lk.lon - lake.lon) < 0.05 and abs(lk.lat - lake.lat) < 0.05]
        x0 = round(cx / tiles.CELL) * tiles.CELL - half
        y_top = round(cy / tiles.CELL) * tiles.CELL + half
        for attempt in range(3):
            try:
                data = hard_cases.fetch_tile(hard_cases.tile_image(case["scene"], near, lake), x0, y_top,
                                             tiles.SIZE, tiles.CELL)
                break
            except Exception as exc:  # Earth Engine timeouts and quota errors: wait and retry
                print(f"  {case['case']}: attempt {attempt + 1} failed: {exc}", flush=True)
                time.sleep(20)
        else:
            continue
        np.savez_compressed(
            TILES / f"{case['case']}.npz", **{b: data[b].astype(np.uint16) for b in ("B2", "B3", "B4", "B8", "B11", "B12")},
            cloud=data["cloud"].astype(np.uint8), slope=(data["slope_x100"] / 100).astype(np.float32),
            label=data["label"].astype(np.uint8), lake=data["lake"].astype(np.uint8),
            x0=np.float64(x0), y_top=np.float64(y_top), scene=np.str_(case["scene"]),
            lake_index=np.int64(case["lake_index"]))
        print(f"  tile {case['case']}", flush=True)


def tile_matches(case: dict) -> bool:
    """A saved tile exists for this case's scene and lake (case numbers move when the selection changes)."""
    path = TILES / f"{case['case']}.npz"
    if not path.exists():
        return False
    with np.load(path) as data:
        return "scene" in data.files and str(data["scene"]) == case["scene"] and int(data["lake_index"]) == case["lake_index"]


def fully_covered(case: dict) -> bool:
    """The scene covers the whole tile (no empty cells off the edge of the swath)."""
    with np.load(TILES / f"{case['case']}.npz") as data:
        return bool((data["B2"] > 0).all())


def sheet(cases: list[dict], title: str, path: Path, show_baseline: bool = False) -> None:
    """Stage 4: true-colour tiles in a grid, the case's lake outlined in cyan and other lakes in yellow."""
    from moraine import plot

    panels = []
    for case in cases:
        tile = tiles.load(TILES / f"{case['case']}.npz")
        flag = {"ice": "ice", "shadow": "shadow", "thin_cloud": "red_rise", "silty": "nir",
                "clear": "cloud_near"}[case["category"]]
        panels.append((tile, tiles.baseline(tile) if show_baseline else None,
                       f"{case['case'].split('-', 1)[1]}\n{case['date']}, {flag} {case[flag]:.2f}"))
    plot.plot_tiles(panels, title, path)


def kept(cases: list[dict], review: dict) -> list[dict]:
    """Cases that passed the visual check, the first KEEP of each area and category."""
    out, counts = [], {}
    for case in cases:
        if case["case"] in review:
            continue
        group = (case["area"], case["category"])
        if counts.get(group, 0) < KEEP[case["area"]]:
            counts[group] = counts.get(group, 0) + 1
            out.append(case)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", default=os.environ.get("EE_PROJECT"))
    args = parser.parse_args()

    import ee

    try:
        ee.Initialize(project=args.project)
    except Exception as exc:  # the client raises plain Exceptions for missing sign-in or project access
        sys.exit(f"Earth Engine would not start: {exc}\nSee pipeline/README.md for sign-in and project setup.")
    cache = OUT / "stats"
    cache.mkdir(parents=True, exist_ok=True)
    by_year = {year: inventory.load(DATA, year) for year in inventory.YEARS}
    areas = lakes_by_area(by_year)
    rows = {key: {year: measure(key, area, year, cache) for year in inventory.YEARS} for key, area in areas.items()}
    missing = [f"{k} {y}" for k, years in rows.items() for y, r in years.items() if r is None]
    if missing:
        print(f"Flags incomplete, rerun to finish: {', '.join(missing)}")
        return 1
    print(f"1. Flags: {sum(len(r) for years in rows.values() for r in years.values()):,} lake-scenes measured")

    cases = candidates(rows, by_year)
    (OUT / "candidates.json").write_text(json.dumps(cases, indent=1))
    print(f"2. Candidates: {len(cases)}")
    export(cases, by_year)
    missing_tiles = [c["case"] for c in cases if not tile_matches(c)]
    if missing_tiles:
        print(f"Tiles incomplete, rerun to finish: {', '.join(missing_tiles)}")
        return 1
    partial = [c["case"] for c in cases if not fully_covered(c)]
    cases = [c for c in cases if c["case"] not in partial]
    print(f"3. Tiles: {len(cases) + len(partial)} in {TILES}; {len(partial)} dropped for running off the scene's edge")

    sheets = OUT / "sheets"
    sheets.mkdir(exist_ok=True)
    for category in hard_cases.CATEGORIES:
        for split in ("test", "validation"):
            group = [c for c in cases if c["category"] == category and c["split"] == split]
            sheet(group, f"Candidates: {category.replace('_', ' ')}, {split} "
                         f"({'North Sikkim' if split == 'test' else 'Bhote Koshi and Khumbu'})",
                  sheets / f"{split}-{category}.png")
    if not REVIEW.exists():
        print(f"4. Contact sheets in {sheets}. Record the cases that fail the visual check in {REVIEW} "
              "as {case: reason}, then rerun.")
        return 0
    review = json.loads(REVIEW.read_text())
    final = kept(cases, review)
    print(f"4. Visual check: {len(review)} candidates dropped, {len(final)} cases kept")

    for case in final:
        tile = tiles.load(TILES / f"{case['case']}.npz")
        case["baseline"] = {v: tiles.score(tiles.baseline(tile, v), tile) for v in ("ndwi", "ndwi_mndwi")}
    (DOCS / "hard-cases.json").write_text(json.dumps(final, indent=1))
    for split in ("test", "validation"):
        group = [c for c in final if c["split"] == split]
        sheet(group, f"Kept cases, {split}: baseline (NDWI rule) in magenta, case lake cyan, other lakes yellow",
              DOCS / f"hard-cases-{split}.jpg", show_baseline=True)

    import statistics

    checks = []
    print("\n5. Baseline on the kept cases (median overlap with the inventory lakes within 500 m of the case's "
          "lake, NDWI rule / with MNDWI):")
    for split in ("test", "validation"):
        print(f"  {split}:")
        medians = {}
        for category in hard_cases.CATEGORIES:
            group = [c for c in final if c["split"] == split and c["category"] == category]
            if not group:
                continue
            ious = {v: [c["baseline"][v]["iou"] for c in group] for v in ("ndwi", "ndwi_mndwi")}
            medians[category] = statistics.median(ious["ndwi"])
            print(f"    {category:<11} {len(group):>2} cases: {statistics.median(ious['ndwi']):.2f} / "
                  f"{statistics.median(ious['ndwi_mndwi']):.2f}")
        hard = [c["baseline"]["ndwi"]["iou"] for c in final if c["split"] == split and c["category"] != "clear"]
        easy = [c["baseline"]["ndwi"]["iou"] for c in final if c["split"] == split and c["category"] == "clear"]
        if hard and easy:
            checks.append((f"{split}: the baseline does worse on hard cases than on clear ones",
                           statistics.median(hard) < statistics.median(easy),
                           f"median overlap {statistics.median(hard):.2f} against {statistics.median(easy):.2f}"))
    for category in hard_cases.CATEGORIES:
        n = sum(c["split"] == "test" and c["category"] == category for c in final)
        checks.append((f"test: at least {MIN_KEPT_TEST} {category.replace('_', ' ')} cases", n >= MIN_KEPT_TEST, f"{n} kept"))
    test_lakes = {c["lake_2022"] for c in final if c["split"] == "test"}
    other = {c["lake_2022"] for c in final if c["split"] != "test"}
    checks.append(("no test lake is also a validation lake", not (test_lakes & other), f"{len(test_lakes)} test lakes"))
    print("\nChecks:")
    for name, ok, detail in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}: {detail}")
    passed = sum(ok for _, ok, _ in checks)
    print(f"\n{passed} of {len(checks)} checks passed. Cases: {DOCS / 'hard-cases.json'}")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
