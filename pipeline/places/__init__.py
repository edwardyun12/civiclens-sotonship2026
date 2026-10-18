"""Places database: one clean, flagged row per real place in Southampton, merged from open registers.

    python run.py places [--offline] [--fsa-file F] [--ch-key K] ...    (same as python -m pipeline.places)

Modules, in the order the build runs them:
    sources.py         download/parse FSA, OpenStreetMap, NHS ODS, Ofsted, postcodes; Google cross-check
    names.py           name cleaning and similarity, source type codes -> our categories
    business_types.py  detailed types for the advanced filter, industry groups, SIC -> category
    merge.py           match records that are the same place, merge them, flag problems
    companies.py       link places to Companies House companies
    build.py           main(): runs everything, saves data/db/ and data/processed/facilities_places.csv
    common.py          paths, thresholds, source log, geometry helpers
"""
from .build import SIM_USES, export_facilities, main, save  # noqa: F401
from .business_types import *  # noqa: F401,F403
from .common import *  # noqa: F401,F403
from .companies import *  # noqa: F401,F403
from .merge import *  # noqa: F401,F403
from .names import *  # noqa: F401,F403
from .sources import *  # noqa: F401,F403
