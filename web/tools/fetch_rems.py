"""Fetch Curiosity's REMS daily weather for the boxwork sols and write it for the site.

The numbers come from the REMS team at Centro de Astrobiología (CAB, Madrid),
through the public feed that NASA's Mars weather page uses. It gives one row
per sol: daily minimum and maximum air temperature, minimum and maximum ground
temperature, pressure, UV index and sky opacity. Humidity and wind are in the
feed too, but REMS has not reported them for years, so they come back empty.

    python web/tools/fetch_rems.py                       # sols 4489 to 4612
    python web/tools/fetch_rems.py --first 4489 --last 4612

Writes web/data/rems_weather_sols_<first>-<last>.csv (the raw daily rows)
and web/data/weather.json (what the page draws). CAB asks that this feed be
used for outreach; the science-grade REMS data lives in the PDS Atmospheres node.
"""
import argparse
import csv
import json
import statistics
import urllib.request
from pathlib import Path

FEED = "https://mars.nasa.gov/rss/api/?feed=weather&category=msl&feedtype=json"
OUT = Path(__file__).resolve().parents[1] / "data"
FIELDS = ["sol", "terrestrial_date", "ls", "min_temp", "max_temp", "min_gts_temp", "max_gts_temp",
          "pressure", "local_uv_irradiance_index", "atmo_opacity", "abs_humidity", "wind_speed",
          "sunrise", "sunset"]


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--first", type=int, default=4489)
    ap.add_argument("--last", type=int, default=4612)
    ap.add_argument("--feed", help="read a saved copy of the feed instead of downloading it")
    args = ap.parse_args()

    if args.feed:
        raw = json.load(open(args.feed))
    else:
        with urllib.request.urlopen(FEED, timeout=60) as r:
            raw = json.load(r)
    rows = [s for s in raw["soles"] if args.first <= int(s["sol"]) <= args.last]
    rows.sort(key=lambda s: int(s["sol"]))
    if not rows:
        raise SystemExit("The feed has no rows for those sols.")

    csv_path = OUT / f"rems_weather_sols_{args.first}-{args.last}.csv"
    with open(csv_path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["sol", "earth_date", "ls_deg", "air_min_C", "air_max_C", "ground_min_C", "ground_max_C",
                    "pressure_Pa", "uv_index", "sky", "abs_humidity", "wind_speed", "sunrise", "sunset"])
        for s in rows:
            w.writerow(["" if s[f] == "--" else s[f] for f in FIELDS])

    keep = ["min_temp", "max_temp", "min_gts_temp", "max_gts_temp", "pressure"]
    sols = [s for s in rows if all(num(s[k]) is not None for k in keep)]
    series = [{
        "sol": int(s["sol"]), "date": s["terrestrial_date"], "ls": int(s["ls"]),
        "airMin": num(s["min_temp"]), "airMax": num(s["max_temp"]),
        "groundMin": num(s["min_gts_temp"]), "groundMax": num(s["max_gts_temp"]),
        "pressurePa": num(s["pressure"]), "uv": s["local_uv_irradiance_index"], "sky": s["atmo_opacity"],
    } for s in sols]
    mean = lambda k: round(statistics.mean(x[k] for x in series), 1)
    out = {
        "source": "REMS on Curiosity, Centro de Astrobiología (CAB) daily summaries via NASA's Mars weather feed",
        "sols": [series[0]["sol"], series[-1]["sol"]],
        "count": len(series),
        "mean": {k: mean(k) for k in ["airMin", "airMax", "groundMin", "groundMax", "pressurePa"]},
        "range": {
            "air": [min(x["airMin"] for x in series), max(x["airMax"] for x in series)],
            "ground": [min(x["groundMin"] for x in series), max(x["groundMax"] for x in series)],
            "pressurePa": [min(x["pressurePa"] for x in series), max(x["pressurePa"] for x in series)],
        },
        "uv": sorted({x["uv"] for x in series}),
        "sky": sorted({x["sky"] for x in series}),
        "series": series,
    }
    json.dump(out, open(OUT / "weather.json", "w"), separators=(",", ":"))
    print(f"{len(rows)} sols in the feed, {len(series)} complete; wrote {csv_path.name} and weather.json")
    print(json.dumps({k: out[k] for k in ["sols", "count", "mean", "range", "uv", "sky"]}, indent=1))


if __name__ == "__main__":
    main()
