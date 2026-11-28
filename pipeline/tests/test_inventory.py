import math

from moraine import inventory


def square(lon, lat, side_deg, hole=None):
    ring = [(lon, lat), (lon, lat + side_deg), (lon + side_deg, lat + side_deg), (lon + side_deg, lat), (lon, lat)]
    rings = [ring]
    if hole:
        hx, hy, hs = hole
        rings.append([(hx, hy), (hx + hs, hy), (hx + hs, hy + hs), (hx, hy + hs), (hx, hy)])
    return inventory.Lake(2022, {"Area": None}, rings, (lon, lat, lon + side_deg, lat + side_deg))


def test_area_of_a_small_square_lake():
    lake = square(88.0, 28.0, 0.01)
    expected = (0.01 * math.pi / 180 * inventory.EARTH_RADIUS_M) ** 2 * math.cos(math.radians(28.005)) / 1e6
    assert abs(lake.area_km2 - expected) / expected < 1e-9


def test_holes_are_subtracted_and_points_in_holes_are_outside():
    lake = square(88.0, 28.0, 0.01, hole=(88.004, 28.004, 0.002))
    assert abs(lake.area_km2 / square(88.0, 28.0, 0.01).area_km2 - 0.96) < 1e-3
    assert lake.contains(88.002, 28.002)
    assert not lake.contains(88.005, 28.005)


def test_nearest_finds_a_lake_only_within_reach():
    lakes = [square(88.0, 28.0, 0.01), square(88.03, 28.0, 0.01)]
    assert inventory.nearest(lakes, 88.005, 28.005, 50) is lakes[0]
    assert inventory.nearest(lakes, 88.02, 28.005, 50) is None  # about 980 m from both
    assert inventory.nearest(lakes, 88.02, 28.005, 1500) is not None


def test_match_pairs_lakes_by_listed_area_not_by_position():
    def lake(year, index, lon, area, **extra):
        return inventory.Lake(year, {"Area": area, "index": index, **extra}, [], (lon, 28.0, lon + 0.001, 28.001))

    # 2022 lists A then B; 2018 lists them the other way round, plus a lake of A's area 30 km away
    reference = [lake(2022, 0, 88.00, 0.05, Area_2018=0.041), lake(2022, 1, 88.02, 0.09, Area_2018=0.072)]
    earlier = [lake(2018, 0, 88.02, 0.072), lake(2018, 1, 88.00, 0.041), lake(2018, 2, 88.30, 0.041)]
    assert inventory.match(earlier, reference, 2018) == {0: 1, 1: 0}


def test_match_can_pair_areas_the_2022_file_rounded():
    def lake(year, index, lon, area, **extra):
        return inventory.Lake(year, {"Area": area, "index": index, **extra}, [], (lon, 28.0, lon + 0.001, 28.001))

    reference = [lake(2022, 0, 88.00, 1.129, Area_2018=1.11)]  # listed to two decimals
    earlier = [lake(2018, 0, 88.03, 1.108), lake(2018, 1, 88.00, 1.113552833)]  # 1.108 rounds to 1.11 too
    assert inventory.match(earlier, reference, 2018) == {}
    assert inventory.match(earlier, reference, 2018, rounded=True) == {0: 1}  # the nearer of the two
