"""Web UI: enter a parcel address and number, get the tax collecting agencies.
Run with: streamlit run app.py"""
import streamlit as st
import agencies
import agent


@st.cache_data
def load_reference_data():
    df = agencies.load()
    return agencies.agency_master(df), agencies.delinquent_collectors(df), agencies.truth_for_parcels(df)


master, always_add, truth = load_reference_data()
names = dict(zip(master.agency_number, master.agency_name))

st.title("Parcel to Tax Agencies")
st.caption("Finds the tax collecting agencies for a parcel: Census geocoding, web research by Claude, "
           "then a choice from the known agency list.")

# Optional: fill the form from a sample parcel so the result can be compared with Operations' answer.
sample = st.selectbox("Try a sample parcel (optional)", [""] + [
    f"{r.property_address_1}, {r.city}, {r.state} | {r.parcel_number}" for r in truth.head(200).itertuples()])
row = None
if sample:
    row = truth[truth.parcel_number == sample.split(" | ")[1]].iloc[0]

with st.form("parcel"):
    street = st.text_input("Street address", row.property_address_1 if row is not None else "")
    col1, col2, col3 = st.columns(3)
    city = col1.text_input("City", row.city if row is not None else "")
    state = col2.text_input("State (2 letters)", row.state if row is not None else "", max_chars=2)
    zip_code = col3.text_input("ZIP", row.zip_code if row is not None else "")
    parcel_number = st.text_input("Parcel number", row.parcel_number if row is not None else "")
    submitted = st.form_submit_button("Find agencies")

if submitted:
    state = state.upper()
    with st.spinner("Geocoding, researching and matching... this takes a minute"):
        geo, research, found = agent.find_agencies(street, city, state, zip_code, parcel_number, master, always_add)

    st.subheader("Location")
    if geo:
        st.write(f"**County:** {geo['county']}  \n"
                 f"**City:** {', '.join(geo['city']) or 'none (unincorporated)'}  \n"
                 f"**Township:** {', '.join(geo['township'])}  \n"
                 f"**School district:** {', '.join(geo['school_district'])}")
    else:
        st.warning("The Census geocoder could not find this address. The county named by Claude was used instead.")

    st.subheader(f"Tax collecting agencies ({len(found)})")
    st.dataframe([{"Agency number": n, "Agency": names[n]} for n in sorted(found)], hide_index=True,
                 width="stretch")

    if row is not None:
        expected = row.agency_number
        st.subheader("Compared with Operations' answer")
        st.write(f"**Correct:** {len(found & expected)} of {len(expected)} expected")
        st.write("**Missing:** " + (", ".join(sorted(names[n] for n in expected - found)) or "none"))
        st.write("**Not in Operations' answer:** " + (", ".join(sorted(names[n] for n in found - expected)) or "none"))

    with st.expander("Research notes from Claude"):
        st.text(research)
