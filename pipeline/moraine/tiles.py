"""Hard-case tiles as numpy arrays: the baseline rule on one scene, and per-case scoring.

A tile is 256 x 256 cells of 10 m (UTM 45N) centred on one inventory lake, exported by
pipeline/scripts/p1_hard_cases.py as a .npz with:

- B2, B3, B4, B8, B11, B12: Sentinel-2 Level-1C reflectance x 10000 (20 m bands resampled to 10 m)
- cloud: s2cloudless probability (0-100)
- slope: GLO-30 slope in degrees
- label: every inventory lake of that year (1 = lake)
- lake: the case's own lake only

Pure numpy, so step 6 can score the U-Net and both rule variants with the same code in Colab.
"""

from __future__ import annotations

import numpy as np

SIZE = 256
CELL = 10.0
NDWI_CUT = 0.25
MNDWI_CUT = 0.10
MAX_SLOPE_DEG = 12
MIN_LAKE_CELLS = 200  # 0.02 km2
BUFFER_CELLS = 6  # 60 m, as in step 3
NEAR_CELLS = 50  # 500 m: the neighbourhood the main score covers


def load(path) -> dict:
    with np.load(path) as data:
        return {name: data[name] for name in data.files}


def rgb(tile: dict) -> np.ndarray:
    """True-colour picture (rows, cols, 3) in 0-1, stretched between the tile's 2nd and 98th percentiles."""
    stack = np.dstack([tile[b].astype(np.float64) for b in ("B4", "B3", "B2")])
    lo, hi = np.percentile(stack, 2), np.percentile(stack, 98)
    return np.clip((stack - lo) / max(hi - lo, 1), 0, 1) ** 0.8


def normalized_difference(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    a, b = a.astype(np.float64), b.astype(np.float64)
    total = a + b
    return np.divide(a - b, total, out=np.zeros_like(total), where=total != 0)


def label_components(mask: np.ndarray) -> tuple[np.ndarray, int]:
    """8-connected components of a boolean mask: (labels with 0 = background, number of components)."""
    labels = np.zeros(mask.shape, dtype=np.int32)
    count = 0
    rows, cols = mask.shape
    for r0, c0 in zip(*np.nonzero(mask)):
        if labels[r0, c0]:
            continue
        count += 1
        labels[r0, c0] = count
        stack = [(r0, c0)]
        while stack:
            r, c = stack.pop()
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    rr, cc = r + dr, c + dc
                    if 0 <= rr < rows and 0 <= cc < cols and mask[rr, cc] and not labels[rr, cc]:
                        labels[rr, cc] = count
                        stack.append((rr, cc))
    return labels, count


def drop_small(mask: np.ndarray, min_cells: int = MIN_LAKE_CELLS) -> np.ndarray:
    """Keep 8-connected patches of at least min_cells."""
    labels, count = label_components(mask)
    if count == 0:
        return mask.copy()
    sizes = np.bincount(labels.ravel(), minlength=count + 1)
    keep = sizes >= min_cells
    keep[0] = False
    return keep[labels]


def baseline(tile: dict, variant: str = "ndwi") -> np.ndarray:
    """Step 3's rule on one scene: NDWI > 0.25 on slopes under 12 degrees (and MNDWI > 0.10 for the
    "ndwi_mndwi" variant), in patches of at least 0.02 km2."""
    water = (normalized_difference(tile["B3"], tile["B8"]) > NDWI_CUT) & (tile["slope"] < MAX_SLOPE_DEG)
    if variant == "ndwi_mndwi":
        water &= normalized_difference(tile["B3"], tile["B11"]) > MNDWI_CUT
    return drop_small(water)


def dilate(mask: np.ndarray, cells: int) -> np.ndarray:
    """Grow a mask by a disk of the given radius in cells."""
    out = mask.copy()
    rows, cols = mask.shape
    for dr in range(-cells, cells + 1):
        for dc in range(-cells, cells + 1):
            if dr * dr + dc * dc > cells * cells:
                continue
            shifted = np.zeros_like(mask)
            shifted[max(dr, 0):rows + min(dr, 0), max(dc, 0):cols + min(dc, 0)] = \
                mask[max(-dr, 0):rows + min(-dr, 0), max(-dc, 0):cols + min(-dc, 0)]
            out |= shifted
    return out


def neighbourhood(lake: np.ndarray, cells: int = NEAR_CELLS) -> np.ndarray:
    """The lake's bounding box grown by `cells` on every side, clipped to the tile."""
    rows, cols = np.nonzero(lake)
    out = np.zeros(lake.shape, dtype=bool)
    out[max(rows.min() - cells, 0):rows.max() + cells + 1, max(cols.min() - cells, 0):cols.max() + cells + 1] = True
    return out


def score(mapped: np.ndarray, tile: dict) -> dict:
    """How well a lake map matches the inventory around one case's lake.

    - iou (the main score): overlap with every inventory lake within 500 m of the case lake's bounding
      box. Water mapped where there is no lake counts against it, so painting everything as lake
      scores about 0.1, not the 0.56 the narrower measure below would give.
    - lake_iou: overlap with the case's own lake inside its outline grown by 60 m, as in step 3.
    - area_error: mapped against listed area for the case's own lake, inside that 60 m window."""
    mapped = mapped.astype(bool)
    lake = tile["lake"].astype(bool)
    near = neighbourhood(lake)
    truth = tile["label"].astype(bool) & near
    got_near = mapped & near
    window = dilate(lake, BUFFER_CELLS)
    got = mapped & window
    def overlap(a, b):
        union = (a | b).sum()
        return float((a & b).sum() / union) if union else 0.0
    return {"iou": overlap(got_near, truth), "lake_iou": overlap(got, lake), "lake_cells": int(lake.sum()),
            "mapped_cells": int(got.sum()), "area_error": float(got.sum() / lake.sum() - 1) if lake.sum() else None}
