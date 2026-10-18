// Density heatmap drawn on a canvas over the Leaflet map. Each point spreads over `radiusM` metres; the colour ramp is
// one hue family (pale lime -> deep green), light to dark = fewer to more places close together.
import { useEffect } from 'react'
import { useMap } from 'react-leaflet'
import L from 'leaflet'

const RAMP = [[215, 255, 63], [120, 200, 70], [15, 122, 92], [6, 43, 37]]
function ramp(t) {
  const x = t * (RAMP.length - 1), i = Math.min(RAMP.length - 2, Math.floor(x)), f = x - i
  return RAMP[i].map((c, k) => Math.round(c + (RAMP[i + 1][k] - c) * f))
}

export default function HeatLayer({ points, radiusM = 250 }) {
  const map = useMap()
  useEffect(() => {
    const canvas = L.DomUtil.create('canvas', 'heat-canvas leaflet-zoom-hide')
    map.getPanes().overlayPane.appendChild(canvas)
    const draw = () => {
      const size = map.getSize(), dpr = window.devicePixelRatio || 1
      L.DomUtil.setPosition(canvas, map.containerPointToLayerPoint([0, 0]))
      canvas.style.width = size.x + 'px'; canvas.style.height = size.y + 'px'
      canvas.width = size.x * dpr; canvas.height = size.y * dpr
      const ctx = canvas.getContext('2d', { willReadFrequently: true }); ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      const lat = map.getCenter().lat, mpp = 40075016.686 * Math.cos((lat * Math.PI) / 180) / 2 ** (map.getZoom() + 8)
      const r = Math.max(6, radiusM / mpp)
      for (const p of points) {
        const c = map.latLngToContainerPoint([p.lat, p.lon])
        if (c.x < -r || c.y < -r || c.x > size.x + r || c.y > size.y + r) continue
        const g = ctx.createRadialGradient(c.x, c.y, 0, c.x, c.y, r)
        g.addColorStop(0, 'rgba(0,0,0,0.14)'); g.addColorStop(1, 'rgba(0,0,0,0)')
        ctx.fillStyle = g; ctx.fillRect(c.x - r, c.y - r, 2 * r, 2 * r)
      }
      const img = ctx.getImageData(0, 0, canvas.width, canvas.height), d = img.data
      let max = 1; for (let i = 3; i < d.length; i += 4) if (d[i] > max) max = d[i]
      for (let i = 0; i < d.length; i += 4) {
        const t = d[i + 3] / max; if (t < 0.03) { d[i + 3] = 0; continue }
        const [R, G, B] = ramp(Math.pow(t, 0.75)); d[i] = R; d[i + 1] = G; d[i + 2] = B; d[i + 3] = Math.round(70 + 165 * Math.pow(t, 0.5))
      }
      ctx.putImageData(img, 0, 0)
    }
    draw()
    map.on('moveend zoomend resize', draw)
    return () => { map.off('moveend zoomend resize', draw); canvas.remove() }
  }, [map, points, radiusM])
  return null
}

export const HEAT_GRADIENT = `linear-gradient(90deg, rgb(${RAMP[0]}), rgb(${RAMP[1]}), rgb(${RAMP[2]}), rgb(${RAMP[3]}))`
