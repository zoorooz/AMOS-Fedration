"""الهدف: حدّ واحد تمرّ به الأنظمة المتخصّصة (نماذج، تدريب، تقييم، نقد) بلا دورة حياة ثانية.

النطاق: federal/executive/services — النواة التنفيذية
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-16

المشكلة المقيسة قبل R2:

| الخدمة | ما كانت تفعله | الإذن | نسب المهمّة | الأثر المُدقَّق |
|---|---|---|---|---|
| `model_gateway` | تستدعي نموذجًا خارجيًّا أو تُرجع نصًّا محليًّا | لا شيء | لا شيء | سجل تكلفة في الذاكرة يضيع |
| `training` | «تُدرّب» وتُرجع `accuracy` مشتقًّا من hash | لا شيء | لا شيء | لا شيء |
| `critic` | يُقيّم خطوات **يرسلها الطالب نفسه** | لا شيء | `task_id` نصّ حرّ لا يُتحقَّق | سجل نقد فقط |
| `evaluation` | تُسجّل خبرة بأي `task_id` | لا شيء | لا يُتحقَّق | سجل خبرات فقط |

فكانت هذه سلطات موازية: تُنتج قرارات ونتائج تُنسب إلى الدولة بلا إذن سيادي وبلا
نسب قابل للتحقّق. هذه الوحدة تُغلق ذلك بحدّ واحد **تملكه النواة**:

1. `authorize` — تقييم دستوري عبر البوابة السيادية نفسها، fail-closed: ما لم
   يكن القرار `ALLOW` فلا نشاط (`SubsystemRefusedError`).
2. `task_provenance` — إن ادّعى النشاط انتسابه لمهمّة، تُقرأ المهمّة من المستودع
   القانوني. مهمّة غير موجودة = نسب مُلفَّق، فيسقط الطلب.
3. `record` — قيد تدقيق ثم حدث دائم على الناقل الموجود، بحقل صريح
   `execution_effect: False`.

وما **لا** تفعله هذه الوحدة، بقصد: لا تنقل حالة مهمّة. لا تستدعي
`compare_and_set` ولا تكتب في `tasks` إطلاقًا. الأنظمة المتخصّصة تُرفِق أثرها
بدورة الحياة، ولا تحرّكها؛ تحريكها بيد آلة الحالات في `engine.py` وحدها —
ويحرس هذا اختبارٌ ساكن يفحص هذه الوحدة نفسها.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from amos_federation.common.durable_event_bus import get_durable_event_bus
from amos_federation.common.persistent import PersistentAuditStore
from amos_federation.services.executive_core.repository import (
    ExecutiveTaskRepository,
    TaskNotFoundError,
)
from amos_federation.services.executive_core.sovereignty_bridge import (
    AuthorityEvidence,
    ConstitutionalAuthorizer,
)

_logger = logging.getLogger(__name__)

if TYPE_CHECKING:  # تُستعمل في التوقيعات فقط — قيمتها تأتي من المُنادي
    from amos_federation.services.executive_core.fidelity import ExecutionFidelity

#: موضوع الحدث الدائم لنشاط الأنظمة المتخصّصة — موضوع واحد على الناقل القائم.
SUBSYSTEM_SUBJECT = "amos_federation.executive.subsystem_activity"

#: الفاعل في سلسلة التدقيق: النواة هي من يُقيّد، لا الخدمة المتخصّصة.
AUDIT_ACTOR = "federal.executive.core"


class ActivityKind(StrEnum):
    """أنواع نشاط الأنظمة المتخصّصة المعروفة للنواة."""

    MODEL_INVOCATION = "model.invocation"
    TRAINING_RUN = "training.run"
    EVALUATION_RUN = "evaluation.run"
    CRITIQUE = "critique.review"


class SubsystemRefusedError(PermissionError):
    """رفض دستوري لنشاط نظام متخصّص — فلا نشاط، ولا مخرَج يُقدَّم كأنه مُجاز."""


@dataclass(frozen=True)
class SubsystemActivity:
    """أثر نشاط واحد: بأي إذن وقع، وإلى أي مهمّة يُنسب، وبأي صدق."""

    activity_id: str
    kind: str
    task_id: str | None
    fidelity: str
    authority: dict[str, Any]
    audit_id: str
    audit_hash: str
    event_id: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "activity_id": self.activity_id,
            "kind": self.kind,
            "task_id": self.task_id,
            "execution_fidelity": self.fidelity,
            "authority": self.authority,
            "audit_id": self.audit_id,
            "audit_hash": self.audit_hash,
            "event_id": self.event_id,
            "execution_effect": False,
        }


class SubsystemBoundary:
    """الحدّ الذي تعبره الأنظمة المتخصّصة: إذن، نسب، تدقيق، حدث — بلا تنفيذ مهمّة."""

    def __init__(
        self,
        authorizer: Any | None = None,
        repository: ExecutiveTaskRepository | None = None,
        audit_store: Any | None = None,
        event_bus: Any | None = None,
    ) -> None:
        self._authorizer = authorizer or ConstitutionalAuthorizer()
        self._repo = repository or ExecutiveTaskRepository()
        self._audit = audit_store or PersistentAuditStore()
        self._bus = event_bus or get_durable_event_bus()

    # ── النسب ────────────────────────────────────────────────────────────
    def task_provenance(self, task_id: str) -> dict[str, Any]:
        """قراءة المهمّة القانونية التي يُنسب إليها النشاط — قراءة فقط.

        Raises:
            TaskNotFoundError: المعرّف لا يقابل صفًّا في مصدر الحقيقة.
        """
        task = self._repo.require(task_id)
        return {
            "task_id": task["id"],
            "state": task["status"],
            "type": task["type"],
            "assigned_agent": task["assigned_agent"],
            "tenant_id": task["tenant_id"],
        }

    def canonical_result(self, task_id: str) -> dict[str, Any]:
        """نتيجة المهمّة كما خزّنتها النواة — مادة تقييم لا يملكها الطالب.

        تُقرأ من مصدر الحقيقة لا من حمولة الطلب، كي لا يُقيّم أحد مادة قدّمها بنفسه.

        Raises:
            TaskNotFoundError: المعرّف لا يقابل مهمّة قانونية.
        """
        task = self._repo.require(task_id)
        result = task.get("result") or {}
        return {
            "task_id": task["id"],
            "state": task["status"],
            "agent_id": result.get("agent_id") or task["assigned_agent"] or "",
            "summary": str(result.get("summary") or ""),
            "steps": list(result.get("steps") or []),
            "execution_fidelity": result.get("execution_fidelity"),
        }

    def classify_provenance(self, task_id: str | None) -> tuple[str, str | None]:
        """تصنيف نسب نشاط قد يذكر مهمّة لا وجود لها — للمسارات القديمة.

        بعض الواجهات (`/reviews`، `/experiences`) تقبل `task_id` نصًّا حرًّا منذ
        ما قبل النواة، وكانت تنسب نفسها إلى مهمّات غير موجودة بلا أن يظهر ذلك.
        هنا لا يُرفض الطلب ولا يُقبل ادّعاؤه: يُصنَّف.

        Returns:
            `("canonical", task_id)` إن كانت المهمّة في مصدر الحقيقة،
            `("unverified", None)` إن ذُكرت ولم تُوجد، `("none", None)` إن لم تُذكر.
        """
        if not task_id:
            return "none", None
        try:
            self._repo.require(task_id)
        except TaskNotFoundError as exc:
            _logger.warning(
                "مرجعُ مهمّةٍ غيرُ مُتحقَّق task_id=%s — %s", task_id, exc
            )
            return "unverified", None
        return "canonical", task_id

    # ── الإذن ────────────────────────────────────────────────────────────
    def authorize(
        self,
        kind: ActivityKind,
        target: str,
        context: dict[str, Any] | None = None,
    ) -> AuthorityEvidence:
        """تقييم دستوري للنشاط قبل وقوعه — الرفض يمنع، لا يُنبّه.

        Raises:
            SubsystemRefusedError: القرار ليس `ALLOW`.
        """
        evidence = self._authorizer.review_only(
            f"subsystem.{kind.value}", target, dict(context or {})
        )
        if evidence.decision != "ALLOW":
            raise SubsystemRefusedError(
                f"رُفض نشاط {kind.value} على {target}: القرار {evidence.decision}"
            )
        return evidence

    # ── الأثر ────────────────────────────────────────────────────────────
    def record(
        self,
        kind: ActivityKind,
        target: str,
        evidence: AuthorityEvidence,
        fidelity: ExecutionFidelity,
        payload: dict[str, Any],
        *,
        task_id: str | None = None,
    ) -> SubsystemActivity:
        """قيد تدقيق ثم حدث دائم — بهذا الترتيب، وبلا أي مساس بحالة المهمّة."""
        activity_id = f"act-{uuid.uuid4()}"
        entry = self._audit.append(
            f"executive.subsystem.{kind.value}",
            AUDIT_ACTOR,
            {
                "activity_id": activity_id,
                "kind": kind.value,
                "target": target,
                "task_id": task_id,
                "execution_fidelity": fidelity.value,
                "authority": evidence.as_dict(),
                "payload": payload,
                "execution_effect": False,
            },
        )
        event = self._bus.publish(
            SUBSYSTEM_SUBJECT,
            {
                "activity_id": activity_id,
                "activity_kind": kind.value,
                "target": target,
                "task_id": task_id,
                "fidelity": fidelity.value,
                "authority_decision": evidence.decision,
                "authority_layer": evidence.authority_layer,
                "audit_id": entry["audit_id"],
                "execution_effect": False,
                "payload": payload,
            },
            correlation_id=task_id or activity_id,
        )
        return SubsystemActivity(
            activity_id=activity_id,
            kind=kind.value,
            task_id=task_id,
            fidelity=fidelity.value,
            authority=evidence.as_dict(),
            audit_id=entry["audit_id"],
            audit_hash=entry["hash"],
            event_id=event["event_id"],
        )

    # ── الطريق المختصر: إذن ثم أثر ────────────────────────────────────────
    def authorized_activity(
        self,
        kind: ActivityKind,
        target: str,
        fidelity: ExecutionFidelity,
        payload: dict[str, Any],
        *,
        task_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> SubsystemActivity:
        """الاستخدام الشائع: تحقّق من النسب، ثم استأذن، ثم قيّد الأثر."""
        provenance: dict[str, Any] | None = None
        if task_id is not None:
            provenance = self.task_provenance(task_id)
        full_context = dict(context or {})
        if provenance is not None:
            full_context["task_state"] = provenance["state"]
            full_context["task_type"] = provenance["type"]
        evidence = self.authorize(kind, target, full_context)
        return self.record(kind, target, evidence, fidelity, payload, task_id=task_id)


_boundary: SubsystemBoundary | None = None


def get_subsystem_boundary() -> SubsystemBoundary:
    """حدّ واحد للعملية — يُبنى عند أول طلب."""
    global _boundary
    if _boundary is None:
        _boundary = SubsystemBoundary()
    return _boundary


def reset_subsystem_boundary() -> None:
    """إسقاط الحدّ المحفوظ — تستخدمه الاختبارات بعد تغيير قاعدة البيانات."""
    global _boundary
    _boundary = None
