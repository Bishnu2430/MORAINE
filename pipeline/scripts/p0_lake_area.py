"""P0 spike: South Lhonak lake area in every clear autumn since 1984, measured on Google Earth Engine.

    .venv\\Scripts\\python pipeline\\scripts\\p0_lake_area.py [--project YOUR-CLOUD-PROJECT]

Writes to pipeline/out/p0_lake_area/: scenes_raw.csv (what Earth Engine returned), scenes.csv,
yearly.csv, aoi.geojson and south_lhonak_area.png. Then prints three checks against published
areas and exits with 0 only if all three pass. --from-csv rebuilds everything from an earlier
scenes_raw.csv without calling Earth Engine.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import pandas as pd

PIPELINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PIPELINE))

from moraine import plot, references, summary  # noqa: E402


def fetch(project: str | None, lake: dict, out: Path) -> pd.DataFrame:
    import ee

    from moraine import lakes

    try:
        # With no project given, Earth Engine uses the one saved by `earthengine set_project`
        ee.Initialize(project=project)
    except Exception as exc:  # the client raises plain Exceptions for missing sign-in or project access
        sys.exit(
            f"Earth Engine would not start: {exc}\n"
            "Sign in with  .venv\\Scripts\\earthengine authenticate , save your project with  "
            ".venv\\Scripts\\earthengine set_project YOUR-PROJECT-ID  and check that the project is "
            "registered for Earth Engine (see pipeline/README.md)."
        )
    print(f"Finding {lake['name']} in JRC Global Surface Water ...")
    aoi = lakes.lake_aoi(lake["lon"], lake["lat"])
    (out / "aoi.geojson").write_text(json.dumps(aoi.getInfo()))
    print(f"  measuring area: {aoi.area(1).getInfo() / 1e6:.2f} km2")
    print("Measuring every autumn scene (runs on Earth Engine, a few minutes) ...")
    raw = pd.DataFrame(lakes.measure_scenes(aoi))
    raw.to_csv(out / "scenes_raw.csv", index=False)
    return raw


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", default=os.environ.get("EE_PROJECT"),
                        help="Google Cloud project registered for Earth Engine; defaults to EE_PROJECT, "
                             "then to the project saved with `earthengine set_project`")
    parser.add_argument("--out", type=Path, default=PIPELINE / "out" / "p0_lake_area")
    parser.add_argument("--from-csv", type=Path, help="rebuild outputs from an earlier scenes_raw.csv")
    args = parser.parse_args()

    lake = references.SOUTH_LHONAK
    args.out.mkdir(parents=True, exist_ok=True)
    if args.from_csv:
        raw = pd.read_csv(args.from_csv)
    else:
        raw = fetch(args.project, lake, args.out)

    scenes = summary.tidy(raw)
    scenes.to_csv(args.out / "scenes.csv", index=False)
    by_year = summary.yearly(scenes, lake["event_date"])
    by_year.to_csv(args.out / "yearly.csv", index=False)
    chart = args.out / "south_lhonak_area.png"
    plot.plot_area(scenes, by_year, lake, chart)

    n_clear = len(summary.clear(scenes))
    print(f"\n{len(scenes)} scenes, {n_clear} clear enough to use. Autumn medians (km2):")
    for _, r in by_year.iterrows():
        print(f"  {r['period']:<12} {r['area_km2']:6.3f}   ({r['area_narrow_km2']:.3f}-{r['area_wide_km2']:.3f}, "
              f"{r['scenes']} scenes, {r['sensors']})")

    results = summary.run_checks(scenes, lake["checks"])
    print("\nChecks against published areas:")
    for r in results:
        value = "none" if r.value_km2 is None else f"{r.value_km2:.3f} km2"
        print(f"  {'PASS' if r.passed else 'FAIL'}  {r.name}: {value} ({r.detail})")
        print(f"        expected {r.low:.2f}-{r.high:.2f}. {r.expect}")
    passed = sum(r.passed for r in results)
    print(f"\n{passed} of {len(results)} checks passed. Chart: {chart}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
