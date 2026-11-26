import * as THREE from "three";
import type { TerrainData } from "./data";
import { terrainFragment, terrainVertex } from "./shaders";

export const PATCH = 64; // cells per patch side
export const LOD_STEPS = [1, 2, 4]; // vertex spacing in cells: 30, 60 and 120 m
const SKIRT_DEPTH = 250; // m; skirts hang below patch edges to hide cracks between levels of detail

interface Patch {
  origin: [number, number];
  box: THREE.Box3;
}

/** One patch grid at a given vertex spacing, with a skirt round its edge, drawn once per visible patch. */
function patchGeometry(step: number): THREE.InstancedBufferGeometry {
  const n = PATCH / step + 1;
  const positions: number[] = [];
  for (let j = 0; j < n; j++) for (let i = 0; i < n; i++) positions.push(i * step, 0, j * step);
  const index: number[] = [];
  for (let j = 0; j < n - 1; j++) {
    for (let i = 0; i < n - 1; i++) {
      const a = j * n + i;
      const b = a + 1;
      const c = a + n;
      const d = c + 1;
      index.push(a, c, b, b, c, d); // counter-clockwise seen from above
    }
  }
  // Perimeter in order, then a copy of it hanging below as the skirt (drawn from both sides)
  const ring: number[] = [];
  for (let i = 0; i < n - 1; i++) ring.push(i);
  for (let j = 0; j < n - 1; j++) ring.push(j * n + n - 1);
  for (let i = n - 1; i > 0; i--) ring.push((n - 1) * n + i);
  for (let j = n - 1; j > 0; j--) ring.push(j * n);
  const base = n * n;
  for (const v of ring) positions.push(positions[3 * v], 1, positions[3 * v + 2]);
  for (let k = 0; k < ring.length; k++) {
    const a = ring[k];
    const b = ring[(k + 1) % ring.length];
    const a2 = base + k;
    const b2 = base + ((k + 1) % ring.length);
    index.push(a, b, b2, a, b2, a2, a, b2, b, a, a2, b2);
  }
  const geometry = new THREE.InstancedBufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  geometry.setIndex(index);
  geometry.userData.triangles = index.length / 3;
  return geometry;
}

export class Terrain {
  readonly object = new THREE.Group();
  readonly material: THREE.ShaderMaterial;
  readonly halfExtent: THREE.Vector2;
  /** Draw every visible patch at this level (0 = 30 m) instead of choosing by distance; null = choose. */
  forceLod: number | null = null;
  /**
   * A patch gets the coarsest level whose cells still project to at most this many pixels. At 2 the
   * whole-valley shot drew 0.7 M triangles of about a pixel each and, drawn twice per frame, dropped
   * 6-9% of frames on Iris Xe; at 4 it draws 0.2 M and holds 60 fps, with no visible change because
   * shading comes from the 30 m normal map either way (P0 finding).
   */
  pixelsPerCell = 4;
  readonly counts = [0, 0, 0];
  triangles = 0;

  private readonly patches: Patch[] = [];
  private readonly meshes: THREE.Mesh<THREE.InstancedBufferGeometry, THREE.ShaderMaterial>[] = [];
  private readonly origins: THREE.InstancedBufferAttribute[] = [];
  private readonly frustum = new THREE.Frustum();
  private readonly viewProjection = new THREE.Matrix4();

  constructor(private readonly data: TerrainData) {
    const { width, height, cell, heights, edge, manifest } = data;
    this.halfExtent = new THREE.Vector2((width * cell) / 2, (height * cell) / 2);

    const heightTex = new THREE.DataTexture(heights, width, height, THREE.RedFormat, THREE.FloatType);
    heightTex.needsUpdate = true;
    const normalTex = new THREE.DataTexture(normalsAndEdge(data), width, height, THREE.RGBAFormat);
    normalTex.minFilter = THREE.LinearMipmapLinearFilter;
    normalTex.magFilter = THREE.LinearFilter;
    normalTex.generateMipmaps = true;
    normalTex.anisotropy = 4;
    normalTex.needsUpdate = true;

    const sun = new THREE.Vector3().setFromSphericalCoords(1, THREE.MathUtils.degToRad(90 - 32), THREE.MathUtils.degToRad(150));
    sun.set(sun.x, sun.y, -sun.z); // azimuth 150 degrees (south-south-east), 32 degrees up; north is -z
    this.material = new THREE.ShaderMaterial({
      vertexShader: terrainVertex,
      fragmentShader: terrainFragment,
      uniforms: {
        heightTex: { value: heightTex },
        normalTex: { value: normalTex },
        gridSize: { value: new THREE.Vector2(width, height) },
        cellSize: { value: cell },
        halfExtent: { value: this.halfExtent },
        exaggeration: { value: 1 },
        skirtDepth: { value: SKIRT_DEPTH },
        offsetM: { value: manifest.offset_m },
        sunDir: { value: sun.normalize() },
        sunColor: { value: new THREE.Color("#fff1dc").multiplyScalar(2.1) },
        skyColor: { value: new THREE.Color("#a9bfd9").multiplyScalar(0.42) },
        fogColor: { value: new THREE.Color("#1a222c") },
        fogDensity: { value: 9e-6 },
        forest: { value: new THREE.Color("#3a4a2c") },
        meadow: { value: new THREE.Color("#7a7550") },
        scree: { value: new THREE.Color("#8a8379") },
        rock: { value: new THREE.Color("#6f6a66") },
        snow: { value: new THREE.Color("#eef2f7") },
      },
    });

    // Patches that touch the corridor, each with a box for culling and distance
    for (let py = 0; py * PATCH < height - 1; py++) {
      for (let px = 0; px * PATCH < width - 1; px++) {
        let inside = false;
        let lo = Infinity;
        let hi = -Infinity;
        for (let y = py * PATCH; y <= Math.min(py * PATCH + PATCH, height - 1); y++) {
          for (let x = px * PATCH; x <= Math.min(px * PATCH + PATCH, width - 1); x++) {
            const i = y * width + x;
            if (edge[i] < 255) inside = true;
            lo = Math.min(lo, heights[i]);
            hi = Math.max(hi, heights[i]);
          }
        }
        if (!inside) continue;
        const x0 = px * PATCH * cell - this.halfExtent.x;
        const z0 = py * PATCH * cell - this.halfExtent.y;
        this.patches.push({
          origin: [px * PATCH, py * PATCH],
          box: new THREE.Box3(
            new THREE.Vector3(x0, lo - SKIRT_DEPTH, z0),
            new THREE.Vector3(x0 + (PATCH + 1) * cell, hi, z0 + (PATCH + 1) * cell),
          ),
        });
      }
    }

    for (const step of LOD_STEPS) {
      const geometry = patchGeometry(step);
      const origins = new THREE.InstancedBufferAttribute(new Float32Array(this.patches.length * 2), 2);
      origins.setUsage(THREE.DynamicDrawUsage);
      geometry.setAttribute("patchOrigin", origins);
      geometry.instanceCount = 0;
      const mesh = new THREE.Mesh(geometry, this.material);
      mesh.frustumCulled = false; // patches are culled one by one in update()
      this.object.add(mesh);
      this.meshes.push(mesh);
      this.origins.push(origins);
    }
  }

  get patchCount(): number {
    return this.patches.length;
  }

  /** Height (m above offset) at a grid position (column, row), nearest cell. */
  heightAt(col: number, row: number): number {
    const x = Math.min(this.data.width - 1, Math.max(0, Math.floor(col)));
    const y = Math.min(this.data.height - 1, Math.max(0, Math.floor(row)));
    return this.data.heights[y * this.data.width + x];
  }

  /** World position of a grid position (column, row as in the manifest), on the ground plus `lift` m. */
  worldAt(col: number, row: number, lift = 0): THREE.Vector3 {
    const { cell } = this.data;
    return new THREE.Vector3(col * cell - this.halfExtent.x, this.heightAt(col, row) + lift, row * cell - this.halfExtent.y);
  }

  /** Cull patches and pick each one's level of detail for this camera and render height (pixels). */
  update(camera: THREE.PerspectiveCamera, renderHeight: number): void {
    this.viewProjection.multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse);
    this.frustum.setFromProjectionMatrix(this.viewProjection);
    const pixelsPerMetreAt1m = renderHeight / (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2));
    const cell = this.data.cell;
    this.counts.fill(0);
    for (const patch of this.patches) {
      if (!this.frustum.intersectsBox(patch.box)) continue;
      let lod = this.forceLod;
      if (lod === null) {
        const distance = Math.max(patch.box.distanceToPoint(camera.position), 1);
        const cellPixels = (cell * pixelsPerMetreAt1m) / distance;
        lod = Math.min(LOD_STEPS.length - 1, Math.max(0, Math.floor(Math.log2(this.pixelsPerCell / cellPixels))));
      }
      const array = this.origins[lod].array as Float32Array;
      array[2 * this.counts[lod]] = patch.origin[0];
      array[2 * this.counts[lod] + 1] = patch.origin[1];
      this.counts[lod]++;
    }
    this.triangles = 0;
    this.meshes.forEach((mesh, lod) => {
      mesh.geometry.instanceCount = this.counts[lod];
      this.origins[lod].clearUpdateRanges();
      this.origins[lod].addUpdateRange(0, 2 * this.counts[lod]);
      this.origins[lod].needsUpdate = true;
      this.triangles += this.counts[lod] * mesh.geometry.userData.triangles;
    });
  }
}

/** RGB: surface normal (x east, y up, z south) from 30 m central differences. A: distance to the river. */
function normalsAndEdge({ width, height, cell, heights, edge }: TerrainData): Uint8Array {
  const out = new Uint8Array(width * height * 4);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const i = y * width + x;
      const east = heights[y * width + Math.min(width - 1, x + 1)];
      const west = heights[y * width + Math.max(0, x - 1)];
      const south = heights[Math.min(height - 1, y + 1) * width + x];
      const north = heights[Math.max(0, y - 1) * width + x];
      const nx = -(east - west) / (2 * cell);
      const nz = -(south - north) / (2 * cell);
      const length = Math.hypot(nx, 1, nz);
      out[4 * i] = Math.round((nx / length) * 127.5 + 127.5);
      out[4 * i + 1] = Math.round((1 / length) * 127.5 + 127.5);
      out[4 * i + 2] = Math.round((nz / length) * 127.5 + 127.5);
      out[4 * i + 3] = edge[i];
    }
  }
  return out;
}
