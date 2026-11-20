import csv
import re
import uuid

from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from single_collector import audit_file, census, confidence, jurisdictions, rank_states, stages, triage, triage_jev
from single_collector.portals import PORTALS

from . import jobs
from .forms import BatchForm, SearchForm, TriageForm, TriageJevForm
from .models import SearchJob


def index(request):
    """Start a search. It runs in the background; the browser goes to the job page and waits there."""
    form = SearchForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        return redirect("job", pk=jobs.start([form.query()]).pk)
    rules = [{"evidence": e, "points": p, "possible": possible, "situation": situation} for e, p, possible, situation in confidence.RULES.values()
             if p or e == "Adjustment"]  # the zero-point rows only describe the failures
    return render(request, "search/index.html", {"form": form, "rules": rules, "levels": confidence.LEVELS, "ranking_rule": stages.RANKING_RULE})


def job(request, pk):
    job = jobs.refresh(get_object_or_404(SearchJob, pk=pk))
    single = job.results[0] if job.results and not job.is_batch else None
    return render(request, "search/job.html", {"job": job, "result": single})


def job_status(request, pk):
    job = jobs.refresh(get_object_or_404(SearchJob, pk=pk))
    return JsonResponse({"status": job.status, "elapsed": int((timezone.now() - job.created).total_seconds())})


@require_POST
def use_parcel(request):
    """The user picked one of the suggested parcels: search again by that parcel ID in the same county."""
    parcel_id = request.POST.get("parcel_id", "").strip()
    state, county = request.POST.get("state", "").strip(), request.POST.get("county", "").strip()
    if not parcel_id or not county or not re.fullmatch(r"[A-Za-z]{2}", state):
        raise Http404("A parcel ID, state and county are needed.")
    return redirect("job", pk=jobs.start([{"address": "", "parcel_id": parcel_id, "state": state.upper(), "county": county}]).pk)


def history(request):
    searches = [jobs.refresh(j) for j in SearchJob.objects.all()[:50]]
    return render(request, "search/history.html", {"searches": searches})


def quick(request):
    """Stages 1 and 2 only, answered immediately. Counties without an adapter need Claude's web research, which takes
    minutes, so those are sent to the full search instead."""
    form = SearchForm(request.POST or None)
    context = {"form": form}
    if request.method == "POST" and form.is_valid():
        query = {key: value or None for key, value in form.query().items()}
        try:
            check = stages.validate_address(query)
            county_code = check.get("county_code")
            if county_code is None and query["parcel_id"]:
                county = census.resolve_county(query["state"], query["county"])
                county_code = county["county_code"] if county else None
            context["check"] = check
            if county_code is not None and county_code not in PORTALS:
                context["no_adapter"] = True
            else:
                parcel = stages.find_validate_parcel(query, check)
                if check["valid"] is None and parcel["status"] == "matched":  # parcel search: validate the parcel's own address
                    context["check"] = stages.validate_address({"address": parcel["full_address"]})
                context["parcel"] = parcel
        except Exception as error:  # a network problem should show as a message, not a server error page
            context["error"] = f"{type(error).__name__}: {error}"
    return render(request, "search/quick.html", context)


def batch(request):
    form = BatchForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        return redirect("job", pk=jobs.start(form.cleaned_data["queries"]).pk)
    return render(request, "search/batch.html", {"form": form})


TRIAGE_DIR = settings.ROOT / "output" / "triage"
TRIAGE_COLUMNS = ["row", "address", "parcel_id", "state", "level", "cause", "meaning", "reason", "route", "county_code", "matched_address", "full_run_estimate_usd"]


def triage_csv(request, token):
    """The CSV saved by a triage run."""
    path = TRIAGE_DIR / f"triage_{token}.csv"
    if not path.is_file():
        raise Http404("No such triage file.")
    return FileResponse(open(path, "rb"), content_type="text/csv; charset=utf-8", as_attachment=True, filename="triage_results.csv")


def triage_page(request):
    """Sort a batch into simple / medium / complex before running it. Free: one Census request, no Claude call."""
    form = TriageForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        result = triage.triage(form.cleaned_data["queries"])
        token = uuid.uuid4().hex[:12]  # the CSV is saved so the page can link to it and still show the summary
        TRIAGE_DIR.mkdir(parents=True, exist_ok=True)
        with open(TRIAGE_DIR / f"triage_{token}.csv", "w", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, fieldnames=TRIAGE_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(result["rows"])
        levels = [(key, triage.LEVELS[key][0], triage.LEVELS[key][1], result["summary"][key], [r for r in result["rows"] if r["level"] == key])
                  for key in triage.LEVELS]
        return render(request, "search/triage.html", {"form": form, "result": result, "levels": levels, "token": token})
    return render(request, "search/triage.html", {"form": form})


JEV_COLUMNS = ["row", "address", "parcel_id", "state", "rule_level", "jev_level", "jev_confidence", "jev_probabilities", "final_level",
               "needs_claude", "decided_by", "address_quality", "parcel_id_wellformed", "public_portal_likely", "billing_offices",
               "cause", "reason", "county_code", "matched_address", "input_tokens", "output_tokens", "error"]


def triage_jev_page(request):
    """Triage with the Jev model next to the rule-based level. One free Census request plus one Jev call per row that needs it."""
    form = TriageJevForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        result = triage_jev.triage_jev(form.cleaned_data["queries"], form.cleaned_data.get("threshold") or triage_jev.DEFAULT_THRESHOLD)
        token = uuid.uuid4().hex[:12]
        TRIAGE_DIR.mkdir(parents=True, exist_ok=True)
        with open(TRIAGE_DIR / f"triage_{token}.csv", "w", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, fieldnames=JEV_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(result["rows"])
        levels = [(key, triage.LEVELS[key][0], result["summary"][key], [r for r in result["rows"] if r["final_level"] == key])
                  for key in triage.LEVELS]
        review = [r for r in result["rows"] if r["needs_claude"]]
        return render(request, "search/triage_jev.html", {"form": form, "result": result, "levels": levels, "token": token, "review": review})
    return render(request, "search/triage_jev.html", {"form": form})


def rank(request):
    """Fetches live county data from the Census, so it runs only when asked."""
    context = {}
    if request.method == "POST":
        try:
            ranked = rank_states.rank_states()
            context["tiers"] = [("Tier 1A: high confidence", [r for r in ranked if r["confidence"] == "high"]),
                                ("Tier 1B: medium confidence, validate first", [r for r in ranked if r["confidence"] == "medium"])]
        except Exception as error:
            context["error"] = f"{type(error).__name__}: {error}"
    return render(request, "search/rank.html", context)


def jurisdictions_page(request):
    rows = list(jurisdictions.load().values())
    only_single = request.GET.get("single") == "1"
    return render(request, "search/jurisdictions.html",
                  {"rows": [r for r in rows if r["is_single_collector"] or not only_single], "only_single": only_single,
                   "single_count": sum(r["is_single_collector"] for r in rows), "total": len(rows)})


RESULT_COLUMNS = ["row", "input_address", "input_parcel_id", "status", "reason", "county", "parcel_id", "parcel_address", "parcel_verified",
                  "agency_name", "payment_address", "portal_url", "collector_model", "agency_validated", "separate_collectors",
                  "tax_year", "bill_file", "confidence_score", "confidence_level", "claude_calls", "web_searches", "cost_usd"]


def result_row(number, r):
    parcel, agency, bill = r.get("parcel") or {}, r.get("agency") or {}, r.get("tax_bill") or {}
    confidence, cost = r.get("confidence") or {}, r.get("cost") or {}
    reason = r.get("reason") or agency.get("reason") or ""
    return {"row": number, "input_address": r["query"].get("address") or "", "input_parcel_id": r["query"].get("parcel_id") or "",
            "status": r["status"], "reason": reason, "county": parcel.get("county", ""), "parcel_id": parcel.get("parcel_id", ""),
            "parcel_address": parcel.get("parcel_address", ""), "parcel_verified": parcel.get("verified", ""),
            "agency_name": agency.get("agency_name") or "", "payment_address": agency.get("payment_address") or "",
            "portal_url": agency.get("portal_url") or "", "collector_model": agency.get("collector_model", ""),
            "agency_validated": agency.get("validated", ""), "separate_collectors": "; ".join(agency.get("separate_collectors") or []),
            "tax_year": agency.get("tax_year") or "", "bill_file": bill.get("file_path", ""),
            "confidence_score": confidence.get("score", ""), "confidence_level": confidence.get("level", ""),
            "claude_calls": cost.get("claude_calls", ""), "web_searches": cost.get("web_searches", ""), "cost_usd": cost.get("total_usd", "")}


def job_results(request, pk):
    """The results of a finished job as a CSV file, one row per search, in the order they were entered."""
    job = get_object_or_404(SearchJob, pk=pk)
    if not job.results:
        raise Http404("This job has no results yet.")
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="agency_results_{str(job.pk)[:8]}.csv"'
    response.write("﻿")  # so Excel reads it as UTF-8
    writer = csv.DictWriter(response, fieldnames=RESULT_COLUMNS)
    writer.writeheader()
    writer.writerows(result_row(n, r) for n, r in enumerate(job.results, start=1))
    return response


def job_audit(request, pk):
    """The audit workbook for a finished job: every step, website and web search behind each answer."""
    job = get_object_or_404(SearchJob, pk=pk)
    if not job.results:
        raise Http404("This job has no results yet.")
    response = HttpResponse(audit_file.build(job.results),
                            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="audit_file_{str(job.pk)[:8]}.xlsx"'
    return response


def download(request):
    """Serve a saved bill. Only PDFs inside the downloads folder can be requested."""
    requested = (settings.ROOT / request.GET.get("path", "")).resolve()
    if settings.DOWNLOADS_DIR.resolve() not in requested.parents or requested.suffix.lower() != ".pdf" or not requested.is_file():
        raise Http404("No such bill.")
    return FileResponse(open(requested, "rb"), content_type="application/pdf", filename=requested.name)
