"""King County, WA (53033): parcel search in the county GIS service, statement from the Treasury payment site.
Same adapter contract as maricopa_az.py. The agency is read from the statement page, not stored here."""
import re
import requests

COUNTY_CODE = "53033"
PARCEL_SOURCE, STATEMENT_SOURCE = "King County GIS", "King County Treasury website"
PARCELS = "https://gismaps.kingcounty.gov/arcgis/rest/services/Property/KingCo_PropertyInfo/MapServer/2/query"
FIELDS = "PIN,ADDR_FULL,POSTALCTYNAME,ZIP5"


def parcel_rows(where):
    params = {"where": where, "outFields": FIELDS, "returnGeometry": "false", "f": "json", "resultRecordCount": 500}
    response = requests.get(PARCELS, params=params, timeout=60)
    response.raise_for_status()
    return [{"parcel_id": a["PIN"], "parcel_address": " ".join((a["ADDR_FULL"] or "").split()),
             "city": a["POSTALCTYNAME"] or "", "zip": a["ZIP5"] or ""}
            for a in (f["attributes"] for f in response.json()["features"])]


def search_by_parcel(parcel_id):
    digits = re.sub(r"\D", "", parcel_id)[:10]  # a 12-digit tax account number starts with the 10-digit parcel number
    return parcel_rows(f"PIN='{digits}'")


def rows_on_street(core_word, zip_code):
    word = re.sub(r"[^A-Z0-9]", "", core_word.upper())
    return parcel_rows(f"UPPER(ADDR_FULL) LIKE '%{word}%' AND ZIP5='{re.sub(r'[^0-9]', '', zip_code)}'")


def open_statement(page, parcel_id):
    """Show the tax year breakdown and the latest year's tax/fee distribution. Returns the tax year."""
    page.goto("https://payment.kingcounty.gov/Home/Index?app=PropertyTaxes", wait_until="domcontentloaded")
    page.wait_for_timeout(2500)
    page.fill("input[name=searchParcel]", parcel_id)
    page.press("input[name=searchParcel]", "Enter")
    page.get_by_text("Breakdown by Tax Year", exact=True).first.wait_for(timeout=30000)
    page.get_by_text("Breakdown by Tax Year", exact=True).first.click()
    page.wait_for_timeout(2500)
    distribution = page.get_by_text(re.compile(r"^\d{4} Tax / Fee Distribution$")).first
    tax_year = distribution.inner_text().split()[0]
    distribution.click()
    page.wait_for_timeout(2500)
    return tax_year
