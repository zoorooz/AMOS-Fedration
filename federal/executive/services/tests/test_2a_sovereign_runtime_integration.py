"""الهدف: إثباتُ نمطِ Sovereign Runtime Integration على كتابتينِ إنتاجيّتين (2A)

النطاق: `state_registry.register_institution` و `governance.state_runtime.allocate_budget`
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-18
تاريخ آخر تعديل: 2026-08-18

هذا الملفُّ لا يُعيدُ اختبارَ 1F–1N ولا يقيسُ تصميمًا؛ يقيسُ ثمانيَ دعاوى على
الكتابتينِ نفسِهما، والقياسُ على الأثرِ في قاعدةِ البياناتِ وعلى مراحلِ الحصيلةِ
لا على وجودِ استثناء:

- G-1 المسارُ القديمُ لتأسيسِ المؤسسةِ لا يُنتِجُ أثرًا.
- G-2 المسارُ الجديدُ يُنتِجُ أثرًا حقيقيًّا ويمرُّ بمراحلِ الحدِّ الإلزاميّة.
- G-3 المسارُ القديمُ لتوزيعِ الميزانيةِ لا يمسُّ حالةً.
- G-4 التوزيعُ الجديدُ يغيّرُ حالةً حقيقيّةً عبرَ الحدِّ وحدَه.
- G-5 غيرُ المُصرَّحِ به لا يغيّرُ شيئًا — بالبوابةِ وبالتخويلِ المحلّيِّ معًا.
- G-6 التكرارُ لا يُنتِجُ أثرًا ثانيًا.
- G-7 الفشلُ بعدَ وقوعِ الأثرِ يحفظُ سلوكَ الإغلاقِ والتعويضِ القائمَ كما هو.
- G-8 الكتابتانِ تسلكانِ المسارَ السياديَّ نفسَه بلا بدائيّةٍ سياديّةٍ جديدة.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from amos_federation.common.database import get_session_factory, init_db
from amos_federation.common.principal import (
    DEFAULT_TENANT,
    AuthorizationContext,
    Principal,
)
from amos_federation.services.executive_core.sovereignty_bridge import (
    ConstitutionalAuthorizer,
    GuardedResult,
    UndeclaredExecutionError,
)
from amos_federation.services.governance import state_runtime as runtime_module
from amos_federation.services.governance.state_runtime import StateModel, StateRuntime
from amos_federation.services.state_registry import service as registry_module
from amos_federation.services.state_registry.models import InstitutionModel
from amos_federation.services.state_registry.service import StateRegistry

# ── تجهيزاتٌ محلّيّة ───────────────────────────────────────────────────────

_KING_PERMISSIONS = ("*",)
_CITIZEN_PERMISSIONS = ("read:public",)


def _context(role_id: str, permissions: tuple[str, ...]) -> AuthorizationContext:
    """سياقٌ مُتحقَّقٌ منه بدورٍ وصلاحيّاتٍ صريحة — لا ادّعاءَ دورٍ من الطلب."""
    return AuthorizationContext.from_principal(
        Principal.from_session_record(
            session_id=f"2a-{role_id}",
            username=f"user-{role_id}",
            role_id=role_id,
            permissions=permissions,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            tenant_id=DEFAULT_TENANT,
        )
    )


class RecordingAuthorizer(ConstitutionalAuthorizer):
    """المُصرِّحُ نفسُه، يُسجِّلُ حصائلَ الحدِّ ليُقاسَ ما مرَّ فعلًا.

    ليس بدائيّةً جديدةً ولا مسارًا ثانيًا: وراثةٌ لا تلمسُ منطقَ التصريحِ، غرضُها
    أن يقرأَ الاختبارُ `BoundaryOutcome.stages` من نداءِ الإنتاجِ نفسِه بدلَ أن
    يُعيدَ بناءَ نداءٍ مُصطنَعٍ ويُسمّيَه إثباتًا.
    """

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
def code() -> str:
    import uuid

    return f"INST-2A-{uuid.uuid4().hex[:8].upper()}"


@pytest.fixture
def registry(tmp_path: Path) -> tuple[StateRegistry, RecordingAuthorizer]:
    authorizer = RecordingAuthorizer(idempotency_ledger_path=tmp_path / "REG-IDEM.json")
    return StateRegistry(authorizer=authorizer), authorizer


@pytest.fixture
def runtime(tmp_path: Path) -> tuple[StateRuntime, RecordingAuthorizer]:
    authorizer = RecordingAuthorizer(
        actor=runtime_module.TREASURY_ACTOR,
        idempotency_ledger_path=tmp_path / "BUDGET-IDEM.json",
    )
    return StateRuntime(authorizer=authorizer), authorizer


def _institution_row(code: str) -> InstitutionModel | None:
    session = get_session_factory()()
    try:
        return session.query(InstitutionModel).filter(InstitutionModel.code == code).first()
    finally:
        session.close()


def _budget_of(runtime: StateRuntime, state_id: str) -> int:
    session = runtime._Session()  # noqa: SLF001 — القياسُ على القاعدةِ لا على القيمةِ المُرجَعة
    try:
        state = session.query(StateModel).filter(StateModel.state_id == state_id).first()
        return int(state.budget or "0") if state else -1
    finally:
        session.close()


def _mandatory_stages() -> set[Any]:
    from core.sovereignty.enforcement_boundary import MANDATORY_INTERNAL_STAGES

    return set(MANDATORY_INTERNAL_STAGES)


# ═══════════════════════════════════════════════════════════════════════════
# G-1 — المسارُ القديمُ لتأسيسِ المؤسسةِ لا يُنتِجُ أثرًا
# ═══════════════════════════════════════════════════════════════════════════


class TestG1LegacyInstitutionWriteClosed:
    def test_unguarded_write_refuses_and_writes_nothing(
        self, registry: tuple[StateRegistry, RecordingAuthorizer], code: str
    ) -> None:
        service, _ = registry
        with pytest.raises(UndeclaredExecutionError):
            service._write_institution_unguarded(  # noqa: SLF001
                code=code, name="وزارةٌ بلا حدّ", kind="ministry", branch="executive"
            )
        assert _institution_row(code) is None, "الكتابةُ القديمةُ أنتجت أثرًا رغمَ إغلاقِها."

    def test_source_has_no_second_write_path(self) -> None:
        """قياسٌ على المصدر: بابٌ جانبيٌّ جديدٌ يجبُ أن يُفشِلَ هذا الاختبار."""
        source = Path(registry_module.__file__).read_text(encoding="utf-8")
        assert "guard_declared(" in source, "التأسيسُ لا يمرُّ بالحدّ."
        assert source.count("InstitutionModel(") == 1, (
            "أكثرُ من موضعِ إنشاءٍ لصفِّ مؤسسةٍ — أي مسارُ كتابةٍ ثانٍ محتمل."
        )


# ═══════════════════════════════════════════════════════════════════════════
# G-2 — التأسيسُ الجديدُ أثرٌ حقيقيٌّ عبرَ مراحلِ الحدّ
# ═══════════════════════════════════════════════════════════════════════════


class TestG2NewInstitutionPathProducesRealEffect:
    def test_registration_writes_row_and_passes_mandatory_stages(
        self, registry: tuple[StateRegistry, RecordingAuthorizer], code: str
    ) -> None:
        service, authorizer = registry
        result = service.register_institution(
            context=_context("king", _KING_PERMISSIONS),
            code=code,
            name="وزارةُ قياسٍ سياديّ",
            kind="ministry",
            branch="executive",
        )
        row = _institution_row(code)
        assert row is not None, "لم يُكتَب صفُّ المؤسسةِ — لا أثرَ حقيقيّ."
        assert row.status == "active"
        assert result["replayed"] is False
        assert result["audit_id"], "لم يُسجَّل أثرُ التدقيقِ داخلَ المُطبِّق."

        assert len(authorizer.results) == 1, "نداءُ حدٍّ واحدٌ متوقَّعٌ لعمليّةٍ واحدة."
        outcome = authorizer.results[0].outcome
        assert outcome is not None, "لا حصيلةَ حدٍّ — فلم يمرَّ بالحدّ."
        missing = _mandatory_stages() - set(outcome.stages)
        assert not missing, f"مرحلةٌ إلزاميّةٌ لم تُمَرّ: {missing}"
        assert authorizer.results[0].evidence.decision == "ALLOW"


# ═══════════════════════════════════════════════════════════════════════════
# G-3 — المسارُ القديمُ للتوزيعِ لا يمسُّ حالة
# ═══════════════════════════════════════════════════════════════════════════


class TestG3LegacyBudgetPathClosed:
    def test_unguarded_allocation_refuses_and_changes_nothing(
        self, runtime: tuple[StateRuntime, RecordingAuthorizer]
    ) -> None:
        rt, _ = runtime
        before = _budget_of(rt, "science")
        with pytest.raises(UndeclaredExecutionError):
            rt._allocate_budget_unguarded("science", "500")  # noqa: SLF001
        assert _budget_of(rt, "science") == before, "تغيّرت الميزانيةُ من مسارٍ مُغلَق."

    def test_source_mutates_budget_from_one_place_only(self) -> None:
        source = Path(runtime_module.__file__).read_text(encoding="utf-8")
        assert "guard_declared(" in source, "التوزيعُ لا يمرُّ بالحدّ."
        assert source.count("state.budget = str(") == 1, (
            "أكثرُ من موضعٍ يكتبُ الميزانيةَ — أي مسارُ تغييرٍ ثانٍ محتمل."
        )


# ═══════════════════════════════════════════════════════════════════════════
# G-4 — التوزيعُ الجديدُ يغيّرُ حالةً حقيقيّةً عبرَ الحدّ
# ═══════════════════════════════════════════════════════════════════════════


class TestG4NewBudgetPathChangesRealState:
    def test_allocation_changes_database_and_passes_mandatory_stages(
        self, runtime: tuple[StateRuntime, RecordingAuthorizer]
    ) -> None:
        rt, authorizer = runtime
        before = _budget_of(rt, "science")
        result = rt.allocate_budget("science", "500", "تمويلٌ بحثيّ", allocation_id="g4-once")
        assert result["allocated"] == 500
        assert _budget_of(rt, "science") == before + 500, "الأثرُ لم يقعْ في القاعدة."

        outcome = authorizer.results[0].outcome
        assert outcome is not None
        missing = _mandatory_stages() - set(outcome.stages)
        assert not missing, f"مرحلةٌ إلزاميّةٌ لم تُمَرّ: {missing}"
        assert authorizer.results[0].evidence.decision == "ALLOW"


# ═══════════════════════════════════════════════════════════════════════════
# G-5 — غيرُ المُصرَّحِ به لا يغيّرُ شيئًا
# ═══════════════════════════════════════════════════════════════════════════


class TestG5UnauthorizedChangesNothing:
    def test_gateway_denial_leaves_budget_untouched(self, tmp_path: Path) -> None:
        """فاعلٌ تنفيذيٌّ يوزِّعُ ميزانيةً: البوابةُ ترفضُ (R-003-1) ولا تتغيّرُ حالة."""
        authorizer = ConstitutionalAuthorizer(
            actor="EXECUTIVE", idempotency_ledger_path=tmp_path / "DENIED.json"
        )
        authorizer.crown_status()  # يُتاحُ `core` بعدَ أوّلِ مسٍّ للبوابةِ نفسِها
        from core.sovereignty.gateway import SovereigntyViolation

        rt = StateRuntime(authorizer=authorizer)
        before = _budget_of(rt, "science")
        with pytest.raises(SovereigntyViolation):
            rt.allocate_budget("science", "500", "توزيعٌ بفاعلٍ غيرِ مختصّ", allocation_id="g5")
        assert _budget_of(rt, "science") == before, "غيرُ المُصرَّحِ به غيَّرَ حالة."

    def test_local_authorization_denial_writes_no_row(
        self, registry: tuple[StateRegistry, RecordingAuthorizer], code: str
    ) -> None:
        service, authorizer = registry
        from amos_federation.services.state_registry.authorization import (
            RegistryAuthorizationError,
        )


        with pytest.raises(RegistryAuthorizationError):
            service.register_institution(
                context=_context("citizen", _CITIZEN_PERMISSIONS),
                code=code,
                name="وزارةٌ غيرُ مأذونة",
                kind="ministry",
                branch="executive",
            )
        assert _institution_row(code) is None, "كُتِبَ صفٌّ لسياقٍ غيرِ مأذون."
        assert authorizer.results == [], "وصلَ نداءٌ إلى الحدِّ قبلَ اجتيازِ التخويل."


# ═══════════════════════════════════════════════════════════════════════════
# G-6 — التكرارُ لا يُنتِجُ أثرًا ثانيًا
# ═══════════════════════════════════════════════════════════════════════════


class TestG6DuplicateProducesNoSecondEffect:
    def test_same_allocation_key_allocates_once(
        self, runtime: tuple[StateRuntime, RecordingAuthorizer]
    ) -> None:
        rt, authorizer = runtime
        before = _budget_of(rt, "science")
        first = rt.allocate_budget("science", "300", "تكرارٌ مقصود", allocation_id="g6")
        second = rt.allocate_budget("science", "300", "تكرارٌ مقصود", allocation_id="g6")
        assert first["replayed"] is False and second["replayed"] is True
        assert second["allocated"] == 0, "ادُّعيَ توزيعٌ ثانٍ لمفتاحٍ واحد."
        assert _budget_of(rt, "science") == before + 300, "وقعَ الأثرُ مرّتينِ لمفتاحٍ واحد."
        assert authorizer.results[1].is_replay

    def test_registration_key_blocks_a_second_effect(
        self, registry: tuple[StateRegistry, RecordingAuthorizer], code: str
    ) -> None:
        """المفتاحُ (المستأجر · الرمز) يمنعُ أثرًا ثانيًا حتى لو غابَ الصفّ.

        يُحذَفُ الصفُّ بينَ النداءينِ لتُقاسَ الذرّيّةُ وحدَها: فحصُ التكرارِ
        السابقُ (`DuplicateCodeError`) يمنعُ قبلَ الحدّ، وضمانُ 1H يمنعُ بعدَه —
        وطبقتانِ لا واحدة.
        """
        service, authorizer = registry
        crown = _context("king", _KING_PERMISSIONS)
        first = service.register_institution(
            context=crown, code=code, name="وزارةٌ للذرّيّة", kind="ministry", branch="executive"
        )
        service._delete_institution_row(first["id"])  # noqa: SLF001
        assert _institution_row(code) is None

        second = service.register_institution(
            context=crown, code=code, name="وزارةٌ للذرّيّة", kind="ministry", branch="executive"
        )
        assert second["replayed"] is True, "أُنتِجَ أثرٌ ثانٍ لمفتاحِ عمليّةٍ واحد."
        assert _institution_row(code) is None, "أُعيدَ إنشاءُ الصفِّ في نداءٍ مُعاد."
        assert authorizer.results[1].is_replay


# ═══════════════════════════════════════════════════════════════════════════
# G-7 — الفشلُ بعدَ وقوعِ الأثرِ يحفظُ السلوكَ القائم
# ═══════════════════════════════════════════════════════════════════════════


class TestG7FailureAfterEffectPreservesExistingBehavior:
    def test_failure_is_fail_closed_and_compensation_plan_covers_the_effect(
        self,
        runtime: tuple[StateRuntime, RecordingAuthorizer],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """الفشلُ بعدَ الكتابةِ لا يُدَّعى نجاحًا، وخطّةُ التعويضِ تغطّي الأثر.

        وهذا قياسٌ لسلوكٍ **قائمٍ** من 1M/1N لا سلوكٍ جديد: الحدُّ يبني خطّةَ
        تعويضٍ ويُغلِقُ على الفشل، ولا يُشغِّلُ المعوّضَ تلقائيًّا. فالأثرُ يبقى
        واقعًا والعمليّةُ غيرَ مُثبَّتةٍ ناجحةً — وهذا هو الدَّينُ المُعلَنُ في 2A
        لا إنجازٌ يُزعَم. ثمّ يُشغَّلُ المعوّضُ يدويًّا ليُثبَتَ أنّه عكسٌ حقيقيّ.
        """
        from core.sovereignty.idempotency import IdempotencyError

        rt, authorizer = runtime
        before = _budget_of(rt, "science")

        def _explode(*_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError("سقوطُ التدقيقِ بعدَ وقوعِ الأثر")

        monkeypatch.setattr(runtime_module.PersistentAuditStore, "append", _explode)
        with pytest.raises((IdempotencyError, RuntimeError)) as failure:
            rt.allocate_budget("science", "400", "فشلٌ بعدَ الأثر", allocation_id="g7")

        assert "نجَح" not in str(failure.value), "ادُّعيَ نجاحٌ في نصِّ الفشل."
        after_failure = _budget_of(rt, "science")
        assert after_failure == before + 400, (
            "الأثرُ لم يقعْ قبلَ الفشلِ — فالقياسُ التالي لا معنى له."
        )

        # العكسُ متاحٌ وحقيقيٌّ: الميزانيةُ تعودُ إلى قيمتِها لا إلى قيمةٍ مظنونة.
        assert rt._add_to_budget("science", -400) == before  # noqa: SLF001
        assert _budget_of(rt, "science") == before

        # والعمليّةُ لم تُثبَّت ناجحةً: لم تُرجَعْ حصيلةٌ ناجحةٌ من نداءٍ فاشل.
        assert len(authorizer.results) == 0, (
            "أُرجِعت حصيلةُ نجاحٍ من نداءٍ فاشل."
        )

        # ── تصحيحُ ادّعاءٍ سابق (P1أ من برنامجِ الهجرة) ────────────────────
        #
        # كان هذا الاختبارُ يزعمُ أنَّ إعادةَ النداءِ الفاشلِ «تُغلِقُ صريحًا»
        # لأنَّ الإذنَ المُستهلَكَ لا يُعادُ استعمالُه. والقياسُ أثبتَ أنَّ هذا
        # **صحيحٌ بالتوقيتِ وحدَه لا في نفسِه**: هويّةُ الإذنِ في 1F هي
        # `EP-{contract_id}-{ثانية}`، فإن وقعت الإعادةُ في الثانيةِ نفسِها
        # اصطدمَ الإذنُ ورُفِضت، وإن وقعت في ثانيةٍ جديدةٍ **نُفِّذت وأنتجت أثرًا
        # ثانيًا** بالمفتاحِ نفسِه (قِيسَ: ميزانيةٌ 1000 ← 1400 ← 1800).
        #
        # فالادّعاءُ الأوّلُ أُسقِط، ولم يُستبدَلْ بادّعاءٍ أضعفَ يُخفي الحقيقة:
        # يُقاسُ هنا كِلا الفرعينِ صراحةً، ويُسجَّلُ الخللُ قرارًا سياديًّا معلَّقًا
        # (Q-12) في `docs/audit/SOVEREIGN_DECISION_REGISTER.md`، لأنَّ إصلاحَه
        # تغييرٌ في عقدِ 1F/1H لا يجوزُ لمُنفِّذٍ أن يُقرِّرَه من تلقاءِ نفسِه.
        monkeypatch.undo()
        after_failure = _budget_of(rt, "science")
        try:
            rt.allocate_budget("science", "400", "فشلٌ بعدَ الأثر", allocation_id="g7")
        except IdempotencyError:
            # الفرعُ الأوّل: إعادةٌ في الثانيةِ نفسِها — الإذنُ مُستهلَكٌ فتُرفَض.
            assert _budget_of(rt, "science") == after_failure, (
                "أُنتِجَ أثرٌ ثانٍ رغمَ رفضِ الإذن."
            )
        else:
            # الفرعُ الثاني: إعادةٌ في ثانيةٍ جديدةٍ — تُنفَّذُ ويقعُ أثرٌ ثانٍ.
            # هذا **خللٌ مُعلَنٌ** لا سلوكٌ مقبولٌ يُوثَّقُ ويُنسى: مفتاحُ الذرّيّةِ
            # لم يمنعْ إعادةَ عمليّةٍ فاشلةٍ، فالحمايةُ من الأثرِ المزدوجِ محدودةٌ
            # بثانيةٍ واحدةٍ لا بمفتاحِ العمليّة.
            assert _budget_of(rt, "science") == after_failure + 400, (
                "نجحت الإعادةُ بلا أثرٍ — فوصفُ الخللِ أعلاه صارَ غيرَ صحيح."
            )


# ═══════════════════════════════════════════════════════════════════════════
# G-8 — مسارٌ سياديٌّ واحدٌ بلا بدائيّةٍ جديدة
# ═══════════════════════════════════════════════════════════════════════════


class TestG8OneSovereignPathNoNewPrimitive:
    def test_both_operations_use_the_same_authorizer_and_boundary_type(
        self,
        registry: tuple[StateRegistry, RecordingAuthorizer],
        runtime: tuple[StateRuntime, RecordingAuthorizer],
    ) -> None:
        service, reg_auth = registry
        rt, run_auth = runtime
        assert isinstance(service.authorizer, ConstitutionalAuthorizer)
        assert isinstance(rt.authorizer, ConstitutionalAuthorizer)
        assert type(reg_auth.boundary) is type(run_auth.boundary), (
            "حدَّانِ مختلفانِ لعمليّتين — أي مسارانِ سياديّانِ لا مسارٌ واحد."
        )

    def test_neither_module_defines_a_new_sovereignty_primitive(self) -> None:
        import re

        for module in (registry_module, runtime_module):
            source = Path(module.__file__).read_text(encoding="utf-8")
            classes = re.findall(r"^class\s+(\w+)", source, flags=re.MULTILINE)
            for name in classes:
                assert not re.search(
                    r"Boundary|Authorizer|Gateway|Idempotenc|Compensat|Jurisdiction",
                    name,
                ), f"بدائيّةٌ سياديّةٌ جديدةٌ في {module.__name__}: {name}"
            for forbidden in ("force", "bypass", "skip_check", "unchecked", "override"):
                assert f"{forbidden}=" not in source, (
                    f"معامَلُ تجاوزٍ محتمَلٌ في {module.__name__}: {forbidden}"
                )
