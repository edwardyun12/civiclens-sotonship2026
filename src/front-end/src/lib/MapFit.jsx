// Keep map content in the part of the map that the floating panels don't cover.
import { useEffect } from 'react'
import { useMap } from 'react-leaflet'
import { bounds } from './cityData.js'

const narrow = () => window.innerWidth <= 760
export const pad = right => (narrow() ? { paddingTopLeft: [20, 80], paddingBottomRight: [20, window.innerHeight * 0.45] }
  : { paddingTopLeft: [370, 70], paddingBottomRight: [right ? 420 : 30, 30] })

// fit the whole city once the outline is known
export function FitCity({ city, right }) {
  const map = useMap()
  useEffect(() => {
    if (!city) return
    const rings = Object.values(city.ward_outlines).flat()
    map.fitBounds(bounds(rings), pad(right))
  }, [map, city]) // eslint-disable-line react-hooks/exhaustive-deps
  return null
}

// pan just enough to keep a point (e.g. the proposed site) visible beside the panels
export function KeepInView({ at, right }) {
  const map = useMap()
  useEffect(() => { if (at) map.panInside(at, { ...pad(right), animate: true }) }, [map, at?.[0], at?.[1]]) // eslint-disable-line react-hooks/exhaustive-deps
  return null
}
