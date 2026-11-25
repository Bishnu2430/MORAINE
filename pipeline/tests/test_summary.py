from moraine import references, summary

AOI = 2_000_000.0  # m², about the size of the South Lhonak measuring area


def period(name: str, water_km2: float, family: str = "Sentinel-2", coverage: float = 1.0) -> dict:
    year = int(name[:4])
    start, end = f"{year}-09-01", f"{year}-11-16"
    if name.endswith("before"):
        end = "2023-10-04"
    if name.endswith("after"):
        start = "2023-10-04"
    return {
        "family": family,
        "period": name,
        "start": start,
        "end": end,
        "scenes": 8,
        "covered_m2": coverage * AOI,
        "aoi_m2": AOI,
        "water_t15_m2": (water_km2 + 0.05) * 1e6,
        "water_t25_m2": water_km2 * 1e6,
        "water_t35_m2": max(water_km2 - 0.05, 0) * 1e6,
    }


def test_autumn_periods_split_the_event_autumn():
    periods = summary.autumn_periods("2023-10-04", first_year=2022, last_year=2024)
    assert [p["period"] for p in periods] == ["2022", "2023 before", "2023 after", "2024"]
    assert periods[1] == {"period": "2023 before", "start": "2023-09-01", "end": "2023-10-04"}
    assert periods[2]["start"] == "2023-10-04" and periods[2]["end"] == "2023-11-16"


def test_autumn_periods_do_not_split_for_an_event_outside_autumn():
    periods = summary.autumn_periods("2013-06-17", first_year=2013, last_year=2013)
    assert [p["period"] for p in periods] == ["2013"]


def test_tidy_handles_periods_with_no_scenes():
    empty = period("1986", 0.0, family="Landsat")
    empty.update(covered_m2=0, aoi_m2=0, scenes=0)
    df = summary.tidy([empty])
    assert df.loc[0, "coverage"] == 0.0
    assert len(summary.usable(df)) == 0


def test_best_prefers_sentinel2_and_falls_back_to_landsat():
    df = summary.tidy([
        period("2020", 1.40, "Landsat"),
        period("2020", 1.45, "Sentinel-2"),
        period("2021", 1.42, "Landsat"),
        period("2021", 1.50, "Sentinel-2", coverage=0.5),  # too little clear coverage
    ])
    picked = summary.best(df, "2023-10-04").set_index("period")
    assert picked.loc["2020", "family"] == "Sentinel-2"
    assert picked.loc["2021", "family"] == "Landsat"
    assert abs(picked.loc["2021", summary.MAIN] - 1.42) < 1e-9


def test_south_lhonak_gates_pass_on_published_like_values():
    df = summary.tidy([
        period("2014", 1.20, "Landsat"),
        period("2015", 1.25, "Landsat"),
        period("2016", 1.30, "Landsat"),
        period("2023 before", 1.65),
        period("2023 after", 1.10),
    ])
    results = {r.name: r for r in summary.run_checks(df, references.SOUTH_LHONAK["checks"], "2023-10-04")}
    gates = [r for r in results.values() if r.role == "gate"]
    assert all(r.in_range for r in gates)
    assert abs(results["Open water shrinks after the outburst"].value - 1.10 / 1.65) < 1e-9
    # The published-figure comparison is reported but does not decide pass or fail
    compare = results["Autumn 2023 after the outburst, against published figures"]
    assert compare.role == "compare" and not compare.in_range


def test_gates_fail_without_a_drop_or_without_data():
    df = summary.tidy([period("2023 before", 1.65), period("2023 after", 1.64)])
    results = {r.name: r for r in summary.run_checks(df, references.SOUTH_LHONAK["checks"], "2023-10-04")}
    assert results["Autumn 2023, before the outburst"].in_range
    assert not results["Open water shrinks after the outburst"].in_range
    assert results["Autumns 2014-2016"].value is None


def test_a_one_year_spike_is_dropped_but_the_outburst_drop_is_kept():
    df = summary.tidy([
        period("1996", 0.62, "Landsat"),
        period("1997", 0.53, "Landsat"),
        period("1998", 0.55, "Landsat"),
        period("1999", 1.65, "Landsat"),  # a lake does not triple for one autumn
        period("2000", 0.66, "Landsat"),
        period("2021", 1.60),
        period("2022", 1.64),
        period("2023 before", 1.67),
        period("2023 after", 1.10),  # real drop: only compared with later autumns
        period("2024", 1.12),
        period("2025", 1.15),
    ])
    picked = summary.best(df, "2023-10-04").set_index("period")
    assert picked.loc["1999", "outlier"]
    assert not picked["outlier"].drop("1999").any()
    assert "1999" not in set(summary.series(df, "2023-10-04")["period"])


def test_every_lake_has_what_the_script_and_chart_need():
    for lake in references.LAKES.values():
        for key in ("name", "lon", "lat", "margin_m", "event_date", "event_label", "published", "checks"):
            assert key in lake, f"{lake.get('name')} is missing {key}"
        for check in lake["checks"]:
            assert check["role"] in ("gate", "compare")
            assert ("periods" in check) != ("ratio" in check)
