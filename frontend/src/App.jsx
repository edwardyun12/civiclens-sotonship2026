import { Component, lazy, Suspense, useEffect, useRef, useState } from 'react'
import { ArrowLeft, Bot, Building2, ExternalLink, MessageCircle, Send, Sparkles, Target, X } from 'lucide-react'
import { Brand } from './lib/Brand.jsx'
import Welcome from './welcome/Welcome.jsx'
import { getAssistantContext } from './lib/assistantContext.js'

const PlacesView = lazy(() => import('./places/PlacesView.jsx'))
const SimulatorView = lazy(() => import('./simulator/SimulatorView.jsx'))
const TABS = [
  { id: 'places', hash: '#places', label: 'Places', icon: Building2 },
  { id: 'simulator', hash: '#simulator', label: 'Simulator', icon: Target },
]
// Old #heatmap links (the removed Signals page) open Places.
const tabFromHash = () => window.location.hash === '#heatmap' ? 'places' : (TABS.find(t => t.hash === window.location.hash) || {}).id || 'welcome'

// common questions offered when the assistant opens, per page (they use what is on screen)
const COMMON_QUESTIONS = {
  simulator: ['Why is the top site the best place for my business?', 'How was my business idea matched to the data?', 'What are the main risks at this site?',
    'How many competitors are near this site?', 'Who would my customers be here?', 'What should I change to make this site work?'],
  places: ['Which areas have the most businesses?', 'Where is commercial vacancy highest?', 'Compare Shirley and Portswood.',
    'Which sectors lead across Southampton’s wards?', 'Which wards have the most people aged 16–24?', 'What is the evidence on Southampton city centre?'],
}

const escapeRegExp = value => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
function AnswerText({ content, sources = [] }) {
  const linked = sources.filter(source => source.url)
  const byCitation = new Map(linked.map(source => [source.citation, source]))
  const pattern = linked.length ? new RegExp(`(\\[(?:${linked.map(source => escapeRegExp(source.citation)).join('|')})\\])`, 'g') : null
  const inline = (text, key) => !pattern ? text : text.split(pattern).map((part, index) => {
    const source = byCitation.get(part.slice(1, -1))
    return source
      ? <a className="inline-citation" key={`${key}-${index}`} href={source.url} target="_blank" rel="noreferrer">{part}</a>
      : part
  })
  const blocks = content.split(/\n\s*\n/).filter(Boolean)
  return blocks.map((block, blockIndex) => {
    const lines = block.split('\n').filter(Boolean)
    const bullets = lines.every(line => /^\s*[-–•]\s+/.test(line))
    if (bullets) return <ul key={blockIndex}>{lines.map((line, lineIndex) => <li key={lineIndex}>{inline(line.replace(/^\s*[-–•]\s+/, ''), `${blockIndex}-${lineIndex}`)}</li>)}</ul>
    return <p key={blockIndex}>{inline(block, blockIndex)}</p>
  })
}

function Chatbot({ startOpen = true, page }) {
  const [open, setOpen] = useState(startOpen)
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [messages, setMessages] = useState([{ role:'assistant', content:'Ask about Southampton’s business landscape, planning evidence, or what you’re looking at in the app, such as “Why is this site a good fit?”', sources:[] }])
  const endRef = useRef(null)
  useEffect(() => { endRef.current?.scrollIntoView({ behavior:'smooth' }) }, [messages, loading])
  const questions = COMMON_QUESTIONS[page] || COMMON_QUESTIONS.places
  const send = async (event, asked) => {
    event?.preventDefault(); const question=(asked??input).trim(); if(!question||loading)return
    const history=messages.map(({role,content})=>({role,content})).slice(-4)
    setMessages(current=>[...current,{role:'user',content:question},{role:'assistant',content:'',sources:[]}]);setInput('');setLoading(true)
    try{
      const response=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question,history,top_k:3,context:(await getAssistantContext(question))||null})})
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
      <div className="chat-messages">{messages.map((message,index)=><div key={index} className={`message ${message.role}`}><div>{message.content?<AnswerText content={message.content} sources={message.sources}/>:<span className="typing">Searching the evidence<span>…</span></span>}</div>{message.sources?.length>0&&<details><summary>View {message.sources.length} source documents</summary>{message.sources.map((source,i)=><a key={i} href={source.url} target="_blank" rel="noreferrer"><span><b>{source.citation}</b><small>{source.preview}</small></span><ExternalLink size={12}/></a>)}</details>}</div>)}{messages.length===1&&<div className="common-questions"><span>Common questions</span>{questions.map(q=><button key={q} disabled={loading} onClick={()=>send(null,q)}>{q}</button>)}</div>}<div ref={endRef}/></div>
      {messages.length>1&&<div className="chat-suggestions">{questions.slice(0,4).map(q=><button key={q} disabled={loading} onClick={()=>send(null,q)}>{q}</button>)}</div>}
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
      {tab === 'places' && <PlacesView/>}
      {tab === 'simulator' && <SimulatorView/>}
    </Suspense>
    <Chatbot key={tab} page={tab} startOpen={false}/>
  </main>
}

// One failing page shows a message with a way back instead of blanking the whole app
class Guard extends Component {
  state = { error: null }
  static getDerivedStateFromError(error) { return { error } }
  componentDidCatch(error) { console.error(error) }
  render() {
    if (!this.state.error) return this.props.children
    return <div className="map-stage"><div className="tool-error">Something went wrong on this page: {String(this.state.error.message || this.state.error)}
      <br/><button className="link-button" onClick={() => { window.location.hash = ''; window.location.reload() }}>Back to the start</button></div></div>
  }
}

export default function App(){
  const [view,setView]=useState(tabFromHash)
  useEffect(()=>{const sync=()=>setView(tabFromHash());window.addEventListener('hashchange',sync);return()=>window.removeEventListener('hashchange',sync)},[])
  const back=()=>{history.pushState('',document.title,window.location.pathname+window.location.search);setView('welcome')}
  return <Guard key={view}>{view==='welcome'?<Welcome onExplore={hash=>{window.location.hash=hash}}/>:<Workspace tab={view} onBack={back}/>}</Guard>
}
