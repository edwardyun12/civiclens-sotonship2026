// Place types shared by the Places page and the simulator: category labels, everyday words for detailed types,
// and specOf(place) = the one label a place is searched and counted under.
export const CAT_LABEL = { restaurant_cafe: 'Restaurant / café', takeaway: 'Takeaway', pub_bar: 'Pub / bar', other_catering: 'Other catering',
  mobile_caterer: 'Mobile caterer', supermarket: 'Supermarket', shop_food: 'Food shop', shop_other: 'Other shop', nursery: 'Nursery / childcare',
  gp: 'GP surgery', pharmacy: 'Pharmacy', dentist: 'Dentist', hospital: 'Hospital', health_other: 'Other health', library: 'Library',
  education: 'School / college', care_childcare_health: 'Care', hotel: 'Hotel / B&B', community: 'Community', leisure: 'Leisure',
  coworking: 'Coworking', hair_beauty: 'Hair and beauty', personal_services: 'Personal services', professional: 'Professional services',
  finance: 'Finance', property: 'Property', it_tech: 'IT and tech', business_services: 'Business services', wholesale: 'Wholesale',
  construction: 'Construction', manufacturing: 'Manufacturing', food_manufacturer: 'Food manufacturer', motor: 'Motor trade',
  transport_logistics: 'Transport and logistics', utilities_primary: 'Utilities and primary', other: 'Other' }
export const catLabel = c => CAT_LABEL[c] || c
// everyday words that should find a detailed type
export const SYN = { 'Bubble tea': 'boba milk tea', Japanese: 'sushi ramen', Korean: 'kbbq', 'Coffee shop': 'cafe coffee', Café: 'cafe coffee',
  'Dental practice': 'dentist teeth', 'GP practice': 'doctor surgery', 'GP or clinic': 'doctor surgery', 'Fish and chips': 'chippy chip shop',
  Barber: 'hair', 'Nail salon': 'nails manicure', 'Gym or fitness centre': 'fitness workout', 'Pub or bar': 'pub bar drinks',
  'Asian supermarket': 'oriental grocery', Pharmacy: 'chemist', 'Veterinary practice': 'vet pets', Optician: 'glasses eyes' }
export const vague = k => /not known|no detail/.test(k) || !k
// categories that are already specific ("GP surgery") don't need a "(no detail)" note
const SPECIFIC = new Set(['gp', 'pharmacy', 'dentist', 'hospital', 'nursery', 'library', 'supermarket', 'pub_bar', 'hotel', 'hair_beauty', 'coworking', 'takeaway'])
// same names the register uses, so one place type isn't split in two ("GP surgery" vs "GP practice")
const SAME_AS = { gp: 'GP practice', dentist: 'Dental practice', nursery: 'Day nursery or childcare', supermarket: 'Supermarket or convenience store', pub_bar: 'Pub or bar' }
export const specOf = p => p.spec || SAME_AS[p.cat] || (SPECIFIC.has(p.cat) ? catLabel(p.cat) : `${catLabel(p.cat)} (no detail)`)
