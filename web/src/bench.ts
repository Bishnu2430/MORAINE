import * as THREE from "three";
import type { Terrain } from "./terrain";

// P0 frame-rate benchmark: fixed camera paths at the plan's 1152 x 1080 canvas, frame times from
// requestAnimationFrame, and (where the browser allows it) GPU time from a timer query.

export const BENCH_SIZE = { width: 1152, height: 1080 }; // 60% of a 1920 x 1080 screen at full height
const WARM_UP_MS = 1500;
const RECORD_MS = 10_000;
const SLOW_FRAME_MS = 20; // a frame later than this missed a 60 Hz refresh

interface Phase {
  name: string;
  draws: number; // how many times the scene is drawn each frame; 2 measures headroom
  lodOff?: boolean;
  role: "gate" | "info";
  pose: (seconds: number) => { position: THREE.Vector3; target: THREE.Vector3 };
}

export interface PhaseResult {
  name: string;
  role: "gate" | "info";
  passed: boolean | null;
  frames: number;
  fps: number;
  medianMs: number;
  p95Ms: number;
  slowShare: number;
  gpuMs: number | null;
  triangles: number;
  lodShare: number[];
}

export interface BenchContext {
  renderer: THREE.WebGLRenderer;
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  terrain: Terrain;
  river: THREE.Vector3[]; // river path in world coordinates, lake first
  onFrame?: () => void;
  log: (line: string) => void;
}

class GpuTimer {
  private readonly ext: { TIME_ELAPSED_EXT: number; GPU_DISJOINT_EXT: number } | null;
  private pending: WebGLQuery[] = [];
  readonly results: number[] = [];

  constructor(private readonly gl: WebGL2RenderingContext) {
    this.ext = gl.getExtension("EXT_disjoint_timer_query_webgl2");
  }

  get available(): boolean {
    return this.ext !== null;
  }

  begin(): void {
    if (!this.ext) return;
    const query = this.gl.createQuery();
    if (!query) return;
    this.gl.beginQuery(this.ext.TIME_ELAPSED_EXT, query);
    this.pending.push(query);
  }

  end(): void {
    if (this.ext) this.gl.endQuery(this.ext.TIME_ELAPSED_EXT);
  }

  poll(): void {
    if (!this.ext) return;
    const disjoint = this.gl.getParameter(this.ext.GPU_DISJOINT_EXT);
    const still: WebGLQuery[] = [];
    for (const query of this.pending) {
      if (!this.gl.getQueryParameter(query, this.gl.QUERY_RESULT_AVAILABLE)) {
        still.push(query);
        continue;
      }
      if (!disjoint) this.results.push(this.gl.getQueryParameter(query, this.gl.QUERY_RESULT) / 1e6);
      this.gl.deleteQuery(query);
    }
    this.pending = still;
  }

  reset(): void {
    this.results.length = 0;
  }
}

function frame(): Promise<number> {
  return new Promise((resolve) => requestAnimationFrame(resolve));
}

function percentile(sorted: number[], p: number): number {
  return sorted[Math.min(sorted.length - 1, Math.floor(p * sorted.length))];
}

function along(path: THREE.Vector3[], metres: number): THREE.Vector3 {
  let left = metres;
  for (let i = 1; i < path.length; i++) {
    const step = path[i].distanceTo(path[i - 1]);
    if (left <= step) return path[i - 1].clone().lerp(path[i], left / step);
    left -= step;
  }
  return path[path.length - 1].clone();
}

export function phases(ctx: BenchContext): Phase[] {
  const target = new THREE.Vector3(0, 2500, 0);
  const orbit = (seconds: number) => {
    const angle = THREE.MathUtils.degToRad(200) + (seconds * 2 * Math.PI) / 20; // one turn every 20 s
    const distance = 62_000;
    const pitch = THREE.MathUtils.degToRad(38);
    return {
      position: new THREE.Vector3(
        Math.sin(angle) * Math.cos(pitch) * distance,
        target.y + Math.sin(pitch) * distance,
        Math.cos(angle) * Math.cos(pitch) * distance,
      ),
      target,
    };
  };
  const flight = (seconds: number) => {
    const s = 4_000 + seconds * 3_000; // 3 km/s down the valley from 4 km below the lake
    const ground = along(ctx.river, s);
    const ahead = along(ctx.river, s + 6_000);
    return { position: ground.clone().add(new THREE.Vector3(0, 1_400, 0)), target: ahead };
  };
  return [
    { name: "Whole valley, turning", draws: 1, role: "gate", pose: orbit },
    { name: "Whole valley, drawn twice per frame", draws: 2, role: "gate", pose: orbit },
    { name: "Low flight down the river", draws: 1, role: "gate", pose: flight },
    { name: "Low flight, drawn twice per frame", draws: 2, role: "gate", pose: flight },
    { name: "Whole valley, every patch at 30 m", draws: 1, role: "info", lodOff: true, pose: orbit },
  ];
}

export async function runBench(ctx: BenchContext): Promise<PhaseResult[]> {
  const { renderer, scene, camera, terrain } = ctx;
  const timer = new GpuTimer(renderer.getContext() as WebGL2RenderingContext);
  const results: PhaseResult[] = [];
  for (const phase of phases(ctx)) {
    terrain.forceLod = phase.lodOff ? 0 : null;
    ctx.log(`Running: ${phase.name} ...`);
    const start = await frame();
    let previous = start;
    const deltas: number[] = [];
    let triangles = 0;
    const lodTotals = [0, 0, 0];
    timer.reset();
    for (;;) {
      const now = await frame();
      const elapsed = now - start;
      if (elapsed > WARM_UP_MS + RECORD_MS) break;
      const recording = elapsed > WARM_UP_MS;
      if (recording) deltas.push(now - previous);
      previous = now;
      const pose = phase.pose(elapsed / 1000);
      camera.position.copy(pose.position);
      camera.lookAt(pose.target);
      camera.updateMatrixWorld();
      terrain.update(camera, BENCH_SIZE.height);
      if (recording) timer.begin();
      for (let d = 0; d < phase.draws; d++) renderer.render(scene, camera);
      if (recording) timer.end();
      timer.poll();
      ctx.onFrame?.();
      if (recording) {
        triangles += terrain.triangles;
        terrain.counts.forEach((c, i) => (lodTotals[i] += c));
      }
    }
    timer.poll();
    const sorted = [...deltas].sort((a, b) => a - b);
    const totalMs = deltas.reduce((a, b) => a + b, 0);
    const slowShare = deltas.filter((d) => d > SLOW_FRAME_MS).length / deltas.length;
    const fps = (1000 * deltas.length) / totalMs;
    const patches = lodTotals.reduce((a, b) => a + b, 0) || 1;
    const result: PhaseResult = {
      name: phase.name,
      role: phase.role,
      passed: phase.role === "gate" ? slowShare <= 0.05 && fps >= 58 : null,
      frames: deltas.length,
      fps,
      medianMs: percentile(sorted, 0.5),
      p95Ms: percentile(sorted, 0.95),
      slowShare,
      gpuMs: timer.results.length ? timer.results.reduce((a, b) => a + b, 0) / timer.results.length : null,
      triangles: triangles / Math.max(1, deltas.length),
      lodShare: lodTotals.map((c) => c / patches),
    };
    results.push(result);
  }
  terrain.forceLod = null;
  return results;
}
