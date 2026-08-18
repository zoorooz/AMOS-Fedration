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
from amos_federation.services.executive_core.sovereignty_bridge import (
    ConstitutionalAuthorizer,
    UndeclaredExecutionError,
    compensator,
    declared_effect,
    get_authorizer,
    operation_key,
)
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


#: نطاقُ مفاتيحِ الذرّيّة (1H) لتأسيسِ المؤسسة — نطاقٌ واحدٌ لا يتصادمُ مع غيرِه.
INSTITUTION_REGISTER_SCOPE = "state_registry.institution.register"

#: فعلُ التأسيسِ كما تراه البوابةُ السياديّة — وهو نفسُ فعلِ التخويلِ المحليٍّ القائم،
#: فلا يوجدُ فعلانِ لعمليّةٍ واحدةٍ يفترقان في التدقيق.
ACTION_INSTITUTION_REGISTER = "registry.institution.register"

#: نطاقُ مفاتيحِ الذرّيّة (1H) لتغييرِ حالةِ المؤسسة — نطاقٌ مستقلٌّ عن التأسيس،
#: فمفتاحُ تأسيسٍ ومفتاحُ تغييرِ حالةٍ لا يتصادمان ولو تشابهت قيمتُهما.
INSTITUTION_STATUS_SCOPE = "state_registry.institution.status"

#: فعلُ تغييرِ الحالةِ كما تراه البوابة — هو نصُّ التخويلِ المحلّيِّ القائمِ نفسُه
#: (`registry.institution.status`)، فلا فعلٌ جديدٌ يُختَرعُ ولا فعلٌ حصريٌّ يُنتحَل.
ACTION_INSTITUTION_STATUS = "registry.institution.status"

#: نطاقُ مفاتيحِ الذرّيّة (1H) لإنشاءِ الإدارة — مستقلٌّ عن نطاقَي المؤسسة.
DEPARTMENT_CREATE_SCOPE = "state_registry.department.create"

#: فعلُ إنشاءِ الإدارةِ كما تراه البوابة — هو نصُّ التخويلِ المحلّيِّ القائمِ نفسُه
#: (`registry.department.create`)، فلا فعلٌ جديدٌ يُختَرعُ ولا فعلٌ حصريٌّ يُنتحَل.
ACTION_DEPARTMENT_CREATE = "registry.department.create"

#: نطاقُ مفاتيحِ الذرّيّة (1H) لتقليدِ المسؤول — مستقلٌّ عن نطاقاتِ المؤسسةِ والإدارة.
OFFICIAL_APPOINT_SCOPE = "state_registry.official.appoint"

#: فعلُ التقليدِ كما تراه البوابة — هو نصُّ التخويلِ المحلّيِّ القائمِ نفسُه
#: (`registry.official.appoint`)، فلا فعلٌ جديدٌ يُختَرعُ ولا فعلٌ حصريٌّ يُنتحَل.
ACTION_OFFICIAL_APPOINT = "registry.official.appoint"

#: نطاقُ مفاتيحِ الذرّيّة (1H) لعزلِ المسؤول.
OFFICIAL_REVOKE_SCOPE = "state_registry.official.revoke"

#: فعلُ العزلِ كما تراه البوابة — نصُّ التخويلِ القائمِ نفسُه.
ACTION_OFFICIAL_REVOKE = "registry.official.revoke"


class StateRegistry:
    """السجل الفدرالي للمؤسسات والإدارات والمسؤولين."""

    def __init__(self, authorizer: ConstitutionalAuthorizer | None = None) -> None:
        init_db()
        # 2A: المُصرِّحُ يُمرَّرُ للاختبارِ بسجلِّ ذرّيّةٍ معزول، والافتراضُ مُصرِّحُ
        # النواةِ التنفيذيّةِ نفسُه — لا مُصرِّحٌ ثانٍ ولا بوابةٌ ثانية.
        self._authorizer = authorizer

    @property
    def authorizer(self) -> ConstitutionalAuthorizer:
        """المُصرِّحُ السياديُّ — يُبنى عندَ أوّلِ حاجةٍ أو يسقطُ صريحًا."""
        if self._authorizer is None:
            self._authorizer = get_authorizer()
        return self._authorizer

    def _write_institution_unguarded(self, **fields: Any) -> None:
        """مسارٌ **مُغلَقٌ** منذ 2A — يُرفَعُ دائمًا ولا يكتبُ شيءًا.

        بقاءُه مقصودٌ: مَن أعادَ الكتابةَ المباشرةَ في جدولِ المؤسساتِ من هذه
        الطبقةِ يرى رفضًا صريحًا يدلُّه على البديل، لا `AttributeError` غامضًا ولا — وهو
        الأسوأ — أثرًا يقعُ بجانبِ الحدّ.
        """
        raise UndeclaredExecutionError(
            "كتابةٌ مباشرةٌ في سجلِّ المؤسساتِ لا تعبرُ حدَّ التنفيذِ السياديَّ "
            f"(حقولٌ: {sorted(fields)}). المسارُ الوحيدُ هو `register_institution` "
            "بأثرٍ مُعلَنٍ ومفتاحِ عمليّةٍ ومعوّضٍ حقيقيٍّ."
        )

    def _delete_institution_row(self, institution_id: str) -> bool:
        """العكسُ الحقيقيُّ للتأسيس (1I) — حذفُ الصفّ لا ادّعاءُ حذفِه.

        معوّضٌ لا يعكسُ أثرًا فعلًا وعدٌ لا خطّةٌ، و 1I يشترطُ العكسَ لا الوعد.
        ولا يُستعملُ إلاّ معوّضًا مربوطًا في خطّةِ التعويضِ قبلَ التنفيذ.
        """
        session = self._session()
        try:
            row = (
                session.query(InstitutionModel)
                .filter(InstitutionModel.id == institution_id)
                .first()
            )
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True
        finally:
            session.close()

    def _delete_department_row(self, department_id: str) -> bool:
        """العكسُ الحقيقيُّ لإنشاءِ الإدارة (1I) — حذفُ الصفِّ لا ادّعاءُ حذفِه.

        لا يُستعملُ إلاّ معوّضًا مربوطًا في خطّةِ التعويضِ قبلَ التنفيذ، ولا يُنادى
        من مسارٍ عامّ: المسارُ العامُّ الوحيدُ لإنشاءِ إدارةٍ هو `create_department`.
        """
        session = self._session()
        try:
            row = (
                session.query(DepartmentModel)
                .filter(DepartmentModel.id == department_id)
                .first()
            )
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True
        finally:
            session.close()

    def _revoke_official_row(
        self, official_id: str, reason: str, *, is_head: bool
    ) -> bool:
        """كتابةُ العزلِ ورجعتُه في دالّةٍ واحدة — لأنَّ العزلَ إسنادُ حالةٍ نهائيّة.

        `is_head=False` يعزل، و`is_head` الأصليُّ مع `reason=None` يُرجِعُ الصفَّ إلى
        `appointed` كما كان. والصفُّ لا يُحذَفُ في الحالتين: أثرُ التقليدِ الماضي
        محفوظٌ، وهذا عقدُ R7 قبلَ الهجرةِ ولم يُغيَّر.
        """
        session = self._session()
        try:
            row = session.query(OfficialModel).filter(OfficialModel.id == official_id).first()
            if row is None:
                return False
            if reason is None:
                row.status = "appointed"
                row.revoked_at = None
                row.revocation_reason = None
            else:
                row.status = "revoked"
                row.revoked_at = _now()
                row.revocation_reason = reason
            row.is_head = is_head
            session.commit()
            return True
        finally:
            session.close()

    def _delete_official_row(self, official_id: str) -> bool:
        """العكسُ الحقيقيُّ للتقليد (1I) — حذفُ صفِّ المسؤولِ المُقلَّدِ لا ادّعاءُ حذفِه.

        ولا يُستعملُ إلاّ معوّضًا مربوطًا في خطّةِ التعويضِ قبلَ التنفيذ. وليس هذا
        عزلًا: العزلُ فعلٌ مُعلَنٌ له مسارُه (`revoke_official`) وأثرُه في التدقيق،
        أمّا هذا فعكسُ أثرٍ لم يتمَّ عقدُه — كأنَّ التقليدَ لم يقعْ أصلًا.
        """
        session = self._session()
        try:
            row = session.query(OfficialModel).filter(OfficialModel.id == official_id).first()
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True
        finally:
            session.close()

    def _set_institution_status_row(self, institution_id: str, status: str) -> bool:
        """اكتبْ حالةَ المؤسسةِ في الصفِّ مباشرةً — أثرٌ وعكسُه بالأداةِ نفسِها.

        تُستعملُ في موضعينِ فقط: داخلَ مُطبِّقِ `set_institution_status` عبرَ الحدّ،
        ومعوّضًا يُعيدُ الحالةَ السابقة. فالعكسُ **حقيقيٌّ** لا وعدٌ: صفٌّ يُكتَبُ
        بقيمةٍ محفوظةٍ قبلَ العبور، لا `pass` ولا تسجيلُ نيّة.

        وليست هذه بابًا خلفيًّا: هي معاونةٌ خاصّةٌ لا يُنادِيها إلاّ الحدُّ ومعوّضُه،
        والمسارُ العامُّ الوحيدُ هو `set_institution_status`.
        """
        session = self._session()
        try:
            row = (
                session.query(InstitutionModel)
                .filter(InstitutionModel.id == institution_id)
                .first()
            )
            if row is None:
                return False
            row.status = status
            session.commit()
            return True
        finally:
            session.close()

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
        finally:
            session.close()

        # ── 2A: الأثرُ يُعلَنُ قبلَ وقوعِه ثمّ يُطبَّقُ داخلَ الحدّ ──────────────
        #
        # المعرّفُ يُولَّدُ هنا لا في المُطبِّق: المعوّضُ يجب أن يعرفَ ما يعكسُه قبلَ
        # أن يقع، وإلاّ كان وعدًا بعكسٍ مجهولِ الهدف.
        institution_id = f"inst-{uuid.uuid4()}"
        target = f"institutions/{tenant}/{code}"
        effect = declared_effect(
            "WRITE", target, f"تأسيسُ مؤسسةٍ '{code}' نوعُها '{kind}' في فرع '{branch}'"
        )

        def _apply(_effect: Any) -> dict[str, Any]:
            """التطبيقُ الحقيقيُّ — كتابةُ الصفِّ ثمّ أثرُ التدقيقِ ثمّ الحدث.

            الترتيبُ هو ترتيبُ R7-A نفسُه ولم يُقلَب: القاعدةُ ثمّ التدقيقُ ثمّ
            الحدث. وكونُه داخلَ المُطبِّقِ يعني أنَّ الإعادةَ (1H) لا تُنتِجُ حدثًا
            ثانيًا لأثرٍ واحد.
            """
            write_session = self._session()
            try:
                row = InstitutionModel(
                    id=institution_id,
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
                write_session.add(row)
                write_session.commit()
                institution = self._institution_dict(row)
            finally:
                write_session.close()

            trace = self._record(
                context,
                ACTION_INSTITUTION_REGISTER,
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

        guarded = self.authorizer.guard_declared(
            ACTION_INSTITUTION_REGISTER,
            target,
            declared_effects=(effect,),
            applier=_apply,
            operation_key=operation_key(INSTITUTION_REGISTER_SCOPE, f"{tenant}:{code}"),
            compensators=(
                compensator(
                    effect.signature,
                    lambda: self._delete_institution_row(institution_id),
                    "حذفُ صفِّ المؤسسةِ المُؤسَّسة — عكسٌ حقيقيٌّ لا ادّعاء",
                ),
            ),
            metadata={"tenant_id": tenant, "code": code, "kind": kind, "branch": branch},
        )
        if guarded.is_replay:
            # إعادةٌ لمفتاحٍ مُثبَّتٍ: لا أثرَ ثانيًا ولا حدثَ ثانيًا. والصدقُ أن
            # يُقال «أُعيدَ» لا أن يُزعَمَ تأسيسٌ جديد.
            return {
                "code": code,
                "tenant_id": tenant,
                "institution_id": institution_id,
                "replayed": True,
                "operation_key": guarded.outcome.operation_key,
            }
        return {**guarded.value, "replayed": False}

    def set_institution_status(
        self,
        *,
        context: AuthorizationContext,
        code: str,
        status: str,
        reason: str,
        change_id: str | None = None,
    ) -> dict[str, Any]:
        """غيّر حالة مؤسسة — عبرَ حدِّ التنفيذِ السياديّ، والحلّ يُرفَض ما بقي تحتها أثر نشط.

        الفحوصُ القائمةُ لم تُنقَل ولم تُضعَّف: التخويلُ المحلّيُّ وحصرُ الحالاتِ
        المعروفةِ ومنعُ إحياءِ المحلولِ ومنعُ الحلِّ ما بقيت إدارةٌ نشطةٌ أو مسؤولٌ
        مُقلَّد — كلُّها **قبلَ** العبور، لأنَّ الحدَّ يحرسُ الأثرَ ولا ينوبُ عن
        قواعدِ النطاق. ثمّ يُعلَنُ الأثرُ ويُطبَّقُ داخلَ الحدِّ بمفتاحِ ذرّيّةٍ
        ومعوّضٍ يعيدُ الحالةَ السابقة.

        `change_id` مفتاحُ العمليّةِ من المُنادي: إيقافانِ مقصودانِ متعاقبانِ
        عمليّتانِ مختلفتان، فيُمرَّرُ لكلٍّ مفتاحُه. وإن لم يُمرَّر اشتُقَّ المفتاحُ
        من (المستأجر · الرمز · الحالةِ السابقةِ ← الحالةِ المطلوبةِ · السبب)،
        فتكرارُ النداءِ نفسِه إعادةٌ لا تغييرٌ ثانٍ — وهذا هو الافتراضُ الآمن.
        """
        require_domain_permission(context, ACTION_INSTITUTION_STATUS, PERMISSIONS_INSTITUTION_WRITE)
        if status not in INSTITUTION_STATUSES:
            raise RegistryError(
                f"حالة مؤسسة غير معروفة '{status}' — المعروف: {list(INSTITUTION_STATUSES)}"
            )
        tenant = self._tenant_of(context)
        session = self._session()
        try:
            row = self._institution_row(session, context, code)
            # المعرّفُ والحالةُ السابقةُ يُقتنَصانِ **قبلَ** العبور: المعوّضُ لا يعرفُ
            # ما يعكسُه إن قُرِئت الحالةُ بعدَ تغييرِها.
            institution_id = row.id
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
        finally:
            session.close()

        target = f"institutions/{tenant}/{code}"
        effect = declared_effect(
            "WRITE",
            f"{target}/status",
            f"تغييرُ حالةِ المؤسسةِ '{code}' من '{previous}' إلى '{status}': "
            f"{reason or 'بلا سبب'}",
        )

        def _apply(_effect: Any) -> dict[str, Any]:
            """التطبيقُ الحقيقيّ: الحالةُ في القاعدةِ ثمّ التدقيقُ ثمّ الحدث.

            الترتيبُ هو ترتيبُ R7-A نفسُه ولم يُقلَب، وكونُه داخلَ المُطبِّقِ يعني
            أنَّ الإعادةَ (1H) لا تُنتِجُ حدثًا ثانيًا لأثرٍ واحد.
            """
            if not self._set_institution_status_row(institution_id, status):
                raise InstitutionNotFoundError(
                    f"المؤسسة '{code}' غابت بينَ الفحصِ والتطبيق — لا أثرَ يُزعَم"
                )
            read_session = self._session()
            try:
                institution = self._institution_dict(
                    self._institution_row(read_session, context, code)
                )
            finally:
                read_session.close()

            trace = self._record(
                context,
                ACTION_INSTITUTION_STATUS,
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

        guarded = self.authorizer.guard_declared(
            ACTION_INSTITUTION_STATUS,
            target,
            declared_effects=(effect,),
            applier=_apply,
            operation_key=operation_key(
                INSTITUTION_STATUS_SCOPE,
                change_id or f"{tenant}:{code}:{previous}->{status}:{reason}",
            ),
            compensators=(
                compensator(
                    effect.signature,
                    lambda: self._set_institution_status_row(institution_id, previous),
                    f"إعادةُ حالةِ المؤسسةِ إلى '{previous}' — عكسٌ حقيقيٌّ لا ادّعاء",
                ),
            ),
            metadata={
                "tenant_id": tenant,
                "code": code,
                "from_status": previous,
                "to_status": status,
                "reason": reason,
            },
        )
        if guarded.is_replay:
            # إعادةٌ لمفتاحٍ مُثبَّت: لا تغييرَ ثانيًا ولا حدثَ ثانيًا. والصدقُ أن
            # يُقال «أُعيدَ» لا أن يُزعَمَ تغييرٌ جديد.
            return {
                "code": code,
                "tenant_id": tenant,
                "institution_id": institution_id,
                "from_status": previous,
                "status": status,
                "replayed": True,
                "operation_key": guarded.outcome.operation_key,
            }
        return {**guarded.value, "replayed": False}

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
        """أنشئ إدارة تحت مؤسسة نشطة — عبرَ حدِّ التنفيذِ السياديّ.

        الفحوصُ القائمةُ لم تُنقَل ولم تُضعَّف: التخويلُ المحلّيُّ، ووجودُ المؤسسةِ
        في مستأجرِ السياق، وكونُها نشطةً، ومنعُ تكرارِ الرمزِ تحتَها — كلُّها
        **قبلَ** العبور، لأنَّ الحدَّ يحرسُ الأثرَ ولا ينوبُ عن قواعدِ النطاق.

        والمعرّفُ يُولَّدُ قبلَ العبورِ لا في المُطبِّق: المعوّضُ يجبُ أن يعرفَ ما
        يعكسُه قبلَ أن يقع، وإلاّ كان وعدًا بعكسٍ مجهولِ الهدف.

        ولا مفتاحَ عمليّةٍ من المُنادي هنا خلافًا لـ`set_institution_status`: هويّةُ
        الإنشاءِ طبيعيّةٌ ومُقيَّدةٌ أصلًا بمنعِ تكرارِ الرمز (المستأجر · رمزُ
        المؤسسة · رمزُ الإدارة)، فتكرارُ النداءِ نفسِه إعادةٌ لا إنشاءٌ ثانٍ.
        """
        require_domain_permission(
            context, ACTION_DEPARTMENT_CREATE, PERMISSIONS_DEPARTMENT_WRITE
        )
        tenant = self._tenant_of(context)
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
            institution_id = institution.id
            institution_tenant = institution.tenant_id
            institution_code_value = institution.code
        finally:
            session.close()

        department_id = f"dept-{uuid.uuid4()}"
        target = f"institutions/{tenant}/{institution_code}/departments/{code}"
        effect = declared_effect(
            "WRITE",
            target,
            f"إنشاءُ إدارةٍ '{code}' تحتَ المؤسسةِ '{institution_code}': {name}",
        )

        def _apply(_effect: Any) -> dict[str, Any]:
            """التطبيقُ الحقيقيّ — الصفُّ ثمّ التدقيقُ ثمّ الحدث.

            الترتيبُ هو ترتيبُ R7 نفسُه ولم يُقلَب، وكونُه داخلَ المُطبِّقِ يعني أنَّ
            الإعادةَ (1H) لا تُنتِجُ حدثًا ثانيًا لأثرٍ واحد.
            """
            write_session = self._session()
            try:
                row = DepartmentModel(
                    id=department_id,
                    institution_id=institution_id,
                    code=code,
                    name=name,
                    mandate=mandate,
                    status="active",
                    tenant_id=institution_tenant,
                    created_by=context.principal_id,
                )
                write_session.add(row)
                write_session.commit()
                department = self._department_dict(row)
            finally:
                write_session.close()

            trace = self._record(
                context,
                ACTION_DEPARTMENT_CREATE,
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

        guarded = self.authorizer.guard_declared(
            ACTION_DEPARTMENT_CREATE,
            target,
            declared_effects=(effect,),
            applier=_apply,
            operation_key=operation_key(
                DEPARTMENT_CREATE_SCOPE, f"{tenant}:{institution_code}:{code}"
            ),
            compensators=(
                compensator(
                    effect.signature,
                    lambda: self._delete_department_row(department_id),
                    "حذفُ صفِّ الإدارةِ المُنشأة — عكسٌ حقيقيٌّ لا ادّعاء",
                ),
            ),
            metadata={
                "tenant_id": tenant,
                "institution_code": institution_code,
                "code": code,
            },
        )
        if guarded.is_replay:
            # إعادةٌ لمفتاحٍ مُثبَّت: لا صفَّ ثانيًا ولا حدثَ ثانيًا. والصدقُ أن
            # يُقالَ «أُعيدَ» لا أن يُزعَمَ إنشاءٌ جديد.
            return {
                "code": code,
                "institution_code": institution_code,
                "tenant_id": tenant,
                "department_id": department_id,
                "replayed": True,
                "operation_key": guarded.outcome.operation_key,
            }
        return {**guarded.value, "replayed": False}

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
        """قلِّد وكيلًا منصبًا — عبرَ حدِّ التنفيذِ السياديّ.

        الفحوصُ القائمةُ لم تُنقَل ولم تُضعَّف، وكلُّها **قبلَ** العبور: التخويلُ
        المحلّيّ، ووجودُ الوكيلِ في `agents` فعلًا (فالتقليدُ لا يُنشئُ هويّةً)،
        وحدُّ المستأجرِ (R6.1)، ونشاطُ المؤسسةِ والإدارة، ولزومُ إدارةٍ للرئاسة،
        ومنعُ رئيسينِ لإدارةٍ واحدة، ومنعُ تقليدٍ مكرَّرٍ في الموضعِ نفسِه.

        والمعرّفُ يُولَّدُ قبلَ العبورِ لا في المُطبِّق: المعوّضُ يجبُ أن يعرفَ ما
        يعكسُه قبلَ أن يقع.
        """
        require_domain_permission(context, ACTION_OFFICIAL_APPOINT, PERMISSIONS_OFFICIAL_WRITE)
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

            institution_id = institution.id
            institution_tenant = institution.tenant_id
        finally:
            session.close()

        official_id = f"offl-{uuid.uuid4()}"
        # الهدفُ موضعُ التقليدِ لا الوكيل: السلطةُ على مواضعِ المؤسسةِ لا على الأشخاص،
        # ولذلك يُبنى الهدفُ من المؤسسةِ (والإدارةِ إن وُجِدت) ثمّ الوكيل.
        seat = f"institutions/{tenant}/{institution_code}"
        if department_code:
            seat = f"{seat}/departments/{department_code}"
        target = f"{seat}/officials/{agent_id}"
        effect = declared_effect(
            "WRITE",
            target,
            f"تقليدُ الوكيلِ '{agent_id}' منصبَ '{title}'"
            + (f" في الإدارةِ '{department_code}'" if department_code else "")
            + (" رئيسًا لها" if is_head else ""),
        )

        def _apply(_effect: Any) -> dict[str, Any]:
            """التطبيقُ الحقيقيّ — الصفُّ ثمّ التدقيقُ ثمّ الحدث، بترتيبِ R7 نفسِه."""
            write_session = self._session()
            try:
                row = OfficialModel(
                    id=official_id,
                    agent_id=agent_id,
                    institution_id=institution_id,
                    department_id=department_id,
                    title=title,
                    status="appointed",
                    is_head=is_head,
                    appointed_by=context.principal_id,
                    tenant_id=institution_tenant,
                )
                write_session.add(row)
                write_session.commit()
                official = self._official_dict(row)
            finally:
                write_session.close()

            trace = self._record(
                context,
                ACTION_OFFICIAL_APPOINT,
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

        guarded = self.authorizer.guard_declared(
            ACTION_OFFICIAL_APPOINT,
            target,
            declared_effects=(effect,),
            applier=_apply,
            operation_key=operation_key(
                OFFICIAL_APPOINT_SCOPE,
                f"{tenant}:{institution_code}:{department_code or '-'}:{agent_id}:{title}",
            ),
            compensators=(
                compensator(
                    effect.signature,
                    lambda: self._delete_official_row(official_id),
                    "حذفُ صفِّ التقليدِ — عكسٌ حقيقيٌّ لا عزلٌ مُقنَّع",
                ),
            ),
            metadata={
                "tenant_id": tenant,
                "institution_code": institution_code,
                "department_code": department_code,
                "agent_id": agent_id,
                "is_head": is_head,
            },
        )
        if guarded.is_replay:
            return {
                "agent_id": agent_id,
                "institution_code": institution_code,
                "department_code": department_code,
                "tenant_id": tenant,
                "official_id": official_id,
                "replayed": True,
                "operation_key": guarded.outcome.operation_key,
            }
        return {**guarded.value, "replayed": False}

    def revoke_official(
        self, *, context: AuthorizationContext, official_id: str, reason: str
    ) -> dict[str, Any]:
        """اعزل مسؤولًا — عبرَ حدِّ التنفيذِ السياديّ.

        العزلُ إسنادُ حالةٍ نهائيّةٍ لا تراكمَ فيه، فمفتاحُ الذرّيّةِ على هويّةِ
        التقليدِ وحدَها. والصفُّ يبقى `revoked` ولا يُحذَف: هذا عقدُ R7 قبلَ الهجرةِ
        ولم تُغيِّرْه، فأثرُ التقليدِ الماضي لا يُمحى.
        """
        require_domain_permission(context, ACTION_OFFICIAL_REVOKE, PERMISSIONS_OFFICIAL_WRITE)
        session = self._session()
        try:
            row = session.query(OfficialModel).filter(OfficialModel.id == official_id).first()
            if row is None:
                raise OfficialNotFoundError(f"لا تقليد بالمعرّف '{official_id}'")
            require_tenant(context, row.tenant_id)
            if row.status == "revoked":
                raise RegistryError(f"التقليد '{official_id}' معزولٌ بالفعل")
            tenant_id = row.tenant_id
            was_head = bool(row.is_head)
        finally:
            session.close()

        target = f"officials/{tenant_id}/{official_id}"
        effect = declared_effect(
            "WRITE", target, f"عزلُ التقليدِ '{official_id}' — السببُ: {reason}"
        )

        def _apply(_effect: Any) -> dict[str, Any]:
            """التطبيقُ الحقيقيّ — الحالةُ ثمّ التدقيق، بترتيبِ R7 نفسِه."""
            self._revoke_official_row(official_id, reason, is_head=False)
            read_session = self._session()
            try:
                row = (
                    read_session.query(OfficialModel)
                    .filter(OfficialModel.id == official_id)
                    .first()
                )
                official = self._official_dict(row)
            finally:
                read_session.close()

            trace = self._record(
                context,
                ACTION_OFFICIAL_REVOKE,
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

        guarded = self.authorizer.guard_declared(
            ACTION_OFFICIAL_REVOKE,
            target,
            declared_effects=(effect,),
            applier=_apply,
            operation_key=operation_key(OFFICIAL_REVOKE_SCOPE, f"{tenant_id}:{official_id}"),
            compensators=(
                compensator(
                    effect.signature,
                    lambda: self._revoke_official_row(official_id, None, is_head=was_head),
                    "إرجاعُ التقليدِ إلى `appointed` برئاستِه الأصليّة",
                ),
            ),
            metadata={"tenant_id": tenant_id, "official_id": official_id, "was_head": was_head},
        )
        if guarded.is_replay:
            return {
                "id": official_id,
                "tenant_id": tenant_id,
                "replayed": True,
                "operation_key": guarded.outcome.operation_key,
            }
        return {**guarded.value, "replayed": False}


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
