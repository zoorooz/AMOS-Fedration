"""
AMOS-Federation Government Services — Service Layer
الهدف: خدمات الدولة وقضاياها وقراراتها فوق السجل، وأثرها التنفيذي عبر النواة القائمة
النطاق: services/government_services
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17 (R7-A، الوحدة 2)

## الترتيب في كل كتابة — هو نفسه ترتيب الوحدة 1

    require_domain_permission → require_tenant → قاعدة البيانات
      → record_domain_trace (تدقيق ثم حدث دائم)

## الأثر التنفيذي: لا مُنفِّذ خاصّ بهذا النطاق (R7-E)

فتح القضية **يُقدِّم مهمّة** إلى `ExecutiveCore` القائم ويحفظ `task_id` مفتاحًا
أجنبيًّا. ومعالجة القضية **تُنادي `ExecutiveCore.run`** ولا تُعيد كتابة آلة الحالات
ولا تلمس عمود `tasks.status` بنفسها. لا `Dispatcher` ولا `Runtime` ولا مُنفِّذ ثانٍ
في هذا الملفّ — والحرس الساكن في الاختبارات يمنع إدخال واحد.

ومعنى ذلك عمليًّا: **إن لم يوجد وكيل مؤهَّل، تفشل المهمّة** وتُخزَّن حالتها
النهائية `failed` في `review_state` كما هي. القضية لا تُجمِّل نتيجة تنفيذ ولا
تُصنِّف الفشل نجاحًا.

## القرار

لا قرار قبل أن تبلغ مهمّة القضية حالةً نهائية. وهذا شرطٌ في طبقة الخدمة لأن
تنفيذه في القاعدة يلزمه قراءة صفٍّ في جدول آخر. ومن يقرّر يلزمه **منصبٌ قائم في
مؤسسة القضية** (`require_office`)، أو سلطة سيادية تُسجَّل صراحةً في القرار.

## حدود تُقال

- **نافذة صغيرة عند فتح القضية:** المهمّة تُقدَّم قبل إدخال صفّ القضية. فلو فشل
  الإدخال (تسابق على نفس المرجع) بقيت مهمّة بلا قضية. المرجع يُفحَص قبل التقديم،
  ويُولَّد عشوائيًّا افتراضيًّا، فالاحتمال نظري — لكنه قائم ولا يُخفى.
- **`sla_hours` مخزَّنة لا مفروضة:** لا مُجدول يراقب التأخير اليوم.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import IntegrityError

from amos_federation.common.database import get_session_factory, init_db
from amos_federation.common.principal import DEFAULT_TENANT
from amos_federation.services.executive_core.agent_identity import get_identity
from amos_federation.services.executive_core.engine import get_executive_core
from amos_federation.services.executive_core.states import is_terminal
from amos_federation.services.government_services.authorization import (
    PERMISSIONS_CASE_ASSIGN,
    PERMISSIONS_CASE_DECIDE,
    PERMISSIONS_CASE_OPEN,
    PERMISSIONS_CASE_PROCESS,
    PERMISSIONS_GOV_READ,
    PERMISSIONS_SERVICE_WRITE,
    has_sovereign_authority,
    require_domain_permission,
    require_office,
    require_tenant,
)
from amos_federation.services.government_services.models import (
    CASE_PRIORITIES,
    DECISION_OUTCOMES,
    SERVICE_STATUSES,
    CaseModel,
    DecisionModel,
    ServiceModel,
)
from amos_federation.services.national_registry.authorization import require_authority
from amos_federation.services.national_registry.models import DecisionProvenanceModel
from amos_federation.services.national_registry.resolver import (
    resolve_identity,
    resolve_official_for_principal,
    resolve_positions,
)
from amos_federation.services.state_registry.models import (
    DepartmentModel,
    InstitutionModel,
    OfficialModel,
)
from amos_federation.services.state_registry.trace import record_domain_trace

if TYPE_CHECKING:
    from amos_federation.common.principal import AuthorizationContext

# === أسماء الأحداث — لكل واحد عقد في `EVENT_CONTRACTS` ===

EVENT_SERVICE_PUBLISHED = "amos_federation.gov.service_published"
EVENT_SERVICE_STATUS_CHANGED = "amos_federation.gov.service_status_changed"
EVENT_CASE_OPENED = "amos_federation.gov.case_opened"
EVENT_CASE_ASSIGNED = "amos_federation.gov.case_assigned"
EVENT_CASE_REVIEWED = "amos_federation.gov.case_reviewed"
EVENT_CASE_DECIDED = "amos_federation.gov.case_decided"
EVENT_CASE_CLOSED = "amos_federation.gov.case_closed"

GOVERNMENT_EVENTS: tuple[str, ...] = (
    EVENT_SERVICE_PUBLISHED,
    EVENT_SERVICE_STATUS_CHANGED,
    EVENT_CASE_OPENED,
    EVENT_CASE_ASSIGNED,
    EVENT_CASE_REVIEWED,
    EVENT_CASE_DECIDED,
    EVENT_CASE_CLOSED,
)

#: نوع المهمّة الذي تُقدِّمه هذه الوحدة إلى العمود التنفيذي — اسم واحد لا يتفرّع.
CASE_TASK_TYPE = "government.case.review"
CASE_TASK_DOMAIN = "government"


# === أخطاء النطاق ===


class GovernmentServiceError(RuntimeError):
    """أصل أخطاء هذا النطاق — كلها رفعٌ صريح لا قيمة فارغة."""


class ServiceNotFoundError(GovernmentServiceError):
    """لا خدمة بهذا الرمز في هذه المؤسسة."""


class ServiceInactiveError(GovernmentServiceError):
    """الخدمة ليست نشطة — لا قضية جديدة على خدمة موقوفة أو مسحوبة."""


class CaseNotFoundError(GovernmentServiceError):
    """لا قضية بهذا المرجع في مستأجر السياق."""


class DuplicateServiceCodeError(GovernmentServiceError):
    """رمز الخدمة مستعمل في هذه المؤسسة."""


class DuplicateReferenceError(GovernmentServiceError):
    """مرجع القضية مستعمل في هذا المستأجر."""


class CaseStateError(GovernmentServiceError):
    """العملية لا تجوز على القضية في حالتها الحالية."""


class DecisionExistsError(GovernmentServiceError):
    """للقضية قرارٌ نهائي بالفعل — إعادة النظر مسارٌ غير موجود اليوم."""


class ReviewIncompleteError(GovernmentServiceError):
    """مهمّة القضية لم تبلغ حالة نهائية — لا قرار قبل انتهاء التنفيذ."""


class UnknownApplicantError(GovernmentServiceError):
    """لا وكيل بهذا المعرّف — الطالب وكيلٌ قائم لا نصٌّ حرّ."""


class OfficialNotFoundError(GovernmentServiceError):
    """لا منصب بهذا المعرّف."""


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


class GovernmentServices:
    """الخدمات الحكومية: إعلان الخدمة، فتح القضية، معالجتها، والقرار فيها."""

    def __init__(self, executive_core: Any | None = None) -> None:
        init_db()
        #: يُمرَّر في الاختبارات، وإلّا فالنواة المشتركة القائمة — لا نواة ثانية.
        self._core = executive_core if executive_core is not None else get_executive_core()

    # ── أدوات داخلية ─────────────────────────────────────────────────────

    def _session(self):
        return get_session_factory()()

    @staticmethod
    def _tenant_of(context: AuthorizationContext) -> str:
        return context.tenant_id or DEFAULT_TENANT

    def _institution_row(
        self, session, context: AuthorizationContext, code: str
    ) -> InstitutionModel:
        tenant = self._tenant_of(context)
        row = (
            session.query(InstitutionModel)
            .filter(InstitutionModel.code == code, InstitutionModel.tenant_id == tenant)
            .first()
        )
        if row is None:
            raise ServiceNotFoundError(f"لا مؤسسة برمز '{code}' في مستأجر '{tenant}'")
        require_tenant(context, row.tenant_id)
        return row

    def _service_row(
        self, session, context: AuthorizationContext, institution_code: str, code: str
    ) -> ServiceModel:
        institution = self._institution_row(session, context, institution_code)
        row = (
            session.query(ServiceModel)
            .filter(
                ServiceModel.institution_id == institution.id,
                ServiceModel.code == code,
            )
            .first()
        )
        if row is None:
            raise ServiceNotFoundError(f"لا خدمة برمز '{code}' في المؤسسة '{institution_code}'")
        require_tenant(context, row.tenant_id)
        return row

    def _case_row(self, session, context: AuthorizationContext, reference: str) -> CaseModel:
        tenant = self._tenant_of(context)
        row = (
            session.query(CaseModel)
            .filter(CaseModel.reference == reference, CaseModel.tenant_id == tenant)
            .first()
        )
        if row is None:
            raise CaseNotFoundError(f"لا قضية بمرجع '{reference}' في مستأجر '{tenant}'")
        require_tenant(context, row.tenant_id)
        return row

    def _official_row(
        self, session, context: AuthorizationContext, official_id: str
    ) -> OfficialModel:
        row = session.query(OfficialModel).filter(OfficialModel.id == official_id).first()
        if row is None:
            raise OfficialNotFoundError(f"لا منصب بمعرّف '{official_id}'")
        require_tenant(context, row.tenant_id)
        return row

    @staticmethod
    def _service_dict(row: ServiceModel) -> dict[str, Any]:
        return {
            "id": row.id,
            "code": row.code,
            "name": row.name,
            "institution_id": row.institution_id,
            "department_id": row.department_id,
            "description": row.description or "",
            "status": row.status,
            "sla_hours": int(row.sla_hours),
            "tenant_id": row.tenant_id,
            "created_by": row.created_by,
            "created_at": _iso(row.created_at),
        }

    @staticmethod
    def _case_dict(row: CaseModel) -> dict[str, Any]:
        return {
            "id": row.id,
            "reference": row.reference,
            "service_id": row.service_id,
            "institution_id": row.institution_id,
            "applicant_agent_id": row.applicant_agent_id,
            "assigned_official_id": row.assigned_official_id,
            "task_id": row.task_id,
            "subject": row.subject,
            "payload": row.payload or {},
            "status": row.status,
            "review_state": row.review_state,
            "priority": row.priority,
            "tenant_id": row.tenant_id,
            "opened_by": row.opened_by,
            "created_at": _iso(row.created_at),
            "updated_at": _iso(row.updated_at),
        }

    @staticmethod
    def _decision_dict(row: DecisionModel) -> dict[str, Any]:
        return {
            "id": row.id,
            "case_id": row.case_id,
            "decided_by_official_id": row.decided_by_official_id,
            "decided_by_principal": row.decided_by_principal,
            "outcome": row.outcome,
            "rationale": row.rationale,
            "task_final_state": row.task_final_state,
            "tenant_id": row.tenant_id,
            "decided_at": _iso(row.decided_at),
        }

    # ── الخدمات ──────────────────────────────────────────────────────────

    def publish_service(
        self,
        *,
        context: AuthorizationContext,
        institution_code: str,
        code: str,
        name: str,
        description: str = "",
        department_code: str | None = None,
        sla_hours: int = 72,
    ) -> dict[str, Any]:
        """أعلن خدمة حكومية تُقدِّمها مؤسسة قائمة ونشطة."""
        require_domain_permission(context, "gov.service.publish", PERMISSIONS_SERVICE_WRITE)
        if sla_hours <= 0:
            raise GovernmentServiceError("مدّة الاستجابة يجب أن تكون ساعاتٍ موجبة")
        session = self._session()
        try:
            institution = self._institution_row(session, context, institution_code)
            if institution.status != "active":
                raise ServiceInactiveError(
                    f"المؤسسة '{institution_code}' حالتها '{institution.status}' — لا خدمة تُعلَن تحتها"
                )
            department_id = None
            if department_code is not None:
                department = (
                    session.query(DepartmentModel)
                    .filter(
                        DepartmentModel.institution_id == institution.id,
                        DepartmentModel.code == department_code,
                    )
                    .first()
                )
                if department is None:
                    raise ServiceNotFoundError(
                        f"لا إدارة برمز '{department_code}' في المؤسسة '{institution_code}'"
                    )
                require_tenant(context, department.tenant_id)
                department_id = department.id

            row = ServiceModel(
                id=f"svc-{uuid.uuid4()}",
                code=code,
                name=name,
                institution_id=institution.id,
                department_id=department_id,
                description=description,
                status="active",
                sla_hours=sla_hours,
                tenant_id=self._tenant_of(context),
                created_by=context.principal_id,
            )
            session.add(row)
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise DuplicateServiceCodeError(
                    f"رمز الخدمة '{code}' مستعمل في المؤسسة '{institution_code}'"
                ) from exc
            entity = self._service_dict(row)
        finally:
            session.close()

        trace = record_domain_trace(
            context,
            "gov.service.publish",
            EVENT_SERVICE_PUBLISHED,
            {
                "service_id": entity["id"],
                "code": entity["code"],
                "institution_id": entity["institution_id"],
                "tenant_id": entity["tenant_id"],
            },
        )
        return {**entity, **trace}

    def set_service_status(
        self,
        *,
        context: AuthorizationContext,
        institution_code: str,
        code: str,
        status: str,
        reason: str,
    ) -> dict[str, Any]:
        """غيِّر حالة خدمة — الحالة من المفردة المُقيَّدة، والسبب مُلزَم."""
        require_domain_permission(context, "gov.service.status", PERMISSIONS_SERVICE_WRITE)
        if status not in SERVICE_STATUSES:
            raise GovernmentServiceError(
                f"حالة خدمة غير معروفة: '{status}' — المسموح {list(SERVICE_STATUSES)}"
            )
        if not reason.strip():
            raise GovernmentServiceError("تغيير حالة خدمة يلزمه سبب مكتوب")
        session = self._session()
        try:
            row = self._service_row(session, context, institution_code, code)
            previous = row.status
            if previous == "retired" and status != "retired":
                raise GovernmentServiceError(
                    f"الخدمة '{code}' مسحوبة — لا تُعاد بتغيير حالة، تُعلَن خدمة جديدة"
                )
            row.status = status
            row.updated_at = _now()
            session.commit()
            entity = self._service_dict(row)
        finally:
            session.close()

        trace = record_domain_trace(
            context,
            "gov.service.status",
            EVENT_SERVICE_STATUS_CHANGED,
            {
                "service_id": entity["id"],
                "from_status": previous,
                "to_status": status,
                "reason": reason,
                "tenant_id": entity["tenant_id"],
            },
        )
        return {**entity, "from_status": previous, **trace}

    # ── القضايا ──────────────────────────────────────────────────────────

    def open_case(
        self,
        *,
        context: AuthorizationContext,
        institution_code: str,
        service_code: str,
        applicant_agent_id: str,
        subject: str,
        payload: dict[str, Any] | None = None,
        priority: str = "normal",
        reference: str | None = None,
    ) -> dict[str, Any]:
        """افتح قضية على خدمة نشطة، وقدِّم مهمّتها إلى العمود التنفيذي.

        الأثر التنفيذي يُقدَّم عبر `ExecutiveCore.submit` (R7-E)، و`task_id`
        يُخزَّن مفتاحًا أجنبيًّا. فالقضية لا تدّعي عملًا لا صفَّ له في `tasks`.
        """
        require_domain_permission(context, "gov.case.open", PERMISSIONS_CASE_OPEN)
        if priority not in CASE_PRIORITIES:
            raise GovernmentServiceError(
                f"أولوية غير معروفة: '{priority}' — المسموح {list(CASE_PRIORITIES)}"
            )
        if not subject.strip():
            raise GovernmentServiceError("القضية تلزمها موضوع مكتوب")

        tenant = self._tenant_of(context)
        case_reference = reference or f"CASE-{uuid.uuid4().hex[:12].upper()}"

        session = self._session()
        try:
            service = self._service_row(session, context, institution_code, service_code)
            if service.status != "active":
                raise ServiceInactiveError(
                    f"الخدمة '{service_code}' حالتها '{service.status}' — لا قضية جديدة عليها"
                )
            institution_id = service.institution_id
            service_id = service.id

            identity = get_identity(applicant_agent_id)
            if identity is None:
                raise UnknownApplicantError(
                    f"لا وكيل بمعرّف '{applicant_agent_id}' — الطالب يجب أن يكون قائمًا في `agents`"
                )
            require_tenant(context, getattr(identity, "tenant_id", None))

            existing = (
                session.query(CaseModel)
                .filter(CaseModel.reference == case_reference, CaseModel.tenant_id == tenant)
                .first()
            )
            if existing is not None:
                raise DuplicateReferenceError(
                    f"مرجع القضية '{case_reference}' مستعمل في مستأجر '{tenant}'"
                )
        finally:
            session.close()

        # المهمّة تُقدَّم إلى النواة القائمة — لا مُنفِّذ خاصّ بهذا النطاق.
        task = self._core.submit(
            CASE_TASK_TYPE,
            f"مراجعة قضية {case_reference}: {subject}",
            priority=priority,
            domain=CASE_TASK_DOMAIN,
            tenant_id=tenant,
        )
        task_id = task["id"]

        session = self._session()
        try:
            row = CaseModel(
                id=f"case-{uuid.uuid4()}",
                reference=case_reference,
                service_id=service_id,
                institution_id=institution_id,
                applicant_agent_id=applicant_agent_id,
                task_id=task_id,
                subject=subject,
                payload=payload or {},
                status="submitted",
                priority=priority,
                tenant_id=tenant,
                opened_by=context.principal_id,
            )
            session.add(row)
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise DuplicateReferenceError(
                    f"تعذّر إدخال القضية '{case_reference}': {exc.orig}"
                ) from exc
            entity = self._case_dict(row)
        finally:
            session.close()

        trace = record_domain_trace(
            context,
            "gov.case.open",
            EVENT_CASE_OPENED,
            {
                "case_id": entity["id"],
                "reference": entity["reference"],
                "service_id": entity["service_id"],
                "institution_id": entity["institution_id"],
                "task_id": task_id,
                "applicant_agent_id": applicant_agent_id,
                "tenant_id": tenant,
            },
        )
        return {**entity, **trace}

    def assign_case(
        self, *, context: AuthorizationContext, reference: str, official_id: str
    ) -> dict[str, Any]:
        """أسنِد القضية إلى منصب قائم في مؤسستها."""
        require_domain_permission(context, "gov.case.assign", PERMISSIONS_CASE_ASSIGN)
        session = self._session()
        try:
            case = self._case_row(session, context, reference)
            if case.status not in {"submitted", "assigned"}:
                raise CaseStateError(
                    f"القضية '{reference}' حالتها '{case.status}' — الإسناد قبل المعالجة"
                )
            official = self._official_row(session, context, official_id)
            require_office(context, official, institution_id=case.institution_id)
            case.assigned_official_id = official.id
            case.status = "assigned"
            case.updated_at = _now()
            session.commit()
            entity = self._case_dict(case)
        finally:
            session.close()

        trace = record_domain_trace(
            context,
            "gov.case.assign",
            EVENT_CASE_ASSIGNED,
            {
                "case_id": entity["id"],
                "reference": entity["reference"],
                "official_id": official_id,
                "institution_id": entity["institution_id"],
                "task_id": entity["task_id"],
                "tenant_id": entity["tenant_id"],
            },
        )
        return {**entity, **trace}

    def process_case(
        self, *, context: AuthorizationContext, reference: str, max_steps: int = 8
    ) -> dict[str, Any]:
        """شغِّل مهمّة القضية عبر `ExecutiveCore.run` — ولا تلمس حالة المهمّة هنا.

        الحالة النهائية تُخزَّن كما قالها العمود التنفيذي، نجاحًا أو فشلًا. وإن لم
        يوجد وكيل مؤهَّل فالمهمّة تفشل، ويُخزَّن `failed` ولا يُدَّعى غيره.
        """
        require_domain_permission(context, "gov.case.process", PERMISSIONS_CASE_PROCESS)
        session = self._session()
        try:
            case = self._case_row(session, context, reference)
            if case.status not in {"submitted", "assigned", "processing"}:
                raise CaseStateError(
                    f"القضية '{reference}' حالتها '{case.status}' — لا معالجة بعد المراجعة"
                )
            task_id = case.task_id
            case.status = "processing"
            case.updated_at = _now()
            session.commit()
        finally:
            session.close()

        outcome = self._core.run(task_id, max_steps=max_steps)
        final_state = str(outcome["final_state"])
        terminal = bool(outcome["terminal"])

        session = self._session()
        try:
            case = self._case_row(session, context, reference)
            case.review_state = final_state
            case.status = "reviewed" if terminal else "processing"
            case.updated_at = _now()
            session.commit()
            entity = self._case_dict(case)
        finally:
            session.close()

        trace = record_domain_trace(
            context,
            "gov.case.review",
            EVENT_CASE_REVIEWED,
            {
                "case_id": entity["id"],
                "reference": entity["reference"],
                "task_id": task_id,
                "task_final_state": final_state,
                "terminal": terminal,
                "tenant_id": entity["tenant_id"],
            },
        )
        return {**entity, "task_final_state": final_state, "terminal": terminal, **trace}

    def decide_case(
        self,
        *,
        context: AuthorizationContext,
        reference: str,
        outcome: str,
        rationale: str,
        official_id: str | None = None,
    ) -> dict[str, Any]:
        """أصدر القرار النهائي في القضية — من منصب قائم وبسبب مكتوب.

        لا قرار قبل أن تبلغ مهمّة القضية حالةً نهائية: القرار يذكر تلك الحالة
        (`task_final_state`)، فلا يُنسَب قرارٌ إلى مراجعةٍ لم تُنجَز.
        """
        require_domain_permission(context, "gov.case.decide", PERMISSIONS_CASE_DECIDE)
        if outcome not in DECISION_OUTCOMES:
            raise GovernmentServiceError(
                f"نتيجة قرار غير معروفة: '{outcome}' — المسموح {list(DECISION_OUTCOMES)}"
            )
        if not rationale.strip():
            raise GovernmentServiceError("القرار يلزمه سبب مكتوب — لا قرار بلا تسبيب")

        session = self._session()
        try:
            case = self._case_row(session, context, reference)
            if case.status == "closed":
                raise CaseStateError(f"القضية '{reference}' مغلقة")
            existing = session.query(DecisionModel).filter(DecisionModel.case_id == case.id).first()
            if existing is not None:
                raise DecisionExistsError(f"للقضية '{reference}' قرارٌ نهائي بالفعل ({existing.id})")
            if case.review_state is None or not is_terminal(case.review_state):
                raise ReviewIncompleteError(
                    f"مهمّة القضية '{reference}' لم تبلغ حالة نهائية "
                    f"(الحالة المخزَّنة: {case.review_state or 'لم تُعالَج'})"
                )

            # === R7-C9: من أين تأتي سلطة القرار ===
            #
            # قبل R7-C كان `official_id` يُقبل من الطلب ويُفحص وجودُه فقط، فمن
            # يملك `write:tasks` يقرّر باسم **أيّ** مسؤول قائم. الآن:
            #
            # - غير السيادي: المنصب **يُشتقّ من هويته** لا من طلبه. وإن ادّعى
            #   منصبًا لا يشغله رُفع `ForgedAuthorityError`.
            # - السيادي (`manage:all`): يمرّ بسلطته كما في R7-A — والتاج لا
            #   يُشتَرط له منصب — ويُسجَّل قراره `UNRESOLVED` أو `PARTIAL` بحسب
            #   ما ثبت من هويته، فلا يُدَّعى إسنادٌ لم يُقرأ.
            sovereign = has_sovereign_authority(context)
            official = None
            if sovereign:
                if official_id is not None:
                    official = self._official_row(session, context, official_id)
                elif case.assigned_official_id is not None:
                    official = self._official_row(session, context, case.assigned_official_id)
            else:
                official = resolve_official_for_principal(
                    session,
                    context,
                    institution_id=case.institution_id,
                    claimed_official_id=official_id,
                )
            require_office(context, official, institution_id=case.institution_id)

            # سلطةٌ على العملية نفسها: غير السيادي يلزمه مِنحة `gov.case.decide`
            # لمنصبه في هذه المؤسسة. والصلاحية وحدها لا تكفي — وهذا هو معنى «لا
            # يقرّر المُنادي سلطته». والسيادي معفى، كما كان في R7-A.
            if not sovereign:
                require_authority(
                    session,
                    context,
                    "gov.case.decide",
                    institution_id=case.institution_id,
                    department_id=official.department_id if official else None,
                    claimed_official_id=official.id if official else None,
                )
            if official is None:
                # سلطة سيادية بلا منصب: العمود مفتاح أجنبي مُلزَم، فالقول الصادق
                # أن المسار غير مدعوم اليوم بدل تخزين قرار منسوب إلى منصب مُختَرع.
                raise GovernmentServiceError(
                    "القرار السيادي بلا منصب غير مدعوم اليوم: عمود "
                    "`decided_by_official_id` مفتاح أجنبي مُلزَم. مرِّر `official_id` "
                    "لمنصب قائم في مؤسسة القضية."
                )

            decision = DecisionModel(
                id=f"dec-{uuid.uuid4()}",
                case_id=case.id,
                decided_by_official_id=official.id,
                decided_by_principal=context.principal_id,
                outcome=outcome,
                rationale=rationale,
                task_final_state=case.review_state,
                tenant_id=case.tenant_id,
            )
            session.add(decision)
            case.status = "decided"
            case.updated_at = _now()
            session.flush()
            provenance = self._record_decision_provenance(
                session, context, decision=decision, case=case, official=official
            )
            session.commit()
            entity = self._decision_dict(decision)
            case_entity = self._case_dict(case)
        finally:
            session.close()

        trace = record_domain_trace(
            context,
            "gov.case.decide",
            EVENT_CASE_DECIDED,
            {
                "case_id": case_entity["id"],
                "reference": case_entity["reference"],
                "decision_id": entity["id"],
                "outcome": outcome,
                "official_id": entity["decided_by_official_id"],
                "task_id": case_entity["task_id"],
                "task_final_state": entity["task_final_state"],
                "provenance": provenance["provenance_class"],
                "identity_id": provenance["identity_id"],
                "tenant_id": entity["tenant_id"],
            },
        )
        return {**entity, "case": case_entity, "provenance": provenance, **trace}

    def _record_decision_provenance(
        self,
        session,
        context: AuthorizationContext,
        *,
        decision: DecisionModel,
        case: CaseModel,
        official: OfficialModel | None,
    ) -> dict[str, Any]:
        """اكتب إسناد القرار إلى سلسلته، وصنِّف قوّته بما قُرئ لا بما يُرجى — R7-C9.

        `PROVEN` تلزمها الحلقات كلها صفوفًا: هوية المبدأ، ومنصبٌ نشط لتلك الهوية،
        وهو نفسه المنصب المنسوب إليه القرار. و`PARTIAL` حين تُعرف الهوية ولا يُقرأ
        لها منصبٌ في هذا القرار (سلطة سيادية مثلًا). و`UNRESOLVED` حين لا هوية —
        وهو حال القرارات التي يُصدرها التاج بجلسةٍ غير مربوطة بهوية كانونية.
        """
        identity = resolve_identity(session, context)
        position_id: str | None = None
        provenance_class = "UNRESOLVED"
        reason = identity.reason

        if identity.resolved:
            provenance_class = "PARTIAL"
            holdings = resolve_positions(
                session, identity.identity_id or "", tenant_id=self._tenant_of(context)
            )
            match = next(
                (h for h in holdings if official is not None and h.official_id == official.id),
                None,
            )
            if match is not None:
                position_id = match.position_id
                provenance_class = "PROVEN"
                reason = "مبدأ ← هوية ← مسؤول ← منصب ← مؤسسة: كل حلقةٍ صفٌّ مقروء"
            else:
                reason = (
                    "الهوية ثابتة ولا منصبَ نشطًا لها منسوبًا إلى هذا القرار — "
                    "سلطةٌ من صلاحية دور لا من منصب"
                )

        row = DecisionProvenanceModel(
            decision_id=decision.id,
            principal_id=context.principal_id,
            identity_id=identity.identity_id,
            official_id=official.id if official is not None else None,
            position_id=position_id,
            institution_id=case.institution_id,
            provenance_class=provenance_class,
            reason=reason,
            session_id=context.session_id,
            correlation_id=context.correlation_id,
            tenant_id=case.tenant_id,
        )
        session.add(row)
        return {
            "decision_id": decision.id,
            "principal_id": context.principal_id,
            "identity_id": identity.identity_id,
            "official_id": official.id if official is not None else None,
            "position_id": position_id,
            "institution_id": case.institution_id,
            "provenance_class": provenance_class,
            "reason": reason,
        }

    def close_case(self, *, context: AuthorizationContext, reference: str) -> dict[str, Any]:
        """أغلق قضية صدر فيها قرار — ولا تُغلَق قضية بلا قرار."""
        require_domain_permission(context, "gov.case.close", PERMISSIONS_CASE_ASSIGN)
        session = self._session()
        try:
            case = self._case_row(session, context, reference)
            if case.status == "closed":
                raise CaseStateError(f"القضية '{reference}' مغلقة بالفعل")
            decision = session.query(DecisionModel).filter(DecisionModel.case_id == case.id).first()
            if decision is None:
                raise CaseStateError(f"القضية '{reference}' بلا قرار — لا تُغلق قضية بلا قرار فيها")
            case.status = "closed"
            case.updated_at = _now()
            session.commit()
            entity = self._case_dict(case)
            decision_id = decision.id
        finally:
            session.close()

        trace = record_domain_trace(
            context,
            "gov.case.close",
            EVENT_CASE_CLOSED,
            {
                "case_id": entity["id"],
                "reference": entity["reference"],
                "decision_id": decision_id,
                "task_id": entity["task_id"],
                "tenant_id": entity["tenant_id"],
            },
        )
        return {**entity, **trace}

    # ── قراءة ────────────────────────────────────────────────────────────

    def list_services(
        self,
        *,
        context: AuthorizationContext,
        institution_code: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """اسرد خدمات مستأجر السياق وحده."""
        require_domain_permission(context, "gov.service.read", PERMISSIONS_GOV_READ)
        session = self._session()
        try:
            query = session.query(ServiceModel).filter(
                ServiceModel.tenant_id == self._tenant_of(context)
            )
            if institution_code is not None:
                institution = self._institution_row(session, context, institution_code)
                query = query.filter(ServiceModel.institution_id == institution.id)
            if status is not None:
                query = query.filter(ServiceModel.status == status)
            rows = query.order_by(ServiceModel.code).limit(limit).all()
            return [self._service_dict(row) for row in rows]
        finally:
            session.close()

    def get_case(self, reference: str, *, context: AuthorizationContext) -> dict[str, Any]:
        """اقرأ قضية واحدة — القراءة مُخوَّلة أيضًا."""
        require_domain_permission(context, "gov.case.read", PERMISSIONS_GOV_READ)
        session = self._session()
        try:
            return self._case_dict(self._case_row(session, context, reference))
        finally:
            session.close()

    def list_cases(
        self,
        *,
        context: AuthorizationContext,
        institution_code: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """اسرد قضايا مستأجر السياق وحده."""
        require_domain_permission(context, "gov.case.read", PERMISSIONS_GOV_READ)
        session = self._session()
        try:
            query = session.query(CaseModel).filter(CaseModel.tenant_id == self._tenant_of(context))
            if institution_code is not None:
                institution = self._institution_row(session, context, institution_code)
                query = query.filter(CaseModel.institution_id == institution.id)
            if status is not None:
                query = query.filter(CaseModel.status == status)
            rows = query.order_by(CaseModel.created_at.desc()).limit(limit).all()
            return [self._case_dict(row) for row in rows]
        finally:
            session.close()

    def case_file(self, reference: str, *, context: AuthorizationContext) -> dict[str, Any]:
        """ملفّ القضية كاملًا من صفوف حقيقية: الخدمة والمؤسسة والمنصب والقرار والمهمّة."""
        require_domain_permission(context, "gov.case.read", PERMISSIONS_GOV_READ)
        session = self._session()
        try:
            case = self._case_row(session, context, reference)
            service = session.query(ServiceModel).filter(ServiceModel.id == case.service_id).first()
            institution = (
                session.query(InstitutionModel)
                .filter(InstitutionModel.id == case.institution_id)
                .first()
            )
            official = (
                session.query(OfficialModel)
                .filter(OfficialModel.id == case.assigned_official_id)
                .first()
                if case.assigned_official_id
                else None
            )
            decision = session.query(DecisionModel).filter(DecisionModel.case_id == case.id).first()
            return {
                "case": self._case_dict(case),
                "service": self._service_dict(service) if service else None,
                "institution": {
                    "id": institution.id,
                    "code": institution.code,
                    "name": institution.name,
                    "branch": institution.branch,
                }
                if institution
                else None,
                "assigned_official": {
                    "id": official.id,
                    "agent_id": official.agent_id,
                    "title": official.title,
                    "status": official.status,
                }
                if official
                else None,
                "decision": self._decision_dict(decision) if decision else None,
            }
        finally:
            session.close()

    def services_health(self, *, context: AuthorizationContext) -> dict[str, Any]:
        """إحصاء من القاعدة لا تقدير."""
        require_domain_permission(context, "gov.service.read", PERMISSIONS_GOV_READ)
        tenant = self._tenant_of(context)
        session = self._session()
        try:
            services = session.query(ServiceModel).filter(ServiceModel.tenant_id == tenant).all()
            cases = session.query(CaseModel).filter(CaseModel.tenant_id == tenant).all()
            decisions = session.query(DecisionModel).filter(DecisionModel.tenant_id == tenant).all()
            cases_by_status: dict[str, int] = {}
            for row in cases:
                cases_by_status[row.status] = cases_by_status.get(row.status, 0) + 1
            outcomes: dict[str, int] = {}
            for row in decisions:
                outcomes[row.outcome] = outcomes.get(row.outcome, 0) + 1
            return {
                "tenant_id": tenant,
                "services": len(services),
                "services_active": sum(1 for row in services if row.status == "active"),
                "cases": len(cases),
                "cases_by_status": cases_by_status,
                "decisions": len(decisions),
                "decisions_by_outcome": outcomes,
                "sovereign_reader": has_sovereign_authority(context),
            }
        finally:
            session.close()


_SERVICES: GovernmentServices | None = None


def get_government_services() -> GovernmentServices:
    """النسخة المشتركة — كما في بقية خدمات المستودع."""
    global _SERVICES  # noqa: PLW0603 — نمط قائم في المستودع
    if _SERVICES is None:
        _SERVICES = GovernmentServices()
    return _SERVICES


def reset_government_services() -> None:
    """للاختبارات: أعِد التهيئة على قاعدة نظيفة."""
    global _SERVICES  # noqa: PLW0603 — نمط قائم في المستودع
    _SERVICES = None


__all__ = [
    "CASE_TASK_DOMAIN",
    "CASE_TASK_TYPE",
    "EVENT_CASE_ASSIGNED",
    "EVENT_CASE_CLOSED",
    "EVENT_CASE_DECIDED",
    "EVENT_CASE_OPENED",
    "EVENT_CASE_REVIEWED",
    "EVENT_SERVICE_PUBLISHED",
    "EVENT_SERVICE_STATUS_CHANGED",
    "GOVERNMENT_EVENTS",
    "CaseNotFoundError",
    "CaseStateError",
    "DecisionExistsError",
    "DuplicateReferenceError",
    "DuplicateServiceCodeError",
    "GovernmentServiceError",
    "GovernmentServices",
    "OfficialNotFoundError",
    "ReviewIncompleteError",
    "ServiceInactiveError",
    "ServiceNotFoundError",
    "UnknownApplicantError",
    "get_government_services",
    "reset_government_services",
]
