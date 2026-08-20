"""
AMOS-Federation National Registry — Canonical Identity Domain Model
الهدف: هويةٌ كانونية واحدة تُربط بها الجلسة والوكيل والمنصب، بمفاتيح أجنبية مفروضة
النطاق: services/national_registry
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17 (R7-C)

## ما كان موجودًا قبل هذه الوحدة (مقيسٌ لا مُفترَض)

| السجلّ | الجدول | ما يُعرِّفه | من يربطه بغيره |
| --- | --- | --- | --- |
| هوية الوكيل (R4) | `agents` | الوكيل التشغيلي: دور، صلاحيات، أدوات، دورة حياة | `state_officials.agent_id` |
| إسقاط سكّاني (R4) | `agent_population` | ملفّ تدريبي — **ليس** سجلّ هوية | نفس `agent_id` |
| الجلسات (R6) | `security_sessions` | `username` + `role_id` + `tenant_id` | **لا شيء** |
| المناصب (R7-A) | `state_officials` | تقليد وكيل منصبًا في مؤسسة | `agents.id` · `state_institutions.id` |
| القرارات (R7-A) | `state_decisions` | `decided_by_official_id` + `decided_by_principal` نصًّا | — |
| الحركات (R7-B) | `state_transactions` | `official_id` مفتاحٌ إلزامي | — |

والفراغ المقيس: **لا جدول يربط `security_sessions.username` بـ`agents.id`**. فمن
يملك `write:tasks` كان يستطيع إصدار قرار باسم أيّ مسؤول قائم في المؤسسة، وذلك
مُسجَّل صراحةً كدَين `PARTIAL` في `government_services/authorization.py` وفي
`docs/audit/R7_DOMAIN_BUILD.md`. R7-C تسدّ هذا الفراغ.

## لا سجلّ هوية ثالث

`agents` يبقى **السجلّ الكانوني للوكيل التشغيلي** كما وحّدته R4، ولم يُنشأ وكيل
جديد ولا نُسخت أعمدته. وما يُضاف هنا هو:

1. `state_identities` — الهوية الكانونية: كيانٌ مستقلٌّ عن الاسم وعن الدور.
2. جداول **ربط** لا جداول هوية موازية: مبدأ↔هوية، وكيل↔هوية، مسؤول↔هوية↔منصب.
3. `state_positions` — المنصب كمصدرٍ للسلطة المؤسسية، مستقلًّا عن سجلّ التقليد.
4. `state_authority_grants` — نطاق السلطة على عملية مُسمّاة وهدفٍ مُسمّى.
5. جدولا إسناد: `state_decision_provenance` و`state_transaction_authority`.

## لماذا جداول ربط لا أعمدة جديدة على الجداول القائمة

`state_officials` و`state_decisions` و`state_transactions` جداولٌ قائمة فيها صفوف.
و`Base.metadata.create_all` **لا تُضيف عمودًا إلى جدول موجود** — وهو ما دفعته R6.1
بهجرة `ALTER TABLE` يدوية لـ`security_sessions.tenant_id`. فكل ما تضيفه R7-C
جداولٌ جديدة بحتة: تطبيقها على قاعدة قائمة لا يحتاج `ALTER` ولا يفقد صفًّا،
والتاريخ يبقى كما هو.

## الهوية ليست اسمًا ولا دورًا

`state_identities` لا تحمل حقل اسم يُستعمل في التعريف: `label` وصفٌ للعرض
مُعلَنٌ أنه **ليس مُعرِّفًا** ولا يحمل قيدًا فريدًا. والتعريف يجري بمعرّف مستقرّ
(`id`) وبالروابط: `state_identity_principals.principal_id` فريدٌ في المستأجر،
و`state_identity_agents.agent_id` فريدٌ مطلقًا. أي أن «من هو؟» يُجاب من صفٍّ في
القاعدة لا من نصٍّ في طلب.

## الغموض يُسمَّى `unresolved` ولا يُدمَج

حين لا يُمكن إثبات أن مبدأً وهويةً واحد، **لا يُدمَجان**. تُنشأ هوية بحالة
`unresolved` أو يُرفَض الربط — والقرار مُسجَّل. ولا `auto-merge` في هذه الوحدة:
لا دالّة واحدة هنا تُوحّد هويتين بناءً على تشابه اسم أو دور.
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
from amos_federation.common.money import MoneyType

# === مفردات الأنواع والحالات — مصدرٌ واحد للقيد وللتحقّق ===

#: أنواع الهوية. قابلة للتوسيع بإضافة قيمة هنا وفي قيد `CHECK` في الهجرة معًا.
IDENTITY_TYPES: tuple[str, ...] = (
    "PERSON",
    "AGENT",
    "ORGANIZATION",
    "INSTITUTION",
    "SYSTEM",
)

#: حالات الهوية. `unresolved` حالةٌ صريحة لا فراغ: هويةٌ أُنشئت ولم يثبت مرجعها.
IDENTITY_STATUSES: tuple[str, ...] = ("active", "suspended", "retired", "unresolved")

#: نطاقات السلطة. **ليست سلّمًا**: لا واحدة منها تُرقّي إلى أخرى تلقائيًّا.
AUTHORITY_SCOPES: tuple[str, ...] = ("FEDERAL", "STATE", "INSTITUTION", "DEPARTMENT")

POSITION_STATUSES: tuple[str, ...] = ("active", "suspended", "abolished")
ASSIGNMENT_STATUSES: tuple[str, ...] = ("active", "revoked")
GRANT_STATUSES: tuple[str, ...] = ("active", "revoked")

#: تصنيف قوّة الإسناد — يُكتب مع كل قرار وكل حركة، ولا يُرفَع بلا دليل.
#:
#: `PROVEN`      : المبدأ ↔ هوية ↔ مسؤول ↔ منصب ↔ مؤسسة كلّها صفوفٌ مقروءة.
#: `PARTIAL`     : المسؤول والمؤسسة ثابتان، والهوية أو المنصب غير مربوط.
#: `UNRESOLVED`  : لا هوية كانونية للمبدأ — يُقال ولا يُختلق.
PROVENANCE_CLASSES: tuple[str, ...] = ("PROVEN", "PARTIAL", "UNRESOLVED")

#: عمليات الخزانة والقضاء — مفردة R7-B/R7-C/R7-D الأصلية. أسماؤها **هي نفسها**
#: أسماء العمليات المفحوصة في `state_treasury/authorization.py::
#: OFFICE_BOUND_OPERATIONS` و`gov.case.decide` في `government_services`.
#: لا اسم مُختَرع، ويحرس اختبارٌ ساكن هذا التطابق.
FISCAL_JUDICIAL_OPERATIONS: tuple[str, ...] = (
    "treasury.funding.post",
    "treasury.allocation.create",
    "treasury.disbursement.post",
    "treasury.transaction.reverse",
    "gov.case.decide",
)

#: عمليات الدولة الاقتصادية (R9). تُضاف إلى **المفردة الكانونية نفسها** ولا
#: تُنشئ مفردةً ثانية ولا جدول مِنَحٍ ثانيًا ولا محرّك تخويلٍ ثانيًا: كلُّ واحدة
#: منها تُحسَم بـ`resolve_authority` عبر `state_authority_grants` كسائر العمليات.
#:
#: - `economy.*.register`  : تسجيلُ كيانٍ اقتصاديّ في السجل الوطني.
#: - `economy.policy.*`    : إصدارُ سياسةٍ ثمّ تنفيذُها — فعلان منفصلان بقصد،
#:                           فالسياسةُ لا تصبح نافذةً بمجرّد وجود صفّها.
#: - `economy.expenditure.authorize` : إجازةُ إنفاقٍ **قبل** أيّ حركةِ خزانة.
#: - `economy.grant.authorize` / `economy.subsidy.authorize` : منفصلتان لأن
#:   إجازة المِنح ليست إجازة الدعم، ولا تُستنتَج إحداهما من الأخرى.
ECONOMIC_OPERATIONS: tuple[str, ...] = (
    "economy.entity.register",
    "economy.program.create",
    "economy.policy.issue",
    "economy.policy.activate",
    "economy.revenue.register",
    "economy.expenditure.authorize",
    "economy.grant.authorize",
    "economy.subsidy.authorize",
    "economy.asset.register",
    "economy.liability.register",
    "economy.procurement.authorize",
)

#: العمليات التي تُمنَح لمنصب — مفردةٌ **واحدة** مغلقة، مصدرُ قيود `CHECK` في
#: `state_authority_grants` و`state_transaction_authority` و
#: `state_government_delegations` جميعًا. توسيعُها في R9 كان بإضافة أسماءٍ لا
#: بإنشاء مفردةٍ موازية، فبقي المحرّك الكانونيّ واحدًا.
GRANTABLE_OPERATIONS: tuple[str, ...] = FISCAL_JUDICIAL_OPERATIONS + ECONOMIC_OPERATIONS

#: جداول هذه الوحدة — تُقرأ في الهجرة وفي فحوص المخطَّط.
NATIONAL_REGISTRY_TABLES: tuple[str, ...] = (
    "state_identities",
    "state_identity_principals",
    "state_identity_agents",
    "state_positions",
    "state_official_positions",
    "state_authority_grants",
    "state_decision_provenance",
    "state_transaction_authority",
)


def _now() -> datetime:
    return datetime.now(UTC)


def _in_check(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ('" + "','".join(values) + "')"


class IdentityModel(Base):
    """الهوية الكانونية — كيانٌ مستقرٌّ لا يُعرَّف باسمٍ ولا بدور."""

    __tablename__ = "state_identities"

    id = Column(String, primary_key=True)
    identity_type = Column(String, nullable=False)
    status = Column(String, nullable=False, default="active")
    #: وصفٌ للعرض فقط — **ليس مُعرِّفًا**، فلا قيد فريد عليه بقصد.
    label = Column(String, default="")
    #: سبب الحالة (تعليق، تقاعد، أو غموض غير محلول) — نصٌّ للتدقيق لا للتخويل.
    status_reason = Column(Text, default="")
    tenant_id = Column(String, nullable=False, default="default")
    created_by = Column(String, nullable=False)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    __table_args__ = (
        CheckConstraint(
            _in_check("identity_type", IDENTITY_TYPES), name="ck_state_identities_type"
        ),
        CheckConstraint(_in_check("status", IDENTITY_STATUSES), name="ck_state_identities_status"),
        Index("ix_state_identities_tenant_type", "tenant_id", "identity_type", "status"),
    )


class IdentityPrincipalModel(Base):
    """ربط المبدأ المُتحقَّق منه بهويته الكانونية — R7-C3.

    `principal_id` هو `security_sessions.username` نفسه (أو `sub` في رمز موقَّع).
    ولا مفتاح أجنبي إليه: `security_sessions` يسكن `SecurityBase` — خريطة تعريف
    منفصلة عن `Base` — فلا يمكن فرض مفتاح أجنبي بينهما في هذه الطبقة، ويُقال ذلك
    ولا يُموَّه. والقيد المفروض فعلًا: `UNIQUE (tenant_id, principal_id)` — أي أن
    **مبدأً واحدًا لا يحمل هويتين** في مستأجر واحد.
    """

    __tablename__ = "state_identity_principals"

    id = Column(String, primary_key=True)
    principal_id = Column(String, nullable=False)
    identity_id = Column(
        String, ForeignKey("state_identities.id", ondelete="RESTRICT"), nullable=False
    )
    #: من أين ثبت الربط: `SESSION_VERIFIED` أو `TOKEN_VERIFIED` أو ربطٌ إداري.
    binding_source = Column(String, nullable=False, default="ADMIN")
    tenant_id = Column(String, nullable=False, default="default")
    linked_by = Column(String, nullable=False)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "principal_id", name="uq_state_identity_principals_tenant_principal"
        ),
        Index("ix_state_identity_principals_identity", "identity_id"),
    )


class IdentityAgentModel(Base):
    """ربط الوكيل التشغيلي (R3/R4) بهويته الكانونية — R7-C5.

    الوكيل **لا يُدمَج** في جدول الهوية: `agents` يبقى كيان التشغيل بدورة حياته
    وصلاحياته وأدواته، و`state_identities` هوية كانونية. والعلاقة واحدٌ لواحد
    مفروضةٌ في القاعدة من الطرفين: `UNIQUE (agent_id)` و`UNIQUE (identity_id)`.
    """

    __tablename__ = "state_identity_agents"

    id = Column(String, primary_key=True)
    agent_id = Column(String, ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False)
    identity_id = Column(
        String, ForeignKey("state_identities.id", ondelete="RESTRICT"), nullable=False
    )
    tenant_id = Column(String, nullable=False, default="default")
    linked_by = Column(String, nullable=False)
    created_at = Column(DateTime, default=_now)

    __table_args__ = (
        UniqueConstraint("agent_id", name="uq_state_identity_agents_agent"),
        UniqueConstraint("identity_id", name="uq_state_identity_agents_identity"),
    )


class PositionModel(Base):
    """المنصب — مصدر السلطة المؤسسية، مستقلٌّ عن شاغله.

    وجودُ المنصب لا يعني وجود شاغل، وعزلُ الشاغل لا يُلغي المنصب. ولهذا فُصِل عن
    `state_officials`: ذاك سجلّ **تقليد** (من يشغل ماذا ومتى)، وهذا سجلّ **سلطة**.
    """

    __tablename__ = "state_positions"

    id = Column(String, primary_key=True)
    code = Column(String, nullable=False)
    title = Column(String, nullable=False)
    institution_id = Column(
        String, ForeignKey("state_institutions.id", ondelete="RESTRICT"), nullable=False
    )
    department_id = Column(
        String, ForeignKey("state_departments.id", ondelete="RESTRICT"), nullable=True
    )
    #: نطاق سلطة المنصب — ولا يُرقّى تلقائيًّا إلى نطاق آخر (R7-C7).
    authority_scope = Column(String, nullable=False)
    status = Column(String, nullable=False, default="active")
    mandate = Column(Text, default="")
    tenant_id = Column(String, nullable=False, default="default")
    created_by = Column(String, nullable=False)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    __table_args__ = (
        UniqueConstraint("institution_id", "code", name="uq_state_positions_institution_code"),
        CheckConstraint(
            _in_check("authority_scope", AUTHORITY_SCOPES), name="ck_state_positions_scope"
        ),
        CheckConstraint(_in_check("status", POSITION_STATUSES), name="ck_state_positions_status"),
        #: نطاق الإدارة يلزمه إدارة مُسمّاة، وما فوقها لا يحمل إدارة — القيد في
        #: القاعدة لا في التعليق، فلا منصبٌ «إداريّ» بلا إدارة يمرّ.
        CheckConstraint(
            "(authority_scope = 'DEPARTMENT' AND department_id IS NOT NULL) "
            "OR (authority_scope <> 'DEPARTMENT' AND department_id IS NULL)",
            name="ck_state_positions_department_scope",
        ),
        Index("ix_state_positions_institution", "institution_id", "status"),
    )


class OfficialPositionModel(Base):
    """تقليد مسؤول منصبًا، ونسبته إلى هويته الكانونية — R7-C4.

    ثلاث إشارات في صفٍّ واحد: `official_id` (سجلّ التقليد القائم من R7-A)،
    و`identity_id` (الهوية الكانونية)، و`position_id` (مصدر السلطة). فصار
    «الهوية X تشغل المنصب Y في المؤسسة Z» **صفًّا مقروءًا** لا استنتاجًا.

    وفهرسٌ فريدٌ جزئيّ يمنع تقليدين نشطين لنفس (مسؤول، منصب) في القاعدة نفسها،
    ويسمح ببقاء الصفوف المعزولة تاريخًا — فلا يُحذف تاريخ لأجل قيد.
    """

    __tablename__ = "state_official_positions"

    id = Column(String, primary_key=True)
    official_id = Column(
        String, ForeignKey("state_officials.id", ondelete="RESTRICT"), nullable=False
    )
    identity_id = Column(
        String, ForeignKey("state_identities.id", ondelete="RESTRICT"), nullable=False
    )
    position_id = Column(
        String, ForeignKey("state_positions.id", ondelete="RESTRICT"), nullable=False
    )
    status = Column(String, nullable=False, default="active")
    assigned_by = Column(String, nullable=False)
    assigned_at = Column(DateTime, default=_now)
    revoked_at = Column(DateTime, nullable=True)
    revocation_reason = Column(Text, default="")
    tenant_id = Column(String, nullable=False, default="default")

    __table_args__ = (
        CheckConstraint(
            _in_check("status", ASSIGNMENT_STATUSES), name="ck_state_official_positions_status"
        ),
        CheckConstraint(
            "(status = 'revoked' AND revoked_at IS NOT NULL) "
            "OR (status <> 'revoked' AND revoked_at IS NULL)",
            name="ck_state_official_positions_revoked_at",
        ),
        Index(
            "uq_state_official_positions_active",
            "official_id",
            "position_id",
            unique=True,
            sqlite_where=Column("status") == "active",
            postgresql_where=Column("status") == "active",
        ),
        Index("ix_state_official_positions_identity", "identity_id", "status"),
        Index("ix_state_official_positions_position", "position_id", "status"),
    )


class AuthorityGrantModel(Base):
    """نطاق سلطة منصبٍ على عمليةٍ مُسمّاة وهدفٍ مُسمّى — R7-C7 و R7-C8.

    الصفّ يقول: «المنصب P يملك العملية O في النطاق S على الهدف T». والهدف مفاتيح
    أجنبية حقيقية (مؤسسة · إدارة · موازنة · حساب)، فلا مِنحة على هدفٍ لا وجود له.

    وليست هذه مفردة صلاحيات ثالثة: `operation` أسماء عمليات **مفحوصة أصلًا** في
    `state_treasury` و`government_services`، لا صلاحيات جديدة تُضاف إلى
    `security_roles`. الصلاحية تقول «من أيّ طبقة أنت»، والمِنحة تقول «على أيّ مال
    بالتحديد» — وهذا هو الفرق الذي جاءت R7-C لبنائه.
    """

    __tablename__ = "state_authority_grants"

    id = Column(String, primary_key=True)
    position_id = Column(
        String, ForeignKey("state_positions.id", ondelete="RESTRICT"), nullable=False
    )
    operation = Column(String, nullable=False)
    scope = Column(String, nullable=False)
    institution_id = Column(
        String, ForeignKey("state_institutions.id", ondelete="RESTRICT"), nullable=True
    )
    department_id = Column(
        String, ForeignKey("state_departments.id", ondelete="RESTRICT"), nullable=True
    )
    budget_id = Column(String, ForeignKey("state_budgets.id", ondelete="RESTRICT"), nullable=True)
    account_id = Column(String, ForeignKey("state_accounts.id", ondelete="RESTRICT"), nullable=True)
    #: حدٌّ أعلى اختياري للمبلغ الواحد — `NUMERIC(20,4)` (الهجرة 014 · Q-20).
    #: غيابه يعني «بلا حدٍّ في هذه المِنحة»، ولا يعني «حدُّه صفر». وكان نصًّا
    #: فكان يقبلُ ما ليس عددًا ثمّ يسقطُ إلى الرفضِ عندَ القراءة؛ فصارَ الرفضُ
    #: عندَ الكتابةِ حيث موضعُه.
    max_amount = Column(MoneyType, nullable=True)
    status = Column(String, nullable=False, default="active")
    granted_by = Column(String, nullable=False)
    granted_at = Column(DateTime, default=_now)
    revoked_at = Column(DateTime, nullable=True)
    revocation_reason = Column(Text, default="")
    tenant_id = Column(String, nullable=False, default="default")

    __table_args__ = (
        CheckConstraint(
            _in_check("operation", GRANTABLE_OPERATIONS), name="ck_state_authority_grants_operation"
        ),
        CheckConstraint(
            _in_check("scope", AUTHORITY_SCOPES), name="ck_state_authority_grants_scope"
        ),
        CheckConstraint(
            _in_check("status", GRANT_STATUSES), name="ck_state_authority_grants_status"
        ),
        #: كل نطاق يلزمه هدفه: بلا هدف لا مِنحة (fail closed في المخطَّط نفسه).
        CheckConstraint(
            "(scope = 'DEPARTMENT' AND department_id IS NOT NULL) "
            "OR (scope IN ('INSTITUTION','STATE','FEDERAL') AND institution_id IS NOT NULL)",
            name="ck_state_authority_grants_target",
        ),
        Index("ix_state_authority_grants_position", "position_id", "status", "operation"),
        Index("ix_state_authority_grants_budget", "budget_id", "status"),
    )


class DecisionProvenanceModel(Base):
    """إسناد القرار إلى سلسلة سلطةٍ كاملة — R7-C9.

    القرار في `state_decisions` يحمل `decided_by_official_id` و`decided_by_principal`
    نصًّا. وهذا الجدول يضيف الحلقات الناقصة (الهوية والمنصب والمؤسسة) **وتصنيف
    قوّة الإسناد**. ولا يُكتب `PROVEN` إلا إذا قُرئت كل حلقة صفًّا.
    """

    __tablename__ = "state_decision_provenance"

    decision_id = Column(
        String, ForeignKey("state_decisions.id", ondelete="RESTRICT"), primary_key=True
    )
    principal_id = Column(String, nullable=False)
    identity_id = Column(
        String, ForeignKey("state_identities.id", ondelete="RESTRICT"), nullable=True
    )
    official_id = Column(
        String, ForeignKey("state_officials.id", ondelete="RESTRICT"), nullable=True
    )
    position_id = Column(
        String, ForeignKey("state_positions.id", ondelete="RESTRICT"), nullable=True
    )
    institution_id = Column(
        String, ForeignKey("state_institutions.id", ondelete="RESTRICT"), nullable=False
    )
    provenance_class = Column(String, nullable=False)
    reason = Column(Text, default="")
    session_id = Column(String, nullable=True)
    correlation_id = Column(String, nullable=True)
    tenant_id = Column(String, nullable=False, default="default")
    recorded_at = Column(DateTime, default=_now)

    __table_args__ = (
        CheckConstraint(
            _in_check("provenance_class", PROVENANCE_CLASSES),
            name="ck_state_decision_provenance_class",
        ),
        Index("ix_state_decision_provenance_identity", "identity_id"),
    )


class TransactionAuthorityModel(Base):
    """إسناد الحركة المالية إلى المِنحة التي أجازتها — R7-C8.

    كل حركة أجازتها مِنحة سلطة تُسجَّل هنا بمعرّف المِنحة نفسه، فيصير سؤال «بأيّ
    سلطة صُرِف هذا المال؟» استعلامًا لا اجتهادًا. والحركة التي مرّت بصلاحية دورٍ
    سيادية بلا مِنحة تُسجَّل أيضًا، مُصنَّفةً `PARTIAL` — لا تُخفى ولا تُرفَّع.
    """

    __tablename__ = "state_transaction_authority"

    transaction_id = Column(
        String, ForeignKey("state_transactions.id", ondelete="RESTRICT"), primary_key=True
    )
    principal_id = Column(String, nullable=False)
    identity_id = Column(
        String, ForeignKey("state_identities.id", ondelete="RESTRICT"), nullable=True
    )
    official_id = Column(
        String, ForeignKey("state_officials.id", ondelete="RESTRICT"), nullable=False
    )
    position_id = Column(
        String, ForeignKey("state_positions.id", ondelete="RESTRICT"), nullable=True
    )
    grant_id = Column(
        String, ForeignKey("state_authority_grants.id", ondelete="RESTRICT"), nullable=True
    )
    operation = Column(String, nullable=False)
    scope = Column(String, nullable=True)
    authority_class = Column(String, nullable=False)
    reason = Column(Text, default="")
    #: أهداف العملية كما فُحصت فعلًا — تُقرأ في التدقيق ولا تُعاد اشتقاقًا.
    targets = Column(JSON, default=dict)
    session_id = Column(String, nullable=True)
    correlation_id = Column(String, nullable=True)
    tenant_id = Column(String, nullable=False, default="default")
    recorded_at = Column(DateTime, default=_now)

    __table_args__ = (
        CheckConstraint(
            _in_check("authority_class", PROVENANCE_CLASSES),
            name="ck_state_transaction_authority_class",
        ),
        CheckConstraint(
            _in_check("operation", GRANTABLE_OPERATIONS),
            name="ck_state_transaction_authority_operation",
        ),
        Index("ix_state_transaction_authority_grant", "grant_id"),
        Index("ix_state_transaction_authority_identity", "identity_id"),
    )


__all__ = [
    "ASSIGNMENT_STATUSES",
    "AUTHORITY_SCOPES",
    "GRANTABLE_OPERATIONS",
    "GRANT_STATUSES",
    "IDENTITY_STATUSES",
    "IDENTITY_TYPES",
    "NATIONAL_REGISTRY_TABLES",
    "POSITION_STATUSES",
    "PROVENANCE_CLASSES",
    "AuthorityGrantModel",
    "DecisionProvenanceModel",
    "IdentityAgentModel",
    "IdentityModel",
    "IdentityPrincipalModel",
    "OfficialPositionModel",
    "PositionModel",
    "TransactionAuthorityModel",
]
