// Places register: every named business and service in Southampton, merged across official registers
// (built by pipeline/places). Search, industry -> detailed type filter, and four map views: Popular, Heatmap
// (where places cluster), People (where residents live, by age group, from city.json) and Places.
import { useEffect, useMemo, useState } from 'react'
import { CircleMarker, MapContainer, Polygon, TileLayer, Tooltip, useMap } from 'react-leaflet'
import L from 'leaflet'
import { Flame, MapPin, Search, Sparkles, Users, X } from 'lucide-react'
import HeatLayer, { HEAT_GRADIENT, PEOPLE_GRADIENT, PEOPLE_RAMP } from '../lib/HeatLayer.jsx'
import { CATEGORICAL, OTHER, bounds, fmt, placeRows, useData } from '../lib/cityData.js'
import { FitCity, pad } from '../lib/MapFit.jsx'

const CAT_LABEL = { restaurant_cafe: 'Restaurant / café', takeaway: 'Takeaway', pub_bar: 'Pub / bar', other_catering: 'Other catering',
  mobile_caterer: 'Mobile caterer', supermarket: 'Supermarket', shop_food: 'Food shop', shop_other: 'Other shop', nursery: 'Nursery / childcare',
  gp: 'GP surgery', pharmacy: 'Pharmacy', dentist: 'Dentist', hospital: 'Hospital', health_other: 'Other health', library: 'Library',
  education: 'School / college', care_childcare_health: 'Care', hotel: 'Hotel / B&B', community: 'Community', leisure: 'Leisure',
  coworking: 'Coworking', hair_beauty: 'Hair and beauty', personal_services: 'Personal services', professional: 'Professional services',
  finance: 'Finance', property: 'Property', it_tech: 'IT and tech', business_services: 'Business services', wholesale: 'Wholesale',
  construction: 'Construction', manufacturing: 'Manufacturing', food_manufacturer: 'Food manufacturer', motor: 'Motor trade',
  transport_logistics: 'Transport and logistics', utilities_primary: 'Utilities and primary', other: 'Other' }
const catLabel = c => CAT_LABEL[c] || c
const VIEWS = [['popular', 'Popular', Sparkles], ['heat', 'Heatmap', Flame], ['people', 'People', Users], ['points', 'Places', MapPin]]
// everyday words that should find a detailed type
const SYN = { 'Bubble tea': 'boba milk tea', Japanese: 'sushi ramen', Korean: 'kbbq', 'Coffee shop': 'cafe coffee', Café: 'cafe coffee',
  'Dental practice': 'dentist teeth', 'GP practice': 'doctor surgery', 'GP or clinic': 'doctor surgery', 'Fish and chips': 'chippy chip shop',
  Barber: 'hair', 'Nail salon': 'nails manicure', 'Gym or fitness centre': 'fitness workout', 'Pub or bar': 'pub bar drinks',
  'Asian supermarket': 'oriental grocery', Pharmacy: 'chemist', 'Veterinary practice': 'vet pets', Optician: 'glasses eyes' }
const vague = k => /not known|no detail/.test(k) || !k
// categories that are already specific ("GP surgery") don't need a "(no detail)" note
const SPECIFIC = new Set(['gp', 'pharmacy', 'dentist', 'hospital', 'nursery', 'library', 'supermarket', 'pub_bar', 'hotel', 'hair_beauty', 'coworking', 'takeaway'])
// same names the register uses, so one place type isn't split in two ("GP surgery" vs "GP practice")
const SAME_AS = { gp: 'GP practice', dentist: 'Dental practice', nursery: 'Day nursery or childcare', supermarket: 'Supermarket or convenience store', pub_bar: 'Pub or bar' }
const specOf = p => p.spec || SAME_AS[p.cat] || (SPECIFIC.has(p.cat) ? catLabel(p.cat) : `${catLabel(p.cat)} (no detail)`)

// leading key per ward: by default the detailed type; keyOf = sector when no sector is chosen on the Popular view.
// Most common, or (lq) the key furthest above its city-wide share with at least 3 places.
function popular(rows, lq, keyOf = specOf) {
  const by = {}, city = {}; let N = 0
  for (const p of rows) { if (!p.ward) continue; const b = (by[p.ward] ||= { n: 0, top: {} }); b.n++; const k = keyOf(p); b.top[k] = (b.top[k] || 0) + 1; city[k] = (city[k] || 0) + 1; N++ }
  const win = {}
  for (const [w, b] of Object.entries(by)) {
    let best = null
    for (const [k, n] of Object.entries(b.top)) {
      if (vague(k) || k === 'Other') continue
      const share = n / b.n, ratio = share / (city[k] / N)
      if (lq ? n >= 3 && ratio > 1 && (!best || ratio > best.ratio) : !best || n > best.n) best = { k, n, share, ratio }
    }
    if (best) win[w] = best
  }
  const wins = {}; for (const b of Object.values(win)) wins[b.k] = (wins[b.k] || 0) + 1
  const order = Object.entries(wins).sort((a, b) => b[1] - a[1] || city[b[0]] - city[a[0]]).map(([k]) => k)
  const color = {}; order.forEach((k, i) => (color[k] = CATEGORICAL[i] || OTHER))
  return { by, city, N, win, order, color }
}

function FitTo({ target }) {
  const map = useMap()
  useEffect(() => { if (target) map.flyToBounds(target, { ...pad(true), duration: 0.6 }) }, [map, target])
  return null
}

// what each view is for: [eyebrow, title, intro]
const VIEW_TEXT = {
  popular: ['Popular', 'What each area is known for', 'Pick a sector to see its leading type of business in each area, or keep all sectors to see which sector leads.'],
  heat: ['Heatmap', 'Where businesses cluster', 'Darker = more places within about 250 m. Pick a sector to compare, say, food with health.'],
  people: ['People', 'Where people live', 'Darker = more people within about 300 m. Pick an age group; hover an area for its age mix.'],
  points: ['Places', 'Find any business in the city', 'Search by name or street, then narrow by industry and detailed type.'],
}

export default function PlacesView() {
  const [cols, error] = useData('places')
  const [city] = useData('city')
  const all = useMemo(() => (cols ? placeRows(cols).filter(p => p.inside) : []), [cols])
  const [view, setView] = useState(() => { const v = new URLSearchParams(window.location.search).get('view'); return VIEWS.some(([id]) => id === v) ? v : 'popular' })  // e.g. ?view=people#places
  const [ward, setWard] = useState(() => new URLSearchParams(window.location.search).get('ward'))  // e.g. ?ward=Portswood#places
  const [place, setPlace] = useState(null)
  // Popular and Heatmap: one sector (industry group) or all
  const [sector, setSector] = useState('')
  const [lq, setLq] = useState(false)
  // People: age group
  const [age, setAge] = useState('all')
  // Places: full search
  const [q, setQ] = useState('')
  const [grp, setGrp] = useState('')
  const [spec, setSpec] = useState(() => new Set())
  const [specQ, setSpecQ] = useState('')
  const [hideRO, setHideRO] = useState(true)

  // Places view: search -> industry -> detailed types
  const base = useMemo(() => {
    const s = q.trim().toLowerCase()
    return all.filter(p => (!hideRO || !p.ro) && (!grp || p.grp === grp) &&
      (!s || `${p.name} ${p.pc} ${p.addr} ${p.spec}`.toLowerCase().includes(s)))
  }, [all, q, grp, hideRO])
  const typed = useMemo(() => (spec.size ? base.filter(p => spec.has(specOf(p))) : base), [base, spec])
  // Popular and Heatmap: trading places in the chosen sector (companies known only by their registered office left out)
  const inSector = useMemo(() => all.filter(p => !p.ro && (!sector || p.grp === sector)), [all, sector])
  const active = view === 'points' ? typed : inSector
  const shown = useMemo(() => (ward ? active.filter(p => p.ward === ward) : active), [active, ward])
  const bySector = view === 'popular' && !sector
  const pop = useMemo(() => popular(active, lq, bySector ? p => p.grp : specOf), [active, lq, bySector])

  const groups = useMemo(() => { const o = {}; for (const p of all) if (!hideRO || !p.ro) o[p.grp] = (o[p.grp] || 0) + 1; return Object.entries(o).sort((a, b) => b[1] - a[1]) }, [all, hideRO])
  const sectors = useMemo(() => { const o = {}; for (const p of all) if (!p.ro) o[p.grp] = (o[p.grp] || 0) + 1; return Object.entries(o).sort((a, b) => b[1] - a[1]) }, [all])
  const specGroups = useMemo(() => {
    const g = {}, s = specQ.trim().toLowerCase()
    for (const p of ward ? base.filter(x => x.ward === ward) : base) {
      const head = grp ? catLabel(p.cat) : p.grp, k = specOf(p)
      const G = (g[head] ||= { n: 0, items: {} }); G.n++; G.items[k] = (G.items[k] || 0) + 1
    }
    return Object.entries(g).sort((a, b) => b[1].n - a[1].n).map(([head, G]) => [head, G.n,
      Object.entries(G.items).filter(([k]) => !s || `${k} ${SYN[k] || ''} ${head}`.toLowerCase().includes(s)).sort((a, b) => b[1] - a[1])])
      .filter(([, , items]) => items.length)
  }, [base, grp, specQ, ward])

  const outlines = useMemo(() => (city ? Object.entries(city.ward_outlines).map(([w, rings]) => ({ w, rings, pos: rings.map(r => r.map(([x, y]) => [y, x])) })) : []), [city])
  const people = useMemo(() => peoplePoints(city, age), [city, age])
  const wardPop = useMemo(() => { const o = {}; if (city) city.oa.ward.forEach((w, i) => (o[w] = (o[w] || 0) + city.oa.pop[i])); return o }, [city])
  const target = useMemo(() => (ward && city ? bounds(city.ward_outlines[ward]) : null), [ward, city])

  const toggle = k => setSpec(s => { const n = new Set(s); n.has(k) ? n.delete(k) : n.add(k); return n })
  const pickWard = w => { setWard(cur => (cur === w ? null : w)); setPlace(null) }
  // a type clicked in an area profile opens the Places search for it
  const searchType = k => { setGrp(view === 'points' ? grp : sector); setSpec(new Set([k])); setQ(''); setView('points') }
  if (error) return <div className="tool-error">{error.message}</div>
  const [eyebrow, title, intro] = VIEW_TEXT[view]
  const ViewIcon = VIEWS.find(([id]) => id === view)[2]

  return <div className="map-stage">
    <MapContainer center={[50.92, -1.40]} zoom={13} minZoom={11} zoomSnap={0.25} scrollWheelZoom className="map-canvas" zoomControl={false} preferCanvas renderer={L.canvas({ padding: 0.3 })}>
      <TileLayer attribution='&copy; OpenStreetMap contributors · Population: ONS' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
      <FitCity city={city} />
      <FitTo target={target} />
      {outlines.map(({ w, pos }) => {
        const b = pop.win[w], on = ward === w, dim = ward && !on
        const fill = view === 'popular' && b ? pop.color[b.k] : '#0b332b'
        const opacity = view === 'popular' && b ? (dim ? 0.12 : 0.25 + 0.5 * (lq ? Math.min(1, (b.ratio - 1) / 2) : b.share)) : dim ? 0.35 : 0.02
        return <Polygon key={w} positions={pos} pathOptions={{ color: on ? '#062b25' : '#0b332b', weight: on ? 4 : 1.2, opacity: on ? 1 : 0.55,
          fillColor: view === 'popular' ? fill : dim ? '#f5f7f2' : '#0b332b', fillOpacity: opacity, fillRule: 'evenodd' }}
          eventHandlers={{ click: () => pickWard(w) }}>
          <Tooltip sticky className="ward-tip">{view === 'people' ? <PeopleTip w={w} people={people} selected={on} />
            : <WardTip w={w} stats={pop.by[w]} pop={pop} wardPop={wardPop[w]} selected={on} />}</Tooltip>
        </Polygon>
      })}
      {view === 'heat' && <HeatLayer points={shown} />}
      {view === 'people' && <HeatLayer points={people.points} radiusM={300} colors={PEOPLE_RAMP} />}
      {view === 'points' && shown.slice(0, 20000).map(p => <CircleMarker key={p.id} center={[p.lat, p.lon]} radius={place?.id === p.id ? 8 : 4}
        pathOptions={{ color: '#fff', weight: 1, fillColor: groupColor(p.grp, groups), fillOpacity: p.ro ? 0.45 : 0.9 }}
        eventHandlers={{ click: () => setPlace(p) }} />)}
      {view === 'popular' && Object.entries(pop.win).map(([w, b]) => { const oa = wardCentre(city, w); return oa && <CircleMarker key={'m' + w} center={oa} radius={7} interactive={false}
        pathOptions={{ color: '#fff', weight: 2.5, fillColor: pop.color[b.k], fillOpacity: ward && ward !== w ? 0.35 : 1 }}>
        <Tooltip permanent direction="bottom" offset={[0, 4]} className="ward-label"><b>{w}</b></Tooltip></CircleMarker> })}
    </MapContainer>

    <aside className="tool-panel">
      <div className="view-switch" role="tablist" aria-label="Map view">
        {VIEWS.map(([id, label, Icon]) => <button key={id} role="tab" aria-selected={view === id} className={view === id ? 'active' : ''} onClick={() => setView(id)}><Icon size={15} /><span>{label}</span></button>)}
      </div>
      <div className="panel-head">
        <span className="eyebrow dark"><ViewIcon size={13} /> {eyebrow}</span>
        <h2>{title}</h2>
        <p className="muted">{intro}</p>
      </div>

      {view === 'popular' && <>
        <Seg value={lq} onChange={setLq} options={[[false, 'Most common'], [true, 'Stands out vs city']]} />
        <SectorList sectors={sectors} value={sector} onChange={setSector} colors={bySector ? pop.color : null} />
      </>}

      {view === 'heat' && <SectorList sectors={sectors} value={sector} onChange={setSector} />}

      {view === 'people' && <AgeList people={people} value={age} onChange={setAge} />}

      {view === 'points' && <>
        <label className="search"><Search size={15} /><input value={q} onChange={e => setQ(e.target.value)} placeholder="Name, postcode, street…" /></label>
        <label className="field-label" htmlFor="grp">Industry</label>
        <select id="grp" value={grp} onChange={e => { setGrp(e.target.value); setSpec(new Set()) }}>
          <option value="">All industries ({fmt(groups.reduce((a, [, n]) => a + n, 0))})</option>
          {groups.map(([g, n]) => <option key={g} value={g}>{g} ({fmt(n)})</option>)}
        </select>
        <div className="field-row"><label className="field-label" htmlFor="specq">Detailed type</label>{spec.size > 0 && <button className="link-button" onClick={() => setSpec(new Set())}>Clear {spec.size}</button>}</div>
        <input id="specq" className="plain-input" value={specQ} onChange={e => setSpecQ(e.target.value)} placeholder="Bubble tea, Korean, barber…" />
        <div className="type-list">
          {specGroups.map(([head, n, items]) => <div key={head}>
            <button className="type-head" onClick={() => setSpec(s => { const all = items.every(([k]) => s.has(k)), x = new Set(s); items.forEach(([k]) => (all ? x.delete(k) : x.add(k))); return x })}><span>{head}</span><span>{fmt(n)}</span></button>
            {items.map(([k, c]) => <label key={k} className={`type-row ${spec.has(k) ? 'on' : ''}`}><input type="checkbox" checked={spec.has(k)} onChange={() => toggle(k)} /><span>{k}</span><span>{fmt(c)}</span></label>)}
          </div>)}
          {!specGroups.length && <p className="muted">No type matches “{specQ}”.</p>}
        </div>
        <label className="check"><input type="checkbox" checked={hideRO} onChange={e => setHideRO(e.target.checked)} /> Hide companies known only by their registered office</label>
      </>}

      <p className="count">{view === 'people' ? <><b>{fmt(Math.round(ward ? people.byWard[ward] || 0 : people.total))}</b> {people.noun}</> : <><b>{fmt(shown.length)}</b> places</>}
        {ward ? <> in <b>{ward}</b> <button className="link-button" onClick={() => setWard(null)}>whole city</button></> : ' · click an area to explore it'}</p>
    </aside>

    <div className="map-legend"><Legend view={view} pop={pop} people={people} /></div>
    {place && <PlaceDetail p={place} onClose={() => setPlace(null)} />}
    {ward && !place && city && <WardProfile ward={ward} typed={active} pop={pop} wardPop={wardPop} city={city} people={people} onClose={() => setWard(null)} onPick={searchType} onWard={pickWard} />}
  </div>
}

// Sectors (industry groups) as one-tap rows; colours match the map when it is coloured by sector
function SectorList({ sectors, value, onChange, colors }) {
  const total = sectors.reduce((a, [, n]) => a + n, 0)
  return <div className="choice-list" role="radiogroup" aria-label="Sector">
    {[['', total], ...sectors].map(([g, n]) => <button key={g || 'all'} role="radio" aria-checked={value === g} className={value === g ? 'on' : ''} onClick={() => onChange(g)}>
      {colors && g ? <i style={{ background: colors[g] || 'transparent', borderColor: colors[g] ? 'transparent' : '#c9d3cb' }} /> : <i className="none" />}
      <span>{g || 'All sectors'}</span><span className="n">{fmt(n)}</span></button>)}
  </div>
}

// Age groups as rows with the city total and share
function AgeList({ people, value, onChange }) {
  const all = people.totals.all || 1
  return <div className="choice-list" role="radiogroup" aria-label="Age group">
    {people.ages.map(([k, label]) => { const n = people.totals[k] || 0
      return <button key={k} role="radio" aria-checked={value === k} className={value === k ? 'on' : ''} onClick={() => onChange(k)}>
        <span>{k === 'all' ? 'All ages' : label}</span>
        {k !== 'all' ? <span className="share"><i style={{ width: `${Math.min(100, 250 * n / all)}%` }} /></span> : <span />}
        <span className="n">{fmt(Math.round(n))}{k !== 'all' && <small> · {Math.round(100 * n / all)}%</small>}</span></button> })}
  </div>
}

function groupColor(g, groups) { const i = groups.findIndex(([x]) => x === g); return i >= 0 && i < CATEGORICAL.length ? CATEGORICAL[i] : OTHER }

const centres = new Map()
function wardCentre(city, w) {
  if (!city) return null
  if (!centres.has(w)) { let la = 0, lo = 0, n = 0; city.oa.ward.forEach((x, i) => { if (x === w) { la += city.oa.lat[i] * city.oa.pop[i]; lo += city.oa.lon[i] * city.oa.pop[i]; n += city.oa.pop[i] } }); centres.set(w, n ? [la / n, lo / n] : null) }
  return centres.get(w)
}

// Age groups: [key, button label, noun, column in city.json] (pop04 is 0-4; the rest live in city.oa.ages)
const AGES = [['all', 'All ages', 'residents', 'pop'], ['0_4', '0–4', 'children aged 0–4', 'pop04'],
  ['5_15', '5–15', 'children aged 5–15', 'pop_5_15'], ['16_24', '16–24', 'people aged 16–24', 'pop_16_24'],
  ['25_44', '25–44', 'people aged 25–44', 'pop_25_44'], ['45_64', '45–64', 'people aged 45–64', 'pop_45_64'],
  ['65', '65+', 'people aged 65 and over', 'pop_65_plus']]
const ageColumn = (o, col) => (col === 'pop' || col === 'pop04' ? o[col] : o.ages?.[col])

// Residents at each Output Area centre (city.json, from data/processed/oa.csv, latest population estimate)
function peoplePoints(city, age) {
  const empty = { points: [], byWard: {}, mix: {}, total: 0, noun: 'residents', ages: AGES.slice(0, 2), totals: {} }
  if (!city) return empty
  const o = city.oa, ages = AGES.filter(([, , , col]) => ageColumn(o, col))
  const [, , noun, col] = ages.find(a => a[0] === age) || ages[0], v = ageColumn(o, col)
  const points = [], byWard = {}, mix = {}
  let total = 0
  for (let i = 0; i < o.lat.length; i++) {
    points.push({ lat: o.lat[i], lon: o.lon[i], w: v[i] })
    byWard[o.ward[i]] = (byWard[o.ward[i]] || 0) + v[i]
    total += v[i]
  }
  // age mix per ward (and the city) for tooltips and the area profile
  for (const [k, label, , c] of ages.slice(1)) {
    const a = ageColumn(o, c)
    o.ward.forEach((w, i) => { const m = (mix[w] ||= {}); m[k] = (m[k] || 0) + a[i] })
  }
  const totals = Object.fromEntries(ages.map(([k, , , c]) => [k, ageColumn(o, c).reduce((s, x) => s + x, 0)]))
  return { points, byWard, mix, total, noun, ages, totals }
}

// Bars of each age group's share of an area's residents, with the city share for comparison
function AgeMix({ mix, ages, city, compact }) {
  if (!mix) return null
  const sum = o => Object.values(o).reduce((a, b) => a + b, 0), n = sum(mix), cn = city ? sum(city) : 0
  return <div className={`age-mix ${compact ? 'compact' : ''}`}>{ages.slice(1).map(([k, label]) => {
    const s = 100 * (mix[k] || 0) / Math.max(1, n), cs = cn ? 100 * (city[k] || 0) / cn : null
    return <div key={k} className="age-row"><span>{label}</span><span className="track"><i style={{ width: `${Math.min(100, s * 2.5)}%` }} />{cs != null && <b style={{ left: `${Math.min(100, cs * 2.5)}%` }} />}</span>
      <span className="n">{s.toFixed(0)}%</span>{!compact && <span className="c">{fmt(Math.round(mix[k] || 0))}</span>}</div>
  })}</div>
}

function PeopleTip({ w, people, selected }) {
  return <div className="tip">
    <b>{w}</b><small>{selected ? 'Click to go back to the whole city' : 'Click to explore this area'}</small>
    <small>{fmt(Math.round(people.byWard[w] || 0))} {people.noun}</small>
    <AgeMix mix={people.mix[w]} ages={people.ages} compact />
  </div>
}

function WardTip({ w, stats, pop, wardPop, selected }) {
  const items = stats ? Object.entries(stats.top).sort((a, b) => b[1] - a[1]).slice(0, 5) : []
  return <div className="tip">
    <b>{w}</b><small>{selected ? 'Click to go back to the whole city' : 'Click to explore this area'}</small>
    {stats ? <><small>{fmt(stats.n)} places · {(1000 * stats.n / Math.max(1, wardPop)).toFixed(1)} per 1,000 residents</small>
      {items.map(([k, n]) => <div key={k} className="tip-row"><i style={{ background: pop.color[k] || OTHER }} /><span>{k}</span><span>{fmt(n)}</span></div>)}</> : <small>No matching places</small>}
  </div>
}

function Seg({ value, onChange, options }) {
  return <div className="seg-small" role="group">{options.map(([v, label]) =>
    <button key={String(v)} className={value === v ? 'active' : ''} aria-pressed={value === v} onClick={() => onChange(v)}>{label}</button>)}</div>
}

function Legend({ view, pop, people }) {
  if (view === 'people') return <div className="map-key"><span>Fewer</span><i className="ramp" style={{ background: PEOPLE_GRADIENT }} /><span>More {people.noun}</span></div>
  if (view === 'heat') return <div className="map-key"><span>Fewer</span><i className="ramp" style={{ background: HEAT_GRADIENT }} /><span>More places</span></div>
  if (view === 'points') return null
  const shown = pop.order.slice(0, 6)
  if (!shown.length) return <div className="map-key"><span>No type leads any area with these filters</span></div>
  return <div className="map-key">{shown.map(k => <span key={k} className="key"><i style={{ background: pop.color[k] }} />{k}</span>)}{pop.order.length > 6 && <span className="key"><i style={{ background: OTHER }} />Other</span>}</div>
}

function PlaceDetail({ p, onClose }) {
  return <aside className="place-card tool-card">
    <button className="close-card" onClick={onClose} aria-label="Close place details"><X size={16} /></button>
    <span className="place-kicker"><MapPin size={13} /> {p.grp}</span>
    <h2>{p.name}</h2>
    <dl className="facts">
      <dt>Type</dt><dd>{specOf(p)}{p.from === 'name' && <em> · guessed from the name</em>}</dd>
      {p.addr && <><dt>Address</dt><dd>{p.addr}</dd></>}
      <dt>Postcode</dt><dd>{p.pc || '–'}{p.ward ? ` · ${p.ward}` : ''}</dd>
      <dt>Sources</dt><dd>{p.src.replace(/\|/g, ' + ')}</dd>
      <dt>Confidence</dt><dd><span className="conf"><i style={{ width: `${p.conf}%` }} /></span>{p.conf}/100{p.ro ? ' · registered office only' : ''}</dd>
    </dl>
    <div className="card-links">{p.gmap && <a href={p.gmap} target="_blank" rel="noreferrer">Check on Google Maps</a>}{p.web && <a href={p.web} target="_blank" rel="noreferrer">Website</a>}</div>
  </aside>
}

function WardProfile({ ward, typed, pop, wardPop, city, people, onClose, onPick, onWard }) {
  const here = typed.filter(p => p.ward === ward), inCity = typed.filter(p => p.ward).length
  const residents = wardPop[ward] || 0, cityRes = Object.values(wardPop).reduce((a, b) => a + b, 0)
  const rate = 1000 * here.length / Math.max(1, residents), cityRate = 1000 * inCity / Math.max(1, cityRes)
  let dep = 0; city.oa.ward.forEach((w, i) => { if (w === ward && city.oa.q[i] === 1) dep += city.oa.pop[i] })
  const H = {}; for (const p of here) { const k = specOf(p); H[k] = (H[k] || 0) + 1 }
  const ratio = k => (H[k] || 0) / Math.max(1, here.length) / ((pop.city[k] || 0) / Math.max(1, pop.N))
  const top = Object.entries(H).sort((a, b) => b[1] - a[1]).slice(0, 8), max = top.length ? top[0][1] : 1
  const gaps = Object.entries(pop.city).filter(([k, n]) => n >= 8 && !vague(k) && ratio(k) < 0.5).sort((a, b) => ratio(a[0]) - ratio(b[0])).slice(0, 4)
  return <aside className="ward-card">
    <button className="close-card" onClick={onClose} aria-label="Back to the whole city"><X size={16} /></button>
    <span className="place-kicker"><MapPin size={13} /> Area profile</span>
    <h2>{ward}</h2>
    <div className="ward-stats">
      <div><b>{fmt(here.length)}</b><span>places</span></div>
      <div><b>{rate.toFixed(1)}</b><span>per 1,000 residents · city {cityRate.toFixed(1)}</span></div>
      <div><b>{fmt(residents)}</b><span>residents · {Math.round(100 * dep / Math.max(1, residents))}% in the most deprived fifth</span></div>
    </div>
    {people.mix[ward] && <><h3>Who lives here</h3>
      <AgeMix mix={people.mix[ward]} ages={people.ages} city={Object.values(people.mix).reduce((t, m) => { for (const k in m) t[k] = (t[k] || 0) + m[k]; return t }, {})} />
      <p className="muted">Share of the area’s residents in each age group. The dark tick is the city average.</p></>}
    <h3>What’s here</h3>
    {top.length ? <div className="bars">{top.map(([k, n]) => { const r = ratio(k)
      return <button key={k} className="bar" onClick={() => onPick(k)} title={`Show only ${k}`}>
        <span>{k}</span><span className="track"><i style={{ width: `${100 * n / max}%`, background: pop.color[k] || OTHER }} /></span><span className="n">{n}</span><span className={`x ${r >= 1.5 ? 'hi' : ''}`}>{r.toFixed(1)}×</span></button> })}</div>
      : <p className="muted">No matching places in this area.</p>}
    <p className="muted">× compares the type’s share here with its share across Southampton: 2.0× = twice as common here.</p>
    {gaps.length > 0 && <><h3>Less of than the city average</h3><div className="chips">{gaps.map(([k]) => <button key={k} onClick={() => onPick(k)}>{k} · {H[k] || 0}</button>)}</div></>}
    <h3>Other areas</h3>
    <div className="chips small">{Object.keys(wardPop).filter(w => w !== ward).sort().map(w => <button key={w} onClick={() => onWard(w)}>{w}</button>)}</div>
  </aside>
}
