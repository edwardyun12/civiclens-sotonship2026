// What the user is looking at right now (current page, business, site, scores), in plain text. The pages set it;
// the chatbot sends it with each question so the assistant can explain the app's own analysis.
// A page can also pass `about(question)`, which adds analysis for what the question itself asks about (another
// area or business), so "a Japanese store in Weston" is answered for Weston, not for the site on screen.
let context = '', about = null
export const setAssistantContext = (text, aboutFn = null) => { context = String(text || ''); about = aboutFn }
export const getAssistantContext = async (question = '') => {
  let extra = ''
  try { extra = about && question ? (await about(question)) || '' : '' } catch (e) { console.warn('assistant context', e) }
  return [extra, extra ? 'What is on screen (only use it if the question is about it):' : '', context].filter(Boolean).join('\n').slice(0, 4500)
}

// Find the ward or neighbourhood a question names ("in Weston", "near Bitterne Park"); the longest match wins.
export function findPlace(question, wards, hoods) {
  const q = ` ${String(question).toLowerCase().replace(/[^a-z' ]+/g, ' ')} `
  let best = null
  const consider = (name, data) => {
    const n = name.toLowerCase().replace(/[^a-z' ]+/g, ' ').trim()
    if (n.length > 2 && q.includes(` ${n} `) && (!best || n.length > best.n.length)) best = { n, ...data }
  }
  for (const h of hoods || []) consider(h.name, { name: h.name, kind: 'neighbourhood', ward: h.ward, lat: h.lat, lon: h.lon })
  for (const w of wards || []) consider(w, { name: w, kind: 'ward', ward: w })
  return best
}

// The business words left in a question once the place and filler words are removed ("japanese store").
const FILLER = new Set(('i im i\'m want wanna would like to build open opening start starting set up setup a an the at in on near ' +
  'around by of for my our new business shop place is it good idea should we can could where what how about there here ' +
  'southampton area ward neighbourhood please think you do does be will').split(' '))
export const businessWords = (question, placeName = '') => String(question).toLowerCase()
  .replace(placeName.toLowerCase(), ' ').replace(/[^a-z' ]+/g, ' ').split(' ').filter(w => w && !FILLER.has(w)).join(' ')
