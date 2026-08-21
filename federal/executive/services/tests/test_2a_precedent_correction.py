"""
AMOS-Federation Tests — 2A Precedent Correction Guard (W-019)
الهدف: إثباتُ نقضِ سابقةِ 2A قياسًا: فعلٌ غيرُ دستوريٍّ · فاعلٌ صادقٌ · حدٌّ لم يُنقَص
النطاق: federal/executive/services/tests
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-22 (W-019 — أثرُ القرارِ Q-17 · الخيارِ 2)

## ما نُقِضَ ولماذا

قرارُ **Q-17** (الخيارُ 2) قضى أنَّ `amos-credit` **وحدةُ قياسٍ تشغيليّةٌ لا مالٌ
دستوريّ**، وأَلزَمَ نصًّا بـ**تصحيحِ سابقةِ 2A** لأنَّها طبَّقَت الفعلَ الدستوريَّ
الحصريَّ `allocate_budget` على عمودٍ مقوَّمٍ بتلك الوحدةِ (`federal_states.budget`)،
ووسَمَت كائنَ التشغيلِ كلَّه بفاعلِ خزانةٍ (`TREASURY_ACTOR`) — وهو ما منعَه **Q-19**
نصًّا. وكانَ التصحيحُ **رابعَ** الترتيبِ المُلزِمِ في Q-5 بعدَ Q-20 وQ-18 وQ-19،
وقد استقرَّ المعجمُ والفاعلُ فحلَّ أجلُه.

## ثلاثُ دعاوى تُقاسُ هنا — لا تُوصَف

- **N-1 · الفعلُ صارَ صادقًا:** الفعلُ الذي تُمارِسُه العمليّةُ ليس في معجمِ المالِ
  الدستوريِّ، وهو مُثبَتٌ صريحًا في المُستثنى بقرارِ Q-17.
- **N-2 · الفاعلُ صارَ صادقًا:** لا وسمَ خزانةٍ في المصدرِ ولا في الكائنِ المبنيّ،
  والفاعلُ الفعليُّ الذي يُقدَّمُ إلى البوابةِ هو الفرعُ التنفيذيّ.
- **N-3 · الحرسُ لم يُنقَص:** الفعلُ الحصريُّ `allocate_budget` ما زالَ مرفوضًا على
  الفاعلِ التنفيذيِّ في البوابةِ نفسِها (R-003-1 قائم)، والتوزيعُ ما زالَ يمرُّ
  بالمراحلِ الإلزاميّةِ كلِّها ويُغيِّرُ حالةً حقيقيّةً في القاعدة.

والقياسُ على الواقعِ لا على الوصف: تُستدعى العمليّةُ الإنتاجيّةُ نفسُها، ويُقرأُ
`BoundaryOutcome` منها، وتُقرأُ الميزانيةُ من القاعدةِ لا من القيمةِ المُرجَعة.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from amos_federation.common.database import get_database_url, init_db
from amos_federation.services.executive_core.sovereignty_bridge import (
    ConstitutionalAuthorizer,
    GuardedResult,
    compensator,
    declared_effect,
    operation_key,
)
from amos_federation.services.governance import state_runtime as runtime_module
from amos_federation.services.governance.state_runtime import StateModel, StateRuntime

RUNTIME_SRC = Path(runtime_module.__file__)


class _Recording(ConstitutionalAuthorizer):
    """المُصرِّحُ نفسُه، يُسجِّلُ حصائلَ الحدِّ ليُقاسَ ما مرَّ فعلًا — لا مسارٌ ثانٍ."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.results: list[GuardedResult] = []

    def guard_declared(self, *args: Any, **kwargs: Any) -> GuardedResult:
        result = super().guard_declared(*args, **kwargs)
        self.results.append(result)
        return result


@pytest.fixture(autouse=True)
def _fresh_db() -> None:
    init_db()


@pytest.fixture
def runtime(tmp_path: Path) -> tuple[StateRuntime, _Recording]:
    authorizer = _Recording(idempotency_ledger_path=tmp_path / "W019-IDEM.json")
    return StateRuntime(authorizer=authorizer), authorizer


def _budget_of(rt: StateRuntime, state_id: str) -> int:
    session = rt._Session()  # noqa: SLF001 — القياسُ على القاعدةِ لا على المُرجَع
    try:
        state = session.query(StateModel).filter(StateModel.state_id == state_id).first()
        return int(state.budget or "0") if state else -1
    finally:
        session.close()


def _lexicons() -> tuple[frozenset[str], frozenset[str]]:
    """معجمُ المالِ والمُستثنى منه — من النواةِ نفسِها لا من نسخةٍ في الاختبار."""
    ConstitutionalAuthorizer._ensure_core_importable()  # noqa: SLF001
    from core.constitutional_engine.rules import (
        NON_CONSTITUTIONAL_MONEY_ACTIONS,
        TREASURY_ACTIONS,
    )

    return frozenset(TREASURY_ACTIONS), frozenset(NON_CONSTITUTIONAL_MONEY_ACTIONS)


# ═══════════════════════════════════════════════════════════════════════════
# N-1 — الفعلُ صارَ صادقًا: غيرُ دستوريٍّ ومُثبَتٌ في المُستثنى
# ═══════════════════════════════════════════════════════════════════════════


class TestN1ActionIsTruthful:
    def test_operation_action_is_outside_the_constitutional_money_lexicon(self) -> None:
        """الفعلُ المُمارَسُ ليس حصرًا للخزانةِ — وإلّا عادَ التناقضُ الذي نُقِضَ."""
        treasury_actions, excluded = _lexicons()
        action = runtime_module.ACTION_ALLOCATE_OPERATIONAL_CREDIT
        assert action not in treasury_actions, (
            f"فعلُ العمليّةِ «{action}» في معجمِ المالِ الدستوريِّ — والعمودُ "
            f"مقوَّمٌ بـ«{runtime_module.BUDGET_UNIT}» وهي ليست مالًا دستوريًّا (Q-17)."
        )
        assert action in excluded, (
            "الفعلُ غيرُ مُثبَتٍ في المُستثنى — والاستثناءُ المسكوتُ عنه يُقرأُ " "غدًا سهوًا لا قرارًا."
        )

    def test_the_exclusive_action_name_is_gone_from_the_source(self) -> None:
        """لا `allocate_budget` فعلًا مُمارَسًا في المصدر — بقاؤه ذكرًا في التوثيقِ مقصود."""
        source = RUNTIME_SRC.read_text(encoding="utf-8")
        assert not re.search(r"^ACTION_ALLOCATE_BUDGET\s*=", source, re.MULTILINE)
        assert "guard_declared(\n            ACTION_ALLOCATE_OPERATIONAL_CREDIT," in source

    def test_the_measured_unit_is_declared_not_inferred(self) -> None:
        """وحدةُ العمودِ مُعلَنةٌ في الوحدةِ وفي المخطَّطِ معًا — فلا تُقرأُ مالًا عامًّا."""
        assert runtime_module.BUDGET_UNIT == "amos-credit"
        source = RUNTIME_SRC.read_text(encoding="utf-8")
        assert re.search(
            r"budget\s*=\s*Column\(String[^\n]*# amos-credit", source
        ), "المخطَّطُ لم يعلنْ وحدةَ العمود — فالإعلانُ في الوحدةِ وحدَه يُنقَضُ بأوّلِ تعديل."


# ═══════════════════════════════════════════════════════════════════════════
# N-2 — الفاعلُ صارَ صادقًا: لا وسمَ خزانةٍ بالجملة
# ═══════════════════════════════════════════════════════════════════════════


class TestN2ActorIsTruthful:
    def test_source_carries_no_wholesale_treasury_tag(self) -> None:
        """نصُّ ما منعَه Q-19: لا ثابتَ فاعلٍ ولا بناءَ مُصرِّحٍ بفاعلِ خزانة."""
        source = RUNTIME_SRC.read_text(encoding="utf-8")
        assert not re.search(r"^TREASURY_ACTOR\s*=", source, re.MULTILINE)
        assert not re.search(r"actor\s*=\s*[\"']TREASURY[\"']", source)
        assert "ConstitutionalAuthorizer(actor=" not in source

    def test_built_authorizer_presents_the_executive_branch(self) -> None:
        """الكائنُ المبنيُّ افتراضًا يُقدِّمُ فاعلًا تنفيذيًّا — قياسٌ على الكائنِ لا على النصّ."""
        rt = StateRuntime()
        assert rt.authorizer._actor == ConstitutionalAuthorizer.DEFAULT_ACTOR  # noqa: SLF001
        assert rt.authorizer._actor == "EXECUTIVE"  # noqa: SLF001

    def test_audit_actor_is_the_runtime_not_the_treasury(
        self, runtime: tuple[StateRuntime, _Recording]
    ) -> None:
        """من كتبَ في التدقيقِ هو زمنُ تشغيلِ الولاياتِ — لا خزانةٌ لم تفعلْ شيئًا."""
        rt, _ = runtime
        rt.allocate_budget("health", "70", "قياسُ فاعلِ التدقيق", allocation_id="w019-audit")
        from amos_federation.common.persistent import PersistentAuditStore

        entries = [
            entry
            for entry in PersistentAuditStore().list_all(limit=50)
            if entry.get("action") == "state.budget_allocated"
        ]
        assert entries, "لا قيدَ تدقيقٍ للتوزيع — فالأثرُ غيرُ مشهود."
        latest = entries[0]
        assert latest.get("actor") == "state_runtime"
        assert latest.get("details", {}).get("unit") == runtime_module.BUDGET_UNIT


# ═══════════════════════════════════════════════════════════════════════════
# N-3 — الحرسُ لم يُنقَص: الجدارُ قائمٌ والحدُّ يعملُ
# ═══════════════════════════════════════════════════════════════════════════


class TestN3GuardNotWeakened:
    def test_exclusive_money_action_is_still_denied_to_the_executive(self, tmp_path: Path) -> None:
        """R-003-1 لم يُمَسّ: `allocate_budget` ما زالَ مرفوضًا على الفاعلِ التنفيذيّ.

        هذا هو الفرقُ بينَ نقضِ سابقةٍ وإسقاطِ حرس: زالَ **الوسمُ الكاذبُ** ولم
        يزُلِ الجدارُ. ولو أُبيحَ الفعلُ الحصريُّ للتنفيذيِّ لكانَ النقضُ ثُغرةً.
        """
        authorizer = ConstitutionalAuthorizer(
            actor="EXECUTIVE", idempotency_ledger_path=tmp_path / "W019-DENIED.json"
        )
        authorizer.crown_status()  # يُتاحُ `core` بعدَ أوّلِ مسٍّ للبوابةِ نفسِها
        from core.sovereignty.gateway import SovereigntyViolation

        target = "federal_states/science"
        effect = declared_effect("WRITE", f"{target}/budget", "فعلٌ حصريٌّ بفاعلٍ غيرِ مختصّ")
        touched: list[str] = []
        with pytest.raises(SovereigntyViolation, match="R-003-1"):
            authorizer.guard_declared(
                "allocate_budget",
                target,
                declared_effects=(effect,),
                applier=lambda _e: touched.append("applied"),
                operation_key=operation_key(runtime_module.BUDGET_OPERATION_SCOPE, "w019-denied"),
                compensators=(
                    compensator(
                        effect.signature,
                        lambda: None,
                        "لا عكسَ مطلوبًا: الرفضُ قبلَ التطبيقِ فلا أثرَ يُعكَس",
                    ),
                ),
            )
        assert not touched, "الفعلُ الحصريُّ مرَّ إلى التطبيقِ — الجدارُ سقط."

    def test_allocation_still_passes_every_mandatory_stage_and_changes_state(
        self, runtime: tuple[StateRuntime, _Recording]
    ) -> None:
        """التوزيعُ بعدَ النقضِ يمرُّ بالمراحلِ الإلزاميّةِ كلِّها ويُغيِّرُ القاعدةَ فعلًا."""
        from core.sovereignty.enforcement_boundary import MANDATORY_INTERNAL_STAGES

        rt, authorizer = runtime
        before = _budget_of(rt, "science")
        result = rt.allocate_budget("science", "250", "قياسُ الحدِّ بعدَ النقض", allocation_id="w019")
        assert result["allocated"] == 250
        assert _budget_of(rt, "science") == before + 250, "لا أثرَ في القاعدة."
        assert authorizer.results, "لم يمرَّ نداءٌ بالحدِّ السياديّ."
        outcome = authorizer.results[-1].outcome
        missing = set(MANDATORY_INTERNAL_STAGES) - set(outcome.stages)
        assert not missing, f"مرحلةٌ إلزاميّةٌ لم تُمَرّ: {missing}"
        assert authorizer.results[-1].evidence.decision == "ALLOW"

    def test_replay_and_compensation_contract_survives_the_correction(
        self, runtime: tuple[StateRuntime, _Recording]
    ) -> None:
        """المفتاحُ ما زالَ يمنعُ أثرًا ثانيًا، والمعوّضُ ما زالَ مُعلَنًا للأثرِ نفسِه."""
        rt, authorizer = runtime
        first = rt.allocate_budget("culture", "40", "أوّلُ توزيع", allocation_id="w019-key")
        after_first = _budget_of(rt, "culture")
        second = rt.allocate_budget("culture", "40", "أوّلُ توزيع", allocation_id="w019-key")
        assert first["replayed"] is False
        assert second["replayed"] is True
        assert second["allocated"] == 0
        assert _budget_of(rt, "culture") == after_first, "الإعادةُ أوقعت أثرًا ثانيًا."
        outcome = authorizer.results[0].outcome
        assert outcome.compensation_plan is not None, "لا معوّضَ مُعلَنٌ للأثر — والحدُّ بلا معوّضٍ نصفُ حدّ."

    def test_the_closed_legacy_path_is_still_closed(
        self, runtime: tuple[StateRuntime, _Recording]
    ) -> None:
        """المسارُ المُغلَقُ منذ 2A يبقى مُغلَقًا بعدَ نقضِ السابقة — النقضُ للفعلِ لا للحدّ."""
        from amos_federation.services.executive_core.sovereignty_bridge import (
            UndeclaredExecutionError,
        )

        rt, _ = runtime
        before = _budget_of(rt, "science")
        with pytest.raises(UndeclaredExecutionError):
            rt._allocate_budget_unguarded("science", "900")  # noqa: SLF001
        assert _budget_of(rt, "science") == before


# ═══════════════════════════════════════════════════════════════════════════
# حدُّ هذا الملفّ — يُعلَنُ ولا يُدَّعى ما لم يُقَس
# ═══════════════════════════════════════════════════════════════════════════


def test_database_under_measurement_is_declared() -> None:
    """يُعلَنُ أنَّ القياسَ على القاعدةِ المُهيَّأةِ للاختبار — لا دعوى على PostgreSQL هنا.

    N-2 من مذكّرةِ Q-5 قاسَ أنَّ `federal_states` **لا وجودَ له** في القاعدةِ
    المُهيَّأة، فإثباتُ هذا الملفِّ على المحرّكِ الذي يُشغَّلُ به لا على غيرِه.
    ومَن أرادَ الإثباتَ على PostgreSQL فليُشغِّلْه بمحرّكِها ولا يستنبطْه من هنا.
    """
    assert get_database_url(), "لا محرّكَ مُعلَنًا — فالقياسُ بلا موضع."
