// Business opportunity model: where would a given business do well in Southampton, and how feasible is a site?
// Deterministic, no AI. Inputs are the app's own data: residents by age at the 792 Output Area centres (city.json)
// and every named place (places.json). Every factor is a percentile against all 792 candidate sites, so 70 means
// "better than 70% of possible sites in the city". It is a comparison between sites, not a sales forecast.
import { SYN, catLabel, specOf } from '../lib/placeTypes.js'

// age groups: [key, label, column in city.json]
export const AGE_GROUPS = [['0_4', '0–4', 'pop04'], ['5_15', '5–15', 'pop_5_15'], ['16_24', '16–24', 'pop_16_24'],
  ['25_44', '25–44', 'pop_25_44'], ['45_64', '45–64', 'pop_45_64'], ['65', '65+', 'pop_65_plus']]
const ALL_AGES = AGE_GROUPS.map(a => a[0])

// default customers from words in the business name (first match wins), else from its sector
const CUSTOMER_RULES = [
  [/nurser|childcare|creche|crèche|pre ?school|playgroup|baby/, ['0_4']],
  [/school|tutor|tuition|toy|kids|children|soft play/, ['5_15', '25_44']],
  [/bubble|boba|nightclub|\bclub\b|\bbar\b|\bpub\b|gaming|esports|vape|tattoo|student/, ['16_24', '25_44']],
  [/gym|fitness|yoga|pilates|coffee|caf[eé]|takeaway|fast food|burger|pizza|sushi|ramen|korean|japanese|chinese|thai|indian|restaurant|barber|nail|salon/, ['16_24', '25_44', '45_64']],
  [/care home|mobility|hearing|funeral|retire/, ['65']],
  [/pharmac|chemist|\bgp\b|doctor|dentist|optician|clinic|health|supermarket|convenience/, ALL_AGES],
]
const SECTOR_CUSTOMERS = { 'Childcare, education and care': ['0_4', '5_15'], 'Food and drink': ['16_24', '25_44', '45_64'],
  'Leisure and hospitality': ['16_24', '25_44'], 'Personal services': ['16_24', '25_44', '45_64'] }
// sectors that live on passing trade: footfall counts for more
const FOOTFALL_SECTORS = new Set(['Food and drink', 'Retail', 'Leisure and hospitality', 'Personal services'])
// the five uses the planning engine also models (coverage, community need, audited brief)
const ENGINE_USES = [[/nurser|childcare|creche/, 'nursery'], [/\bgp\b|doctor|surgery/, 'gp'], [/pharmac|chemist/, 'pharmacy'],
  [/library/, 'library'], [/caf[eé]|coffee/, 'cafe']]

const norm = s => String(s || '').toLowerCase().replace(/é/g, 'e').replace(/[^a-z0-9 ]+/g, ' ').replace(/\s+/g, ' ').trim()
const COS = Math.cos((50.91 * Math.PI) / 180)
export const toXY = (lat, lon) => [lon * 111320 * COS, lat * 111320]

// every detailed type in the data with its count (for suggestions while typing)
export function businessTypes(places) {
  const o = {}
  for (const p of places) {
    if (p.ro) continue
    const k = specOf(p)
    if (/not known|no detail/.test(k)) continue
    const t = (o[k] ||= { label: k, n: 0, cat: p.cat, grp: p.grp })
    t.n++
  }
  return Object.values(o).sort((a, b) => b.n - a.n)
}

// free text -> the business type it most likely means, its category (related businesses) and default customers.
// Words in the type's own name or everyday words count most; a match only on the category ("restaurant") falls
// back to the whole category, so "Korean restaurant" with no Korean places is compared with all restaurants.
const hits = (words, text) => { const toks = norm(text).split(' '); return words.filter(w => toks.some(h => h.startsWith(w) || (h.length > 3 && w.startsWith(h)))).length }
export function matchBusiness(text, types) {
  const q = norm(text)
  if (!q) return null
  const words = q.split(' ').filter(w => w.length > 2)
  let best = null, bestCat = null
  for (const t of types) {
    const label = norm(t.label)
    const s = label === q ? 100 : norm(`${t.label} ${SYN[t.label] || ''}`).includes(q) ? 60 : 30 * hits(words, `${t.label} ${SYN[t.label] || ''}`)
    if (s > 0 && (!best || s + t.n / 100 > best.s + best.n / 100)) best = { ...t, s }
    const c = 10 * hits(words, catLabel(t.cat))
    if (c > 0 && (!bestCat || c > bestCat.c || (c === bestCat.c && t.n > bestCat.n))) bestCat = { ...t, c }
  }
  const engineUse = (ENGINE_USES.find(([re]) => re.test(q)) || [])[1] || null
  const rule = CUSTOMER_RULES.find(([re]) => re.test(q))
  const ages = g => (rule ? rule[1] : SECTOR_CUSTOMERS[g] || ALL_AGES)
  if (best && (best.s >= 60 || !bestCat || best.s >= 30 * Math.max(1, words.length - 1)))
    return { text, label: best.label, spec: best.label, cat: best.cat, grp: best.grp, n: best.n, matched: true, level: 'type', engineUse, ages: ages(best.grp) }
  if (bestCat) {
    const n = types.filter(t => t.cat === bestCat.cat).reduce((a, t) => a + t.n, 0)
    return { text, label: text.trim().replace(/^./, c => c.toUpperCase()), spec: null, cat: bestCat.cat, grp: bestCat.grp, n, matched: true, level: 'category', engineUse, ages: ages(bestCat.grp) }
  }
  return { text, label: text.trim().replace(/^./, c => c.toUpperCase()), spec: null, cat: null, grp: null, n: 0, matched: false, engineUse, ages: rule ? rule[1] : ALL_AGES }
}

// The local LLM's classification (rag/classify.py, checked against the data's own types) -> a target for analyse().
// Direct competitors = the chosen like-for-like types plus places in the same sector whose name contains a niche
// keyword ("Thai Orchid"); similar = other niches of the same kind (other cuisines); related = other same-sector types.
export function targetFromAI(c, text, types) {
  const q = norm(text), byLabel = Object.fromEntries(types.map(t => [t.label, t]))
  const first = byLabel[c.direct_types[0]] || byLabel[c.related_types[0]]
  return { text, label: (c.business || text).replace(/^./, ch => ch.toUpperCase()), niche: c.niche, grp: c.sector || first?.grp || null, cat: first?.cat || null,
    directSpecs: new Set(c.direct_types), similarSpecs: new Set(c.similar_types || []), relatedSpecs: new Set(c.related_types), keywords: c.name_keywords || [],
    ages: c.customers?.length ? c.customers : ALL_AGES, passing: c.passing_trade, reasoning: c.reasoning, tips: c.setup_tips || [],
    matched: c.direct_types.length > 0 || (c.name_keywords || []).length > 0, level: 'ai', source: 'ai', model: c.model,
    engineUse: (ENGINE_USES.find(([re]) => re.test(q) || re.test(norm(c.business))) || [])[1] || null,
    n: c.direct_types.reduce((a, k) => a + (byLabel[k]?.n || 0), 0) }
}

const ageCol = (o, col) => (col === 'pop04' ? o.pop04 : o.ages?.[col])

// Score every Output Area centre as a site for this business
export function analyse(city, places, target, { ages, radius = 800 }) {
  const o = city.oa, N = o.lat.length, R = radius
  const ox = new Float64Array(N), oy = new Float64Array(N)
  for (let i = 0; i < N; i++) [ox[i], oy[i]] = toXY(o.lat[i], o.lon[i])
  const groups = AGE_GROUPS.filter(([k, , c]) => ages.includes(k) && ageCol(o, c))
  const w = new Float64Array(N)
  for (const [, , c] of groups) { const a = ageCol(o, c); for (let i = 0; i < N; i++) w[i] += a[i] }
  if (!groups.length) for (let i = 0; i < N; i++) w[i] = o.pop[i]
  const pop21 = o.pop21 || o.pop
  // places: direct competitors (same niche), similar (another niche of the same kind, e.g. another cuisine),
  // related (same sector), customer-facing (footfall stand-in)
  const direct = [], similar = [], related = [], facing = []
  for (const p of places) {
    if (p.ro || !Number.isFinite(p.lat)) continue
    const [x, y] = toXY(p.lat, p.lon), q = { x, y, lat: p.lat, lon: p.lon, name: p.name, spec: specOf(p), ward: p.ward }
    let isDirect, isRelated, isSimilar = false
    if (target?.level === 'ai') {
      const name = norm(p.name), sameSector = !target.grp || p.grp === target.grp
      isDirect = target.directSpecs.has(q.spec) || (sameSector && target.keywords.some(k => name.split(' ').some(w => w.startsWith(k))))
      isSimilar = target.similarSpecs.has(q.spec)
      isRelated = target.relatedSpecs.has(q.spec)
    } else if (target?.level === 'category') { isDirect = p.cat === target.cat; isRelated = p.grp === target.grp }
    else { isDirect = target?.spec && q.spec === target.spec; isRelated = target?.cat && p.cat === target.cat }
    if (isDirect) direct.push(q)
    else if (isSimilar) similar.push(q)
    else if (isRelated) related.push(q)
    if (p.cf) facing.push(q)
  }
  // nothing like it in the data: a possible gap in the market, judged against similar businesses instead
  const gap = !direct.length && (target?.level === 'ai' || !target?.matched)
  const ctx = { city, o, N, R, ox, oy, w, pop21, groups, direct, similar, related, facing, target, ages, gap }
  const m = []
  for (let i = 0; i < N; i++) m.push(metricsAt(ctx, ox[i], oy[i]))
  // distributions for percentiles
  const sorted = k => Float64Array.from(m.map(x => x[k])).sort()
  ctx.dist = { demand: sorted('demand'), room: sorted('room'), footfall: sorted('footfall'), growth: sorted('growth') }
  ctx.weights = weightsFor(target)
  ctx.sites = m.map((x, i) => score(ctx, { ...x, i, lat: o.lat[i], lon: o.lon[i], ward: o.ward[i], flood: !!o.flood?.[i] }))
  // city benchmark: target customers per existing competitor across Southampton
  const totalW = w.reduce((a, b) => a + b, 0)
  ctx.cityPerCompetitor = direct.length ? totalW / direct.length : null
  ctx.totalCustomers = totalW
  return ctx
}

function weightsFor(target) {
  // the AI's "how much does it depend on passing trade" wins over the sector default
  if (target?.passing === 'high') return { demand: 0.3, room: 0.35, footfall: 0.25, growth: 0.1 }
  if (target?.passing === 'low') return { demand: 0.45, room: 0.4, footfall: 0.05, growth: 0.1 }
  if (target?.passing === 'medium') return { demand: 0.35, room: 0.35, footfall: 0.2, growth: 0.1 }
  return FOOTFALL_SECTORS.has(target?.grp) ? { demand: 0.3, room: 0.35, footfall: 0.25, growth: 0.1 } : { demand: 0.4, room: 0.4, footfall: 0.1, growth: 0.1 }
}

// raw measures for a site at BNG-like metres (x, y)
function metricsAt(ctx, x, y) {
  const { o, N, R, ox, oy, w, pop21, direct, similar, related, facing } = ctx
  let demand = 0, customers = 0, residents = 0, base = 0, cur = 0, dep = 0, u5 = 0, u521 = 0
  const ageMix = {}
  for (let j = 0; j < N; j++) {
    const d = Math.hypot(ox[j] - x, oy[j] - y)
    if (d > R) continue
    demand += w[j] * (1 - (0.5 * d) / R)  // nearer customers count more: full weight at the door, half at the edge
    customers += w[j]; residents += o.pop[j]; cur += o.pop[j]; base += pop21[j]
    if (o.q[j] <= 2) dep += w[j]
    if (o.pop0421) { u5 += o.pop04[j]; u521 += o.pop0421[j] }
    for (const [k, , c] of AGE_GROUPS) { const a = ageCol(o, c); if (a) ageMix[k] = (ageMix[k] || 0) + a[j] }
  }
  let comp = 0, comp400 = 0, compR = 0, nearest = null
  const near = []
  for (const p of direct) {
    const d = Math.hypot(p.x - x, p.y - y)
    if (nearest == null || d < nearest) nearest = d
    if (d <= R) { comp += 1 - (0.5 * d) / R; compR++; near.push({ ...p, d }) }
    if (d <= 400) comp400++
  }
  let rel = 0, relR = 0, sim = 0, simR = 0
  for (const p of related) { const d = Math.hypot(p.x - x, p.y - y); if (d <= R) { rel += 1 - (0.5 * d) / R; relR++ } }
  const nearSim = []
  for (const p of similar) { const d = Math.hypot(p.x - x, p.y - y); if (d <= R) { sim += 1 - (0.5 * d) / R; simR++; nearSim.push({ ...p, d }) } }
  nearSim.sort((a, b) => a.d - b.d)
  let footfall = 0
  for (const p of facing) if (Math.hypot(p.x - x, p.y - y) <= 400) footfall++
  // room in the market: customers per competitor; a similar niche (another cuisine) competes partly, related a little
  const room = demand / (1 + 2 * comp + 0.6 * sim + 0.3 * rel)
  const growth = base ? (100 * (cur - base)) / base : 0
  near.sort((a, b) => a.d - b.d)
  return { x, y, demand, customers, residents, dep, room, footfall, growth, u5Growth: u521 ? (100 * (u5 - u521)) / u521 : null,
    comp400, compR, nearest, near: near.slice(0, 6), relR, simR, nearSim: nearSim.slice(0, 4), ageMix }
}

function pct(sorted, v) {
  let lo = 0, hi = sorted.length
  while (lo < hi) { const mid = (lo + hi) >> 1; if (sorted[mid] < v) lo = mid + 1; else hi = mid }
  return Math.round((100 * lo) / Math.max(1, sorted.length - 1))
}

function score(ctx, s) {
  const { dist, weights } = ctx
  const f = { demand: pct(dist.demand, s.demand), room: pct(dist.room, s.room), footfall: pct(dist.footfall, s.footfall), growth: pct(dist.growth, s.growth) }
  for (const k in f) f[k] = Math.max(0, Math.min(100, f[k]))
  let total = 0
  for (const k in weights) total += weights[k] * f[k]
  if (s.flood) total -= 15
  return { ...s, factors: f, score: Math.max(0, Math.min(100, Math.round(total))) }
}

// a site the user clicked: same measures, ranked against the candidate sites
export function siteAt(ctx, lat, lon) {
  const [x, y] = toXY(lat, lon)
  let k = 0, best = Infinity
  for (let i = 0; i < ctx.N; i++) { const d = Math.hypot(ctx.ox[i] - x, ctx.oy[i] - y); if (d < best) { best = d; k = i } }
  return score(ctx, { ...metricsAt(ctx, x, y), i: null, lat, lon, ward: ctx.o.ward[k], flood: !!ctx.o.flood?.[k] && best < 150 })
}

// best sites: highest feasibility, outside flood zone 3, at least minSep metres apart, optionally in one ward
export function suggest(ctx, { k = 5, ward = null, minSep = 1000 } = {}) {
  const out = []
  for (const s of [...ctx.sites].sort((a, b) => b.score - a.score)) {
    if (s.flood || (ward && s.ward !== ward)) continue
    if (out.some(p => Math.hypot(p.x - s.x, p.y - s.y) < (ward ? minSep / 2 : minSep))) continue
    out.push(s)
    if (out.length === k) break
  }
  return out
}

export const verdict = s => (s >= 70 ? ['good', 'Strong opportunity'] : s >= 55 ? ['ok', 'Promising'] : s >= 40 ? ['warn', 'Mixed'] : ['bad', 'Challenging'])

const DIRS = ['north', 'north-east', 'east', 'south-east', 'south', 'south-west', 'west', 'north-west']
const direction = (a, b) => DIRS[Math.round(((Math.atan2(b.x - a.x, b.y - a.y) * 180) / Math.PI + 360) % 360 / 45) % 8]
const round = n => Math.round(n).toLocaleString('en-GB')
const custNoun = ctx => {
  const g = ctx.groups.map(([, l]) => l)
  return !g.length || g.length === AGE_GROUPS.length ? 'residents' : `people aged ${g.join(', ')}`
}

// Plain-language feasibility brief from the numbers above: strengths, risks, suggested changes, limitations
export function feasibilityBrief(ctx, s, nPlaces) {
  const t = ctx.target, label = t?.label || 'this business', minutes = Math.round(ctx.R / 80), f = s.factors
  const strengths = [], risks = [], changes = [], perComp = s.compR ? s.customers / s.compR : null
  const gap = perComp && ctx.cityPerCompetitor ? perComp / ctx.cityPerCompetitor : null
  if (f.demand >= 65) strengths.push(`${round(s.customers)} ${custNoun(ctx)} live within a ${minutes}-minute walk, more than at ${f.demand}% of sites in the city.`)
  else if (f.demand < 35) risks.push(`Fewer potential customers than most of the city: ${round(s.customers)} ${custNoun(ctx)} within a ${minutes}-minute walk.`)
  if (t?.matched && !ctx.gap) {
    if (!s.compR) strengths.push(`No other ${label.toLowerCase()} within ${ctx.R} m${s.nearest != null ? ` (nearest ${round(s.nearest)} m away)` : ''}.`)
    else if (s.comp400 >= 3) risks.push(`${s.comp400} ${label.toLowerCase()} already within 400 m: a crowded spot.`)
    if (gap != null && gap >= 1.5) strengths.push(`Each ${label.toLowerCase()} nearby has about ${round(perComp)} potential customers, ${gap.toFixed(1)}× the city average: likely under-served.`)
    else if (gap != null && gap <= 0.6) risks.push(`Each ${label.toLowerCase()} nearby has only about ${round(perComp)} potential customers, ${gap.toFixed(1)}× the city average.`)
  }
  if (ctx.weights.footfall >= 0.2) {
    if (f.footfall >= 65) strengths.push(`Busy spot: ${s.footfall} shops and services within 400 m bring passing trade.`)
    else if (f.footfall < 30) risks.push(`Quiet spot: ${s.footfall} shops and services within 400 m, so it relies on people coming on purpose.`)
  }
  if (ctx.gap) {
    const kinds = [...new Set(s.nearSim.map(p => p.spec))].slice(0, 3).join(', ')
    strengths.push(`Nothing like a ${label.toLowerCase()} is in the data${t?.keywords?.length ? ` (names searched for ${t.keywords.slice(0, 3).join(', ')})` : ''}: it would stand out as the first of its kind.`)
    if (s.simR >= 1 && s.simR <= 4) strengths.push(`${s.simR} similar business${s.simR === 1 ? '' : 'es'} within ${ctx.R} m (${kinds}) show people here already spend on this kind of thing.`)
    else if (s.simR > 4) risks.push(`${s.simR} similar businesses within ${ctx.R} m (${kinds}) compete for the same spending; the offer needs to be clearly different.`)
    else if (!s.relR) risks.push('Nothing similar nearby, so demand for this kind of business here is unproven.')
  }
  if (s.growth >= 3) strengths.push(`The population within walking distance grew ${s.growth.toFixed(1)}% since 2021.`)
  else if (s.growth <= -1) risks.push(`The population within walking distance fell ${Math.abs(s.growth).toFixed(1)}% since 2021.`)
  if (s.flood) risks.push('In flood zone 3: expect higher insurance costs and extra planning checks.')
  // a better site close by?
  const better = ctx.sites.filter(x => !x.flood && x.score >= s.score + 8 && Math.hypot(x.x - s.x, x.y - s.y) <= 1500)
    .sort((a, b) => b.score - a.score)[0]
  if (better) changes.push({ text: `Moving about ${round(Math.hypot(better.x - s.x, better.y - s.y) / 50) * 50} m ${direction(s, better)} (${better.ward}) raises feasibility from ${s.score} to ${better.score}.`, site: better })
  if (t?.matched && s.comp400 >= 2) changes.push({ text: `Stand out from the ${s.comp400} nearby ${label.toLowerCase()}: a different offer, opening hours or price point.` })
  if (f.demand < 40) changes.push({ text: 'Reach beyond walking distance: delivery, online booking or a site near a bus route.' })
  if (ctx.weights.footfall >= 0.2 && f.footfall < 30) changes.push({ text: 'Look for a unit on a local high street or next to a supermarket for passing trade.' })
  if (ctx.gap) changes.push({ text: `Possible gap in the market: check on the ground that no ${label.toLowerCase()} has opened recently, then lead with what makes it different from the similar businesses nearby.` })
  if (t?.level === 'category') changes.push({ text: `No exact match for “${t.text}” in the data, so it is compared with all ${t.n} similar businesses. A distinctive offer may face less competition than shown.` })
  const limits = [
    'Straight-line walking distance; rivers, railways and main roads aren’t taken into account.',
    `Competitors come from the places database (${round(nPlaces)} places in the current data); new or unlisted businesses are missed.`,
    'No rents, vacant units or footfall counts: nearby shops and services stand in for passing trade.',
    'Scores compare sites within Southampton. They are not a sales or profit forecast.',
    'Age groups for small areas are estimates spread from official population figures.',
  ]
  return { strengths, risks, changes, limits }
}
