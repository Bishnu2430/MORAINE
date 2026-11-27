"""P1 step 5, part 3: report on the trained U-Net against the validation hard cases.

    .venv\\Scripts\\python pipeline\\scripts\\p1_unet_report.py

Loads pipeline/data/p1_unet/model.pt (trained by p1_unet.py, on Colab or here) and its history, scores
the validation hard cases of step 4 (Bhote Koshi and Khumbu) with the U-Net and the baseline rule, and
writes docs/p1/unet-validation.json (every case), docs/p1/unet-training.png (the training curve and the
per-condition medians) and docs/p1/unet-validation.jpg (the U-Net's lake maps on every case).

The North Sikkim test cases are not read; they are for step 6.
"""

from __future__ import annotations

import hashlib
import json
import statistics
import sys
from pathlib import Path

PIPELINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PIPELINE))
sys.path.insert(0, str(PIPELINE / "scripts"))

from moraine import plot, tiles, unet  # noqa: E402
import p1_unet  # noqa: E402

DOCS = PIPELINE.parent / "docs" / "p1"
CATEGORIES = ("ice", "shadow", "thin_cloud", "silty", "clear")


def main() -> int:
    model_path = p1_unet.DATA / "model.pt"
    model, info = unet.load(model_path)
    history = json.loads((p1_unet.DATA / "history.json").read_text())
    cases = p1_unet.validation_cases()
    rows, panels = [], []
    for case, tile, raw in cases:
        mapped = unet.lake_mask(unet.predict(model, raw))
        s = tiles.score(mapped, tile)
        b = case["baseline"]["ndwi"]
        rows.append({"case": case["case"], "category": case["category"], "unet": round(s["iou"], 3),
                     "baseline": round(b["iou"], 3), "unet_lake_iou": round(s["lake_iou"], 3),
                     "baseline_lake_iou": round(b["lake_iou"], 3),
                     "unet_area_error": None if s["area_error"] is None else round(s["area_error"], 3)})
        short = case["case"].replace("bhote_koshi", "Bhote Koshi").replace("khumbu", "Khumbu").replace("-", " ", 1)
        panels.append((tile, mapped, f"{short}\nU-Net {s['iou']:.2f}, baseline {b['iou']:.2f}"))
    medians = {c: (statistics.median(r["baseline"] for r in rows if r["category"] == c),
                   statistics.median(r["unet"] for r in rows if r["category"] == c)) for c in CATEGORIES}
    better = sum(r["unet"] > r["baseline"] + 0.02 for r in rows)
    worse = sum(r["unet"] < r["baseline"] - 0.02 for r in rows)
    report = {
        "model": {"sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(), "epoch": info["epoch"],
                  "base": info["base"], "depth": info["depth"], "trained_on": info["args"]["device"],
                  "epochs": info["args"]["epochs"], "training_tiles": json.loads(
                      (p1_unet.DATA / "train_keys.json").read_text()).__len__()},
        "mean": {"unet": round(statistics.mean(r["unet"] for r in rows), 4),
                 "baseline": round(statistics.mean(r["baseline"] for r in rows), 4)},
        "median_by_category": {c: {"baseline": round(b, 3), "unet": round(u, 3)} for c, (b, u) in medians.items()},
        "cases_better_same_worse": [better, len(rows) - better - worse, worse],
        "cases": rows,
    }
    (DOCS / "unet-validation.json").write_text(json.dumps(report, indent=1))
    plot.plot_unet(history, info["epoch"], medians, DOCS / "unet-training.png")
    plot.plot_tiles(panels, "U-Net lake maps (magenta) on the validation cases; case lake cyan, other inventory lakes "
                            "yellow", DOCS / "unet-validation.jpg")
    print(f"Model {report['model']['sha256'][:12]}, pass {info['epoch']} of {info['args']['epochs']}, trained on "
          f"{report['model']['trained_on']}, {report['model']['training_tiles']} training tiles")
    print(f"Validation, {len(rows)} cases: mean overlap U-Net {report['mean']['unet']:.3f} against baseline "
          f"{report['mean']['baseline']:.3f}; U-Net better on {better}, worse on {worse}")
    for c, (b, u) in medians.items():
        print(f"  {c:<11} median U-Net {u:.2f}, baseline {b:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
