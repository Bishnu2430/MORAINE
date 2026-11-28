"""P1 step 7b: Landsat 8 scenes for the growth curves of 2013-2016.

Each scene's six reflective bands are renamed to the Sentinel-2 bands they match (blue B2, green B3,
red B4, near-infrared B8, shortwave B11 and B12) and scaled like Sentinel-2 Level-1C (reflectance x
10000), so the step 3 rule and the U-Net read them unchanged. Tiles are resampled bilinearly from 30 m
to the same 10 m grid as step 7a.

Landsat 4, 5 and 7 stay in SENSORS but are not used: the first three runs mapped 1988-2016 with them,
and they were dropped after the third (docs/p1/plan.md). On them the U-Net counts snow, glacier ice,
debris and dry lake bed as water; an open-water gate that removed those also removed frozen and silty
lake.

Flags per lake and scene, as in moraine/hard_cases.py but with a spectral cloud test:
- cloud: share of the lake that is thick cloud, bright in blue (TOA > 0.3) without snow's dark
  shortwave (NDSI < 0.4). Thin cloud passes, as in step 7a, and is left to tier 2 and the U-Net.
  Not the scene's own cloud mask (QA_PIXEL): it calls the cold, bright moraines and glaciers at
  5,000 m cloud and casts their "shadow" over the lakes. The median lake-scene came out 98-100%
  cloudy in every study area, and none of South Lhonak's 106 scenes of 1988-2022 under 18%, clear
  ones included
- shadow: share of the lake in terrain shadow cast by the scene's sun (GLO-30, ee.Terrain.hillShadow)
- ice: share that is snow or ice (NDSI > 0.4 and near-infrared > 0.2)
- covered: share of the lake the scene sees. Unlike hard_cases', cells off the scene, fill and
  Landsat 7's striped gaps (after May 2003) count as 0 here, not as missing
- cloud_near, covered_near: the same in the 1.3 km round the lake
"""

from __future__ import annotations

import math

import ee

from . import hard_cases, terrain, watch

SENSORS = {  # collection, then its blue, green, red, near-infrared, shortwave 1 and 2 bands
    "LT04": ("LANDSAT/LT04/C02/T1_TOA", ("B1", "B2", "B3", "B4", "B5", "B7")),
    "LT05": ("LANDSAT/LT05/C02/T1_TOA", ("B1", "B2", "B3", "B4", "B5", "B7")),
    "LE07": ("LANDSAT/LE07/C02/T1_TOA", ("B1", "B2", "B3", "B4", "B5", "B7")),
    "LC08": ("LANDSAT/LC08/C02/T1_TOA", ("B2", "B3", "B4", "B5", "B6", "B7")),
}
AS_S2 = ("B2", "B3", "B4", "B8", "B11", "B12")
USED = ("LC08",)  # the sensors 7b reads (Landsat 8); the others are kept for the record
YEARS = tuple(range(2013, 2017))
INVENTORY_YEARS = (2018, 2020, 2022)  # to choose the mapper and to join to step 7a
SEASON = ("09-01", "11-15")
SCENE_CLOUD = 80  # % scene cloud allowed; the flags judge each lake
SCALE = 30
MIN_KM2 = 0.05  # about 55 Landsat cells
FILL = 1  # QA_PIXEL bit 0: no data, including Landsat 7's stripes
CLOUD_BLUE = 0.3  # TOA blue reflectance above which ground that is not snow counts as thick cloud
SNOW_NDSI = 0.4


def sensor_of(scene: str) -> str:
    """"LT05" for "LANDSAT/LT05/C02/T1_TOA/LT05_140041_19901015": the collection, not the file name, since
    Landsat 8's collection also holds "LO08_..." scenes taken with only its optical instrument on."""
    return scene.split("/")[1]


def _renamed(bands: tuple[str, ...]):
    def rename(image):
        return image.select(list(bands) + ["QA_PIXEL"], list(AS_S2) + ["QA_PIXEL"]).set("scene", image.get("system:id"))
    return rename


def scenes(region: ee.Geometry, year: int, sensors: tuple[str, ...] = tuple(SENSORS)) -> ee.ImageCollection:
    """One autumn's scenes from the given sensors, bands renamed, each with property "scene" (its asset id)."""
    start, end = f"{year}-{SEASON[0]}", f"{year}-{SEASON[1]}T23:59:59"
    merged = None
    for name in sensors:
        collection, bands = SENSORS[name]
        part = (ee.ImageCollection(collection).filterBounds(region).filterDate(start, end)
                .filter(ee.Filter.lt("CLOUD_COVER", SCENE_CLOUD)).map(_renamed(bands)))
        merged = part if merged is None else merged.merge(part)
    return merged


def _covered(scene: ee.Image) -> ee.Image:
    seen = scene.select("B3").mask().And(scene.select("QA_PIXEL").bitwiseAnd(FILL).eq(0))
    return seen.unmask(0)  # off the scene: 0, not masked, so a mean counts it


def _cloud(scene: ee.Image) -> ee.Image:
    ndsi = scene.normalizedDifference(["B3", "B11"])
    return scene.select("B2").gt(CLOUD_BLUE).And(ndsi.lt(SNOW_NDSI))


def conditions(scene: ee.Image) -> ee.Image:
    """The per-pixel inputs to the flags for one scene (see the module docstring)."""
    dem = ee.ImageCollection(terrain.GLO30).select("DEM").mosaic().reproject(crs="EPSG:32645", scale=30)
    zenith = ee.Number(90).subtract(scene.get("SUN_ELEVATION"))
    lit = ee.Terrain.hillShadow(dem, scene.get("SUN_AZIMUTH"), zenith, hard_cases.SHADOW_REACH_PX, True)
    ndsi = scene.normalizedDifference(["B3", "B11"])
    return ee.Image.cat(
        _cloud(scene).rename("cloud"),
        lit.Not().rename("shadow"),
        ndsi.gt(SNOW_NDSI).And(scene.select("B8").gt(0.2)).rename("ice"),
        _covered(scene).rename("covered"),
    )


def neighbourhood(scene: ee.Image) -> ee.Image:
    """Cloudy and covered ground, for the neighbourhood round each lake."""
    return ee.Image.cat(_cloud(scene).rename("cloud_near"), _covered(scene).rename("covered_near"))


def measure(lakes, scene_ids: list[str], region: ee.Geometry, year: int, sensors: tuple[str, ...]) -> list[dict]:
    """Flag inputs for every lake fully inside each of the given scenes: one dict per lake and scene."""
    collection = watch.inventory_collection(lakes)
    around = collection.map(lambda f: f.buffer(hard_cases.NEAR_M, 20))
    chosen = scenes(region, year, sensors).filter(ee.Filter.inList("scene", scene_ids))

    def per_scene(scene):
        scene = ee.Image(scene)
        inside = conditions(scene).reduceRegions(collection=collection, reducer=ee.Reducer.mean(), scale=SCALE,
                                                 tileScale=4).filter(ee.Filter.gte("covered", 0.999))
        near = neighbourhood(scene).reduceRegions(collection=around, reducer=ee.Reducer.mean(), scale=SCALE,
                                                  tileScale=4)
        both = ee.Join.saveFirst("near").apply(inside, near, ee.Filter.equals(leftField="id", rightField="id"))
        return both.map(lambda f: ee.Feature(None, f.toDictionary().remove(["near"]).combine(
            ee.Feature(f.get("near")).toDictionary(["cloud_near", "covered_near"]))).set(
            "scene", scene.get("scene"), "date", scene.date().format("YYYY-MM-dd")))

    rows = ee.FeatureCollection(chosen.map(per_scene)).flatten().getInfo()["features"]
    return [{"year": year, **r["properties"]} for r in rows]


def tile_bands(scene: str) -> ee.Image:
    """The scene's six bands as Sentinel-2 Level-1C numbers, resampled bilinearly for a 10 m grid."""
    _, bands = SENSORS[sensor_of(scene)]
    image = ee.Image(scene).resample("bilinear").select(list(bands), list(AS_S2))
    return image.multiply(10000).round().toUint16()


# --- Decisions on the results (no Earth Engine) -----------------------------------------------------

def choose_mapper(ratios: dict[str, list[float]]) -> tuple[str, dict[str, float]]:
    """The mapper whose mapped / listed area ratios have the smallest median |log ratio|, with every
    mapper's score. A ratio of 0 (lake missed) scores as log(0.01)."""
    def score(values):
        logs = sorted(abs(math.log(max(v, 0.01))) for v in values)
        n = len(logs)
        return logs[n // 2] if n % 2 else (logs[n // 2 - 1] + logs[n // 2]) / 2
    scores = {name: score(values) for name, values in ratios.items()}
    return min(scores, key=lambda name: (scores[name], name)), scores
