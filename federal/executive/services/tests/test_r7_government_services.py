"""
اختبارات R7-A (الوحدة 2) — الخدمات الحكومية والقضايا والقرارات
الهدف: التحقّق أن العملية الحكومية لها أثر تنفيذي حقيقي وقيود مفروضة وأثر مُدقَّق
النطاق: federal/executive/services
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17 (R7-A، الوحدة 2)

اختبارات مركَّزة على نطاق واحد. وأهمّها ما يفحص ما يُدَّعى كثيرًا ولا يُفرَض:

1. **القضية لها مهمّة حقيقية** في `tasks` بمفتاح أجنبي مفروض — لا «عملية» بلا أثر.
2. **لا مُنفِّذ خاصّ بالنطاق**: المعالجة تمرّ بـ`ExecutiveCore` وحده (حرس ساكن).
3. **القرار يلزمه منصبٌ قائم في مؤسسة القضية** — لا دورٌ مناسب فقط.
4. **لا قرار قبل مراجعة منتهية** — والحالة النهائية تُخزَّن كما قالها العمود.
5. حدّ المستأجر، والتخويل من جلسة، والأثر المُدقَّق لكل كتابة.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from amos_federation.common.database import get_session_factory, init_db
from amos_federation.common.durable_event_bus import get_durable_event_bus
from amos_federation.common.event_bus import EVENT_CONTRACTS, validate_event
from amos_federation.common.persistent import PersistentAuditStore
from amos_federation.common.principal import (
    DEFAULT_TENANT,
    AuthorizationContext,
    Principal,
    PrincipalUnverifiedError,
    SessionInvalidError,
    TenantIsolationError,
    unverified_context,
)
from amos_federation.common.registry import SERVICES
from amos_federation.services.executive_core.agent_identity import register_identity
from amos_federation.services.executive_core.dispatcher import WILDCARD, register_agent
from amos_federation.services.executive_core.engine import reset_executive_core
from amos_federation.services.governance.security import DEFAULT_ROLES
from amos_federation.services.government_services.authorization import (
    GOVERNMENT_PERMISSIONS,
    OfficeAuthorityError,
    RegistryAuthorizationError,
)
from amos_federation.services.government_services.models import (
    CASE_STATUSES,
    DECISION_OUTCOMES,
    SERVICE_STATUSES,
    CaseModel,
    DecisionModel,
    ServiceModel,
)
from amos_federation.services.government_services.service import (
    CASE_TASK_TYPE,
    EVENT_CASE_ASSIGNED,
    EVENT_CASE_CLOSED,
    EVENT_CASE_DECIDED,
    EVENT_CASE_OPENED,
    EVENT_CASE_REVIEWED,
    EVENT_SERVICE_PUBLISHED,
    GOVERNMENT_EVENTS,
    CaseStateError,
    DecisionExistsError,
    DuplicateServiceCodeError,
    GovernmentServiceError,
    GovernmentServices,
    ReviewIncompleteError,
    ServiceInactiveError,
    ServiceNotFoundError,
    UnknownApplicantError,
    get_government_services,
    reset_government_services,
)
from amos_federation.services.state_registry.service import (
    StateRegistry,
    get_state_registry,
    reset_state_registry,
)
from tests.conftest import purge_agents, purge_tasks

SRC = Path(__file__).resolve().parents[1] / "src" / "amos_federation"
GOV_SRC = SRC / "services" / "government_services"

_ROLE_PERMISSIONS = {role["role_id"]: tuple(role["permissions"]) for role in DEFAULT_ROLES}


def _strip_comments(source: str) -> str:
    """أزِل التعليقات وسلاسل التوثيق قبل أي تأكيد على المصدر.

    الدرس من R6 وR6.1 والوحدة 1: حرسٌ يبحث عن نصٍّ في المصدر قد يمرّ أو يفشل
    بسبب **تعليق** يشرح الأمر لا بسبب شيفرة تفعله.
    """
    no_docstrings = re.sub(r'"""(?:.|\n)*?"""', "", source)
    return "\n".join(line.split("#", 1)[0] for line in no_docstrings.splitlines())


def _context(
    role_id: str,
    *,
    tenant_id: str | None = None,
    expires_at: datetime | None = None,
    username: str = "r7b-user",
) -> AuthorizationContext:
    """سياق `SESSION_VERIFIED` بصلاحيات الدور كما هي مزروعة — لا كما يشتهي الاختبار."""
    return AuthorizationContext.from_principal(
        Principal.from_session_record(
            session_id=f"r7b-{role_id}-{username}",
            username=f"{username}-{role_id}",
            role_id=role_id,
            permissions=_ROLE_PERMISSIONS[role_id],
            expires_at=expires_at,
            tenant_id=tenant_id,
        )
    )


@pytest.fixture(autouse=True)
def _fresh_state() -> None:
    """قاعدة نظيفة من صفوف النطاق قبل كل اختبار — الملف مشترك بين الاختبارات."""
    init_db()
    session = get_session_factory()()
    try:
        session.query(DecisionModel).delete()
        session.query(CaseModel).delete()
        session.query(ServiceModel).delete()
        purge_tasks(session)
        purge_agents(session)
        session.commit()
    finally:
        session.close()
    reset_executive_core()
    reset_state_registry()
    reset_government_services()


@pytest.fixture
def registry() -> StateRegistry:
    return get_state_registry()


@pytest.fixture
def gov() -> GovernmentServices:
    return get_government_services()


@pytest.fixture
def crown() -> AuthorizationContext:
    """التاج — يملك `*` فيمرّ في كل حدّ عبر `has_permission` نفسها (R7-F)."""
    return _context("king")


def _agent(tenant_id: str = DEFAULT_TENANT) -> str:
    """وكيلٌ حقيقي في `agents` — الطالب والمسؤول يشيران إليه بمفتاح أجنبي."""
    agent_id = f"agent-r7b-{uuid.uuid4().hex[:10]}"
    register_identity(agent_id, f"وكيل {agent_id}", "executor", tenant_id=tenant_id)
    return agent_id


def _worker() -> str:
    """عاملٌ مؤهَّل فعلًا للتوزيع — بلا واحدٍ كهذا تفشل المهمّة، وهذا سلوك صادق."""
    worker_id = f"worker-r7b-{uuid.uuid4().hex[:8]}"
    register_agent(worker_id, f"عامل {worker_id}", "worker", allowed_tools=[WILDCARD])
    return worker_id


def _code(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def _institution(registry: StateRegistry, crown: AuthorizationContext) -> dict:
    return registry.register_institution(
        context=crown,
        code=_code("INST"),
        name="وزارة الخدمات",
        kind="ministry",
        branch="executive",
    )


def _service(
    gov: GovernmentServices,
    crown: AuthorizationContext,
    institution_code: str,
    **kwargs: object,
) -> dict:
    return gov.publish_service(
        context=crown,
        institution_code=institution_code,
        code=_code("SVC"),
        name="إصدار وثيقة",
        **kwargs,  # type: ignore[arg-type]
    )


def _official(registry: StateRegistry, crown: AuthorizationContext, institution_code: str) -> dict:
    return registry.appoint_official(
        context=crown,
        agent_id=_agent(),
        institution_code=institution_code,
        title="مدير الخدمة",
    )


# ── 1. الأثر التنفيذي حقيقي ───────────────────────────────────────────────


def test_01_case_task_foreign_key_is_enforced(gov: GovernmentServices) -> None:
    """قضية بمهمّة غير موجودة تُرفَض من القاعدة — لا من تعليق في النموذج.

    أوّل اختبار بقصد: لو لم يُفرض هذا المفتاح لأمكن أن توجد «عملية حكومية» لا
    صفَّ لها في `tasks`، وهو بالضبط ما يمنعه R7-E.
    """
    session = get_session_factory()()
    try:
        session.add(
            CaseModel(
                id=f"case-orphan-{uuid.uuid4().hex[:8]}",
                reference="REF-ORPHAN",
                service_id="svc-ghost",
                institution_id="inst-ghost",
                applicant_agent_id="agent-ghost",
                task_id="task-ghost",
                subject="قضية بلا مهمّة",
                opened_by="test",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
    finally:
        session.rollback()
        session.close()


def test_02_open_case_creates_real_task_row(
    gov: GovernmentServices, registry: StateRegistry, crown: AuthorizationContext
) -> None:
    """فتح القضية يُقدِّم مهمّة حقيقية إلى العمود التنفيذي ويحفظ معرّفها."""
    from sqlalchemy import text

    institution = _institution(registry, crown)
    service = _service(gov, crown, institution["code"])
    case = gov.open_case(
        context=crown,
        institution_code=institution["code"],
        service_code=service["code"],
        applicant_agent_id=_agent(),
        subject="طلب وثيقة",
    )
    assert case["task_id"]
    session = get_session_factory()()
    try:
        row = session.execute(
            text("SELECT type, domain, status FROM tasks WHERE id = :tid"),
            {"tid": case["task_id"]},
        ).first()
    finally:
        session.close()
    assert row is not None, "القضية تدّعي مهمّة لا صفَّ لها"
    assert row[0] == CASE_TASK_TYPE
    assert row[2] == "created"


def test_03_process_case_stores_the_core_final_state_verbatim(
    gov: GovernmentServices, registry: StateRegistry, crown: AuthorizationContext
) -> None:
    """المعالجة تُخزِّن ما قاله العمود التنفيذي — والمهمّة نفسها في حالة نهائية."""
    from sqlalchemy import text

    _worker()
    institution = _institution(registry, crown)
    service = _service(gov, crown, institution["code"])
    case = gov.open_case(
        context=crown,
        institution_code=institution["code"],
        service_code=service["code"],
        applicant_agent_id=_agent(),
        subject="طلب يُعالَج",
    )
    result = gov.process_case(context=crown, reference=case["reference"])
    session = get_session_factory()()
    try:
        task_status = session.execute(
            text("SELECT status FROM tasks WHERE id = :tid"), {"tid": case["task_id"]}
        ).scalar()
    finally:
        session.close()
    assert result["review_state"] == task_status, "الحالة المخزَّنة تخالف حالة المهمّة"
    assert result["terminal"] is True
    assert result["status"] == "reviewed"


def test_04_case_failure_is_stored_as_failure_not_dressed_up(
    gov: GovernmentServices, registry: StateRegistry, crown: AuthorizationContext
) -> None:
    """بلا وكيل مؤهَّل تفشل المهمّة — والقضية تُخزِّن `failed` ولا تُجمِّلها."""
    institution = _institution(registry, crown)
    service = _service(gov, crown, institution["code"])
    case = gov.open_case(
        context=crown,
        institution_code=institution["code"],
        service_code=service["code"],
        applicant_agent_id=_agent(),
        subject="طلب بلا عامل",
    )
    result = gov.process_case(context=crown, reference=case["reference"])
    assert result["review_state"] == "failed"
    assert result["status"] == "reviewed"


def test_05_no_parallel_executor_in_this_domain(gov: GovernmentServices) -> None:
    """حرس ساكن: هذا النطاق لا يستورد موزِّعًا ولا زمن تشغيل ولا آلة حالات (R7-E)."""
    forbidden = ("dispatcher", "agent_runtime", "AgentRuntime", "register_agent", "Dispatcher")
    for path in sorted(GOV_SRC.glob("*.py")):
        source = _strip_comments(path.read_text(encoding="utf-8"))
        for token in forbidden:
            assert token not in source, f"{path.name} يستورد مُنفِّذًا موازيًا: {token}"
    service_source = _strip_comments((GOV_SRC / "service.py").read_text(encoding="utf-8"))
    assert "ExecutiveCore" in service_source or "get_executive_core" in service_source


def test_06_case_status_never_written_by_touching_tasks_table(gov: GovernmentServices) -> None:
    """حرس ساكن: النطاق لا يكتب في جدول `tasks` بنفسه — النواة وحدها تُغيّر حالتها."""
    for path in sorted(GOV_SRC.glob("*.py")):
        source = _strip_comments(path.read_text(encoding="utf-8"))
        assert "UPDATE tasks" not in source, f"{path.name} يكتب في `tasks` مباشرة"
        assert "INSERT INTO tasks" not in source, f"{path.name} يُدخل في `tasks` مباشرة"


# ── 2. التخويل والسلطة ────────────────────────────────────────────────────


def test_07_publishing_a_service_requires_manage_all(
    gov: GovernmentServices, registry: StateRegistry, crown: AuthorizationContext
) -> None:
    """المسؤول لا يُعلن خدمة — إعلان الخدمة سلطة `manage:all`."""
    institution = _institution(registry, crown)
    with pytest.raises(RegistryAuthorizationError):
        gov.publish_service(
            context=_context("official"),
            institution_code=institution["code"],
            code=_code("SVC"),
            name="خدمة مرفوضة",
        )


def test_08_agent_may_open_a_case_but_not_assign_it(
    gov: GovernmentServices, registry: StateRegistry, crown: AuthorizationContext
) -> None:
    """الوكيل يفتح قضية بـ`write:tasks` ولا يُسنِدها — الإسناد سلطة أعلى."""
    institution = _institution(registry, crown)
    service = _service(gov, crown, institution["code"])
    agent_context = _context("agent")
    case = gov.open_case(
        context=agent_context,
        institution_code=institution["code"],
        service_code=service["code"],
        applicant_agent_id=_agent(),
        subject="طلب من وكيل",
    )
    official = _official(registry, crown, institution["code"])
    with pytest.raises(RegistryAuthorizationError):
        gov.assign_case(
            context=agent_context, reference=case["reference"], official_id=official["id"]
        )


def test_09_unverified_and_expired_sessions_are_refused(
    gov: GovernmentServices, registry: StateRegistry, crown: AuthorizationContext
) -> None:
    """دورٌ مُدَّعى بلا جلسة، أو جلسة منتهية — كلاهما يُرفَض قبل أي قراءة."""
    institution = _institution(registry, crown)
    with pytest.raises(PrincipalUnverifiedError):
        gov.list_services(context=unverified_context("اختبار", claimed_role="king"))
    expired = _context("king", expires_at=datetime.now(UTC) - timedelta(minutes=5))
    with pytest.raises(SessionInvalidError):
        gov.list_cases(context=expired, institution_code=institution["code"])


def test_10_request_models_never_accept_role_or_tenant(gov: GovernmentServices) -> None:
    """حرس ساكن: لا نموذج طلب يقبل `role` أو `permissions` أو `tenant_id` (R7-F)."""
    source = _strip_comments((GOV_SRC / "main.py").read_text(encoding="utf-8"))
    for banned in ("role:", "permissions:", "tenant_id:", "role =", "permissions ="):
        assert banned not in source, f"واجهة النطاق تقبل `{banned}` من العميل"
    assert "Depends(require_context)" in source


def test_11_permission_vocabulary_is_not_invented(gov: GovernmentServices) -> None:
    """كل صلاحية يفحصها النطاق موجودة فعلًا في `DEFAULT_ROLES` — لا مفردة مُختَرعة."""
    seeded = {perm for perms in _ROLE_PERMISSIONS.values() for perm in perms}
    for permission in GOVERNMENT_PERMISSIONS:
        assert permission in seeded, f"صلاحية غير مزروعة: {permission}"


def test_12_decision_requires_a_standing_office_not_just_a_role(
    gov: GovernmentServices, registry: StateRegistry, crown: AuthorizationContext
) -> None:
    """التاج نفسه لا يقرّر بلا منصب قائم في مؤسسة القضية."""
    _worker()
    institution = _institution(registry, crown)
    service = _service(gov, crown, institution["code"])
    case = gov.open_case(
        context=crown,
        institution_code=institution["code"],
        service_code=service["code"],
        applicant_agent_id=_agent(),
        subject="طلب بلا منصب",
    )
    gov.process_case(context=crown, reference=case["reference"])
    with pytest.raises(GovernmentServiceError):
        gov.decide_case(
            context=crown, reference=case["reference"], outcome="approved", rationale="بلا منصب"
        )


def test_13_decision_refuses_an_office_from_another_institution(
    gov: GovernmentServices, registry: StateRegistry, crown: AuthorizationContext
) -> None:
    """منصبٌ قائم في مؤسسة أخرى لا يقرّر في هذه القضية."""
    _worker()
    home = _institution(registry, crown)
    other = _institution(registry, crown)
    service = _service(gov, crown, home["code"])
    foreign_official = _official(registry, crown, other["code"])
    case = gov.open_case(
        context=crown,
        institution_code=home["code"],
        service_code=service["code"],
        applicant_agent_id=_agent(),
        subject="طلب في مؤسسة أخرى",
    )
    gov.process_case(context=crown, reference=case["reference"])
    with pytest.raises(OfficeAuthorityError):
        gov.decide_case(
            context=crown,
            reference=case["reference"],
            outcome="approved",
            rationale="منصب أجنبي",
            official_id=foreign_official["id"],
        )


def test_14_revoked_office_cannot_decide(
    gov: GovernmentServices, registry: StateRegistry, crown: AuthorizationContext
) -> None:
    """المعزول لا يقرّر — السلطة من منصب **قائم** لا من منصب سابق."""
    _worker()
    institution = _institution(registry, crown)
    service = _service(gov, crown, institution["code"])
    official = _official(registry, crown, institution["code"])
    case = gov.open_case(
        context=crown,
        institution_code=institution["code"],
        service_code=service["code"],
        applicant_agent_id=_agent(),
        subject="طلب لمعزول",
    )
    gov.process_case(context=crown, reference=case["reference"])
    registry.revoke_official(context=crown, official_id=official["id"], reason="إعادة تنظيم")
    with pytest.raises(OfficeAuthorityError):
        gov.decide_case(
            context=crown,
            reference=case["reference"],
            outcome="approved",
            rationale="قرار من معزول",
            official_id=official["id"],
        )


# ── 3. قواعد النطاق ───────────────────────────────────────────────────────


def test_15_no_decision_before_the_review_is_terminal(
    gov: GovernmentServices, registry: StateRegistry, crown: AuthorizationContext
) -> None:
    """قضية لم تُعالَج لا قرار فيها — ولو كان صاحب المنصب قائمًا."""
    institution = _institution(registry, crown)
    service = _service(gov, crown, institution["code"])
    official = _official(registry, crown, institution["code"])
    case = gov.open_case(
        context=crown,
        institution_code=institution["code"],
        service_code=service["code"],
        applicant_agent_id=_agent(),
        subject="طلب بلا مراجعة",
    )
    with pytest.raises(ReviewIncompleteError):
        gov.decide_case(
            context=crown,
            reference=case["reference"],
            outcome="approved",
            rationale="قبل المراجعة",
            official_id=official["id"],
        )


def test_16_full_lifecycle_reaches_a_recorded_decision(
    gov: GovernmentServices, registry: StateRegistry, crown: AuthorizationContext
) -> None:
    """المسار الكامل: خدمة ← قضية ← إسناد ← معالجة ← قرار ← إغلاق، بصفوف حقيقية."""
    _worker()
    institution = _institution(registry, crown)
    service = _service(gov, crown, institution["code"])
    official = _official(registry, crown, institution["code"])
    case = gov.open_case(
        context=crown,
        institution_code=institution["code"],
        service_code=service["code"],
        applicant_agent_id=_agent(),
        subject="طلب كامل",
    )
    assigned = gov.assign_case(
        context=crown, reference=case["reference"], official_id=official["id"]
    )
    assert assigned["assigned_official_id"] == official["id"]
    reviewed = gov.process_case(context=crown, reference=case["reference"])
    decision = gov.decide_case(
        context=crown,
        reference=case["reference"],
        outcome="approved",
        rationale="مستوفٍ للشروط",
    )
    assert decision["decided_by_official_id"] == official["id"]
    assert decision["decided_by_principal"] == crown.principal_id
    assert decision["task_final_state"] == reviewed["review_state"]
    closed = gov.close_case(context=crown, reference=case["reference"])
    assert closed["status"] == "closed"

    dossier = gov.case_file(case["reference"], context=crown)
    assert dossier["decision"]["outcome"] == "approved"
    assert dossier["assigned_official"]["id"] == official["id"]
    assert dossier["service"]["code"] == service["code"]


def test_17_one_decision_per_case_enforced_by_the_database(
    gov: GovernmentServices, registry: StateRegistry, crown: AuthorizationContext
) -> None:
    """قرارٌ ثانٍ لنفس القضية مرفوض — في الخدمة وفي القاعدة معًا."""
    _worker()
    institution = _institution(registry, crown)
    service = _service(gov, crown, institution["code"])
    official = _official(registry, crown, institution["code"])
    case = gov.open_case(
        context=crown,
        institution_code=institution["code"],
        service_code=service["code"],
        applicant_agent_id=_agent(),
        subject="طلب بقرار واحد",
    )
    gov.process_case(context=crown, reference=case["reference"])
    first = gov.decide_case(
        context=crown,
        reference=case["reference"],
        outcome="approved",
        rationale="الأول",
        official_id=official["id"],
    )
    with pytest.raises(DecisionExistsError):
        gov.decide_case(
            context=crown,
            reference=case["reference"],
            outcome="rejected",
            rationale="الثاني",
            official_id=official["id"],
        )
    session = get_session_factory()()
    try:
        session.add(
            DecisionModel(
                id=f"dec-dup-{uuid.uuid4().hex[:8]}",
                case_id=first["case_id"],
                decided_by_official_id=official["id"],
                decided_by_principal="bypass",
                outcome="rejected",
                rationale="تجاوز الخدمة",
                tenant_id=DEFAULT_TENANT,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
    finally:
        session.rollback()
        session.close()


def test_18_case_cannot_be_closed_without_a_decision(
    gov: GovernmentServices, registry: StateRegistry, crown: AuthorizationContext
) -> None:
    """لا إغلاق لقضية بلا قرار فيها."""
    institution = _institution(registry, crown)
    service = _service(gov, crown, institution["code"])
    case = gov.open_case(
        context=crown,
        institution_code=institution["code"],
        service_code=service["code"],
        applicant_agent_id=_agent(),
        subject="طلب يُغلَق بلا قرار",
    )
    with pytest.raises(CaseStateError):
        gov.close_case(context=crown, reference=case["reference"])


def test_19_no_case_on_a_suspended_service(
    gov: GovernmentServices, registry: StateRegistry, crown: AuthorizationContext
) -> None:
    """الخدمة الموقوفة لا تُفتح عليها قضية جديدة."""
    institution = _institution(registry, crown)
    service = _service(gov, crown, institution["code"])
    gov.set_service_status(
        context=crown,
        institution_code=institution["code"],
        code=service["code"],
        status="suspended",
        reason="مراجعة إجراءات",
    )
    with pytest.raises(ServiceInactiveError):
        gov.open_case(
            context=crown,
            institution_code=institution["code"],
            service_code=service["code"],
            applicant_agent_id=_agent(),
            subject="طلب على خدمة موقوفة",
        )


def test_20_applicant_must_be_a_real_agent(
    gov: GovernmentServices, registry: StateRegistry, crown: AuthorizationContext
) -> None:
    """الطالب وكيلٌ قائم في `agents` — لا نصٌّ حرّ."""
    institution = _institution(registry, crown)
    service = _service(gov, crown, institution["code"])
    with pytest.raises(UnknownApplicantError):
        gov.open_case(
            context=crown,
            institution_code=institution["code"],
            service_code=service["code"],
            applicant_agent_id="agent-does-not-exist",
            subject="طلب من طالب وهمي",
        )


def test_21_duplicate_service_code_and_unknown_institution_are_refused(
    gov: GovernmentServices, registry: StateRegistry, crown: AuthorizationContext
) -> None:
    """رمز الخدمة فريد في مؤسستها، ولا خدمة تحت مؤسسة غير موجودة."""
    institution = _institution(registry, crown)
    code = _code("SVC")
    gov.publish_service(context=crown, institution_code=institution["code"], code=code, name="خدمة")
    with pytest.raises(DuplicateServiceCodeError):
        gov.publish_service(
            context=crown, institution_code=institution["code"], code=code, name="خدمة مكرَّرة"
        )
    with pytest.raises(ServiceNotFoundError):
        gov.publish_service(
            context=crown, institution_code="INST-GHOST", code=_code("SVC"), name="خدمة معلّقة"
        )


def test_22_vocabularies_are_closed(
    gov: GovernmentServices, registry: StateRegistry, crown: AuthorizationContext
) -> None:
    """الحالات والنتائج من مفردة مُقيَّدة — لا قيمة حرّة تُقبل."""
    institution = _institution(registry, crown)
    service = _service(gov, crown, institution["code"])
    with pytest.raises(GovernmentServiceError):
        gov.set_service_status(
            context=crown,
            institution_code=institution["code"],
            code=service["code"],
            status="مسحوبة-ربما",
            reason="مفردة غير معروفة",
        )
    assert "active" in SERVICE_STATUSES
    assert "decided" in CASE_STATUSES
    assert set(DECISION_OUTCOMES) == {"approved", "rejected", "deferred"}


# ── 4. المستأجر ───────────────────────────────────────────────────────────


def test_23_tenant_isolation_on_read_and_write(
    gov: GovernmentServices, registry: StateRegistry, crown: AuthorizationContext
) -> None:
    """مستأجر آخر لا يرى خدمات هذا المستأجر ولا يكتب فيها."""
    institution = _institution(registry, crown)
    _service(gov, crown, institution["code"])
    other = _context("king", tenant_id="tenant-other", username="other")
    assert gov.list_services(context=other) == []
    with pytest.raises((TenantIsolationError, ServiceNotFoundError)):
        gov.publish_service(
            context=other,
            institution_code=institution["code"],
            code=_code("SVC"),
            name="خدمة عابرة للحدود",
        )


# ── 5. الأثر: تدقيق وأحداث ────────────────────────────────────────────────


def test_24_every_write_leaves_an_audited_traceable_event(
    gov: GovernmentServices, registry: StateRegistry, crown: AuthorizationContext
) -> None:
    """كل كتابة: صفٌّ في سلسلة التدقيق وحدثٌ دائم يُتتبَّع إلى الكيان والفاعل والمهمّة."""
    _worker()
    institution = _institution(registry, crown)
    service = _service(gov, crown, institution["code"])
    official = _official(registry, crown, institution["code"])
    case = gov.open_case(
        context=crown,
        institution_code=institution["code"],
        service_code=service["code"],
        applicant_agent_id=_agent(),
        subject="طلب مُتتبَّع",
    )
    gov.assign_case(context=crown, reference=case["reference"], official_id=official["id"])
    gov.process_case(context=crown, reference=case["reference"])
    decision = gov.decide_case(
        context=crown, reference=case["reference"], outcome="approved", rationale="موافق"
    )
    gov.close_case(context=crown, reference=case["reference"])

    for result in (service, case, decision):
        assert result["audit_id"], "كتابة بلا صفّ تدقيق"
        assert result["event_id"], "كتابة بلا حدث دائم"

    bus = get_durable_event_bus()
    opened = bus.get_events(subject=EVENT_CASE_OPENED, limit=20)
    mine = [event for event in opened if event["data"].get("reference") == case["reference"]]
    assert mine, "لا حدث فتح لهذه القضية"
    payload = mine[0]["data"]
    assert payload["task_id"] == case["task_id"]
    assert payload["actor"] == crown.principal_id
    assert payload["audit_id"]

    # سلسلة التدقيق تراكمية وأحدثها أولًا — نُرشِّح بالفعل والفاعل معًا.
    entries = PersistentAuditStore().list_all(500)
    actions = {
        entry["action"]
        for entry in entries
        if entry.get("actor") == crown.principal_id and str(entry["action"]).startswith("gov.")
    }
    for action in ("gov.service.publish", "gov.case.open", "gov.case.review", "gov.case.decide"):
        assert action in actions, f"لا أثر تدقيق للفعل {action}"


def test_25_all_domain_events_have_contracts_and_validate(
    gov: GovernmentServices, registry: StateRegistry, crown: AuthorizationContext
) -> None:
    """كل حدث للنطاق له عقد، وحمولته الحقيقية تجتاز التحقّق."""
    for subject in GOVERNMENT_EVENTS:
        assert subject in EVENT_CONTRACTS, f"حدث بلا عقد: {subject}"

    _worker()
    institution = _institution(registry, crown)
    service = _service(gov, crown, institution["code"])
    official = _official(registry, crown, institution["code"])
    case = gov.open_case(
        context=crown,
        institution_code=institution["code"],
        service_code=service["code"],
        applicant_agent_id=_agent(),
        subject="طلب للتحقّق من العقود",
    )
    gov.assign_case(context=crown, reference=case["reference"], official_id=official["id"])
    gov.process_case(context=crown, reference=case["reference"])
    gov.decide_case(
        context=crown, reference=case["reference"], outcome="deferred", rationale="ناقص"
    )
    gov.close_case(context=crown, reference=case["reference"])

    bus = get_durable_event_bus()
    for subject in (
        EVENT_SERVICE_PUBLISHED,
        EVENT_CASE_OPENED,
        EVENT_CASE_ASSIGNED,
        EVENT_CASE_REVIEWED,
        EVENT_CASE_DECIDED,
        EVENT_CASE_CLOSED,
    ):
        events = bus.get_events(subject=subject, limit=5)
        assert events, f"لا حدث منشور للموضوع {subject}"
        valid, message = validate_event(subject, events[0]["data"])
        assert valid, f"{subject}: {message}"


def test_26_health_summary_counts_real_rows(
    gov: GovernmentServices, registry: StateRegistry, crown: AuthorizationContext
) -> None:
    """الإحصاء من القاعدة لا تقدير."""
    _worker()
    institution = _institution(registry, crown)
    service = _service(gov, crown, institution["code"])
    official = _official(registry, crown, institution["code"])
    case = gov.open_case(
        context=crown,
        institution_code=institution["code"],
        service_code=service["code"],
        applicant_agent_id=_agent(),
        subject="طلب للإحصاء",
    )
    gov.process_case(context=crown, reference=case["reference"])
    gov.decide_case(
        context=crown,
        reference=case["reference"],
        outcome="rejected",
        rationale="غير مستوفٍ",
        official_id=official["id"],
    )
    health = gov.services_health(context=crown)
    assert health["services"] == 1
    assert health["services_active"] == 1
    assert health["cases"] == 1
    assert health["cases_by_status"] == {"decided": 1}
    assert health["decisions_by_outcome"] == {"rejected": 1}
    assert health["tenant_id"] == DEFAULT_TENANT
    assert service["status"] == "active"


# ── 6. الخدمة مسجَّلة ─────────────────────────────────────────────────────


def test_27_service_is_registered_and_app_mounts(gov: GovernmentServices) -> None:
    """الخدمة في سجل الخدمات بمنفذها، وتطبيقها يُركَّب فعلًا بنقاطه."""
    definition = SERVICES["government-services"]
    assert definition["port"] == 8011

    from fastapi.testclient import TestClient

    from amos_federation.services.government_services.main import app

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        # بلا رمز: تُرفَض، ولا تُرجَع 200 بجسم خطأ.
        assert client.get("/gov/services").status_code in {401, 403}
        assert client.post("/gov/cases/REF-X/process").status_code in {401, 403}
