"""UI for the single-collector pipeline.
Run from the project folder:  streamlit run single_collector/app.py

Searches that drive a browser or call Claude run through the command line (python -m single_collector.run) in a
separate process, so the UI shows exactly what the pipeline produces."""
import csv
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)  # the pipeline reads and writes relative paths (output/, downloads/, the Excel file)

import streamlit as st

from single_collector import jurisdictions, rank_states, stages
from single_collector.portals import PORTALS

ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}
STATUS_HELP = {
    "success": "The parcel is in the county's records and the agency was read from the county's statement.",
    "found_unverified": "A parcel and agency were found, but from web research, so they are not confirmed against county records.",
    "exception_multi_agency": "The agency was found, but a separate city, school or special-district collector was reported.",
    "agency_not_found": "The parcel was found but no collecting agency was identified.",
    "parcel_not_found": "No parcel matched. See the reason and the suggested parcels below.",
    "parcel_ambiguous": "Several parcels share this address. Pick one below.",
    "county_needed": "A parcel id needs a state and county, or a valid address.",
    "county_unknown": "The state and county did not match a single county.",
    "invalid_address": "The address could not be validated.",
    "error": "The search raised an error.",
}
PARCEL_SEARCH = ["Parcel address", "Parcel ID", "Both (cross-checked)"]


def run_command(args):
    """Run a pipeline command in its own process and return (stdout, stderr)."""
    done = subprocess.run([sys.executable, "-m", *args], cwd=ROOT, env=ENV, capture_output=True, text=True, encoding="utf-8")
    return done.stdout, done.stderr


def run_pipeline(queries):
    """Run single_collector.run on queries (dicts with any of address, parcel_id, state, county)."""
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["address", "parcel_id", "state", "county"], extrasaction="ignore")
        writer.writeheader()
        writer.writerows(queries)
    stdout, stderr = run_command(["single_collector.run", "--file", f.name])
    os.unlink(f.name)
    if not stdout.strip():
        st.error(f"The search produced no output.\n\n{stderr[-1500:]}")
        return []
    return json.loads((ROOT / "output" / "manifest.json").read_text(encoding="utf-8"))


def pdf_button(path, label="Download the tax bill PDF"):
    file = ROOT / path
    if file.exists():
        st.download_button(label, file.read_bytes(), file_name=file.name, mime="application/pdf", key=f"{label}-{file}")


def show_address(check):
    if not check["checked"]:
        st.info(check["reason"])
    elif not check["valid"]:
        st.error(check["reason"])
    else:
        st.write(f"**Normalized address:** {check['normalized_address']}  \n"
                 f"**State / county:** {check['state']} / {check['county']} (code {check['county_code']})  \n"
                 f"**City:** {', '.join(check['city']) or 'none (unincorporated)'}  \n"
                 f"**School district:** {', '.join(check['school_districts'])}")
        st.caption(check["note"])
    for flag in check.get("flags", []):
        st.warning(flag)


def show_parcel(parcel):
    """Show the parcel stage. Returns the parcel id chosen from the suggestions, if the user pressed the button."""
    if parcel["status"] == "matched":
        col1, col2, col3 = st.columns(3)
        col1.metric("Parcel ID", parcel["parcel_id"])
        col2.metric("Parcel address", parcel["parcel_address"])
        col3.metric("Verified in county records", "yes" if parcel["verified"] else "no")
        if parcel.get("address_matches_input") is False:
            st.warning("The parcel's address does not match the address entered.")
    else:
        st.warning(parcel["reason"])
    for flag in parcel.get("flags", []):
        st.warning(flag)
    candidates = parcel.get("candidates", [])
    if not candidates:
        return None
    st.write("**Suggested parcels**")
    st.dataframe([{"Parcel ID": c["parcel_id"], "Parcel address": c["parcel_address"], "City": c["city"], "ZIP": c["zip"]} for c in candidates],
                 hide_index=True, width="stretch")
    choice = st.selectbox("Search with one of these parcels", [f"{c['parcel_id']}  |  {c['parcel_address']}" for c in candidates])
    return choice.split("  |  ")[0] if st.button("Search with this parcel") else None


def show_agency(agency):
    if agency["status"] == "not_searched":
        st.info(agency["reason"])
        return
    if agency["status"] == "not_found":
        st.warning("No collecting agency was identified.")
    st.write(f"**Agency:** {agency['agency_name'] or 'not found'}  \n"
             f"**Office / payment address:** {agency['payment_address'] or 'n/a'}  \n"
             f"**Portal:** {agency['portal_url'] or 'n/a'}  \n"
             f"**Validated:** {'yes' if agency['validated'] else 'no'}   (basis: {agency['basis'].replace('_', ' ')})  \n"
             f"**Collector model:** {agency['collector_model']}   Taxing bodies on the statement: {', '.join(agency['levying_bodies']) or 'none listed'}  \n"
             f"**Separate collectors:** {', '.join(agency['separate_collectors']) or 'none reported'}")
    for check in agency["checks"]:
        st.caption(check)
    if agency.get("notes"):
        st.caption(agency["notes"])


def show_result(result):
    status = result["status"]
    box = st.success if status == "success" else st.error if status in ("error", "invalid_address") else st.warning
    box(f"**{status}**: {STATUS_HELP.get(status, '')}")
    if status == "error":
        st.error(result["reason"])
        return None
    st.subheader("1. Validate address")
    show_address(result["address_validation"])
    st.subheader("2. Find / validate parcel ID and address")
    chosen = show_parcel(result["parcel"])
    st.subheader("3. Find / validate agency")
    show_agency(result["agency"])
    bill = result["tax_bill"]
    if bill["available"]:
        st.write(f"**Tax bill:** available for tax year {bill['tax_year']}")
        pdf_button(bill["file_path"])
    else:
        st.write(f"**Tax bill:** not available. {bill['reason']}")
    for flag in result.get("flags", []):
        st.warning(flag)
    with st.expander("Full JSON result"):
        st.json(result)
    return chosen


def search(query):
    with st.spinner("Searching: validating the address, finding the parcel, identifying the agency..."):
        results = run_pipeline([query])
    st.session_state["result"] = results[0] if results else None


def query_form(key, default_address):
    """The three ways to search. Returns the query dict when the form is submitted."""
    mode = st.radio("Search by", PARCEL_SEARCH, horizontal=True, key=f"{key}-mode")
    with st.form(f"{key}-form"):
        address = st.text_input("Parcel address (street, city, ST ZIP)", default_address) if mode != "Parcel ID" else ""
        parcel_id = st.text_input("Parcel ID") if mode != "Parcel address" else ""
        state = county = ""
        if mode == "Parcel ID":
            col1, col2 = st.columns(2)
            state = col1.text_input("State (2 letters)", max_chars=2)
            county = col2.text_input("County (with or without the word County)")
        go = st.form_submit_button("Search")
    return {"address": address, "parcel_id": parcel_id, "state": state, "county": county} if go else None


st.set_page_config(page_title="Single-collector pipeline")  # browser tab title
st.title("Single-collector pipeline")
st.caption("Find the tax collecting agency for a property, starting from its parcel address, its parcel ID, or both.")
tab_search, tab_address, tab_parcel, tab_batch, tab_statement, tab_rank, tab_jur = st.tabs(
    ["Search", "1. Validate address", "2. Find parcel", "Batch", "County statement", "Rank states", "Jurisdictions"])

with tab_search:
    st.write("Runs all three stages. A county with an adapter takes about a minute; other counties are researched by Claude "
             "on the web and can take a few minutes. Nothing is looked up in a fixed list: the county comes from the Census, "
             "the parcel from the county's records, and the agency from the county's statement.")
    query = query_form("search", "400 Broad St, Seattle, WA 98109")
    if query:
        search(query)
    if st.session_state.get("result"):
        chosen = show_result(st.session_state["result"])
        if chosen:  # the user picked one of the suggested parcels
            parcel = st.session_state["result"]["parcel"]
            search({"parcel_id": chosen, "state": parcel["state"], "county": parcel["county"]})
            st.rerun()
    st.caption("Try: 400 Broad St, Seattle, WA 98109 (bill) · 4800 Ravenna Ave NE, Seattle, WA 98105 (no such parcel, nearest suggested) · "
               "721 Pine St, Seattle, WA 98101 (three parcels) · parcel 118-50-094 in Maricopa, AZ.")

with tab_address:
    st.write("Stage 1 on its own: Census geocoding and TIGERweb boundaries. Fast; no Claude.")
    with st.form("address-form"):
        text = st.text_input("Address (street, city, ST ZIP)", "8559 Spring Green Dr, Houston, TX 77095")
        go = st.form_submit_button("Validate")
    if go:
        show_address(stages.validate_address({"address": text}))

with tab_parcel:
    st.write("Stages 1 and 2: validate the address and find the parcel in the county's records. For a county with an adapter this "
             "is fast and does not call Claude. Other counties are searched by Claude.")
    query = query_form("parcel", "4800 Ravenna Ave NE, Seattle, WA 98105")
    if query:
        query = {key: value.strip() or None for key, value in query.items()}
        check = stages.validate_address(query)
        st.subheader("1. Validate address")
        show_address(check)
        st.subheader("2. Find / validate parcel ID and address")
        show_parcel(stages.find_validate_parcel(query, check))

with tab_batch:
    st.write("Runs several searches one after another. With 10 or more addresses the Census batch geocoder is used. "
             "Results are saved to output/manifest.json.")
    lines = st.text_area("One address per line", "400 Broad St, Seattle, WA 98109\n330 W Holly St, Phoenix, AZ 85003", height=110)
    upload = st.file_uploader("Or upload a CSV (columns: address, parcel_id, state, county)", type="csv")
    if st.button("Run batch"):
        queries = (list(csv.DictReader(upload.getvalue().decode("utf-8-sig").splitlines())) if upload
                   else [{"address": line.strip()} for line in lines.splitlines() if line.strip()])
        with st.spinner(f"Running {len(queries)} searches one after another..."):
            results = run_pipeline(queries)
        st.dataframe([{
            "search": r["query"].get("address") or f"parcel {r['query'].get('parcel_id')}", "status": r["status"],
            "parcel id": (r.get("parcel") or {}).get("parcel_id"), "parcel address": (r.get("parcel") or {}).get("parcel_address"),
            "agency": (r.get("agency") or {}).get("agency_name"), "bill": (r.get("tax_bill") or {}).get("available"),
        } for r in results], width="stretch")
        st.download_button("Download manifest.json", json.dumps(results, indent=2), file_name="manifest.json", mime="application/json")

with tab_statement:
    st.write("Runs one county adapter on its own: open the portal for a parcel and save the statement as a PDF. No Census or Claude calls.")
    with st.form("statement-form"):
        code = st.selectbox("County adapter", list(PORTALS), format_func=lambda c: f"{c}  ({PORTALS[c].__name__.split('.')[-1]})")
        parcel = st.text_input("Parcel ID", "118-50-094")
        go = st.form_submit_button("Open statement")
    st.caption("Maricopa (04013): 118-50-094 · King (53033): 1985200495")
    if go:
        with st.spinner("Driving the county portal in a headless browser..."):
            stdout, stderr = run_command(["single_collector.portals", code, "--parcel", parcel])
        if not stdout.strip():
            st.error(f"The adapter failed.\n\n{stderr[-1500:]}")
        else:
            captured = json.loads(stdout.strip().splitlines()[-1])
            if captured.get("parcel_id") is None:
                st.warning("The parcel was not found in the county's records.")
            else:
                st.success(f"Parcel {captured['parcel_id']} at {captured['parcel_address']}, tax year {captured['tax_year']}")
                pdf_button(captured["file_path"], "Download the statement PDF")
            st.json(captured)

with tab_rank:
    st.write("Ranks the states where one office collects the property tax, easiest first: confidence, then how many counties hold "
             "80% of the state's housing units. Fetches live county data from Census.")
    if st.button("Rank states"):
        with st.spinner("Fetching county data from Census..."):
            ranked = rank_states.rank_states()
        for label, confidence in (("Tier 1A: high confidence", "high"), ("Tier 1B: medium confidence, validate first", "medium")):
            st.subheader(label)
            st.dataframe([{
                "rank": r["rank"], "state": r["name"], "counties": r["counties"],
                "portals for 80% of homes": r["portals_for_80pct_of_homes"],
                "largest counties": ", ".join(r["largest_counties"]),
                "adapter counties": ", ".join(r["scripted_counties"]), "blocked": ", ".join(r["blocked"]),
            } for r in ranked if r["confidence"] == confidence], width="stretch", hide_index=True)
        st.download_button("Download tier1_states.json", json.dumps(ranked, indent=2), file_name="tier1_states.json", mime="application/json")

with tab_jur:
    st.write("The 51-jurisdiction reference file. It is used only by the state ranking; the search itself does not use it.")
    everything = list(jurisdictions.load().values())
    only_tier_1 = st.checkbox("Show only single-collector states")
    rows = [j for j in everything if j["is_single_collector"] or not only_tier_1]
    st.dataframe([{k: j[k] for k in ("state", "name", "tier", "is_single_collector", "primary_collector_level", "confidence", "notes")} for j in rows],
                 width="stretch", hide_index=True)
    st.caption("A draft classification that Operations should validate.")
