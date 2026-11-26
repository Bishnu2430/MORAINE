# P1 Watch: plan

Weeks 4–7 of the plan. **Deliverable:** lake outlines for Sikkim and both Nepal study areas, the
simple water-index method and a U-Net side by side, and growth curves. **Gate:** the U-Net beats
the simple method on held-out hard cases (mountain shadow, frozen lakes, thin cloud, silty water)
in Sikkim.

## Decisions going in

- **Labels.** Zhang et al. (2023), *Enhanced glacial lake activity threatens numerous communities
  and infrastructure in the Third Pole*, Nature Communications. Its dataset
  ([Zenodo 10.5281/zenodo.8369314](https://zenodo.org/records/8369314), CC BY 4.0, 17.3 MB) gives
  hand-drawn Sentinel-2 outlines of every glacial lake of at least 0.02 km² within 10 km of a
  glacier, for 2018, 2020 and 2022.
  - The U-Net trains on lakes outside the three study areas and is tested on Sikkim, so no test
    lake leaks into training.
  - Fallback for the Landsat years: the Hi-MAG database (Chen et al. 2021, annual 2008–2017, 30 m).
- **Size cut-off.** 0.02 km² from 2017 on (Sentinel-2, 10 m), matching the inventory and the P0
  evidence: Thame's 0.044 km² lake measured well, while Gongbatongsha's 0.017 km² lake did not.
  For 1987–2016 (Landsat, 30 m) the cut-off is 0.05 km², about 55 cells.

## Steps, each with its own check

1. **Fetch the inventory and test it against what P0 measured.** Done 26 Nov 2026
   (`pipeline/scripts/p1_inventory.py`), 7 of 7 checks passed (`inventory-checks.json`).
   - **South Lhonak:** 1.452, 1.534 and 1.671 km² in 2018, 2020 and 2022, against P0's
     Sentinel-2 composites of 1.485, 1.551 and 1.644 km² (within 2.2% every year).
   - **Thame's breached lake:** listed every year at 0.044–0.047 km².
   - **Gongbatongsha and Chorabari:** both absent, as they had drained.
   - **Contents:** 5,894 lakes in every year's file. Only the 2022 file carries attributes,
     including each lake's area in 1990, which is useful for growth curves.
   - **Correction (added during step 3):** the files list the same lakes but **not in the same
     order**; only about a third sit at the same position. This was first written down as "same
     order" without a test, and step 3's first scoring of 2018 and 2020 used the wrong outlines
     because of it. A seventh check now pairs each 2022 lake with its 2018 and 2020 outline on the
     listed areas (the 2022 file repeats them): 5,888 and 5,884 of 5,894 pair up. The six original
     checks were unaffected, since they look lakes up by location in each file.
   - **Bonus:** the paper rates South Lhonak's hazard "Very high". Its dataset went online on 22 Sep
     2023, twelve days before the lake burst.
2. **Study areas.** Done 26 Nov 2026 (`pipeline/scripts/p1_study_areas.py`), 12 of 12 checks
   passed. Each area is the whole catchment draining to the end of its P0 flood route, built from
   HydroSHEDS level-12 basins. The outlines are in `pipeline/moraine/study_areas.geojson`, with
   maps in `study-area-*.png`.

   | Area | Catchment | Inventory lakes (≥ 0.02 km² in 2022) | Lake area 1990 → 2022 | Hazard very high / high |
   |---|---|---|---|---|
   | North Sikkim (Teesta above Chungthang) | 2,848 km² | 101 (89) | 15.5 → 20.7 km² | 17 / 24 |
   | Bhote Koshi / Poiqu above Barabise | 2,516 km² | 36 (32) | 11.6 → 18.2 km² | 9 / 7 |
   | Khumbu (Bhote and Dudh Koshi below Thame) | 1,315 km² | 54 (45) | 4.3 → 6.7 km² | 4 / 10 |
   | Mandakini (Kedarnath; count only) | 334 km² | 2 (2) | 0.04 → 0.07 km² | 0 / 0 |

   - **Lake counts:** the inventory keeps a lake that reached 0.02 km² in any of its years, so some
     are smaller in a given year (640 of 5,894 in 2022). This column first called all 101 Sikkim lakes
     "≥ 0.02 km² in 2022"; corrected during step 3.

   - **Area check:** Sikkim and Bhote Koshi agree with MERIT Hydro's drainage area within 3%.
     Khumbu runs 16% larger and Mandakini 30%, because the HydroSHEDS block holding each outlet
     reaches downstream of it.
   - **Why that's fine:** an area-match gate first failed for those two. The gate is now that each
     outline holds exactly the lakes MERIT's exact catchment holds, which it does in all four. The
     extra strip has no lakes.
   - **Scale:** 191 lakes across the three study areas.
3. **Simple method at scale.** Done 26 Nov 2026 (`pipeline/scripts/p1_baseline.py`, chart
   `baseline-scores.png`, numbers `baseline-summary.json`).
   - **Method:** a Sentinel-2 autumn composite (Level-1C, 1 Sep–15 Nov, 80th percentile) for each
     study area and inventory year; water where NDWI > 0.25 on slopes under 12°, in patches of at
     least 0.02 km², masked where fewer than 3 scenes saw the ground.
   - **Scoring:** each inventory lake listed at 0.02 km² or more that year and seen by 3+ scenes;
     found means an overlap (IoU) of at least 0.5 inside a 60 m buffer.

   | Area | Found 2018 / 2020 / 2022 | Median IoU | Mapped vs inventory area | Water away from inventory lakes |
   |---|---|---|---|---|
   | North Sikkim | 80/89, 83/93, 80/89 | 0.83–0.86 | −10% to −13% | 3.7–4.9 km² (17–21% of mapped) |
   | Bhote Koshi / Poiqu | 31/33, 31/33, 31/32 | 0.88–0.90 | −4% to −5% | 2.4–4.4 km² (12–20%) |
   | Khumbu | 37/43, 38/48, 38/45 | 0.80–0.83 | −11% to −16% | 1.5–2.2 km² (21–29%) |

   - **Overall:** 449 of 505 lakes found (88.9%), lake area 9.1% low. The method under-maps the
     ice-choked and shaded margins of lakes; its errors are the hard cases of step 4
     (`baseline-south-lhonak-2022.jpg`: the glacier end of South Lhonak missed, one false patch in a
     glacier's shadow).
   - **Water away from inventory lakes** is reported, not scored as false: part of it is real lakes
     the inventory leaves out, since it lists only glacial lakes within 10 km of a glacier
     (`baseline-unlisted-lake-2022.jpg`).
   - **Variant:** adding MNDWI > 0.10 found 448 instead of 449, lost 0.6 km² at inventory lakes and
     trimmed 0.9 km² (3%) of the water elsewhere, a tie. The baseline is the simpler NDWI rule. The
     MNDWI rule is meant for exactly the hard cases, so step 6 tests the U-Net against both.
   - **Lessons, each found and fixed during this step:**
     - The inventory year files list lakes in different orders (see step 1), so each year's lakes now
       come from that year's own file.
     - Whole-study-area requests at 30 m lose water: Sikkim 2022 summed to 13.4 km² of mapped water
       at 30 m against 21.7 km² at 10 m. Every sum now runs at 10 m. Counting extra lakes as vectors
       at 10 m exceeds Earth Engine's 5-minute limit, so water elsewhere is reported as an area.
     - A run left over from before a bug fix kept writing into the shared cache. Cached results now
       carry a fingerprint of `watch.py` and the lake list, and older ones are recomputed.
   - **Earth Engine quota:** these runs used up the Community tier's 150 EECU-hours for November,
     so the project is in restricted mode (slower, not blocked) until 1 December.
   - Every-autumn runs (2017–2025) move to step 7 and use only the NDWI rule.
4. **Hard-case set.**
   - Pick tiles of shadow, ice, thin cloud and silty water from the inventory lakes, using
     automatic flags with a quick visual check.
   - Keep the Sikkim tiles for the final test only.
5. **U-Net in Colab.** Train on Sentinel-2 patches plus slope outside the study areas, and save
   the model. A single notebook runs on a free GPU.
6. **The gate.** Run the U-Net and both rule variants from step 3 on the held-out Sikkim hard
   cases, and report IoU and area error per case. The U-Net must beat the better rule.
7. **Growth curves.** Area per year for every lake above the cut-off in the three study areas.
   - Back to 1987: Landsat, for lakes big enough to see.
   - From 2017: every autumn, with the better method from step 6.
   - The inventory's 1990 areas give a cross-check.
