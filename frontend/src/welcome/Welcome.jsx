// Welcome page with motion: a map slideshow behind everything, cursor spotlight on the grid, parallax and tilt on
// the orbit graphic, rotating rings, rippling dots joined by drawn lines, ward outlines drawn from city.json, counters
// and a rotating word. Pointer effects only run with a fine pointer; everything is off when the system asks for reduced motion.
import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowRight, Sparkles, Target } from 'lucide-react'
import { Brand } from '../lib/Brand.jsx'
import BackgroundMap, { STOPS } from './BackgroundMap.jsx'
import { fmt, useData } from '../lib/cityData.js'
import './welcome.css'

const WORDS = ['lens', 'angle', 'map', 'light']
// Dots on the orbit graphic: x, y in % of the square, and colour. The lines visit them in this order.
const DOTS = [[28, 17, '#d7ff3f'], [72, 21, '#a6b6ff'], [91, 49, '#69ddbd'], [40, 86, '#ff9e68'], [7, 57, '#d7ff3f']]
const reduceMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches
const finePointer = () => window.matchMedia('(hover: hover) and (pointer: fine)').matches

// Sets --mx/--my (cursor in px) and an eased --px/--py (-1..1) on the page. Writes CSS variables only, so React
// never re-renders on mouse move.
function usePointerMotion(ref) {
  useEffect(() => {
    const page = ref.current
    if (!page || reduceMotion() || !finePointer()) return
    let tx = 0, ty = 0, cx = 0, cy = 0, frame = 0
    const tick = () => {
      cx += (tx - cx) * .08; cy += (ty - cy) * .08
      page.style.setProperty('--px', cx.toFixed(4)); page.style.setProperty('--py', cy.toFixed(4))
      frame = Math.abs(tx - cx) + Math.abs(ty - cy) > .001 ? requestAnimationFrame(tick) : 0
    }
    const move = e => {
      const r = page.getBoundingClientRect()
      page.style.setProperty('--mx', `${e.clientX - r.left}px`); page.style.setProperty('--my', `${e.clientY - r.top}px`)
      page.classList.add('pointer-in')
      tx = e.clientX / innerWidth * 2 - 1; ty = e.clientY / innerHeight * 2 - 1
      if (!frame) frame = requestAnimationFrame(tick)
    }
    const leave = () => {
      tx = ty = 0; page.classList.remove('pointer-in')
      if (!frame) frame = requestAnimationFrame(tick)
    }
    page.addEventListener('pointermove', move); page.addEventListener('pointerleave', leave)
    return () => { page.removeEventListener('pointermove', move); page.removeEventListener('pointerleave', leave); cancelAnimationFrame(frame) }
  }, [ref])
}

function useRotatingWord() {
  const [i, setI] = useState(0)
  useEffect(() => {
    if (reduceMotion()) return
    const t = setInterval(() => setI(n => (n + 1) % WORDS.length), 2800)
    return () => clearInterval(t)
  }, [])
  return WORDS[i]
}

// Slideshow position; each stop shows for 9 s, and picking a stop restarts its timer
function useTour() {
  const [stop, setStop] = useState(0)
  const [still] = useState(reduceMotion)
  useEffect(() => {
    if (still) return
    const t = setTimeout(() => setStop(n => (n + 1) % STOPS.length), 9000)
    return () => clearTimeout(t)
  }, [stop, still])
  return [stop, setStop, still]
}

function useCountUp(target) {
  const [n, setN] = useState(0)
  useEffect(() => {
    if (!target) return
    if (reduceMotion()) { setN(target); return }
    let frame, start
    const step = t => {
      start ??= t
      const k = Math.min(1, (t - start) / 1800)
      setN(Math.round(target * (1 - (1 - k) ** 3)))
      if (k < 1) frame = requestAnimationFrame(step)
    }
    frame = requestAnimationFrame(step)
    return () => cancelAnimationFrame(frame)
  }, [target])
  return n
}

function Stat({ value, label, i }) {
  const n = useCountUp(value)
  return <div className="stat-chip" style={{ '--i': i }}><b>{fmt(n)}</b><span>{label}</span></div>
}

// Real counts from the front-end data files; a chip only appears once its number has loaded.
function Stats({ className }) {
  const [city] = useData('city')
  const [places] = useData('places')
  const items = [
    [places?.id.length, 'places mapped'],
    [city && Object.keys(city.ward_outlines).length, 'wards'],
    [city?.oa.pop.reduce((a, b) => a + b, 0), 'residents'],
  ]
  return <div className={className} aria-label="Southampton in numbers">
    {items.map(([value, label], i) => value ? <Stat key={label} value={value} label={label} i={i} /> : null)}
  </div>
}

// Southampton's ward outlines, projected to a flat SVG and drawn in one by one behind the orbit.
function WardMap() {
  const [city] = useData('city')
  const map = useMemo(() => {
    if (!city) return null
    const k = Math.cos(50.91 * Math.PI / 180)
    const wards = Object.values(city.ward_outlines)
    let w = Infinity, e = -Infinity, s = Infinity, n = -Infinity
    for (const rings of wards) for (const r of rings) for (const [lon, lat] of r) {
      w = Math.min(w, lon * k); e = Math.max(e, lon * k); s = Math.min(s, lat); n = Math.max(n, lat)
    }
    const f = 100 / Math.max(e - w, n - s)
    const pt = ([lon, lat]) => `${((lon * k - w) * f).toFixed(2)},${((n - lat) * f).toFixed(2)}`
    return {
      box: `0 0 ${((e - w) * f).toFixed(2)} ${((n - s) * f).toFixed(2)}`,
      paths: wards.map(rings => rings.map(r => `M${r.map(pt).join('L')}Z`).join('')),
    }
  }, [city])
  if (!map) return null
  return <svg className="ward-map" viewBox={map.box} aria-hidden="true">
    {map.paths.map((d, i) => <path key={i} d={d} pathLength="1" style={{ '--i': i }} />)}
  </svg>
}

function Orbit() {
  const loop = [...DOTS, DOTS[0]].map(([x, y]) => `${x},${y}`).join(' ')
  const spokes = DOTS.map(([x, y]) => `M50,50L${x},${y}`).join('')
  return <div className="city-orbit" aria-hidden="true">
    <WardMap />
    <div className="orbit-line orbit-one"><i /></div>
    <div className="orbit-line orbit-two"><i /></div>
    <div className="orbit-line orbit-three"><i /><i /></div>
    <svg className="orbit-links" viewBox="0 0 100 100" preserveAspectRatio="none">
      <path className="spokes" d={spokes} pathLength="1" />
      <polyline points={loop} pathLength="1" />
      <polyline className="runner" points={loop} pathLength="1" />
    </svg>
    <div className="orbit-dots">
      {DOTS.map(([x, y, c], i) => <span key={i} className="dot" style={{ left: `${x}%`, top: `${y}%`, '--c': c, '--i': i }} />)}
    </div>
    <span className="city-core"><Brand inverse centre /></span>
    <Stats className="orbit-stats" />
  </div>
}

export default function Welcome({ onExplore }) {
  const page = useRef(null)
  usePointerMotion(page)
  const word = useRotatingWord()
  const [stop, setStop, still] = useTour()
  return <main className="welcome-page" ref={page}>
    <BackgroundMap stop={stop} still={still} />
    <div className="welcome-grid" />
    <div className="welcome-grid glow" />
    <div className="welcome-spot" />
    <header className="welcome-header reveal" style={{ '--i': 0 }}><Brand inverse /><span>Urban intelligence for better decisions</span></header>
    <section className="welcome-hero">
      <div className="welcome-copy">
        <span className="eyebrow reveal" style={{ '--i': 1 }}><Sparkles size={14} /> Discover local opportunity</span>
        <h1 className="reveal" style={{ '--i': 2 }} aria-label="See Southampton through a new lens.">
          See Southampton<br />through a new <em key={word} className="swap-word" aria-hidden="true">{word}.</em>
        </h1>
        <p className="reveal" style={{ '--i': 3 }}>Explore the businesses, services and places shaping Southampton, then test a site, on one intelligent map.</p>
        <div className="welcome-actions reveal" style={{ '--i': 4 }}>
          <button className="explore-button" onClick={() => onExplore('#places')}><span>Explore the map</span><ArrowRight size={18} /></button>
          <button className="explore-button ghost" onClick={() => onExplore('#simulator')}><span>Test a site</span><Target size={18} /></button>
        </div>
        <Stats className="welcome-stats reveal" />
      </div>
      <Orbit />
    </section>
    <footer className="welcome-footer reveal" style={{ '--i': 6 }}>
      <div className="tour">
        <div className="tour-steps">{STOPS.map((s, i) => <button key={s.name} className={i === stop ? 'on' : ''} onClick={() => setStop(i)}
          aria-label={`Show ${s.name}`} aria-current={i === stop || undefined}><i key={i === stop ? stop : 'off'} /></button>)}</div>
        <span key={stop} className="tour-caption"><b>{STOPS[stop].name}</b> · {STOPS[stop].kind}</span>
      </div>
      <span>Southampton, United Kingdom</span>
    </footer>
  </main>
}
