import csv
import io
import re

from django import forms

QUERY_KEYS = ("address", "parcel_id", "state", "county")
MAX_BATCH = 200
NEWLINE = chr(10)


class SearchForm(forms.Form):
    """One search: by parcel address, by parcel ID (which needs a state and county), or both."""
    MODES = [("address", "Parcel address"), ("parcel_id", "Parcel ID"), ("both", "Both (cross-checked)")]
    REQUIRED = {"address": ["address"], "parcel_id": ["parcel_id", "state", "county"], "both": ["address", "parcel_id"]}

    mode = forms.ChoiceField(choices=MODES, widget=forms.RadioSelect, initial="address", label="Search by")
    address = forms.CharField(required=False, max_length=200, label="Parcel address (street, city, ST ZIP)")
    parcel_id = forms.CharField(required=False, max_length=60, label="Parcel ID")
    state = forms.CharField(required=False, label="State (2 letters)", widget=forms.TextInput(attrs={"maxlength": 2}))
    county = forms.CharField(required=False, max_length=80, label="County (with or without the word County)")

    def clean(self):
        data = super().clean()
        for field in self.REQUIRED.get(data.get("mode"), []):
            if not (data.get(field) or "").strip():
                self.add_error(field, "Required for this kind of search.")
        if (data.get("state") or "").strip() and not re.fullmatch(r"[A-Za-z]{2}", data["state"].strip()):
            self.add_error("state", "Use the 2-letter state code, for example WA.")
        return data

    def query(self):
        """The search as the dict the pipeline expects. Fields that the chosen search type does not use are left empty."""
        d, mode = self.cleaned_data, self.cleaned_data["mode"]
        return {
            "address": d["address"].strip() if mode != "parcel_id" else "",
            "parcel_id": d["parcel_id"].strip() if mode != "address" else "",
            "state": d["state"].strip().upper() if mode == "parcel_id" else "",
            "county": d["county"].strip() if mode == "parcel_id" else "",
        }


def read_rows(text):
    """The rows of a batch file. Two layouts are accepted:
    - a header line naming the columns (address, parcel_id, state, county), separated by commas or pipes;
    - no header, one search per line as  address|parcel id  (the parcel id is optional)."""
    lines = [line for line in text.splitlines() if line.strip()]
    if lines and "address" in lines[0].lower() and ("|" in lines[0] or "," in lines[0]):
        rows = csv.DictReader(io.StringIO(NEWLINE.join(lines)), delimiter="|" if "|" in lines[0] else ",")
        return [{key: (row.get(key) or "").strip() for key in QUERY_KEYS} for row in rows]
    searches = []
    for line in lines:
        address, _, parcel_id = line.rpartition("|") if "|" in line else (line, "", "")
        searches.append({"address": address.strip(), "parcel_id": parcel_id.strip(), "state": "", "county": ""})
    return searches


class BatchForm(forms.Form):
    max_rows = MAX_BATCH
    lines = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 6}),
                            label="Or type one search per line: parcel address|parcel ID (the parcel ID is optional)")
    csv_file = forms.FileField(required=False, label="Upload a file (address|parcel ID per line, or a CSV with a header row)")
    first_rows = forms.IntegerField(required=False, min_value=1, label="Only process the first N rows (for a test run)")

    def clean(self):
        data = super().clean()
        upload = data.get("csv_file")
        queries = read_rows(upload.read().decode("utf-8-sig", errors="replace") if upload else data.get("lines") or "")
        queries = [q for q in queries if q["address"] or q["parcel_id"]]
        if data.get("first_rows"):
            queries = queries[:data["first_rows"]]
        if not queries:
            raise forms.ValidationError("Enter at least one address, or upload a file that has rows with an address or parcel ID.")
        if len(queries) > self.max_rows:
            raise forms.ValidationError(f"This form takes at most {self.max_rows} rows; this one has {len(queries)}. Use 'first N rows' or split the file.")
        data["queries"] = queries
        return data


class TriageForm(BatchForm):
    """Same inputs as a batch. Triage costs nothing (no Claude call), so it takes many more rows."""
    max_rows = 5000


class TriageJevForm(TriageForm):
    """Triage with Jev: one Jev call per row that needs it, so the batch is capped lower."""
    max_rows = 300
    threshold = forms.FloatField(required=False, min_value=0.5, max_value=0.95, initial=0.7,
                                 label="Confidence threshold: below this, the rule-based level is kept and the row is flagged for Claude review (0.5 to 0.95, default 0.7)")
