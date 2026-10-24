"""Study lakes and the published figures the pipeline is checked against.

Every number here names its source, so a failed check can be traced to what it was compared with.
"""

SOUTH_LHONAK = {
    "name": "South Lhonak",
    # Between Wikipedia (27.914 N, 88.184 E) and EGU24-18788 (27.912 N, 88.198 E); only used to find the lake
    "lon": 88.191,
    "lat": 27.913,
    # The flood reached Chungthang around 00:30 on 4 Oct 2023; scenes dated 3 Oct are before the breach
    "event_date": "2023-10-04",
    # (date, area km², label, source). Year-only figures are placed in mid-October of that year.
    "published": [
        ("1976-10-15", 0.20, "1976", "Natural Hazards 2018, doi:10.1007/s11069-018-3305-0"),
        ("2014-10-15", 1.26, "2014", "AGU Fall Meeting 2015 abstract"),
        ("2016-10-15", 1.31, "2016", "Natural Hazards 2018, doi:10.1007/s11069-018-3305-0"),
        ("2016-10-15", 1.12, "2016", "EGU26-11298 abstract, citing Qu et al. 2025"),
        ("2023-09-17", 1.627, "17 Sep 2023", "ISRO/NRSC satellite study of South Lhonak Lake"),
        ("2023-09-28", 1.674, "28 Sep 2023", "ISRO/NRSC satellite study of South Lhonak Lake"),
        ("2023-10-04", 0.603, "4 Oct 2023", "ISRO/NRSC satellite study of South Lhonak Lake"),
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
