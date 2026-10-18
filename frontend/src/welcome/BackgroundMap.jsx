// Background slideshow for the welcome page: a dark, non-interactive map that flies between Southampton areas,
// with mapped places (lime) and residents by output area (teal) drawn on it.
import { useEffect, useMemo } from 'react'
import { CircleMarker, MapContainer, TileLayer, useMap } from 'react-leaflet'
import { useData } from '../lib/cityData.js'

// Centre types for the five study centres are from the 2024 Centres Study; the other two are plain descriptions.
export const STOPS = [
  { name: 'City Centre', kind: 'Primary shopping area', at: [50.9049, -1.4043] },
  { name: 'Ocean Village', kind: 'Waterfront and marina', at: [50.8957, -1.3929] },
  { name: 'Portswood', kind: 'District centre', at: [50.9272, -1.3906] },
  { name: 'Highfield', kind: 'University campus', at: [50.9350, -1.3960] },
  { name: 'Shirley', kind: 'Town centre', at: [50.9146, -1.4323] },
  { name: 'Woolston', kind: 'District centre', at: [50.8985, -1.3776] },
  { name: 'Bitterne', kind: 'District centre', at: [50.9144, -1.3564] },
]
const ZOOM = 15

function Tour({ stop, still }) {
  const map = useMap()
  useEffect(() => {
    // put the area right of centre, clear of the welcome text
    const size = map.getSize()
    const target = map.unproject(map.project(STOPS[stop].at, ZOOM).subtract([size.x * .16, 0]), ZOOM)
    if (still) { map.setView(target, ZOOM, { animate: false }); return }
    // Leaving the page removes the map before this cleanup runs, and remove() already stops any animation;
    // calling stop() on a removed map throws and takes the whole app down.
    let removed = false
    const onUnload = () => { removed = true }
    const drift = () => map.panBy([80, 26], { duration: 6, easeLinearity: 1 })
    map.on('unload', onUnload)
    map.once('moveend', drift)
    map.flyTo(target, ZOOM, { duration: 2.6 })
    return () => {
      if (removed) return
      map.off('unload', onUnload); map.off('moveend', drift); map.stop()
    }
  }, [stop, still, map])
  return null
}

export default function BackgroundMap({ stop, still }) {
  const [places] = useData('places')
  const [city] = useData('city')
  const dots = useMemo(() => {
    const out = []
    if (city) city.oa.lat.forEach((lat, i) => out.push({ k: `o${i}`, at: [lat, city.oa.lon[i]], r: Math.sqrt(city.oa.pop[i]) / 7, oa: true }))
    // companies known only by their registered office are left out: that address is not where they trade
    if (places) places.lat.forEach((lat, i) => { if (!places.ro[i]) out.push({ k: `p${i}`, at: [lat, places.lon[i]], r: 2.6 }) })
    return out
  }, [places, city])
  return <div className="welcome-bg" aria-hidden="true">
    <MapContainer center={STOPS[0].at} zoom={13} zoomControl={false} dragging={false} scrollWheelZoom={false} doubleClickZoom={false}
      touchZoom={false} boxZoom={false} keyboard={false} preferCanvas className="welcome-bg-map">
      <TileLayer attribution='&copy; OpenStreetMap contributors' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
      {dots.map(d => <CircleMarker key={d.k} center={d.at} radius={d.r} interactive={false}
        pathOptions={d.oa ? { stroke: false, fillColor: '#69ddbd', fillOpacity: .16 } : { stroke: false, fillColor: '#d7ff3f', fillOpacity: .85 }} />)}
      <Tour stop={stop} still={still} />
    </MapContainer>
    <div className="welcome-bg-shade" />
  </div>
}
