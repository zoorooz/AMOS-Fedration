"""
AMOS-Federation R9 — National Economic State: Targeted Tests
الهدف: فحصٌ مركَّزٌ لمحاور R9-T — سجلٌّ وحدودٌ وسياسةٌ ومالٌ وإسنادٌ وسيادة
النطاق: tests
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17 (R9-T)

## لماذا اختباراتٌ مركَّزةٌ لا حزمةٌ كاملة

R9-T تطلب فحوصًا مُوجَّهةً لكلِّ محور، لا تشغيلَ المستودع كلِّه بعد كلِّ تغيير.
فكلُّ دالّةٍ هنا تُثبت **حقيقةً واحدة** يمكن أن تُكسَر وحدها فتفشل بسببٍ مقروء.

## ما يُبنى بعملياتٍ حقيقية

لا صفوفَ مزروعةً في جداول السلطة ولا في جداول المال: الهويةُ والمنصبُ والتقليدُ
والمِنحةُ بواجهات R7-C، والحكومةُ والربطُ بواجهة R8، والخزانةُ بواجهة R7-B. فلو
كُسِرت حلقةٌ لَفشل الاختبار حيث كُسِرت لا حيث نتوقّع.

## الحرسُ الساكن

بعضُ محاور R9 لا يُثبتها سلوكٌ بل **غيابُ طريقٍ** في المصدر: لا دفترَ ثانيًا،
ولا منفِّذَ اقتصاديًّا موازيًا، ولا ناقلَ أحداثٍ جديدًا، ولا رصيدًا مخزّنًا. تلك
تُفحَص على المصدر بعد نزع التعليقات، لأن هذه الملفّات تذكر ما تمنعه لتشرح منعَه.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from amos_federation.common.database import get_session_factory, init_db
from amos_federation.common.event_bus import EVENT_CONTRACTS
from amos_federation.common.persistent import PersistentAuditStore
from amos_federation.common.principal import (
    DEFAULT_TENANT,
    AuthorizationContext,
    Principal,
    PrincipalKind,
    PrincipalUnverifiedError,
    PrincipalVerification,
    SessionInvalidError,
)
from amos_federation.services.executive_core.agent_identity import register_identity
from amos_federation.services.executive_core.dispatcher import WILDCARD, register_agent
from amos_federation.services.executive_core.engine import reset_executive_core
from amos_federation.services.federal_state.authority import GovernmentAuthorityError
from amos_federation.services.federal_state.models import (
    CaseScopeModel,
    GovernmentDelegationModel,
    GovernmentModel,
    GovernmentOperationModel,
    GovernmentRelationModel,
    InstitutionGovernmentModel,
    ServiceScopeModel,
)
from amos_federation.services.federal_state.service import (
    FederalStateGovernment,
    get_federal_state,
    reset_federal_state,
)
from amos_federation.services.governance.security import DEFAULT_ROLES
from amos_federation.services.government_services.models import CaseModel
from amos_federation.services.government_services.service import reset_government_services
from amos_federation.services.national_economy import (
    EconomicCategoryModel,
    EconomicDecisionModel,
    EconomicIndicatorDefinitionModel,
    EconomicPolicyModel,
    EconomicProgramModel,
    EconomicSectorModel,
    EconomicTransferModel,
    ExpenditureAuthorizationModel,
    NationalEconomy,
    ProcurementModel,
    PublicAssetModel,
    PublicEconomicEntityModel,
    PublicLiabilityModel,
    RevenueSourceModel,
)
from amos_federation.services.national_economy.authorization import EconomicAuthorizationError
from amos_federation.services.national_economy.service import (
    DuplicateEconomicEntityError,
    EconomicEntityNotFoundError,
    EconomicStateError,
    get_national_economy,
    reset_national_economy,
)
from amos_federation.services.national_registry.models import (
    ECONOMIC_OPERATIONS,
    GRANTABLE_OPERATIONS,
    AuthorityGrantModel,
    IdentityAgentModel,
    IdentityModel,
    IdentityPrincipalModel,
    OfficialPositionModel,
    PositionModel,
    TransactionAuthorityModel,
)
from amos_federation.services.national_registry.service import (
    NationalRegistry,
    get_national_registry,
    reset_national_registry,
)
from amos_federation.services.state_registry.authorization import RegistryAuthorizationError
from amos_federation.services.state_registry.service import (
    StateRegistry,
    get_state_registry,
    reset_state_registry,
)
from amos_federation.services.state_treasury.models import (
    AccountModel,
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

_ROLE_PERMISSIONS = {role["role_id"]: tuple(role["permissions"]) for role in DEFAULT_ROLES}

_R9_SOURCE_DIR = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "amos_federation"
    / "services"
    / "national_economy"
)
_MIGRATION_011 = (
    Path(__file__).resolve().parents[1] / "migrations" / "011_national_economic_state.sql"
)

#: ترتيبُ الحذف ترتيبُ القيود المرجعية معكوسًا: كلُّ جدولٍ يُحذَف قبل ما يشير
#: إليه. والقراراتُ الاقتصادية آخِرُها لأنّ السياسةَ والإجازةَ والتحويلَ
#: والمشترياتِ تشير إليها بـ `decision_id` (الهجرة 012).
_ECONOMY_MODELS = (
    ProcurementModel,
    EconomicTransferModel,
    ExpenditureAuthorizationModel,
    RevenueSourceModel,
    PublicLiabilityModel,
    PublicAssetModel,
    EconomicIndicatorDefinitionModel,
    EconomicProgramModel,
    EconomicPolicyModel,
    PublicEconomicEntityModel,
    EconomicCategoryModel,
    EconomicSectorModel,
    EconomicDecisionModel,
)


def _strip_comments(source: str) -> str:
    """أزِل التعليقات وسلاسلَ التوثيق قبل أيّ تأكيدٍ على المصدر.

    مصادرُ R9 تذكر «دفترٌ ثانٍ» و«economic_executor» في تعليقاتها لتشرح **منعَها**
    — فلو لم تُنزَع لَفشل الحرسُ على شرحِ نفسه.
    """
    no_docstrings = re.sub(r'"""(?:.|\n)*?"""', "", source)
    return "\n".join(line.split("#", 1)[0] for line in no_docstrings.splitlines())


def _r9_sources() -> dict[str, str]:
    return {
        path.name: _strip_comments(path.read_text(encoding="utf-8"))
        for path in sorted(_R9_SOURCE_DIR.glob("*.py"))
    }


def _context(
    role_id: str,
    *,
    tenant_id: str | None = None,
    username: str = "r9-user",
    expires_at: datetime | None = None,
) -> AuthorizationContext:
    """سياقٌ مُتحقَّقُ الجلسة بصلاحيات الدور كما زُرعت — لا كما يشتهي الاختبار."""
    return AuthorizationContext.from_principal(
        Principal.from_session_record(
            session_id=f"r9-{role_id}-{username}",
            username=username,
            role_id=role_id,
            permissions=_ROLE_PERMISSIONS[role_id],
            expires_at=expires_at,
            tenant_id=tenant_id,
        )
    )


@pytest.fixture(autouse=True)
def _fresh_state() -> None:
    """قاعدةٌ نظيفةٌ من صفوف النطاق قبل كلِّ اختبار — الملفُّ مشتركٌ بينها.

    الترتيبُ ترتيبُ القيود المرجعية: القرارُ الاقتصاديّ أوّلًا لأنه يشير إلى كلِّ
    موضوع، ثمّ المشترياتُ والتحويلاتُ ثمّ الإجازاتُ ثمّ التعريفاتُ ثمّ القطاعات.
    """
    init_db()
    session = get_session_factory()()
    try:
        for model in _ECONOMY_MODELS:
            session.query(model).delete()
        session.flush()
        session.query(GovernmentOperationModel).delete()
        session.query(CaseScopeModel).delete()
        session.query(ServiceScopeModel).delete()
        session.query(GovernmentDelegationModel).delete()
        session.query(GovernmentRelationModel).delete()
        session.query(InstitutionGovernmentModel).delete()
        session.query(GovernmentModel).filter(
            GovernmentModel.parent_government_id.isnot(None)
        ).delete()
        session.flush()
        session.query(GovernmentModel).delete()
        session.query(LedgerEntryModel).delete()
        session.query(TransactionAuthorityModel).delete()
        session.flush()
        session.query(TransactionModel).delete()
        session.query(AllocationModel).delete()
        session.query(BudgetModel).delete()
        session.query(AccountModel).delete()
        session.query(TreasuryModel).delete()
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
    reset_federal_state()
    reset_national_economy()


@pytest.fixture
def registry() -> StateRegistry:
    return get_state_registry()


@pytest.fixture
def national() -> NationalRegistry:
    return get_national_registry()


@pytest.fixture
def treasury() -> StateTreasury:
    return get_state_treasury()


@pytest.fixture
def federation() -> FederalStateGovernment:
    return get_federal_state()


@pytest.fixture
def economy() -> NationalEconomy:
    return get_national_economy()


@pytest.fixture
def crown(national: NationalRegistry) -> AuthorizationContext:
    """التاجُ — `*` فيمرّ في كلِّ حدّ، وله هويةٌ كانونيةٌ كأيّ فاعلٍ آخر."""
    context = _context("king", username="crown")
    identity = national.create_identity(context=context, identity_type="PERSON", label="التاج")
    national.link_principal(
        context=context, principal_id=context.principal_id, identity_id=identity["id"]
    )
    return context


def _agent(tenant_id: str = DEFAULT_TENANT) -> str:
    agent_id = f"agent-r9-{uuid.uuid4().hex[:10]}"
    register_identity(agent_id, f"وكيل {agent_id}", "executor", tenant_id=tenant_id)
    return agent_id


def _worker() -> str:
    worker_id = f"worker-r9-{uuid.uuid4().hex[:8]}"
    register_agent(worker_id, f"عامل {worker_id}", "worker", allowed_tools=[WILDCARD])
    return worker_id


def _code(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def _session():
    return get_session_factory()()


class Chain:
    """سلسلةٌ جاهزة: مؤسسةٌ · مسؤولٌ · هويةٌ · منصبٌ · تقليدٌ · مِنحٌ · ربطٌ حكوميّ."""

    def __init__(self, **kwargs: object) -> None:
        self.__dict__.update(kwargs)


def _identity_of_principal(
    national: NationalRegistry,
    crown: AuthorizationContext,
    context: AuthorizationContext,
    *,
    label: str,
) -> dict[str, Any]:
    """هويةُ المُنادي — تُقرأ إن كانت مربوطةً ولا تُكرَّر (المبدأُ لا يُدمَج تلقائيًّا)."""
    session = _session()
    try:
        existing = (
            session.query(IdentityPrincipalModel)
            .filter(IdentityPrincipalModel.principal_id == context.principal_id)
            .one_or_none()
        )
        if existing is not None:
            return {"id": existing.identity_id}
    finally:
        session.close()
    identity = national.create_identity(context=crown, identity_type="PERSON", label=label)
    national.link_principal(
        context=crown, principal_id=context.principal_id, identity_id=identity["id"]
    )
    return identity


def _authority_chain(
    registry: StateRegistry,
    national: NationalRegistry,
    federation: FederalStateGovernment,
    crown: AuthorizationContext,
    context: AuthorizationContext,
    *,
    government_code: str | None,
    scope: str = "STATE",
    operations: tuple[str, ...] = (),
    department_code: str | None = None,
    max_amount: str | None = None,
    label: str = "مسؤولٌ اقتصاديّ",
) -> Chain:
    """ابنِ سلسلةَ سلطةٍ كاملةً بعملياتٍ حقيقيةٍ ومِنحٍ مُسمّاةٍ لكلِّ عملية."""
    institution = registry.register_institution(
        context=crown,
        code=_code("INS"),
        name="وزارةٌ اقتصادية",
        kind="ministry",
        branch="executive",
    )
    department = None
    if department_code:
        department = registry.create_department(
            context=crown,
            institution_code=institution["code"],
            code=department_code,
            name="إدارةٌ اقتصادية",
        )
    agent_id = _agent()
    official = registry.appoint_official(
        context=crown,
        agent_id=agent_id,
        institution_code=institution["code"],
        title="مسؤول",
    )
    identity = _identity_of_principal(national, crown, context, label=label)
    national.link_agent(context=crown, agent_id=agent_id, identity_id=identity["id"])
    position = national.create_position(
        context=crown,
        code=_code("POS"),
        title="مسؤول",
        institution_code=institution["code"],
        authority_scope=scope,
        department_code=department["code"] if (department and scope == "DEPARTMENT") else None,
    )
    assignment = national.assign_position(
        context=crown, official_id=official["id"], position_id=position["id"]
    )
    bind_to_institution = scope != "FEDERAL"
    grants = {}
    for operation in operations:
        grants[operation] = national.grant_authority(
            context=crown,
            position_id=position["id"],
            operation=operation,
            scope=scope,
            institution_id=institution["id"] if bind_to_institution else None,
            department_id=department["id"] if (department and scope == "DEPARTMENT") else None,
            max_amount=max_amount,
        )
    binding = None
    if government_code:
        binding = federation.bind_institution(
            crown,
            institution_code=institution["code"],
            government_code=government_code,
        )
    return Chain(
        crown=crown,
        government_code=government_code,
        institution=institution,
        department=department,
        agent_id=agent_id,
        official=official,
        identity=identity,
        position=position,
        assignment=assignment,
        grants=grants,
        binding=binding,
    )


def _federal_and_states(
    federation: FederalStateGovernment, crown: AuthorizationContext, count: int = 2
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    federal = federation.register_government(
        crown, code=_code("FED"), name="الحكومة الفدرالية", level="FEDERAL"
    )
    states = [
        federation.register_government(
            crown,
            code=_code("ST"),
            name=f"ولاية {index}",
            level="STATE",
            parent_code=federal["code"],
        )
        for index in range(count)
    ]
    return federal, states


def _treasury_chain(
    treasury: StateTreasury,
    crown: AuthorizationContext,
    institution_code: str,
    official_id: str,
) -> dict[str, Any]:
    """خزانةٌ حقيقيةٌ مموَّلةٌ بواجهة R7-B — لا صفوفَ مالٍ مزروعة."""
    trs = treasury.establish_treasury(
        context=crown,
        code=_code("TRS"),
        name="خزانةٌ حكومية",
        currency="SAR",
        institution_code=institution_code,
    )
    cash = treasury.open_account(
        context=crown,
        treasury_code=trs["code"],
        code=_code("CASH"),
        name="النقد",
        kind="cash",
        institution_code=institution_code,
    )
    revenue = treasury.open_account(
        context=crown,
        treasury_code=trs["code"],
        code=_code("REV"),
        name="الإيرادات",
        kind="revenue",
        institution_code=institution_code,
    )
    expense = treasury.open_account(
        context=crown,
        treasury_code=trs["code"],
        code=_code("EXP"),
        name="المصروفات",
        kind="expense",
        institution_code=institution_code,
    )
    budget = treasury.create_budget(
        context=crown,
        treasury_code=trs["code"],
        institution_code=institution_code,
        code=_code("BDG"),
        period="2026",
        limit_amount="100000.0000",
    )
    treasury.post_funding(
        context=crown,
        treasury_code=trs["code"],
        cash_account_code=cash["code"],
        revenue_account_code=revenue["code"],
        amount="50000.0000",
        purpose="تمويلٌ افتتاحيّ",
        official_id=official_id,
    )
    allocation = treasury.allocate(
        context=crown,
        budget_code=budget["code"],
        account_code=cash["code"],
        purpose="مصروفاتٌ حكومية",
        amount="20000.0000",
        official_id=official_id,
    )
    return {
        "treasury": trs,
        "cash": cash,
        "revenue": revenue,
        "expense": expense,
        "budget": budget,
        "allocation": allocation,
    }


def _sector(
    economy: NationalEconomy, crown: AuthorizationContext, government_code: str, level: str
):
    return economy.register_sector(
        crown,
        code=_code("SEC"),
        name="قطاعُ الطاقة",
        government_code=government_code,
        scope_level=level,
    )


def _program(
    economy: NationalEconomy,
    context: AuthorizationContext,
    chain: Chain,
    scope: str,
    sector_code: str | None = None,
) -> dict[str, Any]:
    """برنامجٌ في قطاعٍ موجود — المخطَّطُ يمنع برنامجًا بلا قطاع."""
    if sector_code is None:
        sector_code = _sector(
            economy,
            chain.crown,
            chain.government_code,
            "FEDERAL" if scope == "FEDERAL" else "STATE",
        )["code"]
    return economy.create_program(
        context,
        code=_code("PRG"),
        name="برنامجٌ اقتصاديّ",
        institution_code=chain.institution["code"],
        scope_level=scope,
        sector_code=sector_code,
        department_id=chain.department["id"]
        if (chain.department and scope == "DEPARTMENT")
        else None,
    )


# ── 1. سجلُّ الاقتصاد: معرِّفٌ مستقرٌّ وحالةٌ وطوابعُ وملكيةٌ صريحة (R9-B) ──


def test_01_economic_entities_have_stable_identity_and_explicit_ownership(
    economy: NationalEconomy,
    registry: StateRegistry,
    national: NationalRegistry,
    federation: FederalStateGovernment,
    crown: AuthorizationContext,
) -> None:
    """كلُّ كيانٍ اقتصاديٍّ صفٌّ بمعرِّفٍ ليس الرمزَ، وبمالكٍ ونطاقٍ ومستأجرٍ صريح."""
    _federal, (state, _other) = _federal_and_states(federation, crown)
    chain = _authority_chain(
        registry,
        national,
        federation,
        crown,
        crown,
        government_code=state["code"],
        scope="STATE",
        operations=("economy.entity.register",),
    )
    sector = _sector(economy, crown, state["code"], "STATE")
    entity_identity = national.create_identity(
        context=crown, identity_type="ORGANIZATION", label="صندوقٌ عامّ"
    )
    entity = economy.register_public_entity(
        crown,
        code=_code("PUB"),
        name="صندوقٌ عامّ",
        entity_kind="PUBLIC_FUND",
        institution_code=chain.institution["code"],
        scope_level="STATE",
        identity_id=entity_identity["id"],
        sector_code=sector["code"],
    )

    assert sector["id"].startswith("esec-") and sector["id"] != sector["code"], "المعرِّفُ ليس الرمز"
    assert sector["status"] == "active" and sector["created_at"]
    assert sector["government_id"] == state["id"], "القطاعُ مملوكٌ لحكومةٍ بمفتاح"
    assert entity["id"].startswith("epub-") and entity["id"] != entity["code"]
    assert entity["government_id"] == state["id"]
    assert entity["institution_id"] == chain.institution["id"], "الملكيةُ صريحةٌ لا مُستنتَجة"
    assert entity["scope_level"] == "STATE"
    assert entity["identity_id"] == entity_identity["id"], "الكيانُ هويةٌ قائمةٌ لا اسمٌ جديد"
    assert entity["tenant_id"] == DEFAULT_TENANT
    assert entity["status"] == "active"
    assert entity["decision"]["reference"].startswith("ECD-"), "لكلِّ فعلٍ قرارٌ بمرجعٍ مقروء"


# ── 2. لا كيانَ مكرَّرًا: الهويةُ مُعرِّفٌ لا اسم (R9-B) ────────────────────


def test_02_duplicate_codes_are_rejected_within_tenant(
    economy: NationalEconomy, federation: FederalStateGovernment, crown: AuthorizationContext
) -> None:
    """رمزُ القطاع فريدٌ في المستأجر، والاسمُ لا يُغني عن الرمز."""
    _federal, (state, _other) = _federal_and_states(federation, crown)
    sector = _sector(economy, crown, state["code"], "STATE")

    with pytest.raises(DuplicateEconomicEntityError):
        economy.register_sector(
            crown,
            code=sector["code"],
            name="اسمٌ مختلفٌ تمامًا",
            government_code=state["code"],
            scope_level="STATE",
        )

    session = _session()
    try:
        assert session.query(EconomicSectorModel).count() == 1, "لا صفَّ ثانيًا كُتب"
    finally:
        session.close()


# ── 3-6. الفصلُ بين المستويات: فدراليٌّ وولايةٌ ومؤسسةٌ وإدارة (R9-C) ───────


def test_03_federal_scope_program_is_owned_by_federal_government(
    economy: NationalEconomy,
    registry: StateRegistry,
    national: NationalRegistry,
    federation: FederalStateGovernment,
    crown: AuthorizationContext,
) -> None:
    """برنامجٌ بنطاقٍ فدراليٍّ يُملَك للحكومة الفدرالية لا لولاية."""
    federal, _states = _federal_and_states(federation, crown)
    chain = _authority_chain(
        registry,
        national,
        federation,
        crown,
        crown,
        government_code=federal["code"],
        scope="FEDERAL",
        operations=("economy.program.create",),
    )
    program = _program(economy, crown, chain, "FEDERAL")
    assert program["scope_level"] == "FEDERAL"
    assert program["government_id"] == federal["id"], "الفدراليُّ ≠ الولاية"


def test_04_state_scope_program_is_owned_by_its_own_state(
    economy: NationalEconomy,
    registry: StateRegistry,
    national: NationalRegistry,
    federation: FederalStateGovernment,
    crown: AuthorizationContext,
) -> None:
    """برنامجُ ولايةٍ يُملَك لولايته بعينها لا لأختها."""
    _federal, (state_a, state_b) = _federal_and_states(federation, crown)
    chain = _authority_chain(
        registry,
        national,
        federation,
        crown,
        crown,
        government_code=state_a["code"],
        scope="STATE",
        operations=("economy.program.create",),
    )
    program = _program(economy, crown, chain, "STATE")
    assert program["government_id"] == state_a["id"]
    assert program["government_id"] != state_b["id"], "ولايةٌ أ ≠ ولايةٌ ب"


def test_05_institution_scope_is_narrower_than_state(
    economy: NationalEconomy,
    registry: StateRegistry,
    national: NationalRegistry,
    federation: FederalStateGovernment,
    crown: AuthorizationContext,
) -> None:
    """نطاقُ المؤسسة يُثبَت في الصفِّ ولا يُوسَّع إلى الولاية."""
    _federal, (state, _other) = _federal_and_states(federation, crown)
    chain = _authority_chain(
        registry,
        national,
        federation,
        crown,
        crown,
        government_code=state["code"],
        scope="INSTITUTION",
        operations=("economy.program.create",),
    )
    program = _program(economy, crown, chain, "INSTITUTION")
    assert program["scope_level"] == "INSTITUTION"
    assert program["institution_id"] == chain.institution["id"]
    assert program["department_id"] is None, "نطاقُ مؤسسةٍ لا يُثبِّت إدارة"


def test_06_department_scope_requires_department_identifier(
    economy: NationalEconomy,
    registry: StateRegistry,
    national: NationalRegistry,
    federation: FederalStateGovernment,
    crown: AuthorizationContext,
) -> None:
    """نطاقُ الإدارة يلزمه معرِّفُ إدارةٍ صريح — والمخطَّطُ يحرسه أيضًا."""
    _federal, (state, _other) = _federal_and_states(federation, crown)
    chain = _authority_chain(
        registry,
        national,
        federation,
        crown,
        crown,
        government_code=state["code"],
        scope="DEPARTMENT",
        department_code=_code("DEP"),
        operations=("economy.program.create",),
    )
    program = _program(economy, crown, chain, "DEPARTMENT")
    assert program["department_id"] == chain.department["id"]

    with pytest.raises(EconomicStateError):
        economy.create_program(
            crown,
            code=_code("PRG"),
            name="برنامجٌ بلا إدارة",
            institution_code=chain.institution["code"],
            scope_level="DEPARTMENT",
        )


# ── 7. الحدُّ بين الولايات: ولايةٌ لا تُخوِّل في أختها (R9-C/R9-M) ──────────


def test_07_cross_state_economic_write_is_denied(
    economy: NationalEconomy,
    registry: StateRegistry,
    national: NationalRegistry,
    federation: FederalStateGovernment,
    crown: AuthorizationContext,
) -> None:
    """مسؤولُ ولايةٍ أ لا يُنشئ برنامجًا في مؤسسةٍ تابعةٍ لولايةٍ ب."""
    _federal, (state_a, state_b) = _federal_and_states(federation, crown)
    officer = _context("royal", username="cross07")
    chain_a = _authority_chain(
        registry,
        national,
        federation,
        crown,
        officer,
        government_code=state_a["code"],
        scope="STATE",
        operations=("economy.program.create",),
    )
    chain_b = _authority_chain(
        registry,
        national,
        federation,
        crown,
        crown,
        government_code=state_b["code"],
        scope="STATE",
        operations=("economy.program.create",),
        label="مسؤولُ ولايةٍ ب",
    )
    assert chain_a.binding is not None and chain_b.binding is not None

    with pytest.raises(GovernmentAuthorityError):
        economy.create_program(
            officer,
            code=_code("PRG"),
            name="برنامجٌ عبر الحدود",
            institution_code=chain_b.institution["code"],
            scope_level="STATE",
        )

    session = _session()
    try:
        assert session.query(EconomicProgramModel).count() == 0, "لا صفَّ لفعلٍ لم يُخوَّل"
        assert session.query(EconomicDecisionModel).count() == 0, "ولا قرارَ إسنادٍ له"
    finally:
        session.close()


# ── 8. السياسةُ لا تصير نافذةً بمجرّد وجودها (R9-D) ────────────────────────


def test_08_policy_is_not_executable_merely_because_it_exists(
    economy: NationalEconomy,
    registry: StateRegistry,
    national: NationalRegistry,
    federation: FederalStateGovernment,
    crown: AuthorizationContext,
) -> None:
    """السياسةُ تُصدَر مسوّدةً بلا تاريخِ نفاذٍ ولا عمليةِ نفاذٍ ولا منصبٍ مُصدِر."""
    _federal, (state, _other) = _federal_and_states(federation, crown)
    chain = _authority_chain(
        registry,
        national,
        federation,
        crown,
        crown,
        government_code=state["code"],
        scope="STATE",
        operations=("economy.policy.issue",),
    )
    policy = economy.issue_policy(
        crown,
        code=_code("POL"),
        title="سياسةٌ ماليةٌ عامّة",
        policy_type="FISCAL",
        institution_code=chain.institution["code"],
        scope_level="STATE",
    )

    assert policy["status"] == "draft"
    assert policy["effective_from"] is None, "لا نفاذَ بمجرّد الوجود"
    assert policy["activation_operation_id"] is None, "ولا عمليةَ نفاذٍ مُخترَعة"
    assert policy["issuing_identity_id"] is None
    assert policy["version"] == 1


# ── 9. نفاذُ السياسة فعلٌ ثانٍ يمرّ بالنواة التنفيذية (R9-D/R9-O) ───────────


def test_09_policy_activation_requires_second_authorized_operation(
    economy: NationalEconomy,
    registry: StateRegistry,
    national: NationalRegistry,
    federation: FederalStateGovernment,
    crown: AuthorizationContext,
) -> None:
    """النفاذُ يُثبِت مهمّةً حقيقيةً وعمليةً حكوميةً وهويةً ومنصبًا في الصفّ."""
    _federal, (state, _other) = _federal_and_states(federation, crown)
    officer = _context("royal", username="pol09")
    chain = _authority_chain(
        registry,
        national,
        federation,
        crown,
        officer,
        government_code=state["code"],
        scope="STATE",
        operations=("economy.policy.issue", "economy.policy.activate"),
    )
    _worker()
    policy = economy.issue_policy(
        officer,
        code=_code("POL"),
        title="سياسةُ دعمٍ قطاعية",
        policy_type="SUBSIDY",
        institution_code=chain.institution["code"],
        scope_level="STATE",
    )
    activated = economy.activate_policy(officer, policy_code=policy["code"])

    assert activated["status"] == "active"
    assert activated["effective_from"] is not None
    assert activated["activation_operation_id"], "النفاذُ يُثبِت عمليةً حقيقية"
    assert activated["issuing_identity_id"] == chain.identity["id"]
    assert activated["issuing_position_id"] == chain.position["id"]
    assert activated["task_id"], "التنفيذُ بمهمّةٍ في الطابور القائم"

    session = _session()
    try:
        operation = session.get(GovernmentOperationModel, activated["activation_operation_id"])
        assert operation is not None and operation.kind == "TASK"
        assert operation.task_id == activated["task_id"], "الأثرُ يشير إلى المهمّة بعينها"
    finally:
        session.close()


# ── 10. الإيرادُ تعريفٌ لا تحصيل (R9-E) ────────────────────────────────────


def test_10_revenue_source_is_definition_not_collection(
    economy: NationalEconomy,
    registry: StateRegistry,
    national: NationalRegistry,
    federation: FederalStateGovernment,
    crown: AuthorizationContext,
) -> None:
    """مصدرُ الإيراد يُسجَّل بحالةِ تحصيلٍ غيرِ متوفّرة، ولا تُقبل ترقيتُها."""
    _federal, (state, _other) = _federal_and_states(federation, crown)
    chain = _authority_chain(
        registry,
        national,
        federation,
        crown,
        crown,
        government_code=state["code"],
        scope="STATE",
        operations=("economy.revenue.register",),
    )
    source = economy.register_revenue_source(
        crown,
        code=_code("REV"),
        name="ضريبةُ قيمةٍ مضافة",
        revenue_kind="TAX",
        basis="نسبةٌ من القيمة",
        institution_code=chain.institution["code"],
        scope_level="STATE",
    )
    assert source["collection_status"] == "UNAVAILABLE"
    assert source["revenue_kind"] == "TAX"

    with pytest.raises(EconomicStateError):
        economy.register_revenue_source(
            crown,
            code=_code("REV"),
            name="ضريبةٌ محصَّلة",
            revenue_kind="TAX",
            basis="نسبة",
            institution_code=chain.institution["code"],
            scope_level="STATE",
            collection_status="REAL",
        )


# ── 11. إجازةُ الإنفاق تُكتب بلا حركةِ مال (R9-F) ──────────────────────────


def test_11_expenditure_authorization_moves_no_money(
    economy: NationalEconomy,
    registry: StateRegistry,
    national: NationalRegistry,
    federation: FederalStateGovernment,
    treasury: StateTreasury,
    crown: AuthorizationContext,
) -> None:
    """الإجازةُ حالتُها `authorized` وبلا مرجعِ حركة، وعددُ حركات الخزانة لا يزيد."""
    _federal, (state, _other) = _federal_and_states(federation, crown)
    chain = _authority_chain(
        registry,
        national,
        federation,
        crown,
        crown,
        government_code=state["code"],
        scope="INSTITUTION",
        operations=("economy.program.create", "economy.expenditure.authorize"),
        max_amount="10000.0000",
    )
    money = _treasury_chain(treasury, crown, chain.institution["code"], chain.official["id"])
    program = _program(economy, crown, chain, "INSTITUTION")

    session = _session()
    try:
        before = session.query(TransactionModel).count()
    finally:
        session.close()

    authorization = economy.authorize_expenditure(
        crown,
        program_code=program["code"],
        allocation_id=money["allocation"]["id"],
        institution_code=chain.institution["code"],
        scope_level="INSTITUTION",
        amount=Decimal("1500.5000"),
        purpose="تشغيلُ برنامج",
    )

    assert authorization["status"] == "authorized"
    assert authorization["transaction_reference"] is None, "لا مرجعَ حركةٍ قبل التنفيذ"
    assert authorization["amount"] == Decimal("1500.5000"), "الدقّةُ العشرية محفوظة"

    session = _session()
    try:
        assert session.query(TransactionModel).count() == before, "لا حركةَ مالٍ كُتبت"
    finally:
        session.close()


# ── 12. التنفيذُ بالخزانة القائمة وحدَها (R9-F/R9-L) ───────────────────────


def test_12_expenditure_execution_uses_the_canonical_treasury(
    economy: NationalEconomy,
    registry: StateRegistry,
    national: NationalRegistry,
    federation: FederalStateGovernment,
    treasury: StateTreasury,
    crown: AuthorizationContext,
) -> None:
    """التنفيذُ يكتب حركةً في `state_transactions` القائم ويربطها بالإجازة."""
    _federal, (state, _other) = _federal_and_states(federation, crown)
    officer = _context("royal", username="exp12")
    chain = _authority_chain(
        registry,
        national,
        federation,
        crown,
        officer,
        government_code=state["code"],
        scope="INSTITUTION",
        operations=(
            "economy.program.create",
            "economy.expenditure.authorize",
            "treasury.disbursement.post",
        ),
        max_amount="10000.0000",
    )
    money = _treasury_chain(treasury, crown, chain.institution["code"], chain.official["id"])
    program = _program(economy, officer, chain, "INSTITUTION")
    authorization = economy.authorize_expenditure(
        officer,
        program_code=program["code"],
        allocation_id=money["allocation"]["id"],
        institution_code=chain.institution["code"],
        scope_level="INSTITUTION",
        amount=Decimal("1200.0000"),
        purpose="صرفُ برنامج",
    )

    session = _session()
    try:
        before = session.query(TransactionModel).count()
    finally:
        session.close()

    executed = economy.execute_expenditure(
        officer,
        treasury=treasury,
        reference=authorization["reference"],
        expense_account_code=money["expense"]["code"],
    )

    assert executed["status"] == "executed"
    assert executed["transaction_reference"] == executed["transaction"]["reference"]
    assert executed["operation_id"], "لكلِّ صرفٍ أثرُ عمليةٍ حكوميّ"

    session = _session()
    try:
        assert session.query(TransactionModel).count() == before + 1, "حركةٌ واحدةٌ في دفترٍ واحد"
        operation = session.get(GovernmentOperationModel, executed["operation_id"])
        assert operation is not None and operation.kind == "TREASURY"
        assert operation.transaction_reference == executed["transaction_reference"]
    finally:
        session.close()


# ── 13. صرفٌ بلا مِنحةِ خزانةٍ مرفوض (R9-L/R9-M) ───────────────────────────


def test_13_unauthorized_treasury_operation_is_denied_and_leaves_no_trace(
    economy: NationalEconomy,
    registry: StateRegistry,
    national: NationalRegistry,
    federation: FederalStateGovernment,
    treasury: StateTreasury,
    crown: AuthorizationContext,
) -> None:
    """إجازةُ الإنفاق لا تُغني عن مِنحةِ الصرف: التنفيذُ يُرفَض وتبقى الإجازةُ كما هي."""
    _federal, (state, _other) = _federal_and_states(federation, crown)
    officer = _context("royal", username="deny13")
    chain = _authority_chain(
        registry,
        national,
        federation,
        crown,
        officer,
        government_code=state["code"],
        scope="INSTITUTION",
        operations=("economy.program.create", "economy.expenditure.authorize"),
        max_amount="10000.0000",
    )
    money = _treasury_chain(treasury, crown, chain.institution["code"], chain.official["id"])
    program = _program(economy, officer, chain, "INSTITUTION")
    authorization = economy.authorize_expenditure(
        officer,
        program_code=program["code"],
        allocation_id=money["allocation"]["id"],
        institution_code=chain.institution["code"],
        scope_level="INSTITUTION",
        amount=Decimal("900.0000"),
        purpose="صرفٌ بلا مِنحة",
    )

    with pytest.raises((GovernmentAuthorityError, RegistryAuthorizationError)):
        economy.execute_expenditure(
            officer,
            treasury=treasury,
            reference=authorization["reference"],
            expense_account_code=money["expense"]["code"],
        )

    session = _session()
    try:
        row = session.query(ExpenditureAuthorizationModel).one()
        assert row.status == "authorized" and row.transaction_reference is None
        assert session.query(TransactionModel).count() == 1, "لا حركةَ صرفٍ بعد التمويل"
    finally:
        session.close()


# ── 14-15. المِنحُ والدعمُ فوق الخزانة نفسِها (R9-I) ───────────────────────


@pytest.mark.parametrize(
    ("transfer_kind", "operation"),
    [("GRANT", "economy.grant.authorize"), ("SUBSIDY", "economy.subsidy.authorize")],
)
def test_14_transfers_are_authorized_then_paid_by_treasury(
    economy: NationalEconomy,
    registry: StateRegistry,
    national: NationalRegistry,
    federation: FederalStateGovernment,
    treasury: StateTreasury,
    crown: AuthorizationContext,
    transfer_kind: str,
    operation: str,
) -> None:
    """المِنحةُ والدعمُ يُجازان بعمليتهما، ويُصرفان بواجهة الخزانة لا بمحرّكٍ ثانٍ."""
    _federal, (state, _other) = _federal_and_states(federation, crown)
    officer = _context("royal", username=f"trf-{transfer_kind.lower()}")
    chain = _authority_chain(
        registry,
        national,
        federation,
        crown,
        officer,
        government_code=state["code"],
        scope="INSTITUTION",
        operations=("economy.program.create", operation, "treasury.disbursement.post"),
        max_amount="10000.0000",
    )
    money = _treasury_chain(treasury, crown, chain.institution["code"], chain.official["id"])
    program = _program(economy, officer, chain, "INSTITUTION")
    beneficiary = national.create_identity(
        context=crown, identity_type="PERSON", label="مستفيدٌ حقيقيّ"
    )

    transfer = economy.authorize_transfer(
        officer,
        transfer_kind=transfer_kind,
        program_code=program["code"],
        beneficiary_identity_id=beneficiary["id"],
        allocation_id=money["allocation"]["id"],
        institution_code=chain.institution["code"],
        scope_level="INSTITUTION",
        amount=Decimal("750.2500"),
        purpose="تحويلٌ مُجاز",
    )
    assert transfer["transfer_kind"] == transfer_kind
    assert transfer["status"] == "authorized" and transfer["transaction_reference"] is None
    assert transfer["decision"]["operation"] == operation, "العمليةُ تُشتَقّ من نوع التحويل"

    paid = economy.execute_transfer(
        officer,
        treasury=treasury,
        reference=transfer["reference"],
        expense_account_code=money["expense"]["code"],
    )
    assert paid["status"] == "executed"
    assert paid["transaction_reference"] == paid["transaction"]["reference"]
    assert paid["amount"] == Decimal("750.2500"), "الدقّةُ العشرية محفوظةٌ عبر الخزانة"


def test_15_transfer_beneficiary_must_be_a_canonical_identity(
    economy: NationalEconomy,
    registry: StateRegistry,
    national: NationalRegistry,
    federation: FederalStateGovernment,
    treasury: StateTreasury,
    crown: AuthorizationContext,
) -> None:
    """مستفيدٌ لا هويةَ له في السجلّ الكانونيّ لا تُجاز له مِنحة."""
    _federal, (state, _other) = _federal_and_states(federation, crown)
    chain = _authority_chain(
        registry,
        national,
        federation,
        crown,
        crown,
        government_code=state["code"],
        scope="INSTITUTION",
        operations=("economy.program.create", "economy.grant.authorize"),
        max_amount="10000.0000",
    )
    money = _treasury_chain(treasury, crown, chain.institution["code"], chain.official["id"])
    program = _program(economy, crown, chain, "INSTITUTION")

    with pytest.raises(EconomicEntityNotFoundError):
        economy.authorize_transfer(
            crown,
            transfer_kind="GRANT",
            program_code=program["code"],
            beneficiary_identity_id="idn-does-not-exist",
            allocation_id=money["allocation"]["id"],
            institution_code=chain.institution["code"],
            scope_level="INSTITUTION",
            amount=Decimal("100.0000"),
            purpose="مِنحةٌ لمستفيدٍ مُخترَع",
        )


# ── 16. الأصولُ: مُسجَّلةٌ في النظام لا مملوكةٌ قانونًا (R9-G) ──────────────


def test_16_public_asset_registration_claims_no_external_ownership(
    economy: NationalEconomy,
    registry: StateRegistry,
    national: NationalRegistry,
    federation: FederalStateGovernment,
    crown: AuthorizationContext,
) -> None:
    """الأصلُ يُسجَّل `SYSTEM_REGISTERED` وملكيتُه الخارجية `UNAVAILABLE` دائمًا."""
    _federal, (state, _other) = _federal_and_states(federation, crown)
    chain = _authority_chain(
        registry,
        national,
        federation,
        crown,
        crown,
        government_code=state["code"],
        scope="STATE",
        operations=("economy.asset.register",),
    )
    custodian = national.create_identity(context=crown, identity_type="PERSON", label="أمينُ أصل")
    asset = economy.register_public_asset(
        crown,
        code=_code("AST"),
        name="أرضٌ حكومية",
        asset_class="LAND",
        institution_code=chain.institution["code"],
        scope_level="STATE",
        custodian_identity_id=custodian["id"],
        book_value=Decimal("125000.0000"),
        currency="SAR",
    )
    assert asset["registration_class"] == "SYSTEM_REGISTERED"
    assert asset["external_ownership_status"] == "UNAVAILABLE"
    assert asset["book_value"] == Decimal("125000.0000")
    assert asset["custodian_identity_id"] == custodian["id"]


# ── 17. الالتزامُ: دائنٌ حقيقيٌّ ولا نفاذَ خارجيًّا (R9-H) ─────────────────


def test_17_public_liability_requires_real_creditor_and_claims_no_enforceability(
    economy: NationalEconomy,
    registry: StateRegistry,
    national: NationalRegistry,
    federation: FederalStateGovernment,
    crown: AuthorizationContext,
) -> None:
    """الدائنُ هويةٌ كانونية، والنفاذُ الخارجيُّ يُقال غيرَ متوفّرٍ لا مُثبَتًا."""
    _federal, (state, _other) = _federal_and_states(federation, crown)
    chain = _authority_chain(
        registry,
        national,
        federation,
        crown,
        crown,
        government_code=state["code"],
        scope="STATE",
        operations=("economy.liability.register",),
        max_amount="1000000.0000",
    )
    creditor = national.create_identity(
        context=crown, identity_type="ORGANIZATION", label="دائنٌ مؤسّسيّ"
    )
    liability = economy.register_public_liability(
        crown,
        code=_code("LIA"),
        name="سندُ تنميةٍ داخليّ",
        liability_class="BOND",
        institution_code=chain.institution["code"],
        scope_level="STATE",
        creditor_identity_id=creditor["id"],
        principal_amount=Decimal("50000.0000"),
    )
    assert liability["external_enforceability"] == "UNAVAILABLE"
    assert liability["creditor_identity_id"] == creditor["id"]
    assert liability["status"] == "outstanding"

    with pytest.raises(EconomicEntityNotFoundError):
        economy.register_public_liability(
            crown,
            code=_code("LIA"),
            name="التزامٌ لدائنٍ مُخترَع",
            liability_class="LOAN",
            institution_code=chain.institution["code"],
            scope_level="STATE",
            creditor_identity_id="idn-fabricated",
            principal_amount=Decimal("10.0000"),
        )


# ── 18. المشترياتُ تجريدٌ داخليٌّ لا سوق (R9-J) ────────────────────────────


def test_18_procurement_is_an_internal_abstraction_only(
    economy: NationalEconomy,
    registry: StateRegistry,
    national: NationalRegistry,
    federation: FederalStateGovernment,
    crown: AuthorizationContext,
) -> None:
    """المشترياتُ تُجاز بواجهةٍ داخليةٍ وحالةُ السوق الخارجيّ `UNAVAILABLE`."""
    _federal, (state, _other) = _federal_and_states(federation, crown)
    chain = _authority_chain(
        registry,
        national,
        federation,
        crown,
        crown,
        government_code=state["code"],
        scope="INSTITUTION",
        operations=("economy.program.create", "economy.procurement.authorize"),
        max_amount="100000.0000",
    )
    program = _program(economy, crown, chain, "INSTITUTION")
    supplier = national.create_identity(
        context=crown, identity_type="ORGANIZATION", label="مورِّدٌ مسجَّل"
    )
    procurement = economy.authorize_procurement(
        crown,
        title="توريدُ معدّات",
        program_code=program["code"],
        institution_code=chain.institution["code"],
        scope_level="INSTITUTION",
        supplier_identity_id=supplier["id"],
        estimated_amount=Decimal("4000.0000"),
        specification="مواصفةٌ مكتوبة",
    )
    assert procurement["backend"] == "INTERNAL_ABSTRACTION"
    assert procurement["external_market_status"] == "UNAVAILABLE"
    assert procurement["status"] == "authorized"


# ── 19. مِنحةٌ مُلغاةٌ تُرفَض (R9-M) ───────────────────────────────────────


def test_19_revoked_authority_is_denied(
    economy: NationalEconomy,
    registry: StateRegistry,
    national: NationalRegistry,
    federation: FederalStateGovernment,
    crown: AuthorizationContext,
) -> None:
    """مَن أُلغيت مِنحتُه لا يُنشئ برنامجًا، ولو كان قد أنشأ واحدًا قبل الإلغاء."""
    _federal, (state, _other) = _federal_and_states(federation, crown)
    officer = _context("royal", username="rev19")
    chain = _authority_chain(
        registry,
        national,
        federation,
        crown,
        officer,
        government_code=state["code"],
        scope="STATE",
        operations=("economy.program.create",),
    )
    first = _program(economy, officer, chain, "STATE")
    assert first["status"] == "draft"

    national.revoke_authority(
        context=crown,
        grant_id=chain.grants["economy.program.create"]["id"],
        reason="انتهاءُ التكليف",
    )

    with pytest.raises(GovernmentAuthorityError):
        _program(economy, officer, chain, "STATE")


# ── 20. جلسةٌ منتهيةٌ تُرفَض قبل أيّ قراءة (R9-M) ──────────────────────────


def test_20_expired_session_is_denied_before_any_write(
    economy: NationalEconomy,
    registry: StateRegistry,
    national: NationalRegistry,
    federation: FederalStateGovernment,
    crown: AuthorizationContext,
) -> None:
    """سلطةٌ انتهى وقتُها ليست سلطة — والرفضُ قبل فتح الجلسة."""
    _federal, (state, _other) = _federal_and_states(federation, crown)
    expired = _context(
        "royal", username="exp20", expires_at=datetime.now(UTC) - timedelta(minutes=1)
    )
    chain = _authority_chain(
        registry,
        national,
        federation,
        crown,
        crown,
        government_code=state["code"],
        scope="STATE",
        operations=("economy.program.create",),
    )

    with pytest.raises(SessionInvalidError):
        economy.create_program(
            expired,
            code=_code("PRG"),
            name="برنامجٌ بجلسةٍ منتهية",
            institution_code=chain.institution["code"],
            scope_level="STATE",
        )

    session = _session()
    try:
        assert session.query(EconomicProgramModel).count() == 0
    finally:
        session.close()


# ── 21. الإسنادُ يُقال كما هو: PROVEN أو PARTIAL أو UNRESOLVED (R9-N) ──────


def test_21_provenance_is_reported_not_fabricated(
    economy: NationalEconomy,
    registry: StateRegistry,
    national: NationalRegistry,
    federation: FederalStateGovernment,
    crown: AuthorizationContext,
) -> None:
    """قرارٌ بسلسلةٍ كاملةٍ `PROVEN`، وأيُّ حلقةٍ ناقصةٍ تُذكر بالاسم لا تُملأ."""
    _federal, (state, _other) = _federal_and_states(federation, crown)
    officer = _context("royal", username="prov21")
    chain = _authority_chain(
        registry,
        national,
        federation,
        crown,
        officer,
        government_code=state["code"],
        scope="STATE",
        operations=("economy.program.create",),
    )
    program = _program(economy, officer, chain, "STATE")
    file = economy.decision_file(officer, decision_reference=program["decision"]["reference"])

    assert file["identity_id"] == chain.identity["id"]
    assert file["official_id"] == chain.official["id"]
    assert file["position_id"] == chain.position["id"]
    assert file["grant_id"] == chain.grants["economy.program.create"]["id"]
    assert file["provenance"] == "PROVEN"
    assert file["provenance_missing_links"] == []
    assert file["execution_evidence"]["task_id"] is None, "قرارٌ لم يُنفَّذ لا يُدَّعى له تنفيذ"


# ── 22. تنفيذُ القرار الاقتصاديّ بالنواة القائمة (R9-K/R9-O) ───────────────


def test_22_economic_decision_executes_through_executive_core(
    economy: NationalEconomy,
    registry: StateRegistry,
    national: NationalRegistry,
    federation: FederalStateGovernment,
    crown: AuthorizationContext,
) -> None:
    """القرارُ يُنفَّذ بمهمّةٍ في `tasks` القائم وأثرٍ في جدول العمليات القائم."""
    _federal, (state, _other) = _federal_and_states(federation, crown)
    officer = _context("royal", username="core22")
    chain = _authority_chain(
        registry,
        national,
        federation,
        crown,
        officer,
        government_code=state["code"],
        scope="STATE",
        operations=("economy.program.create",),
    )
    _worker()
    program = _program(economy, officer, chain, "STATE")
    executed = economy.execute_economic_decision(
        officer, decision_reference=program["decision"]["reference"]
    )

    assert executed["status"] == "executed"
    assert executed["task"]["id"].startswith("task-")
    assert executed["operation"]["kind"] == "TASK"
    assert executed["task_id"] == executed["task"]["id"]

    with pytest.raises(EconomicStateError):
        economy.execute_economic_decision(
            officer, decision_reference=program["decision"]["reference"]
        )


# ── 23. الوكيلُ يُخوَّل بهويته لا بكونه وكيلًا (R9-M) ──────────────────────


def test_23_agent_economic_authorization_flows_through_identity(
    economy: NationalEconomy,
    registry: StateRegistry,
    national: NationalRegistry,
    federation: FederalStateGovernment,
    crown: AuthorizationContext,
) -> None:
    """الوكيلُ المربوطُ بهويةٍ ذاتِ منصبٍ ومِنحةٍ يمرّ، ومِنحتُه هي التي تُقرأ."""
    _federal, (state, _other) = _federal_and_states(federation, crown)
    officer = _context("royal", username="agent23")
    chain = _authority_chain(
        registry,
        national,
        federation,
        crown,
        officer,
        government_code=state["code"],
        scope="STATE",
        operations=("economy.program.create",),
    )
    program = _program(economy, officer, chain, "STATE")

    session = _session()
    try:
        link = (
            session.query(IdentityAgentModel)
            .filter(IdentityAgentModel.identity_id == chain.identity["id"])
            .one()
        )
        assert link.agent_id == chain.agent_id, "الوكيلُ مربوطٌ بهويةِ صاحب القرار"
    finally:
        session.close()
    assert program["decision"]["identity_id"] == chain.identity["id"]


# ── 24. سيادةُ التاج لا تُنتحَل بادّعاء دور (R9-S) ────────────────────────


def test_24_crown_authority_cannot_be_claimed_by_role_alone(
    economy: NationalEconomy,
    registry: StateRegistry,
    national: NationalRegistry,
    federation: FederalStateGovernment,
    crown: AuthorizationContext,
) -> None:
    """سياقٌ بدور `king` بلا جلسةٍ مُتحقَّقةٍ لا يمرّ — الدورُ ليس مصادقة."""
    _federal, (state, _other) = _federal_and_states(federation, crown)
    chain = _authority_chain(
        registry,
        national,
        federation,
        crown,
        crown,
        government_code=state["code"],
        scope="STATE",
        operations=("economy.program.create",),
    )
    impostor = AuthorizationContext(
        principal_id="impostor-king",
        verification=PrincipalVerification.UNVERIFIED,
        principal_kind=PrincipalKind.ANONYMOUS,
        role="king",
        permissions=("*",),
        session_id=None,
    )

    with pytest.raises(PrincipalUnverifiedError):
        economy.create_program(
            impostor,
            code=_code("PRG"),
            name="برنامجُ منتحلٍ للتاج",
            institution_code=chain.institution["code"],
            scope_level="STATE",
        )


# ── 25. انتحالُ منصبٍ لا يملكه المستدعي يُرفَض (R9-C/R9-M) ─────────────────


def test_25_forged_official_claim_is_rejected(
    economy: NationalEconomy,
    registry: StateRegistry,
    national: NationalRegistry,
    federation: FederalStateGovernment,
    crown: AuthorizationContext,
) -> None:
    """مَن يدّعي مسؤولًا ليس هو يُرفَض، ولا يُكتب له صفٌّ ولا قرار."""
    _federal, (state, _other) = _federal_and_states(federation, crown)
    officer = _context("royal", username="forge25")
    chain = _authority_chain(
        registry,
        national,
        federation,
        crown,
        officer,
        government_code=state["code"],
        scope="STATE",
        operations=("economy.program.create",),
    )
    other = _authority_chain(
        registry,
        national,
        federation,
        crown,
        crown,
        government_code=state["code"],
        scope="STATE",
        operations=("economy.program.create",),
        label="مسؤولٌ آخر",
    )

    with pytest.raises(Exception) as excinfo:
        economy.create_program(
            officer,
            code=_code("PRG"),
            name="برنامجٌ بمنصبٍ منتحل",
            institution_code=chain.institution["code"],
            scope_level="STATE",
            claimed_official_id=other.official["id"],
        )
    assert excinfo.type.__name__ in {
        "ForgedAuthorityError",
        "GovernmentAuthorityError",
        "IdentityResolutionError",
    }

    session = _session()
    try:
        assert session.query(EconomicProgramModel).count() == 0
    finally:
        session.close()


# ── 26. حدُّ المستأجر محفوظٌ وSINGLE_TENANT مُعلَنٌ كما هو (R9-R) ──────────


def test_26_tenant_boundary_is_enforced_on_economic_reads(
    economy: NationalEconomy,
    registry: StateRegistry,
    national: NationalRegistry,
    federation: FederalStateGovernment,
    crown: AuthorizationContext,
) -> None:
    """قرارُ مستأجرٍ لا يُقرأ من مستأجرٍ آخر، والنظامُ يُعلن نفسه أحاديَّ المستأجر."""
    _federal, (state, _other) = _federal_and_states(federation, crown)
    chain = _authority_chain(
        registry,
        national,
        federation,
        crown,
        crown,
        government_code=state["code"],
        scope="STATE",
        operations=("economy.program.create",),
    )
    program = _program(economy, crown, chain, "STATE")
    stranger = _context("royal", username="tenant26", tenant_id="tenant-other")

    with pytest.raises((EconomicEntityNotFoundError, RegistryAuthorizationError)):
        economy.decision_file(stranger, decision_reference=program["decision"]["reference"])

    health = economy.economy_health(crown)
    assert health["single_tenant"] is True
    assert health["tenant_id"] == DEFAULT_TENANT


# ── 27. الحدثُ والمُدقَّقُ مرتبطان بالقرار نفسِه (R9-P) ────────────────────


def test_27_events_and_audit_are_correlated_with_the_decision(
    economy: NationalEconomy,
    registry: StateRegistry,
    national: NationalRegistry,
    federation: FederalStateGovernment,
    crown: AuthorizationContext,
) -> None:
    """كلُّ فعلٍ اقتصاديٍّ يُعيد `audit_id` و`event_id` حقيقيَّين، وللحدث عقدٌ مُسجَّل."""
    _federal, (state, _other) = _federal_and_states(federation, crown)
    chain = _authority_chain(
        registry,
        national,
        federation,
        crown,
        crown,
        government_code=state["code"],
        scope="STATE",
        operations=("economy.program.create",),
    )
    program = _program(economy, crown, chain, "STATE")

    assert program["audit_id"] and program["event_id"]
    assert "amos_federation.economy.program_created" in EVENT_CONTRACTS
    entries = PersistentAuditStore().list_all(limit=200)
    matched = [e for e in entries if e["audit_id"] == program["audit_id"]]
    assert matched, "سجلُّ التدقيق يحمل الأثرَ المُعاد لا رقمًا مُخترعًا"
    assert matched[0]["action"] == "economy.program.create"


def test_28_every_economic_event_subject_has_a_contract() -> None:
    """كلُّ موضوعٍ اقتصاديٍّ يُعلَن له عقدٌ في المفردة القائمة — لا حدثَ بلا عقد."""
    subjects = {name for name in EVENT_CONTRACTS if name.startswith("amos_federation.economy.")}
    assert len(subjects) >= 14, "أربعةَ عشرَ عقدًا اقتصاديًّا على الأقلّ"
    for subject in subjects:
        contract = EVENT_CONTRACTS[subject]
        assert "operation" in contract["required_fields"]
        assert "classification" in contract["required_fields"]
        assert "actor" in contract["required_fields"], "لا حدثَ بلا فاعلٍ حقيقيّ"


# ── 29. حرسٌ ساكن: لا نظامَ ماليٍّ ولا منفِّذَ ولا ناقلَ أحداثٍ ثانيًا ──────


def test_29_no_second_ledger_executor_or_event_bus_in_r9_sources() -> None:
    """R9 لا تُنشئ خزانةً ولا دفترًا ولا منفِّذًا ولا ناقلَ أحداثٍ بديلًا."""
    sources = _r9_sources()
    joined = "\n".join(sources.values())
    forbidden = (
        "economic_executor",
        "economic_worker",
        "treasury_executor_v2",
        "policy_executor",
        "class LedgerEntry",
        "state_ledger_entries",
        "shadow_balance",
        "EventBus(",
    )
    for token in forbidden:
        assert token not in joined, f"طريقٌ ثانٍ ظهر في مصادر R9: {token}"
    assert (
        "from amos_federation.services.state_treasury.service import" not in joined
    ), "الخزانةُ تُمرَّر وسيطًا ولا تُستورَد في هذه الطبقة"
    assert "get_executive_core" in sources["service.py"], "التنفيذُ بالنواة القائمة"
    assert "record_domain_trace" in sources["service.py"], "الأثرُ بالمسار القائم"


def test_30_migration_011_operation_vocabulary_matches_the_canonical_tuple() -> None:
    """قوائمُ العمليات في هجرة 011 مطابقةٌ لمفردة R7-C — لا مفردةَ ثانيةً تنحرف."""
    sql = _MIGRATION_011.read_text(encoding="utf-8")
    assert _MIGRATION_011.exists()
    for constraint in (
        "ck_state_authority_grants_operation",
        "ck_state_transaction_authority_operation",
        "ck_state_government_delegations_operation",
    ):
        assert constraint in sql, f"القيدُ غائبٌ عن الهجرة: {constraint}"
        listed: set[str] = set()
        for match in re.finditer(re.escape(constraint), sql):
            window = sql[match.start() : match.start() + 3000]
            listed |= set(re.findall(r"'([a-z]+\.[a-z.]+)'", window))
        expected = set(GRANTABLE_OPERATIONS)
        assert expected.issubset(
            listed
        ), f"{constraint} لا يغطّي المفردة الكانونية: {sorted(expected - listed)}"
        assert set(ECONOMIC_OPERATIONS).issubset(listed), "العملياتُ الاقتصادية غائبةٌ عن القيد"


def test_31_economic_operations_are_the_only_operations_accepted() -> None:
    """طبقةُ الاقتصاد ترفض عمليةً ليست اقتصادية، ولا تُوسِّع المفردةَ عند النداء."""
    from amos_federation.services.national_economy.authorization import assert_economic_operation

    for operation in ECONOMIC_OPERATIONS:
        assert_economic_operation(operation)
    for operation in ("treasury.disbursement.post", "gov.case.decide", "economy.made.up"):
        with pytest.raises(EconomicAuthorizationError):
            assert_economic_operation(operation)


def test_32_capability_classifications_are_stated_honestly(
    economy: NationalEconomy, crown: AuthorizationContext
) -> None:
    """التصنيفاتُ تُقال كما هي: ما لا يوجد يُقال `UNAVAILABLE` ولا يُرقّى بالنصّ."""
    registry_view = economy.economic_registry(crown)
    capabilities = registry_view["capabilities"]
    assert capabilities["revenue_collection"] == "UNAVAILABLE"
    assert capabilities["indicator_measurement"] == "UNAVAILABLE"
    assert capabilities["external_asset_ownership"] == "UNAVAILABLE"
    assert capabilities["external_liability_enforceability"] == "UNAVAILABLE"
    assert capabilities["external_procurement_market"] == "UNAVAILABLE"
    assert capabilities["treasury_execution"] == "REAL", "الخزانةُ مُلاحَظةٌ في هذه الحزمة"
    assert capabilities["executive_core_execution"] == "REAL"
    assert set(registry_view["counts"]) >= {"sectors", "programs", "decisions"}
