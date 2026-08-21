"""
AMOS-Federation National Economy — Economic State Service
الهدف: أفعالُ الدولة الاقتصادية **فوق** الخزانة والنواة القائمتين، بسلطةٍ مُحلَّلةٍ لكلِّ فعل
النطاق: services/national_economy
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17 (R9-D … R9-P)

## ما تفعله هذه الخدمة وما لا تفعله

| تفعل | **لا** تفعل |
| --- | --- |
| تُسجّل قطاعاتٍ وفئاتٍ وبرامجَ وكياناتٍ اقتصاديةً عامّة | سجلَّ مؤسساتٍ أو هوياتٍ ثانيًا |
| تُصدر سياسةً ثمّ تُنفذها **بفعلين مُخوَّلين منفصلين** | سياسةً تصير نافذةً بمجرّد وجود صفّها |
| تُجيز إنفاقًا وتحويلًا ومشترياتٍ قبل أيّ حركةِ مال | حركةَ مالٍ واحدةً بنفسها |
| تُنادي `StateTreasury` **مُمرَّرةً** لتنفيذ الصرف | خزانةً ثانيةً ولا دفترًا ولا رصيدًا مخزّنًا |
| تُنفّذ عبر `ExecutiveCore` وحدَها | `economic_executor` ولا `policy_executor` |
| تكتب أثرَ العملية في `state_government_operations` القائم | جدولَ عملياتٍ ثانيًا |
| تُعلن أحداثًا بعقودٍ في المفردة القائمة | ناقلَ أحداثٍ جديدًا |

## الترتيب في كلِّ فعلٍ مُخوَّل — وسببُه

    صلاحيةُ المجال → سلطةٌ مُحلَّلة (هويةٌ · منصبٌ · مِنحةٌ · حدُّ حكومة)
      → صفُّ المجال → قرارٌ اقتصاديٌّ بإسنادٍ مُصرَّح → إغلاقُ الجلسة
      → [تنفيذٌ بالنواة أو بالخزانة] → أثرُ عمليةٍ → حدثٌ ومُدقَّق

البوّابةُ أوّلًا لأنها أرخصُ من قراءة القاعدة. والسلطةُ قبل الكتابة لأن الرفضَ
بعد الكتابة يعني صفًّا بلا سلطة. والجلسةُ تُغلَق قبل النواة والخزانة لأن كلًّا
منهما يفتح جلستَه، وإبقاءُ جلستنا يُقفل الصفوفَ طولَ التنفيذ.

## المالُ لا يتحرّك هنا

`authorize_expenditure` و`authorize_transfer` تكتبان **إجازةً** حالتُها
`authorized` وبلا `transaction_reference`. ولا تصير `executed` إلا في
`execute_expenditure` / `execute_transfer` بعد أن تُعيد الخزانةُ مرجعَ حركةٍ
حقيقيّ. وقيدُ `CHECK` في 011 يحرس الاتجاهين، فلا حالةٌ تُكتب بلا مرجعها.

## ما يبقى غيرَ متوفّر ويُقال كذلك

لا تحصيلَ إيرادٍ فعليًّا، ولا سوقَ مشترياتٍ خارجية، ولا ملكيةً قانونيةً خارجية،
ولا نفاذًا قانونيًّا على دائن، ولا قياسَ مؤشّرٍ منفَّذًا. هذه مُقيَّدةٌ في
المخطَّط بقيمةٍ واحدة (`UNAVAILABLE` / `PARTIAL`) فلا يستطيع كودٌ لاحقٌ أن
يرقّيها بكتابةِ نصٍّ أفضل.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from amos_federation.common.database import get_session_factory, init_db
from amos_federation.common.money_delegation import resolve_money_delegation
from amos_federation.common.principal import DEFAULT_TENANT
from amos_federation.services.executive_core import get_executive_core
from amos_federation.services.federal_state.authority import require_government_authority
from amos_federation.services.federal_state.models import GovernmentModel
from amos_federation.services.federal_state.service import get_federal_state
from amos_federation.services.national_economy.authorization import (
    PERMISSIONS_ECONOMY_EXECUTE,
    PERMISSIONS_ECONOMY_POLICY_WRITE,
    PERMISSIONS_ECONOMY_READ,
    PERMISSIONS_ECONOMY_STRUCTURE_WRITE,
    TRANSFER_OPERATION_KINDS,
    assert_subject_kind,
    require_domain_permission,
    require_economic_authority,
    require_tenant,
)
from amos_federation.services.national_economy.models import (
    ASSET_CLASSES,
    LIABILITY_CLASSES,
    MEASUREMENT_STATUSES,
    POLICY_TYPES,
    PUBLIC_ENTITY_KINDS,
    REVENUE_KINDS,
    SCOPE_LEVELS,
    SECTOR_SCOPE_LEVELS,
    EconomicCategoryModel,
    EconomicDecisionModel,
    EconomicIndicatorDefinitionModel,
    EconomicPolicyModel,
    EconomicProgramModel,
    EconomicSectorModel,
    EconomicTransferModel,
    ExpenditureAuthorizationModel,
    ProcurementModel,
    PublicAssetModel,
    PublicEconomicEntityModel,
    PublicLiabilityModel,
    RevenueSourceModel,
)
from amos_federation.services.national_registry.models import IdentityModel
from amos_federation.services.national_registry.resolver import resolve_identity
from amos_federation.services.state_registry.models import InstitutionModel
from amos_federation.services.state_registry.trace import record_domain_trace
from amos_federation.services.state_treasury.models import AllocationModel, BudgetModel

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from amos_federation.common.principal import AuthorizationContext
    from amos_federation.services.federal_state.authority import GovernmentAuthority

#: نوعُ المهمّة في النواة التنفيذية — **نوعٌ** لا منفِّذٌ جديد.
TASK_TYPE_ECONOMIC_DECISION = "economic_decision"

#: نطاقُ الأحداث والتدقيق لهذه الوحدة.
DOMAIN = "economy"


class EconomicStateError(ValueError):
    """خللٌ في مُدخَلٍ اقتصاديٍّ أو في مرجعٍ مفقود — ليس رفضَ تخويل."""


class EconomicEntityNotFoundError(EconomicStateError):
    """مرجعٌ اقتصاديٌّ غيرُ موجود في هذا المستأجر."""


class DuplicateEconomicEntityError(EconomicStateError):
    """رمزٌ أو مرجعٌ مكرّرٌ داخل المستأجر — الهويةُ مُعرِّفٌ لا اسم."""


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _money(value: Decimal | str | int) -> Decimal:
    """وحِّد المبلغَ `Decimal` بلا عائمٍ وسيط — الدقّةُ العشرية لا تُفقَد."""
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _currency(value: str) -> str:
    code = (value or "").strip()
    if len(code) != 3 or code != code.upper():
        raise EconomicStateError(f"رمزُ عملةٍ غيرُ مقبول: '{value}' — ثلاثةُ أحرفٍ كبيرة")
    return code


class NationalEconomy:
    """واجهةُ الدولة الاقتصادية — سجلٌّ وسياسةٌ وإيرادٌ وإنفاقٌ وأصولٌ وإسناد."""

    def __init__(
        self,
        executive_core: Any | None = None,
        federation: Any | None = None,
    ) -> None:
        init_db()
        #: النواةُ المشتركة القائمة — تُمرَّر في الاختبارات ولا تُستبدَل بأخرى.
        self._core = executive_core if executive_core is not None else get_executive_core()
        #: طبقةُ الحكومة القائمة: منها حدُّ السلطة وأثرُ العملية. لا شجرةَ ثانية.
        self._federation = federation if federation is not None else get_federal_state()

    # ── أدوات داخلية ─────────────────────────────────────────────────────

    def _session(self) -> Session:
        return get_session_factory()()

    @staticmethod
    def _tenant_of(context: AuthorizationContext) -> str:
        return context.tenant_id or DEFAULT_TENANT

    @staticmethod
    def _identity_id(session: Session, context: AuthorizationContext) -> str | None:
        """هويةُ المبدأ إن حُلَّت، وإلّا `None` — ولا معرِّفٌ يُخترع ليمرّ مخطَّط."""
        resolution = resolve_identity(session, context)
        return resolution.identity_id if resolution.resolved else None

    def _institution_row(
        self, session: Session, context: AuthorizationContext, code: str
    ) -> InstitutionModel:
        tenant = self._tenant_of(context)
        row = session.scalar(
            select(InstitutionModel).where(
                InstitutionModel.code == code, InstitutionModel.tenant_id == tenant
            )
        )
        if row is None:
            raise EconomicEntityNotFoundError(f"لا مؤسسة برمز '{code}' في مستأجر '{tenant}'")
        require_tenant(context, row.tenant_id)
        return row

    def _government_row(
        self, session: Session, context: AuthorizationContext, code: str
    ) -> GovernmentModel:
        tenant = self._tenant_of(context)
        row = session.scalar(
            select(GovernmentModel).where(
                GovernmentModel.code == code, GovernmentModel.tenant_id == tenant
            )
        )
        if row is None:
            raise EconomicEntityNotFoundError(f"لا حكومة برمز '{code}' في مستأجر '{tenant}'")
        require_tenant(context, row.tenant_id)
        return row

    def _identity_row(
        self, session: Session, context: AuthorizationContext, identity_id: str
    ) -> IdentityModel:
        tenant = self._tenant_of(context)
        row = session.get(IdentityModel, identity_id)
        if row is None or row.tenant_id != tenant:
            raise EconomicEntityNotFoundError(
                f"لا هوية كانونية '{identity_id}' في مستأجر '{tenant}'"
            )
        require_tenant(context, row.tenant_id)
        return row

    @staticmethod
    def _target_government(authority: GovernmentAuthority) -> str:
        """حكومةُ الهدف — وغيابُها يُقال `UNRESOLVED` ولا يُختلق.

        Raises:
            EconomicStateError: مؤسسةٌ غيرُ مربوطةٍ بحكومة (صفوفُ ما قبل R8).
        """
        government_id = authority.target.government_id
        if not government_id:
            raise EconomicStateError(
                "مؤسسةُ الهدف غيرُ مربوطةٍ بحكومة — الإسنادُ UNRESOLVED ولا تُخترَع حكومة"
            )
        return government_id

    def _assert_unique(
        self, session: Session, model: Any, column: Any, value: str, tenant: str
    ) -> None:
        """الرمزُ/المرجعُ فريدٌ داخل المستأجر — يُفحَص قبل الكتابة ويحرسه قيدُ القاعدة.

        الفحصُ هنا للرسالة لا للأمان: القيدُ الفريد في 011 هو الحرس الحقيقيّ،
        وهذا النداءُ يُنتج خطأً مقروءًا بدل انتهاكِ قيدٍ خام.
        """
        existing = session.scalar(
            select(func.count())
            .select_from(model)
            .where(column == value, model.tenant_id == tenant)
        )
        if existing:
            raise DuplicateEconomicEntityError(
                f"'{value}' مُستعملٌ في {model.__tablename__} داخل مستأجر '{tenant}'"
            )

    def _issue_decision(
        self,
        session: Session,
        context: AuthorizationContext,
        *,
        operation: str,
        subject_kind: str,
        subject_id: str,
        authority: GovernmentAuthority,
        government_id: str,
        institution_id: str,
        department_id: str | None,
        scope_level: str,
        correlation_id: str,
    ) -> EconomicDecisionModel:
        """اكتب قرارًا اقتصاديًّا بإسنادٍ مُصرَّح — تصنيفُه تصنيفُ المحرّك لا أعلى.

        `assert_subject_kind` تمنع إجازةً على غير موضوعها: مِنحةٌ بعملية دعمٍ
        مرفوضة، وأصلٌ بعملية التزامٍ مرفوض. والقاعدةُ تعرف المفردتين ولا تعرف
        الربطَ بينهما، فيُفرض هنا.
        """
        assert_subject_kind(operation, subject_kind)
        decision = EconomicDecisionModel(
            id=f"ecd-{uuid.uuid4().hex[:12]}",
            reference=f"ECD-{uuid.uuid4().hex[:12].upper()}",
            operation=operation,
            subject_kind=subject_kind,
            subject_id=subject_id,
            government_id=government_id,
            institution_id=institution_id,
            department_id=department_id if scope_level == "DEPARTMENT" else None,
            scope_level=scope_level,
            issued_by=context.principal_id,
            identity_id=authority.decision.identity_id,
            official_id=authority.decision.official_id,
            position_id=authority.decision.position_id,
            grant_id=authority.decision.grant_id,
            delegation_id=authority.delegation_id,
            provenance_class=authority.classification,
            authority_reason=authority.boundary_reason,
            status="issued",
            correlation_id=correlation_id,
            tenant_id=self._tenant_of(context),
        )
        session.add(decision)
        return decision

    @staticmethod
    def _decision_dict(row: EconomicDecisionModel) -> dict[str, Any]:
        return {
            "id": row.id,
            "reference": row.reference,
            "operation": row.operation,
            "subject_kind": row.subject_kind,
            "subject_id": row.subject_id,
            "government_id": row.government_id,
            "institution_id": row.institution_id,
            "department_id": row.department_id,
            "scope_level": row.scope_level,
            "issued_by": row.issued_by,
            "identity_id": row.identity_id,
            "official_id": row.official_id,
            "position_id": row.position_id,
            "grant_id": row.grant_id,
            "delegation_id": row.delegation_id,
            "provenance_class": row.provenance_class,
            "authority_reason": row.authority_reason or "",
            "status": row.status,
            "task_id": row.task_id,
            "transaction_reference": row.transaction_reference,
            "operation_id": row.operation_id,
            "correlation_id": row.correlation_id,
            "tenant_id": row.tenant_id,
            "created_at": _iso(row.created_at),
        }

    def _announce(
        self,
        context: AuthorizationContext,
        *,
        action: str,
        subject: str,
        decision: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """أعلِن الحدثَ بحمولةٍ فيها من فعل وبأيّ سلطةٍ وعلى ماذا — لا حمولةَ فارغة."""
        return record_domain_trace(
            context,
            action,
            subject,
            {
                "subject_id": decision["subject_id"],
                "operation": decision["operation"],
                "scope_level": decision["scope_level"],
                "institution_id": decision["institution_id"],
                "classification": decision["provenance_class"],
                "reference": payload.get("reference") or payload.get("code"),
                "decision_id": decision["id"],
                "decision_reference": decision["reference"],
                "government_id": decision["government_id"],
                "department_id": decision["department_id"],
                "identity_id": decision["identity_id"],
                "official_id": decision["official_id"],
                "position_id": decision["position_id"],
                "grant_id": decision["grant_id"],
                "delegation_id": decision["delegation_id"],
                "provenance_class": decision["provenance_class"],
                "boundary_reason": decision["authority_reason"],
                "status": payload.get("status", decision["status"]),
                "amount": str(payload["amount"]) if payload.get("amount") is not None else None,
                "currency": payload.get("currency"),
                "task_id": decision["task_id"],
                "operation_id": decision["operation_id"],
                "transaction_reference": decision["transaction_reference"],
                "correlation_id": decision["correlation_id"],
                "tenant_id": decision["tenant_id"],
            },
        )

    # ── R9-B: بنيةُ السجلّ الاقتصاديّ (تصنيفٌ لا سلطةٌ مالية) ─────────────

    def register_sector(
        self,
        context: AuthorizationContext,
        *,
        code: str,
        name: str,
        government_code: str,
        scope_level: str,
        description: str = "",
    ) -> dict[str, Any]:
        """سجِّل قطاعًا اقتصاديًّا لحكومةٍ قائمة — تصنيفٌ بنيويّ لا فعلٌ ماليّ.

        القطاعُ لا عمليةَ اقتصاديةً له في مفردة R7-C بقصد: تسجيلُه لا يُجيز
        إنفاقًا ولا يُنشئ مالًا، فبوّابتُه صلاحيةُ بنيةٍ لا مِنحةُ منصب.
        """
        require_domain_permission(
            context, "economy.sector.register", PERMISSIONS_ECONOMY_STRUCTURE_WRITE
        )
        if scope_level not in SECTOR_SCOPE_LEVELS:
            raise EconomicStateError(
                f"مستوى قطاعٍ غيرُ مقبول: '{scope_level}' — القطاعُ لحكومةٍ لا لمؤسسة"
            )
        tenant = self._tenant_of(context)
        session = self._session()
        try:
            government = self._government_row(session, context, government_code)
            if government.level != scope_level:
                raise EconomicStateError(
                    f"مستوى القطاع '{scope_level}' يخالف مستوى حكومته '{government.level}'"
                )
            self._assert_unique(
                session, EconomicSectorModel, EconomicSectorModel.code, code, tenant
            )
            row = EconomicSectorModel(
                id=f"esec-{uuid.uuid4().hex[:12]}",
                code=code,
                name=name,
                description=description,
                government_id=government.id,
                scope_level=scope_level,
                status="active",
                created_by=context.principal_id,
                created_by_identity_id=self._identity_id(session, context),
                tenant_id=tenant,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            payload = {
                "id": row.id,
                "code": row.code,
                "name": row.name,
                "description": row.description or "",
                "government_id": row.government_id,
                "scope_level": row.scope_level,
                "status": row.status,
                "created_by": row.created_by,
                "created_by_identity_id": row.created_by_identity_id,
                "tenant_id": row.tenant_id,
                "created_at": _iso(row.created_at),
            }
        finally:
            session.close()
        return payload

    def register_category(
        self,
        context: AuthorizationContext,
        *,
        sector_code: str,
        code: str,
        name: str,
        description: str = "",
    ) -> dict[str, Any]:
        """سجِّل فئةً داخل قطاع — فريدةٌ في قطاعها، لا في المستأجر كلِّه."""
        require_domain_permission(
            context, "economy.category.register", PERMISSIONS_ECONOMY_STRUCTURE_WRITE
        )
        tenant = self._tenant_of(context)
        session = self._session()
        try:
            sector = self._sector_row(session, context, sector_code)
            existing = session.scalar(
                select(func.count())
                .select_from(EconomicCategoryModel)
                .where(
                    EconomicCategoryModel.sector_id == sector.id,
                    EconomicCategoryModel.code == code,
                    EconomicCategoryModel.tenant_id == tenant,
                )
            )
            if existing:
                raise DuplicateEconomicEntityError(
                    f"الفئة '{code}' مُستعملةٌ في القطاع '{sector_code}'"
                )
            row = EconomicCategoryModel(
                id=f"ecat-{uuid.uuid4().hex[:12]}",
                sector_id=sector.id,
                code=code,
                name=name,
                description=description,
                status="active",
                created_by=context.principal_id,
                created_by_identity_id=self._identity_id(session, context),
                tenant_id=tenant,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            payload = {
                "id": row.id,
                "sector_id": row.sector_id,
                "code": row.code,
                "name": row.name,
                "status": row.status,
                "tenant_id": row.tenant_id,
                "created_at": _iso(row.created_at),
            }
        finally:
            session.close()
        return payload

    def define_indicator(
        self,
        context: AuthorizationContext,
        *,
        code: str,
        name: str,
        unit: str,
        method: str,
        government_code: str,
        scope_level: str,
        sector_code: str | None = None,
        measurement_status: str = "UNAVAILABLE",
    ) -> dict[str, Any]:
        """عرِّف مؤشّرًا اقتصاديًّا — **تعريفًا فقط**: لا قياسَ منفَّذًا يُدَّعى.

        `measurement_status` مفردتُه `PARTIAL`/`UNAVAILABLE` ولا تحتوي `REAL`،
        فلا يستطيع نداءٌ أن يُعلن مؤشّرًا مقيسًا وليس في النظام ما يقيسه.
        """
        require_domain_permission(
            context, "economy.indicator.define", PERMISSIONS_ECONOMY_STRUCTURE_WRITE
        )
        if scope_level not in SCOPE_LEVELS:
            raise EconomicStateError(f"مستوى نطاقٍ مجهول: {scope_level}")
        if measurement_status not in MEASUREMENT_STATUSES:
            raise EconomicStateError(
                f"حالةُ قياسٍ غيرُ مقبولة: '{measurement_status}' — لا قياسَ حقيقيًّا في R9"
            )
        tenant = self._tenant_of(context)
        session = self._session()
        try:
            government = self._government_row(session, context, government_code)
            sector_id = self._sector_row(session, context, sector_code).id if sector_code else None
            self._assert_unique(
                session,
                EconomicIndicatorDefinitionModel,
                EconomicIndicatorDefinitionModel.code,
                code,
                tenant,
            )
            row = EconomicIndicatorDefinitionModel(
                id=f"eind-{uuid.uuid4().hex[:12]}",
                code=code,
                name=name,
                unit=unit,
                method=method,
                scope_level=scope_level,
                government_id=government.id,
                sector_id=sector_id,
                measurement_status=measurement_status,
                status="active",
                created_by=context.principal_id,
                created_by_identity_id=self._identity_id(session, context),
                tenant_id=tenant,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            payload = {
                "id": row.id,
                "code": row.code,
                "name": row.name,
                "unit": row.unit,
                "scope_level": row.scope_level,
                "government_id": row.government_id,
                "sector_id": row.sector_id,
                "measurement_status": row.measurement_status,
                "status": row.status,
                "tenant_id": row.tenant_id,
            }
        finally:
            session.close()
        return payload

    def _sector_row(
        self, session: Session, context: AuthorizationContext, code: str
    ) -> EconomicSectorModel:
        tenant = self._tenant_of(context)
        row = session.scalar(
            select(EconomicSectorModel).where(
                EconomicSectorModel.code == code, EconomicSectorModel.tenant_id == tenant
            )
        )
        if row is None:
            raise EconomicEntityNotFoundError(f"لا قطاع برمز '{code}' في مستأجر '{tenant}'")
        require_tenant(context, row.tenant_id)
        return row

    # ── سلطةٌ مُحلَّلةٌ لكلِّ فعلٍ اقتصاديّ ────────────────────────────────

    def _authorize(
        self,
        session: Session,
        context: AuthorizationContext,
        *,
        operation: str,
        institution_code: str,
        scope_level: str,
        department_id: str | None = None,
        amount: Decimal | None = None,
        budget_id: str | None = None,
        account_id: str | None = None,
        claimed_official_id: str | None = None,
    ) -> tuple[InstitutionModel, GovernmentAuthority]:
        """احلُل السلطةَ على مؤسسةٍ قائمةٍ بمستوى الهدف المطلوب.

        لا صلاحيةَ تُستنتَج من دورٍ ولا اسمٍ ولا عضويةِ مؤسسة: المحرّكُ الكانونيّ
        يمشي المبدأ→الهوية→المنصب→المؤسسة→النطاق→القرار، ونحن نُمرِّر الحدَّ
        الذي نريده ونقبل حكمَه كما هو.
        """
        if scope_level not in SCOPE_LEVELS:
            raise EconomicStateError(f"مستوى نطاقٍ مجهول: {scope_level}")
        if scope_level == "DEPARTMENT" and not department_id:
            raise EconomicStateError("نطاقُ DEPARTMENT يلزمه `department_id` صريح")
        institution = self._institution_row(session, context, institution_code)
        authority = require_economic_authority(
            session,
            context,
            operation,
            target_level=scope_level,
            institution_id=institution.id,
            department_id=department_id,
            budget_id=budget_id,
            account_id=account_id,
            amount=amount,
            claimed_official_id=claimed_official_id,
            tenant_id=self._tenant_of(context),
        )
        return institution, authority

    def _execute_via_core(
        self,
        context: AuthorizationContext,
        *,
        authority: GovernmentAuthority,
        scope_level: str,
        institution_id: str,
        department_id: str | None,
        summary: str,
        detail: dict[str, Any],
        max_steps: int = 8,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """نفِّذ بالنواة التنفيذية القائمة وحدَها ثمّ اكتب أثرَ العملية.

        لا `economic_executor` ولا `policy_executor`: مهمّةٌ من نوعٍ اقتصاديٍّ
        تدخل الطابورَ نفسَه وتخضع لحالاته نفسها، فمسارُ التنفيذ يبقى واحدًا
        قابلًا للمراقبة والاستعادة.
        """
        task = self._core.submit(
            TASK_TYPE_ECONOMIC_DECISION,
            summary,
            domain=DOMAIN,
            tenant_id=self._tenant_of(context),
        )
        outcome = self._core.run(task["id"], max_steps=max_steps)
        final_state = outcome.get("final_state") if isinstance(outcome, dict) else None
        operation_record = self._federation._record_operation(
            context,
            kind="TASK",
            level=scope_level,
            authority=authority,
            institution_id=institution_id,
            department_id=department_id,
            decision_id=None,
            case_id=None,
            ruling_id=None,
            task_id=task["id"],
            transaction_reference=None,
            status="executed" if final_state == "completed" else "failed",
            detail=f"{summary} · {detail} · final_state={final_state}",
        )
        return task, operation_record

    # ── R9-B: كيانٌ اقتصاديٌّ عامّ ────────────────────────────────────────

    def register_public_entity(
        self,
        context: AuthorizationContext,
        *,
        code: str,
        name: str,
        entity_kind: str,
        institution_code: str,
        scope_level: str,
        identity_id: str,
        sector_code: str | None = None,
        department_id: str | None = None,
        claimed_official_id: str | None = None,
    ) -> dict[str, Any]:
        """سجِّل كيانًا اقتصاديًّا عامًّا بسلطةٍ مُحلَّلةٍ على مؤسسةٍ مالكة.

        الكيانُ **هويةٌ كانونيةٌ قائمة** لا اسمٌ جديد: `identity_id` يلزمه صفٌّ في
        `state_identities`، والقيدُ `uq_state_public_economic_entities_identity`
        يمنع كيانَين على هويةٍ واحدة. فلا يُخلَق فاعلٌ اقتصاديٌّ من فراغ.
        """
        require_domain_permission(
            context, "economy.entity.register", PERMISSIONS_ECONOMY_STRUCTURE_WRITE
        )
        if entity_kind not in PUBLIC_ENTITY_KINDS:
            raise EconomicStateError(f"نوعُ كيانٍ عامٍّ مجهول: {entity_kind}")
        tenant = self._tenant_of(context)
        correlation_id = context.correlation_id or f"corr-{uuid.uuid4().hex[:12]}"
        session = self._session()
        try:
            institution, authority = self._authorize(
                session,
                context,
                operation="economy.entity.register",
                institution_code=institution_code,
                scope_level=scope_level,
                department_id=department_id,
                claimed_official_id=claimed_official_id,
            )
            government_id = self._target_government(authority)
            self._assert_unique(
                session,
                PublicEconomicEntityModel,
                PublicEconomicEntityModel.code,
                code,
                tenant,
            )
            row = PublicEconomicEntityModel(
                id=f"epub-{uuid.uuid4().hex[:12]}",
                code=code,
                name=name,
                entity_kind=entity_kind,
                sector_id=self._sector_row(session, context, sector_code).id
                if sector_code
                else None,
                identity_id=self._identity_row(session, context, identity_id).id,
                government_id=government_id,
                institution_id=institution.id,
                status="active",
                authority_classification=authority.classification,
                created_by=context.principal_id,
                created_by_identity_id=authority.decision.identity_id,
                tenant_id=tenant,
            )
            session.add(row)
            decision = self._issue_decision(
                session,
                context,
                operation="economy.entity.register",
                subject_kind="ENTITY",
                subject_id=row.id,
                authority=authority,
                government_id=government_id,
                institution_id=institution.id,
                department_id=department_id,
                scope_level=scope_level,
                correlation_id=correlation_id,
            )
            session.commit()
            session.refresh(row)
            payload = {
                "id": row.id,
                "code": row.code,
                "name": row.name,
                "entity_kind": row.entity_kind,
                "identity_id": row.identity_id,
                "sector_id": row.sector_id,
                "government_id": row.government_id,
                "institution_id": row.institution_id,
                "department_id": department_id if scope_level == "DEPARTMENT" else None,
                "scope_level": scope_level,
                "status": row.status,
                "authority_classification": row.authority_classification,
                "tenant_id": row.tenant_id,
            }
            decision_payload = self._decision_dict(decision)
        finally:
            session.close()
        trace = self._announce(
            context,
            action="economy.entity.register",
            subject="amos_federation.economy.public_entity_registered",
            decision=decision_payload,
            payload=payload,
        )
        return {**payload, "decision": decision_payload, **trace}

    # ── R9-K: برنامجٌ اقتصاديٌّ حكوميّ ────────────────────────────────────

    def create_program(
        self,
        context: AuthorizationContext,
        *,
        code: str,
        name: str,
        institution_code: str,
        scope_level: str,
        sector_code: str | None = None,
        category_code: str | None = None,
        department_id: str | None = None,
        purpose: str = "غرضٌ حكوميٌّ مُعلَن",
        claimed_official_id: str | None = None,
    ) -> dict[str, Any]:
        """أنشئ برنامجًا اقتصاديًّا — مسوّدةً: لا مالَ له حتى تُجاز مصروفاته."""
        require_domain_permission(
            context, "economy.program.create", PERMISSIONS_ECONOMY_STRUCTURE_WRITE
        )
        tenant = self._tenant_of(context)
        correlation_id = context.correlation_id or f"corr-{uuid.uuid4().hex[:12]}"
        session = self._session()
        try:
            institution, authority = self._authorize(
                session,
                context,
                operation="economy.program.create",
                institution_code=institution_code,
                scope_level=scope_level,
                department_id=department_id,
                claimed_official_id=claimed_official_id,
            )
            government_id = self._target_government(authority)
            self._assert_unique(
                session, EconomicProgramModel, EconomicProgramModel.code, code, tenant
            )
            sector = self._sector_row(session, context, sector_code) if sector_code else None
            category_id = None
            if category_code:
                if sector is None:
                    raise EconomicStateError("الفئةُ لا تُحدَّد بلا قطاعها")
                category = session.scalar(
                    select(EconomicCategoryModel).where(
                        EconomicCategoryModel.sector_id == sector.id,
                        EconomicCategoryModel.code == category_code,
                        EconomicCategoryModel.tenant_id == tenant,
                    )
                )
                if category is None:
                    raise EconomicEntityNotFoundError(
                        f"لا فئة '{category_code}' في القطاع '{sector_code}'"
                    )
                category_id = category.id
            row = EconomicProgramModel(
                id=f"eprg-{uuid.uuid4().hex[:12]}",
                code=code,
                name=name,
                purpose=purpose,
                sector_id=sector.id if sector else None,
                category_id=category_id,
                government_id=government_id,
                institution_id=institution.id,
                department_id=department_id if scope_level == "DEPARTMENT" else None,
                scope_level=scope_level,
                status="draft",
                authority_classification=authority.classification,
                created_by=context.principal_id,
                created_by_identity_id=authority.decision.identity_id,
                tenant_id=tenant,
            )
            session.add(row)
            decision = self._issue_decision(
                session,
                context,
                operation="economy.program.create",
                subject_kind="PROGRAM",
                subject_id=row.id,
                authority=authority,
                government_id=government_id,
                institution_id=institution.id,
                department_id=department_id,
                scope_level=scope_level,
                correlation_id=correlation_id,
            )
            session.commit()
            session.refresh(row)
            payload = {
                "id": row.id,
                "code": row.code,
                "name": row.name,
                "sector_id": row.sector_id,
                "category_id": row.category_id,
                "government_id": row.government_id,
                "institution_id": row.institution_id,
                "department_id": row.department_id,
                "scope_level": row.scope_level,
                "status": row.status,
                "authority_classification": row.authority_classification,
                "tenant_id": row.tenant_id,
            }
            decision_payload = self._decision_dict(decision)
        finally:
            session.close()
        trace = self._announce(
            context,
            action="economy.program.create",
            subject="amos_federation.economy.program_created",
            decision=decision_payload,
            payload=payload,
        )
        return {**payload, "decision": decision_payload, **trace}

    # ── R9-D: السياسةُ الاقتصادية — إصدارٌ ثمّ نفاذٌ بفعلين ────────────────

    def issue_policy(
        self,
        context: AuthorizationContext,
        *,
        code: str,
        title: str,
        policy_type: str,
        institution_code: str,
        scope_level: str,
        sector_code: str | None = None,
        department_id: str | None = None,
        body: str = "",
        claimed_official_id: str | None = None,
    ) -> dict[str, Any]:
        """أصدِر سياسةً **مسوّدةً**: وجودُ الصفِّ لا يجعلها نافذة.

        النفاذُ فعلٌ ثانٍ (`activate_policy`) بعمليةٍ ثانيةٍ وسلطةٍ تُحلَّل من
        جديد، ويُشترط في المخطَّط أن للسياسة النافذة تاريخَ نفاذٍ وهويةً
        ومنصبًا ومعرِّفَ عمليةٍ حقيقيًّا. فلا نفاذَ بالكتابة وحدَها.
        """
        require_domain_permission(context, "economy.policy.issue", PERMISSIONS_ECONOMY_POLICY_WRITE)
        if policy_type not in POLICY_TYPES:
            raise EconomicStateError(f"نوعُ سياسةٍ مجهول: {policy_type}")
        tenant = self._tenant_of(context)
        correlation_id = context.correlation_id or f"corr-{uuid.uuid4().hex[:12]}"
        session = self._session()
        try:
            institution, authority = self._authorize(
                session,
                context,
                operation="economy.policy.issue",
                institution_code=institution_code,
                scope_level=scope_level,
                department_id=department_id,
                claimed_official_id=claimed_official_id,
            )
            government_id = self._target_government(authority)
            self._assert_unique(
                session, EconomicPolicyModel, EconomicPolicyModel.code, code, tenant
            )
            row = EconomicPolicyModel(
                id=f"epol-{uuid.uuid4().hex[:12]}",
                code=code,
                title=title,
                policy_type=policy_type,
                body=body,
                sector_id=self._sector_row(session, context, sector_code).id
                if sector_code
                else None,
                government_id=government_id,
                owner_institution_id=institution.id,
                department_id=department_id if scope_level == "DEPARTMENT" else None,
                scope_level=scope_level,
                status="draft",
                version=1,
                issued_by=context.principal_id,
                issuing_identity_id=None,
                issuing_position_id=None,
                activation_operation_id=None,
                authority_classification=authority.classification,
                tenant_id=tenant,
            )
            session.add(row)
            decision = self._issue_decision(
                session,
                context,
                operation="economy.policy.issue",
                subject_kind="POLICY",
                subject_id=row.id,
                authority=authority,
                government_id=government_id,
                institution_id=institution.id,
                department_id=department_id,
                scope_level=scope_level,
                correlation_id=correlation_id,
            )
            row.decision_id = decision.id
            session.commit()
            session.refresh(row)
            payload = self._policy_dict(row)
            decision_payload = self._decision_dict(decision)
        finally:
            session.close()
        trace = self._announce(
            context,
            action="economy.policy.issue",
            subject="amos_federation.economy.policy_created",
            decision=decision_payload,
            payload=payload,
        )
        return {**payload, "decision": decision_payload, **trace}

    def activate_policy(
        self,
        context: AuthorizationContext,
        *,
        policy_code: str,
        effective_from: datetime | None = None,
        effective_until: datetime | None = None,
        claimed_official_id: str | None = None,
        max_steps: int = 8,
    ) -> dict[str, Any]:
        """أنفِذ سياسةً مسوّدةً بعمليةٍ تنفيذيةٍ حقيقيةٍ تُثبَت في صفِّها."""
        require_domain_permission(
            context, "economy.policy.activate", PERMISSIONS_ECONOMY_POLICY_WRITE
        )
        tenant = self._tenant_of(context)
        correlation_id = context.correlation_id or f"corr-{uuid.uuid4().hex[:12]}"
        session = self._session()
        try:
            policy = session.scalar(
                select(EconomicPolicyModel).where(
                    EconomicPolicyModel.code == policy_code,
                    EconomicPolicyModel.tenant_id == tenant,
                )
            )
            if policy is None:
                raise EconomicEntityNotFoundError(f"لا سياسة برمز '{policy_code}'")
            require_tenant(context, policy.tenant_id)
            if policy.status != "draft":
                raise EconomicStateError(
                    f"لا تُنفَّذ سياسةٌ حالتُها '{policy.status}' — النفاذُ من المسوّدة فقط"
                )
            institution = session.get(InstitutionModel, policy.owner_institution_id)
            if institution is None:
                raise EconomicEntityNotFoundError("مؤسسةُ السياسة غيرُ موجودة")
            authority = require_economic_authority(
                session,
                context,
                "economy.policy.activate",
                target_level=policy.scope_level,
                institution_id=policy.owner_institution_id,
                department_id=policy.department_id,
                claimed_official_id=claimed_official_id,
                tenant_id=tenant,
            )
            if not authority.decision.identity_id or not authority.decision.position_id:
                raise EconomicStateError(
                    "النفاذُ يلزمه هويةٌ ومنصبٌ مُحلَّلان — لا سياسةَ نافذةً بإسنادٍ ناقص"
                )
            decision = self._issue_decision(
                session,
                context,
                operation="economy.policy.activate",
                subject_kind="POLICY",
                subject_id=policy.id,
                authority=authority,
                government_id=policy.government_id,
                institution_id=policy.owner_institution_id,
                department_id=policy.department_id,
                scope_level=policy.scope_level,
                correlation_id=correlation_id,
            )
            session.commit()
            decision_id = decision.id
            scope_level = policy.scope_level
            institution_id = policy.owner_institution_id
            department_id = policy.department_id
            policy_id = policy.id
        finally:
            session.close()

        task, operation_record = self._execute_via_core(
            context,
            authority=authority,
            scope_level=scope_level,
            institution_id=institution_id,
            department_id=department_id,
            summary=f"نفاذُ سياسةٍ اقتصادية: {policy_code}",
            detail={"policy_id": policy_id, "operation": "economy.policy.activate"},
            max_steps=max_steps,
        )

        session = self._session()
        try:
            policy = session.get(EconomicPolicyModel, policy_id)
            policy.status = "active"
            policy.effective_from = effective_from or _now()
            policy.effective_until = effective_until
            policy.issuing_identity_id = authority.decision.identity_id
            policy.issuing_position_id = authority.decision.position_id
            policy.activation_operation_id = operation_record["id"]
            policy.updated_at = _now()
            decision = session.get(EconomicDecisionModel, decision_id)
            decision.status = "executed"
            decision.task_id = task["id"]
            decision.operation_id = operation_record["id"]
            session.commit()
            session.refresh(policy)
            payload = self._policy_dict(policy)
            decision_payload = self._decision_dict(decision)
        finally:
            session.close()

        trace = self._announce(
            context,
            action="economy.policy.activate",
            subject="amos_federation.economy.policy_activated",
            decision=decision_payload,
            payload=payload,
        )
        return {**payload, "decision": decision_payload, "task_id": task["id"], **trace}

    @staticmethod
    def _policy_dict(row: EconomicPolicyModel) -> dict[str, Any]:
        return {
            "id": row.id,
            "code": row.code,
            "title": row.title,
            "policy_type": row.policy_type,
            "sector_id": row.sector_id,
            "government_id": row.government_id,
            "owner_institution_id": row.owner_institution_id,
            "department_id": row.department_id,
            "scope_level": row.scope_level,
            "status": row.status,
            "version": row.version,
            "effective_from": _iso(row.effective_from),
            "effective_until": _iso(row.effective_until),
            "issued_by": row.issued_by,
            "issuing_identity_id": row.issuing_identity_id,
            "issuing_position_id": row.issuing_position_id,
            "activation_operation_id": row.activation_operation_id,
            "authority_classification": row.authority_classification,
            "tenant_id": row.tenant_id,
        }

    # ── R9-E: مصادرُ الإيراد — تعريفٌ لا تحصيل ────────────────────────────

    def register_revenue_source(
        self,
        context: AuthorizationContext,
        *,
        code: str,
        name: str,
        revenue_kind: str,
        basis: str,
        institution_code: str,
        scope_level: str,
        sector_code: str | None = None,
        program_code: str | None = None,
        policy_code: str | None = None,
        revenue_account_id: str | None = None,
        department_id: str | None = None,
        collection_status: str = "UNAVAILABLE",
        claimed_official_id: str | None = None,
    ) -> dict[str, Any]:
        """سجِّل مصدرَ إيرادٍ **تعريفًا**: لا تحصيلَ ولا قناةَ دفعٍ في R9.

        `collection_status` مفردتُه `PARTIAL`/`UNAVAILABLE` ولا `REAL` فيها:
        `PARTIAL` تعني أن للمصدر حسابَ إيرادٍ في الخزانة يستقبل تمويلًا
        مُخوَّلًا، و`UNAVAILABLE` تعني تعريفًا بلا قناة. ولا سبيلَ لكودٍ لاحقٍ
        أن يكتب "محصَّلٌ فعليًّا" لأن القاعدةَ لا تعرف هذه القيمة.
        """
        require_domain_permission(
            context, "economy.revenue.register", PERMISSIONS_ECONOMY_STRUCTURE_WRITE
        )
        if revenue_kind not in REVENUE_KINDS:
            raise EconomicStateError(f"نوعُ إيرادٍ مجهول: {revenue_kind}")
        if collection_status not in MEASUREMENT_STATUSES:
            raise EconomicStateError(
                f"حالةُ تحصيلٍ غيرُ مقبولة: '{collection_status}' — لا تحصيلَ حقيقيًّا في R9"
            )
        tenant = self._tenant_of(context)
        correlation_id = context.correlation_id or f"corr-{uuid.uuid4().hex[:12]}"
        session = self._session()
        try:
            institution, authority = self._authorize(
                session,
                context,
                operation="economy.revenue.register",
                institution_code=institution_code,
                scope_level=scope_level,
                department_id=department_id,
                claimed_official_id=claimed_official_id,
            )
            government_id = self._target_government(authority)
            self._assert_unique(session, RevenueSourceModel, RevenueSourceModel.code, code, tenant)
            row = RevenueSourceModel(
                id=f"erev-{uuid.uuid4().hex[:12]}",
                code=code,
                name=name,
                revenue_kind=revenue_kind,
                basis=basis,
                government_id=government_id,
                institution_id=institution.id,
                department_id=department_id if scope_level == "DEPARTMENT" else None,
                sector_id=self._sector_row(session, context, sector_code).id
                if sector_code
                else None,
                program_id=self._program_row(session, context, program_code).id
                if program_code
                else None,
                policy_id=self._policy_row(session, context, policy_code).id
                if policy_code
                else None,
                revenue_account_id=revenue_account_id,
                collection_status=collection_status,
                status="active",
                registered_by=context.principal_id,
                registered_by_identity_id=authority.decision.identity_id,
                registered_by_position_id=authority.decision.position_id,
                authority_classification=authority.classification,
                tenant_id=tenant,
            )
            session.add(row)
            decision = self._issue_decision(
                session,
                context,
                operation="economy.revenue.register",
                subject_kind="REVENUE_SOURCE",
                subject_id=row.id,
                authority=authority,
                government_id=government_id,
                institution_id=institution.id,
                department_id=department_id,
                scope_level=scope_level,
                correlation_id=correlation_id,
            )
            session.commit()
            session.refresh(row)
            payload = {
                "id": row.id,
                "code": row.code,
                "name": row.name,
                "revenue_kind": row.revenue_kind,
                "basis": row.basis,
                "government_id": row.government_id,
                "institution_id": row.institution_id,
                "department_id": row.department_id,
                "sector_id": row.sector_id,
                "program_id": row.program_id,
                "policy_id": row.policy_id,
                "revenue_account_id": row.revenue_account_id,
                "collection_status": row.collection_status,
                "status": row.status,
                "authority_classification": row.authority_classification,
                "tenant_id": row.tenant_id,
            }
            decision_payload = self._decision_dict(decision)
        finally:
            session.close()
        trace = self._announce(
            context,
            action="economy.revenue.register",
            subject="amos_federation.economy.revenue_source_created",
            decision=decision_payload,
            payload=payload,
        )
        return {**payload, "decision": decision_payload, **trace}

    def _program_row(
        self, session: Session, context: AuthorizationContext, code: str
    ) -> EconomicProgramModel:
        tenant = self._tenant_of(context)
        row = session.scalar(
            select(EconomicProgramModel).where(
                EconomicProgramModel.code == code, EconomicProgramModel.tenant_id == tenant
            )
        )
        if row is None:
            raise EconomicEntityNotFoundError(f"لا برنامج برمز '{code}' في مستأجر '{tenant}'")
        require_tenant(context, row.tenant_id)
        return row

    def _policy_row(
        self, session: Session, context: AuthorizationContext, code: str
    ) -> EconomicPolicyModel:
        tenant = self._tenant_of(context)
        row = session.scalar(
            select(EconomicPolicyModel).where(
                EconomicPolicyModel.code == code, EconomicPolicyModel.tenant_id == tenant
            )
        )
        if row is None:
            raise EconomicEntityNotFoundError(f"لا سياسة برمز '{code}' في مستأجر '{tenant}'")
        require_tenant(context, row.tenant_id)
        return row

    def _allocation_pair(
        self, session: Session, context: AuthorizationContext, allocation_id: str
    ) -> tuple[AllocationModel, BudgetModel]:
        """تحقّق أن التخصيصَ وميزانيتَه في مستأجرِ المستدعي قبل أيّ إجازةِ إنفاق."""
        allocation = session.get(AllocationModel, allocation_id)
        if allocation is None:
            raise EconomicEntityNotFoundError(f"لا تخصيص '{allocation_id}'")
        require_tenant(context, allocation.tenant_id)
        budget = session.get(BudgetModel, allocation.budget_id)
        if budget is None:
            raise EconomicEntityNotFoundError("ميزانيةُ التخصيص غيرُ موجودة")
        require_tenant(context, budget.tenant_id)
        return allocation, budget

    # ── R9-F: إجازةُ الإنفاق ثمّ تنفيذُه بالخزانة القائمة ──────────────────

    def authorize_expenditure(
        self,
        context: AuthorizationContext,
        *,
        program_code: str,
        allocation_id: str,
        institution_code: str,
        scope_level: str,
        amount: Decimal | str | int,
        purpose: str,
        currency: str = "SAR",
        policy_code: str | None = None,
        department_id: str | None = None,
        claimed_official_id: str | None = None,
    ) -> dict[str, Any]:
        """أجِز إنفاقًا قبل أيّ حركةِ مال — حالتُها `authorized` وبلا مرجعِ حركة."""
        resolve_money_delegation(
            "economy.expenditure.authorize", entrypoint="authorize_expenditure"
        )
        require_domain_permission(
            context, "economy.expenditure.authorize", PERMISSIONS_ECONOMY_EXECUTE
        )
        spend = _money(amount)
        if spend <= 0:
            raise EconomicStateError("مبلغُ الإجازة يجب أن يكون موجبًا")
        code = _currency(currency)
        if not purpose.strip():
            raise EconomicStateError("الإجازةُ تلزمها غرضٌ مكتوب")
        tenant = self._tenant_of(context)
        correlation_id = context.correlation_id or f"corr-{uuid.uuid4().hex[:12]}"
        session = self._session()
        try:
            program = self._program_row(session, context, program_code)
            allocation, budget = self._allocation_pair(session, context, allocation_id)
            institution, authority = self._authorize(
                session,
                context,
                operation="economy.expenditure.authorize",
                institution_code=institution_code,
                scope_level=scope_level,
                department_id=department_id,
                amount=spend,
                budget_id=budget.id,
                account_id=allocation.account_id,
                claimed_official_id=claimed_official_id,
            )
            government_id = self._target_government(authority)
            row = ExpenditureAuthorizationModel(
                id=f"eexp-{uuid.uuid4().hex[:12]}",
                reference=f"EXP-{uuid.uuid4().hex[:12].upper()}",
                program_id=program.id,
                budget_id=budget.id,
                allocation_id=allocation.id,
                government_id=government_id,
                institution_id=institution.id,
                department_id=department_id if scope_level == "DEPARTMENT" else None,
                scope_level=scope_level,
                amount=spend,
                currency=code,
                purpose=purpose,
                policy_id=self._policy_row(session, context, policy_code).id
                if policy_code
                else None,
                status="authorized",
                authorized_by=context.principal_id,
                authorizing_identity_id=authority.decision.identity_id,
                authorizing_position_id=authority.decision.position_id,
                authority_classification=authority.classification,
                grant_id=authority.decision.grant_id,
                correlation_id=correlation_id,
                tenant_id=tenant,
            )
            session.add(row)
            decision = self._issue_decision(
                session,
                context,
                operation="economy.expenditure.authorize",
                subject_kind="EXPENDITURE",
                subject_id=row.id,
                authority=authority,
                government_id=government_id,
                institution_id=institution.id,
                department_id=department_id,
                scope_level=scope_level,
                correlation_id=correlation_id,
            )
            row.decision_id = decision.id
            session.commit()
            session.refresh(row)
            payload = self._expenditure_dict(row)
            decision_payload = self._decision_dict(decision)
        finally:
            session.close()
        trace = self._announce(
            context,
            action="economy.expenditure.authorize",
            subject="amos_federation.economy.expenditure_authorized",
            decision=decision_payload,
            payload=payload,
        )
        return {**payload, "decision": decision_payload, **trace}

    def execute_expenditure(
        self,
        context: AuthorizationContext,
        *,
        treasury: Any,
        reference: str,
        expense_account_code: str,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """نفِّذ إجازةَ إنفاقٍ **بالخزانة القائمة** — لا دفترَ ولا قفلَ صفوفٍ بديل.

        الخزانةُ تُمرَّر ولا تُستورَد هنا بقصد: هذه الطبقةُ لا تملك الخزانة ولا
        تُنشئ لها نسخةً، بل تُنادي واجهتَها فتبقى الأقفالُ والحدودُ والانعكاسُ
        حيث كانت. وسلطةُ الصرف تُحلَّل بعمليةِ الخزانة `treasury.disbursement.post`
        لا بعملية الإجازة، فإجازةُ الإنفاق لا تُغني عن سلطةِ الصرف.
        """
        require_domain_permission(
            context, "economy.expenditure.execute", PERMISSIONS_ECONOMY_EXECUTE
        )
        tenant = self._tenant_of(context)
        session = self._session()
        try:
            row = session.scalar(
                select(ExpenditureAuthorizationModel).where(
                    ExpenditureAuthorizationModel.reference == reference,
                    ExpenditureAuthorizationModel.tenant_id == tenant,
                )
            )
            if row is None:
                raise EconomicEntityNotFoundError(f"لا إجازةَ إنفاقٍ بمرجع '{reference}'")
            require_tenant(context, row.tenant_id)
            if row.status != "authorized":
                raise EconomicStateError(
                    f"لا تُنفَّذ إجازةٌ حالتُها '{row.status}' — التنفيذُ من `authorized` فقط"
                )
            authority = require_government_authority(
                session,
                context,
                "treasury.disbursement.post",
                target_level=row.scope_level,
                institution_id=row.institution_id,
                department_id=row.department_id,
                budget_id=row.budget_id,
                amount=row.amount,
                tenant_id=tenant,
            )
            official_id = authority.decision.official_id
            if not official_id:
                raise EconomicStateError("الصرفُ يلزمه موظّفٌ مُحلَّلٌ — لا حركةَ مالٍ بإسنادٍ ناقص")
            authorization_id = row.id
            allocation_id = row.allocation_id
            amount = row.amount
            scope_level = row.scope_level
            institution_id = row.institution_id
            department_id = row.department_id
            purpose = row.purpose
            decision_id = row.decision_id
        finally:
            session.close()

        transaction = treasury.disburse(
            context=context,
            allocation_id=allocation_id,
            expense_account_code=expense_account_code,
            amount=amount,
            purpose=purpose,
            official_id=official_id,
            idempotency_key=idempotency_key or f"exp-{reference}",
        )
        transaction_reference = transaction.get("reference") or transaction.get("id")

        operation_record = self._federation._record_operation(
            context,
            kind="TREASURY",
            level=scope_level,
            authority=authority,
            institution_id=institution_id,
            department_id=department_id,
            decision_id=None,
            case_id=None,
            ruling_id=None,
            task_id=None,
            transaction_reference=transaction_reference,
            status="executed",
            detail=f"تنفيذُ إجازةِ إنفاق {reference}",
        )

        session = self._session()
        try:
            row = session.get(ExpenditureAuthorizationModel, authorization_id)
            row.status = "executed"
            row.transaction_reference = transaction_reference
            row.operation_id = operation_record["id"]
            row.updated_at = _now()
            decision = session.get(EconomicDecisionModel, decision_id) if decision_id else None
            if decision is not None:
                decision.status = "executed"
                decision.transaction_reference = transaction_reference
                decision.operation_id = operation_record["id"]
                decision.task_id = decision.task_id or operation_record.get("task_id")
            session.commit()
            session.refresh(row)
            payload = self._expenditure_dict(row)
            decision_payload = (
                self._decision_dict(decision)
                if decision is not None
                else self._orphan_decision(row)
            )
        finally:
            session.close()

        trace = self._announce(
            context,
            action="economy.expenditure.execute",
            subject="amos_federation.economy.expenditure_executed",
            decision=decision_payload,
            payload=payload,
        )
        return {**payload, "transaction": transaction, "decision": decision_payload, **trace}

    @staticmethod
    def _orphan_decision(row: ExpenditureAuthorizationModel) -> dict[str, Any]:
        """إجازةٌ بلا قرارٍ مرتبطٍ — يُقال `UNRESOLVED` ولا يُختلق إسناد."""
        return {
            "id": None,
            "reference": None,
            "operation": "economy.expenditure.authorize",
            "subject_kind": "EXPENDITURE",
            "subject_id": row.id,
            "government_id": row.government_id,
            "institution_id": row.institution_id,
            "department_id": row.department_id,
            "scope_level": row.scope_level,
            "identity_id": row.authorizing_identity_id,
            "official_id": None,
            "position_id": row.authorizing_position_id,
            "grant_id": row.grant_id,
            "delegation_id": None,
            "provenance_class": "UNRESOLVED",
            "authority_reason": "لا قرارَ اقتصاديًّا مرتبطًا بهذه الإجازة",
            "status": row.status,
            "task_id": None,
            "transaction_reference": row.transaction_reference,
            "operation_id": row.operation_id,
            "correlation_id": row.correlation_id,
            "tenant_id": row.tenant_id,
        }

    @staticmethod
    def _expenditure_dict(row: ExpenditureAuthorizationModel) -> dict[str, Any]:
        return {
            "id": row.id,
            "reference": row.reference,
            "program_id": row.program_id,
            "budget_id": row.budget_id,
            "allocation_id": row.allocation_id,
            "government_id": row.government_id,
            "institution_id": row.institution_id,
            "department_id": row.department_id,
            "scope_level": row.scope_level,
            "amount": row.amount,
            "currency": row.currency,
            "purpose": row.purpose,
            "policy_id": row.policy_id,
            "status": row.status,
            "authorized_by": row.authorized_by,
            "authorizing_identity_id": row.authorizing_identity_id,
            "authorizing_position_id": row.authorizing_position_id,
            "authority_classification": row.authority_classification,
            "grant_id": row.grant_id,
            "decision_id": row.decision_id,
            "operation_id": row.operation_id,
            "transaction_reference": row.transaction_reference,
            "correlation_id": row.correlation_id,
            "tenant_id": row.tenant_id,
        }

    # ── R9-I: المِنحُ والدعم — إجازةٌ ثمّ صرفٌ بالخزانة نفسِها ─────────────

    def authorize_transfer(
        self,
        context: AuthorizationContext,
        *,
        transfer_kind: str,
        program_code: str,
        beneficiary_identity_id: str,
        allocation_id: str,
        institution_code: str,
        scope_level: str,
        amount: Decimal | str | int,
        purpose: str,
        currency: str = "SAR",
        beneficiary_entity_code: str | None = None,
        expenditure_reference: str | None = None,
        policy_code: str | None = None,
        department_id: str | None = None,
        claimed_official_id: str | None = None,
    ) -> dict[str, Any]:
        """أجِز مِنحةً أو دعمًا لمستفيدٍ **له هويةٌ كانونية** — لا مستفيدَ نصِّيّ.

        المستفيدُ مربوطٌ بجدول الهويات الكانونيّ لا باسمٍ حرّ، فلا تُجاز مِنحةٌ
        لكيانٍ لا وجودَ له في السجلّ. وعمليةُ التخويل تُشتَقّ من نوع التحويل
        (`GRANT`→`economy.grant.authorize`) فلا تُجاز مِنحةٌ بسلطةِ دعم.
        """
        require_domain_permission(
            context, f"economy.transfer.{transfer_kind.lower()}", PERMISSIONS_ECONOMY_EXECUTE
        )
        operations = {kind: op for op, kind in TRANSFER_OPERATION_KINDS.items()}
        operation = operations.get(transfer_kind)
        if operation is None:
            raise EconomicStateError(
                f"نوعُ تحويلٍ مجهول: '{transfer_kind}' — المقبولُ {sorted(operations)}"
            )
        moved = _money(amount)
        if moved <= 0:
            raise EconomicStateError("مبلغُ التحويل يجب أن يكون موجبًا")
        code = _currency(currency)
        if not purpose.strip():
            raise EconomicStateError("التحويلُ يلزمه غرضٌ مكتوب")
        tenant = self._tenant_of(context)
        correlation_id = context.correlation_id or f"corr-{uuid.uuid4().hex[:12]}"
        session = self._session()
        try:
            program = self._program_row(session, context, program_code)
            allocation, budget = self._allocation_pair(session, context, allocation_id)
            self._identity_row(session, context, beneficiary_identity_id)
            institution, authority = self._authorize(
                session,
                context,
                operation=operation,
                institution_code=institution_code,
                scope_level=scope_level,
                department_id=department_id,
                amount=moved,
                budget_id=budget.id,
                account_id=allocation.account_id,
                claimed_official_id=claimed_official_id,
            )
            government_id = self._target_government(authority)
            expenditure_id = None
            if expenditure_reference:
                expenditure = session.scalar(
                    select(ExpenditureAuthorizationModel).where(
                        ExpenditureAuthorizationModel.reference == expenditure_reference,
                        ExpenditureAuthorizationModel.tenant_id == tenant,
                    )
                )
                if expenditure is None:
                    raise EconomicEntityNotFoundError(
                        f"لا إجازةَ إنفاقٍ بمرجع '{expenditure_reference}'"
                    )
                expenditure_id = expenditure.id
            beneficiary_entity_id = None
            if beneficiary_entity_code:
                entity = session.scalar(
                    select(PublicEconomicEntityModel).where(
                        PublicEconomicEntityModel.code == beneficiary_entity_code,
                        PublicEconomicEntityModel.tenant_id == tenant,
                    )
                )
                if entity is None:
                    raise EconomicEntityNotFoundError(
                        f"لا كيانَ عامًّا برمز '{beneficiary_entity_code}'"
                    )
                beneficiary_entity_id = entity.id
            row = EconomicTransferModel(
                id=f"etrf-{uuid.uuid4().hex[:12]}",
                reference=f"TRF-{uuid.uuid4().hex[:12].upper()}",
                transfer_kind=transfer_kind,
                program_id=program.id,
                beneficiary_identity_id=beneficiary_identity_id,
                beneficiary_entity_id=beneficiary_entity_id,
                government_id=government_id,
                institution_id=institution.id,
                department_id=department_id if scope_level == "DEPARTMENT" else None,
                scope_level=scope_level,
                budget_id=budget.id,
                allocation_id=allocation.id,
                amount=moved,
                currency=code,
                purpose=purpose,
                policy_id=self._policy_row(session, context, policy_code).id
                if policy_code
                else None,
                status="authorized",
                authorized_by=context.principal_id,
                authorizing_identity_id=authority.decision.identity_id,
                authorizing_position_id=authority.decision.position_id,
                authority_classification=authority.classification,
                expenditure_authorization_id=expenditure_id,
                correlation_id=correlation_id,
                tenant_id=tenant,
            )
            session.add(row)
            decision = self._issue_decision(
                session,
                context,
                operation=operation,
                subject_kind="TRANSFER",
                subject_id=row.id,
                authority=authority,
                government_id=government_id,
                institution_id=institution.id,
                department_id=department_id,
                scope_level=scope_level,
                correlation_id=correlation_id,
            )
            row.decision_id = decision.id
            session.commit()
            session.refresh(row)
            payload = self._transfer_dict(row)
            decision_payload = self._decision_dict(decision)
        finally:
            session.close()
        subject = (
            "amos_federation.economy.grant_authorized"
            if transfer_kind == "GRANT"
            else "amos_federation.economy.subsidy_authorized"
        )
        trace = self._announce(
            context,
            action=f"economy.transfer.{transfer_kind.lower()}",
            subject=subject,
            decision=decision_payload,
            payload=payload,
        )
        return {**payload, "decision": decision_payload, **trace}

    def execute_transfer(
        self,
        context: AuthorizationContext,
        *,
        treasury: Any,
        reference: str,
        expense_account_code: str,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """اصرف تحويلًا مُجازًا بالخزانة القائمة — لا محرّكَ نقلِ مالٍ ثانيًا."""
        resolve_money_delegation("economy.transfer.execute", entrypoint="execute_transfer")
        require_domain_permission(context, "economy.transfer.execute", PERMISSIONS_ECONOMY_EXECUTE)
        tenant = self._tenant_of(context)
        session = self._session()
        try:
            row = session.scalar(
                select(EconomicTransferModel).where(
                    EconomicTransferModel.reference == reference,
                    EconomicTransferModel.tenant_id == tenant,
                )
            )
            if row is None:
                raise EconomicEntityNotFoundError(f"لا تحويلَ بمرجع '{reference}'")
            require_tenant(context, row.tenant_id)
            if row.status != "authorized":
                raise EconomicStateError(
                    f"لا يُصرَف تحويلٌ حالتُه '{row.status}' — الصرفُ من `authorized` فقط"
                )
            authority = require_government_authority(
                session,
                context,
                "treasury.disbursement.post",
                target_level=row.scope_level,
                institution_id=row.institution_id,
                department_id=row.department_id,
                budget_id=row.budget_id,
                amount=row.amount,
                tenant_id=tenant,
            )
            official_id = authority.decision.official_id
            if not official_id:
                raise EconomicStateError("الصرفُ يلزمه موظّفٌ مُحلَّل")
            transfer_id, allocation_id, amount = row.id, row.allocation_id, row.amount
            scope_level, institution_id = row.scope_level, row.institution_id
            department_id, purpose, decision_id = row.department_id, row.purpose, row.decision_id
            transfer_kind = row.transfer_kind
        finally:
            session.close()

        transaction = treasury.disburse(
            context=context,
            allocation_id=allocation_id,
            expense_account_code=expense_account_code,
            amount=amount,
            purpose=purpose,
            official_id=official_id,
            idempotency_key=idempotency_key or f"trf-{reference}",
        )
        transaction_reference = transaction.get("reference") or transaction.get("id")
        operation_record = self._federation._record_operation(
            context,
            kind="TREASURY",
            level=scope_level,
            authority=authority,
            institution_id=institution_id,
            department_id=department_id,
            decision_id=None,
            case_id=None,
            ruling_id=None,
            task_id=None,
            transaction_reference=transaction_reference,
            status="executed",
            detail=f"صرفُ تحويل {transfer_kind} {reference}",
        )

        session = self._session()
        try:
            row = session.get(EconomicTransferModel, transfer_id)
            row.status = "executed"
            row.transaction_reference = transaction_reference
            row.operation_id = operation_record["id"]
            row.updated_at = _now()
            decision = session.get(EconomicDecisionModel, decision_id) if decision_id else None
            if decision is not None:
                decision.status = "executed"
                decision.transaction_reference = transaction_reference
                decision.operation_id = operation_record["id"]
            session.commit()
            session.refresh(row)
            payload = self._transfer_dict(row)
            decision_payload = self._decision_dict(decision) if decision is not None else {}
        finally:
            session.close()
        return {**payload, "transaction": transaction, "decision": decision_payload}

    @staticmethod
    def _transfer_dict(row: EconomicTransferModel) -> dict[str, Any]:
        return {
            "id": row.id,
            "reference": row.reference,
            "transfer_kind": row.transfer_kind,
            "program_id": row.program_id,
            "beneficiary_identity_id": row.beneficiary_identity_id,
            "beneficiary_entity_id": row.beneficiary_entity_id,
            "government_id": row.government_id,
            "institution_id": row.institution_id,
            "department_id": row.department_id,
            "scope_level": row.scope_level,
            "budget_id": row.budget_id,
            "allocation_id": row.allocation_id,
            "amount": row.amount,
            "currency": row.currency,
            "purpose": row.purpose,
            "policy_id": row.policy_id,
            "status": row.status,
            "authority_classification": row.authority_classification,
            "expenditure_authorization_id": row.expenditure_authorization_id,
            "decision_id": row.decision_id,
            "operation_id": row.operation_id,
            "transaction_reference": row.transaction_reference,
            "tenant_id": row.tenant_id,
        }

    # ── R9-G / R9-H: الأصولُ والالتزاماتُ العامّة ──────────────────────────

    def register_public_asset(
        self,
        context: AuthorizationContext,
        *,
        code: str,
        name: str,
        asset_class: str,
        institution_code: str,
        scope_level: str,
        custodian_identity_id: str,
        description: str = "",
        book_value: Decimal | str | int | None = None,
        currency: str | None = None,
        department_id: str | None = None,
        claimed_official_id: str | None = None,
    ) -> dict[str, Any]:
        """سجِّل أصلًا عامًّا في **هذا النظام** — لا ملكيةً قانونيةً خارجية.

        `registration_class` ثابتٌ على `SYSTEM_REGISTERED` و`external_ownership_status`
        ثابتٌ على `UNAVAILABLE` بقيدٍ في القاعدة: وجودُ الصفِّ يعني أن النظامَ
        سجّل الأصل، لا أن الدولةَ تملكه في سجلٍّ عقاريٍّ خارجيّ.
        """
        require_domain_permission(
            context, "economy.asset.register", PERMISSIONS_ECONOMY_STRUCTURE_WRITE
        )
        if asset_class not in ASSET_CLASSES:
            raise EconomicStateError(f"صنفُ أصلٍ مجهول: {asset_class}")
        value = _money(book_value) if book_value is not None else None
        if value is not None and value <= 0:
            raise EconomicStateError("قيمةُ الأصل الدفترية يجب أن تكون موجبةً أو غائبة")
        money_code = _currency(currency) if currency else None
        if (value is None) != (money_code is None):
            raise EconomicStateError("القيمةُ الدفترية وعملتُها تُذكران معًا أو تُتركان معًا")
        tenant = self._tenant_of(context)
        correlation_id = context.correlation_id or f"corr-{uuid.uuid4().hex[:12]}"
        session = self._session()
        try:
            self._identity_row(session, context, custodian_identity_id)
            institution, authority = self._authorize(
                session,
                context,
                operation="economy.asset.register",
                institution_code=institution_code,
                scope_level=scope_level,
                department_id=department_id,
                claimed_official_id=claimed_official_id,
            )
            government_id = self._target_government(authority)
            self._assert_unique(session, PublicAssetModel, PublicAssetModel.code, code, tenant)
            row = PublicAssetModel(
                id=f"east-{uuid.uuid4().hex[:12]}",
                code=code,
                name=name,
                asset_class=asset_class,
                description=description,
                government_id=government_id,
                institution_id=institution.id,
                department_id=department_id if scope_level == "DEPARTMENT" else None,
                custodian_identity_id=custodian_identity_id,
                registration_class="SYSTEM_REGISTERED",
                external_ownership_status="UNAVAILABLE",
                book_value=value,
                currency=money_code,
                status="active",
                registered_by=context.principal_id,
                registered_by_identity_id=authority.decision.identity_id,
                registered_by_position_id=authority.decision.position_id,
                authority_classification=authority.classification,
                tenant_id=tenant,
            )
            session.add(row)
            decision = self._issue_decision(
                session,
                context,
                operation="economy.asset.register",
                subject_kind="ASSET",
                subject_id=row.id,
                authority=authority,
                government_id=government_id,
                institution_id=institution.id,
                department_id=department_id,
                scope_level=scope_level,
                correlation_id=correlation_id,
            )
            session.commit()
            session.refresh(row)
            payload = {
                "id": row.id,
                "code": row.code,
                "name": row.name,
                "asset_class": row.asset_class,
                "government_id": row.government_id,
                "institution_id": row.institution_id,
                "department_id": row.department_id,
                "custodian_identity_id": row.custodian_identity_id,
                "registration_class": row.registration_class,
                "external_ownership_status": row.external_ownership_status,
                "book_value": row.book_value,
                "currency": row.currency,
                "status": row.status,
                "authority_classification": row.authority_classification,
                "tenant_id": row.tenant_id,
            }
            decision_payload = self._decision_dict(decision)
        finally:
            session.close()
        trace = self._announce(
            context,
            action="economy.asset.register",
            subject="amos_federation.economy.public_asset_registered",
            decision=decision_payload,
            payload=payload,
        )
        return {**payload, "decision": decision_payload, **trace}

    def register_public_liability(
        self,
        context: AuthorizationContext,
        *,
        code: str,
        name: str,
        liability_class: str,
        institution_code: str,
        scope_level: str,
        creditor_identity_id: str,
        principal_amount: Decimal | str | int,
        currency: str = "SAR",
        description: str = "",
        due_at: datetime | None = None,
        department_id: str | None = None,
        claimed_official_id: str | None = None,
    ) -> dict[str, Any]:
        """سجِّل التزامًا عامًّا — الدائنُ هويةٌ كانونيةٌ ولا نفاذَ خارجيًّا يُدَّعى.

        `external_enforceability` مُقيَّدٌ على `UNAVAILABLE`: الصفُّ يقول إن
        النظامَ يعرف الالتزام، لا إن محكمةً تُنفِّذه.
        """
        require_domain_permission(
            context, "economy.liability.register", PERMISSIONS_ECONOMY_STRUCTURE_WRITE
        )
        if liability_class not in LIABILITY_CLASSES:
            raise EconomicStateError(f"صنفُ التزامٍ مجهول: {liability_class}")
        owed = _money(principal_amount)
        if owed <= 0:
            raise EconomicStateError("أصلُ الالتزام يجب أن يكون موجبًا")
        money_code = _currency(currency)
        tenant = self._tenant_of(context)
        correlation_id = context.correlation_id or f"corr-{uuid.uuid4().hex[:12]}"
        session = self._session()
        try:
            self._identity_row(session, context, creditor_identity_id)
            institution, authority = self._authorize(
                session,
                context,
                operation="economy.liability.register",
                institution_code=institution_code,
                scope_level=scope_level,
                department_id=department_id,
                amount=owed,
                claimed_official_id=claimed_official_id,
            )
            government_id = self._target_government(authority)
            self._assert_unique(
                session, PublicLiabilityModel, PublicLiabilityModel.code, code, tenant
            )
            row = PublicLiabilityModel(
                id=f"elia-{uuid.uuid4().hex[:12]}",
                code=code,
                name=name,
                liability_class=liability_class,
                description=description,
                government_id=government_id,
                institution_id=institution.id,
                department_id=department_id if scope_level == "DEPARTMENT" else None,
                creditor_identity_id=creditor_identity_id,
                principal_amount=owed,
                currency=money_code,
                external_enforceability="UNAVAILABLE",
                due_at=due_at,
                status="outstanding",
                registered_by=context.principal_id,
                registered_by_identity_id=authority.decision.identity_id,
                registered_by_position_id=authority.decision.position_id,
                authority_classification=authority.classification,
                tenant_id=tenant,
            )
            session.add(row)
            decision = self._issue_decision(
                session,
                context,
                operation="economy.liability.register",
                subject_kind="LIABILITY",
                subject_id=row.id,
                authority=authority,
                government_id=government_id,
                institution_id=institution.id,
                department_id=department_id,
                scope_level=scope_level,
                correlation_id=correlation_id,
            )
            session.commit()
            session.refresh(row)
            payload = {
                "id": row.id,
                "code": row.code,
                "name": row.name,
                "liability_class": row.liability_class,
                "government_id": row.government_id,
                "institution_id": row.institution_id,
                "department_id": row.department_id,
                "creditor_identity_id": row.creditor_identity_id,
                "principal_amount": row.principal_amount,
                "currency": row.currency,
                "external_enforceability": row.external_enforceability,
                "due_at": _iso(row.due_at),
                "status": row.status,
                "authority_classification": row.authority_classification,
                "tenant_id": row.tenant_id,
            }
            decision_payload = self._decision_dict(decision)
        finally:
            session.close()
        trace = self._announce(
            context,
            action="economy.liability.register",
            subject="amos_federation.economy.public_liability_registered",
            decision=decision_payload,
            payload=payload,
        )
        return {**payload, "decision": decision_payload, **trace}

    # ── R9-J: المشترياتُ — تجريدٌ داخليٌّ لا سوق ───────────────────────────

    def authorize_procurement(
        self,
        context: AuthorizationContext,
        *,
        title: str,
        program_code: str,
        institution_code: str,
        scope_level: str,
        supplier_identity_id: str,
        estimated_amount: Decimal | str | int,
        specification: str,
        currency: str = "SAR",
        expenditure_reference: str | None = None,
        policy_code: str | None = None,
        department_id: str | None = None,
        claimed_official_id: str | None = None,
    ) -> dict[str, Any]:
        """أجِز مشترياتٍ بتجريدٍ داخليٍّ — لا سوقَ ولا مناقصةَ خارجيةً هنا.

        `backend='INTERNAL_ABSTRACTION'` و`external_market_status='UNAVAILABLE'`
        مُقيَّدتان في القاعدة، فلا يستطيع نداءٌ أن يُعلن تكاملًا مع سوقٍ حقيقيّ.
        """
        require_domain_permission(
            context, "economy.procurement.authorize", PERMISSIONS_ECONOMY_EXECUTE
        )
        estimate = _money(estimated_amount)
        if estimate <= 0:
            raise EconomicStateError("القيمةُ التقديرية يجب أن تكون موجبة")
        money_code = _currency(currency)
        if not specification.strip():
            raise EconomicStateError("المشترياتُ تلزمها مواصفةٌ مكتوبة")
        tenant = self._tenant_of(context)
        correlation_id = context.correlation_id or f"corr-{uuid.uuid4().hex[:12]}"
        session = self._session()
        try:
            program = self._program_row(session, context, program_code)
            self._identity_row(session, context, supplier_identity_id)
            institution, authority = self._authorize(
                session,
                context,
                operation="economy.procurement.authorize",
                institution_code=institution_code,
                scope_level=scope_level,
                department_id=department_id,
                amount=estimate,
                claimed_official_id=claimed_official_id,
            )
            government_id = self._target_government(authority)
            expenditure_id = None
            if expenditure_reference:
                expenditure = session.scalar(
                    select(ExpenditureAuthorizationModel).where(
                        ExpenditureAuthorizationModel.reference == expenditure_reference,
                        ExpenditureAuthorizationModel.tenant_id == tenant,
                    )
                )
                if expenditure is None:
                    raise EconomicEntityNotFoundError(
                        f"لا إجازةَ إنفاقٍ بمرجع '{expenditure_reference}'"
                    )
                expenditure_id = expenditure.id
            row = ProcurementModel(
                id=f"eprc-{uuid.uuid4().hex[:12]}",
                reference=f"PRC-{uuid.uuid4().hex[:12].upper()}",
                title=title,
                program_id=program.id,
                government_id=government_id,
                requesting_institution_id=institution.id,
                department_id=department_id if scope_level == "DEPARTMENT" else None,
                scope_level=scope_level,
                supplier_identity_id=supplier_identity_id,
                estimated_amount=estimate,
                currency=money_code,
                specification=specification,
                backend="INTERNAL_ABSTRACTION",
                external_market_status="UNAVAILABLE",
                policy_id=self._policy_row(session, context, policy_code).id
                if policy_code
                else None,
                status="authorized",
                authorized_by=context.principal_id,
                authorizing_identity_id=authority.decision.identity_id,
                authorizing_position_id=authority.decision.position_id,
                authority_classification=authority.classification,
                expenditure_authorization_id=expenditure_id,
                tenant_id=tenant,
            )
            session.add(row)
            decision = self._issue_decision(
                session,
                context,
                operation="economy.procurement.authorize",
                subject_kind="PROCUREMENT",
                subject_id=row.id,
                authority=authority,
                government_id=government_id,
                institution_id=institution.id,
                department_id=department_id,
                scope_level=scope_level,
                correlation_id=correlation_id,
            )
            row.decision_id = decision.id
            session.commit()
            session.refresh(row)
            payload = {
                "id": row.id,
                "reference": row.reference,
                "title": row.title,
                "program_id": row.program_id,
                "government_id": row.government_id,
                "requesting_institution_id": row.requesting_institution_id,
                "department_id": row.department_id,
                "scope_level": row.scope_level,
                "supplier_identity_id": row.supplier_identity_id,
                "estimated_amount": row.estimated_amount,
                "currency": row.currency,
                "backend": row.backend,
                "external_market_status": row.external_market_status,
                "policy_id": row.policy_id,
                "status": row.status,
                "authority_classification": row.authority_classification,
                "expenditure_authorization_id": row.expenditure_authorization_id,
                "decision_id": row.decision_id,
                "tenant_id": row.tenant_id,
            }
            decision_payload = self._decision_dict(decision)
        finally:
            session.close()
        trace = self._announce(
            context,
            action="economy.procurement.authorize",
            subject="amos_federation.economy.procurement_created",
            decision=decision_payload,
            payload=payload,
        )
        return {**payload, "decision": decision_payload, **trace}

    # ── R9-O: التنفيذُ بالنواة التنفيذية وحدَها ────────────────────────────

    def execute_economic_decision(
        self,
        context: AuthorizationContext,
        *,
        decision_reference: str,
        summary: str | None = None,
        max_steps: int = 8,
    ) -> dict[str, Any]:
        """نفِّذ قرارًا اقتصاديًّا مُصدَرًا عبر `ExecutiveCore` القائمة.

        القرارُ لا يُنفِّذ نفسَه، والتنفيذُ لا يُغيّر سلطتَه: تُعاد قراءةُ صفِّه،
        ويُشترط أن يكون `issued`، ويُسجَّل `task_id` من الطابور الحقيقيّ ومعرِّفُ
        عمليةٍ من جدول العمليات القائم. فمن يقرأ القرارَ منفَّذًا يجد مهمّةً
        ووثيقةَ عمليةٍ يفتحهما.
        """
        require_domain_permission(context, "economy.decision.execute", PERMISSIONS_ECONOMY_EXECUTE)
        tenant = self._tenant_of(context)
        session = self._session()
        try:
            decision = session.scalar(
                select(EconomicDecisionModel).where(
                    EconomicDecisionModel.reference == decision_reference,
                    EconomicDecisionModel.tenant_id == tenant,
                )
            )
            if decision is None:
                raise EconomicEntityNotFoundError(f"لا قرارَ اقتصاديًّا بمرجع '{decision_reference}'")
            require_tenant(context, decision.tenant_id)
            if decision.status != "issued":
                raise EconomicStateError(
                    f"لا يُنفَّذ قرارٌ حالتُه '{decision.status}' — التنفيذُ من `issued` فقط"
                )
            authority = require_economic_authority(
                session,
                context,
                decision.operation,
                target_level=decision.scope_level,
                institution_id=decision.institution_id,
                department_id=decision.department_id,
                tenant_id=tenant,
            )
            decision_id = decision.id
            scope_level = decision.scope_level
            institution_id = decision.institution_id
            department_id = decision.department_id
            operation = decision.operation
            subject_id = decision.subject_id
        finally:
            session.close()

        task, operation_record = self._execute_via_core(
            context,
            authority=authority,
            scope_level=scope_level,
            institution_id=institution_id,
            department_id=department_id,
            summary=summary or f"تنفيذُ قرارٍ اقتصاديّ: {operation}",
            detail={
                "decision_reference": decision_reference,
                "operation": operation,
                "subject_id": subject_id,
            },
            max_steps=max_steps,
        )

        session = self._session()
        try:
            decision = session.get(EconomicDecisionModel, decision_id)
            decision.status = "executed"
            decision.task_id = task["id"]
            decision.operation_id = operation_record["id"]
            decision.updated_at = _now()
            session.commit()
            session.refresh(decision)
            decision_payload = self._decision_dict(decision)
        finally:
            session.close()

        trace = self._announce(
            context,
            action="economy.decision.execute",
            subject="amos_federation.economy.decision_executed",
            decision=decision_payload,
            payload={"reference": decision_payload["reference"], "status": "executed"},
        )
        return {**decision_payload, "task": task, "operation": operation_record, **trace}

    # ── R9-N: قراءةُ الإسناد ──────────────────────────────────────────────

    def decision_file(
        self, context: AuthorizationContext, *, decision_reference: str
    ) -> dict[str, Any]:
        """أعِد ملفَّ قرارٍ اقتصاديٍّ بسلسلة إسنادِه وتصنيفِ اكتمالِها.

        `provenance` يُصنَّف `PROVEN` حين تكتمل الحلقات (هويةٌ · موظّفٌ · منصبٌ ·
        مِنحة)، و`PARTIAL` حين تنقص واحدةٌ منها، و`UNRESOLVED` حين لا هوية.
        ولا حلقةٌ تُملأ بقيمةٍ مُخترعةٍ لترقيةِ التصنيف.
        """
        require_domain_permission(context, "economy.decision.read", PERMISSIONS_ECONOMY_READ)
        tenant = self._tenant_of(context)
        session = self._session()
        try:
            decision = session.scalar(
                select(EconomicDecisionModel).where(
                    EconomicDecisionModel.reference == decision_reference,
                    EconomicDecisionModel.tenant_id == tenant,
                )
            )
            if decision is None:
                raise EconomicEntityNotFoundError(f"لا قرارَ اقتصاديًّا بمرجع '{decision_reference}'")
            require_tenant(context, decision.tenant_id)
            payload = self._decision_dict(decision)
            links = {
                "identity_id": decision.identity_id,
                "official_id": decision.official_id,
                "position_id": decision.position_id,
                "grant_id": decision.grant_id,
            }
        finally:
            session.close()
        missing = sorted(name for name, value in links.items() if not value)
        if not links["identity_id"]:
            provenance = "UNRESOLVED"
        elif missing:
            provenance = "PARTIAL"
        else:
            provenance = "PROVEN"
        return {
            **payload,
            "provenance": provenance,
            "provenance_missing_links": missing,
            "execution_evidence": {
                "task_id": payload["task_id"],
                "operation_id": payload["operation_id"],
                "transaction_reference": payload["transaction_reference"],
            },
        }

    def economic_registry(self, context: AuthorizationContext) -> dict[str, Any]:
        """أعِد إحصاءَ السجلّ الاقتصاديّ لهذا المستأجر — أعدادًا مقروءةً من الصفوف."""
        require_domain_permission(context, "economy.registry.read", PERMISSIONS_ECONOMY_READ)
        tenant = self._tenant_of(context)
        models = {
            "sectors": EconomicSectorModel,
            "categories": EconomicCategoryModel,
            "programs": EconomicProgramModel,
            "public_entities": PublicEconomicEntityModel,
            "policies": EconomicPolicyModel,
            "indicators": EconomicIndicatorDefinitionModel,
            "revenue_sources": RevenueSourceModel,
            "expenditure_authorizations": ExpenditureAuthorizationModel,
            "public_assets": PublicAssetModel,
            "public_liabilities": PublicLiabilityModel,
            "transfers": EconomicTransferModel,
            "procurements": ProcurementModel,
            "decisions": EconomicDecisionModel,
        }
        session = self._session()
        try:
            counts = {
                name: int(
                    session.scalar(
                        select(func.count()).select_from(model).where(model.tenant_id == tenant)
                    )
                    or 0
                )
                for name, model in models.items()
            }
            active_policies = int(
                session.scalar(
                    select(func.count())
                    .select_from(EconomicPolicyModel)
                    .where(
                        EconomicPolicyModel.tenant_id == tenant,
                        EconomicPolicyModel.status == "active",
                    )
                )
                or 0
            )
            executed_expenditures = int(
                session.scalar(
                    select(func.count())
                    .select_from(ExpenditureAuthorizationModel)
                    .where(
                        ExpenditureAuthorizationModel.tenant_id == tenant,
                        ExpenditureAuthorizationModel.status == "executed",
                    )
                )
                or 0
            )
        finally:
            session.close()
        return {
            "tenant_id": tenant,
            "counts": counts,
            "active_policies": active_policies,
            "executed_expenditures": executed_expenditures,
            "capabilities": {
                "revenue_collection": "UNAVAILABLE",
                "indicator_measurement": "UNAVAILABLE",
                "external_asset_ownership": "UNAVAILABLE",
                "external_liability_enforceability": "UNAVAILABLE",
                "external_procurement_market": "UNAVAILABLE",
                "treasury_execution": "REAL",
                "executive_core_execution": "REAL",
            },
        }

    def economy_health(self, context: AuthorizationContext) -> dict[str, Any]:
        """صحّةُ الطبقة الاقتصادية — تُقال بما يُقرأ لا بما يُرجى."""
        require_domain_permission(context, "economy.health.read", PERMISSIONS_ECONOMY_READ)
        registry = self.economic_registry(context)
        tenant = registry["tenant_id"]
        session = self._session()
        try:
            unresolved = int(
                session.scalar(
                    select(func.count())
                    .select_from(EconomicDecisionModel)
                    .where(
                        EconomicDecisionModel.tenant_id == tenant,
                        EconomicDecisionModel.identity_id.is_(None),
                    )
                )
                or 0
            )
            proven = int(
                session.scalar(
                    select(func.count())
                    .select_from(EconomicDecisionModel)
                    .where(
                        EconomicDecisionModel.tenant_id == tenant,
                        EconomicDecisionModel.provenance_class == "PROVEN",
                    )
                )
                or 0
            )
        finally:
            session.close()
        return {
            "tenant_id": tenant,
            "counts": registry["counts"],
            "decisions_without_identity": unresolved,
            "decisions_proven": proven,
            "capabilities": registry["capabilities"],
            "single_tenant": True,
        }


_NATIONAL_ECONOMY: NationalEconomy | None = None


def get_national_economy() -> NationalEconomy:
    """أعِد النسخةَ المشتركة من خدمة الدولة الاقتصادية."""
    global _NATIONAL_ECONOMY
    if _NATIONAL_ECONOMY is None:
        _NATIONAL_ECONOMY = NationalEconomy()
    return _NATIONAL_ECONOMY


def reset_national_economy() -> None:
    """أفرِغ النسخةَ المشتركة — للاختبارات لا للتشغيل."""
    global _NATIONAL_ECONOMY
    _NATIONAL_ECONOMY = None


__all__ = [
    "DOMAIN",
    "TASK_TYPE_ECONOMIC_DECISION",
    "DuplicateEconomicEntityError",
    "EconomicEntityNotFoundError",
    "EconomicStateError",
    "NationalEconomy",
    "get_national_economy",
    "reset_national_economy",
]
