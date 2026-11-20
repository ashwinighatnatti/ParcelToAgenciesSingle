"""Confidence score (0-100) for the agency answer of one search, with the evidence it is based on.

Each stage contributes points for how strong its evidence is (RULES below, the single source for the score, the
web page and the audit file). A search by parcel ID has no address to check, so that part is left out and the score
is points earned / points possible. If no agency is found the score is 0: there is no answer to be confident about.
"""
# key: (evidence, points, points possible for that evidence, the situation that earns them)
RULES = {
    "address_matched": ("Address", 20, 20, "The Census geocoder matched the address"),
    "address_failed": ("Address", 0, 20, "The Census geocoder found no match"),
    "parcel_in_county_records": ("Parcel", 40, 40, "The parcel was found in the county's own records (county GIS service)"),
    "parcel_from_county_portal": ("Parcel", 30, 40, "The parcel number was read from a county portal through Claude's web research"),
    "parcel_third_party": ("Parcel", 15, 40, "The parcel number came from a third-party website, not the county"),
    "parcel_missing": ("Parcel", 0, 40, "No single parcel was matched"),
    "agency_from_statement": ("Agency", 40, 40, "Read from the county statement, which shows this parcel number"),
    "agency_statement_without_parcel": ("Agency", 10, 40, "Read from the county statement, but the parcel number was not on the page"),
    "agency_web_for_parcel": ("Agency", 20, 40, "Named by Claude's web research for this parcel; no county statement was read"),
    "agency_web_for_county": ("Agency", 8, 40, "Named by Claude's web research for the county only; no parcel was matched"),
    "agency_missing": ("Agency", 0, 40, "No collecting agency was found"),
    "adjust_address_differs": ("Adjustment", -20, 0, "The parcel's address differs from the address entered"),
    "adjust_separate_collector": ("Adjustment", -10, 0, "A separate collector was reported, so one agency is not the whole answer"),
}
LEVELS = "high 80-100, medium 50-79, low 0-49"


def factor(key, why=None):
    name, points, possible, situation = RULES[key]
    return {"factor": name, "points": points, "possible": possible, "why": why or situation}


def address_factor(check):
    if check.get("valid"):
        return factor("address_matched")
    if check.get("valid") is False:
        return factor("address_failed", check["reason"])
    return None  # a parcel ID search: no address was entered, so nothing to score


def parcel_factor(parcel):
    if parcel["status"] != "matched":
        return factor("parcel_missing")
    if parcel["source"] == "county_gis":
        return factor("parcel_in_county_records")
    return factor("parcel_from_county_portal" if parcel["verified"] else "parcel_third_party")


def agency_factor(agency, parcel):
    if agency["status"] != "found":
        return factor("agency_missing")
    if agency["basis"] == "statement_page":
        return factor("agency_from_statement" if agency["validated"] else "agency_statement_without_parcel")
    return factor("agency_web_for_parcel" if parcel["status"] == "matched" else "agency_web_for_county")


def score(address_check, parcel, agency):
    parts = [f for f in (address_factor(address_check), parcel_factor(parcel), agency_factor(agency, parcel)) if f]
    adjustments = []
    if parcel.get("address_matches_input") is False:
        adjustments.append(factor("adjust_address_differs"))
    if agency.get("separate_collectors"):
        adjustments.append(factor("adjust_separate_collector"))

    possible = sum(f["possible"] for f in parts)
    earned = sum(f["points"] for f in parts + adjustments)
    value = 0 if agency["status"] != "found" else max(0, min(100, round(100 * earned / possible)))
    level = "high" if value >= 80 else "medium" if value >= 50 else "low"
    summary = (f"{earned} of {possible} points earned = {value}." if agency["status"] == "found"
               else "No agency was found, so there is no answer to be confident about; the score is 0.")
    return {"score": value, "level": level, "summary": summary, "points_earned": earned, "points_possible": possible,
            "factors": parts + adjustments}
