"""P1 step 1: fetch the Zhang et al. (2023) glacial lake inventory and check it against P0.

    .venv\\Scripts\\python pipeline\\scripts\\p1_inventory.py

Downloads the inventory zip from Zenodo into pipeline/data/zhang2023/ if it is not there yet, checks
its MD5 against the published one, unpacks it, then checks the outlines against what P0 measured:
South Lhonak's area, Thame's breached lake, and two lakes that should be absent because they had
drained (Gongbatongsha, Chorabari). Writes pipeline/out/p1_inventory/checks.json. Exits 0 only if
every check passes.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.request
import zipfile
from pathlib import Path

PIPELINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PIPELINE))

from moraine import inventory  # noqa: E402

DATA = PIPELINE / "data" / "zhang2023"
OUT = PIPELINE / "out" / "p1_inventory"

# South Lhonak, autumn Sentinel-2 composites at NDWI > 0.25 (P0 lake-area spike, docs/p0/south-lhonak-periods.csv)
SOUTH_LHONAK = {"lon": 88.191, "lat": 27.913, "p0_km2": {2018: 1.485, 2020: 1.551, 2022: 1.644}}
THAME_LOWER = {"lon": 86.5730, "lat": 27.8278}  # breached in Aug 2024; 0.044 km2 in autumn 2023 (P0 event check)
DRAINED = {"Gongbatongsha (drained 2016, 0.017 km2)": (86.0700, 28.0781),
           "Chorabari (drained 2013)": (79.0608, 30.7475)}


def fetch() -> None:
    archive = DATA / inventory.ZIP_NAME
    if not archive.exists():
        DATA.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {inventory.ZIP_NAME} from Zenodo (17.3 MB) ...", flush=True)
        urllib.request.urlretrieve(inventory.URL, archive)
    digest = hashlib.md5(archive.read_bytes()).hexdigest()
    if digest != inventory.MD5:
        sys.exit(f"{archive} has MD5 {digest}, not the published {inventory.MD5}; delete it and rerun.")
    if not inventory.shapefile_path(DATA, inventory.YEARS[-1]).exists():
        root = os.path.realpath(DATA / "extracted")
        with zipfile.ZipFile(archive) as z:
            for name in z.namelist():  # refuse paths that would land outside the folder
                target = os.path.realpath(os.path.join(root, name))
                if not (target == root or target.startswith(root + os.sep)):
                    sys.exit(f"refusing to unpack {name!r}")
            z.extractall(root)


def main() -> int:
    fetch()
    OUT.mkdir(parents=True, exist_ok=True)
    years = {year: inventory.load(DATA, year) for year in inventory.YEARS}
    results: dict = {"lakes_per_year": {y: len(lakes) for y, lakes in years.items()}}
    checks = []
    print("Lakes in the inventory: " + ", ".join(f"{y}: {len(l):,}" for y, l in years.items()))

    rows = []
    for year, lakes in years.items():
        lake = inventory.nearest(lakes, SOUTH_LHONAK["lon"], SOUTH_LHONAK["lat"], 500)
        p0 = SOUTH_LHONAK["p0_km2"][year]
        if lake is None:
            rows.append({"year": year, "found": False})
            checks.append((f"South Lhonak {year} matches P0 within 5%", False, "not in the inventory"))
            continue
        drawn = lake.area_km2
        gap = drawn / p0 - 1
        rows.append({"year": year, "found": True, "listed_km2": float(lake.attrs["Area"]), "outline_km2": round(drawn, 4),
                     "p0_km2": p0, "gap": round(gap, 4)})
        checks.append((f"South Lhonak {year} matches P0 within 5%", abs(gap) <= 0.05,
                       f"inventory {drawn:.3f} km2 (listed {float(lake.attrs['Area']):.3f}), P0 {p0:.3f} km2, "
                       f"{100 * gap:+.1f}%"))
    results["south_lhonak"] = rows

    thame = []
    for year, lakes in years.items():
        lake = inventory.nearest(lakes, THAME_LOWER["lon"], THAME_LOWER["lat"], 150)
        thame.append({"year": year, "km2": None if lake is None else round(lake.area_km2, 4)})
    present = all(t["km2"] is not None and 0.02 <= t["km2"] <= 0.08 for t in thame)
    checks.append(("Thame's breached lake listed in every year at about 0.04 km2", present,
                   ", ".join(f"{t['year']}: {t['km2'] if t['km2'] is not None else 'absent'}" for t in thame)))
    results["thame_lower"] = thame

    for name, (lon, lat) in DRAINED.items():
        hits = [year for year, lakes in years.items() if inventory.nearest(lakes, lon, lat, 200) is not None]
        checks.append((f"{name} absent", not hits, "absent in all years" if not hits else f"listed in {hits}"))
        results[name] = hits

    import shapefile  # pyshp; the hazard layer adds the paper's own assessment of South Lhonak

    hazard = shapefile.Reader(str(DATA / "extracted" / "Third Pole" / "Third_Pole_Glacial Lake_Hazard.shp"),
                              encoding="utf-8")
    fields = [f[0] for f in hazard.fields[1:]]
    best = None
    for record in hazard.iterRecords():
        attrs = dict(zip(fields, record))
        d = (float(attrs["Lon"]) - SOUTH_LHONAK["lon"]) ** 2 + (float(attrs["Lat"]) - SOUTH_LHONAK["lat"]) ** 2  # 2-decimal centres
        if best is None or d < best[0]:
            best = (d, attrs)
    keep = ("Area", "H_Level", "Released_V", "P_Discharg", "Warning_T", "Distance")
    results["south_lhonak_hazard"] = {k: best[1].get(k) for k in keep if k in best[1]}
    (OUT / "checks.json").write_text(json.dumps(results, indent=1, default=str))

    print("\nChecks against P0:")
    for name, ok, detail in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}: {detail}")
    h = results["south_lhonak_hazard"]
    print(f"  INFO  The paper's hazard entry for South Lhonak: {h}")
    passed = sum(ok for _, ok, _ in checks)
    print(f"\n{passed} of {len(checks)} checks passed. Details: {OUT / 'checks.json'}")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
