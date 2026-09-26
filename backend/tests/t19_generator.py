import random
from datetime import UTC, date, datetime, time, timedelta

from app.modules.data_exchange.registry import TABLES
from app.modules.tickets.enums import TicketCategory, TicketStatus
from app.modules.users.enums import TransportType


def generate_t19_dataset(variant="base", seed=1900):
    random.Random(seed)
    tables = {name: [] for name in TABLES}

    date(2030, 1, 15)
    stamp = datetime(2030, 1, 14, 8, 0, tzinfo=UTC)

    def add(entity, **values):
        for column in TABLES[entity].columns:
            key = column.name
            if key in values or key == "password_hash":
                continue
            if key == "id":
                values[key] = len(tables[entity]) + 1
            elif key in ("created_at", "updated_at", "assigned_at", "next_attempt_at"):
                values[key] = stamp
            elif column.nullable:
                values[key] = None
        tables[entity].append(values)
        return values

    # 3 independent areas
    for i in range(1, 4):
        add("cities", id=i, name=f"City {i}")
        add("districts", id=i, city_id=i, name=f"District {i}")
        add("streets", id=i, city_id=i, name=f"Street {i}")
        add("service_areas", id=100 + i, code=f"SA_{i}", name=f"Area {i}")
        add("divisions", id=i, service_area_id=100 + i)

        # Locations & Buildings
        for b in range(1, 40):  # locations per area
            b_id = i * 100 + b
            add(
                "buildings", id=b_id, city_id=i, street_id=i, service_area_id=100 + i, number=str(b)
            )
            add("entrances", id=b_id, building_id=b_id, number="1")

            # Create a specific unreachable point in negative variant
            if variant == "negative" and b == 10:
                lat = None
                lon = None
            else:
                lat = round(55.75 + b_id * 0.0001, 6)
                lon = round(37.61 + b_id * 0.0001, 6)

            add(
                "locations",
                id=b_id,
                building_id=b_id,
                latitude=lat,
                longitude=lon,
                entrance_id=b_id,
            )

        add("offices", id=i, location_id=i * 100 + 1, name=f"Office {i}")
        foreman_id = add(
            "users", username=f"foreman_{i}", name=f"F{i}", surname=f"A{i}", role="foreman"
        )["id"]
        add(
            "brigades", id=i, division_id=i, office_id=i, foreman_id=foreman_id, name=f"Brigade {i}"
        )

    skills = ["Copper", "Fiber", "Radio"]
    for i, s in enumerate(skills, 1):
        add("worker_skills", id=i, skill=s)

    transport_profiles = [
        TransportType.CAR,
        TransportType.WALKING,
        TransportType.BICYCLE,
        TransportType.PUBLIC_TRANSPORT,
    ]
    for area_idx in range(1, 4):
        for w_idx in range(1, 13):
            user_id = add(
                "users",
                username=f"worker_{area_idx}_{w_idx}",
                name=f"W{w_idx}",
                surname=f"A{area_idx}",
                role="worker",
            )["id"]
            trans = transport_profiles[w_idx % 4]
            is_offline = variant == "negative" and w_idx == 1
            is_night = variant == "edge_cases" and w_idx == 2

            w_start = time(22) if is_night else time(8)
            w_end = time(6) if is_night else time(18)

            add(
                "workers",
                user_id=user_id,
                service_area_id=100 + area_idx,
                transport_type=trans.value,
                workshift_start=w_start,
                workshift_end=w_end,
                is_on_line=not is_offline,
            )
            add("brigade_members", brigade_id=area_idx, worker_id=user_id)

            # For negative variant, we omit some skills on purpose
            if variant == "negative":
                num_skills = 1  # Only Copper
            else:
                num_skills = (w_idx % 3) + 1
            for s_id in range(1, num_skills + 1):
                add("worker_skill_assignments", worker_id=user_id, skill_id=s_id)

    # 4 Canonical Categories
    add(
        "work_types",
        id=1,
        code="EM_1",
        name="EM",
        category=TicketCategory.EMERGENCY.value,
        default_priority=1,
        travel_minutes=15,
        work_minutes=30,
        documents_minutes=10,
        norm_minutes=55,
    )
    add(
        "work_type_planning_rules",
        work_type_id=1,
        service_duration_source="work_norm",
        configured_by=1,
    )
    add("work_type_required_skills", work_type_id=1, skill_id=1)

    add(
        "work_types",
        id=2,
        code="CONN_2",
        name="CONN",
        category=TicketCategory.CONNECTION.value,
        default_priority=2,
        travel_minutes=15,
        work_minutes=30,
        documents_minutes=10,
        norm_minutes=55,
    )
    add(
        "work_type_planning_rules",
        work_type_id=2,
        service_duration_source="work_norm",
        configured_by=1,
    )
    add("work_type_required_skills", work_type_id=2, skill_id=2)

    add(
        "work_types",
        id=3,
        code="REP_3",
        name="REP",
        category=TicketCategory.REPAIR.value,
        default_priority=3,
        travel_minutes=15,
        work_minutes=30,
        documents_minutes=10,
        norm_minutes=55,
    )
    add(
        "work_type_planning_rules",
        work_type_id=3,
        service_duration_source="ticket_estimate",
        configured_by=1,
    )
    add("work_type_required_skills", work_type_id=3, skill_id=3)  # Require Radio

    add(
        "work_types",
        id=4,
        code="ADD_4",
        name="ADD",
        category=TicketCategory.ADDITIONAL.value,
        default_priority=4,
        travel_minutes=15,
        work_minutes=30,
        documents_minutes=10,
        norm_minutes=55,
    )
    add(
        "work_type_planning_rules",
        work_type_id=4,
        service_duration_source="work_norm",
        configured_by=1,
    )
    add("work_type_required_skills", work_type_id=4, skill_id=1)

    add(
        "appliances",
        id=1,
        code="ROUTER",
        name="Router",
        type="CLIENT_ROUTER",
        unit="шт",
        is_active=True,
    )
    add("work_type_required_appliances", work_type_id=4, appliance_id=1, quantity=1)

    if variant == "base":
        distribution = [(1, 40), (2, 40), (3, 10), (4, 10)]
    elif variant == "negative":
        distribution = [(3, 5)]  # Require Radio, but workers only have Copper
    else:
        distribution = [(1, 15)]

    metadata = {
        "variant": variant,
        "seed": seed,
        "versions": {"schema": "1.0", "policy": "case_policy_v1"},
        "invariants": {},
    }

    ticket_idx = 1
    for wt_id, count in distribution:
        for c in range(count):
            ticket_wt_id = wt_id
            area_id = (ticket_idx % 3) + 1
            loc_id = area_id * 100 + ((ticket_idx % 38) + 2)

            status = TicketStatus.PLANNED.value
            lifecycle = "waiting_assignment"
            comments = []
            req_transport = None

            vw_start = stamp + timedelta(days=1, hours=1)
            vw_end = vw_start + timedelta(hours=2)
            recv_at = stamp

            if variant == "base":
                pass
            elif variant == "edge_cases":
                if c == 0:
                    recv_at = datetime(2030, 1, 15, 12, 17, tzinfo=UTC)
                    comments.append(
                        {
                            "text": "Аварийная заявка",
                            "created_at": datetime(2030, 1, 15, 12, 17, tzinfo=UTC),
                        }
                    )
                elif c == 1:
                    status = TicketStatus.WONT_FIX.value
                    lifecycle = "cancelled"
                    metadata["invariants"][ticket_idx] = "ticket_not_planned"
                elif c == 2:
                    status = TicketStatus.IN_PROGRESS.value
                    lifecycle = "in_progress"
                    metadata["invariants"][ticket_idx] = "ticket_not_planned"
                elif c == 3:
                    req_transport = TransportType.BICYCLE.value
                elif c == 4:
                    loc_id = area_id * 100 + 5
                elif c == 5:
                    loc_id = area_id * 100 + 5  # identical coordinate visit
                elif c == 6:
                    vw_start = stamp - timedelta(hours=2)  # early/late windows
                    vw_end = stamp - timedelta(hours=1)
                elif c == 7:
                    loc_id = 1000 + ticket_idx
                    b_id = area_id * 100 + 99
                    add(
                        "buildings",
                        id=b_id,
                        city_id=area_id,
                        street_id=area_id,
                        service_area_id=100 + area_id,
                        number="99",
                    )
                    add("entrances", id=b_id, building_id=b_id, number="1")
                    add(
                        "locations",
                        id=loc_id,
                        building_id=b_id,
                        latitude=56.0,
                        longitude=38.0,
                        entrance_id=b_id,
                    )
                elif c == 8:
                    # Stock shortage for work type 4
                    ticket_wt_id = 4
                    metadata["invariants"][ticket_idx] = "equipment_not_reserved"

            elif variant == "negative":
                if c == 0:
                    metadata["invariants"][ticket_idx] = "missing_skill"
                elif c == 1:
                    loc_id = area_id * 100 + 10  # Unreachable point (lat/lon None)
                    metadata["invariants"][ticket_idx] = "ticket_without_coordinates"

            add(
                "tickets",
                id=ticket_idx,
                service_area_id=100 + area_id,
                location_id=loc_id,
                status=status,
                lifecycle_state=lifecycle,
                revision=1,
                execution_cycle=1,
                work_type="WT",
                work_type_id=ticket_wt_id,
                category=["emergency", "connection", "repair", "additional"][ticket_wt_id - 1]
                if ticket_wt_id <= 4
                else TicketCategory.REPAIR.value,
                priority=1,
                received_at=recv_at,
                title=f"T19 Ticket {ticket_idx}",
                visit_window_start=vw_start,
                visit_window_end=vw_end,
                estimated_duration_minutes=45,
                required_transport_type=req_transport,
                is_pinned=False,
            )

            for comment in comments:
                add(
                    "ticket_comments",
                    ticket_id=ticket_idx,
                    author_id=1,
                    text=comment["text"],
                    created_at=comment["created_at"],
                )
            ticket_idx += 1

    return tables, metadata
