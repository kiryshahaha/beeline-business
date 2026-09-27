import re

with open("backend/tests/t19_generator.py", "r", encoding="utf-8") as f:
    text = f.read()

replacement = """    add("work_type_required_skills", work_type_id=4, skill_id=1)

    add("appliances", id=1, code="ROUTER", name="Router")
    add("work_type_required_appliances", work_type_id=4, appliance_id=1, quantity=1)"""

text = text.replace('    add("work_type_required_skills", work_type_id=4, skill_id=1)', replacement)

# Add stock_inconsistent to edge_cases test
edge_cases_replacement = """                elif c == 7:
                    loc_id = 1000 + ticket_idx
                    add("locations", id=loc_id, building_id=area_id * 100 + 39, latitude=56.0, longitude=38.0, entrance_id=area_id * 100 + 39)
                elif c == 8:
                    # Stock shortage for work type 4
                    wt_id = 4
                    metadata["invariants"][ticket_idx] = "equipment_not_reserved"
"""

text = text.replace('                elif c == 7:\n                    loc_id = 1000 + ticket_idx\n                    add("locations", id=loc_id, building_id=area_id * 100 + 39, latitude=56.0, longitude=38.0, entrance_id=area_id * 100 + 39)', edge_cases_replacement)


with open("backend/tests/t19_generator.py", "w", encoding="utf-8") as f:
    f.write(text)
