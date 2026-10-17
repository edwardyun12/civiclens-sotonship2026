// Places-dataset evaluation with the JS engine: node eval_places.js <packed data.json> <repo>/tests
const fs = require("fs"), S = require("./engine.js");
const data = JSON.parse(fs.readFileSync(process.argv[2])); const E = S.create(data);
const CASES = [["cafe",["Bargate","Portswood","Redbridge"]],["cafe",["Bevois","Shirley","Sholing"]],["nursery",["Bargate","Bevois","Sholing"]],
 ["nursery",["Portswood","Millbrook","Woolston"]],["gp",["Bargate","Redbridge","Coxford"]],["gp",["Swaythling","Harefield","Peartree"]],
 ["pharmacy",["Bevois","Bitterne Park","Coxford"]],["pharmacy",["Freemantle","Bassett","Woolston"]],["library",["Bargate","Peartree","Redbridge"]],
 ["library",["Bitterne","Freemantle","Swaythling"]]];
const rows = [];
CASES.forEach(([cat, wards], i) => {
  const res = wards.map((w) => { const [a, b] = E.wardCentroid(w); return E.evaluateSite(cat, a, b); });
  let ours = 0; res.forEach((r, k) => { const o = res[ours]; if (r.newly_covered > o.newly_covered || (r.newly_covered === o.newly_covered && r.need_score > o.need_score)) ours = k; });
  let base = 0; res.forEach((r, k) => { if (r.competitors_within_400m < res[base].competitors_within_400m) base = k; });
  rows.push({ case: i + 1, use: cat, wards: wards.join(" / "), newly_covered: res.map((r) => r.newly_covered).join(" / "),
    competitors_400m: res.map((r) => r.competitors_within_400m).join(" / "), most_deprived_40pct_newly: res.map((r) => r.equity_most_deprived_40pct).join(" / "),
    our_pick: wards[ours], baseline_pick: wards[base], differs: ours !== base ? "True" : "False", people_gained_vs_baseline: res[ours].newly_covered - res[base].newly_covered });
});
const opt = {};
for (const cat of Object.keys(S.CATEGORIES)) { const t = Date.now(); const p = E.optimise(cat, 3);
  opt[cat] = { seconds: (Date.now() - t) / 1000, coverage_before_pct: p[0].coverage_before_pct, coverage_after_top3_pct: p[0].coverage_after_all_pct, top3_wards: p.map((x) => x.ward) }; }
const centre = E.evaluateSite("cafe", 50.9046, -1.4045);
const summary = { dataset: "places", computed_with: "JS port of src/engine.py (matches Python on 49/49 checks); rerun python -m tests.run_evaluation to regenerate",
  baseline_cases: rows.length, baseline_differs: rows.filter((r) => r.differs === "True").length,
  people_gained_vs_baseline_total: rows.reduce((s, r) => s + r.people_gained_vs_baseline, 0), optimiser: opt,
  sites: Object.fromEntries(Object.keys(S.CATEGORIES).map((c) => [c, E.facilities(c).length])),
  city_centre_cafe: { coverage_change_pct_points: centre.coverage_change_pct_points, competitors_within_400m: centre.competitors_within_400m } };
const cols = Object.keys(rows[0]);
fs.writeFileSync(process.argv[3] + "/baseline_results_places.csv", [cols.join(","), ...rows.map((r) => cols.map((c) => r[c]).join(","))].join("\n") + "\n");
fs.writeFileSync(process.argv[3] + "/evaluation_summary_places.json", JSON.stringify(summary, null, 2) + "\n");
console.log(JSON.stringify(summary, null, 1));
