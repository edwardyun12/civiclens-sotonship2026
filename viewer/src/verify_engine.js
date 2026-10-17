// Compare the JS port with the Python engine's saved results (tests/evaluation_summary.json, baseline_results.csv).
const fs = require("fs");
const path = require("path");
const repo = process.argv[2];
const S = require("./engine.js");
const E = S.create(JSON.parse(fs.readFileSync(path.join(__dirname, "data.json"))));  // data.json = pack_city.py output for the 17 Oct baseline
let pass = 0, fail = 0;
const check = (name, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  ok ? pass++ : fail++;
  if (!ok) console.log("FAIL", name, "got", JSON.stringify(got), "want", JSON.stringify(want));
};

const summ = JSON.parse(fs.readFileSync(path.join(repo, "tests/evaluation_summary.json")));
let t = Date.now();
for (const [cat, o] of Object.entries(summ.optimiser)) {
  const p = E.optimise(cat, 3);
  check(`opt ${cat} before`, p[0].coverage_before_pct, o.coverage_before_pct);
  check(`opt ${cat} after`, p[0].coverage_after_all_pct, o.coverage_after_top3_pct);
  check(`opt ${cat} wards`, p.map((x) => x.ward), o.top3_wards);
}
console.log("optimiser (incl. distance matrix) ms", Date.now() - t);

const rows = fs.readFileSync(path.join(repo, "tests/baseline_results.csv"), "utf8").trim().split("\n").slice(1);
for (const line of rows) {
  const c = line.split(",");
  const cat = c[1], wards = c[2].split(" / ");
  const res = wards.map((w) => { const [la, lo] = E.wardCentroid(w); return E.evaluateSite(cat, la, lo); });
  check(`case ${c[0]} newly`, res.map((r) => r.newly_covered).join(" / "), c[3]);
  check(`case ${c[0]} comp`, res.map((r) => r.competitors_within_400m).join(" / "), c[4]);
  check(`case ${c[0]} dep40`, res.map((r) => r.equity_most_deprived_40pct).join(" / "), c[5]);
}

// Handover demo numbers
const centre = E.evaluateSite("cafe", 50.9046, -1.4045);
check("cafe centre change", centre.coverage_change_pct_points, 0);
console.log("cafe centre competitors", centre.competitors_within_400m, "need", centre.need_score, "via", centre.viability_score, centre.confidence_reasons);
// Outside city
try { E.evaluateSite("cafe", 50.95, -1.2); check("outside city error", "no error", "error"); } catch (e) { check("outside city error", e.constructor.name, "EngineError"); }
// Template audit passes, injected number fails
const r = [E.evaluateSite("library", 50.933, -1.37), E.evaluateSite("cafe", 50.933, -1.37)];
const sens = E.sensitivity(r.map((x, i) => ({ category: x.category, lat: 50.933, lon: -1.37 })));
const p = E.buildPayload(r, sens);
const b = E.brief(p);
check("template audit ok", b.audit.ok, true);
check("injected number caught", E.audit(b.text + " It would cover 123456 people.", p).ok, false);
console.log(b.text, "\n", b.audit, "\nsens stable", sens.stable_need_ranking, sens.stable_coverage_ranking);
console.log(`\n${pass} passed, ${fail} failed`);
