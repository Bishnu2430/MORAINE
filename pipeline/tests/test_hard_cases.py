from moraine import hard_cases


def row(year, index, date, **flags):
    base = {"cloud": 0.0, "shadow": 0.0, "ice": 0.0, "red": 0.05, "nir": 0.03, "cloud_near": 0.0, "covered_near": 1.0}
    return {"year": year, "id": index, "date": date, **base, **flags}


def test_one_case_per_lake_then_another_year_when_short():
    # lake A is index 1 in 2018 and index 5 in 2022; lake B is index 2 in 2022
    same_lake = {(2018, 1): 5, (2022, 5): 5, (2022, 2): 2}
    rows = [row(2018, 1, "2018-12-01", shadow=0.9), row(2018, 1, "2018-12-05", shadow=0.8),
            row(2022, 5, "2022-12-01", shadow=0.7), row(2022, 2, "2022-12-01", shadow=0.3)]
    shadow = hard_cases.choose(rows, same_lake, 2)["shadow"]
    assert [(r["year"], r["id"]) for r in shadow] == [(2018, 1), (2022, 2)]  # strongest per lake
    shadow = hard_cases.choose(rows, same_lake, 3)["shadow"]
    assert [(r["year"], r["id"], r["date"]) for r in shadow] == [(2018, 1, "2018-12-01"), (2022, 2, "2022-12-01"),
                                                                 (2022, 5, "2022-12-01")]  # A again, other year


def test_scenes_not_covering_the_neighbourhood_are_skipped():
    rows = [row(2022, 1, "2022-10-01", shadow=0.9, covered_near=0.9)]
    assert hard_cases.choose(rows, {}, 5)["shadow"] == []


def test_thin_cloud_is_measured_against_the_lakes_own_clear_days():
    rows = [row(2022, 1, "2022-10-01", red=0.05), row(2022, 1, "2022-10-06", red=0.07),
            row(2022, 1, "2022-10-11", red=0.06),  # clear days: median red 0.06
            row(2022, 1, "2022-10-16", cloud=0.6, cloud_near=0.6, red=0.18),  # veiled: +0.12
            row(2022, 1, "2022-10-21", cloud=0.9, cloud_near=0.9, red=0.60)]  # white: +0.54, opaque
    thin = hard_cases.choose(rows, {}, 5)["thin_cloud"]
    assert [r["date"] for r in thin] == ["2022-10-16"] and abs(thin[0]["red_rise"] - 0.12) < 1e-9
