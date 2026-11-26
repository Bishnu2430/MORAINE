import numpy as np

from moraine import study_areas, terrain


def test_upstream_walk_follows_next_down_links():
    # 1 and 2 drain into 3, 3 into 5, 4 into 5, 6 drains elsewhere (7)
    table = [(1, 3), (2, 3), (3, 5), (4, 5), (5, 0), (6, 7), (7, 0)]
    assert study_areas.upstream_of(3, table) == {1, 2, 3}
    assert study_areas.upstream_of(5, table) == {1, 2, 3, 4, 5}
    assert study_areas.upstream_of(6, table) == {6}


def test_point_in_polygon_with_a_hole_and_a_second_part():
    square = [[(0, 0), (0, 4), (4, 4), (4, 0), (0, 0)], [(1, 1), (3, 1), (3, 3), (1, 3), (1, 1)]]
    island = [[(10, 10), (10, 11), (11, 11), (11, 10), (10, 10)]]
    polys = study_areas.polygons_of({"type": "MultiPolygon", "coordinates": [square, island]})
    assert study_areas.contains(polys, 0.5, 0.5)
    assert not study_areas.contains(polys, 2, 2)  # in the hole
    assert study_areas.contains(polys, 10.5, 10.5)
    assert not study_areas.contains(polys, 5, 5)
    assert study_areas.bounds(polys) == (0, 0, 11, 11)


def test_upstream_mask_on_flow_directions():
    # A 3 x 3 grid all draining to the bottom-middle cell (row 2, col 1); the top-left corner drains away east-out
    d = np.array([[2, 4, 8],
                  [1, 4, 16],
                  [1, 0, 16]])
    mask = terrain.upstream_mask(d, (2, 1))
    assert mask.tolist() == [[True, True, True], [True, True, True], [True, True, True]]
    d[0, 0] = 64  # now flows north, off the grid
    assert not terrain.upstream_mask(d, (2, 1))[0, 0]
