// Business-idea classifier benchmark: the LLM behind POST /api/classify (rag/classify.py) against the quick
// keyword matcher the page falls back to (matchBusiness in frontend/src/simulator/opportunity.js).
// For each idea we hand-labelled which business types in the data are true like-for-like competitors ([] = none
// exist, a gap). A method scores a hit when its like-for-like types include an accepted one (or both are empty).
// Needs `python run.py api` (Groq with GROQ_API_KEY set, or Ollama).   Run from the repo root:  node evaluation/classify_benchmark.mjs
// PAUSE_MS between ideas (default 0; use 20000 on the Groq free plan, 8,000 tokens a minute).
import { readFileSync, writeFileSync } from 'node:fs'
import { businessTypes, matchBusiness } from '../frontend/src/simulator/opportunity.js'

const API = process.env.API || 'http://127.0.0.1:8000'
const PAUSE_MS = Number(process.env.PAUSE_MS || 0)
const health = await fetch(`${API}/api/health`).then(r => r.json()).catch(() => ({}))
const CASES = [
  ['japanese restaurant', ['Japanese']], ['sushi bar', ['Japanese']], ['korean bbq', ['Korean']],
  ['ramen shop', ['Japanese', 'Noodle bar']], ['thai takeaway', ['Thai']], ['dim sum restaurant', ['Chinese']],
  ['curry house', ['Indian']], ['vietnamese pho place', ['Vietnamese']], ['pizzeria', ['Pizza']],
  ['chippy', ['Fish and chips']], ['bubble tea shop', ['Bubble tea']], ['craft beer bar', ['Bar', 'Pub or bar', 'Pub/bar/nightclub']],
  ['gastropub', ['Pub', 'Pub or bar']], ['barber shop', ['Barber', 'Hairdresser or barber']], ['nail bar', ['Nail salon']],
  ['yoga studio', ['Gym or fitness centre', 'Sports facility']], ['halal butcher', ['Butcher', 'Halal food shop']],
  ['polish deli', ['Polish or Eastern European shop']], ['vape shop', ['Vape shop']],
  ['ice cream parlour', ['Desserts or ice cream', 'Ice cream or dessert']], ['dog grooming salon', []], ['kids coding club', []],
]

const cols = JSON.parse(readFileSync('frontend/public/data/places.json', 'utf8'))
const keys = Object.keys(cols)
const places = cols.id.map((_, i) => Object.fromEntries(keys.map(k => [k, cols[k][i]]))).filter(p => p.inside)
const types = businessTypes(places)
const sectors = [...new Set(types.map(t => t.grp).filter(Boolean))]
const hit = (pred, ok) => (ok.length ? pred.some(p => ok.includes(p)) : pred.length === 0)

const rows = []
for (const [idea, ok] of CASES) {
  if (rows.length && PAUSE_MS) await new Promise(r => setTimeout(r, PAUSE_MS))
  const q = matchBusiness(idea, types)
  // the matcher's like-for-like: one type; a category match counts every place in the category (not like-for-like)
  const quick = q?.level === 'type' ? [q.label] : q?.level === 'category' ? [`(all ${q.cat})`] : []
  const t0 = Date.now()
  let ai = null, err = null
  try {
    const r = await fetch(`${API}/api/classify`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: idea, types: types.slice(0, 300).map(({ label, cat, grp, n }) => ({ label, cat: cat || '', grp: grp || '', n })), sectors }) })
    const d = await r.json()
    if (d.ok) ai = d; else err = d.error
  } catch (e) { err = e.message }
  const aiPred = ai ? ai.direct_types : null
  rows.push({ idea, accepted: ok, quick, quick_hit: hit(quick, ok), ai: aiPred, ai_hit: aiPred ? hit(aiPred, ok) : false,
    ai_similar: ai?.similar_types || [], ai_sector: ai?.sector || null, seconds: (Date.now() - t0) / 1000, error: err })
  const r = rows.at(-1)
  console.log(`${r.quick_hit ? 'Y' : '-'} ${r.ai_hit ? 'Y' : '-'}  ${idea.padEnd(22)} quick=${JSON.stringify(quick)}  ai=${JSON.stringify(aiPred)}${err ? ' ERROR ' + err : ''}`)
}
const n = rows.length, sum = k => rows.filter(r => r[k]).length
const summary = { run: new Date().toISOString(), provider: health.provider || null, model: health.model || null, places: places.length, types: types.length, cases: n,
  quick_matcher_hits: sum('quick_hit'), llm_hits: sum('ai_hit'), llm_errors: rows.filter(r => r.error).length,
  mean_llm_seconds: +(rows.reduce((a, r) => a + r.seconds, 0) / n).toFixed(1), rows }
// the local run keeps its original file; other providers get their own, e.g. classify_benchmark_groq.json
const out = !health.provider || health.provider === 'ollama' ? 'evaluation/results/classify_benchmark.json' : `evaluation/results/classify_benchmark_${health.provider}.json`
writeFileSync(out, JSON.stringify(summary, null, 1))
console.log(`Saved ${out}`)
console.log(`\nQuick matcher ${summary.quick_matcher_hits}/${n}, LLM ${summary.llm_hits}/${n}, mean ${summary.mean_llm_seconds} s per idea`)
