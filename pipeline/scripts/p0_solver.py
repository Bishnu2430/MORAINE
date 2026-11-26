"""P0 spike: the flood solver against exact solutions.

    .venv\\Scripts\\python pipeline\\scripts\\p0_solver.py

Runs the Kurganov-Petrova solver (pipeline/moraine/swe.py) on test cases whose answers are known
exactly, on this laptop's CPU, in a few minutes. Writes to pipeline/out/p0_solver/: checks.csv,
profile.csv (depth along the channel, solver and exact), refinement.csv and dam-break.png.

"gate" checks decide the exit code (0 only if all pass). "info" lines are measured and reported for
the P2 solver work but do not pass or fail.
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch

PIPELINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PIPELINE))

from moraine import benchmarks as b  # noqa: E402
from moraine import plot  # noqa: E402

SIZES = (10.0, 5.0, 2.5, 1.25)  # cell sizes (m) for the refinement study; 5 m is the headline run
SLOPE = 0.3  # 30% grade, about 17 degrees
COVERED, ISLANDS = 12.0, 4.0  # still-lake surface levels (m) in the test basin, whose ground runs 0.5-11 m
VALLEY_CELL = 30.0  # m, the real runs' grid
VALLEY_LENGTH = 60_000.0  # m, South Lhonak to Chungthang along the valley, roughly


@dataclass
class Check:
    name: str
    role: str  # "gate" or "info"
    passed: bool | None
    value: str
    limit: str
    detail: str


def gate(name, ok, value, limit, detail=""):
    return Check(name, "gate", bool(ok), value, limit, detail)


def info(name, value, detail=""):
    return Check(name, "info", None, value, "", detail)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=PIPELINE / "out" / "p0_solver", help="output folder")
    parser.add_argument("--device", default="cpu", help="torch device: cpu here, cuda on a Colab GPU")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    dev = args.device
    t = b.T_END
    exact_front = b.ritter_front(t)

    print(f"Dam break along x at {', '.join(f'{s:g}' for s in SIZES)} m cells ...", flush=True)
    runs = {s: b.ritter_1d(s, device=dev) for s in SIZES}
    head = runs[5.0]
    errors = [runs[s]["error"] for s in SIZES]
    lags = [exact_front - runs[s]["front"] for s in SIZES]
    print("Same dam break along y, across the grid at 45 degrees, and down a 30% slope ...", flush=True)
    along_y = b.ritter_1d(5.0, axis="y", device=dev)
    diagonal = b.ritter_diagonal(5.0, device=dev)
    slope = b.ritter_1d(5.0, slope=SLOPE, upstream=300.0, downstream=450.0, t_end=10.0, device=dev)
    print("Still lakes, fully covering the bed and with islands, with and without the shoreline change ...",
          flush=True)
    lake = b.lake_at_rest(COVERED, device=dev)
    islands = b.lake_at_rest(ISLANDS, device=dev)
    islands07 = b.lake_at_rest(ISLANDS, shoreline="kp07", device=dev)
    print("Water sloshing round a bowl for one full orbit, with and without the shoreline change ...", flush=True)
    bowl = b.thacker_bowl(device=dev)
    bowl07 = b.thacker_bowl(shoreline="kp07", device=dev)
    print("float32 at South Lhonak's elevation ...", flush=True)
    head32 = b.ritter_1d(5.0, dtype=torch.float32, offset=b.LAKE_ELEVATION, device=dev)
    lake32 = b.lake_at_rest(COVERED, dtype=torch.float32, offset=b.LAKE_ELEVATION, device=dev)
    islands32 = b.lake_at_rest(ISLANDS, dtype=torch.float32, offset=b.LAKE_ELEVATION, device=dev)
    diagonal32 = b.ritter_diagonal(5.0, dtype=torch.float32, offset=b.LAKE_ELEVATION, device=dev)

    float64_runs = [*runs.values(), along_y, diagonal, slope, lake, islands, bowl]
    worst_volume = max(r["volume_change"] for r in float64_runs)
    worst_clamp = max(r["clamped_share"] for r in float64_runs)
    xy_gap = float(np.abs(head["full"] - along_y["full"].T).max())
    err_order = b.order_of_accuracy(SIZES, errors)
    lag_order = b.order_of_accuracy(SIZES, lags)
    lag_cells = [lag / s for lag, s in zip(lags, SIZES)]
    slope_lag = b.ritter_front(10.0) - slope["front"]

    def rate(r):
        return r["cells"] * r["steps"] / r["seconds"]

    checks = [
        gate("Dam break along x: depth error at 5 m cells", head["error"] <= 0.02, f"{100 * head['error']:.2f}%",
             "at most 2%", "total difference from Ritter's exact solution, as a share of the water in the moving wave"),
        gate("Depth error shrinks with finer cells", err_order >= 0.6, f"order {err_order:.2f}", "at least 0.6",
             ", ".join(f"{s:g} m: {100 * e:.2f}%" for s, e in zip(SIZES, errors))
             + " (order 1: the error halves when the cells halve)"),
        gate("Flood front (10 cm deep) converges", lag_order >= 0.6, f"order {lag_order:.2f}", "at least 0.6",
             "behind the exact front by " + ", ".join(f"{lag:.1f} m ({c:.1f} cells)" for lag, c in zip(lags, lag_cells))
             + f"; a 4-cell lag at {VALLEY_CELL:g} m is {100 * 4 * VALLEY_CELL / VALLEY_LENGTH:.1f}% of the valley"),
        gate("Dam break along y gives the same answer as along x", xy_gap <= 1e-12, f"{xy_gap:.1e} m",
             "at most 1e-12 m", "largest depth difference anywhere; catches mixed-up x and y code"),
        gate("Dam break across the grid at 45 degrees: depth error", diagonal["error"] <= 0.03,
             f"{100 * diagonal['error']:.2f}%", "at most 3%",
             f"both directions and their cross terms carry flow; front {exact_front - diagonal['front']:.1f} m behind"),
        gate("Dam break down a 30% slope: depth error", slope["error"] <= 0.03, f"{100 * slope['error']:.2f}%",
             "at most 3%", f"10 s after release; exact by moving with the water; front {slope_lag:.1f} m behind"),
        gate("Water volume is conserved", worst_volume <= 1e-10, f"{worst_volume:.1e}", "at most 1e-10",
             "largest relative change over all float64 runs"),
        gate("Depths never went negative", worst_clamp <= 1e-10, f"{worst_clamp:.1e}", "at most 1e-10",
             "water the safety clamp had to add, as a share of the volume"),
        gate("A lake at rest over a fully covered bed stays still", lake["max_speed"] <= 1e-10,
             f"{lake['max_speed']:.1e} m/s", "at most 1e-10 m/s",
             f"fastest water after 120 s over hills and a 13-degree cone; surface moved {lake['max_surface_change']:.1e} m"),
        gate("A lake at rest with islands and shorelines stays still", islands["max_speed"] <= 1e-8,
             f"{islands['max_speed']:.1e} m/s", "at most 1e-8 m/s",
             f"fastest water after 120 s, {100 * islands['dry_share']:.1f}% of the basin dry; the 2007 tilted surface "
             f"gives {islands07['max_speed_deep']:.2f} m/s in water deeper than 10 cm, its surface moving up to "
             f"{islands07['max_surface_change_deep']:.2f} m"),
        gate("Water sloshing round a bowl, one orbit: depth error", bowl["error"] <= 0.10,
             f"{100 * bowl['error']:.2f}%", "at most 10%",
             f"Thacker (1981): the shoreline climbs and falls the bowl's sides; the 2007 surface gives "
             f"{100 * bowl07['error']:.2f}%"),
        gate("Water sloshing round a bowl, one orbit: wet area", bowl["iou"] >= 0.9, f"overlap {bowl['iou']:.3f}",
             "at least 0.9", f"wet cells (over 1 cm) shared with the exact lens, as a share of either; the 2007 "
             f"surface gives {bowl07['iou']:.3f}"),
        info("Front measured at 1 cm instead of 10 cm", f"{b.ritter_front(t, 0.01) - head['front_1cm']:.1f} m behind",
             "the frictionless wave's last 20 m is under 1 cm deep and smears over a few cells; friction in P2 "
             "changes that tip anyway"),
        info("float32 at 5,200 m elevation: depth error at 5 m cells", f"{100 * head32['error']:.2f}%",
             f"float64 gives {100 * head['error']:.2f}%; volume change {head32['volume_change']:.1e}; across the "
             f"grid at 45 degrees {100 * diagonal32['error']:.2f}% (float64 {100 * diagonal['error']:.2f}%)"),
        info("float32 at 5,200 m elevation: lakes at rest", f"{lake32['max_speed']:.1e} m/s covered, "
             f"{islands32['max_speed']:.1e} m/s with islands",
             f"fastest water after 120 s, against {lake['max_speed']:.1e} and {islands['max_speed']:.1e} m/s in float64"),
        info("Speed on this laptop's CPU", f"{rate(diagonal) / 1e6:.2f} M cell-steps/s float64, "
             f"{rate(diagonal32) / 1e6:.2f} M float32",
             f"{diagonal['cells']:,} cells, {diagonal['steps']} steps; the real runs go on a Colab GPU"),
    ]

    with open(args.out / "checks.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["check", "role", "passed", "value", "limit", "detail"])
        for c in checks:
            writer.writerow([c.name, c.role, "" if c.passed is None else c.passed, c.value, c.limit, c.detail])
    with open(args.out / "profile.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["x_m", "depth_m", "exact_m"])
        writer.writerows(zip(np.round(head["x"], 3), np.round(head["h"], 6), np.round(head["exact"], 6)))
    with open(args.out / "refinement.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["cell_m", "depth_error", "front_lag_m", "steps", "seconds"])
        for s, e, lag in zip(SIZES, errors, lags):
            writer.writerow([s, f"{e:.6f}", f"{lag:.2f}", runs[s]["steps"], f"{runs[s]['seconds']:.2f}"])
    chart = args.out / "dam-break.png"
    plot.plot_dam_break(head, list(zip(SIZES, errors)), t, b.H0, chart)

    print("\nChecks against exact solutions:")
    for c in checks:
        mark = "INFO" if c.role == "info" else ("PASS" if c.passed else "FAIL")
        limit = f"  (limit: {c.limit})" if c.limit else ""
        print(f"  {mark}  {c.name}: {c.value}{limit}")
        if c.detail:
            print(f"        {c.detail}")
    gates = [c for c in checks if c.role == "gate"]
    passed = sum(c.passed for c in gates)
    print(f"\n{passed} of {len(gates)} gate checks passed. Chart: {chart}")
    return 0 if passed == len(gates) else 1


if __name__ == "__main__":
    sys.exit(main())
