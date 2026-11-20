"""Claude's two jobs in the pipeline. Both return a dict with every key present, so callers never hit a KeyError.

research_property: the county has no adapter, so Claude searches the web for the parcel, its address and the agency.
read_statement:    an adapter opened the county's statement page, so Claude reads that page to identify the agency.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # reuse agent.py from the parent folder
from agent import ask
from single_collector import trace

# max_uses caps the search loop: every search re-reads the whole growing context, so cost and time grow quickly with it
MAX_SEARCHES, MAX_FETCHES = 2, 4  # reviewed on 3295 Foothill Plz (6 searches cost $1.99 and still did not reach the county lookup)
WEB_TOOLS = [{"type": "web_search_20260209", "name": "web_search", "max_uses": MAX_SEARCHES},
             {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": MAX_FETCHES}]
RESEARCH_KEYS = {"parcel_id": None, "parcel_id_source": None, "parcel_address": None, "agency_name": None,
                 "payment_address": None, "portal_url": None, "separate_collectors": [], "levying_bodies": [],
                 "tax_year": None, "bill_url": None, "notes": ""}
STATEMENT_KEYS = {"parcel_number_shown": None, "property_address_shown": None, "agency_name": None,
                  "agency_address": None, "levying_bodies": [], "separate_collectors": [], "notes": ""}


def first_json_object(text, defaults):
    """Claude may wrap the JSON in a code fence, add commentary, or answer in prose. Take the first JSON object;
    with none, keep the prose as the note. Keys Claude left out get their default."""
    if "{" not in text:
        return {**defaults, "notes": text.strip()[:400]}
    return {**defaults, **json.JSONDecoder().raw_decode(text[text.index("{"):])[0]}


def research_property(address, county, state, parcel_id, boundaries):
    """address and parcel_id may each be None (the search can start from either)."""
    where = f"Property address: {address}." if address else "The property address is not known; find it from the parcel number."
    prompt = f"""{where} County: {county}, {state}. Parcel number given: {parcel_id or 'none'}.
Census boundaries for the address: {boundaries or 'not available'}.

Use the county's public tax collector / treasurer / assessor sites to find, for this property:
- parcel_id: the parcel number (APN) exactly as a county record shows it. null if you cannot find it. Never guess one.
- parcel_id_source: "portal" only if a county portal or county record showed it, otherwise "third_party".
- parcel_address: the property's address as the county records it.
- agency_name, payment_address, portal_url: the office that collects the property tax for this property.
- levying_bodies: the taxing bodies that levy property tax on it (names).
- separate_collectors: every OTHER office (city, school district, township, special district, tax claim bureau) that bills or collects its own property tax for this property. An empty list if none.
- tax_year and bill_url: the most recent tax year with a bill and a direct link to the bill (PDF or printable statement), else null.
- notes: one short sentence on anything you could not find.

You have at most {MAX_SEARCHES} searches and {MAX_FETCHES} page fetches. Use them in this order:
1. Use a search only to find the county's own parcel lookup (assessor or treasurer). Do not search for the parcel number on real-estate, permit or other third-party sites.
2. Use the fetches on the county's pages: the treasurer's tax-statement page (this gives the agency) and the county's parcel lookup (this gives the parcel).
3. Stop as soon as a county page shows the parcel with this address. If no county page does, set parcel_id to null rather than using a number from a third-party page, and answer with the agency and null for the rest.

Return only one JSON object with exactly these keys: {", ".join(RESEARCH_KEYS)}."""
    found = first_json_object(ask(prompt, tools=WEB_TOOLS), RESEARCH_KEYS)
    trace.claude("Web research: find the parcel and the collecting agency", f"{address or parcel_id}, {county}, {state}",
                 f"parcel {found['parcel_id']} (source: {found['parcel_id_source']}); agency {found['agency_name']}; portal {found['portal_url']}")
    return found


def read_statement(captured, parcel_id):
    """Identify the agency from the text of the county's own statement page."""
    prompt = f"""Below is the text of a county property tax portal page ({captured['page_url']}) that shows the latest tax statement for parcel {parcel_id}.
Using only this text, return one JSON object with exactly these keys: {", ".join(STATEMENT_KEYS)}.
- parcel_number_shown: the parcel number as printed on the page.
- property_address_shown: the property address if the page prints it.
- agency_name: the office that bills and collects the tax, in the portal's own wording.
- agency_address: the office or payment address printed on the page.
- levying_bodies: the taxing bodies the statement itemises or names (for example school, county, city).
- separate_collectors: any other office the page says bills or collects part of this tax. An empty list if none.
- notes: one short sentence on anything the page does not show.
Use null for anything the text does not show. Do not use outside knowledge.

Page title: {captured['page_title']}
Page text:
{captured['page_text'][:12000]}"""
    read = first_json_object(ask(prompt), STATEMENT_KEYS)
    trace.claude("Read the agency from the statement page text", captured["page_url"],
                 f"parcel shown {read['parcel_number_shown']}; agency {read['agency_name']}; separate collectors {read['separate_collectors'] or 'none'}")
    return read
