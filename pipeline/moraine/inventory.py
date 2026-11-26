"""The Zhang et al. (2023) Third Pole glacial lake inventory: hand-drawn Sentinel-2 outlines of every
glacial lake of at least 0.02 km2 within 10 km of a glacier, for 2018, 2020 and 2022, with hazard
and risk attributes. Zenodo 10.5281/zenodo.8369314, CC BY 4.0.

The zip is fetched by pipeline/scripts/p1_inventory.py into pipeline/data/zhang2023/ (not in git).
Shapefiles are WGS84 longitude/latitude; areas here are computed on a local equal-area projection.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

URL = "https://zenodo.org/records/8369314/files/Glacial%20lake%20inventory.zip?download=1"
MD5 = "cec6a9905396bb1adf29b47b9e9f9dc3"
ZIP_NAME = "Glacial lake inventory.zip"
YEARS = (2018, 2020, 2022)
EARTH_RADIUS_M = 6_371_008.8


@dataclass
class Lake:
    year: int
    attrs: dict
    rings: list[list[tuple[float, float]]]  # outer ring(s) and holes, longitude/latitude
    bbox: tuple[float, float, float, float]  # west, south, east, north

    @property
    def lon(self) -> float:  # outline centre; only the 2022 file carries Lat/Lon columns
        return (self.bbox[0] + self.bbox[2]) / 2

    @property
    def lat(self) -> float:
        return (self.bbox[1] + self.bbox[3]) / 2

    @property
    def area_km2(self) -> float:
        """Area of the outline itself (holes subtracted), on a local equal-area projection."""
        lat0 = math.radians((self.bbox[1] + self.bbox[3]) / 2)
        west, south = self.bbox[0], self.bbox[1]  # measure from the lake's own corner to keep precision
        total = 0.0
        for ring in self.rings:
            xs = [math.radians(x - west) * EARTH_RADIUS_M * math.cos(lat0) for x, _ in ring]
            ys = [math.radians(y - south) * EARTH_RADIUS_M for _, y in ring]
            total += sum(xs[i] * ys[i + 1] - xs[i + 1] * ys[i] for i in range(len(ring) - 1)) / 2
        return abs(total) / 1e6

    def distance_m(self, lon: float, lat: float) -> float:
        """Distance from a point to the nearest outline vertex, 0 if the point is inside the outline."""
        if self.contains(lon, lat):
            return 0.0
        cos = math.cos(math.radians(lat))
        return min(math.hypot((x - lon) * 111_320 * cos, (y - lat) * 110_574) for ring in self.rings for x, y in ring)

    def contains(self, lon: float, lat: float) -> bool:
        w, s, e, n = self.bbox
        if not (w <= lon <= e and s <= lat <= n):
            return False
        inside = False
        for ring in self.rings:  # even-odd rule, so holes count correctly
            for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
                if (y1 > lat) != (y2 > lat) and lon < x1 + (lat - y1) * (x2 - x1) / (y2 - y1):
                    inside = not inside
        return inside


def shapefile_path(root: Path, year: int) -> Path:
    return root / "extracted" / "Third Pole" / f"Third_Pole_Glacial Lake_{year}.shp"


def load(root: Path, year: int) -> list[Lake]:
    import shapefile  # pyshp

    reader = shapefile.Reader(str(shapefile_path(root, year)), encoding="utf-8")
    fields = [f[0] for f in reader.fields[1:]]
    lakes = []
    for index, record in enumerate(reader.iterShapeRecords()):
        points, parts = record.shape.points, list(record.shape.parts) + [len(record.shape.points)]
        rings = [[tuple(p) for p in points[a:b]] for a, b in zip(parts[:-1], parts[1:])]
        attrs = dict(zip(fields, record.record))
        # The three files list the same lakes in the same order; each names its area column differently
        attrs["Area"] = attrs.get("Area", attrs.get(f"Area_{year}"))
        attrs["index"] = index
        lakes.append(Lake(year, attrs, rings, tuple(record.shape.bbox)))
    return lakes


def nearest(lakes: list[Lake], lon: float, lat: float, within_m: float) -> Lake | None:
    """The lake whose outline is closest to the point, if any lies within `within_m`."""
    near = [lake for lake in lakes if abs(lake.lat - lat) < 0.05 and abs(lake.lon - lon) < 0.05]
    best = min(near, key=lambda lake: lake.distance_m(lon, lat), default=None)
    return best if best is not None and best.distance_m(lon, lat) <= within_m else None
