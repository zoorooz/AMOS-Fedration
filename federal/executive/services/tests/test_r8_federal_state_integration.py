"""
AMOS-Federation R8 — Federal/State Integration: Targeted Tests
الهدف: فحصٌ مركَّزٌ لمحاور R8-Q — بنيةٌ وحدودٌ وتفويضٌ وتنفيذٌ وإسنادٌ وسيادة
النطاق: tests
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17 (R8-Q)

## لماذا اختباراتٌ مركَّزة لا حزمةٌ كاملة

R8-Q تطلب فحوصًا مُوجَّهةً لكل محورٍ لا تشغيلَ النظام كلِّه بعد كل تغيير. فكل
دالّةٍ هنا تُثبت **حقيقةً واحدة** يمكن أن تُكسَر وحدها، وتفشل بسببٍ مقروء.

## ما يُبنى بعملياتٍ حقيقية

لا صفوفَ مزروعةً يدويًّا في جداول السلطة: الهويةُ بـ`create_identity`، والمنصبُ
بـ`create_position`، والتقليدُ بـ`assign_position`، والمِنحةُ بـ`grant_authority`.
فلو كُسر شرطٌ في السلسلة لَفشل الاختبار حيث كُسر، لا حيث نتوقّع.

## الحرسُ الساكن

بعضُ المحاور لا يُثبتها سلوكٌ واحد بل **غيابُ طريقٍ** في المصدر: لا محرّكَ
تخويلٍ ثانٍ، ولا منفِّذَ حكوميٌّ موازٍ، ولا ناقلَ أحداثٍ جديد، ولا دورٌ يُقرأ
كسلطة. فتلك تُفحَص على المصدر بعد نزع التعليقات — لأن هذه الملفّات مملوءةٌ
بتعليقاتٍ تذكر ما تمنعه لتشرح منعَه.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from amos_federation.common.database import get_session_factory, init_db
from amos_federation.common.durable_event_bus import get_durable_event_bus
from amos_federation.common.event_bus import EVENT_CONTRACTS
from amos_federation.common.persistent import PersistentAuditStore
from amos_federation.common.principal import (
    DEFAULT_TENANT,
    AuthorizationContext,
    Principal,
)
from amos_federation.services.executive_core.agent_identity import register_identity
from amos_federation.services.executive_core.dispatcher import WILDCARD, register_agent
from amos_federation.services.executive_core.engine import reset_executive_core
from amos_federation.services.federal_state import (
    DuplicateGovernmentError,
    FederalStateGovernment,
    FederationError,
    GovernmentAuthorityError,
    ScopePoint,
    evaluate_boundary,
    get_federal_state,
    reset_federal_state,
)
from amos_federation.services.federal_state.models import (
    FEDERAL_STATE_TABLES,
    CaseScopeModel,
    GovernmentDelegationModel,
    GovernmentModel,
    GovernmentOperationModel,
    GovernmentRelationModel,
    InstitutionGovernmentModel,
    ServiceScopeModel,
)
from amos_federation.services.governance.security import DEFAULT_ROLES
from amos_federation.services.government_services.models import CaseModel
from amos_federation.services.government_services.service import (
    get_government_services,
    reset_government_services,
)
from amos_federation.services.national_registry.models import (
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

if TYPE_CHECKING:
    from amos_federation.services.government_services.service import GovernmentServices

_ROLE_PERMISSIONS = {role["role_id"]: tuple(role["permissions"]) for role in DEFAULT_ROLES}

_R8_SOURCE_DIR = (
    Path(__file__).resolve().parents[1] / "src" / "amos_federation" / "services" / "federal_state"
)


def _strip_comments(source: str) -> str:
    """أزِل التعليقات وسلاسل التوثيق قبل أيّ تأكيدٍ على المصدر.

    مصادرُ R8 تذكر `role="governor"` و«محرّكٌ ثانٍ» في تعليقاتها لتشرح **منعَها**
    — فلو لم تُنزَع لَفشل الحرسُ على شرحِ نفسه.
    """
    no_docstrings = re.sub(r'"""(?:.|\n)*?"""', "", source)
    return "\n".join(line.split("#", 1)[0] for line in no_docstrings.splitlines())


def _r8_sources() -> dict[str, str]:
    return {
        path.name: _strip_comments(path.read_text(encoding="utf-8"))
        for path in sorted(_R8_SOURCE_DIR.glob("*.py"))
    }


def _context(
    role_id: str,
    *,
    tenant_id: str | None = None,
    username: str = "r8-user",
) -> AuthorizationContext:
    """سياق `SESSION_VERIFIED` بصلاحيات الدور كما زُرعت — لا كما يشتهي الاختبار."""
    return AuthorizationContext.from_principal(
        Principal.from_session_record(
            session_id=f"r8-{role_id}-{username}",
            username=username,
            role_id=role_id,
            permissions=_ROLE_PERMISSIONS[role_id],
            expires_at=None,
            tenant_id=tenant_id,
        )
    )


@pytest.fixture(autouse=True)
def _fresh_state() -> None:
    """قاعدةٌ نظيفةٌ من صفوف النطاق قبل كل اختبار — الملفّ مشتركٌ بينها.

    الترتيبُ ترتيبُ القيود المرجعية نفسه: أثرُ العملية قبل الإسناد، والإسنادُ قبل
    القضية والخدمة، والتفويضُ قبل الحكومة، والربطُ قبل المؤسسة.
    """
    init_db()
    session = get_session_factory()()
    try:
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
def services() -> GovernmentServices:
    return get_government_services()


@pytest.fixture
def federation() -> FederalStateGovernment:
    return get_federal_state()


@pytest.fixture
def crown(national: NationalRegistry) -> AuthorizationContext:
    """التاجُ — `*` فيمرّ في كل حدّ، وله هويةٌ كانونية كأيّ فاعلٍ آخر."""
    context = _context("king", username="crown")
    identity = national.create_identity(context=context, identity_type="PERSON", label="التاج")
    national.link_principal(
        context=context, principal_id=context.principal_id, identity_id=identity["id"]
    )
    return context


def _agent(tenant_id: str = DEFAULT_TENANT) -> str:
    """وكيلٌ حقيقيٌّ في `agents` — سجلّ R4 الكانوني، ولا تُنشئه هذه الطبقة."""
    agent_id = f"agent-r8-{uuid.uuid4().hex[:10]}"
    register_identity(agent_id, f"وكيل {agent_id}", "executor", tenant_id=tenant_id)
    return agent_id


def _worker() -> str:
    worker_id = f"worker-r8-{uuid.uuid4().hex[:8]}"
    register_agent(worker_id, f"عامل {worker_id}", "worker", allowed_tools=[WILDCARD])
    return worker_id


def _code(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def _session():
    return get_session_factory()()


class Chain:
    """سلسلةٌ جاهزة: مؤسسةٌ · مسؤولٌ · هويةٌ · منصبٌ · تقليدٌ · ربطٌ حكوميّ."""

    def __init__(self, **kwargs: object) -> None:
        self.__dict__.update(kwargs)


def _authority_chain(
    registry: StateRegistry,
    national: NationalRegistry,
    federation: FederalStateGovernment,
    crown: AuthorizationContext,
    context: AuthorizationContext,
    *,
    government_code: str | None,
    scope: str = "STATE",
    branch: str = "executive",
    kind: str = "ministry",
    grant_operation: str | None = "gov.case.decide",
    department_code: str | None = None,
    grant_institution: bool | None = None,
) -> Chain:
    """ابنِ سلسلةَ سلطةٍ كاملةً بعملياتٍ حقيقية، مربوطةً بحكومةٍ إن سُمِّيت."""
    institution = registry.register_institution(
        context=crown,
        code=_code("INS"),
        name="وزارةٌ تنفيذية",
        kind=kind,
        branch=branch,
    )
    department = None
    if department_code:
        department = registry.create_department(
            context=crown,
            institution_code=institution["code"],
            code=department_code,
            name="إدارةٌ فرعية",
        )
    agent_id = _agent()
    official = registry.appoint_official(
        context=crown,
        agent_id=agent_id,
        institution_code=institution["code"],
        title="مسؤول",
    )
    identity = national.create_identity(context=crown, identity_type="PERSON", label="مسؤول")
    national.link_principal(
        context=crown, principal_id=context.principal_id, identity_id=identity["id"]
    )
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
    # مِنحةٌ فدراليةٌ مقيَّدةٌ بمؤسسةٍ واحدةٍ ليست فدراليةً بحقيقتها، فالافتراضُ أنّ
    # المستوى الفدراليّ لا يُقيَّد بمؤسسة — وحدُّ الحكومة (R8) هو ما يمنعه من ولايةٍ
    # لا يملكها، لا قيدُ المؤسسة.
    bind_grant_to_institution = (
        (scope != "FEDERAL") if grant_institution is None else grant_institution
    )
    grant = None
    if grant_operation:
        grant = national.grant_authority(
            context=crown,
            position_id=position["id"],
            operation=grant_operation,
            scope=scope,
            institution_id=institution["id"] if bind_grant_to_institution else None,
            department_id=department["id"] if (department and scope == "DEPARTMENT") else None,
        )
    binding = None
    if government_code:
        binding = federation.bind_institution(
            crown,
            institution_code=institution["code"],
            government_code=government_code,
        )
    return Chain(
        institution=institution,
        department=department,
        agent_id=agent_id,
        official=official,
        identity=identity,
        position=position,
        assignment=assignment,
        grant=grant,
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


def _open_case(
    services: GovernmentServices,
    registry: StateRegistry,
    crown: AuthorizationContext,
    chain: Chain,
) -> dict[str, Any]:
    """قضيةٌ حكوميةٌ حقيقيةٌ بخدمةٍ مُعلَنة — من واجهة R7-A/2 لا بصفٍّ مزروع."""
    service = services.publish_service(
        context=crown,
        institution_code=chain.institution["code"],
        code=_code("SRV"),
        name="خدمةٌ حكومية",
    )
    _worker()
    case = services.open_case(
        context=crown,
        institution_code=chain.institution["code"],
        service_code=service["code"],
        applicant_agent_id=chain.agent_id,
        subject="طلبٌ حكوميّ",
        reference=_code("GC"),
    )
    return {"service": service, "case": case}


# ── 1. الولايةُ صفٌّ بمعرِّفٍ مستقرٍّ وعلاقةٍ فدرالية (R8-C) ───────────────


def test_01_state_is_a_row_with_stable_identity_and_federal_relation(
    federation: FederalStateGovernment, crown: AuthorizationContext
) -> None:
    """الولايةُ تُنشأ بمعرِّفٍ ورمزٍ وحالةٍ وطوابعَ وأصلٍ فدراليٍّ مفروض."""
    federal, (state, _other) = _federal_and_states(federation, crown)

    assert federal["level"] == "FEDERAL" and federal["parent_government_id"] is None
    assert state["level"] == "STATE"
    assert state["parent_government_id"] == federal["id"], "الولايةُ مرتبطةٌ بالفدرالية بمفتاح"
    assert state["id"].startswith("gov-") and state["id"] != state["code"], "المعرِّفُ ليس الرمز"
    assert state["status"] == "active"
    assert state["created_at"] and state["updated_at"]
    assert state["audit_id"] and state["event_id"], "أثرٌ مُدقَّقٌ وحدثٌ دائمٌ لكل كتابة"

    # الاسمُ ليس هوية: اسمان متشابهان مسموحان برمزين مختلفين.
    twin = federation.register_government(
        crown,
        code=_code("ST"),
        name=state["name"],
        level="STATE",
        parent_code=federal["code"],
    )
    assert twin["id"] != state["id"]


def test_02_state_requires_a_federal_parent_and_federal_forbids_one(
    federation: FederalStateGovernment, crown: AuthorizationContext
) -> None:
    """لا ولايةٌ معلَّقةٌ في الهواء، ولا حكومةٌ فدراليةٌ تحت أخرى."""
    federal, (state, _) = _federal_and_states(federation, crown)

    with pytest.raises(FederationError, match="parent_code"):
        federation.register_government(crown, code=_code("ST"), name="ولاية", level="STATE")
    with pytest.raises(FederationError, match="لا أصلَ لها"):
        federation.register_government(
            crown, code=_code("FED"), name="فدرالية", level="FEDERAL", parent_code=federal["code"]
        )
    with pytest.raises(FederationError, match="فدرالية"):
        federation.register_government(
            crown,
            code=_code("ST"),
            name="ولايةٌ تحت ولاية",
            level="STATE",
            parent_code=state["code"],
        )


# ── 2. منعُ رمزِ ولايةٍ مكرَّر — في الخدمة وفي القاعدة (R8-C) ─────────────


def test_03_duplicate_state_code_is_refused_twice(
    federation: FederalStateGovernment, crown: AuthorizationContext
) -> None:
    """الرفضُ في الخدمة، ثمّ في القاعدة لمن حاول تجاوزها."""
    federal, (state, _) = _federal_and_states(federation, crown)

    with pytest.raises(DuplicateGovernmentError):
        federation.register_government(
            crown, code=state["code"], name="ولايةٌ أخرى", level="STATE", parent_code=federal["code"]
        )

    session = _session()
    try:
        session.add(
            GovernmentModel(
                id="gov-duplicate-probe",
                code=state["code"],
                name="تجاوزُ الواجهة",
                level="STATE",
                parent_government_id=federal["id"],
                status="active",
                tenant_id=DEFAULT_TENANT,
                created_by="probe",
            )
        )
        with pytest.raises(Exception, match="(?i)unique|constraint|23505"):
            session.commit()
    finally:
        session.rollback()
        session.close()

    session = _session()
    try:
        assert (
            session.query(GovernmentModel).filter(GovernmentModel.code == state["code"]).count()
            == 1
        )
    finally:
        session.close()


# ── 3. حياةُ الحكومة بلا هدمِ تاريخ (R8-C) ────────────────────────────────


def test_04_government_lifecycle_never_destroys_history(
    federation: FederalStateGovernment, crown: AuthorizationContext
) -> None:
    """التعليقُ والحلُّ حالتان بسببٍ مُصرَّح — والصفُّ يبقى قابلًا للقراءة."""
    _federal, (state, _) = _federal_and_states(federation, crown)

    suspended = federation.set_government_status(crown, state["code"], "suspended", "مراجعةٌ إدارية")
    assert suspended["status"] == "suspended" and suspended["previous_status"] == "active"
    assert suspended["status_reason"] == "مراجعةٌ إدارية"

    dissolved = federation.set_government_status(crown, state["code"], "dissolved", "دمجٌ إداريّ")
    assert dissolved["status"] == "dissolved"

    with pytest.raises(FederationError, match="سبب"):
        federation.set_government_status(crown, state["code"], "active", "   ")

    session = _session()
    try:
        row = session.get(GovernmentModel, state["id"])
        assert row is not None, "الحلُّ حالةٌ لا حذف"
        assert row.created_at is not None
    finally:
        session.close()


# ── 4. المؤسسةُ تُربط بحكومةٍ واحدة، وما قبل R8 غيرُ محلول (R8-B) ─────────


def test_05_institution_belongs_to_exactly_one_government(
    registry: StateRegistry,
    federation: FederalStateGovernment,
    crown: AuthorizationContext,
) -> None:
    """ربطٌ واحدٌ لكل مؤسسة، وإعادةُ الربط تحديثٌ لا صفٌّ ثانٍ."""
    _federal, (state_a, state_b) = _federal_and_states(federation, crown)
    institution = registry.register_institution(
        context=crown, code=_code("INS"), name="وزارة", kind="ministry", branch="executive"
    )

    federation.bind_institution(
        crown, institution_code=institution["code"], government_code=state_a["code"]
    )
    federation.bind_institution(
        crown, institution_code=institution["code"], government_code=state_b["code"]
    )

    session = _session()
    try:
        rows = (
            session.query(InstitutionGovernmentModel)
            .filter(InstitutionGovernmentModel.institution_id == institution["id"])
            .all()
        )
        assert len(rows) == 1, "الفريدُ على (مستأجر، مؤسسة) يمنع الانتماءَ المزدوج"
        assert rows[0].government_id == state_b["id"]
    finally:
        session.close()


def test_06_unbound_institution_reads_unresolved_not_a_guess(
    registry: StateRegistry,
    federation: FederalStateGovernment,
    crown: AuthorizationContext,
) -> None:
    """مؤسسةُ ما قبل R8 لا حكومةَ لها — يُقال ذلك ولا يُخمَّن."""
    institution = registry.register_institution(
        context=crown, code=_code("INS"), name="مؤسسةٌ قديمة", kind="registry", branch="executive"
    )
    scope = federation.describe_institution_scope(crown, institution["code"])
    assert scope["government_id"] is None
    assert scope["classification"] == "UNRESOLVED"
    assert scope["chain"] == []


# ── 5. حدودُ النطاق الأربعة — دالّةٌ صافيةٌ واحدة (R8-D) ───────────────────


def test_07_scope_boundaries_are_explicit_and_never_a_ladder() -> None:
    """أربعةُ حدودٍ في دالّةٍ واحدة: فدراليٌّ · ولايةٌ · مؤسسةٌ · إدارة."""
    federal = ScopePoint("FEDERAL", government_id="gov-fed", institution_id="ins-fed")
    state_a = ScopePoint("STATE", government_id="gov-a", institution_id="ins-a")
    state_b = ScopePoint("STATE", government_id="gov-b", institution_id="ins-b")

    assert evaluate_boundary(federal, federal).allowed
    assert not evaluate_boundary(federal, state_a).allowed, "فدراليٌّ لا يبلغ ولايةً بلا تفويض"
    assert not evaluate_boundary(state_a, federal).allowed, "ولايةٌ لا تبلغ الفدرالية"
    assert not evaluate_boundary(state_a, state_b).allowed, "ولايةٌ لا تبلغ ولايةً أخرى"

    institution = ScopePoint("INSTITUTION", government_id="gov-a", institution_id="ins-a")
    other_institution = ScopePoint("INSTITUTION", government_id="gov-a", institution_id="ins-z")
    assert evaluate_boundary(institution, institution).allowed
    assert not evaluate_boundary(institution, other_institution).allowed
    assert not evaluate_boundary(institution, state_a).allowed, "مؤسسةٌ لا تبلغ مستوى الولاية"

    department = ScopePoint(
        "DEPARTMENT", government_id="gov-a", institution_id="ins-a", department_id="dep-1"
    )
    other_department = ScopePoint(
        "DEPARTMENT", government_id="gov-a", institution_id="ins-a", department_id="dep-2"
    )
    assert evaluate_boundary(department, department).allowed
    assert not evaluate_boundary(department, other_department).allowed
    assert not evaluate_boundary(department, institution).allowed, "إدارةٌ لا تبلغ مستوى مؤسستها"

    # والهدفُ بلا حكومةٍ مربوطة يُرفض معلنًا لا يُخمَّن.
    assert "لا حكومةَ مربوطة" in evaluate_boundary(state_a, ScopePoint("STATE")).reason


def test_08_federal_position_cannot_act_on_a_state_target(
    registry: StateRegistry,
    national: NationalRegistry,
    federation: FederalStateGovernment,
    services: GovernmentServices,
    crown: AuthorizationContext,
) -> None:
    """منصبٌ فدراليٌّ بمِنحةٍ غيرِ مقيَّدةٍ بمؤسسة يُرفض على قضيةِ ولاية — ببوّابتين.

    البوّابةُ الأولى أقدمُ من R8: المحرّكُ الكانونيّ (R7-C) يشترط منصبًا نشطًا في
    **مؤسسة الهدف نفسها**، فيرفض قبل أن يُسأل عن حكومةٍ إطلاقًا. وهذه هي الرسالةُ
    التي تُفحَص هنا لأنها هي الواقعُ المُشاهَد، لا ما نتمنّاه.

    والبوّابةُ الثانية حدُّ الحكومة، ويُفحَص صافيًا بعدها: نقطةُ نطاقٍ فدراليةٌ لا
    تبلغ نقطةَ ولاية. فالمنعُ مُثبَتٌ في الطبقتين، وليس مُعوَّلًا على واحدة.
    """
    federal, (state, _) = _federal_and_states(federation, crown)
    officer = _context("official", username="fed8")
    _authority_chain(
        registry,
        national,
        federation,
        crown,
        officer,
        government_code=federal["code"],
        scope="FEDERAL",
    )
    state_side = _authority_chain(
        registry,
        national,
        federation,
        crown,
        _context("official", username="fed8b"),
        government_code=state["code"],
        scope="STATE",
        grant_operation=None,
    )
    bundle = _open_case(services, registry, crown, state_side)

    with pytest.raises(GovernmentAuthorityError) as denied:
        federation.scope_case(officer, case_reference=bundle["case"]["reference"], level="STATE")
    assert "رفضُ المحرّك الكانونيّ" in str(denied.value), "البوّابةُ الأولى محرّكٌ واحدٌ قائم"
    assert denied.value.authority.classification != "PROVEN"
    assert denied.value.authority.delegation_id is None, "لا تفويضَ يُقرأ لمن لا سلطةَ له"

    federal_point = ScopePoint("FEDERAL", government_id=federal["id"])
    state_point = ScopePoint(
        "STATE", government_id=state["id"], institution_id=state_side.institution["id"]
    )
    verdict = evaluate_boundary(federal_point, state_point)
    assert verdict.allowed is False, "وحدُّ الحكومة يرفض أيضًا لو مرّ الأوّل"

    session = _session()
    try:
        assert session.query(CaseScopeModel).count() == 0, "لا صفَّ إسنادٍ لمن رُفض"
    finally:
        session.close()


def test_09_state_a_cannot_act_on_state_b(
    registry: StateRegistry,
    national: NationalRegistry,
    federation: FederalStateGovernment,
    crown: AuthorizationContext,
) -> None:
    """ولايةُ (أ) لا تبلغ مؤسسةَ ولايةِ (ب) — والرفضُ بحدِّ الحكومة نفسه."""
    _federal, (state_a, state_b) = _federal_and_states(federation, crown)
    officer = _context("official", username="st9")
    _authority_chain(
        registry,
        national,
        federation,
        crown,
        officer,
        government_code=state_a["code"],
        scope="STATE",
    )
    foreign = _authority_chain(
        registry,
        national,
        federation,
        crown,
        _context("official", username="st9b"),
        government_code=state_b["code"],
        scope="STATE",
        grant_operation=None,
    )

    preview = federation.authority_preview(
        officer,
        operation="gov.case.decide",
        institution_code=foreign.institution["code"],
        level="STATE",
    )
    assert preview["government_allowed"] is False
    assert preview["government_target_government_id"] == state_b["id"]


def test_10_department_scope_cannot_reach_institution_level(
    registry: StateRegistry,
    national: NationalRegistry,
    federation: FederalStateGovernment,
    crown: AuthorizationContext,
) -> None:
    """منصبُ إدارةٍ لا يحكم على مستوى مؤسستها ولو كان الهدفُ داخلها."""
    _federal, (state, _) = _federal_and_states(federation, crown)
    officer = _context("official", username="dep10")
    chain = _authority_chain(
        registry,
        national,
        federation,
        crown,
        officer,
        government_code=state["code"],
        scope="DEPARTMENT",
        department_code=_code("DEP"),
    )

    allowed = federation.authority_preview(
        officer,
        operation="gov.case.decide",
        institution_code=chain.institution["code"],
        level="DEPARTMENT",
        department_id=chain.department["id"],
    )
    assert allowed["government_allowed"] is True

    widened = federation.authority_preview(
        officer,
        operation="gov.case.decide",
        institution_code=chain.institution["code"],
        level="INSTITUTION",
    )
    assert widened["government_allowed"] is False, "إدارةٌ لا تحكم مستوى مؤسستها"
    assert widened["classification"] != "PROVEN"
    # الرفضُ قد يقع في المحرّك الكانونيّ (هدفُ المِنحة إدارةٌ بعينها) أو في حدِّ
    # الحكومة (توسيعُ نطاق) — والمهمُّ ألّا يقع في «لا شيء».
    assert widened["government_boundary_reason"]

    # والحدُّ نفسه مُثبَتٌ صافيًا: نقطةُ إدارةٍ لا تبلغ نقطةَ مؤسستها.
    holder = ScopePoint(
        "DEPARTMENT",
        government_id=state["id"],
        institution_id=chain.institution["id"],
        department_id=chain.department["id"],
    )
    target = ScopePoint(
        "INSTITUTION", government_id=state["id"], institution_id=chain.institution["id"]
    )
    verdict = evaluate_boundary(holder, target)
    assert verdict.allowed is False and "توسيعُ نطاق" in verdict.reason


# ── 6. الدورُ والعلاقةُ ليسا سلطة (R8-B · R8-H) ───────────────────────────


def test_11_role_string_is_never_authority(
    registry: StateRegistry,
    national: NationalRegistry,
    federation: FederalStateGovernment,
    crown: AuthorizationContext,
) -> None:
    """صلاحياتٌ واسعةٌ بلا منصبٍ ومِنحةٍ لا تمنح حكمًا على مورد."""
    _federal, (state, _) = _federal_and_states(federation, crown)
    chain = _authority_chain(
        registry,
        national,
        federation,
        crown,
        _context("official", username="holder11"),
        government_code=state["code"],
        scope="STATE",
    )

    # `royal` يملك `write:all` و`manage:all` — ولا منصبَ له ولا مِنحة.
    outsider = _context("royal", username="pretender11")
    preview = federation.authority_preview(
        outsider,
        operation="gov.case.decide",
        institution_code=chain.institution["code"],
        level="STATE",
    )
    assert preview["government_allowed"] is False
    assert preview["position_id"] is None

    sources = _r8_sources()
    for name, source in sources.items():
        for forbidden in ('role == "governor"', 'role == "minister"', 'role == "king"'):
            assert forbidden not in source, f"{name} يقرأ دورًا كسلطة"
        assert (
            "context.role" not in source or name == "service.py"
        ), f"{name} لا يقرأ الدورَ إطلاقًا في حلِّ السلطة"
    assert "context.role" not in sources["authority.py"], "حلُّ السلطة لا يعرف الدورَ أصلًا"
    assert "context.role" not in sources["scopes.py"]


def test_12_relations_describe_and_never_grant(
    registry: StateRegistry,
    national: NationalRegistry,
    federation: FederalStateGovernment,
    crown: AuthorizationContext,
) -> None:
    """علاقةُ `governs` بين حكومتين لا تُحوِّل رفضًا إلى قبول."""
    federal, (state, _) = _federal_and_states(federation, crown)
    officer = _context("official", username="rel12")
    chain = _authority_chain(
        registry,
        national,
        federation,
        crown,
        officer,
        government_code=federal["code"],
        scope="FEDERAL",
    )
    target = _authority_chain(
        registry,
        national,
        federation,
        crown,
        _context("official", username="rel12b"),
        government_code=state["code"],
        scope="STATE",
        grant_operation=None,
    )

    relation = federation.record_relation(
        crown,
        from_kind="GOVERNMENT",
        from_ref=federal["id"],
        to_kind="GOVERNMENT",
        to_ref=state["id"],
        relation="governs",
    )
    assert relation["grants_authority"] is False

    preview = federation.authority_preview(
        officer,
        operation="gov.case.decide",
        institution_code=target.institution["code"],
        level="STATE",
    )
    assert preview["government_allowed"] is False, "العلاقةُ وصفٌ لا صلاحية"
    assert preview["government_delegation_id"] is None
    assert chain.institution["id"] != target.institution["id"]

    # وحرسٌ ساكن: جدولُ العلاقات لا يُقرأ في طبقة حلِّ السلطة إطلاقًا.
    sources = _r8_sources()
    assert "GovernmentRelationModel" not in sources["authority.py"]
    assert "GovernmentRelationModel" not in sources["delegation.py"]


# ── 7. التفويضُ الصريح هو الطريقُ الوحيد للعبور (R8-H) ────────────────────


def test_13_explicit_delegation_is_the_only_crossing_and_is_revocable(
    registry: StateRegistry,
    national: NationalRegistry,
    federation: FederalStateGovernment,
    crown: AuthorizationContext,
) -> None:
    """المستوى الفدراليُّ يُعطى بتفويضٍ صريحٍ من الفدرالية، ويُسترَدُّ بنقضه.

    الطريقُ المفحوص هنا هو الطريقُ الوحيدُ القابل للسلوك فعلًا: شاغلُ منصبٍ
    بنطاق `STATE` في مؤسسةٍ تابعةٍ لولاية يطلب حكمًا بمستوىً **فدراليّ**. الحدُّ
    يرفض التوسيع، ولا يعبره إلا صفُّ تفويضٍ من الجذر الفدراليّ إلى ولايته.

    أمّا العبورُ إلى مؤسسةِ ولايةٍ أخرى فمرفوضٌ قبل هذه الطبقة أصلًا: المحرّكُ
    الكانونيّ (R7-C) يشترط منصبًا في مؤسسة الهدف نفسها — وهذا مُثبَتٌ في
    `test_09` و`test_21`، ولم تُخفَّف هذه الطبقةُ ذلك الشرطَ ولا تستطيع.
    """
    federal, (state, _) = _federal_and_states(federation, crown)
    officer = _context("official", username="dlg13")
    chain = _authority_chain(
        registry,
        national,
        federation,
        crown,
        officer,
        government_code=state["code"],
        scope="STATE",
    )

    def preview() -> dict[str, Any]:
        return federation.authority_preview(
            officer,
            operation="gov.case.decide",
            institution_code=chain.institution["code"],
            level="FEDERAL",
        )

    denied = preview()
    assert denied["government_allowed"] is False
    assert "توسيعُ نطاق" in denied["government_boundary_reason"]

    delegation = federation.grant_delegation(
        crown,
        from_government_code=federal["code"],
        to_government_code=state["code"],
        operation="gov.case.decide",
        scope="FEDERAL",
        reason="تفويضٌ فدراليٌّ مؤقَّت",
    )
    crossed = preview()
    assert crossed["government_allowed"] is True
    assert crossed["government_delegation_id"] == delegation["id"]
    assert "تفويضٍ صريح" in crossed["government_boundary_reason"]
    assert crossed["government_classification"] == "PROVEN"

    federation.revoke_delegation(crown, delegation["id"], "انتهاءُ الحاجة")
    assert preview()["government_allowed"] is False, "النقضُ يُعيد الحدَّ فورًا"

    session = _session()
    try:
        row = session.get(GovernmentDelegationModel, delegation["id"])
        assert row is not None and row.status == "revoked" and row.revoked_at is not None
    finally:
        session.close()

    # ومنتهي الصلاحية لا يُقبل ولو بقيت حالتُه `active` — بلا مُهمَلٍ دوريّ.
    expired = federation.grant_delegation(
        crown,
        from_government_code=federal["code"],
        to_government_code=state["code"],
        operation="gov.case.decide",
        scope="FEDERAL",
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    assert expired["status"] == "active"
    assert preview()["government_allowed"] is False, "المنتهي لا يُقبل"

    # وتفويضُ عمليةٍ أخرى لا يُجيز هذه: المفتاحُ العمليةُ لا الطرفان.
    federation.grant_delegation(
        crown,
        from_government_code=federal["code"],
        to_government_code=state["code"],
        operation="treasury.allocation.create",
        scope="FEDERAL",
    )
    assert preview()["government_allowed"] is False, "التفويضُ لعمليةٍ بعينها"


def test_14_delegation_requires_exactly_one_target_and_no_invented_operation(
    federation: FederalStateGovernment, crown: AuthorizationContext
) -> None:
    """هدفٌ واحدٌ بعينه، وعمليةٌ من مفردة R7-C، ولا تفويضَ لحكومةٍ لنفسها."""
    federal, (state, _) = _federal_and_states(federation, crown)

    with pytest.raises(FederationError, match="هدفٌ واحد"):
        federation.grant_delegation(
            crown, from_government_code=federal["code"], operation="gov.case.decide", scope="STATE"
        )
    with pytest.raises(FederationError):
        federation.grant_delegation(
            crown,
            from_government_code=federal["code"],
            to_government_code=federal["code"],
            operation="gov.case.decide",
            scope="STATE",
        )
    with pytest.raises(FederationError, match="غيرُ قابلةٍ للتفويض"):
        federation.grant_delegation(
            crown,
            from_government_code=federal["code"],
            to_government_code=state["code"],
            operation="gov.invented.operation",
            scope="STATE",
        )


def test_15_delegation_never_grants_authority_to_a_principal_without_a_position(
    registry: StateRegistry,
    national: NationalRegistry,
    federation: FederalStateGovernment,
    crown: AuthorizationContext,
) -> None:
    """من لا منصبَ له يُرفض ولو فُوِّضت الحكوماتُ كلُّها."""
    federal, (state, _) = _federal_and_states(federation, crown)
    target = _authority_chain(
        registry,
        national,
        federation,
        crown,
        _context("official", username="np15"),
        government_code=state["code"],
        scope="STATE",
        grant_operation=None,
    )
    federation.grant_delegation(
        crown,
        from_government_code=federal["code"],
        to_government_code=state["code"],
        operation="gov.case.decide",
        scope="STATE",
    )

    nobody = _context("official", username="nobody15")
    preview = federation.authority_preview(
        nobody,
        operation="gov.case.decide",
        institution_code=target.institution["code"],
        level="STATE",
    )
    assert preview["government_allowed"] is False
    assert preview["government_delegation_id"] is None
    assert "رفضُ المحرّك الكانونيّ" in preview["government_boundary_reason"]


# ── 8. نطاقُ الخدمات (R8-E) ───────────────────────────────────────────────


def test_16_service_scope_is_explicit_and_consistent(
    registry: StateRegistry,
    national: NationalRegistry,
    federation: FederalStateGovernment,
    services: GovernmentServices,
    crown: AuthorizationContext,
) -> None:
    """الخدمةُ تُنطَّق بمستوىً ومالكٍ مفروضَي الاتّساق — بلا خدمةٍ ثانيةٍ ولا منفِّذٍ خاصّ."""
    _federal, (state, _) = _federal_and_states(federation, crown)
    officer = _context("official", username="srv16")
    chain = _authority_chain(
        registry,
        national,
        federation,
        crown,
        officer,
        government_code=state["code"],
        scope="STATE",
        department_code=_code("DEP"),
    )
    bundle = _open_case(services, registry, crown, chain)
    service_code = bundle["service"]["code"]

    scoped = federation.scope_service(
        crown,
        institution_code=chain.institution["code"],
        service_code=service_code,
        level="STATE",
    )
    assert scoped["level"] == "STATE" and scoped["government_id"] == state["id"]

    with pytest.raises(FederationError, match="فدراليٌّ لمؤسسةٍ مربوطةٍ بولاية"):
        federation.scope_service(
            crown,
            institution_code=chain.institution["code"],
            service_code=service_code,
            level="FEDERAL",
        )
    with pytest.raises(FederationError, match="department_id"):
        federation.scope_service(
            crown,
            institution_code=chain.institution["code"],
            service_code=service_code,
            level="DEPARTMENT",
        )

    session = _session()
    try:
        assert session.query(ServiceScopeModel).count() == 1, "نطاقٌ واحدٌ لكل خدمة"
    finally:
        session.close()


def test_17_federal_scope_without_a_binding_is_refused_as_unresolved(
    registry: StateRegistry,
    national: NationalRegistry,
    federation: FederalStateGovernment,
    services: GovernmentServices,
    crown: AuthorizationContext,
) -> None:
    """نطاقٌ حكوميٌّ لمؤسسةٍ غير مربوطة يُرفض — ولا يُفترض له حكومة."""
    officer = _context("official", username="srv17")
    chain = _authority_chain(
        registry, national, federation, crown, officer, government_code=None, scope="INSTITUTION"
    )
    bundle = _open_case(services, registry, crown, chain)

    with pytest.raises(FederationError, match="غيرُ محلول"):
        federation.scope_service(
            crown,
            institution_code=chain.institution["code"],
            service_code=bundle["service"]["code"],
            level="STATE",
        )


# ── 9. إسنادُ القضايا لا يُلفَّق (R8-F) ────────────────────────────────────


def test_18_case_provenance_records_the_whole_chain(
    registry: StateRegistry,
    national: NationalRegistry,
    federation: FederalStateGovernment,
    services: GovernmentServices,
    crown: AuthorizationContext,
) -> None:
    """الإسنادُ يحمل الهويةَ والمنصبَ والمؤسسةَ والحكومةَ والحالةَ والطوابع."""
    _federal, (state, _) = _federal_and_states(federation, crown)
    officer = _context("official", username="case18")
    chain = _authority_chain(
        registry,
        national,
        federation,
        crown,
        officer,
        government_code=state["code"],
        scope="STATE",
    )
    bundle = _open_case(services, registry, crown, chain)

    scoped = federation.scope_case(
        officer, case_reference=bundle["case"]["reference"], level="STATE"
    )
    assert scoped["classification"] == "PROVEN"
    assert scoped["identity_id"] == chain.identity["id"]
    assert scoped["position_id"] == chain.position["id"]
    assert scoped["government_id"] == state["id"]
    assert scoped["institution_id"] == chain.institution["id"]
    assert scoped["audit_id"] and scoped["event_id"]

    with pytest.raises(FederationError, match="مُسنَدةٌ سابقًا"):
        federation.scope_case(officer, case_reference=bundle["case"]["reference"], level="STATE")

    session = _session()
    try:
        row = session.query(CaseScopeModel).one()
        assert row.authority["operation"] == "gov.case.decide"
        assert row.authority["government_target_government_id"] == state["id"]
        assert row.created_at is not None
    finally:
        session.close()


def test_19_unprovable_provenance_is_never_written_as_proven(
    registry: StateRegistry,
    national: NationalRegistry,
    federation: FederalStateGovernment,
    services: GovernmentServices,
    crown: AuthorizationContext,
) -> None:
    """قيدُ القاعدة يرفض `PROVEN` بلا سلسلة — فلا إسنادٌ مُلفَّق."""
    _federal, (state, _) = _federal_and_states(federation, crown)
    officer = _context("official", username="case19")
    chain = _authority_chain(
        registry,
        national,
        federation,
        crown,
        officer,
        government_code=state["code"],
        scope="STATE",
    )
    bundle = _open_case(services, registry, crown, chain)

    session = _session()
    try:
        session.add(
            CaseScopeModel(
                id="css-forged-probe",
                case_id=bundle["case"]["id"],
                level="STATE",
                government_id=None,
                institution_id=chain.institution["id"],
                classification="PROVEN",
                opened_by="probe",
                opened_by_identity_id=None,
                position_id=None,
                tenant_id=DEFAULT_TENANT,
            )
        )
        with pytest.raises(Exception, match="(?i)constraint|check|23514"):
            session.commit()
    finally:
        session.rollback()
        session.close()


# ── 10. التنفيذُ عبر النواة وحدها (R8-G) ──────────────────────────────────


def test_20_execution_goes_through_executive_core_and_records_a_real_task(
    registry: StateRegistry,
    national: NationalRegistry,
    federation: FederalStateGovernment,
    services: GovernmentServices,
    crown: AuthorizationContext,
) -> None:
    """العمليةُ الحكومية مهمّةٌ في `tasks` وأثرٌ يشير إليها بمفتاحٍ مفروض."""
    _federal, (state, _) = _federal_and_states(federation, crown)
    officer = _context("official", username="exe20")
    chain = _authority_chain(
        registry,
        national,
        federation,
        crown,
        officer,
        government_code=state["code"],
        scope="STATE",
    )
    bundle = _open_case(services, registry, crown, chain)
    _worker()

    executed = federation.execute_scoped_operation(
        officer,
        institution_code=chain.institution["code"],
        level="STATE",
        summary="تنفيذُ قرارٍ حكوميّ",
        case_reference=bundle["case"]["reference"],
    )
    assert executed["kind"] == "TASK"
    assert executed["status"] == "executed"
    assert executed["task_id"] == executed["task"]["id"]

    session = _session()
    try:
        row = session.get(GovernmentOperationModel, executed["id"])
        assert row is not None and row.task_id == executed["task"]["id"]
        assert row.government_id == state["id"]
        assert row.identity_id == chain.identity["id"]
        assert row.position_id == chain.position["id"]
    finally:
        session.close()

    # وحرسٌ ساكن: لا محرّكَ حالاتٍ ولا مُرسِلَ مهامٍّ في هذه الطبقة.
    sources = _r8_sources()
    for name, source in sources.items():
        assert "class ExecutiveCore" not in source, f"{name} يعرّف نواةً ثانية"
        assert "TaskModel(" not in source, f"{name} يكتب في جدول المهامّ مباشرةً"
        assert "DurableEventBus(" not in source, f"{name} يبني ناقلَ أحداثٍ جديدًا"
    assert "self._core.submit" in _strip_comments(
        (_R8_SOURCE_DIR / "service.py").read_text(encoding="utf-8")
    )


def test_21_unauthorized_execution_never_creates_a_task(
    registry: StateRegistry,
    national: NationalRegistry,
    federation: FederalStateGovernment,
    crown: AuthorizationContext,
) -> None:
    """الرفضُ يسبق النواة: لا مهمّةَ ولا أثرَ لمن لا سلطةَ له."""
    _federal, (state_a, state_b) = _federal_and_states(federation, crown)
    officer = _context("official", username="exe21")
    _authority_chain(
        registry,
        national,
        federation,
        crown,
        officer,
        government_code=state_a["code"],
        scope="STATE",
    )
    foreign = _authority_chain(
        registry,
        national,
        federation,
        crown,
        _context("official", username="exe21b"),
        government_code=state_b["code"],
        scope="STATE",
        grant_operation=None,
    )

    with pytest.raises(GovernmentAuthorityError):
        federation.execute_scoped_operation(
            officer,
            institution_code=foreign.institution["code"],
            level="STATE",
            summary="محاولةُ تنفيذٍ خارج النطاق",
        )

    session = _session()
    try:
        assert session.query(GovernmentOperationModel).count() == 0
    finally:
        session.close()


# ── 11. الخزانةُ بنطاقٍ حكوميّ (R8-L) ─────────────────────────────────────


def _treasury_chain(
    treasury: StateTreasury, crown: AuthorizationContext, institution_code: str, official_id: str
) -> dict[str, Any]:
    """خزانةٌ وحساباتٌ وموازنةٌ وتخصيصٌ حقيقيّ — من واجهة R7-B لا بصفوفٍ مزروعة."""
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
    return {"expense": expense, "allocation": allocation}


def test_22_treasury_write_requires_scoped_treasury_authority(
    registry: StateRegistry,
    national: NationalRegistry,
    federation: FederalStateGovernment,
    treasury: StateTreasury,
    crown: AuthorizationContext,
) -> None:
    """الصرفُ يمرّ بمسار الخزانة القائم بمِنحةٍ مُنطَّقة — ولا اختصارَ يُدخله."""
    _federal, (state, _) = _federal_and_states(federation, crown)
    officer = _context("official", username="trs22")
    chain = _authority_chain(
        registry,
        national,
        federation,
        crown,
        officer,
        government_code=state["code"],
        scope="INSTITUTION",
        grant_operation=None,
    )
    money = _treasury_chain(treasury, crown, chain.institution["code"], chain.official["id"])

    with pytest.raises((GovernmentAuthorityError, RegistryAuthorizationError)):
        federation.execute_scoped_disbursement(
            officer,
            treasury=treasury,
            institution_code=chain.institution["code"],
            level="INSTITUTION",
            allocation_id=money["allocation"]["id"],
            expense_account_code=money["expense"]["code"],
            amount=Decimal("1000.0000"),
            purpose="صرفٌ بلا مِنحة",
            idempotency_key=_code("IDEM"),
        )

    session = _session()
    try:
        assert session.query(GovernmentOperationModel).count() == 0, "لا أثرَ لعمليةٍ لم تُخوَّل"
    finally:
        session.close()

    national.grant_authority(
        context=crown,
        position_id=chain.position["id"],
        operation="treasury.disbursement.post",
        scope="INSTITUTION",
        institution_id=chain.institution["id"],
        max_amount="5000.0000",
    )
    executed = federation.execute_scoped_disbursement(
        officer,
        treasury=treasury,
        institution_code=chain.institution["code"],
        level="INSTITUTION",
        allocation_id=money["allocation"]["id"],
        expense_account_code=money["expense"]["code"],
        amount=Decimal("1000.0000"),
        purpose="صرفٌ مخوَّل",
        idempotency_key=_code("IDEM"),
    )
    assert executed["kind"] == "TREASURY" and executed["status"] == "executed"
    assert executed["transaction_reference"] == executed["transaction"]["reference"]
    assert executed["government_id"] == state["id"]

    # وحدُّ المبلغ يبقى حدَّ الخزانة والمِنحة: ما فوق السقف يُرفض.
    with pytest.raises((GovernmentAuthorityError, RegistryAuthorizationError)):
        federation.execute_scoped_disbursement(
            officer,
            treasury=treasury,
            institution_code=chain.institution["code"],
            level="INSTITUTION",
            allocation_id=money["allocation"]["id"],
            expense_account_code=money["expense"]["code"],
            amount=Decimal("9000.0000"),
            purpose="صرفٌ فوق السقف",
            idempotency_key=_code("IDEM"),
        )


def test_23_treasury_is_injected_and_never_rebuilt(
    federation: FederalStateGovernment,
) -> None:
    """حرسٌ ساكن: لا استيرادَ خزانةٍ ولا جداولَ دفترٍ في هذه الطبقة."""
    sources = _r8_sources()
    for name, source in sources.items():
        assert "state_treasury.service" not in source, f"{name} يستورد الخزانة"
        assert "LedgerEntryModel" not in source, f"{name} يكتب في الدفتر"
        assert "class StateTreasury" not in source
    assert "treasury.disburse(" in sources["service.py"], "الخزانةُ تُمرَّر وسيطًا وتُنادى كما هي"
    assert federation is not None


# ── 12. الوكلاء والسكّان (R8-I · R8-N) ────────────────────────────────────


def test_24_agent_membership_grants_no_federal_or_state_authority(
    registry: StateRegistry,
    national: NationalRegistry,
    federation: FederalStateGovernment,
    crown: AuthorizationContext,
) -> None:
    """موضعُ الوكيل يُقرأ من سجلّ R4/R7-A، والانتماءُ لا يمنح سلطة."""
    _federal, (state, _) = _federal_and_states(federation, crown)
    officer = _context("official", username="agt24")
    chain = _authority_chain(
        registry,
        national,
        federation,
        crown,
        officer,
        government_code=state["code"],
        scope="STATE",
    )

    view = federation.describe_agent_scope(crown, chain.agent_id)
    assert view["federal_authority"] is False and view["state_authority"] is False
    assert view["memberships"][0]["government_id"] == state["id"]
    assert view["memberships"][0]["classification"] == "PROVEN"

    sources = _r8_sources()
    for name, source in sources.items():
        assert "agent_population" not in source, f"{name} يبني سجلَّ سكّانٍ ثانيًا"
        assert "register_identity(" not in source, f"{name} يسجّل وكيلًا بنفسه"
        assert "class AgentRegistry" not in source


# ── 13. السيادةُ كما هي، والسلطةُ المُلفَّقةُ تُرفض (R8-M · R8-D) ──────────


def test_25_crown_authority_is_preserved_and_forged_authority_is_refused(
    registry: StateRegistry,
    national: NationalRegistry,
    federation: FederalStateGovernment,
    services: GovernmentServices,
    crown: AuthorizationContext,
) -> None:
    """التاجُ يكتب بنيةً كما كان، ومُدَّعي منصبِ غيره يُرفض."""
    _federal, (state, _) = _federal_and_states(federation, crown)
    officer = _context("official", username="crn25")
    chain = _authority_chain(
        registry,
        national,
        federation,
        crown,
        officer,
        government_code=state["code"],
        scope="STATE",
    )
    bundle = _open_case(services, registry, crown, chain)

    # السيادةُ لم تُنقَص: التاجُ ما زال يسجّل الحكوماتَ ويربط المؤسسات.
    assert federation.government_registry(crown), "سلطةُ التاج البنيوية قائمة"

    # ومُدَّعي منصبِ غيره يُرفض من المحرّك الكانونيّ نفسه.
    pretender = _context("official", username="pretender25")
    preview = federation.authority_preview(
        pretender,
        operation="gov.case.decide",
        institution_code=chain.institution["code"],
        level="STATE",
    )
    assert preview["government_allowed"] is False
    assert preview["position_id"] is None
    assert bundle["case"]["reference"]

    sources = _r8_sources()
    for name, source in sources.items():
        assert 'role="king"' not in source, f"{name} يستعمل الدورَ كمصادقةٍ سيادية"
        assert (
            "has_sovereign_authority" not in source
        ), f"{name} يوسّع سلطةً بالسيادة — نموذجُ السيادة لا يُلمَس هنا"


# ── 14. حدُّ المستأجر والمحرّكُ الواحد (R8-P · R8-D) ──────────────────────


def test_26_tenant_boundary_holds_and_tenant_is_never_authority(
    registry: StateRegistry,
    national: NationalRegistry,
    federation: FederalStateGovernment,
    crown: AuthorizationContext,
) -> None:
    """مستأجرٌ آخر لا يرى حكومةً ولا يكتب فيها، و`SINGLE_TENANT` كما هي."""
    _federal, (state, _) = _federal_and_states(federation, crown)
    stranger = _context("king", username="other-tenant", tenant_id="tenant-b")

    with pytest.raises((RegistryAuthorizationError, PermissionError, FederationError)):
        federation.set_government_status(stranger, state["code"], "suspended", "محاولةٌ عابرة")

    session = _session()
    try:
        assert session.get(GovernmentModel, state["id"]).status == "active"
    finally:
        session.close()

    sources = _r8_sources()
    for name, source in sources.items():
        assert "MULTI_TENANT" not in source, f"{name} يدّعي تعدّدَ مستأجرين"


def test_27_single_authorization_engine_and_single_event_vocabulary(
    federation: FederalStateGovernment, crown: AuthorizationContext
) -> None:
    """حرسٌ ساكن: محرّكُ تخويلٍ واحدٌ مُنادىً، ومفردةُ أحداثٍ واحدةٌ مُوسَّعة."""
    sources = _r8_sources()
    assert "resolve_authority(" in sources["authority.py"], "التركيبُ ينادي المحرّكَ الكانونيّ"
    for name, source in sources.items():
        assert "AuthorityGrantModel" not in source, f"{name} يقرأ المِنَح بنفسه — محرّكٌ ثانٍ"
        assert "class AuthorizationContext" not in source
    for subject in (
        "amos_federation.federation.government_registered",
        "amos_federation.federation.institution_bound",
        "amos_federation.federation.delegation_granted",
        "amos_federation.federation.case_scoped",
        "amos_federation.federation.operation_recorded",
    ):
        assert subject in EVENT_CONTRACTS, f"عقدُ {subject} مفقودٌ من المفردة القائمة"
    assert len(FEDERAL_STATE_TABLES) == 7


# ── 15. الأثرُ والتدقيقُ مترابطان (R8-K) ──────────────────────────────────


def test_28_every_write_correlates_audit_and_durable_event(
    registry: StateRegistry,
    national: NationalRegistry,
    federation: FederalStateGovernment,
    services: GovernmentServices,
    crown: AuthorizationContext,
) -> None:
    """لكل كتابةٍ سجلُّ تدقيقٍ وحدثٌ دائمٌ يحمل `audit_id` وارتباطَ الجلسة."""
    _federal, (state, _) = _federal_and_states(federation, crown)
    officer = _context("official", username="trc28")
    chain = _authority_chain(
        registry,
        national,
        federation,
        crown,
        officer,
        government_code=state["code"],
        scope="STATE",
    )
    bundle = _open_case(services, registry, crown, chain)
    scoped = federation.scope_case(
        officer, case_reference=bundle["case"]["reference"], level="STATE"
    )

    events = get_durable_event_bus().get_events(
        subject="amos_federation.federation.case_scoped", limit=20
    )
    match = [event for event in events if event["data"].get("scope_id") == scoped["id"]]
    assert match, "الحدثُ الدائمُ مكتوبٌ بموضوعه المُتعاقد عليه"
    payload = match[0]["data"]
    assert payload["audit_id"] == scoped["audit_id"]
    assert payload["actor"] == officer.principal_id
    assert payload["session_id"] == officer.session_id
    assert payload["classification"] == "PROVEN"
    assert match[0]["correlation_id"] == officer.correlation_id

    audit = PersistentAuditStore().list_all(limit=200)
    assert any(
        entry["audit_id"] == scoped["audit_id"] for entry in audit
    ), "سلسلةُ التدقيق كُتبت قبل الحدث لا بعده"
