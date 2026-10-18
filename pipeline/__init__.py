"""Data pipeline: builds everything in data/ that the simulator and pages read. Run rarely.

    city_data.py   ONS geography, Census 2021, IMD, OSM/NHS facilities, flood zones -> data/processed/
    population.py  ONS mid-2024 small area population estimates -> oa.csv residents
    places/        the places database (data/db/) and the simulator's site list
"""
