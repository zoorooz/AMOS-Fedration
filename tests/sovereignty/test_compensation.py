"""الهدف: اختباراتُ التعويضِ السياديّ — إثباتٌ أنّ حالةَ الدولةِ ترجعُ فعلًا.

النطاق: `tests/sovereignty/` — `CompensationGuard` و`CompensationPlan` و`CompensationJournal`.
المالك: ديوان التدقيق
تاريخ الإنشاء: 2026-08-18
تاريخ آخر تعديل: 2026-08-18
tags: test, compensation, rollback, saga, idempotency, contract

## منهجُ الإثبات

الاختباراتُ هنا **لا تفحصُ وجودَ صنفٍ ولا اسمَ دالّة**. كلُّ ادّعاءٍ يُقاسُ على
**حالةِ خزينةٍ حقيقيّةٍ** (`_Treasury`): تُلتقَطُ الحالةُ قبلَ العمليّة، وتُقارَنُ
بها بعدَ التعويض. فإن لم ترجعِ الأرقامُ إلى ما كانت عليه فالاختبارُ يسقط، ولو
كانت كلُّ الأصنافِ موجودةً وكلُّ الحالاتِ مكتوبة.
"""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from core.sovereignty.compensation import (
    IRREVERSIBLE_EFFECT_KINDS,
    CompensationError,
    CompensationGuard,
    CompensationJournal,
    CompensationPlan,
    CompensationRequired,
    CompensationScopeError,
    CompensationStatus,
    Compensator,
    IrreversibleEffectError,
    UncompensatableEffectError,
    bind_compensation_plan,
    compute_compensation_id,
    effects_of,
)
from core.sovereignty.contract import (
    EffectKind,
    SovereignEffect,
    bind_contract,
)
from core.sovereignty.idempotency import (
    IdempotencyGuard,
    IdempotencyKey,
    IdempotencyLedger,
    OperationStatus,
    compute_fingerprint,
)

# ─────────────────────────────────────────────────────────────────────────────
# حالةُ دولةٍ حقيقيّةٌ يُقاسُ عليها — لا وهمٌ ولا mock
# ─────────────────────────────────────────────────────────────────────────────


class _Treasury:
    """خزينةٌ مبسّطةٌ لكنّها **حالةٌ فعليّة**: الأرقامُ تتغيّرُ وتُقارَن."""

    def __init__(self, **balances: int) -> None:
        self.balances: dict[str, int] = dict(balances)
        self.log: list[str] = []

    def snapshot(self) -> dict[str, int]:
        return dict(self.balances)

    def debit(self, account: str, amount: int) -> None:
        self.balances[account] = self.balances.get(account, 0) - amount
        self.log.append(f"debit:{account}:{amount}")

    def credit(self, account: str, amount: int) -> None:
        self.balances[account] = self.balances.get(account, 0) + amount
        self.log.append(f"credit:{account}:{amount}")


TARGET = "treasury/tx-77"
ACTOR = "minister-of-finance"
ACTION = "settle"

SIG_DEBIT = f"WRITE:{TARGET}/debit"
SIG_CREDIT = f"WRITE:{TARGET}/credit"
SIG_SEAL = f"CREATE:{TARGET}/seal"


def _contract(*, effects: tuple[SovereignEffect, ...] | None = None):
    declared = effects or (
        SovereignEffect(kind=EffectKind.WRITE, resource=f"{TARGET}/debit"),
        SovereignEffect(kind=EffectKind.WRITE, resource=f"{TARGET}/credit"),
        SovereignEffect(kind=EffectKind.CREATE, resource=f"{TARGET}/seal"),
    )
    return bind_contract(
        actor=ACTOR,
        action=ACTION,
        target=TARGET,
        declared_effects=declared,
    )


def _guard(tmp_path: Path) -> CompensationGuard:
    return CompensationGuard(
        journal=CompensationJournal(path=tmp_path / "compensation.json"),
        idempotency=IdempotencyGuard(
            ledger=IdempotencyLedger(path=tmp_path / "idempotency.json")
        ),
    )


def _key(value: str = "settle-77") -> IdempotencyKey:
    return IdempotencyKey(scope="treasury", value=value)


def _fingerprint(contract) -> str:
    return compute_fingerprint(
        scope="treasury",
        action=contract.action,
        target=contract.target,
        effect_signatures=tuple(e.signature for e in contract.mutating_effects),
        actor=contract.actor,
    )


def _plan_for(contract, treasury: _Treasury, *, seal: dict[str, bool] | None = None):
    """خطّةُ تعويضٍ حقيقيّةٌ تعكسُ الأثرَ على الخزينةِ نفسِها."""
    seal = seal if seal is not None else {}
    return bind_compensation_plan(
        contract=contract,
        compensators=(
            Compensator(
                effect_signature=SIG_DEBIT,
                apply=lambda: treasury.credit("A", 100),
                description="إعادةُ ما خُصِمَ من A",
            ),
            Compensator(
                effect_signature=SIG_CREDIT,
                apply=lambda: treasury.debit("B", 100),
                description="سحبُ ما أُضيفَ إلى B",
            ),
            Compensator(
                effect_signature=SIG_SEAL,
                apply=lambda: seal.pop("sealed", None),
                description="فكُّ الختم",
            ),
        ),
    )


def _applier(treasury: _Treasury, seal: dict[str, bool], *, fail_on: str | None = None):
    def apply_effect(sig: str) -> None:
        if sig == fail_on:
            raise RuntimeError(f"الأثرُ «{sig}» تعذّرَ تطبيقُه")
        if sig == SIG_DEBIT:
            treasury.debit("A", 100)
        elif sig == SIG_CREDIT:
            treasury.credit("B", 100)
        elif sig == SIG_SEAL:
            seal["sealed"] = True
        else:  # pragma: no cover — لا يُبلَغُ في الاختبارات
            raise AssertionError(f"أثرٌ غيرُ متوقَّع: {sig}")

    return apply_effect


# ─────────────────────────────────────────────────────────────────────────────
# 1. ربطُ الخطّة — المنعُ سابقٌ لا لاحق
# ─────────────────────────────────────────────────────────────────────────────


class TestBindCompensationPlan:
    """الدولةُ لا تدخلُ في فعلٍ لا تعرفُ كيف تخرجُ منه."""

    def test_mutating_effect_without_compensator_rejected_at_bind(self):
        """أثرٌ مُغيِّرٌ بلا معوّضٍ يُرفَضُ عندَ الربطِ لا عندَ الفشل."""
        contract = _contract()
        treasury = _Treasury(A=1000, B=0)
        with pytest.raises(UncompensatableEffectError, match="بلا معوّض"):
            bind_compensation_plan(
                contract=contract,
                compensators=(
                    Compensator(
                        effect_signature=SIG_DEBIT,
                        apply=lambda: treasury.credit("A", 100),
                    ),
                ),
            )

    def test_rejection_message_names_the_missing_effects(self):
        """الرسالةُ تُسمّي الأثرَ الناقصَ ولا تُلمِّح."""
        contract = _contract()
        with pytest.raises(UncompensatableEffectError) as err:
            bind_compensation_plan(contract=contract, compensators=())
        assert SIG_DEBIT in str(err.value)
        assert SIG_CREDIT in str(err.value)
        assert SIG_SEAL in str(err.value)

    def test_read_effect_needs_no_compensator(self):
        """قراءةٌ لا تُغيِّرُ حالةً فلا تُعكَس."""
        contract = bind_contract(
            actor=ACTOR,
            action=ACTION,
            target=TARGET,
            declared_effects=(
                SovereignEffect(kind=EffectKind.READ, resource=f"{TARGET}/ledger"),
                SovereignEffect(kind=EffectKind.WRITE, resource=f"{TARGET}/debit"),
            ),
        )
        treasury = _Treasury(A=1000)
        plan = bind_compensation_plan(
            contract=contract,
            compensators=(
                Compensator(
                    effect_signature=SIG_DEBIT,
                    apply=lambda: treasury.credit("A", 100),
                ),
            ),
        )
        assert plan.covers(SIG_DEBIT)
        assert not plan.covers(f"READ:{TARGET}/ledger")

    def test_external_effect_contract_cannot_be_compensated(self):
        """نداءٌ خارجيٌّ وقع لا يُسحَب — ولا تُربَطُ له خطّةٌ تزعمُ عكسَه."""
        contract = bind_contract(
            actor=ACTOR,
            action=ACTION,
            target=TARGET,
            declared_effects=(
                SovereignEffect(kind=EffectKind.EXTERNAL, resource=f"{TARGET}/swift"),
            ),
        )
        with pytest.raises(IrreversibleEffectError, match="لا يُعكَس"):
            bind_compensation_plan(
                contract=contract,
                compensators=(
                    Compensator(
                        effect_signature=f"EXTERNAL:{TARGET}/swift",
                        apply=lambda: None,
                    ),
                ),
            )

    def test_external_is_the_declared_irreversible_kind(self):
        """قائمةُ ما لا يُعكَسُ صريحةٌ لا ضمنيّة."""
        assert EffectKind.EXTERNAL in IRREVERSIBLE_EFFECT_KINDS
        assert EffectKind.WRITE not in IRREVERSIBLE_EFFECT_KINDS

    def test_compensator_for_undeclared_effect_rejected(self):
        """معوّضٌ لأثرٍ لم يُعلِنه العقدُ مرفوض."""
        contract = _contract()
        treasury = _Treasury(A=1000, B=0)
        seal: dict[str, bool] = {}
        with pytest.raises(CompensationScopeError, match="لا يُعلِنُ"):
            bind_compensation_plan(
                contract=contract,
                compensators=(
                    Compensator(effect_signature=SIG_DEBIT, apply=lambda: treasury.credit("A", 100)),
                    Compensator(effect_signature=SIG_CREDIT, apply=lambda: treasury.debit("B", 100)),
                    Compensator(effect_signature=SIG_SEAL, apply=lambda: seal.clear()),
                    Compensator(
                        effect_signature="DELETE:treasury/tx-77/other",
                        apply=lambda: None,
                    ),
                ),
            )

    def test_compensator_outside_contract_target_rejected(self):
        """التعويضُ محكومٌ بنطاقِ العقدِ كالتنفيذِ سواءً بسواء."""
        contract = _contract()
        # نبني عقدًا هدفُه أضيقُ لنُثبِتَ أنّ فحصَ النطاقِ حقيقيّ
        narrow = bind_contract(
            actor=ACTOR,
            action=ACTION,
            target=f"{TARGET}/debit",
            declared_effects=(
                SovereignEffect(kind=EffectKind.WRITE, resource=f"{TARGET}/debit"),
            ),
        )
        assert narrow.target != contract.target
        with pytest.raises(CompensationScopeError):
            bind_compensation_plan(
                contract=narrow,
                compensators=(
                    Compensator(effect_signature=SIG_DEBIT, apply=lambda: None),
                    Compensator(effect_signature=SIG_CREDIT, apply=lambda: None),
                ),
            )

    def test_duplicate_compensator_rejected(self):
        """الأثرُ الواحدُ له معكوسٌ واحد — وإلّا صارَ التعويضُ مضاعَفًا."""
        contract = _contract()
        with pytest.raises(CompensationError, match="معوّضانِ"):
            bind_compensation_plan(
                contract=contract,
                compensators=(
                    Compensator(effect_signature=SIG_DEBIT, apply=lambda: None),
                    Compensator(effect_signature=SIG_DEBIT, apply=lambda: None),
                    Compensator(effect_signature=SIG_CREDIT, apply=lambda: None),
                    Compensator(effect_signature=SIG_SEAL, apply=lambda: None),
                ),
            )

    def test_compensator_requires_named_effect(self):
        """معوّضٌ بلا أثرٍ مُسمًّى مرفوض."""
        with pytest.raises(CompensationError, match="بلا أثرٍ مُسمًّى"):
            Compensator(effect_signature="   ", apply=lambda: None)

    def test_compensator_requires_callable(self):
        """معوّضٌ ليس فعلًا قابلًا للاستدعاءِ مرفوض."""
        with pytest.raises(CompensationError, match="قابلًا للاستدعاء"):
            Compensator(effect_signature=SIG_DEBIT, apply="not-callable")  # type: ignore[arg-type]

    def test_plan_is_frozen(self):
        """الخطّةُ لا تُوسَّعُ بعدَ ربطِها."""
        contract = _contract()
        treasury = _Treasury(A=1000, B=0)
        plan = _plan_for(contract, treasury)
        with pytest.raises(Exception):  # noqa: B017 — FrozenInstanceError
            plan.contract_id = "EC-forged"  # type: ignore[misc]

    def test_plan_serialises_without_callables(self):
        """السجلُّ يحملُ وصفًا لا دالّةً — لا يُخزَّنُ ما لا يُقرأ."""
        contract = _contract()
        treasury = _Treasury(A=1000, B=0)
        plan = _plan_for(contract, treasury)
        payload = json.dumps(plan.as_dict(), ensure_ascii=False)
        assert "contract_id" in payload
        assert SIG_DEBIT in payload

    def test_compensator_for_unknown_signature_raises(self):
        """طلبُ معوّضٍ غيرِ مسجَّلٍ يُرفَعُ ولا يُرجِعُ `None` صامتًا."""
        contract = _contract()
        treasury = _Treasury(A=1000, B=0)
        plan = _plan_for(contract, treasury)
        with pytest.raises(UncompensatableEffectError):
            plan.compensator_for("WRITE:treasury/tx-77/ghost")


# ─────────────────────────────────────────────────────────────────────────────
# 2. القدرةُ الأساسيّة — الحالةُ ترجعُ فعلًا
# ─────────────────────────────────────────────────────────────────────────────


class TestStateActuallyReturns:
    """الادّعاءُ الجوهريُّ: بعدَ الفشلِ الجزئيّ ترجعُ أرقامُ الخزينةِ كما كانت."""

    def test_partial_failure_restores_exact_prior_state(self, tmp_path: Path):
        """أثرانِ طُبِّقا ثمّ فشلَ الثالث -> الخزينةُ ترجعُ إلى لقطتِها الأولى."""
        treasury = _Treasury(A=1000, B=500)
        seal: dict[str, bool] = {}
        before = treasury.snapshot()

        contract = _contract()
        plan = _plan_for(contract, treasury, seal=seal)
        guard = _guard(tmp_path)

        with pytest.raises(CompensationRequired) as err:
            guard.run_compensated_transaction(
                contract=contract,
                plan=plan,
                key=_key(),
                fingerprint=_fingerprint(contract),
                apply_effect=_applier(treasury, seal, fail_on=SIG_SEAL),
            )

        assert treasury.snapshot() == before
        assert seal == {}
        assert err.value.outcome.status is CompensationStatus.COMPENSATED
        assert err.value.outcome.state_is_clean is True

    def test_without_compensation_the_state_would_stay_broken(self, tmp_path: Path):
        """قياسُ الفجوة: المسارُ الذرّيُّ وحدَه (1H) يترك الحالةَ نصفيّة."""
        treasury = _Treasury(A=1000, B=500)
        seal: dict[str, bool] = {}
        before = treasury.snapshot()

        contract = _contract()
        idem = IdempotencyGuard(
            ledger=IdempotencyLedger(path=tmp_path / "idem-only.json")
        )
        from core.sovereignty.idempotency import IdempotencyError

        with pytest.raises(IdempotencyError):
            idem.run_effects_once(
                key=_key("bare"),
                fingerprint=_fingerprint(contract),
                declared_effects=tuple(e.signature for e in contract.mutating_effects),
                apply_effect=_applier(treasury, seal, fail_on=SIG_SEAL),
            )

        # هذا هو العيبُ الذي تسدُّه 1I: الحالةُ لم ترجع.
        assert treasury.snapshot() != before
        assert treasury.balances["A"] == 900
        assert treasury.balances["B"] == 600

    def test_success_leaves_effects_applied_and_opens_no_compensation(self, tmp_path: Path):
        """نجاحٌ = لا تعويض. التعويضُ ليس ضريبةً على النجاح."""
        treasury = _Treasury(A=1000, B=500)
        seal: dict[str, bool] = {}
        contract = _contract()
        plan = _plan_for(contract, treasury, seal=seal)
        guard = _guard(tmp_path)

        result = guard.run_compensated_transaction(
            contract=contract,
            plan=plan,
            key=_key(),
            fingerprint=_fingerprint(contract),
            apply_effect=_applier(treasury, seal),
        )

        assert result.status is OperationStatus.SUCCEEDED
        assert treasury.balances == {"A": 900, "B": 600}
        assert seal == {"sealed": True}
        assert guard.journal.count() == 0

    def test_first_effect_fails_nothing_to_compensate(self, tmp_path: Path):
        """فشلٌ قبلَ أيِّ أثر -> `NOT_REQUIRED` والحالةُ لم تُمَسّ."""
        treasury = _Treasury(A=1000, B=500)
        seal: dict[str, bool] = {}
        before = treasury.snapshot()
        contract = _contract()
        plan = _plan_for(contract, treasury, seal=seal)
        guard = _guard(tmp_path)

        with pytest.raises(CompensationRequired) as err:
            guard.run_compensated_transaction(
                contract=contract,
                plan=plan,
                key=_key(),
                fingerprint=_fingerprint(contract),
                apply_effect=_applier(treasury, seal, fail_on=SIG_DEBIT),
            )

        assert treasury.snapshot() == before
        assert err.value.outcome.status is CompensationStatus.NOT_REQUIRED
        assert err.value.outcome.state_is_clean is True

    def test_compensation_runs_in_reverse_order(self, tmp_path: Path):
        """أثرٌ بُنيَ فوقَ أثرٍ يُزالُ قبلَه — LIFO مقيسٌ لا موصوف."""
        order: list[str] = []
        contract = _contract()
        plan = bind_compensation_plan(
            contract=contract,
            compensators=(
                Compensator(effect_signature=SIG_DEBIT, apply=lambda: order.append("undo-debit")),
                Compensator(effect_signature=SIG_CREDIT, apply=lambda: order.append("undo-credit")),
                Compensator(effect_signature=SIG_SEAL, apply=lambda: order.append("undo-seal")),
            ),
        )
        guard = _guard(tmp_path)
        outcome = guard.compensate(
            contract=contract,
            plan=plan,
            operation_key=_key(),
            applied_signatures=(SIG_DEBIT, SIG_CREDIT, SIG_SEAL),
            reason="اختبارُ الترتيب",
        )
        assert order == ["undo-seal", "undo-credit", "undo-debit"]
        assert outcome.status is CompensationStatus.COMPENSATED

    def test_only_applied_effects_are_compensated(self, tmp_path: Path):
        """ما لم يُطبَّق لا يُعكَس — وإلّا كان التعويضُ أثرًا جديدًا."""
        called: list[str] = []
        contract = _contract()
        plan = bind_compensation_plan(
            contract=contract,
            compensators=(
                Compensator(effect_signature=SIG_DEBIT, apply=lambda: called.append(SIG_DEBIT)),
                Compensator(effect_signature=SIG_CREDIT, apply=lambda: called.append(SIG_CREDIT)),
                Compensator(effect_signature=SIG_SEAL, apply=lambda: called.append(SIG_SEAL)),
            ),
        )
        guard = _guard(tmp_path)
        guard.compensate(
            contract=contract,
            plan=plan,
            operation_key=_key(),
            applied_signatures=(SIG_DEBIT,),
            reason="أثرٌ واحدٌ فقط",
        )
        assert called == [SIG_DEBIT]


# ─────────────────────────────────────────────────────────────────────────────
# 3. الصدقُ عندَ العجز — لا ادّعاءَ سلامةٍ بلا دليل
# ─────────────────────────────────────────────────────────────────────────────


class TestHonestyWhenCompensationFails:
    """الدولةُ تُعلِنُ دَينَها ولا تُخفيه."""

    def test_failing_compensator_yields_partial_and_names_residual(self, tmp_path: Path):
        """معوّضٌ فشل -> `PARTIALLY_COMPENSATED` والأثرُ الباقي مُسمًّى."""
        treasury = _Treasury(A=1000, B=500)
        contract = _contract()

        def broken() -> None:
            raise RuntimeError("المعوّضُ نفسُه تعذّر")

        plan = bind_compensation_plan(
            contract=contract,
            compensators=(
                Compensator(effect_signature=SIG_DEBIT, apply=broken),
                Compensator(effect_signature=SIG_CREDIT, apply=lambda: treasury.debit("B", 100)),
                Compensator(effect_signature=SIG_SEAL, apply=lambda: None),
            ),
        )
        guard = _guard(tmp_path)
        outcome = guard.compensate(
            contract=contract,
            plan=plan,
            operation_key=_key(),
            applied_signatures=(SIG_DEBIT, SIG_CREDIT),
            reason="فشلٌ مُصطنَع",
        )

        assert outcome.status is CompensationStatus.PARTIALLY_COMPENSATED
        assert outcome.state_is_clean is False
        assert outcome.requires_human is True
        assert outcome.residual_signatures == (SIG_DEBIT,)

    def test_all_compensators_fail_yields_compensation_failed(self, tmp_path: Path):
        """لا شيءَ عُوِّض -> `COMPENSATION_FAILED` لا `PARTIALLY`."""
        contract = _contract()

        def broken() -> None:
            raise RuntimeError("تعذّر")

        plan = bind_compensation_plan(
            contract=contract,
            compensators=(
                Compensator(effect_signature=SIG_DEBIT, apply=broken),
                Compensator(effect_signature=SIG_CREDIT, apply=broken),
                Compensator(effect_signature=SIG_SEAL, apply=broken),
            ),
        )
        guard = _guard(tmp_path)
        outcome = guard.compensate(
            contract=contract,
            plan=plan,
            operation_key=_key(),
            applied_signatures=(SIG_DEBIT, SIG_CREDIT),
            reason="كلُّ المعوّضاتِ فاشلة",
        )
        assert outcome.status is CompensationStatus.COMPENSATION_FAILED
        assert set(outcome.residual_signatures) == {SIG_DEBIT, SIG_CREDIT}

    def test_one_failure_does_not_abort_the_rest(self, tmp_path: Path):
        """فشلُ معوّضٍ لا يمنعُ عكسَ ما يمكنُ عكسُه — التقليلُ من الضررِ واجب."""
        treasury = _Treasury(A=1000, B=500)
        contract = _contract()

        def broken() -> None:
            raise RuntimeError("تعذّر")

        plan = bind_compensation_plan(
            contract=contract,
            compensators=(
                Compensator(effect_signature=SIG_DEBIT, apply=lambda: treasury.credit("A", 100)),
                Compensator(effect_signature=SIG_CREDIT, apply=broken),
                Compensator(effect_signature=SIG_SEAL, apply=lambda: None),
            ),
        )
        guard = _guard(tmp_path)
        treasury.debit("A", 100)
        treasury.credit("B", 100)
        outcome = guard.compensate(
            contract=contract,
            plan=plan,
            operation_key=_key(),
            applied_signatures=(SIG_DEBIT, SIG_CREDIT),
            reason="فشلٌ في الوسط",
        )
        assert treasury.balances["A"] == 1000  # عُوِّض
        assert treasury.balances["B"] == 600   # لم يُعوَّض ومُعلَن
        assert outcome.residual_signatures == (SIG_CREDIT,)

    def test_applied_effect_without_compensator_is_irreversible(self, tmp_path: Path):
        """أثرٌ مُطبَّقٌ خارجَ الخطّةِ -> `IRREVERSIBLE`، ولا يُزعَمُ عكسُه."""
        treasury = _Treasury(A=1000, B=500)
        contract = _contract()
        plan = _plan_for(contract, treasury)
        guard = _guard(tmp_path)
        outcome = guard.compensate(
            contract=contract,
            plan=plan,
            operation_key=_key(),
            applied_signatures=(SIG_DEBIT, "EXTERNAL:treasury/tx-77/swift"),
            reason="أثرٌ خارجَ الخطّة",
        )
        assert outcome.status is CompensationStatus.IRREVERSIBLE
        assert outcome.state_is_clean is False
        assert outcome.requires_human is True
        # لم يُستدعَ أيُّ معوّض: لا عكسَ جزئيٌّ في حالةٍ لا تُعكَس
        assert treasury.balances == {"A": 1000, "B": 500}

    def test_status_flags_are_not_cosmetic(self):
        """`state_is_clean` و`requires_human` عقدٌ سلوكيٌّ لا زخرفة."""
        assert CompensationStatus.COMPENSATED.state_is_clean is True
        assert CompensationStatus.NOT_REQUIRED.state_is_clean is True
        for bad in (
            CompensationStatus.PARTIALLY_COMPENSATED,
            CompensationStatus.COMPENSATION_FAILED,
            CompensationStatus.IRREVERSIBLE,
        ):
            assert bad.state_is_clean is False
            assert bad.requires_human is True
        assert CompensationStatus.PENDING.requires_human is False

    def test_every_status_has_arabic(self):
        """لا حالةَ بلا اسمٍ مقروء."""
        for status in CompensationStatus:
            assert status.arabic

    def test_outstanding_debt_lists_unclean_only(self, tmp_path: Path):
        """دَينُ الدولةِ = ما لم يرجع، لا كلُّ ما جرى."""
        treasury = _Treasury(A=1000, B=500)
        contract = _contract()
        guard = _guard(tmp_path)

        clean_plan = _plan_for(contract, treasury)
        guard.compensate(
            contract=contract,
            plan=clean_plan,
            operation_key=_key("clean"),
            applied_signatures=(SIG_DEBIT,),
            reason="ينجح",
        )

        def broken() -> None:
            raise RuntimeError("تعذّر")

        dirty_plan = bind_compensation_plan(
            contract=contract,
            compensators=(
                Compensator(effect_signature=SIG_DEBIT, apply=broken),
                Compensator(effect_signature=SIG_CREDIT, apply=broken),
                Compensator(effect_signature=SIG_SEAL, apply=broken),
            ),
        )
        guard.compensate(
            contract=contract,
            plan=dirty_plan,
            operation_key=_key("dirty"),
            applied_signatures=(SIG_CREDIT,),
            reason="يفشل",
        )

        debt = guard.outstanding_debt()
        assert len(debt) == 1
        assert debt[0].operation_key == "treasury:dirty"


# ─────────────────────────────────────────────────────────────────────────────
# 4. التعويضُ ذرّيٌّ بذاتِه
# ─────────────────────────────────────────────────────────────────────────────


class TestCompensationIsItselfIdempotent:
    """تعويضٌ مرّتين = تعويضٌ واحد. وإلّا صارَ العلاجُ داءً."""

    def test_compensation_id_is_content_derived(self):
        """هويّةُ التعويضِ من مضمونِه لا من عدّاد."""
        a = compute_compensation_id(
            contract_id="EC-1", operation_key="treasury:x", applied_signatures=(SIG_DEBIT,)
        )
        b = compute_compensation_id(
            contract_id="EC-1", operation_key="treasury:x", applied_signatures=(SIG_DEBIT,)
        )
        c = compute_compensation_id(
            contract_id="EC-1", operation_key="treasury:x", applied_signatures=(SIG_CREDIT,)
        )
        assert a == b
        assert a != c
        assert a.startswith("CMP-")

    def test_repeated_compensate_does_not_double_reverse(self, tmp_path: Path):
        """استدعاءُ التعويضِ مرّتين لا يعكسُ الأثرَ مرّتين."""
        treasury = _Treasury(A=900, B=600)
        contract = _contract()
        plan = _plan_for(contract, treasury)
        guard = _guard(tmp_path)

        for _ in range(4):
            guard.compensate(
                contract=contract,
                plan=plan,
                operation_key=_key(),
                applied_signatures=(SIG_DEBIT, SIG_CREDIT),
                reason="تكرارٌ متعمَّد",
            )

        assert treasury.balances == {"A": 1000, "B": 500}

    def test_concurrent_compensation_reverses_once(self, tmp_path: Path):
        """أربعةُ طلباتِ تعويضٍ متزامنة -> عكسٌ واحد."""
        treasury = _Treasury(A=900, B=600)
        contract = _contract()
        lock = threading.Lock()
        counter = {"n": 0}

        def undo_debit() -> None:
            with lock:
                counter["n"] += 1
                treasury.credit("A", 100)

        plan = bind_compensation_plan(
            contract=contract,
            compensators=(
                Compensator(effect_signature=SIG_DEBIT, apply=undo_debit),
                Compensator(effect_signature=SIG_CREDIT, apply=lambda: None),
                Compensator(effect_signature=SIG_SEAL, apply=lambda: None),
            ),
        )
        guard = _guard(tmp_path)
        # تعويضٌ أوّلٌ يُغلِقُ السجلّ، ثمّ محاولاتٌ متزامنةٌ تُعيدُ الحصيلةَ نفسَها
        guard.compensate(
            contract=contract,
            plan=plan,
            operation_key=_key(),
            applied_signatures=(SIG_DEBIT,),
            reason="أوّل",
        )
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(
                pool.map(
                    lambda _: guard.compensate(
                        contract=contract,
                        plan=plan,
                        operation_key=_key(),
                        applied_signatures=(SIG_DEBIT,),
                        reason="متزامن",
                    ),
                    range(4),
                )
            )
        assert counter["n"] == 1
        assert treasury.balances["A"] == 1000

    def test_closed_record_is_returned_not_reexecuted(self, tmp_path: Path):
        """سجلٌّ مُغلَقٌ يُعادُ كما هو — الإعادةُ قراءةٌ لا تنفيذ."""
        treasury = _Treasury(A=900, B=600)
        contract = _contract()
        plan = _plan_for(contract, treasury)
        guard = _guard(tmp_path)
        first = guard.compensate(
            contract=contract, plan=plan, operation_key=_key(),
            applied_signatures=(SIG_DEBIT,), reason="أوّل",
        )
        second = guard.compensate(
            contract=contract, plan=plan, operation_key=_key(),
            applied_signatures=(SIG_DEBIT,), reason="ثانٍ",
        )
        assert first.record.compensation_id == second.record.compensation_id
        assert len(first.record.steps) == len(second.record.steps)


# ─────────────────────────────────────────────────────────────────────────────
# 5. السجلُّ: يبقى، ويُقرأ، ولا يُعدَّل
# ─────────────────────────────────────────────────────────────────────────────


class TestJournalDurability:
    """سجلُّ التعويضِ أثرُ تدقيقٍ لا مذكّرةٌ عابرة."""

    def test_journal_survives_restart(self, tmp_path: Path):
        """سجلٌّ جديدٌ على المسارِ نفسِه يقرأُ ما كتبَه سابقُه."""
        treasury = _Treasury(A=900, B=600)
        contract = _contract()
        plan = _plan_for(contract, treasury)
        guard = _guard(tmp_path)
        outcome = guard.compensate(
            contract=contract, plan=plan, operation_key=_key(),
            applied_signatures=(SIG_DEBIT,), reason="قبلَ إعادةِ التشغيل",
        )

        fresh = CompensationJournal(path=tmp_path / "compensation.json")
        reread = fresh.get(outcome.record.compensation_id)
        assert reread is not None
        assert reread.status is CompensationStatus.COMPENSATED
        assert reread.compensated_signatures == (SIG_DEBIT,)

    def test_steps_are_append_only(self, tmp_path: Path):
        """الخطواتُ تُضافُ ولا تُستبدَل — والتسلسلُ يُقرأُ كاملًا."""
        treasury = _Treasury(A=900, B=600)
        contract = _contract()
        plan = _plan_for(contract, treasury)
        guard = _guard(tmp_path)
        outcome = guard.compensate(
            contract=contract, plan=plan, operation_key=_key(),
            applied_signatures=(SIG_DEBIT, SIG_CREDIT), reason="تسلسل",
        )
        steps = outcome.record.steps
        # بدءٌ + (إعلانٌ قبلَ كلِّ معوّض + تسجيلٌ بعدَه) × 2 + ختام
        assert len(steps) == 6
        assert all("at" in s for s in steps)
        announced = [s["compensating"] for s in steps if "compensating" in s]
        assert announced == [SIG_CREDIT, SIG_DEBIT]

    def test_step_written_before_compensator_runs(self, tmp_path: Path):
        """الإعلانُ يسبقُ الفعل: لو انقطعتِ العمليّةُ بقيَ الأثرُ مُعلَنًا."""
        contract = _contract()
        journal = CompensationJournal(path=tmp_path / "compensation.json")
        guard = CompensationGuard(
            journal=journal,
            idempotency=IdempotencyGuard(
                ledger=IdempotencyLedger(path=tmp_path / "idempotency.json")
            ),
        )
        seen: dict[str, Any] = {}

        comp_id = compute_compensation_id(
            contract_id=contract.contract_id,
            operation_key=_key().composite,
            applied_signatures=(SIG_DEBIT,),
        )

        def undo() -> None:
            # وقتَ تنفيذِ المعوّضِ يجبُ أن يكونَ إعلانُه مكتوبًا على القرصِ فعلًا
            on_disk = CompensationJournal(path=tmp_path / "compensation.json").get(comp_id)
            seen["announced"] = any(
                s.get("compensating") == SIG_DEBIT for s in (on_disk.steps if on_disk else [])
            )

        plan = bind_compensation_plan(
            contract=contract,
            compensators=(
                Compensator(effect_signature=SIG_DEBIT, apply=undo),
                Compensator(effect_signature=SIG_CREDIT, apply=lambda: None),
                Compensator(effect_signature=SIG_SEAL, apply=lambda: None),
            ),
        )
        guard.compensate(
            contract=contract, plan=plan, operation_key=_key(),
            applied_signatures=(SIG_DEBIT,), reason="إعلانٌ قبلَ الفعل",
        )
        assert seen["announced"] is True

    def test_corrupted_journal_raises(self, tmp_path: Path):
        """ملفٌّ تالفٌ = استثناءٌ صريح، لا ابتلاعٌ صامت."""
        path = tmp_path / "compensation.json"
        path.write_text("{ليس JSON", encoding="utf-8")
        with pytest.raises(CompensationError, match="تالف"):
            CompensationJournal(path=path).all_records()

    def test_step_on_missing_record_raises(self, tmp_path: Path):
        """خطوةٌ على سجلٍّ غيرِ موجودٍ مرفوضة."""
        journal = CompensationJournal(path=tmp_path / "compensation.json")
        with pytest.raises(CompensationError, match="لا سجلَّ"):
            journal.step(
                compensation_id="CMP-ghost",
                status=CompensationStatus.IN_PROGRESS,
                entry={"note": "لا شيء"},
            )

    def test_record_round_trips_through_json(self, tmp_path: Path):
        """السجلُّ يُكتَبُ ويُقرَأُ بلا فقدِ حقل."""
        treasury = _Treasury(A=900, B=600)
        contract = _contract()
        plan = _plan_for(contract, treasury)
        guard = _guard(tmp_path)
        outcome = guard.compensate(
            contract=contract, plan=plan, operation_key=_key(),
            applied_signatures=(SIG_DEBIT,), reason="دورةٌ كاملة",
        )
        raw = json.loads((tmp_path / "compensation.json").read_text(encoding="utf-8"))
        stored = raw[outcome.record.compensation_id]
        assert stored["contract_id"] == contract.contract_id
        assert stored["operation_key"] == "treasury:settle-77"
        assert stored["reason"] == "دورةٌ كاملة"
        assert stored["closed_at"]


# ─────────────────────────────────────────────────────────────────────────────
# 6. التكاملُ مع 1H — لا سجلَّ موازٍ ولا حقيقةٌ ثانية
# ─────────────────────────────────────────────────────────────────────────────


class TestIntegrationWithIdempotency:
    """التعويضُ يُحدِّثُ سجلَّ الذرّيّةِ القائمَ ولا يُنشئُ حقيقةً ثانية."""

    def test_clean_compensation_clears_recovery_required(self, tmp_path: Path):
        """بعدَ عكسٍ كاملٍ لا تبقى العمليّةُ «تتطلّبُ استعادةً يدويّة»."""
        treasury = _Treasury(A=1000, B=500)
        seal: dict[str, bool] = {}
        contract = _contract()
        plan = _plan_for(contract, treasury, seal=seal)
        guard = _guard(tmp_path)

        with pytest.raises(CompensationRequired):
            guard.run_compensated_transaction(
                contract=contract, plan=plan, key=_key(),
                fingerprint=_fingerprint(contract),
                apply_effect=_applier(treasury, seal, fail_on=SIG_SEAL),
            )

        record = guard.idempotency.get_status(_key())
        assert record is not None
        assert record.status is OperationStatus.FAILED_RETRYABLE
        assert record.applied_effect_signatures == ()

    def test_retry_after_clean_compensation_reapplies_everything(self, tmp_path: Path):
        """بعدَ العكسِ الكامل، إعادةُ المحاولةِ تُطبِّقُ العمليّةَ من أوّلِها مرّةً واحدة."""
        treasury = _Treasury(A=1000, B=500)
        seal: dict[str, bool] = {}
        contract = _contract()
        plan = _plan_for(contract, treasury, seal=seal)
        guard = _guard(tmp_path)

        with pytest.raises(CompensationRequired):
            guard.run_compensated_transaction(
                contract=contract, plan=plan, key=_key(),
                fingerprint=_fingerprint(contract),
                apply_effect=_applier(treasury, seal, fail_on=SIG_SEAL),
            )
        assert treasury.balances == {"A": 1000, "B": 500}

        result = guard.run_compensated_transaction(
            contract=contract, plan=plan, key=_key(),
            fingerprint=_fingerprint(contract),
            apply_effect=_applier(treasury, seal),
        )
        assert result.status is OperationStatus.SUCCEEDED
        assert treasury.balances == {"A": 900, "B": 600}
        assert seal == {"sealed": True}

    def test_unclean_compensation_leaves_recovery_required(self, tmp_path: Path):
        """عكسٌ ناقص -> السجلُّ يبقى `RECOVERY_REQUIRED`، ولا تُبيَّضُ الصفحة."""
        treasury = _Treasury(A=1000, B=500)
        seal: dict[str, bool] = {}
        contract = _contract()

        def broken() -> None:
            raise RuntimeError("المعوّضُ تعذّر")

        plan = bind_compensation_plan(
            contract=contract,
            compensators=(
                Compensator(effect_signature=SIG_DEBIT, apply=broken),
                Compensator(effect_signature=SIG_CREDIT, apply=broken),
                Compensator(effect_signature=SIG_SEAL, apply=lambda: None),
            ),
        )
        guard = _guard(tmp_path)
        with pytest.raises(CompensationRequired):
            guard.run_compensated_transaction(
                contract=contract, plan=plan, key=_key(),
                fingerprint=_fingerprint(contract),
                apply_effect=_applier(treasury, seal, fail_on=SIG_SEAL),
            )

        record = guard.idempotency.get_status(_key())
        assert record is not None
        assert record.status is OperationStatus.RECOVERY_REQUIRED
        assert set(record.applied_effect_signatures) == {SIG_DEBIT, SIG_CREDIT}

    def test_duplicate_successful_transaction_is_replay(self, tmp_path: Path):
        """الطلبُ المكرَّرُ بعدَ النجاحِ إعادةٌ لا تنفيذ — ذرّيّةُ 1H محفوظة."""
        treasury = _Treasury(A=1000, B=500)
        seal: dict[str, bool] = {}
        contract = _contract()
        plan = _plan_for(contract, treasury, seal=seal)
        guard = _guard(tmp_path)

        first = guard.run_compensated_transaction(
            contract=contract, plan=plan, key=_key(),
            fingerprint=_fingerprint(contract),
            apply_effect=_applier(treasury, seal),
        )
        second = guard.run_compensated_transaction(
            contract=contract, plan=plan, key=_key(),
            fingerprint=_fingerprint(contract),
            apply_effect=_applier(treasury, seal),
        )
        assert first.is_replay is False
        assert second.is_replay is True
        assert treasury.balances == {"A": 900, "B": 600}

    def test_plan_of_another_contract_rejected(self, tmp_path: Path):
        """لا تُستعارُ خطّةُ عقدٍ لعقدٍ آخر."""
        treasury = _Treasury(A=1000, B=500)
        contract = _contract()
        plan = _plan_for(contract, treasury)
        other = bind_contract(
            actor="another-minister",
            action=ACTION,
            target=TARGET,
            declared_effects=(
                SovereignEffect(kind=EffectKind.WRITE, resource=f"{TARGET}/debit"),
            ),
        )
        guard = _guard(tmp_path)
        assert other.contract_id != contract.contract_id
        with pytest.raises(CompensationScopeError, match="لا تُستعارُ"):
            guard.compensate(
                contract=other, plan=plan, operation_key=_key(),
                applied_signatures=(SIG_DEBIT,), reason="خطّةٌ مستعارة",
            )
        with pytest.raises(CompensationScopeError):
            guard.run_compensated_transaction(
                contract=other, plan=plan, key=_key(),
                fingerprint=_fingerprint(other),
                apply_effect=lambda _sig: None,
            )


# ─────────────────────────────────────────────────────────────────────────────
# 7. الحارسُ بلا تجاوز — كالجدارِ في 1G وحارسِ 1H
# ─────────────────────────────────────────────────────────────────────────────


class TestNoBypass:
    """لا `force` ولا `bypass` ولا `override`، ولا سلطةَ تُصنَعُ في التعويض."""

    def test_no_bypass_parameter_anywhere(self):
        """لا مَعلَمَ تجاوزٍ في أيِّ دالّةٍ عامّة."""
        import inspect

        from core.sovereignty import compensation as mod

        forbidden = {"force", "bypass", "override", "skip_checks", "unsafe"}
        for name, obj in vars(mod).items():
            if name.startswith("_"):
                continue
            targets = []
            if inspect.isfunction(obj):
                targets.append(obj)
            elif inspect.isclass(obj):
                targets.extend(
                    m for _n, m in inspect.getmembers(obj, inspect.isfunction)
                    if not _n.startswith("_")
                )
            for fn in targets:
                params = set(inspect.signature(fn).parameters)
                assert not (params & forbidden), f"{name}.{fn.__name__} فيه مَعلَمُ تجاوز"

    def test_compensation_does_not_issue_permits(self):
        """التعويضُ لا يُصدِرُ إذنًا ولا يستدعي البوّابة."""
        source = Path("core/sovereignty/compensation.py").read_text(encoding="utf-8")
        assert "issue_permit" not in source
        assert "SovereignGateway" not in source
        assert "PolicyEnforcementPoint" not in source

    def test_compensation_does_not_import_gateway(self):
        """اتّجاهُ الاعتمادِ أحاديّ: التعويضُ فوقَ العقدِ والذرّيّةِ لا فوقَ البوّابة."""
        source = Path("core/sovereignty/compensation.py").read_text(encoding="utf-8")
        assert "from core.sovereignty.gateway" not in source
        assert "from core.sovereignty.enforcement" not in source

    def test_prior_layers_untouched(self):
        """لا هدمَ: طبقاتُ 1E و1F و1G و1H كما هي."""
        for module in ("contract", "enforcement", "jurisdiction", "idempotency"):
            source = Path(f"core/sovereignty/{module}.py").read_text(encoding="utf-8")
            assert "compensation" not in source, f"{module}.py اعتمدَ على التعويض"


# ─────────────────────────────────────────────────────────────────────────────
# 8. أدواتُ القراءة
# ─────────────────────────────────────────────────────────────────────────────


class TestReadHelpers:
    """القراءةُ للتدقيقِ لا للتنفيذ."""

    def test_effects_of_rebuilds_effects(self):
        """بصمةٌ -> أثرٌ مقروء."""
        effects = effects_of((SIG_DEBIT, SIG_SEAL))
        assert effects[0].kind is EffectKind.WRITE
        assert effects[0].resource == f"{TARGET}/debit"
        assert effects[1].kind is EffectKind.CREATE

    def test_effects_of_rejects_unknown_kind(self):
        """بصمةٌ بنوعٍ غيرِ معروفٍ تُرفَض."""
        with pytest.raises(CompensationError, match="غيرُ معروفة"):
            effects_of(("MAGIC:treasury/x",))

    def test_exported_names_resolve_from_package(self):
        """أسماءُ 1I تُحَلُّ من `core.sovereignty` كباقي الطبقات."""
        import core.sovereignty as pkg

        for name in (
            "CompensationGuard",
            "CompensationJournal",
            "CompensationPlan",
            "CompensationStatus",
            "Compensator",
            "bind_compensation_plan",
        ):
            assert getattr(pkg, name) is not None
            assert name in pkg.__all__

    def test_plan_covered_signatures(self):
        """الخطّةُ تُعلِنُ ما تُغطّيه."""
        treasury = _Treasury(A=1000, B=500)
        contract = _contract()
        plan: CompensationPlan = _plan_for(contract, treasury)
        assert plan.covered_signatures == {SIG_DEBIT, SIG_CREDIT, SIG_SEAL}
