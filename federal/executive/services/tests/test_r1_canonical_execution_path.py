"""اختبارات R1 — توحيد التنفيذ الخارجي عبر النواة التنفيذية

الهدف: إثبات أن الطلب الخارجي لا يُنفِّذ شيئًا في الدولة إلا عبر البوابة السيادية
النطاق: api_gateway + orchestrator + agent_runtime → executive_core
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-16

ما تُثبته هذه الحزمة، بندًا ببند من معيار R1:

1. الطلب الخارجي يصل إلى النواة: مهمّة أُنشئت من `api-gateway` تُقرأ في مستودع
   النواة بحالة من آلة الحالات.
2. الإذن السيادي مُطبَّق: كل انتقال يحمل دليل إذن بقرار ALLOW وطبقة سلطة.
3. الحفظ قانوني: صفّ واحد في `tasks` هو مصدر الحقيقة، تقرؤه البوابة والنواة معًا.
4. التوزيع عبر النواة: الوكيل المُعيَّن من سجل `agents`، ولا تنفيذ بلا وكيل مؤهَّل.
5. مسار التدقيق والأحداث سليم: سلسلة التدقيق متّصلة، وأحداث الانتقال منشورة.
6. التجاوز الممنوع يسقط: تنفيذ بحمل خامّ = 403، وتخطيط دائم بلا مهمّة = 400/404.
"""

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from amos_federation.common.auth import create_access_token
from amos_federation.common.database import get_session_factory, init_db
from amos_federation.common.durable_event_bus import get_durable_event_bus
from amos_federation.common.persistent import PersistentAuditStore
from amos_federation.services.agent_runtime.main import app as runtime_app
from amos_federation.services.api_gateway.main import app as gateway_app
from amos_federation.services.executive_core.engine import (
    EXECUTION_FIDELITY,
    TRANSITION_SUBJECT,
    reset_executive_core,
)
from amos_federation.services.executive_core.http_errors import EXECUTION_BYPASS_FORBIDDEN
from amos_federation.services.executive_core.repository import ExecutiveTaskRepository
from amos_federation.services.executive_core.states import TaskState
from amos_federation.services.orchestrator.main import app as orchestrator_app
from tests.conftest import purge_agents, purge_tasks

AUTH_HEADERS = {
    "Authorization": "Bearer "
    + create_access_token("r1-tester", ["tasks:write", "tasks:read", "tasks:execute"], "default")
}

gateway = TestClient(gateway_app)
orchestrator = TestClient(orchestrator_app)
runtime = TestClient(runtime_app)


@pytest.fixture(autouse=True)
def _fresh_state() -> None:
    """قاعدة نظيفة ووكيل عامّ مُسجَّل — التوزيع يقرأ سجلًّا حقيقيًّا لا افتراضًا."""
    init_db()
    session = get_session_factory()()
    try:
        purge_tasks(session)
        purge_agents(session)
        session.commit()
    finally:
        session.close()
    reset_executive_core()
    from amos_federation.services.executive_core.dispatcher import WILDCARD, register_agent

    register_agent("r1-worker", "عامل R1", "worker", allowed_tools=[WILDCARD])


def _accept_task(task_type: str = "analysis", description: str = "مهمّة R1") -> str:
    response = gateway.post(
        "/v1/tasks",
        headers=AUTH_HEADERS,
        json={"type": task_type, "description": description, "domain": "federal"},
    )
    assert response.status_code == 202, response.text
    return str(response.json()["task_id"])


# ── 1 + 3: الطلب الخارجي يصل إلى النواة، والحفظ قانوني ──────────────────────
def test_gateway_task_is_canonical_in_executive_repository() -> None:
    """مهمّة من البوابة تُقرأ في مستودع النواة بحالة من آلة الحالات."""
    response = gateway.post(
        "/v1/tasks",
        headers=AUTH_HEADERS,
        json={"type": "report", "description": "تقرير قانوني", "priority": "high"},
    )
    assert response.status_code == 202
    accepted = response.json()
    assert accepted["status"] == TaskState.CREATED.value

    stored = ExecutiveTaskRepository().require(accepted["task_id"])
    assert stored["description"] == "تقرير قانوني"
    assert stored["status"] == TaskState.CREATED.value
    assert stored["priority"] == "high"


def test_gateway_read_and_executive_repository_agree_on_one_row() -> None:
    """البوابة والنواة تقرآن الصفّ نفسه — لا نسختان للمهمّة."""
    task_id = _accept_task()
    gateway_view = gateway.get(f"/v1/tasks/{task_id}", headers=AUTH_HEADERS)
    assert gateway_view.status_code == 200
    core_view = ExecutiveTaskRepository().require(task_id)
    assert gateway_view.json()["status"] == core_view["status"]
    assert gateway_view.json()["description"] == core_view["description"]

    session = get_session_factory()()
    try:
        rows = session.execute(
            text("SELECT COUNT(*) FROM tasks WHERE id = :id"), {"id": task_id}
        ).scalar()
    finally:
        session.close()
    assert rows == 1


# ── 2: الإذن السيادي مُطبَّق على المسار الخارجي ──────────────────────────────
def test_every_external_transition_carries_sovereign_authorization() -> None:
    """كل انتقال ناتج عن طلب خارجي يحمل دليل إذن سيادي بقرار ALLOW."""
    task_id = _accept_task()
    planned = orchestrator.post(
        "/v1/plan",
        headers=AUTH_HEADERS,
        json={"type": "analysis", "description": "مهمّة R1", "task_id": task_id},
    )
    assert planned.status_code == 200, planned.text
    body = planned.json()
    assert body["mode"] == "canonical"
    assert body["reached_planned"] is True
    assert body["authority"], "لا دليل إذن — المسار لم يمرّ بالبوابة"
    for evidence in body["authority"]:
        assert evidence["decision"] == "ALLOW"
        assert evidence["authority_layer"]
        assert evidence["request_fingerprint"]


def test_execution_response_declares_authority_and_fidelity() -> None:
    """استجابة التنفيذ تُعلن أثر الإذن وأمانة المخرَج — لا نجاح مجرَّد."""
    task_id = _accept_task()
    executed = runtime.post("/v1/execute", headers=AUTH_HEADERS, json={"task_id": task_id})
    assert executed.status_code == 200, executed.text
    body = executed.json()
    assert body["final_state"] == TaskState.COMPLETED.value
    assert body["execution_fidelity"] == EXECUTION_FIDELITY == "SIMULATION"
    assert body["authority"] and all(item["decision"] == "ALLOW" for item in body["authority"])
    assert body["audit_trail"]


# ── 4: التوزيع يحدث عبر النواة من سجل الوكلاء ───────────────────────────────
def test_dispatch_uses_registered_agent_from_registry() -> None:
    """الوكيل المُنفِّذ هو المُسجَّل في `agents` لا اسم من قالب الخطة."""
    task_id = _accept_task()
    body = runtime.post("/v1/execute", headers=AUTH_HEADERS, json={"task_id": task_id}).json()
    assert body["agent_id"] == "r1-worker"
    assert ExecutiveTaskRepository().require(task_id)["assigned_agent"] == "r1-worker"


def test_execution_fails_explicitly_when_no_eligible_agent() -> None:
    """بلا وكيل مؤهَّل: المهمّة تسقط صريحًا ولا تُنفَّذ بوكيل مُختَرع."""
    session = get_session_factory()()
    try:
        purge_agents(session)
        session.commit()
    finally:
        session.close()
    task_id = _accept_task()
    body = runtime.post("/v1/execute", headers=AUTH_HEADERS, json={"task_id": task_id}).json()
    assert body["final_state"] == TaskState.FAILED.value
    assert ExecutiveTaskRepository().require(task_id)["result"]["error"] == "no_eligible_agent"


def test_runtime_available_agents_reads_registry_not_hardcoded_list() -> None:
    """قائمة الوكلاء المتاحين تأتي من السجل — تتغيّر بتغيّره."""
    before = runtime.get("/v1/agents/available", headers=AUTH_HEADERS).json()
    assert before == ["r1-worker"]
    from amos_federation.services.executive_core.dispatcher import register_agent

    register_agent("r1-second", "عامل ثانٍ", "worker", allowed_tools=["generation"])
    after = runtime.get("/v1/agents/available", headers=AUTH_HEADERS).json()
    assert set(after) == {"r1-worker", "r1-second"}


# ── 5: مسار التدقيق والأحداث سليم من الطرف الخارجي ─────────────────────────
def _recomputed_hash(entry: dict[str, Any]) -> str:
    """إعادة حساب hash القيد بنفس صيغة `PersistentAuditStore.append`."""
    details = json.dumps(entry["details"] or {}, sort_keys=True, default=str)
    payload = f"{entry['prev_hash']}:{entry['action']}:{entry['actor']}:{details}"
    return hashlib.sha256(payload.encode()).hexdigest()


def test_external_path_leaves_intact_audit_chain_and_durable_events() -> None:
    """المسار الخارجي الكامل يترك قيود تدقيق مُهشَّرة سليمة وأحداثًا دائمة منشورة.

    يُتحقَّق من قيود **هذه المهمّة** بإعادة حساب hash كل قيد من محتواه، لا من
    صلاحية السلسلة العامّة: حزمة أخرى في المستودع تُتلف السجل بقصد لتُثبت كشف
    التلاعب، فربط نتيجة R1 بالسلسلة العامّة يجعلها تعتمد على ترتيب التشغيل.
    """
    task_id = _accept_task()
    runtime.post("/v1/execute", headers=AUTH_HEADERS, json={"task_id": task_id})

    entries = [
        entry
        for entry in PersistentAuditStore().list_all(limit=300)
        if entry["details"].get("task_id") == task_id
    ]
    assert len(entries) >= 5, "المسار الخارجي لم يقيّد انتقالاته في التدقيق"
    for entry in entries:
        assert entry["hash"] == _recomputed_hash(entry), f"قيد متلاعب به: {entry['audit_id']}"
        assert entry["prev_hash"] and entry["prev_hash"] != entry["hash"]
    events = get_durable_event_bus().get_events(subject=TRANSITION_SUBJECT, limit=200)
    task_events = [event for event in events if event["data"]["task_id"] == task_id]
    assert len(task_events) >= 5
    assert {event["data"]["to_state"] for event in task_events} >= {
        TaskState.AUTHORIZED.value,
        TaskState.PLANNED.value,
        TaskState.DISPATCHED.value,
        TaskState.EXECUTING.value,
        TaskState.COMPLETED.value,
    }


# ── 6: التجاوز الممنوع يسقط ─────────────────────────────────────────────────
def test_raw_payload_execution_is_forbidden() -> None:
    """تنفيذ مهمّة وخطة خامّتين ممنوع — هذا هو تجاوز ما قبل R1 بعينه."""
    response = runtime.post(
        "/v1/execute",
        headers=AUTH_HEADERS,
        json={
            "task": {"task_id": "task-bypass", "type": "analysis", "description": "تجاوز"},
            "plan": [{"number": 1, "description": "خطوة", "tool": "generation"}],
        },
    )
    assert response.status_code == 403
    assert response.json()["detail"] == EXECUTION_BYPASS_FORBIDDEN


def test_execution_of_unknown_task_is_not_invented() -> None:
    """تنفيذ معرّف لا وجود له في القاعدة = 404، لا تنفيذ بمهمّة مُختَرعة."""
    response = runtime.post(
        "/v1/execute", headers=AUTH_HEADERS, json={"task_id": "task-does-not-exist"}
    )
    assert response.status_code == 404


def test_persistent_planning_requires_canonical_task() -> None:
    """التخطيط الدائم بلا مهمّة قانونية مرفوض، والاستطلاع مسموح ومُعلَن."""
    rejected = orchestrator.post(
        "/v1/plan", headers=AUTH_HEADERS, json={"type": "analysis", "description": "بلا مهمّة"}
    )
    assert rejected.status_code == 400

    preview = orchestrator.post(
        "/v1/plan",
        headers=AUTH_HEADERS,
        json={"type": "analysis", "description": "استطلاع", "preview": True},
    )
    assert preview.status_code == 200
    body = preview.json()
    assert body["mode"] == "preview"
    assert body["persisted"] is False
    assert body["authority"] is None
    assert body["plan"]

    session = get_session_factory()()
    try:
        count = session.execute(text("SELECT COUNT(*) FROM tasks")).scalar()
    finally:
        session.close()
    assert count == 0, "الخطة الاستطلاعية كتبت في القاعدة — هذا تجاوز"


def test_planning_unknown_task_is_rejected() -> None:
    """تخطيط دائم لمعرّف غير موجود = 404 لا إنشاء ضمني."""
    response = orchestrator.post(
        "/v1/plan",
        headers=AUTH_HEADERS,
        json={"type": "analysis", "description": "غير موجودة", "task_id": "task-ghost"},
    )
    assert response.status_code == 404


def test_state_mutating_endpoints_require_authentication() -> None:
    """الواجهات التي تغيّر حالة الدولة لا تعمل بلا مصادقة."""
    assert (
        orchestrator.post("/v1/plan", json={"type": "analysis", "description": "س"}).status_code
        == 401
    )
    assert runtime.post("/v1/execute", json={"task_id": "task-x"}).status_code == 401
    assert (
        gateway.post("/v1/tasks", json={"type": "analysis", "description": "س"}).status_code == 401
    )


def test_full_external_chain_gateway_orchestrator_runtime() -> None:
    """السلسلة الخارجية الكاملة: بوابة → منسّق → وقت تشغيل، بصفّ واحد وحالة واحدة."""
    task_id = _accept_task("data", "سلسلة كاملة")
    planned = orchestrator.post(
        "/v1/plan",
        headers=AUTH_HEADERS,
        json={"type": "data", "description": "سلسلة كاملة", "task_id": task_id},
    ).json()
    assert planned["final_state"] == TaskState.PLANNED.value

    executed = runtime.post("/v1/execute", headers=AUTH_HEADERS, json={"task_id": task_id}).json()
    assert executed["final_state"] == TaskState.COMPLETED.value

    final: dict[str, Any] = ExecutiveTaskRepository().require(task_id)
    assert final["status"] == TaskState.COMPLETED.value
    assert final["result"]["execution_fidelity"] == "SIMULATION"
    assert final["plan"] == planned["plan"]


# ── حرس ساكن: لا تجاوز جديد يدخل بعد R1 ──────────────────────────────────────
EDGE_SERVICES = ("api_gateway", "orchestrator", "agent_runtime")

#: بدائيات التنفيذ والكتابة التي تخصّ النواة وحدها. وجودها في خدمة حافّة يعني
#: مسار تنفيذ ثانيًا لا يمرّ بالبوابة السيادية — وهو ما أُلغي في R1.
CORE_ONLY_PRIMITIVES = (
    ".execute(",
    "compare_and_set",
    "PersistentTaskStore",
    "TaskModel(",
)


def _service_sources() -> dict[str, str]:
    import amos_federation.services as services_package

    root = Path(services_package.__file__).parent
    return {
        path.parent.name: path.read_text(encoding="utf-8")
        for path in sorted(root.glob("*/main.py"))
        if path.parent.name != "executive_core"
    }


def test_edge_services_delegate_to_executive_core() -> None:
    """الخدمات الحافّة تستورد النواة فعلًا — لا مجرّد تشابه في الأسماء."""
    sources = _service_sources()
    for service in EDGE_SERVICES:
        assert "executive_core" in sources[service], f"{service} لا يستورد النواة التنفيذية"


def test_edge_services_hold_no_execution_primitives() -> None:
    """لا خدمة حافّة تنفّذ أو تكتب حالة مهمّة بنفسها — وإلا فهو تجاوز جديد."""
    sources = _service_sources()
    offenders = {
        service: [token for token in CORE_ONLY_PRIMITIVES if token in sources[service]]
        for service in EDGE_SERVICES
    }
    assert not any(offenders.values()), f"بدائيات تنفيذ في خدمة حافّة: {offenders}"


def test_no_service_writes_task_state_outside_the_core() -> None:
    """الانتقال الذرّي وسجل المهام الدائم يبقيان حصرًا داخل النواة التنفيذية."""
    violations = {
        service: token
        for service, source in _service_sources().items()
        for token in ("compare_and_set", "PersistentTaskStore")
        if token in source
    }
    assert violations == {}, f"كتابة حالة مهمّة خارج النواة: {violations}"
