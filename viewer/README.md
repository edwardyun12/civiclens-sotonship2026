# Browser views

Open either file in a browser (double-click). No install needed; data is built in.

- `places_register.html`: the places database on a map. Advanced filters (industry group, type, detailed type,
  cuisine family, cuisine), an **Areas** view that shades wards by matching places per 1,000 residents, and
  **Suggest spots to open**, which ranks locations for whatever the filters describe. Load a newer
  `data/db/places.csv` with the button to see a fresh build.
- `site_simulator.html`: the Module C simulator (coverage, who benefits, uncertainty, audited template brief)
  running on the places database, with the 17 Oct baseline selectable.

The opportunity finder is a first screen, not a verdict: it uses residents within 800 m, existing same-type
places within 800 m and shops/services within 400 m (a footfall stand-in), with weights we chose.
