"""
AMOS-Federation Federal/State Integration — Service Facade
الهدف: واجهةٌ واحدةٌ للفدرالية والولايات: سجلٌّ · حدودٌ · تفويضٌ · نطاقٌ · تنفيذٌ بالنواة
النطاق: services/federal_state
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17 (R8-B … R8-N)

## طبقتا الكتابة — تمييزٌ مقصود

| الطبقة | ما فيها | حدُّها |
| --- | --- | --- |
| **بنيويّة** | إنشاء حكومة · حالتُها · ربطُ مؤسسة · علاقةٌ · تفويضٌ · نطاقُ خدمة | صلاحيةُ `manage:all` + حدُّ المستأجر — **نفسُ ما تفرضه R7-A** على إنشاء المؤسسات، بلا مفردةٍ جديدة |
| **تشغيليّة** | إسنادُ قضيةٍ · قرارٌ · تنفيذُ مهمّةٍ · صرفٌ من الخزانة | `require_government_authority` → المحرّكُ الكانونيّ + حدُّ الحكومة |

والفرقُ ليس تخفيفًا: الكتابةُ البنيوية تُنشئ الخريطةَ التي تُقاس عليها السلطة،
ومن يملك `manage:all` يملكها في R7-A أصلًا. أمّا الحكمُ على مورد — قضيةً أو مالًا —
فلا يمرّ إلا بمنصبٍ نشطٍ ومِنحةٍ مطابقةٍ ونطاقٍ يبلغ الهدفَ بعينه.

## لا منفِّذَ ثانٍ (R8-G)

هذه الواجهةُ **لا تُنفّذ شيئًا بنفسها**: التنفيذُ `self._core.submit` ثمّ
`self._core.run` على `ExecutiveCore` القائمة، والمالُ `treasury.disburse` على
كائنِ خزانةٍ **يُمرَّر وسيطًا ولا يُستورَد**. وما يُكتب في
`state_government_operations` أثرٌ يشير إلى `tasks.id` الحقيقيّ — لا جدولُ مهامٍّ
موازٍ ولا محرّكُ حالاتٍ ثانٍ.

## ترتيبُ الجلسة مقصود

الجلسةُ تُغلَق قبل مناداة النواة وتُفتَح بعدها — نفسُ ترتيب R7-D حرفًا. فالنواةُ
تفتح جلستَها الخاصة، وإبقاءُ جلستنا مفتوحةً حولها يُقفل الصفوفَ طولَ التنفيذ
ويورث تعارضًا في PostgreSQL تحت التزامن.

## الوكلاء (R8-N)

`describe_agent_scope` **قراءةٌ محضة** فوق `state_officials.agent_id` و
`agent_population` القائمين: لا سجلَّ وكلاءَ ثانيًا. وتُعيد صراحةً
`federal_authority=False` و`state_authority=False` لأن الانتماءَ المؤسسيّ لا يمنح
سلطةً فدراليةً ولا ولائية — تُقرأ سلطةُ الوكيل من مناصبه ومِنَحه فقط.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from amos_federation.common.database import get_session_factory, init_db
from amos_federation.common.money import to_money
from amos_federation.common.principal import DEFAULT_TENANT
from amos_federation.services.executive_core import get_executive_core
from amos_federation.services.federal_state.authority import (
    GovernmentAuthority,
    GovernmentAuthorityError,
    require_government_authority,
    resolve_government_authority,
)
from amos_federation.services.federal_state.authorization import (
    PERMISSIONS_DELEGATION_WRITE,
    PERMISSIONS_FEDERATION_READ,
    PERMISSIONS_GOVERNMENT_WRITE,
    PERMISSIONS_RELATION_WRITE,
    PERMISSIONS_SCOPE_WRITE,
    require_domain_permission,
    require_tenant,
)
from amos_federation.services.federal_state.delegation import (
    DelegationError,
    new_delegation_id,
    validate_delegation_request,
)
from amos_federation.services.federal_state.models import (
    GOVERNMENT_LEVELS,
    GOVERNMENT_STATUSES,
    RELATION_ENTITY_KINDS,
    RELATION_SEMANTICS,
    SCOPE_LEVELS,
    UNIT_RELATIONS,
    CaseScopeModel,
    GovernmentDelegationModel,
    GovernmentModel,
    GovernmentOperationModel,
    GovernmentRelationModel,
    InstitutionGovernmentModel,
    ServiceScopeModel,
)
from amos_federation.services.federal_state.scopes import (
    government_chain,
    government_of_institution,
)
from amos_federation.services.government_services.models import CaseModel, ServiceModel
from amos_federation.services.national_registry.resolver import resolve_identity
from amos_federation.services.state_registry.models import (
    DepartmentModel,
    InstitutionModel,
    OfficialModel,
)
from amos_federation.services.state_registry.trace import record_domain_trace

if TYPE_CHECKING:
    from amos_federation.common.principal import AuthorizationContext

TASK_TYPE_GOVERNMENT_OPERATION = "government_operation"


class FederationError(ValueError):
    """طلبٌ حكوميٌّ غيرُ صالحٍ بنيويًّا — لا رفضَ تخويل."""


class GovernmentNotFoundError(FederationError):
    """لا حكومةَ بهذا الرمز في هذا المستأجر."""


class DuplicateGovernmentError(FederationError):
    """رمزُ حكومةٍ مستعملٌ في هذا المستأجر — يُرفض قبل القاعدة وفيها."""


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


class FederalStateGovernment:
    """واجهةُ الفدرالية والولايات — سجلٌّ وحدودٌ وتفويضٌ ونطاقٌ وأثرُ تنفيذ."""

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

    def _identity_id(self, session, context: AuthorizationContext) -> str | None:
        """هويةُ المبدأ إن كانت محلولة، وإلّا `None` — ولا قيمةَ مُصطنعة.

        الهويةُ غيرُ المحلولة حقيقةٌ تُكتب `None`، فلا يُخترع معرِّفٌ ليمرّ مخطَّط
        (R8-K). ومَن يقرأ الصفَّ يرى إسنادًا ناقصًا لا إسنادًا كاذبًا.
        """
        resolution = resolve_identity(session, context)
        return resolution.identity_id if resolution.resolved else None

    def _government_row(self, session, context: AuthorizationContext, code: str) -> GovernmentModel:
        tenant = self._tenant_of(context)
        row = session.scalar(
            select(GovernmentModel).where(
                GovernmentModel.code == code, GovernmentModel.tenant_id == tenant
            )
        )
        if row is None:
            raise GovernmentNotFoundError(f"لا حكومة برمز '{code}' في مستأجر '{tenant}'")
        require_tenant(context, row.tenant_id)
        return row

    def _institution_row(
        self, session, context: AuthorizationContext, code: str
    ) -> InstitutionModel:
        tenant = self._tenant_of(context)
        row = session.scalar(
            select(InstitutionModel).where(
                InstitutionModel.code == code, InstitutionModel.tenant_id == tenant
            )
        )
        if row is None:
            raise FederationError(f"لا مؤسسة برمز '{code}' في مستأجر '{tenant}'")
        require_tenant(context, row.tenant_id)
        return row

    @staticmethod
    def _government_dict(row: GovernmentModel) -> dict[str, Any]:
        return {
            "id": row.id,
            "code": row.code,
            "name": row.name,
            "level": row.level,
            "parent_government_id": row.parent_government_id,
            "status": row.status,
            "status_reason": row.status_reason or "",
            "tenant_id": row.tenant_id,
            "created_by": row.created_by,
            "created_at": _iso(row.created_at),
            "updated_at": _iso(row.updated_at),
        }

    # ── R8-B/R8-C: سجلُّ الحكومات ────────────────────────────────────────

    def register_government(
        self,
        context: AuthorizationContext,
        *,
        code: str,
        name: str,
        level: str,
        parent_code: str | None = None,
    ) -> dict[str, Any]:
        """سجِّل حكومةً فدراليةً أو ولايةً بمعرِّفٍ مستقرٍّ ورمزٍ فريد.

        `code` فريدٌ داخل المستأجر ويُفحَص هنا وفي القاعدة (`uq_state_governments_
        tenant_code`) — فالتزامنُ لا يخلق ولايتين برمزٍ واحد. والاسمُ ليس هوية:
        اسمان متشابهان مسموحان، ورمزان متطابقان مرفوضان.
        """
        require_domain_permission(
            context, "federation.government.register", PERMISSIONS_GOVERNMENT_WRITE
        )
        if level not in GOVERNMENT_LEVELS:
            raise FederationError(f"مستوى حكومةٍ مجهول: {level}")
        tenant = self._tenant_of(context)
        session = self._session()
        try:
            existing = session.scalar(
                select(GovernmentModel).where(
                    GovernmentModel.code == code, GovernmentModel.tenant_id == tenant
                )
            )
            if existing is not None:
                raise DuplicateGovernmentError(f"رمزُ الحكومة '{code}' مستعملٌ في مستأجر '{tenant}'")
            parent_id: str | None = None
            if level == "STATE":
                if not parent_code:
                    raise FederationError("الولايةُ تلزمها علاقةٌ فدرالية: `parent_code` مطلوب")
                parent = self._government_row(session, context, parent_code)
                if parent.level != "FEDERAL":
                    raise FederationError("أصلُ الولاية يجب أن يكون حكومةً فدرالية")
                parent_id = parent.id
            elif parent_code:
                raise FederationError("الحكومةُ الفدرالية لا أصلَ لها")

            row = GovernmentModel(
                id=f"gov-{uuid.uuid4().hex[:12]}",
                code=code,
                name=name,
                level=level,
                parent_government_id=parent_id,
                status="active",
                status_reason="",
                tenant_id=tenant,
                created_by=context.principal_id,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            payload = self._government_dict(row)
        finally:
            session.close()

        trace = record_domain_trace(
            context,
            "federation.government.register",
            "amos_federation.federation.government_registered",
            {
                "government_id": payload["id"],
                "code": payload["code"],
                "name": payload["name"],
                "level": payload["level"],
                "parent_government_id": payload["parent_government_id"],
                "status": payload["status"],
                "tenant_id": payload["tenant_id"],
            },
        )
        return {**payload, **trace}

    def set_government_status(
        self, context: AuthorizationContext, code: str, status: str, reason: str
    ) -> dict[str, Any]:
        """غيِّر حالةَ حكومةٍ بسببٍ مُصرَّح — ولا تُحذف ولا يُهدم تاريخُها.

        `dissolved` حالةٌ لا حذف: الصفُّ يبقى، وكلُّ قضيةٍ وقرارٍ وأثرٍ يشير إليه
        يبقى قابلًا للقراءة. والمفاتيحُ الأجنبية `ON DELETE RESTRICT` تجعل ذلك
        قيدًا لا نيّة.
        """
        require_domain_permission(
            context, "federation.government.status", PERMISSIONS_GOVERNMENT_WRITE
        )
        if status not in GOVERNMENT_STATUSES:
            raise FederationError(f"حالةُ حكومةٍ مجهولة: {status}")
        if not reason.strip():
            raise FederationError("تغييرُ الحالة يلزمه سببٌ مُصرَّح")
        session = self._session()
        try:
            row = self._government_row(session, context, code)
            previous = row.status
            row.status = status
            row.status_reason = reason
            row.updated_at = _now()
            session.commit()
            session.refresh(row)
            payload = self._government_dict(row)
        finally:
            session.close()

        trace = record_domain_trace(
            context,
            "federation.government.status",
            "amos_federation.federation.government_status_changed",
            {
                "government_id": payload["id"],
                "code": payload["code"],
                "level": payload["level"],
                "status": payload["status"],
                "previous_status": previous,
                "reason": reason,
                "tenant_id": payload["tenant_id"],
            },
        )
        return {**payload, "previous_status": previous, **trace}

    def bind_institution(
        self,
        context: AuthorizationContext,
        *,
        institution_code: str,
        government_code: str,
        relation: str = "belongs_to",
    ) -> dict[str, Any]:
        """اربط مؤسسةً قائمةً بحكومتها — بلا عمودٍ جديدٍ على `state_institutions`.

        مؤسسةٌ واحدةٌ لحكومةٍ واحدة: الفريدُ على (مستأجر، مؤسسة) يمنع الانتماءَ
        المزدوج. وإعادةُ الربط تحديثٌ صريحٌ لصفٍّ قائمٍ لا صفٌّ ثانٍ.
        """
        require_domain_permission(
            context, "federation.institution.bind", PERMISSIONS_GOVERNMENT_WRITE
        )
        if relation not in UNIT_RELATIONS:
            raise FederationError(f"علاقةُ وحدةٍ مجهولة: {relation}")
        tenant = self._tenant_of(context)
        session = self._session()
        try:
            institution = self._institution_row(session, context, institution_code)
            government = self._government_row(session, context, government_code)
            if government.status != "active":
                raise FederationError(
                    f"لا ربطَ بحكومةٍ حالتُها '{government.status}' — يلزمها 'active'"
                )
            identity_id = self._identity_id(session, context)
            row = session.scalar(
                select(InstitutionGovernmentModel).where(
                    InstitutionGovernmentModel.institution_id == institution.id,
                    InstitutionGovernmentModel.tenant_id == tenant,
                )
            )
            if row is None:
                row = InstitutionGovernmentModel(
                    id=f"gvu-{uuid.uuid4().hex[:12]}",
                    government_id=government.id,
                    institution_id=institution.id,
                    relation=relation,
                    assigned_by=context.principal_id,
                    assigned_by_identity_id=identity_id,
                    tenant_id=tenant,
                )
                session.add(row)
            else:
                row.government_id = government.id
                row.relation = relation
                row.assigned_by = context.principal_id
                row.assigned_by_identity_id = identity_id
                row.updated_at = _now()
            session.commit()
            session.refresh(row)
            payload = {
                "id": row.id,
                "government_id": row.government_id,
                "government_code": government.code,
                "government_level": government.level,
                "institution_id": row.institution_id,
                "institution_code": institution.code,
                "relation": row.relation,
                "identity_id": row.assigned_by_identity_id,
                "tenant_id": row.tenant_id,
            }
        finally:
            session.close()

        trace = record_domain_trace(
            context,
            "federation.institution.bind",
            "amos_federation.federation.institution_bound",
            {
                "binding_id": payload["id"],
                "government_id": payload["government_id"],
                "government_code": payload["government_code"],
                "government_level": payload["government_level"],
                "institution_id": payload["institution_id"],
                "relation": payload["relation"],
                "identity_id": payload["identity_id"],
                "tenant_id": payload["tenant_id"],
            },
        )
        return {**payload, **trace}

    # ── R8-H: العلاقات والتفويض ──────────────────────────────────────────

    def record_relation(
        self,
        context: AuthorizationContext,
        *,
        from_kind: str,
        from_ref: str,
        to_kind: str,
        to_ref: str,
        relation: str,
        note: str = "",
    ) -> dict[str, Any]:
        """سجِّل علاقةً إداريةً صريحة — **وصفٌ لا صلاحية**.

        لا سطرَ في `authority.py` يقرأ هذا الجدول؛ ويحرس ذلك اختبارٌ ساكن. فمن
        أراد أن يمنح فليُفوِّض تفويضًا صريحًا.
        """
        require_domain_permission(context, "federation.relation.record", PERMISSIONS_RELATION_WRITE)
        for kind in (from_kind, to_kind):
            if kind not in RELATION_ENTITY_KINDS:
                raise FederationError(f"نوعُ طرفٍ مجهول: {kind}")
        if relation not in RELATION_SEMANTICS:
            raise FederationError(f"دلالةُ علاقةٍ مجهولة: {relation}")
        if from_kind == to_kind and from_ref == to_ref:
            raise FederationError("لا علاقةَ كيانٍ بنفسه")
        tenant = self._tenant_of(context)
        session = self._session()
        try:
            identity_id = self._identity_id(session, context)
            row = GovernmentRelationModel(
                id=f"grl-{uuid.uuid4().hex[:12]}",
                from_kind=from_kind,
                from_ref=from_ref,
                to_kind=to_kind,
                to_ref=to_ref,
                relation=relation,
                status="active",
                note=note,
                created_by=context.principal_id,
                created_by_identity_id=identity_id,
                tenant_id=tenant,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            payload = {
                "id": row.id,
                "from_kind": row.from_kind,
                "from_ref": row.from_ref,
                "to_kind": row.to_kind,
                "to_ref": row.to_ref,
                "relation": row.relation,
                "status": row.status,
                "note": row.note or "",
                "identity_id": row.created_by_identity_id,
                "tenant_id": row.tenant_id,
                "grants_authority": False,
            }
        finally:
            session.close()

        trace = record_domain_trace(
            context,
            "federation.relation.record",
            "amos_federation.federation.relation_recorded",
            {
                "relation_id": payload["id"],
                "from_kind": payload["from_kind"],
                "from_ref": payload["from_ref"],
                "to_kind": payload["to_kind"],
                "to_ref": payload["to_ref"],
                "relation": payload["relation"],
                "status": payload["status"],
                "note": payload["note"],
                "identity_id": payload["identity_id"],
                "tenant_id": payload["tenant_id"],
            },
        )
        return {**payload, **trace}

    def grant_delegation(
        self,
        context: AuthorizationContext,
        *,
        from_government_code: str,
        operation: str,
        scope: str,
        to_government_code: str | None = None,
        to_institution_code: str | None = None,
        max_amount: Decimal | str | None = None,
        expires_at: datetime | None = None,
        reason: str = "",
    ) -> dict[str, Any]:
        """فوِّض عمليةً بعينها إلى حكومةٍ أو مؤسسةٍ — صريحًا مُنطَّقًا قابلًا للنقض."""
        require_domain_permission(
            context, "federation.delegation.grant", PERMISSIONS_DELEGATION_WRITE
        )
        if scope not in SCOPE_LEVELS:
            raise FederationError(f"نطاقٌ مجهول: {scope}")
        tenant = self._tenant_of(context)
        session = self._session()
        try:
            source = self._government_row(session, context, from_government_code)
            target_government = (
                self._government_row(session, context, to_government_code)
                if to_government_code
                else None
            )
            target_institution = (
                self._institution_row(session, context, to_institution_code)
                if to_institution_code
                else None
            )
            # عيبُ الطلب البنيويّ يُقدَّم للمنادي بوجهٍ واحد: `FederationError`.
            # فالتفويضُ تفصيلٌ داخليٌّ، ولا يُطلب من المنادي أن يعرف أنواعَه.
            try:
                validate_delegation_request(
                    operation=operation,
                    scope=scope,
                    to_government_id=target_government.id if target_government else None,
                    to_institution_id=target_institution.id if target_institution else None,
                    from_government_id=source.id,
                )
            except DelegationError as exc:
                raise FederationError(str(exc)) from exc
            identity_id = self._identity_id(session, context)
            row = GovernmentDelegationModel(
                id=new_delegation_id(),
                from_government_id=source.id,
                to_government_id=target_government.id if target_government else None,
                to_institution_id=target_institution.id if target_institution else None,
                operation=operation,
                scope=scope,
                # `to_money` لا `str`: النصُّ يُخفي العائمَ، والبابُ يردُّه (Q-20).
                max_amount=to_money(max_amount) if max_amount is not None else None,
                status="active",
                reason=reason,
                granted_by=context.principal_id,
                granted_by_identity_id=identity_id,
                tenant_id=tenant,
                expires_at=expires_at,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            payload = {
                "id": row.id,
                "from_government_id": row.from_government_id,
                "to_government_id": row.to_government_id,
                "to_institution_id": row.to_institution_id,
                "operation": row.operation,
                "scope": row.scope,
                "max_amount": row.max_amount,
                "status": row.status,
                "expires_at": _iso(row.expires_at),
                "reason": row.reason or "",
                "identity_id": row.granted_by_identity_id,
                "tenant_id": row.tenant_id,
            }
        finally:
            session.close()

        trace = record_domain_trace(
            context,
            "federation.delegation.grant",
            "amos_federation.federation.delegation_granted",
            {
                "delegation_id": payload["id"],
                "from_government_id": payload["from_government_id"],
                "to_government_id": payload["to_government_id"],
                "to_institution_id": payload["to_institution_id"],
                "operation": payload["operation"],
                "scope": payload["scope"],
                "max_amount": payload["max_amount"],
                "expires_at": payload["expires_at"],
                "reason": payload["reason"],
                "identity_id": payload["identity_id"],
                "tenant_id": payload["tenant_id"],
            },
        )
        return {**payload, **trace}

    def revoke_delegation(
        self, context: AuthorizationContext, delegation_id: str, reason: str
    ) -> dict[str, Any]:
        """انقُض تفويضًا — حالةٌ وطابعٌ وسبب، لا حذفَ صفّ."""
        require_domain_permission(
            context, "federation.delegation.revoke", PERMISSIONS_DELEGATION_WRITE
        )
        if not reason.strip():
            raise FederationError("النقضُ يلزمه سببٌ مُصرَّح")
        session = self._session()
        try:
            row = session.get(GovernmentDelegationModel, delegation_id)
            if row is None:
                raise FederationError(f"لا تفويضَ بمعرّف '{delegation_id}'")
            require_tenant(context, row.tenant_id)
            if row.status == "revoked":
                raise FederationError("التفويضُ منقوضٌ سابقًا")
            previous = row.status
            row.status = "revoked"
            row.revoked_at = _now()
            row.revoked_reason = reason
            row.updated_at = _now()
            session.commit()
            session.refresh(row)
            payload = {
                "id": row.id,
                "from_government_id": row.from_government_id,
                "to_government_id": row.to_government_id,
                "to_institution_id": row.to_institution_id,
                "operation": row.operation,
                "status": row.status,
                "previous_status": previous,
                "revoked_at": _iso(row.revoked_at),
                "reason": reason,
                "tenant_id": row.tenant_id,
            }
        finally:
            session.close()

        trace = record_domain_trace(
            context,
            "federation.delegation.revoke",
            "amos_federation.federation.delegation_revoked",
            {
                "delegation_id": payload["id"],
                "from_government_id": payload["from_government_id"],
                "to_government_id": payload["to_government_id"],
                "to_institution_id": payload["to_institution_id"],
                "operation": payload["operation"],
                "previous_status": previous,
                "reason": reason,
                "tenant_id": payload["tenant_id"],
            },
        )
        return {**payload, **trace}

    # ── R8-E: نطاقُ الخدمات ──────────────────────────────────────────────

    def scope_service(
        self,
        context: AuthorizationContext,
        *,
        institution_code: str,
        service_code: str,
        level: str,
        department_id: str | None = None,
    ) -> dict[str, Any]:
        """أعلِن نطاقَ خدمةٍ حكوميةٍ قائمةٍ وملكيّتَها — بلا خدمةٍ ثانيةٍ ولا منفِّذٍ خاصّ.

        الخدمةُ تبقى صفَّها في `state_services` كما أنشأتها
        `GovernmentServices.publish_service`، وتنفيذُها يبقى عبر `ExecutiveCore`.
        هذا الصفُّ يقول **لمن هي وعلى أيّ مستوى** فقط، ويُفرض اتّساقُه: المستوى
        الفدراليّ/الولائيّ يلزمه ربطٌ حكوميّ فعليّ، والإدارةُ يجب أن تكون في
        مؤسسة الخدمة نفسها.
        """
        require_domain_permission(context, "federation.service.scope", PERMISSIONS_SCOPE_WRITE)
        if level not in SCOPE_LEVELS:
            raise FederationError(f"مستوى نطاقٍ مجهول: {level}")
        tenant = self._tenant_of(context)
        session = self._session()
        try:
            institution = self._institution_row(session, context, institution_code)
            service = session.scalar(
                select(ServiceModel).where(
                    ServiceModel.institution_id == institution.id,
                    ServiceModel.code == service_code,
                )
            )
            if service is None:
                raise FederationError(
                    f"لا خدمة برمز '{service_code}' في المؤسسة '{institution_code}'"
                )
            require_tenant(context, service.tenant_id)

            government_id = government_of_institution(session, institution.id, tenant_id=tenant)
            if level in ("FEDERAL", "STATE") and not government_id:
                raise FederationError("نطاقٌ فدراليٌّ أو ولائيٌّ يلزمه ربطُ المؤسسة بحكومة — غيرُ محلول")
            if level == "DEPARTMENT":
                if not department_id:
                    raise FederationError("مستوى الإدارة يلزمه `department_id`")
                department = session.get(DepartmentModel, department_id)
                if department is None or department.institution_id != institution.id:
                    raise FederationError("الإدارةُ ليست في مؤسسة الخدمة")
                require_tenant(context, department.tenant_id)
            else:
                department_id = None
            if level == "STATE":
                government = session.get(GovernmentModel, government_id)
                if government is not None and government.level != "STATE":
                    raise FederationError("نطاقٌ ولائيٌّ لمؤسسةٍ مربوطةٍ بحكومةٍ فدرالية")
            if level == "FEDERAL":
                government = session.get(GovernmentModel, government_id)
                if government is not None and government.level != "FEDERAL":
                    raise FederationError("نطاقٌ فدراليٌّ لمؤسسةٍ مربوطةٍ بولاية")

            identity_id = self._identity_id(session, context)
            row = session.scalar(
                select(ServiceScopeModel).where(
                    ServiceScopeModel.service_id == service.id,
                    ServiceScopeModel.tenant_id == tenant,
                )
            )
            if row is None:
                row = ServiceScopeModel(
                    id=f"svs-{uuid.uuid4().hex[:12]}",
                    service_id=service.id,
                    level=level,
                    government_id=government_id if level in ("FEDERAL", "STATE") else None,
                    institution_id=institution.id,
                    department_id=department_id,
                    created_by=context.principal_id,
                    created_by_identity_id=identity_id,
                    tenant_id=tenant,
                )
                session.add(row)
            else:
                row.level = level
                row.government_id = government_id if level in ("FEDERAL", "STATE") else None
                row.department_id = department_id
                row.updated_at = _now()
            session.commit()
            session.refresh(row)
            payload = {
                "id": row.id,
                "service_id": row.service_id,
                "service_code": service.code,
                "level": row.level,
                "government_id": row.government_id,
                "institution_id": row.institution_id,
                "department_id": row.department_id,
                "identity_id": row.created_by_identity_id,
                "tenant_id": row.tenant_id,
            }
        finally:
            session.close()

        trace = record_domain_trace(
            context,
            "federation.service.scope",
            "amos_federation.federation.service_scoped",
            {
                "scope_id": payload["id"],
                "service_id": payload["service_id"],
                "level": payload["level"],
                "government_id": payload["government_id"],
                "institution_id": payload["institution_id"],
                "department_id": payload["department_id"],
                "identity_id": payload["identity_id"],
                "tenant_id": payload["tenant_id"],
            },
        )
        return {**payload, **trace}

    # ── R8-F: إسنادُ القضايا ─────────────────────────────────────────────

    def scope_case(
        self,
        context: AuthorizationContext,
        *,
        case_reference: str,
        level: str,
        department_id: str | None = None,
        responsible_official_id: str | None = None,
    ) -> dict[str, Any]:
        """أسنِد قضيةً حكوميةً قائمةً إلى نطاقها وسلسلةِ سلطتها — بإسنادٍ لا يُلفَّق.

        السلطةُ تُحلّ بالمحرّك الكانونيّ (`gov.case.decide`) ثمّ بحدِّ الحكومة،
        و`classification` هو **ما ثبت** لا ما نرجوه: `PROVEN` يلزمه منصبٌ وهويةٌ
        وحكومةٌ مربوطة، وإلّا فـ`PARTIAL` أو `UNRESOLVED`. والرفضُ يمنع الكتابة
        أصلًا، فلا صفَّ إسنادٍ لمن لا سلطةَ له.
        """
        require_domain_permission(context, "federation.case.scope", PERMISSIONS_SCOPE_WRITE)
        if level not in SCOPE_LEVELS:
            raise FederationError(f"مستوى نطاقٍ مجهول: {level}")
        tenant = self._tenant_of(context)
        session = self._session()
        try:
            case = session.scalar(
                select(CaseModel).where(
                    CaseModel.reference == case_reference, CaseModel.tenant_id == tenant
                )
            )
            if case is None:
                raise FederationError(f"لا قضية بمرجع '{case_reference}' في مستأجر '{tenant}'")
            require_tenant(context, case.tenant_id)
            if responsible_official_id is not None:
                official = session.get(OfficialModel, responsible_official_id)
                if official is None:
                    raise FederationError(f"لا منصبَ بمعرّف '{responsible_official_id}'")
                require_tenant(context, official.tenant_id)

            authority = require_government_authority(
                session,
                context,
                "gov.case.decide",
                target_level=level,
                institution_id=case.institution_id,
                department_id=department_id,
                tenant_id=tenant,
            )
            classification = authority.classification
            if classification == "PROVEN" and not (
                authority.decision.position_id
                and authority.decision.identity_id
                and authority.target.government_id
            ):
                # قيدُ القاعدة يرفض `PROVEN` بلا سلسلة، ونُضيّق قبله كي تكون
                # الرسالةُ حقيقةً لا خطأَ قيد.
                classification = "PARTIAL"

            row = CaseScopeModel(
                id=f"css-{uuid.uuid4().hex[:12]}",
                case_id=case.id,
                level=level,
                government_id=authority.target.government_id,
                institution_id=case.institution_id,
                department_id=department_id if level == "DEPARTMENT" else None,
                responsible_official_id=responsible_official_id or authority.decision.official_id,
                opened_by=context.principal_id,
                opened_by_identity_id=authority.decision.identity_id,
                position_id=authority.decision.position_id,
                classification=classification,
                authority=authority.as_dict(),
                tenant_id=tenant,
            )
            existing = session.scalar(
                select(CaseScopeModel).where(
                    CaseScopeModel.case_id == case.id, CaseScopeModel.tenant_id == tenant
                )
            )
            if existing is not None:
                raise FederationError(f"القضية '{case_reference}' مُسنَدةٌ سابقًا")
            session.add(row)
            session.commit()
            session.refresh(row)
            payload = {
                "id": row.id,
                "case_id": row.case_id,
                "case_reference": case.reference,
                "level": row.level,
                "government_id": row.government_id,
                "institution_id": row.institution_id,
                "department_id": row.department_id,
                "responsible_official_id": row.responsible_official_id,
                "identity_id": row.opened_by_identity_id,
                "position_id": row.position_id,
                "classification": row.classification,
                "boundary_reason": authority.boundary_reason,
                "tenant_id": row.tenant_id,
            }
        finally:
            session.close()

        trace = record_domain_trace(
            context,
            "federation.case.scope",
            "amos_federation.federation.case_scoped",
            {
                "scope_id": payload["id"],
                "case_id": payload["case_id"],
                "level": payload["level"],
                "government_id": payload["government_id"],
                "institution_id": payload["institution_id"],
                "department_id": payload["department_id"],
                "responsible_official_id": payload["responsible_official_id"],
                "identity_id": payload["identity_id"],
                "position_id": payload["position_id"],
                "classification": payload["classification"],
                "boundary_reason": payload["boundary_reason"],
                "tenant_id": payload["tenant_id"],
            },
        )
        return {**payload, **trace}

    # ── R8-G: التنفيذ عبر النواة والخزانة ────────────────────────────────

    def _record_operation(
        self,
        context: AuthorizationContext,
        *,
        kind: str,
        level: str,
        authority: GovernmentAuthority,
        institution_id: str,
        department_id: str | None,
        decision_id: str | None,
        case_id: str | None,
        ruling_id: str | None,
        task_id: str | None,
        transaction_reference: str | None,
        status: str,
        detail: str,
    ) -> dict[str, Any]:
        """اكتب أثرَ عمليةٍ حكومية ثمّ أعلنه — الصفُّ يجيب أسئلةَ R8-F السبعة."""
        tenant = self._tenant_of(context)
        session = self._session()
        try:
            row = GovernmentOperationModel(
                id=f"gop-{uuid.uuid4().hex[:12]}",
                kind=kind,
                level=level,
                government_id=authority.target.government_id,
                institution_id=institution_id,
                department_id=department_id,
                decision_id=decision_id,
                case_id=case_id,
                ruling_id=ruling_id,
                identity_id=authority.decision.identity_id,
                position_id=authority.decision.position_id,
                classification=authority.classification,
                authority=authority.as_dict(),
                task_id=task_id,
                transaction_reference=transaction_reference,
                status=status,
                detail=detail,
                requested_by=context.principal_id,
                tenant_id=tenant,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            payload = {
                "id": row.id,
                "kind": row.kind,
                "level": row.level,
                "government_id": row.government_id,
                "institution_id": row.institution_id,
                "department_id": row.department_id,
                "decision_id": row.decision_id,
                "case_id": row.case_id,
                "ruling_id": row.ruling_id,
                "identity_id": row.identity_id,
                "position_id": row.position_id,
                "classification": row.classification,
                "task_id": row.task_id,
                "transaction_reference": row.transaction_reference,
                "status": row.status,
                "detail": row.detail or "",
                "tenant_id": row.tenant_id,
            }
        finally:
            session.close()

        trace = record_domain_trace(
            context,
            "federation.operation.record",
            "amos_federation.federation.operation_recorded",
            {
                "operation_id": payload["id"],
                "kind": payload["kind"],
                "level": payload["level"],
                "government_id": payload["government_id"],
                "institution_id": payload["institution_id"],
                "department_id": payload["department_id"],
                "decision_id": payload["decision_id"],
                "case_id": payload["case_id"],
                "ruling_id": payload["ruling_id"],
                "identity_id": payload["identity_id"],
                "position_id": payload["position_id"],
                "classification": payload["classification"],
                "task_id": payload["task_id"],
                "transaction_reference": payload["transaction_reference"],
                "status": payload["status"],
                "detail": payload["detail"],
                "tenant_id": payload["tenant_id"],
            },
        )
        return {**payload, **trace}

    def execute_scoped_operation(
        self,
        context: AuthorizationContext,
        *,
        institution_code: str,
        level: str,
        summary: str,
        department_id: str | None = None,
        case_reference: str | None = None,
        decision_id: str | None = None,
        ruling_id: str | None = None,
        max_steps: int = 6,
    ) -> dict[str, Any]:
        """نفِّذ عمليةً حكوميةً بسلطةٍ مُحلَّلة — **عبر `ExecutiveCore` وحدها**.

        الترتيب: سلطةٌ (محرّكٌ كانونيّ + حدُّ حكومة) → إغلاقُ الجلسة → مهمّةٌ في
        النواة → أثرٌ يشير إلى `tasks.id` الحقيقيّ. فلا مهمّةَ تُنشأ قبل ثبوت
        السلطة، ولا أثرَ «نُفِّذ» بلا معرِّفِ مهمّةٍ يُفحَص.
        """
        require_domain_permission(context, "federation.operation.execute", PERMISSIONS_SCOPE_WRITE)
        if level not in SCOPE_LEVELS:
            raise FederationError(f"مستوى نطاقٍ مجهول: {level}")
        tenant = self._tenant_of(context)
        session = self._session()
        try:
            institution = self._institution_row(session, context, institution_code)
            case_id: str | None = None
            if case_reference:
                case = session.scalar(
                    select(CaseModel).where(
                        CaseModel.reference == case_reference, CaseModel.tenant_id == tenant
                    )
                )
                if case is None:
                    raise FederationError(f"لا قضية بمرجع '{case_reference}'")
                require_tenant(context, case.tenant_id)
                case_id = case.id
            authority = require_government_authority(
                session,
                context,
                "gov.case.decide",
                target_level=level,
                institution_id=institution.id,
                department_id=department_id,
                tenant_id=tenant,
            )
            institution_id = institution.id
        finally:
            # الجلسةُ تُغلَق قبل النواة بقصد: النواةُ تفتح جلستَها، وإبقاءُ جلستنا
            # يُقفل الصفوفَ طولَ التنفيذ.
            session.close()

        task = self._core.submit(
            TASK_TYPE_GOVERNMENT_OPERATION,
            summary,
            domain="federation",
            tenant_id=tenant,
        )
        outcome = self._core.run(task["id"], max_steps=max_steps)
        final_state = outcome.get("final_state") if isinstance(outcome, dict) else None
        status = "executed" if task.get("id") else "failed"

        record = self._record_operation(
            context,
            kind="TASK",
            level=level,
            authority=authority,
            institution_id=institution_id,
            department_id=department_id if level == "DEPARTMENT" else None,
            decision_id=decision_id,
            case_id=case_id,
            ruling_id=ruling_id,
            task_id=task["id"],
            transaction_reference=None,
            status=status,
            detail=f"final_state={final_state}",
        )
        return {**record, "task": task, "final_state": final_state}

    def execute_scoped_disbursement(
        self,
        context: AuthorizationContext,
        *,
        treasury: Any,
        institution_code: str,
        level: str,
        allocation_id: str,
        expense_account_code: str,
        amount: Decimal | str,
        purpose: str,
        idempotency_key: str,
        department_id: str | None = None,
        decision_id: str | None = None,
    ) -> dict[str, Any]:
        """اصرِف من الخزانة بسلطةٍ حكوميةٍ مُنطَّقة — والخزانةُ **تُمرَّر ولا تُبنى**.

        `treasury` وسيطٌ لا استيراد: فلا خزانةَ ثانية ولا اختصارَ يكتب في دفترها.
        والمبلغُ يُفحَص مرّتين: في مِنحة R7-C (`max_amount`)، وفي التفويض إن كان
        العبورُ بتفويض. والخزانةُ تُطبّق أقفالَ صفوفها القائمة كما هي.
        """
        require_domain_permission(context, "federation.treasury.execute", PERMISSIONS_SCOPE_WRITE)
        if level not in SCOPE_LEVELS:
            raise FederationError(f"مستوى نطاقٍ مجهول: {level}")
        tenant = self._tenant_of(context)
        # المبلغُ يُوحَّد `Decimal` للفحص، ويُمرَّر إلى الخزانة بنصِّه كما تتوقّعه
        # واجهتُها القائمة — فلا تحويلَ صامتٌ يغيّر دقّةً عشرية.
        checked_amount = amount if isinstance(amount, Decimal) else Decimal(str(amount))
        session = self._session()
        try:
            institution = self._institution_row(session, context, institution_code)
            authority = require_government_authority(
                session,
                context,
                "treasury.disbursement.post",
                target_level=level,
                institution_id=institution.id,
                department_id=department_id,
                amount=checked_amount,
                tenant_id=tenant,
            )
            institution_id = institution.id
            official_id = authority.decision.official_id
        finally:
            session.close()

        result = treasury.disburse(
            context=context,
            allocation_id=allocation_id,
            expense_account_code=expense_account_code,
            amount=amount,
            purpose=purpose,
            official_id=official_id,
            idempotency_key=idempotency_key,
        )
        reference = result.get("reference") or result.get("id")
        return {
            **self._record_operation(
                context,
                kind="TREASURY",
                level=level,
                authority=authority,
                institution_id=institution_id,
                department_id=department_id if level == "DEPARTMENT" else None,
                decision_id=decision_id,
                case_id=None,
                ruling_id=None,
                task_id=None,
                transaction_reference=reference,
                status="executed" if reference else "failed",
                detail=purpose,
            ),
            "transaction": result,
        }

    # ── القراءة ──────────────────────────────────────────────────────────

    def government_registry(self, context: AuthorizationContext) -> list[dict[str, Any]]:
        """اقرأ سجلَّ الحكومات في هذا المستأجر — المحلولةَ والمُعلَّقةَ والمُنحلّة."""
        require_domain_permission(context, "federation.registry.read", PERMISSIONS_FEDERATION_READ)
        tenant = self._tenant_of(context)
        session = self._session()
        try:
            rows = session.scalars(
                select(GovernmentModel)
                .where(GovernmentModel.tenant_id == tenant)
                .order_by(GovernmentModel.level, GovernmentModel.code)
            ).all()
            return [self._government_dict(row) for row in rows]
        finally:
            session.close()

    def describe_institution_scope(
        self, context: AuthorizationContext, institution_code: str
    ) -> dict[str, Any]:
        """أين تقع هذه المؤسسة؟ حكومتُها وسلسلتُها — أو `UNRESOLVED` بلا تخمين."""
        require_domain_permission(context, "federation.registry.read", PERMISSIONS_FEDERATION_READ)
        tenant = self._tenant_of(context)
        session = self._session()
        try:
            institution = self._institution_row(session, context, institution_code)
            government_id = government_of_institution(session, institution.id, tenant_id=tenant)
            if not government_id:
                return {
                    "institution_id": institution.id,
                    "institution_code": institution.code,
                    "government_id": None,
                    "chain": [],
                    "classification": "UNRESOLVED",
                    "reason": "لا صفَّ ربطٍ حكوميّ لهذه المؤسسة",
                }
            chain = government_chain(session, government_id, tenant_id=tenant)
            government = session.get(GovernmentModel, government_id)
            return {
                "institution_id": institution.id,
                "institution_code": institution.code,
                "government_id": government_id,
                "government_level": government.level if government else None,
                "government_status": government.status if government else None,
                "chain": list(chain),
                "classification": "PROVEN",
                "reason": "ربطٌ حكوميٌّ حاضر",
            }
        finally:
            session.close()

    def describe_agent_scope(self, context: AuthorizationContext, agent_id: str) -> dict[str, Any]:
        """اقرأ موضعَ وكيلٍ في بنية الدولة — **بلا سلطةٍ من الانتماء** (R8-N).

        لا سجلَّ وكلاءَ جديد: يُقرأ `state_officials.agent_id` القائم. والمُعاد
        يقول صراحةً إن الانتماءَ المؤسسيّ **لا** يمنح سلطةً فدراليةً ولا ولائية،
        فمن أراد سلطةَ وكيلٍ فليقرأ مناصبَه ومِنَحه في R7-C.
        """
        require_domain_permission(context, "federation.registry.read", PERMISSIONS_FEDERATION_READ)
        tenant = self._tenant_of(context)
        session = self._session()
        try:
            officials = session.scalars(
                select(OfficialModel).where(
                    OfficialModel.agent_id == agent_id, OfficialModel.tenant_id == tenant
                )
            ).all()
            memberships = []
            for official in officials:
                government_id = government_of_institution(
                    session, official.institution_id, tenant_id=tenant
                )
                memberships.append(
                    {
                        "official_id": official.id,
                        "institution_id": official.institution_id,
                        "government_id": government_id,
                        "classification": "PROVEN" if government_id else "UNRESOLVED",
                    }
                )
            return {
                "agent_id": agent_id,
                "memberships": memberships,
                "federal_authority": False,
                "state_authority": False,
                "authority_source": "state_positions + state_authority_grants (R7-C)",
                "note": "الانتماءُ المؤسسيّ لا يمنح سلطةً — تُحلُّ السلطةُ بالمناصب والمِنَح",
            }
        finally:
            session.close()

    def authority_preview(
        self,
        context: AuthorizationContext,
        *,
        operation: str,
        institution_code: str,
        level: str,
        department_id: str | None = None,
        amount: Decimal | None = None,
    ) -> dict[str, Any]:
        """اقرأ ما سيكون عليه الحكمُ **بلا كتابةٍ ولا تنفيذ** — للتشخيص والفحص."""
        require_domain_permission(context, "federation.registry.read", PERMISSIONS_FEDERATION_READ)
        tenant = self._tenant_of(context)
        session = self._session()
        try:
            institution = self._institution_row(session, context, institution_code)
            authority = resolve_government_authority(
                session,
                context,
                operation,
                target_level=level,
                institution_id=institution.id,
                department_id=department_id,
                amount=amount,
                tenant_id=tenant,
            )
            return authority.as_dict()
        finally:
            session.close()


_FEDERATION: FederalStateGovernment | None = None


def get_federal_state() -> FederalStateGovernment:
    """المُفردة الوحيدة — على نمط `get_federal_judiciary` القائم."""
    global _FEDERATION
    if _FEDERATION is None:
        _FEDERATION = FederalStateGovernment()
    return _FEDERATION


def reset_federal_state() -> None:
    """أعِد التصفير — للاختبارات وحدها، على النمط القائم في بقيّة النطاقات."""
    global _FEDERATION
    _FEDERATION = None


__all__ = [
    "TASK_TYPE_GOVERNMENT_OPERATION",
    "DuplicateGovernmentError",
    "FederalStateGovernment",
    "FederationError",
    "GovernmentAuthorityError",
    "GovernmentNotFoundError",
    "get_federal_state",
    "reset_federal_state",
]
