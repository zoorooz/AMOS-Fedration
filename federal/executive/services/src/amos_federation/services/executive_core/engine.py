"""الهدف: النواة التنفيذية الفدرالية — دورة حياة المهمّة كاملة، محكومة ومُدقَّقة.

النطاق: federal/executive/services — النواة التنفيذية
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-16
تاريخ آخر تعديل: 2026-08-18

ما كان موجودًا قبل هذه الوحدة، بالقياس لا بالوصف:

| القطعة | حالتها |
|---|---|
| `orchestrator.build_plan` | خطة قوالب ثابتة، تُنشَر كحدث ثم **تُنسى** |
| `WorkerAgent.execute` | ينفّذ خطة تُعطى له، ولا أحد يعطيه واحدة |
| `tasks` في القاعدة | صفوف بحالة نصّية حرّة، بلا آلة حالات |
| `agents` في القاعدة | جدول لا يقرؤه أحد |
| `SovereignGateway` | «المسار الوحيد للتنفيذ» ولا ملف في `federal/` يستورده |
| `PersistentAuditStore` | سلسلة تدقيق حقيقية، غير موصولة بمسار المهام |

فلم تكن الدولة تنفّذ مهمّة: كانت تملك قطع تنفيذ متجاورة. هذه الوحدة هي الوصل:
كل انتقال حالة يمرّ **أولًا** بالبوابة السيادية، ثم يُكتب في القاعدة بانتقال
ذرّي، ثم يُقيَّد في سلسلة التدقيق، ثم يُنشَر كحدث دائم. أربع خطوات بهذا الترتيب،
ولا خطوة منها اختيارية.

صدق المخرَج — ما هو حقيقي وما هو محاكاة في هذا المسار:

- REAL: آلة الحالات، الانتقال الذرّي على PostgreSQL/SQLite، التقييم الدستوري عبر
  البوابة، سلسلة تدقيق مُهشَّرة، ناقل أحداث دائم في القاعدة، اختيار الوكيل من
  سجل الوكلاء، الاسترداد بعد إعادة التشغيل.
- SIMULATION: تنفيذ الأداة نفسه. `ToolSandbox` في `agent_runtime` كله دوالّ
  `_mock_*`. فالنواة تنفّذ خطوات حقيقية على صندوق أدوات محاكٍ، وتقول ذلك في
  نتيجة كل مهمّة بحقل `execution_fidelity = "SIMULATION"`. استبدال الصندوق
  بأدوات حقيقية وحدةُ عمل مستقلّة، ولا يُزعم أنها أُنجزت هنا.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from amos_federation.common.durable_event_bus import get_durable_event_bus
from amos_federation.common.persistent import PersistentAuditStore
from amos_federation.services.executive_core.agent_runtime_gateway import (
    UNKNOWN as UNKNOWN_VALUE,
)
from amos_federation.services.executive_core.agent_runtime_gateway import (
    AgentRuntimeGateway,
    CapabilityDeniedError,
    RuntimeDispatchError,
)
from amos_federation.services.executive_core.dispatcher import (
    CapabilityDispatcher,
    NoEligibleAgentError,
)
from amos_federation.services.executive_core.fidelity import ExecutionFidelity
from amos_federation.services.executive_core.repository import ExecutiveTaskRepository
from amos_federation.services.executive_core.sovereignty_bridge import (
    AuthorityEvidence,
    ConstitutionalAuthorizer,
    GuardedResult,
    compensator,
    declared_effect,
    operation_key,
)
from amos_federation.services.executive_core.states import (
    TaskState,
    assert_transition,
    is_terminal,
    parse_state,
)

#: موضوع الحدث الدائم لكل انتقال حالة في النواة التنفيذية.
TRANSITION_SUBJECT = "amos_federation.executive.task_transitioned"

#: الفاعل المُسجَّل في سلسلة التدقيق — الفرع التنفيذي لا التاج.
AUDIT_ACTOR = "federal.executive.core"

#: نطاقا مفتاحِ الذرّيّة (1H). النطاقُ يمنعُ تصادمَ «قبولِ مهمّة» بـ«انتقالِ حالة»
#: على المهمّةِ نفسِها، فلا تُعَدُّ إحداهما إعادةً للأخرى.
SUBMIT_KEY_SCOPE = "federal.executive.task.submit"
TRANSITION_KEY_SCOPE = "federal.executive.task.transition"

#: أمانة المخرَج: تنفيذ الأدوات محاكاة حتى يُستبدل صندوق الأدوات بأدوات حقيقية.
#: القيمة تأتي من مفردات واحدة (`fidelity.ExecutionFidelity`) لا من نصّ حرّ، كي
#: تُقارَن إعلانات الصدق بين النواة والخدمات المتخصّصة بدلًا من تشابه لفظي.
EXECUTION_FIDELITY = ExecutionFidelity.SIMULATION.value


class ExecutionRefusedError(RuntimeError):
    """طلب تقدُّم على مهمّة لا تقبله حالتها (منتهية أو غير موجودة)."""


@dataclass(frozen=True)
class TransitionOutcome:
    """أثر انتقال واحد: ما تغيّر، وبأي إذن، وبأي دليل."""

    task_id: str
    from_state: TaskState
    to_state: TaskState
    evidence: AuthorityEvidence
    audit_id: str
    audit_hash: str
    event_id: str
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "from_state": self.from_state.value,
            "to_state": self.to_state.value,
            "authority": self.evidence.as_dict(),
            "audit_id": self.audit_id,
            "audit_hash": self.audit_hash,
            "event_id": self.event_id,
            "detail": self.detail,
        }


class ExecutiveCore:
    """محرّك دورة حياة المهمّة — نقطة الدخول الوحيدة للتنفيذ الفدرالي."""

    def __init__(
        self,
        authorizer: Any | None = None,
        repository: ExecutiveTaskRepository | None = None,
        dispatcher: CapabilityDispatcher | None = None,
        audit_store: Any | None = None,
        event_bus: Any | None = None,
        planner: Any | None = None,
        agent_factory: Any | None = None,
        runtime: AgentRuntimeGateway | None = None,
    ) -> None:
        self._authorizer = authorizer or ConstitutionalAuthorizer()
        self._repo = repository or ExecutiveTaskRepository()
        self._dispatcher = dispatcher or CapabilityDispatcher()
        self._audit = audit_store or PersistentAuditStore()
        self._bus = event_bus or get_durable_event_bus()
        self._planner = planner
        self._agent_factory = agent_factory
        # حدّ واحد إلى بيئة تشغيل الوكلاء القائمة. `agent_factory` يُمرَّر إليه كما
        # هو كي يبقى الحقن للاختبار عابرًا بالمسار القانوني لا مُتجاوزًا له.
        self._runtime = runtime or AgentRuntimeGateway(
            agent_factory=agent_factory,
            audit_store=self._audit,
            event_bus=self._bus,
        )

    # ── أدوات داخلية ─────────────────────────────────────────────────────
    def _plan_for(self, task: dict[str, Any]) -> list[dict[str, Any]]:
        """الخطة من المنسّق القائم — لا يُعاد كتابة التخطيط هنا.

        الاستيراد متأخّر بقصد: وحدة المنسّق تبني تطبيق FastAPI عند استيرادها،
        وليس من شأن آلة الحالات أن تُنشئ تطبيقًا لمجرّد أنها تريد خطة.
        """
        if self._planner is not None:
            return list(self._planner(task))
        from amos_federation.services.orchestrator.main import PlanRequest, build_plan

        known = {"analysis", "report", "data", "generic"}
        task_type = task["type"] if task["type"] in known else "generic"
        return build_plan(
            PlanRequest(type=task_type, description=task["description"], task_id=task["id"])
        )

    def _record(
        self,
        task_id: str,
        from_state: TaskState,
        to_state: TaskState,
        evidence: AuthorityEvidence,
        detail: dict[str, Any],
    ) -> TransitionOutcome:
        """قيد التدقيق ثم الحدث الدائم — بهذا الترتيب: الأثر قبل الإعلان."""
        entry = self._audit.append(
            f"executive.task.{to_state.value}",
            AUDIT_ACTOR,
            {
                "task_id": task_id,
                "from_state": from_state.value,
                "to_state": to_state.value,
                "authority": evidence.as_dict(),
                "detail": detail,
            },
        )
        event = self._bus.publish(
            TRANSITION_SUBJECT,
            {
                "task_id": task_id,
                "from_state": from_state.value,
                "to_state": to_state.value,
                "audit_id": entry["audit_id"],
                "authority_decision": evidence.decision,
                "authority_layer": evidence.authority_layer,
                "detail": detail,
            },
            correlation_id=task_id,
        )
        return TransitionOutcome(
            task_id=task_id,
            from_state=from_state,
            to_state=to_state,
            evidence=evidence,
            audit_id=entry["audit_id"],
            audit_hash=entry["hash"],
            event_id=event["event_id"],
            detail=detail,
        )

    def _guarded_transition(
        self,
        task_id: str,
        expected: TaskState,
        target: TaskState,
        action: str,
        *,
        fields: dict[str, Any] | None = None,
        detail: dict[str, Any] | None = None,
    ) -> TransitionOutcome:
        """انتقال محكوم: حدُّ التنفيذ السياديّ → كتابة ذرّية → تدقيق → حدث.

        الكتابة تحدث **داخل** مُطبِّقِ الحدّ، فلا تقع خارج الإذن. وإن سبقنا
        مُنفِّذ آخر إلى الحالة نفسها، يُرفع `ExecutionRefusedError` — ولا يُدّعى نجاح.

        ما أضافته 1N فوقَ ما كان: أثرٌ مُعلَنٌ واحدٌ (`WRITE` على المهمّة) يُقاسُ
        عليه العقد، ومفتاحُ ذرّيّةٍ يجعلُ الانتقالَ الواحدَ غيرَ قابلٍ للتكرار،
        ومعوّضٌ يُعيدُ الحالةَ إلى `expected` إن فشلت العمليّة بعدَ الكتابة.
        والإعادةُ (`is_replay`) تُرفَض هنا كما يُرفَض السَّبْق: الانتقالُ الواحدُ
        لا يقعُ مرّتين، وإرجاعُ نجاحٍ ثانٍ كان سيكون ادّعاءً.
        """
        # مشروعيّةُ الانتقال تُفحَص **قبل** الحدّ: آلةُ الحالاتِ ليست سؤالَ سلطةٍ،
        # وانتقالٌ مستحيلٌ لا يُصدَر له إذنٌ ولا يُحجَز له مفتاحُ ذرّيّة. وبهذا يبقى
        # `IllegalTransitionError` كما كان يراه المُنادي، لا ملفوفًا في خطأِ سجلّ.
        assert_transition(expected, target)
        payload = dict(fields or {})
        resource = f"task:{task_id}"

        def _write(_effect: Any) -> bool:
            return self._repo.compare_and_set(task_id, expected, target, **payload)

        def _revert() -> None:
            self._repo.compare_and_set(task_id, target, expected)

        effect = declared_effect(
            "WRITE", resource, f"{expected.value} → {target.value}"
        )
        guarded: GuardedResult = self._authorizer.guard_declared(
            action,
            resource,
            declared_effects=(effect,),
            applier=_write,
            operation_key=operation_key(
                TRANSITION_KEY_SCOPE, f"{task_id}:{expected.value}->{target.value}"
            ),
            compensators=(
                compensator(
                    effect.signature,
                    _revert,
                    f"إرجاع {task_id} إلى {expected.value}",
                ),
            ),
            metadata={"from_state": expected.value, "to_state": target.value},
        )
        if guarded.is_replay or not guarded.value:
            raise ExecutionRefusedError(
                f"لم يُطبَّق الانتقال {expected.value} → {target.value} للمهمّة {task_id}: "
                + (
                    "العمليّة مُثبَّتة سابقًا في سجل الذرّيّة (إعادة)"
                    if guarded.is_replay
                    else "الحالة تغيّرت قبلنا (تنفيذ متزامن)"
                )
            )
        return self._record(task_id, expected, target, guarded.evidence, dict(detail or {}))

    # ── الاستقبال ────────────────────────────────────────────────────────
    def submit(
        self,
        task_type: str,
        description: str,
        *,
        task_id: str | None = None,
        priority: str = "normal",
        domain: str = "general",
        tenant_id: str = "default",
    ) -> dict[str, Any]:
        """قبول مهمّة جديدة عبر حدِّ التنفيذ: إذن ثم كتابة ثم تدقيق وحدث.

        الأثرُ المُعلَنُ `CREATE` على المهمّة، ومعوّضُه محوُ الصفِّ — ولولا وجودُ
        معكوسٍ حقيقيٍّ في المستودع لرفض 1I العقدَ قبلَ أن يُنشَأ شيء.
        """
        new_id = task_id or f"task-{uuid.uuid4()}"
        resource = f"task:{new_id}"

        def _create(_effect: Any) -> dict[str, Any]:
            return self._repo.create(
                new_id,
                task_type,
                description,
                priority=priority,
                domain=domain,
                tenant_id=tenant_id,
            )

        def _erase() -> None:
            self._repo.delete(new_id)

        effect = declared_effect("CREATE", resource, task_type)
        guarded: GuardedResult = self._authorizer.guard_declared(
            "task.submit",
            resource,
            declared_effects=(effect,),
            applier=_create,
            operation_key=operation_key(SUBMIT_KEY_SCOPE, new_id),
            compensators=(
                compensator(effect.signature, _erase, f"محو المهمّة {new_id}"),
            ),
            metadata={"type": task_type, "priority": priority, "domain": domain},
        )
        if guarded.is_replay:
            raise ExecutionRefusedError(
                f"المهمّة {new_id} مُثبَّتة سابقًا في سجل الذرّيّة — لا قبولَ ثانٍ لها"
            )
        outcome = self._record(
            new_id,
            TaskState.CREATED,
            TaskState.CREATED,
            guarded.evidence,
            {"type": task_type, "priority": priority, "domain": domain, "phase": "submitted"},
        )
        task = dict(guarded.value)
        task["submission"] = outcome.as_dict()
        return task

    # ── التقدّم خطوة واحدة ────────────────────────────────────────────────
    def advance(self, task_id: str) -> TransitionOutcome:
        """خطوة واحدة حتمية في دورة حياة المهمّة، حسب حالتها الحالية."""
        task = self._repo.require(task_id)
        state = parse_state(task["status"])
        if is_terminal(state):
            raise ExecutionRefusedError(
                f"المهمّة {task_id} في حالة نهائية ({state.value}) — لا تقدُّم بعدها"
            )
        if state is TaskState.CREATED:
            return self._authorize_step(task)
        if state is TaskState.AUTHORIZED:
            return self._plan_step(task)
        if state is TaskState.PLANNED:
            return self._dispatch_step(task)
        if state is TaskState.DISPATCHED:
            return self._start_step(task)
        return self._execute_step(task)

    def _authorize_step(self, task: dict[str, Any]) -> TransitionOutcome:
        """التقييم الدستوري للمهمّة نفسها: تُأذَن أو تُرفَض — والرفض قرار مُسجَّل."""
        task_id = task["id"]
        action = f"task.authorize.{task['type']}"
        evidence = self._authorizer.review_only(
            action,
            f"task:{task_id}",
            {"priority": task["priority"], "domain": task["domain"]},
        )
        if evidence.decision != "ALLOW":
            return self._guarded_transition(
                task_id,
                TaskState.CREATED,
                TaskState.REJECTED,
                "task.reject",
                fields={"result": {"rejection": evidence.as_dict()}},
                detail={"reason": "constitutional_denial", "authority": evidence.as_dict()},
            )
        return self._guarded_transition(
            task_id,
            TaskState.CREATED,
            TaskState.AUTHORIZED,
            "task.authorize",
            detail={"authorization": evidence.as_dict()},
        )

    def _plan_step(self, task: dict[str, Any]) -> TransitionOutcome:
        task_id = task["id"]
        plan = self._plan_for(task)
        if not plan:
            return self._guarded_transition(
                task_id,
                TaskState.AUTHORIZED,
                TaskState.FAILED,
                "task.fail",
                fields={"result": {"error": "empty_plan"}},
                detail={"reason": "empty_plan"},
            )
        return self._guarded_transition(
            task_id,
            TaskState.AUTHORIZED,
            TaskState.PLANNED,
            "task.plan",
            fields={"plan": plan},
            detail={"steps": len(plan), "plan": plan},
        )

    def _dispatch_step(self, task: dict[str, Any]) -> TransitionOutcome:
        task_id = task["id"]
        try:
            assignment = self._dispatcher.select(task["plan"], tenant_id=task["tenant_id"])
        except NoEligibleAgentError as exc:
            # سقوط صريح مُسجَّل: لا وكيل مؤهَّل ≠ ننفّذ بأي وكيل.
            return self._guarded_transition(
                task_id,
                TaskState.PLANNED,
                TaskState.FAILED,
                "task.fail",
                fields={"result": {"error": "no_eligible_agent", "message": str(exc)}},
                detail={"reason": "no_eligible_agent", "message": str(exc)},
            )
        return self._guarded_transition(
            task_id,
            TaskState.PLANNED,
            TaskState.DISPATCHED,
            "task.dispatch",
            fields={
                "assigned_agent": assignment.agent_id,
                # لقطة تعيين التوزيع تُحفَظ في القاعدة، لا تُلقى كما كان قبل R3.
                # وهي أثر نسب لا مصدر صلاحية: التنفيذ يُعيد قراءة السجل الحيّ.
                "result": {"dispatch": assignment.as_dict()},
            },
            detail={"assignment": assignment.as_dict()},
        )

    def _start_step(self, task: dict[str, Any]) -> TransitionOutcome:
        """تثبيت بداية التنفيذ في القاعدة **قبل** تشغيل الوكيل.

        الترتيب مقصود: مهمّة انقطع تنفيذها تُقرأ `executing` بعد إعادة التشغيل،
        فيعرف الاسترداد أنها بدأت ولا يُعيد تشغيلها كأنها لم تبدأ.
        """
        return self._guarded_transition(
            task["id"],
            TaskState.DISPATCHED,
            TaskState.EXECUTING,
            "task.start",
            detail={"agent_id": task["assigned_agent"], "started_at": _now()},
        )

    def _execute_step(self, task: dict[str, Any]) -> TransitionOutcome:
        """التنفيذ الفعلي عبر حدّ بيئة التشغيل — لا مسار تنفيذ ثانٍ.

        النواة تبقى صاحبة القرار وحاملة القلم: هي من تقرأ التعيين من السجل، وهي
        من تنقل الحالة وتكتب النتيجة. الحدّ ينفّذ ولا يقرّر، ولا يكتب في `tasks`.
        """
        task_id = task["id"]
        agent_id = task["assigned_agent"]
        if not agent_id:
            return self._guarded_transition(
                task_id,
                TaskState.EXECUTING,
                TaskState.FAILED,
                "task.fail",
                fields={"result": {"error": "missing_agent"}},
                detail={"reason": "missing_agent"},
            )
        plan = list(task["plan"] or [])
        try:
            # تعيين مُعاد قراءته من سجل الوكلاء لحظة التنفيذ — لا تعيين مُلفَّق
            # من أدوات الخطة نفسها كما كان قبل R3.
            assignment = self._dispatcher.assignment_for(
                agent_id, plan, tenant_id=task["tenant_id"]
            )
        except NoEligibleAgentError as exc:
            return self._guarded_transition(
                task_id,
                TaskState.EXECUTING,
                TaskState.FAILED,
                "task.fail",
                fields={
                    "result": {
                        "error": "agent_not_employable",
                        "message": str(exc),
                        "execution_fidelity": EXECUTION_FIDELITY,
                    }
                },
                detail={"reason": "agent_not_employable", "agent_id": agent_id},
            )
        try:
            outcome = self._runtime.dispatch(
                task,
                assignment,
                authorization={
                    "authorized_action": f"task.authorize.{task['type']}",
                    "authorized_by": AUDIT_ACTOR,
                },
            )
        except CapabilityDeniedError as exc:
            # fail-closed: قدرة غير ممنوحة ⇒ لا تنفيذ جزئي ولا بديل صامت.
            return self._guarded_transition(
                task_id,
                TaskState.EXECUTING,
                TaskState.FAILED,
                "task.fail",
                fields={
                    "result": {
                        "error": "capability_denied",
                        "message": str(exc),
                        "agent_id": agent_id,
                        "agent_role": assignment.agent_role,
                        "capabilities_granted": list(assignment.allowed_tools),
                        "capabilities_required": list(assignment.required_tools),
                        "execution_fidelity": EXECUTION_FIDELITY,
                    }
                },
                detail={"reason": "capability_denied", "message": str(exc)},
            )
        except RuntimeDispatchError as exc:
            error, _, message = str(exc).partition(": ")
            return self._guarded_transition(
                task_id,
                TaskState.EXECUTING,
                TaskState.FAILED,
                "task.fail",
                fields={
                    "result": {
                        "error": error,
                        "message": message,
                        "execution_fidelity": EXECUTION_FIDELITY,
                    }
                },
                detail={"reason": "agent_exception", "error": error},
            )
        payload = outcome.as_dict()
        payload["execution_fidelity"] = EXECUTION_FIDELITY
        payload["completed_at"] = _now()
        # نسب كامل: تعيين لحظة التوزيع كما حُفظ، وتعيين لحظة التنفيذ كما قُرئ.
        # اختلافهما ليس خطأً يُخفى بل حقيقة تُقرأ (ضاقت صلاحية الوكيل مثلًا).
        payload["dispatch_assignment"] = (task["result"] or {}).get("dispatch") or UNKNOWN_VALUE
        payload["execution_assignment"] = assignment.as_dict()
        if payload["status"] in {"failed", "empty"}:
            return self._guarded_transition(
                task_id,
                TaskState.EXECUTING,
                TaskState.FAILED,
                "task.fail",
                fields={"result": {**payload, "error": f"agent_execution_{payload['status']}"}},
                detail={
                    "reason": f"agent_execution_{payload['status']}",
                    "agent_id": agent_id,
                    "execution_id": payload["execution_id"],
                },
            )
        return self._guarded_transition(
            task_id,
            TaskState.EXECUTING,
            TaskState.COMPLETED,
            "task.complete",
            fields={"result": payload},
            detail={
                "agent_id": agent_id,
                "agent_role": payload["agent_role"],
                "execution_id": payload["execution_id"],
                "agent_status": payload["status"],
                "steps": len(payload.get("steps", []) or []),
                "execution_fidelity": EXECUTION_FIDELITY,
                "runtime_fidelity": payload["runtime_fidelity"],
                "tool_execution_fidelity": payload["tool_execution_fidelity"],
            },
        )

    # ── التشغيل حتى النهاية ───────────────────────────────────────────────
    def run(self, task_id: str, max_steps: int = 8) -> dict[str, Any]:
        """تقديم المهمّة حتى حالة نهائية أو حتى نفاد الخطوات المسموحة."""
        outcomes: list[TransitionOutcome] = []
        for _ in range(max_steps):
            state = self._repo.state_of(task_id)
            if is_terminal(state):
                break
            outcomes.append(self.advance(task_id))
        task = self._repo.require(task_id)
        return {
            "task": task,
            "transitions": [outcome.as_dict() for outcome in outcomes],
            "final_state": task["status"],
            "terminal": is_terminal(task["status"]),
        }

    def advance_to(self, task_id: str, target: TaskState, max_steps: int = 8) -> dict[str, Any]:
        """تقديم المهمّة حتى حالة مطلوبة — بخطوات `advance` نفسها لا بمسار ثانٍ.

        أُضيفت في R1 لتستطيع الخدمات الخارجية (`orchestrator`) أن تطلب حدًّا من
        دورة الحياة (مثلًا: خطّط ولا تُنفّذ) بلا أن تُعيد تنفيذ آلة الحالات عندها.
        وإن انتهت المهمّة قبل بلوغ الهدف (رفض دستوري أو سقوط)، تُقال الحقيقة في
        `reached=False` ولا يُدّعى بلوغ الهدف.
        """
        outcomes: list[TransitionOutcome] = []
        for _ in range(max_steps):
            state = self._repo.state_of(task_id)
            if state is target or is_terminal(state):
                break
            outcomes.append(self.advance(task_id))
        task = self._repo.require(task_id)
        return {
            "task": task,
            "transitions": [outcome.as_dict() for outcome in outcomes],
            "final_state": task["status"],
            "reached": task["status"] == target.value,
            "terminal": is_terminal(task["status"]),
        }

    def submit_and_run(self, task_type: str, description: str, **kwargs: Any) -> dict[str, Any]:
        """المسار الكامل: قبول ثم تنفيذ حتى النهاية."""
        task = self.submit(task_type, description, **kwargs)
        outcome = self.run(task["id"])
        outcome["submission"] = task["submission"]
        return outcome

    # ── الإلغاء ──────────────────────────────────────────────────────────
    def cancel(self, task_id: str, reason: str) -> TransitionOutcome:
        """إلغاء مهمّة لم تبدأ تنفيذها بعد.

        الإلغاء أثناء `executing` غير مسموح في آلة الحالات، لأن تغيير صفٍّ في
        جدول لا يوقف عملًا جاريًا — والادّعاء بأنه يوقفه كذب تشغيلي.
        """
        state = self._repo.state_of(task_id)
        return self._guarded_transition(
            task_id,
            state,
            TaskState.CANCELLED,
            "task.cancel",
            fields={"result": {"cancellation_reason": reason}},
            detail={"reason": reason},
        )

    # ── الاسترداد ────────────────────────────────────────────────────────
    def recover(self, max_tasks: int = 50) -> dict[str, Any]:
        """استرداد المهام غير المنتهية بعد إعادة تشغيل.

        قاعدة الصدق: مهمّة كانت `executing` لحظة الانقطاع **لا** تُعتبر مكتملة
        ولا تُعاد من الصفر — تُنقل إلى `failed` بسبب `interrupted_execution`،
        لأن نتائج خطواتها لم تُثبَّت. أما ما لم يبدأ تنفيذه فيُقدَّم خطوة واحدة.
        """
        resumed: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        for task in self._repo.list_unfinished(limit=max_tasks):
            task_id = task["id"]
            state = parse_state(task["status"])
            if state is TaskState.EXECUTING:
                outcome = self._guarded_transition(
                    task_id,
                    TaskState.EXECUTING,
                    TaskState.FAILED,
                    "task.fail",
                    fields={"result": {"error": "interrupted_execution"}},
                    detail={"reason": "interrupted_execution"},
                )
                failed.append(outcome.as_dict())
                continue
            resumed.append(self.advance(task_id).as_dict())
        return {
            "resumed": resumed,
            "interrupted": failed,
            "resumed_count": len(resumed),
            "interrupted_count": len(failed),
        }

    # ── قراءة الحالة ─────────────────────────────────────────────────────
    def status(self, task_id: str) -> dict[str, Any]:
        task = self._repo.require(task_id)
        state = parse_state(task["status"])
        return {
            "task": task,
            "state": state.value,
            "terminal": is_terminal(state),
            "execution_fidelity": EXECUTION_FIDELITY,
        }

    def health(self) -> dict[str, Any]:
        """حالة النواة: التاج، أعلى سلطة، وعدد المهام غير المنتهية."""
        return {
            "crown_status": self._authorizer.crown_status(),
            "supreme_authority": self._authorizer.supreme_authority(),
            "unfinished_tasks": len(self._repo.list_unfinished()),
            "execution_fidelity": EXECUTION_FIDELITY,
            "transition_subject": TRANSITION_SUBJECT,
        }


def _now() -> str:
    return datetime.now(UTC).isoformat()


_core: ExecutiveCore | None = None


def get_executive_core() -> ExecutiveCore:
    """نواة تنفيذية واحدة للعملية — تُبنى عند أول طلب."""
    global _core
    if _core is None:
        _core = ExecutiveCore()
    return _core


def reset_executive_core() -> None:
    """إسقاط النواة المحفوظة — تستخدمه الاختبارات بعد تغيير قاعدة البيانات."""
    global _core
    _core = None
