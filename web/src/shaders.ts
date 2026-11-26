// Terrain shaders. Geometry comes from a shared patch grid displaced by the 30 m height texture;
// shading uses a 30 m normal map, so even a patch drawn at 120 m keeps 30 m lighting detail.

export const terrainVertex = /* glsl */ `
uniform sampler2D heightTex;
uniform vec2 gridSize;
uniform float cellSize;
uniform vec2 halfExtent;
uniform float exaggeration;
uniform float skirtDepth;

attribute vec2 patchOrigin;

varying vec2 vUv;
varying float vHeight;
varying vec3 vWorld;

void main() {
  // position.xz: the vertex's cell offset inside its patch; position.y: 1 on the skirt that hides cracks
  vec2 cell = min(patchOrigin + position.xz, gridSize - 1.0);
  float h = texelFetch(heightTex, ivec2(cell), 0).r;
  vHeight = h;
  vec3 world = vec3(
    (cell.x + 0.5) * cellSize - halfExtent.x,
    h * exaggeration - position.y * skirtDepth,
    (cell.y + 0.5) * cellSize - halfExtent.y
  );
  vWorld = world;
  vUv = (cell + 0.5) / gridSize;
  gl_Position = projectionMatrix * viewMatrix * vec4(world, 1.0);
}
`;

export const terrainFragment = /* glsl */ `
uniform sampler2D normalTex;
uniform float offsetM;
uniform vec3 sunDir;
uniform vec3 sunColor;
uniform vec3 skyColor;
uniform vec3 fogColor;
uniform float fogDensity;
uniform vec3 forest;
uniform vec3 meadow;
uniform vec3 scree;
uniform vec3 rock;
uniform vec3 snow;

varying vec2 vUv;
varying float vHeight;
varying vec3 vWorld;

void main() {
  vec4 texel = texture2D(normalTex, vUv);
  float edge = texel.a;  // 0 on the river, 1 at the corridor's edge and beyond
  if (edge > 0.998) discard;
  vec3 n = normalize(texel.rgb * 2.0 - 1.0);
  float elevation = vHeight + offsetM;
  float steep = 1.0 - n.y;

  // Placeholder ground colour from elevation and slope; Sentinel-2 imagery replaces it later
  vec3 albedo = mix(forest, meadow, smoothstep(3300.0, 4100.0, elevation));
  albedo = mix(albedo, scree, smoothstep(4300.0, 4900.0, elevation));
  albedo = mix(albedo, rock, smoothstep(0.28, 0.55, steep));
  float snowLine = 5050.0 + 500.0 * steep;
  float snowCover = smoothstep(snowLine - 150.0, snowLine + 250.0, elevation) * (1.0 - smoothstep(0.5, 0.75, steep));
  albedo = mix(albedo, snow, snowCover);

  float sunlight = max(dot(n, sunDir), 0.0);
  vec3 color = albedo * (sunColor * sunlight + skyColor * (0.55 + 0.45 * n.y));
  float haze = 1.0 - exp(-length(vWorld - cameraPosition) * fogDensity);
  color = mix(color, fogColor, haze);
  color = mix(color, fogColor, smoothstep(0.8, 0.998, edge));
  gl_FragColor = vec4(color, 1.0);
  #include <colorspace_fragment>
}
`;
