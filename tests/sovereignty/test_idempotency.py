"""الهدف: اختباراتُ حارسِ الذرّيّةِ — إثباتٌ أنّ الأثرَ واحدٌ مهما تكررَ الطلب.

النطاق: `tests/sovereignty/` — اختباراتُ `IdempotencyGuard` و`IdempotencyLedger`.
المالك: ديوان التدقيق
تاريخ الإنشاء: 2026-08-18
تاريخ آخر تعديل: 2026-08-18
tags: test, idempotency, concurrency, retry, recovery
"""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import pytest

from core.sovereignty.idempotency import (
    IdempotencyConflictError,
    IdempotencyError,
    IdempotencyGuard,
    IdempotencyKey,
    IdempotencyKeyReuseError,
    IdempotencyLedger,
    OperationNotRecoverableError,
    OperationResult,
    OperationStatus,
    compute_fingerprint,
)

# ─────────────────────────────────────────────────────────────────────────────
# عواملُ مساعدة
# ─────────────────────────────────────────────────────────────────────────────

def _make_key(scope: str = "treasury", value: str = "tx-001") -> IdempotencyKey:
    return IdempotencyKey(scope=scope, value=value)


def _make_fingerprint(**kwargs: Any) -> str:
    defaults: dict[str, Any] = {
        "scope": "treasury",
        "action": "transfer",
        "target": "treasury/account-A",
        "effect_signatures": ("TRANSFER:treasury/account-A",),
        "actor": "minister",
        "payload_digest": "",
    }
    defaults.update(kwargs)
    return compute_fingerprint(**defaults)


def _make_ledger(tmp_path: Path) -> IdempotencyLedger:
    return IdempotencyLedger(path=tmp_path / "idempotency.json")


def _make_guard(tmp_path: Path) -> IdempotencyGuard:
    return IdempotencyGuard(ledger=_make_ledger(tmp_path))


# ─────────────────────────────────────────────────────────────────────────────
# 1. اختباراتُ المفتاحِ والبصمة
# ─────────────────────────────────────────────────────────────────────────────

class TestIdempotencyKey:
    """مفتاحُ الذرّيّة — نطاقٌ وقيمة، لا مفتاحٌ بلا هويّة."""

    def test_key_requires_scope(self):
        """مفتاحٌ بلا نطاقٍ مرفوض."""
        with pytest.raises(IdempotencyError, match="نطاق"):
            IdempotencyKey(scope="", value="tx-001")

    def test_key_requires_value(self):
        """مفتاحٌ بلا قيمةٍ مرفوض."""
        with pytest.raises(IdempotencyError, match="قيمة"):
            IdempotencyKey(scope="treasury", value="")

    def test_composite_format(self):
        """الشكلُ المركَّبُ `scope:value`."""
        key = IdempotencyKey(scope="treasury", value="tx-001")
        assert key.composite == "treasury:tx-001"

    def test_same_key_different_scope_are_different(self):
        """المفتاحُ نفسُه في نطاقينِ مختلفينِ يُشيرُ إلى عمليّتينِ مختلفتين."""
        k1 = IdempotencyKey(scope="treasury", value="tx-001")
        k2 = IdempotencyKey(scope="judiciary", value="tx-001")
        assert k1.composite != k2.composite


class TestFingerprint:
    """بصمةُ العمليّة — ما يجعلُ عمليّتين «هما العمليّةُ نفسُها»."""

    def test_same_inputs_same_fingerprint(self):
        """نفسُ المدخلات = نفسُ البصمة."""
        fp1 = _make_fingerprint()
        fp2 = _make_fingerprint()
        assert fp1 == fp2

    def test_different_action_different_fingerprint(self):
        """فعلٌ مختلف = بصمةٌ مختلفة."""
        fp1 = _make_fingerprint(action="transfer")
        fp2 = _make_fingerprint(action="deposit")
        assert fp1 != fp2

    def test_different_target_different_fingerprint(self):
        """هدفٌ مختلف = بصمةٌ مختلفة."""
        fp1 = _make_fingerprint(target="treasury/account-A")
        fp2 = _make_fingerprint(target="treasury/account-B")
        assert fp1 != fp2

    def test_different_effects_different_fingerprint(self):
        """آثارٌ مختلفة = بصمةٌ مختلفة."""
        fp1 = _make_fingerprint(effect_signatures=("TRANSFER:A",))
        fp2 = _make_fingerprint(effect_signatures=("TRANSFER:B",))
        assert fp1 != fp2

    def test_fingerprint_starts_with_prefix(self):
        """البصمةُ تبدأُ بـ`FP-`."""
        fp = _make_fingerprint()
        assert fp.startswith("FP-")


# ─────────────────────────────────────────────────────────────────────────────
# 2. اختباراتُ السجلِّ والحالات
# ─────────────────────────────────────────────────────────────────────────────

class TestOperationStatus:
    """حالاتُ العمليّة — كلُّها معرّفة، لا `UNKNOWN`."""

    def test_succeeded_is_terminal(self):
        assert OperationStatus.SUCCEEDED.is_terminal

    def test_failed_final_is_terminal(self):
        assert OperationStatus.FAILED_FINAL.is_terminal

    def test_running_not_terminal(self):
        assert not OperationStatus.RUNNING.is_terminal

    def test_interrupted_is_recoverable(self):
        assert OperationStatus.INTERRUPTED.is_recoverable

    def test_failed_retryable_is_recoverable(self):
        assert OperationStatus.FAILED_RETRYABLE.is_recoverable

    def test_succeeded_not_recoverable(self):
        assert not OperationStatus.SUCCEEDED.is_recoverable

    def test_no_unknown_status(self):
        """لا توجد حالة `UNKNOWN` في النظام."""
        statuses = [s.value for s in OperationStatus]
        assert "UNKNOWN" not in statuses


class TestLedgerReserve:
    """الحجزُ على القرص — قبلَ التنفيذ."""

    def test_reserve_creates_record(self, tmp_path):
        """الحجزُ يُنشئُ سجلًّا بحالة `RESERVED`."""
        ledger = _make_ledger(tmp_path)
        key = _make_key()
        fp = _make_fingerprint()
        record = ledger.reserve(key=key, fingerprint=fp)
        assert record.status is OperationStatus.RESERVED
        assert record.fingerprint == fp

    def test_reserve_same_key_same_fingerprint_returns_existing(self, tmp_path):
        """إعادةُ الحجزِ بنفسِ المفتاحِ والبصمةِ تُرجِعُ السجلَّ القائم."""
        ledger = _make_ledger(tmp_path)
        key = _make_key()
        fp = _make_fingerprint()
        r1 = ledger.reserve(key=key, fingerprint=fp)
        r2 = ledger.reserve(key=key, fingerprint=fp)
        assert r1.fingerprint == r2.fingerprint
        assert r1.status == r2.status

    def test_reserve_same_key_different_fingerprint_rejected(self, tmp_path):
        """إعادةُ الحجزِ ببصمةٍ مختلفة = إعادةُ استعمالٍ خاطئة."""
        ledger = _make_ledger(tmp_path)
        key = _make_key()
        fp1 = _make_fingerprint(action="transfer")
        fp2 = _make_fingerprint(action="deposit")
        ledger.reserve(key=key, fingerprint=fp1)
        with pytest.raises(IdempotencyKeyReuseError, match="بصمةٍ مختلفة"):
            ledger.reserve(key=key, fingerprint=fp2)


class TestLedgerTransition:
    """انتقالُ الحالات — أحاديٌّ مسجَّل."""

    def test_mark_running(self, tmp_path):
        ledger = _make_ledger(tmp_path)
        key = _make_key()
        fp = _make_fingerprint()
        ledger.reserve(key=key, fingerprint=fp)
        record = ledger.mark_running(key=key, attempt={"n": 1})
        assert record.status is OperationStatus.RUNNING
        assert len(record.attempts) == 1

    def test_mark_succeeded(self, tmp_path):
        ledger = _make_ledger(tmp_path)
        key = _make_key()
        fp = _make_fingerprint()
        ledger.reserve(key=key, fingerprint=fp)
        record = ledger.mark_succeeded(
            key=key,
            result_digest="RD-abc123",
            applied_effect_signatures=("TRANSFER:A",),
        )
        assert record.status is OperationStatus.SUCCEEDED
        assert record.result_digest == "RD-abc123"
        assert record.succeeded_at is not None

    def test_no_transition_from_terminal(self, tmp_path):
        """لا انتقالَ من النهائي."""
        ledger = _make_ledger(tmp_path)
        key = _make_key()
        fp = _make_fingerprint()
        ledger.reserve(key=key, fingerprint=fp)
        ledger.mark_running(key=key)
        ledger.mark_succeeded(key=key, result_digest="RD-1")
        with pytest.raises(IdempotencyError, match="نهائي"):
            ledger.mark_running(key=key)

    def test_mark_failed_retryable(self, tmp_path):
        ledger = _make_ledger(tmp_path)
        key = _make_key()
        fp = _make_fingerprint()
        ledger.reserve(key=key, fingerprint=fp)
        record = ledger.mark_failed(key=key, reason="timeout", retryable=True)
        assert record.status is OperationStatus.FAILED_RETRYABLE
        assert record.failure_reason == "timeout"

    def test_mark_failed_final(self, tmp_path):
        ledger = _make_ledger(tmp_path)
        key = _make_key()
        fp = _make_fingerprint()
        ledger.reserve(key=key, fingerprint=fp)
        record = ledger.mark_failed(key=key, reason="permanent", retryable=False)
        assert record.status is OperationStatus.FAILED_FINAL

    def test_mark_interrupted(self, tmp_path):
        ledger = _make_ledger(tmp_path)
        key = _make_key()
        fp = _make_fingerprint()
        ledger.reserve(key=key, fingerprint=fp)
        record = ledger.mark_interrupted(key=key)
        assert record.status is OperationStatus.INTERRUPTED

    def test_recover_interrupted(self, tmp_path):
        ledger = _make_ledger(tmp_path)
        key = _make_key()
        fp = _make_fingerprint()
        ledger.reserve(key=key, fingerprint=fp)
        ledger.mark_interrupted(key=key)
        record = ledger.recover(key=key)
        assert record.status is OperationStatus.RECOVERY_REQUIRED

    def test_recover_non_recoverable_rejected(self, tmp_path):
        """استعادةُ عمليّةٍ ناجحةٍ مرفوضة."""
        ledger = _make_ledger(tmp_path)
        key = _make_key()
        fp = _make_fingerprint()
        ledger.reserve(key=key, fingerprint=fp)
        ledger.mark_running(key=key)
        ledger.mark_succeeded(key=key, result_digest="RD-1")
        with pytest.raises(OperationNotRecoverableError):
            ledger.recover(key=key)


# ─────────────────────────────────────────────────────────────────────────────
# 3. اختباراتُ الحارس — التنفيذُ مرّةً واحدة
# ─────────────────────────────────────────────────────────────────────────────

class TestGuardRunOnce:
    """الحارسُ ينفّذُ مرّةً واحدة — أو يُعيدُ النتيجة."""

    def test_first_execution_succeeds(self, tmp_path):
        """الطلبُ الأوّل: تنفيذٌ حقيقيّ، نتيجةٌ، لا إعادة."""
        guard = _make_guard(tmp_path)
        key = _make_key()
        fp = _make_fingerprint()
        counter = {"n": 0}

        def execute() -> str:
            counter["n"] += 1
            return "result-001"

        result = guard.run_once(key=key, fingerprint=fp, execute=execute)
        assert result.succeeded
        assert not result.is_replay
        assert result.value == "result-001"
        assert counter["n"] == 1

    def test_sequential_duplicate_returns_replay(self, tmp_path):
        """الطلبُ نفسُه مرّتين: أثرٌ واحد، والثانيةُ إعادة."""
        guard = _make_guard(tmp_path)
        key = _make_key()
        fp = _make_fingerprint()
        counter = {"n": 0}

        def execute() -> str:
            counter["n"] += 1
            return "result-001"

        r1 = guard.run_once(key=key, fingerprint=fp, execute=execute)
        r2 = guard.run_once(key=key, fingerprint=fp, execute=execute)

        assert r1.succeeded
        assert r2.succeeded
        assert not r1.is_replay
        assert r2.is_replay
        assert counter["n"] == 1  # نُفِّذ مرّةً واحدة فقط

    def test_success_then_retry_no_extra_effect(self, tmp_path):
        """نجاحٌ ثمّ retry: لا أثرٍ إضافيّ."""
        guard = _make_guard(tmp_path)
        key = _make_key()
        fp = _make_fingerprint()
        counter = {"n": 0}

        def execute() -> int:
            counter["n"] += 1
            return 42

        for _ in range(5):
            guard.run_once(key=key, fingerprint=fp, execute=execute)

        assert counter["n"] == 1

    def test_failed_then_retry_no_double_effect(self, tmp_path):
        """فشلٌ ثمّ retry: لا أثرٍ مزدوج."""
        guard = _make_guard(tmp_path)
        key = _make_key()
        fp = _make_fingerprint()
        call_count = {"n": 0}

        def execute() -> str:
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("first attempt fails")
            return "success-on-retry"

        # المحاولة الأولى تفشل
        with pytest.raises(IdempotencyError, match="فشلت"):
            guard.run_once(key=key, fingerprint=fp, execute=execute)

        assert call_count["n"] == 1
        assert guard.get_status(key) is not None
        assert guard.get_status(key).status is OperationStatus.FAILED_RETRYABLE

        # الاستعادةُ ثمّ إعادةُ المحاولة
        guard.recover(key=key)
        r2 = guard.run_once(key=key, fingerprint=fp, execute=execute)
        assert r2.succeeded
        assert call_count["n"] == 2  # مرّتان فقط لا ثلاث

    def test_different_key_different_execution(self, tmp_path):
        """مفاتيحُ مختلفة = تنفيذٌ مختلف."""
        guard = _make_guard(tmp_path)
        counter = {"n": 0}

        def execute() -> str:
            counter["n"] += 1
            return f"result-{counter['n']}"

        k1 = IdempotencyKey(scope="treasury", value="tx-A")
        k2 = IdempotencyKey(scope="treasury", value="tx-B")
        fp1 = _make_fingerprint()
        fp2 = _make_fingerprint(action="deposit")

        r1 = guard.run_once(key=k1, fingerprint=fp1, execute=execute)
        r2 = guard.run_once(key=k2, fingerprint=fp2, execute=execute)

        assert counter["n"] == 2
        assert r1.value != r2.value

    def test_changed_fingerprint_rejected(self, tmp_path):
        """بصمةٌ مختلفة على المفتاحِ نفسِه = إعادةُ استعمالٍ خاطئة."""
        guard = _make_guard(tmp_path)
        key = _make_key()
        fp1 = _make_fingerprint(action="transfer")
        fp2 = _make_fingerprint(action="deposit")

        guard.run_once(
            key=key, fingerprint=fp1, execute=lambda: "r1",
        )
        with pytest.raises(IdempotencyKeyReuseError):
            guard.run_once(
                key=key, fingerprint=fp2, execute=lambda: "r2",
            )

    def test_cross_scope_key_no_collision(self, tmp_path):
        """المفتاحُ نفسُه في نطاقينِ مختلفينِ لا يتصادم."""
        guard = _make_guard(tmp_path)
        counter = {"n": 0}

        def execute() -> str:
            counter["n"] += 1
            return f"r{counter['n']}"

        k1 = IdempotencyKey(scope="treasury", value="tx-001")
        k2 = IdempotencyKey(scope="judiciary", value="tx-001")
        fp1 = compute_fingerprint(
            scope="treasury", action="transfer", target="A",
            effect_signatures=("TRANSFER:A",),
        )
        fp2 = compute_fingerprint(
            scope="judiciary", action="adjudicate", target="case-1",
            effect_signatures=("CREATE:case-1",),
        )

        r1 = guard.run_once(key=k1, fingerprint=fp1, execute=execute)
        r2 = guard.run_once(key=k2, fingerprint=fp2, execute=execute)

        assert counter["n"] == 2
        assert r1.succeeded and r2.succeeded


# ─────────────────────────────────────────────────────────────────────────────
# 4. اختباراتُ التزامن
# ─────────────────────────────────────────────────────────────────────────────

class TestConcurrency:
    """تزامنٌ حقيقيّ: نفسُ الطلبِ في عمليّاتٍ متزامنة → أثرٌ واحد."""

    def test_concurrent_duplicate_single_effect(self, tmp_path):
        """أربعةُ طلباتٍ متزامنة على المفتاحِ نفسِه: تنفيذٌ واحد."""
        guard = _make_guard(tmp_path)
        key = _make_key()
        fp = _make_fingerprint()
        counter = {"n": 0}
        lock = threading.Lock()

        def execute() -> str:
            with lock:
                counter["n"] += 1
            time.sleep(0.05)  # محاكاةُ عملٍ حقيقيّ
            return "shared-result"

        barrier = threading.Barrier(4)
        results: list[OperationResult] = []

        def worker():
            barrier.wait()
            r = guard.run_once(key=key, fingerprint=fp, execute=execute)
            results.append(r)

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(worker) for _ in range(4)]
            for f in as_completed(futures):
                f.result()

        # واحدٌ نُفّذ، والباقي إعادةٌ أو رُفض
        successful = [r for r in results if r.succeeded]
        assert len(successful) >= 1
        assert counter["n"] == 1  # تنفيذٌ واحد فقط

    def test_concurrent_different_keys_all_execute(self, tmp_path):
        """مفاتيحُ مختلفة في تزامن: كلُّها تُنفَّذ."""
        guard = _make_guard(tmp_path)
        counter = {"n": 0}
        lock = threading.Lock()

        def make_execute(idx: int):
            def execute() -> str:
                with lock:
                    counter["n"] += 1
                return f"r{idx}"
            return execute

        keys = [IdempotencyKey(scope="treasury", value=f"tx-{i}") for i in range(4)]
        fps = [
            compute_fingerprint(
                scope="treasury", action="transfer", target=f"A-{i}",
                effect_signatures=(f"TRANSFER:A-{i}",),
                payload_digest=f"payload-{i}",
            )
            for i in range(4)
        ]

        def worker(idx: int):
            guard.run_once(key=keys[idx], fingerprint=fps[idx], execute=make_execute(idx))

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(worker, i) for i in range(4)]
            for f in as_completed(futures):
                f.result()

        assert counter["n"] == 4  # كلُّها نُفِّذت


# ─────────────────────────────────────────────────────────────────────────────
# 5. اختباراتُ الثباتِ والاستعادة
# ─────────────────────────────────────────────────────────────────────────────

class TestPersistenceRestart:
    """الثباتُ على القرص: سجلٌّ جديدٌ يقرأُ ما كان."""

    def test_new_ledger_reads_prior_records(self, tmp_path):
        """سجلٌّ جديدٌ على الملفِّ نفسِه يرى السجلَّ السابق."""
        ledger1 = _make_ledger(tmp_path)
        key = _make_key()
        fp = _make_fingerprint()
        ledger1.reserve(key=key, fingerprint=fp)
        ledger1.mark_running(key=key)
        ledger1.mark_succeeded(key=key, result_digest="RD-001")

        # سجلٌّ جديد على الملفّ نفسه
        ledger2 = IdempotencyLedger(path=ledger1.path)
        record = ledger2.get(key)
        assert record is not None
        assert record.status is OperationStatus.SUCCEEDED
        assert record.result_digest == "RD-001"

    def test_new_guard_returns_replay_after_restart(self, tmp_path):
        """حارسٌ جديدٌ يُعيدُ النتيجةَ السابقة دون تنفيذ."""
        guard1 = _make_guard(tmp_path)
        key = _make_key()
        fp = _make_fingerprint()
        counter = {"n": 0}

        def execute() -> str:
            counter["n"] += 1
            return "persisted-result"

        guard1.run_once(key=key, fingerprint=fp, execute=execute)
        assert counter["n"] == 1

        # حارسٌ جديد على الملفّ نفسه
        guard2 = IdempotencyGuard(ledger=IdempotencyLedger(path=guard1.ledger.path))
        r2 = guard2.run_once(key=key, fingerprint=fp, execute=execute)
        assert r2.is_replay
        assert counter["n"] == 1  # لم يُنفَّذ ثانيةً

    def test_interrupted_record_survives_restart(self, tmp_path):
        """سجلٌّ منقطعٌ يبقى بعدَ إعادةِ التشغيل."""
        ledger = _make_ledger(tmp_path)
        key = _make_key()
        fp = _make_fingerprint()
        ledger.reserve(key=key, fingerprint=fp)
        ledger.mark_running(key=key)
        ledger.mark_interrupted(key=key)

        # محاكاةُ إعادةِ تشغيل
        ledger2 = IdempotencyLedger(path=ledger.path)
        record = ledger2.get(key)
        assert record is not None
        assert record.status is OperationStatus.INTERRUPTED

        # يمكنُ استعادتُه
        recovered = ledger2.recover(key=key)
        assert recovered.status is OperationStatus.RECOVERY_REQUIRED


# ─────────────────────────────────────────────────────────────────────────────
# 6. اختباراتُ الأثرِ الخارجيّ
# ─────────────────────────────────────────────────────────────────────────────

class TestExternalEffects:
    """الأثرُ الخارجيُّ لا يُلغى — لكنّه لا يتكرّر."""

    def test_external_effect_marked_in_record(self, tmp_path):
        """الأثرُ الخارجيُّ يُسجَّلُ في السجلّ."""
        guard = _make_guard(tmp_path)
        key = _make_key()
        fp = _make_fingerprint()

        result = guard.run_once(
            key=key, fingerprint=fp,
            execute=lambda: "external-sent",
            detect_external=lambda v: True,
        )
        assert result.succeeded
        assert result.record.has_external_effect is True

    def test_external_effect_retry_no_duplicate(self, tmp_path):
        """إعادةُ طلبٍ بأثرٍ خارجيّ: لا إرسالٌ ثانٍ."""
        guard = _make_guard(tmp_path)
        key = _make_key()
        fp = _make_fingerprint()
        send_counter = {"n": 0}

        def execute() -> str:
            send_counter["n"] += 1
            return "sent"

        guard.run_once(
            key=key, fingerprint=fp, execute=execute,
            detect_external=lambda v: True,
        )
        guard.run_once(
            key=key, fingerprint=fp, execute=execute,
            detect_external=lambda v: True,
        )
        assert send_counter["n"] == 1  # أُرسل مرّةً واحدة

    def test_non_external_not_marked(self, tmp_path):
        """أثرٌ داخليّ لا يُعلَّمُ كخارجيّ."""
        guard = _make_guard(tmp_path)
        key = _make_key()
        fp = _make_fingerprint()

        result = guard.run_once(
            key=key, fingerprint=fp,
            execute=lambda: "internal",
            detect_external=lambda v: False,
        )
        assert result.record.has_external_effect is False


# ─────────────────────────────────────────────────────────────────────────────
# 7. اختباراتُ سجلِّ التدقيق
# ─────────────────────────────────────────────────────────────────────────────

class TestAuditTrail:
    """السجلُّ يُثبتُ ما جرى — هويّةٌ، بصمةٌ، حالةٌ، نتيجة، محاولات."""

    def test_record_has_key_and_fingerprint(self, tmp_path):
        """السجلُّ يحملُ المفتاحَ والبصمة."""
        guard = _make_guard(tmp_path)
        key = _make_key()
        fp = _make_fingerprint()
        guard.run_once(key=key, fingerprint=fp, execute=lambda: "r")
        record = guard.get_status(key)
        assert record.key.composite == key.composite
        assert record.fingerprint == fp

    def test_record_has_status_and_result(self, tmp_path):
        """السجلُّ يحملُ الحالةَ والنتيجة."""
        guard = _make_guard(tmp_path)
        key = _make_key()
        fp = _make_fingerprint()
        guard.run_once(key=key, fingerprint=fp, execute=lambda: "result-42")
        record = guard.get_status(key)
        assert record.status is OperationStatus.SUCCEEDED
        assert record.result_digest is not None
        assert record.result_digest.startswith("RD-")

    def test_record_has_timestamps(self, tmp_path):
        """السجلُّ يحملُ وقتَ الحجزِ ووقتَ النجاح."""
        guard = _make_guard(tmp_path)
        key = _make_key()
        fp = _make_fingerprint()
        guard.run_once(key=key, fingerprint=fp, execute=lambda: "r")
        record = guard.get_status(key)
        assert record.reserved_at is not None
        assert record.succeeded_at is not None

    def test_record_has_attempt_history(self, tmp_path):
        """السجلُّ يحملُ تاريخَ المحاولات."""
        guard = _make_guard(tmp_path)
        key = _make_key()
        fp = _make_fingerprint()

        call_count = {"n": 0}

        def execute() -> str:
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("fail")
            return "ok"

        with pytest.raises(IdempotencyError):
            guard.run_once(key=key, fingerprint=fp, execute=execute)

        guard.recover(key=key)
        guard.run_once(key=key, fingerprint=fp, execute=execute)

        record = guard.get_status(key)
        assert len(record.attempts) >= 2  # محاولتانِ على الأقل
        assert record.status is OperationStatus.SUCCEEDED

    def test_record_applied_effects_tracked(self, tmp_path):
        """السجلُّ يحملُ بصماتِ الآثارِ المُطبَّقة."""
        guard = _make_guard(tmp_path)
        key = _make_key()
        fp = _make_fingerprint()
        effects = ("TRANSFER:treasury/account-A",)

        result = guard.run_once(
            key=key, fingerprint=fp,
            execute=lambda: {"effects": effects},
            extract_effect_signatures=lambda v: v["effects"],
        )
        assert result.record.applied_effect_signatures == effects

    def test_replay_does_not_modify_record(self, tmp_path):
        """الإعادةُ لا تُعدِّلُ السجلَّ التاريخيّ."""
        guard = _make_guard(tmp_path)
        key = _make_key()
        fp = _make_fingerprint()
        guard.run_once(key=key, fingerprint=fp, execute=lambda: "r1")
        before = guard.get_status(key)
        guard.run_once(key=key, fingerprint=fp, execute=lambda: "r2")
        after = guard.get_status(key)
        assert before.reserved_at == after.reserved_at
        assert before.succeeded_at == after.succeeded_at


# ─────────────────────────────────────────────────────────────────────────────
# 8. اختباراتُ سلامةِ الحارس
# ─────────────────────────────────────────────────────────────────────────────

class TestGuardIntegrity:
    """الحارسُ بلا تجاوز — لا `force` ولا `bypass`."""

    def test_guard_has_no_bypass_parameter(self):
        """لا يوجدُ `force`/`bypass`/`override` في توقيعِ `run_once`."""
        import inspect
        sig = inspect.signature(IdempotencyGuard.run_once)
        forbidden = {"force", "bypass", "override", "skip_check"}
        assert not (forbidden & set(sig.parameters))

    def test_guard_does_not_decide_authority(self):
        """الحارسُ لا يحملُ إشارةَ سلطةٍ ولا مفتاحَ توقيع."""
        import inspect
        # لا يستوردُ enforcement ولا gateway
        source = inspect.getsource(IdempotencyGuard)
        assert "issue_permit" not in source
        assert "SovereignGateway" not in source
        assert "private_key" not in source

    def test_ledger_persistence_on_disk(self, tmp_path):
        """السجلُّ مكتوبٌ على القرصِ لا في الذاكرة."""
        ledger = _make_ledger(tmp_path)
        key = _make_key()
        fp = _make_fingerprint()
        ledger.reserve(key=key, fingerprint=fp)
        assert ledger.path.exists()
        data = json.loads(ledger.path.read_text(encoding="utf-8"))
        assert key.composite in data

    def test_ledger_corrupted_file_raises(self, tmp_path):
        """ملفٌّ تالفٌ = استثناءٌ صريح، لا ابتلاعٌ صامت."""
        ledger = _make_ledger(tmp_path)
        ledger.path.parent.mkdir(parents=True, exist_ok=True)
        ledger.path.write_text("NOT JSON", encoding="utf-8")
        with pytest.raises(IdempotencyError, match="تالف"):
            ledger.get(_make_key())

    def test_ledger_count(self, tmp_path):
        """عددُ السجلاتِ في السجلّ."""
        ledger = _make_ledger(tmp_path)
        assert ledger.count() == 0
        ledger.reserve(key=_make_key(), fingerprint=_make_fingerprint())
        assert ledger.count() == 1
        ledger.reserve(
            key=IdempotencyKey(scope="other", value="k2"),
            fingerprint=_make_fingerprint(scope="other"),
        )
        assert ledger.count() == 2

    def test_ledger_all_records(self, tmp_path):
        """قراءةُ جميع السجلات."""
        ledger = _make_ledger(tmp_path)
        ledger.reserve(key=_make_key(), fingerprint=_make_fingerprint())
        records = ledger.all_records()
        assert len(records) == 1
        assert records[0].key.composite == "treasury:tx-001"

    def test_guard_conflict_on_running(self, tmp_path):
        """عمليّةٌ جاريةٌ ترفضُ عمليّةً ثانية على المفتاحِ نفسِه."""
        guard = _make_guard(tmp_path)
        key = _make_key()
        fp = _make_fingerprint()
        guard.ledger.reserve(key=key, fingerprint=fp)
        guard.ledger.mark_running(key=key)

        # محاولةُ تشغيلٍ على مفتاحٍ جارٍ
        with pytest.raises(IdempotencyConflictError, match="جارية"):
            guard.run_once(key=key, fingerprint=fp, execute=lambda: "x")

    def test_guard_recoverable_then_retry(self, tmp_path):
        """عمليّةٌ فاشلةٌ قابلةٌ للإعادة: استعادةٌ ثمّ نجاح."""
        guard = _make_guard(tmp_path)
        key = _make_key()
        fp = _make_fingerprint()
        guard.ledger.reserve(key=key, fingerprint=fp)
        guard.ledger.mark_failed(key=key, reason="timeout", retryable=True)

        call_count = {"n": 0}

        def execute() -> str:
            call_count["n"] += 1
            return "ok"

        r = guard.run_once(key=key, fingerprint=fp, execute=execute)
        assert r.succeeded
        assert call_count["n"] == 1


# ============================================================
# التصنيف 9: الفشلُ الجزئيّ والآثارُ المُعلَنة
# ============================================================

class TestRunEffectsOnce:
    """اختباراتُ `run_effects_once` — الفشلُ الجزئيّ والاستعادة."""

    def test_all_effects_applied_in_order(self, tmp_path):
        """جميعُ الآثارِ تُطبَّق بالترتيب."""
        guard = _make_guard(tmp_path)
        key = _make_key()
        fp = _make_fingerprint()
        applied = []

        def apply(sig: str) -> None:
            applied.append(sig)

        r = guard.run_effects_once(
            key=key, fingerprint=fp,
            declared_effects=("write:a", "write:b", "write:c"),
            apply_effect=apply,
        )
        assert r.succeeded
        assert applied == ["write:a", "write:b", "write:c"]

    def test_partial_failure_marks_recovery_required(self, tmp_path):
        """فشلٌ بعدَ أثرٍ واحد = RECOVERY_REQUIRED + الأثرُ مُسجَّل."""
        guard = _make_guard(tmp_path)
        key = _make_key()
        fp = _make_fingerprint()
        call_count = {"n": 0}

        def apply(sig: str) -> None:
            call_count["n"] += 1
            if sig == "write:b":
                raise RuntimeError("boom")

        with pytest.raises(IdempotencyError, match="RECOVERY_REQUIRED"):
            guard.run_effects_once(
                key=key, fingerprint=fp,
                declared_effects=("write:a", "write:b", "write:c"),
                apply_effect=apply,
            )

        record = guard.get_status(key)
        assert record.status == OperationStatus.RECOVERY_REQUIRED
        assert "write:a" in record.applied_effect_signatures
        assert "write:b" not in record.applied_effect_signatures
        assert "write:c" not in record.applied_effect_signatures

    def test_retry_after_partial_failure_skips_applied_effects(self, tmp_path):
        """إعادةُ المحاولةِ تُخطّي الآثارَ التي طُبِّقَت."""
        guard = _make_guard(tmp_path)
        key = _make_key()
        fp = _make_fingerprint()

        # المحاولةُ الأولى: فشل بعدَ أثرٍ واحد
        def fail_on_b(sig: str) -> None:
            if sig == "write:b":
                raise RuntimeError("boom")

        with pytest.raises(IdempotencyError):
            guard.run_effects_once(
                key=key, fingerprint=fp,
                declared_effects=("write:a", "write:b", "write:c"),
                apply_effect=fail_on_b,
            )

        # المحاولةُ الثانية: تُخطّي A وتُطبِّقُ B و C
        applied_on_retry = []

        def apply_all(sig: str) -> None:
            applied_on_retry.append(sig)

        r = guard.run_effects_once(
            key=key, fingerprint=fp,
            declared_effects=("write:a", "write:b", "write:c"),
            apply_effect=apply_all,
        )
        assert r.succeeded
        assert applied_on_retry == ["write:b", "write:c"]  # لا إعادةَ لـ A

    def test_effect_applied_then_raises_marks_recovery(self, tmp_path):
        """أثرٌ نُفِّذَ ثمّ رفعَ استثناءً = RECOVERY_REQUIRED + pending."""
        guard = _make_guard(tmp_path)
        key = _make_key()
        fp = _make_fingerprint()
        mutated = []

        def apply_and_fail(sig: str) -> None:
            mutated.append(sig)  # الأثرُ طُبِّقَ فعلًا
            raise RuntimeError("crash after apply")

        with pytest.raises(IdempotencyError, match="قيدَ التطبيق"):
            guard.run_effects_once(
                key=key, fingerprint=fp,
                declared_effects=("write:a", "write:b"),
                apply_effect=apply_and_fail,
            )

        record = guard.get_status(key)
        assert record.status == OperationStatus.RECOVERY_REQUIRED
        # الأثرُ الأوّلُ لم يُسجَّل كـ«مُطبَّق» لأنّه رفعَ قبلَ التأكيد
        assert "write:a" not in record.applied_effect_signatures
        # لكنّه طُبِّقَ فعلًا — يتطلّبُ فحصًا يدويًّا
        assert mutated == ["write:a"]

    def test_external_effect_rejected(self, tmp_path):
        """الأثرُ الخارجيُّ يُرفضُ في المسارِ الذرّيّ المباشر."""
        guard = _make_guard(tmp_path)
        key = _make_key()
        fp = _make_fingerprint()

        with pytest.raises(IdempotencyError, match="خارجيّ"):
            guard.run_effects_once(
                key=key, fingerprint=fp,
                declared_effects=("EXTERNAL:send_email",),
                apply_effect=lambda _: None,
            )

    def test_effects_replay_returns_prior_result(self, tmp_path):
        """تكرارُ آثارٍ ناجحة = إعادة، لا تطبيق."""
        guard = _make_guard(tmp_path)
        key = _make_key()
        fp = _make_fingerprint()
        call_count = {"n": 0}

        def apply(sig: str) -> None:
            call_count["n"] += 1

        guard.run_effects_once(
            key=key, fingerprint=fp,
            declared_effects=("write:a", "write:b"),
            apply_effect=apply,
        )

        r = guard.run_effects_once(
            key=key, fingerprint=fp,
            declared_effects=("write:a", "write:b"),
            apply_effect=apply,
        )
        assert r.is_replay
        assert call_count["n"] == 2  # تطبيقٌ واحد فقط


class TestTransitionLog:
    """اختباراتُ سجلِّ الانتقالات — إعادةُ بناءِ الحالةِ التاريخيّة."""

    def test_transitions_are_append_only(self, tmp_path):
        """سجلُّ الانتقالاتِ إضافيّ — لا يُحذف."""
        ledger = _make_ledger(tmp_path)
        key = _make_key()
        fp = _make_fingerprint()

        ledger.reserve(key=key, fingerprint=fp)
        ledger.mark_running(key=key)
        ledger.mark_succeeded(key=key, result_digest="abc")

        record = ledger.get(key)
        assert len(record.transitions) >= 2  # RESERVED -> RUNNING -> SUCCEEDED
        assert record.transitions[0]["from"] == "RESERVED"
        assert record.transitions[0]["to"] == "RUNNING"
        assert record.transitions[-1]["to"] == "SUCCEEDED"

    def test_transitions_include_retry_indicator(self, tmp_path):
        """الانتقالاتُ تميّزُ المحاولاتِ الأولى من إعادة."""
        ledger = _make_ledger(tmp_path)
        key = _make_key()
        fp = _make_fingerprint()

        ledger.reserve(key=key, fingerprint=fp)
        ledger.mark_running(key=key, attempt={"n": 1})
        ledger.mark_failed(key=key, reason="timeout", retryable=True,
                           attempt={"n": 1, "error": "timeout"})
        ledger.recover(key=key)
        ledger.mark_running(key=key, attempt={"n": 2})
        ledger.mark_succeeded(key=key, result_digest="ok")

        record = ledger.get(key)
        # المحاولةُ الأولى ليست retry، الثانية retry
        runs = [t for t in record.transitions if t["to"] == "RUNNING"]
        first_run = runs[0]
        second_run = runs[1]
        assert first_run["is_retry"] is False  # المحاولةُ الأولى ليست retry
        assert second_run["is_retry"] is True  # المحاولةُ الثانية retry

    def test_transitions_survive_restart(self, tmp_path):
        """الانتقالاتُ تبقى على القرصِ بعدَ إعادةِ التشغيل."""
        ledger1 = _make_ledger(tmp_path)
        key = _make_key()
        fp = _make_fingerprint()
        ledger1.reserve(key=key, fingerprint=fp)
        ledger1.mark_running(key=key)

        ledger2 = IdempotencyLedger(ledger1.path)
        record = ledger2.get(key)
        assert len(record.transitions) >= 1  # RESERVED -> RUNNING على الأقل


class TestOneFIntegration:
    """تكاملٌ مع 1F — إذن + تنفيذ + ذرّيّة."""

    def test_duplicate_retry_does_not_reapply_effects(self, tmp_path):
        """إعادةُ الطلبِ لا تُعيدُ تطبيقَ الأثر — الذرّيّةُ تحمي التنفيذَ المنفذ."""
        from cryptography.hazmat.primitives.asymmetric import ed25519

        from core.constitutional_engine.engine import ConstitutionalEngine
        from core.constitutional_engine.ledger import ConstitutionalLedger
        from core.sovereignty.contract import (
            EffectKind,
            SovereignEffect,
            bind_contract,
        )
        from core.sovereignty.enforcement import (
            ConsumedPermitLedger,
            PolicyEnforcementPoint,
            issue_permit,
        )
        from core.sovereignty.gateway import SovereignGateway

        # بناءُ البوابةِ والمنفّذ
        gw_ledger = ConstitutionalLedger(tmp_path / "gw.jsonl")
        gateway = SovereignGateway(ConstitutionalEngine(ledger=gw_ledger))
        permit_ledger = ConsumedPermitLedger(tmp_path / "permits.json")
        pep = PolicyEnforcementPoint(
            verifying_key=ed25519.Ed25519PublicKey.from_public_bytes(
                bytes.fromhex(gateway.verifying_key_hex)
            ),
            consumed=permit_ledger,
        )
        guard = _make_guard(tmp_path / "idem")

        target = "treasury/account-1"
        effect = SovereignEffect(
            kind=EffectKind.WRITE,
            resource=target,
            detail="خصم",
            payload_digest="d1",
        )

        contract = bind_contract(
            actor="agent-1",
            action="transfer",
            target=target,
            declared_effects=(effect,)
        )
        permit = issue_permit(
            contract=contract,
            request_fingerprint="fp-1",
            decision="ALLOW",
            ledger_entry_hash=None,
            private_key=gateway._permit_key,
        )

        key = IdempotencyKey(scope="treasury", value=permit.permit_id)
        fp = compute_fingerprint(
            scope="treasury",
            action="transfer",
            target=target,
            actor="agent-1",
            effect_signatures=("WRITE:treasury/account-1",),
            payload_digest="d1",
        )

        effect_apply_count = {"n": 0}

        def execute() -> str:
            pep.enforce(
                permit,
                planner=lambda p: (effect,),
                applier=lambda e: effect_apply_count.__setitem__("n", effect_apply_count["n"] + 1),
            )
            return "ok"

        guard.run_once(key=key, fingerprint=fp, execute=execute)
        guard.run_once(key=key, fingerprint=fp, execute=execute)
        guard.run_once(key=key, fingerprint=fp, execute=execute)

        assert effect_apply_count["n"] == 1  # أثرٌ واحد، ثلاثةُ طلبات

    def test_duplicate_retry_does_not_reconsume_permit(self, tmp_path):
        """إعادةُ الطلبِ لا تُعيدُ استهلاكَ الإذن."""
        from cryptography.hazmat.primitives.asymmetric import ed25519

        from core.constitutional_engine.engine import ConstitutionalEngine
        from core.constitutional_engine.ledger import ConstitutionalLedger
        from core.sovereignty.contract import (
            EffectKind,
            SovereignEffect,
            bind_contract,
        )
        from core.sovereignty.enforcement import (
            ConsumedPermitLedger,
            PolicyEnforcementPoint,
            issue_permit,
        )
        from core.sovereignty.gateway import SovereignGateway

        gw_ledger = ConstitutionalLedger(tmp_path / "gw.jsonl")
        gateway = SovereignGateway(ConstitutionalEngine(ledger=gw_ledger))
        permit_ledger = ConsumedPermitLedger(tmp_path / "permits.json")
        pep = PolicyEnforcementPoint(
            verifying_key=ed25519.Ed25519PublicKey.from_public_bytes(
                bytes.fromhex(gateway.verifying_key_hex)
            ),
            consumed=permit_ledger,
        )
        guard = _make_guard(tmp_path / "idem")

        target = "treasury/account-1"
        effect = SovereignEffect(
            kind=EffectKind.WRITE,
            resource=target,
            detail="خصم",
            payload_digest="d1",
        )

        contract = bind_contract(
            actor="agent-1",
            action="transfer",
            target=target,
            declared_effects=(effect,)
        )
        permit = issue_permit(
            contract=contract,
            request_fingerprint="fp-1",
            decision="ALLOW",
            ledger_entry_hash=None,
            private_key=gateway._permit_key,
        )

        key = IdempotencyKey(scope="treasury", value=permit.permit_id)
        fp = compute_fingerprint(
            scope="treasury",
            action="transfer",
            target=target,
            actor="agent-1",
            effect_signatures=("WRITE:treasury/account-1",),
            payload_digest="d1",
        )

        execute_count = {"n": 0}

        def execute() -> str:
            execute_count["n"] += 1
            pep.enforce(
                permit,
                planner=lambda p: (effect,),
                applier=lambda e: None,
            )
            return "ok"

        r1 = guard.run_once(key=key, fingerprint=fp, execute=execute)
        assert r1.succeeded

        r2 = guard.run_once(key=key, fingerprint=fp, execute=execute)
        assert r2.is_replay
        assert execute_count["n"] == 1  # تنفيذٌ واحد، لا إعادة
