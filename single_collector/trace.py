"""The trail of one search: every public service called, every Claude web search and page read, and what each returned.

run.process() calls start() first, then each stage sets its name with stage(). The code that talks to a source calls
add() (a public service) or claude() (a Claude call) right after it gets the answer. report() turns the trail into the
`audit` block of the result: the steps, the websites touched, the web searches run, and a one-line summary per stage.
"""
import agent
from single_collector import cost

STAGES = {"validate_address": "1. Validate address", "find_validate_parcel": "2. Find / validate parcel",
          "find_validate_agency": "3. Find / validate agency"}
STEPS, CURRENT = [], {"stage": None}


def start():
    STEPS.clear()


def stage(name):
    CURRENT["stage"] = name


def add(source, action, request, outcome, url=None):
    """A call to a public service or a county website, with what was asked and what came back."""
    STEPS.append({"n": len(STEPS) + 1, "stage": CURRENT["stage"], "kind": "service", "source": source, "action": action,
                  "url": url, "request": request, "outcome": outcome})


def claude(action, request, outcome):
    """The Claude call that has just returned (the last entry of agent.USAGE): its searches, pages and cost."""
    call = agent.USAGE[-1]
    STEPS.append({"n": len(STEPS) + 1, "stage": CURRENT["stage"], "kind": "claude", "source": "Claude on Azure AI Foundry",
                  "action": action, "url": None, "request": request, "outcome": outcome,
                  "web_searches": call["queries"], "search_results": call["results"], "pages_read": call["fetched"],
                  "claude_notes": [note[:1500] for note in call["notes"]], "server_code_runs": call["code_runs"],
                  "input_tokens": call["input"], "output_tokens": call["output"],
                  "cost_usd": cost.between(len(agent.USAGE) - 1, len(agent.USAGE))["total_usd"]})


def websites():
    """Every site touched, once each, with how it was used."""
    seen = {}

    def note(url, kind, title, step):
        if url and (url, kind) not in seen:
            seen[(url, kind)] = {"url": url, "how": kind, "title": title or "", "step": step["n"], "stage": step["stage"]}

    for step in STEPS:
        note(step.get("url"), "public service or county site called by the pipeline" if step["kind"] == "service" else "", "", step)
        for url in step.get("pages_read", []):
            note(url, "page opened by Claude", "", step)
        for hit in step.get("search_results", []):
            note(hit["url"], "returned by a Claude web search", hit["title"], step)
    return list(seen.values())


def report():
    steps = [dict(step) for step in STEPS]
    by_stage = []
    for key, label in STAGES.items():
        mine = [s for s in steps if s["stage"] == key]
        by_stage.append({"stage": label, "steps": len(mine),
                         "summary": " | ".join(f"{s['source']}: {s['outcome']}" for s in mine) or "No step was needed."})
    searches = [{"step": s["n"], "query": q, "results": [h["url"] for h in s["search_results"]]}
                for s in steps if s["kind"] == "claude" for q in s["web_searches"]]
    return {"steps": steps, "websites": websites(), "web_searches": searches, "by_stage": by_stage}
