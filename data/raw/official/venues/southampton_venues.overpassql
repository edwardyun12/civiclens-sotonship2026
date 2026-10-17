[out:json][timeout:120];
rel(127864)->.boundary;
.boundary map_to_area -> .southampton;
(
  nwr(area.southampton)["shop"]["shop"!~"^(no|vacant)$"];
  nwr(area.southampton)["office"]["office"!="no"];
  nwr(area.southampton)["craft"]["craft"!="no"];
  nwr(area.southampton)["amenity"~"^(restaurant|cafe|bar|pub|fast_food|food_court|bank|pharmacy|clinic|doctors|dentist|hospital|veterinary|childcare|kindergarten|school|college|university|library|cinema|theatre|community_centre|place_of_worship|social_facility|marketplace|fuel|post_office|car_rental|car_wash|gambling|internet_cafe|events_venue|music_venue)$"];
  nwr(area.southampton)["tourism"~"^(hotel|guest_house|hostel|motel|museum|gallery|attraction)$"];
  nwr(area.southampton)["leisure"~"^(fitness_centre|sports_centre|amusement_arcade|bowling_alley|dance|adult_gaming_centre)$"];
  nwr(area.southampton)["building"~"^(commercial|retail|industrial|warehouse|office|supermarket|hotel)$"];
)->.venues;
.boundary out tags;
.venues out meta center;

