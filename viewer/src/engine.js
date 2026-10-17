/* Southampton simulator engine, a direct port of src/engine.py and the template/audit parts of src/brief.py.
   Deterministic. Distances in metres on British National Grid. */
(function (root) {
  "use strict";

  const CATEGORIES = {
    nursery: { label: "Nursery / childcare", demand: "pop04", demandLabel: "children aged 0-4", jobs: [12, 8, 20] },
    gp: { label: "GP surgery", demand: "pop", demandLabel: "residents", jobs: [20, 10, 35] },
    pharmacy: { label: "Pharmacy", demand: "pop", demandLabel: "residents", jobs: [6, 4, 10] },
    cafe: { label: "Cafe", demand: "pop", demandLabel: "residents", jobs: [5, 3, 8] },
    library: { label: "Library", demand: "pop", demandLabel: "residents", jobs: [4, 2, 8] },
  };
  const CFG = {
    MIN_FACILITIES: 5, LOW_CONFIDENCE_BELOW: 10, DEFAULT_RADIUS_M: 800, WALK_M_PER_MIN: 80,
    SENSITIVITY_RADII: [600, 800, 1000], COMPETITION_RADIUS_M: 400, CANNIBALISATION_THRESHOLD: 3,
    EDGE_WARNING_M: 500, NEED_WEIGHTS: { uncovered_share: 0.4, distance_to_nearest: 0.3, deprivation: 0.3 },
    VIABILITY_WEIGHTS: { catchment_demand: 0.6, low_competition: 0.4 }, FLOOD_VIABILITY_PENALTY: 15,
    RESIDENTS_PER_HOME: 2.3,
  };

  class EngineError extends Error {}

  // Python's round(): half to even.
  function pyRound(x, nd = 0) {
    const f = Math.pow(10, nd), v = x * f, fl = Math.floor(v), diff = v - fl;
    let r;
    if (Math.abs(diff - 0.5) < 1e-9) r = fl % 2 === 0 ? fl : fl + 1;
    else r = Math.round(v);
    return nd ? r / f : r;
  }

  // ---------------------------------------------------------------- WGS84 -> OSGB36 -> British National Grid
  const rad = Math.PI / 180;
  function toBNG(lat, lon) {
    // WGS84 cartesian
    let a = 6378137.0, b = 6356752.314245, e2 = 1 - (b * b) / (a * a);
    let phi = lat * rad, lam = lon * rad;
    let nu = a / Math.sqrt(1 - e2 * Math.sin(phi) ** 2);
    let x1 = nu * Math.cos(phi) * Math.cos(lam), y1 = nu * Math.cos(phi) * Math.sin(lam), z1 = nu * (1 - e2) * Math.sin(phi);
    // Helmert WGS84 -> OSGB36
    const tx = -446.448, ty = 125.157, tz = -542.06, s = 20.4894e-6;
    const rx = (-0.1502 / 3600) * rad, ry = (-0.247 / 3600) * rad, rz = (-0.8421 / 3600) * rad;
    const x2 = tx + (1 + s) * x1 - rz * y1 + ry * z1;
    const y2 = ty + rz * x1 + (1 + s) * y1 - rx * z1;
    const z2 = tz - ry * x1 + rx * y1 + (1 + s) * z1;
    // Airy 1830
    a = 6377563.396; b = 6356256.909; e2 = 1 - (b * b) / (a * a);
    const p = Math.sqrt(x2 * x2 + y2 * y2);
    phi = Math.atan2(z2, p * (1 - e2));
    for (let i = 0; i < 10; i++) {
      nu = a / Math.sqrt(1 - e2 * Math.sin(phi) ** 2);
      phi = Math.atan2(z2 + e2 * nu * Math.sin(phi), p);
    }
    lam = Math.atan2(y2, x2);
    // Transverse Mercator (OS formulas)
    const F0 = 0.9996012717, lat0 = 49 * rad, lon0 = -2 * rad, N0 = -100000, E0 = 400000;
    const n = (a - b) / (a + b);
    const sinP = Math.sin(phi), cosP = Math.cos(phi), tanP = Math.tan(phi);
    nu = a * F0 / Math.sqrt(1 - e2 * sinP * sinP);
    const rho = a * F0 * (1 - e2) / Math.pow(1 - e2 * sinP * sinP, 1.5);
    const eta2 = nu / rho - 1;
    const dphi = phi - lat0, sphi = phi + lat0;
    const M = b * F0 * ((1 + n + 1.25 * n * n + 1.25 * n ** 3) * dphi
      - (3 * n + 3 * n * n + 2.625 * n ** 3) * Math.sin(dphi) * Math.cos(sphi)
      + (1.875 * n * n + 1.875 * n ** 3) * Math.sin(2 * dphi) * Math.cos(2 * sphi)
      - (35 / 24) * n ** 3 * Math.sin(3 * dphi) * Math.cos(3 * sphi));
    const I = M + N0, II = (nu / 2) * sinP * cosP, III = (nu / 24) * sinP * cosP ** 3 * (5 - tanP ** 2 + 9 * eta2);
    const IIIA = (nu / 720) * sinP * cosP ** 5 * (61 - 58 * tanP ** 2 + tanP ** 4);
    const IV = nu * cosP, V = (nu / 6) * cosP ** 3 * (nu / rho - tanP ** 2);
    const VI = (nu / 120) * cosP ** 5 * (5 - 18 * tanP ** 2 + tanP ** 4 + 14 * eta2 - 58 * tanP ** 2 * eta2);
    const dl = lam - lon0;
    return [E0 + IV * dl + V * dl ** 3 + VI * dl ** 5, I + II * dl ** 2 + III * dl ** 4 + IIIA * dl ** 6];
  }

  function pipRings(x, y, rings) { // even-odd, rings are [[lon,lat],...]
    let inside = false;
    for (const r of rings) {
      for (let i = 0, j = r.length - 1; i < r.length; j = i++) {
        const xi = r[i][0], yi = r[i][1], xj = r[j][0], yj = r[j][1];
        if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
      }
    }
    return inside;
  }

  function segDist(px, py, ax, ay, bx, by) {
    const dx = bx - ax, dy = by - ay, L = dx * dx + dy * dy;
    let t = L ? ((px - ax) * dx + (py - ay) * dy) / L : 0;
    t = Math.max(0, Math.min(1, t));
    return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
  }

  function create(data) {
    const O = data.oa, N = O.lat.length;
    const ox = new Float64Array(N), oy = new Float64Array(N);
    for (let i = 0; i < N; i++) [ox[i], oy[i]] = toBNG(O.lat[i], O.lon[i]);
    const fac = data.fac.map((f) => { const [x, y] = toBNG(f.lat, f.lon); return { ...f, x, y }; });
    const edges = data.edges.map(([lo1, la1, lo2, la2]) => [...toBNG(la1, lo1), ...toBNG(la2, lo2)]);
    const wards = [...new Set(O.ward)].sort();

    let D = null; // candidate distance matrix, row i = OA i, col j = candidate j
    function candDist() {
      if (!D) {
        D = new Float64Array(N * N);
        for (let i = 0; i < N; i++) for (let j = 0; j < N; j++) D[i * N + j] = Math.hypot(ox[i] - ox[j], oy[i] - oy[j]);
      }
      return D;
    }
    const facCache = {}, distCache = {}, candCache = {};
    function facilities(cat) { return facCache[cat] || (facCache[cat] = fac.filter((f) => f.c === cat)); }
    function existingDist(cat) {
      if (distCache[cat]) return distCache[cat];
      const f = facilities(cat), d = new Float64Array(N).fill(Infinity);
      for (let i = 0; i < N; i++) for (const q of f) { const v = Math.hypot(ox[i] - q.x, oy[i] - q.y); if (v < d[i]) d[i] = v; }
      return (distCache[cat] = d);
    }

    function checkCategory(cat) {
      if (!CATEGORIES[cat]) throw new EngineError(`Unknown category '${cat}'.`);
    }

    function demand(cat, extra) {
      const col = CATEGORIES[cat].demand, w = Float64Array.from(O[col]);
      if (extra) {
        for (const [ward, n] of Object.entries(extra)) {
          const idx = []; for (let i = 0; i < N; i++) if (O.ward[i] === ward) idx.push(i);
          if (!idx.length) throw new EngineError(`Unknown ward: ${ward}`);
          const base = idx.reduce((s, i) => s + O.pop[i], 0);
          const ratio = idx.reduce((s, i) => s + O.pop04[i], 0) / base;
          for (const i of idx) w[i] += col === "pop04" ? n * ratio * (O.pop[i] / base) : n * (O.pop[i] / base);
        }
      }
      return w;
    }

    function cityEdgeDist(x, y) {
      let m = Infinity;
      for (const e of edges) { const v = segDist(x, y, e[0], e[1], e[2], e[3]); if (v < m) m = v; }
      return m;
    }
    function insideCity(lat, lon) {
      for (const l of data.lsoa) if (pipRings(lon, lat, l.rings)) return true;
      const [x, y] = toBNG(lat, lon);
      return cityEdgeDist(x, y) <= 50; // the Python engine buffers the boundary by 50 m
    }
    function siteInFlood(lat, lon) {
      // exact flag for OA centroids (precomputed at full resolution), simplified shapes elsewhere
      for (let i = 0; i < N; i++) if (O.lat[i] === lat && O.lon[i] === lon) return !!O.flood[i];
      for (const poly of data.flood) if (pipRings(lon, lat, poly)) return true;
      return false;
    }

    function resolveSite(lat, lon) {
      if (lat == null || lon == null || Number.isNaN(lat)) throw new EngineError("No site chosen. Click the map, enter coordinates or pick a ward.");
      if (!insideCity(lat, lon)) throw new EngineError("That location is outside Southampton city. Pick a site inside the city boundary.");
      return toBNG(lat, lon);
    }

    const sum = (a) => { let s = 0; for (const v of a) s += v; return s; };
    function coverage(w, d, r) { let a = 0, t = 0; for (let i = 0; i < w.length; i++) { t += w[i]; if (d[i] <= r) a += w[i]; } return t > 0 ? a / t : 0; }
    function wmean(w, v) { let a = 0, t = 0; for (let i = 0; i < w.length; i++) if (Number.isFinite(v[i])) { a += w[i] * v[i]; t += w[i]; } return t > 0 ? a / t : NaN; }
    function pctRank(dist, value) { let c = 0; for (const v of dist) if (v <= value + 1e-9) c++; return (100 * c) / dist.length; }

    function candidateInputs(cat, radius) {
      const key = cat + "|" + radius;
      if (candCache[key]) return candCache[key];
      const w = demand(cat), d0 = existingDist(cat), Dm = candDist();
      const catch_ = new Float64Array(N), unc = new Float64Array(N), dn = new Float64Array(N), dep = new Float64Array(N), comp = new Float64Array(N);
      for (let i = 0; i < N; i++) {
        const wi = w[i], cov = d0[i] > radius, dfin = Number.isFinite(d0[i]) ? d0[i] : 5000, depw = (5 - O.q[i]) / 4;
        for (let j = 0; j < N; j++) {
          if (Dm[i * N + j] <= radius) { catch_[j] += wi; if (cov) unc[j] += wi; dn[j] += wi * dfin; dep[j] += wi * depw; }
        }
      }
      const unc_share = new Float64Array(N);
      for (let j = 0; j < N; j++) {
        unc_share[j] = catch_[j] > 0 ? unc[j] / catch_[j] : 0;
        const den = catch_[j] > 0 ? catch_[j] : 1;
        dn[j] /= den; dep[j] /= den;
      }
      const f = facilities(cat);
      for (let j = 0; j < N; j++) { let c = 0; for (const q of f) if (Math.hypot(ox[j] - q.x, oy[j] - q.y) <= CFG.COMPETITION_RADIUS_M) c++; comp[j] = c; }
      return (candCache[key] = { uncovered_share: unc_share, distance_to_nearest: dn, deprivation: dep, catchment_demand: catch_, competition: comp, newly_covered: unc });
    }

    function scores(cat, radius, raw, flood, needW, viaW) {
      needW = needW || CFG.NEED_WEIGHTS; viaW = viaW || CFG.VIABILITY_WEIGHTS;
      const cand = candidateInputs(cat, radius);
      const needIn = {}; for (const k in needW) needIn[k] = pctRank(cand[k], raw[k]);
      let ge = 0; for (const v of cand.competition) if (v >= raw.competition - 1e-9) ge++;
      const viaIn = { catchment_demand: pctRank(cand.catchment_demand, raw.catchment_demand), low_competition: (100 * ge) / N };
      const sw = (o) => Object.values(o).reduce((a, b) => a + b, 0);
      let need = 0; for (const k in needW) need += needW[k] * needIn[k]; need /= sw(needW);
      let via = 0; for (const k in viaW) via += viaW[k] * viaIn[k]; via /= sw(viaW);
      if (flood) via = Math.max(0, via - CFG.FLOOD_VIABILITY_PENALTY);
      const r = (o) => Object.fromEntries(Object.entries(o).map(([k, v]) => [k, pyRound(v)]));
      return { need: pyRound(need), viability: pyRound(via), need_inputs_pct: r(needIn), viability_inputs_pct: r(viaIn) };
    }

    function evaluateSite(cat, lat, lon, radius = CFG.DEFAULT_RADIUS_M, extra = null, needW = null, viaW = null) {
      checkCategory(cat);
      if (!(radius > 0)) throw new EngineError("Walking radius must be positive.");
      const [sx, sy] = resolveSite(lat, lon);
      const cfg = CATEGORIES[cat], f = facilities(cat), nFac = f.length;
      const w = demand(cat, extra), d0 = existingDist(cat);
      const ds = new Float64Array(N), d1 = new Float64Array(N);
      for (let i = 0; i < N; i++) { ds[i] = Math.hypot(ox[i] - sx, oy[i] - sy); d1[i] = Math.min(d0[i], ds[i]); }
      const cov0 = coverage(w, d0, radius), cov1 = coverage(w, d1, radius);
      const newly = new Uint8Array(N); let newlyN = 0, catchN = 0;
      for (let i = 0; i < N; i++) {
        if (d0[i] > radius && ds[i] <= radius) { newly[i] = 1; newlyN += w[i]; }
        if (ds[i] <= radius) catchN += w[i];
      }
      let comp = 0, nearest = Infinity;
      for (const q of f) { const v = Math.hypot(q.x - sx, q.y - sy); if (v <= CFG.COMPETITION_RADIUS_M) comp++; if (v < nearest) nearest = v; }
      const nearCats = new Set(fac.filter((q) => Math.hypot(q.x - sx, q.y - sy) <= CFG.COMPETITION_RADIUS_M).map((q) => q.c));
      const div0 = nearCats.size, div1 = div0 + (nearCats.has(cat) ? 0 : 1);
      const flood = siteInFlood(lat, lon);
      const edgeM = cityEdgeDist(sx, sy);
      const byQ = {}; for (let k = 1; k <= 5; k++) { let s = 0; for (let i = 0; i < N; i++) if (newly[i] && O.q[i] === k) s += w[i]; byQ[k] = pyRound(s); }
      const dep40 = byQ[1] + byQ[2];
      const inW = [], inD = [], inQ = [];
      for (let i = 0; i < N; i++) if (ds[i] <= radius) { inW.push(w[i]); inD.push(Number.isFinite(d0[i]) ? d0[i] : 5000); inQ.push((5 - O.q[i]) / 4); }
      const raw = {
        uncovered_share: catchN ? newlyN / catchN : 0,
        distance_to_nearest: inW.length ? wmean(inW, inD) : 0,
        deprivation: inW.length ? wmean(inW, inQ) : 0,
        catchment_demand: catchN, competition: comp,
      };
      const sc = scores(cat, radius, raw, flood, needW, viaW);
      const reasons = []; let conf;
      if (nFac < CFG.MIN_FACILITIES) { conf = "Low"; reasons.push(`only ${nFac} existing ${cfg.label.toLowerCase()} sites in the data`); }
      else if (nFac < CFG.LOW_CONFIDENCE_BELOW) { conf = "Medium"; reasons.push(`few existing sites in the data (${nFac})`); }
      else conf = "High";
      if (sum(w) <= 0) { conf = "Low"; reasons.push("no demand data"); }
      if (edgeM < CFG.EDGE_WARNING_M) reasons.push(`site is ${pyRound(edgeM)} m from the city boundary or waterfront; residents outside the city are not counted`);
      let nearestOA = 0; for (let i = 1; i < N; i++) if (ds[i] < ds[nearestOA]) nearestOA = i;
      const d0f = Array.from(d0, (v) => (Number.isFinite(v) ? v : NaN)), d1f = Array.from(d1, (v) => (Number.isFinite(v) ? v : NaN));
      return {
        category: cat, category_label: cfg.label, demand_label: cfg.demandLabel,
        site: { lat: pyRound(lat, 5), lon: pyRound(lon, 5), ward: O.ward[nearestOA] },
        radius_m: Math.trunc(radius), walk_minutes: pyRound(radius / CFG.WALK_M_PER_MIN),
        existing_facilities: nFac,
        coverage_before_pct: pyRound(100 * cov0, 1), coverage_after_pct: pyRound(100 * cov1, 1),
        coverage_change_pct_points: pyRound(100 * (cov1 - cov0), 1),
        newly_covered: pyRound(newlyN),
        mean_distance_before_m: pyRound(wmean(w, d0f)), mean_distance_after_m: pyRound(wmean(w, d1f)),
        catchment_demand: pyRound(catchN),
        nearest_existing_m: nFac ? pyRound(nearest) : null,
        competitors_within_400m: comp, cannibalisation_flag: comp >= CFG.CANNIBALISATION_THRESHOLD,
        diversity_before: div0, diversity_after: div1,
        jobs_estimate: cfg.jobs[0], jobs_range: [cfg.jobs[1], cfg.jobs[2]],
        flood_zone3: flood, distance_to_city_edge_m: pyRound(edgeM),
        equity_newly_covered_by_quintile: byQ, equity_most_deprived_40pct: dep40,
        equity_most_deprived_40pct_share: newlyN >= 0.5 ? pyRound((100 * dep40) / newlyN) : 0,
        need_score: sc.need, viability_score: sc.viability,
        need_inputs_pct: sc.need_inputs_pct, viability_inputs_pct: sc.viability_inputs_pct,
        confidence: conf, confidence_reasons: reasons,
        insufficient_evidence: nFac < CFG.MIN_FACILITIES || sum(w) <= 0,
      };
    }

    function doNothing(cat, radius = CFG.DEFAULT_RADIUS_M, extra = null) {
      checkCategory(cat);
      const cov = coverage(demand(cat, extra), existingDist(cat), radius);
      return { category: cat, category_label: "Do nothing", radius_m: radius, coverage_before_pct: pyRound(100 * cov, 1),
        coverage_after_pct: pyRound(100 * cov, 1), coverage_change_pct_points: 0, newly_covered: 0, need_score: 0, viability_score: 0,
        jobs_estimate: 0, equity_most_deprived_40pct: 0 };
    }

    function argmax(a) { let b = 0; for (let i = 1; i < a.length; i++) if (a[i] > a[b]) b = i; return b; }
    function sensitivity(scen, extra = null) {
      const runs = [];
      for (const r of CFG.SENSITIVITY_RADII) {
        const res = scen.map((s) => evaluateSite(s.category, s.lat, s.lon, r, extra));
        runs.push({ label: `${r} m`, newly: res.map((x) => x.newly_covered), need: res.map((x) => x.need_score) });
      }
      for (const k of Object.keys(CFG.NEED_WEIGHTS)) for (const f of [0.8, 1.2]) {
        const nw = { ...CFG.NEED_WEIGHTS, [k]: CFG.NEED_WEIGHTS[k] * f };
        const res = scen.map((s) => evaluateSite(s.category, s.lat, s.lon, CFG.DEFAULT_RADIUS_M, extra, nw));
        runs.push({ label: `${k} x${f}`, newly: res.map((x) => x.newly_covered), need: res.map((x) => x.need_score) });
      }
      const wn = new Set(runs.map((r) => argmax(r.need)));
      const wc = new Set(runs.slice(0, CFG.SENSITIVITY_RADII.length).map((r) => argmax(r.newly)));
      const byR = {}; CFG.SENSITIVITY_RADII.forEach((r, i) => (byR[r] = runs[i].newly));
      const range = scen.map((_, i) => [Math.min(...runs.map((r) => r.need[i])), Math.max(...runs.map((r) => r.need[i]))]);
      return { runs, stable_need_ranking: wn.size === 1, stable_coverage_ranking: wc.size === 1, newly_covered_by_radius: byR, need_score_range: range };
    }

    function optimise(cat, k = 3, radius = CFG.DEFAULT_RADIUS_M, extra = null, excludeFlood = true) {
      checkCategory(cat);
      if (!(k >= 1 && k <= 5)) throw new EngineError("Choose between 1 and 5 new facilities.");
      const w = demand(cat, extra), d0 = existingDist(cat), Dm = candDist();
      const covered = new Uint8Array(N); for (let i = 0; i < N; i++) covered[i] = d0[i] <= radius ? 1 : 0;
      const picks = [];
      for (let step = 0; step < k; step++) {
        const gain = new Float64Array(N);
        for (let i = 0; i < N; i++) if (!covered[i]) { const wi = w[i]; for (let j = 0; j < N; j++) if (Dm[i * N + j] <= radius) gain[j] += wi; }
        if (excludeFlood) for (let j = 0; j < N; j++) if (O.flood[j]) gain[j] = -1;
        const j = argmax(gain);
        if (gain[j] <= 0) break;
        picks.push({ rank: step + 1, lat: pyRound(O.lat[j], 5), lon: pyRound(O.lon[j], 5), lat_exact: O.lat[j], lon_exact: O.lon[j],
          ward: O.ward[j], oa_code: O.code[j], marginal_newly_covered: pyRound(gain[j]) });
        for (let i = 0; i < N; i++) if (Dm[i * N + j] <= radius) covered[i] = 1;
      }
      let a = 0, t = 0; for (let i = 0; i < N; i++) { t += w[i]; if (covered[i]) a += w[i]; }
      const total = pyRound((a / t) * 100, 1), base = pyRound(coverage(w, d0, radius) * 100, 1);
      for (const p of picks) { p.coverage_before_pct = base; p.coverage_after_all_pct = total; }
      return picks;
    }

    function wardCentroid(ward) {
      const idx = []; for (let i = 0; i < N; i++) if (O.ward[i].toLowerCase() === ward.trim().toLowerCase()) idx.push(i);
      if (!idx.length) throw new EngineError(`No ward called '${ward}'.`);
      let px = 0, py = 0, pw = 0; for (const i of idx) { px += ox[i] * O.pop[i]; py += oy[i] * O.pop[i]; pw += O.pop[i]; }
      const cx = px / pw, cy = py / pw;
      let best = idx[0], bd = Infinity; for (const i of idx) { const d = Math.hypot(ox[i] - cx, oy[i] - cy); if (d < bd) { bd = d; best = i; } }
      return [O.lat[best], O.lon[best]];
    }

    // ---------------------------------------------------------------- brief payload, template and audit (src/brief.py)
    const SOURCE_TAGS = {
      census: "Census 2021 TS007A (ONS, OGL)", imd: "English Indices of Deprivation 2019 (MHCLG, OGL)",
      osm: "OpenStreetMap (ODbL)", nhs: "NHS Organisation Data Service (OGL)",
      flood: "Environment Agency Flood Map for Planning (OGL)", assumption: "Jobs-per-facility assumption table (ours, unvalidated)",
      engine: "Our coverage calculation (straight-line distance from Census 2021 Output Area centroids)",
    };
    const KEEP = ["category_label", "demand_label", "site", "radius_m", "walk_minutes", "existing_facilities",
      "coverage_before_pct", "coverage_after_pct", "coverage_change_pct_points", "newly_covered",
      "mean_distance_before_m", "mean_distance_after_m", "catchment_demand", "nearest_existing_m",
      "competitors_within_400m", "cannibalisation_flag", "jobs_estimate", "jobs_range", "flood_zone3",
      "equity_most_deprived_40pct", "equity_most_deprived_40pct_share", "need_score", "viability_score",
      "confidence", "confidence_reasons"];
    function buildPayload(results, sens, extra) {
      const p = {
        scenarios: results.map((r, i) => { const s = {}; for (const k of KEEP) if (k in r) s[k] = r[k]; s.scenario = String.fromCharCode(65 + i); return s; }),
        score_notes: "need_score and viability_score are 0-100 percentiles against every possible site in the city; weights are design choices, not validated",
        data_years: { census: 2021, imd: 2019 },
        definitions: { most_deprived_share_pct: 40, competition_radius_m: 400, score_scale_max: 100, demand_age_band: "0-4", sensitivity_weight_change_pct: 20 },
        sources: SOURCE_TAGS,
      };
      if (sens) p.sensitivity = { radii_tested_m: Object.keys(sens.newly_covered_by_radius).map(Number), newly_covered_by_radius: sens.newly_covered_by_radius,
        ranking_stable_across_radii_and_weights: sens.stable_need_ranking && sens.stable_coverage_ranking };
      if (extra) Object.assign(p, extra);
      return p;
    }
    function refusal(p) {
      const bad = p.scenarios.filter((s) => s.confidence === "Low");
      if (!bad.length) return null;
      const s = bad[0], reasons = (s.confidence_reasons && s.confidence_reasons.length ? s.confidence_reasons : ["data too thin"]).join("; ");
      return `Insufficient evidence. The tool will not make a recommendation for ${s.category_label.toLowerCase()} at this site because: ${reasons}. What is missing: a fuller register of existing ${s.category_label.toLowerCase()} sites. Add a better data source, then rerun.`;
    }
    const fmtInt = (n) => Number(n).toLocaleString("en-GB");
    const pyNum = (v) => (Number.isInteger(v) ? v.toFixed(1).replace(/\.0$/, ".0") : String(v));
    function template(p) {
      const lines = p.scenarios.map((s) =>
        `Scenario ${s.scenario}: a new ${s.category_label.toLowerCase()} in ${s.site.ward} would change ` +
        `${s.walk_minutes}-minute-walk coverage of ${s.demand_label} from ${pyNum(s.coverage_before_pct)}% to ` +
        `${pyNum(s.coverage_after_pct)}%, newly covering ${fmtInt(s.newly_covered)} people ` +
        `(${s.equity_most_deprived_40pct_share}% of them in the most deprived 40% of areas) [engine]. ` +
        `There are ${s.competitors_within_400m} existing ${s.category_label.toLowerCase()} sites within 400 m [osm]. ` +
        `Community need ${s.need_score}/100, commercial viability ${s.viability_score}/100. Confidence: ${s.confidence}.`);
      lines.push("Limits: straight-line distances from Census 2021 Output Area centroids; score weights are design choices, not validated; decision support only.");
      return lines.join("\n\n");
    }
    function flatten(o, out) {
      if (typeof o === "boolean" || o == null) return;
      if (typeof o === "number") { out.push(o); return; }
      if (typeof o === "string") { for (const m of o.match(/-?\d+(?:\.\d+)?/g) || []) out.push(parseFloat(m)); return; }
      if (Array.isArray(o)) { o.forEach((v) => flatten(v, out)); return; }
      for (const [k, v] of Object.entries(o)) { flatten(k, out); flatten(v, out); }
    }
    function audit(text, p) {
      const allowed = []; flatten(p, allowed);
      const body = text.replace(/\[[^\]]*\]/g, " ");
      const found = body.match(/(?<![\w.])-?\d[\d,]*(?:\.\d+)?/g) || [];
      const failed = [];
      for (const raw of found) {
        const n = parseFloat(raw.replace(/,/g, "")), dec = raw.includes(".") ? raw.split(".")[1].length : 0;
        if (!allowed.some((v) => pyRound(v, dec) === n || Math.abs(v - n) < 1e-9)) failed.push(raw);
      }
      return { ok: !failed.length && found.length > 0, checked: found.length, failed };
    }
    function brief(p) {
      const ref = refusal(p);
      if (ref) return { text: ref, mode: "refusal", audit: { ...audit(ref, p), ok: true } };
      const t = template(p);
      return { text: t, mode: "template", audit: audit(t, p) };
    }

    return { CATEGORIES, CFG, EngineError, N, wards, ox, oy, oa: O, fac, facilities, toBNG, insideCity, evaluateSite, doNothing,
      sensitivity, optimise, wardCentroid, buildPayload, brief, audit, template, pyRound, demand, existingDist, coverage };
  }

  const api = { create, CATEGORIES, CFG, EngineError, toBNG, pyRound };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.SimEngine = api;
})(typeof window !== "undefined" ? window : globalThis);
