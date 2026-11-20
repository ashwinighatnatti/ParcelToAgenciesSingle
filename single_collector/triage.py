"""Triage a batch: which addresses will be easy, medium or hard for the pipeline? This is NOT a search run.

It uses only free, fast sources and makes no Claude call, so it costs $0:
  1. the Census batch geocoder (one request for the whole file) says whether each address is real and in which county;
  2. the county either has a scripted adapter (portals/) or it does not;
  3. the state is one where a single office collects the tax, or one with several collectors (jurisdictions_config.json).

    triage(queries) -> {"rows": [...], "summary": {...}}      queries as in run.py: dicts with address, parcel_id
"""
import time

from single_collector import census, jurisdictions
from single_collector.portals import PORTALS

# What a full run is expected to cost per row, from runs already made (estimates, not guarantees):
ADAPTER_COST = 0.015  # Maricopa AZ $0.012 and King WA $0.015: county GIS plus one statement page, one small Claude read
WEB_COST = 0.85      # no adapter: Claude web research capped at 2 searches / 4 pages (Mohave AZ re-run $0.849; before the cap $0.86 to $1.99)
LEVELS = {
    "simple": ("Easily accessible", "Census geocoder, then the county's own parcel service and treasurer statement page (a scripted adapter). No web research.", ADAPTER_COST),
    "medium": ("Few steps", "Census geocoder, then Claude web research on the county's sites (2 searches, 4 pages). One county-level office is expected to collect the tax.", WEB_COST),
    "complex": ("Complex", "Several offices may collect the tax in this state, or the address could not be matched; expect web research and a manual check.", WEB_COST),
}


# why a row got its level: cause -> (level, what it means). The summary on the Triage tab counts rows per cause.
CAUSES = {
    "adapter": ("simple", "The county has a scripted adapter (county GIS parcel service and treasurer statement page)"),
    "single_collector_state": ("medium", "No adapter, but the state has one county-level collector, so web research should find one agency"),
    "several_collectors_state": ("complex", "No adapter, and the state has several collectors (towns, boroughs, cities, districts)"),
    "address_not_matched": ("complex", "The Census geocoder could not match the address, so it cannot be validated or placed in a county"),
    "state_unknown": ("complex", "The state could not be identified"),
}


def classify(query, geo):
    """(cause, reason, state) for one row. geo is the Census match for the address, or None. The cause gives the level (CAUSES)."""
    address = query.get("address")
    part = census.ADDRESS.match(address) if address else None
    state = part["state"].upper() if part else (query.get("state") or "").upper()
    if address and geo is None:
        return "address_not_matched", CAUSES["address_not_matched"][1] + ".", state
    county_code = geo["county_code"] if geo else None
    if county_code in PORTALS:
        return "adapter", f"The county ({county_code}) has a scripted adapter: parcel and agency come from the county's own records.", state
    if state not in jurisdictions.load():
        return "state_unknown", "The state could not be identified.", state
    state_info = jurisdictions.get(state)
    if state_info["is_single_collector"]:
        return "single_collector_state", f"No adapter for this county, but {state_info['name']} is a state where one county-level office collects the tax.", state
    return "several_collectors_state", f"No adapter for this county, and {state_info['name']} has several collectors: {state_info['notes']}", state


def triage(queries):
    started = time.time()
    addresses = [q["address"] for q in queries if q.get("address")]
    geocoded = census.geocode_batch(addresses) if addresses else {}
    rows = []
    for number, query in enumerate(queries, start=1):
        geo = geocoded.get(query.get("address"))
        cause, reason, state = classify(query, geo)
        level = CAUSES[cause][0]
        label, route, estimate = LEVELS[level]
        if cause == "address_not_matched":
            estimate = 0.0  # a full run stops at the address check (county_needed) without calling Claude
        rows.append({"row": number, "address": query.get("address") or "", "parcel_id": query.get("parcel_id") or "",
                     "state": state, "level": level, "cause": cause, "meaning": label, "reason": reason, "route": route,
                     "county_code": geo["county_code"] if geo else "", "matched_address": geo["matched_address"] if geo else "",
                     "full_run_estimate_usd": estimate})
    total = len(rows) or 1
    summary = {level: {"rows": sum(r["level"] == level for r in rows), "share_pct": round(100 * sum(r["level"] == level for r in rows) / total),
                       "full_run_estimate_usd": round(sum(r["full_run_estimate_usd"] for r in rows if r["level"] == level), 2)}
               for level in LEVELS}
    summary["total"] = {"rows": len(rows), "share_pct": 100, "full_run_estimate_usd": round(sum(r["full_run_estimate_usd"] for r in rows), 2)}
    summary["causes"] = [{"cause": text, "level": level, "rows": sum(r["cause"] == key for r in rows),
                          "full_run_estimate_usd": round(sum(r["full_run_estimate_usd"] for r in rows if r["cause"] == key), 2)}
                         for key, (level, text) in CAUSES.items() if any(r["cause"] == key for r in rows)]
    summary["by_state"] = [{"state": state or "?", "rows": sum(r["state"] == state for r in rows),
                            **{level: sum(r["state"] == state and r["level"] == level for r in rows) for level in LEVELS}}
                           for state in sorted({r["state"] for r in rows})]
    summary["notes"] = {"with_parcel_id": sum(bool(r["parcel_id"]) for r in rows),
                        "unmatched_with_parcel_id": sum(r["cause"] == "address_not_matched" and bool(r["parcel_id"]) for r in rows),
                        "distinct_counties": len({r["county_code"] for r in rows if r["county_code"]}),
                        "adapter_cost_each": ADAPTER_COST, "web_cost_each": WEB_COST}
    summary["triage_run"] = {"claude_calls": 0, "tokens": 0, "cost_usd": 0.0, "census_batch_requests": 1 if addresses else 0,
                             "seconds": round(time.time() - started, 1)}
    return {"rows": rows, "summary": summary}
