"""The three test events and the Earth Engine checks behind their one-page data checks (P0).

Facts are from the sources named in each entry; coordinates were checked against them on
26 Nov 2026. South Lhonak, the pilot, is covered by the lake-area and terrain spikes.
"""

from __future__ import annotations

from datetime import datetime, timezone

import ee

from . import lakes, terrain

EVENTS = {
    "gongbatongsha": {
        "name": "Gongbatongsha 2016",
        "date": "2016-07-05",
        "when": "night of 5 July 2016; flood front passed the Nepal seismometers about 15:15-15:40 UTC",
        "lake": {"name": "Gongbatongsha lake", "lon": 86.0700, "lat": 28.0781},  # 28°04'41"N 86°04'12"E, 4,623 m
        "places": [],
        # Decided 26 Nov 2026: the first 6.5 km were a debris flow, beyond a water-only solver, so the run
        # starts at the Zhangzangbo-Poiqu confluence, fed with Sattar et al.'s (2022) modelled flow there,
        # and is scored in Nepal against the seismic record (Cook et al. 2018)
        # (found as the biggest jump in upstream area within 15 km of the lake)
        "run_start": {"name": "Run starts: confluence", "search_km": 15.0},
        "length_km": 52.0,  # 6.5 km to the Zhangzangbo-Poiqu confluence, then about 45 km to Barabise
        "half_width_m": 3000.0,
        "crs": "EPSG:32645",
        "search": (85.80, 27.70, 86.15, 28.15),
        "lake_method": "documented",
        "lake_note": "Too small to measure: at the lake, Landsat's best autumn water index is 0.17-0.21, under "
                     "the 0.25 cut-off, and Sentinel-2 Level-1C counts snow as water (about 0.075 km2 both before "
                     "and after a lake of 0.017 km2 that drained). The published size is used.",
        "rain": ("2016-06-29", "2016-07-06"),
        "published": [
            "Lake 1.7 x 10^4 m2 before, fully drained; about 1.1-1.2 x 10^5 m3 of water (Cook 2018; Sattar 2022)",
            "Peak about 620 m3/s at the lake, about 4,100 m3/s at the confluence 6.5 km down after entraining "
            "about 8.3 x 10^6 m3 of debris (Sattar 2022)",
            "Front at 8.7 m/s past four seismometers 21-29 km along the river; 1,500-2,100 m3/s at Chaku "
            "(Cook 2018)",
        ],
    },
    "thame": {
        "name": "Thame 2024",
        "date": "2024-08-16",
        "when": "16 August 2024; lake about 0.05 km2 at 10:46 NPT, breach about 13:25 NPT (ICIMOD)",
        "lake": None,  # no published coordinates: found as the lake that drained, upstream of Thame
        "lake_search": (86.54, 27.81, 86.65, 27.91),  # the breached lower lake is at about 27.828 N
        "places": [{"name": "Thame", "lon": 86.650, "lat": 27.831}],
        "length_km": 20.0,
        "half_width_m": 3000.0,
        "crs": "EPSG:32645",
        "search": (86.50, 27.75, 86.80, 27.95),
        "lake_method": "drained",
        "rain": ("2024-08-09", "2024-08-17"),
        "published": [
            "Thyanbo lake, about 0.05 km2 on the morning of 16 Aug 2024 (ICIMOD 2024)",
            "156,000 m3 from the first lake and 303,000 m3 from the second, 459,000 m3 in all (ICIMOD 2025)",
            "25 homes destroyed, 135 people displaced, no deaths; school, health post, bridge and a "
            "hydropower plant damaged (ICIMOD 2025)",
        ],
    },
    "kedarnath": {
        "name": "Kedarnath 2013",
        "date": "2013-06-17",
        "when": "rain 10-17 June 2013; Chorabari lake breached on the morning of 17 June",
        "lake": {"name": "Chorabari lake", "lon": 79.0608, "lat": 30.7475},
        "places": [{"name": "Kedarnath", "lon": 79.0669, "lat": 30.7352}],
        "length_km": 20.0,
        "half_width_m": 3000.0,
        "crs": "EPSG:32644",
        "search": (78.90, 30.55, 79.15, 30.80),
        "lake_method": "documented",
        "lake_note": "Too small, silty and shaded for 30 m Landsat (P0 lake spike); Sentinel-2 did not exist yet. "
                     "The documented size and volume are used.",
        "rain": ("2013-06-10", "2013-06-18"),
        "published": [
            "Lake about 400 x 200 m, 15-20 m deep, about 262,000 m3; emptied within minutes (documented)",
            "About 390 mm of rain over 10-17 June after weeks of fast snowmelt (Allen 2016; Singh 2015)",
            "Modelled breach peak about 1,700 m3/s (Journal of Mountain Science study)",
        ],
    },
}

CLEAR_SCENE_CLOUD = 20  # % scene cloud cover counted as clear
IMAGERY_WINDOW_DAYS = 120


def drained_lake(box, before: tuple[str, str], after: tuple[str, str], threshold: float = 0.25) -> dict:
    """The water body in `box` that lost the most area between two Sentinel-2 composites."""
    region = ee.Geometry.Rectangle(list(box))

    def water(period):
        scenes = lakes.ndwi_scenes("Sentinel-2", region, *period)
        return scenes.reduce(ee.Reducer.percentile([lakes.PERCENTILE])).gt(threshold).rename("water")

    was, now = water(before), water(after)
    polygons = was.selfMask().reduceToVectors(geometry=region, scale=10, geometryType="polygon",
                                              eightConnected=True, maxPixels=1e9, bestEffort=False)
    area = ee.Image.pixelArea()

    def measure(feature):
        geometry = feature.geometry()
        sums = ee.Image.cat(was.multiply(area).rename("before"), now.multiply(area).rename("after")).reduceRegion(
            ee.Reducer.sum(), geometry, 10, maxPixels=1e9)
        centroid = geometry.centroid(1).coordinates()
        return feature.set({"before_m2": sums.get("before"), "after_m2": sums.get("after"),
                            "lon": centroid.get(0), "lat": centroid.get(1)})

    measured = polygons.filter(ee.Filter.gte("count", 20)).map(measure)
    lost = measured.map(lambda f: f.set("lost_m2", ee.Number(f.get("before_m2")).subtract(f.get("after_m2"))))
    best = ee.Feature(lost.sort("lost_m2", False).first())
    info = best.getInfo()
    props = info["properties"]
    return {"lon": props["lon"], "lat": props["lat"], "before_m2": props["before_m2"], "after_m2": props["after_m2"],
            "geometry": ee.Geometry(info["geometry"])}


def clear_scenes(region: ee.Geometry, date: str, days: int = IMAGERY_WINDOW_DAYS) -> dict:
    """Clear Sentinel-2 and Landsat scenes over `region` in the `days` before and after `date`."""
    day = ee.Date(date)
    sources = {
        "Sentinel-2": (ee.ImageCollection("COPERNICUS/S2_HARMONIZED"), "CLOUDY_PIXEL_PERCENTAGE"),
        "Landsat": (ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
                    .merge(ee.ImageCollection("LANDSAT/LC09/C02/T1_L2"))
                    .merge(ee.ImageCollection("LANDSAT/LE07/C02/T1_L2")), "CLOUD_COVER"),
    }
    out = {}
    for name, (collection, cloud) in sources.items():
        clear = collection.filterBounds(region).filter(ee.Filter.lt(cloud, CLEAR_SCENE_CLOUD))
        before = clear.filterDate(day.advance(-days, "day"), day).aggregate_array("system:time_start")
        after = clear.filterDate(day.advance(1, "day"), day.advance(days, "day")).aggregate_array("system:time_start")
        out[name] = {"before": before, "after": after}
    info = ee.Dictionary({k: ee.Dictionary(v) for k, v in out.items()}).getInfo()

    def day_of(ms):
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")

    return {name: {when: sorted({day_of(t) for t in times}) for when, times in info[name].items()} for name in info}


def rain_total(region: ee.Geometry, start: str, end: str) -> dict:
    """GPM IMERG V07 rain (mm) summed from start to end (exclusive): mean and wettest cell over `region`."""
    half_hours = ee.ImageCollection("NASA/GPM_L3/IMERG_V07").filterDate(start, end).select("precipitation")
    total = half_hours.sum().multiply(0.5)  # mm/h every half hour -> mm
    stats = total.reduceRegion(ee.Reducer.mean().combine(ee.Reducer.max(), sharedInputs=True), region.buffer(10_000),
                               scale=5_000, maxPixels=1e9).getInfo()
    return {"mean_mm": stats["precipitation_mean"], "max_mm": stats["precipitation_max"],
            "half_hours": half_hours.size().getInfo()}


def water_mask_code(lon: float, lat: float) -> int | None:
    """GLO-30's water body mask at a point: 0 land, 1 ocean, 2 lake, 3 river."""
    dem = ee.ImageCollection(terrain.GLO30)
    image = dem.select("WBM").mosaic()
    value = image.reduceRegion(ee.Reducer.mode(), ee.Geometry.Point([lon, lat]).buffer(60), 30).get("WBM")
    return value.getInfo()
