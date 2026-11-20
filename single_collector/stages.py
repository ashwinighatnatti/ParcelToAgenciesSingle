"""The three search stages of the single-collector pipeline. Each returns a plain dict with a status and a reason,
and none of them guesses.

  1. validate_address       Is the address real, and where is it? (Census geocoder + TIGERweb)
  2. find_validate_parcel   Which parcel is it? Search by address or by parcel id; when both are given, check they agree.
  3. find_validate_agency   Who collects the tax on that parcel? Read from the county's own statement page.

Nothing here is a lookup table: the county comes from the Census, the parcel from the county's records, and the
agency from the county's statement (or, for a county without an adapter, from Claude's live web research).
"""
import difflib
import re
from urllib.parse import urlparse

from geocode import URL as GEOCODER_URL, geocode_oneline
from single_collector import bill, census, portal, trace
from single_collector.portals import PORTALS, capture_statement

SIMILAR = 0.85  # two street names this alike are the same street (RAVENNA AVE NE ~ RAVENNA AV NE)
NEAREST = 5  # how many nearby parcels to suggest when the address has no parcel
RANKING_RULE = (f"When no parcel has the address entered, the parcels on the same street (same street name, same ZIP) are ranked by how close "
                f"their house number is to the one entered, and the {NEAREST} nearest are suggested. None is ever picked automatically.")
NOT_GEOCODED = object()  # "not geocoded yet"; None means "geocoded, no match"


def clean(text):
    return " ".join(re.sub(r"[^A-Z0-9 ]", " ", (text or "").upper()).split())


def house_number(street):
    match = re.match(r"\d+", clean(street))
    return int(match.group()) if match else None


def street_name(street):
    return re.sub(r"^\d+\s*", "", clean(street))


def same_street(a, b):
    return difflib.SequenceMatcher(None, street_name(a), street_name(b)).ratio() >= SIMILAR


def same_house(a, b):
    return house_number(a) is not None and house_number(a) == house_number(b) and same_street(a, b)


def core_word(street):
    """The most distinctive word of the street name, used to search the county's records (RAVENNA in 4800 RAVENNA AVE NE)."""
    words = street_name(street).split()
    return max(words, key=len) if words else ""


# ---------------------------------------------------------------- stage 1

def validate_address(query, geocoded=NOT_GEOCODED):
    """Stage 1. Returns valid True/False (None when the search started from a parcel id and there is no address yet)."""
    address = query.get("address")
    if not address:
        return {"checked": False, "valid": None, "flags": [],
                "reason": "Searching by parcel id: the parcel's own address is validated once the parcel is found."}
    if geocoded is NOT_GEOCODED:
        geo, source, url = geocode_oneline(address), "US Census Geocoder (one address)", GEOCODER_URL
    else:
        geo, source, url = geocoded, "US Census Geocoder (batch file)", census.BATCH_URL
    trace.add(source, "Match the address", address, f"matched as '{geo['matched_address']}'" if geo else "no match", url)
    if geo is None:
        return {"checked": True, "valid": False, "flags": [], "reason": "The Census geocoder found no match for this address."}
    bounds = census.tigerweb_boundaries(geo["x"], geo["y"])
    trace.add("US Census TIGERweb", "Boundaries at the matched point", f"point {geo['x']}, {geo['y']}",
              f"county {bounds['county']}; city {', '.join(bounds['incorporated_city']) or 'none (unincorporated)'}; "
              f"school districts {', '.join(bounds['school_districts']) or 'none'}", census.TIGERWEB_URL)
    street, city, state, zip_code = geo["matched_address"].rsplit(", ", 3)
    flags = []
    if query.get("state") and query["state"].upper() != state:
        flags.append(f"The address is in {state}, not {query['state'].upper()}; the Census state is used.")
    if bounds["county_geoid"] != geo["county_code"]:
        flags.append("The geocoder and TIGERweb disagree on the county.")
    if query.get("county") and query["county"].lower() not in bounds["county"].lower():
        flags.append(f"The address is in {bounds['county']}, not {query['county']}; the Census county is used.")
    trace.add("Check (no outside call)", "Cross-check state and county", "geocoder county vs TIGERweb county vs the state/county entered",
              "; ".join(flags) or "consistent")
    return {
        "checked": True, "valid": True, "normalized_address": geo["matched_address"],
        "street": street, "city_name": city, "state": state, "zip": zip_code,
        "county": bounds["county"], "county_code": geo["county_code"],
        "coordinates": {"x": geo["x"], "y": geo["y"]},
        "city": bounds["incorporated_city"], "school_districts": bounds["school_districts"],
        "flags": flags,
        "note": "The Census estimates a position along the street, so a real parcel is still needed to confirm the address exists.",
    }


# ---------------------------------------------------------------- stage 2

def parcel_matched(row, state, source="county_gis"):
    return {"status": "matched", "parcel_id": row["parcel_id"], "parcel_address": row["parcel_address"],
            "full_address": f"{row['parcel_address']}, {row['city']}, {state} {row['zip']}",
            "verified": True, "source": source, "candidates": [], "reason": None}


def candidate(row):
    return {"parcel_id": row["parcel_id"], "parcel_address": row["parcel_address"], "city": row["city"], "zip": row["zip"]}


def parcel_by_id(adapter, parcel_id, address_check, county, state):
    rows = adapter.search_by_parcel(parcel_id)
    trace.add(adapter.PARCEL_SOURCE, "Look up the parcel ID", parcel_id, f"{len(rows)} parcel(s) found"
              + (f": {rows[0]['parcel_id']} at {rows[0]['parcel_address'] or 'no address on record'}" if rows else ""), adapter.PARCELS)
    if not rows:
        return {"status": "not_found", "verified": False, "source": "county_gis", "candidates": [],
                "reason": f"No parcel '{parcel_id}' exists in the {county['county']} records."}
    result = parcel_matched(rows[0], state)
    if address_check.get("valid"):  # both were given: do they agree?
        agrees = same_house(rows[0]["parcel_address"], address_check["street"])
        result["address_matches_input"] = agrees
        if not agrees:
            result["flags"] = [f"The parcel's address ({rows[0]['parcel_address']}) differs from the address entered ({address_check['street']})."]
    return result


def parcel_by_address(adapter, address_check, county, state):
    street, number = address_check["street"], house_number(address_check["street"])
    word = core_word(street)
    rows = adapter.rows_on_street(word, address_check["zip"]) if word else []
    trace.add(adapter.PARCEL_SOURCE, "Search the street", f"addresses containing '{word}' in ZIP {address_check['zip']}", f"{len(rows)} parcel(s) returned", adapter.PARCELS)
    on_street = [r for r in rows if same_street(r["parcel_address"], street)]
    exact = [r for r in on_street if number is not None and house_number(r["parcel_address"]) == number]
    trace.add("Check (no outside call)", "Compare house numbers", f"house number {number} on '{street}'",
              f"{len(on_street)} on the same street; {len(exact)} with the same house number")
    if len(exact) == 1:
        return {**parcel_matched(exact[0], state), "address_matches_input": True}
    if len(exact) > 1:
        return {"status": "ambiguous", "verified": False, "source": "county_gis", "candidates": [candidate(r) for r in exact],
                "reason": f"{len(exact)} parcels share the address '{street}' (for example a condominium building). Pick one, or enter its parcel id."}
    numbered = sorted((r for r in on_street if house_number(r["parcel_address"]) is not None),
                      key=lambda r: abs(house_number(r["parcel_address"]) - (number or 0)))
    near = [candidate(r) for r in numbered[:NEAREST]]
    trace.add("Check (no outside call)", "Rank the nearest parcels", RANKING_RULE, ", ".join(f"{c['parcel_address']} ({c['parcel_id']})" for c in near) or "none")
    reason = (f"No parcel at '{street}' exists in the {county['county']} records, although the Census placed the address on that street. "
              + ("The nearest parcels on that street are listed. Pick one, or enter its parcel id." if near
                 else f"No parcels on that street were found in ZIP {address_check['zip']}."))
    return {"status": "not_found", "verified": False, "source": "county_gis", "candidates": near, "reason": reason}


def parcel_by_web_search(address_check, county, state, parcel_id):
    """No adapter for this county: Claude searches the web for the parcel. Its answer is reused by stage 3."""
    boundaries = ({"city": address_check["city"], "school_districts": address_check["school_districts"]}
                  if address_check.get("valid") else None)
    research = portal.research_property(address_check.get("normalized_address"), county["county"], state, parcel_id or None, boundaries)
    if not research["parcel_id"]:
        return {"status": "not_found", "verified": False, "source": "claude_search", "candidates": [], "research": research,
                "reason": f"The web search did not find a parcel number. {research['notes']}".strip()}
    verified = research["parcel_id_source"] == "portal"
    return {"status": "matched", "parcel_id": research["parcel_id"], "parcel_address": research["parcel_address"],
            "full_address": research["parcel_address"], "verified": verified, "source": "claude_search",
            "parcel_id_source": research["parcel_id_source"], "candidates": [], "research": research, "reason": None,
            "flags": [] if verified else ["The parcel number comes from a third-party source and is not verified against county records."]}


def find_validate_parcel(query, address_check):
    """Stage 2. Search by parcel id, by address, or check both against each other.
    status: matched | ambiguous | not_found | county_needed | county_unknown | not_searched"""
    parcel_id = (query.get("parcel_id") or "").strip()
    if address_check.get("valid"):
        county = {"county_code": address_check["county_code"], "county": address_check["county"]}
        state = address_check["state"]
    elif parcel_id and query.get("state") and query.get("county"):
        county = census.resolve_county(query["state"], query["county"])
        state = query["state"].upper()
        trace.add("US Census TIGERweb", "Look up the county", f"{query['county']}, {state}",
                  f"{county['county']} (code {county['county_code']})" if county else "no single county found", census.TIGERWEB_URL)
        if county is None:
            return {"status": "county_unknown", "flags": [], "reason": f"No single county named '{query['county']}' was found in {state}."}
    elif parcel_id:
        return {"status": "county_needed", "flags": [],
                "reason": "A parcel number is only unique within one county. Give the state and county, or a valid address."}
    else:
        return {"status": "not_searched", "flags": [],
                "reason": "The address could not be validated, so no parcel search was made. To search by parcel instead, give a parcel id with its state and county."}

    base = {"county_code": county["county_code"], "county": county["county"], "state": state, "flags": []}
    adapter = PORTALS.get(county["county_code"])
    if adapter is None:
        found = parcel_by_web_search(address_check, county, state, parcel_id)
    elif parcel_id:
        found = parcel_by_id(adapter, parcel_id, address_check, county, state)
    else:
        found = parcel_by_address(adapter, address_check, county, state)
    return {**base, **found}


# ---------------------------------------------------------------- stage 3

def no_bill(reason):
    return {"available": False, "reason": reason}


def agency_record(basis, validated, name, address, url, separate, levying, tax_year, checks, notes):
    separate, levying = separate or [], levying or []
    model = "multiple" if separate else "single" if len(levying) >= 2 else "unknown"  # several taxing bodies on one statement = single
    return {"status": "found" if name else "not_found", "validated": bool(validated and name), "basis": basis,
            "agency_name": name, "payment_address": address, "portal_url": url, "separate_collectors": separate,
            "levying_bodies": levying, "collector_model": model, "tax_year": tax_year, "checks": checks, "notes": notes}


def agency_from_statement(adapter, parcel):
    """The county's own statement page is the evidence: Claude reads the agency from it, and we check the parcel is on it."""
    captured = capture_statement(adapter, parcel["parcel_id"])
    trace.add(adapter.STATEMENT_SOURCE, "Open the tax statement page", f"parcel {parcel['parcel_id']}",
              f"statement for tax year {captured['tax_year']}, page '{captured['page_title']}'", captured["page_url"])
    read = portal.read_statement(captured, parcel["parcel_id"])
    digits = lambda text: re.sub(r"\D", "", text or "")
    parcel_on_page = bool(digits(parcel["parcel_id"])) and digits(parcel["parcel_id"]) in digits(captured["page_text"])
    host = "{0.scheme}://{0.netloc}".format(urlparse(captured["page_url"]))
    checks = ["The parcel number appears on the county statement." if parcel_on_page
              else "WARNING: the parcel number was not found on the statement page.",
              f"The statement is for tax year {captured['tax_year']}."]
    agency = agency_record("statement_page", parcel_on_page, read["agency_name"], read["agency_address"], host,
                           read["separate_collectors"], read["levying_bodies"], captured["tax_year"], checks, read["notes"])
    trace.add("Check (no outside call)", "Is the parcel number on the statement?", parcel["parcel_id"],
              "yes" if parcel_on_page else "no: the agency is not marked validated")
    path = bill.save_pdf_bytes(captured["pdf"], parcel["state"], parcel["county"], parcel["parcel_id"], captured["tax_year"])
    trace.add("Local file", "Save the statement page as the tax bill PDF", captured["page_url"], path)
    return agency, {"available": True, "tax_year": captured["tax_year"], "file_path": path}


def agency_from_search(research, basis, validated, checks):
    return agency_record(basis, validated, research["agency_name"], research["payment_address"], research["portal_url"],
                         research["separate_collectors"], research["levying_bodies"], research["tax_year"], checks, research["notes"])


def find_validate_agency(query, address_check, parcel):
    """Stage 3. Returns (agency, tax_bill).
    basis: statement_page (read from the county statement) | claude_search (web research) | county_level_search (no single parcel)"""
    if parcel["status"] in ("county_needed", "county_unknown", "not_searched"):
        return {"status": "not_searched", "validated": False, "reason": parcel["reason"]}, no_bill("no agency search was made")

    adapter = PORTALS.get(parcel["county_code"])
    if parcel["status"] == "matched" and adapter:
        try:
            return agency_from_statement(adapter, parcel)
        except Exception as error:  # the portal changed or timed out: fall back to web research, and say so
            parcel["flags"] = parcel.get("flags", []) + [f"County portal script failed ({type(error).__name__}); web research was used instead."]
            trace.add(adapter.STATEMENT_SOURCE, "Open the tax statement page", parcel["parcel_id"], f"failed: {type(error).__name__}; falling back to web research")

    research = parcel.get("research") or portal.research_property(
        address_check.get("normalized_address"), parcel["county"], parcel["state"],
        parcel.get("parcel_id"), {"city": address_check.get("city"), "school_districts": address_check.get("school_districts")})
    if parcel["status"] == "matched":
        agency = agency_from_search(research, "claude_search", parcel["verified"],
                                    ["The agency comes from web research, not from the county statement."])
        tax_bill = bill.download_bill(research["bill_url"], parcel["state"], parcel["county"], parcel["parcel_id"], research["tax_year"])
        trace.add("Bill link found by Claude", "Download the tax bill", research["bill_url"] or "no link",
                  tax_bill.get("file_path") or tax_bill["reason"], research["bill_url"])
        return agency, tax_bill
    agency = agency_from_search(research, "county_level_search", False,
                                ["No single parcel was matched, so this is the agency for the county, not confirmed for a parcel."])
    return agency, no_bill("no single parcel was matched")
