"""اختبارات R3 — بيئة تشغيل الوكلاء داخل مسار التنفيذ القانوني

الهدف: إثبات أن الوكيل الحقيقي يُستدعى عبر النواة، وأن القدرة تُتحقَّق fail-closed
النطاق: executive_core (agent_runtime_gateway, dispatcher, engine) + agent_runtime
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-16

ما تُثبته هذه الحزمة، بندًا ببند من معيار R3:

1. **C — توزيع فعلي**: التنفيذ يمرّ بحدّ واحد إلى `WorkerAgent` القائم، ونتيجته
   تُحفَظ في المهمّة، ولا يُنشأ وكيل ولا بيئة تشغيل ثانية.
2. **C/E — القدرة لم تكن تُفحَص**: قبل R3 كان التعيين يُلفَّق من أدوات الخطة نفسها،
   فيصير الفحص صحيحًا بحكم البناء. الاختبار يقيس أن الأدوات الممنوحة تأتي من
   سجل الوكلاء لا من الخطة.
3. **E — fail-closed**: أداة تطلبها الخطة ولا يملكها الوكيل ⇒ لا تنفيذ، والمهمّة
   تسقط بسبب مُسمّى. وأداة غير موجودة في بيئة التشغيل تسقط كذلك.
4. **E — حالة الوكيل**: وكيل خرج من حالات التشغيل بعد التوزيع لا ينفّذ.
5. **F — سياق التنفيذ**: `task_id` و`agent_id` و`execution_id` و`correlation_id`
   وسياق الإذن حاضرة، والسياق ليس بديلًا عن الحفظ.
6. **D — دورة حياة الوكيل**: مراحل مُعلَنة تُنشَر على الناقل الدائم بموضوع منفصل،
   ولا تحرّك حالة المهمّة.
7. **G — النسب**: النتيجة تُسند لمهمّة ووكيل وتنفيذ وأدوات استُدعيت فعلًا، وما لا
   يُعرف يُقال `UNKNOWN` ولا يُخترع.
8. **G — الصدق المحسوب**: `WorkerAgent` يُرجع `completed` دائمًا؛ الحدّ يحسب الحالة
   من الخطوات فلا يُعلَن نجاح على عمل لم يقع.
9. **H — حدّ المحاكاة**: صدق بيئة التشغيل وصدق الأداة حقلان منفصلان مُسجَّلان.
10. **I — حرس التجاوز**: الحدّ لا ينقل حالة مهمّة ولا يكتب في `tasks`، والمحرّك لا
    يعود يُلفّق تعيينًا.
"""

from __future__ import annotations

import io
import json
import tokenize
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from amos_federation.common.database import get_session_factory, init_db
from amos_federation.services.executive_core.agent_runtime_gateway import (
    AGENT_LIFECYCLE_SUBJECT,
    RUNTIME_FIDELITY,
    TOOL_EXECUTION_FIDELITY,
    UNKNOWN,
    AgentLifecycle,
    AgentRuntimeGateway,
    CapabilityDeniedError,
    RuntimeDispatchError,
    _honest_status,
    reset_agent_runtime_gateway,
)
from amos_federation.services.executive_core.dispatcher import (
    WILDCARD,
    AgentAssignment,
    CapabilityDispatcher,
    NoEligibleAgentError,
    register_agent,
)
from amos_federation.services.executive_core.engine import (
    ExecutiveCore,
    get_executive_core,
    reset_executive_core,
)
from amos_federation.services.executive_core.fidelity import ExecutionFidelity
from amos_federation.services.executive_core.repository import ExecutiveTaskRepository
from amos_federation.services.executive_core.states import TaskState
from tests.conftest import purge_agents, purge_tasks


def analysis_tools() -> list[str]:
    """أدوات خطة `analysis` مقروءة من المنسّق القائم لا مكتوبة هنا.

    كتابتها قائمة ثابتة تجعل الاختبار يقيس نصًّا كتبناه بأنفسنا؛ قراءتها من
    `build_plan` تجعله يقيس الخطة التي تُنتَج فعلًا.
    """
    from amos_federation.services.orchestrator.main import PlanRequest, build_plan

    plan = build_plan(PlanRequest(type="analysis", description="قياس الأدوات", preview=True))
    return [str(step["tool"]) for step in plan]


@pytest.fixture(autouse=True)
def _fresh_state() -> None:
    """قاعدة نظيفة — التوزيع والتنفيذ يقرأان سجلًّا حقيقيًّا لا افتراضًا."""
    init_db()
    session = get_session_factory()()
    try:
        purge_tasks(session)
        purge_agents(session)
        session.commit()
    finally:
        session.close()
    reset_executive_core()
    reset_agent_runtime_gateway()


def _set_agent_status(agent_id: str, status: str) -> None:
    session = get_session_factory()()
    try:
        session.execute(
            text("UPDATE agents SET status = :status WHERE id = :id"),
            {"status": status, "id": agent_id},
        )
        session.commit()
    finally:
        session.close()


def _run(description: str, task_type: str = "analysis") -> dict[str, Any]:
    return get_executive_core().submit_and_run(task_type, description)


# ── R3-C: توزيع فعلي إلى بيئة التشغيل القائمة ────────────────────────────
def test_execution_runs_the_real_worker_agent_through_one_gateway() -> None:
    """التنفيذ يستدعي `WorkerAgent` القائم عبر حدّ واحد، ونتيجته تُحفَظ.

    القياس لا يثق بتوثيق: يُحقن حدّ يلفّ الحدّ الحقيقي ويعدّ استدعاءاته، ويُتحقَّق
    أن الوكيل المبنيّ من صنف بيئة التشغيل نفسه — لا وكيل بديل أُنشئ في النواة.
    """
    register_agent("r3-worker", "عامل R3", "worker", allowed_tools=[WILDCARD], status="active")
    seen: list[str] = []

    class CountingGateway(AgentRuntimeGateway):
        def _agent_for(self, context: Any) -> Any:
            agent = super()._agent_for(context)
            seen.append(type(agent).__module__ + "." + type(agent).__name__)
            return agent

    core = ExecutiveCore(runtime=CountingGateway())
    outcome = core.submit_and_run("analysis", "تنفيذ عبر بيئة التشغيل الحقيقية")

    assert outcome["final_state"] == TaskState.COMPLETED.value, outcome
    assert seen == ["amos_federation.services.agent_runtime.worker.WorkerAgent"]
    result = outcome["task"]["result"]
    assert result["agent_id"] == "r3-worker"
    assert result["tools_invoked"] == analysis_tools()


# ── R3-C/E: القدرة تأتي من السجل لا من الخطة ─────────────────────────────
def test_granted_capabilities_come_from_the_registry_not_from_the_plan() -> None:
    """الأدوات الممنوحة هي أدوات الوكيل المُسجَّلة، لا أدوات الخطة.

    قبل R3 كان التنفيذ يبني التعيين هكذا: `allowed_tools = أدوات الخطة`، فيُمنَح
    الوكيل بالضبط ما تطلبه الخطة ويصير فحص القدرة تحصيل حاصل. هنا يُسجَّل وكيل
    يملك أدوات الخطة **وأكثر**، فلو كانت المنحة مشتقّة من الخطة لتساوت القائمتان.
    """
    register_agent(
        "r3-wide",
        "عامل واسع",
        "specialist",
        allowed_tools=[*analysis_tools(), "sql_query", "generation"],
        status="active",
    )
    result = _run("قدرة من السجل")["task"]["result"]

    assert set(result["capabilities_granted"]) == {*analysis_tools(), "sql_query", "generation"}
    assert set(result["capabilities_granted"]) != set(analysis_tools())
    assert result["agent_role"] == "specialist"


def test_capability_gap_fails_closed_before_any_step_runs() -> None:
    """أداة مطلوبة غير ممنوحة ⇒ لا تنفيذ جزئي ولا بديل صامت.

    الوكيل يملك أداتين من ثلاث. لو كان الحدّ يتسامح لكان نفّذ الخطوتين وأعلن
    نتيجة جزئية تبدو عملًا. المطلوب سقوط صريح قبل أي خطوة.
    """
    register_agent(
        "r3-narrow",
        "عامل ناقص",
        "worker",
        allowed_tools=["research_apis", "data_analysis"],
        status="active",
    )
    dispatcher = CapabilityDispatcher()
    tools = analysis_tools()
    plan = [{"number": index, "tool": tool} for index, tool in enumerate(tools, start=1)]
    assignment = dispatcher.assignment_for("r3-narrow", plan)

    with pytest.raises(CapabilityDeniedError) as excinfo:
        AgentRuntimeGateway().dispatch({"id": "task-x", "plan": plan}, assignment)
    assert "capability_not_granted_to_agent" in str(excinfo.value)
    assert "critic_review" in str(excinfo.value)


def test_tool_absent_from_runtime_inventory_fails_closed() -> None:
    """أداة لا وجود لها في بيئة التشغيل تسقط، ولو منحها السجل صراحةً.

    منح السجل لا يخلق أداة. الوكيل هنا ممنوح `quantum_oracle` و`*` معًا، وبيئة
    التشغيل لا تعرفها — فالنتيجة سقوط لا تنفيذ يتظاهر بأداة غير موجودة.
    """
    assignment = AgentAssignment(
        agent_id="r3-ghost",
        agent_role="worker",
        permissions=(WILDCARD,),
        allowed_tools=(WILDCARD, "quantum_oracle"),
        required_tools=("quantum_oracle",),
    )
    with pytest.raises(CapabilityDeniedError) as excinfo:
        AgentRuntimeGateway().verify_capabilities(assignment)
    assert "tool_not_available_in_runtime" in str(excinfo.value)
    assert "quantum_oracle" not in AgentRuntimeGateway().available_tools()


def test_agent_that_left_employable_status_cannot_execute() -> None:
    """وكيل عُزل أو تقاعد بعد التوزيع لا ينفّذ — السجل يُقرأ لحظة التنفيذ.

    قبل R3 كان التنفيذ لا يقرأ جدول `agents` إطلاقًا، فوكيل معزول بعد التوزيع
    كان ينفّذ كأن شيئًا لم يكن.
    """
    register_agent("r3-isolated", "عامل معزول", "worker", allowed_tools=[WILDCARD], status="active")
    core = get_executive_core()
    task_id = core.submit("analysis", "عزل بعد التوزيع")["id"]
    core.advance_to(task_id, TaskState.EXECUTING)
    _set_agent_status("r3-isolated", "isolated")

    outcome = core.advance(task_id)
    assert outcome.to_state == TaskState.FAILED.value
    assert ExecutiveTaskRepository().require(task_id)["result"]["error"] == "agent_not_employable"

    with pytest.raises(NoEligibleAgentError):
        CapabilityDispatcher().assignment_for("r3-isolated", [{"tool": "generation"}])


# ── R3-F: سياق التنفيذ ───────────────────────────────────────────────────
def test_execution_context_carries_identity_and_authorization() -> None:
    """السياق يحمل المهمّة والوكيل والتنفيذ والتتبُّع والإذن — بلا أسرار."""
    register_agent("r3-ctx", "عامل سياق", "worker", allowed_tools=[WILDCARD], status="active")
    plan = [{"number": 1, "tool": "generation"}]
    assignment = CapabilityDispatcher().assignment_for("r3-ctx", plan)
    context = AgentRuntimeGateway().build_context(
        {"id": "task-ctx", "plan": plan, "tenant_id": "default"},
        assignment,
        authorization={"authorized_action": "task.authorize.analysis"},
    )

    payload = context.as_dict()
    assert payload["task_id"] == "task-ctx"
    assert payload["agent_id"] == "r3-ctx"
    assert payload["execution_id"].startswith("exec-")
    assert payload["correlation_id"] == "task-ctx"
    assert payload["authorization"]["authorized_action"] == "task.authorize.analysis"
    assert "token" not in repr(payload).lower()
    # السياق أثر لا مخزن: مصدر الحقيقة لحالة المهمّة يبقى المستودع.
    assert "status" not in payload


# ── R3-D: دورة حياة الوكيل، منفصلة عن حالة المهمّة ───────────────────────
def test_agent_lifecycle_is_published_and_does_not_move_task_state() -> None:
    """مراحل الوكيل تُنشَر بموضوع منفصل وتُعلن أنها بلا أثر على الحالة."""
    register_agent("r3-life", "عامل حياة", "worker", allowed_tools=[WILDCARD], status="active")
    outcome = _run("دورة حياة الوكيل")
    task_id = outcome["task"]["id"]

    session = get_session_factory()()
    try:
        rows = session.execute(
            text(
                "SELECT data FROM durable_events "
                "WHERE subject = :subject AND correlation_id = :cid ORDER BY id"
            ),
            {"subject": AGENT_LIFECYCLE_SUBJECT, "cid": task_id},
        ).fetchall()
    finally:
        session.close()

    assert rows, "لا حدث دورة حياة على الناقل الدائم"
    payloads = [row[0] if isinstance(row[0], dict) else json.loads(row[0]) for row in rows]
    phases = [payload["phase"] for payload in payloads]
    assert phases[0] == AgentLifecycle.RESOLVED.value
    assert phases[-1] == AgentLifecycle.IDLE.value
    assert AgentLifecycle.EXECUTING.value in phases
    # كل مرحلة تُعلن صراحةً أنها بلا أثر على حالة المهمّة.
    assert all(payload["task_state_effect"] is False for payload in payloads)
    assert {payload["execution_id"] for payload in payloads} != {None}
    assert len({payload["execution_id"] for payload in payloads}) == 1

    result = outcome["task"]["result"]
    assert result["agent_lifecycle"][0] == AgentLifecycle.RESOLVED.value
    assert result["agent_lifecycle"][-1] == AgentLifecycle.IDLE.value


# ── R3-G: نسب النتيجة ───────────────────────────────────────────────────
def test_result_provenance_is_complete_and_unknowns_are_declared() -> None:
    """النتيجة مُسندة بالكامل، وما لا يُعرف يُقال `UNKNOWN` لا يُخترع."""
    register_agent("r3-prov", "عامل نسب", "", allowed_tools=[WILDCARD], status="active")
    outcome = _run("نسب النتيجة")
    result = outcome["task"]["result"]

    assert result["task_id"] == outcome["task"]["id"]
    assert result["agent_id"] == "r3-prov"
    assert result["execution_id"].startswith("exec-")
    # الدور غائب في السجل ⇒ يُعلَن مجهولًا، ولا يُملأ بـ"worker" مُلفَّقة.
    assert result["agent_role"] == UNKNOWN
    # الأدوات المُسجَّلة هي ما استُدعي فعلًا من خطوات مكتملة — لا قائمة أماني.
    assert result["tools_invoked"] == analysis_tools()
    assert result["dispatch_assignment"]["agent_id"] == "r3-prov"
    assert result["execution_assignment"]["required_tools"] == analysis_tools()


def test_status_is_computed_from_steps_not_taken_from_the_agent() -> None:
    """`WorkerAgent` يُعلن `completed` دائمًا — الحدّ يحسب الحقيقة من الخطوات."""
    from amos_federation.services.agent_runtime import worker

    worker_code = Path(worker.__file__).read_text(encoding="utf-8")
    # الحقيقة المقيسة: الوكيل يكتب النجاح حرفيًّا في مخرَجه.
    assert '"status": "completed"' in worker_code

    assert _honest_status(()) == "empty"
    assert _honest_status(({"status": "skipped"}, {"status": "skipped"})) == "failed"
    assert _honest_status(({"status": "completed"}, {"status": "skipped"})) == "partial"
    assert _honest_status(({"status": "completed"},)) == "completed"
    # خطوة لا تُعلن حالتها لا تُحسَب نجاحًا ولا فشلًا.
    assert _honest_status(({"description": "بلا حالة"},)) == "unreported"


def test_all_steps_skipped_fails_the_task_instead_of_declaring_success() -> None:
    """تنفيذ لم تُنفَّذ فيه خطوة واحدة يُسقط المهمّة، ولا يُعلَن مكتملًا."""
    register_agent("r3-skip", "عامل متخطٍّ", "worker", allowed_tools=[WILDCARD], status="active")

    class SkippingAgent:
        async def execute(
            self, task: dict[str, Any], plan: list[dict[str, Any]]
        ) -> dict[str, Any]:
            return {
                "status": "completed",  # ادّعاء الوكيل
                "steps": [{**step, "status": "skipped"} for step in plan],
                "result_summary": "لم يُنفَّذ شيء",
            }

    core = ExecutiveCore(runtime=AgentRuntimeGateway(agent_factory=lambda context: SkippingAgent()))
    outcome = core.submit_and_run("analysis", "كل الخطوات متخطّاة")

    assert outcome["final_state"] == TaskState.FAILED.value
    assert outcome["task"]["result"]["status"] == "failed"
    assert outcome["task"]["result"]["error"] == "agent_execution_failed"
    assert outcome["task"]["result"]["tools_invoked"] == []


# ── R3-H: حدّ المحاكاة ──────────────────────────────────────────────────
def test_runtime_and_tool_fidelity_are_recorded_separately() -> None:
    """بيئة التشغيل حقيقية والأدوات محاكاة — حقلان لا حقل واحد يخلطهما."""
    register_agent("r3-fid", "عامل صدق", "worker", allowed_tools=[WILDCARD], status="active")
    result = _run("حدّ المحاكاة")["task"]["result"]

    assert ExecutionFidelity.REAL.value == RUNTIME_FIDELITY
    assert ExecutionFidelity.SIMULATION.value == TOOL_EXECUTION_FIDELITY
    assert result["runtime_fidelity"] == RUNTIME_FIDELITY
    assert result["tool_execution_fidelity"] == TOOL_EXECUTION_FIDELITY
    assert result["tool_fidelity_reason"]


# ── R3-I: حرس التجاوز الساكن ────────────────────────────────────────────
def _code_only(source: str) -> str:
    """إسقاط التعليقات والنصوص — الحرس يفحص شفرة تعمل لا نثرًا يشرح."""
    kept: list[str] = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in {tokenize.COMMENT, tokenize.STRING}:
            continue
        kept.append(token.string)
    return "\n".join(kept)


def test_gateway_never_writes_task_state_and_engine_no_longer_fabricates_assignment() -> None:
    """حرس ساكن: الحدّ لا يملك قلم الحالة، والمحرّك لا يعود يلفّق تعيينًا."""
    from amos_federation.services.executive_core import agent_runtime_gateway, engine

    gateway_code = _code_only(Path(agent_runtime_gateway.__file__).read_text(encoding="utf-8"))
    # ملاحظة: `_code_only` تفصل الرموز بأسطر، فالفحص على الأسماء لا على نمط النداء.
    for forbidden in ("compare_and_set", "TaskModel", "_guarded_transition", "TaskState"):
        assert forbidden not in gateway_code, f"الحدّ يتجاوز دورة الحياة: {forbidden}"

    engine_code = _code_only(Path(engine.__file__).read_text(encoding="utf-8"))
    # التعيين لم يعد يُبنى في المحرّك: يُقرأ من السجل عبر الموزّع.
    assert "AgentAssignment" not in engine_code
    assert "assignment_for" in engine_code
    # ولا وكيل يُبنى في المحرّك مباشرةً.
    assert "WorkerAgent" not in engine_code


def test_dispatch_does_not_raise_on_runtime_failure_silently() -> None:
    """فشل داخل بيئة التشغيل يُرفع كما هو ويُسجَّل — لا يُقلب نتيجة ناجحة."""

    class ExplodingAgent:
        async def execute(
            self, task: dict[str, Any], plan: list[dict[str, Any]]
        ) -> dict[str, Any]:
            raise RuntimeError("الأداة سقطت فعلًا")

    register_agent("r3-boom", "عامل ساقط", "worker", allowed_tools=[WILDCARD], status="active")
    gateway = AgentRuntimeGateway(agent_factory=lambda context: ExplodingAgent())
    plan = [{"number": 1, "tool": "generation"}]
    assignment = CapabilityDispatcher().assignment_for("r3-boom", plan)

    with pytest.raises(RuntimeDispatchError) as excinfo:
        gateway.dispatch({"id": "task-boom", "plan": plan, "tenant_id": "default"}, assignment)
    assert "RuntimeError" in str(excinfo.value)

    core = ExecutiveCore(runtime=gateway)
    outcome = core.submit_and_run("analysis", "سقوط داخل بيئة التشغيل")
    assert outcome["final_state"] == TaskState.FAILED.value
    assert outcome["task"]["result"]["error"] == "RuntimeError"
