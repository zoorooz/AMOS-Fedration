"""اختبارات R2 — دورة حياة واحدة، أحداث دائمة، وحدود الأنظمة المتخصّصة

الهدف: إثبات أن التنفيذ يُنتج حدثًا دائمًا فعلًا، وأن لا دورة حياة ثانية موازية
النطاق: executive_core + common/event_wiring + model_gateway/training/critic/evaluation
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-16

ما تُثبته هذه الحزمة، بندًا ببند من معيار R2:

1. **A — مسار الحدث**: تنفيذ مهمّة يُنتج صفوفًا في جدول `durable_events` تُقرأ
   بعد إسقاط كل الكائنات من الذاكرة، ويُعاد تشغيلها (`replay`). فالحدث ليس
   محاكاة في الذاكرة.
2. **A — الإسقاط لا المحاكاة**: أحداث النطاق القديمة (`agent.assigned`) تُشتقّ من
   انتقال حقيقي وتحمل الوكيل المُعيَّن نفسه من سجل الوكلاء، ولا تحمل درجة جودة
   مُخترعة.
3. **B — دورة حياة واحدة**: لا وحدة خارج النواة تكتب حالة مهمّة، ونشاط الأنظمة
   المتخصّصة لا يحرّك الحالة قيد أنملة.
4. **C — حدّ النماذج**: استدعاء منسوب لمهمّة وهمية يُردّ، والمنسوب لمهمّة قانونية
   يُقيَّد بإذن سيادي وأثر مُدقَّق بلا أثر تنفيذي.
5. **D — حدّ التدريب**: التدريب يستأذن ويُقيَّد، ومقاييسه مُعلَنة `SIMULATION`.
6. **E — حدّ التقييم والنقد**: الناقد يُقيّم نتيجة المستودع لا حمولة الطالب،
   والنسب غير المتحقّق يُوسَم `unverified` لا يُقبل بلا تمييز.
7. **F — الصدق**: مفردات واحدة، وإعلان غير REAL يلزمه سبب مُسمّى.
8. **G — الحرس الساكن**: أصناف التجاوز الستّة تسقط إن ظهرت من جديد.
"""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from amos_federation.common.auth import create_access_token
from amos_federation.common.database import get_session_factory, init_db
from amos_federation.common.durable_event_bus import get_durable_event_bus
from amos_federation.services.critic.main import app as critic_app
from amos_federation.services.evaluation.main import app as evaluation_app
from amos_federation.services.executive_core.engine import (
    EXECUTION_FIDELITY,
    TRANSITION_SUBJECT,
    get_executive_core,
    reset_executive_core,
)
from amos_federation.services.executive_core.fidelity import ExecutionFidelity, declare
from amos_federation.services.executive_core.repository import ExecutiveTaskRepository
from amos_federation.services.executive_core.states import TaskState
from amos_federation.services.executive_core.subsystem_boundary import (
    SUBSYSTEM_SUBJECT,
    ActivityKind,
    SubsystemBoundary,
    get_subsystem_boundary,
    reset_subsystem_boundary,
)
from amos_federation.services.model_gateway.main import app as model_app
from amos_federation.services.training.main import app as training_app
from tests.conftest import purge_agents, purge_tasks

MODEL_HEADERS = {"Authorization": "Bearer " + create_access_token("r2", ["models:invoke"])}
TRAINING_HEADERS = {
    "Authorization": "Bearer " + create_access_token("r2", ["training:read", "training:write"])
}
CRITIC_HEADERS = {
    "Authorization": "Bearer " + create_access_token("r2", ["critic:read", "critic:write"])
}
EVAL_HEADERS = {
    "Authorization": "Bearer " + create_access_token("r2", ["evaluation:read", "evaluation:write"])
}

model_client = TestClient(model_app)
training_client = TestClient(training_app)
critic_client = TestClient(critic_app)
evaluation_client = TestClient(evaluation_app)


@pytest.fixture(autouse=True)
def _fresh_state() -> None:
    """قاعدة نظيفة ووكيل مُسجَّل — التوزيع يقرأ سجلًّا حقيقيًّا لا افتراضًا."""
    init_db()
    session = get_session_factory()()
    try:
        purge_tasks(session)
        purge_agents(session)
        session.commit()
    finally:
        session.close()
    reset_executive_core()
    reset_subsystem_boundary()
    from amos_federation.services.executive_core.dispatcher import WILDCARD, register_agent

    register_agent("r2-worker", "عامل R2", "worker", allowed_tools=[WILDCARD])


def _completed_task() -> dict[str, Any]:
    """مهمّة نُفِّذت فعلًا عبر النواة — مصدر كل ما يُقاس بعدها."""
    outcome = get_executive_core().submit_and_run("analysis", "مهمّة R2 للتنفيذ الكامل")
    assert outcome["final_state"] == TaskState.COMPLETED.value, outcome
    return outcome


# ── R2-A: التنفيذ يُنتج حدثًا دائمًا حقيقيًّا ─────────────────────────────────
def test_execution_writes_durable_event_rows_to_the_database() -> None:
    """تنفيذ مهمّة يُنتج صفوف أحداث في القاعدة — لا محاكاة في الذاكرة.

    القياس لا يمرّ بكائن الناقل: يُستعلم جدول `durable_events` بـSQL مباشرة.
    لو كان الحدث in-memory لكان العدد صفرًا.
    """
    outcome = _completed_task()
    task_id = outcome["task"]["id"]

    session = get_session_factory()()
    try:
        rows = session.execute(
            text(
                "SELECT subject, data FROM durable_events "
                "WHERE correlation_id = :cid ORDER BY id"
            ),
            {"cid": task_id},
        ).fetchall()
    finally:
        session.close()

    transitions = [row for row in rows if row[0] == TRANSITION_SUBJECT]
    assert len(transitions) >= 4, f"انتقالات دائمة أقل من المتوقّع: {[r[0] for r in rows]}"


def test_durable_events_survive_bus_reconstruction_and_replay() -> None:
    """الأحداث تُقرأ وتُعاد بعد بناء ناقل جديد — ordering و persistence و replay."""
    task_id = _completed_task()["task"]["id"]

    from amos_federation.common import durable_event_bus as bus_module

    bus_module._bus = None  # إسقاط المفرد: القراءة التالية تأتي من القاعدة لا من الذاكرة
    fresh = get_durable_event_bus()

    events = [
        event
        for event in fresh.get_events(subject=TRANSITION_SUBJECT, limit=200)
        if event["correlation_id"] == task_id
    ]
    assert events, "لا أحداث انتقال في القاعدة بعد إعادة بناء الناقل"

    ids = [event["event_id"] for event in events]
    assert len(set(ids)) == len(ids), "معرّف حدث مكرّر يُفسد سلامة السجل"

    # replay يقرأ من أوّل السجلِّ تصاعديًّا، فحدٌّ ثابتٌ يقطعُ الأحداثَ الأحدثَ
    # متى تجاوزَ السجلُّ المشتركُ ذلك الحدَّ. الحدُّ يُقاسُ من طولِ السجلِّ نفسِه.
    stream_length = fresh.count(subject=TRANSITION_SUBJECT)
    replayed = fresh.replay("r2_replay_probe", subject=TRANSITION_SUBJECT, limit=stream_length)
    assert any(event["data"]["task_id"] == task_id for event in replayed)


def test_legacy_domain_events_are_projected_from_real_transitions() -> None:
    """`agent.assigned` تُشتقّ من انتقال حقيقي وتحمل الوكيل المُعيَّن نفسه."""
    from amos_federation.common.event_wiring import (
        init_event_consumers,
        reset_event_consumers,
    )

    reset_event_consumers()
    init_event_consumers()

    outcome = _completed_task()
    task_id = outcome["task"]["id"]
    assigned_agent = ExecutiveTaskRepository().require(task_id)["assigned_agent"]

    bus = get_durable_event_bus()
    assigned = [
        event
        for event in bus.get_events(subject="amos_federation.agent.assigned", limit=200)
        if event["data"].get("task_id") == task_id
    ]
    assert assigned, "لم يُسقَط حدث تعيين الوكيل من الانتقال القانوني"
    assert assigned[0]["data"]["agent_id"] == assigned_agent

    completed = [
        event
        for event in bus.get_events(subject="amos_federation.agent.completed", limit=200)
        if event["data"].get("task_id") == task_id
    ]
    assert completed, "لم يُسقَط حدث الإكمال من الانتقال القانوني"
    # لا درجة جودة مُخترعة: المُسقِط لا يملك حكمًا على الجودة فلا يُصدره
    assert "quality_score" not in completed[0]["data"]
    assert completed[0]["data"]["result"]["execution_fidelity"] == EXECUTION_FIDELITY


def test_event_wiring_holds_no_second_lifecycle() -> None:
    """وحدة ربط الأحداث لا تُنشئ مهمّة ولا تكتب حالة — دورة الحياة واحدة."""
    from amos_federation.common import event_wiring

    source = _code_only(Path(event_wiring.__file__).read_text(encoding="utf-8"))
    for forbidden in ("_task_store", "update_status(", "compare_and_set", "PersistentTaskStore"):
        assert forbidden not in source, f"دورة حياة ثانية في event_wiring: {forbidden}"


# ── R2-B: نشاط الأنظمة المتخصّصة لا يحرّك الحالة ──────────────────────────────
def test_subsystem_activity_never_changes_task_state() -> None:
    """نشاط نظام متخصّص يُرفَق بالمهمّة ولا يحرّك حالتها."""
    task_id = _completed_task()["task"]["id"]
    repo = ExecutiveTaskRepository()
    before = repo.state_of(task_id)

    boundary = get_subsystem_boundary()
    activity = boundary.authorized_activity(
        ActivityKind.MODEL_INVOCATION,
        "model:test",
        ExecutionFidelity.SIMULATION,
        {"tokens_used": 3},
        task_id=task_id,
    )

    assert repo.state_of(task_id) == before
    assert activity.as_dict()["execution_effect"] is False
    assert activity.task_id == task_id


def test_subsystem_activity_is_audited_and_published() -> None:
    """كل نشاط مُجاز يُقيَّد في التدقيق ويُنشَر على الناقل الدائم الموجود."""
    task_id = _completed_task()["task"]["id"]
    activity = get_subsystem_boundary().authorized_activity(
        ActivityKind.EVALUATION_RUN,
        "experience:success",
        ExecutionFidelity.REAL,
        {"quality_score": None},
        task_id=task_id,
    )

    events = [
        event
        for event in get_durable_event_bus().get_events(subject=SUBSYSTEM_SUBJECT, limit=100)
        if event["data"]["activity_id"] == activity.activity_id
    ]
    assert len(events) == 1
    assert events[0]["data"]["execution_effect"] is False
    assert events[0]["data"]["authority_decision"] == "ALLOW"
    assert activity.audit_id.startswith("audit-")


def test_boundary_rejects_ghost_task_provenance() -> None:
    """نسب نشاط إلى مهمّة لا وجود لها يسقط — لا يُقبل ادّعاء نسب."""
    from amos_federation.services.executive_core.repository import TaskNotFoundError

    with pytest.raises(TaskNotFoundError):
        get_subsystem_boundary().task_provenance("task-لا-وجود-له")


def test_boundary_classifies_unverified_provenance_without_silence() -> None:
    """المسارات القديمة تُصنَّف: canonical أو unverified أو none — لا صمت."""
    boundary = get_subsystem_boundary()
    task_id = _completed_task()["task"]["id"]
    assert boundary.classify_provenance(task_id) == ("canonical", task_id)
    assert boundary.classify_provenance("task-وهمي") == ("unverified", None)
    assert boundary.classify_provenance(None) == ("none", None)


def test_boundary_fails_closed_when_authorization_is_denied() -> None:
    """قرار غير ALLOW يمنع النشاط ولا يُنبّه فقط."""
    from amos_federation.services.executive_core.subsystem_boundary import (
        SubsystemRefusedError,
    )

    class DenyingAuthorizer:
        """مُصرِّح يرفض — لاختبار الإغلاق عند الرفض."""

        def review_only(self, action: str, target: str, metadata: dict[str, Any]) -> Any:
            from amos_federation.services.executive_core.sovereignty_bridge import (
                AuthorityEvidence,
            )

            return AuthorityEvidence(
                action=action,
                target=target,
                decision="DENY",
                authority_layer="FEDERAL",
                decision_kind="review",
                request_fingerprint="deny",
                ledger_entry_hash="deny",
                rules_evaluated=1,
                advisory_violations=(),
            )

    boundary = SubsystemBoundary(authorizer=DenyingAuthorizer())
    with pytest.raises(SubsystemRefusedError):
        boundary.authorize(ActivityKind.TRAINING_RUN, "training:x", {})


# ── R2-C: حدّ بوابة النماذج ─────────────────────────────────────────────────
def test_model_invocation_with_ghost_task_is_rejected() -> None:
    """استدعاء نموذج منسوب لمهمّة وهمية يُردّ بـ404."""
    response = model_client.post(
        "/v1/models/invoke",
        headers=MODEL_HEADERS,
        json={"prompt": "اختبار", "task_id": "task-وهمي"},
    )
    assert response.status_code == 404


def test_model_invocation_linked_to_canonical_task_is_recorded() -> None:
    """استدعاء منسوب لمهمّة قانونية يُقيَّد بإذن، ولا يمسّ حالتها."""
    task_id = _completed_task()["task"]["id"]
    before = ExecutiveTaskRepository().state_of(task_id)

    response = model_client.post(
        "/v1/models/invoke",
        headers=MODEL_HEADERS,
        json={"prompt": "اختبار نسب", "task_id": task_id},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["task_id"] == task_id
    assert body["activity_id"].startswith("act-")
    assert body["authority_decision"] == "ALLOW"
    assert ExecutiveTaskRepository().state_of(task_id) == before


def test_model_invocation_without_key_declares_unavailable_not_simulation() -> None:
    """غياب المفتاح يُعلَن `UNAVAILABLE` بسبب مُسمّى — لا محاكاة تُغطّي انقطاعًا."""
    response = model_client.post(
        "/v1/models/invoke", headers=MODEL_HEADERS, json={"prompt": "بلا مفتاح"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["execution_fidelity"] == ExecutionFidelity.UNAVAILABLE.value
    assert body["fidelity_reason"]
    assert body["source"] == "local_fallback"


# ── R2-D: حدّ التدريب ───────────────────────────────────────────────────────
def _dataset_id() -> str:
    response = training_client.post(
        "/v1/datasets",
        headers=TRAINING_HEADERS,
        json={"experiences": [{"type": "success", "outcome": {"x": 1}}], "target_per_type": 1},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["dataset_id"])


def test_training_declares_simulation_and_metric_origin() -> None:
    """مقاييس التدريب مشتقّة من hash، فتُعلَن محاكاة في الاستجابة وفي المقاييس."""
    response = training_client.post(
        "/v1/models/train", headers=TRAINING_HEADERS, json={"dataset_id": _dataset_id()}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["execution_fidelity"] == ExecutionFidelity.SIMULATION.value
    assert body["fidelity_reason"]
    assert body["model_card"]["metrics"]["metrics_origin"] == "sha256_seed"
    assert body["authority_decision"] == "ALLOW"


def test_training_with_ghost_task_is_rejected() -> None:
    """تدريب منسوب لمهمّة وهمية يُردّ — لا مسار تدريب مستقل عن النظام التنفيذي."""
    response = training_client.post(
        "/v1/models/train",
        headers=TRAINING_HEADERS,
        json={"dataset_id": _dataset_id(), "task_id": "task-وهمي"},
    )
    assert response.status_code == 404


def test_training_linked_to_task_does_not_move_its_state() -> None:
    """التدريب المنسوب لمهمّة قانونية لا يحرّك حالتها."""
    task_id = _completed_task()["task"]["id"]
    before = ExecutiveTaskRepository().state_of(task_id)
    response = training_client.post(
        "/v1/models/train",
        headers=TRAINING_HEADERS,
        json={"dataset_id": _dataset_id(), "task_id": task_id},
    )
    assert response.status_code == 201, response.text
    assert response.json()["task_id"] == task_id
    assert ExecutiveTaskRepository().state_of(task_id) == before


# ── R2-E: حدّ النقد والتقييم ────────────────────────────────────────────────
def test_critic_scores_canonical_result_not_caller_payload() -> None:
    """مهمّة قانونية تُقيَّم من نتيجتها المُخزّنة، والمادة المُقدَّمة تُردّ."""
    task_id = _completed_task()["task"]["id"]

    rejected = critic_client.post(
        "/v1/reviews",
        headers=CRITIC_HEADERS,
        json={
            "task_id": task_id,
            "steps": [{"number": 1, "status": "completed", "result": {"ok": True}}],
        },
    )
    assert rejected.status_code == 403

    accepted = critic_client.post("/v1/reviews", headers=CRITIC_HEADERS, json={"task_id": task_id})
    assert accepted.status_code == 201, accepted.text
    body = accepted.json()
    assert body["task_provenance"] == "canonical"
    assert body["scored_material"] == "canonical_result"
    assert body["activity_id"].startswith("act-")


def test_critic_marks_unlinked_review_as_unverified() -> None:
    """مراجعة تذكر مهمّة غير موجودة تمرّ موسومة `unverified` لا كحكم رسمي."""
    response = critic_client.post(
        "/v1/reviews",
        headers=CRITIC_HEADERS,
        json={
            "task_id": "task-غير-موجود",
            "steps": [{"number": 1, "status": "completed", "result": {"ok": True}}],
            "result_summary": "ملخّص",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["task_provenance"] == "unverified"
    assert body["scored_material"] == "caller_supplied"


def test_experience_records_task_provenance() -> None:
    """الخبرة تُوسَم canonical إن كانت المهمّة قانونية، وunverified إن لم تكن."""
    task_id = _completed_task()["task"]["id"]
    linked = evaluation_client.post(
        "/v1/experiences",
        headers=EVAL_HEADERS,
        json={"task_id": task_id, "type": "success", "outcome": {"ok": True}},
    )
    assert linked.status_code == 201, linked.text
    assert linked.json()["task_provenance"] == "canonical"
    assert linked.json()["provenance"]["task_provenance"] == "canonical"

    unlinked = evaluation_client.post(
        "/v1/experiences",
        headers=EVAL_HEADERS,
        json={"task_id": "task-وهمي", "type": "success", "outcome": {"ok": True}},
    )
    assert unlinked.status_code == 201
    assert unlinked.json()["task_provenance"] == "unverified"


# ── R2-F: مفردات الصدق ─────────────────────────────────────────────────────
def test_engine_fidelity_comes_from_the_shared_vocabulary() -> None:
    """صدق النواة يأتي من التعداد الواحد لا من نصّ حرّ."""
    assert ExecutionFidelity.SIMULATION.value == EXECUTION_FIDELITY


def test_non_real_fidelity_requires_a_named_reason() -> None:
    """إعلان محاكاة أو غياب بلا سبب مرفوض — وإلا صار الإعلان غطاءً للفشل."""
    with pytest.raises(ValueError):
        declare(ExecutionFidelity.UNAVAILABLE)
    assert declare(ExecutionFidelity.REAL) == {"execution_fidelity": "REAL"}
    declared = declare(ExecutionFidelity.SIMULATION, reason="tool_sandbox")
    assert declared["fidelity_reason"] == "tool_sandbox"


# ── R2-G: الحرس الساكن لأصناف التجاوز الستّة ────────────────────────────────
def _code_only(source: str) -> str:
    """إسقاط التعليقات والنصوص الحرفية — الحرس يفحص شفرة تعمل لا نثرًا يشرح.

    بلا هذا الإسقاط يسقط الحرس على توثيق يذكر البدائية المحرَّمة بالاسم، فيصبح
    الشرح الصادق مخالفة. المُحرَّم هو الاستدعاء، لا ذكره.
    """
    import io
    import tokenize

    kept: list[str] = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        kept.append(token.string)
    return " ".join(kept)


def _service_sources() -> dict[str, str]:
    import amos_federation.services as services_package

    root = Path(services_package.__file__).parent
    return {
        path.parent.name: _code_only(path.read_text(encoding="utf-8"))
        for path in sorted(root.glob("*/main.py"))
        if path.parent.name != "executive_core"
    }


def test_no_service_creates_tasks_outside_the_core() -> None:
    """لا خدمة تُنشئ صفّ مهمّة بنفسها — الإنشاء انتقال في آلة الحالات."""
    violations = {
        service: token
        for service, source in _service_sources().items()
        for token in ("task_store.create(", "_task_store.create(", "TaskModel(")
        if token in source
    }
    assert violations == {}, f"إنشاء مهمّة خارج النواة: {violations}"


def test_no_edge_service_publishes_task_events_directly() -> None:
    """الخدمات الحافّة لا تنشر أحداث انتقال — إصدار الحدث قرار النواة."""
    for service, source in _service_sources().items():
        assert TRANSITION_SUBJECT not in source, f"{service} ينشر حدث انتقال مباشرة"
        assert "task_transitioned" not in source, f"{service} ينشر حدث انتقال مباشرة"


def test_subsystem_services_pass_through_the_core_boundary() -> None:
    """النماذج والتدريب والنقد والتقييم تعبر حدّ النواة، لا تعمل بسلطة ذاتية."""
    sources = _service_sources()
    for service in ("model_gateway", "training", "critic", "evaluation"):
        assert "subsystem_boundary" in sources[service], f"{service} لا يعبر حدّ النواة"


def test_subsystem_boundary_never_mutates_task_state() -> None:
    """حدّ الأنظمة المتخصّصة لا يملك بدائية كتابة حالة — بالنصّ لا بالنيّة."""
    from amos_federation.services.executive_core import subsystem_boundary

    source = _code_only(Path(subsystem_boundary.__file__).read_text(encoding="utf-8"))
    for forbidden in ("compare_and_set", "update_status(", "PersistentTaskStore"):
        assert forbidden not in source, f"حدّ الأنظمة المتخصّصة يكتب حالة: {forbidden}"


def test_no_service_fabricates_a_quality_score() -> None:
    """لا خدمة تُسند درجة جودة ثابتة مُخترعة — الدرجة تُحسب أو تُترك غائبة."""
    import amos_federation.services as services_package

    root = Path(services_package.__file__).parent
    for path in sorted(root.glob("*/main.py")):
        raw = path.read_text(encoding="utf-8")
        assert "quality_score=0.85" not in raw, f"{path.parent.name} يخترع درجة جودة"
        assert '"quality_score": 0.85' not in raw, f"{path.parent.name} يخترع درجة جودة"
