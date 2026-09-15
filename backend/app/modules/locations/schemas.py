"""Address representation assembled from the normalized directory for API responses."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, computed_field

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]

LOCATION_CREATE_EXAMPLE = {
    "city": "Санкт-Петербург",
    "district": "Невский район",
    "street": "Искровский проспект",
    "building_number": "4",
    "block": "корпус 2",
    "entrance_number": "1",
    "floor": 3,
    "apartment": "12",
    "latitude": 59.9156,
    "longitude": 30.4631,
}


class LocationCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"examples": [LOCATION_CREATE_EXAMPLE]}
    )

    city: NonEmptyStr = Field(description="Название города")
    district: NonEmptyStr = Field(description="Название района")
    street: NonEmptyStr = Field(description="Название улицы")
    building_number: NonEmptyStr = Field(description="Номер дома")
    block: NonEmptyStr | None = Field(default=None, description="Корпус, литера или строение")
    entrance_number: NonEmptyStr | None = Field(default=None, description="Номер подъезда")
    floor: int | None = Field(default=None, description="Номер этажа")
    apartment: NonEmptyStr | None = Field(default=None, description="Номер квартиры или помещения")
    latitude: float | None = Field(default=None, description="Широта (геокоординаты)")
    longitude: float | None = Field(default=None, description="Долгота (геокоординаты)")


class LocationRead(BaseModel):
    id: int
    city_id: int
    city: str
    district_id: int
    district: str
    street_id: int
    street: str
    building_id: int
    building_number: str
    block: str | None
    entrance_id: int | None
    entrance_number: str | None
    floor: int | None
    apartment: str | None
    latitude: float | None
    longitude: float | None

    @computed_field
    @property
    def address(self) -> str:
        """A display string; the database still stores separate directory references."""
        parts = [self.city, self.district, self.street, f"д. {self.building_number}"]
        if self.block is not None:
            parts.append(self.block)
        if self.entrance_number is not None:
            parts.append(f"подъезд {self.entrance_number}")
        if self.floor is not None:
            parts.append(f"этаж {self.floor}")
        if self.apartment is not None:
            parts.append(f"кв./пом. {self.apartment}")
        return ", ".join(parts)
