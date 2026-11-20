"""Address -> county, city, township and school district using the free US Census geocoder (no API key)."""
import requests

URL = "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress"


def names(geographies, layer_contains):
    """Names of all returned layers whose title contains the given text."""
    return [item["NAME"] for layer, items in geographies.items() if layer_contains in layer for item in items]


def geocode(street, city, state, zip_code):
    """Returns the geography of the address, or None if the Census cannot find it."""
    return geocode_oneline(f"{street}, {city}, {state} {zip_code}")


def geocode_oneline(address):
    """Same as geocode() but takes the address as a single line."""
    params = {
        "address": address,
        "benchmark": "Public_AR_Current",
        "vintage": "Current_Current",
        "layers": "all",
        "format": "json",
    }
    response = requests.get(URL, params=params, timeout=60)
    response.raise_for_status()
    matches = response.json()["result"]["addressMatches"]
    if not matches:
        return None
    match = matches[0]
    geographies = match["geographies"]
    county = geographies["Counties"][0]
    return {
        "county_code": county["GEOID"],  # state+county code, same as the first 5 digits of agency_number
        "county": county["NAME"],
        "city": names(geographies, "Incorporated Places"),
        "township": names(geographies, "County Subdivisions"),
        "school_district": names(geographies, "School Districts"),
        "matched_address": match["matchedAddress"],
        "x": match["coordinates"]["x"],
        "y": match["coordinates"]["y"],
    }
