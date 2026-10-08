# WX//SYS weather dashboard

A Flask weather dashboard with city search, a 24-hour trace, a 7-day forecast and animated NEXRAD radar.

## Run it locally

```
pip install -r requirements.txt
python app.py
```

Then open http://localhost:5050

## Put it online (Render, free)

1. Create a GitHub repository and upload `app.py`, `requirements.txt` and `render.yaml`.
2. Sign up at https://render.com and connect your GitHub account.
3. Choose **New → Blueprint**, pick the repository, and confirm. Render reads `render.yaml` and builds the site.
   (Or choose **New → Web Service** and enter the build command `pip install -r requirements.txt`
   and the start command `gunicorn app:app --workers 2 --timeout 60`, with the Free instance type.)
4. When the build finishes you get a public address like `https://wx-sys.onrender.com`.

Every time you push a change to GitHub, Render redeploys automatically.

Free-tier note: the site goes to sleep after 15 minutes without visitors, and the next visit takes
about a minute to wake it up. A paid instance stays on all the time.

## Data sources

- Forecast and city search: Open-Meteo (free, no key, non-commercial use)
- Radar: Iowa Environmental Mesonet NEXRAD tiles (free, no key, US coverage only)
- Map: CARTO dark basemap, © OpenStreetMap contributors
