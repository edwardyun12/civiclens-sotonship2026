"""Deterministic scenario engine. No LLM, no UI. Every number the app shows comes from here.

Geometry: everything is projected to British National Grid (EPSG:27700), so distances are metres.
Demand points: Census 2021 Output Area population-weighted centroids (792 in Southampton).
Distances are straight-line (a known underestimate of walking distance; see README limits).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
from pyproj import Transformer
from shapely.geometry import Point, shape
from shapely.ops import unary_union

from . import config as C

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
CACHE = ROOT / "data" / "cache"
_TO_BNG = Transformer.from_crs(4326, 27700, always_xy=True)
_TO_WGS = Transformer.from_crs(27700, 4326, always_xy=True)


class EngineError(ValueError):
    """A problem with the user's input that the app should show as a plain message."""


def to_bng(lat, lon):
    x, y = _TO_BNG.transform(np.asarray(lon, float), np.asarray(lat, float))
    return x, y


def to_wgs(x, y):
    lon, lat = _TO_WGS.transform(np.asarray(x, float), np.asarray(y, float))
    return lat, lon


def pairwise(ax, ay, bx, by) -> np.ndarray:
    """Distance matrix (len(a) x len(b)) in metres."""
    ax, ay, bx, by = map(lambda v: np.asarray(v, float), (ax, ay, bx, by))
    return np.hypot(ax[:, None] - bx[None, :], ay[:, None] - by[None, :])


# ------------------------------------------------------------------ data
@dataclass(eq=False)
class City:
    oa: pd.DataFrame
    fac: pd.DataFrame
    boundary: object               # shapely polygon in BNG
    boundary_wgs: object           # shapely polygon in lat/lon (for maps)
    sources: dict
    flood: object | None = None    # shapely geometry in BNG, or None if not loaded
    _cand_dist: np.ndarray | None = field(default=None, repr=False)

    # Candidate sites for the optimiser and for score percentiles = all OA centroids.
    @property
    def cand_dist(self) -> np.ndarray:
        if self._cand_dist is None:
            f = CACHE / "oa_oa_dist.npy"
            if f.exists():
                d = np.load(f)
                if d.shape == (len(self.oa), len(self.oa)):
                    self._cand_dist = d
            if self._cand_dist is None:
                d = pairwise(self.oa.x, self.oa.y, self.oa.x, self.oa.y).astype(np.float32)
                CACHE.mkdir(parents=True, exist_ok=True)
                np.save(f, d)
                self._cand_dist = d
        return self._cand_dist

    @property
    def flood_mask(self) -> np.ndarray:
        """True where a candidate site (OA centroid) is in Flood Zone 3."""
        if getattr(self, "_flood_mask", None) is None:
            import shapely
            self._flood_mask = (np.zeros(len(self.oa), bool) if self.flood is None
                                else shapely.contains_xy(self.flood, self.oa.x.to_numpy(), self.oa.y.to_numpy()))
        return self._flood_mask

    def facilities(self, category: str) -> pd.DataFrame:
        return self.fac[self.fac.category == category]

    @lru_cache(maxsize=32)
    def existing_dist(self, category: str) -> np.ndarray:
        """Distance from every OA centroid to its nearest existing facility of this category."""
        f = self.facilities(category)
        if f.empty:
            return np.full(len(self.oa), np.inf)
        return pairwise(self.oa.x, self.oa.y, f.x, f.y).min(axis=1)

    def __hash__(self):  # for lru_cache
        return id(self)


# Where existing sites come from. "places" = the merged places database (src/build_places.py), the default when
# it exists; "baseline" = the 17 Oct 2026 OSM + NHS file the published test numbers were computed on.
DATASETS = {"places": "facilities_places.csv", "baseline": "facilities.csv"}


def dataset_file(proc: Path, dataset: str | None) -> tuple[str, Path]:
    dataset = dataset or os.environ.get("SIM_DATASET") or "places"
    if dataset not in DATASETS:
        raise EngineError(f"Unknown dataset '{dataset}'. Choose one of: {', '.join(DATASETS)}.")
    f = proc / DATASETS[dataset]
    if not f.exists():  # no database built yet: fall back to the baseline file
        dataset, f = "baseline", proc / DATASETS["baseline"]
    return dataset, f


def load_city(proc: Path = PROC, dataset: str | None = None) -> City:
    oa = pd.read_csv(proc / "oa.csv")
    dataset, fac_file = dataset_file(proc, dataset)
    fac = pd.read_csv(fac_file)
    oa["x"], oa["y"] = to_bng(oa.lat, oa.lon)
    fac["x"], fac["y"] = to_bng(fac.lat, fac.lon)
    gj = json.loads((proc / "lsoa.geojson").read_text())
    wgs = unary_union([shape(f["geometry"]) for f in gj["features"]]).buffer(0)
    from shapely.ops import transform
    bng = transform(lambda x, y, z=None: _TO_BNG.transform(x, y), wgs)
    src_f = ROOT / "data" / "raw" / "SOURCES.json"
    sources = json.loads(src_f.read_text()) if src_f.exists() else {}
    flood = None
    ff = proc / "flood_zone3.geojson"
    if ff.exists():
        fj = json.loads(ff.read_text())
        geoms = [shape(f["geometry"]) for f in fj["features"]]
        if geoms:
            flood = transform(lambda x, y, z=None: _TO_BNG.transform(x, y), unary_union(geoms))
    city = City(oa=oa, fac=fac, boundary=bng, boundary_wgs=wgs, sources=sources, flood=flood)
    city.dataset = dataset
    return city


# ------------------------------------------------------------------ helpers
def demand(city: City, category: str, extra_pop: dict | None = None) -> np.ndarray:
    """Demand weight per OA. extra_pop = {ward_name: residents} adds housing growth (E15)."""
    col = C.CATEGORIES[category]["demand"]
    w = city.oa[col].to_numpy(float).copy()
    if extra_pop:
        for ward, n in extra_pop.items():
            m = (city.oa.ward == ward).to_numpy()
            if not m.any():
                raise EngineError(f"Unknown ward: {ward}")
            base = city.oa.loc[m, "pop"].to_numpy(float)
            share = base / base.sum()
            # new homes add residents in proportion to existing population; 0-4s at the ward's current ratio
            if col == "pop_0_4":
                ratio = city.oa.loc[m, "pop_0_4"].sum() / city.oa.loc[m, "pop"].sum()
                w[m] += n * ratio * share
            else:
                w[m] += n * share
    return w


def check_category(city: City, category: str) -> None:
    if category not in C.CATEGORIES:
        raise EngineError(f"Unknown category '{category}'. Choose one of: {', '.join(C.CATEGORIES)}.")


def resolve_site(city: City, lat: float | None, lon: float | None) -> tuple[float, float]:
    if lat is None or lon is None or (isinstance(lat, float) and np.isnan(lat)):
        raise EngineError("No site chosen. Click the map, enter a postcode or pick a ward.")
    x, y = to_bng(lat, lon)
    x, y = float(x), float(y)
    if not city.boundary.buffer(50).contains(Point(x, y)):
        raise EngineError("That location is outside Southampton city. Pick a site inside the city boundary.")
    return x, y


def coverage(w: np.ndarray, d: np.ndarray, r: float) -> float:
    return float(w[d <= r].sum() / w.sum()) if w.sum() > 0 else 0.0


def wmean(w: np.ndarray, v: np.ndarray) -> float:
    v = np.where(np.isfinite(v), v, np.nan)
    m = np.isfinite(v)
    return float((w[m] * v[m]).sum() / w[m].sum()) if w[m].sum() > 0 else float("nan")


def pct_rank(dist: np.ndarray, value: float) -> float:
    """Share (0-100) of candidate sites with a value <= this one."""
    return float(100.0 * (np.asarray(dist) <= value + 1e-9).mean())


# ------------------------------------------------------------------ candidate-level inputs for scores
@lru_cache(maxsize=64)
def _candidate_inputs(city: City, category: str, radius: float) -> dict:
    """Raw score inputs for every candidate site (OA centroid). Used to turn a site's raw
    inputs into percentiles: 'higher need than 82% of possible sites in the city'."""
    w = demand(city, category)
    d0 = city.existing_dist(category)
    D = city.cand_dist                      # oa x cand
    in_r = D <= radius
    catch = in_r.T @ w                      # demand within R of each candidate
    unc = in_r.T @ (w * (d0 > radius))      # of which not already covered
    with np.errstate(invalid="ignore", divide="ignore"):
        unc_share = np.where(catch > 0, unc / catch, 0.0)
        dfin = np.where(np.isfinite(d0), d0, 5000)
        dist_near = (in_r.T @ (w * dfin)) / np.where(catch > 0, catch, 1)
        dep_w = (5 - city.oa.imd_quintile.to_numpy(float)) / 4.0   # 1 = most deprived quintile
        dep = (in_r.T @ (w * dep_w)) / np.where(catch > 0, catch, 1)
    f = city.facilities(category)
    comp = (pairwise(city.oa.x, city.oa.y, f.x, f.y) <= C.COMPETITION_RADIUS_M).sum(axis=1) if len(f) else np.zeros(len(city.oa))
    return {"uncovered_share": unc_share, "distance_to_nearest": dist_near, "deprivation": dep,
            "catchment_demand": catch, "competition": comp.astype(float), "newly_covered": unc}


def scores(city: City, category: str, radius: float, raw: dict, flood: bool | None,
           need_w: dict | None = None, via_w: dict | None = None) -> dict:
    need_w = need_w or C.NEED_WEIGHTS
    via_w = via_w or C.VIABILITY_WEIGHTS
    cand = _candidate_inputs(city, category, radius)
    need_in = {k: pct_rank(cand[k], raw[k]) for k in need_w}
    via_in = {"catchment_demand": pct_rank(cand["catchment_demand"], raw["catchment_demand"]),
              # fewer competitors is better: percentile of candidates with MORE or equal competition
              "low_competition": float(100.0 * (cand["competition"] >= raw["competition"] - 1e-9).mean())}
    need = sum(need_w[k] * need_in[k] for k in need_w) / sum(need_w.values())
    via = sum(via_w[k] * via_in[k] for k in via_w) / sum(via_w.values())
    if flood:
        via = max(0.0, via - C.FLOOD_VIABILITY_PENALTY)
    return {"need": round(need), "viability": round(via),
            "need_inputs_pct": {k: round(v) for k, v in need_in.items()},
            "viability_inputs_pct": {k: round(v) for k, v in via_in.items()}}


# ------------------------------------------------------------------ E1-E8, E11, E14: one site
def evaluate_site(city: City, category: str, lat: float, lon: float, radius: float = C.DEFAULT_RADIUS_M,
                  extra_pop: dict | None = None, need_w: dict | None = None, via_w: dict | None = None) -> dict:
    check_category(city, category)
    if radius <= 0:
        raise EngineError("Walking radius must be positive.")
    sx, sy = resolve_site(city, lat, lon)
    cfg = C.CATEGORIES[category]
    f = city.facilities(category)
    n_fac = len(f)
    w = demand(city, category, extra_pop)
    d0 = city.existing_dist(category)
    ds = np.hypot(city.oa.x.to_numpy() - sx, city.oa.y.to_numpy() - sy)
    d1 = np.minimum(d0, ds)

    cov0, cov1 = coverage(w, d0, radius), coverage(w, d1, radius)
    newly = (d0 > radius) & (ds <= radius)
    newly_n = float(w[newly].sum())
    catch = float(w[ds <= radius].sum())

    # E3 competition, E4 diversity
    comp = int((np.hypot(f.x - sx, f.y - sy) <= C.COMPETITION_RADIUS_M).sum()) if n_fac else 0
    near_all = city.fac[np.hypot(city.fac.x - sx, city.fac.y - sy) <= C.COMPETITION_RADIUS_M]
    div0 = int(near_all.category.nunique())
    div1 = div0 + (0 if category in set(near_all.category) else 1)

    # E7 constraints
    flood = None if city.flood is None else bool(city.flood.contains(Point(sx, sy)))
    edge_m = float(city.boundary.exterior.distance(Point(sx, sy))) if hasattr(city.boundary, "exterior") \
        else float(city.boundary.boundary.distance(Point(sx, sy)))

    # E11 equity: newly covered demand by IMD quintile (1 = most deprived 20% nationally)
    q = city.oa.imd_quintile.to_numpy()
    by_q = {int(k): round(float(w[newly & (q == k)].sum())) for k in range(1, 6)}
    most_dep40 = by_q[1] + by_q[2]

    # E8 scores
    dfin = np.where(np.isfinite(d0), d0, 5000)
    in_r = ds <= radius
    raw = {
        "uncovered_share": newly_n / catch if catch else 0.0,
        "distance_to_nearest": wmean(w[in_r], dfin[in_r]) if in_r.any() else 0.0,
        "deprivation": wmean(w[in_r], (5 - q[in_r]) / 4.0) if in_r.any() else 0.0,
        "catchment_demand": catch,
        "competition": comp,
    }
    sc = scores(city, category, radius, raw, flood, need_w, via_w)

    # E6 jobs (ASSUMPTION table)
    jc, jl, jh = cfg["jobs"]

    # E14 confidence
    reasons = []
    if n_fac < C.MIN_FACILITIES:
        conf = "Low"
        reasons.append(f"only {n_fac} existing {cfg['label'].lower()} sites in the data")
    elif n_fac < C.LOW_CONFIDENCE_BELOW:
        conf = "Medium"
        reasons.append(f"few existing sites in the data ({n_fac})")
    else:
        conf = "High"
    if w.sum() <= 0:
        conf = "Low"
        reasons.append("no demand data")
    if edge_m < C.EDGE_WARNING_M:
        # The boundary follows the waterfront, so this is a caveat, not a downgrade.
        reasons.append(f"site is {round(edge_m)} m from the city boundary or waterfront; residents outside the city are not counted")
    if flood is None:
        reasons.append("flood zones not checked")

    nearest_existing = float(np.hypot(f.x - sx, f.y - sy).min()) if n_fac else None
    lat_s, lon_s = float(lat), float(lon)
    ward = city.oa.ward.iloc[int(np.argmin(ds))]
    return {
        "category": category, "category_label": cfg["label"], "demand_label": cfg["demand_label"],
        "site": {"lat": round(lat_s, 5), "lon": round(lon_s, 5), "ward": ward},
        "radius_m": int(radius), "walk_minutes": round(radius / C.WALK_M_PER_MIN),
        "existing_facilities": n_fac,
        "coverage_before_pct": round(100 * cov0, 1), "coverage_after_pct": round(100 * cov1, 1),
        "coverage_change_pct_points": round(100 * (cov1 - cov0), 1),
        "newly_covered": round(newly_n),
        "mean_distance_before_m": round(wmean(w, np.where(np.isfinite(d0), d0, np.nan))),
        "mean_distance_after_m": round(wmean(w, np.where(np.isfinite(d1), d1, np.nan))),
        "catchment_demand": round(catch),
        "nearest_existing_m": None if nearest_existing is None else round(nearest_existing),
        "competitors_within_400m": comp,
        "cannibalisation_flag": comp >= C.CANNIBALISATION_THRESHOLD,
        "diversity_before": div0, "diversity_after": div1,
        "jobs_estimate": jc, "jobs_range": [jl, jh],
        "flood_zone3": flood, "distance_to_city_edge_m": round(edge_m),
        "equity_newly_covered_by_quintile": by_q,
        "equity_most_deprived_40pct": most_dep40,
        "equity_most_deprived_40pct_share": round(100 * most_dep40 / newly_n) if newly_n >= 0.5 else 0,
        "need_score": sc["need"], "viability_score": sc["viability"],
        "need_inputs_pct": sc["need_inputs_pct"], "viability_inputs_pct": sc["viability_inputs_pct"],
        "confidence": conf, "confidence_reasons": reasons,
        "insufficient_evidence": n_fac < C.MIN_FACILITIES or w.sum() <= 0,
    }


def do_nothing(city: City, category: str, radius: float = C.DEFAULT_RADIUS_M, extra_pop: dict | None = None) -> dict:
    check_category(city, category)
    w = demand(city, category, extra_pop)
    d0 = city.existing_dist(category)
    cov = coverage(w, d0, radius)
    return {"category": category, "category_label": "Do nothing", "radius_m": int(radius),
            "coverage_before_pct": round(100 * cov, 1), "coverage_after_pct": round(100 * cov, 1),
            "coverage_change_pct_points": 0.0, "newly_covered": 0, "need_score": 0, "viability_score": 0,
            "jobs_estimate": 0, "equity_most_deprived_40pct": 0}


# ------------------------------------------------------------------ E9 sensitivity
def _perturb(weights: dict, key: str, f: float) -> dict:
    w = dict(weights)
    w[key] *= f
    return w


def sensitivity(city: City, scenarios: list[dict], extra_pop: dict | None = None) -> dict:
    """scenarios: [{'category':..., 'lat':..., 'lon':...}]. Ranks by newly covered people and by need score
    at radii 600/800/1000 and with each weight +/-20%. Reports whether the winner ever changes."""
    runs = []
    for r in C.SENSITIVITY_RADII:
        res = [evaluate_site(city, s["category"], s["lat"], s["lon"], r, extra_pop) for s in scenarios]
        runs.append({"label": f"{r} m", "newly": [x["newly_covered"] for x in res], "need": [x["need_score"] for x in res]})
    for k in C.NEED_WEIGHTS:
        for f in (0.8, 1.2):
            res = [evaluate_site(city, s["category"], s["lat"], s["lon"], C.DEFAULT_RADIUS_M, extra_pop,
                                 need_w=_perturb(C.NEED_WEIGHTS, k, f)) for s in scenarios]
            runs.append({"label": f"{k} x{f}", "newly": [x["newly_covered"] for x in res], "need": [x["need_score"] for x in res]})
    winners_need = {int(np.argmax(r["need"])) for r in runs}
    winners_newly = {int(np.argmax(r["newly"])) for r in runs[:len(C.SENSITIVITY_RADII)]}
    newly_by_r = {int(r): runs[i]["newly"] for i, r in enumerate(C.SENSITIVITY_RADII)}
    need_range = [[min(r["need"][i] for r in runs), max(r["need"][i] for r in runs)] for i in range(len(scenarios))]
    return {"runs": runs, "stable_need_ranking": len(winners_need) == 1,
            "stable_coverage_ranking": len(winners_newly) == 1,
            "newly_covered_by_radius": newly_by_r, "need_score_range": need_range}


# ------------------------------------------------------------------ E12 optimiser
def optimise(city: City, category: str, k: int = 3, radius: float = C.DEFAULT_RADIUS_M,
             extra_pop: dict | None = None, exclude_flood: bool = True) -> list[dict]:
    """Greedy max-coverage: pick the candidate (OA centroid) that newly covers the most demand,
    add it, recompute, repeat k times. Greedy is within (1 - 1/e) of optimal for this problem."""
    check_category(city, category)
    if not 1 <= k <= 5:
        raise EngineError("Choose between 1 and 5 new facilities.")
    w = demand(city, category, extra_pop)
    covered = city.existing_dist(category) <= radius
    A = city.cand_dist <= radius                       # oa x cand
    allowed = np.ones(A.shape[1], bool)
    if exclude_flood and city.flood is not None:
        allowed = ~city.flood_mask
    picks = []
    for step in range(k):
        gain = A.T @ (w * ~covered)
        gain[~allowed] = -1
        j = int(np.argmax(gain))
        if gain[j] <= 0:
            break
        lat, lon = float(city.oa.lat.iloc[j]), float(city.oa.lon.iloc[j])
        picks.append({"rank": step + 1, "lat": round(lat, 5), "lon": round(lon, 5),
                      "ward": city.oa.ward.iloc[j], "oa_code": city.oa.oa_code.iloc[j],
                      "marginal_newly_covered": round(float(gain[j]))})
        covered |= A[:, j]
    total = round(float(w[covered].sum() / w.sum() * 100), 1)
    base = round(coverage(w, city.existing_dist(category), radius) * 100, 1)
    for p in picks:
        p["coverage_before_pct"], p["coverage_after_all_pct"] = base, total
    return picks


def brute_force_best(city: City, category: str, candidates: list[int], radius: float = C.DEFAULT_RADIUS_M) -> int:
    """Test helper: index (within candidates) of the single best site by exhaustive evaluation."""
    w = demand(city, category)
    d0 = city.existing_dist(category)
    gains = []
    for j in candidates:
        ds = np.hypot(city.oa.x - city.oa.x.iloc[j], city.oa.y - city.oa.y.iloc[j]).to_numpy()
        gains.append(float(w[(d0 > radius) & (ds <= radius)].sum()))
    return candidates[int(np.argmax(gains))]


# ------------------------------------------------------------------ baseline (T2)
def baseline_rank(city: City, category: str, sites: list[tuple[float, float]]) -> int:
    """The spreadsheet answer: pick the site with the fewest competitors within 400 m."""
    f = city.facilities(category)
    counts = []
    for lat, lon in sites:
        x, y = to_bng(lat, lon)
        counts.append(int((np.hypot(f.x - float(x), f.y - float(y)) <= C.COMPETITION_RADIUS_M).sum()))
    return int(np.argmin(counts))


def ward_centroid(city: City, ward: str) -> tuple[float, float]:
    m = city.oa[city.oa.ward.str.lower() == ward.strip().lower()]
    if m.empty:
        raise EngineError(f"No ward called '{ward}'.")
    # population-weighted centre of the ward, snapped to the nearest OA centroid so it is inside the city
    cx = (m.x * m["pop"]).sum() / m["pop"].sum()
    cy = (m.y * m["pop"]).sum() / m["pop"].sum()
    j = int(np.argmin(np.hypot(m.x - cx, m.y - cy)))
    return float(m.lat.iloc[j]), float(m.lon.iloc[j])
