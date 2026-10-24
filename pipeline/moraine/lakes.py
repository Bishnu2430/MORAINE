"""Measure a glacial lake's water area in every Landsat and Sentinel-2 scene, on Google Earth Engine.

This module only builds Earth Engine requests; the pixel work runs on Google's servers and
only one small table per sensor comes back.
"""

from __future__ import annotations

from typing import Callable

import ee

# NDWI (green vs near-infrared) cut-offs. Open water sits well above 0; snow, ice and rock sit
# near or below it. 0.25 is the estimate; 0.15 and 0.35 show how much the answer depends on it.
THRESHOLDS = (0.15, 0.25, 0.35)

# Landsat Collection 2 Level-2: (sensor, collection, green band, near-infrared band)
LANDSAT = (
    ("Landsat 5", "LANDSAT/LT05/C02/T1_L2", "SR_B2", "SR_B4"),
    ("Landsat 7", "LANDSAT/LE07/C02/T1_L2", "SR_B2", "SR_B4"),
    ("Landsat 8", "LANDSAT/LC08/C02/T1_L2", "SR_B3", "SR_B5"),
    ("Landsat 9", "LANDSAT/LC09/C02/T1_L2", "SR_B3", "SR_B5"),
)
SENTINEL2 = ("Sentinel-2", "COPERNICUS/S2_SR_HARMONIZED", "B3", "B8")

# QA_PIXEL bits that make a Landsat pixel unusable: 0 fill, 1 dilated cloud, 3 cloud, 4 cloud shadow
LANDSAT_BAD_BITS = (1 << 0) | (1 << 1) | (1 << 3) | (1 << 4)
# Sentinel-2 scene classes that are unusable: no data, defective, cloud shadow, cloud (medium, high), cirrus
S2_BAD_CLASSES = (0, 1, 3, 8, 9, 10)

# Only autumn scenes are requested: after the monsoon cloud, before the lake freezes
SEASON_MONTHS = (9, 11)


def threshold_band(t: float) -> str:
    return f"water_t{round(t * 100):02d}_m2"


def lake_aoi(lon: float, lat: float, margin_m: float = 200, search_m: float = 400) -> ee.Geometry:
    """The lake's largest outline in JRC Global Surface Water (1984-2021), widened to allow for later growth."""
    seed = ee.Geometry.Point([lon, lat])
    max_extent = ee.Image("JRC/GSW1_4/GlobalSurfaceWater").select("max_extent")
    polygons = max_extent.selfMask().reduceToVectors(
        geometry=seed.buffer(5000),
        scale=30,
        geometryType="polygon",
        eightConnected=True,
        maxPixels=1e9,
    )
    near_seed = polygons.filterBounds(seed.buffer(search_m)).map(
        lambda f: f.set("area_m2", f.geometry().area(1))
    )
    if near_seed.size().getInfo() == 0:
        raise ValueError(
            f"No water within {search_m} m of ({lat}, {lon}) in JRC Global Surface Water. Check the lake coordinates."
        )
    lake = ee.Feature(near_seed.sort("area_m2", False).first()).geometry()
    return lake.buffer(margin_m, 1)


def _scene_stats(ndwi: ee.Image, valid: ee.Image, aoi: ee.Geometry, scale: int) -> ee.Dictionary:
    """Square metres of usable pixels, of the whole measuring area, and of water at each threshold."""
    pixel_area = ee.Image.pixelArea()
    bands = [valid.multiply(pixel_area).rename("valid_m2"), pixel_area.rename("aoi_m2")]
    for t in THRESHOLDS:
        water = ndwi.gt(t).unmask(0).And(valid)
        bands.append(water.multiply(pixel_area).rename(threshold_band(t)))
    return ee.Image.cat(bands).reduceRegion(ee.Reducer.sum(), aoi, scale, maxPixels=1e9)


def _landsat_scene(sensor: str, green: str, nir: str, aoi: ee.Geometry) -> Callable[[ee.Image], ee.Feature]:
    def per_image(img: ee.Image) -> ee.Feature:
        reflectance = img.select([green, nir]).multiply(0.0000275).add(-0.2)
        ndwi = reflectance.normalizedDifference([green, nir])
        clear = img.select("QA_PIXEL").bitwiseAnd(LANDSAT_BAD_BITS).eq(0)
        valid = clear.And(ndwi.mask()).unmask(0)
        return ee.Feature(None, _scene_stats(ndwi, valid, aoi, 30)).set(
            {"sensor": sensor, "scene": img.get("system:index"), "time_ms": img.get("system:time_start")}
        )

    return per_image


def _sentinel2_scene(aoi: ee.Geometry) -> Callable[[ee.Image], ee.Feature]:
    sensor, _, green, nir = SENTINEL2

    def per_image(img: ee.Image) -> ee.Feature:
        reflectance = img.select([green, nir]).divide(10000)
        ndwi = reflectance.normalizedDifference([green, nir])
        clear = img.select("SCL").remap(list(S2_BAD_CLASSES), [0] * len(S2_BAD_CLASSES), 1)
        valid = clear.And(ndwi.mask()).unmask(0)
        return ee.Feature(None, _scene_stats(ndwi, valid, aoi, 10)).set(
            {"sensor": sensor, "scene": img.get("system:index"), "time_ms": img.get("system:time_start")}
        )

    return per_image


def _autumn(collection_id: str, aoi: ee.Geometry, start: str, end: str) -> ee.ImageCollection:
    return (
        ee.ImageCollection(collection_id)
        .filterBounds(aoi)
        .filterDate(start, end)
        .filter(ee.Filter.calendarRange(SEASON_MONTHS[0], SEASON_MONTHS[1], "month"))
    )


def _rows(features: ee.FeatureCollection) -> list[dict]:
    return [f["properties"] for f in features.getInfo()["features"]]


def measure_scenes(
    aoi: ee.Geometry,
    start: str = "1984-01-01",
    end: str = "2027-01-01",
    progress: Callable[[str], None] = print,
) -> list[dict]:
    """One row per autumn scene: sensor, scene id, time, usable area, measuring area and water area per threshold."""
    rows: list[dict] = []
    for sensor, collection_id, green, nir in LANDSAT:
        scenes = _autumn(collection_id, aoi, start, end).map(_landsat_scene(sensor, green, nir, aoi))
        batch = _rows(scenes)
        progress(f"  {sensor}: {len(batch)} autumn scenes")
        rows += batch
    scenes = _autumn(SENTINEL2[1], aoi, max(start, "2017-01-01"), end).map(_sentinel2_scene(aoi))
    batch = _rows(scenes)
    progress(f"  {SENTINEL2[0]}: {len(batch)} autumn scenes")
    return rows + batch
