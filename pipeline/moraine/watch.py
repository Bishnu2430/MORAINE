"""P1 Watch: map lakes from Sentinel-2 autumn composites, and score maps against the inventory.

The baseline is the classic rule-based method: a per-pixel 80th-percentile autumn composite of the
water index (NDWI, green against near-infrared) above a cut-off, on flat ground (GLO-30 slope), with
an optional second rule on the infrared water index (MNDWI, green against shortwave infrared).
Sentinel-2 Level-1C (top of atmosphere) is used for every year, because the surface-reflectance
product has almost no scenes over these valleys before late 2018.

Scoring is per inventory lake: overlap (IoU) and area error inside a 60 m buffer round its outline,
plus the mapped water lying away from every inventory lake.

Every sum runs on the 10 m grid: a whole-study-area request at 30 m loses water (see outside()).
"""

from __future__ import annotations

import ee

from . import terrain

S2_L1C = "COPERNICUS/S2_HARMONIZED"
SEASON = ("09-01", "11-16")
SCENE_CLOUD = 60  # % scene cloud allowed into a composite; the percentile copes with the rest
MIN_OBSERVATIONS = 3
NDWI_CUT = 0.25
MNDWI_CUT = 0.10
MAX_SLOPE_DEG = 12
MIN_LAKE_PIXELS = 200  # 0.02 km2 at 10 m
SCALE = 10
VARIANTS = {"ndwi": "NDWI > 0.25 on slopes under 12°", "ndwi_mndwi": "and MNDWI > 0.10"}


def composite(region: ee.Geometry, year: int) -> ee.Image:
    """80th-percentile NDWI and MNDWI over one autumn, and how many scenes saw each pixel."""
    scenes = (ee.ImageCollection(S2_L1C).filterBounds(region)
              .filterDate(f"{year}-{SEASON[0]}", f"{year}-{SEASON[1]}")
              .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", SCENE_CLOUD)))

    def indices(img):
        valid = img.select("B3").gt(0)
        ndwi = img.normalizedDifference(["B3", "B8"]).rename("ndwi")
        mndwi = img.normalizedDifference(["B3", "B11"]).rename("mndwi")
        return ndwi.addBands(mndwi).updateMask(valid)

    stack = scenes.map(indices)
    p80 = stack.reduce(ee.Reducer.percentile([80])).rename(["ndwi", "mndwi"])
    count = stack.select("ndwi").count().rename("count")
    return p80.addBands(count).set("scenes", scenes.size())


def slope_deg() -> ee.Image:
    dem = ee.ImageCollection(terrain.GLO30).select("DEM")
    return ee.Terrain.slope(dem.mosaic().setDefaultProjection(dem.first().projection()))


def water(image: ee.Image, variant: str) -> ee.Image:
    """1 where the baseline calls water, 0 elsewhere, masked where too few scenes saw the pixel."""
    rule = image.select("ndwi").gt(NDWI_CUT).And(slope_deg().lt(MAX_SLOPE_DEG))
    if variant == "ndwi_mndwi":
        rule = rule.And(image.select("mndwi").gt(MNDWI_CUT))
    return rule.rename("water").updateMask(image.select("count").gte(MIN_OBSERVATIONS))


def lakes_only(mask: ee.Image) -> ee.Image:
    """Keep water patches of at least 0.02 km2 (MIN_LAKE_PIXELS of 10 m).

    The patch size is counted on a fixed 10 m grid (UTM 45N, which covers all three study areas), so
    the 0.02 km2 rule holds whatever scale a later step asks for. Without this, a request at 30 m
    counted 30 m pixels and kept only patches of 0.18 km2 or more."""
    fixed = mask.reproject(crs="EPSG:32645", scale=SCALE)
    size = fixed.selfMask().connectedPixelCount(MIN_LAKE_PIXELS + 1, True)
    # Stays masked where too few scenes saw the ground, so scoring can tell "not seen" from "dry"
    return fixed.And(size.gte(MIN_LAKE_PIXELS).unmask(0)).rename("water")


def inventory_collection(lakes) -> ee.FeatureCollection:
    """Inventory lakes (moraine.inventory.Lake) as an Earth Engine collection, one feature per lake."""
    features = []
    for lake in lakes:
        geometry = ee.Geometry.Polygon([[list(p) for p in ring] for ring in lake.rings], None, False)
        # "index" is the lake's position in the inventory files, the same in every year's file
        features.append(ee.Feature(geometry, {"id": int(lake.attrs["index"]), "listed_km2": float(lake.area_km2)}))
    return ee.FeatureCollection(features)


def score(mapped: ee.Image, lakes, buffer_m: float = 60) -> list[dict]:
    """Per inventory lake: its area, the mapped water inside its buffered outline, and the overlap."""
    collection = inventory_collection(lakes)
    truth = ee.Image(0).byte().paint(collection, 1).rename("truth")
    area = ee.Image.pixelArea()
    stack = ee.Image.cat(
        truth.multiply(area).rename("truth_m2"),
        mapped.unmask(0).multiply(area).rename("mapped_m2"),
        truth.And(mapped.unmask(0)).multiply(area).rename("both_m2"),
        mapped.mask().multiply(area).rename("seen_m2"),
        area.rename("all_m2"),
    )
    buffered = collection.map(lambda f: f.buffer(buffer_m, 5))
    rows = stack.reduceRegions(collection=buffered, reducer=ee.Reducer.sum(), scale=SCALE, tileScale=4).getInfo()
    out = []
    for f in rows["features"]:
        p = f["properties"]
        union = p["truth_m2"] + p["mapped_m2"] - p["both_m2"]
        out.append({"id": p["id"], "truth_km2": p["truth_m2"] / 1e6, "mapped_km2": p["mapped_m2"] / 1e6,
                    "iou": p["both_m2"] / union if union > 0 else 0.0,
                    "seen_share": p["seen_m2"] / p["all_m2"] if p["all_m2"] else 0.0})
    return out


def outside(mapped: ee.Image, region: ee.Geometry, lakes, buffer_m: float = 60) -> float:
    """Mapped water (km2) farther than buffer_m from every inventory outline.

    Part of it is error (shadow, wet ground, spill beyond a lake's edge) and part is real lakes the
    inventory leaves out, as it lists only glacial lakes within 10 km of a glacier; so it is reported, not
    scored as false. Summed on the 10 m grid: counting extra lakes as vectors at 30 m lost water over a
    whole study area (Sikkim 2022: 13.4 km2 mapped at 30 m against 21.7 km2 at 10 m), and vectors or a
    second patch-size pass at 10 m exceed Earth Engine's 5-minute limit for interactive requests."""
    near = ee.Image(0).byte().paint(inventory_collection(lakes).map(lambda f: f.buffer(buffer_m, 5)), 1)
    lone = mapped.unmask(0).And(near.Not()).multiply(ee.Image.pixelArea()).rename("lone")
    return lone.reduceRegion(ee.Reducer.sum(), region, SCALE, maxPixels=1e10, tileScale=4).getInfo()["lone"] / 1e6


def total_area(mapped: ee.Image, region: ee.Geometry) -> dict:
    """Mapped lake area (km2) inside the region, and the share of the region seen by enough scenes."""
    area = ee.Image.pixelArea()
    stats = ee.Image.cat(mapped.unmask(0).multiply(area).rename("water"), mapped.mask().multiply(area).rename("seen"),
                         area.rename("all")).reduceRegion(ee.Reducer.sum(), region, SCALE, maxPixels=1e10,
                                                          tileScale=4).getInfo()
    return {"km2": stats["water"] / 1e6, "seen_share": stats["seen"] / stats["all"]}
