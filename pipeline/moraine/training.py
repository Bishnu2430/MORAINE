"""P1 step 5: training tiles for the U-Net, from inventory lakes outside the study areas.

Each training lake gets one random inventory year (2018, 2020 or 2022) and one random Sentinel-2
Level-1C scene of that year's 1 September-31 December that covers its whole tile, so frozen,
shadowed, veiled and silty lakes appear at their natural rates. The tile is 160 x 160 cells of 10 m
in the lake's own UTM zone, centred within 300 m of the lake so the lake is not always in the middle.
The label is every inventory lake of that year in the tile.

Tiles where cloud hides the lakes (mean cloud probability over the label above HIDDEN) are dropped:
no method can see them, and the label would teach the model to call cloud a lake.
"""

from __future__ import annotations

import math
import random

import ee

from . import watch

SIZE = 160
CELL = 10.0
JITTER_CELLS = 30  # lake centre within 300 m of the tile centre
SCENE_CLOUD = 70  # % scene cloud allowed when picking scenes
MARGIN_DEG = 0.05  # keep training lakes this far (about 5 km) outside every study area's bounds
HIDDEN = 60  # mean cloud probability (%) over the label above which a tile is dropped
BANDS = ("B2", "B3", "B4", "B8", "B11", "B12")


def utm_epsg(lon: float) -> int:
    return 32600 + int((lon + 180) // 6) + 1


def plan_tiles(by_year: dict, pairs: dict, excluded_boxes: list, count: int, seed: int) -> list[dict]:
    """Choose `count` training lakes and, for each, a year and a tile.

    `pairs[year]` maps 2022 index -> index in that year's file (inventory.match). A lake qualifies in a
    year when it is at least 0.02 km2 that year; lakes inside any excluded box are skipped."""
    rng = random.Random(seed)
    lakes22 = by_year[2022]
    candidates = []
    for lake in lakes22:
        if any(w - MARGIN_DEG <= lake.lon <= e + MARGIN_DEG and s - MARGIN_DEG <= lake.lat <= n + MARGIN_DEG
               for w, s, e, n in excluded_boxes):
            continue
        years = [y for y in by_year if (y == 2022 or lake.attrs["index"] in pairs[y])
                 and by_year[y][lake.attrs["index"] if y == 2022 else pairs[y][lake.attrs["index"]]].area_km2 >= 0.02]
        if years:
            candidates.append((lake.attrs["index"], years))
    rng.shuffle(candidates)
    plans = []
    for i22, years in candidates[:count]:
        year = rng.choice(sorted(years))
        index = i22 if year == 2022 else pairs[year][i22]
        lake = by_year[year][index]
        plans.append({"key": f"{year}-{index:04d}", "year": year, "lake_index": index, "lake_2022": i22,
                      "lon": lake.lon, "lat": lake.lat, "epsg": utm_epsg(lake.lon), "seed": rng.randrange(1 << 30),
                      "jitter": (rng.randint(-JITTER_CELLS, JITTER_CELLS), rng.randint(-JITTER_CELLS, JITTER_CELLS))})
    return plans


def place(plans: list[dict], utm_by_zone) -> None:
    """Add each tile's top-left corner, from the lake centre in UTM (utm_by_zone(epsg, lonlat list))."""
    for epsg in {p["epsg"] for p in plans}:
        group = [p for p in plans if p["epsg"] == epsg]
        for p, (x, y) in zip(group, utm_by_zone(epsg, [(p["lon"], p["lat"]) for p in group])):
            half = SIZE * CELL / 2
            p["x0"] = round(x / CELL) * CELL - half + p["jitter"][0] * CELL
            p["y_top"] = round(y / CELL) * CELL + half + p["jitter"][1] * CELL


def box(p: dict) -> ee.Geometry:
    return ee.Geometry.Rectangle([p["x0"], p["y_top"] - SIZE * CELL, p["x0"] + SIZE * CELL, p["y_top"]],
                                 f"EPSG:{p['epsg']}", False)


def pick_scenes(plans: list[dict]) -> list[str | None]:
    """One random scene per tile (seeded), covering the whole tile and with a cloud-probability image."""

    def pick(f):
        area, start = f.geometry(), ee.Date.fromYMD(ee.Number(f.get("year")), 9, 1)
        end = start.advance(4, "month")
        s2 = (ee.ImageCollection(watch.S2_L1C).filterBounds(area).filterDate(start, end)
              .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", SCENE_CLOUD))
              .filter(ee.Filter.contains(leftField=".geo", rightValue=area)))
        probability = ee.ImageCollection("COPERNICUS/S2_CLOUD_PROBABILITY").filterBounds(area).filterDate(start, end)
        joined = ee.ImageCollection(ee.Join.saveFirst("cloud").apply(
            s2, probability, ee.Filter.equals(leftField="system:index", rightField="system:index")))
        chosen = joined.filter(ee.Filter.notNull(["cloud"])).randomColumn("r", f.get("seed")).sort("r").first()
        return f.set("scene", ee.Algorithms.If(chosen, ee.Image(chosen).get("system:index"), None))

    features = ee.FeatureCollection([ee.Feature(box(p), {"year": p["year"], "seed": p["seed"]}) for p in plans])
    return [f["properties"].get("scene") for f in features.map(pick).getInfo()["features"]]


def fetch(p: dict, lakes) -> dict:
    """The tile's pixels: the six bands, cloud probability, slope x 100, and the painted label."""
    image = ee.Image.cat(
        ee.Image(f"{watch.S2_L1C}/{p['scene']}").select(list(BANDS)).toUint16(),
        ee.Image(f"COPERNICUS/S2_CLOUD_PROBABILITY/{p['scene']}").select("probability").rename("cloud").toUint16(),
        watch.slope_deg().multiply(100).round().rename("slope_x100").toUint16(),
        ee.Image(0).paint(watch.inventory_collection(lakes), 1).rename("label").toUint16(),
    )
    data = ee.data.computePixels({
        "expression": image, "fileFormat": "NUMPY_NDARRAY",
        "grid": {"dimensions": {"width": SIZE, "height": SIZE},
                 "affineTransform": {"scaleX": CELL, "shearX": 0, "translateX": p["x0"],
                                     "shearY": 0, "scaleY": -CELL, "translateY": p["y_top"]},
                 "crsCode": f"EPSG:{p['epsg']}"}})
    return {name: data[name] for name in data.dtype.names}


def nearby(lakes_by_cell: dict, lon: float, lat: float, reach_deg: float = 0.05) -> list:
    """Lakes whose centre lies within reach_deg of a point, from a {(floor(lon*10), floor(lat*10)): lakes} index."""
    cx, cy = math.floor(lon * 10), math.floor(lat * 10)
    out = []
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            out += [lk for lk in lakes_by_cell.get((cx + dx, cy + dy), [])
                    if abs(lk.lon - lon) <= reach_deg and abs(lk.lat - lat) <= reach_deg]
    return out
