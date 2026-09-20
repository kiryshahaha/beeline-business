"""Calendar link contracts. The token itself is shown only once, inside the link."""

from pydantic import AwareDatetime, BaseModel, Field


class CalendarLinkRead(BaseModel):
    url: str = Field(
        description="Ссылка для подписки в Google/Apple Calendar. Сохраните её сразу: "
        "повторно получить ту же ссылку нельзя, только выпустить новую."
    )
    created_at: AwareDatetime


class CalendarLinkStatus(BaseModel):
    active: bool
    created_at: AwareDatetime | None = None
