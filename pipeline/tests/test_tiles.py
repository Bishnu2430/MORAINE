import numpy as np

from moraine import tiles


def test_components_join_diagonals_and_drop_small_patches():
    mask = np.zeros((20, 20), dtype=bool)
    mask[0, 0] = mask[1, 1] = mask[2, 2] = True  # one diagonal patch of 3
    mask[10:13, 10:13] = True  # a square patch of 9
    labels, count = tiles.label_components(mask)
    assert count == 2 and labels[0, 0] == labels[2, 2] != labels[10, 10]
    kept = tiles.drop_small(mask, 5)
    assert kept[10:13, 10:13].all() and not kept[:3, :3].any()


def test_dilate_grows_by_a_disk():
    mask = np.zeros((11, 11), dtype=bool)
    mask[5, 5] = True
    grown = tiles.dilate(mask, 2)
    assert grown.sum() == 13 and grown[5, 3] and grown[3, 5] and not grown[3, 3]


def test_baseline_and_score_on_a_synthetic_lake():
    shape = (60, 60)
    lake = np.zeros(shape, dtype=bool)
    lake[20:40, 15:45] = True  # 600 cells, above the 200-cell cut-off
    tile = {"B3": np.where(lake, 900, 1200), "B8": np.where(lake, 300, 1500), "B11": np.where(lake, 100, 1400),
            "slope": np.zeros(shape), "lake": lake}
    for variant in ("ndwi", "ndwi_mndwi"):
        mapped = tiles.baseline(tile, variant)
        assert (mapped == lake).all()
        assert tiles.score(mapped, tile) == {"iou": 1.0, "lake_cells": 600, "mapped_cells": 600, "area_error": 0.0}
    steep = dict(tile, slope=np.full(shape, 20.0))
    assert tiles.score(tiles.baseline(steep), tile)["iou"] == 0.0
