"""Design choices in one place. Every number here is a choice, not a validated fact."""

CATEGORIES = {
    # key: label, demand column, jobs (ASSUMPTION: central, low, high), minimum facilities to analyse
    "nursery": {"label": "Nursery / childcare", "demand": "pop_0_4", "demand_label": "children aged 0-4",
                "jobs": (12, 8, 20)},
    "gp": {"label": "GP surgery", "demand": "pop", "demand_label": "residents", "jobs": (20, 10, 35)},
    "pharmacy": {"label": "Pharmacy", "demand": "pop", "demand_label": "residents", "jobs": (6, 4, 10)},
    "cafe": {"label": "Cafe", "demand": "pop", "demand_label": "residents", "jobs": (5, 3, 8)},
    "library": {"label": "Library", "demand": "pop", "demand_label": "residents", "jobs": (4, 2, 8)},
}
# Categories with fewer facilities than this are refused ("insufficient evidence").
MIN_FACILITIES = 5
LOW_CONFIDENCE_BELOW = 10

DEFAULT_RADIUS_M = 800          # about a 10 minute walk at 80 m/min, straight line
WALK_M_PER_MIN = 80
SENSITIVITY_RADII = (600, 800, 1000)
COMPETITION_RADIUS_M = 400
CANNIBALISATION_THRESHOLD = 3   # same-category facilities within 400 m
EDGE_WARNING_M = 500            # caveat: residents outside the city are not counted

# Score weights (design choices, shown in the app and perturbed +/-20% in the sensitivity check)
NEED_WEIGHTS = {"uncovered_share": 0.4, "distance_to_nearest": 0.3, "deprivation": 0.3}
VIABILITY_WEIGHTS = {"catchment_demand": 0.6, "low_competition": 0.4}
FLOOD_VIABILITY_PENALTY = 15    # points off viability if the site is in Flood Zone 3
