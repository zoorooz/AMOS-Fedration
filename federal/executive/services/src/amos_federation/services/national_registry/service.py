"""
AMOS-Federation National Registry — Service Layer
الهدف: إنشاء الهويات وربطها ومنح سلطات المناصب، بحدّ تخويل وتدقيق وأحداث دائمة
النطاق: services/national_registry
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17 (R7-C2 · R7-C3 · R7-C4 · R7-C5)

## نفس ترتيب الأثر — لا ترتيب ثانٍ

    require_domain_permission → require_tenant → كتابة في القاعدة
      → PersistentAuditStore.append → DurableEventBus.publish

والتنفيذ نفسه: `record_domain_trace` المُستخرَجة في R7-A. لا ناقل أحداث جديد،
ولا مخزن تدقيق جديد، ولا مُنفِّذ مهامّ خاصٌّ بالسجل.

## لا دمج تلقائي للهويات

لا دالّة هنا تُوحّد هويتين. `link_principal` و`link_agent` كلٌّ منهما يرفض إن كان
الطرف مربوطًا بهوية أخرى (`IdentityConflictError`) — فالربط الخاطئ يُصحَّح بقرار
صريح لا بدمجٍ صامت. و`create_identity(status="unresolved")` هو الجواب حين لا
يُمكن إثبات المرجع: هويةٌ مُسمَّاة الغموض، لا هويةٌ مُختلَقة ولا صفٌّ فارغ.

## الحذف ليس أداةً هنا

لا دالّة حذف في هذه الوحدة. عزل التقليد وسحب المِنحة يُغيّران `status` ويكتبان
`revoked_at` والسبب، فتبقى الصفوف تاريخًا يُقرأ. و`ondelete="RESTRICT"` على كل
مفتاح أجنبي يمنع أن يمحو حذفٌ في مكانٍ آخر سلسلةَ إسنادٍ هنا.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from amos_federation.common.database import get_session_factory, init_db
from amos_federation.common.principal import DEFAULT_TENANT
from amos_federation.services.executive_core.agent_identity import get_identity
from amos_federation.services.national_registry.authorization import (
    PERMISSIONS_AGENT_LINK,
    PERMISSIONS_ASSIGNMENT_WRITE,
    PERMISSIONS_GRANT_WRITE,
    PERMISSIONS_IDENTITY_READ,
    PERMISSIONS_IDENTITY_WRITE,
    PERMISSIONS_POSITION_WRITE,
    PERMISSIONS_PRINCIPAL_LINK,
    require_domain_permission,
    require_tenant,
)
from amos_federation.services.national_registry.models import (
    AUTHORITY_SCOPES,
    GRANTABLE_OPERATIONS,
    IDENTITY_STATUSES,
    IDENTITY_TYPES,
    AuthorityGrantModel,
    IdentityAgentModel,
    IdentityModel,
    IdentityPrincipalModel,
    OfficialPositionModel,
    PositionModel,
)
from amos_federation.services.national_registry.resolver import (
    describe_chain,
    resolve_identity,
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

# === أسماء الأحداث — مُسجَّلة في `EVENT_CONTRACTS` ===

EVENT_IDENTITY_CREATED = "amos_federation.registry.identity_created"
EVENT_IDENTITY_STATUS_CHANGED = "amos_federation.registry.identity_status_changed"
EVENT_PRINCIPAL_LINKED = "amos_federation.registry.principal_linked"
EVENT_AGENT_IDENTITY_LINKED = "amos_federation.registry.agent_identity_linked"
EVENT_POSITION_CREATED = "amos_federation.registry.position_created"
EVENT_POSITION_GRANTED = "amos_federation.registry.position_granted"
EVENT_POSITION_REVOKED = "amos_federation.registry.position_revoked"
EVENT_AUTHORITY_CHANGED = "amos_federation.registry.authority_changed"

NATIONAL_REGISTRY_EVENTS: tuple[str, ...] = (
    EVENT_IDENTITY_CREATED,
    EVENT_IDENTITY_STATUS_CHANGED,
    EVENT_PRINCIPAL_LINKED,
    EVENT_AGENT_IDENTITY_LINKED,
    EVENT_POSITION_CREATED,
    EVENT_POSITION_GRANTED,
    EVENT_POSITION_REVOKED,
    EVENT_AUTHORITY_CHANGED,
)


# === أخطاء النطاق ===


class NationalRegistryError(RuntimeError):
    """أصل أخطاء السجل الوطني — كلها رفعٌ صريح لا قيمة فارغة."""


class IdentityNotFoundError(NationalRegistryError):
    """لا هوية بهذا المعرّف في مستأجر السياق."""


class IdentityConflictError(NationalRegistryError):
    """الطرف مربوطٌ بهوية أخرى — ولا دمج تلقائيّ يحلّ هذا."""


class PositionNotFoundError(NationalRegistryError):
    """لا منصب بهذا الرمز في هذه المؤسسة."""


class PositionInactiveError(NationalRegistryError):
    """المنصب ليس نشطًا — لا تقليد ولا مِنحة على منصب ملغى."""


class AssignmentNotFoundError(NationalRegistryError):
    """لا تقليد منصبٍ بهذا المعرّف."""


class DuplicateAssignmentError(NationalRegistryError):
    """هذا المسؤول يشغل هذا المنصب بالفعل — القيد في القاعدة، وهذا فحصٌ مسبق."""


class GrantNotFoundError(NationalRegistryError):
    """لا مِنحة سلطةٍ بهذا المعرّف."""


class InvalidGrantTargetError(NationalRegistryError):
    """هدف المِنحة لا يطابق نطاقها أو لا ينتمي إلى مؤسسة المنصب."""


class UnknownAgentError(NationalRegistryError):
    """لا وكيل بهذا المعرّف — الربط لا يُنشئ وكيلًا (R7-C5)."""


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


class NationalRegistry:
    """السجل الوطني: الهوية الكانونية وروابطها ومناصبها وسلطاتها."""

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
        return record_domain_trace(context, action, subject, entity)

    @staticmethod
    def _identity_dict(row: IdentityModel) -> dict[str, Any]:
        return {
            "id": row.id,
            "identity_type": row.identity_type,
            "status": row.status,
            "label": row.label or "",
            "status_reason": row.status_reason or "",
            "tenant_id": row.tenant_id,
            "created_by": row.created_by,
            "created_at": _iso(row.created_at),
            "updated_at": _iso(row.updated_at),
        }

    @staticmethod
    def _position_dict(row: PositionModel) -> dict[str, Any]:
        return {
            "id": row.id,
            "code": row.code,
            "title": row.title,
            "institution_id": row.institution_id,
            "department_id": row.department_id,
            "authority_scope": row.authority_scope,
            "status": row.status,
            "mandate": row.mandate or "",
            "tenant_id": row.tenant_id,
            "created_by": row.created_by,
            "created_at": _iso(row.created_at),
        }

    @staticmethod
    def _assignment_dict(row: OfficialPositionModel) -> dict[str, Any]:
        return {
            "id": row.id,
            "official_id": row.official_id,
            "identity_id": row.identity_id,
            "position_id": row.position_id,
            "status": row.status,
            "assigned_by": row.assigned_by,
            "assigned_at": _iso(row.assigned_at),
            "revoked_at": _iso(row.revoked_at),
            "revocation_reason": row.revocation_reason or "",
            "tenant_id": row.tenant_id,
        }

    @staticmethod
    def _grant_dict(row: AuthorityGrantModel) -> dict[str, Any]:
        return {
            "id": row.id,
            "position_id": row.position_id,
            "operation": row.operation,
            "scope": row.scope,
            "institution_id": row.institution_id,
            "department_id": row.department_id,
            "budget_id": row.budget_id,
            "account_id": row.account_id,
            "max_amount": row.max_amount,
            "status": row.status,
            "granted_by": row.granted_by,
            "granted_at": _iso(row.granted_at),
            "revoked_at": _iso(row.revoked_at),
            "revocation_reason": row.revocation_reason or "",
            "tenant_id": row.tenant_id,
        }

    def _identity_row(self, session, context: AuthorizationContext, identity_id: str):
        row = session.get(IdentityModel, identity_id)
        if row is None or row.tenant_id != self._tenant_of(context):
            raise IdentityNotFoundError(
                f"لا هوية بالمعرّف '{identity_id}' في مستأجر '{self._tenant_of(context)}'"
            )
        require_tenant(context, row.tenant_id)
        return row

    def _institution_row(self, session, context: AuthorizationContext, code: str):
        tenant = self._tenant_of(context)
        row = (
            session.query(InstitutionModel)
            .filter(InstitutionModel.code == code, InstitutionModel.tenant_id == tenant)
            .first()
        )
        if row is None:
            raise NationalRegistryError(f"لا مؤسسة برمز '{code}' في مستأجر '{tenant}'")
        require_tenant(context, row.tenant_id)
        return row

    # ── R7-C2: الهوية الكانونية ──────────────────────────────────────────

    def create_identity(
        self,
        *,
        context: AuthorizationContext,
        identity_type: str,
        label: str = "",
        status: str = "active",
        status_reason: str = "",
    ) -> dict[str, Any]:
        """أنشئ هويةً كانونية — بمعرّفٍ مستقرّ لا باسمٍ ولا بدور.

        `label` وصفٌ للعرض ولا يُستعمل في التعريف ولا يحمل قيدًا فريدًا. والغموض
        يُنشأ صريحًا: `status="unresolved"` مع سببٍ مكتوب، ولا هوية تُختلق.
        """
        require_domain_permission(context, "identity.create", PERMISSIONS_IDENTITY_WRITE)
        if identity_type not in IDENTITY_TYPES:
            raise ValueError(
                f"نوع هوية غير معروف '{identity_type}' — المفردة: {list(IDENTITY_TYPES)}"
            )
        if status not in IDENTITY_STATUSES:
            raise ValueError(
                f"حالة هوية غير معروفة '{status}' — المفردة: {list(IDENTITY_STATUSES)}"
            )
        if status == "unresolved" and not status_reason:
            raise ValueError("الهوية غير المحلولة تلزمها كتابة سببها — الغموض يُسمّى ولا يُترك فراغًا")

        tenant = self._tenant_of(context)
        session = self._session()
        try:
            row = IdentityModel(
                id=f"idn-{uuid.uuid4()}",
                identity_type=identity_type,
                status=status,
                label=label,
                status_reason=status_reason,
                tenant_id=tenant,
                created_by=context.principal_id,
            )
            session.add(row)
            session.commit()
            identity = self._identity_dict(row)
        finally:
            session.close()

        trace = self._record(
            context,
            "identity.create",
            EVENT_IDENTITY_CREATED,
            {
                "identity_id": identity["id"],
                "identity_type": identity["identity_type"],
                "status": identity["status"],
                "tenant_id": identity["tenant_id"],
            },
        )
        return {**identity, **trace}

    def set_identity_status(
        self,
        *,
        context: AuthorizationContext,
        identity_id: str,
        status: str,
        reason: str,
    ) -> dict[str, Any]:
        """غيّر حالة هوية — تعليقًا أو تقاعدًا أو حلًّا لغموضٍ سابق."""
        require_domain_permission(context, "identity.status", PERMISSIONS_IDENTITY_WRITE)
        if status not in IDENTITY_STATUSES:
            raise ValueError(
                f"حالة هوية غير معروفة '{status}' — المفردة: {list(IDENTITY_STATUSES)}"
            )
        if not reason:
            raise ValueError("تغيير حالة الهوية يلزمه سبب مكتوب")

        session = self._session()
        try:
            row = self._identity_row(session, context, identity_id)
            previous = row.status
            row.status = status
            row.status_reason = reason
            row.updated_at = _now()
            session.commit()
            identity = self._identity_dict(row)
        finally:
            session.close()

        trace = self._record(
            context,
            "identity.status",
            EVENT_IDENTITY_STATUS_CHANGED,
            {
                "identity_id": identity_id,
                "previous_status": previous,
                "status": status,
                "reason": reason,
                "tenant_id": identity["tenant_id"],
            },
        )
        return {**identity, "previous_status": previous, **trace}

    # ── R7-C3: المبدأ ← الهوية ───────────────────────────────────────────

    def link_principal(
        self,
        *,
        context: AuthorizationContext,
        principal_id: str,
        identity_id: str,
        binding_source: str = "ADMIN",
    ) -> dict[str, Any]:
        """اربط مبدأً بهويته الكانونية — والربط قرارٌ إداريٌّ مُخوَّل.

        لا يستطيع مبدأٌ أن يربط نفسه بهوية عبر طلبٍ عاديّ: العملية تلزمها
        `manage:all`. وهذا هو معنى «لا يحدّد المُستدعي هويته»: الجلسة تحمل اسمًا،
        وتحويله إلى هوية يجري في هذا الجدول لا في جسم الطلب.

        Raises:
            IdentityConflictError: المبدأ مربوطٌ بهوية أخرى — لا دمج صامت.
        """
        require_domain_permission(context, "identity.principal.link", PERMISSIONS_PRINCIPAL_LINK)
        tenant = self._tenant_of(context)
        session = self._session()
        try:
            identity = self._identity_row(session, context, identity_id)
            existing = (
                session.query(IdentityPrincipalModel)
                .filter(
                    IdentityPrincipalModel.principal_id == principal_id,
                    IdentityPrincipalModel.tenant_id == tenant,
                )
                .first()
            )
            if existing is not None:
                if existing.identity_id == identity_id:
                    return {**self._link_dict(existing), "created": False}
                raise IdentityConflictError(
                    f"المبدأ '{principal_id}' مربوطٌ بالهوية '{existing.identity_id}' — "
                    "لا يُدمَج تلقائيًّا؛ افصل الربط بقرار صريح أولًا"
                )
            row = IdentityPrincipalModel(
                id=f"idp-{uuid.uuid4()}",
                principal_id=principal_id,
                identity_id=identity.id,
                binding_source=binding_source,
                tenant_id=tenant,
                linked_by=context.principal_id,
            )
            session.add(row)
            session.commit()
            link = self._link_dict(row)
        finally:
            session.close()

        trace = self._record(
            context,
            "identity.principal.link",
            EVENT_PRINCIPAL_LINKED,
            {
                "link_id": link["id"],
                "principal_id": principal_id,
                "identity_id": identity_id,
                "binding_source": binding_source,
                "tenant_id": tenant,
            },
        )
        return {**link, "created": True, **trace}

    @staticmethod
    def _link_dict(row: IdentityPrincipalModel) -> dict[str, Any]:
        return {
            "id": row.id,
            "principal_id": row.principal_id,
            "identity_id": row.identity_id,
            "binding_source": row.binding_source,
            "tenant_id": row.tenant_id,
            "linked_by": row.linked_by,
            "created_at": _iso(row.created_at),
        }

    # ── R7-C5: الوكيل ← الهوية ──────────────────────────────────────────

    def link_agent(
        self,
        *,
        context: AuthorizationContext,
        agent_id: str,
        identity_id: str | None = None,
    ) -> dict[str, Any]:
        """اربط وكيلًا تشغيليًّا قائمًا بهويةٍ كانونية — R7-C5.

        الوكيل يجب أن يكون موجودًا في `agents` (سجلّ R4 الكانوني): لا يُنشأ وكيل
        هنا ولا تُنسَخ صلاحياته ولا تُلمَس دورة حياته. وإن لم تُعطَ `identity_id`
        أُنشئت هوية من نوع `AGENT` وربُطت به — وهذا **ليس** دمج الجدولين: صفّان في
        جدولين وصفُّ ربطٍ بينهما.

        Raises:
            UnknownAgentError: لا وكيل بهذا المعرّف.
            IdentityConflictError: الوكيل أو الهوية مربوطٌ بغيره.
        """
        require_domain_permission(context, "identity.agent.link", PERMISSIONS_AGENT_LINK)
        agent = get_identity(agent_id)
        if agent is None:
            raise UnknownAgentError(f"لا وكيل بالمعرّف '{agent_id}' — الربط لا يُنشئ وكيلًا")
        require_tenant(context, getattr(agent, "tenant_id", self._tenant_of(context)))
        tenant = self._tenant_of(context)

        created_identity: dict[str, Any] | None = None
        if identity_id is None:
            created_identity = self.create_identity(
                context=context,
                identity_type="AGENT",
                label=getattr(agent, "name", "") or agent_id,
            )
            identity_id = created_identity["id"]

        session = self._session()
        try:
            identity = self._identity_row(session, context, identity_id)
            by_agent = (
                session.query(IdentityAgentModel)
                .filter(IdentityAgentModel.agent_id == agent_id)
                .first()
            )
            if by_agent is not None:
                if by_agent.identity_id == identity_id:
                    return {**self._agent_link_dict(by_agent), "created": False}
                raise IdentityConflictError(
                    f"الوكيل '{agent_id}' مربوطٌ بالهوية '{by_agent.identity_id}' — لا دمج تلقائيّ"
                )
            by_identity = (
                session.query(IdentityAgentModel)
                .filter(IdentityAgentModel.identity_id == identity_id)
                .first()
            )
            if by_identity is not None:
                raise IdentityConflictError(
                    f"الهوية '{identity_id}' مربوطةٌ بالوكيل '{by_identity.agent_id}'"
                )
            row = IdentityAgentModel(
                id=f"ida-{uuid.uuid4()}",
                agent_id=agent_id,
                identity_id=identity.id,
                tenant_id=tenant,
                linked_by=context.principal_id,
            )
            session.add(row)
            session.commit()
            link = self._agent_link_dict(row)
        finally:
            session.close()

        trace = self._record(
            context,
            "identity.agent.link",
            EVENT_AGENT_IDENTITY_LINKED,
            {
                "link_id": link["id"],
                "agent_id": agent_id,
                "identity_id": identity_id,
                "tenant_id": tenant,
            },
        )
        return {**link, "created": True, **trace}

    @staticmethod
    def _agent_link_dict(row: IdentityAgentModel) -> dict[str, Any]:
        return {
            "id": row.id,
            "agent_id": row.agent_id,
            "identity_id": row.identity_id,
            "tenant_id": row.tenant_id,
            "linked_by": row.linked_by,
            "created_at": _iso(row.created_at),
        }

    # ── R7-C4: المناصب ──────────────────────────────────────────────────

    def create_position(
        self,
        *,
        context: AuthorizationContext,
        code: str,
        title: str,
        institution_code: str,
        authority_scope: str,
        department_code: str | None = None,
        mandate: str = "",
    ) -> dict[str, Any]:
        """أنشئ منصبًا في مؤسسة — المنصب مصدر السلطة، مستقلٌّ عن شاغله.

        نطاق `DEPARTMENT` يلزمه إدارة، وما فوقه لا يحمل إدارة — والقيد مفروضٌ في
        القاعدة أيضًا (`ck_state_positions_department_scope`) لا هنا وحده.
        """
        require_domain_permission(context, "position.create", PERMISSIONS_POSITION_WRITE)
        if authority_scope not in AUTHORITY_SCOPES:
            raise ValueError(
                f"نطاق سلطة غير معروف '{authority_scope}' — المفردة: {list(AUTHORITY_SCOPES)}"
            )
        session = self._session()
        try:
            institution = self._institution_row(session, context, institution_code)
            if institution.status != "active":
                raise NationalRegistryError(
                    f"المؤسسة '{institution_code}' حالتها '{institution.status}' — لا منصب فيها"
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
                    raise PositionNotFoundError(
                        f"لا إدارة برمز '{department_code}' في المؤسسة '{institution_code}'"
                    )
                department_id = department.id
            if authority_scope == "DEPARTMENT" and department_id is None:
                raise InvalidGrantTargetError(
                    "نطاق الإدارة يلزمه إدارة مُسمّاة — لا سلطة إدارةٍ بلا إدارة"
                )
            if authority_scope != "DEPARTMENT" and department_id is not None:
                raise InvalidGrantTargetError(
                    f"نطاق '{authority_scope}' لا يحمل إدارة — الإدارة تخصّ نطاق DEPARTMENT وحده"
                )
            duplicate = (
                session.query(PositionModel)
                .filter(
                    PositionModel.institution_id == institution.id,
                    PositionModel.code == code,
                )
                .first()
            )
            if duplicate is not None:
                raise NationalRegistryError(
                    f"رمز المنصب '{code}' مستعمل في المؤسسة '{institution_code}'"
                )
            row = PositionModel(
                id=f"pos-{uuid.uuid4()}",
                code=code,
                title=title,
                institution_id=institution.id,
                department_id=department_id,
                authority_scope=authority_scope,
                status="active",
                mandate=mandate,
                tenant_id=institution.tenant_id,
                created_by=context.principal_id,
            )
            session.add(row)
            session.commit()
            position = self._position_dict(row)
        finally:
            session.close()

        trace = self._record(
            context,
            "position.create",
            EVENT_POSITION_CREATED,
            {
                "position_id": position["id"],
                "code": position["code"],
                "institution_id": position["institution_id"],
                "department_id": position["department_id"],
                "authority_scope": position["authority_scope"],
                "tenant_id": position["tenant_id"],
            },
        )
        return {**position, **trace}

    def assign_position(
        self,
        *,
        context: AuthorizationContext,
        official_id: str,
        position_id: str,
    ) -> dict[str, Any]:
        """قلِّد مسؤولًا قائمًا منصبًا، ونسبه إلى هويته الكانونية — R7-C4.

        شرطان لا يُتجاوزان: سجلّ المسؤول `appointed`، ووكيله مربوطٌ بهوية. فبلا
        هوية لا تقليد — لأن التقليد بلا هوية هو بالضبط ما جعل الإسناد `PARTIAL`
        قبل R7-C. والمؤسسة يجب أن تكون واحدة في الطرفين: منصبُ مؤسسةٍ لا يُقلَّد
        لمسؤولٍ في مؤسسةٍ أخرى.

        Raises:
            DuplicateAssignmentError: تقليدٌ نشطٌ لنفس (مسؤول، منصب) قائم.
            IdentityConflictError: وكيل المسؤول لا هوية كانونية له.
        """
        require_domain_permission(context, "position.assign", PERMISSIONS_ASSIGNMENT_WRITE)
        tenant = self._tenant_of(context)
        session = self._session()
        try:
            official = session.get(OfficialModel, official_id)
            if official is None or official.tenant_id != tenant:
                raise AssignmentNotFoundError(
                    f"لا تقليد رسميّ بالمعرّف '{official_id}' في مستأجر '{tenant}'"
                )
            require_tenant(context, official.tenant_id)
            if official.status != "appointed":
                raise PositionInactiveError(
                    f"المسؤول '{official_id}' حالته '{official.status}' — لا منصب لغير القائم"
                )
            position = session.get(PositionModel, position_id)
            if position is None or position.tenant_id != tenant:
                raise PositionNotFoundError(f"لا منصب بالمعرّف '{position_id}'")
            if position.status != "active":
                raise PositionInactiveError(
                    f"المنصب '{position_id}' حالته '{position.status}' — لا تقليد على منصب ملغى"
                )
            if position.institution_id != official.institution_id:
                raise InvalidGrantTargetError(
                    f"المنصب في المؤسسة '{position.institution_id}' والمسؤول في "
                    f"'{official.institution_id}' — لا تقليد عبر المؤسسات"
                )
            agent_link = (
                session.query(IdentityAgentModel)
                .filter(IdentityAgentModel.agent_id == official.agent_id)
                .first()
            )
            if agent_link is None:
                raise IdentityConflictError(
                    f"وكيل المسؤول '{official.agent_id}' لا هوية كانونية له — "
                    "اربطه بهوية قبل التقليد (R7-C5)"
                )
            duplicate = (
                session.query(OfficialPositionModel)
                .filter(
                    OfficialPositionModel.official_id == official_id,
                    OfficialPositionModel.position_id == position_id,
                    OfficialPositionModel.status == "active",
                )
                .first()
            )
            if duplicate is not None:
                raise DuplicateAssignmentError(
                    f"المسؤول '{official_id}' يشغل المنصب '{position_id}' بالفعل ({duplicate.id})"
                )
            row = OfficialPositionModel(
                id=f"opos-{uuid.uuid4()}",
                official_id=official_id,
                identity_id=agent_link.identity_id,
                position_id=position_id,
                status="active",
                assigned_by=context.principal_id,
                tenant_id=tenant,
            )
            session.add(row)
            session.commit()
            assignment = self._assignment_dict(row)
        finally:
            session.close()

        trace = self._record(
            context,
            "position.assign",
            EVENT_POSITION_GRANTED,
            {
                "assignment_id": assignment["id"],
                "official_id": official_id,
                "identity_id": assignment["identity_id"],
                "position_id": position_id,
                "tenant_id": tenant,
            },
        )
        return {**assignment, **trace}

    def revoke_assignment(
        self,
        *,
        context: AuthorizationContext,
        assignment_id: str,
        reason: str,
    ) -> dict[str, Any]:
        """اعزل تقليد منصب — والصفّ يبقى تاريخًا ولا يُحذَف."""
        require_domain_permission(context, "position.revoke", PERMISSIONS_ASSIGNMENT_WRITE)
        if not reason:
            raise ValueError("العزل يلزمه سبب مكتوب")
        tenant = self._tenant_of(context)
        session = self._session()
        try:
            row = session.get(OfficialPositionModel, assignment_id)
            if row is None or row.tenant_id != tenant:
                raise AssignmentNotFoundError(f"لا تقليد منصبٍ بالمعرّف '{assignment_id}'")
            require_tenant(context, row.tenant_id)
            if row.status == "revoked":
                return {**self._assignment_dict(row), "changed": False}
            row.status = "revoked"
            row.revoked_at = _now()
            row.revocation_reason = reason
            session.commit()
            assignment = self._assignment_dict(row)
        finally:
            session.close()

        trace = self._record(
            context,
            "position.revoke",
            EVENT_POSITION_REVOKED,
            {
                "assignment_id": assignment_id,
                "official_id": assignment["official_id"],
                "identity_id": assignment["identity_id"],
                "position_id": assignment["position_id"],
                "reason": reason,
                "tenant_id": tenant,
            },
        )
        return {**assignment, "changed": True, **trace}

    # ── R7-C7 · R7-C8: مِنَح السلطة ─────────────────────────────────────

    def grant_authority(
        self,
        *,
        context: AuthorizationContext,
        position_id: str,
        operation: str,
        scope: str,
        institution_id: str | None = None,
        department_id: str | None = None,
        budget_id: str | None = None,
        account_id: str | None = None,
        max_amount: str | int | None = None,
    ) -> dict[str, Any]:
        """امنح منصبًا سلطةً على عمليةٍ مُسمّاة وهدفٍ مُسمّى — R7-C8.

        الأهداف تُتحقَّق من القاعدة: الموازنة والحساب والإدارة يجب أن تنتمي إلى
        مؤسسة المِنحة. فلا مِنحة على موازنة مؤسسةٍ أخرى، ولو صحّ معرّفها.

        `operation` من `GRANTABLE_OPERATIONS` — وهي أسماء عمليات مفحوصةٌ أصلًا في
        الخزانة والخدمات الحكومية، لا صلاحياتٌ جديدة تُضاف إلى `security_roles`.
        """
        require_domain_permission(context, "authority.grant", PERMISSIONS_GRANT_WRITE)
        if operation not in GRANTABLE_OPERATIONS:
            raise ValueError(
                f"عملية غير قابلة للمنح '{operation}' — المفردة: {list(GRANTABLE_OPERATIONS)}"
            )
        if scope not in AUTHORITY_SCOPES:
            raise ValueError(f"نطاق غير معروف '{scope}' — المفردة: {list(AUTHORITY_SCOPES)}")

        tenant = self._tenant_of(context)
        session = self._session()
        try:
            position = session.get(PositionModel, position_id)
            if position is None or position.tenant_id != tenant:
                raise PositionNotFoundError(f"لا منصب بالمعرّف '{position_id}'")
            require_tenant(context, position.tenant_id)
            if position.status != "active":
                raise PositionInactiveError(
                    f"المنصب '{position_id}' حالته '{position.status}' — لا مِنحة على منصب ملغى"
                )

            target_institution = institution_id or position.institution_id
            if target_institution != position.institution_id:
                raise InvalidGrantTargetError(
                    f"مِنحة على مؤسسة '{target_institution}' لمنصبٍ في "
                    f"'{position.institution_id}' — السلطة لا تُمنَح خارج مؤسسة المنصب"
                )
            if scope == "DEPARTMENT":
                target_department = department_id or position.department_id
                if target_department is None:
                    raise InvalidGrantTargetError("نطاق الإدارة يلزمه إدارة مُسمّاة")
                self._assert_department_in(session, target_department, target_institution)
                department_id = target_department
            else:
                if department_id is not None:
                    self._assert_department_in(session, department_id, target_institution)

            if budget_id is not None:
                self._assert_budget_in(session, budget_id, target_institution)
            if account_id is not None:
                self._assert_account_exists(session, account_id)

            row = AuthorityGrantModel(
                id=f"agr-{uuid.uuid4()}",
                position_id=position_id,
                operation=operation,
                scope=scope,
                institution_id=target_institution,
                department_id=department_id,
                budget_id=budget_id,
                account_id=account_id,
                max_amount=None if max_amount is None else str(max_amount),
                status="active",
                granted_by=context.principal_id,
                tenant_id=tenant,
            )
            session.add(row)
            session.commit()
            grant = self._grant_dict(row)
        finally:
            session.close()

        trace = self._record(
            context,
            "authority.grant",
            EVENT_AUTHORITY_CHANGED,
            {
                "grant_id": grant["id"],
                "position_id": position_id,
                "operation": operation,
                "scope": scope,
                "change": "granted",
                "tenant_id": tenant,
            },
        )
        return {**grant, **trace}

    def revoke_authority(
        self,
        *,
        context: AuthorizationContext,
        grant_id: str,
        reason: str,
    ) -> dict[str, Any]:
        """اسحب مِنحة سلطة — والصفّ يبقى، فيُقرأ لاحقًا أن السلطة كانت ثم سُحبت."""
        require_domain_permission(context, "authority.revoke", PERMISSIONS_GRANT_WRITE)
        if not reason:
            raise ValueError("سحب المِنحة يلزمه سبب مكتوب")
        tenant = self._tenant_of(context)
        session = self._session()
        try:
            row = session.get(AuthorityGrantModel, grant_id)
            if row is None or row.tenant_id != tenant:
                raise GrantNotFoundError(f"لا مِنحة سلطةٍ بالمعرّف '{grant_id}'")
            require_tenant(context, row.tenant_id)
            if row.status == "revoked":
                return {**self._grant_dict(row), "changed": False}
            row.status = "revoked"
            row.revoked_at = _now()
            row.revocation_reason = reason
            session.commit()
            grant = self._grant_dict(row)
        finally:
            session.close()

        trace = self._record(
            context,
            "authority.revoke",
            EVENT_AUTHORITY_CHANGED,
            {
                "grant_id": grant_id,
                "position_id": grant["position_id"],
                "operation": grant["operation"],
                "scope": grant["scope"],
                "change": "revoked",
                "reason": reason,
                "tenant_id": tenant,
            },
        )
        return {**grant, "changed": True, **trace}

    # ── تحقّق أهداف المِنَح — استيرادٌ متأخّر لتجنّب اعتمادٍ دائريّ ──────

    @staticmethod
    def _assert_department_in(session, department_id: str, institution_id: str) -> None:
        row = session.get(DepartmentModel, department_id)
        if row is None:
            raise InvalidGrantTargetError(f"لا إدارة بالمعرّف '{department_id}'")
        if row.institution_id != institution_id:
            raise InvalidGrantTargetError(
                f"الإدارة '{department_id}' تتبع المؤسسة '{row.institution_id}' لا '{institution_id}'"
            )

    @staticmethod
    def _assert_budget_in(session, budget_id: str, institution_id: str) -> None:
        from amos_federation.services.state_treasury.models import BudgetModel

        row = session.get(BudgetModel, budget_id)
        if row is None:
            raise InvalidGrantTargetError(f"لا موازنة بالمعرّف '{budget_id}'")
        if row.institution_id != institution_id:
            raise InvalidGrantTargetError(
                f"الموازنة '{budget_id}' تتبع المؤسسة '{row.institution_id}' لا '{institution_id}'"
            )

    @staticmethod
    def _assert_account_exists(session, account_id: str) -> None:
        from amos_federation.services.state_treasury.models import AccountModel

        if session.get(AccountModel, account_id) is None:
            raise InvalidGrantTargetError(f"لا حساب بالمعرّف '{account_id}'")

    # ── قراءة ───────────────────────────────────────────────────────────

    def get_identity_of_principal(
        self, *, context: AuthorizationContext, principal_id: str | None = None
    ) -> dict[str, Any]:
        """اقرأ هوية مبدأ — افتراضًا هوية المُنادي نفسه."""
        require_domain_permission(context, "identity.read", PERMISSIONS_IDENTITY_READ)
        session = self._session()
        try:
            if principal_id is None or principal_id == context.principal_id:
                return resolve_identity(session, context).as_dict()
            link = (
                session.query(IdentityPrincipalModel)
                .filter(
                    IdentityPrincipalModel.principal_id == principal_id,
                    IdentityPrincipalModel.tenant_id == self._tenant_of(context),
                )
                .first()
            )
            if link is None:
                return {
                    "principal_id": principal_id,
                    "identity_id": None,
                    "resolved": False,
                    "reason": "لا صفَّ ربطٍ بين هذا المبدأ وأيّ هوية كانونية",
                }
            identity = self._identity_row(session, context, link.identity_id)
            return {
                **self._link_dict(link),
                "identity": self._identity_dict(identity),
                "resolved": identity.status == "active",
            }
        finally:
            session.close()

    def list_positions(
        self,
        *,
        context: AuthorizationContext,
        institution_code: str | None = None,
        include_inactive: bool = False,
    ) -> list[dict[str, Any]]:
        """اسرد مناصب مستأجر السياق."""
        require_domain_permission(context, "position.list", PERMISSIONS_IDENTITY_READ)
        session = self._session()
        try:
            query = session.query(PositionModel).filter(
                PositionModel.tenant_id == self._tenant_of(context)
            )
            if institution_code:
                institution = self._institution_row(session, context, institution_code)
                query = query.filter(PositionModel.institution_id == institution.id)
            if not include_inactive:
                query = query.filter(PositionModel.status == "active")
            return [self._position_dict(row) for row in query.order_by(PositionModel.code).all()]
        finally:
            session.close()

    def list_grants(
        self,
        *,
        context: AuthorizationContext,
        position_id: str,
        include_revoked: bool = False,
    ) -> list[dict[str, Any]]:
        """اسرد مِنَح منصب — والمسحوبة مُستثناة افتراضًا ولا تُحذَف."""
        require_domain_permission(context, "authority.list", PERMISSIONS_IDENTITY_READ)
        session = self._session()
        try:
            query = session.query(AuthorityGrantModel).filter(
                AuthorityGrantModel.position_id == position_id,
                AuthorityGrantModel.tenant_id == self._tenant_of(context),
            )
            if not include_revoked:
                query = query.filter(AuthorityGrantModel.status == "active")
            return [self._grant_dict(row) for row in query.all()]
        finally:
            session.close()

    def authority_chain(self, *, context: AuthorizationContext) -> dict[str, Any]:
        """صِف سلسلة سلطة المُنادي كما تُقرأ من القاعدة — للتدقيق لا للتخويل."""
        require_domain_permission(context, "identity.chain", PERMISSIONS_IDENTITY_READ)
        session = self._session()
        try:
            return describe_chain(session, context)
        finally:
            session.close()

    def registry_health(self, *, context: AuthorizationContext) -> dict[str, Any]:
        """إحصاء السجل الوطني — أرقامٌ من القاعدة لا تقديرات."""
        require_domain_permission(context, "identity.health", PERMISSIONS_IDENTITY_READ)
        tenant = self._tenant_of(context)
        session = self._session()
        try:
            identities = (
                session.query(IdentityModel).filter(IdentityModel.tenant_id == tenant).all()
            )
            by_status: dict[str, int] = dict.fromkeys(IDENTITY_STATUSES, 0)
            by_type: dict[str, int] = dict.fromkeys(IDENTITY_TYPES, 0)
            for row in identities:
                by_status[row.status] = by_status.get(row.status, 0) + 1
                by_type[row.identity_type] = by_type.get(row.identity_type, 0) + 1
            return {
                "tenant_id": tenant,
                "identities": len(identities),
                "identities_by_status": by_status,
                "identities_by_type": by_type,
                "linked_principals": session.query(IdentityPrincipalModel)
                .filter(IdentityPrincipalModel.tenant_id == tenant)
                .count(),
                "linked_agents": session.query(IdentityAgentModel)
                .filter(IdentityAgentModel.tenant_id == tenant)
                .count(),
                "positions_active": session.query(PositionModel)
                .filter(PositionModel.tenant_id == tenant, PositionModel.status == "active")
                .count(),
                "assignments_active": session.query(OfficialPositionModel)
                .filter(
                    OfficialPositionModel.tenant_id == tenant,
                    OfficialPositionModel.status == "active",
                )
                .count(),
                "grants_active": session.query(AuthorityGrantModel)
                .filter(
                    AuthorityGrantModel.tenant_id == tenant,
                    AuthorityGrantModel.status == "active",
                )
                .count(),
            }
        finally:
            session.close()

    def positions_of_identity(
        self, *, context: AuthorizationContext, identity_id: str
    ) -> list[dict[str, Any]]:
        """اسرد المناصب التي يشغلها صاحب هوية فعلًا."""
        require_domain_permission(context, "position.of_identity", PERMISSIONS_IDENTITY_READ)
        session = self._session()
        try:
            self._identity_row(session, context, identity_id)
            return [
                {
                    "official_id": h.official_id,
                    "position_id": h.position_id,
                    "position_code": h.position_code,
                    "institution_id": h.institution_id,
                    "institution_branch": h.institution_branch,
                    "department_id": h.department_id,
                    "authority_scope": h.authority_scope,
                }
                for h in resolve_positions(session, identity_id, tenant_id=self._tenant_of(context))
            ]
        finally:
            session.close()


_registry: NationalRegistry | None = None


def get_national_registry() -> NationalRegistry:
    """الوصول الموحَّد إلى السجل الوطني — مثيلٌ واحد لكل عملية."""
    global _registry
    if _registry is None:
        _registry = NationalRegistry()
    return _registry


def reset_national_registry() -> None:
    """إعادة التعيين — للاختبارات وحدها."""
    global _registry
    _registry = None


__all__ = [
    "EVENT_AGENT_IDENTITY_LINKED",
    "EVENT_AUTHORITY_CHANGED",
    "EVENT_IDENTITY_CREATED",
    "EVENT_IDENTITY_STATUS_CHANGED",
    "EVENT_POSITION_CREATED",
    "EVENT_POSITION_GRANTED",
    "EVENT_POSITION_REVOKED",
    "EVENT_PRINCIPAL_LINKED",
    "NATIONAL_REGISTRY_EVENTS",
    "AssignmentNotFoundError",
    "DuplicateAssignmentError",
    "GrantNotFoundError",
    "IdentityConflictError",
    "IdentityNotFoundError",
    "InvalidGrantTargetError",
    "NationalRegistry",
    "NationalRegistryError",
    "PositionInactiveError",
    "PositionNotFoundError",
    "UnknownAgentError",
    "get_national_registry",
    "reset_national_registry",
]
