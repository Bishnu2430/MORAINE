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
   (`pipeline/scripts/p1_inventory.py`), 6 of 6 checks passed (`inventory-checks.json`).
   - **South Lhonak:** 1.452, 1.534 and 1.671 km² in 2018, 2020 and 2022, against P0's
     Sentinel-2 composites of 1.485, 1.551 and 1.644 km² (within 2.2% every year).
   - **Thame's breached lake:** listed every year at 0.044–0.047 km².
   - **Gongbatongsha and Chorabari:** both absent, as they had drained.
   - **Contents:** 5,894 lakes, the same lakes in the same order in every year's file. Only the
     2022 file carries attributes, including each lake's area in 1990, which is useful for growth
     curves.
   - **Bonus:** the paper rates South Lhonak's hazard "Very high". Its dataset went online on 22 Sep
     2023, twelve days before the lake burst.
2. **Study areas.** Done 26 Nov 2026 (`pipeline/scripts/p1_study_areas.py`), 12 of 12 checks
   passed. Each area is the whole catchment draining to the end of its P0 flood route, built from
   HydroSHEDS level-12 basins. The outlines are in `pipeline/moraine/study_areas.geojson`, with
   maps in `study-area-*.png`.

   | Area | Catchment | Lakes ≥ 0.02 km² (2022) | Lake area 1990 → 2022 | Hazard very high / high |
   |---|---|---|---|---|
   | North Sikkim (Teesta above Chungthang) | 2,848 km² | 101 | 15.5 → 20.7 km² | 17 / 24 |
   | Bhote Koshi / Poiqu above Barabise | 2,516 km² | 36 | 11.6 → 18.2 km² | 9 / 7 |
   | Khumbu (Bhote and Dudh Koshi below Thame) | 1,315 km² | 54 | 4.3 → 6.7 km² | 4 / 10 |
   | Mandakini (Kedarnath; count only) | 334 km² | 2 | 0.04 → 0.07 km² | 0 / 0 |

   - **Area check:** Sikkim and Bhote Koshi agree with MERIT Hydro's drainage area within 3%.
     Khumbu runs 16% larger and Mandakini 30%, because the HydroSHEDS block holding each outlet
     reaches downstream of it.
   - **Why that's fine:** an area-match gate first failed for those two. The gate is now that each
     outline holds exactly the lakes MERIT's exact catchment holds, which it does in all four. The
     extra strip has no lakes.
   - **Scale:** 191 lakes across the three study areas.
3. **Simple method at scale.** For every autumn from 2017 to 2025:
   - Build a Sentinel-2 composite.
   - Apply the water index plus an infrared water index, a slope mask and a shadow mask.
   - Produce outlines.
   - Score them against the inventory years: IoU, area error and lakes missed or invented.
4. **Hard-case set.**
   - Pick tiles of shadow, ice, thin cloud and silty water from the inventory lakes, using
     automatic flags with a quick visual check.
   - Keep the Sikkim tiles for the final test only.
5. **U-Net in Colab.** Train on Sentinel-2 patches plus slope outside the study areas, and save
   the model. A single notebook runs on a free GPU.
6. **The gate.** Run both methods on the held-out Sikkim hard cases, and report IoU and area error
   per case.
7. **Growth curves.** Area per year for every lake above the cut-off in the three study areas. Use
   Landsat back to 1987 for lakes big enough, and the better method from step 6 from 2017.
