"""Run the agent on a sample of parcels and compare with what Operations identified.
Usage: python evaluate.py [sample_size]"""
import sys
import agencies
import agent

df = agencies.load()
master = agencies.agency_master(df)
always_add = agencies.delinquent_collectors(df)
truth = agencies.truth_for_parcels(df).sample(int(sys.argv[1]) if len(sys.argv) > 1 else 10, random_state=1)

expected_total = found_total = correct_total = 0
for row in truth.itertuples():
    address = f"{row.property_address_1}, {row.city}, {row.state} {row.zip_code}"
    geo, research, found = agent.find_agencies(row.property_address_1, row.city, row.state, row.zip_code, row.parcel_number, master, always_add)
    hit = found & row.agency_number
    print(f"{address} | parcel {row.parcel_number}")
    names_by_number = dict(zip(master.agency_number, master.agency_name))
    print(f"  geocoded    : {geo}")
    print(f"  expected    : {sorted(names_by_number[n] for n in row.agency_number)}")
    print(f"  matched to  : {sorted(names_by_number[n] for n in found)}")
    print(f"  expected {len(row.agency_number)}, found {len(found)}, correct {len(hit)}"
          f"  (recall {len(hit)/len(row.agency_number):.0%}, precision {len(hit)/max(len(found),1):.0%})")
    expected_total += len(row.agency_number)
    found_total += len(found)
    correct_total += len(hit)

print(f"TOTAL over {len(truth)} parcels: expected {expected_total}, found {found_total}, correct {correct_total}"
      f"  (recall {correct_total/expected_total:.0%}, precision {correct_total/found_total:.0%})")
