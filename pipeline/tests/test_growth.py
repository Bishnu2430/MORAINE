import numpy as np

from moraine import growth


def row(date, granule="A", **flags):
    base = {"cloud": 0.0, "shadow": 0.0, "ice": 0.0, "cloud_near": 0.0, "covered_near": 1.0}
    return {"date": date, "scene": f"{date}_{granule}", **base, **flags}


def test_candidates_rank_clear_then_thin_cloud_and_stay_in_season():
    rows = [row("2022-09-10", "B", cloud_near=0.01), row("2022-09-10", "A", cloud_near=0.0),  # two granules
            row("2022-10-01", cloud_near=0.15, cloud=0.2),  # thin cloud: tier 2
            row("2022-10-20", cloud_near=0.03), row("2022-11-20"),  # after 15 Nov
            row("2022-09-30", covered_near=0.9), row("2022-10-05", cloud_near=0.6),  # off the swath, cloudy
            row("2022-11-02", shadow=0.5)]  # lake in shadow
    ranked = growth.candidates(rows, 2022)
    assert [(r["scene"], r["tier"]) for r in ranked] == [
        ("2022-09-10_A", 1), ("2022-09-10_B", 1), ("2022-10-20_A", 1), ("2022-10-01_A", 2)]


def test_take_tries_the_other_granule_of_a_date_only_when_the_first_is_cut():
    ranked = [row("09-10", "A"), row("09-10", "B"), row("09-12", "A"), row("09-12", "B"), row("09-20", "A")]
    cut = {"09-10_A"}
    kept, tried = growth.take(ranked, 2, lambda r: r["scene"] not in cut)
    assert [r["scene"] for r in kept] == ["09-10_B", "09-12_A"]
    assert [r["scene"] for r in tried] == ["09-10_A", "09-10_B", "09-12_A"]
    kept, tried = growth.take(ranked, 5, lambda r: False)  # everything cut: all tried, none kept
    assert kept == [] and len(tried) == 5


def test_tile_box_fits_the_lake_with_margin_on_a_32_cell_grid():
    x0, y_top, size = growth.tile_box([500_000, 503_000], [3_000_000, 3_001_000])
    assert size % 32 == 0 and size * 10 >= 3_000 + 2 * growth.MARGIN_M
    assert x0 <= 500_000 - growth.MARGIN_M and x0 + size * 10 >= 503_000 + growth.MARGIN_M
    assert growth.tile_box([0, 10], [0, 10])[2] == growth.MIN_SIZE


def test_lake_area_keeps_growth_joined_to_the_lake_and_shares_a_patch_between_lakes():
    ids = np.zeros((60, 60), dtype=np.uint16)
    ids[10:30, 10:30] = 7  # the lake's old outline, 400 cells
    ids[10:30, 46:56] = 9  # another lake, 200 cells
    p = np.zeros((60, 60))
    p[10:30, 10:40] = 0.9  # the lake has grown 10 cells eastwards: 600 cells
    p[10:30, 46:56] = 0.9  # the other lake
    p[50:55, 0:50] = 0.9  # a separate 250-cell patch touching no outline
    assert abs(growth.lake_area(p, ids, 7) - 600 * 100 / 1e6) < 1e-12
    p[10:30, 40:46] = 0.9  # now one patch: columns 30-37 are nearer lake 7, 38-45 nearer lake 9
    seven, nine = growth.lake_area(p, ids, 7), growth.lake_area(p, ids, 9)
    assert abs(seven - 560 * 100 / 1e6) < 1e-12 and abs(nine - 360 * 100 / 1e6) < 1e-12
    assert abs(seven + nine - 20 * 46 * 100 / 1e6) < 1e-12  # the patch is counted once
