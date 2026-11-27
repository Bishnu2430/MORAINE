"""P1 step 5, part 2: train the U-Net and pick its checkpoint on the validation hard cases.

    .venv\\Scripts\\python pipeline\\scripts\\p1_unet.py --epochs 25
    python pipeline/scripts/p1_unet.py --epochs 25 --device cuda --workers 2      (Colab)

Packs the training tiles of pipeline/data/p1_unet/tiles/ into two arrays (train_raw.npy,
train_labels.npy) the first time, then trains (moraine/unet.py). After every epoch it scores the
validation hard cases of step 4 (Bhote Koshi and Khumbu, docs/p1/hard-cases.json): overlap with each
case's lake, as in step 4. The checkpoint with the best mean overlap is saved as
pipeline/data/p1_unet/model.pt, the history as pipeline/data/p1_unet/history.json.

The North Sikkim test cases are never read here; step 6 uses them once, for the gate.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

PIPELINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PIPELINE))

import numpy as np  # noqa: E402
import torch  # noqa: E402

from moraine import tiles, unet  # noqa: E402

DATA = PIPELINE / "data" / "p1_unet"
CASES = PIPELINE.parent / "docs" / "p1" / "hard-cases.json"
CASE_TILES = PIPELINE / "data" / "p1_hard_cases"


def pack(data: Path) -> tuple[np.ndarray, np.ndarray]:
    """The kept training tiles as memory-mapped arrays, rebuilt when the set of tiles changes."""
    keys = sorted(p["key"] for p in json.loads((data / "index.json").read_text()) if p.get("kept"))
    raw_path, label_path, keys_path = data / "train_raw.npy", data / "train_labels.npy", data / "train_keys.json"
    if not (keys_path.exists() and json.loads(keys_path.read_text()) == keys):
        size = None
        for n, key in enumerate(keys):
            with np.load(data / "tiles" / f"{key}.npz") as t:
                if size is None:
                    size = t["label"].shape[-1]
                    raw = np.lib.format.open_memmap(raw_path, "w+", np.uint16, (len(keys), len(unet.RAW), size, size))
                    labels = np.lib.format.open_memmap(label_path, "w+", np.uint8, (len(keys), size, size))
                raw[n] = np.stack([t[b] for b in unet.RAW])
                labels[n] = t["label"]
        raw.flush()
        labels.flush()
        del raw, labels
        keys_path.write_text(json.dumps(keys))
        print(f"Packed {len(keys)} training tiles", flush=True)
    return np.load(raw_path, mmap_mode="r"), np.load(label_path, mmap_mode="r")


def validation_cases() -> list[tuple[dict, dict, np.ndarray]]:
    """(case, tile, raw) for every validation hard case. Test cases are refused."""
    cases = [c for c in json.loads(CASES.read_text()) if c["split"] == "validation"]
    assert cases and all(c["split"] == "validation" and not c["area"] == "sikkim" for c in cases)
    out = []
    for case in cases:
        tile = tiles.load(CASE_TILES / f"{case['case']}.npz")
        out.append((case, tile, unet.raw_from_tile(tile)))
    return out


def reseed(worker_id: int) -> None:
    """Give each data-loading worker its own augmentation stream (torch varies its seed per worker
    and per epoch; numpy's generator would otherwise be copied identically into every worker)."""
    info = torch.utils.data.get_worker_info()
    info.dataset.rng = np.random.default_rng(torch.initial_seed() % 2 ** 32)


def evaluate(model, cases, device: str) -> dict:
    ious = {}
    for case, tile, raw in cases:
        mask = unet.lake_mask(unet.predict(model, raw, device))
        ious.setdefault(case["category"], []).append(tiles.score(mask, tile)["iou"])
    every = [v for vals in ious.values() for v in vals]
    return {"mean_iou": statistics.mean(every), "median_iou": statistics.median(every),
            "by_category": {k: round(statistics.median(v), 3) for k, v in ious.items()}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, default=DATA)
    parser.add_argument("--epochs", type=int, default=25)
    parser.add_argument("--base", type=int, default=24)
    parser.add_argument("--crop", type=int, default=128)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--max-tiles", type=int, help="train on only the first N tiles (a quick check)")
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args()

    torch.manual_seed(args.seed)
    raw, labels = pack(args.data)
    if args.max_tiles:
        raw, labels = raw[:args.max_tiles], labels[:args.max_tiles]
    cases = validation_cases()
    baseline = {}
    for case, tile, _ in cases:
        baseline.setdefault(case["category"], []).append(case["baseline"]["ndwi"]["iou"])
    every = [v for vals in baseline.values() for v in vals]
    print(f"{len(raw)} training tiles, {len(cases)} validation cases. Baseline (NDWI rule) on them: mean overlap "
          f"{statistics.mean(every):.3f}, by category {({k: round(statistics.median(v), 2) for k, v in baseline.items()})}",
          flush=True)

    model = unet.UNet(base=args.base).to(args.device)
    mean, std = unet.channel_stats(raw)
    model.mean.copy_(torch.from_numpy(mean))
    model.std.copy_(torch.from_numpy(std))
    loader = torch.utils.data.DataLoader(unet.TileSet(raw, labels, args.crop, args.seed), batch_size=args.batch,
                                         shuffle=True, num_workers=args.workers, drop_last=True,
                                         worker_init_fn=reseed if args.workers else None,
                                         persistent_workers=False)
    optimiser = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    schedule = torch.optim.lr_scheduler.OneCycleLR(optimiser, args.lr, total_steps=args.epochs * len(loader))
    history, best = [], -1.0
    for epoch in range(1, args.epochs + 1):
        model.train()
        start, losses = time.time(), []
        for x, y in loader:
            x, y = x.to(args.device), y.to(args.device)
            loss = unet.loss_fn(model(x), y)
            optimiser.zero_grad()
            loss.backward()
            optimiser.step()
            schedule.step()
            losses.append(loss.item())
        scores = evaluate(model, cases, args.device)
        row = {"epoch": epoch, "loss": statistics.mean(losses), "seconds": round(time.time() - start), **scores}
        history.append(row)
        marker = ""
        if scores["mean_iou"] > best:
            best = scores["mean_iou"]
            unet.save(model, args.data / "model.pt", epoch=epoch, validation=scores, args=vars(args) | {"data": str(args.data)})
            marker = "  (best so far, saved)"
        print(f"epoch {epoch:>2}: loss {row['loss']:.3f}, validation mean overlap {scores['mean_iou']:.3f}, "
              f"by category {scores['by_category']}, {row['seconds']} s{marker}", flush=True)
        (args.data / "history.json").write_text(json.dumps(
            {"baseline": {k: v for k, v in baseline.items()}, "epochs": history}, indent=1))
    print(f"\nBest validation mean overlap {best:.3f}; model: {args.data / 'model.pt'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
