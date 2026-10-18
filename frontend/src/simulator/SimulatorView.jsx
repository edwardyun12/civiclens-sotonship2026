// Business simulator: type what you want to open; the opportunity model (opportunity.js) scores every site in
// Southampton on customers nearby (by age), competitors, passing trade and population growth, proposes the best
// sites, and explains how feasible any site is. For the five public-service uses the planning engine
// (viewer/src/engine.js, a verified port of simulator/engine.py) adds coverage and an audited planning brief.
import { Fragment, useEffect, useMemo, useState } from 'react'
import L from 'leaflet'
import { Circle, CircleMarker, MapContainer, Marker, Polygon, TileLayer, Tooltip, useMapEvents } from 'react-leaflet'
import { AlertTriangle, BadgeCheck, CheckCircle2, ChevronLeft, ChevronRight, ClipboardList, Crosshair, Droplets, Footprints, Info, Lightbulb,
  Loader2, Map as MapIcon, MapPin, Search, ShieldAlert, Sparkles, Store, Target, TrendingUp, Users } from 'lucide-react'
import '@engine'
import { fmt, metres, placeRows, useData } from '../lib/cityData.js'
import { FitCity, KeepInView } from '../lib/MapFit.jsx'
import { businessWords, findPlace, setAssistantContext } from '../lib/assistantContext.js'
import { AGE_GROUPS, analyse, businessTypes, feasibilityBrief, matchBusiness, siteAt, suggest, targetFromAI, verdict } from './opportunity.js'

const SimEngine = window.SimEngine
// quick picks: these when the data has them, topped up with the most common types
const QUICK = ['Café', 'Coffee shop', 'Bubble tea', 'Barber', 'Day nursery or childcare', 'Pharmacy', 'Gym or fitness centre', 'Takeaway']
const SCOPES = [['city', 'Whole Southampton', MapIcon], ['area', 'Choose an area', Search], ['map', 'Pick on map', Crosshair]]
const TONE = { good: '#2f7a4f', ok: '#7bbf1f', warn: '#d38b1c', bad: '#c0392b' }
const COMPETITOR = '#f0544f', RELATED = '#8a9bb0'
// business markers: coral ring for competitors, small soft dot for related businesses; CSS makes them grow on hover
const bizIcons = {}
const bizIcon = kind => (bizIcons[kind] ||= L.divIcon({ className: 'biz-dot-wrap', iconSize: kind === 'comp' ? [18, 18] : [12, 12],
  tooltipAnchor: [0, kind === 'comp' ? -9 : -6], html: `<span class="biz-dot ${kind}"></span>` }))
const distText = m => (m < 1000 ? `${Math.round(m / 10) * 10}\u00a0m` : `${(m / 1000).toFixed(1)}\u00a0km`)

// teardrop map pin coloured by feasibility, with the rank (or an icon) inside; the open site is larger with a pulse
const pinIcons = new Map()
function pinIcon(label, color, on) {
  const key = `${label}|${color}|${on}`
  if (!pinIcons.has(key)) {
    const w = on ? 40 : 30, h = Math.round(w * 1.3)
    pinIcons.set(key, L.divIcon({ className: 'site-pin-wrap', iconSize: [w, h], iconAnchor: [w / 2, h], tooltipAnchor: [0, -h + 4],
      html: `<div class="site-pin${on ? ' on' : ''}" style="--pin:${color}">${on ? '<i class="pulse"></i>' : ''}<svg viewBox="0 0 30 39" width="${w}" height="${h}" aria-hidden="true">
        <path d="M15 38c-1-3.6-3.4-7-6.5-10.5C5 23.6 1.5 20 1.5 14.5a13.5 13.5 0 0 1 27 0c0 5.5-3.5 9.1-7 13C18.4 31 16 34.4 15 38z" fill="var(--pin)" stroke="#fff" stroke-width="2"/>
        <circle cx="15" cy="14.5" r="8.6" fill="#fff"/></svg><b>${label}</b></div>` }))
  }
  return pinIcons.get(key)
}

// hover card, key details only: competitor or related, name, what it is, walk from the selected site
function PlaceTip({ p, kind, site }) {
  const comp = kind === 'Competitor', d = site ? metres(site.lat, site.lon, p.lat, p.lon) : null
  return <div className="biz-card">
    <span className={`biz-chip ${comp ? 'comp' : 'rel'}`}>{kind}</span>
    <b>{p.name || 'Unnamed business'}</b>
    <span className="biz-type">{p.spec || 'Type not known'}</span>
    {d != null && <span className="biz-meta"><Footprints size={12} /> {distText(d)} from your site</span>}
  </div>
}

// AI classifications already made this session (the local model takes a few seconds per idea)
const classified = new Map()
// ask the local LLM (same model as the assistant) to classify an idea against the data's own sectors and types
function classifyIdea(idea, types) {
  const key = idea.trim().toLowerCase()
  if (!classified.has(key)) {
    const job = fetch('/api/classify', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: idea, types: types.slice(0, 300).map(({ label, cat, grp, n }) => ({ label, cat: cat || '', grp: grp || '', n })),
        sectors: [...new Set(types.map(x => x.grp).filter(Boolean))] }) })
      .then(r => r.json()).then(d => { if (!d.ok) throw new Error(d.error || 'no answer'); return d })
    job.catch(() => classified.delete(key))   // a failure is not remembered, so it can be retried
    classified.set(key, job)
  }
  return classified.get(key)
}

function ClickToPlace({ on }) { useMapEvents({ click: e => on([e.latlng.lat, e.latlng.lng]) }); return null }

export default function SimulatorView() {
  const [city, error] = useData('city')
  const [cols] = useData('places')
  const [hoods] = useData('neighbourhoods')
  const places = useMemo(() => (cols ? placeRows(cols).filter(p => p.inside) : []), [cols])
  const types = useMemo(() => businessTypes(places), [places])
  const quick = useMemo(() => { const have = new Set(types.map(t => t.label)); const q = QUICK.filter(x => have.has(x)); for (const t of types) if (q.length < 6 && !q.includes(t.label)) q.push(t.label); return q.slice(0, 6) }, [types])
  const E = useMemo(() => (city ? SimEngine.create(city) : null), [city])

  const [text, setText] = useState('')
  const [typed, setQuery] = useState('')               // what is analysed (typing settles first)
  const query = typed.trim() ? typed : quick[0] || 'Café'  // empty box: show a starter business so the map is never blank
  const [ages, setAges] = useState(null)               // null = the business's default customers
  const [radius, setRadius] = useState(800)
  const [scope, setScope] = useState('city')
  const [area, setArea] = useState('')
  const [pick, setPick] = useState(0)                  // which suggested site is open
  const [point, setPoint] = useState(null)             // a site clicked on the map
  const [flood, setFlood] = useState(false)
  const [ai, setAi] = useState({ status: 'idle' })     // the local LLM's reading of the idea: idle | loading | done | error
  useEffect(() => { const t = setTimeout(() => setQuery(text), 350); return () => clearTimeout(t) }, [text])

  // the typed idea is classified by the local LLM; results build on that classification
  const askAI = async idea => {
    if (idea.trim().length < 2 || !types.length) return
    setText(idea); setQuery(idea)
    setAi({ status: 'loading', text: idea })
    try {
      const d = await classifyIdea(idea, types)
      setAi(cur => (cur.text === idea ? { status: 'done', text: idea, result: d } : cur))
    } catch (e) {
      setAi(cur => (cur.text === idea ? { status: 'error', text: idea, error: e.message } : cur))
    }
  }
  // ?idea=thai%20restaurant#simulator analyses an idea straight from a link
  useEffect(() => { const idea = new URLSearchParams(window.location.search).get('idea'); if (idea && types.length) askAI(idea) }, [types.length > 0])
  const aiReady = ai.status === 'done' && ai.text.trim().toLowerCase() === query.trim().toLowerCase()
  const target = useMemo(() => (!types.length ? null : aiReady ? targetFromAI(ai.result, query, types) : matchBusiness(query, types)), [query, types, aiReady, ai])
  useEffect(() => { setAges(null); setPick(0) }, [target?.label])
  const customers = ages || target?.ages || AGE_GROUPS.map(a => a[0])
  const ctx = useMemo(() => (city && places.length && target ? analyse(city, places, target, { ages: customers, radius }) : null),
    [city, places, target, customers.join(), radius])
  const picks = useMemo(() => (ctx ? suggest(ctx, scope === 'area' && area ? { k: 3, ward: area } : { k: 5 }) : []), [ctx, scope, area])
  const site = useMemo(() => (!ctx ? null : scope === 'map' ? (point ? siteAt(ctx, point[0], point[1]) : null) : picks[Math.min(pick, picks.length - 1)] || null),
    [ctx, scope, point, picks, pick])
  const brief = useMemo(() => (ctx && site ? feasibilityBrief(ctx, site, places.length) : null), [ctx, site, places.length])
  // planning engine view for the five public-service uses
  const engine = useMemo(() => {
    if (!E || !site || !target?.engineUse) return null
    try {
      const r = E.evaluateSite(target.engineUse, site.lat, site.lon, radius)
      return { r, brief: E.brief(E.buildPayload([r], E.sensitivity([{ category: target.engineUse, lat: site.lat, lon: site.lon }]))) }
    } catch (e) { return { error: e.message } }
  }, [E, site, target?.engineUse, radius])

  const outlines = useMemo(() => (city ? city.ward_outlines : {}), [city])
  const wards = useMemo(() => Object.keys(outlines).sort(), [outlines])
  const onMap = p => { setPoint(p); setScope('map') }
  const choosePick = i => { setPick(i); if (scope === 'map') setScope('city') }

  // a chat question that names an area or neighbourhood ("a Japanese store in Weston") gets the model's own analysis
  // of that place, for the business it names (quick type matching) or else the business on screen
  const aboutQuestion = async question => {
    const place = findPlace(question, Object.keys(city?.ward_outlines || {}), hoods)
    if (!place || !ctx) return ''
    const words = businessWords(question, place.name)
    let t = target
    if (words && words.toLowerCase() !== target.text?.trim().toLowerCase()) {
      const quick = matchBusiness(words, types)
      if (quick?.level === 'type') t = quick
      else {
        try { t = targetFromAI(await classifyIdea(words, types), words, types) } catch { t = quick || target }
      }
    }
    const c = t === target ? ctx : analyse(city, places, t, { ages: t.ages, radius })
    const s = place.kind === 'ward' ? suggest(c, { k: 1, ward: place.ward })[0] : siteAt(c, place.lat, place.lon)
    if (!s) return `The question is about ${place.name}; no suitable site was found there (flood zone or no data).`
    const b = feasibilityBrief(c, s, places.length), f = s.factors, best = suggest(c, { k: 3 })
    return [
      `The question is about ${place.name}${place.kind === 'neighbourhood' ? ` (a neighbourhood in ${place.ward} ward)` : ' ward'}. Answer about ${place.name}, not about the site selected on screen.`,
      t.level === 'ai' && t !== target ? `AI classification of "${words}": ${t.label}; sector ${t.grp}; niche ${t.niche}; like-for-like types ${[...t.directSpecs].join(', ') || 'none in the data'}; name keywords ${t.keywords.join(', ')}.` : '',
      `Business analysed: ${t.label}${t === target ? ' (the business on screen)' : ` (read from the question "${words}")`}${t.level === 'category' ? `; no exact type in the data, so compared with all ${t.n} similar businesses` : ''}${t.matched ? '' : '; none like it in the data'}.`,
      c.gap ? `No ${t.label} exists in the data: a possible gap in the market. ${c.similar.length} similar businesses (other niches of the same kind${t.similarSpecs?.size ? `: ${[...t.similarSpecs].slice(0, 5).join(', ')}` : ''}) are used instead to judge competition and demand.` : '',
      `App analysis for ${place.name} (${place.kind === 'ward' ? 'best site in the ward' : 'at the neighbourhood centre'}): feasibility ${s.score}/100 (${verdict(s.score)[1]}). Factors (percentile vs all sites in Southampton): customers ${f.demand}, room in the market ${f.room}, passing trade ${f.footfall}, growth ${f.growth}.`,
      `${Math.round(s.customers)} target customers and ${Math.round(s.residents)} residents within ${radius} m; ${s.compR} direct competitors within ${radius} m${s.nearest != null ? `, nearest ${Math.round(s.nearest)} m away` : ''}; ${s.simR} similar businesses${s.nearSim.length ? ` (${[...new Set(s.nearSim.map(p => p.spec))].join(', ')})` : ''}; ${s.relR} related businesses; ${s.footfall} shops/services within 400 m; population change since 2021 ${s.growth.toFixed(1)}%;${s.flood ? ' in flood zone 3;' : ''}`,
      b.strengths.length ? `Strengths in ${place.name}: ${b.strengths.join(' ')}` : '', b.risks.length ? `Risks in ${place.name}: ${b.risks.join(' ')}` : '',
      best.length ? `For comparison, the best sites in Southampton for ${t.label}: ${best.map((p, i) => `${i + 1}. ${p.ward} ${p.score}/100`).join('; ')}.` : '',
    ].filter(Boolean).join('\n')
  }

  // tell the assistant what is on screen
  useEffect(() => {
    if (!ctx || !site || !brief) return
    const [, v] = verdict(site.score), f = site.factors
    setAssistantContext([
      target.level === 'ai' ? `AI classification of "${target.text}": ${target.label}; sector ${target.grp}; niche ${target.niche}; like-for-like types ${[...target.directSpecs].join(', ') || 'none in the data'}; name keywords ${target.keywords.join(', ')}; related ${[...target.relatedSpecs].join(', ')}; passing trade ${target.passing}. ${target.reasoning}` : '',
      `Page: Business simulator. Business: ${target.label}${ctx.gap ? ' (none in the data: a possible gap in the market)' : ''}. Customers: ${customers.map(k => AGE_GROUPS.find(a => a[0] === k)[1]).join(', ')}. Walking distance ${radius} m.`,
      `Search: ${scope === 'area' ? `area ${area || 'not chosen'}` : scope === 'map' ? 'site picked on the map' : 'whole Southampton'}.`,
      `Selected site in ${site.ward}: feasibility ${site.score}/100 (${v}). Factors (percentile vs all sites): customers ${f.demand}, room in the market ${f.room}, passing trade ${f.footfall}, growth ${f.growth}.`,
      `${Math.round(site.customers)} target customers and ${Math.round(site.residents)} residents within walking distance; ${site.compR} direct competitors within ${radius} m (${site.comp400} within 400 m); ${site.simR} similar businesses (other niches of the same kind); ${site.relR} related businesses; ${site.footfall} shops/services within 400 m; population change since 2021 ${site.growth.toFixed(1)}%;${site.flood ? ' in flood zone 3;' : ''}`,
      brief.strengths.length ? `Strengths: ${brief.strengths.join(' ')}` : '', brief.risks.length ? `Risks: ${brief.risks.join(' ')}` : '',
      brief.changes.length ? `Suggested changes: ${brief.changes.map(c => c.text).join(' ')}` : '',
      picks.length ? `Top suggested sites: ${picks.map((p, i) => `${i + 1}. ${p.ward} ${p.score}/100`).join('; ')}.` : '',
      engine?.r ? `Planning view (${engine.r.category_label}): coverage ${engine.r.coverage_before_pct}% -> ${engine.r.coverage_after_pct}%, ${engine.r.newly_covered} newly within walking distance, community need ${engine.r.need_score}/100.` : '',
    ].filter(Boolean).join('\n'), aboutQuestion)
  }, [ctx, site, brief, picks, engine, scope, area, hoods])

  if (error) return <div className="tool-error">{error.message}</div>
  if (!city || !cols) return <div className="tool-error">Loading the city…</div>
  const showSite = site && [site.lat, site.lon]

  return <div className="map-stage">
    <MapContainer center={[50.92, -1.40]} zoom={13} minZoom={11} zoomSnap={0.25} scrollWheelZoom className="map-canvas" zoomControl={false} preferCanvas>
      <TileLayer attribution='&copy; OpenStreetMap contributors · Population: ONS' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
      <FitCity city={city} right />
      <ClickToPlace on={onMap} />
      {showSite && <KeepInView at={showSite} right />}
      {flood && city.flood.map((poly, i) => <Polygon key={'f' + i} positions={poly.map(r => r.map(([x, y]) => [y, x]))} interactive={false}
        pathOptions={{ stroke: false, fillColor: '#3d78b8', fillOpacity: 0.35, fillRule: 'evenodd' }} />)}
      {scope === 'area' && area && outlines[area] && <Polygon positions={outlines[area].map(r => r.map(([x, y]) => [y, x]))} interactive={false}
        pathOptions={{ color: '#062b25', weight: 3, fillColor: '#d7ff3f', fillOpacity: 0.06 }} />}
      {ctx && ctx.related.map((p, i) => <Marker key={'r' + i} position={[p.lat, p.lon]} icon={bizIcon('rel')} zIndexOffset={-200}>
        <Tooltip direction="top" className="biz-tip"><PlaceTip p={p} kind="Related business" site={site} /></Tooltip></Marker>)}
      {ctx && ctx.similar.map((p, i) => <Marker key={'s' + i} position={[p.lat, p.lon]} icon={bizIcon('rel')} zIndexOffset={-100}>
        <Tooltip direction="top" className="biz-tip"><PlaceTip p={p} kind="Similar business" site={site} /></Tooltip></Marker>)}
      {ctx && ctx.direct.map((p, i) => <Marker key={'d' + i} position={[p.lat, p.lon]} icon={bizIcon('comp')} zIndexOffset={0}>
        <Tooltip direction="top" className="biz-tip"><PlaceTip p={p} kind="Competitor" site={site} /></Tooltip></Marker>)}
      {site && <Circle center={showSite} radius={radius} interactive={false} pathOptions={{ color: '#062b25', weight: 2, dashArray: '6 6', fillColor: '#d7ff3f', fillOpacity: 0.1 }} />}
      {scope !== 'map' && picks.map((p, i) => { const on = site === p
        return <Marker key={'p' + i + on} position={[p.lat, p.lon]} icon={pinIcon(i + 1, TONE[verdict(p.score)[0]], on)} zIndexOffset={on ? 1000 : 500 - i}
          eventHandlers={{ click: () => choosePick(i) }}>
          <Tooltip direction="top" className="biz-tip"><div className="biz-card"><span className={`biz-chip ${verdict(p.score)[0]}`}>Suggested site {i + 1}</span><b>{p.ward}</b><span className="biz-type">{verdict(p.score)[1]} · <span className="nowrap">{p.score}/100</span></span></div></Tooltip></Marker> })}
      {scope === 'map' && site && <Marker position={showSite} icon={pinIcon('★', TONE[verdict(site.score)[0]], true)} zIndexOffset={1000}>
        <Tooltip permanent direction="top" className="site-label">Your site</Tooltip></Marker>}
    </MapContainer>

    <aside className="tool-panel">
      <span className="eyebrow dark"><Target size={13} /> Business simulator</span>
      <h2>Where should my business go?</h2>
      <label className="field-label" htmlFor="biz">What do you want to open?</label>
      <form className="idea-form" onSubmit={e => { e.preventDefault(); askAI(text) }}>
        <label className="search"><Store size={15} /><input id="biz" list="biz-types" value={text} onChange={e => setText(e.target.value)} placeholder="Thai restaurant, dog grooming, kids coding club…" /></label>
      </form>
      <datalist id="biz-types">{types.slice(0, 200).map(t => <option key={t.label} value={t.label} />)}</datalist>
      <div className="chips small">{quick.map(q => <button key={q} className={query === q ? 'on' : ''} onClick={() => askAI(q)}>{q.replace(' or childcare', '').replace(' or fitness centre', '')}</button>)}</div>
      {target && target.level !== 'ai' && ai.status !== 'loading' && <p className={`match ${target.matched ? '' : 'gap'}`}>{target.matched
        ? target.level === 'category' ? <>No exact match, so compared with all <b>{fmt(target.n)} {catText(target.cat)}</b> in the data.</>
          : <>Compared with <b>{fmt(target.n)} {target.label.toLowerCase()}</b> in the data; related: other {catText(target.cat)}.</>
        : <>No “{target.text}” in the data yet: a possible gap in the market. Check the area on the ground for competitors.</>}</p>}

      <label className="field-label">Your customers</label>
      <div className="chips small age-chips">{AGE_GROUPS.map(([k, l]) => <button key={k} className={customers.includes(k) ? 'on' : ''}
        onClick={() => setAges(customers.includes(k) ? (customers.length > 1 ? customers.filter(x => x !== k) : customers) : [...customers, k])}>{l}</button>)}</div>

      <label className="field-label">Where</label>
      <div className="seg-light three">{SCOPES.map(([id, label, Icon]) => <button key={id} className={scope === id ? 'on' : ''} onClick={() => setScope(id)}><Icon size={14} /> {label}</button>)}</div>
      {scope === 'area' && <select value={area} onChange={e => { setArea(e.target.value); setPick(0) }} aria-label="Area">
        <option value="" disabled>Choose an area…</option>{wards.map(w => <option key={w} value={w}>{w}</option>)}
      </select>}
      {scope === 'map' && <p className="muted">Click anywhere on the map to test that spot.</p>}
      {target && scope !== 'map' && (scope === 'city' || area) && <ol className="pick-list">{picks.map((p, i) => { const [tone, label] = verdict(p.score)
        return <li key={i}><button className={site === p ? 'on' : ''} onClick={() => choosePick(i)}>
          <span className="rank" style={{ background: TONE[tone] }}>{i + 1}</span><span><b>{p.ward}</b><small>{label}</small></span><span className={`pill ${tone}`}>{p.score}</span></button></li> })}
        {!picks.length && <li className="muted">No suitable site outside the flood zone here.</li>}</ol>}

      <label className="field-label" htmlFor="rad">Walking distance: {radius} m · about {Math.round(radius / 80)} minutes</label>
      <input id="rad" type="range" min="400" max="1200" step="100" value={radius} onChange={e => setRadius(+e.target.value)} />
      <label className="check"><input type="checkbox" checked={flood} onChange={e => setFlood(e.target.checked)} /> Show flood zone 3</label>
    </aside>

    {!target ? <aside className="result-card"><h2>What do you want to open?</h2><p className="muted">Type a business on the left and press Enter to see the best sites across Southampton.</p></aside>
      : site ? <SiteResult ctx={ctx} site={site} brief={brief} engine={engine} target={target} radius={radius}
      nav={scope !== 'map' && picks.length > 1 ? { i: picks.indexOf(site), n: picks.length, go: d => setPick((picks.indexOf(site) + d + picks.length) % picks.length) } : null}
      onSite={s => { setPoint([s.lat, s.lon]); setScope('map') }} />
      : <aside className="result-card"><h2>{scope === 'area' ? 'Choose an area' : 'Pick a spot'}</h2><p className="muted">{scope === 'area' ? 'Pick an area on the left to see the best sites in it.' : 'Click the map to test any spot in Southampton.'}</p></aside>}

    <div className="legend tool-legend">
      <span className="key"><i style={{ background: TONE.good, borderRadius: '50% 50% 50% 0', transform: 'rotate(-45deg)' }} />Suggested site (colour = feasibility)</span>
      <span className="key"><i className="biz-dot comp key-dot" />Competitor</span>
      <span className="key"><i className="biz-dot rel key-dot" />Similar or related business</span>
      {flood && <span className="key"><i style={{ background: '#3d78b8' }} />Flood zone 3</span>}
    </div>
  </div>
}

const catText = c => ({ restaurant_cafe: 'restaurants and cafés', takeaway: 'takeaways', pub_bar: 'pubs and bars', shop_food: 'food shops',
  shop_other: 'shops', hair_beauty: 'hair and beauty', health_other: 'health services', nursery: 'childcare', leisure: 'leisure places' }[c] || 'businesses of this kind')

function Factor({ label, value, hint }) {
  const tone = value >= 65 ? 'good' : value >= 45 ? 'ok' : value >= 30 ? 'warn' : 'bad'
  return <div className={`factor ${tone}`}><div><span>{label}</span><b>{value}</b></div><span className="track"><i style={{ width: `${Math.max(3, value)}%` }} /></span><small>{String(hint).replace(/(\d) (?=(m|min)\b)/g, '$1\u00a0')}</small></div>
}

function SiteResult({ ctx, site: s, brief, engine, target, radius, nav, onSite }) {
  const [tone, label] = verdict(s.score), f = s.factors, minutes = Math.round(radius / 80)
  const perComp = s.compR ? s.customers / s.compR : null
  const ageTotal = Object.values(s.ageMix).reduce((a, b) => a + b, 0) || 1
  return <aside className="result-card">
    <div className="result-top">
      <span className="place-kicker"><MapPin size={13} /> {s.ward}</span>
      {nav && <span className="site-nav"><button onClick={() => nav.go(-1)} aria-label="Previous site"><ChevronLeft size={16} /></button>Site {nav.i + 1} of {nav.n}<button onClick={() => nav.go(1)} aria-label="Next site"><ChevronRight size={16} /></button></span>}
    </div>
    <h2>{target.label}</h2>
    <div className={`feasibility ${tone}`}><b>{s.score}<small>/100</small></b><div><strong>{label}</strong><span>How feasible this site is compared with every other spot in Southampton</span></div></div>

    <div className="factors">
      <Factor label="Customers nearby" value={f.demand} hint={`${fmt(Math.round(s.customers))} within ${minutes} min walk`} />
      {ctx.gap ? <Factor label="Stands out" value={f.room} hint={`none like it nearby · ${s.simR} similar within ${radius} m`} />
        : <Factor label="Room in the market" value={f.room} hint={`${s.compR} competitor${s.compR === 1 ? '' : 's'} within ${radius} m`} />}
      <Factor label="Passing trade" value={f.footfall} hint={`${s.footfall} shops and services within 400 m`} />
      <Factor label="Growth" value={f.growth} hint={`population ${s.growth >= 0 ? '+' : ''}${s.growth.toFixed(1)}% since 2021`} />
    </div>
    <p className="muted small">Each bar is a percentile: 70 = better than 70% of sites. Weights: customers {Math.round(100 * ctx.weights.demand)}%, room {Math.round(100 * ctx.weights.room)}%, passing trade {Math.round(100 * ctx.weights.footfall)}%, growth {Math.round(100 * ctx.weights.growth)}%{s.flood ? '; −15 for flood zone 3' : ''}.</p>

    <h3><TrendingUp size={14} /> Market and trends</h3>
    <div className="facts-grid">
      {ctx.gap ? <>
        <div><Users size={14} /><b>{s.simR}</b><span>similar businesses within {radius}&nbsp;m{s.nearSim.length ? <em>{[...new Set(s.nearSim.map(p => p.spec))].slice(0, 3).join(', ')}</em> : null}</span></div>
        <div><Footprints size={14} /><b>{s.nearSim.length ? `${fmt(Math.round(s.nearSim[0].d))} m` : 'None'}</b><span>to the nearest similar business</span></div>
      </> : <>
        <div><Users size={14} /><b>{perComp ? fmt(Math.round(perComp)) : '–'}</b><span>customers per existing {target.label.toLowerCase()} here{ctx.cityPerCompetitor ? <em>City average <b>{fmt(Math.round(ctx.cityPerCompetitor))}</b></em> : null}</span></div>
        <div><Footprints size={14} /><b>{s.nearest != null ? `${fmt(Math.round(s.nearest))} m` : '–'}</b><span>to the nearest competitor</span></div>
      </>}
      <div><TrendingUp size={14} /><b>{s.growth >= 0 ? '+' : ''}{s.growth.toFixed(1)}%</b><span>residents since 2021{s.u5Growth != null ? <em>Under-5s <b>{s.u5Growth >= 0 ? '+' : ''}{s.u5Growth.toFixed(1)}%</b></em> : null}</span></div>
      <div><Droplets size={14} /><b>{s.flood ? 'Yes' : 'No'}</b><span>in flood zone 3</span></div>
    </div>
    {s.near.length > 0 && <div className="near-list"><span>Nearest competitors</span>{s.near.slice(0, 4).map((p, i) => <div key={i}><span>{p.name || 'Unnamed'}</span><b>{fmt(Math.round(p.d))} m</b></div>)}</div>}

    <h3><Users size={14} /> Who benefits</h3>
    <p className="muted small">People who would have this {target.label.toLowerCase()} within a {minutes}-minute walk ({radius} m).</p>
    <div className="benefit-head"><div><b>{fmt(Math.round(s.residents))}</b><span>residents in total</span></div><div><b>{fmt(Math.round(s.customers))}</b><span>your target customers</span></div><div><b>{Math.round(100 * s.dep / Math.max(1, s.customers))}%</b><span>of them in the most deprived 40% of areas</span></div></div>
    <div className="age-mix">{AGE_GROUPS.map(([k, l]) => { const n = s.ageMix[k] || 0, on = ctx.ages.includes(k)
      return <div key={k} className={`age-row ${on ? 'target' : ''}`}><span>{l}</span><span className="track"><i style={{ width: `${Math.min(100, 250 * n / ageTotal)}%` }} /></span><span className="n">{Math.round(100 * n / ageTotal)}%</span><span className="c">{fmt(Math.round(n))}</span></div> })}</div>
    {engine?.r && engine.r.newly_covered === 0 && <p className="muted small">As a public service: everyone within {radius} m can already walk to a {engine.r.category_label.toLowerCase()} (coverage {engine.r.coverage_before_pct}%), so this site adds choice rather than new access.</p>}
    {engine?.r && engine.r.newly_covered > 0 && <p className="muted small">As a public service: {fmt(engine.r.newly_covered)} {engine.r.demand_label} would be newly within walking distance of a {engine.r.category_label.toLowerCase()} (coverage {engine.r.coverage_before_pct}% → {engine.r.coverage_after_pct}%), {engine.r.equity_most_deprived_40pct_share}% of them in the most deprived 40% of areas.</p>}

    <h3><Lightbulb size={14} /> Feasibility brief</h3>
    <div className="callouts">
      {brief.strengths.map((t, i) => <p key={'s' + i} className="callout good"><CheckCircle2 size={15} /><span>{t}</span></p>)}
      {brief.risks.map((t, i) => <p key={'r' + i} className="callout bad"><AlertTriangle size={15} /><span>{t}</span></p>)}
      {brief.changes.map((c, i) => <p key={'c' + i} className="callout change"><Lightbulb size={15} /><span>{c.text}{c.site && <> <button className="link-button" onClick={() => onSite(c.site)}>Show that site</button></>}</span></p>)}
      {!brief.strengths.length && !brief.risks.length && <p className="callout info"><Info size={15} /><span>An average site on every measure: nothing stands out either way.</span></p>}
    </div>
    {target.tips?.length > 0 && <><h3><ClipboardList size={14} /> Before you open</h3>
      <ul className="tips">{target.tips.map((x, i) => <li key={i}>{x}</li>)}</ul>
      <p className="muted small">Suggestions from the AI model ({target.model}), not from the data: check them with the council and official guidance.</p></>}
    <details className="limits"><summary>Limitations ({brief.limits.length})</summary><ul>{brief.limits.map((t, i) => <li key={i}>{t}</li>)}</ul></details>
    {engine?.brief && <EngineBrief b={engine.brief} />}
  </aside>
}

function EngineBrief({ b }) {
  return <details className="brief">
    <summary>Planning brief for the council (numbers checked)</summary>
    {b.mode === 'refusal' ? <p className="refusal"><ShieldAlert size={14} /> {b.text}</p> : b.text.split('\n\n').map((t, i) => <p key={i}>{t.replace(/\s*\[[^\]]*\]/g, '')}</p>)}
    <span className={`audit ${b.audit.ok ? 'ok' : 'bad'}`}><BadgeCheck size={14} /> {b.audit.ok ? `All ${b.audit.checked} numbers checked against the data` : `${b.audit.failed.length} numbers not in the data`}</span>
  </details>
}
