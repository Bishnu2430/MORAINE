"""P1 step 5, part 1: training tiles for the U-Net.

    .venv\\Scripts\\python pipeline\\scripts\\p1_unet_data.py --project YOUR-CLOUD-PROJECT

Chooses TILES inventory lakes outside all four study areas (and a 5 km margin), each in one random
inventory year and one random Sep-Dec Sentinel-2 scene (moraine/training.py), and saves each tile
as pipeline/data/p1_unet/tiles/<key>.npz (not in git). Rerunning resumes where it stopped. Writes
pipeline/data/p1_unet/index.json: every planned tile with its scene and whether it was kept.
About an hour with four requests at a time.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PIPELINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PIPELINE))

import numpy as np  # noqa: E402

from moraine import inventory, study_areas, terrain, training  # noqa: E402

DATA = PIPELINE / "data" / "zhang2023"
OUT = PIPELINE / "data" / "p1_unet"
TILES = 3500
SEED = 2026
PICK_BATCH = 150
WORKERS = 4


def excluded_boxes() -> list[tuple[float, float, float, float]]:
    outlines = json.loads((PIPELINE / "moraine" / "study_areas.geojson").read_text())
    return [study_areas.bounds(study_areas.polygons_of(f["geometry"])) for f in outlines["features"]]


def utm_by_zone(epsg: int, lonlat: list) -> list:
    out = []
    for i in range(0, len(lonlat), 500):
        out += terrain.to_utm(lonlat[i:i + 500], f"EPSG:{epsg}").tolist()
    return out


def save_tile(plan: dict, lakes_by_cell: dict) -> dict:
    """Fetch one tile and save it, unless cloud hides its lakes. Returns what happened."""
    path = OUT / "tiles" / f"{plan['key']}.npz"
    if path.exists():
        return {"kept": True}
    lakes = training.nearby(lakes_by_cell, plan["lon"], plan["lat"], 0.06)
    for attempt in range(3):
        try:
            data = training.fetch(plan, lakes)
            break
        except Exception as exc:  # Earth Engine timeouts and quota errors: wait and retry
            error = str(exc)
            time.sleep(15 * (attempt + 1))
    else:
        return {"kept": False, "why": f"fetch failed: {error[:120]}"}
    label = data["label"] > 0
    if not (data["B2"] > 0).all():
        return {"kept": False, "why": "tile runs off the scene"}
    if label.sum() == 0:
        return {"kept": False, "why": "no lake in the tile"}
    cloud = float(data["cloud"][label].mean())
    if cloud > training.HIDDEN:
        return {"kept": False, "why": "cloud hides the lakes", "cloud_on_lakes": round(cloud, 1)}
    np.savez_compressed(path, **{b: data[b].astype(np.uint16) for b in training.BANDS},
                        slope_x100=data["slope_x100"].astype(np.uint16), cloud=data["cloud"].astype(np.uint8),
                        label=label.astype(np.uint8))
    return {"kept": True, "cloud_on_lakes": round(cloud, 1), "lake_share": round(float(label.mean()), 4)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", default=os.environ.get("EE_PROJECT"))
    parser.add_argument("--tiles", type=int, default=TILES)
    args = parser.parse_args()

    import ee

    try:
        ee.Initialize(project=args.project)
    except Exception as exc:  # the client raises plain Exceptions for missing sign-in or project access
        sys.exit(f"Earth Engine would not start: {exc}\nSee pipeline/README.md for sign-in and project setup.")
    (OUT / "tiles").mkdir(parents=True, exist_ok=True)
    index_path = OUT / "index.json"
    by_year = {year: inventory.load(DATA, year) for year in inventory.YEARS}

    if index_path.exists():
        plans = json.loads(index_path.read_text())
    else:
        pairs = {y: inventory.match(by_year[y], by_year[2022], y) for y in inventory.YEARS[:-1]}
        plans = training.plan_tiles(by_year, pairs, excluded_boxes(), args.tiles, SEED)
        training.place(plans, utm_by_zone)
        print(f"Planned {len(plans)} tiles in UTM zones {sorted({p['epsg'] - 32600 for p in plans})}", flush=True)
    todo = [p for p in plans if "scene" not in p]
    for i in range(0, len(todo), PICK_BATCH):
        batch = todo[i:i + PICK_BATCH]
        for p, scene in zip(batch, training.pick_scenes(batch)):
            p["scene"] = scene
        index_path.write_text(json.dumps(plans))
        print(f"  scenes picked for {min(i + PICK_BATCH, len(todo))}/{len(todo)}", flush=True)

    cells = {year: collections.defaultdict(list) for year in by_year}
    for year, lakes in by_year.items():
        for lake in lakes:
            cells[year][(int(np.floor(lake.lon * 10)), int(np.floor(lake.lat * 10)))].append(lake)
    work = [p for p in plans if p.get("scene") and "kept" not in p]
    start, done = time.time(), 0
    with ThreadPoolExecutor(WORKERS) as pool:
        for p, result in zip(work, pool.map(lambda p: save_tile(p, cells[p["year"]]), work)):
            p.update(result)
            done += 1
            if done % 100 == 0 or done == len(work):
                index_path.write_text(json.dumps(plans))
                print(f"  tiles {done}/{len(work)}, {time.time() - start:.0f} s", flush=True)
    for p in plans:
        if not p.get("scene"):
            p.update({"kept": False, "why": "no covering scene"})
    index_path.write_text(json.dumps(plans))

    kept = [p for p in plans if p.get("kept")]
    why = collections.Counter(p.get("why") for p in plans if not p.get("kept"))
    months = collections.Counter(p["scene"][4:6] for p in kept)
    print(f"\nKept {len(kept)} of {len(plans)} tiles. Dropped: {dict(why)}")
    print("Months of the kept scenes:", dict(sorted(months.items())))
    print(f"Years: {dict(sorted(collections.Counter(p['year'] for p in kept).items()))}; "
          f"UTM zones: {dict(sorted(collections.Counter(p['epsg'] - 32600 for p in kept).items()))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
