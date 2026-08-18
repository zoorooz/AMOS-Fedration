"""الهدف: إثباتُ هجرةِ الكتاباتِ الثلاثِ العامّةِ في `governance/factories.py` (P13)

النطاق: `Factory.start_production` · `Factory.complete_step` ·
`FactoryRegistry.assign_manager`
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-18

هذا الملفُّ لا يُعيدُ اختبارَ 1F–1N ولا يقيسُ تصميمًا. يقيسُ عشرَ دعاوى على الكتاباتِ
نفسِها، والقياسُ على الأثرِ في قاعدةِ البياناتِ وعلى مراحلِ الحصيلةِ لا على وجودِ استثناء:

- F-1  المساراتُ القديمةُ الثلاثةُ مُقفَلةٌ ولا تُنتِجُ أثرًا.
- F-2  الإنتاجُ الجديدُ يُنشئُ صفًّا حقيقيًّا ويمرُّ بالمراحلِ الإلزاميّةِ كلِّها.
- F-3  الأثرُ المُعلَنُ يُطابِقُ الهدفَ نوعًا ومَوردًا.
- F-4  إكمالُ الخطوةِ يُغيِّرُ حالةً حقيقيّةً عبرَ الحدِّ وحدَه.
- F-5  تعيينُ المديرِ يُغيِّرُ صفَّ المصنعِ عبرَ الحدِّ ويُعيدُ المديرَ السابقَ في نتيجتِه.
- F-6  خطأُ النطاقِ يُرفَعُ صريحًا **قبلَ** الحدِّ ولا يُلَفُّ في خطأِ ذرّيّة.
- F-7  المفتاحُ نفسُه لا يُنتِجُ أثرًا ثانيًا (ذرّيّة).
- F-8  المعوّضاتُ عكسٌ حقيقيٌّ لا رمزيّ — تُشغَّلُ ويُقاسُ رجوعُ الحالة.
- F-9  الفشلُ بعدَ وقوعِ الأثرِ يُغلَقُ عليه ولا يُدَّعى نجاحًا.
- F-10 لا بدائيّةَ سياديّةَ جديدةً ولا معامَلَ تجاوزٍ في الوحدة.
- F-11 خطُّ الأنابيبِ الكاملُ يعملُ عبرَ الحدِّ — قياسٌ لهويّةِ الإذنِ (Q-11).
- F-12 القيدُ الباقي يُقاسُ لا يُخفَى: إعادةُ تعيينِ مديرٍ سابقٍ لا تُعيدُه.
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest

from amos_federation.services.executive_core.sovereignty_bridge import (
    ConstitutionalAuthorizer,
    GuardedResult,
    UndeclaredExecutionError,
)
from amos_federation.services.governance import factories as factories_module
from amos_federation.services.governance.factories import (
    FACTORIES,
    Factory,
    FactoryModel,
    FactoryNotFoundError,
    FactoryProductModel,
    FactoryRegistry,
    ProductNotFoundError,
)

FACTORY_ID = "content"


class RecordingAuthorizer(ConstitutionalAuthorizer):
    """المُصرِّحُ نفسُه، يُسجِّلُ حصائلَ الحدِّ ليُقاسَ ما مرَّ فعلًا — لا بدائيّةٌ ثانية."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.results: list[GuardedResult] = []

    def guard_declared(self, *args: Any, **kwargs: Any) -> GuardedResult:
        result = super().guard_declared(*args, **kwargs)
        self.results.append(result)
        return result


@pytest.fixture
def factory(tmp_path: Path) -> tuple[Factory, RecordingAuthorizer]:
    authorizer = RecordingAuthorizer(
        actor=factories_module.FACTORY_ACTOR,
        idempotency_ledger_path=tmp_path / "FACTORY-IDEM.json",
    )
    return Factory(FACTORY_ID, authorizer=authorizer), authorizer


@pytest.fixture
def registry(tmp_path: Path) -> tuple[FactoryRegistry, RecordingAuthorizer]:
    authorizer = RecordingAuthorizer(
        actor=factories_module.FACTORY_ACTOR,
        idempotency_ledger_path=tmp_path / "MANAGER-IDEM.json",
    )
    Factory(FACTORY_ID)  # يضمنُ وجودَ صفِّ المصنعِ للقياس
    return FactoryRegistry(authorizer=authorizer), authorizer


def _product_row(fac: Factory, product_id: str) -> FactoryProductModel | None:
    session = fac._Session()  # noqa: SLF001 — القياسُ على القاعدةِ لا على القيمةِ المُرجَعة
    try:
        return (
            session.query(FactoryProductModel)
            .filter(FactoryProductModel.product_id == product_id)
            .first()
        )
    finally:
        session.close()


def _manager_of(reg: FactoryRegistry, factory_id: str) -> str | None:
    session = reg._Session()  # noqa: SLF001
    try:
        row = session.query(FactoryModel).filter(FactoryModel.factory_id == factory_id).first()
        return row.manager_agent_id if row else None
    finally:
        session.close()


def _mandatory_stages() -> set[Any]:
    from core.sovereignty.enforcement_boundary import MANDATORY_INTERNAL_STAGES

    return set(MANDATORY_INTERNAL_STAGES)


# ═══════════════════════════════════════════════════════════════════════════
# F-1 — المساراتُ القديمةُ مُقفَلة
# ═══════════════════════════════════════════════════════════════════════════


class TestF1LegacyPathsClosed:
    def test_unguarded_production_refuses_and_writes_nothing(
        self, factory: tuple[Factory, RecordingAuthorizer]
    ) -> None:
        fac, _ = factory
        before = len(fac.list_products(limit=500))
        with pytest.raises(UndeclaredExecutionError):
            fac._start_production_unguarded("عنوانٌ مرفوض")  # noqa: SLF001
        assert len(fac.list_products(limit=500)) == before

    def test_unguarded_step_refuses(self, factory: tuple[Factory, RecordingAuthorizer]) -> None:
        fac, _ = factory
        with pytest.raises(UndeclaredExecutionError):
            fac._complete_step_unguarded("prod-x", "review")  # noqa: SLF001

    def test_unguarded_manager_assignment_refuses_and_changes_nothing(
        self, registry: tuple[FactoryRegistry, RecordingAuthorizer]
    ) -> None:
        reg, _ = registry
        before = _manager_of(reg, FACTORY_ID)
        with pytest.raises(UndeclaredExecutionError):
            reg._assign_manager_unguarded(FACTORY_ID, "agent-rejected")  # noqa: SLF001
        assert _manager_of(reg, FACTORY_ID) == before

    def test_source_has_no_second_write_path(self) -> None:
        """كتابةُ الحالةِ تقعُ في دوالِّ الأثرِ وحدَها لا في نسخةٍ ثانيةٍ للفعل."""
        source = Path(factories_module.__file__).read_text(encoding="utf-8")
        assert source.count("def start_production") == 1
        assert source.count("def assign_manager") == 1
        assert source.count("guard_declared") == 3, "عمليّةٌ عامّةٌ بلا حدٍّ أو حدٌّ زائد."


# ═══════════════════════════════════════════════════════════════════════════
# F-2 · F-3 — أثرٌ حقيقيٌّ ومراحلُ إلزاميّةٌ وأثرٌ مُعلَنٌ مُطابِق
# ═══════════════════════════════════════════════════════════════════════════


class TestF2F3ProductionCrossesBoundary:
    def test_production_writes_row_and_passes_mandatory_stages(
        self, factory: tuple[Factory, RecordingAuthorizer]
    ) -> None:
        fac, authorizer = factory
        result = fac.start_production("مقالٌ سياديّ", "agent-1", operation_ref="ref-f2")
        row = _product_row(fac, result["product_id"])
        assert row is not None, "لا صفَّ في القاعدةِ — الأثرُ مُدَّعًى لا واقع."
        assert row.title == "مقالٌ سياديّ"
        outcome = authorizer.results[-1].outcome
        assert _mandatory_stages().issubset(set(outcome.stages)), "مرحلةٌ إلزاميّةٌ لم تُنفَّذ."

    def test_declared_effect_matches_target(
        self, factory: tuple[Factory, RecordingAuthorizer]
    ) -> None:
        fac, authorizer = factory
        result = fac.start_production("منتجٌ للأثر", "agent-2", operation_ref="ref-f3")
        evidence = result["evidence"]
        assert result["product_id"] in evidence["target"], "الهدفُ لا يُسمّي المَوردَ المُتأثِّر."
        assert evidence["action"] == factories_module.ACTION_START_PRODUCTION


# ═══════════════════════════════════════════════════════════════════════════
# F-4 · F-5 — الخطوةُ والتعيينُ يعبرانِ الحدَّ
# ═══════════════════════════════════════════════════════════════════════════


class TestF4F5StepAndManager:
    def test_step_changes_database_through_boundary(
        self, factory: tuple[Factory, RecordingAuthorizer]
    ) -> None:
        fac, authorizer = factory
        created = fac.start_production("منتجٌ للخطوة", "agent-3", operation_ref="ref-f4")
        pid = created["product_id"]
        fac.complete_step(pid, "review", "مخرجُ مراجعة", quality=90)
        row = _product_row(fac, pid)
        steps = json.loads(row.pipeline_steps or "[]")
        assert [s["step"] for s in steps] == ["review"], "الخطوةُ لم تُكتَبْ في القاعدة."
        assert row.status == "reviewed"
        assert _mandatory_stages().issubset(set(authorizer.results[-1].outcome.stages))

    def test_manager_assignment_writes_row_and_reports_previous(
        self, registry: tuple[FactoryRegistry, RecordingAuthorizer]
    ) -> None:
        reg, authorizer = registry
        previous = _manager_of(reg, FACTORY_ID)
        result = reg.assign_manager(FACTORY_ID, "agent-manager-1")
        assert _manager_of(reg, FACTORY_ID) == "agent-manager-1"
        assert result["previous_manager_agent_id"] == previous
        assert _mandatory_stages().issubset(set(authorizer.results[-1].outcome.stages))


# ═══════════════════════════════════════════════════════════════════════════
# F-6 — خطأُ النطاقِ قبلَ الحدّ
# ═══════════════════════════════════════════════════════════════════════════


class TestF6DomainRulesBeforeBoundary:
    def test_missing_product_raises_domain_error_not_idempotency_error(
        self, factory: tuple[Factory, RecordingAuthorizer]
    ) -> None:
        fac, authorizer = factory
        with pytest.raises(ProductNotFoundError):
            fac.complete_step("prod-ghost", "review")
        assert authorizer.results == [], "عُبِرَ الحدُّ لعمليّةٍ مرفوضةٍ نطاقيًّا."

    def test_missing_factory_raises_domain_error(
        self, registry: tuple[FactoryRegistry, RecordingAuthorizer]
    ) -> None:
        reg, authorizer = registry
        with pytest.raises(FactoryNotFoundError):
            reg.assign_manager("factory-ghost", "agent-x")
        assert authorizer.results == []

    def test_factory_without_pipeline_refuses_production(self, tmp_path: Path) -> None:
        authorizer = RecordingAuthorizer(
            actor=factories_module.FACTORY_ACTOR,
            idempotency_ledger_path=tmp_path / "GHOST-IDEM.json",
        )
        ghost = Factory("factory-without-pipeline", authorizer=authorizer)
        with pytest.raises(FactoryNotFoundError):
            ghost.start_production("لا خطَّ أنابيب")
        assert authorizer.results == []


# ═══════════════════════════════════════════════════════════════════════════
# F-7 — الذرّيّة
# ═══════════════════════════════════════════════════════════════════════════


class TestF7Idempotency:
    def test_same_reference_produces_once(
        self, factory: tuple[Factory, RecordingAuthorizer]
    ) -> None:
        fac, authorizer = factory
        first = fac.start_production("منتجٌ ذرّيّ", "agent-4", operation_ref="ref-f7")
        second = fac.start_production("منتجٌ ذرّيّ", "agent-4", operation_ref="ref-f7")
        assert second["replay"] is True, "أُنتِجَ أثرٌ ثانٍ لمفتاحِ عمليّةٍ واحد."
        assert authorizer.results[-1].is_replay
        rows = [p for p in fac.list_products(limit=500) if p["title"] == "منتجٌ ذرّيّ"]
        assert len(rows) == 1, "صفّانِ لعمليّةٍ واحدة."
        assert first["product_id"] == rows[0]["product_id"]

    def test_same_step_key_writes_once(
        self, factory: tuple[Factory, RecordingAuthorizer]
    ) -> None:
        fac, _ = factory
        created = fac.start_production("منتجٌ لخطوةٍ مُعادة", "agent-5", operation_ref="ref-f7b")
        pid = created["product_id"]
        fac.complete_step(pid, "review", "أوّل", quality=70)
        again = fac.complete_step(pid, "review", "ثانٍ", quality=95)
        assert again["replay"] is True
        steps = json.loads(_product_row(fac, pid).pipeline_steps or "[]")
        assert len(steps) == 1, "الخطوةُ كُتِبتْ مرّتينِ لمفتاحٍ واحد."


# ═══════════════════════════════════════════════════════════════════════════
# F-8 — المعوّضاتُ عكسٌ حقيقيّ
# ═══════════════════════════════════════════════════════════════════════════


class TestF8CompensationIsReal:
    def test_production_compensator_deletes_the_row(
        self, factory: tuple[Factory, RecordingAuthorizer]
    ) -> None:
        fac, _ = factory
        created = fac.start_production("منتجٌ للعكس", "agent-6", operation_ref="ref-f8")
        pid = created["product_id"]
        assert _product_row(fac, pid) is not None
        assert fac._delete_product_row(pid) is True  # noqa: SLF001
        assert _product_row(fac, pid) is None, "المعوّضُ لم يعكسْ إنشاءً."
        assert fac._delete_product_row(pid) is False, "زُعِمَ عكسٌ لما لا وجودَ له."  # noqa: SLF001

    def test_step_compensator_restores_previous_pipeline(
        self, factory: tuple[Factory, RecordingAuthorizer]
    ) -> None:
        fac, _ = factory
        created = fac.start_production("منتجٌ لعكسِ الخطوة", "agent-7", operation_ref="ref-f8b")
        pid = created["product_id"]
        before = _product_row(fac, pid)
        previous_steps, previous_status = before.pipeline_steps or "[]", before.status
        fac.complete_step(pid, "review", "مخرج", quality=88)
        assert _product_row(fac, pid).status == "reviewed"
        assert fac._restore_product_pipeline(  # noqa: SLF001
            pid, previous_steps, previous_status, None
        )
        after = _product_row(fac, pid)
        assert after.status == previous_status
        assert json.loads(after.pipeline_steps or "[]") == json.loads(previous_steps)

    def test_manager_compensator_restores_previous_manager(
        self, registry: tuple[FactoryRegistry, RecordingAuthorizer]
    ) -> None:
        reg, _ = registry
        reg.assign_manager(FACTORY_ID, "agent-first")
        previous = _manager_of(reg, FACTORY_ID)
        reg.assign_manager(FACTORY_ID, "agent-second")
        assert _manager_of(reg, FACTORY_ID) == "agent-second"
        assert reg._set_manager_row(FACTORY_ID, previous) is True  # noqa: SLF001
        assert _manager_of(reg, FACTORY_ID) == previous, "المعوّضُ لم يُعِدِ المديرَ السابق."


# ═══════════════════════════════════════════════════════════════════════════
# F-9 — الفشلُ بعدَ الأثرِ لا يُدَّعى نجاحًا
# ═══════════════════════════════════════════════════════════════════════════


class TestF9FailureIsFailClosed:
    def test_failure_after_effect_is_not_claimed_successful(
        self, factory: tuple[Factory, RecordingAuthorizer], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """يُقاسُ سلوكُ الإغلاقِ القائمُ من 1M/1N: الحدُّ يُغلِقُ ولا يزعمُ نجاحًا.

        والحدُّ لا يُشغِّلُ المعوّضَ تلقائيًّا — وهذا دَينٌ مُعلَنٌ منذ 2A لا إنجازٌ
        يُزعَمُ هنا. فيُشغَّلُ المعوّضُ يدويًّا بعدَه ليُثبَتَ أنَّه عكسٌ حقيقيّ.
        """
        fac, authorizer = factory
        created = fac.start_production("منتجٌ للفشل", "agent-8", operation_ref="ref-f9")
        pid = created["product_id"]
        before = _product_row(fac, pid)
        previous_steps, previous_status = before.pipeline_steps or "[]", before.status

        original = fac._complete_step_row  # noqa: SLF001

        def _explode(product_id: str, step: str, output: str, quality: int) -> dict[str, Any]:
            original(product_id, step, output, quality)
            raise RuntimeError("فشلٌ مُصطنَعٌ بعدَ وقوعِ الأثر")

        monkeypatch.setattr(fac, "_complete_step_row", _explode)
        with pytest.raises(Exception) as raised:
            fac.complete_step(pid, "review", "مخرجٌ يفشلُ بعدَه", quality=50)
        assert not isinstance(raised.value, AssertionError)

        # الأثرُ واقعٌ والعمليّةُ غيرُ مُثبَّتةٍ ناجحة — ثمّ يعكسُ المعوّضُ فعلًا.
        assert fac._restore_product_pipeline(  # noqa: SLF001
            pid, previous_steps, previous_status, None
        )
        restored = _product_row(fac, pid)
        assert json.loads(restored.pipeline_steps or "[]") == json.loads(previous_steps)
        assert restored.status == previous_status


# ═══════════════════════════════════════════════════════════════════════════
# F-10 — لا بدائيّةَ جديدةً ولا تجاوز
# ═══════════════════════════════════════════════════════════════════════════


class TestF10NoNewPrimitiveNoBypass:
    def test_module_defines_no_new_sovereignty_primitive(self) -> None:
        source = Path(factories_module.__file__).read_text(encoding="utf-8")
        for name in re.findall(r"^class\s+(\w+)", source, flags=re.MULTILINE):
            assert not re.search(
                r"Boundary|Authorizer|Gateway|Idempotenc|Compensat|Jurisdiction", name
            ), f"بدائيّةٌ سياديّةٌ جديدةٌ في الوحدة: {name}"
        for forbidden in ("force", "bypass", "skip_check", "unchecked", "override"):
            assert f"{forbidden}=" not in source, f"معامَلُ تجاوزٍ محتمَل: {forbidden}"

    def test_both_surfaces_share_one_authorizer_type(
        self,
        factory: tuple[Factory, RecordingAuthorizer],
        registry: tuple[FactoryRegistry, RecordingAuthorizer],
    ) -> None:
        fac, fac_auth = factory
        reg, reg_auth = registry
        assert isinstance(fac.authorizer, ConstitutionalAuthorizer)
        assert isinstance(reg.authorizer, ConstitutionalAuthorizer)
        assert type(fac_auth.boundary) is type(reg_auth.boundary), (
            "حدَّانِ مختلفانِ لعمليّتين — أي مسارانِ سياديّانِ لا مسارٌ واحد."
        )


# ═══════════════════════════════════════════════════════════════════════════
# F-11 — خطُّ الأنابيبِ الكاملُ وهويّةُ الإذنِ (Q-28)
# ═══════════════════════════════════════════════════════════════════════════


class TestF11FullPipelineAndPermitIdentity:
    def test_full_pipeline_publishes_through_the_boundary(
        self, factory: tuple[Factory, RecordingAuthorizer]
    ) -> None:
        """خطواتٌ متتاليةٌ في الثانيةِ نفسِها تعبرُ الحدَّ ولا تُرفَضُ استهلاكًا.

        هذا قياسُ الاكتشافِ لا تجميلُه: هويّةُ الإذنِ تجزئةُ (فاعلٍ · فعلٍ · هدفٍ ·
        آثارٍ) في الثانيةِ الواحدة، فلو بقيَ الهدفُ خشِنًا (المنتجُ وحدَه) لصارت
        خطواتُ خطِّ الأنابيبِ إذنًا واحدًا ورُفِضَ ما بعدَ أوّلِها.
        """
        fac, authorizer = factory
        result = fac.run_full_pipeline("منتجٌ لخطِّ أنابيبَ كامل", "agent-9")
        pipeline = FACTORIES[FACTORY_ID]["pipeline"]
        assert result["status"] == "published"
        assert result["published_at"] is not None
        steps = json.loads(_product_row(fac, result["product_id"]).pipeline_steps or "[]")
        assert [s["step"] for s in steps] == list(pipeline)
        assert len(authorizer.results) == 1 + len(pipeline), "عمليّةٌ لم تعبرِ الحدَّ."
        assert not any(r.is_replay for r in authorizer.results)

    def test_two_distinct_assignments_get_distinct_permits(
        self, registry: tuple[FactoryRegistry, RecordingAuthorizer]
    ) -> None:
        """تعيينانِ مختلفانِ في الثانيةِ نفسِها عمليّتانِ لا إعادةٌ واحدة."""
        reg, authorizer = registry
        reg.assign_manager(FACTORY_ID, "agent-alpha")
        reg.assign_manager(FACTORY_ID, "agent-beta")
        assert _manager_of(reg, FACTORY_ID) == "agent-beta"
        first, second = authorizer.results[0], authorizer.results[1]
        assert not first.is_replay and not second.is_replay
        assert first.outcome.operation_key != second.outcome.operation_key


# ═══════════════════════════════════════════════════════════════════════════
# F-12 — قيدٌ باقٍ مُعلَنٌ (امتدادُ Q-11/Q-12)
# ═══════════════════════════════════════════════════════════════════════════


class TestF12DeclaredResidualConstraint:
    def test_reassigning_a_former_manager_is_a_replay_not_a_restoration(
        self, registry: tuple[FactoryRegistry, RecordingAuthorizer]
    ) -> None:
        """مفتاحُ العمليّةِ (مصنعٌ + وكيل) يجعلُ إعادةَ مديرٍ سابقٍ لا فعلًا.

        يُقاسُ هنا ما هو واقعٌ لا ما يُرادُ أن يكون: النّداءُ الثالِثُ يُرجِعُ
        `replay=True` ولا يُعيدُ المديرَ الأوّل. وهذا قيدٌ مُعلَنٌ في الوثيقةِ
        والسّجلِّ (امتدادُ Q-11/Q-12)، وحلُّه قرارٌ بشريٌّ في دلالةِ «العمليّةِ
        نفسِها»، لا توسيعٌ للمفتاحِ أفعلُه من تلقاءِ نفسي: توسيعُه يُلغي الذرّيّةَ
        التي من أجلِها وُجِدَ المفتاح.
        """
        reg, _ = registry
        reg.assign_manager(FACTORY_ID, "agent-one")
        reg.assign_manager(FACTORY_ID, "agent-two")
        third = reg.assign_manager(FACTORY_ID, "agent-one")
        assert third["replay"] is True
        assert third["assigned"] is False
        assert _manager_of(reg, FACTORY_ID) == "agent-two", (
            "القيدُ المُعلَنُ تغيّرَ — يُعادُ قياسُه وتُحدَّثُ الوثيقةُ لا يُمحَى الاختبار."
        )
