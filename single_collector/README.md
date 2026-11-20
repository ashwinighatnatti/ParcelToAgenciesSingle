# Single-collector pipeline: dynamic tax agency search

Find the tax collecting agency for a property, starting from its **parcel address**, its **parcel ID**, or **both**.
It reuses `geocode.py` (Census geocoder) and `agent.py` (Claude client from `.env`) from the parent folder.
Nothing is looked up in a fixed list: the county comes from the Census, the parcel from the county's own records,
and the agency from the county's statement page (or from Claude's live web research where no adapter exists).

## The three stages (`stages.py`)
| Stage | Function | Question it answers |
|---|---|---|
| 1 | `validate_address` | Is the address real, and where is it? (Census geocoder + TIGERweb: normalized address, state, county, city, school district) |
| 2 | `find_validate_parcel` | Which parcel is it? Search by address or by parcel ID; when both are given, check they agree. Returns the parcel ID **and the parcel's own address**. If the address has no parcel, or several, it says why and lists the nearest parcels. |
| 3 | `find_validate_agency` | Who collects the tax? Read from the county's statement page and checked against the parcel ID. |

See `Search_Flow.html` for the data-flow diagram and worked examples, `Feature_Specification.html` for every feature and how it was tested, and `Developer_Guide.html` for the code walkthrough.

## Web UI (`../django_ui/`)
Django app: Search (three modes), Quick check (stages 1 and 2), Batch, History, Rank states, Jurisdictions. A search runs as a background job that the page polls, because it can take minutes. Results are stored in a local SQLite database. For local use only: no login, DEBUG on.

## Run (from the project folder)
    python -m single_collector.run "400 Broad St, Seattle, WA 98109"                       # by address
    python -m single_collector.run --parcel 1985200495 --state WA --county King            # by parcel id
    python -m single_collector.run "400 Broad St, Seattle, WA 98109" --parcel 1985200495   # both, cross-checked
    python -m single_collector.run --file searches.csv                                     # columns: address,parcel_id,state,county
    python django_ui/manage.py migrate && python django_ui/manage.py runserver             # the web UI at http://127.0.0.1:8000/

Output: `output/manifest.json` and PDFs under `downloads/{state}/{county}/{parcel_id}_{tax_year}_bill.pdf`.
With 10 or more addresses the Census `/addressbatch` endpoint geocodes them in one request.

Statuses: `success` (parcel verified in county records and agency read from the county statement), `found_unverified` (found by web research only), `exception_multi_agency`, `agency_not_found`, `parcel_not_found`, `parcel_ambiguous`,
`county_needed`, `county_unknown`, `invalid_address`, `error`.

## Files
| File | What it does |
|---|---|
| `stages.py` | The three stages |
| `run.py` | Orchestrates the stages; CLI; manifest |
| `census.py` | Batch geocoding, TIGERweb boundaries, county lookup by name (live Census) |
| `portal.py` | Claude: web research for counties without an adapter, and reading the agency from a statement page |
| `portals/` | County adapters (Maricopa AZ, King WA): parcel search in the county GIS service, and the statement in a headless browser |
| `bill.py` | Saves bill PDFs; renders an HTML statement to PDF |
| `jurisdictions.py`, `jurisdictions_config.json`, `rank_states.py` | The state ranking only. The search does not use them. |
| `app.py` | The earlier Streamlit UI (superseded by `../django_ui/`) |

> The sections below (capability check, county scripts, ranking) describe the earlier version in places: the Tier 1 gate,
> the fixed agency text in the county scripts and the single `success` status no longer exist.

## What the capability check showed
| Step | Result |
|---|---|
| Geocoding, FIPS, TIGERweb boundaries | Works. Found 21 of 30 (70%) sample addresses earlier; batch endpoint tested. |
| Tier 1 filter | Works. Fragmented states are skipped with the reason. |
| State check | Added after testing: the spec's example address (4600 Silver Hill Rd, "Washington, DC") is in Maryland. The Census state wins over the input state. |
| Agency name, payment address, portal | Works for San Francisco CA and Orange County FL (county pages are indexed). Not found for the DC test address. |
| Parcel id | Only found from third-party sources (`parcel_id_source: third_party`). The county portals need an interactive search, so it is not verified. |
| Tax bill PDF | No bill link was found for any tested property, so nothing was downloaded. The download code itself works for a direct PDF, an HTML page rendered to PDF, a missing link and a blocked page. |

## County browser scripts (`portals/`)
A county with a script in `portals/` skips the Claude research and gets the parcel id, agency and bill straight from the county's own systems.
Other counties use the Claude route above. To add a county: write a module with `COUNTY_CODE`, `AGENCY`, `find_parcel()` and `open_statement()`, then list it in `portals/__init__.py`.

| County | Parcel lookup | Statement | Result |
|---|---|---|---|
| Maricopa, AZ (04013) | Assessor GIS parcel layer, exact address match | Treasurer site, Payment Coupon tax breakdown (HTML, printed to PDF) | 2 of 2 bills saved |
| King, WA (53033) | County GIS parcel layer, exact address match | Treasury site, tax breakdown by year and tax/fee distribution (HTML, printed to PDF) | 2 of 2 bills saved |
| San Francisco, CA (06075) | not attempted | `county-taxes.com` is behind a Cloudflare bot challenge | Blocked. Not bypassed. |
| Orange, FL (12095) | not attempted | `county-taxes.net` is behind the same Cloudflare challenge | Blocked. Not bypassed. |

Checked: the saved PDFs contain the parcel number, the address and the billed amounts shown on the portals.
Test outputs: `test_run2.json`, `test_run3.json`. PDFs are in `../downloads/`.

What this showed:
- Where a portal is open, bills can be retrieved. Both open portals needed a script, because the statement is an HTML page behind a search form and a year picker, not a PDF link.
- The Census point is interpolated along the street and often falls outside the parcel, so the parcel is matched by exact address in the county GIS layer. A condo or multi-parcel address matches several parcels and is reported as "no single parcel", not guessed.
- Each script is about 40 lines but depends on one county's page layout, so a site redesign breaks it. A failed script is flagged and the Claude route takes over.
- Large Texas, Florida and California counties are the likely hard cases: shared hosting families (such as county-taxes) use Cloudflare. A script per family would not help there.
- Bills were for commercial properties (a landmark, office towers, an LLC-owned building) and a city-owned building. No private homes were queried.

## Ranking the easiest states (`rank_states.py`)
    python -m single_collector.rank_states        ->  output/tier1_states.json and output/tier1_states.csv

Lists the Tier 1 states, easiest first. Every signal is shown, with no hidden weighted score:
1. **Gate:** `is_single_collector` in `jurisdictions_config.json`, so a parcel maps directly to one collecting agency.
2. **Confidence** of that classification. High-confidence states are listed first (Tier 1A); medium ones (Tier 1B) need Operations to validate.
3. **Portals to cover:** how many of the state's largest counties hold 80% of its housing units (live from Census TIGERweb). Each county runs its own portal, so fewer counties means fewer portals to script.

Also in the output: the three largest counties, how many sample parcels Operations' file has for the state, and which counties we already scripted or found blocked.

Result (Tier 1A, first ten): DC (1 portal), Nevada (2), Arizona (4), Utah (6), Washington (10), Colorado (11), Wyoming (12), New Mexico (12), Oregon (12), Idaho (15).
California and Florida are single-collector states but rank 11 and 13 because many counties are needed (15 and 21 portals), and both counties we tried there were blocked.

Limits of the ranking:
- The county count is a proxy. Counties on a shared vendor portal count separately, and a shared portal that blocks bots (as county-taxes does) is not captured.
- The classification is still a draft from general knowledge. Operations' sample has 1 parcel each for CA and FL and none for the other Tier 1 states, so it cannot confirm or refute it. (The one FL parcel is corrupt: 25 unrelated agencies.)

## Test UI and specification
    streamlit run single_collector/app.py          (tabs: Find tax bill, Geocode only, Batch, County script, Jurisdictions, Rank states)
`Developer_Guide.html` is the code walkthrough for engineers (flow, data shapes, per-module reference, tech debt, how to extend).
`Feature_Specification.html` lists every feature, how it was verified, the output schema, limits and how to add a county.

## Limits
- County portals are interactive forms with no stable per-parcel link. Claude's search and fetch tools cannot fill them in, so verified parcel ids and bill PDFs need a different step (a headless browser script per portal family, or an assessor data feed).
- `jurisdictions_config.json` is a draft from general knowledge and the Operations sample file. Operations should validate it, especially the entries marked `medium` confidence. Portal URL patterns are null except DC because they differ by county.
- "Single collector" does not mean one agency in Operations' data: a San Francisco parcel lists 4 agencies (secured, supplemental, unsecured, business tax), all from one office.
