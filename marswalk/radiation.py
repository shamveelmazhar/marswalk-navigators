"""Radiation on the surface, from Curiosity's Radiation Assessment Detector (RAD).

RAD files are big (around 70 MB a sol) because they hold full particle
histograms. We only want the total dose rate from each observation, so we read
the label file to find exactly where those numbers sit, then ask the server for
just those bytes.

Detector E is made of a plastic that absorbs radiation much like human tissue,
so it's the best stand-in for what an astronaut would receive.
"""
import re
import statistics
from collections import defaultdict

import requests

# One RAD observation lasts about 16 minutes, and a sol is about 24.66 hours.
HOURS_PER_SOL = 24.66

_POINTER = re.compile(
    r'\^OBS(\d+)_TOT_DOSE_B_ELEMENT\s*=\s*\("[^"]+",\s*(\d+)\s*<BYTES>\)'
)
_DOSE = re.compile(r"\[DOSIMETRY_TOTAL_DOSE_([BE]): (\d+)\]\s+([-\d.eE+]+)")


def dose_pointers(label_text):
    """Byte offsets of the total-dose values in a RAD data file, keyed by observation number."""
    return {int(obs): int(offset) for obs, offset in _POINTER.findall(label_text)}


def parse_doses(text):
    """Pull total dose rates (microgray per hour) out of RAD text, as {observation: {"B": .., "E": ..}}."""
    doses = defaultdict(dict)
    for detector, obs, value in _DOSE.findall(text):
        doses[int(obs)][detector] = float(value)
    return dict(doses)


def fetch_sol_doses(folder_url, file_stem, session=None, batch=40):
    """Download the dose rates for one RAD file (one sol) using HTTP byte ranges."""
    http = session or requests.Session()
    label = http.get(folder_url + file_stem + ".LBL", timeout=120).text
    offsets = sorted(dose_pointers(label).values())
    # The dose value sits a few bytes either side of the pointer, so grab a little extra.
    ranges = [f"{max(0, o - 60)}-{o + 80}" for o in offsets]
    text = ""
    for i in range(0, len(ranges), batch):
        headers = {"Range": "bytes=" + ",".join(ranges[i : i + batch])}
        text += http.get(folder_url + file_stem + ".TXT", headers=headers, timeout=120).text
    return parse_doses(text)


def list_rad_files(folder_url, session=None):
    """Names (without extension) of the RAD data files in a folder, with the sol each one starts on."""
    http = session or requests.Session()
    html = http.get(folder_url, timeout=60).text
    stems = sorted(set(re.findall(r"(RAD_RDR_\d{4}_\d{3}_\d{2}_\d{2}_(\d+)_V\d+)\.TXT", html)))
    return [(stem, int(sol)) for stem, sol in stems]


def daily_dose_mgy(rows, detector="E", min_rate=0.5):
    """Average dose per sol in milligray, from rows of (sol, observation, B, E).

    Very low readings usually mean the instrument was warming up or interrupted,
    so anything under `min_rate` microgray per hour is left out.
    """
    column = 2 if detector == "B" else 3
    per_sol = defaultdict(list)
    for row in rows:
        rate = row[column]
        if rate is not None and rate >= min_rate:
            per_sol[row[0]].append(rate)
    return {sol: statistics.mean(r) * HOURS_PER_SOL / 1000 for sol, r in sorted(per_sol.items())}
