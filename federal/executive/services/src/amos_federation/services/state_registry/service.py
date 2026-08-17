"""
AMOS-Federation State Registry — Service Layer
الهدف: عمليات السجل الفدرالي فوق قاعدة البيانات، بحدّ تخويل وتدقيق وأحداث دائمة
النطاق: services/state_registry
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17 (R7-A)

## ما تفعله هذه الطبقة فعلًا

كل عملية كتابة تمرّ بالترتيب نفسه، ولا واحدة تقفز خطوة:

    require_domain_permission → require_tenant → كتابة في القاعدة
      → PersistentAuditStore.append → DurableEventBus.publish

التدقيق **قبل** الحدث بقصد: سلسلة التدقيق هي السجلّ الذي لا يُعدَّل، والحدث
إعلانٌ عنها يحمل `audit_id`. ولو نُشر الحدث أولًا لأمكن أن يوجد إعلانٌ عن أثرٍ
لا سجلّ له.

## لا مخزن ولا ناقل ولا مدقِّق جديد

`get_durable_event_bus()` و`PersistentAuditStore` و`get_session_factory()` كلها
قائمة في المستودع من قبل. هذه الوحدة تستعملها ولا تُنشئ موازيًا لها.

## حدود تُقال

- **رئاسة الإدارة** مفروضة هنا لا في المخطَّط (فهرس جزئي غير محمول) — والفرض
  فعليّ ومُختبَر، لكنه في طبقة الخدمة، فمن كتب في الجدول مباشرة تجاوزه.
- **الحلّ لا يُشلّل**: `dissolve` يُرفَض ما بقيت إدارةٌ نشطة أو مسؤولٌ مُقلَّد،
  ولا تُحذَف صفوف تابعة تلقائيًّا (`ondelete="RESTRICT"`). الدولة لا تُخفي أثر
  مؤسسة بحذفها.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from amos_federation.common.database import get_session_factory, init_db
from amos_federation.common.principal import DEFAULT_TENANT
from amos_federation.services.executive_core.agent_identity import get_identity
from amos_federation.services.state_registry.authorization import (
    PERMISSIONS_DEPARTMENT_WRITE,
    PERMISSIONS_INSTITUTION_WRITE,
    PERMISSIONS_OFFICIAL_WRITE,
    PERMISSIONS_REGISTRY_READ,
    require_domain_permission,
    require_tenant,
)
from amos_federation.services.state_registry.models import (
    INSTITUTION_BRANCHES,
    INSTITUTION_KINDS,
    INSTITUTION_STATUSES,
    DepartmentModel,
    InstitutionModel,
    OfficialModel,
)
from amos_federation.services.state_registry.trace import record_domain_trace

if TYPE_CHECKING:
    from amos_federation.common.principal import AuthorizationContext

# === أسماء الأحداث — مُسجَّلة في `EVENT_CONTRACTS` ===

EVENT_INSTITUTION_REGISTERED = "amos_federation.registry.institution_registered"
EVENT_INSTITUTION_STATUS_CHANGED = "amos_federation.registry.institution_status_changed"
EVENT_DEPARTMENT_CREATED = "amos_federation.registry.department_created"
EVENT_OFFICIAL_APPOINTED = "amos_federation.registry.official_appointed"
EVENT_OFFICIAL_REVOKED = "amos_federation.registry.official_revoked"

REGISTRY_EVENTS: tuple[str, ...] = (
    EVENT_INSTITUTION_REGISTERED,
    EVENT_INSTITUTION_STATUS_CHANGED,
    EVENT_DEPARTMENT_CREATED,
    EVENT_OFFICIAL_APPOINTED,
    EVENT_OFFICIAL_REVOKED,
)


# === أخطاء النطاق ===


class RegistryError(RuntimeError):
    """أصل أخطاء السجل — كلها رفعٌ صريح لا قيمة فارغة."""


class InstitutionNotFoundError(RegistryError):
    """لا مؤسسة بهذا الرمز في مستأجر السياق."""


class DepartmentNotFoundError(RegistryError):
    """لا إدارة بهذا الرمز في هذه المؤسسة."""


class OfficialNotFoundError(RegistryError):
    """لا تقليد بهذا المعرّف."""


class DuplicateCodeError(RegistryError):
    """الرمز مستعمل — القيد في القاعدة، وهذا فحصٌ مسبق برسالة مفهومة."""


class InstitutionInactiveError(RegistryError):
    """المؤسسة ليست نشطة — لا إدارة ولا تقليد تحت مؤسسة موقوفة أو محلولة."""


class UnknownAgentError(RegistryError):
    """لا وكيل بهذا المعرّف — المسؤول وكيلٌ مُقلَّد، ولا هوية تُختَرع هنا."""


class DepartmentHeadConflictError(RegistryError):
    """للإدارة رئيسٌ مُقلَّد بالفعل — رئيسٌ واحد لكل إدارة."""


class InstitutionNotEmptyError(RegistryError):
    """لا يُحلّ ما تحته إدارات نشطة أو مسؤولون مُقلَّدون."""


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


class StateRegistry:
    """السجل الفدرالي للمؤسسات والإدارات والمسؤولين."""

    def __init__(self) -> None:
        init_db()

    # ── أدوات داخلية ─────────────────────────────────────────────────────

    def _session(self):
        return get_session_factory()()

    def _tenant_of(self, context: AuthorizationContext) -> str:
        return context.tenant_id or DEFAULT_TENANT

    def _record(
        self,
        context: AuthorizationContext,
        action: str,
        subject: str,
        entity: dict[str, Any],
    ) -> dict[str, Any]:
        """اكتب أثرًا مُدقَّقًا ثم أعلنه حدثًا دائمًا — بهذا الترتيب.

        الحدث يحمل ما يلزم لتتبّعه إلى الكيان والفاعل والارتباط (R7-G):
        معرّف الكيان في الحمولة، `actor` هو المبدأ، `correlation_id` من السياق،
        والوقت يُضيفه الناقل.

        التنفيذ في `trace.record_domain_trace` — استُخرج في الوحدة 2 ليستعمله
        نطاق الخدمات الحكومية نفسه، فلا يوجد ترتيبان للأثر يتباعدان.
        """
        return record_domain_trace(context, action, subject, entity)

    # ── قراءة ────────────────────────────────────────────────────────────

    def _institution_row(self, session, context: AuthorizationContext, code: str):
        tenant = self._tenant_of(context)
        row = (
            session.query(InstitutionModel)
            .filter(InstitutionModel.code == code, InstitutionModel.tenant_id == tenant)
            .first()
        )
        if row is None:
            raise InstitutionNotFoundError(f"لا مؤسسة برمز '{code}' في مستأجر '{tenant}'")
        require_tenant(context, row.tenant_id)
        return row

    @staticmethod
    def _institution_dict(row: InstitutionModel) -> dict[str, Any]:
        return {
            "id": row.id,
            "code": row.code,
            "name": row.name,
            "kind": row.kind,
            "branch": row.branch,
            "status": row.status,
            "mandate": row.mandate or "",
            "parent_institution_id": row.parent_institution_id,
            "tenant_id": row.tenant_id,
            "created_by": row.created_by,
            "created_at": _iso(row.created_at),
        }

    @staticmethod
    def _department_dict(row: DepartmentModel) -> dict[str, Any]:
        return {
            "id": row.id,
            "institution_id": row.institution_id,
            "code": row.code,
            "name": row.name,
            "mandate": row.mandate or "",
            "status": row.status,
            "tenant_id": row.tenant_id,
            "created_by": row.created_by,
            "created_at": _iso(row.created_at),
        }

    @staticmethod
    def _official_dict(row: OfficialModel) -> dict[str, Any]:
        return {
            "id": row.id,
            "agent_id": row.agent_id,
            "institution_id": row.institution_id,
            "department_id": row.department_id,
            "title": row.title,
            "status": row.status,
            "is_head": bool(row.is_head),
            "appointed_by": row.appointed_by,
            "appointed_at": _iso(row.appointed_at),
            "revoked_at": _iso(row.revoked_at),
            "revocation_reason": row.revocation_reason or "",
            "tenant_id": row.tenant_id,
        }

    def get_institution(self, code: str, *, context: AuthorizationContext) -> dict[str, Any]:
        """اقرأ مؤسسة واحدة — القراءة مُخوَّلة أيضًا، لا مفتوحة."""
        require_domain_permission(context, "registry.institution.read", PERMISSIONS_REGISTRY_READ)
        session = self._session()
        try:
            return self._institution_dict(self._institution_row(session, context, code))
        finally:
            session.close()

    def list_institutions(
        self,
        *,
        context: AuthorizationContext,
        kind: str | None = None,
        branch: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """اسرد مؤسسات مستأجر السياق وحده — لا سردًا عابرًا للمستأجرين."""
        require_domain_permission(context, "registry.institution.list", PERMISSIONS_REGISTRY_READ)
        session = self._session()
        try:
            query = session.query(InstitutionModel).filter(
                InstitutionModel.tenant_id == self._tenant_of(context)
            )
            if kind:
                query = query.filter(InstitutionModel.kind == kind)
            if branch:
                query = query.filter(InstitutionModel.branch == branch)
            if status:
                query = query.filter(InstitutionModel.status == status)
            rows = query.order_by(InstitutionModel.code).limit(limit).all()
            return [self._institution_dict(row) for row in rows]
        finally:
            session.close()

    def list_departments(
        self, *, context: AuthorizationContext, institution_code: str
    ) -> list[dict[str, Any]]:
        """اسرد إدارات مؤسسة."""
        require_domain_permission(context, "registry.department.list", PERMISSIONS_REGISTRY_READ)
        session = self._session()
        try:
            institution = self._institution_row(session, context, institution_code)
            rows = (
                session.query(DepartmentModel)
                .filter(DepartmentModel.institution_id == institution.id)
                .order_by(DepartmentModel.code)
                .all()
            )
            return [self._department_dict(row) for row in rows]
        finally:
            session.close()

    def list_officials(
        self,
        *,
        context: AuthorizationContext,
        institution_code: str | None = None,
        include_revoked: bool = False,
    ) -> list[dict[str, Any]]:
        """اسرد المسؤولين — والمعزولون مُستثنون افتراضًا ولا يُحذَفون."""
        require_domain_permission(context, "registry.official.list", PERMISSIONS_REGISTRY_READ)
        session = self._session()
        try:
            query = session.query(OfficialModel).filter(
                OfficialModel.tenant_id == self._tenant_of(context)
            )
            if institution_code:
                institution = self._institution_row(session, context, institution_code)
                query = query.filter(OfficialModel.institution_id == institution.id)
            if not include_revoked:
                query = query.filter(OfficialModel.status != "revoked")
            return [self._official_dict(row) for row in query.all()]
        finally:
            session.close()

    def institution_chart(self, code: str, *, context: AuthorizationContext) -> dict[str, Any]:
        """مُخطَّط مؤسسة: المؤسسة ثم إداراتها ثم مسؤولو كل إدارة."""
        require_domain_permission(context, "registry.institution.chart", PERMISSIONS_REGISTRY_READ)
        session = self._session()
        try:
            institution = self._institution_row(session, context, code)
            departments = (
                session.query(DepartmentModel)
                .filter(DepartmentModel.institution_id == institution.id)
                .order_by(DepartmentModel.code)
                .all()
            )
            officials = (
                session.query(OfficialModel)
                .filter(
                    OfficialModel.institution_id == institution.id,
                    OfficialModel.status != "revoked",
                )
                .all()
            )
            by_department: dict[str | None, list[dict[str, Any]]] = {}
            for official in officials:
                by_department.setdefault(official.department_id, []).append(
                    self._official_dict(official)
                )
            return {
                "institution": self._institution_dict(institution),
                "departments": [
                    {
                        **self._department_dict(department),
                        "officials": by_department.get(department.id, []),
                    }
                    for department in departments
                ],
                "unassigned_officials": by_department.get(None, []),
            }
        finally:
            session.close()

    def registry_health(self, *, context: AuthorizationContext) -> dict[str, Any]:
        """إحصاء السجل — أرقامٌ من القاعدة لا تقديرات."""
        require_domain_permission(context, "registry.health", PERMISSIONS_REGISTRY_READ)
        session = self._session()
        tenant = self._tenant_of(context)
        try:
            institutions = (
                session.query(InstitutionModel).filter(InstitutionModel.tenant_id == tenant).all()
            )
            departments = (
                session.query(DepartmentModel).filter(DepartmentModel.tenant_id == tenant).all()
            )
            officials = session.query(OfficialModel).filter(OfficialModel.tenant_id == tenant).all()
            by_status: dict[str, int] = {status: 0 for status in INSTITUTION_STATUSES}
            for row in institutions:
                by_status[row.status] = by_status.get(row.status, 0) + 1
            return {
                "tenant_id": tenant,
                "institutions": len(institutions),
                "institutions_by_status": by_status,
                "departments": len(departments),
                "departments_active": sum(1 for row in departments if row.status == "active"),
                "officials": len(officials),
                "officials_appointed": sum(1 for row in officials if row.status == "appointed"),
            }
        finally:
            session.close()

    # ── كتابة: المؤسسات ──────────────────────────────────────────────────

    def register_institution(
        self,
        *,
        context: AuthorizationContext,
        code: str,
        name: str,
        kind: str,
        branch: str,
        mandate: str = "",
        parent_code: str | None = None,
    ) -> dict[str, Any]:
        """أسِّس مؤسسة — سلطة ملكية، لا سلطة مسؤول."""
        require_domain_permission(
            context, "registry.institution.register", PERMISSIONS_INSTITUTION_WRITE
        )
        if kind not in INSTITUTION_KINDS:
            raise RegistryError(
                f"نوع مؤسسة غير معروف '{kind}' — المعروف: {list(INSTITUTION_KINDS)}"
            )
        if branch not in INSTITUTION_BRANCHES:
            raise RegistryError(f"فرع غير معروف '{branch}' — المعروف: {list(INSTITUTION_BRANCHES)}")
        tenant = self._tenant_of(context)
        require_tenant(context, tenant)

        session = self._session()
        try:
            existing = (
                session.query(InstitutionModel)
                .filter(InstitutionModel.code == code, InstitutionModel.tenant_id == tenant)
                .first()
            )
            if existing is not None:
                raise DuplicateCodeError(f"رمز المؤسسة '{code}' مستعمل في مستأجر '{tenant}'")

            parent_id = None
            if parent_code:
                parent = self._institution_row(session, context, parent_code)
                if parent.status != "active":
                    raise InstitutionInactiveError(
                        f"المؤسسة الأمّ '{parent_code}' حالتها '{parent.status}' — لا تبعية تحتها"
                    )
                parent_id = parent.id

            row = InstitutionModel(
                id=f"inst-{uuid.uuid4()}",
                code=code,
                name=name,
                kind=kind,
                branch=branch,
                status="active",
                mandate=mandate,
                parent_institution_id=parent_id,
                tenant_id=tenant,
                created_by=context.principal_id,
            )
            session.add(row)
            session.commit()
            institution = self._institution_dict(row)
        finally:
            session.close()

        trace = self._record(
            context,
            "registry.institution.register",
            EVENT_INSTITUTION_REGISTERED,
            {
                "institution_id": institution["id"],
                "code": institution["code"],
                "kind": institution["kind"],
                "branch": institution["branch"],
                "tenant_id": institution["tenant_id"],
                "parent_institution_id": institution["parent_institution_id"],
            },
        )
        return {**institution, **trace}

    def set_institution_status(
        self,
        *,
        context: AuthorizationContext,
        code: str,
        status: str,
        reason: str,
    ) -> dict[str, Any]:
        """غيّر حالة مؤسسة — والحلّ يُرفَض ما بقي تحتها أثر نشط."""
        require_domain_permission(
            context, "registry.institution.status", PERMISSIONS_INSTITUTION_WRITE
        )
        if status not in INSTITUTION_STATUSES:
            raise RegistryError(
                f"حالة مؤسسة غير معروفة '{status}' — المعروف: {list(INSTITUTION_STATUSES)}"
            )
        session = self._session()
        try:
            row = self._institution_row(session, context, code)
            previous = row.status
            if previous == "dissolved" and status != "dissolved":
                raise RegistryError(f"المؤسسة '{code}' محلولة — لا إحياء لها في هذا المسار")
            if status == "dissolved":
                active_departments = (
                    session.query(DepartmentModel)
                    .filter(
                        DepartmentModel.institution_id == row.id,
                        DepartmentModel.status == "active",
                    )
                    .count()
                )
                appointed_officials = (
                    session.query(OfficialModel)
                    .filter(
                        OfficialModel.institution_id == row.id,
                        OfficialModel.status == "appointed",
                    )
                    .count()
                )
                if active_departments or appointed_officials:
                    raise InstitutionNotEmptyError(
                        f"لا تُحلّ '{code}': إدارات نشطة={active_departments}، "
                        f"مسؤولون مُقلَّدون={appointed_officials}"
                    )
            row.status = status
            session.commit()
            institution = self._institution_dict(row)
        finally:
            session.close()

        trace = self._record(
            context,
            "registry.institution.status",
            EVENT_INSTITUTION_STATUS_CHANGED,
            {
                "institution_id": institution["id"],
                "code": institution["code"],
                "from_status": previous,
                "to_status": status,
                "reason": reason,
                "tenant_id": institution["tenant_id"],
            },
        )
        return {**institution, "from_status": previous, **trace}

    # ── كتابة: الإدارات ──────────────────────────────────────────────────

    def create_department(
        self,
        *,
        context: AuthorizationContext,
        institution_code: str,
        code: str,
        name: str,
        mandate: str = "",
    ) -> dict[str, Any]:
        """أنشئ إدارة تحت مؤسسة نشطة."""
        require_domain_permission(
            context, "registry.department.create", PERMISSIONS_DEPARTMENT_WRITE
        )
        session = self._session()
        try:
            institution = self._institution_row(session, context, institution_code)
            if institution.status != "active":
                raise InstitutionInactiveError(
                    f"المؤسسة '{institution_code}' حالتها '{institution.status}' — لا إدارة تحتها"
                )
            existing = (
                session.query(DepartmentModel)
                .filter(
                    DepartmentModel.institution_id == institution.id,
                    DepartmentModel.code == code,
                )
                .first()
            )
            if existing is not None:
                raise DuplicateCodeError(
                    f"رمز الإدارة '{code}' مستعمل في المؤسسة '{institution_code}'"
                )
            row = DepartmentModel(
                id=f"dept-{uuid.uuid4()}",
                institution_id=institution.id,
                code=code,
                name=name,
                mandate=mandate,
                status="active",
                tenant_id=institution.tenant_id,
                created_by=context.principal_id,
            )
            session.add(row)
            session.commit()
            department = self._department_dict(row)
            institution_code_value = institution.code
        finally:
            session.close()

        trace = self._record(
            context,
            "registry.department.create",
            EVENT_DEPARTMENT_CREATED,
            {
                "department_id": department["id"],
                "institution_id": department["institution_id"],
                "institution_code": institution_code_value,
                "code": department["code"],
                "tenant_id": department["tenant_id"],
            },
        )
        return {**department, **trace}

    # ── كتابة: المسؤولون ─────────────────────────────────────────────────

    def appoint_official(
        self,
        *,
        context: AuthorizationContext,
        agent_id: str,
        institution_code: str,
        title: str,
        department_code: str | None = None,
        is_head: bool = False,
    ) -> dict[str, Any]:
        """قلِّد وكيلًا منصبًا — والوكيل يجب أن يكون موجودًا في `agents` فعلًا."""
        require_domain_permission(context, "registry.official.appoint", PERMISSIONS_OFFICIAL_WRITE)
        tenant = self._tenant_of(context)
        identity = get_identity(agent_id)
        if identity is None:
            raise UnknownAgentError(f"لا وكيل بالمعرّف '{agent_id}' — التقليد لا يُنشئ هوية جديدة")
        # هوية الوكيل تحمل مستأجرها؛ التقليد عبر الحدود يُرفَض بنفس دالّة R6.1.
        require_tenant(context, getattr(identity, "tenant_id", tenant))

        session = self._session()
        try:
            institution = self._institution_row(session, context, institution_code)
            if institution.status != "active":
                raise InstitutionInactiveError(
                    f"المؤسسة '{institution_code}' حالتها '{institution.status}' — لا تقليد فيها"
                )
            department_id = None
            if department_code:
                department = (
                    session.query(DepartmentModel)
                    .filter(
                        DepartmentModel.institution_id == institution.id,
                        DepartmentModel.code == department_code,
                    )
                    .first()
                )
                if department is None:
                    raise DepartmentNotFoundError(
                        f"لا إدارة برمز '{department_code}' في المؤسسة '{institution_code}'"
                    )
                if department.status != "active":
                    raise InstitutionInactiveError(
                        f"الإدارة '{department_code}' حالتها '{department.status}' — لا تقليد فيها"
                    )
                department_id = department.id

            if is_head:
                if department_id is None:
                    raise RegistryError("رئاسة الإدارة تلزمها إدارة — لا رئيس بلا إدارة")
                current_head = (
                    session.query(OfficialModel)
                    .filter(
                        OfficialModel.department_id == department_id,
                        OfficialModel.is_head.is_(True),
                        OfficialModel.status == "appointed",
                    )
                    .first()
                )
                if current_head is not None:
                    raise DepartmentHeadConflictError(
                        f"للإدارة '{department_code}' رئيسٌ مُقلَّد ({current_head.id}) — "
                        "اعزله قبل تقليد غيره"
                    )

            duplicate = (
                session.query(OfficialModel)
                .filter(
                    OfficialModel.agent_id == agent_id,
                    OfficialModel.institution_id == institution.id,
                    OfficialModel.department_id == department_id,
                    OfficialModel.status == "appointed",
                )
                .first()
            )
            if duplicate is not None:
                raise DuplicateCodeError(
                    f"الوكيل '{agent_id}' مُقلَّد بالفعل في هذا الموضع ({duplicate.id})"
                )

            row = OfficialModel(
                id=f"offl-{uuid.uuid4()}",
                agent_id=agent_id,
                institution_id=institution.id,
                department_id=department_id,
                title=title,
                status="appointed",
                is_head=is_head,
                appointed_by=context.principal_id,
                tenant_id=institution.tenant_id,
            )
            session.add(row)
            session.commit()
            official = self._official_dict(row)
        finally:
            session.close()

        trace = self._record(
            context,
            "registry.official.appoint",
            EVENT_OFFICIAL_APPOINTED,
            {
                "official_id": official["id"],
                "agent_id": official["agent_id"],
                "institution_id": official["institution_id"],
                "department_id": official["department_id"],
                "title": official["title"],
                "is_head": official["is_head"],
                "tenant_id": official["tenant_id"],
            },
        )
        return {**official, **trace}

    def revoke_official(
        self, *, context: AuthorizationContext, official_id: str, reason: str
    ) -> dict[str, Any]:
        """اعزل مسؤولًا — الصفّ يبقى بحالة `revoked`، ولا يُحذَف أثره."""
        require_domain_permission(context, "registry.official.revoke", PERMISSIONS_OFFICIAL_WRITE)
        session = self._session()
        try:
            row = session.query(OfficialModel).filter(OfficialModel.id == official_id).first()
            if row is None:
                raise OfficialNotFoundError(f"لا تقليد بالمعرّف '{official_id}'")
            require_tenant(context, row.tenant_id)
            if row.status == "revoked":
                raise RegistryError(f"التقليد '{official_id}' معزولٌ بالفعل")
            row.status = "revoked"
            row.revoked_at = _now()
            row.revocation_reason = reason
            row.is_head = False
            session.commit()
            official = self._official_dict(row)
        finally:
            session.close()

        trace = self._record(
            context,
            "registry.official.revoke",
            EVENT_OFFICIAL_REVOKED,
            {
                "official_id": official["id"],
                "agent_id": official["agent_id"],
                "institution_id": official["institution_id"],
                "reason": reason,
                "tenant_id": official["tenant_id"],
            },
        )
        return {**official, **trace}


_registry: StateRegistry | None = None


def get_state_registry() -> StateRegistry:
    """الوصول الموحَّد إلى السجل — مثيلٌ واحد لكل عملية."""
    global _registry
    if _registry is None:
        _registry = StateRegistry()
    return _registry


def reset_state_registry() -> None:
    """إعادة التعيين — للاختبارات وحدها."""
    global _registry
    _registry = None


__all__ = [
    "EVENT_DEPARTMENT_CREATED",
    "EVENT_INSTITUTION_REGISTERED",
    "EVENT_INSTITUTION_STATUS_CHANGED",
    "EVENT_OFFICIAL_APPOINTED",
    "EVENT_OFFICIAL_REVOKED",
    "REGISTRY_EVENTS",
    "DepartmentHeadConflictError",
    "DepartmentNotFoundError",
    "DuplicateCodeError",
    "InstitutionInactiveError",
    "InstitutionNotEmptyError",
    "InstitutionNotFoundError",
    "OfficialNotFoundError",
    "RegistryError",
    "StateRegistry",
    "UnknownAgentError",
    "get_state_registry",
    "reset_state_registry",
]
