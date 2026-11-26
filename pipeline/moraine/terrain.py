"""Terrain for the web viewer: the flood corridor's elevation, cut from Copernicus GLO-30.

The corridor follows the river from the lake to the town, traced downhill on MERIT Hydro's flow
directions, and keeps everything within a fixed distance of that path. Elevation is reprojected to
UTM so cells are square in metres, then stored as Uint16 at 30, 60 and 120 m with a scale and offset
in the manifest. The Earth Engine calls live here; the array work below them is plain NumPy and is
tested offline.
"""

from __future__ import annotations

import numpy as np

GLO30 = "COPERNICUS/DEM/GLO30_2024_1"  # the 2024 edition; Earth Engine deprecated the original asset
MERIT = "MERIT/Hydro/v1_0_1"
MERIT_STEP = 1 / 1200  # MERIT Hydro's 3 arc-second grid, in degrees
UTM_45N = "EPSG:32645"
NODATA = 65535
SCALE = 0.1  # m per Uint16 step: 0-6553.4 m above the offset

# MERIT Hydro flow directions (D8): code -> (row step, column step), rows running south
D8 = {1: (0, 1), 2: (1, 1), 4: (1, 0), 8: (1, -1), 16: (0, -1), 32: (-1, -1), 64: (-1, 0), 128: (-1, 1)}


# --- Earth Engine -----------------------------------------------------------------------------------

def merit_directions(west: float, south: float, east: float, north: float):
    """MERIT flow directions on their native grid. Returns (array, lon of column 0's west edge, lat of row 0's north edge)."""
    data, x0, y0 = merit_band("dir", west, south, east, north)
    return data.astype(np.int32), x0, y0


def merit_band(band: str, west: float, south: float, east: float, north: float):
    """One MERIT Hydro band (e.g. "dir", or "upa" for upstream area in km2) on its native grid, as merit_directions."""
    import ee

    x0 = np.floor(west / MERIT_STEP) * MERIT_STEP
    y0 = np.ceil(north / MERIT_STEP) * MERIT_STEP
    width = int(round((east - x0) / MERIT_STEP))
    height = int(round((y0 - south) / MERIT_STEP))
    data = ee.data.computePixels({
        "expression": ee.Image(MERIT).select(band),
        "fileFormat": "NUMPY_NDARRAY",
        "grid": {
            "dimensions": {"width": width, "height": height},
            "affineTransform": {"scaleX": MERIT_STEP, "shearX": 0, "translateX": x0,
                                "shearY": 0, "scaleY": -MERIT_STEP, "translateY": y0},
            "crsCode": "EPSG:4326",
        },
    })
    return np.asarray(data[band]).astype(np.float64), x0, y0


def glo30_utm(x0: float, y_top: float, width: int, height: int, cell: float = 30.0, crs: str = UTM_45N) -> np.ndarray:
    """GLO-30 elevation (m), bilinearly resampled onto a UTM grid (zone 45N unless `crs` says otherwise) whose
    top-left corner is (x0, y_top)."""
    import ee

    dem = ee.ImageCollection(GLO30).select("DEM")
    image = dem.mosaic().setDefaultProjection(dem.first().projection()).resample("bilinear")
    data = ee.data.computePixels({
        "expression": image,
        "fileFormat": "NUMPY_NDARRAY",
        "grid": {
            "dimensions": {"width": width, "height": height},
            "affineTransform": {"scaleX": cell, "shearX": 0, "translateX": x0,
                                "shearY": 0, "scaleY": -cell, "translateY": y_top},
            "crsCode": crs,
        },
    })
    return np.asarray(data["DEM"]).astype(np.float64)


def to_utm(lonlat: list[tuple[float, float]], crs: str = UTM_45N) -> np.ndarray:
    """Longitude/latitude pairs to UTM metres (zone 45N unless `crs` says otherwise), one Earth Engine call."""
    import ee

    points = ee.Geometry.MultiPoint([list(p) for p in lonlat]).transform(crs, 0.01)
    return np.array(points.coordinates().getInfo(), dtype=np.float64)


# --- Arrays ------------------------------------------------------------------------------------------

def trace_downhill(directions: np.ndarray, start: tuple[int, int], stop=None, max_steps: int = 100_000):
    """Follow D8 flow directions from `start` (row, col) until they end, leave the grid, loop, or stop(r, c)."""
    r, c = start
    path, seen = [(r, c)], {(r, c)}
    for _ in range(max_steps):
        step = D8.get(int(directions[r, c]))
        if step is None:
            break
        r, c = r + step[0], c + step[1]
        if not (0 <= r < directions.shape[0] and 0 <= c < directions.shape[1]) or (r, c) in seen:
            break
        path.append((r, c))
        seen.add((r, c))
        if stop is not None and stop(r, c):
            break
    return path


def upstream_mask(directions: np.ndarray, outlet: tuple[int, int]) -> np.ndarray:
    """Every cell whose D8 flow path reaches `outlet` (row, col), the outlet included."""
    rows, cols = directions.shape
    mask = np.zeros(directions.shape, dtype=bool)
    mask[outlet] = True
    stack = [outlet]
    while stack:
        r, c = stack.pop()
        for dr, dc in D8.values():
            nr, nc = r - dr, c - dc  # the neighbour that would flow into (r, c) by stepping (dr, dc)
            if 0 <= nr < rows and 0 <= nc < cols and not mask[nr, nc] and D8.get(int(directions[nr, nc])) == (dr, dc):
                mask[nr, nc] = True
                stack.append((nr, nc))
    return mask


def distance_to_polyline(xs: np.ndarray, ys: np.ndarray, line: np.ndarray) -> np.ndarray:
    """Distance from every point (xs, ys broadcast together) to the polyline `line` (n x 2), same units."""
    best = np.full(np.broadcast(xs, ys).shape, np.inf)
    for (ax, ay), (bx, by) in zip(line[:-1], line[1:]):
        dx, dy = bx - ax, by - ay
        length2 = dx * dx + dy * dy
        t = np.clip(((xs - ax) * dx + (ys - ay) * dy) / length2, 0, 1) if length2 > 0 else 0.0
        np.minimum(best, np.hypot(xs - (ax + t * dx), ys - (ay + t * dy)), out=best)
    return best


def block_mean(heights: np.ndarray, factor: int) -> np.ndarray:
    """Average factor x factor blocks, ignoring NaN; a block with no valid cell stays NaN."""
    h, w = heights.shape
    blocks = heights[: h - h % factor, : w - w % factor].reshape(h // factor, factor, w // factor, factor)
    valid = ~np.isnan(blocks)
    counts = valid.sum(axis=(1, 3))
    sums = np.where(valid, blocks, 0).sum(axis=(1, 3))
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(counts > 0, sums / counts, np.nan)


def encode(heights: np.ndarray, offset: float, scale: float = SCALE) -> np.ndarray:
    """Metres to Uint16 steps above `offset`; NaN becomes NODATA."""
    steps = np.round((heights - offset) / scale)
    if np.nanmax(steps) >= NODATA:
        raise ValueError("relief too large for one Uint16 scale; raise SCALE")
    return np.where(np.isnan(heights), NODATA, steps).astype("<u2")


def decode(data: np.ndarray, offset: float, scale: float = SCALE) -> np.ndarray:
    return np.where(data == NODATA, np.nan, offset + data.astype(np.float64) * scale)


def hillshade(heights: np.ndarray, cell: float, azimuth: float = 315.0, altitude: float = 40.0) -> np.ndarray:
    """0-1 shaded relief for preview images."""
    gy, gx = np.gradient(np.nan_to_num(heights, nan=np.nanmin(heights)), cell)
    slope = np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    az, alt = np.radians(360 - azimuth + 90), np.radians(altitude)
    return np.clip(np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect), 0, 1)
