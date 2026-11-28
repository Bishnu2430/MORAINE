import math

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


def test_7b_reads_landsat_8_for_2013_to_2016():
    assert landsat.USED == ("LC08",) and landsat.YEARS == (2013, 2014, 2015, 2016)
