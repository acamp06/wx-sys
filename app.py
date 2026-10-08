from flask import Flask, render_template_string, request
from datetime import datetime
from functools import lru_cache
import os
import time
import requests

DEFAULT_CITY = "Nocatee"   # <-- shown when no location is chosen

GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
WX_URL = "https://api.open-meteo.com/v1/forecast"

app = Flask(__name__)


@lru_cache(maxsize=256)
def geocode(query):
    """Turn 'Nocatee' or 'Springfield, Illinois' or 'Paris, France' into coords.
    Returns {"lat", "lon", "place"} or None if nothing matches."""
    parts = [p.strip() for p in query.split(",") if p.strip()]
    if not parts:
        return None
    name, regions = parts[0], [r.lower() for r in parts[1:]]

    results = requests.get(
        GEO_URL, params={"name": name, "count": 10, "language": "en"}, timeout=10
    ).json().get("results") or []
    if not results:
        return None

    # If the user typed "City, State" or "City, Country", prefer a result that matches
    def matches(g):
        fields = [g.get(k, "").lower() for k in ("admin1", "country", "country_code")]
        return all(any(f.startswith(r) for f in fields if f) for r in regions)

    geo = next((g for g in results if matches(g)), results[0])
    place = ", ".join(p for p in (geo["name"], geo.get("admin1")) if p)
    return {"lat": geo["latitude"], "lon": geo["longitude"], "place": place}


# Weather codes -> (description, short code)
CODES = {
    0: ("Clear sky", "CLR"), 1: ("Mostly clear", "CLR"),
    2: ("Partly cloudy", "PCLD"), 3: ("Overcast", "OVC"),
    45: ("Fog", "FOG"), 48: ("Freezing fog", "FZFG"),
    51: ("Light drizzle", "DZ"), 53: ("Drizzle", "DZ"), 55: ("Heavy drizzle", "+DZ"),
    61: ("Light rain", "-RA"), 63: ("Rain", "RA"), 65: ("Heavy rain", "+RA"),
    66: ("Freezing rain", "FZRA"), 67: ("Freezing rain", "FZRA"),
    71: ("Light snow", "-SN"), 73: ("Snow", "SN"), 75: ("Heavy snow", "+SN"),
    77: ("Snow grains", "SG"),
    80: ("Rain showers", "SHRA"), 81: ("Rain showers", "SHRA"), 82: ("Violent showers", "+SHRA"),
    85: ("Snow showers", "SHSN"), 86: ("Snow showers", "+SHSN"),
    95: ("Thunderstorm", "TS"), 96: ("Thunderstorm & hail", "TSGR"), 99: ("Thunderstorm & hail", "TSGR"),
}

def describe(code):
    return CODES.get(code, ("Unknown", "UNK"))

def compass(deg):
    dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    return dirs[round(deg / 22.5) % 16]

_wx_cache = {}          # (lat, lon) -> (fetched_at, data)
WX_CACHE_SECONDS = 600  # reuse a forecast for 10 minutes so many visitors = few API calls

def get_weather(lat, lon):
    key = (round(lat, 2), round(lon, 2))
    hit = _wx_cache.get(key)
    if hit and time.time() - hit[0] < WX_CACHE_SECONDS:
        return hit[1]
    data = fetch_weather(lat, lon)
    if len(_wx_cache) > 500:   # keep memory bounded
        _wx_cache.clear()
    _wx_cache[key] = (time.time(), data)
    return data

def fetch_weather(lat, lon):
    params = {
        "latitude": lat, "longitude": lon,
        "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m,"
                   "apparent_temperature,weather_code,is_day,surface_pressure,cloud_cover",
        "hourly": "temperature_2m,weather_code,precipitation_probability",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,"
                 "weather_code,sunrise,sunset,uv_index_max",
        "temperature_unit": "fahrenheit", "wind_speed_unit": "mph",
        "timezone": "auto", "forecast_days": 7,
    }
    return requests.get(WX_URL, params=params, timeout=10).json()


@app.route("/")
def home():
    # Location comes from the URL: /?city=Denver  or  /?lat=..&lon=..  (from "use my location")
    query = request.args.get("city", "").strip()
    qlat = request.args.get("lat", type=float)
    qlon = request.args.get("lon", type=float)
    error = None

    if qlat is not None and qlon is not None:
        loc = {"lat": qlat, "lon": qlon, "place": "Your location"}
    else:
        loc = geocode(query or DEFAULT_CITY)
        if loc is None:
            error = f'NO MATCH FOR "{query.upper()}" — SHOWING {DEFAULT_CITY.upper()}'
            loc = geocode(DEFAULT_CITY)

    LAT, LON, PLACE = loc["lat"], loc["lon"], loc["place"]

    w = get_weather(LAT, LON)
    c, h, d = w["current"], w["hourly"], w["daily"]
    text, short = describe(c["weather_code"])

    # Next 24 hours, starting from the current hour
    now_hour = c["time"][:13]
    start = next((i for i, t in enumerate(h["time"]) if t.startswith(now_hour)), 0)
    idx = range(start, start + 24)
    temps = [h["temperature_2m"][i] for i in idx]
    rains = [h["precipitation_probability"][i] or 0 for i in idx]
    labels = [datetime.fromisoformat(h["time"][i]).strftime("%H") for i in idx]

    # Build the 24-hour chart (SVG coordinates)
    W, H, PAD = 600, 160, 20
    tmin, tmax = min(temps) - 2, max(temps) + 2
    def x(i): return PAD + i * (W - 2 * PAD) / 23
    def y(t): return PAD + (tmax - t) / (tmax - tmin) * (H - 2 * PAD - 20)
    line = " ".join(f"{x(i):.1f},{y(t):.1f}" for i, t in enumerate(temps))
    area = f"{x(0):.1f},{H - 20} {line} {x(23):.1f},{H - 20}"
    chart = {
        "W": W, "H": H, "line": line, "area": area,
        "points": [{"x": x(i), "y": y(t), "t": round(t), "l": labels[i],
                    "rain": rains[i], "show": i % 3 == 0} for i, t in enumerate(temps)],
        "bars": [{"x": x(i) - 4, "h": r / 100 * 30, "y": H - 20 - r / 100 * 30}
                 for i, r in enumerate(rains)],
    }

    # 7-day forecast with range bars
    lo_all, hi_all = min(d["temperature_2m_min"]), max(d["temperature_2m_max"])
    span = (hi_all - lo_all) or 1
    days = []
    for i in range(len(d["time"])):
        dt = datetime.fromisoformat(d["time"][i])
        lo, hi = d["temperature_2m_min"][i], d["temperature_2m_max"][i]
        days.append({
            "name": "TODAY" if i == 0 else dt.strftime("%a").upper(),
            "date": dt.strftime("%m.%d"),
            "code": describe(d["weather_code"][i])[1],
            "lo": round(lo), "hi": round(hi),
            "rain": d["precipitation_probability_max"][i] or 0,
            "left": (lo - lo_all) / span * 100,
            "width": max((hi - lo) / span * 100, 4),
        })

    return render_template_string(
        PAGE, place=PLACE, lat=LAT, lon=LON, c=c, text=text, short=short,
        query=query, error=error,
        wind_dir=compass(c["wind_direction_10m"]),
        pressure=round(c["surface_pressure"] * 0.02953, 2),   # hPa -> inHg
        uv=d["uv_index_max"][0],
        sunrise=datetime.fromisoformat(d["sunrise"][0]).strftime("%H:%M"),
        sunset=datetime.fromisoformat(d["sunset"][0]).strftime("%H:%M"),
        chart=chart, days=days, today=days[0],
        tz=w.get("timezone", "UTC"),
        updated=datetime.now().strftime("%H:%M:%S"),
    )

PAGE = """
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="600">
<title>WX // {{ place }}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;600&family=Orbitron:wght@400;700;900&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<style>
  :root {
    --bg: #050505;
    --panel: #0c0c0d;
    --line: #2a0a0c;
    --red: #ff1f3d;
    --red-dim: #8a1022;
    --red-glow: rgba(255, 31, 61, .45);
    --text: #e8e8e8;
    --muted: #6b6b70;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: "JetBrains Mono", Menlo, monospace;
    min-height: 100vh;
    padding: 24px 16px 40px;
    background-image:
      linear-gradient(rgba(255,31,61,.04) 1px, transparent 1px),
      linear-gradient(90deg, rgba(255,31,61,.04) 1px, transparent 1px);
    background-size: 32px 32px;
  }
  /* scanlines */
  body::after {
    content: ""; position: fixed; inset: 0; pointer-events: none;
    background: repeating-linear-gradient(0deg, rgba(0,0,0,.25) 0 1px, transparent 1px 3px);
  }
  .wrap { max-width: 900px; margin: 0 auto; }

  .top {
    display: flex; justify-content: space-between; align-items: center;
    border-bottom: 1px solid var(--red-dim); padding-bottom: 10px; margin-bottom: 18px;
    font-size: .75rem; letter-spacing: 2px; color: var(--muted);
  }
  .top .brand { color: var(--red); font-family: Orbitron, sans-serif; font-weight: 700; letter-spacing: 4px; }
  .live { color: var(--red); }
  .live::before {
    content: ""; display: inline-block; width: 7px; height: 7px; border-radius: 50%;
    background: var(--red); margin-right: 6px; box-shadow: 0 0 8px var(--red);
    animation: pulse 1.4s infinite;
  }
  @keyframes pulse { 50% { opacity: .2; } }

  /* ---- location search ---- */
  .search { display: flex; gap: 8px; margin-bottom: 14px; position: relative; z-index: 1; }
  .search .field {
    flex: 1; display: flex; align-items: center;
    background: var(--panel); border: 1px solid var(--red-dim);
  }
  .search .field:focus-within { border-color: var(--red); box-shadow: 0 0 10px var(--red-glow); }
  .search .prompt { color: var(--red); padding: 0 4px 0 12px; font-weight: 600; }
  .search input {
    flex: 1; min-width: 0; background: transparent; border: none; outline: none;
    color: var(--text); font: inherit; font-size: .9rem; letter-spacing: 1px; padding: 11px 10px 11px 4px;
  }
  .search input::placeholder { color: var(--muted); }
  .search button {
    background: var(--panel); color: var(--red); border: 1px solid var(--red-dim);
    font: inherit; font-size: .72rem; letter-spacing: 2px; padding: 0 14px; cursor: pointer;
    white-space: nowrap;
  }
  .search button:hover { border-color: var(--red); background: #1a0508; box-shadow: 0 0 10px var(--red-glow); }
  .search button.primary { background: var(--red); color: var(--bg); border-color: var(--red); font-weight: 600; }
  .search button.primary:hover { background: #ff4560; }
  .err {
    border: 1px solid var(--red); color: var(--red); background: #1a0508;
    font-size: .72rem; letter-spacing: 2px; padding: 9px 12px; margin-bottom: 14px;
  }
  .status { font-size: .68rem; letter-spacing: 2px; color: var(--muted); margin: -8px 0 14px; min-height: 1em; }

  .panel {
    position: relative; background: var(--panel);
    border: 1px solid var(--line); padding: 18px; margin-bottom: 14px;
  }
  /* corner brackets */
  .panel::before, .panel::after {
    content: ""; position: absolute; width: 14px; height: 14px; border: 2px solid var(--red);
  }
  .panel::before { top: -1px; left: -1px; border-right: none; border-bottom: none; }
  .panel::after  { bottom: -1px; right: -1px; border-left: none; border-top: none; }
  .tag {
    font-size: .68rem; letter-spacing: 3px; color: var(--red);
    margin-bottom: 14px; display: flex; justify-content: space-between;
  }
  .tag span { color: var(--muted); }

  .hero { display: grid; grid-template-columns: 1.3fr 1fr; gap: 14px; }
  .temp {
    font-family: Orbitron, sans-serif; font-weight: 900;
    font-size: clamp(5rem, 16vw, 8.5rem); line-height: .9; color: var(--red);
    text-shadow: 0 0 24px var(--red-glow), 0 0 2px var(--red);
  }
  .temp sup { font-size: .35em; vertical-align: top; position: relative; top: .3em; }
  .cond { font-size: 1.1rem; letter-spacing: 3px; text-transform: uppercase; margin-top: 12px; }
  .cond b { color: var(--red); font-weight: 600; margin-right: 10px; }
  .sub { color: var(--muted); font-size: .8rem; margin-top: 6px; letter-spacing: 1px; }
  .sub em { color: var(--text); font-style: normal; }

  .readouts { display: grid; grid-template-columns: 1fr 1fr; gap: 1px; background: var(--line); }
  .ro { background: var(--panel); padding: 12px; }
  .ro .k { font-size: .62rem; letter-spacing: 2px; color: var(--muted); }
  .ro .v { font-family: Orbitron, sans-serif; font-size: 1.35rem; margin-top: 6px; }
  .ro .v small { font-family: "JetBrains Mono", monospace; font-size: .7rem; color: var(--muted); margin-left: 4px; }
  .meter { height: 3px; background: #1a1a1c; margin-top: 8px; }
  .meter i { display: block; height: 100%; background: var(--red); box-shadow: 0 0 6px var(--red); }

  /* ---- radar ---- */
  #radar {
    height: 360px; background: #050505; isolation: isolate;
    border: 1px solid var(--line); font-family: "JetBrains Mono", monospace;
  }
  #radar .leaflet-bar a {
    background: var(--panel); color: var(--red); border-bottom-color: var(--line);
  }
  #radar .leaflet-bar a:hover { background: #1a0508; }
  #radar .leaflet-bar { border: 1px solid var(--red-dim); }
  #radar .leaflet-control-attribution {
    background: rgba(5,5,5,.75); color: var(--muted); font-size: 9px;
  }
  #radar .leaflet-control-attribution a { color: var(--muted); }
  .radar-ctl { display: flex; align-items: center; gap: 12px; margin-top: 12px; font-size: .72rem; letter-spacing: 2px; }
  .radar-ctl button {
    background: var(--panel); color: var(--red); border: 1px solid var(--red-dim);
    font: inherit; padding: 6px 12px; cursor: pointer; min-width: 74px;
  }
  .radar-ctl button:hover { border-color: var(--red); box-shadow: 0 0 10px var(--red-glow); }
  .radar-ctl input[type=range] { flex: 1; accent-color: var(--red); }
  .radar-ctl .rt { color: var(--text); min-width: 52px; text-align: right; }

  svg { width: 100%; height: auto; display: block; }
  .ax { fill: var(--muted); font-size: 10px; font-family: "JetBrains Mono", monospace; }
  .val { fill: var(--text); font-size: 11px; font-family: "JetBrains Mono", monospace; }

  .day {
    display: grid; grid-template-columns: 70px 54px 64px 46px 34px 1fr 34px;
    align-items: center; gap: 10px; padding: 9px 0; font-size: .85rem;
    border-top: 1px dashed #1e1e20;
  }
  .day:first-of-type { border-top: none; }
  .day .n { color: var(--text); letter-spacing: 2px; }
  .day .dt { color: var(--muted); font-size: .72rem; }
  .day .cd { color: var(--red); font-weight: 600; }
  .day .r { color: var(--muted); font-size: .75rem; }
  .day .r.hot { color: var(--red); }
  .day .lo { color: var(--muted); text-align: right; }
  .bar { position: relative; height: 4px; background: #1a1a1c; }
  .bar i {
    position: absolute; top: 0; bottom: 0;
    background: linear-gradient(90deg, var(--red-dim), var(--red));
    box-shadow: 0 0 8px var(--red-glow);
  }

  .foot {
    display: flex; justify-content: space-between; font-size: .68rem;
    color: var(--muted); letter-spacing: 2px; margin-top: 8px;
  }

  @media (max-width: 640px) {
    .hero { grid-template-columns: 1fr; }
    .day { grid-template-columns: 58px 50px 40px 30px 1fr 30px; }
    .day .dt { display: none; }
    .search { flex-wrap: wrap; }
    .search .field { flex-basis: 100%; }
    .search button { flex: 1; padding: 10px; }
  }
</style>
</head>
<body>
<div class="wrap">

  <div class="top">
    <div class="brand">WX//SYS</div>
    <div class="live">LIVE FEED</div>
    <div id="clock">--:--:--</div>
  </div>

  <form class="search" method="get" action="/" id="search">
    <label class="field">
      <span class="prompt">&gt;</span>
      <input type="text" name="city" id="city" list="suggest" autocomplete="off"
             value="{{ query }}" placeholder="ENTER CITY  (e.g. Denver  or  Portland, Maine)">
      <datalist id="suggest"></datalist>
    </label>
    <button type="submit" class="primary">SCAN</button>
    <button type="button" id="locate">⌖ MY LOCATION</button>
  </form>
  <div class="status" id="status"></div>

  {% if error %}<div class="err">!! {{ error }}</div>{% endif %}

  <div class="hero">
    <div class="panel">
      <div class="tag">CURRENT CONDITIONS <span>{{ "%.2f"|format(lat|abs) }}{{ "N" if lat >= 0 else "S" }} {{ "%.2f"|format(lon|abs) }}{{ "W" if lon < 0 else "E" }}</span></div>
      <div class="temp">{{ c.temperature_2m | round | int }}<sup>°F</sup></div>
      <div class="cond"><b>[{{ short }}]</b>{{ text }}</div>
      <div class="sub">LOC: <em>{{ place | upper }}</em></div>
      <div class="sub">HI <em>{{ today.hi }}°</em> &nbsp;/&nbsp; LO <em>{{ today.lo }}°</em> &nbsp;/&nbsp; FEELS <em>{{ c.apparent_temperature | round | int }}°</em></div>
    </div>

    <div class="panel">
      <div class="tag">SENSOR READOUT <span>SYS.OK</span></div>
      <div class="readouts">
        <div class="ro"><div class="k">HUMIDITY</div><div class="v">{{ c.relative_humidity_2m }}<small>%</small></div>
          <div class="meter"><i style="width: {{ c.relative_humidity_2m }}%"></i></div></div>
        <div class="ro"><div class="k">CLOUD COVER</div><div class="v">{{ c.cloud_cover }}<small>%</small></div>
          <div class="meter"><i style="width: {{ c.cloud_cover }}%"></i></div></div>
        <div class="ro"><div class="k">WIND</div><div class="v">{{ c.wind_speed_10m | round | int }}<small>MPH {{ wind_dir }}</small></div>
          <div class="meter"><i style="width: {{ [c.wind_speed_10m * 2.5, 100] | min }}%"></i></div></div>
        <div class="ro"><div class="k">PRESSURE</div><div class="v">{{ pressure }}<small>inHg</small></div>
          <div class="meter"><i style="width: {{ [[(pressure - 29) / 2 * 100, 0] | max, 100] | min }}%"></i></div></div>
        <div class="ro"><div class="k">UV INDEX</div><div class="v">{{ uv | round(1) }}</div>
          <div class="meter"><i style="width: {{ [uv * 9, 100] | min }}%"></i></div></div>
        <div class="ro"><div class="k">SUN ▲ / ▼</div><div class="v" style="font-size:1rem">{{ sunrise }} <small>/</small> {{ sunset }}</div></div>
      </div>
    </div>
  </div>

  <div class="panel">
    <div class="tag">PRECIP RADAR <span id="radar-status">LOADING FEED...</span></div>
    <div id="radar"></div>
    <div class="radar-ctl">
      <button type="button" id="radar-play">❚❚ PAUSE</button>
      <input type="range" id="radar-slider" min="0" max="0" value="0">
      <div class="rt" id="radar-time">--:--</div>
    </div>
  </div>

  <div class="panel">
    <div class="tag">24H TEMPERATURE TRACE <span>RED BARS = PRECIP PROBABILITY</span></div>
    <svg viewBox="0 0 {{ chart.W }} {{ chart.H }}">
      <defs>
        <linearGradient id="fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#ff1f3d" stop-opacity=".35"/>
          <stop offset="100%" stop-color="#ff1f3d" stop-opacity="0"/>
        </linearGradient>
        <filter id="glow"><feGaussianBlur stdDeviation="2.5" result="b"/>
          <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
      </defs>
      {% for b in chart.bars %}
        <rect x="{{ b.x }}" y="{{ b.y }}" width="8" height="{{ b.h }}" fill="#8a1022" opacity=".7"/>
      {% endfor %}
      <line x1="20" x2="580" y1="{{ chart.H - 20 }}" y2="{{ chart.H - 20 }}" stroke="#2a0a0c"/>
      <polygon points="{{ chart.area }}" fill="url(#fill)"/>
      <polyline points="{{ chart.line }}" fill="none" stroke="#ff1f3d" stroke-width="2" filter="url(#glow)"/>
      {% for p in chart.points %}{% if p.show %}
        <circle cx="{{ p.x }}" cy="{{ p.y }}" r="3" fill="#050505" stroke="#ff1f3d" stroke-width="1.5"/>
        <text class="val" x="{{ p.x }}" y="{{ p.y - 9 }}" text-anchor="middle">{{ p.t }}°</text>
        <text class="ax" x="{{ p.x }}" y="{{ chart.H - 4 }}" text-anchor="middle">{{ p.l }}:00</text>
      {% endif %}{% endfor %}
    </svg>
  </div>

  <div class="panel">
    <div class="tag">7-DAY PROJECTION <span>LO · RANGE · HI</span></div>
    {% for dy in days %}
    <div class="day">
      <div class="n">{{ dy.name }}</div>
      <div class="dt">{{ dy.date }}</div>
      <div class="cd">{{ dy.code }}</div>
      <div class="r {{ 'hot' if dy.rain >= 50 }}">{{ dy.rain }}%</div>
      <div class="lo">{{ dy.lo }}°</div>
      <div class="bar"><i style="left: {{ dy.left }}%; width: {{ dy.width }}%"></i></div>
      <div class="hi">{{ dy.hi }}°</div>
    </div>
    {% endfor %}
  </div>

  <div class="foot">
    <div>LAST SYNC {{ updated }}</div>
    <div>SRC: OPEN-METEO</div>
    <div>REFRESH 600S</div>
  </div>
</div>

<script>
  function tick() {
    document.getElementById("clock").textContent =
      new Date().toLocaleTimeString("en-US", { hour12: false });
  }
  tick(); setInterval(tick, 1000);

  const form = document.getElementById("search");
  const input = document.getElementById("city");
  const list = document.getElementById("suggest");
  const status = document.getElementById("status");

  // ---- Autocomplete: ask Open-Meteo for matching places as you type ----
  let timer, options = [];
  input.addEventListener("input", () => {
    // Picking a suggestion from the dropdown submits right away
    if (options.includes(input.value)) { form.submit(); return; }

    clearTimeout(timer);
    const q = input.value.split(",")[0].trim();
    if (q.length < 2) return;
    timer = setTimeout(async () => {
      try {
        const res = await fetch("https://geocoding-api.open-meteo.com/v1/search?count=6&language=en&name="
                                + encodeURIComponent(q));
        const data = await res.json();
        options = (data.results || []).map(g =>
          [g.name, g.admin1, g.country].filter(Boolean).join(", "));
        list.innerHTML = "";
        options.forEach(o => {
          const opt = document.createElement("option");
          opt.value = o;
          list.appendChild(opt);
        });
      } catch (e) { /* suggestions are optional; ignore network hiccups */ }
    }, 250);
  });

  // ---- "My location" button: use the browser's geolocation ----
  document.getElementById("locate").addEventListener("click", () => {
    if (!navigator.geolocation) { status.textContent = "!! GEOLOCATION NOT SUPPORTED"; return; }
    status.textContent = "ACQUIRING POSITION...";
    navigator.geolocation.getCurrentPosition(
      pos => {
        const { latitude, longitude } = pos.coords;
        location.href = "/?lat=" + latitude.toFixed(4) + "&lon=" + longitude.toFixed(4);
      },
      err => { status.textContent = "!! POSITION UNAVAILABLE (" + err.message.toUpperCase() + ")"; },
      { timeout: 10000 }
    );
  });

  // ---- Radar: dark basemap + animated RainViewer precipitation frames ----
  (function radar() {
    const LAT = {{ lat }}, LON = {{ lon }}, TZ = {{ tz | tojson }};
    const FRAMES = 11;         // 5-minute frames to animate (max 11 = last 50 minutes)
    const SPEED = 600;         // ms per frame
    const statusEl = document.getElementById("radar-status");
    const slider = document.getElementById("radar-slider");
    const timeEl = document.getElementById("radar-time");
    const playBtn = document.getElementById("radar-play");

    const map = L.map("radar", { scrollWheelZoom: false, minZoom: 3, maxZoom: 11 })
                 .setView([LAT, LON], 7);

    // Base map without labels, then labels in their own pane ABOVE the radar
    const carto = "https://{s}.basemaps.cartocdn.com/{style}/{z}/{x}/{y}{r}.png";
    L.tileLayer(carto, {
      style: "dark_nolabels", subdomains: "abcd",
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
    }).addTo(map);
    map.createPane("labels");
    map.getPane("labels").style.zIndex = 450;
    map.getPane("labels").style.pointerEvents = "none";
    L.tileLayer(carto, { style: "dark_only_labels", subdomains: "abcd", pane: "labels" }).addTo(map);

    // Your location
    L.circleMarker([LAT, LON], {
      radius: 6, color: "#ff1f3d", weight: 2, fillColor: "#050505", fillOpacity: 1,
    }).addTo(map);

    let layers = [], labels = [], current = 0, timer = null;

    function show(i) {
      layers.forEach((l, j) => l.setOpacity(j === i ? 0.7 : 0));
      current = i;
      slider.value = i;
      timeEl.textContent = labels[i];
    }
    function step() {
      show((current + 1) % layers.length);
      // linger a little on the newest frame
      timer = setTimeout(step, current === layers.length - 1 ? SPEED * 3 : SPEED);
    }
    function play()  { clearTimeout(timer); timer = setTimeout(step, SPEED); playBtn.textContent = "❚❚ PAUSE"; }
    function pause() { clearTimeout(timer); timer = null; playBtn.textContent = "▶ PLAY"; }

    playBtn.addEventListener("click", () => (timer ? pause() : play()));
    slider.addEventListener("input", () => { pause(); show(+slider.value); });

    // NEXRAD composite from the Iowa Environmental Mesonet: free, no API key, US only.
    // The "-mXXm" layers are the same map XX minutes ago, in 5-minute steps (max 50).
    const IEM = "https://mesonet.agron.iastate.edu/cache/tile.py/1.0.0/nexrad-n0q-900913{ago}/{z}/{x}/{y}.png";
    for (let m = (FRAMES - 1) * 5; m >= 0; m -= 5) {
      const ago = m ? "-m" + String(m).padStart(2, "0") + "m" : "";
      layers.push(L.tileLayer(IEM, {
        ago, opacity: 0,
        attribution: 'Radar: <a href="https://mesonet.agron.iastate.edu/">Iowa Env. Mesonet</a> / NWS NEXRAD',
      }).addTo(map));
      labels.push(m ? "-" + m + " MIN" : "NOW");
    }
    slider.max = layers.length - 1;
    show(layers.length - 1);
    layers[layers.length - 1].on("tileerror", () => { statusEl.textContent = "!! RADAR FEED OFFLINE"; });

    // Rough US bounding box (incl. Alaska, Hawaii, Puerto Rico); NEXRAD has no data elsewhere
    const inUS = LAT > 17 && LAT < 72 && LON > -180 && LON < -64;
    statusEl.textContent = inUS ? "NEXRAD · LAST " + (FRAMES - 1) * 5 + " MIN" : "NEXRAD COVERS THE US ONLY";
    play();
  })();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    # Local testing: python app.py  ->  http://localhost:5050
    # When hosted, gunicorn runs the app instead (see README.md)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5050)))
