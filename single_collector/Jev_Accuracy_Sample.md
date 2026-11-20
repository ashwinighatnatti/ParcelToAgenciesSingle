# Jev triage accuracy: 30-row labelled sample

Run 2026-11-19. Compares the rule-based triage and the Jev triage against what the full pipeline actually did on the same 30 rows.
Row-level data: `sample_files/jev_sample_30_results.csv`. Sample: `sample_files/jev_sample_30.csv`. Triage code: `triage.py`, `triage_jev.py`.

## How it was measured

- **Sample (stratified from the 260-row file by rule level):** 3 adapter rows, 12 medium by rule (one per state first), 9 complex in several-collector states, 6 complex with an address the Census could not match (3 junk, 3 real streets).
- **Truth:** each row was run through the full pipeline (2-search / 4-page cap, the current setting). Real outcome gives the true level:
  - **simple:** adapter county and `success`
  - **medium:** web route (no adapter) and `success` or `found_unverified`
  - **complex:** anything else (`parcel_not_found`, `county_needed`, `exception_multi_agency`, error, ambiguous, invalid)
  - Cost is not part of the label (the caps bound it).
- **Triagers compared:** rule-based; Jev for every answer; Jev with the 0.7 confidence threshold (below it, the rule level is kept). Jev model `jev-latest`.
- Two rows failed for reasons unrelated to difficulty (an Azure rate limit caused by running three chunks in parallel; a Claude JSON parsing error). They were run again on their own and the re-run is used.

## Results

| | Correct | Accuracy |
|---|---|---|
| Rule-based | 17 / 30 | 57% |
| Jev, every answer | 17 / 30 | 57% |
| Jev with 0.7 threshold, rule fallback | 17 / 30 | 57% |

True levels: complex 26, simple 2, medium 2. Pipeline statuses: parcel_not_found 19, county_needed 6, success 2, found_unverified 2, exception_multi_agency 1.

Confusion matrix, identical for rule-based and Jev (true down, predicted across: simple, medium, complex):

| True | simple | medium | complex |
|---|---|---|---|
| simple (2) | 2 | 0 | 0 |
| medium (2) | 0 | 1 | 1 |
| complex (26) | 1 | 11 | 14 |

**Cost of the sample:** $13.02 for the 30 rows (about 29 web searches; 20 web-route rows averaged $0.60). Estimate beforehand was $18 to $25. Triage itself costs $0 (rule-based) or Jev tokens only.

## What it shows

1. **Jev did not beat the rules on this sample.** Both predicted medium for 12 rows that failed to find a parcel, and both missed the same two rows.
2. **The sample is mostly failures.** With the 2-search cap, only 4 of 22 web-route rows found an agency (18%); 26 of 30 rows are complex by outcome. Neither triager captured "web research will probably not find the parcel", because most web rows look alike to both.
3. **Jev's low-confidence rows were mixed.** Illinois (0.67) and North Dakota (0.34): Jev said complex and was right, but the 0.7 threshold sent both back to the rule level (medium), which was wrong. With a lower threshold Jev would score higher on those two, but 30 rows cannot choose a threshold.
4. **The hard rule was wrong once.** The Mesa address `2240-2340 West University Drive` (a range) is in an adapter county and ended `parcel_not_found`. Jev would also have said simple (0.92), so it needs a rule on ranges, not Jev.
5. **One Jev signal looks useful and is not used in the level.** `parcel_id_wellformed`: all 7 placeholder IDs (X, X1, X6...) scored 0.01 to 0.08 and none found an agency; the 2 web rows that found one scored 0.93. Among matched web rows: 0 of 5 found with probability < 0.5, 2 of 16 found with >= 0.5. Too few rows to conclude.
6. **The 6 unmatched addresses all ended `county_needed`** (junk or real): the batch gives a parcel ID but no county, and a parcel number is only unique within a county. Jev separated the junk (3 of 6) from real streets (2) correctly, but the outcome was the same.

## Pipeline problems found

- A Claude reply with malformed JSON raised `JSONDecodeError` and ended the row as `error` (New Hampshire; fine on re-run).
- Running three batches in parallel hit the Azure limit of 250,000 uncached input tokens per minute (HTTP 429). Run batches one at a time.
- Placeholder parcel IDs (X, X1) are still sent as parcel numbers; in this sample all 7 failed.

## Limits of this measurement

- 30 rows, 2 simple and 2 medium: far too few to compare triagers or to tune a threshold.
- One run per row. Web research varies between runs (the same address can find a parcel once and not again), and Jev's confidence moved slightly between two runs of the same rows (for example 0.67 and 0.68).
- The truth depends on the 2-search cap. With the earlier 6-search cap more web rows found an agency (all five Alaska rows did), so "complex" here partly means "the cap was too low".
- The label counts `found_unverified` as success, even though the parcel may be wrong (as in the Foothill Plaza run).

## Next steps that would make the comparison meaningful

1. Label more rows, with at least 20 per level; many more medium and simple rows are needed.
2. Decide what "complex" should mean (failure to find a parcel, or need for manual work), and label rows that way.
3. Try using `parcel_id_wellformed` and `address_quality` as rules or as inputs to the level, and a range-address rule for adapter counties.
4. Fix the malformed-JSON error; blank placeholder parcel IDs before running.

---

# Update: 192 labelled rows

Run 2026-11-19. The 30-row sample was extended with 22 more adapter-county rows and 140 more web-route rows. Row-level data: `sample_files/jev_labelled_results.csv`. Same label definition and the same 2-search / 4-page cap as above.

## Label counts (target was at least 20 per level)

| True level | Rows | Target met |
|---|---|---|
| simple | 23 | yes |
| medium | 13 | **no** |
| complex | 156 | yes |

Medium stopped at 13 because the web route only found an agency for 13 of 168 rows (8%). The run stopped at the $70 spend cap set beforehand. Reaching 20 would have needed about 90 more web rows (roughly $45 to $50 more).

How the rows were obtained:
- **Simple (23):** only 3 distinct adapter addresses exist in the user's file, so 22 addresses and parcel IDs were drawn from the Maricopa and King GIS services. These are not rows from the user's file. 21 ended `success`, 1 `county_needed`. Cost $0.28.
- **Web rows:** 140 unrun web-route rows from the 260-row file, in random order. 2 ended `error` (malformed JSON from Claude, as before) and were re-run alone.
- Cost of all full runs, 192 rows: **$88.77**. Jev triage of 192 rows: 168 calls, 159,003 input and 31,656 output tokens, 4.9 s, no errors.

Pipeline statuses: parcel_not_found 148, success 26, found_unverified 10, county_needed 7, exception_multi_agency 1.

## Accuracy

| Triager | Correct | Accuracy |
|---|---|---|
| Rule-based | 109 / 192 | 57% |
| Jev, every answer | 107 / 192 | 56% |
| Jev with 0.7 threshold, rule fallback | 105 / 192 | 55% |

Confusion matrix, true down, predicted across (simple, medium, complex):

| | Rule-based | Jev raw | Jev with threshold |
|---|---|---|---|
| simple (23) | 23, 0, 0 | 23, 0, 0 | 23, 0, 0 |
| medium (13) | 0, 5, 8 | 0, 5, 8 | 0, 5, 8 |
| complex (156) | 1, 74, 81 | 1, 76, 79 | 1, 78, 77 |

Per level (rule-based): simple precision 23/24, recall 23/23; medium precision 5/79, recall 5/13; complex precision 81/89, recall 81/156. Jev is the same within 2 rows.

## What it shows

1. **Jev is no better than the rules, and slightly worse.** The 0.7 threshold sent more rows back to the rule level (medium) and lowered accuracy by 2 rows. Differences of 2 rows out of 192 are noise.
2. **The weakness is the same for both:** about 75 rows predicted medium were really complex (parcel not found). Both triagers say "medium" to almost every web-route row in a single-collector state, and 92% of web rows fail under the 2-search cap, so neither separates the rows that will succeed.
3. **Simple is solved by the adapter rule, not by Jev.** All 23 simple rows were adapter counties. The one miss is the Mesa range address.
4. **`parcel_id_wellformed` is a weak signal at this size.** Web rows with probability under 0.5: 3 of 51 found an agency (6%); 0.5 or more: 10 of 117 (9%). The earlier 30-row hint (0 of 5 against 2 of 16) does not hold up as a useful split.
5. **Cost:** Jev triage of 192 rows used about 190,000 tokens; no price is configured, so USD is not reported. A full web run cost about $0.55 per row on average.

## Limits

- Medium has only 13 rows, so medium recall (5/13) is uncertain.
- Simple rows are GIS-sampled addresses, not the user's data; they test the adapter rule, not Jev.
- Labels come from one run per row and depend on the 2-search cap. With a higher cap, more web rows would be medium and the true level mix would change.
- `found_unverified` counts as medium even when the parcel may be wrong.

## Conclusion

On 192 labelled rows, neither the rule-based nor the Jev triage predicts web-route outcomes better than about 57%, because they cannot tell which web rows will succeed. Jev adds nothing over the rules as configured. A change to the inputs (county, parcel-ID format, whether the county has a searchable portal) or to the label is needed before a Jev experiment can be expected to win.
