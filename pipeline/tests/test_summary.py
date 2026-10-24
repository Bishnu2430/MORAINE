import pandas as pd

from moraine import references, summary

AOI = 2_000_000.0  # m², about the size of the South Lhonak measuring area


def scene(day: str, water_km2: float, sensor: str = "Landsat 8", valid: float = 1.0) -> dict:
    ms = int(pd.Timestamp(day).timestamp() * 1000)
    return {
        "sensor": sensor,
        "scene": f"{sensor}-{day}",
        "time_ms": ms,
        "valid_m2": valid * AOI,
        "aoi_m2": AOI,
        "water_t15_m2": (water_km2 + 0.1) * 1e6,
        "water_t25_m2": water_km2 * 1e6,
        "water_t35_m2": (water_km2 - 0.1) * 1e6,
    }


def test_tidy_keeps_the_clearer_image_of_a_repeated_day():
    df = summary.tidy([scene("2020-10-01", 1.0, valid=0.6), scene("2020-10-01", 1.4, valid=0.99)])
    assert len(df) == 1
    assert df.loc[0, "water_t25_km2"] == 1.4


def test_tidy_keeps_landsat_and_sentinel2_of_the_same_day():
    df = summary.tidy([scene("2020-10-01", 1.0), scene("2020-10-01", 1.1, sensor="Sentinel-2")])
    assert sorted(df["family"]) == ["Landsat", "Sentinel-2"]


def test_yearly_drops_cloudy_and_out_of_season_scenes():
    df = summary.tidy([
        scene("2019-10-01", 1.0),
        scene("2019-10-20", 1.2),
        scene("2019-10-10", 0.1, valid=0.5),  # cloudy
        scene("2019-11-25", 0.0),  # after 15 Nov: lake may be frozen
    ])
    by_year = summary.yearly(df, "2023-10-04")
    assert list(by_year["period"]) == ["2019"]
    assert by_year.loc[0, "scenes"] == 2
    assert abs(by_year.loc[0, "area_km2"] - 1.1) < 1e-9


def test_yearly_splits_the_event_year_at_the_event_date():
    df = summary.tidy([
        scene("2023-09-28", 1.65),
        scene("2023-10-03", 1.66),
        scene("2023-10-05", 0.62),
    ])
    by_year = summary.yearly(df, "2023-10-04")
    assert list(by_year["period"]) == ["2023 before", "2023 after"]
    assert list(by_year["scenes"]) == [2, 1]


def test_south_lhonak_checks_pass_on_published_like_values():
    df = summary.tidy([
        scene("2014-10-10", 1.20),
        scene("2015-10-10", 1.25),
        scene("2016-10-10", 1.30),
        scene("2023-09-28", 1.67),
        scene("2023-10-05", 0.61),
    ])
    results = summary.run_checks(df, references.SOUTH_LHONAK["checks"])
    assert [r.passed for r in results] == [True, True, True]
    assert results[0].detail.endswith("28 Sep 2023")
    assert results[1].detail.endswith("05 Oct 2023")


def test_checks_fail_when_the_drop_is_missing_or_there_is_no_data():
    df = summary.tidy([scene("2023-09-28", 1.67), scene("2023-10-05", 1.66)])
    results = summary.run_checks(df, references.SOUTH_LHONAK["checks"])
    assert [r.passed for r in results] == [True, False, False]
    assert results[2].value_km2 is None
