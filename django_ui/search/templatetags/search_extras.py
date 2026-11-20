import json

from django import template
from django.urls import reverse
from django.utils.http import urlencode

register = template.Library()

STATUS_HELP = {
    "success": "The parcel is in the county's records and the agency was read from the county's statement.",
    "found_unverified": "A parcel and agency were found, but from web research, so they are not confirmed against county records.",
    "exception_multi_agency": "The agency was found, but a separate city, school or special-district collector was reported.",
    "agency_not_found": "The parcel was found but no collecting agency was identified.",
    "parcel_not_found": "No parcel matched. See the reason and the suggested parcels below.",
    "parcel_ambiguous": "Several parcels share this address. Pick one below.",
    "county_needed": "A parcel ID needs a state and county, or a valid address.",
    "county_unknown": "The state and county did not match a single county.",
    "invalid_address": "The address could not be validated.",
    "error": "The search raised an error.",
}


@register.filter
def status_help(status):
    return STATUS_HELP.get(status, "")


@register.filter
def status_tone(status):
    """CSS class for the status banner."""
    return "good" if status == "success" else "bad" if status in ("error", "invalid_address") else "warn"


@register.filter
def pdf_url(path):
    return f"{reverse('download')}?{urlencode({'path': path})}"


@register.filter
def pretty(value):
    return json.dumps(value, indent=2)


@register.filter
def spaced(value):
    """county_gis -> county gis"""
    return str(value or "").replace("_", " ")
