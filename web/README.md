# The Marswalk Navigators website

This folder is the front end of our project: a single page that opens on Mount Sharp and then walks you through the field map, the route planner, the mission budgets and the rover load cases. It's plain HTML, CSS and JavaScript with no build step, so anyone on the team can open it and change it.

## Running it

The page loads its data with `fetch`, so it has to be served over http rather than opened as a file. From the repository root:

```
python -m http.server 8000 --directory web
```

Then open http://localhost:8000.

## What's on the page

1. **Mount Sharp.** A full-screen opening with four chapters (the mountain, the boxwork ridges, radiation and the rover). The arrows on the right, the tabs, or a swipe on a phone step through them. Each chapter has its own strip of numbers taken straight from our data.
2. **Field map.** A Leaflet map with the HiRISE photo, shaded terrain, slope, a go / caution / no-go hazard layer, THEMIS night infrared and Curiosity's radiation readings. Click two points and the page plans a route for an astronaut and for the support rover, with a height profile. Below the map are eight of Curiosity's real stops from the 2025 boxwork campaign, each with the rover's own photos.
3. **Route planning.** How the planner works and how much of the area falls into each hazard class. It also runs Curiosity's actual path through the same rules as a sanity check.
4. **Mission budgets.** Walking time, distance, energy, oxygen and radiation dose for the astronaut, and distance, energy and time for the rover. These update with whatever route is on the map.
5. **Rover load cases.** The worst slope and roughness on the rover's route turned into five load cases for one wheel, ready to apply in Ansys or SolidWorks. The rover numbers can be edited, and the table downloads as a CSV.
6. **Data and credits.**

## Where the data comes from

Everything in `assets/layers/` and `data/` is made by one script from the full-size files that `python -m marswalk.build` downloads:

```
python web/tools/build_web_data.py --data data/gale-boxwork
```

It shrinks the 15 to 20 MB rasters into light WebP images, writes a 20 m terrain grid (`data/grid.bin`) for the in-browser planner, picks the science stops and their photos, and works out the headline numbers. The output is small (a few megabytes) and is checked in, so the site works without rebuilding anything.

The four photographs in `assets/img/` are public-domain NASA images (PIA19912, PIA26680, PIA21710 and PIA19142). Rover photos at the stops are loaded straight from NASA's raw image server. Leaflet 1.9.4 is in `vendor/` so the map also works offline.

## Hooking up the team's planner

By default, routes are planned in the browser with an A* search over the 20 m grid. When the FastAPI route planner is running, add `?api=http://localhost:8001` (or wherever it lives) to the page address and the map will ask it first:

```
GET {api}/route?start_lat=..&start_lon=..&end_lat=..&end_lon=..&agent=astronaut|rover
```

It can answer with a GeoJSON LineString or with `{"path": [[lat, lon], ...]}`. A 4xx answer with `{"detail": "..."}` is shown to the user as the reason there's no route. If the API doesn't answer, the browser planner takes over quietly. See `js/api.js`.

Once the API has a public address, put it in `config.js` (`window.MARSWALK_API = "https://..."`) so every visitor uses it without needing the `?api=` part.

## Putting it online

The site is static, so any static host works. On Vercel, import the repository, set the Root Directory to `web`, choose "Other" as the framework, and leave the build command and output directory empty. Every push to `main` then redeploys it.

The API can run on Render as a Python web service from the repository root, with `pip install -r requirements-api.txt` as the build command and `uvicorn marswalk.api:app --host 0.0.0.0 --port $PORT` as the start command. It reads the terrain grid from `web/data/grid.bin`, so nothing has to be downloaded first, and CORS is already open to any site.

## Files

- `index.html`: the page.
- `config.js`: the address of the team's planner API, if it's online.
- `css/style.css`: all styling, including the phone layout.
- `js/main.js`: wires everything together.
- `js/hero.js`: the opening chapters.
- `js/map.js`: map layers, legend, stops and route lines.
- `js/terrain.js`: the terrain grid and the A* planner.
- `js/physics.js`: walking and driving budgets and the wheel load cases. Every assumption is a named constant at the top.
- `js/charts.js`: the small line charts.
- `js/api.js`: the optional link to the team's planner.
- `tools/build_web_data.py`: rebuilds the data files.
