"""Dynamic tax agency search. Start from a parcel address, a parcel id, or both. Three stages, in order:
  1. validate_address       2. find_validate_parcel       3. find_validate_agency
(see stages.py). Results go to output/manifest.json (or --manifest PATH) and the bill PDFs to downloads/.

Usage (from the project folder):
  python -m single_collector.run "400 Broad St, Seattle, WA 98109"                       # by address
  python -m single_collector.run --parcel 1985200495 --state WA --county King            # by parcel id
  python -m single_collector.run "400 Broad St, Seattle, WA 98109" --parcel 1985200495   # both, cross-checked
  python -m single_collector.run --file searches.csv                                     # columns: address,parcel_id,state,county
"""
import argparse
import csv
import json
from pathlib import Path

from single_collector import census, confidence, cost, stages, trace

BATCH_MIN = 10  # at or above this many addresses, geocode them with one /addressbatch call
OUTPUT = Path("output")
PARCEL_PROBLEMS = {"not_found": "parcel_not_found", "ambiguous": "parcel_ambiguous", "county_needed": "county_needed",
                   "county_unknown": "county_unknown", "not_searched": "invalid_address"}


def process(query, geocoded=stages.NOT_GEOCODED):
    """Run the three stages for one search. query: dict with any of address, parcel_id, state, county."""
    query = {key: (query.get(key) or "").strip() or None for key in ("address", "parcel_id", "state", "county")}
    if not (query["address"] or query["parcel_id"]):
        return {"status": "error", "query": query, "reason": "Give a parcel address, a parcel id, or both."}
    mode = "both" if query["address"] and query["parcel_id"] else "address" if query["address"] else "parcel_id"

    start = cost.mark()
    trace.start()
    trace.stage("validate_address")
    address_check = stages.validate_address(query, geocoded)
    after_address = cost.mark()
    trace.stage("find_validate_parcel")
    parcel = stages.find_validate_parcel(query, address_check)
    if address_check["valid"] is None and parcel["status"] == "matched":  # parcel search: validate the parcel's own address
        if parcel.get("parcel_address"):
            address_check = stages.validate_address({"address": parcel["full_address"]})
        else:
            address_check = {"checked": False, "valid": None, "flags": [],
                             "reason": "The county has no street address on record for this parcel (for example vacant land)."}
    after_parcel = cost.mark()
    trace.stage("find_validate_agency")
    agency, tax_bill = stages.find_validate_agency(query, address_check, parcel)
    spent = cost.combine({"validate_address": cost.between(start, after_address),
                          "find_validate_parcel": cost.between(after_address, after_parcel),
                          "find_validate_agency": cost.between(after_parcel, cost.mark())})

    if address_check["valid"] is False and not query["parcel_id"]:
        status = "invalid_address"
    elif parcel["status"] != "matched":
        status = PARCEL_PROBLEMS[parcel["status"]]
    elif agency["status"] != "found":
        status = "agency_not_found"
    elif agency["separate_collectors"]:
        status = "exception_multi_agency"
    elif parcel["verified"] and agency["validated"]:
        status = "success"  # parcel found in the county's records and the agency read from the county's statement
    else:
        status = "found_unverified"  # found, but from web research or a third-party source

    score = confidence.score(address_check, parcel, agency)
    trace.add("Check (no outside call)", "Final status and confidence score", "the three stages above",
              f"status {status}; confidence {score['score']} ({score['level']}): {score['summary']}")
    parcel_out = {key: value for key, value in parcel.items() if key not in ("research", "flags")}
    return {
        "status": status,
        "reason": address_check.get("reason") if status == "invalid_address" else parcel.get("reason"),
        "query": {**query, "search_mode": mode},
        "address_validation": address_check,
        "parcel": parcel_out,
        "agency": agency,
        "tax_bill": tax_bill,
        "flags": address_check.get("flags", []) + parcel.get("flags", []),
        "confidence": score,
        "cost": spent,
        "audit": trace.report(),
    }


def read_queries(args):
    if args.file:
        return list(csv.DictReader(open(args.file, newline="", encoding="utf-8-sig")))
    if args.addresses:
        return [{"address": a, "parcel_id": args.parcel, "state": args.state, "county": args.county} for a in args.addresses]
    return [{"parcel_id": args.parcel, "state": args.state, "county": args.county}]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Find the tax collecting agency from a parcel address and/or parcel id.")
    parser.add_argument("addresses", nargs="*", help='"street, city, ST zip"')
    parser.add_argument("--parcel", help="parcel id (needs --state and --county if no address is given)")
    parser.add_argument("--state", help="2-letter state")
    parser.add_argument("--county", help="county name, with or without the word County")
    parser.add_argument("--file", help="CSV with columns address,parcel_id,state,county")
    parser.add_argument("--manifest", default=str(OUTPUT / "manifest.json"), help="where to write the JSON results")
    args = parser.parse_args()
    queries = read_queries(args)

    addresses = [q["address"] for q in queries if q.get("address")]
    batch = census.geocode_batch(addresses) if len(addresses) >= BATCH_MIN else {}
    manifest = []
    for q in queries:
        try:
            manifest.append(process(q, batch.get(q.get("address"), stages.NOT_GEOCODED)))
        except Exception as error:  # one bad search must not lose the rest
            manifest.append({"status": "error", "query": q, "reason": f"{type(error).__name__}: {error}"})
    Path(args.manifest).parent.mkdir(parents=True, exist_ok=True)
    Path(args.manifest).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
