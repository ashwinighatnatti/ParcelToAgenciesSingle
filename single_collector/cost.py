"""What one search cost, from the usage of every Claude call it made (agent.USAGE).

Prices are US dollars and can be overridden in .env to match your Azure contract:
  COST_INPUT_PER_MTOK, COST_OUTPUT_PER_MTOK, COST_WEB_SEARCH_EACH
The defaults are Anthropic's published list prices for an Opus-class model and are an assumption:
check them against the Azure invoice.
"""
import os

import agent

INPUT_PER_MTOK = float(os.environ.get("COST_INPUT_PER_MTOK", 5.00))
OUTPUT_PER_MTOK = float(os.environ.get("COST_OUTPUT_PER_MTOK", 25.00))
WEB_SEARCH_EACH = float(os.environ.get("COST_WEB_SEARCH_EACH", 0.01))  # $10 per 1,000 searches
CACHE_WRITE_FACTOR, CACHE_READ_FACTOR = 1.25, 0.10                     # multiples of the input price


def mark():
    """Position in the usage log; two of them delimit a stage."""
    return len(agent.USAGE)


def between(start, end):
    """The cost of the Claude calls made between two mark() values."""
    calls = agent.USAGE[start:end]
    total = lambda key: sum(call[key] for call in calls)
    per_token = INPUT_PER_MTOK / 1e6
    input_usd = (total("input") + total("cache_write") * CACHE_WRITE_FACTOR + total("cache_read") * CACHE_READ_FACTOR) * per_token
    output_usd = total("output") * OUTPUT_PER_MTOK / 1e6
    search_usd = total("web_searches") * WEB_SEARCH_EACH
    return {"claude_calls": len(calls), "input_tokens": total("input"), "output_tokens": total("output"),
            "cache_tokens": total("cache_write") + total("cache_read"), "web_searches": total("web_searches"),
            "input_usd": round(input_usd, 4), "output_usd": round(output_usd, 4), "web_search_usd": round(search_usd, 4),
            "total_usd": round(input_usd + output_usd + search_usd, 4)}


def combine(stages):
    """Add up the per-stage costs: {stage name: cost dict} -> one total plus the breakdown."""
    keys = [k for k in next(iter(stages.values())) if k != "total_usd"]
    total = {k: round(sum(s[k] for s in stages.values()), 4) for k in keys}
    total["total_usd"] = round(sum(s["total_usd"] for s in stages.values()), 4)
    return {**total, "by_stage": stages, "prices": {"input_per_mtok": INPUT_PER_MTOK, "output_per_mtok": OUTPUT_PER_MTOK,
                                                    "web_search_each": WEB_SEARCH_EACH}}
