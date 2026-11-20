"""The audit file: an Excel workbook that lets a reviewer check every answer against the sources it came from.

Sheets: Summary (one row per search), Trajectory (every step of every search), Websites, Web searches,
Confidence (the points behind each score) and Method (how the trajectory, the confidence score and the ranking work).
    build(results) -> bytes of the .xlsx
"""
import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

from single_collector import confidence, stages, trace

METHOD = [
    ("Trajectory", "Every search runs three stages in order: 1. validate the address, 2. find / validate the parcel, 3. find / validate the agency. "
                   "Each call to a public service or website, and each Claude call with its web searches and pages read, is recorded as one step."),
    ("Stage 1 sources", "US Census Geocoder (matches the address) and US Census TIGERweb (county, city, school districts at the matched point)."),
    ("Stage 2 sources", "County GIS parcel services for Maricopa AZ and King WA; for every other county, Claude's web search and page reads."),
    ("Stage 3 sources", "The county treasurer's statement page for Maricopa AZ and King WA (opened with a browser, read by Claude); "
                        "for every other county, Claude's web research."),
    ("Verified vs unverified", "A county adapter reads the county's own records, so its answer is 'verified'. Web research answers are 'found_unverified': "
                               "they depend on what Claude found online and should be checked against the websites listed here."),
    ("Confidence score", "Points are earned for the strength of the evidence at each stage (table below). Score = points earned / points possible x 100. "
                         "A parcel ID search has no address to check, so the address points are left out. No agency found = 0. "
                         f"Levels: {confidence.LEVELS}. The weights are a judgement, not a statistical calibration."),
    ("Ranking", stages.RANKING_RULE + " The 'Rank states' tab is separate: it ranks whole states by how few portals cover most homes."),
    ("Cost", "Claude input/output tokens and web searches, priced per stage (see the Summary and Trajectory sheets). Census and county map services are free."),
]


def write_sheet(workbook, title, header, rows, widths):
    sheet = workbook.create_sheet(title)
    sheet.append(header)
    for row in rows:
        sheet.append(row)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    sheet.freeze_panes = "A2"
    return sheet


def build(results):
    workbook = Workbook()
    workbook.remove(workbook.active)
    summary, steps, sites, searches, points = [], [], [], [], []
    for number, r in enumerate(results, start=1):
        query, agency, parcel = r["query"], r.get("agency") or {}, r.get("parcel") or {}
        audit, conf, cost = r.get("audit") or {}, r.get("confidence") or {}, r.get("cost") or {}
        summary.append([number, query.get("address") or "", query.get("parcel_id") or "", r["status"], parcel.get("county", ""),
                        parcel.get("parcel_id", ""), parcel.get("parcel_address", ""), agency.get("agency_name") or "",
                        conf.get("score", ""), conf.get("level", ""), conf.get("summary", ""), cost.get("total_usd", ""),
                        len(audit.get("steps", [])), len(audit.get("websites", [])), len(audit.get("web_searches", [])),
                        "\n".join(f"{s['stage']}: {s['summary']}" for s in audit.get("by_stage", []))])
        for s in audit.get("steps", []):
            steps.append([number, s["n"], trace.STAGES.get(s["stage"], s["stage"]), s["source"], s["action"], s.get("url") or "", s["request"],
                          s["outcome"], "\n".join(s.get("web_searches", [])), "\n".join(s.get("pages_read", [])),
                          "\n".join(s.get("claude_notes", [])), s.get("input_tokens", ""), s.get("output_tokens", ""), s.get("cost_usd", "")])
        for w in audit.get("websites", []):
            sites.append([number, w["step"], trace.STAGES.get(w["stage"], w["stage"]), w["url"], w["title"], w["how"]])
        for q in audit.get("web_searches", []):
            searches.append([number, q["step"], q["query"], "\n".join(q["results"])])
        for f in conf.get("factors", []):
            points.append([number, f["factor"], f["points"], f["possible"], f["why"]])
        if conf:
            points.append([number, "TOTAL", conf["points_earned"], conf["points_possible"], f"{conf['summary']} Level: {conf['level']}."])

    write_sheet(workbook, "Summary", ["Row", "Input address", "Input parcel ID", "Status", "County", "Parcel ID found", "Parcel address found",
                                      "Agency", "Confidence", "Level", "How the score came out", "Cost USD", "Steps", "Websites", "Web searches",
                                      "Trajectory by stage"], summary, [6, 38, 20, 18, 24, 20, 32, 40, 11, 9, 36, 10, 7, 9, 9, 90])
    write_sheet(workbook, "Trajectory", ["Row", "Step", "Stage", "Source", "Action", "URL", "Asked", "Result", "Claude web searches",
                                         "Pages Claude opened", "Claude's notes", "Input tokens", "Output tokens", "Cost USD"],
                steps, [6, 6, 24, 30, 34, 44, 44, 60, 44, 44, 60, 11, 11, 10])
    write_sheet(workbook, "Websites", ["Row", "Step", "Stage", "URL", "Page title", "How it was used"], sites, [6, 6, 24, 70, 44, 40])
    write_sheet(workbook, "Web searches", ["Row", "Step", "Search query", "Results returned by that Claude call"], searches, [6, 6, 60, 90])
    write_sheet(workbook, "Confidence", ["Row", "Evidence", "Points", "Possible", "Why"], points, [6, 16, 9, 9, 80])

    method = write_sheet(workbook, "Method", ["Topic", "How it works"], METHOD, [24, 130])
    method.append([])
    method.append(["Confidence points", "Evidence | points | possible | situation"])
    for key, (name, pts, possible, situation) in confidence.RULES.items():
        method.append([name, f"{pts} of {possible}: {situation}"])

    out = io.BytesIO()
    workbook.save(out)
    return out.getvalue()
