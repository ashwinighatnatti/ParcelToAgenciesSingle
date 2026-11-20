"""County adapters, keyed by county code (state FIPS + county FIPS). An adapter gives deterministic, verified parcel
search and statement access for one county. Counties without an adapter are handled by Claude's live web research.
Add a module here to support another county (see Developer_Guide.html)."""
from playwright.sync_api import sync_playwright

from single_collector.portals import king_wa, maricopa_az

PORTALS = {module.COUNTY_CODE: module for module in (maricopa_az, king_wa)}


def capture_statement(adapter, parcel_id):
    """Open the county portal in a headless browser, show the latest statement, and return what is on it:
    the PDF, the visible text (so the agency can be read from it), the page title and URL, and the tax year."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.set_default_timeout(30000)
        tax_year = adapter.open_statement(page, parcel_id)
        captured = {"tax_year": tax_year, "pdf": page.pdf(), "page_text": page.inner_text("body"),
                    "page_title": page.title(), "page_url": page.url}
        browser.close()
    return captured
