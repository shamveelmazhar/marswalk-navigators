# Marswalk Navigators

A route planner for the first astronauts to walk on Mars.

**Live demo:** https://marswalk-navigators.vercel.app/

Our team is building this for the 2026 NASA Space Apps Challenge, "Interplanetary Survival Guide: Martian Map". The idea is simple. Before a crew steps outside on Mars, they need to know which way to walk, what the ground is like, how much radiation they'll pick up, and whether their support rover can follow them. We pull real NASA data together into one map that answers those questions.

We're starting at Mount Sharp in Gale Crater, where the Curiosity rover studied the "boxwork" ridges in 2025. These are low, criss-crossing walls of rock left behind by groundwater long ago, and they're the example NASA gives in the challenge itself.

## What we're working on

- **Robotics:** a path planner that finds safe routes for an astronaut and a support rover over real terrain, avoiding steep slopes and rough ground. Curiosity's actual route gives us something to check it against.
- **Aerospace:** planning a Marswalk around its time, energy and radiation budgets, using Curiosity's own radiation measurements from the surface.
- **FEA:** Curiosity's aluminum wheels were punctured by sharp rocks on this mountain. We turn the worst terrain along a route (steepest slopes, tallest ridges) into load cases and check a rover wheel or suspension part against them.

## Getting the data

You'll need Python 3.10 or newer.

```bash
pip install -r requirements.txt
python -m marswalk.build
```

That downloads everything for the Mount Sharp site into `data/gale-boxwork/` in about a minute. Add `--skip-radiation` if you're in a hurry and don't need the radiation readings yet. The data folder isn't checked into git, so everyone builds their own copy.

Here's what you get:

| File | What it is |
|---|---|
| `elevation_hirise_2m.tif` | Height of the ground every 2 meters, from the HiRISE camera on Mars Reconnaissance Orbiter |
| `ortho_hirise_1m.tif` | A black-and-white photo of the area at 1 meter per pixel, lined up with the height map |
| `slope_deg_2m.tif`, `slope_deg_10m.tif` | How steep the ground is, in degrees. The 10 m version is smoothed to the scale a person or rover feels |
| `roughness_m_10m.tif` | How bumpy the ground is over a 10 m patch, in meters. High values mean ridges, ledges and rocks |
| `themis_night_ir_100m.tif`, `themis_day_ir_100m.tif` | Infrared views from Mars Odyssey over a wider area. At night, solid rock stays warmer than sand and dust, so bright means firm ground |
| `curiosity_traverse.geojson`, `curiosity_waypoints.geojson` | The path Curiosity actually drove here, and every stop it made, with its tilt at each one |
| `rad_dose_rate_sols_4489-4612.csv` | About 10,800 radiation readings from Curiosity's RAD instrument. Detector E behaves like human tissue, so it's the one to use for crew dose |
| `raw_images_sols_4530-4600.csv` | Links to Curiosity's photos from the boxwork campaign, each tagged with where the rover was |

All the maps share one Mars map grid (equirectangular, Mars radius 3,396,190 m), so they stack without any reprojecting.

A few numbers to give a feel for the place: half the area is gentler than 11°, but about a third of it is steeper than 15°, so route choice really matters. The radiation dose works out to about 0.16 milligray per sol.

## The website

The `web/` folder holds the site: a full-screen look at Mount Sharp, a layered map of the boxwork where you can plan a walk, and live budgets, a written mission briefing and wheel load cases for whatever route you pick. To run it:

```
python -m http.server 8000 --directory web
```

Then open http://localhost:8000. The [web README](web/README.md) explains each part and how to rebuild its data.

## Code layout

- `marswalk/site.py`: the site boundaries, the data sources, and conversion between latitude/longitude and map coordinates
- `marswalk/rasters.py`: downloads just the piece of a big Mars map we need
- `marswalk/terrain.py`: slope and roughness
- `marswalk/radiation.py`: reads dose rates out of the RAD files
- `marswalk/rover.py`: Curiosity's path, stops and photos
- `marswalk/build.py`: runs everything above in order
- `marswalk/planner.py`: the A* route planner, with separate slope and roughness limits for the astronaut and the rover
- `marswalk/budgets.py`: walking time, energy, oxygen and radiation for the astronaut, driving energy for the rover, and the wheel load cases
- `marswalk/assistant.py`: writes the mission briefing for a route from those numbers
- `marswalk/api.py`: a small FastAPI service that serves all of the above
- `web/`: the website, with its own [README](web/README.md)

Run the tests with `pytest`.

## The route API

The planner, budgets and briefing can also run as a web service:

```bash
uvicorn marswalk.api:app --port 8001
```

Then open http://localhost:8001/docs to try it. The main calls are `/route`, `/budget` and `/briefing`, each taking a start and end latitude and longitude. The API only needs the small terrain grid in `web/data/`, so you don't have to download the full data set first. The website works without it, because it can plan routes in the browser too.

## Where the data comes from

All of it is public NASA and USGS data:

- HiRISE elevation model DTEEC_019698_1750_019988_1750_U01 and its orthoimage, via the [USGS Astrogeology STAC catalog](https://stac.astrogeology.usgs.gov/)
- THEMIS infrared mosaics (MC-23 Aeolis quadrangle), also via USGS
- Curiosity's traverse and waypoints from NASA's [mission map](https://mars.nasa.gov/maps/location/?mission=Curiosity)
- Curiosity raw images from the [NASA raw image site](https://mars.nasa.gov/msl/multimedia/raw-images/)
- RAD radiation data from the [Planetary Data System](https://pds-ppi.igpp.ucla.edu/data/MSL-M-RAD-3-RDR-V1.0/)

## Tools we used

We used AI tools to help write parts of the code and process the data.
