"""Study lakes and the published figures the pipeline is checked against.

Every number here names its source, so a failed check can be traced to what it was compared with.
"""

SOUTH_LHONAK = {
    "name": "South Lhonak",
    # Between Wikipedia (27.914 N, 88.184 E) and EGU24-18788 (27.912 N, 88.198 E); only used to find the lake
    "lon": 88.191,
    "lat": 27.913,
    # The lake kept growing west toward its glacier after 2021, past the JRC outline; these
    # Sentinel-2 autumns add that growth to the measuring area
    "recent_years": list(range(2017, 2027)),
    "margin_m": 100,
    # The flood reached Chungthang around 00:30 on 4 Oct 2023; scenes dated 3 Oct are before the breach
    "event_date": "2023-10-04",
    "event_label": "4 Oct 2023",
    # Year-only figures are placed in mid-October. "note" offsets (points) give a value a written label on the chart.
    "published": [
        {"date": "1976-10-15", "area_km2": 0.20, "label": "1976",
         "source": "Natural Hazards 2018, doi:10.1007/s11069-018-3305-0"},
        {"date": "2014-10-15", "area_km2": 1.26, "label": "2014", "source": "AGU Fall Meeting 2015 abstract"},
        {"date": "2016-10-15", "area_km2": 1.31, "label": "2016",
         "source": "Natural Hazards 2018, doi:10.1007/s11069-018-3305-0"},
        {"date": "2016-10-15", "area_km2": 1.12, "label": "2016",
         "source": "EGU26-11298 abstract, citing Qu et al. 2025"},
        {"date": "2023-09-17", "area_km2": 1.627, "label": "17 Sep 2023",
         "source": "ISRO/NRSC satellite study of South Lhonak Lake"},
        {"date": "2023-09-28", "area_km2": 1.674, "label": "28 Sep 2023", "note": (-8, 14),
         "source": "ISRO/NRSC satellite study of South Lhonak Lake"},
        {"date": "2023-10-04", "area_km2": 0.603, "label": "4 Oct 2023", "note": (-10, 0),
         "source": "ISRO/NRSC satellite study of South Lhonak Lake"},
    ],
    # "gate" checks decide pass/fail; "compare" checks are printed for comparison only
    "checks": [
        {
            "name": "Autumn 2023, before the outburst",
            "role": "gate",
            "periods": ["2023 before"],
            "low": 1.40,
            "high": 1.90,
            "expect": "ISRO: 1.63-1.67 km2 on 17-28 Sep 2023 (band: +/-15%)",
        },
        {
            "name": "Autumns 2014-2016",
            "role": "gate",
            "periods": ["2014", "2015", "2016"],
            "low": 0.95,
            "high": 1.50,
            "expect": "Published: 1.12-1.31 km2 for 2014-2016",
        },
        {
            "name": "Open water shrinks after the outburst",
            "role": "gate",
            "ratio": ("2023 after", "2023 before"),
            "low": 0.0,
            "high": 0.90,
            "expect": "About 50 million m3 drained, so the after/before area ratio must be below 0.9",
        },
        {
            "name": "Autumn 2023 after the outburst, against published figures",
            "role": "compare",
            "periods": ["2023 after"],
            "low": 0.48,
            "high": 0.76,
            "expect": (
                "ISRO 0.60 km2 at 06:00 on 4 Oct 2023; Saha et al. 2025 0.63 km2. The 06:00 time matches the "
                "dawn pass of ISRO's EOS-04 radar satellite, and radar can miss water under floating ice, which "
                "covered the lake that week. Optical images show open water over most of the basin."
            ),
        },
    ],
}

# Chorabari lake, Kedarnath. Not measured from satellites: even 90th-percentile autumn
# composites from 1990-2012 Landsat find at most ~0.02 km2 of water near the lake point,
# against documented dimensions of about 400 x 200 m. The lake was small, silty and often
# shaded, below what 30 m Landsat can track. The flood model uses the documented values.
CHORABARI_DOCUMENTED = {
    "name": "Chorabari",
    "lon": 79.0608,  # Wikipedia, at the snout of Chorabari Glacier about 2 km above Kedarnath
    "lat": 30.7475,
    "length_m": 400,  # WIHG via Dialogue Earth
    "width_m": 200,
    "depth_m": (15, 20),
    "volume_m3": 262_000,  # Wikipedia (262,000,000 L)
    "breach": "morning of 17 Jun 2013; emptied within minutes (WIHG via Dialogue Earth)",
}

LAKES = {"south-lhonak": SOUTH_LHONAK}
