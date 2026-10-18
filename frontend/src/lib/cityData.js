// City and places data written by viewer/build_viewers.py into public/data/.
import { useEffect, useState } from 'react'

const cache = {}
function load(name) {
  return (cache[name] ||= fetch(`/data/${name}.json`).then(r => {
    if (!r.ok) throw new Error(`Could not load ${name}.json. Run python run.py viewers from the repo root.`)
    return r.json()
  }))
}

export function useData(name) {
  const [state, setState] = useState({ data: null, error: null })
  useEffect(() => { load(name).then(data => setState({ data, error: null }), error => setState({ data: null, error })) }, [name])
  return [state.data, state.error]
}

// places.json is stored as columns; turn it into one object per place
export function placeRows(cols) {
  const keys = Object.keys(cols), n = cols.id.length, out = new Array(n)
  for (let i = 0; i < n; i++) { const p = {}; for (const k of keys) p[k] = cols[k][i]; out[i] = p }
  return out
}

// Fixed categorical order (never cycled): 6 hues, then everything else folds into Other
export const CATEGORICAL = ['#0f7a5c', '#e0782f', '#3d78b8', '#c2416f', '#7a5cc4', '#b8911f']
export const OTHER = '#8f9c96'

// One fixed colour per sector (industry group from pipeline/places/business_types.py INDUSTRY_GROUP), used on
// every map and list so a sector always looks the same
export const SECTOR_COLOR = {
  'Food and drink': '#e0782f', Retail: '#c2416f', Health: '#0f7a5c', 'Childcare, education and care': '#3d78b8',
  'Community and culture': '#7a5cc4', 'Leisure and hospitality': '#d4a514', 'Personal services': '#2bb3b1',
  'Business and professional': '#475569', 'Industry, construction and transport': '#8a5a2b',
  'Dormant or non-trading': '#b7c0bb', Other: OTHER,
}
export const sectorColor = g => SECTOR_COLOR[g] || OTHER

export const fmt = n => Number(n).toLocaleString('en-GB')

// metres between two lat/lon points (fine at city scale)
export function metres(la1, lo1, la2, lo2) { return Math.hypot((lo2 - lo1) * 70000, (la2 - la1) * 111200) }

export function bounds(rings) {
  let s = 90, w = 180, n = -90, e = -180
  for (const r of rings) for (const [x, y] of r) { s = Math.min(s, y); n = Math.max(n, y); w = Math.min(w, x); e = Math.max(e, x) }
  return [[s, w], [n, e]]
}
