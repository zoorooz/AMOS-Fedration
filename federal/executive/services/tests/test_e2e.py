"""
اختبارات شاملة من البداية للنهاية (E2E)
الهدف: التحقق من دورة: طلب خارجي → قبول → تخطيط → تنفيذ → نتيجة، عبر النواة
النطاق: api-gateway → orchestrator → agent-runtime → executive-core
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-15
تاريخ آخر تعديل: 2026-08-16 (R1)

ما تغيّر في R1 ولماذا:

كانت هذه الحزمة تُثبت دورة «تخطيط ثم تنفيذ» لا تلمس القاعدة ولا البوابة السيادية:
خطة تُبنى وتُعاد، ثم تُرسَل مع مهمّة مُلفَّقة إلى `/v1/execute` فتُنفَّذ. أي أنها
كانت تُثبت صحّة **التجاوز**. بعد R1 صارت تُثبت الدورة القانونية نفسها: المهمّة
تُقبَل في البوابة، وتُخطَّط بمعرّفها، وتُنفَّذ بمعرّفها، والحالة النهائية تُقرأ من
الصفّ الواحد في القاعدة.

الحالة الوسطى المتوقَّعة بعد القبول صارت `created` — حالة من آلة الحالات — بدل
`pending` التي كانت كلمة خارج الآلة لا يعرفها أحد.
"""

import pytest
from fastapi.testclient import TestClient

from amos_federation.common.auth import create_access_token
from amos_federation.common.database import get_session_factory, init_db
from amos_federation.services.agent_runtime.main import app as agent_app
from amos_federation.services.api_gateway.main import app as gateway_app
from amos_federation.services.executive_core.dispatcher import WILDCARD, register_agent
from amos_federation.services.executive_core.engine import reset_executive_core
from amos_federation.services.executive_core.repository import ExecutiveTaskRepository
from amos_federation.services.orchestrator.main import app as orchestrator_app
from tests.conftest import purge_agents, purge_tasks

orchestrator_client = TestClient(orchestrator_app)
agent_client = TestClient(agent_app)
gateway_client = TestClient(gateway_app)

AUTH_HEADERS = {
    "Authorization": f"Bearer {create_access_token('e2e-tester', ['tasks:write', 'tasks:read', 'tasks:execute'])}"
}


@pytest.fixture(autouse=True)
def _clean_state() -> None:
    """قاعدة نظيفة ووكيل عامّ مُسجَّل قبل كل اختبار."""
    init_db()
    session = get_session_factory()()
    try:
        purge_tasks(session)
        purge_agents(session)
        session.commit()
    finally:
        session.close()
    reset_executive_core()
    register_agent("e2e-worker", "عامل E2E", "worker", allowed_tools=[WILDCARD])


def _accept(task_type: str, description: str, **extra: object) -> str:
    response = gateway_client.post(
        "/v1/tasks",
        headers=AUTH_HEADERS,
        json={"type": task_type, "description": description, **extra},
    )
    assert response.status_code == 202, response.text
    return str(response.json()["task_id"])


def test_e2e_accept_then_plan_then_execute() -> None:
    """دورة كاملة على المسار القانوني: قبول ثم تخطيط ثم تنفيذ."""
    description = "حلل أداء المبيعات في الربع الثاني"
    task_id = _accept("analysis", description, domain="finance")

    plan_response = orchestrator_client.post(
        "/v1/plan",
        headers=AUTH_HEADERS,
        json={"type": "analysis", "description": description, "task_id": task_id},
    )
    assert plan_response.status_code == 200
    plan_data = plan_response.json()
    assert len(plan_data["plan"]) >= 2
    assert plan_data["final_state"] == "planned"

    execute_response = agent_client.post(
        "/v1/execute", headers=AUTH_HEADERS, json={"task_id": task_id}
    )
    assert execute_response.status_code == 200
    exec_data = execute_response.json()
    assert exec_data["status"] == "completed"
    assert exec_data["task_id"] == task_id
    assert all(step["status"] == "completed" for step in exec_data["steps"])


def test_e2e_task_creation_then_plan() -> None:
    """دورة: قبول مهمة في البوابة بحالة قانونية ثم تخطيطها."""
    description = "تقرير سنوي عن الأداء"
    task_id = _accept("report", description, priority="high")

    get_response = gateway_client.get(f"/v1/tasks/{task_id}", headers=AUTH_HEADERS)
    assert get_response.status_code == 200
    assert get_response.json()["status"] == "created"

    plan_response = orchestrator_client.post(
        "/v1/plan",
        headers=AUTH_HEADERS,
        json={"type": "report", "description": description, "task_id": task_id},
    )
    assert plan_response.status_code == 200
    assert len(plan_response.json()["plan"]) >= 2
    assert ExecutiveTaskRepository().require(task_id)["plan"]


def test_e2e_all_task_types_complete() -> None:
    """كل أنواع المهام تكتمل دورتها من القبول للتنفيذ عبر النواة."""
    for task_type in ["analysis", "report", "data", "generic"]:
        task_id = _accept(task_type, f"مهمة {task_type}")
        exec_resp = agent_client.post(
            "/v1/execute", headers=AUTH_HEADERS, json={"task_id": task_id}
        )
        assert exec_resp.status_code == 200
        assert exec_resp.json()["final_state"] == "completed"
