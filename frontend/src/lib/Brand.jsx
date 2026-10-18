export function LogoMark() {
  return <svg className="logo-mark" viewBox="0 0 42 42" aria-hidden="true">
    <circle cx="20" cy="22" r="14.5" fill="none" stroke="currentColor" strokeWidth="2"/>
    <circle cx="20" cy="22" r="6.5" fill="none" stroke="#d7ff3f" strokeWidth="3"/>
    <circle cx="20" cy="22" r="2.4" fill="#d7ff3f"/>
    <circle cx="33.5" cy="8.5" r="3.2" fill="#d7ff3f" stroke="currentColor" strokeWidth="1.5"/>
  </svg>
}

export function Brand({ inverse = false, centre = false }) {
  return <div className={`brand ${inverse ? 'inverse' : ''} ${centre ? 'centre' : ''}`} aria-label="CivicLens">
    <LogoMark />
    <span className="brand-wordmark"><b>Civic</b><b>Lens</b></span>
  </div>
}
