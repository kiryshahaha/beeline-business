"""Work type response contract."""

from pydantic import BaseModel, ConfigDict, Field

WORK_TYPE_EXAMPLE = {
    "id": 1,
    "name": "Подключение клиентов Базовая",
    "travel_minutes": 20,
    "work_minutes": 60,
    "documents_minutes": 10,
    "norm_minutes": 90,
}


class WorkTypeRead(BaseModel):
    model_config = ConfigDict(
        from_attributes=True, json_schema_extra={"examples": [WORK_TYPE_EXAMPLE]}
    )

    id: int
    name: str = Field(description="Название вида работ из нормативов организаторов.")
    travel_minutes: int = Field(description="Дорога до клиента или ТКД, минуты.")
    work_minutes: int = Field(description="Технические работы, минуты.")
    documents_minutes: int = Field(description="Оформление документов, минуты.")
    norm_minutes: int = Field(
        description="Базовый норматив: сумма дороги, технических работ и документов."
    )
