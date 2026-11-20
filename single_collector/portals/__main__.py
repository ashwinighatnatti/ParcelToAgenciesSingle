"""Test one county adapter on its own (no Census, no Claude): parcel search plus the statement PDF.
  python -m single_collector.portals 04013 --parcel 118-50-094
  python -m single_collector.portals 53033 --street "400 BROAD ST" --zip 98109
Prints one JSON line. The PDF is saved under downloads/portal_tests/."""
import argparse
import json
from pathlib import Path

from single_collector import stages
from single_collector.portals import PORTALS, capture_statement

parser = argparse.ArgumentParser()
parser.add_argument("county_code")
parser.add_argument("--parcel")
parser.add_argument("--street")
parser.add_argument("--zip")
args = parser.parse_args()
adapter = PORTALS[args.county_code]

if args.parcel:
    rows = adapter.search_by_parcel(args.parcel)
else:
    rows = [r for r in adapter.rows_on_street(stages.core_word(args.street), args.zip) if stages.same_house(r["parcel_address"], args.street)]
if len(rows) != 1:
    print(json.dumps({"parcel_id": None, "matches": rows[:10]}))
else:
    captured = capture_statement(adapter, rows[0]["parcel_id"])
    path = Path("downloads/portal_tests") / f"{args.county_code}_{rows[0]['parcel_id']}_{captured['tax_year']}.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(captured["pdf"])
    print(json.dumps({**rows[0], "tax_year": captured["tax_year"], "file_path": str(path), "page_url": captured["page_url"]}))
