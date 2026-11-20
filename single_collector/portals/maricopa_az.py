"""Maricopa County, AZ (04013): parcel search in the Assessor's GIS service, statement from the Treasurer's site.

County adapter contract (see portals/__init__.py):
  search_by_parcel(parcel_id)      -> list of parcel rows
  rows_on_street(core_word, zip)   -> list of parcel rows whose address contains the word, in that ZIP
  open_statement(page, parcel_id)  -> tax year; leaves the latest statement showing on the page
A parcel row is {"parcel_id", "parcel_address", "city", "zip"}. Nothing about the agency is stored here:
the agency is read from the statement page itself.
"""
import re
import requests

COUNTY_CODE = "04013"
PARCEL_SOURCE, STATEMENT_SOURCE = "Maricopa County Assessor GIS", "Maricopa County Treasurer website"
PARCELS = "https://gis.mcassessor.maricopa.gov/arcgis/rest/services/Parcels/MapServer/0/query"
FIELDS = "APN_DASH,PHYSICAL_ADDRESS,PHYSICAL_CITY,PHYSICAL_ZIP"


def parcel_rows(where):
    params = {"where": where, "outFields": FIELDS, "returnGeometry": "false", "f": "json", "resultRecordCount": 500}
    response = requests.get(PARCELS, params=params, timeout=60)
    response.raise_for_status()
    rows = []
    for feature in response.json()["features"]:
        a = feature["attributes"]
        city, zip_code = a["PHYSICAL_CITY"] or "", a["PHYSICAL_ZIP"] or ""
        address = " ".join((a["PHYSICAL_ADDRESS"] or "").split())  # the field is padded: "330 W HOLLY ST   PHOENIX  85003"
        street = re.sub(rf"\s*{re.escape(city)}\s*{re.escape(zip_code)}$", "", address)
        rows.append({"parcel_id": a["APN_DASH"], "parcel_address": street, "city": city, "zip": zip_code})
    return rows


def search_by_parcel(parcel_id):
    dashed = re.sub(r"[^0-9A-Za-z-]", "", parcel_id).upper()
    plain = dashed.replace("-", "")
    return parcel_rows(f"APN_DASH='{dashed}' OR APN='{plain}'")


def rows_on_street(core_word, zip_code):
    word = re.sub(r"[^A-Z0-9]", "", core_word.upper())
    return parcel_rows(f"UPPER(PHYSICAL_ADDRESS) LIKE '%{word}%' AND PHYSICAL_ZIP='{re.sub(r'[^0-9]', '', zip_code)}'")


def open_statement(page, parcel_id):
    """Show the latest tax year's payment coupon (tax breakdown) on the page. Returns the tax year."""
    page.goto(f"https://treasurer.maricopa.gov/PropertyTaxInformation/?parcel={parcel_id.replace('-', '')}",
              wait_until="domcontentloaded")
    page.wait_for_timeout(5000)
    page.get_by_text("Payment Coupon", exact=True).first.click()
    page.wait_for_timeout(2500)
    page.locator(".k-picker").first.click()
    page.wait_for_timeout(1000)
    latest_year = page.locator(".k-list-item").first
    tax_year = latest_year.inner_text().strip()
    latest_year.click()
    page.wait_for_timeout(1000)
    page.locator("button.create-button").click()
    page.get_by_text("Tax Breakdown").wait_for(timeout=20000)
    return tax_year
