# Search budget review: 3295 FOOTHILL PLZ, LAKE HAVASU CITY, AZ 86404

Review date: 2026-11-19. Review only: no code was changed.

**Purpose:** show the team (A) what the current pipeline did for this address, then (B) the proposed limits and what changes. Part A is recorded fact from the audit file. Part B is a proposal: its cost figures are estimates and have not been measured.

Sources:
- Job `91b06f9d-2396-4eab-bfa6-46b31e52a866` (web app run, 2026-11-19 14:50:49 to 14:52:13 UTC)
- `audit_file_91b06f9d.xlsx` (this folder)
- `3295 FOOTHILL PLZ, LAKE HAVASU CITY, AZ 86404 _ result download.pdf` (this folder; print of the result page)
- `ParcelsToAgencies\sample_files\ParcelList_cleaned.csv` (expected parcel for this address: `112-08-068`)

---

# Part A. Earlier result: the extensive search as it ran

Input was the address only (no parcel ID). Final status `found_unverified`, confidence 55 (medium), cost $1.993, about 84 seconds.

## A1. Trajectory

| Stage | What happened | Claude calls | Cost |
|---|---|---|---|
| 1. Validate address | Census geocoder matched the address; TIGERweb gave Mohave County, Lake Havasu City, Lake Havasu Unified District; cross-check consistent | 0 | $0 |
| 2. Find / validate parcel | One Claude research call: **6 web searches, 4 pages opened (one twice), 54 search results, 15 server-side code runs** | 1 | $1.993 |
| 3. Find / validate agency | No call of its own: the agency came from the stage 2 answer; the bill download found no link | 0 | $0 |

Tokens: 366,919 input, 3,937 output. Input tokens were $1.83 of $1.993; the six searches themselves cost $0.06. That is about 61,000 input tokens per search on average (a simple division; real cost grows each round). Claude hit its tool limit (6 searches, 4 fetches) and finished with what it had.

## A2. The 6 web searches Claude ran

1. `Mohave County Arizona parcel search 3295 Foothill Plz Lake Havasu City assessor`
2. `Mohave County assessor parcel search "Foothill Plz" OR "Foothill Plaza" Lake Havasu`
3. `Mohave County treasurer tax statement search parcel Foothill Plaza 3295 Lake Havasu`
4. `appsweb.mohave.gov assessor parcel search 3295 Foothill`
5. `"3295 Foothill Plaza" Lake Havasu City parcel APN`
6. `"3295 Foothill Plaza" Lake Havasu 86404 parcel OR APN`

Each query shows 54 results in the audit file because the API returns the results of the whole Claude call together, not per query.

## A3. Pages Claude opened

1. `https://www.mohave.gov/departments/treasurer/property-taxes/tax-statements/` (opened twice)
2. `https://eaglerss.mohave.gov/web` (treasurer search)
3. `https://www.mohave.gov/departments/assessor/assessor-search/`

Claude never submitted either county lookup form. Its last notes: "Let me verify with assessor search", then "I've hit the tool use limits."

## A4. The 50 websites touched

| Group | Sites | Which |
|---|---|---|
| County-owned (Mohave) | 10 | `mohave.gov` 7, `appsweb.mohave.gov` 2, `eaglerss.mohave.gov` 1 |
| City of Lake Havasu permit PDFs | 5 | `lhcaz.gov` (source of the parcel number used) |
| Census services | 2 | geocoder, TIGERweb |
| Third-party | 33 | redfin 10, parcelrecordsusa 2, gisfinder 2, coldwellbankerhomes 2, loopnet 2, homes.com 2, and 1 each: 211arizona, assessorsearch, arizonaofficialrecords, countytaxassessor, property-recordss, countypropertyappraiser, an Indian university site, propertytaxusa, searchsystems, propertychecker, Wikipedia ("Fortification Hill"), zillow, longrealty |

Most third-party results were for other addresses and added nothing.

## A5. What the run concluded

| Item | Result | Weakness |
|---|---|---|
| Parcel | `112-08-297`, source third_party | Read from a permit PDF whose table text was split across cells ("112- ... 08- ... 297"); never confirmed on a county page. The cleaned file has `112-08-068`, so it is probably wrong. |
| Agency | Mohave County Treasurer, P.O. Box 712, Kingman, AZ 86402 | Reliable, but it came from web research, not a county statement (not validated). |
| Confidence | 55 / 100 (medium): address 20/20, parcel 15/40, agency 20/40 | Gives the agency 20/40 "for this parcel" though the parcel was unverified; lets a probably wrong parcel reach "medium". |

## A6. Findings from the review

1. **The parcel is probably wrong** (see A5). "Probably", because the evidence is the cleaned file, and Claude may also have misread the PDF.
2. **The agency needed no searching.** The geocoder and TIGERweb already gave Mohave County, and in Arizona the county treasurer bills all property tax in the county. The county tax-statements page, opened early, confirms it.
3. **The only parcel clue came from the later searches** (the permit PDF, after the portals and the recorder's search). The audit file cannot say which query returned which result, so searches 2 to 6 cannot be called pure waste.
4. **The run was cut off by the cap before the validating step.** The 6-search / 4-fetch limit stopped Claude after exploration and before it used either county portal. The budget was spent in the wrong order.
5. **Not established (my inference, not shown by the run):** whether the Mohave assessor or treasurer lookup can be reached by fetch. Claude never submitted either form.

---

# Part B. Modified approach: proposed limits and what changes

## B1. Proposed limits (current code allows 6 searches and 4 page opens)

| Step | Web searches | Pages opened | Rule |
|---|---|---|---|
| Agency decision | 0 | 1 | Open the county treasurer page once the geocoder gives the county. Stop when the county matches. |
| Parcel validation | 1 to 2, only to find the county's parcel-lookup URL | 2 to 3, spent on the county assessor and treasurer lookup | Page opens come before searching for third-party numbers. Stop when a county page shows the parcel with the same address, or the lookup cannot be used. A third-party number counts as unverified and never earns more searches. |
| **Per address** | **2 (hard cap 3)** | **3 to 4** | If no county page is reached, report "parcel not verified" and suggest nearby parcels. |

If the input includes the parcel ID (as in the cleaned file, `11208068`), the job is a single county lookup. This run was address-only, which is why it searched so widely.

## B2. Before and after

| | Earlier run (A) | Proposed (B) | Status of the B figure |
|---|---|---|---|
| Web searches | 6 | 2 (hard cap 3) | Proposed limit |
| Pages opened | 4 | 3 to 4, spent on county lookups first | Proposed limit |
| Websites touched | 50 (33 third-party) | A handful: county sites and Census | Expected, not measured |
| Search results read | 54 | About 18 or fewer (2 searches at about 9 results each) | Estimate from this run |
| Input tokens | 366,919 | Roughly a third | Estimate |
| Cost | $1.993 | About $0.60 to $0.80 | **Estimate, not measured** |
| Agency decision | After 6 searches | Geocoder county plus one county page, 0 searches | Expected |
| Parcel `112-08-297` accepted from a city PDF | Yes, scored "medium" | No: unconfirmed third-party numbers marked unverified, score capped | Proposed rule |
| Order of work | Searched widely, ran out of budget before the county lookup | County lookup first | Proposed rule |

Whether the proposed order really validates the parcel depends on whether the Mohave lookup can be reached by fetch (finding 5), which has not been tried. If it cannot, the proposal returns "parcel not verified" at about $0.60 to $0.80 instead of an unverified, probably wrong parcel at $1.99.

## B3. Further savings beyond the caps

- **County cache:** the agency for a county is the same for every parcel in it, so after the first Mohave address the agency stage could cost nothing.
- **Mohave adapter:** query the county's parcel service directly, as for Maricopa and King (about $0.01 per address).
- **Scoring:** a parcel number from third-party text should score lower or be capped below "medium", and the agency should not be scored "for this parcel" when the parcel is unverified.
- **Early exit:** ask Claude to return "not verified" as soon as the county portals turn out to be interactive, instead of searching on.

## B4. Corrections made during this review (kept for the record)

- An earlier claim that search 1 found everything useful was overstated (A6, finding 3).
- An earlier claim that the portals cannot be reached by more searching was my inference (A6, finding 5).
- Official-website counts were inconsistent between messages; A4 uses the audit file's count.
- An earlier claim that the cap was too generous was wrong: the cap ended the run before validation (A6, finding 4).

## B5. Open decisions

1. Apply the lower caps and stop rules, then re-run this address to **measure** the real cost (this replaces the B2 estimates).
2. Build a Mohave County adapter.
3. Add a per-county agency cache.
4. Change the confidence weights for unconfirmed parcels.

---

# Part C. Measured result after applying the limits (re-run, 2026-11-19)

**Change made (`single_collector/portal.py` only):** `MAX_SEARCHES, MAX_FETCHES` from 6, 4 to **2, 4**, and the research prompt now sets the order: a search only to find the county's own parcel lookup; fetches on the county's treasurer and assessor pages; stop when a county page shows the parcel; never use a parcel number from a third-party page (return null instead). The previous file is not kept in the project; the old values are the 6 and 4 of Part A. The confidence weights were **not** changed.

Same input as Part A (address only). Raw result: `output/foothill_rerun_2_searches.json`.

## C1. Before and after, measured

| | Part A run (6 searches, 4 fetches) | Part C run (2 searches, 4 fetches) |
|---|---|---|
| Web searches | 6 | **2** |
| Pages opened | 4 | 4 (treasurer statements page, assessor search page, assessor parcel-search app, treasurer page again) |
| Search results read | 54 | **18** |
| Websites touched | 50 | **23** |
| Server-side code runs | 15 | 8 |
| Input / output tokens | 366,919 / 3,937 | **155,477 / 2,073** |
| Cost | $1.993 | **$0.849** (57% lower) |
| Time | about 84 s | about 57 s |
| Status | found_unverified | parcel_not_found |
| Parcel returned | `112-08-297` (third-party PDF, probably wrong) | none (null) |
| Agency | Mohave County Treasurer | Mohave County Treasurer (same), county-level only |
| Confidence | 55 medium (address 20, parcel 15, agency 20) | **28 low** (address 20, parcel 0, agency 8) |

The two searches: `Mohave County Arizona treasurer parcel lookup tax statement` and `Mohave County assessor parcel search "3295 FOOTHILL" Lake Havasu`.

## C2. What the re-run showed

1. **Cost fell from $1.99 to $0.85 and the agency answer did not change.** The estimate in B2 ($0.60 to $0.80) was slightly low: the four page fetches add a lot of input tokens, so cutting only the searches saved less than hoped. Input tokens are still the cost (155,477 tokens is about $0.78 of the $0.85).
2. **A wrong parcel is no longer reported.** The run returns no parcel instead of `112-08-297`, and the confidence is 28 (low) instead of 55 (medium).
3. **Finding 5 of Part A is now answered.** The Mohave assessor parcel-search app (`appsweb.mohave.gov/data_apps/assessor_parcel_search`) returned no usable content to a direct fetch (Claude: "returned no interactive content for a non-JS fetch"). So the parcel cannot be validated for Mohave by web fetch, with or without more searches. It needs a Mohave County adapter that queries the county's parcel service directly (Part B3), or a browser, as for Maricopa and King.
4. **Result of this change:** this address now ends as "parcel not found, agency known at county level" at $0.85 instead of "unverified, probably wrong parcel" at $1.99. It does not find the parcel; only the adapter can.
5. **Noise remains.** 23 websites were still touched; the search results again included redfin, Wikipedia (Lake Havasu State Park, Mohave Mountains) and other third-party pages. The limit controls how many searches run, not which results come back.

## C3. Caveats

- One run only. Web research is not deterministic (the same Texas address earlier sometimes found a parcel and sometimes not), so repeat it before treating $0.85 as typical.
- The lower caps were applied to all counties without an adapter, not just Mohave. Other addresses may need more than 2 searches to reach the county's portal. Run a sample batch (for example the 5 Alaska rows) and compare cost and status with the earlier $4.94 run before keeping the caps.
- Only the research prompt and caps were changed. The scoring rules in B3 (agency score "for this parcel" when the parcel is unverified, third-party parcel weight) are still open.

## C4. Updated open decisions

1. ~~Apply the lower caps and re-run~~ done (Part C).
2. Build a Mohave County adapter (the only way to validate the parcel for this county, finding C2.3).
3. Add a per-county agency cache (the agency was identical in both runs).
4. Re-run the Alaska sample with the new caps to check the lower limit does not hurt other counties.
5. Change the confidence weights for unconfirmed parcels.
