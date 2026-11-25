"""P0 spike: a study lake's area each autumn since 1984, measured on Google Earth Engine.

    .venv\\Scripts\\python pipeline\\scripts\\p0_lake_area.py [--project YOUR-CLOUD-PROJECT]

The default lake is South Lhonak. Writes to pipeline/out/p0_lake_area/<lake>/: periods_raw.csv
(what Earth Engine returned), periods.csv, aoi.geojson and area.png. Then prints the lake's checks
against published figures. "gate" checks decide the exit code (0 only if all pass); "compare"
checks are printed for comparison. --from-csv rebuilds everything from an earlier periods_raw.csv
without calling Earth Engine.
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
    print(f"Outlining {lake['name']} ...")
    aoi = lakes.lake_aoi(lake["lon"], lake["lat"], margin_m=lake["margin_m"], recent_years=lake.get("recent_years"))
    (out / "aoi.geojson").write_text(json.dumps(aoi.getInfo()))
    print(f"  measuring area: {aoi.area(1).getInfo() / 1e6:.2f} km2")
    print("Building autumn composites (runs on Earth Engine, a few minutes) ...")
    raw = pd.DataFrame(lakes.measure_periods(aoi, summary.autumn_periods(lake["event_date"])))
    raw.to_csv(out / "periods_raw.csv", index=False)
    return raw


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", default=os.environ.get("EE_PROJECT"),
                        help="Google Cloud project registered for Earth Engine; defaults to EE_PROJECT, "
                             "then to the project saved with `earthengine set_project`")
    parser.add_argument("--lake", choices=sorted(references.LAKES), default="south-lhonak")
    parser.add_argument("--out", type=Path, help="output folder (default: pipeline/out/p0_lake_area/<lake>)")
    parser.add_argument("--from-csv", type=Path, help="rebuild outputs from an earlier periods_raw.csv")
    args = parser.parse_args()

    lake = references.LAKES[args.lake]
    args.out = args.out or PIPELINE / "out" / "p0_lake_area" / args.lake
    args.out.mkdir(parents=True, exist_ok=True)
    raw = pd.read_csv(args.from_csv) if args.from_csv else fetch(args.project, lake, args.out)

    periods = summary.tidy(raw)
    periods.to_csv(args.out / "periods.csv", index=False)
    chart = args.out / "area.png"
    plot.plot_area(periods, lake, chart)

    table = periods.pivot_table(index="period", columns="family", values=summary.MAIN, sort=False)
    ok = periods.pivot_table(index="period", columns="family", values="coverage", sort=False) >= summary.MIN_COVERAGE
    picked = summary.best(periods, lake["event_date"]).set_index("period")
    print(f"\n{lake['name']}: autumn area in km2 (NDWI > 0.25; '-' = not enough clear coverage)")
    print(f"  {'period':<12} {'Landsat':>8} {'Sentinel-2':>11} {'best':>7}")
    for period in picked.index.union(table.index, sort=False):
        cells = []
        for family in ("Landsat", "Sentinel-2"):
            usable = family in table.columns and period in table.index and bool(ok.loc[period, family])
            cells.append(f"{table.loc[period, family]:.3f}" if usable else "-")
        chosen = "-"
        if period in picked.index:
            chosen = f"{picked.loc[period, summary.MAIN]:.3f}"
            if picked.loc[period, "outlier"]:
                chosen += "  dropped: outlier"
        print(f"  {period:<12} {cells[0]:>8} {cells[1]:>11} {chosen:>7}")

    results = summary.run_checks(periods, lake["checks"], lake["event_date"])
    print("\nChecks against published figures:")
    for r in results:
        value = "none" if r.value is None else f"{r.value:.3f}"
        if r.role == "gate":
            mark = "PASS" if r.in_range else "FAIL"
        else:
            mark = "INFO"
        print(f"  {mark}  {r.name}: {value}  ({r.detail})")
        print(f"        expected {r.low:.2f}-{r.high:.2f}. {r.expect}")
    gates = [r for r in results if r.role == "gate"]
    passed = sum(r.in_range for r in gates)
    print(f"\n{passed} of {len(gates)} gate checks passed. Chart: {chart}")
    return 0 if passed == len(gates) else 1


if __name__ == "__main__":
    sys.exit(main())
