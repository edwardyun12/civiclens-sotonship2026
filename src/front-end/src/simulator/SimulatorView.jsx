// Module C simulator in the CivicLens app. Every number comes from the shared engine (viewer/src/engine.js, a
// verified port of src/engine.py); this file only draws it.
import { Fragment, useMemo, useState } from 'react'
import { Circle, CircleMarker, MapContainer, Polygon, TileLayer, Tooltip, useMapEvents } from 'react-leaflet'
import { BadgeCheck, Crosshair, Droplets, Footprints, MapPin, ShieldAlert, Target, Users } from 'lucide-react'
import '@engine'
import { fmt, useData } from '../lib/cityData.js'
import { FitCity, KeepInView } from '../lib/MapFit.jsx'

const SimEngine = window.SimEngine
const USES = ['nursery', 'gp', 'pharmacy', 'cafe', 'library']
const QUINTILE = ['Most deprived 20%', '2nd', '3rd', '4th', 'Least deprived 20%']

function ClickToPlace({ on }) { useMapEvents({ click: e => on([e.latlng.lat, e.latlng.lng]) }); return null }

export default function SimulatorView() {
  const [city, error] = useData('city')
  const E = useMemo(() => (city ? SimEngine.create(city) : null), [city])
  const [cat, setCat] = useState('nursery')
  const [mode, setMode] = useState('test')
  const [radius, setRadius] = useState(800)
  const [k, setK] = useState(3)
  const [site, setSite] = useState(null)
  const [flood, setFlood] = useState(false)
  const at = site || (E ? E.wardCentroid('Sholing') : null)

  const out = useMemo(() => {
    if (!E || !at) return null
    try {
      if (mode === 'test') {
        const r = E.evaluateSite(cat, at[0], at[1], radius)
        const sens = E.sensitivity([{ category: cat, lat: at[0], lon: at[1] }])
        const payload = E.buildPayload([r], sens)
        return { kind: 'test', r, sens, nothing: E.doNothing(cat, radius), brief: E.brief(payload), newly: newlyCovered(E, cat, at, radius) }
      }
      const picks = E.optimise(cat, k, radius)
      const results = picks.map(p => E.evaluateSite(cat, p.lat_exact, p.lon_exact, radius))
      const payload = picks.length ? E.buildPayload(results, null, { optimiser: { method: 'greedy maximum coverage', candidate_sites: E.N,
        coverage_before_pct: picks[0].coverage_before_pct, coverage_after_all_pct: picks[0].coverage_after_all_pct } }) : null
      return { kind: 'best', picks, results, brief: payload ? E.brief(payload) : null }
    } catch (e) {
      return { error: e instanceof SimEngine.EngineError ? e.message : `Something went wrong: ${e.message}` }
    }
  }, [E, cat, mode, radius, k, at?.[0], at?.[1]])

  if (error) return <div className="tool-error">{error.message}</div>
  if (!E) return <div className="tool-error">Loading the city…</div>
  const C = SimEngine.CATEGORIES, existing = E.facilities(cat)

  return <div className="map-stage">
    <MapContainer center={[50.92, -1.40]} zoom={13} minZoom={11} zoomSnap={0.25} scrollWheelZoom className="map-canvas" zoomControl={false} preferCanvas>
      <TileLayer attribution='&copy; OpenStreetMap contributors' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
      <FitCity city={city} right />
      {mode === 'test' && <><ClickToPlace on={setSite} /><KeepInView at={at} right /></>}
      {flood && city.flood.map((poly, i) => <Polygon key={'f' + i} positions={poly.map(r => r.map(([x, y]) => [y, x]))} interactive={false}
        pathOptions={{ stroke: false, fillColor: '#3d78b8', fillOpacity: 0.35, fillRule: 'evenodd' }} />)}
      {existing.map((f, i) => <CircleMarker key={'e' + i} center={[f.lat, f.lon]} radius={4.5} pathOptions={{ color: '#fff', weight: 1.2, fillColor: '#0b332b', fillOpacity: 0.85 }}>
        <Tooltip>{f.n || 'Unnamed'} · existing {C[cat].label.toLowerCase()}</Tooltip></CircleMarker>)}
      {out?.kind === 'test' && <>
        {out.newly.map(([la, lo, w], i) => <CircleMarker key={'n' + i} center={[la, lo]} radius={3 + Math.min(6, w / 40)} interactive={false}
          pathOptions={{ stroke: false, fillColor: '#7bbf1f', fillOpacity: 0.85 }} />)}
        <Circle center={at} radius={radius} pathOptions={{ color: '#062b25', weight: 2, dashArray: '6 6', fillColor: '#d7ff3f', fillOpacity: 0.12 }} interactive={false} />
        <CircleMarker center={at} radius={10} pathOptions={{ color: '#062b25', weight: 3, fillColor: '#d7ff3f', fillOpacity: 1 }}>
          <Tooltip permanent direction="top" offset={[0, -10]} className="site-label">Proposed {C[cat].label.toLowerCase()}</Tooltip></CircleMarker>
      </>}
      {out?.kind === 'best' && out.picks.map(p => <Fragment key={p.rank}>
        <Circle center={[p.lat_exact, p.lon_exact]} radius={radius} interactive={false} pathOptions={{ color: '#062b25', weight: 1.5, dashArray: '5 6', fillColor: '#d7ff3f', fillOpacity: 0.12 }} />
        <CircleMarker center={[p.lat_exact, p.lon_exact]} radius={13} pathOptions={{ color: '#062b25', weight: 3, fillColor: '#d7ff3f', fillOpacity: 1 }}>
          <Tooltip permanent direction="center" className="rank-label">{p.rank}</Tooltip></CircleMarker>
      </Fragment>)}
    </MapContainer>

    <aside className="tool-panel">
      <span className="eyebrow dark"><Target size={13} /> Planning simulator</span>
      <h2>Where should the next one go?</h2>
      <label className="field-label">Use</label>
      <div className="chips use-chips">{USES.map(u => <button key={u} className={cat === u ? 'on' : ''} onClick={() => setCat(u)}>{C[u].label}</button>)}</div>
      <label className="field-label">Mode</label>
      <div className="seg-light">
        <button className={mode === 'test' ? 'on' : ''} onClick={() => setMode('test')}><Crosshair size={14} /> Test a site</button>
        <button className={mode === 'best' ? 'on' : ''} onClick={() => setMode('best')}><Target size={14} /> Find best sites</button>
      </div>
      {mode === 'test' ? <>
        <p className="muted">Click the map to place the site, or jump to an area:</p>
        <select value="" onChange={e => e.target.value && setSite(E.wardCentroid(e.target.value))}>
          <option value="">Choose an area…</option>{E.wards.map(w => <option key={w}>{w}</option>)}
        </select>
      </> : <>
        <label className="field-label" htmlFor="k">New sites: {k}</label>
        <input id="k" type="range" min="1" max="3" value={k} onChange={e => setK(+e.target.value)} />
      </>}
      <label className="field-label" htmlFor="rad">Walking distance: {radius} m · about {Math.round(radius / 80)} minutes</label>
      <input id="rad" type="range" min="400" max="1200" step="100" value={radius} onChange={e => setRadius(+e.target.value)} />
      <label className="check"><input type="checkbox" checked={flood} onChange={e => setFlood(e.target.checked)} /> Show flood zone 3</label>
      <p className="count"><b>{existing.length}</b> existing {C[cat].label.toLowerCase()} sites in the data · demand: {C[cat].demandLabel}</p>
    </aside>

    {out?.error && <aside className="result-card"><h2>Can’t test that site</h2><p className="muted">{out.error}</p></aside>}
    {out?.kind === 'test' && <TestResult o={out} />}
    {out?.kind === 'best' && <BestResult o={out} label={C[cat].label} radius={radius} n={E.N} />}

    <div className="legend tool-legend">
      <span className="key"><i style={{ background: '#d7ff3f', border: '2px solid #062b25' }} />Proposed site</span>
      <span className="key"><i style={{ background: '#0b332b' }} />Existing site</span>
      {mode === 'test' && <span className="key"><i style={{ background: '#7bbf1f' }} />Newly within walking distance</span>}
      {flood && <span className="key"><i style={{ background: '#3d78b8' }} />Flood zone 3</span>}
    </div>
  </div>
}

// Output Area centres the site brings within walking distance for the first time (for the map only)
function newlyCovered(E, cat, at, radius) {
  const d0 = E.existingDist(cat), [sx, sy] = E.toBNG(at[0], at[1]), w = E.demand(cat), out = []
  for (let i = 0; i < E.N; i++) if (d0[i] > radius && Math.hypot(E.ox[i] - sx, E.oy[i] - sy) <= radius) out.push([E.oa.lat[i], E.oa.lon[i], w[i]])
  return out
}

function Score({ label, value, hint }) {
  return <div className="score"><div><span>{label}</span><b>{value}</b></div><span className="track"><i style={{ width: `${value}%` }} /></span><small>{hint}</small></div>
}

function TestResult({ o }) {
  const r = o.r, q = r.equity_newly_covered_by_quintile, qmax = Math.max(1, ...Object.values(q))
  const [lo, hi] = o.sens.need_score_range[0]
  return <aside className="result-card">
    <span className="place-kicker"><MapPin size={13} /> {r.site.ward}</span>
    <h2>New {r.category_label.toLowerCase()}</h2>
    <span className={`badge ${r.confidence.toLowerCase()}`}>{r.confidence} confidence</span>
    <div className="headline"><b>{fmt(r.newly_covered)}</b><span>{r.demand_label} newly within a {r.walk_minutes}-minute walk</span></div>
    <div className="cov">
      <div className="cov-bar"><i className="before" style={{ width: `${r.coverage_before_pct}%` }} /><i className="after" style={{ left: `${r.coverage_before_pct}%`, width: `${r.coverage_change_pct_points}%` }} /></div>
      <div className="cov-legend"><span>Covered now {r.coverage_before_pct}%</span><span>With this site {r.coverage_after_pct}% (+{r.coverage_change_pct_points})</span></div>
      <small className="muted">Do nothing: stays at {o.nothing.coverage_before_pct}%</small>
    </div>
    <div className="scores">
      <Score label="Community need" value={r.need_score} hint="Gaps, distance and deprivation in the catchment" />
      <Score label="Commercial viability" value={r.viability_score} hint={`Demand and competition${r.flood_zone3 ? '; flood penalty applied' : ''}`} />
    </div>
    <div className="facts-grid">
      <div><Users size={14} /><b>{r.competitors_within_400m}</b><span>competitors within 400 m{r.cannibalisation_flag ? ' · crowded' : ''}</span></div>
      <div><Footprints size={14} /><b>{r.nearest_existing_m != null ? `${fmt(r.nearest_existing_m)} m` : '–'}</b><span>to the nearest existing site</span></div>
      <div><BadgeCheck size={14} /><b>{r.jobs_estimate}</b><span>jobs (range {r.jobs_range[0]}–{r.jobs_range[1]}, our assumption)</span></div>
      <div><Droplets size={14} /><b>{r.flood_zone3 ? 'Yes' : 'No'}</b><span>in flood zone 3</span></div>
    </div>
    <h3>Who benefits</h3>
    <div className="quint">{[1, 2, 3, 4, 5].map(k => <div key={k}><span>{QUINTILE[k - 1]}</span><span className="track"><i style={{ width: `${100 * q[k] / qmax}%` }} /></span><b>{fmt(q[k])}</b></div>)}</div>
    <p className="muted">{r.equity_most_deprived_40pct_share}% of the newly covered live in the most deprived 40% of areas.</p>
    <h3>How sure is this?</h3>
    <p className="muted">Need score ranges {lo}–{hi} when the walking distance (600–1000 m) and score weights (±20%) change.{r.confidence_reasons.length ? ' ' + r.confidence_reasons.join('; ') + '.' : ''}</p>
    <Brief b={o.brief} />
  </aside>
}

function BestResult({ o, label, radius, n }) {
  if (!o.picks.length) return <aside className="result-card"><h2>No better sites</h2><p className="muted">Everyone is already within {radius} m of an existing {label.toLowerCase()}.</p></aside>
  const p0 = o.picks[0]
  return <aside className="result-card">
    <span className="place-kicker"><Target size={13} /> Best sites</span>
    <h2>{o.picks.length} new {label.toLowerCase()} sites</h2>
    <div className="headline"><b>{p0.coverage_before_pct}% → {p0.coverage_after_all_pct}%</b><span>coverage within {radius} m with all {o.picks.length}</span></div>
    <ol className="picks">{o.picks.map((p, i) => <li key={p.rank}><span className="rank">{p.rank}</span><div><b>{p.ward}</b>
      <small>+{fmt(p.marginal_newly_covered)} newly covered · need {o.results[i].need_score} · viability {o.results[i].viability_score}{o.results[i].flood_zone3 ? ' · flood zone' : ''}</small></div></li>)}</ol>
    <p className="muted">Greedy maximum coverage over {n} Census area centres; flood zone 3 is skipped.</p>
    <Brief b={o.brief} />
  </aside>
}

function Brief({ b }) {
  if (!b) return null
  return <div className="brief">
    <h3>Planning brief</h3>
    {b.mode === 'refusal' ? <p className="refusal"><ShieldAlert size={14} /> {b.text}</p> : b.text.split('\n\n').map((t, i) => <p key={i}>{t.replace(/\s*\[[^\]]*\]/g, '')}</p>)}
    <span className={`audit ${b.audit.ok ? 'ok' : 'bad'}`}><BadgeCheck size={14} /> {b.audit.ok ? `All ${b.audit.checked} numbers checked against the data` : `${b.audit.failed.length} numbers not in the data`}</span>
  </div>
}
