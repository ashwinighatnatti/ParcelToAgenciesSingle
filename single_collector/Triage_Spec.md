# Triage specification: sorting parcel addresses into simple, medium and complex

Written 2026-11-19 for the Jev experiment. It describes (a) how the pipeline validates a parcel address and searches for the tax agency
(the trajectory), and (b) how the triage sorts a batch before any search is run, so it can be given to a model as input.
Code: `single_collector/stages.py`, `run.py`, `portal.py`, `trace.py`, `confidence.py` (pipeline); `triage.py` (rule-based triage);
`triage_jev.py` (Jev triage). Web app tabs: Triage (`/triage/`) and Triage-Jev (`/triage-jev/`).

**How the Jev triage was built from this spec (section 6):** the SDK is `typesafe-sdk` (`TypeSafeClient.system_one(state=..., questions={...}, model=...)`
with `Choice` and `Noul` questions). The model must be `jev-latest` or `jev-preview` (the `client.models.list()` result); the `jev-1.12` in
`.env_typesafe` is rejected by the API as an unknown model, so the code sets the model explicitly.

## 1. Purpose and scope

Given a batch of rows `address | parcel_id`, decide for each row how hard it will be for the pipeline to (1) validate the address and find a valid parcel and (2) find the tax agency: **simple** (easily accessible), **medium** (few steps), **complex**. Triage is an identification step only. It does not run the search and must cost far less than one.

## 2. The pipeline being triaged (what a full run does)

Three stages, in order (`stages.py`, `run.py`). Each returns a status and a reason; nothing guesses.

**Stage 1. Validate the address** (free: Census)
1. US Census Geocoder (`onelineaddress`, or `addressbatch` for 10+ addresses): matches the address, returns matched address, coordinates, county code (state+county FIPS).
2. US Census TIGERweb at the matched point: county, incorporated city (none = unincorporated), school districts.
3. Cross-check (no outside call): flags if state or county entered differs from the Census, or geocoder and TIGERweb disagree.
4. No match -> `valid = false`; the run stops unless a parcel ID with state and county was also given. The Census only estimates a point along the street, so a real parcel is still needed to prove the address exists.

**Stage 2. Find and validate the parcel**
- Needs a county: from the valid address, or from a parcel ID plus state and county. A parcel number is unique only within a county. Otherwise status `county_needed` / `county_unknown` / `not_searched`.
- Route is decided by the county code: does it have a scripted **adapter**? Today only Maricopa AZ (04013) and King WA (53033).
- **Adapter, parcel ID given:** look it up in the county GIS; if the address was also given, check the parcel's address agrees (same house number, street name >= 0.85 similar).
- **Adapter, address only:** take the most distinctive word of the street (`core_word`), search the county GIS in the ZIP, keep same-street rows (similarity >= 0.85), compare house numbers: exactly 1 match = parcel; more than 1 = `ambiguous` (for example a condominium); none = `not_found` plus the 5 nearest house numbers on the street as suggestions (never auto-picked).
- **No adapter:** Claude web research (`portal.research_property`), capped at **2 searches and 4 page fetches** (was 6 and 4). Order: search only to find the county's own lookup, fetch county pages, stop when a county page shows the parcel, never use a third-party parcel number (return null). A parcel number read from a county portal = verified; otherwise `third_party` = unverified.

**Stage 3. Find and validate the agency**
- **Adapter and parcel matched:** open the county treasurer statement page in a browser, save it as PDF, Claude reads the agency from the page text, code checks the parcel number is on the page. Parcel on page = **validated**.
- **No adapter:** the agency comes from the stage 2 web research (or a county-level web search if no parcel matched). Never validated.
- Result fields: agency name, payment address, portal URL, levying bodies, separate collectors (others that bill part of the tax), collector model (single / multiple / unknown).

**Final status:** `success` (parcel from county records AND agency from county statement), `found_unverified` (web research), `exception_multi_agency`, `agency_not_found`, `parcel_not_found`, `parcel_ambiguous`, `county_needed`, `county_unknown`, `invalid_address`, `error`.

**Confidence 0-100:** points per stage (address 20, parcel 40, agency 40) normalised by points possible; adjustments -20 (parcel address differs from input), -10 (separate collector); no agency = 0. Levels: high 80+, medium 50-79, low below 50.

**Cost of a full run:** Claude input and output tokens plus web searches ($5/M input, $25/M output, $0.01/search; env-overridable assumptions). Input tokens dominate because every search round re-bills the growing context.

## 3. The search trajectory (the record each run produces)

`trace.py` records ordered steps. Each step: stage, source, action, URL, what was asked, what came back. A Claude step also records its web searches, the results it received, pages it opened, its notes, tokens and cost. Sources that appear:

| Stage | Source | Cost |
|---|---|---|
| 1 | Census Geocoder, Census TIGERweb, cross-check | $0 |
| 2 (adapter) | County GIS parcel service (Maricopa Assessor GIS, King County GIS) | $0 |
| 2 (no adapter) | Claude web search and web fetch: county assessor/treasurer pages, plus whatever the search returns (real-estate and aggregator sites, city PDFs) | about $0.85 |
| 3 (adapter) | County treasurer statement page (browser), one small Claude read | about $0.01 |
| 3 (no adapter) | Reuses stage 2 research | $0 extra |

Limits of the record: the API returns search results per Claude call, not per query; the server-side code runs behind the search tool are counted but their billing is not visible.

## 4. The current triage (rule-based baseline)

Inputs: the rows, plus the Census batch geocoder (one request, free), the adapter list (`PORTALS`), and `jurisdictions_config.json` (state classified single-collector or fragmented; a draft not yet checked with Operations).

Per row, in order (first match wins):

| # | Condition | Cause | Level | Est. full-run cost |
|---|---|---|---|---|
| 1 | Address given, Census does not match | address_not_matched | complex | $0 (full run stops at stage 1) |
| 2 | County has an adapter | adapter | simple | $0.015 |
| 3 | State not identified | state_unknown | complex | $0.85 |
| 4 | No adapter, state is single-collector | single_collector_state | medium | $0.85 |
| 5 | No adapter, state has several collectors | several_collectors_state | complex | $0.85 |

Outputs: summary table (rows, share, estimated full-run cost per level, total), steps per level, counts per cause, by-state table, notes, every row with its reason, and a CSV.

**Result on `sample_files/ParcelList_cleaned.csv` (260 rows):** simple 4 ($0.06), medium 89 ($75.65), complex 167 ($85.00), total about $160.71. Of the 167 complex: 67 unmatched addresses (some are junk such as "No situs, NONE, AL" or "+/- 6.7 acres Hwy 5") and 100 in several-collector states. Triage cost: $0, no Claude call, 1 Census request, about 4 s.

**Known weaknesses (where Jev could help):**
- The level comes from the state and the adapter list only. It ignores the address text, the parcel ID format, and the county.
- Complex does not mean "will fail": all five Alaska rows (complex by rule) found an agency in a real run.
- Unmatched addresses are lumped with several-collector states, but their causes differ (junk text, a typo, a new street the geocoder lacks).
- The state classification is a draft; the rule has never been compared with real outcomes.

## 5. Ground truth available from real runs (for labelling and examples)

| Row | Route | Result | Cost |
|---|---|---|---|
| Maricopa AZ address | adapter | success, confidence 100 | $0.012 |
| King WA, 4745 Ravenna | adapter | success, confidence 100 | $0.015 |
| 11205 Tindall Rd, Orlando FL | web | found_unverified, 55 | $0.86 (after cap) |
| 5 Alaska rows (Mat-Su and others) | web | 1 success (70), 4 found_unverified (55) | $4.94 total, 362 s |
| 3295 Foothill Plz, Lake Havasu City AZ | web | before: found_unverified, wrong parcel, $1.99; after 2-search cap: parcel_not_found, 28, $0.85 | $1.99 -> $0.85 |
| Earlier 10-row, 6-state sample | mixed | 2 success, 3 found_unverified, 5 failed (3 county_needed because the Census rejected the address, 2 parcel_not_found) | not recorded |

Caveat: web research is not deterministic (a Texas address sometimes found a parcel and sometimes not), so labels from one run are noisy. Only about 20 rows have real outcomes; the other 240 do not.

## 6. How Jev fits (from the user's Jev rules)

Jev is a probabilistic classifier/router: it takes `state` (context) and `questions` (choice, noul or score primitives), returns probabilities, and independent questions about the same state go in one parallel call. It must not do math, counting, date comparison or open-ended extraction. So the work splits:

**Stays deterministic code (never Jev):** Census geocoding and county FIPS, adapter lookup (`county_code in PORTALS`), state lookup from config, row and cost arithmetic, share percentages, counting rows per level, the `core_word` / house-number / 0.85 similarity logic.

**Jev decisions (judgement from text and context):**

`state` per row (one JSON-style dict; facts computed by code are passed in, Jev only judges): `address`, `parcel_id`, `census_matched` (bool), `matched_address`, `state`, `county_code`, `county_has_adapter` (bool), `state_collector_model` (single / several, from `jurisdictions_config.json`) and `state_note`.

Questions, all asked in ONE `client.system_one(...)` call per row (independent questions about the same state are batched):

| Name | SDK primitive | Criteria | Purpose |
|---|---|---|---|
| `address_quality` | `Choice` | real_street_address / placeholder_or_junk / ambiguous | Separates fixable unmatched rows from junk ("No situs", "+/- 6.7 acres", "0 Mill Bridge Rd") |
| `parcel_id_wellformed` | `Noul` (yes/no) | true = looks like a complete county parcel number | Flags typos or truncated IDs before a search |
| `public_portal_likely` | `Choice` | yes / partial / no | Will the county publish a searchable parcel and tax site? |
| `billing_offices` | `Choice` | one_office / several / unsure | Row-level replacement for the blunt state rule |
| `difficulty` | `Choice` | simple / medium / complex (each with a one-line description from the table in section 4) | The triage label |

**Routing (guardrails), in `triage_jev.py`:**
1. Hard rule first, no Jev call: adapter county with a matched address = simple (Jev is not needed and a call would cost).
2. Otherwise Jev answers. The triage label is `difficulty.choice`, and its `confidence` is compared with a threshold (default 0.7, a setting on the tab). Below the threshold the row is marked "needs Claude review" and keeps the rule-based level as a fallback; no Claude call is made inside triage (keeps triage cheap and traceable; the flagged rows are the ones to send to Claude).
3. Never ask Jev for text, a parcel number, a count or arithmetic; counts, shares and cost sums are code.

## 7. Experiment design

1. **Labels.** Define the true level from actual outcomes: simple = adapter route, success, under $0.05; medium = web route, found_unverified or success, one agency, under $1; complex = failed, ambiguous, multi-agency, or needed manual follow-up. Use the roughly 20 rows already run; add a **stratified sample** to run in full (for example 30 rows chosen across the three rule levels). Estimated cost to label: about $0.85 per web row, so roughly $20 to $25 for 30 rows (estimate, not measured).
2. **Compare** three triagers on the same rows: rule baseline, Jev, Jev with Claude fallback. Measures: accuracy against the label, confusion matrix, and the share routed to Claude.
3. **Cost.** Triage must stay far below the $0.85 per web row it tries to predict. Record Jev cost per 260 rows.
4. **Report.** The Triage tab summary table, per method.

## 8. Open items

- Jev pricing (not in the SDK): tokens are reported; USD only if the user sets a price in `.env_typesafe`.
- Whether `TYPESAFE_DEFAULT_MODEL` accepts the same question set (checked by the smoke test below).
- The probability threshold for routing to Claude (default 0.7; tune from the experiment).
- "More accurate" cannot be claimed until labelled outcomes exist (section 7); the tab shows agreement with the rule-based level and Jev's confidence, not accuracy.
- Operations review of `jurisdictions_config.json`.
- More adapters (Mohave AZ is the clearest case) would move rows to simple and change the labels.
