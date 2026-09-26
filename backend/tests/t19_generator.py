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

        # 1 Office per area
        add("offices", id=i, location_id=i * 100 + 1, name=f"Office {i}")
        # 1 Brigade per area
        foreman_id = add(
            "users", username=f"foreman_{i}", name=f"F{i}", surname=f"A{i}", role="foreman"
        )["id"]
        add(
            "brigades", id=i, division_id=i, office_id=i, foreman_id=foreman_id, name=f"Brigade {i}"
        )

    # Skills
    skills = ["Copper", "Fiber", "Radio"]
    for i, s in enumerate(skills, 1):
        add("worker_skills", id=i, skill=s)

    # Workers (10-15 per area -> let's do 12 per area = 36 workers)
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
            add(
                "workers",
                user_id=user_id,
                service_area_id=100 + area_idx,
                transport_type=trans.value,
                workshift_start=time(8),
                workshift_end=time(18),
                is_on_line=True,
            )
            add("brigade_members", brigade_id=area_idx, worker_id=user_id)

            # Unequal skill sets: 1/2/3 skills
            num_skills = (w_idx % 3) + 1
            for s_id in range(1, num_skills + 1):
                add("worker_skill_assignments", worker_id=user_id, skill_id=s_id)

    # 4 Canonical Categories
    # emergency, connection, repair, additional
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
    add("work_type_required_skills", work_type_id=1, skill_id=1)  # requires Copper

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
    add("work_type_required_skills", work_type_id=2, skill_id=2)  # requires Fiber

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

    # Tickets
    # 40/40/10/10 distribution for base variant
    if variant == "base":
        distribution = [(1, 40), (3, 40), (2, 10), (4, 10)]  # EM:40, REP:40, CONN:10, ADD:10
    elif variant == "negative":
        distribution = [(1, 20)]  # Fewer tickets for negative testing
    else:
        distribution = [(1, 25), (2, 25), (3, 25), (4, 25)]

    ticket_idx = 1
    for wt_id, count in distribution:
        for _ in range(count):
            area_id = (ticket_idx % 3) + 1
            loc_id = area_id * 100 + ((ticket_idx % 38) + 2)

            # Events and specific conditions logic
            status = TicketStatus.PLANNED.value
            lifecycle = "waiting_assignment"
            comments = []
            req_transport = None

            vw_start = stamp + timedelta(days=1, hours=1)  # 2030-01-15 09:00
            vw_end = vw_start + timedelta(hours=2)  # 2030-01-15 11:00

            if ticket_idx == 1:
                # Emergency at 12:17
                comments.append(
                    {"text": "Urgent leak", "created_at": datetime(2030, 1, 15, 12, 17, tzinfo=UTC)}
                )
            elif ticket_idx == 2:
                # Cancelled before departure
                status = TicketStatus.WONT_FIX.value
                lifecycle = "cancelled"
            elif ticket_idx == 3:
                # Extending work with status in_progress
                status = TicketStatus.IN_PROGRESS.value
                lifecycle = "in_progress"
            elif ticket_idx == 4:
                # Mandatory transport type
                req_transport = TransportType.BICYCLE.value
            elif ticket_idx == 5:
                # Unreachable point (will be handled by coordinates)
                pass
            elif ticket_idx in (6, 7):
                # Two separate visits with identical coordinates
                loc_id = area_id * 100 + 5  # same location

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
                work_type_id=wt_id,
                category=["emergency", "connection", "repair", "additional"][wt_id - 1]
                if wt_id <= 4
                else TicketCategory.REPAIR.value,
                priority=1,
                received_at=stamp,
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

    return tables
