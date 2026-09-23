"""Explicit, replaceable work requirements; an empty configured list is meaningful."""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.planning_guard import lock_planning_mutation
from app.modules.appliances.models import Appliance
from app.modules.users.models import WorkerSkill
from app.modules.work_types.models import (
    WorkType,
    WorkTypePlanningRule,
    WorkTypeRequiredAppliance,
    WorkTypeRequiredSkill,
)

PositiveId = Annotated[int, Field(strict=True, ge=1, le=2_147_483_647)]


class RequiredAppliance(BaseModel):
    model_config = ConfigDict(extra="forbid")
    appliance_id: PositiveId
    quantity: PositiveId


class PlanningRulesWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    service_duration_source: Literal["ticket_estimate", "work_norm"]
    required_skill_ids: list[PositiveId] = Field(max_length=100)
    required_appliances: list[RequiredAppliance] = Field(max_length=100)

    @model_validator(mode="after")
    def no_duplicates(self) -> Self:
        if len(set(self.required_skill_ids)) != len(self.required_skill_ids):
            raise ValueError("Duplicate skill IDs")
        ids = [item.appliance_id for item in self.required_appliances]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate appliance IDs")
        return self


def read_rules(session: Session, work_type_id: int) -> dict:
    if session.get(WorkType, work_type_id) is None:
        raise LookupError("Вид работ не найден")
    rule = session.get(WorkTypePlanningRule, work_type_id)
    if rule is None:
        return {"configured": False}
    return {
        "configured": True,
        "service_duration_source": rule.service_duration_source,
        "required_skill_ids": list(
            session.scalars(
                select(WorkTypeRequiredSkill.skill_id)
                .where(WorkTypeRequiredSkill.work_type_id == work_type_id)
                .order_by(WorkTypeRequiredSkill.skill_id)
            )
        ),
        "required_appliances": [
            {"appliance_id": a.appliance_id, "quantity": a.quantity}
            for a in session.scalars(
                select(WorkTypeRequiredAppliance)
                .where(WorkTypeRequiredAppliance.work_type_id == work_type_id)
                .order_by(WorkTypeRequiredAppliance.appliance_id)
            )
        ],
    }


def replace_rules(session: Session, work_type_id: int, data: PlanningRulesWrite, actor: int):
    with session.begin_nested() if session.in_transaction() else session.begin():
        lock_planning_mutation(session)
        work_type = session.get(WorkType, work_type_id)
        if work_type is None:
            raise LookupError("Вид работ не найден")
        skills = set(
            session.scalars(
                select(WorkerSkill.id).where(WorkerSkill.id.in_(data.required_skill_ids))
            )
        )
        if skills != set(data.required_skill_ids):
            raise ValueError("Навык не найден")
        ids = {item.appliance_id for item in data.required_appliances}
        active = set(
            session.scalars(
                select(Appliance.id).where(Appliance.id.in_(ids), Appliance.is_active.is_(True))
            )
        )
        if ids != active:
            raise ValueError("Оборудование не найдено или неактивно")
        if data.service_duration_source == "work_norm" and (
            work_type.work_minutes + work_type.documents_minutes <= 0
        ):
            raise ValueError("Норматив обслуживания должен быть положительным")
        rule = session.get(WorkTypePlanningRule, work_type_id)
        if rule is None:
            rule = WorkTypePlanningRule(work_type_id=work_type_id)
            session.add(rule)
        rule.service_duration_source = data.service_duration_source
        rule.configured_by = actor
        session.flush()
        for model in (WorkTypeRequiredSkill, WorkTypeRequiredAppliance):
            session.execute(delete(model).where(model.work_type_id == work_type_id))
        session.add_all(
            WorkTypeRequiredSkill(work_type_id=work_type_id, skill_id=skill)
            for skill in data.required_skill_ids
        )
        session.add_all(
            WorkTypeRequiredAppliance(work_type_id=work_type_id, **a.model_dump())
            for a in data.required_appliances
        )
        session.flush()
        return read_rules(session, work_type_id)
