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
   <https://code.earthengine.google.com/register>, choose unpaid, non-commercial use for academic
   research, and create or pick a Google Cloud project. Note the project ID.

3. **Sign in on this laptop.** A browser window opens; use the same Google account.

   ```
   .venv\Scripts\earthengine authenticate
   ```

## P0 spike: South Lhonak lake area

```
.venv\Scripts\python pipeline\scripts\p0_lake_area.py --project YOUR-PROJECT-ID
```

It takes a few minutes. You can also set `EE_PROJECT` once instead of passing `--project`.

What a good run looks like:

- It ends with **3 of 3 checks passed**: about 1.65 km² just before the October 2023 outburst,
  about 0.60 km² just after it, and 1.1 to 1.3 km² for 2014 to 2016.
- `pipeline/out/p0_lake_area/south_lhonak_area.png` shows the lake growing from the late 1980s,
  then dropping sharply at the outburst.

If a check fails, everything is still written to `pipeline/out/p0_lake_area/`. To redo the tables
and chart without calling Earth Engine again, pass `--from-csv pipeline\out\p0_lake_area\scenes_raw.csv`.

Offline tests: `.venv\Scripts\python -m pytest pipeline\tests -q`

## How the measurement works

- **Where to measure:** the lake's largest outline in JRC Global Surface Water (1984 to 2021),
  widened by 200 m for growth since then.
- **Each scene:** every autumn (September to November) image from Landsat 5, 7, 8, 9 and
  Sentinel-2. Cloud and cloud-shadow pixels are removed using each product's own quality band.
  A pixel counts as water when NDWI (green against near-infrared) is above 0.25. The 0.15 and
  0.35 cut-offs are recorded too, to show how much the answer depends on that choice.
- **Each year:** the median of the scenes where at least 95% of the measuring area is clear,
  between 1 September and 15 November. 2023 is split at the outburst.

Known limits: Landsat 7 images after 2003 have striped gaps, so most get dropped; 2012 has no
good sensor over the lake; a frozen or snow-covered lake reads as dry; mountain shadow inside
the 200 m margin can read as water.
