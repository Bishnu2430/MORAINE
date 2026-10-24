"""Study lakes and the published figures the pipeline is checked against.

Every number here names its source, so a failed check can be traced to what it was compared with.
"""

SOUTH_LHONAK = {
    "name": "South Lhonak",
    # Between Wikipedia (27.914 N, 88.184 E) and EGU24-18788 (27.912 N, 88.198 E); only used to find the lake
    "lon": 88.191,
    "lat": 27.913,
    # Margin around the lake's 1984-2021 outline, for growth since 2021
    "margin_m": 200,
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
    # Each check takes clear scenes in a date window, picks one value and compares it with a tolerance band
    "checks": [
        {
            "name": "Last clear scene before the outburst",
            "window": ("2023-09-01", "2023-10-03"),
            "pick": "last",
            "low": 1.40,
            "high": 1.90,
            "expect": "ISRO: 1.63-1.67 km2 on 17-28 Sep 2023 (band: +/-15%)",
        },
        {
            "name": "First clear scene after the outburst",
            "window": ("2023-10-04", "2023-11-15"),
            "pick": "first",
            "low": 0.48,
            "high": 0.76,
            "expect": "ISRO: 0.60 km2 on 4 Oct 2023; Saha et al. 2025: 0.63 km2 (band: +/-20%)",
        },
        {
            "name": "Median of the 2014-2016 autumns",
            "window": ("2014-01-01", "2016-12-31"),
            "pick": "median",
            "low": 0.95,
            "high": 1.50,
            "expect": "Published: 1.12-1.31 km2 for 2014-2016",
        },
    ],
}

CHORABARI = {
    "name": "Chorabari",
    # Wikipedia: 30.7475 N, 79.0608 E, at the snout of Chorabari Glacier about 2 km above Kedarnath
    "lon": 79.0608,
    "lat": 30.7475,
    # The lake was not growing before 2013, so only a narrow margin; a wide one would pick up shadow and debris
    "margin_m": 60,
    # Breached on the morning of 17 Jun 2013 and has not refilled
    "event_date": "2013-06-17",
    "event_label": "17 Jun 2013",
    # No published area series; WIHG gives dimensions only (about 400 x 200 m, 15-20 m deep)
    "published": [],
    "checks": [
        {
            "name": "Lake present before the breach (2005-2012 autumns)",
            "window": ("2005-01-01", "2012-12-31"),
            "pick": "median",
            "low": 0.02,
            "high": 0.10,
            "expect": "About 400 x 200 m before 2013 (WIHG via Dialogue Earth), roughly 0.06 km2",
        },
        {
            "name": "Lake gone after the breach (2014-2016 autumns)",
            "window": ("2014-01-01", "2016-12-31"),
            "pick": "median",
            "low": 0.0,
            "high": 0.02,
            "expect": "Emptied in June 2013 and has not refilled (Dialogue Earth)",
        },
    ],
}

LAKES = {"south-lhonak": SOUTH_LHONAK, "chorabari": CHORABARI}
