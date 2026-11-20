"""Loads the Operations team's sample data: the ground truth and the agency master list."""
import pandas as pd

FILE = "Parcels_With_Mulitple_Agencies.xlsx"


def load():
    df = pd.read_excel(FILE, dtype=str)
    df["state"] = df["state"].str.upper()
    return df


def agency_master(df):
    """One row per agency_number -> name and state. Used to turn Claude's names into agency numbers."""
    return df.drop_duplicates("agency_number")[["agency_number", "agency_name", "state"]]


def truth_for_parcels(df):
    """One row per (parcel, address) with the set of agency_numbers Operations identified."""
    keys = ["parcel_number", "property_address_1", "city", "state", "zip_code"]
    return df.groupby(keys)["agency_number"].apply(set).reset_index()


def delinquent_collectors(df, min_share=0.5):
    """Rule: agency_numbers of 'Delinquent' / 'Tax Claim' collectors to always add.
    Operations includes them for only some counties, so we add a county's collectors
    only if at least `min_share` of that county's sample parcels have one."""
    df = df.assign(county=df.agency_number.str[:5], is_delinquent=df.agency_name.str.contains("delinquent|tax claim", case=False))
    parcels_in_county = df.groupby("county").parcel_number.nunique()
    delinquent = df[df.is_delinquent]
    share = delinquent.groupby("county").parcel_number.nunique() / parcels_in_county
    counties = share[share >= min_share].index
    return set(delinquent[delinquent.county.isin(counties)].agency_number)
