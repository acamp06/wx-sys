# WX//SYS weather dashboard

A single-page weather dashboard: city search, current conditions, animated NEXRAD radar,
a 24-hour trace and a 7-day forecast. Everything runs in the visitor's browser, so the
whole site is one file, `index.html`, and needs no server.

## Run it locally

Double-click `index.html` to open it in your browser. Everything works except the
"My location" button, which browsers only allow on https:// pages, which includes the live site.

## Put it online (GitHub Pages, free, always on)

1. Upload `index.html` to a **public** GitHub repository (the free plan requires public for Pages).
2. In the repository, open **Settings → Pages**.
3. Under **Build and deployment**, set Source to **Deploy from a branch**, Branch to **main**, folder **/ (root)**, then **Save**.
4. After a minute or two the page shows your address: `https://YOUR-USERNAME.github.io/REPO-NAME/`

To change the site later, edit `index.html` on GitHub (pencil icon → Commit changes).
It updates within a minute or two.

## Settings

At the top of the script in `index.html`:

- `DEFAULT_CITY`: the city shown when no location is chosen.
- `CARTO_KEY`: optional free key from https://carto.com/basemaps/apikey/ for a nicer dark radar map.
  Leave it empty to use OpenStreetMap tiles (no key needed).

## Data sources

- Forecast and city search: Open-Meteo (free, no key, non-commercial use)
- Radar: Iowa Environmental Mesonet NEXRAD tiles (free, no key, US coverage only)
- Map: OpenStreetMap tiles (no key), or CARTO dark basemap with an optional key
