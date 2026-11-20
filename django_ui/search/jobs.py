"""Runs a search in the background. The pipeline (python -m single_collector.run) can take minutes and drives a
headless browser, so each job runs it in a separate process from a worker thread and stores the result in the database."""
import csv
import json
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.utils import timezone

from .models import SearchJob

ACTIVE = set()  # ids of jobs whose worker thread is alive in this server process


def start(queries):
    job = SearchJob.objects.create(queries=queries)
    ACTIVE.add(str(job.id))
    threading.Thread(target=run, args=(job.id,), daemon=True).start()
    return job


def run(job_id):
    job = SearchJob.objects.get(pk=job_id)
    try:
        work = Path(tempfile.mkdtemp(prefix="search-"))
        queries_file, manifest = work / "queries.csv", work / "manifest.json"
        with open(queries_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["address", "parcel_id", "state", "county"], extrasaction="ignore")
            writer.writeheader()
            writer.writerows(job.queries)
        done = subprocess.run(
            [sys.executable, "-m", "single_collector.run", "--file", str(queries_file), "--manifest", str(manifest)],
            cwd=settings.ROOT, env={**os.environ, "PYTHONIOENCODING": "utf-8"}, capture_output=True, text=True,
            encoding="utf-8", timeout=settings.SEARCH_TIMEOUT_SECONDS)
        if manifest.exists():
            job.results, job.status = json.loads(manifest.read_text(encoding="utf-8")), SearchJob.Status.DONE
        else:
            job.status, job.error = SearchJob.Status.FAILED, (done.stderr or "The pipeline produced no results.")[-2000:]
    except Exception as error:  # a worker thread must always leave the job in a final state
        job.status, job.error = SearchJob.Status.FAILED, f"{type(error).__name__}: {error}"
    job.finished = timezone.now()
    job.save()
    ACTIVE.discard(str(job_id))
    connection.close()  # this thread opened its own database connection


def refresh(job):
    """A job left 'running' by a server restart has no worker any more: mark it failed instead of waiting forever."""
    if job.status == SearchJob.Status.RUNNING and str(job.id) not in ACTIVE:
        job.status, job.error, job.finished = SearchJob.Status.FAILED, "The server restarted while this search was running.", timezone.now()
        job.save()
    return job
