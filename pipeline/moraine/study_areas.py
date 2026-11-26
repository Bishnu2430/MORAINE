"""P1 study areas: the whole catchment draining to the end of each P0 flood corridor.

The outlet is the end of the river route P0 traced on MERIT Hydro. The catchment is every HydroSHEDS
level-12 basin whose downstream chain reaches the basin holding that outlet, cross-checked against
MERIT Hydro's own upstream area at the outlet. The Earth Engine calls are at the top; the graph walk
and the point-in-polygon test below them are plain Python and are tested offline.
"""

from __future__ import annotations

from collections import defaultdict

HYDROBASINS = "WWF/HydroSHEDS/v1/Basins/hybas_12"

# lake: where the P0 route starts; route_km: how far down it the outlet sits; search: west, south, east,
# north (degrees), which must hold the whole catchment
AREAS = {
    "sikkim": {"name": "North Sikkim: Teesta above Chungthang", "lake": (88.191, 27.913), "route_km": 76.2,
               "search": (87.9, 27.4, 89.2, 28.4), "role": "study"},
    "bhote_koshi": {"name": "Bhote Koshi / Poiqu above Barabise", "lake": (86.0700, 28.0781), "route_km": 52.0,
                    "search": (85.3, 27.6, 86.6, 29.0), "role": "study"},
    "khumbu": {"name": "Khumbu: Bhote Koshi below Thame", "lake": (86.5730, 27.8278), "route_km": 20.0,
               "search": (86.3, 27.6, 87.3, 28.3), "role": "study"},
    "mandakini": {"name": "Mandakini above Kedarnath's flood route end", "lake": (79.0608, 30.7475),
                  "route_km": 20.0, "search": (78.7, 30.3, 79.4, 31.0), "role": "count only"},
}
# Lakes each catchment must contain (longitude, latitude)
MUST_CONTAIN = {
    "sikkim": {"South Lhonak": (88.191, 27.913)},
    "bhote_koshi": {"Gongbatongsha (drained 2016)": (86.0700, 28.0781)},
    "khumbu": {"Thame's breached lake": (86.5730, 27.8278)},
    "mandakini": {"Chorabari (drained 2013)": (79.0608, 30.7475)},
}


def basin_table(box):
    """(HYBAS_ID, NEXT_DOWN) for every level-12 basin touching the box."""
    import ee

    basins = ee.FeatureCollection(HYDROBASINS).filterBounds(ee.Geometry.Rectangle(list(box)))
    rows = basins.reduceColumns(ee.Reducer.toList(2), ["HYBAS_ID", "NEXT_DOWN"]).get("list").getInfo()
    return [(int(a), int(b)) for a, b in rows]


def basin_at(lon: float, lat: float) -> int:
    import ee

    basin = ee.FeatureCollection(HYDROBASINS).filterBounds(ee.Geometry.Point([lon, lat])).first()
    return int(basin.get("HYBAS_ID").getInfo())


def catchment_geometry(ids: list[int], simplify_m: float = 60):
    """The dissolved outline of the given basins, as GeoJSON, and its area in km2."""
    import ee

    basins = ee.FeatureCollection(HYDROBASINS).filter(ee.Filter.inList("HYBAS_ID", ids))
    geometry = basins.geometry().dissolve(maxError=30).simplify(maxError=simplify_m)
    info = ee.Dictionary({"geometry": geometry, "area": geometry.area(maxError=30)}).getInfo()
    return info["geometry"], info["area"] / 1e6


# --- Plain Python ------------------------------------------------------------------------------------

def upstream_of(outlet: int, table: list[tuple[int, int]]) -> set[int]:
    """Every basin whose NEXT_DOWN chain reaches `outlet`, the outlet included."""
    children = defaultdict(list)
    for basin, down in table:
        children[down].append(basin)
    found, stack = {outlet}, [outlet]
    while stack:
        for child in children[stack.pop()]:
            if child not in found:
                found.add(child)
                stack.append(child)
    return found


def polygons_of(geojson: dict) -> list[list[list[tuple[float, float]]]]:
    """Polygon or MultiPolygon GeoJSON as a list of polygons, each a list of rings (outer first)."""
    if geojson["type"] == "Polygon":
        polys = [geojson["coordinates"]]
    elif geojson["type"] == "MultiPolygon":
        polys = geojson["coordinates"]
    elif geojson["type"] == "GeometryCollection":
        return [p for g in geojson["geometries"] if g["type"] in ("Polygon", "MultiPolygon") for p in polygons_of(g)]
    else:
        raise ValueError(f"not a polygon: {geojson['type']}")
    return [[[tuple(pt) for pt in ring] for ring in poly] for poly in polys]


def contains(polygons, lon: float, lat: float) -> bool:
    """Even-odd point-in-polygon over all rings of all polygons (holes included)."""
    inside = False
    for poly in polygons:
        for ring in poly:
            for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
                if (y1 > lat) != (y2 > lat) and lon < x1 + (lat - y1) * (x2 - x1) / (y2 - y1):
                    inside = not inside
    return inside


def bounds(polygons) -> tuple[float, float, float, float]:
    xs = [x for poly in polygons for ring in poly for x, _ in ring]
    ys = [y for poly in polygons for ring in poly for _, y in ring]
    return min(xs), min(ys), max(xs), max(ys)
