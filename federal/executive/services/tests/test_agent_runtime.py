"""
اختبارات وقت تشغيل الوكلاء
الهدف: التحقق من أن التنفيذ يمرّ بالنواة التنفيذية، ومن سلوك الوكيل نفسه
النطاق: services/agent-runtime
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-15
تاريخ آخر تعديل: 2026-08-16 (R1)

ما تغيّر في R1 ولماذا — لا يُخفى:

كانت ثلاثة اختبارات هنا تُثبت سلوكًا صار ممنوعًا: تنفيذ مهمّة وخطة **خامّتين**
عبر `POST /v1/execute` بلا مهمّة قانونية في القاعدة ولا إذن سيادي. ذلك السلوك هو
تجاوز R1 بعينه، فلم يُحفَظ الاختبار على حاله ولم يُحذف تحقُّقه:

- `test_execute_task_with_plan` → صار `test_execute_canonical_task_via_core`:
  نفس التحقق (خطوات مكتملة، معرّف المهمّة صحيح) على المسار القانوني.
- `test_execute_unknown_tool_is_skipped` → نُقل إلى مستوى `WorkerAgent` مباشرة،
  لأن تخطّي أداة غير معروفة سلوك الوكيل والصندوق لا سلوك الواجهة. التحقق باقٍ.
- `test_execute_rejects_empty_plan` → صار `test_execute_rejects_raw_payload`:
  الحمل الخامّ يُرفَض بـ403 قبل أن يُنظَر في خطته أصلًا.
"""

import pytest
from fastapi.testclient import TestClient

from amos_federation.common.auth import create_access_token
from amos_federation.common.database import get_session_factory, init_db
from amos_federation.services.agent_runtime.main import app
from amos_federation.services.agent_runtime.worker import WorkerAgent
from amos_federation.services.executive_core.dispatcher import WILDCARD, register_agent
from amos_federation.services.executive_core.engine import get_executive_core, reset_executive_core
from amos_federation.services.executive_core.http_errors import EXECUTION_BYPASS_FORBIDDEN
from tests.conftest import purge_agents, purge_tasks

client = TestClient(app)
AUTH_HEADERS = {"Authorization": f"Bearer {create_access_token('tester', ['tasks:execute'])}"}


@pytest.fixture(autouse=True)
def _clean_state() -> None:
    """قاعدة نظيفة قبل كل اختبار — عدد الوكلاء المُتوقَّع لا يعتمد على ترتيب التشغيل."""
    init_db()
    session = get_session_factory()()
    try:
        purge_tasks(session)
        purge_agents(session)
        session.commit()
    finally:
        session.close()
    reset_executive_core()


def test_execute_canonical_task_via_core() -> None:
    """تنفيذ مهمّة مقبولة في النواة ينتج نتائج لكل خطوة، ويُعلن أنه محاكاة."""
    register_agent("worker-generic-001", "عامل عامّ", "worker", allowed_tools=[WILDCARD])
    task = get_executive_core().submit("analysis", "حلل أداء المبيعات", domain="finance")

    response = client.post("/v1/execute", headers=AUTH_HEADERS, json={"task_id": task["id"]})

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["final_state"] == "completed"
    assert data["task_id"] == task["id"]
    assert data["agent_id"] == "worker-generic-001"
    assert len(data["steps"]) == 3
    assert all(step["status"] == "completed" for step in data["steps"])
    assert "اكتملت" in data["result_summary"]
    assert data["execution_fidelity"] == "SIMULATION"


@pytest.mark.asyncio
async def test_worker_skips_unknown_tool() -> None:
    """خطوة بأداة غير معروفة تُتخطى ولا تفشل المهمة — سلوك الوكيل نفسه."""
    agent = WorkerAgent(agent_id="worker-test", permissions=[WILDCARD])
    result = await agent.execute(
        {"task_id": "task-test-002", "description": "اختبار"},
        [
            {"number": 1, "description": "خطوة صحيحة", "tool": "generation", "agent": "worker"},
            {
                "number": 2,
                "description": "أداة غير معروفة",
                "tool": "nonexistent_tool",
                "agent": "worker",
            },
        ],
    )
    assert result["steps"][0]["status"] == "completed"
    assert result["steps"][1]["status"] == "skipped"


def test_execute_rejects_raw_payload() -> None:
    """الحمل الخامّ (مهمّة/خطة) يُرفَض بـ403 — لا تنفيذ خارج النواة."""
    response = client.post(
        "/v1/execute",
        headers=AUTH_HEADERS,
        json={"task": {"description": "اختبار"}, "plan": []},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == EXECUTION_BYPASS_FORBIDDEN


def test_execute_rejects_missing_auth() -> None:
    """التنفيذ يتطلب مصادقة."""
    response = client.post("/v1/execute", json={"task_id": "task-x"})
    assert response.status_code == 401


def test_available_agents() -> None:
    """عرض الوكلاء المتاحين من سجل الوكلاء — لا قائمة ثابتة في الشِفرة."""
    for index in range(3):
        register_agent(f"worker-{index}", f"عامل {index}", "worker", allowed_tools=[WILDCARD])
    response = client.get("/v1/agents/available", headers=AUTH_HEADERS)
    assert response.status_code == 200
    assert len(response.json()) >= 3


def test_available_tools() -> None:
    """عرض الأدوات المتاحة في الصندوق الرمل."""
    response = client.get("/v1/tools/available", headers=AUTH_HEADERS)
    assert response.status_code == 200
    assert "sql_query" in response.json()
    assert "generation" in response.json()
