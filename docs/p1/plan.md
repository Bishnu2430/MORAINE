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
4. **Hard-case set.** Done 26 Nov 2026 (`pipeline/scripts/p1_hard_cases.py`), 8 of 8 checks
   passed. The cases are in `hard-cases.json`, the visual-check drops in `hard-case-review.json`,
   and the kept tiles with the baseline drawn on are in `hard-cases-test.jpg` and
   `hard-cases-validation.jpg`.
   - **A case** is one inventory lake in one Sentinel-2 scene (1 Sep–31 Dec of an inventory year,
     so that year's outline is the label). It becomes a 256 × 256 tile of 10 m cells, 2.56 km
     across, centred on the lake.
   - **Flags**, measured for 18,335 lake-scenes inside each lake and in the 1.3 km around it:
     - **Ice:** snow or ice on at least 30% of the lake, ranked toward partly frozen lakes.
     - **Shadow:** at least 20% of the lake in terrain shadow cast by that scene's sun.
     - **Thin cloud:** the lake brighter in red than on its own clear days that year, by between
       0.03 and 0.25: veiled, not white.
     - **Silty:** water bright in near-infrared (B8 ≥ 0.09) with clear surroundings, so the
       brightness is silt rather than haze.
     - **Clear:** none of the above, and no cloud within 1.3 km. This is the control.
   - **The flags never look at a lake map or at what the baseline finds**, so the cases are not
     chosen for being hard for one method.
   - **Visual check:** a case was dropped if no part of its lake could be told apart by eye, or if
     its flag was plainly wrong. 16 of the 182 candidates were dropped, all thin cloud: 7 because the
     lake was hidden and 9 because no cloud was over the lake. Another 17 ran off the edge of their
     scene and were dropped automatically.
   - **Split:** North Sikkim gives the test set, 49 cases on 36 lakes, used only in step 6.
     Bhote Koshi and Khumbu give a validation set of 49 cases that step 5 may tune against.

   - **Score:** overlap (IoU) between a lake map and every inventory lake within 500 m of the case
     lake's bounding box. Mapped water where there is no lake counts against it. (Step 4 first
     scored only the 60 m round the case lake, as step 3 did; step 5 found that painting the whole
     tile as lake scored 0.56 that way, against about 0.1 now. That narrower measure is still
     reported as `lake_iou`.)

   | Baseline (NDWI rule), median overlap | Ice | Shadow | Thin cloud | Silty | Clear |
   |---|---|---|---|---|---|
   | Test, North Sikkim | 0.16 (10) | 0.38 (10) | 0.50 (9) | 0.65 (10) | 0.86 (10) |
   | Validation, Bhote Koshi and Khumbu | 0.00 (10) | 0.80 (10) | 0.24 (10) | 0.33 (10) | 0.88 (9) |

   - **The cases are hard:** the baseline's median overlap on the hard test cases is 0.46, against
     0.86 on clear ones. It misses frozen lakes (4 of 10 test cases score zero; the rest score only
     for open lakes nearby), small lakes in deep shadow (5 of 10 zero), and brown silty water. The
     MNDWI variant differs on only 22 of the 98 cases, and only slightly.
   - **Weak spot, shadow:** North Sikkim's lakes are mostly on the open plateau, and only 6 are ever
     a fifth in shadow. The 10 test shadow cases therefore come from 5 lakes in different years, so
     they are less independent than the other categories.
   - **What went wrong first:** measuring the flags inside the lake only let cloud surround
     "clear" lakes and let haze pass as silt, and ranking ice by its share picked lakes buried under
     one snowfall. The neighbourhood measures and the ranking above fixed both.
   - **The tiles** (98 MB of .npz) are in `pipeline/data/p1_hard_cases/`, outside git. The script
     rebuilds them from `hard-cases.json`'s scenes, and `moraine/tiles.py` reads and scores them
     with numpy alone, so step 6 can run in Colab.
5. **U-Net in Colab.** Done 27 Nov 2026. Chart `unet-training.png`, every validation case in
   `unet-validation.json` and, as lake maps, in `unet-validation.jpg`.
   - **Training tiles** (`pipeline/scripts/p1_unet_data.py`): 3,500 inventory lakes at least 5 km
     outside all four study areas, each in one random inventory year and one random
     September–December scene. Each tile is 160 × 160 cells of 10 m in the lake's own UTM zone
     (42–48), with every inventory lake of that year as the label. 2,707 were kept: 772 were dropped
     because cloud hid the lakes and 21 because they ran off the scene. The kept scenes spread
     evenly over the four months (612, 717, 666, 712), so frozen and shadowed lakes are well
     represented.
   - **Inputs:** the six bands, NDWI, MNDWI, and only the baseline's own "steeper than 12°" mask.
     **Not slope itself:** GLO-30 levels lake surfaces flat (from radar of about 2011–2015). In the
     training tiles, ground flatter than 1° covers half of all lake cells and 0.5% of everything
     else, so a model given slope would copy those old outlines instead of reading the scene.
   - **Model and training** (`moraine/unet.py`, `pipeline/scripts/p1_unet.py`): a U-Net with 4.4
     million weights (24 channels at full resolution, 4 halvings). Training used random 128-cell
     crops with flips and rotations and a cross-entropy plus Dice loss, for 25 passes on Colab's T4
     GPU at about 16 seconds each (`pipeline/notebooks/p1_unet_colab.ipynb`). Its output keeps
     patches of 0.02 km² or more, as the baseline's does.
   - **Checkpoint:** the pass with the best mean score on the 49 validation cases, pass 11 (0.768).
     Scores wobble between passes on so few cases; passes 19–25 average 0.759, so the pick's edge is
     noise. The North Sikkim test cases were never read.

   | Validation, median overlap | Ice | Shadow | Thin cloud | Silty | Clear | Mean, all 49 |
   |---|---|---|---|---|---|---|
   | Baseline (NDWI rule) | 0.00 | 0.80 | 0.24 | 0.33 | 0.88 | 0.454 |
   | U-Net | 0.84 | 0.83 | 0.70 | 0.81 | 0.93 | 0.768 |

   - **Case by case:** the U-Net is better on 40 of the 49 cases and worse on 3 (two shadowed Bhote
     Koshi lakes and one clear one, where it maps a little water beside the lake); 6 are within
     0.02.
   - **Its mistakes:** bright snow patches mapped as lake, and a lake behind a gap in the cloud.
   - **The model** is `pipeline/data/p1_unet/model.pt` (17.5 MB, outside git, sha256
     `d787c41dc22c6aa9…`, in `unet-validation.json`). `pipeline/scripts/p1_unet_report.py`
     rebuilds the report from it.
6. **The gate. Passed 27 Nov 2026** (`pipeline/scripts/p1_gate.py`). Every case is in
   `gate.json`, the chart is `gate.png`, and the U-Net's maps on every test case are in
   `gate-cases.jpg`.
   - **Criteria, committed before the script read a test case** (commit c4c91f0):
     1. The model is step 5's, by sha256.
     2. On the hard test cases, the U-Net's mean overlap beats the better of the two rule variants.
     3. Resampling lakes rather than cases, the 95% interval of the difference lies above zero.
   - **Result:** on the 39 hard North Sikkim cases (28 lakes), the U-Net's mean overlap is
     **0.729 against 0.405** for the better rule (NDWI with MNDWI). The difference is +0.32, with a
     95% interval of +0.21 to +0.45. The U-Net is better on 33 cases, worse on none, and within 0.02
     on 6.

   | North Sikkim test, median overlap | Ice | Shadow | Thin cloud | Silty | Clear |
   |---|---|---|---|---|---|
   | NDWI rule | 0.16 | 0.38 | 0.50 | 0.65 | 0.86 |
   | U-Net | 0.77 | 0.87 | 0.76 | 0.87 | 0.89 |
   | Median area error of the case lake, rule / U-Net | 100% / 6% | 70% / 10% | 52% / 11% | 36% / 4% | 4% / 3% |

   - **Where the U-Net still fails:**
     - **One small lake in deep shadow** (shadow-01, 07 and 08, the same lake in three years):
       both methods score zero. These are three of the six ties.
     - **Bright snow patches mapped as lake** (ice-02, 04, 09), which lowers its scores but stays
       above the rule's.
     - **One frozen lake missed** (ice-05).
   - **Clear controls:** 0.89 against the rule's 0.86, worse on one (clear-02, 0.77 against 0.85).
     So the U-Net gives up nothing on easy scenes.
   - **Limits of the test:**
     - 39 hard cases from 28 lakes, and shadow has only 5 lakes.
     - The truth is the inventory's hand-drawn outline of that year, not a field survey.
     - The cases were chosen by automatic flags and checked by eye, so they are hard cases of
       these four kinds, not a random sample of scenes.
     - The model was trained once. A second training run would give a somewhat different model,
       and its spread is not measured.
7. **Growth curves.** Area per year for every inventory lake in the three study areas, in two
   parts.
   - **7a, 2017–2025, with the U-Net. Done 28 Nov 2026** (`pipeline/scripts/p1_growth.py`,
     `moraine/growth.py`). Every lake and autumn is in `growth.json`, and the chart is
     `growth.png`.
     - **Scenes:** for each lake and autumn (1 September–15 November), Sentinel-2 scenes are
       ranked clear first (little cloud within 1.3 km of the lake), then thin cloud. Scenes with
       20% or more of the lake in terrain shadow are skipped. The first three, one per date, whose
       tile lies wholly inside the scene are mapped.
     - **Mapping:** the U-Net maps each scene, and the median of its lake probability across the
       scenes gives the autumn's map.
     - **A lake's area** is the mapped water joined to any of its inventory outlines (2018, 2020 or
       2022). Water inside an outline belongs to that lake; the rest of a patch goes to the lake
       whose outline is nearest through the water. So a lake that grows past its old outline is
       still counted in full, and a patch touching two lakes is shared, not counted twice.
   - **7a checks, fixed before the run:**
     1. Lake-autumns with a usable scene: at least 90%.
     2. Inventory years, lakes of 0.02 km² or more: the median ratio of mapped to listed area is
        within 10% of 1.
     3. Inventory years, each study area's total within 10% of the inventory's.
     4. South Lhonak within 5% of the inventory in 2018, 2020 and 2022.
     5. South Lhonak's 2023 scenes show the outburst of 3–4 October: the median area after it is at
        least 0.15 km² below the median before it.
   - **Result: 5 of 5 passed** on 191 lakes (101 North Sikkim, 36 Bhote Koshi / Poiqu, 54
     Khumbu).

   | Check | Result |
   |---|---|
   | 1. Lake-autumns with a usable scene | 1,572 of 1,719 (91.4%) |
   | 2. Median mapped / listed area, 453 lake-years | 1.045 |
   | 3. Study-area totals against the inventory | +2% to +5% in all nine area-years |
   | 4. South Lhonak against the inventory, 2018 / 2020 / 2022 | +0.8% / +1.5% / −0.3% |
   | 5. South Lhonak, drop across the 2023 outburst | 0.197 km² (3 scenes before, 10 after) |

   - **Bugs found by looking at the maps.** A first run passed all five checks, but its maps had
     three bugs the checks were too coarse to see. The thresholds were not changed.
     - **Tiles off the edge of a scene:** step 4's coverage flag reads 100% for a lake half off
       the edge, because cells off the edge are masked and a mean skips them. Such tiles gave two
       Bhote Koshi lakes 0.03–0.07 km² instead of 0.25–0.33. Each tile is now checked when
       fetched: 601 of the 4,729 fetched (13%) were cut. Where two 100 km granules overlap, the
       other one is tried. With the check alone, check 1 fell to 89.8%, a narrow fail; trying the
       other granule brought it to 91.4%.
     - **Shadow counted twice:** a ridge shadow mapped as water touched two small Khumbu ponds, and
       each was given all 0.29 km² of it. Patches are now shared by nearest outline, and shadowed
       scenes are skipped (41 of the 3,761 first chosen).
     - **A missing pairing:** the 2022 file rounds a few earlier areas to two decimals, so a 1.1 km²
       North Sikkim lake (4827) had no 2018 or 2020 outline, and the chart's inventory totals came
       out 1.1 km² low. `inventory.match` now has a rounded fallback (6 lakes unpaired with 2018
       and 10 with 2020, of 5,894). Only this step uses it, so steps 4–6 are unchanged.
   - **What the curves show:**
     - **Totals,** over lakes mapped every autumn and listed in every inventory year: North Sikkim
       (73 lakes) grows from 17.3 to 18.1 km², 2017–2025, +5%. Bhote Koshi / Poiqu (29) stays
       between 17.3 and 17.8. Khumbu (24) swings between 4.6 and 5.1, mostly because of Imja
       (below).
     - **South Lhonak:** 1.43 km² in 2017, 1.67 in 2022 and 1.70 in September 2023. After the
       outburst each scene gives 1.38–1.51, then 1.47 in 2024 and 1.49 in 2025. The Sikkim
       government's Sentinel-2 figure, 162 to 144 ha, agrees; ISRO's radar figure, 167 to 60 ha,
       does not. The 2023 autumn value is the lake before the outburst, since two of its three
       clearest scenes are from September; every 2023 scene is in `growth.json`.
     - **Large lakes are steady:** the largest, 5.5 km² in Poiqu, is within 0.3–1.8% of the
       inventory in all three years, and most lakes over 0.3 km² stay within a few percent.
     - **Small lakes read high:** median mapped / listed is 1.08 for lakes of 0.02–0.05 km², 1.05
       for 0.05–0.2 and 1.02 above. That fits the mapped edge sitting about half a cell outside
       the inventory's outline.
   - **Where it still fails:**
     - **Imja Tsho** (Khumbu, 1.7 km²): in 2021, 2023 and 2025 the U-Net leaves out the lake's
       eastern end, bright water full of small icebergs at the glacier front. Those autumns read
       1.37, 1.36 and 1.45 km² against 1.6–1.75 in the years between. Filling enclosed gaps does
       not help, as the gap opens onto the glacier. The fix belongs in the model: training
       examples of calving fronts.
     - **Two ponds of about 0.02 km² on a Khumbu glacier** (4517, 4776) still read 0.05–0.10 km² in
       some years, from shadow beside them.
     - **Lake 4215** (North Sikkim, 0.05 km²) reads zero from 2023. In the scenes it looks filled
       with sediment; that is not checked against any other source.
     - **147 lake-autumns have no map:** 133 for want of a clear scene, 13 because every scene was
       cut by an edge, and 1 for shadow. Khumbu has 92 of them: 62 for cloud, 20 for ice or shadow
       on the lake and 10 cut by an edge.
   - **7b, 1988–2016, with Landsat** (`pipeline/scripts/p1_landsat.py`, `moraine/landsat.py`).
     - **Lakes:** the 114 of the 191 that reach 0.05 km² (about 55 Landsat cells) in 1990, 2018,
       2020 or 2022: 61 in North Sikkim, 28 in Bhote Koshi / Poiqu, 25 in Khumbu.
     - **Scenes:** Landsat 4, 5, 7 and 8 top-of-atmosphere scenes of 1 September–15 November,
       their bands renamed to the Sentinel-2 ones they match. A survey of scene counts (no lake
       maps) found none in 1987, none for Bhote Koshi or Khumbu in 1990, and none for Sikkim in
       1995. Landsat 7 has striped gaps from mid-2003 and is the only Landsat in 2003 and 2012.
     - **Flags** as in 7a, with coverage counted so that cells off the scene or in a gap count as
       uncovered. Cloud was first taken from each scene's own cloud mask (QA_PIXEL); after the first
       run it is a spectral test instead (see the runs, below). The checks did not change.
     - **Choosing scenes and areas** as in 7a: up to three scenes per autumn, one per date, whose
       10 m tile (resampled from 30 m) has no empty cell; the median of their lake probability; the
       same attribution to inventory outlines. A striped Landsat 7 scene passes only where the tile
       misses every stripe.
     - **Mapper, chosen by rule before any history is mapped:** both the step 3 NDWI rule and the
       U-Net map the Landsat 8 scenes of the inventory autumns (2018, 2020, 2022), and the one whose
       mapped / listed areas have the smaller median |log ratio| maps 1988–2016.
     - **Open-water gate, added after the second run** (see the runs, below). A cell the mapper
       calls water counts only within 30 m (one Landsat cell) of a cell that is open water by its
       bands: near-infrared (B8) and shortwave (B11) both at or below thresholds taken from Landsat 8.
       - Snow and ice are bright in near-infrared; debris, rock and dry sediment are bright in
         shortwave. Water is dark in both, and turbid water is lighter only in near-infrared.
       - The 30 m allowance keeps the lake's edge cells, which at 30 m mix water with shore.
       - **Thresholds:** the 98th percentile of each band, each lake weighted equally, over cells at
         least 30 m inside the outlines of stable lakes. Stable means listed at 0.05 km² or more in
         2022, with the 2018, 2020 and 2022 areas within 10% of each other. The cells come from the
         tier 1 Landsat 8 scenes of autumn 2022 that the selection keeps.
       - **When the percentile was chosen:** after a diagnostic on those same cells, and before any
         1988–2016 map was gated or compared with 1990. The diagnostic gave near-infrared 0.018 at
         the median, 0.142 at the 98th percentile and 0.178 at the 99th; shortwave 0.008, 0.103 and
         0.157. The 99th is pulled up by a few Khumbu lakes with ice or islands inside.
       - The gate applies to both mappers before the mapper is chosen, and to every year. The checks
         did not change.
       - So 7b measures open water: the frozen or snow-covered part of a lake more than 30 m from
         open water is not counted. Step 7a (Sentinel-2) is not gated.
   - **7b checks, fixed before the run** (lakes of 0.05 km² or more):
     1. At least 90% of lake-windows have a mapped autumn, the windows being 1988–1992, 1993–1997,
        1998–2002, 2003–2007, 2008–2012 and 2013–2016.
     2. Landsat 8, inventory autumns, the chosen mapper: median mapped / listed area within 10%
        of 1.
     3. The same lake-autumns against 7a's Sentinel-2 areas: median ratio within 10% of 1, so the
        two series join without a step.
     4. Against the inventory's 1990 areas (lakes of 0.05 km² or more then), using each lake's
        mapped autumn nearest 1990 within 1988–1992: median ratio within 15% of 1. Wider than 7a's
        10%, for 30 m cells and an inventory year that may be a nearby year.
     5. The same, each study area's total within 20% of the inventory's.
     6. South Lhonak within 20% of its 1990 area, and its latest autumn of 2014–2016 within 10% of
        7a's 2017 area.
   - **7b runs.**
     - **First run, cloud from QA_PIXEL: 3 of 6 checks passed.**
       - The scene cloud mask calls the cold, bright moraines and glaciers cloud. The median
         lake-scene came out 98–100% cloudy, so few autumns had a usable scene.
       - Only 49 Landsat 8 lake-autumns chose the mapper (U-Net 0.045 against the rule's 0.103), and
         172 of 684 lake-windows were mapped.
       - Checks 2–4 passed (0.973, 0.964, 1.038 over 19 lakes). Checks 1, 5 (Khumbu had no lake) and
         6 (no South Lhonak autumn) failed.
       - Replaced by the spectral cloud test, checked by eye on 8 scenes.
     - **Second run, spectral cloud test: 4 of 6 checks passed.**
       - The U-Net was chosen on 290 lake-autumns (0.047 against the rule's 0.164). 2,402
         lake-autumns of 1988–2016 were mapped.
       - Passed: check 1 (619 of 684), check 2 (1.022), check 3 (0.985 over 275) and check 4
         (1.092 over 82 lakes).
       - Failed, check 5: Sikkim +6%, Bhote Koshi +53%, Khumbu +18%.
       - Failed, check 6: South Lhonak 1991 was +74.8% of its 1990 area of 0.491 km², though 2016
         was within 1.6% of 2017.
       - **The cause, seen in false colour** (shortwave, near-infrared, green): on Landsat 5 and 7,
         the U-Net calls water much of the ground that the lake fills by 2022. Snow on a flat
         glacier tongue, glacier ice, debris and dry or silty lake bed were all counted.
       - South Lhonak's 1991 open water looks like the inventory's 0.49 km². The extra came from the
         glacier tongue to its west. Lakes 4629, 4630, 4646, 4680, 4688 and 4690 show the same.
       - The model makes the snow error on Sentinel-2 too: flat snow next to a lake looks like a
         frozen lake, which the training outlines include.
       - The errors run one way. 46 of the 82 lakes were within 15% of 1990. The 14 lakes above
         1.3 times held 6.79 of the 27.11 km² listed in 1990.
       - Hence the open-water gate above.
