import uuid

from django.db import models


class SearchJob(models.Model):
    """One search (or one batch of searches) and its results. The pipeline runs in the background; see jobs.py."""

    class Status(models.TextChoices):
        RUNNING = "running"
        DONE = "done"
        FAILED = "failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created = models.DateTimeField(auto_now_add=True)
    finished = models.DateTimeField(null=True, blank=True)
    queries = models.JSONField()  # [{"address", "parcel_id", "state", "county"}, ...]
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.RUNNING)
    results = models.JSONField(null=True, blank=True)  # one pipeline result record per query
    error = models.TextField(blank=True)

    class Meta:
        ordering = ["-created"]

    @property
    def is_batch(self):
        return len(self.queries) > 1

    @property
    def title(self):
        """A short description of the first query, for headings and the history list."""
        q = self.queries[0]
        text = q.get("address") or f"Parcel {q.get('parcel_id')} ({q.get('state') or '?'}, {q.get('county') or '?'})"
        return f"{text} (+{len(self.queries) - 1} more)" if self.is_batch else text
