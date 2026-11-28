# Moraine pipeline

The offline half of Moraine. Scripts run on your laptop; the satellite processing runs on
Google Earth Engine, and only small tables come back.

## One-time setup

1. **Python environment.** It already exists on this laptop as `.venv`. On a fresh clone:

   ```
   python -m venv .venv
   .venv\Scripts\python -m pip install -r pipeline\requirements.txt
   ```

2. **Earth Engine access** (in your browser, once). Open
   <https://code.earthengine.google.com/register>, choose unpaid, non-commercial use, pick the
   free Community tier, and create or pick a Google Cloud project. Note the project ID.
   Moraine's project is `master-bruin-515809-p2`.

3. **Sign in on this laptop.** A browser window opens; use the same Google account.

   ```
   .venv\Scripts\earthengine authenticate
   ```

   Either save the project as your default with `.venv\Scripts\earthengine set_project ID`, or
   pass `--project ID` to each script. On this laptop the saved default belongs to another
   project, so pass `--project`.

## P0 spike: South Lhonak lake area

```
.venv\Scripts\python pipeline\scripts\p0_lake_area.py --project master-bruin-515809-p2
```

It takes a few minutes. What a good run looks like (first real run, 25 Nov 2026):

- It ends with **3 of 3 gate checks passed**: about 1.67 km² in autumn 2023 before the outburst
  (ISRO: 1.63-1.67 km²), 1.30-1.38 km² for 2014-2016 (published: 1.12-1.31 km²), and less open
  water after the outburst than before.
- An **INFO** line compares the after-outburst area (about 1.45 km² of open water) with the
  published 0.60 km². That figure was taken at 06:00 on 4 October, which matches the dawn pass of
  ISRO's EOS-04 radar satellite; radar can miss water under the floating ice that covered the lake
  that week. It is reported, not used as a pass/fail gate.
- `pipeline/out/p0_lake_area/south-lhonak/area.png` shows the lake growing from about 0.43 km² in
  the early 1990s to 1.67 km² in 2023, dropping at the outburst, and slowly refilling since.

Everything is written to `pipeline/out/p0_lake_area/south-lhonak/` even if a check fails. To redo
the tables and chart without calling Earth Engine, pass
`--from-csv pipeline\out\p0_lake_area\south-lhonak\periods_raw.csv`.

Offline tests, lake summary and solver (seconds): `.venv\Scripts\python -m pytest pipeline\tests -q`

## How the measurement works

- **Where to measure:** the lake's largest outline in JRC Global Surface Water (1984-2021),
  joined with its largest Sentinel-2 outline from the 2017-2026 autumns (the lake kept growing
  west toward its glacier), widened by 100 m.
- **No cloud masks.** Landsat's own cloud mask labels dark lake water as cloud shadow and silty
  water as cloud, so it threw away the lake itself. Instead, each autumn (1 September to
  15 November) gets a per-pixel 80th-percentile composite of NDWI, green against near-infrared.
  Clouds, ice and snow only lower NDWI, so the composite picks each pixel's clear-water state.
  This also fills Landsat 7's striped gaps.
- **Water:** NDWI above 0.25. The 0.15 and 0.35 cut-offs are kept too and drawn as a grey band;
  a wide band means the answer depends on the cut-off.
- **Which periods count:** at least 95% of the measuring area must be seen by 3 or more scenes.
  Sentinel-2 (10 m) is used where it qualifies, otherwise Landsat (30 m).
- **Outliers:** a lake does not double for one autumn and shrink back. A period that differs by
  more than 30% from the median of the periods within 4 years, on the same side of the outburst,
  is dropped and drawn hollow. The first real run dropped 1988, 1999 and 2002, all built from
  3-4 scenes.

Known limits: the 1990s rest on 4-5 Landsat scenes a year, so their band is wide; 2001, 2003
and 1984-1990 (except 1988) have too few scenes to use.

## P0 spike: the flood solver against exact solutions

```
.venv\Scripts\python pipeline\scripts\p0_solver.py
```

No sign-in needed; it runs on the laptop CPU in about 5 minutes. What a good run looks like
(26 Nov 2026, with the shoreline change):

- It ends with **12 of 12 gate checks passed**. A dam holding 10 m of water fails onto a dry, flat,
  frictionless bed, and the solver matches Ritter's 1892 exact solution within 0.86% at 5 m cells.
  Halving the cells halves the error (order 1.03). The same dam break run along y gives an
  identical answer, run at 45° across the grid is within 0.75%, and run down a 30% slope is
  within 1.93%. Water volume is conserved to about 1e-15 and no depth ever went negative.
- **Still water stays still**, over a fully covered bed (7e-15 m/s) and with islands and
  shorelines (5e-14 m/s). With the 2007 paper's own shoreline step, the island lake reaches
  2.1 m/s in water deeper than 10 cm; that comparison is printed on the same line.
- **Moving shorelines stay right.** Water sloshing round a bowl (Thacker 1981), its shoreline
  climbing and falling the bowl's sides, is back where the exact solution puts it after one full
  orbit: 0.19% depth error, wet area overlapping the exact one by 0.991. The 2007 step gives 0.17%
  and 0.991, so the shoreline change costs nothing here.
- `pipeline/out/p0_solver/dam-break.png` shows the depth profile on top of the exact one, and the
  error falling as cells get finer.
- **INFO lines** feed the solver work in P2:
  - *float32 at 5,200 m* is as accurate as float64 for the flood itself (0.84% against 0.86%), but
    each depth is then the small difference of two large elevations. Volume drifts by about 5e-5
    in 20 s, and the island lake creeps at 1.7 cm/s (4e-5 m/s for the same lake at sea level). The
    real runs should measure elevations from the lowest point in the valley.
  - *Speed* on this CPU is about 0.5-0.8 million cell-steps per second, far too slow for the
    valley runs, which need millions of cells over tens of thousands of 0.3 s steps. Those go on a
    Colab GPU; P2 measures how long one takes.

How the solver works (`moraine/swe.py`): the second-order central-upwind scheme of Kurganov and
Petrova (2007) in PyTorch, with walls on all sides and no friction yet. Two changes from the paper:

- Face velocities are built from cell velocities instead of face discharges from cell discharges.
  With discharges, a film of water 1 mm thick ran ahead of the flood front at 24 m/s, faster than
  the 19.8 m/s the physics allows, and near shorelines the solver needed five times as many time
  steps.
- Shorelines. Where a lake's edge crosses a cell, the paper tilts the cell's water surface down to
  the bed, and still water starts moving. Following Bollermann, Chen, Kurganov and Noelle (2013),
  such a cell gets a flat surface at its "pool level", the level that holds its water. The cell's
  ground is treated as four quarters at its corner heights, and one level serves both directions,
  so still water stays exactly still in 2D. A cell is pooled only when its wet neighbours' surfaces
  are level with it to within a tenth of the cell's own relief. Pooling every partly dry cell made
  moving water creep across dry ground (twice the true wet area in the bowl test), and a gradual
  blend instead of a switch let rounding noise in a still lake grow. The bed-slope term is
  rewritten so a flat surface feels no net force; where water covers a cell it equals the paper's.

Changed after the first run: the front check was set up as "the 1 cm contour within 3% of the
distance travelled". It failed with every setting tried (13-45 m behind at 5 m cells) and did not
improve with finer cells, because the last 20 m of a frictionless dry-bed wave is under 1 cm deep.
The gate now measures the front where water is 10 cm deep, 1% of the dam's depth, and requires
the gap to shrink as cells get finer. It is 2-4 cells behind at every cell size, which at 30 m
cells is about 0.2% of the 60 km valley. The 1 cm figure is still printed as an INFO line.

## P0 spike: Teesta terrain for the browser

```
.venv\Scripts\python pipeline\scripts\p0_terrain.py --project master-bruin-515809-p2
```

About a minute on Earth Engine. It traces the river from South Lhonak lake to Chungthang on MERIT
Hydro's flow directions (74 km). It keeps the Copernicus GLO-30 elevation (2024 edition) within
5 km of the river, on a 30 m UTM 45N grid, and writes the web package to
`web/public/data/teesta/terrain/`. A good run (26 Nov 2026) ends with **3 of 3 checks passed**:

- the lake surface reads 5,194 m (expected 5,100-5,300 m)
- the Teesta at Chungthang reads 1,531 m (expected 1,400-1,900 m)
- all three height levels come to 2.05 MB as a web server sends them, gzip-compressed (budget 3 MB)

The corridor covers 742 km² and runs from 1,296 to 6,878 m. A shaded map of it is in
`docs/p0/terrain-corridor.png`. The browser side, and its frame-rate test, is described in
`web/README.md`. Measured on this laptop's Iris Xe at 1152 × 1080, it holds 60 fps with no
frame over 20 ms, for the whole valley turning and for a low flight down the river. It still
does so with the terrain drawn twice per frame (`docs/p0/terrain-bench.json`).

## P0: one-page data checks for the test events

```
.venv\Scripts\python pipeline\scripts\p0_events.py --project master-bruin-515809-p2
```

Checks Gongbatongsha 2016, Thame 2024 and Kedarnath 2013 (add `--event thame` for one). For each,
it covers:

- **Route:** the flood route on MERIT Hydro, and how close it passes the named town.
- **Terrain:** the GLO-30 corridor around the route.
- **Lake:** its area in the autumns before and after, where satellites can see it.
- **Imagery:** clear Sentinel-2 and Landsat scenes within 120 days either side of the date.
- **Rain:** GPM IMERG rain over the days before.

Findings and verdicts are written up in `docs/p0/events.md`. The facts behind each event, with
their sources, are in `moraine/events.py`.

## P1: the glacial lake inventory used as labels

```
.venv\Scripts\python pipeline\scripts\p1_inventory.py
```

This fetches the Zhang et al. (2023) Third Pole inventory (Zenodo 10.5281/zenodo.8369314, CC BY
4.0, 17.3 MB). It holds hand-drawn Sentinel-2 outlines of the 5,894 glacial lakes of at least
0.02 km² within 10 km of a glacier, for 2018, 2020 and 2022.

The script saves the zip to `pipeline/data/zhang2023/`, which stays out of git, and checks it
against the published MD5. It then tests the outlines against what P0 measured. A good run ends
with **7 of 7 checks passed**: South Lhonak within 2.2% of P0 in every year, Thame's breached lake
present, the two drained lakes absent, and every 2018 and 2020 outline paired with its 2022 lake.

The three year files list the same lakes in **different orders**, so never pair lakes across years
by their position in the file. Use `inventory.match()`, which pairs them on the listed areas (the
2022 file repeats each lake's 2018 and 2020 area). The P1 plan is in `docs/p1/plan.md`.

```
.venv\Scripts\python pipeline\scripts\p1_study_areas.py --project master-bruin-515809-p2
```

Builds the study areas: the whole catchment draining to the end of each P0 flood route, from
HydroSHEDS level-12 basins. It writes them to `pipeline/moraine/study_areas.geojson` and counts the
inventory lakes in each. A good run ends with **12 of 12 checks passed**: each catchment closes
inside its search box, holds its key lake, and holds exactly the lakes MERIT Hydro's own catchment
holds. North Sikkim has 101 inventory lakes, Bhote Koshi/Poiqu 36 and Khumbu 54 (89, 32 and 45 of
them at least 0.02 km² in 2022; the inventory keeps a lake that reached that size in any year).

```
.venv\Scripts\python pipeline\scripts\p1_baseline.py --project master-bruin-515809-p2
```

P1 step 3, the simple lake mapper (`moraine/watch.py`): Sentinel-2 autumn composites, water where
NDWI > 0.25 on slopes under 12°, patches of at least 0.02 km². It scores both rule variants against
the inventory for 2018, 2020 and 2022 in the three study areas. A good run ends with the NDWI rule
finding **449 of 505** inventory lakes (overlap at least 0.5), lake area 9.1% low. It also reports
the water it maps away from inventory lakes, which is partly error and partly lakes the inventory
does not list.

- **Time:** about 1–2 hours on Earth Engine.
- **Cache:** each area-year is saved in `pipeline/out/p1_baseline/cache/`, stamped with a
  fingerprint of `watch.py` and the lake list, so a rerun skips finished work and recomputes anything
  made by older code.
- **Run one copy at a time.** Check that no earlier run is still going before starting another.
- **Sum at 10 m.** Over a whole study area, Earth Engine requests at 30 m lose mapped water.
- **Quota:** the Community tier allows 150 EECU-hours a month. Past that, the project runs in
  restricted mode until the 1st of the next month.

```
.venv\Scripts\python pipeline\scripts\p1_hard_cases.py --project master-bruin-515809-p2
```

P1 step 4, the hard-case set (`moraine/hard_cases.py` flags, `moraine/tiles.py` tiles). It
measures ice, terrain shadow, thin cloud and silt for every inventory lake in every
September–December scene of the inventory years. It then picks the strongest cases per category,
exports each as a 256 × 256 tile of 10 m cells to `pipeline/data/p1_hard_cases/` (not in git), and
draws contact sheets in `pipeline/out/p1_hard_cases/sheets/`.

- **Visual check:** cases that fail it are listed with a reason in
  `docs/p1/hard-case-review.json`. After a change that adds candidates, look at the new ones
  before trusting the results.
- **Good run:** ends with **8 of 8 checks passed**, 49 test cases (North Sikkim) and 49 validation
  cases. The baseline scores a median overlap of 0.46 on the hard test cases against 0.86 on clear
  ones (overlap with every inventory lake within 500 m of the case lake, `tiles.score`).
- **Time:** about 25 minutes the first time, then a minute from the caches.

P1 step 5, the lake U-Net (`moraine/training.py`, `moraine/unet.py`), in three commands:

```
.venv\Scripts\python pipeline\scripts\p1_unet_data.py --project master-bruin-515809-p2
```

```
.venv\Scripts\python pipeline\scripts\p1_unet.py --epochs 25
```

```
.venv\Scripts\python pipeline\scripts\p1_unet_report.py
```

- **Data:** the first command exports about 2,700 training tiles from lakes outside every study
  area to `pipeline/data/p1_unet/` (not in git). It takes about 30 minutes and resumes if stopped.
- **Training:** the second trains and keeps the pass that scores best on the validation hard cases.
  It takes about 2 hours on the laptop's CPU. On a free GPU it takes 7 minutes: run
  `pipeline\scripts\p1_unet_bundle.py`, upload `pipeline/data/p1_unet_bundle.zip` to a `MORAINE`
  folder in Google Drive, and run `pipeline/notebooks/p1_unet_colab.ipynb` in Colab. Then put
  `model.pt` and `history.json` in `pipeline/data/p1_unet/`.
- **Report:** the third scores the model on the validation cases. A good run gives a mean overlap
  of **0.768 against the baseline's 0.454**, better on 40 of 49 cases.
- **No slope input.** The U-Net never sees slope, only the 12° mask: GLO-30's flattened lakes
  would hand it 2011–2015 lake outlines.

```
.venv\Scripts\python pipeline\scripts\p1_gate.py
```

P1 step 6, the gate: the U-Net and both baseline rules on the held-out North Sikkim cases. The
criteria are in the script's docstring and were committed before it first ran. A good run ends with
**GATE PASSED**: on the 39 hard cases, overlap 0.729 for the U-Net against 0.405 for the better rule,
95% interval of the difference +0.21 to +0.45. It needs no Earth Engine and takes about a minute.

```
.venv\Scripts\python pipeline\scripts\p1_growth.py --project master-bruin-515809-p2
```

P1 step 7a, growth curves 2017–2025 (`moraine/growth.py`): every inventory lake's area each autumn
in the three study areas, mapped by the U-Net, so it needs `pipeline/data/p1_unet/model.pt`.

- **Good run:** ends with **5 of 5 checks passed**. 1,572 of 1,719 lake-autumns are mapped, the
  median lake comes out 4.5% above its listed area, and South Lhonak is within 1.5% of the inventory
  and 0.20 km² smaller after the October 2023 outburst. It writes `docs/p1/growth.json` and
  `docs/p1/growth.png`.
- **Time:** about 45 minutes of flags and an hour of maps the first time. Both are cached
  (`pipeline/out/p1_growth/`, `pipeline/data/p1_growth/`), so a stopped run resumes where it left
  off. Keep the laptop on: a shutdown stops the run.
- **Tiles off the edge of a scene:** step 4's coverage flag cannot see them, so the script checks
  every tile it fetches and tries the next scene, or the overlapping granule of the same date.

## Chorabari (Kedarnath) is not measured from satellites

Even generous composites of 1990-2012 Landsat find at most about 0.02 km² of water near the
lake point, against documented dimensions of about 400 × 200 m. The lake was small, silty and
often shaded, below what 30 m Landsat can track. The flood model uses its documented size and
volume instead (`CHORABARI_DOCUMENTED` in `moraine/references.py`).
