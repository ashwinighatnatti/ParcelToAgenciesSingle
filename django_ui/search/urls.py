from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("jobs/<uuid:pk>/", views.job, name="job"),
    path("jobs/<uuid:pk>/status/", views.job_status, name="job_status"),
    path("jobs/<uuid:pk>/results.csv", views.job_results, name="job_results"),
    path("jobs/<uuid:pk>/audit.xlsx", views.job_audit, name="job_audit"),
    path("use-parcel/", views.use_parcel, name="use_parcel"),
    path("history/", views.history, name="history"),
    path("quick/", views.quick, name="quick"),
    path("batch/", views.batch, name="batch"),
    path("triage/", views.triage_page, name="triage"),
    path("triage/<str:token>.csv", views.triage_csv, name="triage_csv"),
    path("triage-jev/", views.triage_jev_page, name="triage_jev"),
    path("rank/", views.rank, name="rank"),
    path("jurisdictions/", views.jurisdictions_page, name="jurisdictions"),
    path("download/", views.download, name="download"),
]
