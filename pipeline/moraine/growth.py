"""P1 step 7a: every inventory lake's area each autumn from 2017, mapped with the U-Net.

For each lake and autumn (1 September-15 November) the Sentinel-2 scenes are ranked from the step 4
flag measurements: clear first (little cloud within 1.3 km of the lake), then thin cloud, never with
the lake mostly in terrain shadow. The first few, one per date, whose tile lies wholly inside the
scene are mapped with the U-Net, and the per-cell median of their lake probability gives the autumn's
map. (The flags' own coverage measure cannot be trusted at swath or granule edges; see
moraine/hard_cases.py.)

A lake's area is the mapped water in patches that touch any of its inventory outlines (2018, 2020 or
2022). Water inside an outline belongs to that outline's lake; the rest of a patch goes to whichever
lake's outline is nearest through the water, so a lake that grows past its old outline is counted in
full while a patch touching two lakes is shared, not counted twice. The tile is labelled with `ids`:
0 for no lake, else 1 + the lake's index in the 2022 file, painted from all three years' outlines.
"""

from __future__ import annotations

import numpy as np

from . import tiles

YEARS = tuple(range(2017, 2026))
SEASON_END = "11-15"  # mapping season; later scenes are mostly frozen and low-sun
PER_AUTUMN = 3
MARGIN_M = 400  # tile margin round the lake's outlines
MIN_SIZE = 256
FIELDS = ("cloud", "shadow", "ice", "cloud_near", "covered_near")

# (cloud within 1.3 km, cloud over the lake, ice on the lake): clear first, then the U-Net's thin-cloud range
TIERS = ((0.05, 0.10, 0.10), (0.20, 0.30, 0.30))
MAX_SHADOW = 0.2  # share of the lake in terrain shadow; step 4's shadow cases start here


def candidates(rows: list[dict], year: int) -> list[dict]:
    """One lake's usable scenes in one autumn, best first.

    `rows` are that lake's flag measurements (moraine/hard_cases.measure). Returns the rows ranked by tier,
    then by cloud near and over the lake, each with "tier" 1 (clear) or 2 (thin cloud allowed). A scene
    is one 100 km granule, so a lake where two granules overlap has two rows for a date: if the first
    one's edge cuts the tile, the other may not (see take)."""
    end = f"{year}-{SEASON_END}"
    usable = [r for r in rows if r["date"] <= end and all(r.get(f) is not None for f in FIELDS)
              and r["covered_near"] >= 0.999 and r["shadow"] < MAX_SHADOW]
    ranked, seen = [], set()
    for tier, (near, over, ice) in enumerate(TIERS, 1):
        ok = [r for r in usable if r["cloud_near"] < near and r["cloud"] < over and r["ice"] < ice
              and r["scene"] not in seen]
        seen.update(r["scene"] for r in ok)
        ranked += [dict(r, tier=tier) for r in sorted(ok, key=lambda r: (r["cloud_near"], r["cloud"], r["scene"]))]
    return ranked


def take(ranked: list[dict], want: int, whole) -> tuple[list[dict], list[dict]]:
    """Walk `ranked` in order until `want` scenes of different dates pass `whole(row)` (their tile lies
    wholly inside the granule). Returns (kept, tried); a date already kept is not tried again."""
    kept, tried, dates = [], [], set()
    for r in ranked:
        if len(kept) == want:
            break
        if r["date"] in dates:
            continue
        tried.append(r)
        if whole(r):
            kept.append(r)
            dates.add(r["date"])
    return kept, tried


def tile_box(xs: list[float], ys: list[float], cell: float = tiles.CELL) -> tuple[float, float, int]:
    """Top-left corner and side (cells, a multiple of 32) of a square tile holding every outline
    vertex given in UTM metres, with MARGIN_M to spare."""
    span = max(max(xs) - min(xs), max(ys) - min(ys)) + 2 * MARGIN_M
    size = max(MIN_SIZE, int(np.ceil(span / cell / 32)) * 32)
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    half = size * cell / 2
    return round((cx - half) / cell) * cell, round((cy + half) / cell) * cell, size


NEIGHBOURS = ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1))


def owners(water: np.ndarray, ids: np.ndarray) -> np.ndarray:
    """Which lake each water cell belongs to (0: none): the lake whose outline holds it, else the lake
    whose outline is fewest 8-connected steps away through water. Water no outline reaches stays 0."""
    owner = np.where(water, ids, 0).astype(np.int32)
    rows, cols = owner.shape
    while True:
        free = water & (owner == 0)
        grown = owner.copy()
        for dr, dc in NEIGHBOURS:  # one step of every lake's front; the first neighbour listed wins a tie
            shifted = np.zeros_like(owner)
            shifted[max(dr, 0):rows + min(dr, 0), max(dc, 0):cols + min(dc, 0)] = \
                owner[max(-dr, 0):rows + min(-dr, 0), max(-dc, 0):cols + min(-dc, 0)]
            take = free & (grown == 0) & (shifted > 0)
            grown[take] = shifted[take]
        if (grown == owner).all():
            return owner
        owner = grown


def lake_area(probability: np.ndarray, ids: np.ndarray, lake: int, threshold: float = 0.5) -> float:
    """Area (km2) of lake `lake` (its value in `ids`) in a lake-probability map; see the module docstring."""
    water = tiles.drop_small(probability > threshold)
    return float((owners(water, ids) == lake).sum()) * tiles.CELL * tiles.CELL / 1e6
