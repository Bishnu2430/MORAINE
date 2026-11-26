import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { BENCH_SIZE, runBench, type PhaseResult } from "./bench";
import { loadTerrain } from "./data";
import { Terrain } from "./terrain";
import "./style.css";

const bench = new URLSearchParams(location.search).has("bench");
const view = document.querySelector<HTMLElement>("#view")!;
const canvas = document.querySelector<HTMLCanvasElement>("#scene")!;
const labelLayer = document.querySelector<HTMLElement>("#labels")!;
const statusLine = document.querySelector<HTMLElement>("#status")!;
const statsList = document.querySelector<HTMLElement>("#stats")!;
const benchPanel = document.querySelector<HTMLElement>("#bench")!;

const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: "high-performance" });
renderer.setPixelRatio(1); // the plan caps the pixel ratio at 1; render size follows the canvas
renderer.setClearColor(new THREE.Color("#1a222c"));
const gl = renderer.getContext();
const debugInfo = gl.getExtension("WEBGL_debug_renderer_info");
const gpu = String(debugInfo ? gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER));

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(32, 1, 50, 400_000);

const data = await loadTerrain(`${import.meta.env.BASE_URL}data/teesta/terrain`);
const terrain = new Terrain(data);
const pixelsPerCell = Number(new URLSearchParams(location.search).get("px"));
if (pixelsPerCell > 0) terrain.pixelsPerCell = pixelsPerCell; // ?px=4: coarser geometry sooner
scene.add(terrain.object);
document.querySelector("#river-km")!.textContent = data.manifest.river.length_km.toFixed(0);

// Lifted 30 m so coarser distant patches don't hide it; later the flood is drawn on the terrain itself
const river = data.manifest.river.grid.map(([col, row]) => terrain.worldAt(col, row, 30));
scene.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(river), new THREE.LineBasicMaterial({ color: "#6cc4ff" })));

const labels = data.manifest.places.map((place) => {
  const element = document.createElement("div");
  element.className = "label";
  element.textContent = place.name;
  labelLayer.append(element);
  return { element, position: terrain.worldAt(place.grid[0], place.grid[1], 60) };
});

const controls = new OrbitControls(camera, canvas);
controls.target.set(0, 2500, 0);
camera.position.set(-30_000, 40_000, 45_000);
controls.enableDamping = true;
controls.autoRotate = true;
controls.autoRotateSpeed = 0.5;
controls.minDistance = 2_000;
controls.maxDistance = 160_000;
controls.maxPolarAngle = THREE.MathUtils.degToRad(82);
controls.enabled = !bench;
if (new URLSearchParams(location.search).has("still")) {
  // ?still: freeze on the benchmark's opening shot, for comparing settings side by side
  controls.autoRotate = false;
  const angle = THREE.MathUtils.degToRad(200);
  const pitch = THREE.MathUtils.degToRad(38);
  camera.position.set(Math.sin(angle) * Math.cos(pitch) * 62_000, 2_500 + Math.sin(pitch) * 62_000,
    Math.cos(angle) * Math.cos(pitch) * 62_000);
}

const renderSize = new THREE.Vector2();
function resize(): void {
  if (bench) renderSize.set(BENCH_SIZE.width, BENCH_SIZE.height);
  else renderSize.set(Math.max(1, view.clientWidth), Math.max(1, view.clientHeight));
  renderer.setSize(renderSize.x, renderSize.y, false);
  camera.aspect = renderSize.x / renderSize.y;
  camera.updateProjectionMatrix();
}
resize();
window.addEventListener("resize", resize);

function placeLabels(): void {
  // The canvas keeps its render aspect inside the view (object-fit: contain), so find the drawn area
  const box = canvas.getBoundingClientRect();
  const scale = Math.min(box.width / renderSize.x, box.height / renderSize.y);
  const width = renderSize.x * scale;
  const height = renderSize.y * scale;
  const left = (box.width - width) / 2;
  const top = (box.height - height) / 2;
  for (const { element, position } of labels) {
    const p = position.clone().project(camera);
    const visible = p.z < 1 && Math.abs(p.x) < 1 && Math.abs(p.y) < 1;
    element.style.display = visible ? "block" : "none";
    element.style.transform = `translate(${left + ((p.x + 1) / 2) * width}px, ${top + ((1 - p.y) / 2) * height}px)`;
  }
}

const recent: number[] = [];
let last = performance.now();
let firstFrameMs: number | null = null;
function showStats(now: number): void {
  recent.push(now - last);
  last = now;
  if (recent.length > 120) recent.shift();
  const mean = recent.reduce((a, b) => a + b, 0) / recent.length;
  const rows: [string, string][] = [
    ["Frame rate", `${(1000 / mean).toFixed(0)} fps (${mean.toFixed(1)} ms)`],
    ["Render size", `${renderSize.x} × ${renderSize.y}`],
    ["Triangles", `${(terrain.triangles / 1e6).toFixed(2)} M`],
    ["Patches at 30 / 60 / 120 m", terrain.counts.join(" / ")],
    ["Terrain data", `${(data.bytes / 1e6).toFixed(1)} MB unpacked`],
    ["First frame", firstFrameMs === null ? "-" : `${(firstFrameMs / 1000).toFixed(1)} s after opening`],
    ["GPU", gpu],
  ];
  statsList.innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("");
}

function draw(now: number): void {
  controls.update();
  terrain.update(camera, renderSize.y);
  renderer.render(scene, camera);
  placeLabels();
  if (firstFrameMs === null) {
    firstFrameMs = performance.now();
    statusLine.hidden = true;
  }
  if (now - last > 0) showStats(now);
}

function loop(now: number): void {
  draw(now);
  requestAnimationFrame(loop);
}

function report(results: PhaseResult[]): void {
  const pct = (x: number) => `${(100 * x).toFixed(1)}%`;
  const rows = results
    .map((r) => {
      const mark = r.role === "info" ? "INFO" : r.passed ? "PASS" : "FAIL";
      const gpuMs = r.gpuMs === null ? "-" : r.gpuMs.toFixed(1);
      return `<tr class="${mark.toLowerCase()}"><td>${mark}</td><td>${r.name}</td><td>${r.fps.toFixed(1)}</td><td>${r.p95Ms.toFixed(1)}</td><td>${pct(r.slowShare)}</td><td>${gpuMs}</td><td>${(r.triangles / 1e6).toFixed(2)}</td></tr>`;
    })
    .join("");
  const gates = results.filter((r) => r.role === "gate");
  const passed = gates.filter((r) => r.passed).length;
  benchPanel.innerHTML = `
    <h2>Frame-rate test at ${BENCH_SIZE.width} × ${BENCH_SIZE.height}</h2>
    <p>${passed} of ${gates.length} gates passed. A gate holds 60 fps: average at least 58 fps and at most 5% of frames over 20 ms.</p>
    <table><thead><tr><th></th><th>Shot</th><th>fps</th><th>p95 ms</th><th>&gt;20 ms</th><th>GPU ms</th><th>M tris</th></tr></thead><tbody>${rows}</tbody></table>`;
  console.log(
    "MORAINE_BENCH " +
      JSON.stringify({
        gpu,
        size: BENCH_SIZE,
        pixelsPerCell: terrain.pixelsPerCell,
        firstFrameMs,
        dataBytes: data.bytes,
        patches: terrain.patchCount,
        results,
      }),
  );
}

if (bench) {
  draw(performance.now());
  benchPanel.innerHTML = `<p id="bench-status">Starting the frame-rate test ...</p>`;
  const results = await runBench({
    renderer,
    scene,
    camera,
    terrain,
    river,
    onFrame: placeLabels,
    log: (line) => (benchPanel.innerHTML = `<p>${line}</p>`),
  });
  report(results);
  controls.enabled = true;
}
requestAnimationFrame(loop);
