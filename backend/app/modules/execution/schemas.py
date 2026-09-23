"""HTTP and service contracts for observer execution commands."""

from datetime import UTC, date, datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class ExecutionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(strict=True, ge=1)
    occurred_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    reason: str | None = Field(default=None, max_length=2000)
    expected_available_at: AwareDatetime | None = None
    worker_id: int | None = Field(default=None, ge=1)
    ticket_id: int | None = Field(default=None, ge=1)
    location_id: int | None = Field(default=None, ge=1)
    destination_id: int | None = Field(default=None, ge=1)
    payload: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_reason(self):
        if self.reason is not None:
            self.reason = self.reason.strip()
            if not self.reason:
                raise ValueError("Причина не может быть пустой")
        return self


class WindowChangeCommand(ExecutionCommand):
    new_window_start: AwareDatetime
    new_window_end: AwareDatetime

    @model_validator(mode="after")
    def validate_window(self):
        if self.new_window_end <= self.new_window_start:
            raise ValueError("Конец окна должен быть позже начала")
        if self.reason is None:
            raise ValueError("Для сдвига окна нужна причина")
        return self


class WorkerUnavailableCommand(ExecutionCommand):
    district_id: int = Field(strict=True, ge=1)
    route_date: date


class RedirectCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    worker_id: int = Field(strict=True, ge=1)
    current_ticket_id: int = Field(strict=True, ge=1)
    new_destination_id: int = Field(strict=True, ge=1)
    expected_day_revision: int = Field(strict=True, ge=1)
    occurred_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    reason: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def validate_reason(self):
        self.reason = self.reason.strip()
        if not self.reason:
            raise ValueError("Причина не может быть пустой")
        return self


class WorkerDayStateRead(BaseModel):
    worker_id: int
    district_id: int
    route_date: date
    available: bool
    unavailable_at: AwareDatetime | None = None
    unavailable_until: AwareDatetime | None = None
    last_location_id: int | None = None
    current_ticket_id: int | None = None
    current_destination_id: int | None = None
    en_route_started_at: AwareDatetime | None = None
    expected_available_at: AwareDatetime | None = None
    reason: str | None = None
    revision: int
    completed_ticket_ids: list[int] = Field(default_factory=list)
    in_progress_ticket_id: int | None = None
    remaining_ticket_ids: list[int] = Field(default_factory=list)
    event_ids: list[int] = Field(default_factory=list)
    current_plan_revision: int | None = None


class ExecutionResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ticket: object
    event_id: int | None
    revision: int
    replayed: bool = False


class ExecutionConflictRead(BaseModel):
    code: str
    current_revision: int | None = None
    current_state: str | None = None
