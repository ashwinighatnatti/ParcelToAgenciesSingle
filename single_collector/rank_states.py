"""Rank the Tier 1 (easiest) states: one collector per parcel, and few portals cover most parcels.

Run from the project folder:  python -m single_collector.rank_states

How a state is ranked (all signals are printed, nothing is hidden in a score):
  1. Gate: the state must be marked is_single_collector in jurisdictions_config.json, so a parcel maps directly to one
     collecting agency (the county treasurer / tax collector) and not to a city, school district or private firm.
  2. Confidence of that classification: "high" states first, "medium" states need Operations to validate them.
  3. Portals to cover: how many of the state's largest counties hold 80% of its housing units. Each county runs its own
     portal, so fewer counties means fewer portals to script. Housing units are the proxy for parcels.
"""
import csv
import json
from pathlib import Path

import requests

import agencies
from single_collector import jurisdictions
from single_collector.portals import PORTALS

COUNTIES_URL = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer/67/query"
COVERAGE = 0.80
# Counties we tried in this project whose portal blocked automation (see single_collector/README.md)
BLOCKED = {"06075": "San Francisco CA: Cloudflare bot challenge", "12095": "Orange FL: Cloudflare bot challenge"}
OUTPUT = Path("output")


def load_counties():
    """All US counties with housing units and population, from Census TIGERweb (no API key)."""
    rows, offset = [], 0
    while True:
        params = {"where": "1=1", "outFields": "STATE,COUNTY,NAME,POP100,HU100", "returnGeometry": "false",
                  "f": "json", "resultOffset": offset, "resultRecordCount": 1000}
        response = requests.get(COUNTIES_URL, params=params, timeout=120)
        response.raise_for_status()
        result = response.json()
        rows += [f["attributes"] for f in result["features"]]
        offset += len(result["features"])
        if not result.get("exceededTransferLimit"):
            return rows


def counties_covering(counties, share=COVERAGE):
    """The state's largest counties (by housing units) needed to reach `share` of all its housing units."""
    ordered = sorted(counties, key=lambda c: c["HU100"], reverse=True)
    total, running, needed = sum(c["HU100"] for c in ordered), 0, []
    for county in ordered:
        needed.append(county)
        running += county["HU100"]
        if running >= share * total:
            return needed


def sample_evidence(sample, state):
    """What Operations' sample file shows for this state (it is a small, biased sample, so this is context only)."""
    rows = sample[sample.state == state]
    if rows.empty:
        return {"sample_parcels": 0, "sample_agencies_per_parcel": None}
    per_parcel = rows.groupby("parcel_number").agency_name.nunique()
    return {"sample_parcels": len(per_parcel), "sample_agencies_per_parcel": round(per_parcel.mean(), 1)}


def portal_tests(state_fips):
    """Counties of this state we already ran a browser script against, and counties that blocked us."""
    worked = [code for code in PORTALS if code.startswith(state_fips)]
    blocked = [reason for code, reason in BLOCKED.items() if code.startswith(state_fips)]
    return {"scripted_counties": worked, "blocked": blocked}


def rank_states():
    counties = load_counties()
    sample = agencies.load()
    ranked = []
    for state, j in jurisdictions.load().items():
        if not j["is_single_collector"]:
            continue
        in_state = [c for c in counties if c["STATE"] == j["fips"]]
        needed = counties_covering(in_state)
        ranked.append({
            "state": state, "name": j["name"], "confidence": j["confidence"],
            "collector_level": j["primary_collector_level"],
            "counties": len(in_state), "portals_for_80pct_of_homes": len(needed),
            "largest_counties": [c["NAME"] for c in needed[:3]],
            **sample_evidence(sample, state), **portal_tests(j["fips"]), "notes": j["notes"],
        })
    ranked.sort(key=lambda r: (r["confidence"] != "high", r["portals_for_80pct_of_homes"], r["counties"]))
    for position, row in enumerate(ranked, start=1):
        row["rank"] = position
    return ranked


def show(ranked):
    for label, confidence in (("Tier 1A: high confidence", "high"), ("Tier 1B: medium confidence, validate first", "medium")):
        print(f"\n{label}")
        print(f"{'#':>3} {'State':<22}{'Counties':>9}{'Portals for 80%':>17}  Largest counties")
        for r in (r for r in ranked if r["confidence"] == confidence):
            print(f"{r['rank']:>3} {r['name']:<22}{r['counties']:>9}{r['portals_for_80pct_of_homes']:>17}  {', '.join(r['largest_counties'])}")


if __name__ == "__main__":
    ranked = rank_states()
    show(ranked)
    OUTPUT.mkdir(exist_ok=True)
    (OUTPUT / "tier1_states.json").write_text(json.dumps(ranked, indent=2), encoding="utf-8")
    with open(OUTPUT / "tier1_states.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(ranked[0]))
        writer.writeheader()
        writer.writerows({k: "; ".join(v) if isinstance(v, list) else v for k, v in r.items()} for r in ranked)
    print(f"\nWrote {OUTPUT / 'tier1_states.json'} and {OUTPUT / 'tier1_states.csv'}")
