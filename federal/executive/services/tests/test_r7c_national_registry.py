"""
اختبارات R7-C — السجلّ الوطني وربط الهوية الكانونية
الهدف: التحقّق أن السلسلة مبدأ ← هوية ← مسؤول ← منصب ← مؤسسة ← نطاق ← عملية مقروءةٌ من القاعدة
النطاق: federal/executive/services
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17 (R7-C15)

اختبارات مركَّزة على نطاق R7-C وحده — لا مجموعةَ نظامٍ كاملة بعد كل تعديل. وما
تفحصه هذه الملفّة هو بالضبط ما يُدَّعى في أنظمة الحكومة الرقمية ولا يُفرَض:

1. **الاسم ليس هوية**: الهوية صفٌّ بمعرّفٍ مستقرّ، ولا قيد فريد على الاسم.
2. **المُنادي لا يحدّد هويته**: الربط عمليةٌ مُخوَّلة بـ`manage:all`، لا حقلٌ في الطلب.
3. **`role="official"` ليس إثبات منصب**: المنصب صفُّ تقليدٍ نشطٍ في مؤسسةٍ معيّنة.
4. **النطاقات ليست سلّمًا**: لا ترقية ضمنية بين FEDERAL/STATE/INSTITUTION/DEPARTMENT.
5. **دَين R7-B مسدود**: مسؤولٌ بمِنحةٍ يصرف بلا `write:all`، ومسؤولٌ بلا مِنحة يُرفض.
6. **الإسناد يُكتب لا يُستنتج**: صفٌّ لكل حركة وصفٌّ لكل قرار، بتصنيفٍ من الأدلة.
7. **لا تجاوز ساكن**: لا `identity_id` ولا `position_id` ولا نطاقٌ في أجسام الطلبات.

ما **لا** تفحصه ولا يُدَّعى: تزامنٌ حقيقيّ بجلستين (SQLite يتجاهل `FOR UPDATE`)،
ولا مصادقةُ أمرٍ سياديّ تعمويّة، ولا محاكم ولا بنك مركزي — خارج نطاق R7-C.
"""

from __future__ import annotations

import inspect
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from amos_federation.common.database import get_session_factory, init_db
from amos_federation.common.principal import (
    DEFAULT_TENANT,
    AuthorizationContext,
    Principal,
)
from amos_federation.services.executive_core.agent_identity import register_identity
from amos_federation.services.executive_core.dispatcher import WILDCARD, register_agent
from amos_federation.services.executive_core.engine import reset_executive_core
from amos_federation.services.governance.security import DEFAULT_ROLES
from amos_federation.services.government_services.models import CaseModel, DecisionModel
from amos_federation.services.government_services.service import (
    GovernmentServices,
    get_government_services,
    reset_government_services,
)
from amos_federation.services.national_registry.authorization import (
    NATIONAL_REGISTRY_PERMISSIONS,
    AuthorityDeniedError,
    require_authority,
)
from amos_federation.services.national_registry.models import (
    AUTHORITY_SCOPES,
    GRANTABLE_OPERATIONS,
    IDENTITY_TYPES,
    NATIONAL_REGISTRY_TABLES,
    PROVENANCE_CLASSES,
    AuthorityGrantModel,
    DecisionProvenanceModel,
    IdentityAgentModel,
    IdentityModel,
    IdentityPrincipalModel,
    OfficialPositionModel,
    PositionModel,
    TransactionAuthorityModel,
)
from amos_federation.services.national_registry.resolver import (
    ForgedAuthorityError,
    resolve_authority,
    resolve_identity,
    resolve_positions,
)
from amos_federation.services.national_registry.service import (
    DuplicateAssignmentError,
    IdentityConflictError,
    InvalidGrantTargetError,
    NationalRegistry,
    UnknownAgentError,
    get_national_registry,
    reset_national_registry,
)
from amos_federation.services.state_registry.authorization import (
    RegistryAuthorizationError,
)
from amos_federation.services.state_registry.models import (
    DepartmentModel,
    InstitutionModel,
    OfficialModel,
)
from amos_federation.services.state_registry.service import (
    StateRegistry,
    get_state_registry,
    reset_state_registry,
)
from amos_federation.services.state_treasury.models import (
    AccountModel as TreasuryAccountModel,
)
from amos_federation.services.state_treasury.models import (
    AllocationModel,
    BudgetModel,
    LedgerEntryModel,
    TransactionModel,
    TreasuryModel,
)
from amos_federation.services.state_treasury.service import (
    StateTreasury,
    get_state_treasury,
    reset_state_treasury,
)
from tests.conftest import purge_agents, purge_tasks

SRC = Path(__file__).resolve().parents[1] / "src" / "amos_federation"
REGISTRY_SRC = SRC / "services" / "national_registry"
MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "008_national_registry.sql"

_ROLE_PERMISSIONS = {role["role_id"]: tuple(role["permissions"]) for role in DEFAULT_ROLES}


def _strip_comments(source: str) -> str:
    """أزِل التعليقات وسلاسل التوثيق قبل أي تأكيد على المصدر.

    هذه الملفّة ومصادر R7-C مملوءةٌ بتعليقاتٍ تذكر `identity_id` و`position_id`
    لتشرح **منعها** — فلو لم تُنزَع لَفشل الحرس على شرحِ نفسه.
    """
    no_docstrings = re.sub(r'"""(?:.|\n)*?"""', "", source)
    return "\n".join(line.split("#", 1)[0] for line in no_docstrings.splitlines())


def _context(
    role_id: str,
    *,
    tenant_id: str | None = None,
    expires_at: datetime | None = None,
    username: str = "r7c-user",
) -> AuthorizationContext:
    """سياق `SESSION_VERIFIED` بصلاحيات الدور كما زُرعت — لا كما يشتهي الاختبار."""
    return AuthorizationContext.from_principal(
        Principal.from_session_record(
            session_id=f"r7c-{role_id}-{username}",
            username=username,
            role_id=role_id,
            permissions=_ROLE_PERMISSIONS[role_id],
            expires_at=expires_at,
            tenant_id=tenant_id,
        )
    )


@pytest.fixture(autouse=True)
def _fresh_state() -> None:
    """قاعدة نظيفة من صفوف النطاق قبل كل اختبار — الملفّ مشترك بين الاختبارات.

    الترتيب مقصود: صفوف الإسناد أوّلًا (تشير إلى الحركات والقرارات)، ثمّ المال،
    ثمّ التقليد قبل المسؤولين، ثمّ المناصب قبل المؤسسات.
    """
    init_db()
    session = get_session_factory()()
    try:
        session.query(TransactionAuthorityModel).delete()
        session.query(DecisionProvenanceModel).delete()
        session.query(LedgerEntryModel).delete()
        session.query(TransactionModel).filter(
            TransactionModel.reverses_transaction_id.isnot(None)
        ).delete()
        session.flush()
        session.query(TransactionModel).delete()
        session.query(AllocationModel).delete()
        session.query(BudgetModel).delete()
        session.query(TreasuryAccountModel).delete()
        session.query(TreasuryModel).delete()
        session.query(DecisionModel).delete()
        session.query(CaseModel).delete()
        session.query(AuthorityGrantModel).delete()
        session.query(OfficialPositionModel).delete()
        session.query(PositionModel).delete()
        session.query(IdentityAgentModel).delete()
        session.query(IdentityPrincipalModel).delete()
        session.query(IdentityModel).delete()
        purge_tasks(session)
        purge_agents(session)
        session.commit()
    finally:
        session.close()
    reset_executive_core()
    reset_state_registry()
    reset_government_services()
    reset_state_treasury()
    reset_national_registry()


@pytest.fixture
def registry() -> StateRegistry:
    return get_state_registry()


@pytest.fixture
def national() -> NationalRegistry:
    return get_national_registry()


@pytest.fixture
def gov() -> GovernmentServices:
    return get_government_services()


@pytest.fixture
def treasury() -> StateTreasury:
    return get_state_treasury()


@pytest.fixture
def crown() -> AuthorizationContext:
    """التاج — `*` فيمرّ في كل حدّ عبر `has_permission` نفسها."""
    return _context("king")


def _agent(tenant_id: str = DEFAULT_TENANT) -> str:
    """وكيلٌ حقيقي في `agents` — سجلّ R4 الكانوني، ولا يُنشئه السجلّ الوطني."""
    agent_id = f"agent-r7c-{uuid.uuid4().hex[:10]}"
    register_identity(agent_id, f"وكيل {agent_id}", "executor", tenant_id=tenant_id)
    return agent_id


def _worker() -> str:
    worker_id = f"worker-r7c-{uuid.uuid4().hex[:8]}"
    register_agent(worker_id, f"عامل {worker_id}", "worker", allowed_tools=[WILDCARD])
    return worker_id


def _code(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def _session():
    return get_session_factory()()


class Chain:
    """سلسلةٌ كاملة جاهزة: مؤسسة · مسؤول · هوية · منصب · تقليد."""

    def __init__(self, **kwargs: object) -> None:
        self.__dict__.update(kwargs)


def _chain(
    registry: StateRegistry,
    national: NationalRegistry,
    crown: AuthorizationContext,
    context: AuthorizationContext,
    *,
    branch: str = "executive",
    scope: str = "INSTITUTION",
    department: bool = False,
) -> Chain:
    """ابنِ السلسلة بعملياتٍ حقيقية — لا صفوفًا مزروعة يدويًّا.

    وهوية واحدة تُربط بالمبدأ **وبوكيل** المسؤول: هذا هو ما يجعل جلسة `context`
    قابلةً للحلّ إلى منصبٍ في القاعدة بلا أن تحمل الطلبات أيّ معرّف هوية.
    """
    institution = registry.register_institution(
        context=crown,
        code=_code("INST"),
        name="وزارة المالية",
        kind="ministry",
        branch=branch,
    )
    dept = None
    if department:
        dept = registry.create_department(
            context=crown,
            institution_code=institution["code"],
            code=_code("DEP"),
            name="إدارة الصرف",
        )
    agent_id = _agent()
    official = registry.appoint_official(
        context=crown,
        agent_id=agent_id,
        institution_code=institution["code"],
        title="أمين الخزانة",
        department_code=dept["code"] if dept else None,
    )
    identity = national.create_identity(
        context=crown, identity_type="PERSON", label="أمين الخزانة"
    )
    national.link_principal(
        context=crown, principal_id=context.principal_id, identity_id=identity["id"]
    )
    national.link_agent(context=crown, agent_id=agent_id, identity_id=identity["id"])
    position = national.create_position(
        context=crown,
        code=_code("POS"),
        title="أمين الخزانة",
        institution_code=institution["code"],
        authority_scope=scope,
        department_code=dept["code"] if (dept and scope == "DEPARTMENT") else None,
    )
    assignment = national.assign_position(
        context=crown, official_id=official["id"], position_id=position["id"]
    )
    return Chain(
        institution=institution,
        department=dept,
        agent_id=agent_id,
        official=official,
        identity=identity,
        position=position,
        assignment=assignment,
    )


def _fiscal(
    treasury: StateTreasury,
    crown: AuthorizationContext,
    chain: Chain,
    *,
    limit_amount: str = "100000.0000",
    funding: str = "50000.0000",
    allocation: str = "20000.0000",
) -> Chain:
    """أضِف خزانةً وحساباتٍ وموازنةً وتخصيصًا إلى سلسلةٍ قائمة — بأمر التاج."""
    code = chain.institution["code"]
    trs = treasury.establish_treasury(
        context=crown,
        code=_code("TRS"),
        name="الخزانة العامة",
        currency="SAR",
        institution_code=code,
    )
    cash = treasury.open_account(
        context=crown,
        treasury_code=trs["code"],
        code=_code("CASH"),
        name="النقد",
        kind="cash",
        institution_code=code,
    )
    revenue = treasury.open_account(
        context=crown,
        treasury_code=trs["code"],
        code=_code("REV"),
        name="الإيرادات",
        kind="revenue",
        institution_code=code,
    )
    expense = treasury.open_account(
        context=crown,
        treasury_code=trs["code"],
        code=_code("EXP"),
        name="المصروفات",
        kind="expense",
        institution_code=code,
    )
    budget = treasury.create_budget(
        context=crown,
        treasury_code=trs["code"],
        institution_code=code,
        code=_code("BDG"),
        period="2026",
        limit_amount=limit_amount,
    )
    treasury.post_funding(
        context=crown,
        treasury_code=trs["code"],
        cash_account_code=cash["code"],
        revenue_account_code=revenue["code"],
        amount=funding,
        purpose="تمويل افتتاحي",
        official_id=chain.official["id"],
    )
    alloc = treasury.allocate(
        context=crown,
        budget_code=budget["code"],
        account_code=cash["code"],
        purpose="تشغيل",
        amount=allocation,
        official_id=chain.official["id"],
    )
    chain.treasury = trs
    chain.cash = cash
    chain.revenue = revenue
    chain.expense = expense
    chain.budget = budget
    chain.allocation = alloc
    return chain


# ── 1. الهوية الكانونية (R7-C2) ───────────────────────────────────────────


def test_01_identity_is_a_real_row_with_a_stable_id_not_a_name(
    national: NationalRegistry, crown: AuthorizationContext
) -> None:
    """الهوية صفٌّ بمعرّفٍ مستقرّ — والاسم وصفٌ للعرض لا مُعرِّف."""
    first = national.create_identity(context=crown, identity_type="PERSON", label="سالم")
    second = national.create_identity(context=crown, identity_type="PERSON", label="سالم")
    assert first["id"] != second["id"], "الاسم المتطابق لا يجعل الهويتين واحدة"
    session = _session()
    try:
        rows = session.query(IdentityModel).filter(IdentityModel.label == "سالم").all()
        assert len(rows) == 2, "صفّان حقيقيّان في القاعدة — لا دمج على الاسم"
        assert all(row.id.startswith("idn-") for row in rows)
    finally:
        session.close()

    with pytest.raises(ValueError, match="نوع هوية"):
        national.create_identity(context=crown, identity_type="ROBOT")
    assert set(IDENTITY_TYPES) == {"PERSON", "AGENT", "ORGANIZATION", "INSTITUTION", "SYSTEM"}


def test_02_ambiguous_identity_is_named_unresolved_and_never_invented(
    national: NationalRegistry, crown: AuthorizationContext
) -> None:
    """الغموض يُسمّى `unresolved` بسببٍ مكتوب — ولا هوية تُختلق ولا تُدمج."""
    with pytest.raises(ValueError, match="سببها"):
        national.create_identity(context=crown, identity_type="PERSON", status="unresolved")

    unresolved = national.create_identity(
        context=crown,
        identity_type="PERSON",
        status="unresolved",
        status_reason="مستندان متعارضان لنفس الاسم",
    )
    assert unresolved["status"] == "unresolved"
    assert unresolved["status_reason"]

    other = national.create_identity(context=crown, identity_type="PERSON", label="آخر")
    national.link_principal(context=crown, principal_id="p-amb", identity_id=unresolved["id"])
    with pytest.raises(IdentityConflictError, match="لا يُدمَج"):
        national.link_principal(context=crown, principal_id="p-amb", identity_id=other["id"])


def test_03_session_resolves_to_identity_only_through_a_link_row(
    national: NationalRegistry, crown: AuthorizationContext
) -> None:
    """الجلسة تُحلّ إلى هوية بصفّ ربطٍ — وغيابه يُقال صراحةً لا يُملأ بتخمين."""
    context = _context("official", username="r7c-linked")
    session = _session()
    try:
        before = resolve_identity(session, context)
        assert before.resolved is False and before.identity_id is None
        assert before.reason, "الغياب يُشرح بالعربية لا يُترك فراغًا"
    finally:
        session.close()

    identity = national.create_identity(context=crown, identity_type="PERSON")
    national.link_principal(
        context=crown, principal_id=context.principal_id, identity_id=identity["id"]
    )
    session = _session()
    try:
        after = resolve_identity(session, context)
        assert after.resolved is True
        assert after.identity_id == identity["id"]
    finally:
        session.close()


def test_04_a_principal_cannot_bind_its_own_identity(
    national: NationalRegistry, crown: AuthorizationContext
) -> None:
    """الربط قرارٌ إداريٌّ مُخوَّل — لا يستطيع صاحب الجلسة أن يُسند نفسه إلى هوية."""
    identity = national.create_identity(context=crown, identity_type="PERSON")
    impostor = _context("official", username="r7c-impostor")
    with pytest.raises(RegistryAuthorizationError):
        national.link_principal(
            context=impostor,
            principal_id=impostor.principal_id,
            identity_id=identity["id"],
        )
    with pytest.raises(RegistryAuthorizationError):
        national.create_identity(context=impostor, identity_type="PERSON")


# ── 2. المسؤول والمنصب والمؤسسة (R7-C4/C5) ───────────────────────────────


def test_05_assignment_requires_an_appointed_official_and_a_canonical_identity(
    registry: StateRegistry, national: NationalRegistry, crown: AuthorizationContext
) -> None:
    """التقليد يلزمه مسؤولٌ قائم ووكيلٌ مربوطٌ بهوية — وإلّا فلا منصب."""
    institution = registry.register_institution(
        context=crown, code=_code("INST"), name="وزارة", kind="ministry", branch="executive"
    )
    official = registry.appoint_official(
        context=crown, agent_id=_agent(), institution_code=institution["code"], title="مدير"
    )
    position = national.create_position(
        context=crown,
        code=_code("POS"),
        title="مدير",
        institution_code=institution["code"],
        authority_scope="INSTITUTION",
    )
    with pytest.raises(IdentityConflictError, match="هوية كانونية"):
        national.assign_position(
            context=crown, official_id=official["id"], position_id=position["id"]
        )

    identity = national.create_identity(context=crown, identity_type="PERSON")
    national.link_agent(context=crown, agent_id=official["agent_id"], identity_id=identity["id"])
    assignment = national.assign_position(
        context=crown, official_id=official["id"], position_id=position["id"]
    )
    assert assignment["identity_id"] == identity["id"], "التقليد يُنسب إلى الهوية لا إلى الاسم"
    assert assignment["status"] == "active"


def test_06_a_position_belongs_to_one_institution_and_does_not_cross_it(
    registry: StateRegistry, national: NationalRegistry, crown: AuthorizationContext
) -> None:
    """منصبُ مؤسسةٍ لا يُقلَّد لمسؤولٍ في مؤسسةٍ أخرى — ولا نطاقَ إدارةٍ بلا إدارة."""
    first = registry.register_institution(
        context=crown, code=_code("INST"), name="أ", kind="ministry", branch="executive"
    )
    second = registry.register_institution(
        context=crown, code=_code("INST"), name="ب", kind="authority", branch="executive"
    )
    agent_id = _agent()
    official = registry.appoint_official(
        context=crown, agent_id=agent_id, institution_code=second["code"], title="مدير"
    )
    identity = national.create_identity(context=crown, identity_type="PERSON")
    national.link_agent(context=crown, agent_id=agent_id, identity_id=identity["id"])
    position = national.create_position(
        context=crown,
        code=_code("POS"),
        title="مدير",
        institution_code=first["code"],
        authority_scope="INSTITUTION",
    )
    with pytest.raises(InvalidGrantTargetError, match="عبر المؤسسات"):
        national.assign_position(
            context=crown, official_id=official["id"], position_id=position["id"]
        )

    with pytest.raises((ValueError, InvalidGrantTargetError)):
        national.create_position(
            context=crown,
            code=_code("POS"),
            title="رئيس إدارة",
            institution_code=first["code"],
            authority_scope="DEPARTMENT",
        )


def test_07_agent_link_never_creates_an_agent_nor_merges_the_two_tables(
    national: NationalRegistry, crown: AuthorizationContext
) -> None:
    """الربط لا يُنشئ وكيلًا ولا يدمج الجدولين — صفّان وصفُّ ربطٍ بينهما (R7-C5)."""
    with pytest.raises(UnknownAgentError, match="لا وكيل"):
        national.link_agent(context=crown, agent_id="agent-does-not-exist")

    agent_id = _agent()
    linked = national.link_agent(context=crown, agent_id=agent_id)
    assert linked["identity_id"], "أُنشئت هوية AGENT وربُطت — لا نسخٌ لصلاحيات الوكيل"
    session = _session()
    try:
        identity = session.get(IdentityModel, linked["identity_id"])
        assert identity is not None and identity.identity_type == "AGENT"
        columns = set(IdentityModel.__table__.columns.keys())
        assert "agent_id" not in columns, "الهوية لا تحمل عمود وكيل — الربط في جدوله"
        assert "permissions" not in columns and "role" not in columns
    finally:
        session.close()

    with pytest.raises(IdentityConflictError):
        national.link_agent(context=crown, agent_id=agent_id)


def test_08_duplicate_active_assignment_is_refused(
    registry: StateRegistry,
    national: NationalRegistry,
    crown: AuthorizationContext,
) -> None:
    """تقليدان نشطان لنفس (مسؤول، منصب) مرفوضان — والعزل يُعيد الباب مفتوحًا."""
    context = _context("official", username="r7c-dup")
    chain = _chain(registry, national, crown, context)
    with pytest.raises(DuplicateAssignmentError):
        national.assign_position(
            context=crown,
            official_id=chain.official["id"],
            position_id=chain.position["id"],
        )
    national.revoke_assignment(
        context=crown, assignment_id=chain.assignment["id"], reason="إعادة تنظيم"
    )
    again = national.assign_position(
        context=crown, official_id=chain.official["id"], position_id=chain.position["id"]
    )
    assert again["status"] == "active"
    session = _session()
    try:
        rows = session.query(OfficialPositionModel).all()
        assert len(rows) == 2, "الصفّ المعزول يبقى تاريخًا ولا يُحذَف"
        assert {row.status for row in rows} == {"active", "revoked"}
    finally:
        session.close()


# ── 3. حلّ السلطة والنطاقات (R7-C6/C7) ───────────────────────────────────


def test_09_authority_is_proven_only_by_a_matching_active_grant(
    registry: StateRegistry, national: NationalRegistry, crown: AuthorizationContext
) -> None:
    """`PROVEN` تلزمها مِنحةٌ نشطةٌ مطابقةٌ للعملية وللهدف — وقبلها الرفض هو الافتراض."""
    context = _context("official", username="r7c-proven")
    chain = _chain(registry, national, crown, context)
    session = _session()
    try:
        denied = resolve_authority(
            session,
            context,
            "treasury.disbursement.post",
            institution_id=chain.institution["id"],
        )
        assert denied.allowed is False
        assert denied.classification == "PARTIAL", "الهوية معروفة والمِنحة ناقصة — يُقال الفرق"
        assert denied.identity_id == chain.identity["id"]
    finally:
        session.close()

    grant = national.grant_authority(
        context=crown,
        position_id=chain.position["id"],
        operation="treasury.disbursement.post",
        scope="INSTITUTION",
        institution_id=chain.institution["id"],
    )
    session = _session()
    try:
        allowed = resolve_authority(
            session,
            context,
            "treasury.disbursement.post",
            institution_id=chain.institution["id"],
        )
        assert allowed.allowed is True
        assert allowed.classification == "PROVEN"
        assert allowed.grant_id == grant["id"]
        assert allowed.official_id == chain.official["id"]
        assert allowed.position_id == chain.position["id"]
        assert allowed.scope == "INSTITUTION"
    finally:
        session.close()


def test_10_federal_scope_is_not_authority_over_every_institution(
    registry: StateRegistry, national: NationalRegistry, crown: AuthorizationContext
) -> None:
    """مِنحة `FEDERAL` تُقيَّد بمؤسستها — لا ترقيةَ «فدرالي ⇒ كل مؤسسة»."""
    context = _context("official", username="r7c-federal")
    chain = _chain(registry, national, crown, context, scope="FEDERAL")
    national.grant_authority(
        context=crown,
        position_id=chain.position["id"],
        operation="treasury.funding.post",
        scope="FEDERAL",
        institution_id=chain.institution["id"],
    )
    other = registry.register_institution(
        context=crown, code=_code("INST"), name="أخرى", kind="authority", branch="executive"
    )
    session = _session()
    try:
        own = resolve_authority(
            session, context, "treasury.funding.post", institution_id=chain.institution["id"]
        )
        assert own.allowed is True and own.classification == "PROVEN"
        foreign = resolve_authority(
            session, context, "treasury.funding.post", institution_id=other["id"]
        )
        assert foreign.allowed is False
        assert "المؤسسة" in foreign.reason
    finally:
        session.close()


def test_11_state_scope_is_not_federal_treasury_authority(
    registry: StateRegistry, national: NationalRegistry, crown: AuthorizationContext
) -> None:
    """مِنحة `STATE` على مؤسسةٍ فرعها `treasury` مرفوضة بنصٍّ صريح — R7-C7."""
    context = _context("official", username="r7c-state")
    chain = _chain(registry, national, crown, context, branch="treasury", scope="STATE")
    national.grant_authority(
        context=crown,
        position_id=chain.position["id"],
        operation="treasury.disbursement.post",
        scope="STATE",
        institution_id=chain.institution["id"],
    )
    session = _session()
    try:
        decision = resolve_authority(
            session,
            context,
            "treasury.disbursement.post",
            institution_id=chain.institution["id"],
        )
        assert decision.allowed is False
        assert "خزانة" in decision.reason
    finally:
        session.close()


def test_12_department_scope_does_not_reach_institution_level_resources(
    registry: StateRegistry, national: NationalRegistry, crown: AuthorizationContext
) -> None:
    """سلطة إدارة لا تُغطّي موردًا على مستوى المؤسسة — ولا ترقيةَ إدارة ⇒ مؤسسة."""
    context = _context("official", username="r7c-dept")
    chain = _chain(registry, national, crown, context, scope="DEPARTMENT", department=True)
    national.grant_authority(
        context=crown,
        position_id=chain.position["id"],
        operation="treasury.allocation.create",
        scope="DEPARTMENT",
        institution_id=chain.institution["id"],
        department_id=chain.department["id"],
    )
    session = _session()
    try:
        institution_level = resolve_authority(
            session,
            context,
            "treasury.allocation.create",
            institution_id=chain.institution["id"],
        )
        assert institution_level.allowed is False
        assert any(
            phrase in institution_level.reason
            for phrase in ("ترقية", "مستوى المؤسسة", "لا يطابق")
        ), "الرفض يُشرح: إدارةٌ مُسمّاة في المِنحة لا تُغطّي موردًا بلا إدارة"

        in_department = resolve_authority(
            session,
            context,
            "treasury.allocation.create",
            institution_id=chain.institution["id"],
            department_id=chain.department["id"],
        )
        assert in_department.allowed is True
        assert in_department.scope == "DEPARTMENT"
    finally:
        session.close()


def test_13_revoked_position_ends_authority_without_any_extra_check(
    registry: StateRegistry, national: NationalRegistry, crown: AuthorizationContext
) -> None:
    """عزل المنصب يُنهي السلطة أثرًا آليًّا — لأن السلسلة تُقرأ من الصفوف كل مرّة."""
    context = _context("official", username="r7c-revoked-pos")
    chain = _chain(registry, national, crown, context)
    national.grant_authority(
        context=crown,
        position_id=chain.position["id"],
        operation="gov.case.decide",
        scope="INSTITUTION",
        institution_id=chain.institution["id"],
    )
    session = _session()
    try:
        assert resolve_authority(
            session, context, "gov.case.decide", institution_id=chain.institution["id"]
        ).allowed
    finally:
        session.close()

    national.revoke_assignment(
        context=crown, assignment_id=chain.assignment["id"], reason="عزل"
    )
    session = _session()
    try:
        after = resolve_authority(
            session, context, "gov.case.decide", institution_id=chain.institution["id"]
        )
        assert after.allowed is False
        assert resolve_positions(session, chain.identity["id"], tenant_id=DEFAULT_TENANT) == ()
    finally:
        session.close()


def test_14_revoked_grant_ends_authority_and_leaves_its_history(
    registry: StateRegistry, national: NationalRegistry, crown: AuthorizationContext
) -> None:
    """سحب المِنحة يمنع، وصفُّها يبقى فيُقرأ أنها كانت ثم سُحبت."""
    context = _context("official", username="r7c-revoked-grant")
    chain = _chain(registry, national, crown, context)
    grant = national.grant_authority(
        context=crown,
        position_id=chain.position["id"],
        operation="treasury.transaction.reverse",
        scope="INSTITUTION",
        institution_id=chain.institution["id"],
    )
    national.revoke_authority(context=crown, grant_id=grant["id"], reason="تغيّر التفويض")
    session = _session()
    try:
        decision = resolve_authority(
            session,
            context,
            "treasury.transaction.reverse",
            institution_id=chain.institution["id"],
        )
        assert decision.allowed is False
        row = session.get(AuthorityGrantModel, grant["id"])
        assert row is not None and row.status == "revoked"
        assert row.revocation_reason == "تغيّر التفويض" and row.revoked_at is not None
    finally:
        session.close()


def test_15_a_dead_session_resolves_to_no_authority(
    registry: StateRegistry, national: NationalRegistry, crown: AuthorizationContext
) -> None:
    """جلسةٌ منتهية لا تُنتج سلطةً ولو كانت السلسلة كاملة — R6.1 تبقى مفروضة."""
    context = _context("official", username="r7c-dead")
    chain = _chain(registry, national, crown, context)
    national.grant_authority(
        context=crown,
        position_id=chain.position["id"],
        operation="gov.case.decide",
        scope="INSTITUTION",
        institution_id=chain.institution["id"],
    )
    dead = _context(
        "official",
        username="r7c-dead",
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    assert dead.principal_id == context.principal_id, "نفس المبدأ — الفارق هو موت الجلسة"
    session = _session()
    try:
        with pytest.raises(PermissionError):
            require_authority(
                session, dead, "gov.case.decide", institution_id=chain.institution["id"]
            )
    finally:
        session.close()


def test_16_tenant_boundary_holds_across_the_whole_chain(
    registry: StateRegistry, national: NationalRegistry, crown: AuthorizationContext
) -> None:
    """حدّ المستأجر مفروض على السلسلة كلّها — R6.1 `SINGLE_TENANT` كما هي."""
    context = _context("official", username="r7c-tenant")
    chain = _chain(registry, national, crown, context)
    national.grant_authority(
        context=crown,
        position_id=chain.position["id"],
        operation="gov.case.decide",
        scope="INSTITUTION",
        institution_id=chain.institution["id"],
    )
    foreign = _context("official", username="r7c-tenant", tenant_id="tenant-other")
    session = _session()
    try:
        decision = resolve_authority(
            session, foreign, "gov.case.decide", institution_id=chain.institution["id"]
        )
        assert decision.allowed is False, "مستأجر آخر لا يقرأ سلسلة هذا المستأجر"
    finally:
        session.close()


def test_17_claiming_a_position_you_do_not_hold_is_refused_as_forgery(
    registry: StateRegistry, national: NationalRegistry, crown: AuthorizationContext
) -> None:
    """`official_id` ادّعاءٌ يُتحقَّق منه لا مصدرُ سلطة — الثغرة التي سدّتها R7-C."""
    holder_ctx = _context("official", username="r7c-holder")
    other_ctx = _context("official", username="r7c-other")
    chain = _chain(registry, national, crown, holder_ctx)
    identity = national.create_identity(context=crown, identity_type="PERSON")
    national.link_principal(
        context=crown, principal_id=other_ctx.principal_id, identity_id=identity["id"]
    )
    session = _session()
    try:
        with pytest.raises(ForgedAuthorityError, match="ليس من مناصب"):
            resolve_authority(
                session,
                other_ctx,
                "treasury.disbursement.post",
                institution_id=chain.institution["id"],
                claimed_official_id=chain.official["id"],
            )
        stranger = _context("official", username="r7c-stranger")
        with pytest.raises(ForgedAuthorityError):
            resolve_authority(
                session,
                stranger,
                "treasury.disbursement.post",
                institution_id=chain.institution["id"],
                claimed_official_id=chain.official["id"],
            )
    finally:
        session.close()


def test_18_operation_vocabulary_is_closed_and_scopes_are_the_four_named(
    national: NationalRegistry, crown: AuthorizationContext
) -> None:
    """لا عمليةً مُختَرعةً تُمنح ولا نطاقًا خارج الأربعة — والمفردة مغلقة في القاعدة."""
    assert set(AUTHORITY_SCOPES) == {"FEDERAL", "STATE", "INSTITUTION", "DEPARTMENT"}
    assert set(PROVENANCE_CLASSES) == {"PROVEN", "PARTIAL", "UNRESOLVED"}
    with pytest.raises(ValueError, match="غير قابلة للمنح"):
        national.grant_authority(
            context=crown,
            position_id="pos-x",
            operation="treasury.print_money",
            scope="FEDERAL",
        )
    session = _session()
    try:
        with pytest.raises(ValueError, match="عملية غير معروفة"):
            resolve_authority(
                session, crown, "treasury.print_money", institution_id="inst-x"
            )
    finally:
        session.close()


# ── 4. المال والقرار (R7-C8/C9) ──────────────────────────────────────────


def test_19_an_official_with_a_grant_spends_without_write_all(
    registry: StateRegistry,
    national: NationalRegistry,
    treasury: StateTreasury,
    crown: AuthorizationContext,
) -> None:
    """دَين R7-B مسدود: مِنحةُ منصبٍ تُجيز الصرف، لا توسيعُ صلاحيات الدور — R7-C8."""
    context = _context("official", username="r7c-spender")
    assert "write:all" not in context.permissions and "manage:all" not in context.permissions
    chain = _fiscal(treasury, crown, _chain(registry, national, crown, context))
    national.grant_authority(
        context=crown,
        position_id=chain.position["id"],
        operation="treasury.disbursement.post",
        scope="INSTITUTION",
        institution_id=chain.institution["id"],
        max_amount="5000.0000",
    )
    result = treasury.disburse(
        context=context,
        allocation_id=chain.allocation["id"],
        expense_account_code=chain.expense["code"],
        amount="1500.0000",
        purpose="أجور",
        official_id=chain.official["id"],
    )
    assert result["status"] == "posted"
    assert result["official_id"] == chain.official["id"]
    official_role = next(role for role in DEFAULT_ROLES if role["role_id"] == "official")
    assert set(official_role["permissions"]) == {
        "read:all",
        "write:tasks",
        "execute:tools",
        "manage:agents",
    }, "صلاحيات دور المسؤول لم تُوسَّع لتمرير المال — الحلّ كان مِنحة منصب"


def test_20_the_transaction_records_the_authority_chain_that_allowed_it(
    registry: StateRegistry,
    national: NationalRegistry,
    treasury: StateTreasury,
    crown: AuthorizationContext,
) -> None:
    """كل حركة تُكتب معها سلسلةُ سلطتها في صفٍّ مفتاحُه الحركة — R7-C9."""
    context = _context("official", username="r7c-recorded")
    chain = _fiscal(treasury, crown, _chain(registry, national, crown, context))
    grant = national.grant_authority(
        context=crown,
        position_id=chain.position["id"],
        operation="treasury.disbursement.post",
        scope="INSTITUTION",
        institution_id=chain.institution["id"],
    )
    result = treasury.disburse(
        context=context,
        allocation_id=chain.allocation["id"],
        expense_account_code=chain.expense["code"],
        amount="900.0000",
        purpose="صيانة",
        official_id=chain.official["id"],
    )
    session = _session()
    try:
        row = session.get(TransactionAuthorityModel, result["id"])
        assert row is not None, "لا حركةَ بلا إسناد مكتوب"
        assert row.authority_class == "PROVEN"
        assert row.grant_id == grant["id"]
        assert row.identity_id == chain.identity["id"]
        assert row.official_id == chain.official["id"]
        assert row.position_id == chain.position["id"]
        assert row.operation == "treasury.disbursement.post"
        assert row.scope == "INSTITUTION"
        assert row.targets and row.targets.get("amount") == "900.0000"
        assert row.principal_id == context.principal_id
    finally:
        session.close()


def test_21_an_official_without_a_grant_cannot_move_money(
    registry: StateRegistry,
    national: NationalRegistry,
    treasury: StateTreasury,
    crown: AuthorizationContext,
) -> None:
    """بلا مِنحةٍ لا مال — ولا يُحلّ الرفض بمنح `write:all` ولا `manage:all`."""
    context = _context("official", username="r7c-ungranted")
    chain = _fiscal(treasury, crown, _chain(registry, national, crown, context))
    with pytest.raises((AuthorityDeniedError, RegistryAuthorizationError)):
        treasury.disburse(
            context=context,
            allocation_id=chain.allocation["id"],
            expense_account_code=chain.expense["code"],
            amount="100.0000",
            purpose="محاولة",
            official_id=chain.official["id"],
        )
    session = _session()
    try:
        assert (
            session.query(TransactionModel).filter(TransactionModel.kind == "disbursement").count()
            == 0
        ), "الرفض قبل أيّ كتابة — لا حركة ولا قيد"
    finally:
        session.close()


def test_22_an_amount_above_the_grant_limit_is_refused(
    registry: StateRegistry,
    national: NationalRegistry,
    treasury: StateTreasury,
    crown: AuthorizationContext,
) -> None:
    """حدّ المِنحة مفروضٌ عشريًّا — والمِنحة سلطةٌ مقيَّدة لا مفتاحٌ مفتوح."""
    context = _context("official", username="r7c-limited")
    chain = _fiscal(treasury, crown, _chain(registry, national, crown, context))
    national.grant_authority(
        context=crown,
        position_id=chain.position["id"],
        operation="treasury.disbursement.post",
        scope="INSTITUTION",
        institution_id=chain.institution["id"],
        max_amount="1000.0000",
    )
    with pytest.raises((AuthorityDeniedError, RegistryAuthorizationError)):
        treasury.disburse(
            context=context,
            allocation_id=chain.allocation["id"],
            expense_account_code=chain.expense["code"],
            amount="1000.0001",
            purpose="تجاوز",
            official_id=chain.official["id"],
        )
    ok = treasury.disburse(
        context=context,
        allocation_id=chain.allocation["id"],
        expense_account_code=chain.expense["code"],
        amount="1000.0000",
        purpose="في الحدّ",
        official_id=chain.official["id"],
    )
    assert ok["status"] == "posted", "الحدّ يُقارَن بـ`Decimal` لا بعائم"


def test_23_a_decision_carries_its_provenance_and_the_crown_is_not_proven(
    registry: StateRegistry,
    national: NationalRegistry,
    gov: GovernmentServices,
    treasury: StateTreasury,
    crown: AuthorizationContext,
) -> None:
    """القرار يُنسب إلى سلسلةٍ مقروءة، وما لا يُثبَت يُصنَّف `PARTIAL`/`UNRESOLVED`.

    والتاج يمرّ بصلاحيته السيادية — ويُقال ذلك في الأثر بدل أن يُلبَس ثوب
    `PROVEN`. هذا هو معنى R7-C10: نموذج السيادة لم يُغيَّر، وصدق التصنيف حُفظ.
    """
    _worker()
    context = _context("official", username="r7c-judge")
    chain = _chain(registry, national, crown, context)
    national.grant_authority(
        context=crown,
        position_id=chain.position["id"],
        operation="gov.case.decide",
        scope="INSTITUTION",
        institution_id=chain.institution["id"],
    )
    service = gov.publish_service(
        context=crown,
        institution_code=chain.institution["code"],
        code=_code("SVC"),
        name="اعتماد",
    )

    def _decide(actor: AuthorizationContext, official_id: str | None) -> dict:
        case = gov.open_case(
            context=crown,
            institution_code=chain.institution["code"],
            service_code=service["code"],
            applicant_agent_id=_agent(),
            subject="طلب",
        )
        gov.process_case(context=crown, reference=case["reference"])
        return gov.decide_case(
            context=actor,
            reference=case["reference"],
            outcome="approved",
            rationale="مستوفٍ",
            official_id=official_id,
        )

    proven = _decide(context, chain.official["id"])
    assert proven["provenance"]["provenance_class"] == "PROVEN"
    sovereign = _decide(crown, chain.official["id"])
    assert sovereign["provenance"]["provenance_class"] in {"PARTIAL", "UNRESOLVED"}, (
        "التاج لا يُصنَّف `PROVEN` — سلطته من صلاحيةٍ سيادية لا من منصبٍ لهويته"
    )

    session = _session()
    try:
        first = session.get(DecisionProvenanceModel, proven["id"])
        assert first is not None
        assert first.identity_id == chain.identity["id"]
        assert first.official_id == chain.official["id"]
        assert first.position_id == chain.position["id"]
        assert first.institution_id == chain.institution["id"]
        second = session.get(DecisionProvenanceModel, sovereign["id"])
        assert second is not None and second.provenance_class in {"PARTIAL", "UNRESOLVED"}
        assert second.reason, "سبب عدم الإثبات مكتوب لا مُستنتج"
    finally:
        session.close()
    assert treasury is not None  # الخزانة مُهيَّأة في نفس القاعدة — الجداول موجودة


# ── 5. حرّاس ساكنة (R7-C15) ──────────────────────────────────────────────


def test_24_no_request_body_ever_carries_identity_position_or_scope() -> None:
    """أجسام الطلبات لا تحمل هويةً ولا منصبًا ولا نطاقًا — لا مسار تجاوزٍ من الشبكة."""
    forbidden = ("identity_id", "position_id", "authority_scope", "scope", "grant_id")
    for service in ("state_treasury", "government_services", "state_registry"):
        main = SRC / "services" / service / "main.py"
        source = _strip_comments(main.read_text(encoding="utf-8"))
        models = re.findall(r"class\s+\w+\(BaseModel\):(.*?)(?=\nclass |\n@|\Z)", source, re.S)
        for block in models:
            for field in forbidden:
                assert not re.search(rf"^\s+{field}\s*:", block, re.M), (
                    f"حقل '{field}' في جسم طلبٍ في {service}/main.py — "
                    "المُنادي لا يقرّر سلطته"
                )


def test_25_the_money_and_decision_paths_actually_call_the_resolver() -> None:
    """الحرس يفحص الاستدعاء لا التعليق: المُحلّل مُستعمَلٌ فعلًا في مسارَي المال والقرار."""
    treasury_source = _strip_comments(
        (SRC / "services" / "state_treasury" / "service.py").read_text(encoding="utf-8")
    )
    assert "require_treasury_authority(" in treasury_source
    assert "_record_transaction_authority(" in treasury_source
    assert "gate_treasury_operation(" in treasury_source
    for operation in (
        "treasury.funding.post",
        "treasury.allocation.create",
        "treasury.disbursement.post",
        "treasury.transaction.reverse",
    ):
        assert f'"{operation}"' in treasury_source, f"العملية '{operation}' غير مُبوَّبة بالسلطة"

    gov_source = _strip_comments(
        (SRC / "services" / "government_services" / "service.py").read_text(encoding="utf-8")
    )
    assert "require_authority(" in gov_source
    assert "_record_decision_provenance(" in gov_source
    assert "resolve_official_for_principal(" in gov_source

    signature = inspect.signature(StateTreasury._post)
    assert "authority" in signature.parameters, "مسار الكتابة الوحيد يلزمه قرار سلطة"
    assert signature.parameters["authority"].default is inspect.Parameter.empty, (
        "قرار السلطة إلزاميٌّ بلا قيمة افتراضية — لا حركةَ بلا إسناد"
    )


def test_26_the_registry_invents_no_permission_vocabulary_and_no_third_registry() -> None:
    """لا صلاحيةً جديدة ولا سجلًّا ثالثًا ولا مُنفِّذًا ولا ناقل أحداثٍ خاصًّا — C1/C12/C13."""
    granted = {permission for role in DEFAULT_ROLES for permission in role["permissions"]}
    for permission in NATIONAL_REGISTRY_PERMISSIONS:
        assert permission in granted, f"صلاحية '{permission}' ليست من `DEFAULT_ROLES`"

    for path in sorted(REGISTRY_SRC.glob("*.py")):
        source = _strip_comments(path.read_text(encoding="utf-8"))
        assert "class AgentModel" not in source, "لا إعادةَ بناءٍ لسجلّ الوكلاء الموحَّد في R4"
        assert "ThreadPoolExecutor" not in source and "asyncio.create_task" not in source
        assert "class EventBus" not in source and "def publish(" not in source
        assert "create_all" not in source, "تعديل المخطّط بترحيلٍ صريح لا بـ`create_all`"

    tables = {
        model.__tablename__
        for model in (
            IdentityModel,
            IdentityPrincipalModel,
            IdentityAgentModel,
            PositionModel,
            OfficialPositionModel,
            AuthorityGrantModel,
            DecisionProvenanceModel,
            TransactionAuthorityModel,
        )
    }
    assert tables == set(NATIONAL_REGISTRY_TABLES)
    assert OfficialModel.__tablename__ not in tables, "المسؤولون سجلّ R7-A ولم يُستنسخ"
    assert InstitutionModel.__tablename__ not in tables
    assert DepartmentModel.__tablename__ not in tables

    migration = MIGRATION.read_text(encoding="utf-8")
    for table in NATIONAL_REGISTRY_TABLES:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in migration
    assert "DROP TABLE" not in migration and "DELETE FROM" not in migration, (
        "الترحيل لا يحذف تاريخًا"
    )
    assert set(GRANTABLE_OPERATIONS) >= {
        "treasury.funding.post",
        "treasury.allocation.create",
        "treasury.disbursement.post",
        "treasury.transaction.reverse",
        "gov.case.decide",
    }
