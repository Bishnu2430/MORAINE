import numpy as np
import pytest

from moraine import terrain


def test_trace_follows_flow_directions_off_the_grid():
    d = np.zeros((3, 4), dtype=int)
    d[0, 0] = 1  # east
    d[0, 1] = 2  # south-east
    d[1, 2] = 1  # east
    d[1, 3] = 4  # south
    d[2, 3] = 1  # east, off the grid
    assert terrain.trace_downhill(d, (0, 0)) == [(0, 0), (0, 1), (1, 2), (1, 3), (2, 3)]


def test_trace_stops_on_a_loop_and_on_request():
    d = np.array([[1, 4], [64, 16]])  # east, south, north, west: a closed loop
    assert terrain.trace_downhill(d, (0, 0)) == [(0, 0), (0, 1), (1, 1), (1, 0)]
    assert terrain.trace_downhill(d, (0, 0), stop=lambda r, c: c == 1) == [(0, 0), (0, 1)]


def test_distance_to_polyline():
    line = np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0]])
    xs = np.array([5.0, 15.0, -3.0, 12.0])
    ys = np.array([2.0, 5.0, -4.0, 12.0])
    np.testing.assert_allclose(terrain.distance_to_polyline(xs, ys, line), [2.0, 5.0, 5.0, np.hypot(2, 2)])


def test_block_mean_ignores_empty_cells():
    h = np.array([[1.0, 3.0, np.nan, np.nan], [5.0, np.nan, np.nan, np.nan]])
    out = terrain.block_mean(h, 2)
    assert out[0, 0] == 3.0 and np.isnan(out[0, 1])


def test_encode_round_trip_and_nodata():
    h = np.array([[1296.04, 6877.95], [np.nan, 3000.0]])
    data = terrain.encode(h, 1296.0)
    assert data.dtype == np.dtype("<u2") and data[1, 0] == terrain.NODATA
    back = terrain.decode(data, 1296.0)
    assert np.isnan(back[1, 0])
    np.testing.assert_allclose(back[~np.isnan(back)], h[~np.isnan(h)], atol=terrain.SCALE / 2 + 1e-9)


def test_encode_refuses_relief_beyond_one_scale():
    with pytest.raises(ValueError):
        terrain.encode(np.array([0.0, 7000.0]), 0.0)


def test_every_event_has_what_the_checks_need():
    from moraine import events

    for key, event in events.EVENTS.items():
        for field in ("name", "date", "places", "length_km", "half_width_m", "crs", "search", "lake_method", "rain"):
            assert field in event, f"{key} is missing {field}"
        assert event["lake_method"] in ("drained", "documented", "jrc")
        if event["lake_method"] == "drained":
            assert event["lake"] is None and len(event["lake_search"]) == 4
        else:
            assert {"lon", "lat"} <= set(event["lake"])
        if event["lake_method"] == "documented":
            assert event["lake_note"]
        zone = int(event["crs"][-2:])
        lon = event["lake"]["lon"] if event["lake"] else event["lake_search"][0]
        assert zone == int((lon + 180) // 6) + 1, f"{key}: {event['crs']} is not the UTM zone at {lon} E"
