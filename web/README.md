# Moraine web

The site: Vite, TypeScript and Three.js (WebGL2). It only plays back files made by the pipeline;
nothing is simulated in the browser.

## Run it

```
cd web
npm install
npm run build
npm run preview
```

Then open <http://localhost:4173>. `npm run dev` serves the same page with live reload while editing.

## P0 terrain spike

The page shows the Teesta corridor from `public/data/teesta/terrain/`, which
`pipeline/scripts/p0_terrain.py` writes from Earth Engine. Drag to orbit; it turns slowly on its own.

Frame-rate test: open <http://localhost:4173/?bench> and keep the window in view and the laptop
plugged in. It takes about a minute. The canvas is drawn at 1152 × 1080, 60% of a 1920 × 1080
screen at full height, whatever the window size. It flies five fixed camera paths and prints a
table, plus a `MORAINE_BENCH {...}` line in the browser console. A gate holds 60 fps: an average
of at least 58 fps, with at most 5% of frames taking longer than 20 ms. The "drawn twice per frame"
shots check there is room left for water, particles and effects.

Other address options: `?still` freezes the camera on the test's opening shot, and `?px=2` sets how
many pixels a cell may cover before a patch switches to coarser geometry (default 4).

How the terrain is drawn (`src/terrain.ts`): the corridor is cut into 64-cell patches. Each patch is
drawn at 30, 60 or 120 m vertex spacing depending on its distance, using three shared grids. Each
grid is drawn once with one entry per visible patch. Heights come from one 30 m float texture, and
lighting comes from a 30 m normal map, so a distant 120 m patch keeps 30 m shading. Skirts hang
below patch edges to hide cracks where two levels meet. The corridor edge fades into the
background.
