import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { CircleMarker, MapContainer, Popup, TileLayer, Tooltip } from 'react-leaflet'
import { Activity, ArrowLeft, ArrowRight, Bot, Building2, ChevronDown, Layers3, MapPin, MessageCircle, Navigation, Send, Sparkles, Target, X } from 'lucide-react'
import { centres } from './data.js'

const PlacesView = lazy(() => import('./places/PlacesView.jsx'))
const SimulatorView = lazy(() => import('./simulator/SimulatorView.jsx'))
const TABS = [
  { id: 'signals', hash: '#heatmap', label: 'Signals', icon: Activity },
  { id: 'places', hash: '#places', label: 'Places', icon: Building2 },
  { id: 'simulator', hash: '#simulator', label: 'Simulator', icon: Target },
]
const tabFromHash = () => (TABS.find(t => t.hash === window.location.hash) || {}).id || 'welcome'

const layers = {
  vacancy: { label: 'Vacancy', title: 'Vacancy pressure', suffix: '%', detail: 'Share of surveyed commercial units recorded as vacant.' },
  footfall: { label: 'Footfall', title: 'Footfall movement', suffix: '%', detail: 'Recorded change in centre footfall from 2023 to 2024.' },
  units: { label: 'Business density', title: 'Commercial density', suffix: ' units', detail: 'Number of surveyed commercial units in each centre.' },
}

function LogoMark() {
  return <svg className="logo-mark" viewBox="0 0 42 42" aria-hidden="true">
    <circle cx="20" cy="22" r="14.5" fill="none" stroke="currentColor" strokeWidth="2"/>
    <circle cx="20" cy="22" r="6.5" fill="none" stroke="#d7ff3f" strokeWidth="3"/>
    <circle cx="20" cy="22" r="2.4" fill="#d7ff3f"/>
    <circle cx="33.5" cy="8.5" r="3.2" fill="#d7ff3f" stroke="currentColor" strokeWidth="1.5"/>
  </svg>
}

function Brand({ inverse = false, centre = false }) {
  return <div className={`brand ${inverse ? 'inverse' : ''} ${centre ? 'centre' : ''}`} aria-label="CivicLens">
    <LogoMark />
    <span className="brand-wordmark"><b>Civic</b><b>Lens</b></span>
  </div>
}

function Welcome({ onExplore }) {
  return <main className="welcome-page">
    <div className="welcome-grid" />
    <header className="welcome-header"><Brand inverse /><span>Urban intelligence for better decisions</span></header>
    <section className="welcome-hero">
      <div className="welcome-copy">
        <span className="eyebrow"><Sparkles size={14} /> Discover local opportunity</span>
        <h1>See Southampton<br />through a <em>new lens.</em></h1>
        <p>Explore the signals shaping local business—from commercial vacancy to changing footfall—on one intelligent map.</p>
        <div className="welcome-actions">
          <button className="explore-button" onClick={() => onExplore('#heatmap')}>Explore the heatmap <ArrowRight size={19} /></button>
          <button className="explore-button ghost" onClick={() => onExplore('#places')}><Building2 size={18} /> Find places</button>
          <button className="explore-button ghost" onClick={() => onExplore('#simulator')}><Target size={18} /> Test a site</button>
        </div>
      </div>
      <div className="city-orbit" aria-hidden="true">
        <div className="orbit-line orbit-one" /><div className="orbit-line orbit-two" /><div className="orbit-line orbit-three" />
        <span className="city-core"><Brand inverse centre /></span>
        <span className="pulse p1" /><span className="pulse p2" /><span className="pulse p3" /><span className="pulse p4" />
      </div>
    </section>
    <footer className="welcome-footer"><span>Southampton, United Kingdom</span><span>Built for evidence-led exploration</span></footer>
  </main>
}

function HeatSpot({ centre, metric, selected, onSelect }) {
  const values = centres.map(item => Math.abs(item[metric]))
  const max = Math.max(...values)
  const min = Math.min(...values)
  const strength = Math.max(.12, (Math.abs(centre[metric]) - min) / (max - min || 1))
  const positive = metric === 'footfall' && centre.footfall > 0
  const colour = positive ? '#36d399' : strength > .67 ? '#ff6647' : strength > .36 ? '#ffad45' : '#dafa55'
  const radius = 22 + strength * 34
  return <>
    <CircleMarker center={centre.position} radius={radius * 1.65} pathOptions={{ stroke:false, fillColor:colour, fillOpacity:.08 }} interactive={false}/>
    <CircleMarker center={centre.position} radius={radius * 1.18} pathOptions={{ stroke:false, fillColor:colour, fillOpacity:.14 }} interactive={false}/>
    <CircleMarker center={centre.position} radius={radius * .7} pathOptions={{ color:selected ? '#fff' : colour, weight:selected ? 3 : 1, fillColor:colour, fillOpacity:.55 }} eventHandlers={{ click: () => onSelect(centre) }}>
      <Tooltip direction="top" offset={[0,-10]}><b>{centre.name}</b><br/>{centre[metric] > 0 && metric === 'footfall' ? '+' : ''}{centre[metric]}{layers[metric].suffix}</Tooltip>
      <Popup><strong>{centre.name}</strong><br/>{centre[metric]}{layers[metric].suffix}</Popup>
    </CircleMarker>
  </>
}

function Heatmap({ metric, selected, onSelect }) {
  return <MapContainer center={[50.913, -1.401]} zoom={12.4} scrollWheelZoom className="map-canvas" zoomControl={false}>
    <TileLayer attribution='&copy; OpenStreetMap contributors' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
    {centres.map(centre => <HeatSpot key={centre.name} centre={centre} metric={metric} selected={selected?.name === centre.name} onSelect={onSelect}/>) }
  </MapContainer>
}

function PlaceCard({ place, metric, onClose }) {
  if (!place) return null
  const value = place[metric]
  return <aside className="place-card">
    <button className="close-card" onClick={onClose} aria-label="Close location details"><X size={16}/></button>
    <span className="place-kicker"><MapPin size={13}/> Selected centre</span>
    <h2>{place.name}</h2>
    <div className="place-value"><strong>{metric === 'footfall' && value > 0 ? '+' : ''}{value}{layers[metric].suffix}</strong><span>{layers[metric].title}</span></div>
    <div className="place-stats"><span><b>{place.units}</b>commercial units</span><span><b>{place.vacancy}%</b>vacancy</span><span><b>{place.footfall > 0 ? '+' : ''}{place.footfall}%</b>footfall</span></div>
    {!place.comparable && <p>Footfall is a partial series and should not be treated as a full-year comparison.</p>}
  </aside>
}

function Chatbot({ startOpen = true }) {
  const [open, setOpen] = useState(startOpen)
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [messages, setMessages] = useState([{ role:'assistant', content:'Ask about Southampton’s business landscape, local centres or planning evidence.', sources:[] }])
  const endRef = useRef(null)
  useEffect(() => { endRef.current?.scrollIntoView({ behavior:'smooth' }) }, [messages, loading])
  const send = async event => {
    event?.preventDefault(); const question=input.trim(); if(!question||loading)return
    const history=messages.map(({role,content})=>({role,content})).slice(-4)
    setMessages(current=>[...current,{role:'user',content:question},{role:'assistant',content:'',sources:[]}]);setInput('');setLoading(true)
    try{
      const response=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question,history,top_k:3})})
      if(!response.ok||!response.body)throw new Error('The evidence service is unavailable.')
      const reader=response.body.getReader();const decoder=new TextDecoder();let buffer=''
      while(true){const {value,done}=await reader.read();if(done)break;buffer+=decoder.decode(value,{stream:true});const lines=buffer.split('\n');buffer=lines.pop()??''
        for(const line of lines){if(!line)continue;const data=JSON.parse(line);if(data.type==='error')throw new Error(data.message)
          setMessages(current=>{const next=[...current];const last={...next.at(-1)};if(data.type==='token')last.content+=data.content;if(data.type==='sources')last.sources=data.sources;next[next.length-1]=last;return next})}}
    }catch(error){setMessages(current=>{const next=[...current];next[next.length-1]={role:'assistant',content:error.message,sources:[]};return next})}finally{setLoading(false)}
  }
  return <>
    {!open&&<button className="chat-launcher" onClick={()=>setOpen(true)}><MessageCircle size={21}/><span>Ask the assistant</span></button>}
    {open&&<section className="chat-panel">
      <header><span className="bot-icon"><Bot size={19}/></span><div><strong>Opportunity assistant</strong><small><i/> Evidence connected</small></div><button onClick={()=>setOpen(false)} aria-label="Close assistant"><X size={18}/></button></header>
      <div className="chat-intro"><Sparkles size={15}/><span>Grounded answers from Southampton evidence</span></div>
      <div className="chat-messages">{messages.map((message,index)=><div key={index} className={`message ${message.role}`}><div>{message.content||<span className="typing">Searching the evidence<span>…</span></span>}</div>{message.sources?.length>0&&<details><summary>{message.sources.length} sources</summary>{message.sources.map((source,i)=><span key={i}>{source.citation}</span>)}</details>}</div>)}<div ref={endRef}/></div>
      <div className="chat-suggestions"><button onClick={()=>setInput('Where is commercial vacancy highest?')}>Highest vacancy</button><button onClick={()=>setInput('Compare Shirley and Portswood.')}>Compare centres</button></div>
      <form onSubmit={send}><input value={input} onChange={event=>setInput(event.target.value)} placeholder="Ask about Southampton…"/><button disabled={!input.trim()||loading} aria-label="Send question"><Send size={17}/></button></form>
    </section>}
  </>
}

function Workspace({ tab, onBack }) {
  return <main className="map-page">
    <header className="map-header"><Brand/><button className="back-button" onClick={onBack}><ArrowLeft size={16}/> Welcome</button>
      <nav className="tabs" aria-label="Tools">{TABS.map(({ id, hash, label, icon: Icon }) => <a key={id} href={hash} className={tab === id ? 'active' : ''} aria-current={tab === id ? 'page' : undefined}><Icon size={15}/> {label}</a>)}</nav>
      <div className="status"><i/> Evidence service online</div></header>
    <Suspense fallback={<div className="map-stage"><div className="tool-error">Loading…</div></div>}>
      {tab === 'signals' && <SignalsMap/>}
      {tab === 'places' && <PlacesView/>}
      {tab === 'simulator' && <SimulatorView/>}
    </Suspense>
    <Chatbot key={tab} startOpen={tab === 'signals'}/>
  </main>
}

function SignalsMap() {
  const [metric,setMetric]=useState('vacancy');const [selected,setSelected]=useState(null)
  return <div className="map-stage">
      <Heatmap metric={metric} selected={selected} onSelect={setSelected}/>
      <section className="map-title"><span className="eyebrow"><Navigation size={13}/> Southampton intelligence</span><h1>Explore the city’s<br/><em>opportunity signals.</em></h1><p>Select a centre to inspect its local evidence.</p></section>
      <section className="layer-panel"><span><Layers3 size={14}/> Map layer</span><div>{Object.entries(layers).map(([id,layer])=><button key={id} className={metric===id?'active':''} onClick={()=>{setMetric(id);setSelected(null)}}>{layer.label}</button>)}</div><p>{layers[metric].detail}</p></section>
      <div className="legend"><span>Lower signal</span><i/><i/><i/><span>Higher signal</span></div>
      <PlaceCard place={selected} metric={metric} onClose={()=>setSelected(null)}/>
      <div className="map-source">Observed centre-level evidence · 2024 <button><ChevronDown size={13}/> Methodology</button></div>
    </div>
}

export default function App(){
  const [view,setView]=useState(tabFromHash)
  useEffect(()=>{const sync=()=>setView(tabFromHash());window.addEventListener('hashchange',sync);return()=>window.removeEventListener('hashchange',sync)},[])
  const back=()=>{history.pushState('',document.title,window.location.pathname+window.location.search);setView('welcome')}
  return view==='welcome'?<Welcome onExplore={hash=>{window.location.hash=hash}}/>:<Workspace tab={view} onBack={back}/>
}
