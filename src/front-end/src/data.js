export const useCases = [
  {
    id: 'founder',
    eyebrow: 'Build',
    title: 'Start a business',
    description: 'Find underserved locations, compare local demand and understand nearby competition.',
    accent: '#dbff4a',
  },
  {
    id: 'investor',
    eyebrow: 'Invest',
    title: 'Invest or develop',
    description: 'Explore commercial activity, vacancy signals and the planning context around growth areas.',
    accent: '#7fe3d2',
  },
  {
    id: 'planner',
    eyebrow: 'Plan',
    title: 'Plan public services',
    description: 'Connect neighbourhood needs with accessibility, demographics and evidence-led priorities.',
    accent: '#ffc978',
  },
  {
    id: 'researcher',
    eyebrow: 'Understand',
    title: 'Research the city',
    description: 'Ask questions across official reports and trace every claim back to its evidence.',
    accent: '#a6b6ff',
  },
  {
    id: 'other',
    eyebrow: 'Explore',
    title: 'Something else',
    description: 'Start with a broad view and shape the analysis around your own objective.',
    accent: '#e8f1ed',
  },
]

export const centres = [
  { name: 'City Centre', position: [50.9049, -1.4043], vacancy: 12.04, footfall: -9.6, units: 458, comparable: true },
  { name: 'Shirley', position: [50.9146, -1.4323], vacancy: 10.94, footfall: -24.0, units: 265, comparable: true },
  { name: 'Bitterne', position: [50.9144, -1.3564], vacancy: 10.89, footfall: -23.0, units: 98, comparable: false },
  { name: 'Lordshill', position: [50.9382, -1.4468], vacancy: 12.5, footfall: 4.0, units: 16, comparable: true },
  { name: 'Portswood', position: [50.9272, -1.3906], vacancy: 6.45, footfall: -16.3, units: 124, comparable: true },
  { name: 'Woolston', position: [50.8985, -1.3776], vacancy: 9.35, footfall: -33.0, units: 108, comparable: false },
]

export const features = [
  { id: 'map', title: 'Opportunity map', copy: 'See business activity, vacancy and footfall signals by centre.', for: ['founder', 'investor'] },
  { id: 'compare', title: 'Neighbourhood comparison', copy: 'Compare local conditions without losing the caveats behind each number.', for: ['founder', 'planner', 'researcher'] },
  { id: 'scenario', title: 'Scenario explorer', copy: 'Frame a potential use against accessibility, competition and policy evidence.', for: ['investor', 'planner'] },
  { id: 'evidence', title: 'Evidence assistant', copy: 'Ask in plain English and receive concise answers with document citations.', for: ['researcher', 'founder', 'investor', 'planner', 'other'] },
]
