"""
اختبارات R7-D — القضاء الفدرالي: محكمة ونطاق وقضية وحكم وتنفيذ
الهدف: التحقّق أن السلطة القضائية مقروءةٌ من القاعدة، وأن الحكم لا يُنفِّذ نفسه
النطاق: federal/executive/services
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17 (R7-D16)

اختبارات مركَّزة على نطاق R7-D وحده — لا مجموعةَ نظامٍ كاملة بعد كل تعديل. وما
تفحصه هذه الملفّة هو بالضبط ما يُدَّعى في «الأنظمة القضائية الرقمية» ولا يُفرَض:

1. **`role="judge"` ليس سلطة**: السلطةُ سلسلةٌ من ستّ حلقاتٍ تُقرأ من القاعدة.
2. **النطاق صريحٌ لا سلّم**: لا محكمةَ فدرالية تملك قضايا الولايات بالترقية.
3. **القاضي المعزول يُرفَض**: التقليدُ حالةٌ في صفٍّ، لا اسمٌ في جلسة.
4. **دورةُ الحياة مفروضة**: لا `force transition` ولا انتقالٌ يتخطّى مرحلة.
5. **الطرفُ هويةٌ كانونية**: لا اسمَ نصّيًّا بديلًا عنها.
6. **حكمٌ واحدٌ لكل مرحلة**: والثاني يُرفض، والبديل يلزمه إلغاءٌ مكتوب.
7. **المحكمة لا تنفّذ**: التنفيذ عبر `ExecutiveCore` أو `StateTreasury` كما هما.
8. **الحكمُ لا يمنح مالًا**: تخويلُ الخزانة يبقى كما هو، ورفضُها ينتشر.

ما **لا** تفحصه ولا يُدَّعى: سلسلةَ حيازةٍ للأدلّة (لم تُبنَ)، ولا قابليةَ نفاذٍ
قانونيةً خارج النظام، ولا تزامنًا حقيقيًّا بجلستين (SQLite يتجاهل `FOR UPDATE`)،
ولا قانونًا موضوعيًّا فوق المطالبة: مرجعُها نصٌّ **غير محقَّق** ويُقال ذلك صريحًا.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from amos_federation.common.database import get_session_factory, init_db
from amos_federation.common.durable_event_bus import get_durable_event_bus
from amos_federation.common.persistent import PersistentAuditStore
from amos_federation.common.principal import (
    DEFAULT_TENANT,
    AuthorizationContext,
    Principal,
)
from amos_federation.services.executive_core.agent_identity import register_identity
from amos_federation.services.executive_core.dispatcher import WILDCARD, register_agent
from amos_federation.services.executive_core.engine import reset_executive_core
from amos_federation.services.federal_judiciary import (
    CaseTransitionError,
    DuplicateRulingError,
    EnforcementError,
    EvidenceError,
    FederalJudiciary,
    JudgeAppointmentError,
    JudicialAuthorityError,
    JudiciaryError,
    JurisdictionError,
    get_federal_judiciary,
    reset_federal_judiciary,
)
from amos_federation.services.federal_judiciary.authority import (
    RULABLE_CASE_STATUSES,
    resolve_judicial_authority,
)
from amos_federation.services.federal_judiciary.docket import ALLOWED_TRANSITIONS
from amos_federation.services.federal_judiciary.models import (
    CASE_STATUSES,
    FEDERAL_JUDICIARY_TABLES,
    JURISDICTIONS,
    CaseClaimModel,
    CaseEvidenceModel,
    CasePartyModel,
    CaseProceedingModel,
    CourtJudgeModel,
    CourtModel,
    LegalCaseModel,
    RulingEnforcementModel,
    RulingModel,
)
from amos_federation.services.governance.security import DEFAULT_ROLES
from amos_federation.services.government_services.models import CaseModel, DecisionModel
from amos_federation.services.government_services.service import (
    reset_government_services,
)
from amos_federation.services.national_registry.models import (
    AuthorityGrantModel,
    DecisionProvenanceModel,
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
from amos_federation.services.state_registry.authorization import (
    RegistryAuthorizationError,
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

if TYPE_CHECKING:
    from datetime import datetime

SRC = Path(__file__).resolve().parents[1] / "src" / "amos_federation"
JUDICIARY_SRC = SRC / "services" / "federal_judiciary"
MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "009_federal_judiciary.sql"

_ROLE_PERMISSIONS = {role["role_id"]: tuple(role["permissions"]) for role in DEFAULT_ROLES}


def _strip_comments(source: str) -> str:
    """أزِل التعليقات وسلاسل التوثيق قبل أي تأكيد على المصدر.

    مصادرُ R7-D مملوءةٌ بتعليقاتٍ تذكر `CourtExecutor` و`identity_id` لتشرح
    **منعها** — فلو لم تُنزَع لَفشل الحرس على شرحِ نفسه.
    """
    no_docstrings = re.sub(r'"""(?:.|\n)*?"""', "", source)
    return "\n".join(line.split("#", 1)[0] for line in no_docstrings.splitlines())


def _context(
    role_id: str,
    *,
    tenant_id: str | None = None,
    expires_at: datetime | None = None,
    username: str = "r7d-user",
) -> AuthorizationContext:
    """سياق `SESSION_VERIFIED` بصلاحيات الدور كما زُرعت — لا كما يشتهي الاختبار."""
    return AuthorizationContext.from_principal(
        Principal.from_session_record(
            session_id=f"r7d-{role_id}-{username}",
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

    الترتيب مقصود: أثرُ التنفيذ قبل الحكم، والحكمُ قبل القضية، والقضيةُ قبل
    المحكمة، وتقليدُ القاضي قبل المسؤولين. وهو ترتيبُ القيود المرجعية نفسه.
    """
    init_db()
    session = get_session_factory()()
    try:
        session.query(RulingEnforcementModel).delete()
        session.query(RulingModel).delete()
        session.query(CaseProceedingModel).delete()
        session.query(CaseEvidenceModel).delete()
        session.query(CaseClaimModel).delete()
        session.query(CasePartyModel).delete()
        session.query(LegalCaseModel).delete()
        session.query(CourtJudgeModel).delete()
        session.query(CourtModel).delete()
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
    reset_federal_judiciary()


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
def judiciary() -> FederalJudiciary:
    return get_federal_judiciary()


@pytest.fixture
def crown(national: NationalRegistry) -> AuthorizationContext:
    """التاج — `*` فيمرّ في كل حدّ، وله هويةٌ كانونية كأيّ فاعلٍ آخر.

    الصلاحيةُ وحدها لا تكفي في R7-D: كلُّ عمليةٍ تحلّ هوية المُنادي من القاعدة
    قبل الكتابة. فالتاجُ يُربَط بهويةٍ إداريةٍ هنا لا لتقييد سيادته، بل ليصير
    أثرُه منسوبًا إلى صفٍّ حقيقيّ لا إلى اسمِ جلسة.
    """
    context = _context("king", username="crown")
    identity = national.create_identity(
        context=context, identity_type="PERSON", label="التاج"
    )
    national.link_principal(
        context=context, principal_id=context.principal_id, identity_id=identity["id"]
    )
    return context


def _agent(tenant_id: str = DEFAULT_TENANT) -> str:
    """وكيلٌ حقيقي في `agents` — سجلّ R4 الكانوني، ولا يُنشئه القضاء."""
    agent_id = f"agent-r7d-{uuid.uuid4().hex[:10]}"
    register_identity(agent_id, f"وكيل {agent_id}", "executor", tenant_id=tenant_id)
    return agent_id


def _worker() -> str:
    worker_id = f"worker-r7d-{uuid.uuid4().hex[:8]}"
    register_agent(worker_id, f"عامل {worker_id}", "worker", allowed_tools=[WILDCARD])
    return worker_id


def _code(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def _session():
    return get_session_factory()()


class Bench:
    """منصّةٌ قضائية جاهزة: مؤسسةٌ قضائية · مسؤول · هوية · منصب · محكمة · قاضٍ."""

    def __init__(self, **kwargs: object) -> None:
        self.__dict__.update(kwargs)


def _judicial_chain(
    registry: StateRegistry,
    national: NationalRegistry,
    crown: AuthorizationContext,
    context: AuthorizationContext,
    *,
    scope: str = "FEDERAL",
    branch: str = "judicial",
) -> Bench:
    """ابنِ سلسلة المنصب القضائي بعملياتٍ حقيقية — لا صفوفًا مزروعة يدويًّا."""
    institution = registry.register_institution(
        context=crown,
        code=_code("JUD"),
        name="المحكمة الفدرالية",
        kind="court",
        branch=branch,
    )
    agent_id = _agent()
    official = registry.appoint_official(
        context=crown,
        agent_id=agent_id,
        institution_code=institution["code"],
        title="قاضٍ",
    )
    identity = national.create_identity(context=crown, identity_type="PERSON", label="قاضٍ")
    national.link_principal(
        context=crown, principal_id=context.principal_id, identity_id=identity["id"]
    )
    national.link_agent(context=crown, agent_id=agent_id, identity_id=identity["id"])
    position = national.create_position(
        context=crown,
        code=_code("POS"),
        title="قاضٍ",
        institution_code=institution["code"],
        authority_scope=scope,
    )
    assignment = national.assign_position(
        context=crown, official_id=official["id"], position_id=position["id"]
    )
    return Bench(
        institution=institution,
        agent_id=agent_id,
        official=official,
        identity=identity,
        position=position,
        assignment=assignment,
    )


def _bench(
    registry: StateRegistry,
    national: NationalRegistry,
    judiciary: FederalJudiciary,
    crown: AuthorizationContext,
    judge_ctx: AuthorizationContext,
    *,
    jurisdiction: str = "FEDERAL",
    level: str = "FIRST_INSTANCE",
) -> Bench:
    """سلسلةٌ قضائية كاملة تنتهي بمحكمةٍ نشطةٍ وقاضٍ مُقلَّدٍ فيها."""
    bench = _judicial_chain(registry, national, crown, judge_ctx, scope=jurisdiction)
    bench.court = judiciary.register_court(
        context=crown,
        code=_code("CRT"),
        name="محكمة الدرجة الأولى",
        level=level,
        jurisdiction=jurisdiction,
        institution_code=bench.institution["code"],
    )
    bench.judge = judiciary.appoint_judge(
        context=crown,
        court_id=bench.court["id"],
        official_id=bench.official["id"],
        position_id=bench.position["id"],
    )
    return bench


def _party_identity(
    national: NationalRegistry, crown: AuthorizationContext, context: AuthorizationContext
) -> dict[str, Any]:
    """هويةٌ كانونية لمُقدِّم الطلب، مربوطةٌ بمبدأ جلسته."""
    identity = national.create_identity(
        context=crown, identity_type="PERSON", label="مُدَّعٍ"
    )
    national.link_principal(
        context=crown, principal_id=context.principal_id, identity_id=identity["id"]
    )
    return identity


def _open_and_assign(
    judiciary: FederalJudiciary,
    filer_ctx: AuthorizationContext,
    crown: AuthorizationContext,
    bench: Bench,
    *,
    case_type: str = "CIVIL",
) -> dict[str, Any]:
    """قضيةٌ مفتوحةٌ ومُقدَّمةٌ ومُسندةٌ إلى قاضي المنصّة — بالتتابع المفروض."""
    case = judiciary.open_case(
        context=filer_ctx,
        court_id=bench.court["id"],
        case_type=case_type,
        subject="نزاعٌ على تنفيذ التزام",
        reference=_code("CASE"),
    )
    judiciary.file_case(context=filer_ctx, case_id=case["id"])
    return judiciary.assign_case(
        context=crown, case_id=case["id"], judge_id=bench.judge["id"]
    )


# ── 1. المحكمة كيانٌ بمعرّفٍ مستقرّ على مؤسسةٍ قضائية (R7-D2/D4) ──────────


def test_01_court_is_a_row_on_a_judicial_institution_not_a_name(
    registry: StateRegistry,
    national: NationalRegistry,
    judiciary: FederalJudiciary,
    crown: AuthorizationContext,
) -> None:
    """المحكمةُ صفٌّ بمعرّفٍ مستقرّ ومؤسسةٍ قضائيةٍ قائمة — لا اسمٌ في طلب."""
    chain = _judicial_chain(registry, national, crown, _context("official", username="j1"))
    court = judiciary.register_court(
        context=crown,
        code=_code("CRT"),
        name="محكمة الدرجة الأولى",
        level="FIRST_INSTANCE",
        jurisdiction="FEDERAL",
        institution_code=chain.institution["code"],
    )
    assert court["id"].startswith("crt-"), "المعرّف مستقرٌّ ومُوسَمٌ بنوعه"
    assert court["institution_id"] == chain.institution["id"]
    assert court["status"] == "active"

    session = _session()
    try:
        row = session.get(CourtModel, court["id"])
        assert row is not None and row.jurisdiction == "FEDERAL"
        assert row.created_by == crown.principal_id, "الفاعلُ مكتوبٌ في الصفّ"
    finally:
        session.close()

    executive = registry.register_institution(
        context=crown,
        code=_code("EXE"),
        name="وزارة تنفيذية",
        kind="ministry",
        branch="executive",
    )
    with pytest.raises(JudiciaryError, match="لا 'judicial'"):
        judiciary.register_court(
            context=crown,
            code=_code("CRT"),
            name="محكمةٌ في وزارة",
            level="FIRST_INSTANCE",
            jurisdiction="FEDERAL",
            institution_code=executive["code"],
        )


# ── 2. النطاق صريحٌ وليس سلّمًا (R7-D3) ───────────────────────────────────


def test_02_jurisdiction_is_explicit_and_never_a_ladder(
    registry: StateRegistry,
    national: NationalRegistry,
    judiciary: FederalJudiciary,
    crown: AuthorizationContext,
) -> None:
    """لا نطاقَ مُختَرعًا، ولا فدراليةَ تملك قضايا الولايات بالترقية الضمنية."""
    chain = _judicial_chain(registry, national, crown, _context("official", username="j2"))
    with pytest.raises(JurisdictionError):
        judiciary.register_court(
            context=crown,
            code=_code("CRT"),
            name="محكمةٌ بنطاقٍ مُختَرع",
            level="FIRST_INSTANCE",
            jurisdiction="GALACTIC",
            institution_code=chain.institution["code"],
        )
    assert set(JURISDICTIONS) == {"FEDERAL", "STATE", "INSTITUTION"}, (
        "المفردةُ ثلاثةٌ موجودةٌ فعلًا — ولا رابعَ يُخترَع في الاختبار"
    )

    federal = judiciary.register_court(
        context=crown,
        code=_code("FED"),
        name="محكمة فدرالية",
        level="SUPREME",
        jurisdiction="FEDERAL",
        institution_code=chain.institution["code"],
    )
    state = judiciary.register_court(
        context=crown,
        code=_code("STA"),
        name="محكمة ولاية",
        level="FIRST_INSTANCE",
        jurisdiction="STATE",
        institution_code=chain.institution["code"],
    )
    filer = _context("official", username="filer2")
    _party_identity(national, crown, filer)
    state_case = judiciary.open_case(
        context=filer,
        court_id=state["id"],
        case_type="CIVIL",
        subject="نزاعٌ ولائيّ",
        reference=_code("CASE"),
    )
    assert state_case["jurisdiction"] == "STATE", "النطاقُ يُنسَخ من المحكمة لا من الطلب"

    session = _session()
    try:
        federal_ids = {
            row.id
            for row in session.query(LegalCaseModel).filter(
                LegalCaseModel.court_id == federal["id"]
            )
        }
    finally:
        session.close()
    assert state_case["id"] not in federal_ids, (
        "المحكمةُ الفدرالية — وإن كانت SUPREME — لا تملك قضيةَ الولاية تلقائيًّا"
    )


# ── 3. تقليدُ القاضي سلسلةٌ لا دور (R7-D4) ────────────────────────────────


def test_03_judge_appointment_requires_the_whole_chain(
    registry: StateRegistry,
    national: NationalRegistry,
    judiciary: FederalJudiciary,
    crown: AuthorizationContext,
) -> None:
    """التقليدُ يلزمه مسؤولٌ ومنصبٌ نشطٌ في فرعٍ قضائيّ وفي مؤسسة المحكمة نفسها."""
    judge_ctx = _context("official", username="j3")
    bench = _bench(registry, national, judiciary, crown, judge_ctx)
    assert bench.judge["id"].startswith("jdg-")
    assert bench.judge["identity_id"] == bench.identity["id"], (
        "التقليدُ يحمل الهوية الكانونية — لا الاسم"
    )
    assert bench.judge["status"] == "active"

    with pytest.raises(JudgeAppointmentError, match="نشطٌ في المحكمة"):
        judiciary.appoint_judge(
            context=crown,
            court_id=bench.court["id"],
            official_id=bench.official["id"],
            position_id=bench.position["id"],
        )

    other = _judicial_chain(
        registry, national, crown, _context("official", username="j3b"), branch="judicial"
    )
    with pytest.raises(JudgeAppointmentError, match="مؤسسةٍ غير مؤسسة المحكمة"):
        judiciary.appoint_judge(
            context=crown,
            court_id=bench.court["id"],
            official_id=other.official["id"],
            position_id=other.position["id"],
        )

    executive_chain = _judicial_chain(
        registry,
        national,
        crown,
        _context("official", username="j3c"),
        branch="executive",
    )
    with pytest.raises(JudgeAppointmentError, match="فرع"):
        judiciary.appoint_judge(
            context=crown,
            court_id=bench.court["id"],
            official_id=executive_chain.official["id"],
            position_id=executive_chain.position["id"],
        )


# ── 4. `role="judge"` ليس إثبات سلطة (R7-D9) ─────────────────────────────


def test_04_role_and_permission_are_not_judicial_authority(
    registry: StateRegistry,
    national: NationalRegistry,
    judiciary: FederalJudiciary,
    crown: AuthorizationContext,
) -> None:
    """صاحبُ الصلاحية بلا تقليدٍ في هذه المحكمة يُرفَض — `FAIL CLOSED`."""
    judge_ctx = _context("official", username="j4")
    bench = _bench(registry, national, judiciary, crown, judge_ctx)
    filer = _context("official", username="filer4")
    _party_identity(national, crown, filer)
    case = _open_and_assign(judiciary, filer, crown, bench)

    # مُنادٍ له `write:tasks` وهويةٌ كانونية، لكنه ليس مُقلَّدًا قاضيًا هنا.
    with pytest.raises(JudicialAuthorityError, match="لا تقليدَ قضاءٍ نشطًا"):
        judiciary.issue_ruling(
            context=filer,
            case_id=case["id"],
            decision="GRANTED",
            disposition="حكمٌ من غير قاضٍ",
        )

    # والتاجُ نفسه — `*` — لا يصير قاضيًا بصلاحيته: السلطةُ من الصفوف لا من الدور.
    with pytest.raises(JudicialAuthorityError):
        judiciary.issue_ruling(
            context=crown,
            case_id=case["id"],
            decision="GRANTED",
            disposition="حكمٌ بصلاحيةٍ سيادية",
        )

    session = _session()
    try:
        assert session.query(RulingModel).count() == 0, "لم يُكتب حكمٌ واحد"
    finally:
        session.close()


# ── 5. القاضي المعزول يُرفَض (R7-D9) ──────────────────────────────────────


def test_05_suspended_judge_is_denied(
    registry: StateRegistry,
    national: NationalRegistry,
    judiciary: FederalJudiciary,
    crown: AuthorizationContext,
) -> None:
    """التقليدُ حالةٌ في صفٍّ: تعليقُه يقطع السلطة في الحال."""
    judge_ctx = _context("official", username="j5")
    bench = _bench(registry, national, judiciary, crown, judge_ctx)
    filer = _context("official", username="filer5")
    _party_identity(national, crown, filer)
    case = _open_and_assign(judiciary, filer, crown, bench)

    session = _session()
    try:
        authority = resolve_judicial_authority(
            session, judge_ctx, court_id=bench.court["id"], case_id=case["id"]
        )
        assert authority.allowed and authority.classification == "PROVEN"
    finally:
        session.close()

    judiciary.set_judge_status(
        context=crown, judge_id=bench.judge["id"], status="suspended", reason="تحقيق"
    )
    with pytest.raises(JudicialAuthorityError, match="لا تقليدَ قضاءٍ نشطًا"):
        judiciary.issue_ruling(
            context=judge_ctx,
            case_id=case["id"],
            decision="GRANTED",
            disposition="حكمٌ من قاضٍ معلَّق",
        )

    # والمحكمةُ المعلَّقة كذلك: مؤسسةٌ غير نشطةٍ لا تُصدِر حكمًا.
    judiciary.set_judge_status(
        context=crown, judge_id=bench.judge["id"], status="active", reason="انتهى التحقيق"
    )
    judiciary.set_court_status(
        context=crown, court_id=bench.court["id"], status="suspended", reason="إعادة تنظيم"
    )
    with pytest.raises(JudicialAuthorityError, match="حالتها"):
        judiciary.issue_ruling(
            context=judge_ctx,
            case_id=case["id"],
            decision="GRANTED",
            disposition="حكمٌ في محكمةٍ معلَّقة",
        )


# ── 6. قاضٍ من خارج النطاق يُرفَض (R7-D3/D9) ─────────────────────────────


def test_06_judge_outside_the_courts_jurisdiction_is_denied(
    registry: StateRegistry,
    national: NationalRegistry,
    judiciary: FederalJudiciary,
    crown: AuthorizationContext,
) -> None:
    """نطاقُ المنصب يجب أن **يساوي** نطاق المحكمة — لا يعلوه ولا يشمله."""
    state_judge = _context("official", username="j6")
    chain = _judicial_chain(registry, national, crown, state_judge, scope="STATE")
    federal_court = judiciary.register_court(
        context=crown,
        code=_code("FED"),
        name="محكمة فدرالية",
        level="APPELLATE",
        jurisdiction="FEDERAL",
        institution_code=chain.institution["code"],
    )
    with pytest.raises(JurisdictionError):
        judiciary.appoint_judge(
            context=crown,
            court_id=federal_court["id"],
            official_id=chain.official["id"],
            position_id=chain.position["id"],
        )

    federal_judge = _context("official", username="j6b")
    fed_chain = _judicial_chain(registry, national, crown, federal_judge, scope="FEDERAL")
    state_court = judiciary.register_court(
        context=crown,
        code=_code("STA"),
        name="محكمة ولاية",
        level="FIRST_INSTANCE",
        jurisdiction="STATE",
        institution_code=fed_chain.institution["code"],
    )
    with pytest.raises(JurisdictionError):
        judiciary.appoint_judge(
            context=crown,
            court_id=state_court["id"],
            official_id=fed_chain.official["id"],
            position_id=fed_chain.position["id"],
        )


# ── 7. دورةُ حياة القضية مفروضة (R7-D5) ──────────────────────────────────


def test_07_case_lifecycle_is_ordered_with_no_force_transition(
    registry: StateRegistry,
    national: NationalRegistry,
    judiciary: FederalJudiciary,
    crown: AuthorizationContext,
) -> None:
    """التتابعُ مفروضٌ في خريطةٍ واحدة، ولا دالّةَ تُمرِّر انتقالًا بالقوّة."""
    judge_ctx = _context("official", username="j7")
    bench = _bench(registry, national, judiciary, crown, judge_ctx)
    filer = _context("official", username="filer7")
    _party_identity(national, crown, filer)

    case = judiciary.open_case(
        context=filer,
        court_id=bench.court["id"],
        case_type="CIVIL",
        subject="نزاع",
        reference=_code("CASE"),
    )
    assert case["status"] == "opened"

    # تخطّي `filed` مرفوض: لا إسنادَ لقضيةٍ لم تُقدَّم.
    with pytest.raises(CaseTransitionError):
        judiciary.assign_case(
            context=crown, case_id=case["id"], judge_id=bench.judge["id"]
        )
    with pytest.raises(CaseTransitionError):
        judiciary.open_hearing(context=judge_ctx, case_id=case["id"])

    judiciary.file_case(context=filer, case_id=case["id"])
    assigned = judiciary.assign_case(
        context=crown, case_id=case["id"], judge_id=bench.judge["id"]
    )
    assert assigned["status"] == "assigned"
    assert assigned["assigned_at"], "الإسنادُ زوجٌ: قاضٍ وطابعُ وقت"
    hearing = judiciary.open_hearing(context=judge_ctx, case_id=case["id"])
    assert hearing["status"] == "hearing"

    judiciary.issue_ruling(
        context=judge_ctx,
        case_id=case["id"],
        decision="GRANTED",
        disposition="أُجيبت الدعوى",
    )
    closed = judiciary.close_case(context=crown, case_id=case["id"], reason="نُفِّذ الحكم")
    assert closed["status"] == "closed" and closed["closed_at"]

    with pytest.raises(CaseTransitionError):
        judiciary.open_hearing(context=judge_ctx, case_id=case["id"])

    assert ALLOWED_TRANSITIONS["closed"] == (), "المُغلقةُ نهاية — لا انتقالَ منها"
    assert set(ALLOWED_TRANSITIONS) == set(CASE_STATUSES), (
        "كلُّ حالةٍ في المفردة لها مدخلٌ في الخريطة — فلا حالةٌ بلا قانونِ انتقال"
    )
    source = _strip_comments((JUDICIARY_SRC / "docket.py").read_text(encoding="utf-8"))
    assert re.search(r"\bforce", source, re.IGNORECASE) is None, (
        "لا انتقالَ بالقوّة في مصدر السجلّ — والحدُّ على الكلمة كي لا يخدعنا 'enforcement'"
    )


# ── 8. الطرفُ هويةٌ كانونية (R7-D6) ───────────────────────────────────────


def test_08_party_must_be_a_canonical_identity_not_a_string(
    registry: StateRegistry,
    national: NationalRegistry,
    judiciary: FederalJudiciary,
    crown: AuthorizationContext,
) -> None:
    """الطرفُ صفٌّ يشير إلى هويةٍ قائمة — والاسمُ عرضٌ لا تعريف."""
    judge_ctx = _context("official", username="j8")
    bench = _bench(registry, national, judiciary, crown, judge_ctx)
    filer = _context("official", username="filer8")
    identity = _party_identity(national, crown, filer)
    case = judiciary.open_case(
        context=filer,
        court_id=bench.court["id"],
        case_type="CIVIL",
        subject="نزاع",
        reference=_code("CASE"),
    )

    party = judiciary.add_party(
        context=filer,
        case_id=case["id"],
        party_role="PLAINTIFF",
        identity_id=identity["id"],
    )
    assert party["identity_id"] == identity["id"]
    assert party["display_label"], "الوسمُ للعرض — مشتقٌّ من الهوية لا بديلٌ عنها"

    with pytest.raises(JudiciaryError):
        judiciary.add_party(
            context=filer,
            case_id=case["id"],
            party_role="PLAINTIFF",
            identity_id="idn-غير-موجودة",
        )
    with pytest.raises(JudiciaryError, match="مُسجَّلةٌ أصلًا"):
        judiciary.add_party(
            context=filer,
            case_id=case["id"],
            party_role="PLAINTIFF",
            identity_id=identity["id"],
        )

    session = _session()
    try:
        column = CasePartyModel.__table__.c.identity_id
        assert not column.nullable, "`identity_id` إلزاميّ في القاعدة لا في الكود فقط"
        assert column.foreign_keys, "ويشير إلى `state_identities` بمفتاحٍ مفروض"
    finally:
        session.close()


# ── 9. المطالبة تُربَط بمرجعٍ قانونيّ غير محقَّق بعلمٍ (R7-D6) ────────────


def test_09_claim_records_an_unverified_legal_basis_honestly(
    registry: StateRegistry,
    national: NationalRegistry,
    judiciary: FederalJudiciary,
    crown: AuthorizationContext,
) -> None:
    """لا قانونَ موضوعيًّا مبنيًّا — فالمرجعُ نصٌّ و`legal_basis_verified=False`."""
    judge_ctx = _context("official", username="j9")
    bench = _bench(registry, national, judiciary, crown, judge_ctx)
    filer = _context("official", username="filer9")
    identity = _party_identity(national, crown, filer)
    case = judiciary.open_case(
        context=filer,
        court_id=bench.court["id"],
        case_type="CIVIL",
        subject="نزاع",
        reference=_code("CASE"),
    )
    party = judiciary.add_party(
        context=filer, case_id=case["id"], party_role="PLAINTIFF", identity_id=identity["id"]
    )
    claim = judiciary.add_claim(
        context=filer,
        case_id=case["id"],
        claimant_party_id=party["id"],
        claim_type="MONETARY",
        statement="مطالبةٌ بقيمة الالتزام",
        legal_basis_kind="LEGISLATION",
        legal_basis_ref="نظامُ المعاملات المدنية م. 12",
        amount="1500.0000",
    )
    assert claim["legal_basis_kind"] == "LEGISLATION"
    assert claim["legal_basis_verified"] is False, (
        "لا سجلَّ تشريعاتٍ يُحقَّق منه — فالعَلَمُ يقول ذلك بلا تجميل"
    )
    assert claim["claimant_party_id"] == party["id"], "المطالبةُ لطرفٍ في هذه القضية"

    with pytest.raises(JudiciaryError):
        judiciary.add_claim(
            context=filer,
            case_id=case["id"],
            claimant_party_id=party["id"],
            claim_type="MONETARY",
            statement="مرجعٌ بلا نصّ",
            legal_basis_kind="LEGISLATION",
            legal_basis_ref="",
        )


# ── 10. الأدلّة: بصمةٌ مفروضة ولا ادّعاءَ حيازة (R7-D7) ──────────────────


def test_10_evidence_is_a_deposit_record_and_claims_no_chain_of_custody(
    registry: StateRegistry,
    national: NationalRegistry,
    judiciary: FederalJudiciary,
    crown: AuthorizationContext,
) -> None:
    """البصمةُ sha256 بطولٍ مفروض، ولا خوارزميةَ بلا بصمة، ولا سلسلةَ حيازة."""
    judge_ctx = _context("official", username="j10")
    bench = _bench(registry, national, judiciary, crown, judge_ctx)
    filer = _context("official", username="filer10")
    _party_identity(national, crown, filer)
    case = judiciary.open_case(
        context=filer,
        court_id=bench.court["id"],
        case_type="CIVIL",
        subject="نزاع",
        reference=_code("CASE"),
    )
    digest = "a" * 64
    evidence = judiciary.submit_evidence(
        context=filer,
        case_id=case["id"],
        evidence_type="DOCUMENT",
        source="عقدٌ موقَّع",
        content_hash=digest.upper(),
    )
    assert evidence["content_hash"] == digest, "البصمةُ تُطبَّع صغيرةً قبل الحفظ"
    assert evidence["fingerprint_algo"] == "sha256"
    assert evidence["status"] == "submitted"

    with pytest.raises(EvidenceError, match="بطول 64"):
        judiciary.submit_evidence(
            context=filer,
            case_id=case["id"],
            evidence_type="DOCUMENT",
            source="عقدٌ آخر",
            content_hash="abc123",
        )
    with pytest.raises(EvidenceError, match="بلا بصمة"):
        judiciary.submit_evidence(
            context=filer,
            case_id=case["id"],
            evidence_type="DOCUMENT",
            source="عقدٌ ثالث",
            fingerprint_algo="sha256",
        )

    admitted = judiciary.set_evidence_status(
        context=crown, evidence_id=evidence["id"], status="admitted", reason="ذو صلة"
    )
    assert admitted["status"] == "admitted"

    columns = set(CaseEvidenceModel.__table__.c.keys())
    assert not any("custody" in name for name in columns), (
        "لا عمودَ حيازة: ما لم يُبنَ لا يُسمّى"
    )


# ── 11. الإجراءات مُرتَّبةٌ ونوعُ RULING محجوز (R7-D8) ────────────────────


def test_11_proceedings_are_sequenced_and_ruling_type_is_reserved(
    registry: StateRegistry,
    national: NationalRegistry,
    judiciary: FederalJudiciary,
    crown: AuthorizationContext,
) -> None:
    """كلُّ إجراءٍ برقمٍ متتابعٍ وفاعلٍ وهوية — والنصُّ الحرّ ليس بديلًا."""
    judge_ctx = _context("official", username="j11")
    bench = _bench(registry, national, judiciary, crown, judge_ctx)
    filer = _context("official", username="filer11")
    _party_identity(national, crown, filer)
    case = _open_and_assign(judiciary, filer, crown, bench)

    first = judiciary.record_proceeding(
        context=judge_ctx,
        case_id=case["id"],
        proceeding_type="MOTION",
        summary="طلبُ تأجيل",
    )
    second = judiciary.record_proceeding(
        context=judge_ctx,
        case_id=case["id"],
        proceeding_type="REVIEW",
        summary="مراجعةُ الأدلّة",
        record={"count": 2},
    )
    assert second["sequence"] == first["sequence"] + 1, "الترتيبُ يتزايد بواحد"
    assert second["actor_identity_id"] == bench.identity["id"], "الفاعلُ هويةٌ كانونية"
    assert second["record"] == {"count": 2}

    with pytest.raises(JudiciaryError, match="RULING"):
        judiciary.record_proceeding(
            context=judge_ctx,
            case_id=case["id"],
            proceeding_type="RULING",
            summary="حكمٌ بلا حكم",
        )

    ruling = judiciary.issue_ruling(
        context=judge_ctx,
        case_id=case["id"],
        decision="PARTIAL",
        disposition="أُجيبت الدعوى جزئيًّا",
    )
    file_view = judiciary.case_file(context=crown, case_id=case["id"])
    ruling_steps = [
        step for step in file_view["proceedings"] if step["proceeding_type"] == "RULING"
    ]
    assert len(ruling_steps) == 1, "إجراءُ الحكم يُقيَّد مرّةً واحدةً ومن مسارٍ واحد"
    assert ruling_steps[0]["record"]["ruling_id"] == ruling["id"]


# ── 12. الحكم يلزمه سلطةٌ مُثبَتة (R7-D9/D10) ────────────────────────────


def test_12_ruling_requires_proven_authority_and_links_to_the_case(
    registry: StateRegistry,
    national: NationalRegistry,
    judiciary: FederalJudiciary,
    crown: AuthorizationContext,
) -> None:
    """`PROVEN` وحدَه يُصدِر حكمًا، والقرارُ يُخزَّن مع الحكم ليُراجَع."""
    judge_ctx = _context("official", username="j12")
    bench = _bench(registry, national, judiciary, crown, judge_ctx)
    filer = _context("official", username="filer12")
    _party_identity(national, crown, filer)
    case = _open_and_assign(judiciary, filer, crown, bench)

    session = _session()
    try:
        court_only = resolve_judicial_authority(
            session, judge_ctx, court_id=bench.court["id"]
        )
        assert court_only.classification == "PARTIAL", (
            "بلا قضيةٍ يبقى التصنيفُ PARTIAL — لا يُرقّى تسامحًا"
        )
    finally:
        session.close()

    ruling = judiciary.issue_ruling(
        context=judge_ctx,
        case_id=case["id"],
        decision="GRANTED",
        disposition="أُجيبت الدعوى",
    )
    assert ruling["case_id"] == case["id"]
    assert ruling["judge_id"] == bench.judge["id"]
    assert ruling["court_id"] == bench.court["id"]
    assert ruling["provenance_class"] == "PROVEN"
    assert ruling["status"] == "issued"

    session = _session()
    try:
        row = session.get(RulingModel, ruling["id"])
        assert row is not None
        assert row.authority["classification"] == "PROVEN"
        assert row.authority["identity_id"] == bench.identity["id"]
        assert row.authority["position_id"] == bench.position["id"]
        assert session.get(LegalCaseModel, case["id"]).status == "decided", (
            "القضيةُ تنتقل إلى `decided` مع الحكم — لا يدويًّا"
        )
    finally:
        session.close()

    assert "decided" in RULABLE_CASE_STATUSES


# ── 13. حكمٌ واحدٌ قائمٌ لكل مرحلة (R7-D10) ──────────────────────────────


def test_13_second_ruling_for_the_same_stage_is_denied(
    registry: StateRegistry,
    national: NationalRegistry,
    judiciary: FederalJudiciary,
    crown: AuthorizationContext,
) -> None:
    """الثاني يُرفض، والبديلُ يلزمه إلغاءٌ مكتوبٌ لا حذفًا للتاريخ."""
    judge_ctx = _context("official", username="j13")
    bench = _bench(registry, national, judiciary, crown, judge_ctx)
    filer = _context("official", username="filer13")
    _party_identity(national, crown, filer)
    case = _open_and_assign(judiciary, filer, crown, bench)

    first = judiciary.issue_ruling(
        context=judge_ctx,
        case_id=case["id"],
        decision="GRANTED",
        disposition="الحكمُ الأوّل",
    )
    with pytest.raises(DuplicateRulingError):
        judiciary.issue_ruling(
            context=judge_ctx,
            case_id=case["id"],
            decision="DENIED",
            disposition="حكمٌ ثانٍ لنفس المرحلة",
        )

    # والإلغاءُ نفسه عملٌ قضائيّ: يلزمه سلطةٌ مُثبَتة لا صلاحيةً إداريّة.
    with pytest.raises(JudicialAuthorityError):
        judiciary.vacate_ruling(context=crown, ruling_id=first["id"], reason="بأمرٍ إداريّ")
    vacated = judiciary.vacate_ruling(
        context=judge_ctx, ruling_id=first["id"], reason="عيبٌ إجرائيّ"
    )
    assert vacated["status"] == "vacated" and vacated["vacated_at"]

    replacement = judiciary.issue_ruling(
        context=judge_ctx,
        case_id=case["id"],
        decision="DENIED",
        disposition="حكمٌ بديلٌ بعد الإلغاء",
    )
    session = _session()
    try:
        rows = session.query(RulingModel).filter(RulingModel.case_id == case["id"]).all()
        assert len(rows) == 2, "التاريخُ محفوظ: الملغى باقٍ والبديلُ مكتوب"
        active = [row for row in rows if row.status in ("issued", "enforced")]
        assert len(active) == 1 and active[0].id == replacement["id"]
    finally:
        session.close()

    # ومرحلةٌ أخرى تقبل حكمًا مستقلًّا — القيدُ على المرحلة لا على القضية.
    appeal = judiciary.issue_ruling(
        context=judge_ctx,
        case_id=case["id"],
        decision="PARTIAL",
        disposition="حكمُ استئناف",
        stage="APPEAL",
    )
    assert appeal["stage"] == "APPEAL"


# ── 14. سلسلةُ التخويل القضائي مقروءةٌ من القاعدة (R7-D9) ────────────────


def test_14_judicial_chain_is_readable_and_names_every_link(
    registry: StateRegistry,
    national: NationalRegistry,
    judiciary: FederalJudiciary,
    crown: AuthorizationContext,
) -> None:
    """ستُّ حلقاتٍ مُسمّاة: هوية · مسؤول · منصب · تقليد · محكمة · قضية."""
    judge_ctx = _context("official", username="j14")
    bench = _bench(registry, national, judiciary, crown, judge_ctx)
    filer = _context("official", username="filer14")
    _party_identity(national, crown, filer)
    case = _open_and_assign(judiciary, filer, crown, bench)

    authority = judiciary.judicial_chain(
        context=judge_ctx, court_id=bench.court["id"], case_id=case["id"]
    )
    assert authority["allowed"] is True
    assert authority["classification"] == "PROVEN"
    assert authority["identity_id"] == bench.identity["id"]
    assert authority["official_id"] == bench.official["id"]
    assert authority["position_id"] == bench.position["id"]
    assert authority["judge_id"] == bench.judge["id"]
    assert authority["court_id"] == bench.court["id"]
    assert authority["case_id"] == case["id"]
    assert authority["jurisdiction"] == "FEDERAL"

    unknown = _context("official", username="stranger14")
    session = _session()
    try:
        decision = resolve_judicial_authority(
            session, unknown, court_id=bench.court["id"], case_id=case["id"], strict=False
        )
        assert decision.allowed is False
        assert decision.classification == "UNRESOLVED"
        assert decision.reason, "الرفضُ يحمل سببَ السقوط لا صمتًا"
    finally:
        session.close()


# ── 15. التنفيذ عبر ExecutiveCore لا بمُنفِّذٍ قضائيّ (R7-D11) ────────────


def test_15_enforcement_goes_through_executive_core_task(
    registry: StateRegistry,
    national: NationalRegistry,
    judiciary: FederalJudiciary,
    crown: AuthorizationContext,
) -> None:
    """المحكمةُ تُحيل إلى `tasks` وتنتظر حالتَها — ولا تُنفِّذ بنفسها."""
    _worker()
    judge_ctx = _context("official", username="j15")
    bench = _bench(registry, national, judiciary, crown, judge_ctx)
    filer = _context("official", username="filer15")
    _party_identity(national, crown, filer)
    case = _open_and_assign(judiciary, filer, crown, bench)
    ruling = judiciary.issue_ruling(
        context=judge_ctx,
        case_id=case["id"],
        decision="GRANTED",
        disposition="يُلزَم المدَّعى عليه بالتنفيذ",
    )

    result = judiciary.enforce_ruling_via_task(
        context=judge_ctx, ruling_id=ruling["id"], description="تنفيذُ الحكم"
    )
    assert result["kind"] == "TASK"
    assert result["task_id"], "أثرُ التنفيذ يحمل معرّف المهمّة الحقيقيّ"
    assert result["status"] == "executed"
    assert result["task_final_state"] == "completed"

    session = _session()
    try:
        row = session.get(RulingEnforcementModel, result["id"])
        assert row is not None and row.task_id == result["task_id"]
        assert session.get(RulingModel, ruling["id"]).status == "enforced"
        assert session.get(LegalCaseModel, case["id"]).status == "enforcement"
        task_fk = list(RulingEnforcementModel.__table__.c.task_id.foreign_keys)
        assert task_fk and task_fk[0].target_fullname == "tasks.id", (
            "الأثرُ يشير إلى جدول المهامّ القائم — لا إلى جدولٍ قضائيّ موازٍ"
        )
    finally:
        session.close()

    with pytest.raises(EnforcementError):
        judiciary.enforce_ruling_via_task(context=judge_ctx, ruling_id=ruling["id"])


# ── 16. الحكمُ لا يتجاوز تخويلَ الخزانة (R7-D12) ─────────────────────────


def test_16_ruling_never_bypasses_treasury_authorization(
    registry: StateRegistry,
    national: NationalRegistry,
    judiciary: FederalJudiciary,
    treasury: StateTreasury,
    crown: AuthorizationContext,
) -> None:
    """رفضُ الخزانة ينتشر، ويُكتب أثرٌ `failed`، ويبقى الحكم `issued`."""
    # دورُ «مسؤول» مقصود: لا `write:all` ولا `manage:all`، فطريقه الوحيد المشروع
    # إلى المال هو مِنحةُ سلطةٍ `PROVEN` لمنصبه. والحكمُ لا يصنع له طريقًا ثانيًا.
    judge_ctx = _context("official", username="j16")
    bench = _bench(registry, national, judiciary, crown, judge_ctx)
    filer = _context("official", username="filer16")
    _party_identity(national, crown, filer)
    case = _open_and_assign(judiciary, filer, crown, bench)
    ruling = judiciary.issue_ruling(
        context=judge_ctx,
        case_id=case["id"],
        decision="GRANTED",
        disposition="يُصرَف للمدَّعي مبلغُ الالتزام",
    )

    code = bench.institution["code"]
    trs = treasury.establish_treasury(
        context=crown,
        code=_code("TRS"),
        name="خزانةُ المحكمة",
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
        limit_amount="100000.0000",
    )
    treasury.post_funding(
        context=crown,
        treasury_code=trs["code"],
        cash_account_code=cash["code"],
        revenue_account_code=revenue["code"],
        amount="50000.0000",
        purpose="تمويل افتتاحي",
        official_id=bench.official["id"],
    )
    allocation = treasury.allocate(
        context=crown,
        budget_code=budget["code"],
        account_code=cash["code"],
        purpose="تنفيذُ الأحكام",
        amount="20000.0000",
        official_id=bench.official["id"],
    )

    # القاضي حكم، ولا مِنحةَ سلطةٍ مالية لمنصبه: الصرفُ يُرفض والحكمُ لا يُغيّر ذلك.
    with pytest.raises(RegistryAuthorizationError) as denied:
        judiciary.enforce_ruling_via_treasury(
            context=judge_ctx,
            ruling_id=ruling["id"],
            treasury=treasury,
            allocation_id=allocation["id"],
            expense_account_code=expense["code"],
            amount="1000.0000",
            purpose="تنفيذُ حكم",
            official_id=bench.official["id"],
        )
    assert "treasury.disbursement.post" in str(denied.value), (
        "الرفضُ من حدِّ الخزانة نفسه — لا من حدٍّ قضائيّ موازٍ"
    )

    session = _session()
    try:
        failed = (
            session.query(RulingEnforcementModel)
            .filter(RulingEnforcementModel.ruling_id == ruling["id"])
            .all()
        )
        assert len(failed) == 1 and failed[0].status == "failed"
        assert failed[0].transaction_reference is None, "لا مرجعَ حركةٍ لم تجرِ"
        assert session.get(RulingModel, ruling["id"]).status == "issued"
    finally:
        session.close()

    # وبمِنحةٍ حقيقية لمنصب القاضي يمرّ الصرف — من مسار الخزانة نفسه لا حوله.
    national.grant_authority(
        context=crown,
        position_id=bench.position["id"],
        operation="treasury.disbursement.post",
        scope="INSTITUTION",
        institution_id=bench.institution["id"],
        max_amount="5000.0000",
    )
    executed = judiciary.enforce_ruling_via_treasury(
        context=judge_ctx,
        ruling_id=ruling["id"],
        treasury=treasury,
        allocation_id=allocation["id"],
        expense_account_code=expense["code"],
        amount="1000.0000",
        purpose="تنفيذُ حكم",
        official_id=bench.official["id"],
    )
    assert executed["kind"] == "TREASURY"
    assert executed["status"] == "executed"
    assert executed["transaction_reference"] == executed["transaction"]["reference"]

    session = _session()
    try:
        assert session.get(RulingModel, ruling["id"]).status == "enforced"
        assert session.get(LegalCaseModel, case["id"]).status == "enforcement"
    finally:
        session.close()


# ── 17. الإسنادُ يُكتب لكل عملٍ قضائيّ (R7-D15) ──────────────────────────


def test_17_every_judicial_action_writes_audit_and_event(
    registry: StateRegistry,
    national: NationalRegistry,
    judiciary: FederalJudiciary,
    crown: AuthorizationContext,
) -> None:
    """أثرٌ مُدقَّقٌ ثمّ حدثٌ دائم — بمعرّفين حقيقيين من المخزنين لا بادّعاء."""
    judge_ctx = _context("official", username="j17")
    bench = _bench(registry, national, judiciary, crown, judge_ctx)
    assert bench.court["audit_id"] and bench.court["event_id"]
    assert bench.judge["audit_id"] and bench.judge["event_id"]

    filer = _context("official", username="filer17")
    _party_identity(national, crown, filer)
    case = _open_and_assign(judiciary, filer, crown, bench)
    ruling = judiciary.issue_ruling(
        context=judge_ctx,
        case_id=case["id"],
        decision="GRANTED",
        disposition="أُجيبت الدعوى",
    )
    assert ruling["audit_id"] and ruling["event_id"]

    bus = get_durable_event_bus()
    issued = bus.get_events(subject="amos_federation.judiciary.ruling_issued", limit=20)
    assert any(event["event_id"] == ruling["event_id"] for event in issued)
    payload = next(event for event in issued if event["event_id"] == ruling["event_id"])["data"]
    assert payload["case_id"] == case["id"]
    assert payload["actor"] == judge_ctx.principal_id
    assert payload["judge_identity_id"] == bench.identity["id"]
    assert payload["audit_id"] == ruling["audit_id"], "الحدثُ يحمل مفتاحَ الأثر"

    actions = {
        entry["action"] for entry in PersistentAuditStore().list_all(limit=200)
    }
    for action in (
        "judiciary.court.register",
        "judiciary.judge.appoint",
        "judiciary.case.open",
        "judiciary.case.assign",
        "judiciary.ruling.issue",
    ):
        assert action in actions, f"فعلٌ بلا أثرٍ مُدقَّق: {action}"


# ── 18. الرفضُ هو الافتراض عند نقص الصلاحية أو المستأجر (R7-D17) ─────────


def test_18_unauthorized_and_cross_tenant_actions_are_denied(
    registry: StateRegistry,
    national: NationalRegistry,
    judiciary: FederalJudiciary,
    crown: AuthorizationContext,
) -> None:
    """صلاحيةُ النطاق تُفحَص أوّلًا، والمستأجرُ يُفحَص على الصفّ لا على الطلب."""
    judge_ctx = _context("official", username="j18")
    bench = _bench(registry, national, judiciary, crown, judge_ctx)

    plain = _context("official", username="plain18")
    with pytest.raises(RegistryAuthorizationError):
        judiciary.register_court(
            context=plain,
            code=_code("CRT"),
            name="محكمةٌ بلا صلاحية",
            level="FIRST_INSTANCE",
            jurisdiction="FEDERAL",
            institution_code=bench.institution["code"],
        )
    with pytest.raises(RegistryAuthorizationError):
        judiciary.appoint_judge(
            context=plain,
            court_id=bench.court["id"],
            official_id=bench.official["id"],
            position_id=bench.position["id"],
        )

    foreign = _context("king", username="foreign18", tenant_id="tenant-b")
    with pytest.raises(Exception) as blocked:
        judiciary.get_court(context=foreign, court_id=bench.court["id"])
    assert "tenant-b" in str(blocked.value) or "مستأجر" in str(blocked.value)


# ── 19. حرَسٌ ساكنٌ على التجاوز (R7-D11/D13/D14) ─────────────────────────


def test_19_static_guards_forbid_parallel_executors_and_schema_rewrites() -> None:
    """ما يمنعه التصميمُ يجب أن يُمنع في المصدر لا في النيّة."""
    sources = {
        path.name: _strip_comments(path.read_text(encoding="utf-8"))
        for path in JUDICIARY_SRC.glob("*.py")
    }
    joined = "\n".join(sources.values())
    assert "CourtExecutor" not in joined, "لا مُنفِّذَ قضائيًّا موازيًا لـ`ExecutiveCore`"
    assert "AgentRuntime(" not in joined, "المحكمةُ لا تُنادي زمنَ التشغيل مباشرةً"

    # `enforcement.py` سجلُّ أثرٍ محض: لا يستورد تنفيذًا ولا مالًا.
    enforcement_src = sources["enforcement.py"]
    assert "executive_core" not in enforcement_src
    assert "state_treasury" not in enforcement_src

    # الخزانةُ تُمرَّر إلى الدالّة ولا تُستورَد في الوحدة — فلا مسارَ صرفٍ خاصّ.
    service_src = sources["service.py"]
    assert "state_treasury" not in service_src, (
        "`enforce_ruling_via_treasury` يأخذ الخزانةَ وسيطًا كأيّ مُنادٍ آخر"
    )

    # الهجرةُ 009 تُضيف ولا تُعيد كتابة التاريخ.
    migration = MIGRATION.read_text(encoding="utf-8")
    body = "\n".join(
        line for line in migration.splitlines() if not line.strip().startswith("--")
    )
    for forbidden in ("ALTER TABLE", "DROP TABLE", "DROP INDEX", "DELETE FROM", "TRUNCATE"):
        assert forbidden not in body.upper(), f"الهجرةُ 009 لا تحتوي {forbidden}"
    for table in FEDERAL_JUDICIARY_TABLES:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in body, f"جدولٌ بلا هجرة: {table}"

    # القضاءُ القديم في `governance/federation.py` يبقى تحكيمًا غير رسميّ.
    legacy = _strip_comments(
        (SRC / "services" / "governance" / "federation.py").read_text(encoding="utf-8")
    )
    for canonical in ("state_rulings", "RulingModel", "federal_judiciary"):
        assert canonical not in legacy, (
            "المسارُ القديم لا يكتب في جداول القضاء الكانونية — ولا يُدَّعى أنه محكمة"
        )

    # ولا سيادةَ تُنتزَع: لا نقضَ قضائيًّا لأمرٍ سياديّ صحيح في مصدر القضاء.
    for forbidden in ("veto", "override_sovereign", "revoke_crown"):
        assert forbidden not in joined.lower(), f"لا {forbidden} في القضاء (R7-D13)"
