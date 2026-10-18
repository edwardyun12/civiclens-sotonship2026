// What the user is looking at right now (current page, business, site, scores), in plain text. The pages set it;
// the chatbot sends it with each question so the assistant can explain the app's own analysis.
let context = ''
export const setAssistantContext = text => { context = String(text || '').slice(0, 3500) }
export const getAssistantContext = () => context
