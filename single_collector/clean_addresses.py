"""Turn a raw loan/parcel list into the CSV that `python -m single_collector.run --file` accepts.

    python -m single_collector.clean_addresses single_collector/sample_files/ParcelList.csv

Reads the columns property_address_1, city, state, zip_code, parcel_number.
Writes <name>_clean.csv    (columns address, parcel_id, state, county) - rows the pipeline can search
       <name>_rejected.csv (the original row plus a reason)           - rows that need a person to fix
The agency_name column in the raw file is the answer, so it is never copied into the clean file.
"""
import csv
import re
import sys
from pathlib import Path


def clean_street(text):
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^(\d+)\s*,\s*", r"\1 ", text)      # "2301 , South Knik" -> "2301 South Knik"
    return text.rstrip(".,")


def clean_zip(text):
    digits = re.sub(r"\D", "", text)
    return digits[:5] if len(digits) in (5, 9) else ""


def clean_parcel_id(text):
    """Operations typed X, X1, XX ... where the parcel number is unknown; those are not parcel IDs."""
    text = text.strip()
    return "" if re.fullmatch(r"\d?[Xx]+\d{0,2}", text) else text


def problem(street, city, state, zip5):
    """The reason this row cannot be searched, or '' when it can."""
    if re.match(r"\d+ *(&|-|and) *\d+ ", street):
        return "Several street numbers in one address; search each one separately"
    if not re.match(r"[1-9]\d*[A-Za-z]?(-\d+)? +(?=.*[A-Za-z])", street) or re.search(r"acres|\+/-", street, re.I):
        return "No street number and name (placeholder, road only, or land description)"
    if not re.fullmatch(r"[A-Za-z]{2}", state):
        return f"State '{state}' is not a 2-letter code"
    if not city:
        return "No city"
    if not zip5:
        return "ZIP is not 5 or 9 digits"
    return ""


def main(path):
    source = Path(path)
    kept, rejected, seen = [], [], set()
    with open(source, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            street = clean_street(row["property_address_1"])
            city = re.sub(r"\s+", " ", row["city"]).strip()
            state = row["state"].strip().upper()
            zip5 = clean_zip(row["zip_code"])
            reason = problem(street, city, state, zip5)
            address = f"{street}, {city}, {state} {zip5}"
            key = (address.upper(), row["parcel_number"].strip())
            if not reason and key in seen:
                reason = "Same address and parcel number as an earlier row"
            if reason:
                rejected.append({**row, "reason": reason})
                continue
            seen.add(key)
            kept.append({"address": address, "parcel_id": clean_parcel_id(row["parcel_number"]), "state": "", "county": ""})

    with open(source.with_name(source.stem + "_clean.csv"), "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, ["address", "parcel_id", "state", "county"])
        writer.writeheader()
        writer.writerows(kept)
    with open(source.with_name(source.stem + "_rejected.csv"), "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, list(rejected[0]))
        writer.writeheader()
        writer.writerows(rejected)
    print(f"{len(kept)} searchable rows, {len(rejected)} rejected (of {len(kept) + len(rejected)})")


if __name__ == "__main__":
    main(sys.argv[1])
