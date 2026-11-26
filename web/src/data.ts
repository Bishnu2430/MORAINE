// Loads one valley's terrain package (written by pipeline/scripts/p0_terrain.py).

export interface Level {
  file: string;
  cell_m: number;
  width: number;
  height: number;
}

export interface Manifest {
  valley: string;
  crs: string;
  origin: { x: number; y: number };
  offset_m: number;
  scale_m: number;
  nodata: number;
  levels: Level[];
  corridor: { file: string; step_m: number; outside: number; half_width_m: number };
  river: { grid: [number, number][]; length_km: number };
  places: { name: string; grid: [number, number] }[];
  sources: string[];
}

export interface TerrainData {
  manifest: Manifest;
  width: number;
  height: number;
  cell: number;
  /** Metres above manifest.offset_m, row 0 at the north. Holes are filled outward so edge triangles stay level. */
  heights: Float32Array;
  /** 0 on the river, 254 at the corridor's edge, 255 outside it. */
  edge: Uint8Array;
  bytes: number;
}

async function fetchBytes(url: string): Promise<ArrayBuffer> {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url}: ${response.status} ${response.statusText}`);
  return response.arrayBuffer();
}

export async function loadTerrain(base: string, cell = 30): Promise<TerrainData> {
  const manifest = (await (await fetch(`${base}/manifest.json`)).json()) as Manifest;
  const level = manifest.levels.find((l) => l.cell_m === cell);
  if (!level) throw new Error(`no ${cell} m level in ${base}/manifest.json`);
  const [heightBuffer, corridorBuffer] = await Promise.all([
    fetchBytes(`${base}/${level.file}`),
    fetchBytes(`${base}/${manifest.corridor.file}`),
  ]);
  const raw = new Uint16Array(heightBuffer);
  const corridor = new Uint8Array(corridorBuffer);
  const { width, height } = level;
  const heights = new Float32Array(width * height);
  for (let i = 0; i < raw.length; i++) heights[i] = raw[i] === manifest.nodata ? NaN : raw[i] * manifest.scale_m;
  fillHoles(heights, width, height, 12);

  // The corridor file is a distance from the river (in step_m units); rescale it to a share of the half width
  const edge = new Uint8Array(corridor.length);
  const perStep = (manifest.corridor.step_m / manifest.corridor.half_width_m) * 254;
  for (let i = 0; i < corridor.length; i++) {
    edge[i] = corridor[i] === manifest.corridor.outside ? 255 : Math.min(254, Math.round(corridor[i] * perStep));
  }
  return {
    manifest,
    width,
    height,
    cell,
    heights,
    edge,
    bytes: heightBuffer.byteLength + corridorBuffer.byteLength,
  };
}

/** Grow valid heights into the empty cells around them for `passes` cells, then set what is left to 0. */
function fillHoles(h: Float32Array, w: number, rows: number, passes: number): void {
  let frontier: number[] = [];
  for (let i = 0; i < h.length; i++) if (Number.isNaN(h[i])) frontier.push(i);
  for (let pass = 0; pass < passes && frontier.length; pass++) {
    const filled: [number, number][] = [];
    const left: number[] = [];
    for (const i of frontier) {
      const x = i % w;
      const y = (i - x) / w;
      let sum = 0;
      let n = 0;
      if (x > 0 && !Number.isNaN(h[i - 1])) (sum += h[i - 1]), n++;
      if (x < w - 1 && !Number.isNaN(h[i + 1])) (sum += h[i + 1]), n++;
      if (y > 0 && !Number.isNaN(h[i - w])) (sum += h[i - w]), n++;
      if (y < rows - 1 && !Number.isNaN(h[i + w])) (sum += h[i + w]), n++;
      if (n) filled.push([i, sum / n]);
      else left.push(i);
    }
    for (const [i, value] of filled) h[i] = value;
    frontier = left;
  }
  for (const i of frontier) h[i] = 0;
}
