"""اختبارات R4 — هوية وكيل واحدة، وسكّان كإسقاط لا كسجل ثانٍ

الهدف: إثبات أن الهوية تُنشأ وتُقرأ من مصدر واحد، وأن السكّان إسقاط عنه
النطاق: executive_core.agent_identity + agent_runtime.population/health + dispatcher
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-16

ما تقيسه هذه الحزمة، بندًا ببند من معيار R4:

1. **C — تفرّد الهوية**: معرّف واحد لا يُسجَّل مرّتين، والاسم ليس هوية.
2. **B — القراءة الكانونية**: الهوية تُقرأ من `agents`، والمجهول يسقط صريحًا.
3. **D — الموزِّع كانوني**: وكيل مُسجَّل في السجل الكانوني وحده يُوزَّع عليه فعلًا.
4. **D — التشغيل كانوني**: تعيين التنفيذ يقرأ الصلاحيات من السجل لا من السكّان.
5. **E — السكّان إسقاط**: عدّاد السكّان = عدّاد السجل الكانوني، بلا سجل ثانٍ.
6. **C/E — لا رقم مُختلق**: `executing`/`failed` لا تُصفَّر بل تُعلَن غير مرصودة.
7. **C — دورة حياة واحدة**: تغيير الحالة عبر السكّان ينتقل إلى الحقل الكانوني.
8. **F — الصحّة على مكوّنات**: التقرير يُبنى على فحوص فعلية لا على وجود عملية.
9. **F — الصحّة كانونية**: الفحص الصحي يقرأ الهوية من السجل الكانوني.
10. **G — ترحيل متكرِّر غير مُدمِّر**: صفّ سكّاني بلا هوية يُوفَّق، والتشغيل الثاني بلا أثر.
11. **H — حرس ساكن**: لا إنشاء هوية في مصدرين، ولا قراءة هوية من السكّان في
    الموزِّع أو حدّ بيئة التشغيل، ولا SQL خام يقرأ السكّان كمصدر هوية.
"""

from __future__ import annotations

import tokenize
from pathlib import Path

import pytest

from amos_federation.common.database import get_session_factory, init_db
from amos_federation.services.agent_runtime.health import HealthChecker, population_health
from amos_federation.services.agent_runtime.population import (
    AgentPopulationModel,
    PopulationRegistry,
    unmigrated_profiles,
)
from amos_federation.services.executive_core.agent_identity import (
    CANONICAL_IDENTITY_TABLE,
    PROJECTION_TABLE,
    AgentLifecycleState,
    DuplicateAgentIdentityError,
    UnknownAgentIdentityError,
    get_identity,
    identity_health,
    list_identities,
    new_agent_id,
    population_projection,
    register_identity,
    require_identity,
    set_lifecycle_state,
)
from amos_federation.services.executive_core.agent_runtime_gateway import (
    reset_agent_runtime_gateway,
)
from amos_federation.services.executive_core.dispatcher import (
    WILDCARD,
    CapabilityDispatcher,
    NoEligibleAgentError,
)
from amos_federation.services.executive_core.engine import reset_executive_core
from tests.conftest import purge_agents, purge_tasks

_SERVICES_ROOT = Path(__file__).resolve().parents[1] / "src/amos_federation/services"
_REPO_ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture(autouse=True)
def _fresh_state() -> None:
    """قاعدة نظيفة في الجدولين — القياس على سجل حقيقي لا على بقايا."""
    init_db()
    session = get_session_factory()()
    try:
        purge_tasks(session)
        purge_agents(session)
        session.commit()
    finally:
        session.close()
    registry = PopulationRegistry()
    session = registry._Session()  # noqa: SLF001 — تهيئة اختبار
    try:
        session.query(AgentPopulationModel).delete()
        session.commit()
    finally:
        session.close()
    reset_executive_core()
    reset_agent_runtime_gateway()


def _code_only(path: Path) -> str:
    """نصّ الملفّ بلا تعليقات ولا سلاسل — الحرس يقيس كودًا لا توثيقًا."""
    tokens = []
    with path.open("rb") as handle:
        for token in tokenize.tokenize(handle.readline):
            if token.type in {tokenize.COMMENT, tokenize.STRING}:
                continue
            tokens.append(token.string)
    return "\n".join(tokens)


def _plan(tool: str = "data_analysis") -> list[dict[str, str]]:
    return [{"tool": tool, "description": "خطوة قياس"}]


# ── R4-C: تفرّد الهوية ────────────────────────────────────────────────────
def test_identity_is_unique_and_name_is_not_identity() -> None:
    """المعرّف لا يُسجَّل مرّتين، ووكيلان بنفس الاسم هويّتان مختلفتان.

    قبل R4 كان `agent_population.register_agent` يولّد معرّفًا جديدًا لكل نداء
    ولو لنفس الوكيل، و`dispatcher.register_agent` يستعمل `session.merge` فيكتب
    فوق هوية قائمة بلا اعتراض. الآن الإنشاء يرفض التكرار صراحةً.
    """
    identity = register_identity("r4-unique", "وكيل قياس", "worker")
    with pytest.raises(DuplicateAgentIdentityError):
        register_identity("r4-unique", "اسم آخر تمامًا", "auditor")

    twin_a = register_identity(new_agent_id(), "اسم مكرَّر", "worker")
    twin_b = register_identity(new_agent_id(), "اسم مكرَّر", "worker")
    assert twin_a.agent_id != twin_b.agent_id
    assert identity.as_dict()["identity_source"] == CANONICAL_IDENTITY_TABLE
    assert len(list_identities()) == 3


# ── R4-B: القراءة الكانونية ──────────────────────────────────────────────
def test_canonical_lookup_reads_agents_table_and_unknown_fails_loud() -> None:
    """الهوية تُقرأ من الجدول الكانوني، والمجهول يرفع خطأً لا يُخترَع وكيلًا."""
    register_identity("r4-lookup", "وكيل قراءة", "worker", allowed_tools=["sql_query"])
    identity = require_identity("r4-lookup")
    assert identity.allowed_tools == ("sql_query",)
    assert identity.lifecycle_state == AgentLifecycleState.REGISTERED.value
    assert identity.employable is True

    assert get_identity("r4-does-not-exist") is None
    with pytest.raises(UnknownAgentIdentityError):
        require_identity("r4-does-not-exist")


# ── R4-D: الموزِّع يقرأ الكانوني ─────────────────────────────────────────
def test_dispatcher_selects_from_canonical_registry_only() -> None:
    """وكيل موجود في السجل الكانوني وحده يُوزَّع عليه؛ وصفّ سكّاني وحده لا يُوزَّع.

    هذا هو جوهر الازدواجية قبل R4: كان يمكن أن يوجد «وكيل» في `agent_population`
    لا يعرفه الموزِّع أبدًا. القياس يُنشئ صفًّا سكّانيًّا خامًا بلا هوية كانونية
    ويتأكّد أن التوزيع يسقط.
    """
    session = PopulationRegistry()._Session()  # noqa: SLF001 — كتابة خام مقصودة للقياس
    try:
        session.add(
            AgentPopulationModel(
                agent_id="r4-population-only",
                name="وكيل سكّاني بلا هوية",
                role="worker",
                category="cognitive",
                state="active",
                permissions="[]",
                allowed_tools='["*"]',
            )
        )
        session.commit()
    finally:
        session.close()

    with pytest.raises(NoEligibleAgentError):
        CapabilityDispatcher().select(_plan())

    register_identity("r4-canonical", "وكيل كانوني", "worker", allowed_tools=[WILDCARD])
    assignment = CapabilityDispatcher().select(_plan())
    assert assignment.agent_id == "r4-canonical"


# ── R4-D: التشغيل يقرأ الكانوني ──────────────────────────────────────────
def test_runtime_assignment_reads_capabilities_from_canonical_not_population() -> None:
    """الصلاحيات لحظة التنفيذ تأتي من `agents`؛ تغييرها في السكّان لا يغيّرها."""
    registry = PopulationRegistry()
    agent = registry.register_agent(
        name="وكيل تشغيل",
        role="worker",
        category="cognitive",
        permissions=["task:execute"],
        allowed_tools=[WILDCARD],
    )
    agent_id = agent["agent_id"]

    session = registry._Session()  # noqa: SLF001 — تلويث المرآة المهجورة عمدًا
    try:
        row = (
            session.query(AgentPopulationModel)
            .filter(AgentPopulationModel.agent_id == agent_id)
            .first()
        )
        row.allowed_tools = "[]"
        row.permissions = '["root:everything"]'
        session.commit()
    finally:
        session.close()

    assignment = CapabilityDispatcher().assignment_for(agent_id, _plan())
    assert assignment.allowed_tools == (WILDCARD,)
    assert assignment.permissions == ("task:execute",)


# ── R4-E: السكّان إسقاط لا سجل ثانٍ ──────────────────────────────────────
def test_population_is_a_projection_of_the_canonical_registry() -> None:
    """عدّاد السكّان = عدّاد السجل الكانوني، والصفوف تُعلن مصدر هويّتها."""
    registry = PopulationRegistry()
    for index in range(3):
        registry.register_agent(
            name=f"وكيل {index}", role="worker", category="cognitive", allowed_tools=["sql_query"]
        )
    register_identity("r4-canonical-only", "وكيل بلا ملفّ", "auditor")

    projection = population_projection()
    stats = registry.population_stats()
    assert projection["total"] == len(list_identities()) == 4
    assert stats["total"] == projection["total"]
    assert projection["identity_source"] == CANONICAL_IDENTITY_TABLE
    assert all(row["canonical"] for row in registry.list_agents())
    assert unmigrated_profiles() == []


# ── R4-E/J: لا رقم مُختلق ────────────────────────────────────────────────
def test_projection_declares_unobserved_runtime_counts_instead_of_zero() -> None:
    """`executing`/`failed` غير مرصودتين ⇒ `None` وإعلان صريح، لا صفر كأنه قياس."""
    register_identity("r4-idle", "وكيل خامل", "worker", allowed_tools=[WILDCARD])
    projection = population_projection()
    activity = projection["runtime_activity"]
    if not activity["observed"]:
        assert projection["executing"] is None
        assert projection["failed"] is None
    else:
        assert isinstance(projection["executing"], int)
    assert projection["employable"] == 1
    assert activity["source"].endswith("agent_lifecycle")


# ── R4-C: دورة حياة واحدة ───────────────────────────────────────────────
def test_lifecycle_state_is_consistent_across_canonical_and_projection() -> None:
    """تغيير الحالة عبر واجهة السكّان يكتب الحقل الكانوني، والتقاعد يمنع التنفيذ."""
    registry = PopulationRegistry()
    agent = registry.register_agent(
        name="وكيل دورة حياة", role="worker", category="cognitive", allowed_tools=[WILDCARD]
    )
    agent_id = agent["agent_id"]

    assert registry.update_state(agent_id, AgentLifecycleState.RETIRED.value) is True
    assert require_identity(agent_id).lifecycle_state == AgentLifecycleState.RETIRED.value
    assert registry.get_agent(agent_id)["state"] == AgentLifecycleState.RETIRED.value
    with pytest.raises(NoEligibleAgentError):
        CapabilityDispatcher().assignment_for(agent_id, _plan())

    assert set_lifecycle_state(agent_id, AgentLifecycleState.EMPLOYED.value) is True
    assert CapabilityDispatcher().assignment_for(agent_id, _plan()).agent_id == agent_id
    assert set_lifecycle_state("r4-ghost", AgentLifecycleState.ACTIVE.value) is False


# ── R4-F: الصحّة على مكوّنات حقيقية ──────────────────────────────────────
def test_health_report_is_built_on_component_checks_not_process_existence() -> None:
    """التقرير يسمّي المكوّنات المفحوصة، وينزل عن `healthy` عند صفّ غير مُوفَّق."""
    report = identity_health()
    assert report["basis"] == "component_checks"
    assert {"canonical_registry", "event_bus", "population_projection"} <= set(report["components"])
    assert report["status"] == "healthy"

    session = PopulationRegistry()._Session()  # noqa: SLF001 — إدخال دَين توفيق مقصود
    try:
        session.add(
            AgentPopulationModel(
                agent_id="r4-orphan",
                name="صفّ بلا هوية",
                role="worker",
                category="cognitive",
                state="active",
            )
        )
        session.commit()
    finally:
        session.close()

    degraded = population_health()
    assert degraded["status"] == "degraded"
    projection = degraded["components"]["population_projection"]
    assert projection["unmigrated_profile_rows"] == 1
    assert projection["reconciliation_debt_rows"] == 1, "حالة active = دليل ⇒ دَين حقيقي"
    assert projection["legacy_seed_rows"] == 0
    assert degraded["components"]["isolation_system"]["status"] == "available"


def test_legacy_seed_rows_are_declared_but_do_not_degrade_health() -> None:
    """صفّ بذر بلا أثر يُعلَن legacy ولا يُنزِل الصحّة — ولا يُخفَى.

    قبل R4 (OPTION 2) كان كلّ صفّ بلا هوية يُحسب دَين توفيق، فكانت 5068 صفّ
    بذر تُبقي النِّطاق `degraded` دائمًا فيفقد المقياس قيمته التشخيصية.
    """
    from amos_federation.services.agent_runtime.population import (
        legacy_seed_profiles,
        reconciliation_debt,
    )

    session = PopulationRegistry()._Session()  # noqa: SLF001 — حالة ما قبل الترحيل
    try:
        session.add(
            AgentPopulationModel(
                agent_id="r4-seed-row",
                name="احتياطي 1",
                role="worker",
                category="cognitive",
                state=AgentLifecycleState.REGISTERED.value,
            )
        )
        session.commit()
    finally:
        session.close()

    assert legacy_seed_profiles() == ["r4-seed-row"]
    assert reconciliation_debt() == []

    report = population_health()
    projection = report["components"]["population_projection"]
    assert projection["status"] == "available", "بذر بلا أثر ليس خللًا"
    assert projection["legacy_seed_rows"] == 1, "لكنّه مُعلَن لا مخفيّ"
    assert projection["unmigrated_profile_rows"] == 1
    assert projection["reconciliation_debt_rows"] == 0


# ── R4-F: الفحص الصحي يقرأ الهوية الكانونية ──────────────────────────────
def test_health_checker_reads_identity_from_canonical_registry() -> None:
    """وكيل كانوني بلا صفّ سكّاني يُفحَص؛ ووكيل غير مُسجَّل يسقط صريحًا."""
    register_identity("r4-health", "وكيل صحّة", "worker", allowed_tools=["sql_query"])
    check = HealthChecker().check_agent("r4-health")
    assert check["agent_id"] == "r4-health"
    assert check["resource_usage"]["tools_available"] == 1
    with pytest.raises(ValueError, match="غير موجود"):
        HealthChecker().check_agent("r4-not-registered")


# ── R4-G: ترحيل بالدليل التاريخي وحده (OPTION 2) ─────────────────────────
def _load_migration():
    """تحميل سكربت الترحيل كوحدة — مسجَّلة في `sys.modules` كي يعمل الاستبطان."""
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(
        "r4_migration", _REPO_ROOT / "tools/migrations/r4_unify_agent_identity.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["r4_migration"] = module
    spec.loader.exec_module(module)
    return module


def _add_population_row(agent_id: str, **overrides: object) -> None:
    session = PopulationRegistry()._Session()  # noqa: SLF001 — حالة ما قبل الترحيل
    try:
        fields: dict[str, object] = {
            "agent_id": agent_id,
            "name": "وكيل",
            "role": "auditor",
            "category": "audit",
            "state": AgentLifecycleState.REGISTERED.value,
            "permissions": '["audit:view"]',
            "allowed_tools": '["sql_query"]',
        }
        fields.update(overrides)
        session.add(AgentPopulationModel(**fields))
        session.commit()
    finally:
        session.close()


def test_migration_applies_only_to_rows_with_historical_evidence() -> None:
    """صفّ البذر لا يكتسب هوية؛ الصفّ ذو الدليل يكتسبها بنفس المعرّف.

    الحقيقة المقيسة التي فرضت هذه السياسة: `agent_population` الحقيقي يحمل 5116
    صفًّا بـ24 اسمًا متميزًا فقط (تنفيذ بذر متكرِّر)، و`registered` من
    `EMPLOYABLE_STATUSES`؛ فترحيل الكل كان سيُدخل آلاف الوكلاء إلى التوزيع.
    """
    module = _load_migration()

    _add_population_row("r4-seed-only")  # بذر: registered وبلا أي أثر
    _add_population_row(
        "r4-evidenced-state",
        name="وكيل تاريخي",
        state=AgentLifecycleState.EMPLOYED.value,
    )

    dry = module.migrate()
    assert dry["applied"] is False
    assert dry["policy"] == "OPTION_2_HISTORICAL_EVIDENCE_ONLY"
    assert dry["total_population"] == 2
    assert dry["historically_evidenced_rows"] == 1
    assert dry["canonical_agents_to_create"] == 1
    assert dry["seed_only_rows"] == 1
    assert dry["created_agent_ids"] == ["r4-evidenced-state"]
    assert get_identity("r4-evidenced-state") is None, "الفحص لا يكتب"

    first = module.migrate(apply=True)
    assert first["identities_created"] == 1
    assert first["failed"] == []
    assert first["rows_deleted"] == 0
    assert first["columns_cleared"] == 0

    migrated = require_identity("r4-evidenced-state")
    assert migrated.agent_id == "r4-evidenced-state", "نفس المعرّف: provenance محفوظة"
    assert migrated.name == "وكيل تاريخي"
    assert migrated.lifecycle_state == AgentLifecycleState.EMPLOYED.value
    assert migrated.allowed_tools == ("sql_query",)

    assert get_identity("r4-seed-only") is None, "صفّ البذر لا هوية له"
    assert len(list_identities()) == 1

    # غير مُدمِّر: الصفّان السكّانيان باقيان كما هما.
    session = PopulationRegistry()._Session()  # noqa: SLF001
    try:
        assert session.query(AgentPopulationModel).count() == 2
    finally:
        session.close()

    second = module.migrate(apply=True)
    assert second["identities_created"] == 0
    assert second["already_canonical"] == 1
    assert second["seed_only_rows"] == 1


def test_school_results_are_historical_evidence_even_when_state_is_seed() -> None:
    """سجل مدرسة حقيقي = دليل، فيُرحَّل الصفّ ولو بقيت حالته `registered`."""
    module = _load_migration()
    from amos_federation.services.agent_runtime.population import SchoolResultModel

    _add_population_row("r4-schooled")
    session = PopulationRegistry()._Session()  # noqa: SLF001
    try:
        session.add(SchoolResultModel(agent_id="r4-schooled", step="1", passed="true", score=90))
        session.commit()
    finally:
        session.close()

    report = module.migrate(apply=True)
    assert report["historically_evidenced_rows"] == 1
    assert report["seed_only_rows"] == 0
    assert "reference:school_results" in module.classify()["_evidenced"][0]["evidence"]
    assert require_identity("r4-schooled").lifecycle_state == AgentLifecycleState.REGISTERED.value


def test_orphan_history_never_invents_an_identity() -> None:
    """أثر تاريخي لمعرّف بلا صفّ سكّاني: يُعلَن unresolved ولا تُخترَع هوية."""
    module = _load_migration()
    from amos_federation.common.database import ExperienceModel

    session = get_session_factory()()
    try:
        session.add(ExperienceModel(id="exp-orphan", type="task", agent_id="worker-ghost"))
        session.commit()
    finally:
        session.close()

    report = module.migrate(apply=True)
    assert "worker-ghost" in report["unresolved_identifiers"]
    assert "worker-ghost" in report["orphan_references"]["experiences"]
    assert report["unresolved_rows"] == len(report["unresolved_identifiers"])
    assert get_identity("worker-ghost") is None, "لا هوية بلا إثبات هوية"
    assert "worker-ghost" not in {identity.agent_id for identity in list_identities()}


def test_name_and_name_role_are_not_identity_in_migration() -> None:
    """صفّان بنفس (الاسم، الدور) ⇒ هويّتان منفصلتان، والتصادم يُعلَن لا يُدمَج."""
    module = _load_migration()

    _add_population_row("r4-twin-a", name="توأم", state=AgentLifecycleState.ACTIVE.value)
    _add_population_row("r4-twin-b", name="توأم", state=AgentLifecycleState.ACTIVE.value)

    report = module.migrate(apply=True)
    assert report["identities_created"] == 2, "الاسم ليس هوية: لا دمج"
    assert report["ambiguous_identities"] == [
        {"name": "توأم", "role": "auditor", "agent_ids": ["r4-twin-a", "r4-twin-b"]}
    ]
    assert require_identity("r4-twin-a").agent_id != require_identity("r4-twin-b").agent_id
    assert unmigrated_profiles() == []


def test_emitted_sql_is_evidence_gated_transactional_and_non_destructive() -> None:
    """SQL المكافئ يحمل نفس السياسة: معاملة واحدة، بلا حذف، وبلا اسم كهوية."""
    sql = _load_migration().emit_sql()
    statements = "\n".join(
        line for line in sql.splitlines() if not line.lstrip().startswith("--")
    ).upper()
    assert sql.count("BEGIN;") == 1 and sql.count("COMMIT;") == 1
    assert "ON CONFLICT (ID) DO NOTHING" in statements, "idempotent"
    assert "DELETE" not in statements and "TRUNCATE" not in statements
    assert "UPDATE AGENT_POPULATION" not in statements
    assert "P.STATE <> 'REGISTERED'" in statements, "حالة غير البذر = دليل"
    assert "FROM SCHOOL_RESULTS" in statements and "FROM EXPERIENCES" in statements
    assert "GROUP BY P.NAME" not in statements and "P.NAME =" not in statements


# ── R4-H: حرس ساكن ضدّ العودة للازدواجية ────────────────────────────────
def test_static_guards_forbid_second_identity_source() -> None:
    """لا يُنشئ الهوية إلا السجل الكانوني، ولا يقرأها الموزِّع/الحدّ من السكّان."""
    population_code = _code_only(_SERVICES_ROOT / "agent_runtime/population.py")
    assert "register_identity" in population_code
    assert "uuid" not in population_code, "توليد معرّف هوية محليًّا يعيد الازدواجية"

    for module_name in ("executive_core/dispatcher.py", "executive_core/agent_runtime_gateway.py"):
        code = _code_only(_SERVICES_ROOT / module_name)
        assert "population" not in code, f"{module_name} يقرأ السكّان كمصدر هوية"

    health_code = _code_only(_SERVICES_ROOT / "agent_runtime/health.py")
    assert "get_population_registry" not in health_code
    assert "get_identity" in health_code
    assert "set_lifecycle_state" in health_code

    royal_source = (_SERVICES_ROOT / "royal/main.py").read_text(encoding="utf-8")
    assert "FROM agent_population" not in royal_source, "SQL خام يقرأ السكّان كمصدر هوية"
    assert "UPDATE agent_population" not in royal_source, "SQL خام يعدّل السكّان كمصدر هوية"

    identity_code = _code_only(_SERVICES_ROOT / "executive_core/agent_identity.py")
    assert "merge" not in identity_code, "الدمج الصامت يكتب فوق هوية قائمة"

    writers = []
    for path in sorted(_SERVICES_ROOT.rglob("*.py")):
        if path.name == "population.py":
            continue
        if "AgentPopulationModel" in _code_only(path):
            writers.append(str(path.relative_to(_SERVICES_ROOT)))
    assert writers == [], f"جدول السكّان يُكتب من خارج وحدته: {writers}"
    assert PROJECTION_TABLE == "agent_population"
