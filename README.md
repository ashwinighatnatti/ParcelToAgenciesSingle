# Parcel -> Tax Agencies

## Setup on a new machine (full steps, start/stop scripts: see `RUN_STEPS.md`)
    git clone <repo-url> && cd <repo>
    python -m venv .venv && .venv\Scriptsctivate        (macOS/Linux: source .venv/bin/activate)
    pip install -r requirements.txt
    python -m playwright install chromium                   (needed for the county portal scripts)
    copy .env.example .env                                  (then fill in the Azure key, endpoint and deployment name)
    copy .env.example single_collector\.env_typesafe        (keep only the TYPESAFE_* lines; needed for triage only)
    python django_ui/manage.py migrate
    python django_ui/manage.py runserver                    (UI at http://127.0.0.1:8000/)

`.env`, `.env_typesafe`, `db.sqlite3`, `downloads/` and `output/` are not in git; they are created or supplied per machine.

## What the sample data shows (`Parcels_With_Mulitple_Agencies.xlsx`)
- 8,358 rows, 1,843 parcels, 1,954 distinct agencies (`agency_number`), mostly PA, TX, NY, GA, MI.
- Every parcel has at least 4 agencies. Typical mix: county, city/town, school district, plus special districts
  (MUD, WCID, solid waste, sewer, BID, "delinquent only" collectors).
- **ZIP code does not determine agencies.** Only 384 of 561 ZIPs have one agency set, covering 574 of 1,843 parcels.
  Special districts and school districts cut across ZIPs, so a ZIP/city lookup table alone is not enough.
- `agency_number` is structured: 2-digit state FIPS + 3-digit county FIPS + type/id (`131210000` = GA, Fulton County).
- Agency names are Operations' own labels, e.g. `Atlanta City (Fulton)`, `Buffalo City SD (...) (INACTIVE - COLLECTED ON CITY BILL)`.
  A free-text answer from any source has to be mapped to these names or numbers.
- Data quirks: `AgencyCount` is unreliable for big parcels (TX rows with 66 and 68); mixed case (`Ny`, `ATLANTA`);
  parcel numbers have stray spaces (`14 -0242-...`); 1,151 rows have no `tax_collector_property_number`.

## Approaches compared
| Approach | Accuracy | Scalability | Effort | Verdict |
|---|---|---|---|---|
| A. ZIP/city -> agencies lookup built from this file | Low (see ZIP finding) | Very fast and free | Low | Good only as a hint |
| B. Geocode address -> county, city, school district via GIS/Census, then lookup | High for county, city, school | Fast and cheap | Medium; special districts still need county GIS layers | Best long-term backbone |
| C. LLM + web search (the prompt in `prompt.txt`) | Good for the main entities, uncertain for special districts | Slow, costs per call | Low | **Start here** |
| D. Scrape each county tax site by parcel number | Highest | Hard: thousands of different sites | Very high | Not now |

**Recommendation:** start with C and add a matching step to the agency master. The matching step is the
important part, because it turns free text into `agency_number` and filters out invented names. Use this
file as the evaluation set. Once the numbers are measured, add B for the county, city and school entities
and use the LLM only for special districts. Cache results per parcel number, because the same parcel
repeats across applications (8,358 rows for 1,843 parcels).

## Geocoding (`geocode.py`)
The free US Census geocoder gives county, city, township and school district for an address. Its county code equals the first 5 digits of `agency_number`, so it picks the candidate list directly. In a 30-parcel check it found 21 addresses (70%), and the county matched Operations' data in all 21. Unmatched addresses fall back to the county Claude names.

## Files
- `agencies.py` loads the Excel file and builds the ground truth and the agency master.
- `agent.py` holds the prompt from `prompt.txt`, the Claude call with web search, and the match to agency master.
- `evaluate.py` runs a sample of parcels and prints recall and precision against Operations' answers.

## UI
    pip install streamlit
    streamlit run app.py

Enter a street address, city, state, ZIP and parcel number. The page shows the geocoded location, the agencies found,
and Claude's research notes. Choosing a sample parcel fills the form and compares the result with Operations' answer.

## Run (command line)
    pip install anthropic pandas openpyxl
    set ANTHROPIC_API_KEY=...
    python evaluate.py 10

## Results (10 random parcels, `python evaluate.py 10`)
| Version | Recall | Precision |
|---|---|---|
| 1. Claude names + fuzzy match to agency master (3 parcels) | ~30% | ~30% |
| 2. Claude researches, then picks from the county's agency list (10 parcels) | 51% (22 of 43) | 76% (22 of 29) |
| 3. Version 2 + delinquent/tax-claim rule (same 10 parcels, `run3.txt`) | 58% (25 of 43) | 86% (25 of 29) |
| 4. Version 3 + Census geocoding (same 10 parcels, `run4.txt`) | 58% (25 of 43) | 86% (25 of 29) |
| 5. Version 4 on 50 parcels (`run5.txt`) | 56% (128 of 227) | 88% (128 of 145) |

The rule adds a county's "Delinquent" / "Tax Claim" collectors only where at least half of that county's sample parcels have one (adding them everywhere would add 636 wrong entries for 245 correct ones). The 50% cut-off is learned from this same file, so the gain is optimistic for new counties.

Where the misses come from (see `run2.txt`):
- Operations lists collectors a web search never mentions: "Delinquent Only", "Tax Claim Bureau", law firms (Portnoff).
- The wrong local district: 1507 Elgin Ave got Humble ISD instead of Spring Branch ISD; Reading PA got Muhlenberg instead of Reading.
- Parcels near a county line: Chappell Hill TX lists Austin CAD and Washington CAD.
