"""P1 step 4: flag hard conditions per inventory lake and Sentinel-2 scene.

A case is one lake in one scene. Two places are measured: the neighbourhood (1.3 km round the lake,
about the size of its tile), for the share of cloudy ground (cloud_near) and of ground the scene
covers (covered_near); and the lake's inventory outline itself:

- cloud: mean s2cloudless probability (COPERNICUS/S2_CLOUD_PROBABILITY, joined by scene)
- cirrus: mean B10 top-of-atmosphere reflectance. Recorded but not used: at 5,000 m there is too
  little water vapour above the ground to absorb this band, so it sees the ground (median 0.016 even
  in near-clear scenes)
- shadow: share in terrain shadow cast by the scene's sun (GLO-30 at 30 m, ee.Terrain.hillShadow)
- ice: share that is snow or ice (NDSI > 0.4 and bright in near-infrared, B8 > 0.2). Turbid water
  also has a high NDSI, but is dark in near-infrared.
- red, nir: mean B4 and B8 reflectance; silt makes water bright in both

The flags never look at any lake map or at how much water a method finds, so the cases are not
chosen for being hard for one particular method.

Scenes come from the inventory years only (2018, 2020, 2022), 1 September to 31 December, so the
year's inventory outline is the label; the extra six weeks past the mapping season bring frozen lakes.
"""

from __future__ import annotations

import hashlib

import ee

from . import terrain, watch

SEASON = ("09-01", "12-31")
SCENE_CLOUD = 80  # % scene cloud allowed; thin-cloud cases come from the cloudier scenes
SHADOW_REACH_PX = 150  # 4.5 km at 30 m, longer than any ridge shadow at a December noon here
NEAR_M = 1300  # neighbourhood round each lake: about half a 2.56 km tile
CLOUDY = 40  # s2cloudless probability (%) above which a neighbourhood pixel counts as cloudy


def scenes(region: ee.Geometry, year: int) -> ee.ImageCollection:
    """Level-1C scenes of one autumn, each carrying its cloud-probability image as property "cloud"."""
    start, end = f"{year}-{SEASON[0]}", f"{year}-{SEASON[1]}T23:59:59"
    s2 = (ee.ImageCollection(watch.S2_L1C).filterBounds(region).filterDate(start, end)
          .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", SCENE_CLOUD)))
    probability = ee.ImageCollection("COPERNICUS/S2_CLOUD_PROBABILITY").filterBounds(region).filterDate(start, end)
    match = ee.Filter.equals(leftField="system:index", rightField="system:index")
    return ee.ImageCollection(ee.Join.saveFirst("cloud").apply(s2, probability, match))


def conditions(scene: ee.Image) -> ee.Image:
    """The per-pixel inputs to the flags for one scene (see the module docstring)."""
    dem = ee.ImageCollection(terrain.GLO30).select("DEM").mosaic().reproject(crs="EPSG:32645", scale=30)
    lit = ee.Terrain.hillShadow(dem, scene.get("MEAN_SOLAR_AZIMUTH_ANGLE"), scene.get("MEAN_SOLAR_ZENITH_ANGLE"),
                                SHADOW_REACH_PX, True)
    toa = scene.select(["B3", "B4", "B8", "B10", "B11"]).divide(10000)
    ndsi = toa.normalizedDifference(["B3", "B11"])
    return ee.Image.cat(
        ee.Image(scene.get("cloud")).select("probability").divide(100).rename("cloud"),
        toa.select("B10").rename("cirrus"),
        lit.Not().rename("shadow"),
        ndsi.gt(0.4).And(toa.select("B8").gt(0.2)).rename("ice"),
        toa.select("B4").rename("red"),
        toa.select("B8").rename("nir"),
        scene.select("B3").gt(0).rename("covered"),
    )


def neighbourhood(scene: ee.Image) -> ee.Image:
    """Cloudy and covered ground, for the neighbourhood round each lake."""
    cloud = ee.Image(scene.get("cloud")).select("probability")
    return ee.Image.cat(cloud.gt(CLOUDY).rename("cloud_near"), scene.select("B2").gt(0).rename("covered_near"))


def measure(lakes, scene_ids: list[str], region: ee.Geometry, year: int) -> list[dict]:
    """Flag inputs for every lake fully inside each of the given scenes: one dict per lake and scene."""
    collection = watch.inventory_collection(lakes)
    around = collection.map(lambda f: f.buffer(NEAR_M, 20))
    chosen = scenes(region, year).filter(ee.Filter.inList("system:index", scene_ids))

    def per_scene(scene):
        scene = ee.Image(scene)
        inside = conditions(scene).reduceRegions(collection=collection, reducer=ee.Reducer.mean(), scale=watch.SCALE,
                                                 tileScale=4).filter(ee.Filter.gte("covered", 0.999))
        near = neighbourhood(scene).reduceRegions(collection=around, reducer=ee.Reducer.mean(), scale=20, tileScale=4)
        both = ee.Join.saveFirst("near").apply(inside, near, ee.Filter.equals(leftField="id", rightField="id"))
        return both.map(lambda f: ee.Feature(None, f.toDictionary().remove(["near"]).combine(
            ee.Feature(f.get("near")).toDictionary(["cloud_near", "covered_near"]))).set(
            "scene", scene.get("system:index"), "date", scene.date().format("YYYY-MM-dd"),
            "tile", scene.get("MGRS_TILE"), "sun_zenith", scene.get("MEAN_SOLAR_ZENITH_ANGLE")))

    rows = ee.FeatureCollection(chosen.map(per_scene)).flatten().getInfo()["features"]
    return [{"year": year, **r["properties"]} for r in rows]


# --- Choosing cases ---------------------------------------------------------------------------------

FIELDS = ("cloud", "shadow", "ice", "red", "nir", "cloud_near", "covered_near")


def clear_sky(r: dict) -> bool:
    """Lake and its surroundings free of cloud, ice and shadow."""
    return r["cloud"] < 0.1 and r["cloud_near"] < 0.05 and r["ice"] < 0.05 and r["shadow"] < 0.1


# Each category: (test on one lake-scene, how strongly it shows the condition). The cloud-probability
# layer reads some snow and ice as cloud, so the ice test allows more of it; the visual check removes
# real cloud. "red_rise" is how much brighter in red the lake is than on its own clear days that year.
CATEGORIES = {
    # partly frozen lakes first: a lake wholly under snow cannot be seen by any method
    "ice": (lambda r: r["ice"] >= 0.3 and r["cloud"] < 0.5 and r["cloud_near"] < 0.5,
            lambda r: -abs(r["ice"] - 0.65)),
    "shadow": (lambda r: r["shadow"] >= 0.2 and r["cloud"] < 0.3 and r["cloud_near"] < 0.2 and r["ice"] < 0.3,
               lambda r: r["shadow"]),
    # veiled but see-through: brighter than on clear days, not white
    "thin_cloud": (lambda r: r["cloud"] >= 0.3 and r.get("red_rise") is not None and 0.03 <= r["red_rise"] <= 0.25
                   and r["ice"] < 0.1 and r["shadow"] < 0.2, lambda r: -abs(r["red_rise"] - 0.12)),
    # silt raises near-infrared, which pushes the water index under its cut-off; clear surroundings so
    # the rise is not haze
    "silty": (lambda r: r["nir"] >= 0.09 and r["red"] >= 0.12 and clear_sky(r) and r["ice"] < 0.02,
              lambda r: r["nir"]),
    "clear": (lambda r: clear_sky(r) and r["cloud_near"] < 0.01 and r["shadow"] < 0.02 and r["ice"] < 0.02
              and r["nir"] < 0.06, lambda r: -r["cloud_near"]),
}


def shuffle_key(r: dict) -> str:
    """A reproducible pseudo-random tie-break, so ties do not all fall on one date."""
    return hashlib.md5(f"{r['year']}-{r['id']}-{r['date']}".encode()).hexdigest()


def choose(rows: list[dict], same_lake: dict, per_category: int) -> dict[str, list[dict]]:
    """Up to per_category lake-scenes per category, the strongest first, one per physical lake; a
    category that runs short takes the same lake again in another year.

    `same_lake` maps (year, index in that year's file) to the lake's index in the 2022 file, so a lake
    counts once however many years it is flagged in. Only scenes covering the lake's whole
    neighbourhood are used."""
    usable, seen = [], set()
    for r in sorted(rows, key=lambda r: (r["date"], r["id"])):
        key = (r["year"], r["id"], r["date"])  # the same day twice comes from overlapping tiles
        if key in seen or any(r.get(f) is None for f in FIELDS) or r["covered_near"] < 0.999:
            continue
        seen.add(key)
        usable.append(dict(r))
    reference: dict[tuple, list[float]] = {}
    for r in usable:
        if clear_sky(r):
            reference.setdefault((r["year"], r["id"]), []).append(r["red"])
    for r in usable:
        clear = sorted(reference.get((r["year"], r["id"]), []))
        r["red_rise"] = r["red"] - clear[len(clear) // 2] if clear else None
    chosen = {}
    for name, (test, strength) in CATEGORIES.items():
        ranked = sorted((r for r in usable if test(r)), key=lambda r: (-strength(r), shuffle_key(r)))
        picked, lakes, lake_years = [], set(), set()
        for second_pass in (False, True):  # first one case per lake, then one per lake and year
            for r in ranked:
                lake = same_lake.get((r["year"], r["id"]), (r["year"], r["id"]))
                if len(picked) == per_category or (lake, r["year"]) in lake_years or (lake in lakes and not second_pass):
                    continue
                lakes.add(lake)
                lake_years.add((lake, r["year"]))
                picked.append(r)
        chosen[name] = picked
    return chosen


# --- Tiles ------------------------------------------------------------------------------------------

def tile_image(scene_id: str, lakes, lake) -> ee.Image:
    """The bands of one case tile (see moraine/tiles.py); `lakes` are that year's lakes near the tile."""
    s2 = ee.Image(f"{watch.S2_L1C}/{scene_id}").select(["B2", "B3", "B4", "B8", "B11", "B12"]).toUint16()
    cloud = ee.Image(f"COPERNICUS/S2_CLOUD_PROBABILITY/{scene_id}").select("probability").rename("cloud").toUint16()
    slope = watch.slope_deg().multiply(100).round().rename("slope_x100").toUint16()
    label = ee.Image(0).paint(watch.inventory_collection(lakes), 1).rename("label").toUint16()
    own = ee.Image(0).paint(watch.inventory_collection([lake]), 1).rename("lake").toUint16()
    return ee.Image.cat(s2, cloud, slope, label, own)


def fetch_tile(image: ee.Image, x0: float, y_top: float, size: int, cell: float) -> dict:
    """computePixels of a tile on the UTM 45N grid whose top-left corner is (x0, y_top)."""
    data = ee.data.computePixels({
        "expression": image,
        "fileFormat": "NUMPY_NDARRAY",
        "grid": {"dimensions": {"width": size, "height": size},
                 "affineTransform": {"scaleX": cell, "shearX": 0, "translateX": x0,
                                     "shearY": 0, "scaleY": -cell, "translateY": y_top},
                 "crsCode": "EPSG:32645"},
    })
    return {name: data[name] for name in data.dtype.names}
