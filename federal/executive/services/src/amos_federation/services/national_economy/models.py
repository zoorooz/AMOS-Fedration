"""
AMOS-Federation National Economy — Economic State Domain Model
الهدف: طبقةٌ اقتصاديةٌ **فوق** الخزانة القائمة — بلا دفترٍ ثانٍ ولا محرّك حركاتٍ ثانٍ
النطاق: services/national_economy
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17 (R9-B · R9-D … R9-K)

## ما كان موجودًا قبل هذه الوحدة (جردُ R9-A — مقيسٌ لا مُفترَض)

| ما وُجد | الملفّ · الهجرة | القرار في R9 |
| --- | --- | --- |
| الخزانة: خزائن وحسابات وميزانيات وتخصيصات وحركاتٌ ودفترُ قيود | `state_treasury/*` · 007 | **المنفِّذُ الماليّ الوحيد**. لا حركةَ مالٍ تُنشأ هنا |
| الهوية الكانونية والمناصب والمِنَح وحلُّ السلطة | `national_registry/*` · 008 | **محرّكُ التخويل الوحيد**. لا محرّكَ ثانيًا |
| الحكومة الفدرالية والولايات والنطاقات والتفويض | `federal_state/*` · 010 | **حدودُ السلطة الوحيدة**. لا شجرةَ حكوماتٍ ثانية |
| المؤسسات والإدارات والمسؤولون | `state_registry/*` · 006 | يُعاد استعماله بمفاتيحَ أجنبية |
| الخدمات والقضايا والقرارات | `government_services/*` | يُعاد استعماله؛ لا نظامَ قراراتٍ إداريّ ثانٍ |
| النواة التنفيذية والمهامّ | `executive_core/*` · `tasks` | **المنفِّذُ الوحيد**. لا `economic_executor` |
| ناقلُ الأحداث ومخزنُ التدقيق | `common/event_bus.py` · `PersistentAuditStore` | عقودٌ تُضاف إلى المفردة القائمة؛ لا ناقلَ ثانيًا |

فما تضيفه هذه الوحدة **ثلاثةَ عشرَ جدولًا جديدًا بحتًا** (الهجرة 011). ولا عمودَ
رصيدٍ في أيٍّ منها، ولا جدولَ حركاتٍ، ولا قيدَ دفتر: المالُ يُنفَّذ في
`state_transactions` وحدها، وصفوفُ هذه الطبقة تُشير إليه بـ`transaction_reference`.

## أين الحدُّ بين «إجازةٍ» و«حركة»

الإنفاقُ والتحويلُ هنا **إجازةٌ** لا نقدٌ متحرّك:

    برنامج → ميزانية → تخصيص → إجازةٌ مُخوَّلة → عمليةُ خزانة → حركة → تدقيق

الصفُّ في `state_expenditure_authorizations` يُخلَق بحالة `authorized` وبلا
`transaction_reference`؛ ولا يصير `executed` إلا بمرجعِ حركةٍ نفَّذتها الخزانة
وبأثرِ عمليةٍ في `state_government_operations`. وقيدُ `CHECK` يمنع العكس أيضًا:
مرجعُ حركةٍ على إجازةٍ لم تُنفَّذ يعني حركةً بلا إجازة.

## ما لا تدّعيه هذه الجداول

| الجدول | ما يُسجَّل | ما **لا** يُدَّعى |
| --- | --- | --- |
| `state_public_assets` | `SYSTEM_REGISTERED`: صفٌّ داخليّ في هذا النظام | ملكيةٌ قانونية في العالم الخارجيّ — `external_ownership_status` مقيَّدٌ بـ`UNAVAILABLE` |
| `state_public_liabilities` | دائنٌ **بهويةٍ كانونية** ومبلغٌ ومدّة | نفاذٌ قانونيّ خارجيّ — `external_enforceability` مقيَّدٌ بـ`UNAVAILABLE` |
| `state_revenue_sources` | تعريفُ مصدرِ الإيراد وأساسُه | تحصيلٌ فعليّ — `collection_status` مفردتُه `PARTIAL`/`UNAVAILABLE` فقط |
| `state_economic_indicator_definitions` | تعريفُ المؤشّر وطريقةُ قياسه | قياسٌ منفَّذ — المفردةُ **لا تحتوي** `REAL` |
| `state_procurements` | تجريدٌ خلفيٌّ داخليّ | سوقٌ أو مورّدٌ خارجيّ — `backend` مقيَّدٌ بـ`INTERNAL_ABSTRACTION` |

وهذه القيودُ في القاعدة لا في التعليق: لا يستطيع كودٌ لاحقٌ أن يرقّي تصنيفًا
بكتابةِ نصٍّ أفضل.

## ما لا يفرضه المخطَّط ويجب أن يفرضه الكود

1. أن العمليةَ المُخوَّلة هي العمليةُ المناسبة للجدول: القاعدةُ تعرف أن
   `operation` من المفردة، ولا تعرف أن `economy.grant.authorize` لا تُجيز دعمًا.
2. أن `authority_classification` يُنسَخ من `AuthorityDecision` حقيقيّ لا يُختَلق.
3. أن حدودَ الحكومة مُحترمة: `evaluate_boundary` في `federal_state/scopes.py`.
4. أن التخصيصَ والميزانيةَ يتبعان نفس مؤسسةِ الإجازة.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)

from ...common.database import Base
from ..national_registry.models import (
    AUTHORITY_SCOPES,
    ECONOMIC_OPERATIONS,
    PROVENANCE_CLASSES,
)

#: مستوياتُ النطاق — **مستوردةٌ** من R7-C لا معادةَ التعريف، فلا مفردتان تتباعدان.
SCOPE_LEVELS: tuple[str, ...] = AUTHORITY_SCOPES

#: مستويات القطاع: القطاعُ الاقتصاديّ يخصّ حكومةً، لا مؤسسةً ولا إدارة.
SECTOR_SCOPE_LEVELS: tuple[str, ...] = ("FEDERAL", "STATE")

#: حالاتُ السجلّ التعريفيّ (قطاع · فئة · مصدرُ إيراد).
REGISTRY_STATUSES: tuple[str, ...] = ("active", "suspended", "closed")

#: حالاتُ البرنامج — يبدأ مسوّدةً ولا يصير نافذًا بمجرّد وجوده.
PROGRAM_STATUSES: tuple[str, ...] = ("draft", "active", "suspended", "closed")

#: أنواعُ الكيان الاقتصاديّ العامّ.
PUBLIC_ENTITY_KINDS: tuple[str, ...] = (
    "STATE_OWNED_ENTERPRISE",
    "PUBLIC_FUND",
    "REGULATORY_BODY",
    "PUBLIC_UTILITY",
    "PUBLIC_AGENCY",
)

#: حالاتُ الكيان الاقتصاديّ العامّ.
PUBLIC_ENTITY_STATUSES: tuple[str, ...] = ("active", "suspended", "dissolved")

#: أنواعُ السياسة الاقتصادية. `MONETARY_ADVISORY` استشاريٌّ بقصد: لا مصرفَ
#: مركزيًّا في R9، فلا سياسةَ نقديةٍ نافذة تُدَّعى.
POLICY_TYPES: tuple[str, ...] = (
    "FISCAL",
    "MONETARY_ADVISORY",
    "TRADE",
    "SUBSIDY",
    "TAXATION",
    "PROCUREMENT",
    "SECTORAL",
)

#: حالاتُ السياسة. `draft` ≠ `active`: النفاذُ فعلٌ ثانٍ مُخوَّلٌ على حدة.
POLICY_STATUSES: tuple[str, ...] = ("draft", "active", "suspended", "expired", "revoked")

#: حالاتُ تعريف المؤشّر.
INDICATOR_STATUSES: tuple[str, ...] = ("active", "suspended", "retired")

#: حالةُ القياس — **لا `REAL`**: لا مؤشّرَ مقيسٌ فعلًا في R9.
MEASUREMENT_STATUSES: tuple[str, ...] = ("PARTIAL", "UNAVAILABLE")

#: أنواعُ الإيراد الحكوميّ (R9-E).
REVENUE_KINDS: tuple[str, ...] = (
    "TAX",
    "FEE",
    "LICENSE",
    "SERVICE_CHARGE",
    "FINE",
    "GRANT_RECEIVED",
    "OTHER",
)

#: حالةُ التحصيل — **لا `REAL`**: لا قنواتَ تحصيلٍ حقيقية في R9.
COLLECTION_STATUSES: tuple[str, ...] = ("PARTIAL", "UNAVAILABLE")

#: حالاتُ الإجازة المالية (إنفاقٌ · تحويل).
AUTHORIZATION_STATUSES: tuple[str, ...] = ("authorized", "executed", "failed", "reversed")

#: الحالاتُ التي تلزمها حركةُ خزانةٍ فعلية.
SETTLED_STATUSES: tuple[str, ...] = ("executed", "reversed")

#: أصنافُ الأصل العامّ.
ASSET_CLASSES: tuple[str, ...] = (
    "LAND",
    "BUILDING",
    "INFRASTRUCTURE",
    "EQUIPMENT",
    "FINANCIAL",
    "INTANGIBLE",
)

#: صنفُ التسجيل — قيمةٌ واحدة: صفٌّ في هذا النظام، لا ملكيةٌ في العالم.
ASSET_REGISTRATION_CLASS = "SYSTEM_REGISTERED"

#: حالةُ الملكية الخارجية — قيمةٌ واحدة: غيرُ متوفّرة.
EXTERNAL_OWNERSHIP_STATUS = "UNAVAILABLE"

#: حالاتُ الأصل العامّ.
ASSET_STATUSES: tuple[str, ...] = ("active", "suspended", "disposed")

#: أصنافُ الالتزام العامّ.
LIABILITY_CLASSES: tuple[str, ...] = (
    "BOND",
    "LOAN",
    "PAYABLE",
    "PENSION",
    "GUARANTEE",
    "OTHER",
)

#: حالاتُ الالتزام العامّ.
LIABILITY_STATUSES: tuple[str, ...] = ("outstanding", "settled", "written_off", "disputed")

#: النفاذُ القانونيّ الخارجيّ — قيمةٌ واحدة: غيرُ متوفّر.
EXTERNAL_ENFORCEABILITY = "UNAVAILABLE"

#: أنواعُ التحويل. مِنحةٌ ودعمٌ **منفصلان**، ولا تُستنتَج إجازةُ أحدهما من الآخر.
TRANSFER_KINDS: tuple[str, ...] = ("GRANT", "SUBSIDY")

#: الخلفيةُ الوحيدة للمشتريات: تجريدٌ داخليّ — لا سوقَ ولا مورّدَ خارجيّ.
PROCUREMENT_BACKEND = "INTERNAL_ABSTRACTION"

#: حالةُ السوق الخارجيّ — قيمةٌ واحدة: غيرُ متوفّرة.
EXTERNAL_MARKET_STATUS = "UNAVAILABLE"

#: حالاتُ المشتريات.
PROCUREMENT_STATUSES: tuple[str, ...] = ("authorized", "fulfilled", "cancelled")

#: أنواعُ موضوع القرار الاقتصاديّ.
DECISION_SUBJECT_KINDS: tuple[str, ...] = (
    "SECTOR",
    "CATEGORY",
    "PROGRAM",
    "ENTITY",
    "POLICY",
    "REVENUE_SOURCE",
    "EXPENDITURE",
    "TRANSFER",
    "ASSET",
    "LIABILITY",
    "PROCUREMENT",
)

#: حالاتُ القرار الاقتصاديّ.
DECISION_STATUSES: tuple[str, ...] = ("issued", "executed", "failed")

#: العملياتُ الاقتصادية — **مستوردةٌ** من المفردة الكانونية في R7-C.
ECONOMIC_DECISION_OPERATIONS: tuple[str, ...] = ECONOMIC_OPERATIONS

#: أقصى مبلغٍ مقبول — نفسُ حدّ `state_transactions` في R7-B، فلا إجازةٌ تتجاوز
#: ما تستطيع الخزانة تنفيذَه.
MAX_AMOUNT = 900000000000

#: جداولُ هذه الوحدة — تُقرأ في الهجرة 011 وفي فحوص المخطَّط.
NATIONAL_ECONOMY_TABLES: tuple[str, ...] = (
    "state_economic_sectors",
    "state_economic_categories",
    "state_economic_programs",
    "state_public_economic_entities",
    "state_economic_policies",
    "state_economic_indicator_definitions",
    "state_revenue_sources",
    "state_expenditure_authorizations",
    "state_public_assets",
    "state_public_liabilities",
    "state_economic_transfers",
    "state_procurements",
    "state_economic_decisions",
)


def _now() -> datetime:
    return datetime.now(UTC)


def _in_check(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ('" + "','".join(values) + "')"


def _eq_check(column: str, value: str) -> str:
    return f"{column} = '{value}'"


def _department_check(prefix: str) -> CheckConstraint:
    """مستوى الإدارة يلزمه إدارةٌ مُسمّاة — وإلّا فالنطاق ادّعاءٌ بلا هدف."""

    return CheckConstraint(
        "scope_level <> 'DEPARTMENT' OR department_id IS NOT NULL",
        name=f"ck_{prefix}_department",
    )


def _classification_check(prefix: str) -> CheckConstraint:
    return CheckConstraint(
        _in_check("authority_classification", PROVENANCE_CLASSES),
        name=f"ck_{prefix}_classification",
    )


class EconomicSectorModel(Base):
    """القطاعُ الاقتصاديّ — تصنيفٌ يملكه مستوى حكومةٍ لا مؤسسة."""

    __tablename__ = "state_economic_sectors"

    id = Column(String, primary_key=True)
    code = Column(String, nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, default="")
    government_id = Column(
        String, ForeignKey("state_governments.id", ondelete="RESTRICT"), nullable=False
    )
    scope_level = Column(String, nullable=False)
    status = Column(String, nullable=False, default="active")
    created_by = Column(String, nullable=False)
    created_by_identity_id = Column(String, ForeignKey("state_identities.id", ondelete="RESTRICT"))
    tenant_id = Column(String, nullable=False, default="default")
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_state_economic_sectors_tenant_code"),
        CheckConstraint(
            _in_check("scope_level", SECTOR_SCOPE_LEVELS),
            name="ck_state_economic_sectors_scope",
        ),
        CheckConstraint(
            _in_check("status", REGISTRY_STATUSES), name="ck_state_economic_sectors_status"
        ),
        CheckConstraint("length(code) > 0", name="ck_state_economic_sectors_code_present"),
        Index("ix_state_economic_sectors_tenant_gov", "tenant_id", "government_id", "status"),
    )


class EconomicCategoryModel(Base):
    """فئةٌ داخل قطاع — فريدةٌ داخل قطاعها لا داخل المستأجر كلِّه."""

    __tablename__ = "state_economic_categories"

    id = Column(String, primary_key=True)
    sector_id = Column(
        String, ForeignKey("state_economic_sectors.id", ondelete="RESTRICT"), nullable=False
    )
    code = Column(String, nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, default="")
    status = Column(String, nullable=False, default="active")
    created_by = Column(String, nullable=False)
    created_by_identity_id = Column(String, ForeignKey("state_identities.id", ondelete="RESTRICT"))
    tenant_id = Column(String, nullable=False, default="default")
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "sector_id", "code", name="uq_state_economic_categories_sector_code"
        ),
        CheckConstraint(
            _in_check("status", REGISTRY_STATUSES), name="ck_state_economic_categories_status"
        ),
        CheckConstraint("length(code) > 0", name="ck_state_economic_categories_code_present"),
        Index("ix_state_economic_categories_sector", "tenant_id", "sector_id", "status"),
    )


class EconomicProgramModel(Base):
    """برنامجٌ اقتصاديّ — وعاءُ الإنفاق والتحويل والمشتريات، بمالكٍ صريح."""

    __tablename__ = "state_economic_programs"

    id = Column(String, primary_key=True)
    code = Column(String, nullable=False)
    name = Column(String, nullable=False)
    purpose = Column(Text, nullable=False)
    sector_id = Column(
        String, ForeignKey("state_economic_sectors.id", ondelete="RESTRICT"), nullable=False
    )
    category_id = Column(String, ForeignKey("state_economic_categories.id", ondelete="RESTRICT"))
    government_id = Column(
        String, ForeignKey("state_governments.id", ondelete="RESTRICT"), nullable=False
    )
    institution_id = Column(
        String, ForeignKey("state_institutions.id", ondelete="RESTRICT"), nullable=False
    )
    department_id = Column(String, ForeignKey("state_departments.id", ondelete="RESTRICT"))
    scope_level = Column(String, nullable=False)
    status = Column(String, nullable=False, default="draft")
    policy_id = Column(String, ForeignKey("state_economic_policies.id", ondelete="RESTRICT"))
    created_by = Column(String, nullable=False)
    created_by_identity_id = Column(String, ForeignKey("state_identities.id", ondelete="RESTRICT"))
    created_by_position_id = Column(String, ForeignKey("state_positions.id", ondelete="RESTRICT"))
    authority_classification = Column(String, nullable=False)
    tenant_id = Column(String, nullable=False, default="default")
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_state_economic_programs_tenant_code"),
        CheckConstraint(
            _in_check("scope_level", SCOPE_LEVELS), name="ck_state_economic_programs_scope"
        ),
        CheckConstraint(
            _in_check("status", PROGRAM_STATUSES), name="ck_state_economic_programs_status"
        ),
        _department_check("state_economic_programs"),
        _classification_check("state_economic_programs"),
        CheckConstraint("length(purpose) > 0", name="ck_state_economic_programs_purpose_present"),
        Index("ix_state_economic_programs_owner", "tenant_id", "institution_id", "status"),
        Index("ix_state_economic_programs_sector", "tenant_id", "sector_id", "status"),
    )


class PublicEconomicEntityModel(Base):
    """كيانٌ اقتصاديٌّ عامّ — هويتُه كانونيةٌ في `state_identities` لا اسمُه هنا."""

    __tablename__ = "state_public_economic_entities"

    id = Column(String, primary_key=True)
    code = Column(String, nullable=False)
    name = Column(String, nullable=False)
    entity_kind = Column(String, nullable=False)
    identity_id = Column(
        String, ForeignKey("state_identities.id", ondelete="RESTRICT"), nullable=False
    )
    government_id = Column(
        String, ForeignKey("state_governments.id", ondelete="RESTRICT"), nullable=False
    )
    institution_id = Column(String, ForeignKey("state_institutions.id", ondelete="RESTRICT"))
    sector_id = Column(String, ForeignKey("state_economic_sectors.id", ondelete="RESTRICT"))
    status = Column(String, nullable=False, default="active")
    created_by = Column(String, nullable=False)
    created_by_identity_id = Column(String, ForeignKey("state_identities.id", ondelete="RESTRICT"))
    authority_classification = Column(String, nullable=False)
    tenant_id = Column(String, nullable=False, default="default")
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_state_public_economic_entities_tenant_code"),
        UniqueConstraint(
            "tenant_id", "identity_id", name="uq_state_public_economic_entities_identity"
        ),
        CheckConstraint(
            _in_check("entity_kind", PUBLIC_ENTITY_KINDS),
            name="ck_state_public_economic_entities_kind",
        ),
        CheckConstraint(
            _in_check("status", PUBLIC_ENTITY_STATUSES),
            name="ck_state_public_economic_entities_status",
        ),
        _classification_check("state_public_economic_entities"),
        Index("ix_state_public_economic_entities_gov", "tenant_id", "government_id", "status"),
    )


class EconomicPolicyModel(Base):
    """سياسةٌ اقتصادية — إصدارُها لا يجعلها نافذة، والنفاذُ يلزمه سلسلةُ إسناد."""

    __tablename__ = "state_economic_policies"

    id = Column(String, primary_key=True)
    code = Column(String, nullable=False)
    version = Column(Integer, nullable=False, default=1)
    title = Column(String, nullable=False)
    body = Column(Text, nullable=False)
    policy_type = Column(String, nullable=False)
    scope_level = Column(String, nullable=False)
    government_id = Column(
        String, ForeignKey("state_governments.id", ondelete="RESTRICT"), nullable=False
    )
    owner_institution_id = Column(
        String, ForeignKey("state_institutions.id", ondelete="RESTRICT"), nullable=False
    )
    department_id = Column(String, ForeignKey("state_departments.id", ondelete="RESTRICT"))
    sector_id = Column(String, ForeignKey("state_economic_sectors.id", ondelete="RESTRICT"))
    status = Column(String, nullable=False, default="draft")
    effective_from = Column(DateTime)
    effective_until = Column(DateTime)
    issued_by = Column(String, nullable=False)
    issuing_identity_id = Column(String, ForeignKey("state_identities.id", ondelete="RESTRICT"))
    issuing_position_id = Column(String, ForeignKey("state_positions.id", ondelete="RESTRICT"))
    decision_id = Column(String, ForeignKey("state_economic_decisions.id", ondelete="RESTRICT"))
    issue_operation_id = Column(
        String, ForeignKey("state_government_operations.id", ondelete="RESTRICT")
    )
    activation_operation_id = Column(
        String, ForeignKey("state_government_operations.id", ondelete="RESTRICT")
    )
    authority_classification = Column(String, nullable=False)
    tenant_id = Column(String, nullable=False, default="default")
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)
    revoked_at = Column(DateTime)
    revoked_reason = Column(Text, default="")

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "code", "version", name="uq_state_economic_policies_code_version"
        ),
        CheckConstraint(
            _in_check("policy_type", POLICY_TYPES), name="ck_state_economic_policies_type"
        ),
        CheckConstraint(
            _in_check("scope_level", SCOPE_LEVELS), name="ck_state_economic_policies_scope"
        ),
        CheckConstraint(
            _in_check("status", POLICY_STATUSES), name="ck_state_economic_policies_status"
        ),
        _department_check("state_economic_policies"),
        CheckConstraint("version >= 1", name="ck_state_economic_policies_version"),
        _classification_check("state_economic_policies"),
        CheckConstraint(
            "status <> 'active' OR ("
            "effective_from IS NOT NULL"
            " AND issuing_identity_id IS NOT NULL"
            " AND issuing_position_id IS NOT NULL"
            " AND activation_operation_id IS NOT NULL"
            ")",
            name="ck_state_economic_policies_active_needs_provenance",
        ),
        CheckConstraint(
            "effective_until IS NULL OR effective_from IS NULL"
            " OR effective_until > effective_from",
            name="ck_state_economic_policies_window",
        ),
        CheckConstraint(
            "(status = 'revoked' AND revoked_at IS NOT NULL)"
            " OR (status <> 'revoked' AND revoked_at IS NULL)",
            name="ck_state_economic_policies_revoked_at",
        ),
        Index("ix_state_economic_policies_owner", "tenant_id", "owner_institution_id", "status"),
        Index("ix_state_economic_policies_code", "tenant_id", "code", "version"),
    )


class EconomicIndicatorDefinitionModel(Base):
    """تعريفُ مؤشّرٍ اقتصاديّ — تعريفٌ فقط: لا قياسَ منفَّذًا يُدَّعى."""

    __tablename__ = "state_economic_indicator_definitions"

    id = Column(String, primary_key=True)
    code = Column(String, nullable=False)
    name = Column(String, nullable=False)
    unit = Column(String, nullable=False)
    method = Column(Text, nullable=False)
    scope_level = Column(String, nullable=False)
    government_id = Column(
        String, ForeignKey("state_governments.id", ondelete="RESTRICT"), nullable=False
    )
    sector_id = Column(String, ForeignKey("state_economic_sectors.id", ondelete="RESTRICT"))
    measurement_status = Column(String, nullable=False, default="UNAVAILABLE")
    status = Column(String, nullable=False, default="active")
    created_by = Column(String, nullable=False)
    created_by_identity_id = Column(String, ForeignKey("state_identities.id", ondelete="RESTRICT"))
    tenant_id = Column(String, nullable=False, default="default")
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "code", name="uq_state_economic_indicator_definitions_tenant_code"
        ),
        CheckConstraint(
            _in_check("scope_level", SCOPE_LEVELS),
            name="ck_state_economic_indicator_definitions_scope",
        ),
        CheckConstraint(
            _in_check("status", INDICATOR_STATUSES),
            name="ck_state_economic_indicator_definitions_status",
        ),
        CheckConstraint(
            _in_check("measurement_status", MEASUREMENT_STATUSES),
            name="ck_state_economic_indicator_definitions_measurement",
        ),
        CheckConstraint(
            "length(method) > 0", name="ck_state_economic_indicator_definitions_method_present"
        ),
        Index("ix_state_economic_indicator_definitions_gov", "tenant_id", "government_id"),
    )


class RevenueSourceModel(Base):
    """مصدرُ إيرادٍ حكوميّ — تعريفُه وأساسُه؛ والتحصيلُ الفعليّ غيرُ منفَّذ."""

    __tablename__ = "state_revenue_sources"

    id = Column(String, primary_key=True)
    code = Column(String, nullable=False)
    name = Column(String, nullable=False)
    revenue_kind = Column(String, nullable=False)
    basis = Column(Text, nullable=False)
    government_id = Column(
        String, ForeignKey("state_governments.id", ondelete="RESTRICT"), nullable=False
    )
    institution_id = Column(
        String, ForeignKey("state_institutions.id", ondelete="RESTRICT"), nullable=False
    )
    department_id = Column(String, ForeignKey("state_departments.id", ondelete="RESTRICT"))
    sector_id = Column(String, ForeignKey("state_economic_sectors.id", ondelete="RESTRICT"))
    program_id = Column(String, ForeignKey("state_economic_programs.id", ondelete="RESTRICT"))
    policy_id = Column(String, ForeignKey("state_economic_policies.id", ondelete="RESTRICT"))
    revenue_account_id = Column(String, ForeignKey("state_accounts.id", ondelete="RESTRICT"))
    collection_status = Column(String, nullable=False, default="UNAVAILABLE")
    status = Column(String, nullable=False, default="active")
    registered_by = Column(String, nullable=False)
    registered_by_identity_id = Column(
        String, ForeignKey("state_identities.id", ondelete="RESTRICT")
    )
    registered_by_position_id = Column(
        String, ForeignKey("state_positions.id", ondelete="RESTRICT")
    )
    authority_classification = Column(String, nullable=False)
    operation_id = Column(String, ForeignKey("state_government_operations.id", ondelete="RESTRICT"))
    tenant_id = Column(String, nullable=False, default="default")
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_state_revenue_sources_tenant_code"),
        CheckConstraint(
            _in_check("revenue_kind", REVENUE_KINDS), name="ck_state_revenue_sources_kind"
        ),
        CheckConstraint(
            _in_check("collection_status", COLLECTION_STATUSES),
            name="ck_state_revenue_sources_collection",
        ),
        CheckConstraint(
            _in_check("status", REGISTRY_STATUSES), name="ck_state_revenue_sources_status"
        ),
        _classification_check("state_revenue_sources"),
        CheckConstraint("length(basis) > 0", name="ck_state_revenue_sources_basis_present"),
        Index("ix_state_revenue_sources_owner", "tenant_id", "institution_id", "status"),
    )


class ExpenditureAuthorizationModel(Base):
    """إجازةُ إنفاق — تسبق الحركة ولا تحملها؛ ولا تصير منفَّذةً بلا مرجعِ خزانة."""

    __tablename__ = "state_expenditure_authorizations"

    id = Column(String, primary_key=True)
    reference = Column(String, nullable=False)
    program_id = Column(
        String, ForeignKey("state_economic_programs.id", ondelete="RESTRICT"), nullable=False
    )
    budget_id = Column(String, ForeignKey("state_budgets.id", ondelete="RESTRICT"), nullable=False)
    allocation_id = Column(
        String, ForeignKey("state_allocations.id", ondelete="RESTRICT"), nullable=False
    )
    government_id = Column(
        String, ForeignKey("state_governments.id", ondelete="RESTRICT"), nullable=False
    )
    institution_id = Column(
        String, ForeignKey("state_institutions.id", ondelete="RESTRICT"), nullable=False
    )
    department_id = Column(String, ForeignKey("state_departments.id", ondelete="RESTRICT"))
    scope_level = Column(String, nullable=False)
    amount = Column(Numeric(20, 4), nullable=False)
    currency = Column(String, nullable=False)
    purpose = Column(Text, nullable=False)
    policy_id = Column(String, ForeignKey("state_economic_policies.id", ondelete="RESTRICT"))
    status = Column(String, nullable=False, default="authorized")
    authorized_by = Column(String, nullable=False)
    authorizing_identity_id = Column(String, ForeignKey("state_identities.id", ondelete="RESTRICT"))
    authorizing_position_id = Column(String, ForeignKey("state_positions.id", ondelete="RESTRICT"))
    authority_classification = Column(String, nullable=False)
    grant_id = Column(String, ForeignKey("state_authority_grants.id", ondelete="RESTRICT"))
    decision_id = Column(String, ForeignKey("state_economic_decisions.id", ondelete="RESTRICT"))
    operation_id = Column(String, ForeignKey("state_government_operations.id", ondelete="RESTRICT"))
    transaction_reference = Column(String)
    correlation_id = Column(String)
    tenant_id = Column(String, nullable=False, default="default")
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "reference", name="uq_state_expenditure_authorizations_tenant_reference"
        ),
        CheckConstraint(
            _in_check("scope_level", SCOPE_LEVELS),
            name="ck_state_expenditure_authorizations_scope",
        ),
        CheckConstraint(
            _in_check("status", AUTHORIZATION_STATUSES),
            name="ck_state_expenditure_authorizations_status",
        ),
        CheckConstraint(
            f"amount > 0 AND amount <= {MAX_AMOUNT}",
            name="ck_state_expenditure_authorizations_amount",
        ),
        CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="ck_state_expenditure_authorizations_currency",
        ),
        _department_check("state_expenditure_authorizations"),
        _classification_check("state_expenditure_authorizations"),
        CheckConstraint(
            "(status IN ('executed','reversed') AND transaction_reference IS NOT NULL"
            " AND operation_id IS NOT NULL)"
            " OR (status NOT IN ('executed','reversed') AND transaction_reference IS NULL)",
            name="ck_state_expenditure_authorizations_executed",
        ),
        CheckConstraint(
            "length(purpose) > 0", name="ck_state_expenditure_authorizations_purpose_present"
        ),
        Index("ix_state_expenditure_authorizations_program", "tenant_id", "program_id", "status"),
        Index("ix_state_expenditure_authorizations_budget", "tenant_id", "budget_id", "status"),
    )


class PublicAssetModel(Base):
    """أصلٌ عامّ **مُسجَّلٌ في هذا النظام** — لا ملكيةَ قانونيةٍ خارجيةً يُدَّعى بها."""

    __tablename__ = "state_public_assets"

    id = Column(String, primary_key=True)
    code = Column(String, nullable=False)
    name = Column(String, nullable=False)
    asset_class = Column(String, nullable=False)
    description = Column(Text, default="")
    government_id = Column(
        String, ForeignKey("state_governments.id", ondelete="RESTRICT"), nullable=False
    )
    institution_id = Column(
        String, ForeignKey("state_institutions.id", ondelete="RESTRICT"), nullable=False
    )
    department_id = Column(String, ForeignKey("state_departments.id", ondelete="RESTRICT"))
    custodian_identity_id = Column(
        String, ForeignKey("state_identities.id", ondelete="RESTRICT"), nullable=False
    )
    registration_class = Column(String, nullable=False, default=ASSET_REGISTRATION_CLASS)
    external_ownership_status = Column(String, nullable=False, default=EXTERNAL_OWNERSHIP_STATUS)
    book_value = Column(Numeric(20, 4))
    currency = Column(String)
    status = Column(String, nullable=False, default="active")
    registered_by = Column(String, nullable=False)
    registered_by_identity_id = Column(
        String, ForeignKey("state_identities.id", ondelete="RESTRICT")
    )
    registered_by_position_id = Column(
        String, ForeignKey("state_positions.id", ondelete="RESTRICT")
    )
    authority_classification = Column(String, nullable=False)
    operation_id = Column(String, ForeignKey("state_government_operations.id", ondelete="RESTRICT"))
    tenant_id = Column(String, nullable=False, default="default")
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_state_public_assets_tenant_code"),
        CheckConstraint(
            _in_check("asset_class", ASSET_CLASSES), name="ck_state_public_assets_class"
        ),
        CheckConstraint(
            _eq_check("registration_class", ASSET_REGISTRATION_CLASS),
            name="ck_state_public_assets_registration",
        ),
        CheckConstraint(
            _eq_check("external_ownership_status", EXTERNAL_OWNERSHIP_STATUS),
            name="ck_state_public_assets_external_ownership",
        ),
        CheckConstraint(_in_check("status", ASSET_STATUSES), name="ck_state_public_assets_status"),
        CheckConstraint(
            f"book_value IS NULL OR (book_value >= 0 AND book_value <= {MAX_AMOUNT})",
            name="ck_state_public_assets_value",
        ),
        CheckConstraint(
            "currency IS NULL OR (length(currency) = 3 AND currency = upper(currency))",
            name="ck_state_public_assets_currency",
        ),
        CheckConstraint(
            "(book_value IS NULL AND currency IS NULL)"
            " OR (book_value IS NOT NULL AND currency IS NOT NULL)",
            name="ck_state_public_assets_value_currency",
        ),
        _classification_check("state_public_assets"),
        Index("ix_state_public_assets_owner", "tenant_id", "institution_id", "status"),
    )


class PublicLiabilityModel(Base):
    """التزامٌ عامّ — دائنٌ بهويةٍ كانونية، ولا نفاذَ قانونيًّا خارجيًّا يُدَّعى."""

    __tablename__ = "state_public_liabilities"

    id = Column(String, primary_key=True)
    code = Column(String, nullable=False)
    name = Column(String, nullable=False)
    liability_class = Column(String, nullable=False)
    description = Column(Text, default="")
    government_id = Column(
        String, ForeignKey("state_governments.id", ondelete="RESTRICT"), nullable=False
    )
    institution_id = Column(
        String, ForeignKey("state_institutions.id", ondelete="RESTRICT"), nullable=False
    )
    department_id = Column(String, ForeignKey("state_departments.id", ondelete="RESTRICT"))
    creditor_identity_id = Column(
        String, ForeignKey("state_identities.id", ondelete="RESTRICT"), nullable=False
    )
    principal_amount = Column(Numeric(20, 4), nullable=False)
    currency = Column(String, nullable=False)
    external_enforceability = Column(String, nullable=False, default=EXTERNAL_ENFORCEABILITY)
    due_at = Column(DateTime)
    status = Column(String, nullable=False, default="outstanding")
    registered_by = Column(String, nullable=False)
    registered_by_identity_id = Column(
        String, ForeignKey("state_identities.id", ondelete="RESTRICT")
    )
    registered_by_position_id = Column(
        String, ForeignKey("state_positions.id", ondelete="RESTRICT")
    )
    authority_classification = Column(String, nullable=False)
    operation_id = Column(String, ForeignKey("state_government_operations.id", ondelete="RESTRICT"))
    tenant_id = Column(String, nullable=False, default="default")
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_state_public_liabilities_tenant_code"),
        CheckConstraint(
            _in_check("liability_class", LIABILITY_CLASSES),
            name="ck_state_public_liabilities_class",
        ),
        CheckConstraint(
            _eq_check("external_enforceability", EXTERNAL_ENFORCEABILITY),
            name="ck_state_public_liabilities_enforceability",
        ),
        CheckConstraint(
            _in_check("status", LIABILITY_STATUSES), name="ck_state_public_liabilities_status"
        ),
        CheckConstraint(
            f"principal_amount > 0 AND principal_amount <= {MAX_AMOUNT}",
            name="ck_state_public_liabilities_amount",
        ),
        CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="ck_state_public_liabilities_currency",
        ),
        _classification_check("state_public_liabilities"),
        Index("ix_state_public_liabilities_owner", "tenant_id", "institution_id", "status"),
    )


class EconomicTransferModel(Base):
    """مِنحةٌ أو دعمٌ — إجازةُ تحويلٍ فوق الخزانة، لا محرّكُ نقلِ مالٍ بديل."""

    __tablename__ = "state_economic_transfers"

    id = Column(String, primary_key=True)
    reference = Column(String, nullable=False)
    transfer_kind = Column(String, nullable=False)
    program_id = Column(
        String, ForeignKey("state_economic_programs.id", ondelete="RESTRICT"), nullable=False
    )
    beneficiary_identity_id = Column(
        String, ForeignKey("state_identities.id", ondelete="RESTRICT"), nullable=False
    )
    beneficiary_entity_id = Column(
        String, ForeignKey("state_public_economic_entities.id", ondelete="RESTRICT")
    )
    government_id = Column(
        String, ForeignKey("state_governments.id", ondelete="RESTRICT"), nullable=False
    )
    institution_id = Column(
        String, ForeignKey("state_institutions.id", ondelete="RESTRICT"), nullable=False
    )
    department_id = Column(String, ForeignKey("state_departments.id", ondelete="RESTRICT"))
    scope_level = Column(String, nullable=False)
    budget_id = Column(String, ForeignKey("state_budgets.id", ondelete="RESTRICT"), nullable=False)
    allocation_id = Column(
        String, ForeignKey("state_allocations.id", ondelete="RESTRICT"), nullable=False
    )
    amount = Column(Numeric(20, 4), nullable=False)
    currency = Column(String, nullable=False)
    purpose = Column(Text, nullable=False)
    policy_id = Column(String, ForeignKey("state_economic_policies.id", ondelete="RESTRICT"))
    status = Column(String, nullable=False, default="authorized")
    authorized_by = Column(String, nullable=False)
    authorizing_identity_id = Column(String, ForeignKey("state_identities.id", ondelete="RESTRICT"))
    authorizing_position_id = Column(String, ForeignKey("state_positions.id", ondelete="RESTRICT"))
    authority_classification = Column(String, nullable=False)
    expenditure_authorization_id = Column(
        String, ForeignKey("state_expenditure_authorizations.id", ondelete="RESTRICT")
    )
    decision_id = Column(String, ForeignKey("state_economic_decisions.id", ondelete="RESTRICT"))
    operation_id = Column(String, ForeignKey("state_government_operations.id", ondelete="RESTRICT"))
    transaction_reference = Column(String)
    correlation_id = Column(String)
    tenant_id = Column(String, nullable=False, default="default")
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "reference", name="uq_state_economic_transfers_tenant_reference"
        ),
        CheckConstraint(
            _in_check("transfer_kind", TRANSFER_KINDS), name="ck_state_economic_transfers_kind"
        ),
        CheckConstraint(
            _in_check("scope_level", SCOPE_LEVELS), name="ck_state_economic_transfers_scope"
        ),
        CheckConstraint(
            _in_check("status", AUTHORIZATION_STATUSES),
            name="ck_state_economic_transfers_status",
        ),
        CheckConstraint(
            f"amount > 0 AND amount <= {MAX_AMOUNT}", name="ck_state_economic_transfers_amount"
        ),
        CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="ck_state_economic_transfers_currency",
        ),
        _department_check("state_economic_transfers"),
        _classification_check("state_economic_transfers"),
        CheckConstraint(
            "(status IN ('executed','reversed') AND transaction_reference IS NOT NULL"
            " AND operation_id IS NOT NULL)"
            " OR (status NOT IN ('executed','reversed') AND transaction_reference IS NULL)",
            name="ck_state_economic_transfers_executed",
        ),
        CheckConstraint("length(purpose) > 0", name="ck_state_economic_transfers_purpose_present"),
        Index("ix_state_economic_transfers_program", "tenant_id", "program_id", "status"),
        Index(
            "ix_state_economic_transfers_beneficiary",
            "tenant_id",
            "beneficiary_identity_id",
            "status",
        ),
    )


class ProcurementModel(Base):
    """مشترياتٌ — تجريدٌ خلفيٌّ داخليّ فقط: لا سوقَ ولا مورّدَ خارجيّ."""

    __tablename__ = "state_procurements"

    id = Column(String, primary_key=True)
    reference = Column(String, nullable=False)
    title = Column(String, nullable=False)
    program_id = Column(
        String, ForeignKey("state_economic_programs.id", ondelete="RESTRICT"), nullable=False
    )
    government_id = Column(
        String, ForeignKey("state_governments.id", ondelete="RESTRICT"), nullable=False
    )
    requesting_institution_id = Column(
        String, ForeignKey("state_institutions.id", ondelete="RESTRICT"), nullable=False
    )
    department_id = Column(String, ForeignKey("state_departments.id", ondelete="RESTRICT"))
    scope_level = Column(String, nullable=False)
    supplier_identity_id = Column(
        String, ForeignKey("state_identities.id", ondelete="RESTRICT"), nullable=False
    )
    estimated_amount = Column(Numeric(20, 4), nullable=False)
    currency = Column(String, nullable=False)
    specification = Column(Text, nullable=False)
    backend = Column(String, nullable=False, default=PROCUREMENT_BACKEND)
    external_market_status = Column(String, nullable=False, default=EXTERNAL_MARKET_STATUS)
    policy_id = Column(String, ForeignKey("state_economic_policies.id", ondelete="RESTRICT"))
    status = Column(String, nullable=False, default="authorized")
    authorized_by = Column(String, nullable=False)
    authorizing_identity_id = Column(String, ForeignKey("state_identities.id", ondelete="RESTRICT"))
    authorizing_position_id = Column(String, ForeignKey("state_positions.id", ondelete="RESTRICT"))
    authority_classification = Column(String, nullable=False)
    decision_id = Column(String, ForeignKey("state_economic_decisions.id", ondelete="RESTRICT"))
    expenditure_authorization_id = Column(
        String, ForeignKey("state_expenditure_authorizations.id", ondelete="RESTRICT")
    )
    operation_id = Column(String, ForeignKey("state_government_operations.id", ondelete="RESTRICT"))
    tenant_id = Column(String, nullable=False, default="default")
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    __table_args__ = (
        UniqueConstraint("tenant_id", "reference", name="uq_state_procurements_tenant_reference"),
        CheckConstraint(_in_check("scope_level", SCOPE_LEVELS), name="ck_state_procurements_scope"),
        CheckConstraint(
            _eq_check("backend", PROCUREMENT_BACKEND), name="ck_state_procurements_backend"
        ),
        CheckConstraint(
            _eq_check("external_market_status", EXTERNAL_MARKET_STATUS),
            name="ck_state_procurements_external_market",
        ),
        CheckConstraint(
            _in_check("status", PROCUREMENT_STATUSES), name="ck_state_procurements_status"
        ),
        CheckConstraint(
            f"estimated_amount > 0 AND estimated_amount <= {MAX_AMOUNT}",
            name="ck_state_procurements_amount",
        ),
        CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="ck_state_procurements_currency",
        ),
        _department_check("state_procurements"),
        _classification_check("state_procurements"),
        CheckConstraint(
            "length(specification) > 0", name="ck_state_procurements_specification_present"
        ),
        Index("ix_state_procurements_program", "tenant_id", "program_id", "status"),
    )


class EconomicDecisionModel(Base):
    """القرارُ الاقتصاديّ — أثرُ إسنادٍ لكلِّ فعل: من، بأيّ منصب، بأيّ مِنحة."""

    __tablename__ = "state_economic_decisions"

    id = Column(String, primary_key=True)
    reference = Column(String, nullable=False)
    operation = Column(String, nullable=False)
    subject_kind = Column(String, nullable=False)
    subject_id = Column(String, nullable=False)
    government_id = Column(
        String, ForeignKey("state_governments.id", ondelete="RESTRICT"), nullable=False
    )
    institution_id = Column(
        String, ForeignKey("state_institutions.id", ondelete="RESTRICT"), nullable=False
    )
    department_id = Column(String, ForeignKey("state_departments.id", ondelete="RESTRICT"))
    scope_level = Column(String, nullable=False)
    issued_by = Column(String, nullable=False)
    identity_id = Column(String, ForeignKey("state_identities.id", ondelete="RESTRICT"))
    official_id = Column(String, ForeignKey("state_officials.id", ondelete="RESTRICT"))
    position_id = Column(String, ForeignKey("state_positions.id", ondelete="RESTRICT"))
    grant_id = Column(String, ForeignKey("state_authority_grants.id", ondelete="RESTRICT"))
    delegation_id = Column(
        String, ForeignKey("state_government_delegations.id", ondelete="RESTRICT")
    )
    provenance_class = Column(String, nullable=False)
    authority_reason = Column(Text, default="")
    status = Column(String, nullable=False, default="issued")
    task_id = Column(String, ForeignKey("tasks.id", ondelete="RESTRICT"))
    transaction_reference = Column(String)
    operation_id = Column(String, ForeignKey("state_government_operations.id", ondelete="RESTRICT"))
    correlation_id = Column(String)
    audit_id = Column(String)
    event_id = Column(String)
    tenant_id = Column(String, nullable=False, default="default")
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "reference", name="uq_state_economic_decisions_tenant_reference"
        ),
        CheckConstraint(
            _in_check("operation", ECONOMIC_DECISION_OPERATIONS),
            name="ck_state_economic_decisions_operation",
        ),
        CheckConstraint(
            _in_check("subject_kind", DECISION_SUBJECT_KINDS),
            name="ck_state_economic_decisions_subject_kind",
        ),
        CheckConstraint(
            _in_check("scope_level", SCOPE_LEVELS), name="ck_state_economic_decisions_scope"
        ),
        CheckConstraint(
            _in_check("provenance_class", PROVENANCE_CLASSES),
            name="ck_state_economic_decisions_provenance",
        ),
        CheckConstraint(
            _in_check("status", DECISION_STATUSES), name="ck_state_economic_decisions_status"
        ),
        CheckConstraint(
            "provenance_class <> 'PROVEN' OR ("
            "identity_id IS NOT NULL"
            " AND official_id IS NOT NULL"
            " AND position_id IS NOT NULL"
            " AND grant_id IS NOT NULL"
            ")",
            name="ck_state_economic_decisions_proven_needs_chain",
        ),
        # «نُفِّذ» يلزمه دليلٌ من مسارٍ قائم: مهمّةٌ في النواة التنفيذية أو
        # حركةٌ في الخزانة (الهجرة 013). ولا ثالثَ لهما.
        CheckConstraint(
            "status <> 'executed' OR task_id IS NOT NULL OR transaction_reference IS NOT NULL",
            name="ck_state_economic_decisions_executed_needs_evidence",
        ),
        _department_check("state_economic_decisions"),
        Index("ix_state_economic_decisions_subject", "tenant_id", "subject_kind", "subject_id"),
        Index("ix_state_economic_decisions_operation", "tenant_id", "operation", "status"),
        Index("ix_state_economic_decisions_correlation", "tenant_id", "correlation_id"),
    )
