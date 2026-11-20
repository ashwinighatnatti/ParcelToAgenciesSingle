"""Triage with the Jev model (TypeSafe), shown next to the rule-based triage in triage.py. Not a search run.

Jev is a classifier, not a text generator: for each row it is given the facts that code has already computed (the Census
match, whether the county has an adapter, how the state collects tax) plus the raw address and parcel ID text, and it answers
five questions with probabilities, all in ONE call. Counting, cost sums and shares stay in code.

  1. Rows whose county has an adapter (and a matched address) are 'simple' by rule: no Jev call is made.
  2. For every other row Jev answers. The triage level is its `difficulty` choice. If its confidence is below the threshold
     the row keeps the rule-based level and is flagged 'needs Claude review' (no Claude call is made here).
  3. A failed call for one row keeps the rule-based level and records the error; the rest of the batch continues.

The API key and model come from .env_typesafe (TYPESAFE_API_KEY, TYPESAFE_DEFAULT_MODEL); the key is never printed or stored.
    triage_jev(queries, threshold) -> {"rows": [...], "summary": {...}}
"""
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv
from typesafe_sdk import Choice, Noul, TypeSafeClient

from single_collector import jurisdictions, triage

ENV_FILE = Path(__file__).with_name(".env_typesafe")
DEFAULT_THRESHOLD = 0.7  # below this confidence in `difficulty`, the row is flagged for Claude review
WORKERS = 8
# The API accepts jev-latest and jev-preview (client.models.list()); the TYPESAFE_DEFAULT_MODEL in .env_typesafe, jev-1.12, is rejected as unknown.
# Set TYPESAFE_TRIAGE_MODEL in .env_typesafe to use another model.
MODEL_DEFAULT = "jev-latest"

QUESTIONS = {
    "address_quality": Choice(
        instructions="Look at the address text. Is it a real, complete street address, or a placeholder or land description "
                     "(for example 'No situs', an acreage, 'NONE', a house number of 0, a range of lots)?",
        criteria={"real_street_address": "A complete street address with a street number and a street name",
                  "placeholder_or_junk": "A placeholder or a description of land, not a street address",
                  "ambiguous": "Could be real but is incomplete or unusual"}),
    "parcel_id_wellformed": Noul(
        instructions="Does the parcel ID look like a complete parcel number as counties write them (digits, letters or dashes; "
                     "not blank, not a placeholder such as X or N/A, not obviously cut short)?"),
    "public_portal_likely": Choice(
        instructions="Does this county, or this state's counties in general, publish a searchable public parcel and property tax "
                     "website that a program can read?",
        criteria={"yes": "A public searchable parcel and tax site is likely", "partial": "Some information is online, or only some counties publish it",
                  "no": "Little or nothing is published online"}),
    "billing_offices": Choice(
        instructions="Does one office (usually the county treasurer or tax collector) bill all the property tax for a parcel here, "
                     "or can towns, boroughs, cities or districts bill separately?",
        criteria={"one_office": "One office bills the whole property tax", "several": "Several offices can bill separately",
                  "unsure": "It is not clear from the facts given"}),
    "difficulty": Choice(
        instructions="How hard will it be to validate this parcel address and parcel ID, and find the tax collecting agency, using "
                     "public websites? Use census_matched, county_has_adapter and the state notes.",
        criteria={"simple": "The address is matched and a scripted adapter reads the county's own parcel and tax records",
                  "medium": "No adapter, but one county-level office collects the tax, so web research should find one agency",
                  "complex": "The address could not be matched or is junk, or several offices may collect the tax: expect manual review"}),
}


def load_key():
    """Put the Jev key and model from .env_typesafe into the environment (the SDK reads them from there)."""
    load_dotenv(ENV_FILE)
    return {"key_present": bool(os.environ.get("TYPESAFE_API_KEY")), "model": os.environ.get("TYPESAFE_TRIAGE_MODEL", MODEL_DEFAULT)}


def facts(row):
    """What Jev is told about one row. `row` is a rule-based triage row (triage.triage); these are facts, Jev only judges."""
    state_info = jurisdictions.load().get(row["state"])
    return {"address": row["address"], "parcel_id": row["parcel_id"], "census_matched": bool(row["county_code"]),
            "matched_address": row["matched_address"], "state": row["state"], "county_code": row["county_code"],
            "county_has_adapter": row["cause"] == "adapter",
            "state_collector_model": ("single" if state_info["is_single_collector"] else "several") if state_info else "unknown",
            "state_note": state_info["notes"] if state_info else ""}


def ask_jev(row):
    """One Jev call, all five questions. Returns the answers as a flat dict."""
    with TypeSafeClient() as client:
        response = client.system_one(state=facts(row), questions=QUESTIONS, model=load_key()["model"])
    level = response.choices["difficulty"]
    return {"jev_level": level.choice, "jev_confidence": round(level.confidence, 3),
            "jev_probabilities": ", ".join(f"{k} {v:.2f}" for k, v in level.probabilities.items()),
            "address_quality": response.choices["address_quality"].choice,
            "parcel_id_wellformed": round(response.nouls["parcel_id_wellformed"].noul, 2),
            "public_portal_likely": response.choices["public_portal_likely"].choice,
            "billing_offices": response.choices["billing_offices"].choice,
            "input_tokens": response.usage.input_tokens or 0, "output_tokens": response.usage.output_tokens or 0, "error": ""}


EMPTY = {"jev_level": "", "jev_confidence": "", "jev_probabilities": "", "address_quality": "", "parcel_id_wellformed": "",
         "public_portal_likely": "", "billing_offices": "", "input_tokens": 0, "output_tokens": 0, "error": ""}


def decide(rule_row, threshold):
    """The Jev answer for one row (or none for a hard-rule row) and the level that results."""
    if rule_row["cause"] == "adapter":
        return {**EMPTY, "final_level": "simple", "needs_claude": False, "decided_by": "hard rule (adapter county, no Jev call)"}
    try:
        answer = ask_jev(rule_row)
    except Exception as error:  # one failed call must not lose the batch
        return {**EMPTY, "error": f"{type(error).__name__}: {error}"[:200], "final_level": rule_row["level"], "needs_claude": True,
                "decided_by": "rule level (Jev call failed)"}
    if answer["jev_confidence"] >= threshold:
        return {**answer, "final_level": answer["jev_level"], "needs_claude": False, "decided_by": "Jev"}
    return {**answer, "final_level": rule_row["level"], "needs_claude": True,
            "decided_by": f"rule level (Jev confidence {answer['jev_confidence']} is below {threshold})"}


def triage_jev(queries, threshold=DEFAULT_THRESHOLD):
    started = time.time()
    key = load_key()
    rule = triage.triage(queries)["rows"]  # the Census batch geocode (free) and the rule-based level for every row
    with ThreadPoolExecutor(WORKERS) as pool:
        decisions = list(pool.map(lambda row: decide(row, threshold), rule))
    rows = [{**row, "rule_level": row["level"], **decision} for row, decision in zip(rule, decisions)]
    for row in rows:
        row["level"] = row["final_level"]

    total = len(rows) or 1
    asked = [r for r in rows if r["decided_by"] != "hard rule (adapter county, no Jev call)" and not r["error"]]
    answered = [r for r in asked if r["jev_level"]]
    summary = {level: {"rows": sum(r["final_level"] == level for r in rows), "share_pct": round(100 * sum(r["final_level"] == level for r in rows) / total)}
               for level in triage.LEVELS}
    summary["total"] = {"rows": len(rows), "share_pct": 100}
    summary["agreement"] = [{"rule": level, "rows": sum(r["rule_level"] == level for r in answered),
                             **{jev: sum(r["rule_level"] == level and r["jev_level"] == jev for r in answered) for jev in triage.LEVELS}}
                            for level in triage.LEVELS]
    summary["jev"] = {"model": key["model"], "key_present": key["key_present"], "threshold": threshold,
                      "hard_rule_rows": sum(r["decided_by"].startswith("hard rule") for r in rows), "calls": sum(not r["decided_by"].startswith("hard rule") for r in rows), "errors": sum(bool(r["error"]) for r in rows),
                      "used_jev_level": sum(r["decided_by"] == "Jev" for r in rows), "needs_claude": sum(r["needs_claude"] for r in rows),
                      "agree_with_rule": sum(r["rule_level"] == r["jev_level"] for r in answered), "answered": len(answered),
                      "input_tokens": sum(r["input_tokens"] for r in rows), "output_tokens": sum(r["output_tokens"] for r in rows),
                      "seconds": round(time.time() - started, 1)}
    price_in, price_out = os.environ.get("TYPESAFE_COST_INPUT_PER_MTOK"), os.environ.get("TYPESAFE_COST_OUTPUT_PER_MTOK")
    summary["jev"]["cost_usd"] = (round((summary["jev"]["input_tokens"] * float(price_in) + summary["jev"]["output_tokens"] * float(price_out)) / 1e6, 4)
                                  if price_in and price_out else None)  # the price is not in the SDK: set both in .env_typesafe to see dollars
    return {"rows": rows, "summary": summary}
