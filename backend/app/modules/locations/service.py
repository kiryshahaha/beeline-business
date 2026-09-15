"""Transaction boundaries and domain logic for the address directory."""

from sqlalchemy.orm import Session

from app.modules.locations import repository
from app.modules.locations.schemas import LocationCreate, LocationRead


def get_or_create_location(session: Session, data: LocationCreate) -> LocationRead:
    """Create or resolve the full address hierarchy."""
    with session.begin():
        city_id = repository.get_or_create_id(
            session,
            "SELECT id FROM cities WHERE lower(name) = lower(:name)",
            "INSERT INTO cities (name) VALUES (:name) RETURNING id",
            {"name": data.city},
        )

        district_id = repository.get_or_create_id(
            session,
            """
            SELECT id FROM districts
            WHERE city_id = :city_id AND lower(name) = lower(:name)
            """,
            "INSERT INTO districts (city_id, name) VALUES (:city_id, :name) RETURNING id",
            {"city_id": city_id, "name": data.district},
        )

        street_id = repository.get_or_create_id(
            session,
            """
            SELECT id FROM streets
            WHERE city_id = :city_id AND lower(name) = lower(:name)
            """,
            "INSERT INTO streets (city_id, name) VALUES (:city_id, :name) RETURNING id",
            {"city_id": city_id, "name": data.street},
        )

        building_id = repository.get_or_create_id(
            session,
            """
            SELECT id FROM buildings
            WHERE street_id = :street_id AND lower(number) = lower(:number)
              AND lower(block) IS NOT DISTINCT FROM lower(CAST(:block AS text))
            """,
            """
            INSERT INTO buildings (city_id, street_id, district_id, number, block)
            VALUES (:city_id, :street_id, :district_id, :number, :block) RETURNING id
            """,
            {
                "city_id": city_id,
                "street_id": street_id,
                "district_id": district_id,
                "number": data.building_number,
                "block": data.block,
            },
        )

        entrance_id = None
        if data.entrance_number is not None:
            entrance_id = repository.get_or_create_id(
                session,
                """
                SELECT id FROM entrances
                WHERE building_id = :building_id AND lower(number) = lower(:number)
                """,
                """
                INSERT INTO entrances (building_id, number)
                VALUES (:building_id, :number) RETURNING id
                """,
                {"building_id": building_id, "number": data.entrance_number},
            )

        destination = {
            "building_id": building_id,
            "entrance_id": entrance_id,
            "apartment": data.apartment,
        }
        coordinates = {"latitude": data.latitude, "longitude": data.longitude}

        location_id = repository.get_or_create_id(
            session,
            """
            SELECT id FROM locations
            WHERE building_id = :building_id
              AND entrance_id IS NOT DISTINCT FROM CAST(:entrance_id AS integer)
              AND lower(apartment) IS NOT DISTINCT FROM lower(CAST(:apartment AS text))
            """,
            """
            INSERT INTO locations (
                building_id, entrance_id, floor, apartment, latitude, longitude
            ) VALUES (
                :building_id, :entrance_id, :floor, :apartment, :latitude, :longitude
            )
            RETURNING id
            """,
            {**destination, "floor": data.floor, **coordinates},
        )

        details = repository.find_location(session, location_id)
        if details is None:
            raise RuntimeError("Failed to read created location")

        return LocationRead(
            id=details["id"],
            city_id=details["city_id"],
            city=details["city"],
            district_id=details["district_id"],
            district=details["district"],
            street_id=details["street_id"],
            street=details["street"],
            building_id=details["building_id"],
            building_number=details["building_number"],
            block=details["block"],
            entrance_id=details["entrance_id"],
            entrance_number=details["entrance_number"],
            floor=details["floor"],
            apartment=details["apartment"],
            latitude=details["latitude"],
            longitude=details["longitude"],
        )
