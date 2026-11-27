"""P1 step 6: the gate. The U-Net against both baseline rules on the held-out North Sikkim cases.

    .venv\\Scripts\\python pipeline\\scripts\\p1_gate.py

The criteria were fixed, and committed, before this script first read a test case:

1. The model is step 5's: its sha256 matches docs/p1/unet-validation.json.
2. On the hard test cases (ice, shadow, thin cloud, silty), the U-Net's mean overlap beats the better
   of the two rule variants (NDWI, and NDWI with MNDWI).
3. The lead is not luck: in a bootstrap that resamples lakes rather than cases (some lakes appear in
   several cases, in different years), the 95% interval of the mean difference lies above zero.

Overlap is tiles.score's: every inventory lake within 500 m of the case lake, water mapped where there
is no lake counting against. Also reported, not gated: each category, the clear controls, cases won and
lost, and area error. Writes docs/p1/gate.json, docs/p1/gate.png and docs/p1/gate-cases.jpg.
"""

from __future__ import annotations

import hashlib
import json
import statistics
import sys
from pathlib import Path

PIPELINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PIPELINE))

import numpy as np  # noqa: E402

from moraine import plot, tiles, unet  # noqa: E402

DOCS = PIPELINE.parent / "docs" / "p1"
MODEL = PIPELINE / "data" / "p1_unet" / "model.pt"
CASE_TILES = PIPELINE / "data" / "p1_hard_cases"
HARD = ("ice", "shadow", "thin_cloud", "silty")
RULES = ("ndwi", "ndwi_mndwi")
RESAMPLES = 10_000
SEED = 2026


def lake_bootstrap(rows: list[dict], better: str) -> tuple[float, float]:
    """95% interval of the mean (U-Net minus rule) difference, resampling lakes with all their cases."""
    by_lake: dict = {}
    for r in rows:
        by_lake.setdefault(r["lake"], []).append(r["unet"]["iou"] - r[better]["iou"])
    groups = list(by_lake.values())
    rng = np.random.default_rng(SEED)
    means = []
    for _ in range(RESAMPLES):
        picked = [d for i in rng.integers(0, len(groups), len(groups)) for d in groups[i]]
        means.append(sum(picked) / len(picked))
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def main() -> int:
    digest = hashlib.sha256(MODEL.read_bytes()).hexdigest()
    expected = json.loads((DOCS / "unet-validation.json").read_text())["model"]["sha256"]
    model, info = unet.load(MODEL)
    cases = [c for c in json.loads((DOCS / "hard-cases.json").read_text()) if c["split"] == "test"]

    rows, panels = [], []
    for case in cases:
        tile = tiles.load(CASE_TILES / f"{case['case']}.npz")
        mapped = unet.lake_mask(unet.predict(model, unet.raw_from_tile(tile)))
        row = {"case": case["case"], "category": case["category"], "date": case["date"],
               "lake": case["lake_2022"] if case["lake_2022"] is not None else case["case"],
               "unet": tiles.score(mapped, tile)}
        for rule in RULES:
            row[rule] = tiles.score(tiles.baseline(tile, rule), tile)
        rows.append(row)
        panels.append((tile, mapped, f"{case['case'].split('-', 1)[1]}, {case['date']}\n"
                                     f"U-Net {row['unet']['iou']:.2f}, rule {row['ndwi']['iou']:.2f}"))

    hard = [r for r in rows if r["category"] in HARD]
    mean = {m: statistics.mean(r[m]["iou"] for r in hard) for m in ("unet",) + RULES}
    better = max(RULES, key=lambda m: mean[m])
    low, high = lake_bootstrap(hard, better)
    wins = sum(r["unet"]["iou"] > r[better]["iou"] + 0.02 for r in hard)
    losses = sum(r["unet"]["iou"] < r[better]["iou"] - 0.02 for r in hard)
    checks = [
        ("the model is step 5's", digest == expected, f"sha256 {digest[:12]}, step 5 recorded {expected[:12]}"),
        (f"hard cases: the U-Net's mean overlap beats the better rule ({better})", mean["unet"] > mean[better],
         f"{mean['unet']:.3f} against {mean[better]:.3f} over {len(hard)} cases"),
        ("the lead is not luck: 95% interval above zero, resampling lakes", low > 0,
         f"U-Net minus rule {mean['unet'] - mean[better]:+.3f}, interval {low:+.3f} to {high:+.3f}, "
         f"{len({r['lake'] for r in hard})} lakes"),
    ]

    def median(group, method, key="iou"):
        vals = [r[method][key] for r in group if r[method][key] is not None]
        return statistics.median(vals) if vals else None

    by_category = {}
    for category in HARD + ("clear",):
        group = [r for r in rows if r["category"] == category]
        by_category[category] = {
            "cases": len(group), "lakes": len({r["lake"] for r in group}),
            **{m: round(median(group, m), 3) for m in ("unet",) + RULES},
            "abs_area_error": {m: round(statistics.median(abs(r[m]["area_error"]) for r in group), 3)
                               for m in ("unet",) + RULES},
        }
    result = {
        "criteria_passed": all(ok for _, ok, _ in checks),
        "checks": [{"name": n, "passed": ok, "detail": d} for n, ok, d in checks],
        "model": {"sha256": digest, "epoch": info["epoch"]},
        "hard_cases": {"cases": len(hard), "mean": {m: round(v, 4) for m, v in mean.items()}, "better_rule": better,
                       "difference_interval_95": [round(low, 4), round(high, 4)],
                       "won_tied_lost": [wins, len(hard) - wins - losses, losses]},
        "by_category": by_category,
        "cases": [{k: v if not isinstance(v, dict) else {kk: (round(vv, 3) if isinstance(vv, float) else vv)
                                                       for kk, vv in v.items()} for k, v in r.items()} for r in rows],
    }
    (DOCS / "gate.json").write_text(json.dumps(result, indent=1))
    plot.plot_gate(rows, better, DOCS / "gate.png")
    plot.plot_tiles(panels, "U-Net lake maps (magenta) on the North Sikkim test cases; case lake cyan, other inventory "
                            "lakes yellow", DOCS / "gate-cases.jpg")

    print(f"North Sikkim test: {len(rows)} cases, {len(hard)} of them hard. Median overlap "
          f"(U-Net / NDWI rule / with MNDWI) and median area error of the case lake:")
    for category, s in by_category.items():
        e = s["abs_area_error"]
        print(f"  {category:<11} {s['cases']:>2} cases, {s['lakes']:>2} lakes: {s['unet']:.2f} / {s['ndwi']:.2f} / "
              f"{s['ndwi_mndwi']:.2f};  area error {e['unet']:.0%} / {e['ndwi']:.0%} / {e['ndwi_mndwi']:.0%}")
    print(f"  hard cases: U-Net better on {wins}, worse on {losses}, within 0.02 on {len(hard) - wins - losses}")
    print("\nThe gate:")
    for name, ok, detail in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}: {detail}")
    print(f"\n{'GATE PASSED' if result['criteria_passed'] else 'GATE FAILED'}. Details: {DOCS / 'gate.json'}")
    return 0 if result["criteria_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
