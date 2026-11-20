"""Task 1: the 51-jurisdiction reference file (50 states + DC) and lookups into it."""
import json
from pathlib import Path

CONFIG = Path(__file__).with_name("jurisdictions_config.json")


def load():
    jurisdictions = json.loads(CONFIG.read_text())["jurisdictions"]
    assert len(jurisdictions) == 51, "config must list 50 states + DC"
    return {j["state"]: j for j in jurisdictions}


def get(state):
    return load()[state.upper()]


def state_for_fips(state_fips):
    return next(j for j in load().values() if j["fips"] == state_fips)


def tier_1_states():
    return sorted(s for s, j in load().items() if j["is_single_collector"])
