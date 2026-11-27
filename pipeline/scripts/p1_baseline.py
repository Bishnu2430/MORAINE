"""P1 step 3: the simple water-index lake mapper, scored against the inventory.

    .venv\\Scripts\\python pipeline\\scripts\\p1_baseline.py --project YOUR-CLOUD-PROJECT

For each study area (pipeline/moraine/study_areas.geojson) and inventory year (2018, 2020, 2022),
builds the Sentinel-2 autumn composite and maps lakes with two variants of the rule
(moraine/watch.py). Records the total lake area and scores every inventory lake listed at 0.02 km2
or more that year (the method's own cut-off):

- found: overlap (IoU) of at least 0.5, among lakes seen by 3+ scenes
- the mapped area against the inventory's
- the mapped water lying away from every inventory lake (reported, not scored: part of it is real
  lakes the inventory leaves out, as it lists only glacial lakes within 10 km of a glacier)

Each year's lakes come from that year's own file, picked by position: the files do not list the lakes
in the same order (see inventory.match).

The Earth Engine results for each area-year are cached in pipeline/out/p1_baseline/cache/, stamped
with a fingerprint of watch.py and the lake list, so a rerun skips finished work but never reuses
results from older code. Scores are worked out here from the cached numbers. Writes
pipeline/out/p1_baseline/summary.json. Takes one to two hours on Earth Engine. --all-years adds
every autumn 2017-2025 (totals only), for the growth curves in step 7.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import sys
import time
from pathlib import Path

PIPELINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PIPELINE))

from moraine import inventory, study_areas, watch  # noqa: E402

DATA = PIPELINE / "data" / "zhang2023"
OUT = PIPELINE / "out" / "p1_baseline"
ALL_YEARS = range(2017, 2026)
AREAS = ("sikkim", "bhote_koshi", "khumbu")
MIN_KM2 = watch.MIN_LAKE_PIXELS * watch.SCALE ** 2 / 1e6  # 0.02 km2
SEEN = 0.9  # a lake counts as seen when 3+ scenes saw at least this share of its buffered outline
FOUND_IOU = 0.5
CODE = hashlib.sha1((PIPELINE / "moraine" / "watch.py").read_bytes()).hexdigest()[:12]


def measure(region, lakes, year: int, result: dict | None = None) -> dict:
    """The Earth Engine part, cached: scene count, and per variant the total area, per-lake rows and the
    water away from inventory lakes. Given a cached result, fills in only the parts it lacks."""
    image = watch.composite(region, year)
    if result is None:
        result = {"year": year, "code": CODE, "lake_ids": lake_ids(lakes), "scenes": image.get("scenes").getInfo(),
                  "variants": {}}
    for variant in watch.VARIANTS:
        mapped = watch.lakes_only(watch.water(image, variant))
        entry = result["variants"].setdefault(variant, {})
        if "total" not in entry:
            entry["total"] = watch.total_area(mapped, region)
        if lakes is not None and "per_lake" not in entry:
            entry["per_lake"] = watch.score(mapped, lakes)
        if lakes is not None and "outside_km2" not in entry:
            entry["outside_km2"] = watch.outside(mapped, region, lakes)
    return result


def complete(result: dict, lakes) -> bool:
    return all("total" in e and (lakes is None or ("per_lake" in e and "outside_km2" in e))
               for e in (result["variants"].get(v, {}) for v in watch.VARIANTS))


def lake_ids(lakes) -> list[int] | None:
    return None if lakes is None else sorted(int(lake.attrs["index"]) for lake in lakes)


def cached(path: Path, lakes) -> dict | None:
    """The cached result, if it came from this watch.py and the same lakes."""
    if not path.exists():
        return None
    result = json.loads(path.read_text())
    return result if result.get("code") == CODE and result.get("lake_ids") == lake_ids(lakes) else None


def scores(entry: dict, lakes) -> dict:
    """Lakes found, overlap and area error from one variant's per-lake rows, plus the water elsewhere."""
    listed = {int(lake.attrs["index"]): lake.area_km2 for lake in lakes}
    rows = [r for r in entry["per_lake"] if listed[r["id"]] >= MIN_KM2]
    seen = [r for r in rows if r["seen_share"] >= SEEN]
    found = sum(r["iou"] >= FOUND_IOU for r in seen)
    truth, mapped = sum(r["truth_km2"] for r in seen), sum(r["mapped_km2"] for r in seen)
    return {"lakes": len(rows), "seen": len(seen), "found": found, "recall": found / len(seen) if seen else 0.0,
            "median_iou": statistics.median(r["iou"] for r in seen) if seen else None,
            "truth_km2": truth, "mapped_km2": mapped, "area_error": mapped / truth - 1 if truth else None,
            "outside_km2": entry["outside_km2"], "outside_share": entry["outside_km2"] / entry["total"]["km2"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", default=os.environ.get("EE_PROJECT"))
    parser.add_argument("--area", choices=AREAS, action="append")
    parser.add_argument("--all-years", action="store_true", help="every autumn 2017-2025, not just inventory years")
    args = parser.parse_args()

    import ee

    try:
        ee.Initialize(project=args.project)
    except Exception as exc:  # the client raises plain Exceptions for missing sign-in or project access
        sys.exit(f"Earth Engine would not start: {exc}\nSee pipeline/README.md for sign-in and project setup.")
    cache = OUT / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    outlines = json.loads((PIPELINE / "moraine" / "study_areas.geojson").read_text())
    by_year = {year: inventory.load(DATA, year) for year in inventory.YEARS}

    summary = {}
    for key in args.area or AREAS:
        feature = next(f for f in outlines["features"] if f["properties"]["id"] == key)
        polygons = study_areas.polygons_of(feature["geometry"])
        region = ee.Geometry(feature["geometry"])
        # Each year's lakes from that year's own file: positions differ between the files
        in_area = {year: [lk for lk in lakes if study_areas.contains(polygons, lk.lon, lk.lat)]
                   for year, lakes in by_year.items()}
        summary[key] = []
        for year in (ALL_YEARS if args.all_years else inventory.YEARS):
            lakes = in_area.get(year)
            path = cache / f"{key}_{year}.json"
            result = cached(path, lakes)
            if result is None or not complete(result, lakes):
                start = time.time()
                for attempt in range(3):
                    try:
                        result = measure(region, lakes, year, result)
                        break
                    except Exception as exc:  # Earth Engine timeouts and quota errors: wait and retry
                        print(f"  {key} {year}: attempt {attempt + 1} failed: {exc}", flush=True)
                        time.sleep(30)
                else:
                    continue
                path.write_text(json.dumps(result))
                print(f"{key} {year}: {result['scenes']} scenes, {time.time() - start:.0f} s", flush=True)
            row = {"year": year, "scenes": result["scenes"], "variants": {}}
            for name, entry in result["variants"].items():
                row["variants"][name] = {"total": entry["total"]} | (scores(entry, lakes) if lakes is not None else {})
            summary[key].append(row)
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1))

    print(f"\nInventory years (lakes listed at {MIN_KM2:.2f} km2 or more and seen by 3+ scenes; "
          f"found = overlap of at least {FOUND_IOU}):")
    for variant, label in watch.VARIANTS.items():
        print(f"  {variant} ({label})")
        scored = []
        for key, years in summary.items():
            for row in years:
                entry = row["variants"].get(variant, {})
                if "found" not in entry:
                    continue
                scored.append(entry)
                print(f"    {key:<12} {row['year']}: found {entry['found']}/{entry['seen']} (of {entry['lakes']}), "
                      f"median IoU {entry['median_iou']:.2f}, area {entry['mapped_km2']:.2f} vs "
                      f"{entry['truth_km2']:.2f} km2 ({100 * entry['area_error']:+.0f}%), water away from inventory "
                      f"lakes {entry['outside_km2']:.2f} km2 ({100 * entry['outside_share']:.0f}% of all mapped)")
        if scored:
            found, seen = sum(e["found"] for e in scored), sum(e["seen"] for e in scored)
            truth, mapped = sum(e["truth_km2"] for e in scored), sum(e["mapped_km2"] for e in scored)
            print(f"    all: found {found}/{seen} ({100 * found / seen:.1f}%), median IoU of area-years "
                  f"{statistics.median(e['median_iou'] for e in scored):.2f}, area {100 * (mapped / truth - 1):+.1f}%, "
                  f"water away from inventory lakes {sum(e['outside_km2'] for e in scored):.2f} km2")
    print(f"\nSummary: {OUT / 'summary.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
