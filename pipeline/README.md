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

No sign-in needed; it runs on the laptop CPU in about 3 minutes. What a good run looks like
(first run, 26 Nov 2026):

- It ends with **9 of 9 gate checks passed**. A dam holding 10 m of water fails onto a dry, flat,
  frictionless bed, and the solver matches Ritter's 1892 exact solution within 0.86% at 5 m cells.
  Halving the cells halves the error (order 1.03). The same dam break run along y gives an
  identical answer, run at 45° across the grid is within 0.75%, and run down a 30% slope is
  within 1.93%. Water volume is conserved to 2e-16, no depth ever went negative, and a lake at
  rest over a fully covered bed stays still to 6e-15 m/s.
- `pipeline/out/p0_solver/dam-break.png` shows the depth profile on top of the exact one, and the
  error falling as cells get finer.
- **INFO lines** feed P1's decisions:
  - *Shorelines.* A still lake with islands does not stay still: water deeper than 10 cm reaches
    about 2 m/s at the shores. Where a shoreline crosses a cell, the 2007 scheme tilts that cell's
    water surface. P1 replaces that step with the wet/dry reconstruction of Bollermann, Chen,
    Kurganov and Noelle (2013), and this line must drop to near zero.
  - *float32 at 5,200 m* is as accurate as float64 for the flood itself (0.83% against 0.86%), but
    volume drifts by about 1e-4 in 20 s, because each depth is the small difference of two large
    elevations. The real runs should store elevations relative to the lowest point in the valley.
  - *Speed* on this CPU is about 0.5-0.8 million cell-steps per second, far too slow for the
    valley runs, which need millions of cells over tens of thousands of 0.3 s steps. Those go on a
    Colab GPU; P1 measures how long one takes.

How the solver works (`moraine/swe.py`): the second-order central-upwind scheme of Kurganov and
Petrova (2007) in PyTorch, with walls on all sides and no friction yet. One change from the paper:
face velocities are built from cell velocities instead of face discharges from cell discharges.
With discharges, a film of water 1 mm thick ran ahead of the flood front at 24 m/s, faster than
the 19.8 m/s the physics allows, and near shorelines the solver needed five times as many time
steps.

Changed after the first run: the front check was set up as "the 1 cm contour within 3% of the
distance travelled". It failed with every setting tried (13-45 m behind at 5 m cells) and did not
improve with finer cells, because the last 20 m of a frictionless dry-bed wave is under 1 cm deep.
The gate now measures the front where water is 10 cm deep, 1% of the dam's depth, and requires
the gap to shrink as cells get finer. It is 2-4 cells behind at every cell size, which at 30 m
cells is about 0.2% of the 60 km valley. The 1 cm figure is still printed as an INFO line.

## Chorabari (Kedarnath) is not measured from satellites

Even generous composites of 1990-2012 Landsat find at most about 0.02 km² of water near the
lake point, against documented dimensions of about 400 × 200 m. The lake was small, silty and
often shaded, below what 30 m Landsat can track. The flood model uses its documented size and
volume instead (`CHORABARI_DOCUMENTED` in `moraine/references.py`).
