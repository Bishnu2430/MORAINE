"""Measure a glacial lake's water area each autumn from Landsat and Sentinel-2, on Google Earth Engine.

The cloud masks shipped with Landsat label dark lake water as cloud shadow and silty water as
cloud, so per-pixel masks are not used. Instead each period gets a per-pixel percentile
composite of NDWI (green vs near-infrared). Clouds, ice and snow only ever lower NDWI, so a
pixel's 80th-percentile value is its clear-water state whenever it was clear in at least a
fifth of the period's scenes. This also fills the striped gaps in Landsat 7 after 2003.

This module only builds Earth Engine requests; the pixel work runs on Google's servers.
"""

from __future__ import annotations

from typing import Callable

import ee

# NDWI cut-offs. 0.25 is the estimate; 0.15 and 0.35 show how much the answer depends on it.
THRESHOLDS = (0.15, 0.25, 0.35)
PERCENTILE = 80
# A pixel counts as covered in a period only if this many scenes saw it
MIN_OBSERVATIONS = 3

# Landsat Collection 2 Level-2: (collection, green band, near-infrared band)
LANDSAT = (
    ("LANDSAT/LT05/C02/T1_L2", "SR_B2", "SR_B4"),
    ("LANDSAT/LE07/C02/T1_L2", "SR_B2", "SR_B4"),
    ("LANDSAT/LC08/C02/T1_L2", "SR_B3", "SR_B5"),
    ("LANDSAT/LC09/C02/T1_L2", "SR_B3", "SR_B5"),
)
SENTINEL2 = ("COPERNICUS/S2_SR_HARMONIZED", "B3", "B8")
SCALE = {"Landsat": 30, "Sentinel-2": 10}
FAMILIES = ("Landsat", "Sentinel-2")
SENTINEL2_START = "2017-01-01"


def threshold_band(t: float) -> str:
    return f"water_t{round(t * 100):02d}_m2"


def _landsat_ndwi(green: str, nir: str) -> Callable[[ee.Image], ee.Image]:
    def per_image(img: ee.Image) -> ee.Image:
        reflectance = img.select([green, nir]).multiply(0.0000275).add(-0.2)
        has_data = img.select("QA_PIXEL").bitwiseAnd(1).eq(0)  # bit 0: fill
        ndwi = reflectance.normalizedDifference([green, nir]).updateMask(has_data).rename("ndwi")
        return ee.Image(ndwi.copyProperties(img, ["system:time_start"]))

    return per_image


def _sentinel2_ndwi(img: ee.Image) -> ee.Image:
    _, green, nir = SENTINEL2
    reflectance = img.select([green, nir]).divide(10000)
    has_data = img.select("SCL").neq(0)  # class 0: no data
    ndwi = reflectance.normalizedDifference([green, nir]).updateMask(has_data).rename("ndwi")
    return ee.Image(ndwi.copyProperties(img, ["system:time_start"]))


def ndwi_scenes(family: str, region: ee.Geometry, start, end) -> ee.ImageCollection:
    """Every scene of one sensor family touching the region between start (inclusive) and end (exclusive)."""
    if family == "Sentinel-2":
        return ee.ImageCollection(SENTINEL2[0]).filterBounds(region).filterDate(start, end).map(_sentinel2_ndwi)
    merged = None
    for collection_id, green, nir in LANDSAT:
        scenes = ee.ImageCollection(collection_id).filterBounds(region).filterDate(start, end)
        scenes = scenes.map(_landsat_ndwi(green, nir))
        merged = scenes if merged is None else merged.merge(scenes)
    return merged


def _largest_near(polygons: ee.FeatureCollection, seed: ee.Geometry, search_m: float, what: str) -> ee.Geometry:
    near = polygons.filterBounds(seed.buffer(search_m)).map(lambda f: f.set("area_m2", f.geometry().area(1)))
    if near.size().getInfo() == 0:
        raise ValueError(f"No water within {search_m} m of the lake point in {what}. Check the lake coordinates.")
    return ee.Feature(near.sort("area_m2", False).first()).geometry()


def lake_aoi(lon: float, lat: float, margin_m: float = 100, search_m: float = 400,
             recent_years: list[int] | None = None) -> ee.Geometry:
    """The lake's largest outline, widened by a margin.

    Starts from JRC Global Surface Water (1984-2021). If recent_years is given, adds the largest
    Sentinel-2 outline of those autumns, for lakes that kept growing after 2021.
    """
    seed = ee.Geometry.Point([lon, lat])
    region = seed.buffer(5000)
    vectors = {"geometry": region, "geometryType": "polygon", "eightConnected": True, "maxPixels": 1e10}

    jrc = ee.Image("JRC/GSW1_4/GlobalSurfaceWater").select("max_extent").selfMask()
    lake = _largest_near(jrc.reduceToVectors(scale=30, **vectors), seed, search_m, "JRC Global Surface Water")

    if recent_years:
        yearly = [
            ndwi_scenes("Sentinel-2", region, f"{y}-09-01", f"{y}-11-16").reduce(ee.Reducer.percentile([PERCENTILE]))
            for y in recent_years
        ]
        extent = ee.ImageCollection(yearly).max().gt(0.25).selfMask()
        recent = _largest_near(extent.reduceToVectors(scale=10, **vectors), seed, search_m, "recent Sentinel-2 autumns")
        lake = lake.union(recent, 1)
    return lake.buffer(margin_m, 1)


def _period_feature(family: str, aoi: ee.Geometry, period: dict) -> ee.Feature:
    scenes = ndwi_scenes(family, aoi, period["start"], period["end"])
    composite = scenes.reduce(ee.Reducer.percentile([PERCENTILE])).rename("ndwi")
    covered = scenes.count().rename("n").gte(MIN_OBSERVATIONS)
    pixel_area = ee.Image.pixelArea()
    bands = [covered.unmask(0).multiply(pixel_area).rename("covered_m2"), pixel_area.rename("aoi_m2")]
    for t in THRESHOLDS:
        water = composite.gt(t).And(covered).unmask(0)
        bands.append(water.multiply(pixel_area).rename(threshold_band(t)))
    measured = ee.Feature(None, ee.Image.cat(bands).reduceRegion(ee.Reducer.sum(), aoi, SCALE[family], maxPixels=1e9))
    empty = ee.Feature(None, {"covered_m2": 0, "aoi_m2": 0, **{threshold_band(t): 0 for t in THRESHOLDS}})
    return ee.Feature(ee.Algorithms.If(scenes.size().gt(0), measured, empty)).set(
        {"family": family, "period": period["period"], "start": period["start"], "end": period["end"],
         "scenes": scenes.size()}
    )


def measure_periods(aoi: ee.Geometry, periods: list[dict], progress: Callable[[str], None] = print) -> list[dict]:
    """One row per sensor family per period: scene count, covered area, measuring area, water area per threshold."""
    rows: list[dict] = []
    for family in FAMILIES:
        usable = [p for p in periods if family != "Sentinel-2" or p["end"] > SENTINEL2_START]
        features = ee.FeatureCollection([_period_feature(family, aoi, p) for p in usable])
        batch = [f["properties"] for f in features.getInfo()["features"]]
        progress(f"  {family}: {len(batch)} periods, {sum(r['scenes'] for r in batch)} scenes")
        rows += batch
    return rows
