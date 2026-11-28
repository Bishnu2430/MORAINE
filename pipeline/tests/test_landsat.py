import math

import numpy as np

from moraine import landsat


def test_sensor_of_reads_the_asset_id():
    assert landsat.sensor_of("LANDSAT/LT05/C02/T1_TOA/LT05_140041_19901015") == "LT05"
    assert landsat.sensor_of("LANDSAT/LC08/C02/T1_TOA/LC08_140041_20181020") == "LC08"
    assert landsat.sensor_of("LANDSAT/LC08/C02/T1_TOA/LO08_139041_20201022") == "LC08"  # optical-only scene


def test_every_sensor_maps_six_bands_onto_the_sentinel_2_names():
    assert all(len(bands) == len(landsat.AS_S2) for _, bands in landsat.SENSORS.values())
    assert landsat.SENSORS["LC08"][1][3] == "B5" and landsat.SENSORS["LT05"][1][3] == "B4"  # near-infrared


def test_choose_mapper_takes_the_smaller_median_log_error_and_scores_a_miss_as_large():
    chosen, scores = landsat.choose_mapper({"rule": [0.9, 0.95, 0.0], "unet": [1.05, 1.02, 0.97]})
    assert chosen == "unet"
    assert math.isclose(scores["rule"], abs(math.log(0.9)))  # median of |log| over 0.95, 0.9 and the miss
    assert landsat.choose_mapper({"b": [1.1], "a": [1.1]})[0] == "a"  # a tie goes to the first name


def test_near_1990_prefers_1990_then_the_nearest_years():
    assert landsat.near_1990({1988: 1, 1991: 1, 1990: 1}) == 1990
    assert landsat.near_1990({1988: 1, 1991: 1}) == 1991
    assert landsat.near_1990({1993: 1}) is None


def test_windows_mapped_counts_windows_with_a_year():
    assert landsat.windows_mapped({1988, 1990, 2016}) == 2
    assert landsat.windows_mapped(set(range(1988, 2017))) == len(landsat.WINDOWS)


def test_pack_keeps_reflectance_to_0_002():
    packed = landsat.pack(np.array([0, 1420, 1031, 60000], dtype=np.uint16))
    assert packed.dtype == np.uint8
    assert np.allclose(landsat.unpack(packed), [0, 0.142, 0.1040, 0.51], atol=1e-6)  # 1031 rounds to 0.104; capped at 0.51


def test_stable_needs_three_listed_areas_within_10_percent():
    assert landsat.stable({2018: 0.30, 2020: 0.31, 2022: 0.32})
    assert not landsat.stable({2018: 0.30, 2020: 0.31, 2022: 0.34})  # 13% apart
    assert not landsat.stable({2020: 0.31, 2022: 0.32})  # not listed in 2018
    assert not landsat.stable({2018: 0.04, 2020: 0.04, 2022: 0.04})  # under 0.05 km2


def test_interior_keeps_cells_at_least_n_inside():
    ids = np.zeros((12, 12), np.uint16)
    ids[2:10, 2:10] = 5
    inside = landsat.interior(ids, 5, 2)
    assert inside[4:8, 4:8].all() and inside.sum() == 16


def test_thresholds_weigh_each_lake_equally():
    big, small = np.full(1000, 0.01), np.full(10, 0.20)
    assert landsat.weighted_percentile([big, small], 98) == 0.20  # pooled by cell it would be 0.01
    assert landsat.weighted_percentile([big, small], 40) == 0.01
    assert landsat.gate_thresholds([(big, small), (small, big)]) == (0.20, 0.20)


def test_open_water_keeps_mapped_cells_within_30_m_of_open_water():
    probability = np.ones((20, 20), np.float32)
    nir = np.full((20, 20), 0.5, np.float32)  # snow
    nir[:, :5] = 0.05  # open water in the first five columns
    swir = np.full((20, 20), 0.02, np.float32)
    kept = landsat.open_water(probability, nir, swir, (0.142, 0.103)) > 0
    assert kept[:, :8].all() and not kept[:, 8:].any()  # five columns, then three cells of 10 m
    debris = landsat.open_water(probability, np.full((20, 20), 0.05), np.full((20, 20), 0.25), (0.142, 0.103))
    assert not debris.any()
