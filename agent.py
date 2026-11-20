"""Single-agent solution in two steps:
1. Claude (with web search) researches the property: which county, which taxing entities.
2. Claude picks, from our agency master list for that county, the agencies that collect the tax.
"""
import os
import re
from anthropic import AnthropicFoundry
from dotenv import load_dotenv

from geocode import geocode

load_dotenv()  # reads .env in the working folder
_missing = [k for k in ("AZURE_ANTHROPIC_API_KEY", "AZURE_ANTHROPIC_API_ENDPOINT", "AZURE_ANTHROPIC_DEPLOYMENT_NAME") if not os.environ.get(k)]
if _missing:
    raise SystemExit(f"Missing {', '.join(_missing)}. Copy .env.example to .env in the project folder and fill it in.")
client = AnthropicFoundry(
    api_key=os.environ["AZURE_ANTHROPIC_API_KEY"],
    base_url=os.environ["AZURE_ANTHROPIC_API_ENDPOINT"],
)
MODEL = os.environ["AZURE_ANTHROPIC_DEPLOYMENT_NAME"]  # on Azure, `model` is the deployment name


USAGE = []  # one entry per Claude call, as billed; single_collector/cost.py prices it and trace.py reports it


def what_claude_did(content):
    """What a response shows of Claude's work: the searches it ran, the results it got back, the pages it opened,
    and the text it wrote along the way. Web search and fetch run server-side, so these blocks are the only record."""
    work = {"queries": [], "results": [], "fetched": [], "notes": [], "code_runs": 0}
    for block in content:
        if block.type == "text" and block.text.strip():
            work["notes"].append(block.text.strip())
        elif block.type == "server_tool_use":
            if block.name == "web_search":
                work["queries"].append(block.input.get("query", ""))
            elif block.name == "web_fetch":
                work["fetched"].append(block.input.get("url", ""))
            else:
                work["code_runs"] += 1  # the 20260209 tools run their filtering as server-side code
        elif block.type == "web_search_tool_result" and isinstance(block.content, list):
            work["results"] += [{"title": r.title, "url": r.url} for r in block.content if r.type == "web_search_result"]
    return work


def ask(prompt, tools=None):
    """Send one prompt; return only the text written after the last search call (earlier text is narration)."""
    response = client.messages.create(
        model=MODEL, max_tokens=4000, tools=tools or [], messages=[{"role": "user", "content": prompt}]
    )
    usage, server_tools = response.usage, response.usage.server_tool_use
    USAGE.append({"input": usage.input_tokens, "output": usage.output_tokens,
                  "cache_write": usage.cache_creation_input_tokens or 0, "cache_read": usage.cache_read_input_tokens or 0,
                  "web_searches": getattr(server_tools, "web_search_requests", 0) or 0,
                  "web_fetches": getattr(server_tools, "web_fetch_requests", 0) or 0,
                  **what_claude_did(response.content)})
    answer = []
    for block in response.content:
        if block.type == "text":
            answer.append(block.text)
        else:
            answer = []
    return "".join(answer)


def facts_sentence(geo):
    if geo is None:
        return ""
    return (f" Census geocoding places the address in {geo['county']}, city/town: {geo['city'] or 'none (unincorporated)'}, "
            f"township: {geo['township']}, school district: {geo['school_district']}. Treat these as correct.")


def research_property(address, parcel_number, geo):
    """Step 1: same question as prompt.txt, plus the county on the first line."""
    prompt = (
        f"Identify and list *all * governmental and quasi-governmental entities that levy property taxes "
        f"for the property located at {address} and if parcel number exists use parcel number {parcel_number} ."
        f"Provide only the names in a clean list, without any additional explanation. "
        f"Start with one line in the form 'County: <county name>'."
        f"{facts_sentence(geo)}"
    )
    return ask(prompt, tools=[{"type": "web_search_20260209", "name": "web_search"}])


def county_agencies(research, state, master, geo):
    """Agency numbers start with state+county code, so the county's own agency gives us all agencies of that county."""
    in_state = master[master.state == state]
    if geo:
        return in_state[in_state.agency_number.str.startswith(geo["county_code"])]
    # Address not found by the geocoder: fall back to the county Claude named.
    county = re.search(r"County:\s*(.+?)(?:\s+County)?\s*$", research, re.MULTILINE | re.IGNORECASE).group(1)
    names = in_state.agency_name.str.lower()
    named_for_county = in_state[names.str.startswith(county.lower() + " county") | names.str.contains(f"({county.lower()})", regex=False)]
    prefix = named_for_county.agency_number.str[:5].mode().iloc[0]
    return in_state[in_state.agency_number.str.startswith(prefix)]


def pick_agencies(address, parcel_number, research, candidates, geo):
    """Step 2: Claude chooses from the candidate list, so it cannot invent agency names."""
    options = "\n".join(f"{num}: {name}" for num, name in zip(candidates.agency_number, candidates.agency_name))
    prompt = (
        f"Property: {address}, parcel number {parcel_number}.\n\n"
        f"Research notes on the taxing entities:\n{research}\n"
        f"{facts_sentence(geo)}\n\n"
        f"Below are the tax collecting agencies we track for this county. Choose the ones that collect property "
        f"tax for this property. A county that collects on behalf of its flood control, hospital or similar "
        f"districts counts as the county only. Include a special district only if it applies to this property.\n"
        f"{options}\n\n"
        f"Answer with the agency numbers only, separated by commas."
    )
    chosen = set(re.findall(r"\d{9}", ask(prompt)))
    return chosen & set(candidates.agency_number)


def find_agencies(street, city, state, zip_code, parcel_number, master, always_add):
    address = f"{street}, {city}, {state} {zip_code}"
    geo = geocode(street, city, state, zip_code)
    research = research_property(address, parcel_number, geo)
    candidates = county_agencies(research, state, master, geo)
    chosen = pick_agencies(address, parcel_number, research, candidates, geo)
    return geo, research, chosen | (always_add & set(candidates.agency_number))  # delinquent/tax claim rule
