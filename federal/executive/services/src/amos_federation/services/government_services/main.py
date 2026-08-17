"""
AMOS-Federation Government Services — HTTP Interface
الهدف: نقاط طرفية للخدمات والقضايا والقرارات، سياقها من الرمز لا من جسم الطلب
النطاق: services/government_services
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17 (R7-A، الوحدة 2)

## النمط نفسه — لا نمط ثانٍ

`Depends(require_context)` في كل نقطة، و`create_service_app` من `common/`،
و**لا نموذج طلب في هذا الملفّ يحمل `role` أو `permissions` أو `tenant_id`** —
محروسٌ باختبار ساكن كما في الوحدة 1.

## الأخطاء

نقص الصلاحية 403 · انعدام السلطة من المنصب 403 · الجلسة المنتهية 401 ·
الكيان المفقود 404 · تعارض الرمز أو المرجع أو وجود قرار 409 · حالة القضية
المانعة 409 · المراجعة غير المنجَزة 409 · مخالفة المفردة 400.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from amos_federation.common.auth_context import require_context
from amos_federation.common.principal import (
    AuthorizationContext,
    PrincipalUnverifiedError,
    SessionInvalidError,
    TenantIsolationError,
)
from amos_federation.common.registry import SERVICES
from amos_federation.common.service import create_service_app
from amos_federation.services.government_services.authorization import (
    OfficeAuthorityError,
    RegistryAuthorizationError,
)
from amos_federation.services.government_services.service import (
    CaseNotFoundError,
    CaseStateError,
    DecisionExistsError,
    DuplicateReferenceError,
    DuplicateServiceCodeError,
    GovernmentServiceError,
    OfficialNotFoundError,
    ReviewIncompleteError,
    ServiceInactiveError,
    ServiceNotFoundError,
    UnknownApplicantError,
    get_government_services,
)

router = APIRouter(prefix="/gov", tags=["government-services"])

Context = Annotated[AuthorizationContext, Depends(require_context)]


# === نماذج الطلب — بلا دور ولا صلاحيات ولا مستأجر ===


class ServiceRequest(BaseModel):
    """إعلان خدمة حكومية."""

    code: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=2, max_length=200)
    description: str = ""
    department_code: str | None = None
    sla_hours: int = Field(default=72, gt=0, le=8760)


class ServiceStatusRequest(BaseModel):
    """تغيير حالة خدمة."""

    status: str
    reason: str = Field(min_length=3, max_length=500)


class CaseRequest(BaseModel):
    """فتح قضية على خدمة."""

    service_code: str = Field(min_length=2, max_length=64)
    applicant_agent_id: str = Field(min_length=1, max_length=128)
    subject: str = Field(min_length=3, max_length=500)
    payload: dict[str, Any] | None = None
    priority: str = "normal"
    reference: str | None = None


class AssignmentRequest(BaseModel):
    """إسناد قضية إلى منصب."""

    official_id: str = Field(min_length=1, max_length=128)


class DecisionRequest(BaseModel):
    """إصدار قرار في قضية."""

    outcome: str
    rationale: str = Field(min_length=3, max_length=2000)
    official_id: str | None = None


def _http(exc: Exception) -> HTTPException:
    """ترجمة خطأ نطاق إلى رمز HTTP صادق."""
    if isinstance(exc, SessionInvalidError):
        return HTTPException(status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    if isinstance(
        exc,
        RegistryAuthorizationError
        | OfficeAuthorityError
        | PrincipalUnverifiedError
        | TenantIsolationError,
    ):
        return HTTPException(status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, ServiceNotFoundError | CaseNotFoundError | OfficialNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(
        exc,
        DuplicateServiceCodeError
        | DuplicateReferenceError
        | DecisionExistsError
        | CaseStateError
        | ReviewIncompleteError
        | ServiceInactiveError
        | UnknownApplicantError,
    ):
        return HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))


_DOMAIN_ERRORS = (
    GovernmentServiceError,
    RegistryAuthorizationError,
    OfficeAuthorityError,
    SessionInvalidError,
    PrincipalUnverifiedError,
    TenantIsolationError,
)


# === الخدمات ===


@router.post("/institutions/{code}/services", status_code=status.HTTP_201_CREATED)
async def publish_service(code: str, payload: ServiceRequest, context: Context) -> dict:
    """أعلن خدمة تُقدِّمها مؤسسة."""
    try:
        return get_government_services().publish_service(
            context=context,
            institution_code=code,
            code=payload.code,
            name=payload.name,
            description=payload.description,
            department_code=payload.department_code,
            sla_hours=payload.sla_hours,
        )
    except _DOMAIN_ERRORS as exc:
        raise _http(exc) from exc


@router.get("/services")
async def list_services(
    context: Context,
    institution_code: str | None = None,
    service_status: str | None = None,
    limit: int = 100,
) -> dict:
    """اسرد الخدمات."""
    try:
        items = get_government_services().list_services(
            context=context,
            institution_code=institution_code,
            status=service_status,
            limit=limit,
        )
    except _DOMAIN_ERRORS as exc:
        raise _http(exc) from exc
    return {"count": len(items), "services": items}


@router.patch("/institutions/{code}/services/{service_code}/status")
async def set_service_status(
    code: str, service_code: str, payload: ServiceStatusRequest, context: Context
) -> dict:
    """غيّر حالة خدمة."""
    try:
        return get_government_services().set_service_status(
            context=context,
            institution_code=code,
            code=service_code,
            status=payload.status,
            reason=payload.reason,
        )
    except _DOMAIN_ERRORS as exc:
        raise _http(exc) from exc


# === القضايا ===


@router.post("/institutions/{code}/cases", status_code=status.HTTP_201_CREATED)
async def open_case(code: str, payload: CaseRequest, context: Context) -> dict:
    """افتح قضية — تُقدِّم مهمّة إلى العمود التنفيذي وتحفظ معرّفها."""
    try:
        return get_government_services().open_case(
            context=context,
            institution_code=code,
            service_code=payload.service_code,
            applicant_agent_id=payload.applicant_agent_id,
            subject=payload.subject,
            payload=payload.payload,
            priority=payload.priority,
            reference=payload.reference,
        )
    except _DOMAIN_ERRORS as exc:
        raise _http(exc) from exc


@router.get("/cases")
async def list_cases(
    context: Context,
    institution_code: str | None = None,
    case_status: str | None = None,
    limit: int = 100,
) -> dict:
    """اسرد القضايا."""
    try:
        items = get_government_services().list_cases(
            context=context,
            institution_code=institution_code,
            status=case_status,
            limit=limit,
        )
    except _DOMAIN_ERRORS as exc:
        raise _http(exc) from exc
    return {"count": len(items), "cases": items}


@router.get("/cases/{reference}")
async def get_case(reference: str, context: Context) -> dict:
    """اقرأ قضية."""
    try:
        return get_government_services().get_case(reference, context=context)
    except _DOMAIN_ERRORS as exc:
        raise _http(exc) from exc


@router.get("/cases/{reference}/file")
async def case_file(reference: str, context: Context) -> dict:
    """ملفّ القضية: الخدمة والمؤسسة والمنصب والقرار."""
    try:
        return get_government_services().case_file(reference, context=context)
    except _DOMAIN_ERRORS as exc:
        raise _http(exc) from exc


@router.patch("/cases/{reference}/assignment")
async def assign_case(reference: str, payload: AssignmentRequest, context: Context) -> dict:
    """أسنِد القضية إلى منصب في مؤسستها."""
    try:
        return get_government_services().assign_case(
            context=context, reference=reference, official_id=payload.official_id
        )
    except _DOMAIN_ERRORS as exc:
        raise _http(exc) from exc


@router.post("/cases/{reference}/process")
async def process_case(reference: str, context: Context) -> dict:
    """شغِّل مهمّة القضية عبر النواة التنفيذية."""
    try:
        return get_government_services().process_case(context=context, reference=reference)
    except _DOMAIN_ERRORS as exc:
        raise _http(exc) from exc


@router.post("/cases/{reference}/decision", status_code=status.HTTP_201_CREATED)
async def decide_case(reference: str, payload: DecisionRequest, context: Context) -> dict:
    """أصدر القرار النهائي في القضية."""
    try:
        return get_government_services().decide_case(
            context=context,
            reference=reference,
            outcome=payload.outcome,
            rationale=payload.rationale,
            official_id=payload.official_id,
        )
    except _DOMAIN_ERRORS as exc:
        raise _http(exc) from exc


@router.post("/cases/{reference}/close")
async def close_case(reference: str, context: Context) -> dict:
    """أغلق قضية صدر فيها قرار."""
    try:
        return get_government_services().close_case(context=context, reference=reference)
    except _DOMAIN_ERRORS as exc:
        raise _http(exc) from exc


# === الصحة ===


@router.get("/health/summary")
async def services_health(context: Context) -> dict:
    """إحصاء الخدمات والقضايا والقرارات من القاعدة."""
    try:
        return get_government_services().services_health(context=context)
    except _DOMAIN_ERRORS as exc:
        raise _http(exc) from exc


_definition = SERVICES["government-services"]

app = create_service_app(
    service_name=_definition["name"],
    port=_definition["port"],
    description=_definition["responsibility"],
    routers=[router],
)

__all__ = ["app", "router"]
