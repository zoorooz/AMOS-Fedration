"""
AMOS-Federation Federal/State Integration — Domain Model
الهدف: حكومةٌ فدرالية وولاياتٌ ووحداتٌ ونطاقاتٌ وتفويضٌ صريح، بقيودٍ مفروضةٍ في القاعدة
النطاق: services/federal_state
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17 (R8-B · R8-C)

## ما كان موجودًا قبل هذه الوحدة (جردُ R8-A — مقيسٌ لا مُفترَض)

| ما وُجد | الملفّ | التصنيف | القرار |
| --- | --- | --- | --- |
| `federal_states` + `state_agent_assignments` + `state_messages` | `services/governance/state_runtime.py` | تنفيذيٌّ **غير كانونيّ**: خريطةُ تعريفٍ خاصّة (`StateBase`) ومحرّكٌ خاصّ، ومفتاحٌ أوّليّ `Integer autoincrement`، و**لا `tenant_id`**، و`role` نصٌّ في تعيين الوكلاء، ولا مفتاحَ أجنبيّ إلى مؤسسةٍ ولا إلى هوية | **يُترك عاملًا** كزمنِ تشغيل Phase-12، و**لا** يُعتبر سجلَّ الولايات الكانونيّ. يحرسه اختبارٌ ساكن يمنعه من الكتابة في جداول R8 |
| `state_institutions` + `state_departments` + `state_officials` | `services/state_registry/*` (R7-A) | تنفيذيٌّ قائم | **يُعاد استعماله**: لا سجلَّ مؤسساتٍ ثانيًا. والربطُ بالحكومة **جدولٌ رابط** لا عمودٌ جديد على جدولٍ قائم |
| الهوية الكانونية والمناصب والمِنَح وحلُّ السلطة | `services/national_registry/*` (R7-C) | تنفيذيٌّ قائم | **محرّكُ التخويل الوحيد**. R8 تُركّب فوقه قيودًا ولا تبني محرّكًا ثانيًا |
| `state_services` + `state_cases` + `state_decisions` | `services/government_services/*` | تنفيذيٌّ قائم | **يُعاد استعماله**: النطاقُ والإسنادُ جداولُ رابطة (`state_service_scopes` · `state_case_scopes`) لا أعمدةٌ جديدة |
| `tasks` + `ExecutiveCore` | `common/database.py` + `services/executive_core/*` | تنفيذيٌّ قائم | **المنفِّذُ الوحيد**. لا منفِّذَ حكوميّ موازٍ |
| الخزانة والقضاء | `state_treasury` (R7-B) · `federal_judiciary` (R7-D) | تنفيذيٌّ قائم | يُناديان كما هما بحدودهما |
| `common/durable_event_bus.py` + `common/event_bus.py` + `PersistentAuditStore` | القائم (R7-G) | تنفيذيٌّ قائم | **لا ناقلَ أحداثٍ جديد**: عقودٌ تُضاف إلى المفردة القائمة |

فما يُضاف هنا **سبعةُ جداولٍ جديدة بحتة**: لا `ALTER` على جدولٍ قائم، ولا عمودٌ
جديد على `state_institutions` ولا على `state_services` ولا على `state_cases`.
والصفوفُ السابقة لـR8 تبقى كما هي: مؤسسةٌ بلا صفِّ ربطٍ حكوميّ **لا حكومة لها**
في قراءة R8، وذلك يُقال `UNRESOLVED` ولا يُختلق.

## الاسم ليس هوية (R8-C)

كل كيانٍ هنا: مُعرِّفٌ مستقرّ بسابقةٍ دالّة · حالةٌ صريحة · طوابعُ زمنية · إسنادٌ
(مبدأً وهويةً) · `tenant_id`. و`code` فريدٌ داخل المستأجر — يمنع ولايتين برمزٍ
واحد — **ولكنه ليس مفتاحَ الربط**: كل رابطةٍ مفتاحٌ أجنبيّ إلى `id`.

## المستويات ليست سلّمًا (R8-D)

`SCOPE_LEVELS` هي `AUTHORITY_SCOPES` القائمة في R7-C **مستوردةً لا معادةَ
التعريف** — فلا مفردتان تتباعدان. والقواعد المفروضة في `scopes.py`:

| المستوى | يعمل على | لا يعمل على |
| --- | --- | --- |
| `FEDERAL` | الحكومة الفدرالية ومؤسساتها المُسمّاة | مؤسسةَ ولايةٍ لمجرّد أنها «أدنى» |
| `STATE` | مؤسسات **ولايته هو** | ولايةً أخرى · الحكومةَ الفدرالية |
| `INSTITUTION` | مؤسسته وإداراتها | مؤسسةً أخرى ولو في نفس الولاية |
| `DEPARTMENT` | إدارته المُسمّاة | مواردَ المؤسسة على مستواها |

## العلاقة ليست سلطة (R8-H)

`state_government_relations` تصف الواقع الإداريّ (`governs` · `belongs_to` ·
`administers` · `delegates` · `scopes` · `reports_to`) و**لا تمنح صلاحيةً واحدة**.
ما يمنح — بحدٍّ ومدّةٍ وقابليةِ نقض — هو `state_government_delegations` وحده،
ويُقرأ في `authority.py` كدليلٍ إضافيّ **بعد** قرار المحرّك الكانونيّ، فلا يوسّع
رفضًا إلى قبولٍ في نطاقٍ لم يُثبته.

## ما لا يُدَّعى في هذه الملفّة

1. **لا سجلَّ سكّانٍ ثانيًا**: `agent_population` (R4) و`state_identities` (R7-C)
   يُقرآن كما هما. ولا عمودَ «مواطَنة» يمنح سلطة.
2. **لا نفاذَ قانونيّ خارج النظام**: `state_government_operations` يربط قرارًا
   بمهمّةٍ في `tasks` أو بمرجع حركةٍ في الخزانة — أثرٌ داخليّ لا إلزامَ لجهةٍ خارجية.
3. **لا تعدّدَ مستأجرين**: `tenant_id` عمودٌ في كل جدول، والسياسةُ `SINGLE_TENANT`
   كما هي (R6.1). العمودُ حدٌّ لا وعدٌ بمنتجٍ متعدّد المستأجرين.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)

from amos_federation.common.database import Base

# === تسجيلُ جداول الأصل — قبل تعريف جداولنا بقصد ===
#
# مفاتيحُنا الأجنبية تشير إلى `state_institutions`/`state_departments` (R7-A) و
# `state_positions`/`state_identities` (R7-C) و`state_services`/`state_cases`/
# `state_decisions` (R7-A الوحدة 2) و`state_rulings` (R7-D) و`tasks` (common).
# و`create_all` ترفع `NoReferencedTableError` إن سُجِّل الفرعُ ولم يُسجَّل أصله.
#
# والترتيبُ مقصودٌ حرفًا كما في `federal_judiciary/models.py`: `state_registry`
# أوّلًا، ثمّ `state_treasury` (يلزمها `national_registry`)، ثمّ
# `national_registry`، ثمّ `government_services`، ثمّ `federal_judiciary`.
#
# لا تُرتّب هذه الأسطر آليًّا ولا تنقلها ولا تحذف واحدًا منها كـ«غير مستخدم».
# isort: off
from amos_federation.services.state_registry import models as _state_registry_models
from amos_federation.services.state_treasury import models as _state_treasury_models
from amos_federation.common.money import MoneyType
from amos_federation.services.national_registry import models as _national_registry_models
from amos_federation.services.government_services import models as _government_services_models
from amos_federation.services.federal_judiciary import models as _federal_judiciary_models

# isort: on

_PARENT_MODEL_MODULES = (
    _state_registry_models,
    _state_treasury_models,
    _national_registry_models,
    _government_services_models,
    _federal_judiciary_models,
)
"""الوحداتُ التي تُسجّل جداولَ الأصل. مرجعٌ صريحٌ يمنع حذفَ الاستيراد كـ«غير مستخدم»."""

# === مفردات الأنواع والحالات — مصدرٌ واحد للقيد وللتحقّق ===

#: مستوى الحكومة. الفدرالية أصلٌ بلا أصل، والولاية فرعٌ يلزمه أصلٌ فدراليّ —
#: قيدٌ في القاعدة لا تعليق. و**ليس سلّمَ سلطة**: انظر `scopes.py`.
GOVERNMENT_LEVELS: tuple[str, ...] = ("FEDERAL", "STATE")

GOVERNMENT_STATUSES: tuple[str, ...] = ("active", "suspended", "dissolved")

#: نطاقات السلطة — **مستوردةٌ** من R7-C لا معادةَ التعريف، فلا مفردتان تتباعدان.
SCOPE_LEVELS: tuple[str, ...] = _national_registry_models.AUTHORITY_SCOPES

#: العملياتُ القابلة للتفويض — مفردةُ R7-C نفسها. لا عمليةَ مُختَرعة في R8،
#: ولا `ALTER` على قيد `ck_state_authority_grants_operation` القائم.
DELEGABLE_OPERATIONS: tuple[str, ...] = _national_registry_models.GRANTABLE_OPERATIONS

#: أنواعُ أطراف العلاقة. الإدارةُ طرفٌ لأن `reports_to` بين إدارتين واقعٌ إداريّ.
RELATION_ENTITY_KINDS: tuple[str, ...] = ("GOVERNMENT", "INSTITUTION", "DEPARTMENT")

#: دلالاتُ العلاقة (R8-H). وصفيّةٌ بحتة: **لا واحدةَ منها تمنح صلاحية**.
RELATION_SEMANTICS: tuple[str, ...] = (
    "governs",
    "belongs_to",
    "administers",
    "delegates",
    "scopes",
    "reports_to",
)

RELATION_STATUSES: tuple[str, ...] = ("active", "revoked")

#: علاقةُ الوحدة بحكومتها. `belongs_to` انتماءٌ تنظيميّ، و`administers` إدارةٌ
#: تشغيلية — والاثنتان لا تمنحان سلطةً على شيء.
UNIT_RELATIONS: tuple[str, ...] = ("belongs_to", "administers")

DELEGATION_STATUSES: tuple[str, ...] = ("active", "revoked", "expired")

#: تصنيفُ الإسناد — نفسُ مفردة R7-C/R7-D. `PROVEN` يلزمه صفوفٌ كاملة.
PROVENANCE_CLASSIFICATIONS: tuple[str, ...] = ("PROVEN", "PARTIAL", "UNRESOLVED")

#: نوعُ العملية الحكومية: مهمّةٌ في `ExecutiveCore` أو حركةٌ في الخزانة. ولا ثالثَ:
#: لا منفِّذَ حكوميّ موازٍ (R8-G).
OPERATION_KINDS: tuple[str, ...] = ("TASK", "TREASURY")
OPERATION_STATUSES: tuple[str, ...] = ("requested", "executed", "failed")

#: جداول هذه الوحدة — تُقرأ في الهجرة وفي فحوص المخطَّط وفي تنظيف الاختبارات.
#: الترتيب من الأصل إلى الفرع: من يُشار إليه أوّلًا.
FEDERAL_STATE_TABLES: tuple[str, ...] = (
    "state_governments",
    "state_institution_governments",
    "state_government_relations",
    "state_government_delegations",
    "state_service_scopes",
    "state_case_scopes",
    "state_government_operations",
)


def _now() -> datetime:
    return datetime.now(UTC)


def _in_check(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ('" + "','".join(values) + "')"


class GovernmentModel(Base):
    """الحكومة — فدراليةٌ أو ولاية، في شجرةٍ واحدةٍ صريحة (R8-B · R8-C).

    كيانٌ واحدٌ بمستوىً صريح بدل كيانين: فالعلاقةُ «الحكومةُ الفدرالية ← ولاية»
    عمودُ أصلٍ مفروضٌ بقيد، لا اتفاقٌ بين جدولين. و`federal_states` القديم
    (Phase-12) لا يُلمَس ولا يُهجَّر — ولا يُعتبر كانونيًّا.

    والحالةُ لا تُهدم تاريخًا: `dissolved` صفٌّ بحالةٍ وسببٍ وطابع، لا `DELETE`.
    """

    __tablename__ = "state_governments"

    id = Column(String, primary_key=True)
    code = Column(String, nullable=False)
    name = Column(String, nullable=False)
    level = Column(String, nullable=False)
    parent_government_id = Column(
        String, ForeignKey("state_governments.id", ondelete="RESTRICT"), nullable=True
    )
    status = Column(String, nullable=False, default="active")
    status_reason = Column(Text, default="")
    tenant_id = Column(String, nullable=False, default="default")
    created_by = Column(String, nullable=False)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_state_governments_tenant_code"),
        CheckConstraint(_in_check("level", GOVERNMENT_LEVELS), name="ck_state_governments_level"),
        CheckConstraint(
            _in_check("status", GOVERNMENT_STATUSES), name="ck_state_governments_status"
        ),
        # الولايةُ يلزمها أصلٌ فدراليّ، والفدراليةُ لا أصلَ لها — فلا ولايةٌ
        # معلَّقةٌ في الهواء ولا حكومةٌ فدرالية تحت أخرى.
        CheckConstraint(
            "(level = 'FEDERAL' AND parent_government_id IS NULL)"
            " OR (level = 'STATE' AND parent_government_id IS NOT NULL)",
            name="ck_state_governments_parent",
        ),
        CheckConstraint(
            "parent_government_id IS NULL OR parent_government_id <> id",
            name="ck_state_governments_not_self_parent",
        ),
        Index("ix_state_governments_tenant_level", "tenant_id", "level"),
        Index("ix_state_governments_parent", "parent_government_id"),
    )


class InstitutionGovernmentModel(Base):
    """ربطُ مؤسسةٍ قائمةٍ بحكومتها — جدولٌ رابطٌ لا عمودٌ جديد (R8-B).

    الفريدُ على (مستأجر، مؤسسة) يجعل لكل مؤسسةٍ حكومةً واحدة: فلا مؤسسةٌ في
    ولايتين، ولا مؤسسةٌ فدراليةٌ وولائيةٌ معًا. والمؤسسةُ بلا صفٍّ هنا **لا حكومة
    لها** في قراءة R8 — وهو حالُ كل صفوف ما قبل R8، ويُقال `UNRESOLVED`.
    """

    __tablename__ = "state_institution_governments"

    id = Column(String, primary_key=True)
    government_id = Column(
        String, ForeignKey("state_governments.id", ondelete="RESTRICT"), nullable=False
    )
    institution_id = Column(
        String, ForeignKey("state_institutions.id", ondelete="RESTRICT"), nullable=False
    )
    relation = Column(String, nullable=False, default="belongs_to")
    assigned_by = Column(String, nullable=False)
    assigned_by_identity_id = Column(
        String, ForeignKey("state_identities.id", ondelete="RESTRICT"), nullable=True
    )
    tenant_id = Column(String, nullable=False, default="default")
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "institution_id", name="uq_state_institution_governments_institution"
        ),
        CheckConstraint(
            _in_check("relation", UNIT_RELATIONS), name="ck_state_institution_governments_relation"
        ),
        Index("ix_state_institution_governments_government", "government_id"),
    )


class GovernmentRelationModel(Base):
    """علاقةٌ حكوميةٌ صريحة — وصفٌ للواقع الإداريّ **بلا صلاحية** (R8-H).

    لا سطرَ في `authority.py` يقرأ هذا الجدول ليمنح شيئًا؛ يحرسه اختبار. وما
    يمنح — بحدٍّ ومدّةٍ ونقضٍ — هو `state_government_delegations` وحده.
    """

    __tablename__ = "state_government_relations"

    id = Column(String, primary_key=True)
    from_kind = Column(String, nullable=False)
    from_ref = Column(String, nullable=False)
    to_kind = Column(String, nullable=False)
    to_ref = Column(String, nullable=False)
    relation = Column(String, nullable=False)
    status = Column(String, nullable=False, default="active")
    note = Column(Text, default="")
    created_by = Column(String, nullable=False)
    created_by_identity_id = Column(
        String, ForeignKey("state_identities.id", ondelete="RESTRICT"), nullable=True
    )
    tenant_id = Column(String, nullable=False, default="default")
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)
    revoked_at = Column(DateTime, nullable=True)
    revoked_reason = Column(Text, default="")

    __table_args__ = (
        CheckConstraint(
            _in_check("from_kind", RELATION_ENTITY_KINDS),
            name="ck_state_government_relations_from_kind",
        ),
        CheckConstraint(
            _in_check("to_kind", RELATION_ENTITY_KINDS),
            name="ck_state_government_relations_to_kind",
        ),
        CheckConstraint(
            _in_check("relation", RELATION_SEMANTICS),
            name="ck_state_government_relations_relation",
        ),
        CheckConstraint(
            _in_check("status", RELATION_STATUSES), name="ck_state_government_relations_status"
        ),
        # لا علاقةَ كيانٍ بنفسه، والنقضُ يلزمه طابع — فلا «منقوضٌ» بلا وقت.
        CheckConstraint(
            "NOT (from_kind = to_kind AND from_ref = to_ref)",
            name="ck_state_government_relations_not_self",
        ),
        CheckConstraint(
            "(status = 'revoked' AND revoked_at IS NOT NULL)"
            " OR (status <> 'revoked' AND revoked_at IS NULL)",
            name="ck_state_government_relations_revoked_at",
        ),
        Index("ix_state_government_relations_from", "from_kind", "from_ref", "status"),
        Index("ix_state_government_relations_to", "to_kind", "to_ref", "status"),
    )


class GovernmentDelegationModel(Base):
    """تفويضٌ صريحٌ مُنطَّقٌ قابلٌ للنقض (R8-H).

    أربعةُ حدودٍ في القاعدة: عمليةٌ من مفردة R7-C حصرًا · هدفٌ واحدٌ لا اثنان
    (حكومةٌ أو مؤسسة) · لا تفويضَ لحكومةٍ لنفسها · والنقضُ يلزمه طابع. والفهرسان
    الجزئيّان يمنعان تفويضين نشطين لنفس (المُفوِّض، الهدف، العملية) — ويُبقيان
    المنقوضَ صفًّا في التاريخ.
    """

    __tablename__ = "state_government_delegations"

    id = Column(String, primary_key=True)
    from_government_id = Column(
        String, ForeignKey("state_governments.id", ondelete="RESTRICT"), nullable=False
    )
    to_government_id = Column(
        String, ForeignKey("state_governments.id", ondelete="RESTRICT"), nullable=True
    )
    to_institution_id = Column(
        String, ForeignKey("state_institutions.id", ondelete="RESTRICT"), nullable=True
    )
    operation = Column(String, nullable=False)
    scope = Column(String, nullable=False)
    #: حدٌّ أعلى اختياري للمبلغ الواحد — `NUMERIC(20,4)` (الهجرة 014 · Q-20).
    max_amount = Column(MoneyType, nullable=True)
    status = Column(String, nullable=False, default="active")
    reason = Column(Text, default="")
    granted_by = Column(String, nullable=False)
    granted_by_identity_id = Column(
        String, ForeignKey("state_identities.id", ondelete="RESTRICT"), nullable=True
    )
    tenant_id = Column(String, nullable=False, default="default")
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)
    expires_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    revoked_reason = Column(Text, default="")

    __table_args__ = (
        CheckConstraint(
            _in_check("operation", DELEGABLE_OPERATIONS),
            name="ck_state_government_delegations_operation",
        ),
        CheckConstraint(
            _in_check("scope", SCOPE_LEVELS), name="ck_state_government_delegations_scope"
        ),
        CheckConstraint(
            _in_check("status", DELEGATION_STATUSES),
            name="ck_state_government_delegations_status",
        ),
        CheckConstraint(
            "(to_government_id IS NOT NULL AND to_institution_id IS NULL)"
            " OR (to_government_id IS NULL AND to_institution_id IS NOT NULL)",
            name="ck_state_government_delegations_target",
        ),
        CheckConstraint(
            "to_government_id IS NULL OR to_government_id <> from_government_id",
            name="ck_state_government_delegations_not_self",
        ),
        CheckConstraint(
            "(status = 'revoked' AND revoked_at IS NOT NULL)"
            " OR (status <> 'revoked' AND revoked_at IS NULL)",
            name="ck_state_government_delegations_revoked_at",
        ),
        Index(
            "ix_state_government_delegations_lookup",
            "tenant_id",
            "from_government_id",
            "operation",
            "status",
        ),
    )


class ServiceScopeModel(Base):
    """نطاقُ خدمةٍ حكوميةٍ قائمة — ملكيةٌ صريحة لا مُستنتَجة (R8-E).

    فريدٌ على (مستأجر، خدمة): لكل خدمةٍ نطاقٌ واحد. والمستويان `FEDERAL`/`STATE`
    يلزمهما حكومةٌ مُسمّاة، و`DEPARTMENT` تلزمه إدارةٌ مُسمّاة — قيودٌ في القاعدة
    كي لا تكون «خدمةٌ فدرالية» صفةً بلا مرجع.
    """

    __tablename__ = "state_service_scopes"

    id = Column(String, primary_key=True)
    service_id = Column(
        String, ForeignKey("state_services.id", ondelete="RESTRICT"), nullable=False
    )
    level = Column(String, nullable=False)
    government_id = Column(
        String, ForeignKey("state_governments.id", ondelete="RESTRICT"), nullable=True
    )
    institution_id = Column(
        String, ForeignKey("state_institutions.id", ondelete="RESTRICT"), nullable=False
    )
    department_id = Column(
        String, ForeignKey("state_departments.id", ondelete="RESTRICT"), nullable=True
    )
    created_by = Column(String, nullable=False)
    created_by_identity_id = Column(
        String, ForeignKey("state_identities.id", ondelete="RESTRICT"), nullable=True
    )
    tenant_id = Column(String, nullable=False, default="default")
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    __table_args__ = (
        UniqueConstraint("tenant_id", "service_id", name="uq_state_service_scopes_service"),
        CheckConstraint(_in_check("level", SCOPE_LEVELS), name="ck_state_service_scopes_level"),
        CheckConstraint(
            "(level = 'DEPARTMENT' AND department_id IS NOT NULL)"
            " OR (level <> 'DEPARTMENT' AND department_id IS NULL)",
            name="ck_state_service_scopes_department",
        ),
        CheckConstraint(
            "(level IN ('FEDERAL','STATE') AND government_id IS NOT NULL)"
            " OR (level IN ('INSTITUTION','DEPARTMENT'))",
            name="ck_state_service_scopes_government",
        ),
        Index("ix_state_service_scopes_scope", "tenant_id", "level", "government_id"),
    )


class CaseScopeModel(Base):
    """إسنادُ قضيةٍ حكوميةٍ قائمة إلى سلسلتها ونطاقها (R8-F).

    فريدٌ على (مستأجر، قضية). و`PROVEN` **لا يُكتب بلا صفوف**: قيدٌ في القاعدة
    يلزمه منصبٌ وهويةٌ وحكومة. فمن لم تكتمل سلسلته يُكتب `PARTIAL` أو
    `UNRESOLVED` — إسنادٌ ناقصٌ مُعلَنٌ أصدقُ من إسنادٍ مُلفَّق.
    """

    __tablename__ = "state_case_scopes"

    id = Column(String, primary_key=True)
    case_id = Column(String, ForeignKey("state_cases.id", ondelete="RESTRICT"), nullable=False)
    level = Column(String, nullable=False)
    government_id = Column(
        String, ForeignKey("state_governments.id", ondelete="RESTRICT"), nullable=True
    )
    institution_id = Column(
        String, ForeignKey("state_institutions.id", ondelete="RESTRICT"), nullable=False
    )
    department_id = Column(
        String, ForeignKey("state_departments.id", ondelete="RESTRICT"), nullable=True
    )
    responsible_official_id = Column(
        String, ForeignKey("state_officials.id", ondelete="RESTRICT"), nullable=True
    )
    opened_by = Column(String, nullable=False)
    opened_by_identity_id = Column(
        String, ForeignKey("state_identities.id", ondelete="RESTRICT"), nullable=True
    )
    position_id = Column(
        String, ForeignKey("state_positions.id", ondelete="RESTRICT"), nullable=True
    )
    classification = Column(String, nullable=False)
    authority = Column(JSON, nullable=True)
    tenant_id = Column(String, nullable=False, default="default")
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    __table_args__ = (
        UniqueConstraint("tenant_id", "case_id", name="uq_state_case_scopes_case"),
        CheckConstraint(_in_check("level", SCOPE_LEVELS), name="ck_state_case_scopes_level"),
        CheckConstraint(
            _in_check("classification", PROVENANCE_CLASSIFICATIONS),
            name="ck_state_case_scopes_classification",
        ),
        CheckConstraint(
            "classification <> 'PROVEN'"
            " OR (position_id IS NOT NULL AND opened_by_identity_id IS NOT NULL"
            " AND government_id IS NOT NULL)",
            name="ck_state_case_scopes_proven_needs_chain",
        ),
        CheckConstraint(
            "(level = 'DEPARTMENT' AND department_id IS NOT NULL)"
            " OR (level <> 'DEPARTMENT' AND department_id IS NULL)",
            name="ck_state_case_scopes_department",
        ),
        Index("ix_state_case_scopes_scope", "tenant_id", "level", "government_id"),
    )


class GovernmentOperationModel(Base):
    """أثرُ عمليةٍ حكومية: قرارٌ → سلطة → تنفيذٌ (مهمّة أو خزانة) — R8-G.

    هذا الجدولُ هو ما يُجيب أسئلة R8-F السبعة في صفٍّ واحد: مَن (هوية) · بأيّ
    منصب · في أيّ مؤسسةٍ وحكومةٍ ومستوى · بأيّ سلطة (`authority` كما صدر) · على
    أيّ قرارٍ أو قضيةٍ أو حكم · بأيّ مهمّةٍ نُفِّذ · وأيّ أثرٍ ماليّ نتج.

    ولا يستورد هذا الجدولُ منفِّذًا: `task_id` مفتاحٌ أجنبيّ إلى `tasks.id`
    القائم، و`transaction_reference` مرجعُ حركةٍ كتبتها الخزانة. فلا منفِّذَ ثانٍ
    ولا جدولَ مهامٍّ حكوميّ موازٍ.
    """

    __tablename__ = "state_government_operations"

    id = Column(String, primary_key=True)
    kind = Column(String, nullable=False)
    level = Column(String, nullable=False)
    government_id = Column(
        String, ForeignKey("state_governments.id", ondelete="RESTRICT"), nullable=True
    )
    institution_id = Column(
        String, ForeignKey("state_institutions.id", ondelete="RESTRICT"), nullable=False
    )
    department_id = Column(
        String, ForeignKey("state_departments.id", ondelete="RESTRICT"), nullable=True
    )
    decision_id = Column(
        String, ForeignKey("state_decisions.id", ondelete="RESTRICT"), nullable=True
    )
    case_id = Column(String, ForeignKey("state_cases.id", ondelete="RESTRICT"), nullable=True)
    ruling_id = Column(String, ForeignKey("state_rulings.id", ondelete="RESTRICT"), nullable=True)
    identity_id = Column(
        String, ForeignKey("state_identities.id", ondelete="RESTRICT"), nullable=True
    )
    position_id = Column(
        String, ForeignKey("state_positions.id", ondelete="RESTRICT"), nullable=True
    )
    classification = Column(String, nullable=False)
    authority = Column(JSON, nullable=True)
    task_id = Column(String, ForeignKey("tasks.id", ondelete="RESTRICT"), nullable=True)
    transaction_reference = Column(String, nullable=True)
    status = Column(String, nullable=False, default="requested")
    detail = Column(Text, default="")
    requested_by = Column(String, nullable=False)
    tenant_id = Column(String, nullable=False, default="default")
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    __table_args__ = (
        CheckConstraint(
            _in_check("kind", OPERATION_KINDS), name="ck_state_government_operations_kind"
        ),
        CheckConstraint(
            _in_check("level", SCOPE_LEVELS), name="ck_state_government_operations_level"
        ),
        CheckConstraint(
            _in_check("status", OPERATION_STATUSES), name="ck_state_government_operations_status"
        ),
        CheckConstraint(
            _in_check("classification", PROVENANCE_CLASSIFICATIONS),
            name="ck_state_government_operations_classification",
        ),
        # «نُفِّذ» ادّعاءٌ يلزمه مرجعٌ: مهمّةٌ للمهمّة، وحركةٌ للخزانة. فلا صفَّ
        # تنفيذٍ ناجحٍ بلا ما يُثبته.
        CheckConstraint(
            "status <> 'executed' OR kind <> 'TASK' OR task_id IS NOT NULL",
            name="ck_state_government_operations_task_target",
        ),
        CheckConstraint(
            "status <> 'executed' OR kind <> 'TREASURY' OR transaction_reference IS NOT NULL",
            name="ck_state_government_operations_treasury_target",
        ),
        Index("ix_state_government_operations_scope", "tenant_id", "level", "government_id"),
        Index("ix_state_government_operations_decision", "decision_id"),
        Index("ix_state_government_operations_task", "task_id"),
    )


__all__ = [
    "DELEGATION_STATUSES",
    "DELEGABLE_OPERATIONS",
    "FEDERAL_STATE_TABLES",
    "GOVERNMENT_LEVELS",
    "GOVERNMENT_STATUSES",
    "OPERATION_KINDS",
    "OPERATION_STATUSES",
    "PROVENANCE_CLASSIFICATIONS",
    "RELATION_ENTITY_KINDS",
    "RELATION_SEMANTICS",
    "RELATION_STATUSES",
    "SCOPE_LEVELS",
    "UNIT_RELATIONS",
    "CaseScopeModel",
    "GovernmentDelegationModel",
    "GovernmentModel",
    "GovernmentOperationModel",
    "GovernmentRelationModel",
    "InstitutionGovernmentModel",
    "ServiceScopeModel",
]
