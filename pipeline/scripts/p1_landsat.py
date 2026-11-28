"""P1 step 7b: lake areas each autumn 2013-2016 from Landsat 8, for the lakes of 0.05 km2 or more.

    .venv\\Scripts\\python pipeline\\scripts\\p1_landsat.py --project YOUR-CLOUD-PROJECT

1. Flags (Earth Engine): cloud, shadow, ice and coverage for the 114 lakes in every Landsat 8 scene of
   1 Sep-15 Nov, 2013-2016, 2018, 2020 and 2022 (moraine/landsat.py; cached in
   pipeline/out/p1_landsat/stats/).
2. The mapper: both the step 3 NDWI rule and the U-Net map the inventory autumns (maps in
   pipeline/data/p1_landsat/select/), and the rule fixed in docs/p1/plan.md picks one.
3. History: 2013-2016 mapped by the chosen one (pipeline/data/p1_landsat/<mapper>/). Scenes and areas
   follow step 7a (moraine/growth.py). Stages 2 and 3 save every lake-autumn, so a rerun resumes.
4. Areas and the checks fixed in docs/p1/plan.md (step 7b, narrowed after the third run). Writes
   docs/p1/landsat.json and docs/p1/growth-history.png, where each lake's 1990 inventory area is the
   only point before 2013.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
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

import p1_growth as g7a  # noqa: E402
from moraine import growth, hard_cases, inventory, landsat, plot, tiles, unet  # noqa: E402

OUT = PIPELINE / "out" / "p1_landsat"
MAPS = PIPELINE / "data" / "p1_landsat"
DOCS = PIPELINE.parent / "docs" / "p1"
MAPPERS = ("rule", "unet")
CHUNK = 8  # scenes per flag request
WORKERS = 4
CODE = hashlib.sha1("".join(
    [inspect.getsource(f) for f in (landsat.scenes, landsat._renamed, landsat._covered, landsat._cloud,
                                     landsat.conditions, landsat.neighbourhood, landsat.measure)]
    + [repr((landsat.SENSORS, landsat.AS_S2, landsat.SEASON, landsat.SCENE_CLOUD, landsat.SCALE, landsat.FILL,
             landsat.CLOUD_BLUE, landsat.SNOW_NDSI, hard_cases.SHADOW_REACH_PX, hard_cases.NEAR_M))]
).encode()).hexdigest()[:12]


def flags(key: str, geometry: dict, lakes22: list, year: int, sensors: tuple[str, ...]) -> list[dict] | None:
    """Stage 1 for one area and autumn, cached in OUT/stats."""
    import ee

    ids = sorted(int(lk.attrs["index"]) for lk in lakes22)
    path = OUT / "stats" / f"{key}_{year}.json"
    if path.exists():
        saved = json.loads(path.read_text())
        if saved["code"] == CODE and saved["lake_ids"] == ids and saved["sensors"] == list(sensors):
            return saved["rows"]
    region = ee.Geometry(geometry)
    start = time.time()
    scene_ids = landsat.scenes(region, year, sensors).aggregate_array("scene").getInfo()
    rows = []
    for i in range(0, len(scene_ids), CHUNK):
        for attempt in range(3):
            try:
                rows += landsat.measure(lakes22, scene_ids[i:i + CHUNK], region, year, sensors)
                break
            except Exception as exc:  # Earth Engine timeouts and quota errors: wait and retry
                print(f"  {key} {year} scenes {i}-{i + CHUNK}: attempt {attempt + 1} failed: {str(exc)[:150]}",
                      flush=True)
                time.sleep(30)
        else:
            print(f"  {key} {year}: giving up, nothing cached", flush=True)
            return None
    path.write_text(json.dumps({"code": CODE, "lake_ids": ids, "sensors": list(sensors), "scenes": len(scene_ids),
                                "rows": rows}))
    print(f"{key} {year}: {len(scene_ids)} scenes, {len(rows)} lake-scenes, {time.time() - start:.0f} s", flush=True)
    return rows


def lake_probability(data: dict, mapper: str, model) -> np.ndarray:
    """One tile's lake probability (0-1) from the NDWI rule (0 or 1) or the U-Net."""
    if mapper == "rule":
        tile = {"B3": data["B3"], "B8": data["B8"], "B11": data["B11"], "slope": data["slope_x100"] / 100}
        return tiles.baseline(tile, "ndwi").astype(np.float32)
    return unet.predict(model, np.stack([data[b] for b in unet.RAW]))


def run_maps(jobs: list, mappers: tuple[str, ...], model, label: str) -> int:
    """Fetch and map each job's scenes (growth.take); save probabilities per mapper. Returns failures."""

    def fetch_job(job):
        lake, year, ranked, want, near, _ = job
        datas = {}

        def fetched_whole(r):
            image = g7a.with_slope_and_ids(landsat.tile_bands(r["scene"]), near)
            data = g7a.fetch(r["scene"], near, lake["box"], image=image)
            if g7a.whole(data):
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
    with ThreadPoolExecutor(WORKERS) as pool:
        for n, (job, got) in enumerate(zip(jobs, pool.map(fetch_job, jobs)), 1):
            lake, year, ranked, want, near, path = job
            if got is None:
                failed += 1
                continue
            kept, tried = got
            cut += len(tried) - len(kept)
            size = lake["box"][2]
            probs = np.zeros((len(mappers), len(kept), size, size), np.uint8)
            for k, mapper in enumerate(mappers):
                for j, (_, d) in enumerate(kept):
                    probs[k, j] = np.round(lake_probability(d, mapper, model) * 255).astype(np.uint8)
            np.savez_compressed(path, probs=probs, mappers=np.array(mappers),
                                ids=kept[0][1]["ids"].astype(np.uint16) if kept else np.zeros((size, size), np.uint16),
                                scenes=np.array([r["scene"] for r, _ in kept], dtype=str),
                                dates=np.array([r["date"] for r, _ in kept], dtype=str),
                                tiers=np.array([r["tier"] for r, _ in kept], dtype=np.int64), tried=np.array(tried))
            if n % 50 == 0 or n == len(jobs):
                print(f"  {label}: {n}/{len(jobs)} lake-autumns, {cut} scenes cut so far, {time.time() - start:.0f} s",
                      flush=True)
    return failed


def autumn(path: Path, i22: int, mapper_index: int = 0) -> dict | None:
    """A saved lake-autumn's area (median of up to three scenes' probability) and each scene's."""
    with np.load(path) as saved:
        if len(saved["scenes"]) == 0:  # every usable scene was cut by an edge or a stripe
            return None
        probs = saved["probs"][mapper_index].astype(np.float32) / 255
        ids, tiers, dates, names = saved["ids"], saved["tiers"], saved["dates"], saved["scenes"]
    scenes = [{"date": str(d), "sensor": landsat.sensor_of(str(s)), "tier": int(t),
               "km2": round(growth.lake_area(p, ids, i22 + 1), 5)} for d, s, t, p in zip(dates, names, tiers, probs)]
    best = probs[np.argsort(tiers, kind="stable")[:growth.PER_AUTUMN]]
    return {"km2": round(growth.lake_area(np.median(best, axis=0), ids, i22 + 1), 5), "scenes": scenes}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", default=os.environ.get("EE_PROJECT"))
    args = parser.parse_args()

    import ee

    try:
        ee.Initialize(project=args.project)
    except Exception as exc:  # the client raises plain Exceptions for missing sign-in or project access
        sys.exit(f"Earth Engine would not start: {exc}\nSee pipeline/README.md for sign-in and project setup.")
    (OUT / "stats").mkdir(parents=True, exist_ok=True)
    by_year = {year: inventory.load(g7a.DATA, year) for year in inventory.YEARS}
    areas = g7a.lakes_by_area(by_year)
    every = []
    for key, (_, lakes) in areas.items():
        for lake in lakes:
            lake["area"] = key
            lake["km2_1990"] = round(float(by_year[2022][lake["i22"]].attrs.get("Area_90") or 0), 5)
            every.append(lake)
    chosen = [lk for lk in every if max(list(lk["listed_km2"].values()) + [lk["km2_1990"]]) >= landsat.MIN_KM2]
    chosen_ids = {lk["i22"] for lk in chosen}
    g7a.add_boxes(every)
    south_lhonak = min(every, key=lambda lk: (lk["lon"] - g7a.SOUTH_LHONAK[0]) ** 2 + (lk["lat"] - g7a.SOUTH_LHONAK[1]) ** 2)
    model, _ = unet.load(PIPELINE / "data" / "p1_unet" / "model.pt")
    print(f"{len(chosen)} lakes of {landsat.MIN_KM2} km2 or more", flush=True)

    # 1. Flags
    rows = {}
    autumns = [(y, landsat.USED) for y in landsat.YEARS + landsat.INVENTORY_YEARS]
    for key, (geometry, lakes) in areas.items():
        lakes22 = [by_year[2022][lk["i22"]] for lk in lakes if lk["i22"] in chosen_ids]
        for year, sensors in autumns:
            got = flags(key, geometry, lakes22, year, sensors)
            if got is None:
                print(f"Flags incomplete for {key} {year}; rerun to finish")
                return 1
            for r in got:
                rows.setdefault((r["id"], year), []).append(r)
    print(f"1. Flags: {sum(len(v) for v in rows.values()):,} lake-scenes", flush=True)

    near = {lake["i22"]: [o for o in every if abs(o["lon"] - lake["lon"]) < 0.08 and abs(o["lat"] - lake["lat"]) < 0.08]
            for lake in chosen}

    def plan_maps(years, folder: Path):
        folder.mkdir(parents=True, exist_ok=True)
        jobs, plan = [], {}
        for lake in chosen:
            for year in years:
                ranked = growth.candidates(rows.get((lake["i22"], year), []), year)
                path = folder / f"{lake['i22']}_{year}.npz"
                plan[lake["i22"], year] = (path, ranked)
                if ranked and not g7a.done(path, ranked, growth.PER_AUTUMN):
                    jobs.append((lake, year, ranked, growth.PER_AUTUMN, near[lake["i22"]], path))
        return jobs, plan

    def saved(plan, i22, year):
        path, ranked = plan[i22, year]
        return path if ranked and g7a.done(path, ranked, growth.PER_AUTUMN) else None

    # 2. The mapper, chosen on the Landsat 8 inventory autumns
    jobs, select_plan = plan_maps(landsat.INVENTORY_YEARS, MAPS / "select")
    print(f"2. Mapper: {len(jobs)} Landsat 8 lake-autumns to map", flush=True)
    if run_maps(jobs, MAPPERS, model, "select"):
        print("Some lake-autumns failed to fetch; rerun to finish them")
        return 1
    landsat8 = {m: {} for m in MAPPERS}
    ratios = {m: [] for m in MAPPERS}
    for lake in chosen:
        for year in landsat.INVENTORY_YEARS:
            path = saved(select_plan, lake["i22"], year)
            got = {m: autumn(path, lake["i22"], k) for k, m in enumerate(MAPPERS)} if path else {}
            if not got or any(a is None for a in got.values()):
                continue
            for m in MAPPERS:
                landsat8[m][lake["i22"], year] = got[m]["km2"]
            listed = lake["listed_km2"].get(year, 0)
            if listed >= landsat.MIN_KM2:
                for m in MAPPERS:
                    ratios[m].append(got[m]["km2"] / listed)
    mapper, scores = landsat.choose_mapper(ratios)
    print("   median |log(mapped / listed)|: " + ", ".join(f"{m} {s:.3f}" for m, s in scores.items())
          + f" over {len(ratios[mapper])} lake-autumns. Chosen: {mapper}", flush=True)

    # 3. History
    jobs, history_plan = plan_maps(landsat.YEARS, MAPS / mapper)
    print(f"3. History: {len(jobs)} lake-autumns to map with the {mapper}", flush=True)
    if run_maps(jobs, (mapper,), model, "history"):
        print("Some lake-autumns failed to fetch; rerun to finish them")
        return 1

    # 4. Areas and checks
    sentinel = {lk["i22"]: lk for lk in json.loads((DOCS / "growth.json").read_text())["lakes"]}
    series = []
    for lake in chosen:
        entry = {"area": lake["area"], "i22": lake["i22"], "lon": round(lake["lon"], 5), "lat": round(lake["lat"], 5),
                 "listed_km2": lake["listed_km2"], "km2_1990": lake["km2_1990"], "autumns": {},
                 "landsat8": {y: landsat8[mapper][lake["i22"], y] for y in landsat.INVENTORY_YEARS
                              if (lake["i22"], y) in landsat8[mapper]}}
        for year in landsat.YEARS:
            path = saved(history_plan, lake["i22"], year)
            got = autumn(path, lake["i22"]) if path else None
            if got:
                entry["autumns"][year] = got
        series.append(entry)

    mapped = sum(bool(s["autumns"]) for s in series)
    accuracy = statistics.median(ratios[mapper])
    join = [s["landsat8"][y] / sentinel[s["i22"]]["autumns"][str(y)]["km2"] for s in series for y in s["landsat8"]
            if s["listed_km2"].get(y, 0) >= landsat.MIN_KM2
            and sentinel[s["i22"]]["autumns"].get(str(y), {}).get("km2", 0) > 0]
    sl = next(s for s in series if s["i22"] == south_lhonak["i22"])
    sl_late = next((y for y in (2016, 2015, 2014) if y in sl["autumns"]), None)
    sl_2017 = sentinel[sl["i22"]]["autumns"]["2017"]["km2"]
    sl_join = sl["autumns"][sl_late]["km2"] / sl_2017 - 1 if sl_late else None
    checks = [
        (f"at least 90% of lakes have a mapped autumn in {landsat.YEARS[0]}-{landsat.YEARS[-1]}",
         mapped >= 0.9 * len(series), f"{mapped} of {len(series)}"),
        (f"Landsat 8 inventory autumns, the {mapper}: median mapped/listed within 10% of 1", abs(accuracy - 1) <= 0.10,
         f"median {accuracy:.3f} over {len(ratios[mapper])} lake-autumns"),
        ("the same against step 7a's Sentinel-2 areas: median within 10% of 1",
         bool(join) and abs(statistics.median(join) - 1) <= 0.10,
         f"median {statistics.median(join):.3f} over {len(join)} lake-autumns" if join else "none"),
        ("South Lhonak's latest autumn of 2014-2016 within 10% of 7a's 2017",
         sl_join is not None and abs(sl_join) <= 0.10,
         f"{sl_late} {100 * sl_join:+.1f}% of {sl_2017} km2" if sl_late else "no autumn 2014-2016"),
    ]
    result = {"checks": [{"name": n, "passed": ok, "detail": d} for n, ok, d in checks],
              "mapper": {"chosen": mapper, "median_abs_log_ratio": {m: round(s, 4) for m, s in scores.items()},
                         "lake_autumns": len(ratios[mapper])},
              "sensors": list(landsat.USED), "south_lhonak_i22": sl["i22"], "lakes": series}
    (DOCS / "landsat.json").write_text(json.dumps(result, indent=1))
    plot.plot_history(series, sentinel, sl["i22"], g7a.OUTBURST, DOCS / "growth-history.png")
    print("\n4. Areas. Checks:")
    for name, ok, detail in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}: {detail}")
    passed = sum(ok for _, ok, _ in checks)
    print(f"\n{passed} of {len(checks)} checks passed. Details: {DOCS / 'landsat.json'}")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
