"""اختبارات النواة التنفيذية الفدرالية

الهدف: إثبات أن دورة حياة المهمة تمرّ بالبوابة السيادية وتُكتب ذرّيًا وتُدقَّق
النطاق: amos_federation.services.executive_core
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-16
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from amos_federation.common.database import get_session_factory, init_db
from amos_federation.common.persistent import PersistentAuditStore
from amos_federation.services.executive_core import (
    CapabilityDispatcher,
    ExecutionRefusedError,
    ExecutiveCore,
    ExecutiveTaskRepository,
    IllegalTransitionError,
    NoEligibleAgentError,
    TaskNotFoundError,
    TaskState,
    assert_transition,
    is_legal,
    is_terminal,
    next_states,
    parse_state,
    register_agent,
    reset_executive_core,
)
from amos_federation.services.executive_core.dispatcher import WILDCARD
from amos_federation.services.executive_core.engine import TRANSITION_SUBJECT
from amos_federation.services.executive_core.main import app
from tests.conftest import purge_agents, purge_tasks


@pytest.fixture(autouse=True)
def _fresh_db() -> None:
    """قاعدة الاختبار جاهزة ونواة غير محفوظة قبل كل اختبار.

    تُفرَّغ صفوف المهام والوكلاء لأن ملف قاعدة الاختبار مشترك بين الاختبارات:
    بلا تفريغ، يعتمد اختبارُ العدد على ترتيب التشغيل — وهذا اختبار يكذب.
    """
    init_db()
    session = get_session_factory()()
    try:
        purge_tasks(session)
        purge_agents(session)
        session.commit()
    finally:
        session.close()
    reset_executive_core()


@pytest.fixture
def core() -> ExecutiveCore:
    return ExecutiveCore()


@pytest.fixture
def worker() -> dict[str, Any]:
    return register_agent(
        "worker-exec-test",
        "عامل اختبار النواة",
        "worker",
        allowed_tools=[WILDCARD],
        status="active",
    )


# ── آلة الحالات ───────────────────────────────────────────────────────────
def test_state_machine_rejects_illegal_transition() -> None:
    """آلة الحالات ترفض الانتقال غير المشروع بلا استثناء مبتلَع."""
    assert is_legal(TaskState.CREATED, TaskState.AUTHORIZED)
    assert not is_legal(TaskState.CREATED, TaskState.COMPLETED)
    with pytest.raises(IllegalTransitionError):
        assert_transition(TaskState.COMPLETED, TaskState.EXECUTING)


def test_terminal_states_have_no_successors() -> None:
    for state in (TaskState.COMPLETED, TaskState.FAILED, TaskState.REJECTED, TaskState.CANCELLED):
        assert is_terminal(state)
        assert next_states(state) == frozenset()


def test_parse_state_rejects_unknown_status() -> None:
    from amos_federation.services.executive_core import UnknownStateError

    with pytest.raises(UnknownStateError):
        parse_state("almost_done")


# ── المستودع: الانتقال الذرّي ───────────────────────────────────────────────
def test_compare_and_set_applies_once_only() -> None:
    """انتقال الحالة يُطبَّق مرّة واحدة — الثانية تُرجع False لا استثناءً صامتًا."""
    repo = ExecutiveTaskRepository()
    repo.create("task-cas-1", "analysis", "اختبار الانتقال الذرّي")
    assert repo.compare_and_set("task-cas-1", TaskState.CREATED, TaskState.AUTHORIZED)
    assert not repo.compare_and_set("task-cas-1", TaskState.CREATED, TaskState.AUTHORIZED)
    assert repo.state_of("task-cas-1") is TaskState.AUTHORIZED


def test_repository_requires_existing_task() -> None:
    with pytest.raises(TaskNotFoundError):
        ExecutiveTaskRepository().require("task-does-not-exist")


# ── الموزّع: القدرة لا الاسم ───────────────────────────────────────────────
def test_dispatcher_refuses_when_no_agent_has_the_tools() -> None:
    """لا وكيل مؤهَّل ⇒ استثناء صريح، لا اختيار وكيل غير قادر."""
    register_agent("agent-limited", "وكيل محدود", "worker", allowed_tools=["generation"])
    with pytest.raises(NoEligibleAgentError):
        CapabilityDispatcher().select([{"tool": "sql_query", "number": 1}])


def test_dispatcher_selects_agent_covering_required_tools() -> None:
    register_agent("agent-limited", "وكيل محدود", "worker", allowed_tools=["generation"])
    register_agent(
        "agent-capable",
        "وكيل قادر",
        "worker",
        allowed_tools=["sql_query", "data_analysis"],
        status="active",
    )
    assignment = CapabilityDispatcher().select(
        [{"tool": "sql_query", "number": 1}, {"tool": "data_analysis", "number": 2}]
    )
    assert assignment.agent_id == "agent-capable"
    assert assignment.required_tools == ("sql_query", "data_analysis")


def test_dispatcher_ignores_preference_without_capability() -> None:
    """التفضيل لا يلغي القدرة."""
    register_agent("agent-weak", "وكيل ضعيف", "worker", allowed_tools=["generation"])
    register_agent("agent-strong", "وكيل قوي", "worker", allowed_tools=[WILDCARD])
    assignment = CapabilityDispatcher().select(
        [{"tool": "sql_query", "number": 1}], preferred_agent="agent-weak"
    )
    assert assignment.agent_id == "agent-strong"


# ── دورة الحياة الكاملة ───────────────────────────────────────────────────
def test_full_lifecycle_reaches_completed(core: ExecutiveCore, worker: dict[str, Any]) -> None:
    """المهمّة تمرّ created → authorized → planned → dispatched → executing → completed."""
    submitted = core.submit("data", "تشغيل دورة حياة كاملة")
    result = core.run(submitted["id"])
    states = [transition["to_state"] for transition in result["transitions"]]
    assert states == ["authorized", "planned", "dispatched", "executing", "completed"]
    assert result["final_state"] == "completed"
    assert result["terminal"] is True
    assert result["task"]["assigned_agent"] == worker["agent_id"]


def test_every_transition_carries_sovereign_authority(
    core: ExecutiveCore, worker: dict[str, Any]
) -> None:
    """كل انتقال يحمل دليل إذن من البوابة السيادية — لا انتقال بلا سلطة."""
    result = core.submit_and_run("analysis", "إثبات أن كل انتقال مأذون")
    assert result["transitions"], "لا انتقالات مسجّلة"
    for transition in result["transitions"]:
        authority = transition["authority"]
        assert authority["decision"] == "ALLOW"
        assert authority["request_fingerprint"]
        assert authority["authority_layer"]


def test_transitions_are_audited_and_published(core: ExecutiveCore, worker: dict[str, Any]) -> None:
    """كل انتقال يُقيَّد في سلسلة تدقيق سليمة ويُنشَر كحدث دائم."""
    result = core.submit_and_run("report", "إثبات التدقيق والنشر")
    task_id = result["task"]["id"]

    audit = PersistentAuditStore()
    actions = {entry["action"] for entry in audit.list_all(limit=200)}
    assert "executive.task.completed" in actions
    assert audit.verify_chain()["valid"] is True

    events = core._bus.get_events(subject=TRANSITION_SUBJECT, limit=200)
    task_events = [event for event in events if event["data"]["task_id"] == task_id]
    assert len(task_events) >= 5
    assert {event["data"]["to_state"] for event in task_events} >= {
        "authorized",
        "planned",
        "dispatched",
        "executing",
        "completed",
    }


def test_task_without_eligible_agent_fails_explicitly(core: ExecutiveCore) -> None:
    """بلا وكيل مُسجَّل: المهمّة تسقط بسبب مُسجَّل، ولا تُنفَّذ بوكيل وهمي."""
    result = core.submit_and_run("data", "لا وكيل مؤهَّل في السجل")
    assert result["final_state"] == "failed"
    assert result["task"]["result"]["error"] == "no_eligible_agent"


def test_advance_refuses_terminal_task(core: ExecutiveCore, worker: dict[str, Any]) -> None:
    result = core.submit_and_run("analysis", "مهمّة منتهية لا تُقدَّم")
    with pytest.raises(ExecutionRefusedError):
        core.advance(result["task"]["id"])


def test_result_declares_simulation_fidelity(core: ExecutiveCore, worker: dict[str, Any]) -> None:
    """صدق المخرَج: تنفيذ الأدوات محاكاة ومُعلَن كذلك في النتيجة."""
    result = core.submit_and_run("generic", "أمانة المخرَج")
    assert result["task"]["result"]["execution_fidelity"] == "SIMULATION"


def test_cancel_before_execution_and_not_after(core: ExecutiveCore, worker: dict[str, Any]) -> None:
    """الإلغاء مسموح قبل التنفيذ وممنوع أثناءه — لأن الصفّ لا يوقف عملًا جاريًا."""
    task = core.submit("analysis", "إلغاء قبل التنفيذ")
    outcome = core.cancel(task["id"], "قرار تنفيذي")
    assert outcome.to_state is TaskState.CANCELLED

    running = core.submit("analysis", "إلغاء أثناء التنفيذ")
    for _ in range(4):
        core.advance(running["id"])
    assert core._repo.state_of(running["id"]) is TaskState.EXECUTING
    with pytest.raises(IllegalTransitionError):
        core.cancel(running["id"], "محاولة إلغاء متأخّرة")


def test_recover_marks_interrupted_execution_as_failed(
    core: ExecutiveCore, worker: dict[str, Any]
) -> None:
    """مهمّة انقطعت أثناء التنفيذ تُعلَن فاشلة، لا مكتملة ولا مُعاد تشغيلها."""
    task = core.submit("analysis", "انقطاع أثناء التنفيذ")
    for _ in range(4):
        core.advance(task["id"])
    assert core._repo.state_of(task["id"]) is TaskState.EXECUTING

    report = core.recover()
    assert report["interrupted_count"] == 1
    assert core._repo.state_of(task["id"]) is TaskState.FAILED
    assert core._repo.require(task["id"])["result"]["error"] == "interrupted_execution"


def test_recover_advances_unstarted_tasks(core: ExecutiveCore, worker: dict[str, Any]) -> None:
    core.submit("analysis", "مهمّة لم تبدأ")
    report = core.recover()
    assert report["resumed_count"] == 1


# ── الواجهة ───────────────────────────────────────────────────────────────
def test_http_submit_and_status_roundtrip(worker: dict[str, Any]) -> None:
    client = TestClient(app)
    response = client.post(
        "/v1/executive/tasks",
        json={"type": "data", "description": "مهمّة عبر الواجهة", "run": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["final_state"] == "completed"

    status = client.get(f"/v1/executive/tasks/{body['task']['id']}")
    assert status.status_code == 200
    assert status.json()["state"] == "completed"
    assert status.json()["terminal"] is True


def test_http_unknown_task_is_404() -> None:
    client = TestClient(app)
    assert client.get("/v1/executive/tasks/task-missing").status_code == 404


def test_http_state_reports_crown_and_supreme_authority() -> None:
    """حالة النواة تُظهر أن التاج أعلى سلطة — لا طبقة أعلى منه."""
    response = TestClient(app).get("/v1/executive/state")
    assert response.status_code == 200
    body = response.json()
    assert body["crown_status"]
    assert body["supreme_authority"]
    assert body["execution_fidelity"] == "SIMULATION"


# ── فروع الحدّ والفشل ─────────────────────────────────────────────────────
def test_injected_planner_and_agent_factory_are_used(worker: dict[str, Any]) -> None:
    """يمكن حقن مُخطِّط ووكيل — الحقن للاختبار لا يغيّر المسار الحقيقي."""
    calls: dict[str, int] = {"plan": 0, "agent": 0}

    def planner(task: dict[str, Any]) -> list[dict[str, Any]]:
        calls["plan"] += 1
        return [{"number": 1, "description": "خطوة محقونة", "tool": "generation"}]

    class StubAgent:
        async def execute(self, task: dict[str, Any], plan: list[dict[str, Any]]) -> dict[str, Any]:
            calls["agent"] += 1
            return {"steps": plan, "status": "done"}

    def factory(assignment: Any) -> StubAgent:
        return StubAgent()

    core = ExecutiveCore(planner=planner, agent_factory=factory)
    result = core.submit_and_run("analysis", "حقن مُخطِّط ووكيل")
    assert result["final_state"] == "completed"
    assert calls == {"plan": 1, "agent": 1}


def test_empty_plan_fails_task(worker: dict[str, Any]) -> None:
    """خطة فارغة تُسقط المهمّة بسبب مُسجَّل، ولا تُمرَّر إلى التوزيع."""
    core = ExecutiveCore(planner=lambda task: [])
    result = core.submit_and_run("analysis", "خطة فارغة")
    assert result["final_state"] == "failed"
    assert result["task"]["result"]["error"] == "empty_plan"


def test_agent_exception_fails_task_with_recorded_cause(worker: dict[str, Any]) -> None:
    """فشل الوكيل يُسجَّل بنوعه ورسالته — لا يُبتلَع ولا يُقلب نجاحًا."""

    class ExplodingAgent:
        async def execute(self, task: dict[str, Any], plan: list[dict[str, Any]]) -> dict[str, Any]:
            raise RuntimeError("الأداة سقطت فعلًا")

    core = ExecutiveCore(agent_factory=lambda assignment: ExplodingAgent())
    result = core.submit_and_run("analysis", "سقوط وكيل")
    assert result["final_state"] == "failed"
    assert result["task"]["result"]["error"] == "RuntimeError"
    assert "الأداة سقطت فعلًا" in result["task"]["result"]["message"]


def test_constitutional_denial_rejects_task(worker: dict[str, Any]) -> None:
    """حكم DENY على المهمّة يُنتج حالة `rejected` مع حفظ الحكم في نتيجتها."""
    from amos_federation.services.executive_core.sovereignty_bridge import (
        AuthorityEvidence,
        ConstitutionalAuthorizer,
    )

    class DenyingAuthorizer(ConstitutionalAuthorizer):
        def review_only(
            self, action: str, target: str, metadata: dict[str, Any] | None = None
        ) -> AuthorityEvidence:
            return AuthorityEvidence(
                action=action,
                target=target,
                decision="DENY",
                authority_layer="CONSTITUTIONAL",
                decision_kind="SUBORDINATE",
                request_fingerprint="test-fingerprint",
                ledger_entry_hash=None,
                rules_evaluated=1,
                advisory_violations=(),
            )

    core = ExecutiveCore(authorizer=DenyingAuthorizer())
    result = core.submit_and_run("analysis", "مهمّة مرفوضة دستوريًّا")
    assert result["final_state"] == "rejected"
    assert result["task"]["result"]["rejection"]["decision"] == "DENY"


def test_executing_task_without_agent_fails(core: ExecutiveCore, worker: dict[str, Any]) -> None:
    """مهمّة في التنفيذ بلا وكيل مُعيَّن تسقط بسبب `missing_agent`."""
    task = core.submit("analysis", "تنفيذ بلا وكيل")
    for _ in range(4):
        core.advance(task["id"])
    repo = ExecutiveTaskRepository()
    session_task = repo.require(task["id"])
    assert session_task["status"] == "executing"

    from sqlalchemy import update

    from amos_federation.common.database import TaskModel, get_session_factory

    session = get_session_factory()()
    try:
        session.execute(
            update(TaskModel).where(TaskModel.id == task["id"]).values(assigned_agent=None)
        )
        session.commit()
    finally:
        session.close()

    outcome = core.advance(task["id"])
    assert outcome.to_state is TaskState.FAILED
    assert outcome.detail["reason"] == "missing_agent"


def test_run_respects_max_steps_without_claiming_completion(
    core: ExecutiveCore, worker: dict[str, Any]
) -> None:
    """تشغيل محدود الخطوات يُرجع حالة غير نهائية صريحة — لا يُدّعى الإنجاز."""
    task = core.submit("analysis", "تشغيل خطوة واحدة")
    result = core.run(task["id"], max_steps=1)
    assert result["terminal"] is False
    assert result["final_state"] == "authorized"
    assert len(result["transitions"]) == 1


def test_concurrent_transition_is_refused_not_faked(worker: dict[str, Any]) -> None:
    """إذا سبقنا مُنفِّذ آخر، يُرفَع رفض صريح بدل ادّعاء نجاح الانتقال."""

    class LosingRepository(ExecutiveTaskRepository):
        def compare_and_set(self, task_id, expected, target, **fields):  # type: ignore[no-untyped-def]
            super().compare_and_set(task_id, expected, target, **fields)
            return False

    core = ExecutiveCore(repository=LosingRepository())
    task = ExecutiveTaskRepository().create("task-race-1", "analysis", "تسابق مُنفِّذين")
    with pytest.raises(ExecutionRefusedError):
        core.advance(task["id"])


def test_list_by_state_reads_from_database(core: ExecutiveCore) -> None:
    repo = ExecutiveTaskRepository()
    repo.create("task-list-1", "analysis", "مهمّة أولى")
    repo.create("task-list-2", "analysis", "مهمّة ثانية")
    rows = repo.list_by_state(TaskState.CREATED)
    assert {row["id"] for row in rows} == {"task-list-1", "task-list-2"}


def test_dispatcher_ignores_steps_without_tool() -> None:
    """خطوة بلا أداة لا تُحسَب متطلَّبًا — ولا تُسقط الاختيار."""
    register_agent("agent-plain", "وكيل عام", "worker", allowed_tools=["generation"])
    assignment = CapabilityDispatcher().select(
        [{"number": 1, "description": "بلا أداة"}, {"number": 2, "tool": "generation"}]
    )
    assert assignment.required_tools == ("generation",)
    assert assignment.agent_id == "agent-plain"


def test_get_authorizer_returns_real_gateway_backed_authorizer() -> None:
    """المُصرِّح الافتراضي حقيقي: يقرأ حال التاج من النواة السيادية نفسها."""
    from amos_federation.services.executive_core import get_authorizer

    authorizer = get_authorizer()
    assert authorizer.crown_status()
    assert authorizer.supreme_authority()
