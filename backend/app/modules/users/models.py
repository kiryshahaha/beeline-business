from datetime import date, datetime, time

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Time,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IntegerIdMixin
from app.modules.users.enums import ScheduleType, TransportType, UserRole


class User(IntegerIdMixin, Base):
    __tablename__ = "users"

    name: Mapped[str] = mapped_column(String(100))
    surname: Mapped[str] = mapped_column(String(100))
    lastname: Mapped[str | None] = mapped_column(String(100), nullable=True)
    username: Mapped[str] = mapped_column(String(50))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(
        Enum(
            UserRole,
            values_callable=lambda roles: [role.value for role in roles],
            native_enum=False,
            create_constraint=True,
            length=20,
            name="role_valid",
        )
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    # Archived accounts keep their identity and history but cannot sign in or receive work.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("name = btrim(name) AND name <> ''", name="name_not_blank"),
        CheckConstraint("surname = btrim(surname) AND surname <> ''", name="surname_not_blank"),
        CheckConstraint(
            "lastname IS NULL OR (lastname = btrim(lastname) AND lastname <> '')",
            name="lastname_not_blank_if_present",
        ),
        CheckConstraint("username = btrim(username) AND username <> ''", name="username_not_blank"),
        CheckConstraint(
            "password_hash = btrim(password_hash) AND password_hash <> ''",
            name="password_hash_not_blank",
        ),
        Index("uq_users_username", func.lower(username), unique=True),
    )


class Worker(Base):
    __tablename__ = "workers"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    workshift_start: Mapped[time] = mapped_column(Time)
    workshift_end: Mapped[time] = mapped_column(Time)
    transport_type: Mapped[TransportType] = mapped_column(
        Enum(
            TransportType,
            values_callable=lambda values: [value.value for value in values],
            native_enum=False,
            create_constraint=True,
            name="worker_transport_type",
        ),
        default=TransportType.WALKING,
        server_default=TransportType.WALKING.value,
    )
    is_on_line: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
    )
    service_area_id: Mapped[int | None] = mapped_column(
        ForeignKey("service_areas.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    start_location_id: Mapped[int | None] = mapped_column(
        ForeignKey("locations.id", ondelete="RESTRICT"), nullable=True
    )
    stock_office_id: Mapped[int | None] = mapped_column(
        ForeignKey("offices.id", ondelete="RESTRICT"), nullable=True
    )
    end_location_id: Mapped[int | None] = mapped_column(
        ForeignKey("locations.id", ondelete="RESTRICT"), nullable=True
    )
    schedule_type: Mapped[ScheduleType] = mapped_column(
        Enum(
            ScheduleType,
            values_callable=lambda values: [value.value for value in values],
            native_enum=False,
            create_constraint=True,
            name="worker_schedule_type",
        ),
        default=ScheduleType.FIVE_TWO,
        server_default=ScheduleType.FIVE_TWO.value,
    )
    cycle_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    workdays_mask: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        CheckConstraint("workshift_start <> workshift_end", name="workshift_duration_not_zero"),
    )


class WorkerShiftException(IntegerIdMixin, Base):
    __tablename__ = "worker_shift_exceptions"

    worker_id: Mapped[int] = mapped_column(
        ForeignKey("workers.user_id", ondelete="CASCADE"), index=True
    )
    exception_date: Mapped[date] = mapped_column(Date)
    is_working: Mapped[bool] = mapped_column(Boolean)
    workshift_start: Mapped[time | None] = mapped_column(Time, nullable=True)
    workshift_end: Mapped[time | None] = mapped_column(Time, nullable=True)

    __table_args__ = (
        Index("uq_worker_shift_exception_date", "worker_id", "exception_date", unique=True),
        CheckConstraint(
            "is_working = false OR "
            "(workshift_start IS NOT NULL AND workshift_end IS NOT NULL "
            "AND workshift_start <> workshift_end)",
            name="worker_shift_exception_hours_valid",
        ),
    )


class WorkerSkill(IntegerIdMixin, Base):
    __tablename__ = "worker_skills"

    skill: Mapped[str] = mapped_column(String(100), unique=True)

    __table_args__ = (
        CheckConstraint("skill = btrim(skill) AND skill <> ''", name="skill_not_blank"),
    )


class WorkerSkillAssignment(Base):
    __tablename__ = "worker_skill_assignments"

    worker_id: Mapped[int] = mapped_column(
        ForeignKey("workers.user_id", ondelete="CASCADE"), primary_key=True
    )
    skill_id: Mapped[int] = mapped_column(
        ForeignKey("worker_skills.id", ondelete="RESTRICT"), primary_key=True, index=True
    )


class RefreshToken(IntegerIdMixin, Base):
    __tablename__ = "refresh_tokens"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(255))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("uq_refresh_tokens_token_hash", "token_hash", unique=True),)
