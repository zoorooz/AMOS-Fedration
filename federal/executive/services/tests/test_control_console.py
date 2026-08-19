"""
اختبارات منصة التحكم البشري (Phase 7)
الهدف: التحقق أن كل رقم في الواجهة من خدمات حقيقية لا Mock
النطاق: services/control_console
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-15
"""

import pytest
from fastapi.testclient import TestClient

from amos_federation.common.auth import create_access_token
from amos_federation.services.agent_runtime.population import get_population_registry
from amos_federation.services.control_console.main import app

AUTH_HEADERS = {
    "Authorization": "Bearer "
    + create_access_token(
        "tester",
        [
            "governance:read",
            "governance:write",
        ],
    )
}
client = TestClient(app)


@pytest.fixture(autouse=True)
def seed_data():
    """بذر بيانات حقيقية قبل الاختبارات."""
    from amos_federation.services.governance.canary import reset_kill_switch

    reset_kill_switch()
    registry = get_population_registry()
    registry.seed_initial_population()
    yield
    reset_kill_switch()


# === 7.1: Dashboard shows real data ===


def test_dashboard_returns_real_agents() -> None:
    """اللوحة تعرض وكلاء حقيقيين."""
    resp = client.get("/v1/dashboard", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["agents"]["total"] >= 20
    assert "by_state" in data["agents"]


def test_dashboard_returns_real_cost() -> None:
    """اللوحة تعرض تكلفة حقيقية."""
    resp = client.get("/v1/dashboard", headers=AUTH_HEADERS)
    data = resp.json()
    assert "cost" in data
    assert "total_cost_usd" in data["cost"]
    assert "total_tokens" in data["cost"]


def test_dashboard_returns_real_audit() -> None:
    """اللوحة تعرض سجل تدقيق حقيقي."""
    resp = client.get("/v1/dashboard", headers=AUTH_HEADERS)
    data = resp.json()
    assert "audit" in data
    assert "chain_valid" in data["audit"]
    assert "total_entries" in data["audit"]


def test_dashboard_returns_real_events() -> None:
    """اللوة تعرض أحداث حقيقية."""
    resp = client.get("/v1/dashboard", headers=AUTH_HEADERS)
    data = resp.json()
    assert "events" in data
    assert data["events"]["total"] >= 0


def test_dashboard_returns_system_status() -> None:
    """اللوحة تعرض حالة Kill Switch."""
    resp = client.get("/v1/dashboard", headers=AUTH_HEADERS)
    data = resp.json()
    assert data["system_status"]["level"] == "normal"


def test_dashboard_returns_tools_count() -> None:
    """اللوحة تعرض عدد الأدوات."""
    resp = client.get("/v1/dashboard", headers=AUTH_HEADERS)
    data = resp.json()
    assert data["tools"]["total"] >= 0


# === 7.2: Agent management ===


def test_list_agents() -> None:
    """عرض قائمة الوكلاء."""
    resp = client.get("/v1/agents", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    agents = resp.json()
    assert len(agents) >= 20


def test_get_single_agent() -> None:
    """عرض وكيل واحد."""
    agents = client.get("/v1/agents", headers=AUTH_HEADERS).json()
    agent_id = agents[0]["agent_id"]
    resp = client.get(f"/v1/agents/{agent_id}", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["agent_id"] == agent_id


def test_get_nonexistent_agent() -> None:
    """وكيل غير موجود يعيد 404."""
    resp = client.get("/v1/agents/nonexistent", headers=AUTH_HEADERS)
    assert resp.status_code == 404


def test_update_agent_state_pause() -> None:
    """7.4: إيقاف وكيل من الواجهة."""
    agents = client.get("/v1/agents", headers=AUTH_HEADERS).json()
    agent_id = agents[0]["agent_id"]
    resp = client.post(
        f"/v1/agents/{agent_id}/state", headers=AUTH_HEADERS, json={"state": "paused"}
    )
    assert resp.status_code == 200
    assert resp.json()["state"] == "paused"

    # التحقق أن الحالة تغيّرت فعليًا
    agent = client.get(f"/v1/agents/{agent_id}", headers=AUTH_HEADERS).json()
    assert agent["state"] == "paused"


def test_update_agent_state_activate() -> None:
    """7.4: تفعيل وكيل من الواجهة."""
    agents = client.get("/v1/agents", headers=AUTH_HEADERS).json()
    agent_id = agents[0]["agent_id"]
    client.post(f"/v1/agents/{agent_id}/state", headers=AUTH_HEADERS, json={"state": "paused"})
    resp = client.post(
        f"/v1/agents/{agent_id}/state", headers=AUTH_HEADERS, json={"state": "active"}
    )
    assert resp.status_code == 200
    assert resp.json()["state"] == "active"


def test_update_agent_state_publishes_event() -> None:
    """تغيير حالة وكيل ينشر حدثًا."""
    from amos_federation.common.event_bus import get_event_bus

    bus = get_event_bus()
    initial = bus.count("amos_federation.agent.state_changed")
    agents = client.get("/v1/agents", headers=AUTH_HEADERS).json()
    agent_id = agents[0]["agent_id"]
    client.post(f"/v1/agents/{agent_id}/state", headers=AUTH_HEADERS, json={"state": "paused"})
    assert bus.count("amos_federation.agent.state_changed") > initial


# === 7.3: Audit log ===


def test_list_audit() -> None:
    """عرض سجل التدقيق."""
    resp = client.get("/v1/audit", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_verify_audit_chain() -> None:
    """التحقق من سلامة السلسلة."""
    resp = client.get("/v1/audit/verify", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["valid"] is True


# === 7.6: Kill Switch ===


def test_kill_switch_activate() -> None:
    """تفعيل Kill Switch من الواجهة."""
    resp = client.post(
        "/v1/kill-switch",
        headers=AUTH_HEADERS,
        json={"level": "alert", "reason": "اختبار", "activated_by": "tester"},
    )
    assert resp.status_code == 200
    assert resp.json()["level"] == "alert"


def test_kill_switch_reset() -> None:
    """إعادة ضبط Kill Switch."""
    client.post(
        "/v1/kill-switch",
        headers=AUTH_HEADERS,
        json={"level": "alert", "reason": "اختبار", "activated_by": "tester"},
    )
    resp = client.post("/v1/kill-switch/reset", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["level"] == "normal"


def test_kill_switch_writes_audit() -> None:
    """تفعيل Kill Switch يكتب في سجل التدقيق."""
    # ‎/v1/audit مُسقَّفٌ بـ limit، فطولُ صفحتِه يتشبَّعُ متى تجاوزَ السجلُّ السقفَ
    # ولا يَشهدُ بنموِّ السلسلةِ. عددُ المُدخلاتِ في ‎/v1/audit/verify غيرُ مُسقَّفٍ.
    audit_before = client.get("/v1/audit/verify", headers=AUTH_HEADERS).json()["entries"]
    client.post(
        "/v1/kill-switch",
        headers=AUTH_HEADERS,
        json={"level": "alert", "reason": "اختبار تدقيق", "activated_by": "tester"},
    )
    audit_after = client.get("/v1/audit/verify", headers=AUTH_HEADERS).json()["entries"]
    assert audit_after > audit_before


# === 7.5: Approval ===


def test_approval_sign() -> None:
    """زر الموافقة/الرفض يعمل."""
    resp = client.post(
        "/v1/approval",
        headers=AUTH_HEADERS,
        json={"decision": "approve", "signed_by": "tester", "model_id": "test-model"},
    )
    assert resp.status_code == 200
    assert resp.json()["decision"] == "approve"
    assert resp.json()["signature_pending"] is True


def test_approval_reject() -> None:
    """زر الرفض يعمل."""
    resp = client.post(
        "/v1/approval", headers=AUTH_HEADERS, json={"decision": "reject", "signed_by": "tester"}
    )
    assert resp.status_code == 200
    assert resp.json()["decision"] == "reject"


def test_approval_publishes_event() -> None:
    """الموافقة تنشر حدثًا."""
    from amos_federation.common.event_bus import get_event_bus

    bus = get_event_bus()
    initial = bus.count("amos_federation.approval.signed")
    client.post(
        "/v1/approval", headers=AUTH_HEADERS, json={"decision": "approve", "signed_by": "tester"}
    )
    assert bus.count("amos_federation.approval.signed") > initial


# === 7.7: Cost ===


def test_get_cost() -> None:
    """عرض التكلفة."""
    resp = client.get("/v1/cost", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    assert "total_cost_usd" in resp.json()
    assert "total_tokens" in resp.json()


# === 7.8: Events ===


def test_list_events() -> None:
    """عرض الأحداث."""
    resp = client.get("/v1/events", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# === 7.1: HTML UI ===


def test_ui_returns_html() -> None:
    """الواجهة تعيد HTML."""
    resp = client.get("/v1/ui")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    assert "AMOS Federation" in resp.text
    assert "Kill Switch" in resp.text
    assert "agents-table" in resp.text


def test_ui_has_real_data_bindings() -> None:
    """الواجهة مربوطة بـ APIs حقيقية."""
    resp = client.get("/v1/ui")
    html = resp.text
    # فحص أن الواجهة تستدعي endpoints حقيقية
    assert "/dashboard" in html
    assert "/agents" in html
    assert "/audit" in html
    assert "/events" in html
    assert "/kill-switch" in html
    assert "/v1" in html  # JS URL prefix


# === 7.8: No mock data — all from real services ===


def test_all_numbers_from_real_services() -> None:
    """كل رقم في اللوحة من خدمة حقيقية."""
    dashboard = client.get("/v1/dashboard", headers=AUTH_HEADERS).json()

    # مقارنة مع البيانات الحقيقية
    registry = get_population_registry()
    real_agents = registry.list_agents()
    assert dashboard["agents"]["total"] == len(real_agents)

    from amos_federation.common.event_bus import get_event_bus

    real_events = get_event_bus().count()
    assert dashboard["events"]["total"] == real_events
