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

Offline tests: `.venv\Scripts\python -m pytest pipeline\tests -q`

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

## Chorabari (Kedarnath) is not measured from satellites

Even generous composites of 1990-2012 Landsat find at most about 0.02 km² of water near the
lake point, against documented dimensions of about 400 × 200 m. The lake was small, silty and
often shaded, below what 30 m Landsat can track. The flood model uses its documented size and
volume instead (`CHORABARI_DOCUMENTED` in `moraine/references.py`).
