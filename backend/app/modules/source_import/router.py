"""Dispatcher API for the organizer's source files; the domain exchange stays separate."""

from datetime import time
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, UploadFile
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_session
from app.modules.auth.dependencies import require_roles
from app.modules.source_import import classify, repository, service
from app.modules.source_import.geocoding import GeoapifyGeocoder
from app.modules.source_import.profile import MAX_FILE_BYTES, SourceFormatError
from app.modules.source_import.schemas import (
    AddressReview,
    SourceAddressRead,
    SourceImportSummary,
)
from app.modules.users.enums import TransportType, UserRole
from app.modules.users.schemas import UserRead

router = APIRouter(prefix="/api/v1/data/sources", tags=["source-import"])
DatabaseSession = Annotated[Session, Depends(get_session)]
Observer = Annotated[UserRead, Depends(require_roles(UserRole.OBSERVER))]
Id = Annotated[int, Path(ge=1, le=2_147_483_647)]


def get_geocoder() -> GeoapifyGeocoder | None:
    settings = get_settings()
    if not settings.geoapify_api_key:
        return None
    return GeoapifyGeocoder(
        settings.geoapify_api_key, timeout_seconds=settings.geoapify_timeout_seconds
    )


def fail(error: Exception):
    if isinstance(error, SourceFormatError):
        raise HTTPException(422, detail={"code": "source_format", **error.detail}) from error
    raise HTTPException(error.status, detail=error.detail) from error


@router.get("/mapping")
def read_mapping(_: Observer) -> dict[str, Any]:
    """Версия и таблицы соответствий классификаторов BK/HD справочнику видов работ."""
    return classify.describe()


@router.post("/import")
def import_source(
    file: UploadFile,
    session: DatabaseSession,
    observer: Observer,
    geocoder=Depends(get_geocoder),
    kind: Annotated[
        Literal["demand", "control"] | None,
        Query(
            description="demand — синтетические данные, control — контрольное распределение; "
            "по умолчанию по столбцам файла."
        ),
    ] = None,
    dataset: Annotated[
        str | None, Query(max_length=100, description="Участок; по умолчанию из имени файла.")
    ] = None,
    dry_run: Annotated[bool, Query(description="Только отчёт, без записи.")] = True,
    geocode: Annotated[bool, Query(description="Геокодировать адреса без координат.")] = False,
    workshift_start: time = time(9),
    workshift_end: time = time(22),
    transport_type: TransportType = TransportType.CAR,
) -> dict[str, Any]:
    """Загрузить исходный CSV/XLSX организатора и получить отчёт по каждой строке.

    По умолчанию dry_run=true: весь импорт проверяется в транзакции и откатывается.
    Смена, транспорт — параметры исполнителей, создаваемых из бригад контрольного файла.
    """
    if workshift_start == workshift_end:
        raise HTTPException(422, detail="Начало и конец смены не могут совпадать")
    content = file.file.read(MAX_FILE_BYTES + 1)
    options = service.ImportOptions(
        actor_id=observer.id,
        kind=kind,
        dataset=dataset,
        dry_run=dry_run,
        geocode=geocode,
        workshift_start=workshift_start,
        workshift_end=workshift_end,
        transport_type=transport_type,
    )
    try:
        return service.import_source(session, content, file.filename or "", options, geocoder)
    except (SourceFormatError, service.SourceImportError) as error:
        fail(error)


@router.get("/imports", response_model=list[SourceImportSummary])
def list_imports(
    session: DatabaseSession,
    _: Observer,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=2_147_483_647)] = 0,
):
    with session.begin():
        return repository.list_imports(session, limit, offset)


@router.get("/imports/{import_id}")
def read_import(import_id: Id, session: DatabaseSession, _: Observer) -> dict[str, Any]:
    """Сохранённый отчёт применённого импорта."""
    with session.begin():
        row = repository.find_import(session, import_id)
    if row is None:
        raise HTTPException(404, detail="Импорт не найден")
    return row["report"]


@router.get("/addresses", response_model=list[SourceAddressRead])
def list_addresses(
    session: DatabaseSession,
    _: Observer,
    service_area_id: Annotated[int | None, Query(ge=1, le=2_147_483_647)] = None,
    status: Literal["unresolved", "geocoded", "ambiguous", "manual"] | None = None,
):
    """Адреса исходных файлов со статусом координат: unresolved/ambiguous ждут проверки."""
    with session.begin():
        return repository.list_addresses(session, service_area_id, status)


@router.put("/addresses/{address_id}", response_model=SourceAddressRead)
def review_address(
    address_id: Id, data: AddressReview, session: DatabaseSession, observer: Observer
):
    """Задать проверенные координаты адреса вручную (статус manual)."""
    try:
        return service.review_address(
            session,
            address_id,
            Decimal(str(data.latitude)).quantize(Decimal("0.000001")),
            Decimal(str(data.longitude)).quantize(Decimal("0.000001")),
            observer.id,
        )
    except service.SourceImportError as error:
        fail(error)


@router.get("/areas/{service_area_id}/replay")
def read_replay(service_area_id: Id, session: DatabaseSession, _: Observer) -> dict[str, Any]:
    """События контрольного дня по окну визита: итог заявки и исполнитель организатора."""
    return service.replay(session, service_area_id)
