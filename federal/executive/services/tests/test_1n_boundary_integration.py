"""الهدف: إثباتُ أنَّ النواةَ التنفيذيّةَ الفدراليّةَ صارت تنفُذ عبر حدِّ 1M فعلًا

النطاق: amos_federation.services.executive_core (الجسر + المحرّك) وحدَه
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-18
تاريخ آخر تعديل: 2026-08-18

المُنادي الإنتاجيُّ الوحيدُ الذي كان يتجاوزُ حدَّ التنفيذِ هو
`ConstitutionalAuthorizer.guard` في الجسرِ السياديّ، ومَن يناديه: `submit`
و`_guarded_transition` في المحرّك. وهذا الملفُّ يقيسُ ستَّ دعاوى بعدَ الهجرة:

1. المُنادي المُهجَّر ينفُذ عبرَ الحدّ (مراحلُ 1M الإلزاميّةُ مُسجَّلةٌ فعلًا).
2. المسارُ القديمُ `guard` مُغلَقٌ ولا يُنتِجُ أثرًا.
3. التنفيذُ المُصرَّحُ به ما زالَ ينجحُ بدلالاتِه العامّةِ نفسِها.
4. غيرُ المُصرَّحِ به ما زالَ يفشلُ مُغلَقًا بالاستثناءِ نفسِه.
5. الأثرُ لا يُطبَّقُ مرّتينِ لمفتاحٍ واحد (ذرّيّةُ 1H صارت في الإنتاج).
6. الحالةُ لا تتغيّرُ حينَ يُرفَض — القياسُ على قاعدةِ البياناتِ لا على الاستثناء.

ولا يُعادُ اختبارُ 1F–1M هنا، ولا دورةُ حياةِ المهمّةِ كاملةً: لها ملفُّها.
الأسماءُ لاتينيّةٌ هنا التزامًا بقاعدةِ التسميةِ (`N`) المُفعَّلةِ في هذه الحزمة،
والشرحُ عربيٌّ كما تقتضي قاعدةُ التوثيق.
"""

from pathlib import Path
from typing import Any

import pytest

from amos_federation.common.database import get_session_factory, init_db
from amos_federation.services.executive_core import (
    ExecutionRefusedError,
    ExecutiveCore,
    ExecutiveTaskRepository,
    IllegalTransitionError,
    TaskState,
    reset_executive_core,
)
from amos_federation.services.executive_core.sovereignty_bridge import (
    ConstitutionalAuthorizer,
    GuardedResult,
    UndeclaredExecutionError,
    compensator,
    declared_effect,
    operation_key,
)
from tests.conftest import purge_agents, purge_tasks


@pytest.fixture(autouse=True)
def _fresh_db() -> None:
    """قاعدةُ الاختبارِ نظيفةٌ قبلَ كلِّ اختبار — وإلّا اعتمدَ القياسُ على الترتيب."""
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
def authorizer(tmp_path: Path) -> ConstitutionalAuthorizer:
    """مُصرِّحٌ بسجلِّ ذرّيّةٍ معزولٍ على القرص — لا في الذاكرة."""
    return ConstitutionalAuthorizer(
        idempotency_ledger_path=tmp_path / "IDEMPOTENCY.json"
    )


@pytest.fixture
def core(tmp_path: Path) -> ExecutiveCore:
    return ExecutiveCore(
        authorizer=ConstitutionalAuthorizer(
            idempotency_ledger_path=tmp_path / "ENGINE-IDEMPOTENCY.json"
        )
    )


@pytest.fixture
def repo() -> ExecutiveTaskRepository:
    return ExecutiveTaskRepository()


# ═══════════════════════════════════════════════════════════════════════════
# 1 — المُنادي المُهجَّر ينفُذ عبرَ الحدّ
# ═══════════════════════════════════════════════════════════════════════════


class TestBridgePassesThroughBoundary:
    """الجسرُ السياديُّ صارَ يمرُّ بحدِّ 1M لا بجانبِه."""

    def test_guard_declared_passes_all_mandatory_stages(
        self, authorizer: ConstitutionalAuthorizer
    ) -> None:
        """المراحلُ تُقرأُ من الحصيلةِ نفسِها: ما مرَّ فعلًا لا ما كان مُخطَّطًا."""
        from core.sovereignty.enforcement_boundary import MANDATORY_INTERNAL_STAGES

        state: dict[str, str] = {"record/a": "ORIGINAL"}
        effect = declared_effect("WRITE", "record/a", "قياسُ الوصل")
        result: GuardedResult = authorizer.guard_declared(
            "execute_task",
            "record/a",
            declared_effects=(effect,),
            applier=lambda _e: state.update({"record/a": "MUTATED"}) or "نجاح",
            operation_key=operation_key("test.1n", "full-pass"),
            compensators=(
                compensator(
                    effect.signature, lambda: state.update({"record/a": "ORIGINAL"})
                ),
            ),
        )
        assert result.value == "نجاح", "قيمةُ المُنادي لم تُحفَظ عبرَ الحدّ."
        assert state["record/a"] == "MUTATED", "الأثرُ المُصرَّحُ به لم يقع."
        assert result.outcome is not None, "لا حصيلةَ حدٍّ — فلم يمرَّ بالحدّ."
        assert set(MANDATORY_INTERNAL_STAGES) <= set(result.outcome.stages), (
            "مرحلةٌ إلزاميّةٌ لم تُمَرّ: "
            f"{set(MANDATORY_INTERNAL_STAGES) - set(result.outcome.stages)}"
        )
        assert result.evidence.decision == "ALLOW"

    def test_replay_does_not_apply_effect_twice(
        self, authorizer: ConstitutionalAuthorizer
    ) -> None:
        """ذرّيّةُ 1H دخلت الإنتاجَ في 1N — والقياسُ على عددِ التطبيقات."""
        applied: list[str] = []
        effect = declared_effect("WRITE", "record/b")
        kwargs: dict[str, Any] = {
            "declared_effects": (effect,),
            "applier": lambda _e: applied.append("once"),
            "operation_key": operation_key("test.1n", "only-once"),
            "compensators": (compensator(effect.signature, applied.clear),),
        }
        first = authorizer.guard_declared("execute_task", "record/b", **kwargs)
        second = authorizer.guard_declared("execute_task", "record/b", **kwargs)
        assert not first.is_replay and second.is_replay
        assert applied == ["once"], "طُبِّقَ الأثرُ مرّتينِ لمفتاحٍ واحد."

    def test_boundary_is_built_once_not_per_call(
        self, authorizer: ConstitutionalAuthorizer
    ) -> None:
        """حدٌّ واحدٌ لا حدَّانِ يفترقان — والقياسُ على هويّةِ الكائن."""
        first = authorizer.boundary
        assert authorizer.boundary is first, "بُنيَ حدٌّ ثانٍ لكلِّ نداء."


# ═══════════════════════════════════════════════════════════════════════════
# 2 — المسارُ القديمُ مُغلَق
# ═══════════════════════════════════════════════════════════════════════════


class TestLegacyPathIsClosed:
    """`guard` بقيَ بتوقيعِه، وصارَ يُغلِقُ لا يُنفِّذ."""

    def test_guard_refuses_and_never_calls_executor(
        self, authorizer: ConstitutionalAuthorizer
    ) -> None:
        called: list[str] = []
        with pytest.raises(UndeclaredExecutionError):
            authorizer.guard(
                "execute_task",
                "record/c",
                lambda: called.append("executed") or "bypass",
            )
        assert called == [], "استُدعي المُنفِّذُ المُبهَمُ رغمَ إغلاقِ المسار."

    def test_engine_does_not_call_the_closed_path(self) -> None:
        """قياسٌ على المصدرِ: بابٌ جانبيٌّ جديدٌ يجبُ أن يُفشِلَ الاختبار."""
        from amos_federation.services.executive_core import engine as engine_module

        source = Path(engine_module.__file__).read_text(encoding="utf-8")
        assert "_authorizer.guard(" not in source, (
            "المحرّكُ عادَ ينادي المسارَ المُغلَق."
        )
        assert "_authorizer.guard_declared(" in source, "المحرّكُ لا يمرُّ بالحدّ."


# ═══════════════════════════════════════════════════════════════════════════
# 3 + 4 + 6 — دلالاتُ النجاحِ والفشلِ محفوظةٌ والحالةُ لا تتغيّرُ عندَ الرفض
# ═══════════════════════════════════════════════════════════════════════════


class TestEngineSemanticsPreserved:
    """ما كان ينجحُ ينجح، وما كان يُمنَعُ يُمنَع — والقياسُ على قاعدةِ البيانات."""

    def test_submit_succeeds_and_really_creates_a_task(
        self, core: ExecutiveCore, repo: ExecutiveTaskRepository
    ) -> None:
        task = core.submit("analysis", "مهمّةُ قياسٍ للهجرة")
        assert task["id"], "لم تُرجَع هويّةُ المهمّة."
        assert repo.state_of(task["id"]) is TaskState.CREATED, (
            "لم تُكتَب المهمّةُ في قاعدةِ البياناتِ بحالتِها الأولى."
        )

    def test_legal_transition_really_changes_state(
        self, core: ExecutiveCore, repo: ExecutiveTaskRepository
    ) -> None:
        task = core.submit("analysis", "انتقالٌ مشروع")
        core.advance(task["id"])
        assert repo.state_of(task["id"]) is not TaskState.CREATED, (
            "لم يتقدّم الانتقالُ المشروعُ عبرَ الحدّ."
        )

    def test_illegal_transition_keeps_its_own_error_and_state(
        self, core: ExecutiveCore, repo: ExecutiveTaskRepository
    ) -> None:
        """`IllegalTransitionError` لا يُلَفُّ في خطأِ ذرّيّةٍ — الدلالةُ محفوظة."""
        task = core.submit("analysis", "انتقالٌ غيرُ مشروع")
        before = repo.state_of(task["id"])
        with pytest.raises(IllegalTransitionError):
            core._guarded_transition(
                task["id"], before, TaskState.COMPLETED, "task.illegal"
            )
        assert repo.state_of(task["id"]) == before, (
            "تغيّرت الحالةُ بانتقالٍ غيرِ مشروع."
        )

    def test_cancel_succeeds_then_repeat_is_refused_without_state_change(
        self, core: ExecutiveCore, repo: ExecutiveTaskRepository
    ) -> None:
        """الإلغاءُ مسارٌ عامٌّ يمرُّ بالحدّ؛ وتكرارُه ليس نجاحًا ثانيًا."""
        task = core.submit("analysis", "إلغاءٌ ثمَّ تكرار")
        core.cancel(task["id"], "قياسُ الهجرة")
        assert repo.state_of(task["id"]) is TaskState.CANCELLED
        with pytest.raises((ExecutionRefusedError, IllegalTransitionError)):
            core.cancel(task["id"], "قياسُ الهجرة")
        assert repo.state_of(task["id"]) is TaskState.CANCELLED, (
            "تغيّرت الحالةُ بإلغاءٍ مُكرَّر."
        )


# ═══════════════════════════════════════════════════════════════════════════
# 5 — المعوّضُ مربوطٌ بعكسٍ حقيقيّ
# ═══════════════════════════════════════════════════════════════════════════


class TestCompensationHasRealInverse:
    """1I يشترطُ عكسًا فعليًّا — و`delete` أُضيفت في 1N لتكونَ عكسَ `create`."""

    def test_repository_delete_is_the_real_inverse_of_create(
        self, repo: ExecutiveTaskRepository
    ) -> None:
        assert hasattr(repo, "delete"), "لا عكسَ لإنشاءِ المهمّة — فالمعوّضُ ادّعاء."
        task_id = "task-erased-1n"
        repo.create(task_id, "analysis", "مهمّةٌ تُمحى")
        assert repo.get(task_id) is not None, "لم يُنشَأ الصفُّ أصلًا."
        assert repo.delete(task_id) is True
        assert repo.get(task_id) is None, "لم يُمحَ الصفُّ فعلًا."
        assert repo.delete(task_id) is False, "المحوُ الثاني ادّعى نجاحًا."
