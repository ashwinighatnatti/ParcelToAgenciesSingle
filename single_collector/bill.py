"""Task 3: save the latest tax bill as a PDF. A missing bill is reported, never raised."""
import re
from pathlib import Path
import requests

DOWNLOADS = Path("downloads")


def save_pdf_bytes(content, state, county, parcel_id, tax_year):
    folder = DOWNLOADS / state / re.sub(r"\W+", "_", county)
    folder.mkdir(parents=True, exist_ok=True)
    safe = lambda text: re.sub(r"[^A-Za-z0-9.-]+", "_", str(text))
    path = folder / f"{safe(parcel_id)}_{safe(tax_year)}_bill.pdf"
    path.write_bytes(content)
    return str(path)


def render_page_to_pdf(url):
    """Fallback: the portal shows an HTML statement, so print the page to PDF in a headless browser."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(url, wait_until="networkidle", timeout=60000)
        content = page.pdf()
        browser.close()
    return content


def download_bill(bill_url, state, county, parcel_id, tax_year):
    if not (bill_url and parcel_id and tax_year):
        return {"available": False, "reason": "no public bill link, parcel id or tax year was found"}
    try:
        response = requests.get(bill_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
        response.raise_for_status()
        content = response.content
        if not content.startswith(b"%PDF"):
            content = render_page_to_pdf(bill_url)
    except Exception as error:  # network error, login wall, missing browser: report it, do not crash the pipeline
        return {"available": False, "reason": f"{type(error).__name__}: {str(error)[:200]}"}
    if not content.startswith(b"%PDF"):
        return {"available": False, "reason": "downloaded content is not a PDF"}
    return {"available": True, "tax_year": str(tax_year),
            "file_path": save_pdf_bytes(content, state, county, parcel_id, tax_year)}
