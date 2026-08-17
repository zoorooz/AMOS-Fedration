"""
AMOS-Federation Federal Judiciary — Domain Model
الهدف: محكمةٌ ونطاقٌ وقضيةٌ وأطرافٌ وأدلةٌ وإجراءاتٌ وحكمٌ وتنفيذٌ، بقيودٍ مفروضةٍ في القاعدة
النطاق: services/federal_judiciary
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17 (R7-D2)

## ما كان موجودًا قبل هذه الوحدة (مقيسٌ لا مُفترَض)

جردُ R7-D1 قرأ الشجرة كلّها وصنَّف كل ما يمسّ القانون والقضاء:

| ما وُجد | الملفّ | التصنيف | القرار |
| --- | --- | --- | --- |
| `JudicialBranch` + `CourtCaseModel` (`court_cases`) | `services/governance/federation.py` | تنفيذيٌّ ضعيف: القاضي **نصٌّ حرّ** (`rule(..., judge: str)`)، وخريطة تعريف خاصّة `_GovBase`، وأحداثٌ بلا عقد | يُترك عاملًا كتحكيمٍ غير رسميّ بين الوكلاء، و**لا** يُعتبر سلطةً قضائية. يحرسه اختبارٌ ساكن يمنعه من كتابة أحكامٍ كانونية |
| `state_cases` + `state_decisions` | `services/government_services/*` | تنفيذيٌّ مكتمل: قضايا **إدارية** (خدمةٌ حكومية ← مسؤول ← قرار) | نطاقٌ مختلف يُترك كما هو. القضية الإدارية ليست قضيةً قضائية |
| `state_institutions.kind` يحتوي `'court'` أصلًا، و`branch` يحتوي `'judicial'` | `services/state_registry/models.py` | تنفيذيٌّ قائم | **يُعاد استعماله**: المحكمة مؤسسةٌ في السجلّ، لا كيانٌ موازٍ |
| الهوية الكانونية والمناصب والتقليد وحلّ السلطة | `services/national_registry/*` (R7-C) | تنفيذيٌّ قائم | **يُعاد استعماله**: القاضي هويةٌ كانونية بمنصبٍ نشط، لا اسمٌ ولا دور |
| `institutions/court/**`, `federal/judicial/**`, `states/law/**`, `core/constitution/**` | ملفّات `md`/`json` | **مواصفاتٌ لا كود** | مرجعٌ للتصميم فقط، ولا يُدَّعى أنها تعمل |

فلا `Court system` ثالث هنا: المحكمة تُسجَّل مؤسسةً في `state_institutions`
(بالنوع `court` والفرع `judicial`)، والقاضي يُقلَّد بمنصبٍ في `state_positions`،
وما يُضاف في هذه الملفّة **جداولٌ جديدة بحتة** — لا `ALTER` على جدولٍ قائم، ولا
عمودٌ جديد على `state_cases` ولا على `court_cases`.

## الاسم ليس هوية (R7-D2)

كل كيانٍ هنا: مُعرِّفٌ مستقرّ (`id` بسابقةٍ دالّة) · حالةٌ صريحة · طوابعُ زمنية ·
إسنادٌ (`created_by` أو `submitted_by`/`requested_by` مبدأً وهويةً) · `tenant_id`
حيث يلزم الفصل. ولا يُستعمل اسمٌ ولا رمزٌ كمفتاحٍ للربط: الروابط كلّها مفاتيح
أجنبية إلى `id`.

## النطاق ليس سلّمًا (R7-D3)

`JURISDICTIONS` مجموعةٌ **فرعية** من `AUTHORITY_SCOPES` القائمة في R7-C:
`FEDERAL` · `STATE` · `INSTITUTION`. و`DEPARTMENT` مُستثنىً بقصد — لا محاكمَ
إدارية داخل إدارة. ولا ترقية ضمنية: محكمةٌ فدرالية **لا** تملك قضايا الولايات
تلقائيًّا، ومحكمةُ ولايةٍ **لا** تتجاوز إلى النطاق الفدرالي. المطابقة تُفرَض في
`jurisdiction.py` مساواةً صريحة، لا احتواءً.

## ما لا يُدَّعى في هذه الملفّة

1. **لا سلسلة حيازةٍ كاملة للأدلّة**: `state_case_evidence` يحمل بصمةً اختيارية
   (`content_hash`) ومُقدِّمًا وطابعًا وحالة. وهذا سجلُّ إيداعٍ مُدقَّق — وليس
   `chain-of-custody` بمعناه القانوني (لا حرزٌ مادّي، ولا سلسلة نقلٍ موقَّعة، ولا
   توقيعٌ تعمويّ). يُقال صريحًا في العمود وفي `docs/audit/R7D_FEDERAL_JUDICIARY.md`.
2. **لا نفاذٌ قانونيّ خارج النظام**: `state_ruling_enforcements` يربط الحكم بمهمّةٍ
   في `tasks` أو بحركةٍ في الخزانة. وهذا أثرٌ داخليّ، لا إلزامَ لجهةٍ خارجية.
3. **لا استئناف ولا إحالة**: `stage` عمودٌ موجود ويمنع حكمين لمرحلةٍ واحدة، لكن
   دورةَ الاستئناف نفسها **دَينٌ معلن** لم يُبنَ.
4. **لا ربطَ مفروضٍ بنصٍّ قانونيّ**: `state_case_claims.legal_basis_ref` نصٌّ
   حرّ بعلمٍ، و`legal_basis_verified` عمودٌ منطقيّ يقول هل تحقّق أحدٌ منه فعلًا —
   وقيمته الافتراضية `False` لأن سجلّ النصوص القانونية التنفيذي غير موجود.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from amos_federation.common.database import Base

# === تسجيلُ جداول الأصل — قبل تعريف جداولنا بقصد ===
#
# مفاتيحُنا الأجنبية تشير إلى `state_institutions` و`state_officials` (R7-A) و
# `state_positions` و`state_identities` (R7-C) و`tasks` (في `common.database`).
# و`create_all` ترفع `NoReferencedTableError` إن نُفِّذت وقد سُجِّل الفرعُ ولم
# يُسجَّل أصله.
#
# والموضعُ هنا — قبل تعريف جداولنا لا بعده — هو ما يجعل ذلك سالمًا: استيرادُ أيّ
# من هاتين الحزمتين ينفّذ `__init__` فيها ويمرّ بـ`executive_core` الذي يُنشئ
# الجداول وقت التحميل. فإن سبق استيرادُهما تعريفَنا، رأت `create_all` جداولَ
# الأصل وحدها فمرّت، ثم أُنشئت جداولُنا في أوّل `init_db` بعدها. ولو تأخّر
# الاستيرادُ إلى أسفل الملف لرأت `create_all` جداولَنا بلا أصولها فانكسرت.
#
# والترتيبُ الثلاثيّ مقصودٌ حرفًا: `state_registry` أولًا (فيها
# `state_institutions`)، ثمّ `state_treasury` (فيها `state_accounts` التي يشير
# إليها `state_authority_grants.account_id`)، ثمّ `national_registry` أخيرًا —
# فهي وحدَها تشير إلى الاثنتين قبلها، ولو سبقت إحداهما لانكسرت `create_all` على
# مفتاحٍ بلا هدف. و`state_treasury` ليست من مفاتيحنا نحن: نُحمّلها لأنّ تحميلَ
# `national_registry` يتطلّبها، وإصلاحُ ذلك في موضعه يفتح حلقةَ استيرادٍ أخرى.
#
# لا تُرتّب هذه الأسطر آليًّا ولا تنقلها ولا تحذف واحدًا منها كـ«غير مستخدم».
# isort: off
from amos_federation.services.state_registry import models as _state_registry_models
from amos_federation.services.state_treasury import models as _state_treasury_models
from amos_federation.services.national_registry import models as _national_registry_models

# isort: on

_PARENT_MODEL_MODULES = (
    _state_registry_models,
    _state_treasury_models,
    _national_registry_models,
)
"""الوحداتُ التي تُسجّل جداولَ الأصل. مرجعٌ صريحٌ يمنع حذفَ الاستيراد كـ«غير مستخدم»."""

# === مفردات الأنواع والحالات — مصدرٌ واحد للقيد وللتحقّق ===

#: نطاقات الاختصاص — مجموعةٌ فرعية من `AUTHORITY_SCOPES` (R7-C)، و`DEPARTMENT`
#: مُستثنىً بقصد: لا محكمةَ إدارةٍ داخل مؤسسة. **ليست سلّمًا**: لا ترقية ضمنية.
JURISDICTIONS: tuple[str, ...] = ("FEDERAL", "STATE", "INSTITUTION")

#: درجات المحكمة. وصفيّةٌ للعرض والتنظيم — و**ليست** مصدرًا للاختصاص: الاختصاص
#: من `jurisdiction` وحده، فلا `SUPREME` تُرقّي محكمةً إلى نطاقٍ لا تملكه.
COURT_LEVELS: tuple[str, ...] = ("FIRST_INSTANCE", "APPELLATE", "SUPREME", "SPECIALIZED")

COURT_STATUSES: tuple[str, ...] = ("active", "suspended", "dissolved")

#: حالات تقليد القاضي — مطابقةٌ لمفردة `state_officials.status` القائمة بقصد.
JUDGE_STATUSES: tuple[str, ...] = ("active", "suspended", "revoked")

#: دورة حياة القضية — تتابعٌ صريحٌ لا نصٌّ حرّ. خريطة الانتقالات في `docket.py`،
#: ولا انتقالَ قسريّ (`force`) في هذه الوحدة.
CASE_STATUSES: tuple[str, ...] = (
    "opened",
    "filed",
    "assigned",
    "hearing",
    "decided",
    "enforcement",
    "closed",
)

CASE_TYPES: tuple[str, ...] = ("CIVIL", "ADMINISTRATIVE", "CONSTITUTIONAL", "DISCIPLINARY")

#: أدوار الأطراف. كلٌّ منها يلزمه هويةٌ كانونية — لا نصَّ اسمٍ (R7-D6).
PARTY_ROLES: tuple[str, ...] = ("PLAINTIFF", "DEFENDANT", "INTERVENOR", "WITNESS", "COUNSEL")

CLAIM_TYPES: tuple[str, ...] = ("MONETARY", "DECLARATORY", "INJUNCTIVE", "APPEAL", "SANCTION")

#: نوع المرجع القانونيّ للمطالبة. `NONE` قيمةٌ صريحة — ولا مرجعَ مُختلق.
LEGAL_BASIS_KINDS: tuple[str, ...] = ("NONE", "CONSTITUTION_ARTICLE", "LEGISLATION", "DECREE", "POLICY")

EVIDENCE_TYPES: tuple[str, ...] = ("DOCUMENT", "RECORD", "TESTIMONY", "ARTIFACT", "AUDIT_ENTRY")
EVIDENCE_STATUSES: tuple[str, ...] = ("submitted", "admitted", "excluded", "withdrawn")

#: أنواع الإجراءات — بديلُ النصّ الحرّ (R7-D8). كل إجراءٍ صفٌّ بترتيبٍ وفاعلٍ وطابع.
PROCEEDING_TYPES: tuple[str, ...] = ("FILING", "HEARING", "MOTION", "REVIEW", "RULING")
PROCEEDING_STATUSES: tuple[str, ...] = ("recorded", "superseded")

#: مراحل الحكم. القيد الفريد على (قضية، مرحلة) للأحكام غير المُلغاة يمنع حكمين
#: لنفس المرحلة القضائية — وهو جوهر D10.
RULING_STAGES: tuple[str, ...] = ("FIRST_INSTANCE", "APPEAL", "FINAL")
RULING_DECISIONS: tuple[str, ...] = ("GRANTED", "DENIED", "PARTIAL", "DISMISSED")
RULING_STATUSES: tuple[str, ...] = ("issued", "enforced", "vacated")

#: نوع التنفيذ: مهمّةٌ في `ExecutiveCore` أو عملية خزانة. ولا منفِّذٌ ثالث.
ENFORCEMENT_KINDS: tuple[str, ...] = ("TASK", "TREASURY")
ENFORCEMENT_STATUSES: tuple[str, ...] = ("requested", "executed", "failed")

#: جداول هذه الوحدة — تُقرأ في الهجرة وفي فحوص المخطَّط وفي تنظيف الاختبارات.
#: الترتيب من الأصل إلى الفرع: من يُشار إليه أوّلًا.
FEDERAL_JUDICIARY_TABLES: tuple[str, ...] = (
    "state_courts",
    "state_court_judges",
    "state_legal_cases",
    "state_case_parties",
    "state_case_claims",
    "state_case_evidence",
    "state_case_proceedings",
    "state_rulings",
    "state_ruling_enforcements",
)


def _now() -> datetime:
    return datetime.now(UTC)


def _in_check(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ('" + "','".join(values) + "')"


class CourtModel(Base):
    """المحكمة — كيانٌ قضائيّ مربوطٌ بمؤسسةٍ قائمة في السجلّ (R7-D4).

    `institution_id` مفتاحٌ أجنبيّ إلى `state_institutions` وليس نصًّا: فالمحكمة
    **ليست** سجلًّا موازيًا للمؤسسات، بل قراءةٌ قضائية لمؤسسةٍ مُسجَّلة. ويفرض
    `registry.py` أن تلك المؤسسة فرعُها `judicial` وحالتها نشطة.
    """

    __tablename__ = "state_courts"

    id = Column(String, primary_key=True)
    code = Column(String, nullable=False)
    name = Column(String, nullable=False)
    level = Column(String, nullable=False)
    #: نطاق الاختصاص — يُطابق نطاق القضية **مساواةً**، لا احتواءً (R7-D3).
    jurisdiction = Column(String, nullable=False)
    institution_id = Column(
        String, ForeignKey("state_institutions.id", ondelete="RESTRICT"), nullable=False
    )
    status = Column(String, nullable=False, default="active")
    #: سببُ التعليق أو الحلّ — للتدقيق لا للتخويل.
    status_reason = Column(Text, default="")
    tenant_id = Column(String, nullable=False, default="default")
    created_by = Column(String, nullable=False)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    __table_args__ = (
        CheckConstraint(_in_check("level", COURT_LEVELS), name="ck_state_courts_level"),
        CheckConstraint(
            _in_check("jurisdiction", JURISDICTIONS), name="ck_state_courts_jurisdiction"
        ),
        CheckConstraint(_in_check("status", COURT_STATUSES), name="ck_state_courts_status"),
        UniqueConstraint("tenant_id", "code", name="uq_state_courts_tenant_code"),
        Index("ix_state_courts_jurisdiction", "tenant_id", "jurisdiction", "status"),
        Index("ix_state_courts_institution", "institution_id"),
    )


class CourtJudgeModel(Base):
    """تقليد القاضي — الحلقةُ التي تجعل «قاضٍ» أمرًا مقروءًا من القاعدة (R7-D4).

    السلسلة المفروضة: هوية كانونية (`identity_id`) ← سجلّ مسؤول (`official_id`)
    ← منصبٌ نشط (`position_id`) ← محكمة (`court_id`). و`role="judge"` **ليس** في
    هذا الجدول ولا يُفحَص في أيّ مكان من هذه الوحدة: الدور مفردةُ صلاحياتٍ عامّة،
    والقضاء صفُّ تقليدٍ في محكمةٍ بعينها.

    والفهرسُ الفريدُ **جزئيّ**: تقليدٌ نشطٌ واحد لكل (محكمة، مسؤول)، والصفوف
    المعزولة تبقى تاريخًا يُقرأ — فلا يُحذف تاريخٌ ليمرّ تقليدٌ جديد.
    """

    __tablename__ = "state_court_judges"

    id = Column(String, primary_key=True)
    court_id = Column(String, ForeignKey("state_courts.id", ondelete="RESTRICT"), nullable=False)
    official_id = Column(
        String, ForeignKey("state_officials.id", ondelete="RESTRICT"), nullable=False
    )
    position_id = Column(
        String, ForeignKey("state_positions.id", ondelete="RESTRICT"), nullable=False
    )
    identity_id = Column(
        String, ForeignKey("state_identities.id", ondelete="RESTRICT"), nullable=False
    )
    title = Column(String, nullable=False, default="قاضٍ")
    status = Column(String, nullable=False, default="active")
    appointed_by = Column(String, nullable=False)
    appointed_at = Column(DateTime, default=_now)
    revoked_at = Column(DateTime)
    revocation_reason = Column(Text, default="")
    tenant_id = Column(String, nullable=False, default="default")
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    __table_args__ = (
        CheckConstraint(_in_check("status", JUDGE_STATUSES), name="ck_state_court_judges_status"),
        CheckConstraint(
            "(status = 'revoked' AND revoked_at IS NOT NULL) "
            "OR (status <> 'revoked' AND revoked_at IS NULL)",
            name="ck_state_court_judges_revoked_at",
        ),
        Index(
            "uq_state_court_judges_active",
            "court_id",
            "official_id",
            unique=True,
            sqlite_where=Column("status") == "active",
            postgresql_where=Column("status") == "active",
        ),
        Index("ix_state_court_judges_identity", "identity_id", "status"),
        Index("ix_state_court_judges_court", "court_id", "status"),
    )


class LegalCaseModel(Base):
    """القضية القضائية — كيانٌ بدورة حياةٍ صريحة (R7-D5).

    ليست `state_cases`: ذاك سجلُّ **معاملةٍ إدارية** يلزمه `service_id` و`task_id`
    ويُقرِّره مسؤولٌ تنفيذيّ. وهذه قضيةٌ أمام محكمةٍ يفصلها قاضٍ بسلطةٍ قضائية،
    ولا مفتاحَ أجنبيًّا بينهما — ولو رُبِطا لَصار قرارُ موظَّفٍ حكمًا قضائيًّا.

    `assigned_judge_id` يشير إلى صفّ التقليد لا إلى الهوية مباشرةً: فالإسناد إلى
    «قاضٍ في هذه المحكمة»، لا إلى شخصٍ قد يكون قاضيًا في محكمةٍ أخرى.
    """

    __tablename__ = "state_legal_cases"

    id = Column(String, primary_key=True)
    reference = Column(String, nullable=False)
    court_id = Column(String, ForeignKey("state_courts.id", ondelete="RESTRICT"), nullable=False)
    #: نطاق القضية — يُنسَخ عند الفتح ويُطابَق مع نطاق المحكمة مساواةً.
    jurisdiction = Column(String, nullable=False)
    case_type = Column(String, nullable=False)
    subject = Column(Text, nullable=False)
    status = Column(String, nullable=False, default="opened")
    #: من فتح القضية: مبدأً **وهويةً كانونية** — لا اسمَ مقدِّمٍ حرًّا.
    opened_by_principal = Column(String, nullable=False)
    opened_by_identity_id = Column(
        String, ForeignKey("state_identities.id", ondelete="RESTRICT"), nullable=False
    )
    assigned_judge_id = Column(String, ForeignKey("state_court_judges.id", ondelete="RESTRICT"))
    assigned_at = Column(DateTime)
    opened_at = Column(DateTime, default=_now)
    closed_at = Column(DateTime)
    closure_reason = Column(Text, default="")
    tenant_id = Column(String, nullable=False, default="default")
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    __table_args__ = (
        CheckConstraint(_in_check("status", CASE_STATUSES), name="ck_state_legal_cases_status"),
        CheckConstraint(_in_check("case_type", CASE_TYPES), name="ck_state_legal_cases_type"),
        CheckConstraint(
            _in_check("jurisdiction", JURISDICTIONS), name="ck_state_legal_cases_jurisdiction"
        ),
        CheckConstraint(
            "(status = 'closed' AND closed_at IS NOT NULL) "
            "OR (status <> 'closed' AND closed_at IS NULL)",
            name="ck_state_legal_cases_closed_at",
        ),
        CheckConstraint(
            "(assigned_judge_id IS NULL AND assigned_at IS NULL) "
            "OR (assigned_judge_id IS NOT NULL AND assigned_at IS NOT NULL)",
            name="ck_state_legal_cases_assignment_pair",
        ),
        UniqueConstraint("tenant_id", "reference", name="uq_state_legal_cases_tenant_reference"),
        Index("ix_state_legal_cases_court", "court_id", "status"),
        Index("ix_state_legal_cases_judge", "assigned_judge_id", "status"),
    )


class CasePartyModel(Base):
    """طرفٌ في قضية — هويةٌ كانونية إلزامًا، لا نصُّ اسمٍ (R7-D6).

    `identity_id` مفتاحٌ أجنبيّ `NOT NULL`: فلا يستطيع مقدِّمُ الطلب أن يعرِّف
    خصمَه بنصّ. و`institution_id` اختياريٌّ يُضاف حين يكون الطرفُ مؤسسةً — وهو
    وصفٌ إضافيّ لا بديلٌ عن الهوية.
    """

    __tablename__ = "state_case_parties"

    id = Column(String, primary_key=True)
    case_id = Column(
        String, ForeignKey("state_legal_cases.id", ondelete="RESTRICT"), nullable=False
    )
    party_role = Column(String, nullable=False)
    identity_id = Column(
        String, ForeignKey("state_identities.id", ondelete="RESTRICT"), nullable=False
    )
    institution_id = Column(String, ForeignKey("state_institutions.id", ondelete="RESTRICT"))
    #: تسميةٌ للعرض فقط — **ليست** مُعرِّفًا ولا يُبحَث بها عن طرف.
    display_label = Column(String, default="")
    added_by = Column(String, nullable=False)
    tenant_id = Column(String, nullable=False, default="default")
    created_at = Column(DateTime, default=_now)

    __table_args__ = (
        CheckConstraint(_in_check("party_role", PARTY_ROLES), name="ck_state_case_parties_role"),
        UniqueConstraint(
            "case_id", "identity_id", "party_role", name="uq_state_case_parties_case_identity_role"
        ),
        Index("ix_state_case_parties_case", "case_id", "party_role"),
        Index("ix_state_case_parties_identity", "identity_id"),
    )


class CaseClaimModel(Base):
    """مطالبةٌ في قضية — تربط القضية بطرفٍ مُطالِبٍ وبمرجعٍ قانونيّ إن وُجد (R7-D6).

    `legal_basis_verified` عمودٌ صريحٌ يقول الحقّ: سجلّ النصوص القانونية التنفيذي
    غير موجود في هذه الجولة (`states/law/**` و`federal/legislative/laws` ملفّات
    توثيق)، فالمرجعُ نصٌّ **غير محقَّق** افتراضًا. ولو أُخفي هذا العمود لَبدا كل
    مرجعٍ ثابتًا وهو ليس كذلك.
    """

    __tablename__ = "state_case_claims"

    id = Column(String, primary_key=True)
    case_id = Column(
        String, ForeignKey("state_legal_cases.id", ondelete="RESTRICT"), nullable=False
    )
    claimant_party_id = Column(
        String, ForeignKey("state_case_parties.id", ondelete="RESTRICT"), nullable=False
    )
    claim_type = Column(String, nullable=False)
    statement = Column(Text, nullable=False)
    legal_basis_kind = Column(String, nullable=False, default="NONE")
    legal_basis_ref = Column(String, default="")
    legal_basis_verified = Column(Boolean, nullable=False, default=False)
    #: مبلغُ المطالبة نصًّا بأربع منازل — مفردةُ الخزانة نفسها (R7-B).
    amount = Column(String)
    filed_by = Column(String, nullable=False)
    tenant_id = Column(String, nullable=False, default="default")
    created_at = Column(DateTime, default=_now)

    __table_args__ = (
        CheckConstraint(_in_check("claim_type", CLAIM_TYPES), name="ck_state_case_claims_type"),
        CheckConstraint(
            _in_check("legal_basis_kind", LEGAL_BASIS_KINDS), name="ck_state_case_claims_basis_kind"
        ),
        CheckConstraint(
            "(legal_basis_kind = 'NONE' AND (legal_basis_ref = '' OR legal_basis_ref IS NULL)) "
            "OR (legal_basis_kind <> 'NONE' AND legal_basis_ref <> '')",
            name="ck_state_case_claims_basis_ref",
        ),
        CheckConstraint(
            "NOT legal_basis_verified OR legal_basis_kind <> 'NONE'",
            name="ck_state_case_claims_verified_needs_basis",
        ),
        CheckConstraint("length(statement) > 0", name="ck_state_case_claims_statement"),
        Index("ix_state_case_claims_case", "case_id", "claim_type"),
    )


class CaseEvidenceModel(Base):
    """دليلٌ مُودَع — سجلُّ إيداعٍ مُدقَّق، و**ليس** سلسلة حيازة (R7-D7).

    ما يُفرَض فعلًا: نوعٌ ومصدرٌ ومُقدِّمٌ (مبدأً وهويةً) وطابعٌ زمنيّ وحالة،
    وبصمةُ `sha256` بطولٍ مفروض حين تُقدَّم. وما **لا** يُدَّعى: حرزٌ مادّي، ولا
    سلسلةُ نقلٍ بين حائزين، ولا توقيعٌ تعمويّ، ولا منعُ تعديل المصدر الأصليّ.
    """

    __tablename__ = "state_case_evidence"

    id = Column(String, primary_key=True)
    case_id = Column(
        String, ForeignKey("state_legal_cases.id", ondelete="RESTRICT"), nullable=False
    )
    evidence_type = Column(String, nullable=False)
    #: مصدر الدليل: مرجعٌ نصّيّ إلى وثيقةٍ أو سجلٍّ أو أثرٍ مُدقَّق — لا محتوى.
    source = Column(Text, nullable=False)
    #: بصمةٌ اختيارية. `NULL` تعني «لم تُقدَّم بصمة» ولا تعني «سليم».
    content_hash = Column(String)
    fingerprint_algo = Column(String, default="")
    submitted_by_principal = Column(String, nullable=False)
    submitted_by_identity_id = Column(
        String, ForeignKey("state_identities.id", ondelete="RESTRICT"), nullable=False
    )
    submitted_at = Column(DateTime, default=_now)
    status = Column(String, nullable=False, default="submitted")
    status_reason = Column(Text, default="")
    tenant_id = Column(String, nullable=False, default="default")
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    __table_args__ = (
        CheckConstraint(
            _in_check("evidence_type", EVIDENCE_TYPES), name="ck_state_case_evidence_type"
        ),
        CheckConstraint(
            _in_check("status", EVIDENCE_STATUSES), name="ck_state_case_evidence_status"
        ),
        CheckConstraint("length(source) > 0", name="ck_state_case_evidence_source"),
        CheckConstraint(
            "content_hash IS NULL OR length(content_hash) = 64",
            name="ck_state_case_evidence_hash_length",
        ),
        CheckConstraint(
            "(content_hash IS NULL AND (fingerprint_algo = '' OR fingerprint_algo IS NULL)) "
            "OR (content_hash IS NOT NULL AND fingerprint_algo <> '')",
            name="ck_state_case_evidence_hash_algo",
        ),
        Index("ix_state_case_evidence_case", "case_id", "status"),
        Index("ix_state_case_evidence_hash", "content_hash"),
    )


class CaseProceedingModel(Base):
    """إجراءٌ في قضية — بديلُ النصّ الحرّ عن دورة الحياة (R7-D8).

    `sequence` عددٌ فريدٌ داخل القضية يجعل الترتيب مفروضًا في القاعدة لا مستنتجًا
    من طوابع زمنية قد تتساوى. و`record` حمولةُ `JSON` للتفاصيل — تُقرأ ولا تُخوِّل.
    """

    __tablename__ = "state_case_proceedings"

    id = Column(String, primary_key=True)
    case_id = Column(
        String, ForeignKey("state_legal_cases.id", ondelete="RESTRICT"), nullable=False
    )
    sequence = Column(Integer, nullable=False)
    proceeding_type = Column(String, nullable=False)
    actor_principal = Column(String, nullable=False)
    actor_identity_id = Column(
        String, ForeignKey("state_identities.id", ondelete="RESTRICT"), nullable=False
    )
    summary = Column(Text, nullable=False)
    record = Column(JSON, default=dict)
    status = Column(String, nullable=False, default="recorded")
    occurred_at = Column(DateTime, default=_now)
    tenant_id = Column(String, nullable=False, default="default")
    created_at = Column(DateTime, default=_now)

    __table_args__ = (
        CheckConstraint(
            _in_check("proceeding_type", PROCEEDING_TYPES), name="ck_state_case_proceedings_type"
        ),
        CheckConstraint(
            _in_check("status", PROCEEDING_STATUSES), name="ck_state_case_proceedings_status"
        ),
        CheckConstraint("sequence > 0", name="ck_state_case_proceedings_sequence"),
        UniqueConstraint("case_id", "sequence", name="uq_state_case_proceedings_case_sequence"),
        Index("ix_state_case_proceedings_case", "case_id", "proceeding_type"),
    )


class RulingModel(Base):
    """الحكم — قرارٌ قضائيّ مربوطٌ بقضيةٍ ومحكمةٍ وقاضٍ مُثبَتٍ (R7-D10).

    كل عمودٍ هنا مقصود: `case_id` يمنع حكمًا بلا قضية، و`judge_id` يشير إلى صفّ
    التقليد (لا إلى هويةٍ مجرَّدة) فيُثبت أنّ المُصدِر كان قاضيًا في هذه المحكمة،
    و`authority` يحمل قرارَ حلّ السلطة كما صدر ليُراجَع لاحقًا.

    والفهرسُ الفريدُ الجزئيّ على (قضية، مرحلة) للأحكام `issued`/`enforced` يمنع
    **حكمًا ثانيًا لنفس المرحلة القضائية**. والإلغاء (`vacated`) يُخرج الصفّ من
    الفهرس فيُمكن إصدارُ حكمٍ بديل — بأثرٍ مكتوبٍ لا بحذف.
    """

    __tablename__ = "state_rulings"

    id = Column(String, primary_key=True)
    case_id = Column(
        String, ForeignKey("state_legal_cases.id", ondelete="RESTRICT"), nullable=False
    )
    court_id = Column(String, ForeignKey("state_courts.id", ondelete="RESTRICT"), nullable=False)
    judge_id = Column(
        String, ForeignKey("state_court_judges.id", ondelete="RESTRICT"), nullable=False
    )
    judge_identity_id = Column(
        String, ForeignKey("state_identities.id", ondelete="RESTRICT"), nullable=False
    )
    stage = Column(String, nullable=False, default="FIRST_INSTANCE")
    decision = Column(String, nullable=False)
    #: منطوقُ الحكم نصًّا — يُقرأ للتدقيق، ولا يُشتقّ منه تنفيذٌ تلقائيّ.
    disposition = Column(Text, nullable=False)
    status = Column(String, nullable=False, default="issued")
    #: تصنيفُ قوّة الإسناد — من `PROVENANCE_CLASSES` (R7-C)، ولا يُرفَع بلا دليل.
    provenance_class = Column(String, nullable=False, default="PROVEN")
    #: قرارُ حلّ السلطة القضائية كما صدر: الهوية والمنصب والمحكمة والنطاق.
    authority = Column(JSON, default=dict)
    issued_by_principal = Column(String, nullable=False)
    issued_at = Column(DateTime, default=_now)
    vacated_at = Column(DateTime)
    vacatur_reason = Column(Text, default="")
    tenant_id = Column(String, nullable=False, default="default")
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    __table_args__ = (
        CheckConstraint(_in_check("stage", RULING_STAGES), name="ck_state_rulings_stage"),
        CheckConstraint(_in_check("decision", RULING_DECISIONS), name="ck_state_rulings_decision"),
        CheckConstraint(_in_check("status", RULING_STATUSES), name="ck_state_rulings_status"),
        CheckConstraint("length(disposition) > 0", name="ck_state_rulings_disposition"),
        CheckConstraint(
            "(status = 'vacated' AND vacated_at IS NOT NULL) "
            "OR (status <> 'vacated' AND vacated_at IS NULL)",
            name="ck_state_rulings_vacated_at",
        ),
        Index(
            "uq_state_rulings_case_stage_active",
            "case_id",
            "stage",
            unique=True,
            sqlite_where=Column("status").in_(("issued", "enforced")),
            postgresql_where=Column("status").in_(("issued", "enforced")),
        ),
        Index("ix_state_rulings_case", "case_id", "status"),
        Index("ix_state_rulings_judge", "judge_id", "status"),
    )


class RulingEnforcementModel(Base):
    """تنفيذُ حكم — أثرُ الإحالة إلى السلطة التنفيذية أو الخزانة (R7-D11/D12).

    الصفُّ **لا ينفِّذ**: هو سجلٌّ لِما نفَّذه `ExecutiveCore` (`task_id` مفتاحٌ
    أجنبيّ إلى `tasks`) أو ما سجّلته الخزانة (`transaction_reference`). فالمحكمة
    لا تشغّل مهمّةً بنفسها، ولا `CourtExecutor` في هذه الوحدة.
    """

    __tablename__ = "state_ruling_enforcements"

    id = Column(String, primary_key=True)
    ruling_id = Column(String, ForeignKey("state_rulings.id", ondelete="RESTRICT"), nullable=False)
    case_id = Column(
        String, ForeignKey("state_legal_cases.id", ondelete="RESTRICT"), nullable=False
    )
    kind = Column(String, nullable=False)
    #: مهمّةُ `ExecutiveCore` — مفتاحٌ أجنبيّ لا نصّ، فلا تنفيذَ مُدَّعى بلا مهمّة.
    task_id = Column(String, ForeignKey("tasks.id", ondelete="RESTRICT"))
    #: مرجعُ حركة الخزانة كما أعادته `disburse` — ولا حركةَ تُنشئها هذه الوحدة.
    transaction_reference = Column(String)
    status = Column(String, nullable=False, default="requested")
    detail = Column(Text, default="")
    requested_by_principal = Column(String, nullable=False)
    requested_by_identity_id = Column(
        String, ForeignKey("state_identities.id", ondelete="RESTRICT"), nullable=False
    )
    requested_at = Column(DateTime, default=_now)
    completed_at = Column(DateTime)
    tenant_id = Column(String, nullable=False, default="default")
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    __table_args__ = (
        CheckConstraint(_in_check("kind", ENFORCEMENT_KINDS), name="ck_state_ruling_enforcements_kind"),
        CheckConstraint(
            _in_check("status", ENFORCEMENT_STATUSES), name="ck_state_ruling_enforcements_status"
        ),
        CheckConstraint(
            "(kind = 'TASK' AND task_id IS NOT NULL) "
            "OR (kind = 'TREASURY' AND transaction_reference IS NOT NULL) "
            "OR status = 'failed'",
            name="ck_state_ruling_enforcements_target",
        ),
        Index("ix_state_ruling_enforcements_ruling", "ruling_id", "status"),
        Index("ix_state_ruling_enforcements_case", "case_id"),
    )


__all__ = [
    "CASE_STATUSES",
    "CASE_TYPES",
    "CLAIM_TYPES",
    "COURT_LEVELS",
    "COURT_STATUSES",
    "ENFORCEMENT_KINDS",
    "ENFORCEMENT_STATUSES",
    "EVIDENCE_STATUSES",
    "EVIDENCE_TYPES",
    "FEDERAL_JUDICIARY_TABLES",
    "JUDGE_STATUSES",
    "JURISDICTIONS",
    "LEGAL_BASIS_KINDS",
    "PARTY_ROLES",
    "PROCEEDING_STATUSES",
    "PROCEEDING_TYPES",
    "RULING_DECISIONS",
    "RULING_STAGES",
    "RULING_STATUSES",
    "CaseClaimModel",
    "CaseEvidenceModel",
    "CasePartyModel",
    "CaseProceedingModel",
    "CourtJudgeModel",
    "CourtModel",
    "LegalCaseModel",
    "RulingEnforcementModel",
    "RulingModel",
]
