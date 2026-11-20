"""Live Census services: batch geocoding, TIGERweb boundaries, and county lookup by name.
Single-address geocoding is geocode.py in the parent folder."""
import csv
import io
import re
import requests

BATCH_URL = "https://geocoding.geo.census.gov/geocoder/geographies/addressbatch"
TIGERWEB_URL = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/tigerWMS_Current/MapServer/identify"
# tigerWMS_Current layer ids: school districts (unified, secondary, elementary), cities, counties
SCHOOL_LAYERS, PLACE_LAYERS, COUNTY_LAYER, STATE_LAYER = [14, 16, 18], [26, 28], [82], 80
ADDRESS = re.compile(r"^(?P<street>.+?),\s*(?P<city>[^,]+),\s*(?P<state>[A-Za-z]{2})\s*(?P<zip>\d{5})?")


def geocode_batch(addresses):
    """Geocode up to 10,000 one-line addresses in one request.
    Returns {address: geo or None} with the keys matched_address, x, y, county_code."""
    rows, results = [], {}
    for i, address in enumerate(addresses):
        part = ADDRESS.match(address)
        if part is None:  # not in "street, city, ST zip" form: report no match instead of failing the whole batch
            results[address] = None
            continue
        rows.append([i, part["street"], part["city"], part["state"], part["zip"] or ""])
    if not rows:
        return results
    buffer = io.StringIO()
    csv.writer(buffer).writerows(rows)
    response = requests.post(
        BATCH_URL,
        data={"benchmark": "Public_AR_Current", "vintage": "Current_Current"},
        files={"addressFile": ("addresses.csv", buffer.getvalue())},
        timeout=600,
    )
    response.raise_for_status()
    for row in csv.reader(io.StringIO(response.text)):
        address = addresses[int(row[0])]
        if row[2] != "Match":
            results[address] = None
            continue
        x, y = map(float, row[5].split(","))
        results[address] = {"matched_address": row[4], "x": x, "y": y, "county_code": row[8] + row[9]}
    return results


def tigerweb_boundaries(x, y):
    """What boundaries contain this point: county, incorporated city (if any) and school districts."""
    params = {
        "geometry": f"{x},{y}", "geometryType": "esriGeometryPoint", "sr": 4326,
        "layers": "all:" + ",".join(str(i) for i in SCHOOL_LAYERS + PLACE_LAYERS + COUNTY_LAYER),
        "tolerance": 1, "mapExtent": f"{x-0.01},{y-0.01},{x+0.01},{y+0.01}", "imageDisplay": "400,400,96",
        "returnGeometry": "false", "f": "json",
    }
    response = requests.get(TIGERWEB_URL, params=params, timeout=60)
    response.raise_for_status()
    results = response.json()["results"]

    def attributes_in(layer_ids):
        return [r["attributes"] for r in results if r["layerId"] in layer_ids]

    county = attributes_in(COUNTY_LAYER)[0]
    return {
        "county": county["NAME"],
        "county_geoid": county["GEOID"],
        "incorporated_city": [a["NAME"] for a in attributes_in(PLACE_LAYERS)],  # empty = unincorporated county area
        "school_districts": [a["NAME"] for a in attributes_in(SCHOOL_LAYERS)],
    }


def query_layer(layer_id, where, fields):
    params = {"where": where, "outFields": fields, "returnGeometry": "false", "f": "json"}
    response = requests.get(f"{TIGERWEB_URL.rsplit('/', 1)[0]}/{layer_id}/query", params=params, timeout=60)
    response.raise_for_status()
    return [f["attributes"] for f in response.json()["features"]]


def resolve_county(state, county):
    """County code and name from a state abbreviation and a county name, using live Census data.
    Returns None unless exactly one county matches."""
    states = query_layer(STATE_LAYER, f"STUSAB='{re.sub('[^A-Za-z]', '', state).upper()}'", "STATE")
    if len(states) != 1:
        return None
    base = re.sub(r"\s+(county|parish|borough)$", "", county.strip(), flags=re.IGNORECASE).replace("'", "''")
    counties = query_layer(COUNTY_LAYER[0], f"STATE='{states[0]['STATE']}' AND UPPER(BASENAME)=UPPER('{base}')", "GEOID,NAME")
    return {"county_code": counties[0]["GEOID"], "county": counties[0]["NAME"]} if len(counties) == 1 else None
