"""الهدف: مستودع المهام للنواة التنفيذية — انتقال حالة ذرّي على مصدر الحقيقة.

النطاق: federal/executive/services — النواة التنفيذية
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-16
تاريخ آخر تعديل: 2026-08-18

`PersistentTaskStore.update_status` القائم يكتب الحالة الجديدة بلا شرط: يقرأ
الصفّ ثم يكتب. وذلك كافٍ لواجهة إدارية، وغير كافٍ لمحرّك تنفيذ: مُنفِّذان
يقرآن `dispatched` في اللحظة نفسها فيكتبان `executing` كلاهما، وتُنفَّذ المهمّة
مرتين — وهذا هو بالضبط ما يجعل «التنفيذ مرة واحدة» ادّعاءً لا خاصيّة.

فهذا المستودع يضيف ما تحتاجه النواة ولا يملكه المخزن العام:

1. `compare_and_set` — تحديث مشروط بـ`WHERE status = expected`، ويُرجع عدد
   الصفوف المتأثّرة. صفر يعني «سبقك غيرك»، لا يعني «نجح».
2. `claim_next` — التقاط مهمّة غير منتهية للتقدّم بها.
3. `list_unfinished` — أساس الاسترداد بعد إعادة التشغيل.
4. `delete` — معكوسُ `create` (أضافته 1N). ليس مرفقًا إداريًّا: خطّةُ التعويض
   (1I) لا تُربَط بأثرِ إنشاءٍ لا يملكُ معكوسًا، والدولةُ لا تدخلُ فعلًا لا تعرفُ
   كيف تخرجُ منه. فبلا هذه الدالّة كان إعلانُ `CREATE` سيُرفَض قبلَ التنفيذ.

ولا يُنشئ نموذجًا ثانيًا لجدول `tasks`: يستخدم `TaskModel` نفسه، احترامًا لقرار
الهجرة 004 (نموذج واحد مرجعي لهذا الجدول).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, update

from amos_federation.common.database import TaskModel, get_session_factory
from amos_federation.services.executive_core.states import (
    TaskState,
    assert_transition,
    parse_state,
)


class TaskNotFoundError(LookupError):
    """لا صفّ لهذه المهمّة في مصدر الحقيقة."""


def _row_as_dict(row: TaskModel) -> dict[str, Any]:
    return {
        "id": row.id,
        "type": row.type,
        "description": row.description,
        "status": row.status,
        "priority": row.priority,
        "domain": row.domain,
        "assigned_agent": row.assigned_agent,
        "plan": row.plan or [],
        "result": row.result or {},
        "tenant_id": row.tenant_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


class ExecutiveTaskRepository:
    """قراءة وكتابة المهام لأجل النواة التنفيذية — على القاعدة لا على الذاكرة."""

    def create(
        self,
        task_id: str,
        task_type: str,
        description: str,
        *,
        priority: str = "normal",
        domain: str = "general",
        tenant_id: str = "default",
        state: TaskState = TaskState.CREATED,
    ) -> dict[str, Any]:
        """إدراج مهمّة جديدة في القاعدة وإرجاع صفّها كما خُزِّن."""
        session = get_session_factory()()
        try:
            session.add(
                TaskModel(
                    id=task_id,
                    type=task_type,
                    description=description,
                    status=state.value,
                    priority=priority,
                    domain=domain,
                    tenant_id=tenant_id,
                    plan=[],
                    result={},
                )
            )
            session.commit()
        finally:
            session.close()
        return self.require(task_id)

    def get(self, task_id: str) -> dict[str, Any] | None:
        session = get_session_factory()()
        try:
            row = session.query(TaskModel).filter(TaskModel.id == task_id).first()
            return None if row is None else _row_as_dict(row)
        finally:
            session.close()

    def require(self, task_id: str) -> dict[str, Any]:
        """قراءة مهمّة أو رفع `TaskNotFoundError` — لا إرجاع صفّ فارغ يُقرأ كأنه مهمّة."""
        task = self.get(task_id)
        if task is None:
            raise TaskNotFoundError(f"لا مهمّة بالمعرّف: {task_id}")
        return task

    def state_of(self, task_id: str) -> TaskState:
        return parse_state(self.require(task_id)["status"])

    def compare_and_set(
        self,
        task_id: str,
        expected: TaskState,
        target: TaskState,
        **fields: Any,
    ) -> bool:
        """انتقال حالة ذرّي: ينجح مرّة واحدة فقط لكل حالة متوقَّعة.

        يتحقّق من مشروعية الانتقال أولًا (آلة الحالات)، ثم ينفّذ `UPDATE` مشروطًا
        بالحالة المتوقَّعة. الإرجاع `False` معناه أن أحدًا غيّر الحالة قبلنا —
        وليس معناه فشل الكتابة.
        """
        assert_transition(expected, target)
        values: dict[str, Any] = {
            "status": target.value,
            "updated_at": datetime.now(UTC),
        }
        values.update(fields)
        session = get_session_factory()()
        try:
            result = session.execute(
                update(TaskModel)
                .where(TaskModel.id == task_id, TaskModel.status == expected.value)
                .values(**values)
            )
            session.commit()
            return bool(result.rowcount)
        finally:
            session.close()

    def delete(self, task_id: str) -> bool:
        """امحُ صفَّ مهمّةٍ — معكوسُ `create` وحدَه، لا أداةَ تنظيفٍ عامّة.

        يُستدعى من معوّضِ 1I عندَ فشلِ عمليّةٍ أعلنت أثرَ `CREATE`. الإرجاع
        `False` معناه لا صفَّ لِيُمحى (سبقَنا غيرُنا أو لم يُنشَأ قطُّ) — لا
        يعني فشلًا يُبتلَع، والمُنادي يقرؤه.
        """
        session = get_session_factory()()
        try:
            result = session.execute(delete(TaskModel).where(TaskModel.id == task_id))
            session.commit()
            return bool(result.rowcount)
        finally:
            session.close()

    def list_unfinished(self, limit: int = 100) -> list[dict[str, Any]]:
        """المهام في حالة غير نهائية — أساس الاسترداد بعد إعادة التشغيل."""
        active = [
            TaskState.CREATED.value,
            TaskState.AUTHORIZED.value,
            TaskState.PLANNED.value,
            TaskState.DISPATCHED.value,
            TaskState.EXECUTING.value,
        ]
        session = get_session_factory()()
        try:
            rows = (
                session.query(TaskModel)
                .filter(TaskModel.status.in_(active))
                .order_by(TaskModel.created_at.asc())
                .limit(limit)
                .all()
            )
            return [_row_as_dict(row) for row in rows]
        finally:
            session.close()

    def list_by_state(self, state: TaskState, limit: int = 100) -> list[dict[str, Any]]:
        session = get_session_factory()()
        try:
            rows = (
                session.query(TaskModel).filter(TaskModel.status == state.value).limit(limit).all()
            )
            return [_row_as_dict(row) for row in rows]
        finally:
            session.close()
