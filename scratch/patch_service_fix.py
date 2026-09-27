import re

with open("backend/app/modules/tickets/service.py", "r", encoding="utf-8") as f:
    content = f.read()

# Fix the patch
def_recalculate = """    if result.get("routes"):
        r = result["routes"][0]
        rc = RouteCreate(worker_id=r.worker_id, transport_type=r.transport_type, stops=[{"ticket_id": s.ticket_id, "location_id": s.location_id, "sequence": s.sequence, "arrival_at": s.arrival_at, "service_start_at": s.service_start_at, "service_end_at": s.service_end_at} for s in r.stops], geometry=r.geometry, legs=r.legs)
"""

fix_recalculate = """    if result.get("routes"):
        r = result["routes"][0]
        from pydantic import BaseModel
        stops_dump = [{"location_id": s.location_id, "ticket_id": s.ticket_id, "arrival_at": s.arrival_at.isoformat(), "service_start_at": s.service_start_at.isoformat(), "service_end_at": s.service_end_at.isoformat(), "waiting_minutes": s.waiting_minutes, "effective_service_minutes": s.effective_service_minutes, "duration_source": s.duration_source} for s in r.stops]
        path_props = {"kind": "path", "source": "provided", "legs": [l.model_dump(mode="json") for l in r.legs]} if r.legs else None
        rc = RouteCreate.model_validate({"worker_id": r.worker_id, "route_date": route_date, "stops": stops_dump, "geometry": r.geometry.model_dump(mode="json") if r.geometry else None, "path_properties": path_props})
"""

content = content.replace(def_recalculate, fix_recalculate)

# Also fix the build_plan_state usage
def_build = """                    plan_state=build_plan_state({"routes": [{"worker_id": worker_id, "stops": [{"ticket_id": s.ticket_id, "sequence": s.sequence, "arrival_at": s.arrival_at.isoformat(), "service_start_at": s.service_start_at.isoformat(), "service_end_at": s.service_end_at.isoformat()} for s in r.stops]}]}, {worker_id: saved[0].id}),"""

fix_build = """                    plan_state=build_plan_state({"routes": [r.model_dump(mode="json")]}, {worker_id: saved[0].id}),"""

content = content.replace(def_build, fix_build)

with open("backend/app/modules/tickets/service.py", "w", encoding="utf-8") as f:
    f.write(content)
