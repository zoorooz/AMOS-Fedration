"""الهدف: قياسُ صندوقِ الصادرِ الدائم — هل يبقى الأثرُ الخارجيُّ بعدَ السقوط؟

النطاق: `core/sovereignty/outbox.py` وتكامُلُه مع 1E و1F و1H.
المالك: tests/sovereignty/ — ديوان التدقيق
تاريخ الإنشاء: 2026-08-18
تاريخ آخر تعديل: 2026-08-18

القياسُ هنا ليس «هل الصنفُ موجود» بل «ماذا يبقى في الملفِّ بعدَ أن تموتَ
العمليّة». ولذلك تُبنى في كلِّ اختبارٍ **نسخةٌ جديدةٌ من السجلِّ على المسارِ
نفسِه**: نسخةٌ لا تعرفُ شيئًا من الذاكرةِ السابقة. فما قرأتْه فهو مُثبَّتٌ حقًّا،
وما لم تقرأْه فقد كان وهمًا في ذاكرةِ الاختبار.

والدعوى المُقاسةُ في 1K أربعٌ:
1. الأثرُ الخارجيُّ يُثبَّتُ قبلَ النداءِ ويبقى بعدَ إعادةِ التشغيل.
2. التسليمُ لا يُزعَمُ إلّا بإيصالٍ من المُزوّد.
3. السقوطُ داخلَ النداءِ يُقرأُ **غموضًا** لا فشلًا ولا نجاحًا.
4. الصندوقُ لا يُنشئُ سلطةً ولا يتجاوزُ إذنًا.
"""

from __future__ import annotations

import ast
import inspect
import json
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519

from core.sovereignty import outbox as outbox_module
from core.sovereignty.compensation import (
    CompensationGuard,
    CompensationJournal,
    CompensationStatus,
    Compensator,
    bind_compensation_plan,
)
from core.sovereignty.contract import EffectKind, SovereignEffect, bind_contract
from core.sovereignty.enforcement import (
    EnforcementPermit,
    issue_permit,
    sign_permit,
)
from core.sovereignty.fail_closed import ExecutionCompletion, attempt_execution
from core.sovereignty.idempotency import (
    IdempotencyGuard,
    IdempotencyKey,
    IdempotencyLedger,
    OperationStatus,
    compute_fingerprint,
)
from core.sovereignty.outbox import (
    DEFAULT_LEASE_SECONDS,
    DeliveryOutcome,
    DeliveryReceipt,
    DeliveryStatus,
    EffectEnvelope,
    EffectPayload,
    OutboxAuthorityError,
    OutboxClaimError,
    OutboxError,
    OutboxLedger,
    OutboxOrderingError,
    OutboxPayloadError,
    OutboxSecretMaterialError,
    OutboxStateError,
    OutboxWorker,
    ProviderDeliveryError,
    ProviderIndeterminateError,
    SovereignOutbox,
    compute_effect_id,
    enqueue_write_ahead,
    external_effect_of,
    orphaned_effects,
    settlement_of,
)

TARGET = "external/payments"
RESOURCE = "external/payments/charge"
FORBIDDEN_BYPASS_PARAMS = frozenset(
    {"force", "bypass", "skip_check", "unchecked", "override", "no_verify", "unsafe"}
)


# ═══════════════════════════════════════════════════════════════════════════
# تجهيزات — مُزوّدونَ مُزيَّفونَ يُمثّلونَ سلوكًا حقيقيًّا لا يُنفِّخونَ تغطية
# ═══════════════════════════════════════════════════════════════════════════

class _مُزوّدٌ_أساس:
    """مُحوّلٌ يُسجّلُ نداءاتِه وأثرَه في «نظامٍ خارجيٍّ» صريح.

    الأثرُ الخارجيُّ يُكتَبُ في `external_state`: بذلك يُقاسُ التكرارُ الحقيقيُّ
    لا عدُّ الاستدعاءاتِ وحدَه.
    """

    name = "payments"
    supports_idempotency = True

    def __init__(self, external_state: dict[str, int] | None = None) -> None:
        self.envelopes: list[EffectEnvelope] = []
        self.external_state: dict[str, int] = (
            external_state if external_state is not None else {}
        )

    def _apply(self, envelope: EffectEnvelope) -> None:
        token = envelope.idempotency_token
        if self.supports_idempotency and token in self.external_state:
            return
        self.external_state[token] = self.external_state.get(token, 0) + 1

    def deliver(self, envelope: EffectEnvelope) -> DeliveryReceipt:  # pragma: no cover
        raise NotImplementedError


class مُزوّدٌ_ناجح(_مُزوّدٌ_أساس):
    def deliver(self, envelope: EffectEnvelope) -> DeliveryReceipt:
        self.envelopes.append(envelope)
        known = envelope.idempotency_token in self.external_state
        self._apply(envelope)
        return DeliveryReceipt(
            outcome=(
                DeliveryOutcome.DUPLICATE if known else DeliveryOutcome.SUCCESS
            ),
            provider_reference=f"PR-{envelope.idempotency_token}",
            detail="تمّ",
        )


class مُزوّدٌ_فاشلٌ_يقبلُ_الإعادة(_مُزوّدٌ_أساس):
    def deliver(self, envelope: EffectEnvelope) -> DeliveryReceipt:
        self.envelopes.append(envelope)
        raise ProviderDeliveryError("انقطاعُ شبكةٍ قبلَ إرسالِ الطلب")


class مُزوّدٌ_فاشلٌ_نهائيًّا(_مُزوّدٌ_أساس):
    def deliver(self, envelope: EffectEnvelope) -> DeliveryReceipt:
        self.envelopes.append(envelope)
        return DeliveryReceipt(
            outcome=DeliveryOutcome.PERMANENT_FAILURE,
            detail="حسابٌ مُجمَّدٌ — لا تُعِدْ",
        )


class مُزوّدٌ_غامض(_مُزوّدٌ_أساس):
    """مهلةٌ انقضت: الطلبُ **قد** وصلَ وأحدثَ أثرَه."""

    def deliver(self, envelope: EffectEnvelope) -> DeliveryReceipt:
        self.envelopes.append(envelope)
        self._apply(envelope)  # الأثرُ وقعَ فعلًا — ثمّ ضاعَ الجواب
        raise ProviderIndeterminateError("انقضتِ المهلةُ قبلَ وصولِ الجواب")


class مُزوّدٌ_غامضٌ_غيرُ_متفرِّد(مُزوّدٌ_غامض):
    supports_idempotency = False


class مُزوّدٌ_يرفعُ_استثناءً_غيرَ_مُصنَّف(_مُزوّدٌ_أساس):
    def deliver(self, envelope: EffectEnvelope) -> DeliveryReceipt:
        self.envelopes.append(envelope)
        raise RuntimeError("خللٌ غيرُ متوقَّعٍ في المُحوّل")


class مُزوّدٌ_يعيدُ_شكلًا_مجهولًا(_مُزوّدٌ_أساس):
    def deliver(self, envelope: EffectEnvelope):  # type: ignore[override]
        return "تمّ"


@pytest.fixture()
def مفتاحُ_القرار() -> ed25519.Ed25519PrivateKey:
    """مفتاحُ موضعِ القرار — الصندوقُ لا يملكُه بحال."""
    return ed25519.Ed25519PrivateKey.generate()


@pytest.fixture()
def مفتاحُ_التحقّق(مفتاحُ_القرار) -> ed25519.Ed25519PublicKey:
    return مفتاحُ_القرار.public_key()


@pytest.fixture()
def مسارُ_الصادر(tmp_path: Path) -> Path:
    return tmp_path / "OUTBOX.json"


@pytest.fixture()
def سجلُّ_الصادر(مسارُ_الصادر: Path) -> OutboxLedger:
    return OutboxLedger(path=مسارُ_الصادر)


@pytest.fixture()
def صندوق(سجلُّ_الصادر, مفتاحُ_التحقّق) -> SovereignOutbox:
    return SovereignOutbox(ledger=سجلُّ_الصادر, verifying_key=مفتاحُ_التحقّق)


@pytest.fixture()
def حمولة() -> EffectPayload:
    return EffectPayload(
        data={"amount": 100, "currency": "SAR", "invoice": "INV-7"}
    )


@pytest.fixture()
def أثرٌ_خارجيّ(حمولة: EffectPayload) -> SovereignEffect:
    return external_effect_of(
        resource=RESOURCE, detail="سدادُ فاتورة", payload=حمولة
    )


def _إذن(
    *,
    private_key: ed25519.Ed25519PrivateKey,
    effect: SovereignEffect,
    decision: str = "ALLOW",
    ttl_seconds: int = 3600,
    now: datetime | None = None,
    anchor: str | None = "LE-anchor-1",
):
    """إذنٌ موقَّعٌ صادرٌ عن موضعِ القرارِ — قبلَ أيِّ إدراجٍ في الصندوق."""
    عقد = bind_contract(
        actor="EXECUTIVE",
        action="settle_invoice",
        target=TARGET,
        declared_effects=(effect,),
    )
    غير_موقَّع = issue_permit(
        contract=عقد,
        request_fingerprint="RF-1",
        decision=decision,
        ledger_entry_hash=anchor,
        private_key=private_key,
        authority_layer="EXECUTIVE",
        decision_kind="ORDINARY",
        ttl_seconds=ttl_seconds,
        now=now,
    )
    return sign_permit(غير_موقَّع, private_key)


@pytest.fixture()
def إذنٌ_نافذ(مفتاحُ_القرار, أثرٌ_خارجيّ):
    return _إذن(private_key=مفتاحُ_القرار, effect=أثرٌ_خارجيّ)


@pytest.fixture()
def مُدرَج(صندوق, إذنٌ_نافذ, أثرٌ_خارجيّ, حمولة):
    """أثرٌ مُثبَّتٌ على القرصِ وجاهزٌ للتسليم."""
    مُزوّد = مُزوّدٌ_ناجح()
    سجل = صندوق.enqueue(
        permit=إذنٌ_نافذ,
        effect=أثرٌ_خارجيّ,
        operation_key="invoice:INV-7",
        provider=مُزوّد,
        payload=حمولة,
        correlation_id="CID-1",
    )
    return سجل, مُزوّد


def _قراءةٌ_جديدة(path: Path) -> OutboxLedger:
    """سجلٌّ جديدٌ على المسارِ نفسِه — يُمثّلُ عمليّةً بعدَ إعادةِ التشغيل."""
    return OutboxLedger(path=path)


def _ملفٌّ_خام(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ═══════════════════════════════════════════════════════════════════════════
# 1 — الإدراجُ يُثبَّتُ دائمًا (المتطلّب 1) والنجاةُ من إعادةِ التشغيل (2)
# ═══════════════════════════════════════════════════════════════════════════

class Testالديمومة:
    def test_الادراج_يكتب_على_القرص_لا_في_الذاكرة(self, مُدرَج, مسارُ_الصادر):
        """القياسُ على الملفِّ نفسِه: لو كان مخزنَ ذاكرةٍ لم يوجدْ ملفّ."""
        سجل, _ = مُدرَج
        assert مسارُ_الصادر.exists()
        خام = _ملفٌّ_خام(مسارُ_الصادر)
        assert سجل.effect_id in خام
        assert خام[سجل.effect_id]["status"] == "PENDING"

    def test_المعلق_يبقى_بعد_اعادة_التشغيل(self, مُدرَج, مسارُ_الصادر):
        """سجلٌّ جديدٌ لا يعرفُ ذاكرةَ ما قبلَه — ومع ذلك يجدُ الأثر."""
        سجل, _ = مُدرَج
        بعدَ_الإقلاع = _قراءةٌ_جديدة(مسارُ_الصادر)
        مُستعاد = بعدَ_الإقلاع.require(سجل.effect_id)
        assert مُستعاد.status is DeliveryStatus.PENDING
        assert مُستعاد.payload_digest == سجل.payload_digest
        assert مُستعاد.operation_key == "invoice:INV-7"
        assert [r.effect_id for r in بعدَ_الإقلاع.by_status(DeliveryStatus.PENDING)] == [
            سجل.effect_id
        ]

    def test_الحمولة_والمرجعية_تثبتان_كاملتين(self, مُدرَج, مسارُ_الصادر):
        """هويّةُ الأثرِ وحمولتُه ومرساتُه تُقرأُ بعدَ الإقلاع — لا نصفُ سجلّ."""
        سجل, _ = مُدرَج
        مُستعاد = _قراءةٌ_جديدة(مسارُ_الصادر).require(سجل.effect_id)
        assert مُستعاد.payload == {
            "amount": 100,
            "currency": "SAR",
            "invoice": "INV-7",
        }
        assert مُستعاد.payload_version == 1
        assert مُستعاد.authorization_anchor == "LE-anchor-1"
        assert مُستعاد.permit_id == سجل.permit_id
        assert مُستعاد.correlation_id == "CID-1"
        assert مُستعاد.provider_supports_idempotency is True

    def test_سجل_تالف_يرفع_ولا_يبتلع(self, مسارُ_الصادر):
        """السجلُّ المشكوكُ فيه لا يُقرأُ فراغًا: الفراغُ الكاذبُ أخطرُ من الخطأ."""
        مسارُ_الصادر.write_text("{ نصٌّ غيرُ صالح", encoding="utf-8")
        with pytest.raises(OutboxError, match="تالف"):
            OutboxLedger(path=مسارُ_الصادر).all_records()

    def test_الكتابة_ذرية_فلا_يبقى_ملف_مؤقت(self, مُدرَج, مسارُ_الصادر):
        """`os.replace` لا يترك أنصافَ ملفّاتٍ في المجلَّد."""
        assert list(مسارُ_الصادر.parent.glob("tmp*")) == []


# ═══════════════════════════════════════════════════════════════════════════
# 2 — الحجزُ الدائم (3) واستعادةُ المهجور (4)
# ═══════════════════════════════════════════════════════════════════════════

class Testالحجزُوالعقدُالزمنيّ:
    def test_الحجز_يثبت_على_القرص(self, مُدرَج, سجلُّ_الصادر, مسارُ_الصادر):
        """الحجزُ في الذاكرةِ يضيعُ مع العامل. فليُقرَأْ من الملفّ."""
        سجل, _ = مُدرَج
        سجلُّ_الصادر.claim(effect_id=سجل.effect_id, worker_id="W1")
        خام = _ملفٌّ_خام(مسارُ_الصادر)[سجل.effect_id]
        assert خام["status"] == "CLAIMED"
        assert خام["claimed_by"] == "W1"
        assert خام["lease_expires_at"] is not None
        مُستعاد = _قراءةٌ_جديدة(مسارُ_الصادر).require(سجل.effect_id)
        assert مُستعاد.claimed_by == "W1"

    def test_عاملان_لا_يحجزان_الاثر_نفسه(self, مُدرَج, سجلُّ_الصادر):
        """المتطلّب 8: الحجزُ المزدوجُ مرفوضٌ ما دامَ العقدُ ساريًا."""
        سجل, _ = مُدرَج
        سجلُّ_الصادر.claim(effect_id=سجل.effect_id, worker_id="W1")
        with pytest.raises(OutboxClaimError):
            سجلُّ_الصادر.claim(effect_id=سجل.effect_id, worker_id="W2")

    def test_الحجز_المهجور_بلا_نداء_يعود_معلقا(self, مُدرَج, سجلُّ_الصادر):
        """نافذةُ B: العاملُ حجزَ ثمّ مات قبلَ أن يُنادي ⇒ يُعادُ للطابور."""
        سجل, _ = مُدرَج
        الآن = datetime.now(timezone.utc).replace(microsecond=0)
        سجلُّ_الصادر.claim(
            effect_id=سجل.effect_id, worker_id="W1", lease_seconds=5, now=الآن
        )
        مُستعاد = سجلُّ_الصادر.reclaim_expired(now=الآن + timedelta(seconds=6))
        assert [r.status for r in مُستعاد] == [DeliveryStatus.PENDING]
        assert سجلُّ_الصادر.require(سجل.effect_id).claimed_by is None

    def test_الحجز_الساري_لا_يستعاد(self, مُدرَج, سجلُّ_الصادر):
        """الاستعادةُ قبلَ الانقضاءِ سرقةُ عملٍ جارٍ — فلا تقع."""
        سجل, _ = مُدرَج
        الآن = datetime.now(timezone.utc).replace(microsecond=0)
        سجلُّ_الصادر.claim(
            effect_id=سجل.effect_id, worker_id="W1", lease_seconds=60, now=الآن
        )
        assert سجلُّ_الصادر.reclaim_expired(now=الآن + timedelta(seconds=10)) == []

    def test_عامل_ثان_يحجز_بعد_انقضاء_العقد(self, مُدرَج, سجلُّ_الصادر):
        """الأثرُ لا يُجمَّدُ إلى الأبدِ بموتِ عاملٍ واحد."""
        سجل, _ = مُدرَج
        الآن = datetime.now(timezone.utc).replace(microsecond=0)
        سجلُّ_الصادر.claim(
            effect_id=سجل.effect_id, worker_id="W1", lease_seconds=5, now=الآن
        )
        بعد = الآن + timedelta(seconds=10)
        مُعاد = سجلُّ_الصادر.claim(
            effect_id=سجل.effect_id, worker_id="W2", lease_seconds=5, now=بعد
        )
        assert مُعاد.claimed_by == "W2"

    def test_حجز_بلا_هوية_مرفوض(self, مُدرَج, سجلُّ_الصادر):
        سجل, _ = مُدرَج
        with pytest.raises(OutboxClaimError):
            سجلُّ_الصادر.claim(effect_id=سجل.effect_id, worker_id="   ")

    def test_عقد_زمني_غير_موجب_مرفوض(self, مُدرَج, سجلُّ_الصادر):
        """عقدٌ لا ينتهي أو ينتهي قبلَ أن يبدأ ليس عقدًا."""
        سجل, _ = مُدرَج
        with pytest.raises(OutboxClaimError):
            سجلُّ_الصادر.claim(
                effect_id=سجل.effect_id, worker_id="W1", lease_seconds=0
            )

    def test_محاولة_بلا_حجز_مرفوضة(self, مُدرَج, سجلُّ_الصادر):
        سجل, _ = مُدرَج
        with pytest.raises(OutboxStateError):
            سجلُّ_الصادر.begin_attempt(effect_id=سجل.effect_id, worker_id="W1")

    def test_عامل_غير_الحاجز_لا_يبدأ_محاولة(self, مُدرَج, سجلُّ_الصادر):
        سجل, _ = مُدرَج
        سجلُّ_الصادر.claim(effect_id=سجل.effect_id, worker_id="W1")
        with pytest.raises(OutboxClaimError):
            سجلُّ_الصادر.begin_attempt(effect_id=سجل.effect_id, worker_id="W2")


# ═══════════════════════════════════════════════════════════════════════════
# 3 — التسليمُ والفشلُ والإعادة (5 · 6 · 7 · 13)
# ═══════════════════════════════════════════════════════════════════════════

class Testالتسليم:
    def test_النجاح_يثبت_تسليما(self, مُدرَج, سجلُّ_الصادر, مسارُ_الصادر):
        سجل, مُزوّد = مُدرَج
        عامل = OutboxWorker(
            ledger=سجلُّ_الصادر, adapters={مُزوّد.name: مُزوّد}, worker_id="W1"
        )
        تقرير = عامل.run_once()
        assert تقرير is not None
        assert تقرير.record.status is DeliveryStatus.DELIVERED
        assert تقرير.record.delivered_at is not None
        assert تقرير.record.provider_reference == f"PR-{سجل.effect_id}"
        مُستعاد = _قراءةٌ_جديدة(مسارُ_الصادر).require(سجل.effect_id)
        assert مُستعاد.status.certifies_delivery
        assert مُزوّد.external_state == {سجل.effect_id: 1}

    def test_الفشل_القابل_للاعادة_لا_يقتل_الاثر(self, صندوق, إذنٌ_نافذ, أثرٌ_خارجيّ, حمولة, سجلُّ_الصادر):
        """نافذةُ C: نداءٌ فشلَ بإقرارِ المُزوّد ⇒ `FAILED_RETRYABLE` لا `DEAD`."""
        مُزوّد = مُزوّدٌ_فاشلٌ_يقبلُ_الإعادة()
        صندوق.enqueue(
            permit=إذنٌ_نافذ,
            effect=أثرٌ_خارجيّ,
            operation_key="op:1",
            provider=مُزوّد,
            payload=حمولة,
        )
        عامل = OutboxWorker(
            ledger=سجلُّ_الصادر,
            adapters={مُزوّد.name: مُزوّد},
            worker_id="W1",
            max_attempts=3,
        )
        تقرير = عامل.run_once()
        assert تقرير.record.status is DeliveryStatus.FAILED_RETRYABLE
        assert تقرير.record.attempt_count == 1
        assert "انقطاعُ شبكة" in (تقرير.record.failure_reason or "")
        assert مُزوّد.external_state == {}

    def test_الاعادة_تزيد_عدد_المحاولات_المثبت(self, صندوق, إذنٌ_نافذ, أثرٌ_خارجيّ, حمولة, سجلُّ_الصادر, مسارُ_الصادر):
        """نافذةُ E: كلُّ محاولةٍ تُضافُ ولا تُمحى سابقتُها."""
        مُزوّد = مُزوّدٌ_فاشلٌ_يقبلُ_الإعادة()
        سجل = صندوق.enqueue(
            permit=إذنٌ_نافذ,
            effect=أثرٌ_خارجيّ,
            operation_key="op:1",
            provider=مُزوّد,
            payload=حمولة,
        )
        عامل = OutboxWorker(
            ledger=سجلُّ_الصادر,
            adapters={مُزوّد.name: مُزوّد},
            worker_id="W1",
            max_attempts=5,
        )
        عامل.run_once()
        عامل.run_once()
        مُستعاد = _قراءةٌ_جديدة(مسارُ_الصادر).require(سجل.effect_id)
        assert مُستعاد.attempt_count == 2
        assert len(مُستعاد.attempts) == 2
        assert [a["attempt"] for a in مُستعاد.attempts] == [1, 2]
        assert all(a["outcome"] == "RETRYABLE_FAILURE" for a in مُستعاد.attempts)

    def test_استنفاد_المحاولات_يبلغ_صندوق_الموتى(self, صندوق, إذنٌ_نافذ, أثرٌ_خارجيّ, حمولة, سجلُّ_الصادر, مسارُ_الصادر):
        """نافذةُ G: الفشلُ النهائيُّ مُثبَّتٌ ولا يُعادُ إلى الأبد."""
        مُزوّد = مُزوّدٌ_فاشلٌ_يقبلُ_الإعادة()
        سجل = صندوق.enqueue(
            permit=إذنٌ_نافذ,
            effect=أثرٌ_خارجيّ,
            operation_key="op:1",
            provider=مُزوّد,
            payload=حمولة,
        )
        عامل = OutboxWorker(
            ledger=سجلُّ_الصادر,
            adapters={مُزوّد.name: مُزوّد},
            worker_id="W1",
            max_attempts=2,
        )
        عامل.drain(limit=10)
        مُستعاد = _قراءةٌ_جديدة(مسارُ_الصادر).require(سجل.effect_id)
        assert مُستعاد.status is DeliveryStatus.DEAD
        assert مُستعاد.terminal_reason == "MAX_ATTEMPTS_EXHAUSTED"
        assert مُستعاد.attempt_count == 2
        assert سجلُّ_الصادر.dead_letters()[0].effect_id == سجل.effect_id
        assert عامل.run_once() is None

    def test_الفشل_النهائي_المقر_لا_يعاد(self, صندوق, إذنٌ_نافذ, أثرٌ_خارجيّ, حمولة, سجلُّ_الصادر):
        """مُزوّدٌ قال «لا تُعِدْ» — فلا إعادةَ ولو بقيت محاولات."""
        مُزوّد = مُزوّدٌ_فاشلٌ_نهائيًّا()
        سجل = صندوق.enqueue(
            permit=إذنٌ_نافذ,
            effect=أثرٌ_خارجيّ,
            operation_key="op:1",
            provider=مُزوّد,
            payload=حمولة,
        )
        عامل = OutboxWorker(
            ledger=سجلُّ_الصادر,
            adapters={مُزوّد.name: مُزوّد},
            worker_id="W1",
            max_attempts=9,
        )
        تقرير = عامل.run_once()
        assert تقرير.record.status is DeliveryStatus.DEAD
        assert تقرير.record.terminal_reason == "PERMANENT_FAILURE"
        assert سجلُّ_الصادر.require(سجل.effect_id).attempt_count == 1
        assert عامل.run_once() is None

    def test_لا_انتقال_من_حالة_نهائية(self, مُدرَج, سجلُّ_الصادر):
        """التسليمُ لا يتراجع: النهائيُّ نهائيّ."""
        سجل, مُزوّد = مُدرَج
        OutboxWorker(
            ledger=سجلُّ_الصادر, adapters={مُزوّد.name: مُزوّد}, worker_id="W1"
        ).run_once()
        with pytest.raises(OutboxClaimError):
            سجلُّ_الصادر.claim(effect_id=سجل.effect_id, worker_id="W2")

    def test_الغياب_عن_محول_لا_يصنف_فشلا(self, مُدرَج, سجلُّ_الصادر):
        """عجزُنا عن النداءِ ليس فشلَ المُزوّد — ولا يُقيَّدُ عليه."""
        سجل, _ = مُدرَج
        عامل = OutboxWorker(ledger=سجلُّ_الصادر, adapters={}, worker_id="W1")
        with pytest.raises(OutboxError, match="لا مُحوّلَ"):
            عامل.run_once()
        assert سجلُّ_الصادر.require(سجل.effect_id).status is DeliveryStatus.PENDING

    def test_محول_يعيد_شكلا_مجهولا_لا_يقرأ_نجاحا(self, صندوق, إذنٌ_نافذ, أثرٌ_خارجيّ, حمولة, سجلُّ_الصادر):
        مُزوّد = مُزوّدٌ_يعيدُ_شكلًا_مجهولًا()
        سجل = صندوق.enqueue(
            permit=إذنٌ_نافذ,
            effect=أثرٌ_خارجيّ,
            operation_key="op:1",
            provider=مُزوّد,
            payload=حمولة,
        )
        عامل = OutboxWorker(
            ledger=سجلُّ_الصادر, adapters={مُزوّد.name: مُزوّد}, worker_id="W1"
        )
        with pytest.raises(OutboxError, match="إيصالًا"):
            عامل.run_once()
        assert سجلُّ_الصادر.require(سجل.effect_id).status is DeliveryStatus.CLAIMED

    def test_نتيجة_بلا_محاولة_مثبتة_مرفوضة(self, مُدرَج, سجلُّ_الصادر):
        """لا تسليمَ يُكتَبُ بلا نداءٍ سُجِّلَ قبلَه."""
        سجل, _ = مُدرَج
        سجلُّ_الصادر.claim(effect_id=سجل.effect_id, worker_id="W1")
        with pytest.raises(OutboxStateError, match="قيدَ الطيران"):
            سجلُّ_الصادر.record_result(
                effect_id=سجل.effect_id,
                worker_id="W1",
                receipt=DeliveryReceipt(outcome=DeliveryOutcome.SUCCESS),
            )

    def test_نتيجة_من_عامل_غير_الحاجز_مرفوضة(self, مُدرَج, سجلُّ_الصادر):
        سجل, _ = مُدرَج
        سجلُّ_الصادر.claim(effect_id=سجل.effect_id, worker_id="W1")
        سجلُّ_الصادر.begin_attempt(effect_id=سجل.effect_id, worker_id="W1")
        with pytest.raises(OutboxClaimError):
            سجلُّ_الصادر.record_result(
                effect_id=سجل.effect_id,
                worker_id="W2",
                receipt=DeliveryReceipt(outcome=DeliveryOutcome.SUCCESS),
            )

    def test_محاولتان_قيد_الطيران_لا_تجتمعان(self, مُدرَج, سجلُّ_الصادر):
        سجل, _ = مُدرَج
        سجلُّ_الصادر.claim(effect_id=سجل.effect_id, worker_id="W1")
        سجلُّ_الصادر.begin_attempt(effect_id=سجل.effect_id, worker_id="W1")
        with pytest.raises(OutboxStateError, match="لم تُحسَم"):
            سجلُّ_الصادر.begin_attempt(effect_id=سجل.effect_id, worker_id="W1")


# ═══════════════════════════════════════════════════════════════════════════
# 4 — الهويّةُ والتفرُّد (9 · 10)
# ═══════════════════════════════════════════════════════════════════════════

class Testهويّةُالتفرُّد:
    def test_هوية_الاثر_ثابتة_وحاسمة(self):
        """المتطلّب 9: الهويّةُ نفسُها لنفسِ المادّةِ في كلِّ مرّةٍ وفي كلِّ عمليّة."""
        وسائط = {
            "operation_key": "op:1",
            "effect_signature": "EXTERNAL:x",
            "provider": "payments",
            "payload_digest": "PD-abc",
        }
        assert compute_effect_id(**وسائط) == compute_effect_id(**وسائط)
        assert compute_effect_id(**{**وسائط, "operation_key": "op:2"}) != (
            compute_effect_id(**وسائط)
        )

    def test_الهوية_لا_تعتمد_على_الزمن(self, monkeypatch):
        """الهويّةُ لو دخلَ فيها وقتٌ لصارت كلُّ إعادةٍ أثرًا جديدًا.

        القياسُ بتحريكِ ساعةِ الوحدةِ نفسِها: لو كانت الهويّةُ تقرأُ الوقتَ
        لتغيّرت. وهذا يُغلِقُ الطفرةَ التي تُدخِلُ `nonce` زمنيًّا في المادّة.
        """
        وسائط = {
            "operation_key": "op:1",
            "effect_signature": "EXTERNAL:x",
            "provider": "payments",
            "payload_digest": "PD-abc",
        }
        أوّل = compute_effect_id(**وسائط)
        monkeypatch.setattr(
            outbox_module, "_now", lambda: datetime(2031, 5, 5, tzinfo=timezone.utc)
        )
        monkeypatch.setattr(outbox_module, "_iso", lambda moment=None: "2031-05-05")
        assert compute_effect_id(**وسائط) == أوّل

    def test_مادة_الهوية_محصورة_في_وسائطها(self):
        """قياسٌ على المصدر: لا مادّةَ في الهويّةِ إلّا الوسائطُ الأربع.

        الفحصُ السلوكيُّ وحدَه لا يكفي هنا: طفرةٌ تُدخِلُ عنصرًا خارجيًّا ذا
        دقّةٍ ثانويّةٍ تنجو من قياسينِ متتاليينِ في الثانيةِ نفسِها. فالقياسُ
        على البنيةِ لا على الحظّ.
        """
        شجرة = ast.parse(textwrap.dedent(inspect.getsource(compute_effect_id)))
        دالّة = شجرة.body[0]
        assert isinstance(دالّة, ast.FunctionDef)
        وسائط = {a.arg for a in دالّة.args.kwonlyargs}
        assert وسائط == {
            "operation_key",
            "effect_signature",
            "provider",
            "payload_digest",
        }
        مفاتيح = {
            مفتاح.value
            for عقدة in ast.walk(دالّة)
            if isinstance(عقدة, ast.Dict)
            for مفتاح in عقدة.keys
            if isinstance(مفتاح, ast.Constant)
        }
        assert مفاتيح == وسائط, f"مادّةٌ زائدةٌ في الهويّة: {مفاتيح - وسائط}"
        نداءات = {
            ast.unparse(عقدة.func)
            for عقدة in ast.walk(دالّة)
            if isinstance(عقدة, ast.Call)
        }
        ممنوع = ("now", "time", "iso", "random", "uuid", "uuid4", "token")
        for نداء in نداءات:
            assert not any(ك in نداء.lower() for ك in ممنوع), نداء

    def test_الهوية_لا_تتغير_بترتيب_مفاتيح_الحمولة(self):
        """بصمةُ الحمولةِ قانونيّةٌ لا مرتبطةٌ بترتيبِ الكتابة."""
        أ = EffectPayload(data={"a": 1, "b": 2})
        ب = EffectPayload(data={"b": 2, "a": 1})
        assert أ.digest == ب.digest

    def test_الادراج_المكرر_لا_ينشئ_سجلا_ثانيا(self, صندوق, إذنٌ_نافذ, أثرٌ_خارجيّ, حمولة, سجلُّ_الصادر):
        """المتطلّب 10 · أوّلُ صفٍّ في الدفاع: هويّةٌ واحدةٌ ⇒ سجلٌّ واحد."""
        مُزوّد = مُزوّدٌ_ناجح()
        أوّل = صندوق.enqueue(
            permit=إذنٌ_نافذ,
            effect=أثرٌ_خارجيّ,
            operation_key="op:1",
            provider=مُزوّد,
            payload=حمولة,
        )
        ثانٍ = صندوق.enqueue(
            permit=إذنٌ_نافذ,
            effect=أثرٌ_خارجيّ,
            operation_key="op:1",
            provider=مُزوّد,
            payload=حمولة,
        )
        assert أوّل.effect_id == ثانٍ.effect_id
        assert سجلُّ_الصادر.count() == 1

    def test_رقم_التفرد_ثابت_عبر_كل_المحاولات(self, صندوق, إذنٌ_نافذ, أثرٌ_خارجيّ, حمولة, سجلُّ_الصادر):
        """المُزوّدُ يرى الرقمَ نفسَه في المحاولةِ الأولى والثانية."""
        class مُتذبذب(_مُزوّدٌ_أساس):
            def __init__(self) -> None:
                super().__init__()
                self.count = 0

            def deliver(self, envelope: EffectEnvelope) -> DeliveryReceipt:
                self.envelopes.append(envelope)
                self.count += 1
                if self.count == 1:
                    raise ProviderDeliveryError("أوّلُ نداءٍ فشل")
                self._apply(envelope)
                return DeliveryReceipt(outcome=DeliveryOutcome.SUCCESS)

        مُزوّد = مُتذبذب()
        سجل = صندوق.enqueue(
            permit=إذنٌ_نافذ,
            effect=أثرٌ_خارجيّ,
            operation_key="op:1",
            provider=مُزوّد,
            payload=حمولة,
        )
        عامل = OutboxWorker(
            ledger=سجلُّ_الصادر,
            adapters={مُزوّد.name: مُزوّد},
            worker_id="W1",
            max_attempts=5,
        )
        عامل.run_once()
        عامل.run_once()
        رموز = {e.idempotency_token for e in مُزوّد.envelopes}
        assert رموز == {سجل.effect_id}
        assert مُزوّد.external_state == {سجل.effect_id: 1}

    def test_اقرار_المزود_بالتكرار_يقرأ_تسليما_لا_فشلا(self, صندوق, إذنٌ_نافذ, أثرٌ_خارجيّ, حمولة, سجلُّ_الصادر):
        """المتطلّب 10: إعادةٌ على مُزوّدٍ متفرِّدٍ ⇒ `DUPLICATE` ⇒ تسليمٌ واحد."""
        خارجيّ: dict[str, int] = {}
        مُزوّد = مُزوّدٌ_ناجح(external_state=خارجيّ)
        سجل = صندوق.enqueue(
            permit=إذنٌ_نافذ,
            effect=أثرٌ_خارجيّ,
            operation_key="op:1",
            provider=مُزوّد,
            payload=حمولة,
        )
        # نداءٌ سابقٌ أحدثَ الأثرَ خارجيًّا ثمّ ضاعَ جوابُه
        خارجيّ[سجل.effect_id] = 1
        عامل = OutboxWorker(
            ledger=سجلُّ_الصادر, adapters={مُزوّد.name: مُزوّد}, worker_id="W1"
        )
        تقرير = عامل.run_once()
        assert تقرير.receipt.outcome is DeliveryOutcome.DUPLICATE
        assert تقرير.record.status is DeliveryStatus.DELIVERED
        assert خارجيّ == {سجل.effect_id: 1}

    def test_هوية_واحدة_لحمولتين_مرفوضة(self, سجلُّ_الصادر, حمولة):
        """اختلافُ البصمةِ على الهويّةِ نفسِها خللٌ في الاستدعاءِ لا يُبتلَع."""
        وسائط = {
            "effect_id": "OB-ثابت",
            "operation_key": "op:1",
            "effect_signature": "EXTERNAL:x",
            "provider": "payments",
            "provider_supports_idempotency": True,
            "permit_id": "EP-1",
            "authorization_anchor": "LE-1",
        }
        سجلُّ_الصادر.enqueue(payload=حمولة, **وسائط)
        with pytest.raises(OutboxStateError, match="بصمةِ حمولةٍ مختلفة"):
            سجلُّ_الصادر.enqueue(
                payload=EffectPayload(data={"amount": 999}), **وسائط
            )


# ═══════════════════════════════════════════════════════════════════════════
# 5 — الغموض: المتطلّبان 11 و12 · النافذتان D و F
# ═══════════════════════════════════════════════════════════════════════════

class Testالغموضُلايُكذَب:
    def test_نتيجة_مجهولة_لا_تصنف_نجاحا_ولا_فشلا(self, صندوق, إذنٌ_نافذ, أثرٌ_خارجيّ, حمولة, سجلُّ_الصادر, مسارُ_الصادر):
        """المتطلّب 11: مهلةٌ انقضت ⇒ `INDETERMINATE` صريحة."""
        مُزوّد = مُزوّدٌ_غامض()
        سجل = صندوق.enqueue(
            permit=إذنٌ_نافذ,
            effect=أثرٌ_خارجيّ,
            operation_key="op:1",
            provider=مُزوّد,
            payload=حمولة,
        )
        عامل = OutboxWorker(
            ledger=سجلُّ_الصادر, adapters={مُزوّد.name: مُزوّد}, worker_id="W1"
        )
        تقرير = عامل.run_once()
        assert تقرير.record.status is DeliveryStatus.INDETERMINATE
        assert not تقرير.record.status.certifies_delivery
        assert تقرير.record.status.is_ambiguous
        assert not تقرير.record.status.is_terminal
        مُستعاد = _قراءةٌ_جديدة(مسارُ_الصادر).require(سجل.effect_id)
        assert مُستعاد.status is DeliveryStatus.INDETERMINATE
        # والأثرُ وقعَ فعلًا خارجيًّا — فلو صُنِّفَ فشلًا لضاعَتِ الحقيقة
        assert مُزوّد.external_state == {سجل.effect_id: 1}

    def test_استثناء_غير_مصنف_يقرأ_غموضا_لا_فشلا(self, صندوق, إذنٌ_نافذ, أثرٌ_خارجيّ, حمولة, سجلُّ_الصادر):
        """الافتراضُ الآمنُ عندَ الجهلِ هو الغموضُ: الطلبُ قد يكونُ وصل."""
        مُزوّد = مُزوّدٌ_يرفعُ_استثناءً_غيرَ_مُصنَّف()
        صندوق.enqueue(
            permit=إذنٌ_نافذ,
            effect=أثرٌ_خارجيّ,
            operation_key="op:1",
            provider=مُزوّد,
            payload=حمولة,
        )
        تقرير = OutboxWorker(
            ledger=سجلُّ_الصادر, adapters={مُزوّد.name: مُزوّد}, worker_id="W1"
        ).run_once()
        assert تقرير.record.status is DeliveryStatus.INDETERMINATE
        assert "استثناءٌ غيرُ مُصنَّف" in (تقرير.record.failure_reason or "")

    def test_السقوط_داخل_النداء_يقرأ_غموضا_لا_تعليقا(self, مُدرَج, سجلُّ_الصادر, مسارُ_الصادر):
        """النافذةُ D — أخطرُ ما في المرحلة.

        العاملُ ثبَّتَ محاولةً ثمّ نادى المُزوّدَ (فنجحَ خارجيًّا) ثمّ مات قبلَ
        تثبيتِ النتيجة. المُستعيدُ يجدُ محاولةً قيدَ الطيرانِ فيقولُ «مجهول».
        ولو قال «معلَّق» لأُعيدَ الإرسالُ على مُزوّدٍ قد لا يكونُ متفرِّدًا.
        """
        سجل, مُزوّد = مُدرَج
        الآن = datetime.now(timezone.utc).replace(microsecond=0)
        سجلُّ_الصادر.claim(
            effect_id=سجل.effect_id, worker_id="W-قتيل", lease_seconds=5, now=الآن
        )
        قيدَ_الطيران = سجلُّ_الصادر.begin_attempt(
            effect_id=سجل.effect_id, worker_id="W-قتيل", now=الآن
        )
        assert قيدَ_الطيران.in_flight_attempt_id is not None
        # النداءُ وقعَ خارجيًّا ثمّ ماتتِ العمليّةُ قبلَ تثبيتِ النتيجة
        مُزوّد.deliver(
            EffectEnvelope(
                effect_id=سجل.effect_id,
                idempotency_token=سجل.effect_id,
                operation_key=سجل.operation_key,
                effect_signature=سجل.effect_signature,
                provider=سجل.provider,
                payload_version=سجل.payload_version,
                payload=dict(سجل.payload),
                attempt=1,
                attempt_id=قيدَ_الطيران.in_flight_attempt_id,
                authorization_anchor=سجل.authorization_anchor,
            )
        )
        بعدَ_الإقلاع = _قراءةٌ_جديدة(مسارُ_الصادر)
        مُستعاد = بعدَ_الإقلاع.reclaim_expired(now=الآن + timedelta(seconds=6))
        assert [r.status for r in مُستعاد] == [DeliveryStatus.INDETERMINATE]
        نهائيّ = بعدَ_الإقلاع.require(سجل.effect_id)
        assert نهائيّ.status is DeliveryStatus.INDETERMINATE
        assert نهائيّ.in_flight_attempt_id is None
        assert نهائيّ.attempts[0]["outcome"] == "INDETERMINATE"
        assert not نهائيّ.status.certifies_delivery

    def test_الغامض_يعاد_فقط_مع_مزود_متفرد(self, صندوق, إذنٌ_نافذ, أثرٌ_خارجيّ, حمولة, سجلُّ_الصادر):
        """الإعادةُ بعدَ الغموضِ رخصةٌ يمنحُها تفرُّدُ المُزوّدِ لا تفاؤلُنا."""
        مُزوّد = مُزوّدٌ_غامض()
        سجل = صندوق.enqueue(
            permit=إذنٌ_نافذ,
            effect=أثرٌ_خارجيّ,
            operation_key="op:1",
            provider=مُزوّد,
            payload=حمولة,
        )
        سجلُّ_الصادر.claim(effect_id=سجل.effect_id, worker_id="W1")
        سجلُّ_الصادر.begin_attempt(effect_id=سجل.effect_id, worker_id="W1")
        غامض = سجلُّ_الصادر.record_result(
            effect_id=سجل.effect_id,
            worker_id="W1",
            receipt=DeliveryReceipt(outcome=DeliveryOutcome.INDETERMINATE),
        )
        assert غامض.is_claimable() is True
        assert غامض.requires_human_resolution is False

    def test_الغامض_مع_مزود_غير_متفرد_يحتاج_فصلا_بشريا(self, صندوق, إذنٌ_نافذ, أثرٌ_خارجيّ, حمولة, سجلُّ_الصادر):
        """حيثُ لا تفرُّدَ، لا إعادةَ آليّة — والدولةُ تُصرِّحُ بعجزِها."""
        مُزوّد = مُزوّدٌ_غامضٌ_غيرُ_متفرِّد()
        سجل = صندوق.enqueue(
            permit=إذنٌ_نافذ,
            effect=أثرٌ_خارجيّ,
            operation_key="op:1",
            provider=مُزوّد,
            payload=حمولة,
        )
        عامل = OutboxWorker(
            ledger=سجلُّ_الصادر,
            adapters={مُزوّد.name: مُزوّد},
            worker_id="W1",
            max_attempts=5,
        )
        عامل.run_once()
        سجلٌّ = سجلُّ_الصادر.require(سجل.effect_id)
        assert سجلٌّ.status is DeliveryStatus.INDETERMINATE
        assert سجلٌّ.requires_human_resolution is True
        assert سجلٌّ.is_claimable() is False
        assert عامل.run_once() is None
        assert len(مُزوّد.envelopes) == 1
        assert عامل.self_check()["requires_human_resolution"] == 1

    def test_عاملان_متنافسان_لا_يضاعفان_الاثر_الخارجي(self, صندوق, إذنٌ_نافذ, أثرٌ_خارجيّ, حمولة, سجلُّ_الصادر):
        """النافذةُ F: عاملانِ على الأثرِ نفسِه ⇒ نداءٌ واحدٌ وأثرٌ واحد."""
        خارجيّ: dict[str, int] = {}
        مُزوّد = مُزوّدٌ_ناجح(external_state=خارجيّ)
        سجل = صندوق.enqueue(
            permit=إذنٌ_نافذ,
            effect=أثرٌ_خارجيّ,
            operation_key="op:1",
            provider=مُزوّد,
            payload=حمولة,
        )
        أوّل = OutboxWorker(
            ledger=سجلُّ_الصادر, adapters={مُزوّد.name: مُزوّد}, worker_id="W1"
        )
        ثانٍ = OutboxWorker(
            ledger=OutboxLedger(path=سجلُّ_الصادر.path),
            adapters={مُزوّد.name: مُزوّد},
            worker_id="W2",
        )
        assert أوّل.run_once() is not None
        assert ثانٍ.run_once() is None
        assert خارجيّ == {سجل.effect_id: 1}
        assert len(مُزوّد.envelopes) == 1


# ═══════════════════════════════════════════════════════════════════════════
# 6 — حدُّ الذرّيّةِ الحقيقيّ · النافذةُ A
# ═══════════════════════════════════════════════════════════════════════════

class Testترتيبُالديمومة:
    def test_الاثر_مثبت_ولم_يسلم_يبقى_مكتشفا(self, مُدرَج, مسارُ_الصادر):
        """النافذةُ A: مُثبَّتٌ ولم يُنادَ ⇒ يوجَدُ ويُستحَقّ."""
        سجل, _ = مُدرَج
        بعدَ_الإقلاع = _قراءةٌ_جديدة(مسارُ_الصادر)
        مُستحَقّ = بعدَ_الإقلاع.next_claimable()
        assert مُستحَقّ is not None
        assert مُستحَقّ.effect_id == سجل.effect_id
        assert مُستحَقّ.attempt_count == 0

    def test_الادراج_قبل_تثبيت_النجاح_مسموح(self, صندوق, إذنٌ_نافذ, أثرٌ_خارجيّ, حمولة, tmp_path):
        """الترتيبُ الصحيح: سجلُّ الصادرِ أوّلًا ثمّ نجاحُ العمليّة."""
        سجلُّ_التفرُّد = IdempotencyLedger(path=tmp_path / "IDEMPOTENCY.json")
        مفتاح = IdempotencyKey(scope="invoice", value="INV-7")
        بصمة = compute_fingerprint(
            scope="invoice",
            action="settle",
            target=TARGET,
            effect_signatures=(أثرٌ_خارجيّ.signature,),
        )
        سجلُّ_التفرُّد.reserve(key=مفتاح, fingerprint=بصمة)
        سجل = enqueue_write_ahead(
            outbox=صندوق,
            idempotency_ledger=سجلُّ_التفرُّد,
            key=مفتاح,
            permit=إذنٌ_نافذ,
            effect=أثرٌ_خارجيّ,
            provider=مُزوّدٌ_ناجح(),
            payload=حمولة,
        )
        assert سجل.status is DeliveryStatus.PENDING
        assert سجل.operation_key == "invoice:INV-7"

    def test_الادراج_بعد_تثبيت_النجاح_مرفوض(self, صندوق, إذنٌ_نافذ, أثرٌ_خارجيّ, حمولة, tmp_path):
        """النافذةُ الخطرةُ مُغلَقةٌ بنيويًّا: لا أثرَ يُدرَجُ بعدَ إعلانِ النجاح."""
        سجلُّ_التفرُّد = IdempotencyLedger(path=tmp_path / "IDEMPOTENCY.json")
        مفتاح = IdempotencyKey(scope="invoice", value="INV-7")
        سجلُّ_التفرُّد.reserve(key=مفتاح, fingerprint="FP")
        سجلُّ_التفرُّد.mark_running(key=مفتاح, attempt={})
        سجلُّ_التفرُّد.mark_succeeded(key=مفتاح, result_digest="RD-1")
        with pytest.raises(OutboxOrderingError, match="ترتيبَ الديمومة"):
            enqueue_write_ahead(
                outbox=صندوق,
                idempotency_ledger=سجلُّ_التفرُّد,
                key=مفتاح,
                permit=إذنٌ_نافذ,
                effect=أثرٌ_خارجيّ,
                provider=مُزوّدٌ_ناجح(),
                payload=حمولة,
            )

    def test_الادراج_لعملية_غير_محجوزة_مرفوض(self, صندوق, إذنٌ_نافذ, أثرٌ_خارجيّ, حمولة, tmp_path):
        سجلُّ_التفرُّد = IdempotencyLedger(path=tmp_path / "IDEMPOTENCY.json")
        with pytest.raises(OutboxOrderingError, match="غيرُ محجوزة"):
            enqueue_write_ahead(
                outbox=صندوق,
                idempotency_ledger=سجلُّ_التفرُّد,
                key=IdempotencyKey(scope="invoice", value="X"),
                permit=إذنٌ_نافذ,
                effect=أثرٌ_خارجيّ,
                provider=مُزوّدٌ_ناجح(),
                payload=حمولة,
            )

    def test_الاثر_اليتيم_يكتشف_صراحة(self, صندوق, إذنٌ_نافذ, أثرٌ_خارجيّ, حمولة, سجلُّ_الصادر, tmp_path):
        """الحدُّ المُعلَن: سجلُّ صادرٍ لعمليّةٍ لم تكتمل يُكتشَفُ ولا يُخفى."""
        سجلُّ_التفرُّد = IdempotencyLedger(path=tmp_path / "IDEMPOTENCY.json")
        مفتاح = IdempotencyKey(scope="invoice", value="INV-7")
        سجلُّ_التفرُّد.reserve(key=مفتاح, fingerprint="FP")
        enqueue_write_ahead(
            outbox=صندوق,
            idempotency_ledger=سجلُّ_التفرُّد,
            key=مفتاح,
            permit=إذنٌ_نافذ,
            effect=أثرٌ_خارجيّ,
            provider=مُزوّدٌ_ناجح(),
            payload=حمولة,
        )
        أيتام = orphaned_effects(
            ledger=سجلُّ_الصادر, idempotency_ledger=سجلُّ_التفرُّد
        )
        assert len(أيتام) == 1
        سجلُّ_التفرُّد.mark_running(key=مفتاح, attempt={})
        سجلُّ_التفرُّد.mark_succeeded(key=مفتاح, result_digest="RD-1")
        assert orphaned_effects(
            ledger=سجلُّ_الصادر, idempotency_ledger=سجلُّ_التفرُّد
        ) == []

    def test_حالة_العملية_لا_تدمج_في_حالة_الاثر(self, صندوق, إذنٌ_نافذ, أثرٌ_خارجيّ, حمولة, سجلُّ_الصادر, tmp_path):
        """«نجحَ محلّيًّا» ≠ «وقعَ خارجيًّا» — والقراءةُ المشتركةُ تقولُ ذلك."""
        سجلُّ_التفرُّد = IdempotencyLedger(path=tmp_path / "IDEMPOTENCY.json")
        مفتاح = IdempotencyKey(scope="invoice", value="INV-7")
        سجلُّ_التفرُّد.reserve(key=مفتاح, fingerprint="FP")
        مُزوّد = مُزوّدٌ_ناجح()
        enqueue_write_ahead(
            outbox=صندوق,
            idempotency_ledger=سجلُّ_التفرُّد,
            key=مفتاح,
            permit=إذنٌ_نافذ,
            effect=أثرٌ_خارجيّ,
            provider=مُزوّد,
            payload=حمولة,
        )
        سجلُّ_التفرُّد.mark_running(key=مفتاح, attempt={})
        سجلُّ_التفرُّد.mark_succeeded(
            key=مفتاح, result_digest="RD-1", has_external_effect=True
        )
        تسوية = settlement_of(
            ledger=سجلُّ_الصادر, idempotency_ledger=سجلُّ_التفرُّد, key=مفتاح
        )
        assert تسوية.operation_status is OperationStatus.SUCCEEDED
        assert تسوية.externally_settled is False
        assert تسوية.claims_completion is False
        assert len(تسوية.outstanding) == 1

        OutboxWorker(
            ledger=سجلُّ_الصادر, adapters={مُزوّد.name: مُزوّد}, worker_id="W1"
        ).run_once()
        بعد = settlement_of(
            ledger=سجلُّ_الصادر, idempotency_ledger=سجلُّ_التفرُّد, key=مفتاح
        )
        assert بعد.externally_settled is True
        assert بعد.claims_completion is True
        assert بعد.as_dict()["ambiguous_count"] == 0

    def test_التسوية_لعملية_غير_موجودة_ترفع(self, سجلُّ_الصادر, tmp_path):
        سجلُّ_التفرُّد = IdempotencyLedger(path=tmp_path / "IDEMPOTENCY.json")
        with pytest.raises(OutboxError, match="غيرُ موجودة"):
            settlement_of(
                ledger=سجلُّ_الصادر,
                idempotency_ledger=سجلُّ_التفرُّد,
                key=IdempotencyKey(scope="a", value="b"),
            )


# ═══════════════════════════════════════════════════════════════════════════
# 7 — الحمولةُ والأسرار (المتطلّب 14)
# ═══════════════════════════════════════════════════════════════════════════

class Testسلامةُالحمولة:
    @pytest.mark.parametrize(
        "مفتاح",
        ["api_key", "Authorization", "db_password", "PRIVATE_KEY", "session_token"],
    )
    def test_مفاتيح_السر_مرفوضة(self, مفتاح):
        with pytest.raises(OutboxSecretMaterialError):
            EffectPayload(data={مفتاح: "x"})

    def test_مفتاح_سر_متداخل_مرفوض(self):
        """التداخلُ لا يُخفي السرَّ: الفحصُ يمشي في الشجرةِ كلِّها."""
        with pytest.raises(OutboxSecretMaterialError):
            EffectPayload(data={"meta": {"headers": [{"authorization": "x"}]}})

    # truth-audit: not-a-secret — القيمُ أدناه مُختَرَعةٌ بالكامل لاختبارٍ سلبيّ
    @pytest.mark.parametrize(
        "قيمة",
        [
            "-----BEGIN PRIVATE KEY-----abc",
            "Bearer abcdefghijklmnop",
            "sb_publishable_AAAABBBBCCCCDDDD",
            "ghp_0123456789abcdefgh",
            "sk-0123456789abcdefgh",
            "postgresql://u:p@host:5432/db",
        ],
    )
    def test_قيم_تشبه_الاسرار_مرفوضة(self, قيمة):
        """ولو كان المفتاحُ بريئًا: القيمةُ نفسُها تُفشي السرّ."""
        with pytest.raises(OutboxSecretMaterialError):
            EffectPayload(data={"note": قيمة})

    def test_لا_سر_في_الملف_المثبت(self, صندوق, إذنٌ_نافذ, أثرٌ_خارجيّ, مسارُ_الصادر):
        """القياسُ على النصِّ المكتوبِ فعلًا لا على النيّة."""
        with pytest.raises(OutboxSecretMaterialError):
            صندوق.enqueue(
                permit=إذنٌ_نافذ,
                effect=أثرٌ_خارجيّ,
                operation_key="op:1",
                provider=مُزوّدٌ_ناجح(),
                # truth-audit: not-a-secret — قيمةٌ مُختَرَعةٌ في اختبارٍ سلبيّ
                payload=EffectPayload(data={"api_key": "SECRET-XYZ"}),
            )
        assert not مسارُ_الصادر.exists()

    def test_نص_الخطأ_ينقى_من_السر(self, صندوق, إذنٌ_نافذ, أثرٌ_خارجيّ, حمولة, سجلُّ_الصادر, مسارُ_الصادر):
        """رسالةُ المُزوّدِ قد تحملُ سرًّا — فتُنقّى قبلَ التثبيت."""
        class مُفشٍ(_مُزوّدٌ_أساس):
            def deliver(self, envelope: EffectEnvelope) -> DeliveryReceipt:
                raise ProviderDeliveryError(
                    "رُفِضَ الطلبُ بالرأس Bearer abcdefghijklmnopqrs"
                )

        مُزوّد = مُفشٍ()
        صندوق.enqueue(
            permit=إذنٌ_نافذ,
            effect=أثرٌ_خارجيّ,
            operation_key="op:1",
            provider=مُزوّد,
            payload=حمولة,
        )
        OutboxWorker(
            ledger=سجلُّ_الصادر, adapters={مُزوّد.name: مُزوّد}, worker_id="W1"
        ).run_once()
        نصُّ_الملفّ = مسارُ_الصادر.read_text(encoding="utf-8")
        assert "abcdefghijklmnopqrs" not in نصُّ_الملفّ
        assert "[REDACTED]" in نصُّ_الملفّ

    def test_كائن_اعتباطي_لا_يسلسل(self):
        """لا تسلسلَ أعمى: كائنٌ اعتباطيٌّ لا يدخلُ سجلًّا دائمًا."""
        with pytest.raises(OutboxPayloadError, match="اعتباطيّ"):
            EffectPayload(data={"obj": object()})

    def test_حمولة_ضخمة_مرفوضة(self):
        with pytest.raises(OutboxPayloadError, match="يتجاوزُ الحدَّ"):
            EffectPayload(data={"blob": "x" * 20_000})

    def test_نسخة_الحمولة_مثبتة_وموجبة(self, حمولة):
        assert حمولة.version == 1
        assert حمولة.as_dict()["version"] == 1
        with pytest.raises(OutboxPayloadError):
            EffectPayload(data={"a": 1}, version=0)

    def test_حمولة_غير_خريطة_مرفوضة(self):
        with pytest.raises(OutboxPayloadError):
            EffectPayload(data=[1, 2, 3])  # type: ignore[arg-type]

    def test_مفتاح_غير_نصي_مرفوض(self):
        with pytest.raises(OutboxPayloadError, match="غيرُ نصّيٍّ"):
            EffectPayload(data={1: "a"})  # type: ignore[dict-item]


# ═══════════════════════════════════════════════════════════════════════════
# 8 — حدُّ السلطة (المتطلّب 15)
# ═══════════════════════════════════════════════════════════════════════════

class Testحدُّالسلطة:
    def test_الصندوق_لا_يملك_مفتاح_توقيع(self, صندوق):
        """من ملكَ مفتاحَ التوقيعِ أذِنَ لنفسِه. فليس عندَه إلّا التحقّق."""
        assert set(SovereignOutbox.__slots__) == {"ledger", "verifying_key"}
        assert isinstance(صندوق.verifying_key, ed25519.Ed25519PublicKey)
        assert not isinstance(صندوق.verifying_key, ed25519.Ed25519PrivateKey)
        assert not hasattr(صندوق.verifying_key, "sign")

    def test_الوحدة_لا_تستورد_محركا_ولا_بوابة_ولا_تاجا(self):
        """امتناعٌ بنيويٌّ يُقاسُ على المصدرِ لا على السلوك."""
        مصدر = Path("core/sovereignty/outbox.py").read_text(encoding="utf-8")
        سطور = "\n".join(
            س for س in مصدر.splitlines() if س.startswith(("import ", "from "))
        )
        assert "constitutional_engine" not in سطور
        assert "gateway" not in سطور
        assert "crown" not in سطور
        assert "authority" not in سطور
        assert "ROYAL" not in مصدر
        assert "CROWN" not in مصدر

    def test_لا_رايات_تجاوز_في_اي_دالة(self):
        """المتطلّب 15: لا `force` ولا `bypass` ولا `override` في الوحدةِ كلِّها."""
        مصدر = Path("core/sovereignty/outbox.py").read_text(encoding="utf-8")
        شجرة = ast.parse(مصدر)
        for عقدة in ast.walk(شجرة):
            if isinstance(عقدة, (ast.FunctionDef, ast.AsyncFunctionDef)):
                أسماء = {
                    a.arg
                    for a in list(عقدة.args.args)
                    + list(عقدة.args.kwonlyargs)
                    + list(عقدة.args.posonlyargs)
                }
                مُخالِف = أسماء & FORBIDDEN_BYPASS_PARAMS
                assert not مُخالِف, f"{عقدة.name} يحملُ {مُخالِف}"

    def test_الادراج_بلا_اذن_غير_ممكن(self):
        """التوقيعُ يُثبِتُ أنّ الإذنَ مُعامِلٌ إلزاميّ — لا افتراضَ فيه."""
        بصمة = inspect.signature(SovereignOutbox.enqueue)
        assert بصمة.parameters["permit"].default is inspect.Parameter.empty
        assert بصمة.parameters["permit"].kind is inspect.Parameter.KEYWORD_ONLY

    def test_اذن_مزور_مرفوض(self, صندوق, أثرٌ_خارجيّ, حمولة, مسارُ_الصادر):
        """أخطرُ الحالات: مَن يأذنُ لنفسِه بمفتاحٍ من عندِه."""
        دخيل = ed25519.Ed25519PrivateKey.generate()
        مُزوَّر = _إذن(private_key=دخيل, effect=أثرٌ_خارجيّ)
        with pytest.raises(OutboxAuthorityError, match="تزويرٌ"):
            صندوق.enqueue(
                permit=مُزوَّر,
                effect=أثرٌ_خارجيّ,
                operation_key="op:1",
                provider=مُزوّدٌ_ناجح(),
                payload=حمولة,
            )
        assert not مسارُ_الصادر.exists()

    def test_اذن_بلا_توقيع_مرفوض(self, صندوق, مفتاحُ_القرار, أثرٌ_خارجيّ, حمولة):
        عقد = bind_contract(
            actor="EXECUTIVE",
            action="settle_invoice",
            target=TARGET,
            declared_effects=(أثرٌ_خارجيّ,),
        )
        موقَّع = issue_permit(
            contract=عقد,
            request_fingerprint="RF-1",
            decision="ALLOW",
            ledger_entry_hash=None,
            private_key=مفتاحُ_القرار,
        )
        غير_موقَّع = EnforcementPermit(
            **{**موقَّع.as_dict(), "signature_hex": ""}
        )
        with pytest.raises(OutboxAuthorityError, match="بلا توقيع"):
            صندوق.enqueue(
                permit=غير_موقَّع,
                effect=أثرٌ_خارجيّ,
                operation_key="op:1",
                provider=مُزوّدٌ_ناجح(),
                payload=حمولة,
            )

    def test_المنع_لا_يتحول_الى_اذن(self, صندوق, مفتاحُ_القرار, أثرٌ_خارجيّ, حمولة, مسارُ_الصادر):
        """المتطلّب 15 صريحًا: `DENY` لا يصيرُ أثرًا خارجيًّا بحال."""
        مانع = _إذن(
            private_key=مفتاحُ_القرار, effect=أثرٌ_خارجيّ, decision="DENY"
        )
        with pytest.raises(OutboxAuthorityError, match="لا يُحوِّلُ المنعَ"):
            صندوق.enqueue(
                permit=مانع,
                effect=أثرٌ_خارجيّ,
                operation_key="op:1",
                provider=مُزوّدٌ_ناجح(),
                payload=حمولة,
            )
        assert not مسارُ_الصادر.exists()

    def test_اذن_منقض_مرفوض(self, صندوق, مفتاحُ_القرار, أثرٌ_خارجيّ, حمولة):
        قديم = datetime.now(timezone.utc) - timedelta(hours=2)
        مُنقضٍ = _إذن(
            private_key=مفتاحُ_القرار,
            effect=أثرٌ_خارجيّ,
            ttl_seconds=60,
            now=قديم,
        )
        with pytest.raises(OutboxAuthorityError, match="انقضى"):
            صندوق.enqueue(
                permit=مُنقضٍ,
                effect=أثرٌ_خارجيّ,
                operation_key="op:1",
                provider=مُزوّدٌ_ناجح(),
                payload=حمولة,
            )

    def test_اثر_خارج_نطاق_الاذن_مرفوض(self, صندوق, إذنٌ_نافذ, حمولة):
        """لا توسيعَ لنطاقٍ مُعلَن: إذنٌ لموردٍ لا يأذنُ لغيرِه."""
        آخر = external_effect_of(resource="external/payments/refund")
        with pytest.raises(OutboxAuthorityError, match="لا يشملُ"):
            صندوق.enqueue(
                permit=إذنٌ_نافذ,
                effect=آخر,
                operation_key="op:1",
                provider=مُزوّدٌ_ناجح(),
                payload=حمولة,
            )

    def test_اثر_غير_خارجي_مرفوض(self, صندوق, مفتاحُ_القرار, حمولة):
        """الصندوقُ ليس مسارًا موازيًا للأثرِ المحلّيّ."""
        محلّيّ = SovereignEffect(kind=EffectKind.WRITE, resource=RESOURCE)
        إذن = _إذن(private_key=مفتاحُ_القرار, effect=محلّيّ)
        with pytest.raises(OutboxError, match="ليس خارجيًّا"):
            صندوق.enqueue(
                permit=إذن,
                effect=محلّيّ,
                operation_key="op:1",
                provider=مُزوّدٌ_ناجح(),
                payload=حمولة,
            )

    def test_اثر_بلا_مفتاح_عملية_مرفوض(self, صندوق, إذنٌ_نافذ, أثرٌ_خارجيّ, حمولة):
        with pytest.raises(OutboxError, match="بلا مفتاحِ عمليّة"):
            صندوق.enqueue(
                permit=إذنٌ_نافذ,
                effect=أثرٌ_خارجيّ,
                operation_key="  ",
                provider=مُزوّدٌ_ناجح(),
                payload=حمولة,
            )

    def test_المحول_لا_يرى_الاذن_ولا_مفتاحا(self, مُدرَج, سجلُّ_الصادر):
        """المُحوّلُ ينقلُ ولا يقرّر — فلا يُعطى إلّا مرساةَ إذنٍ للتدقيق."""
        _, مُزوّد = مُدرَج
        OutboxWorker(
            ledger=سجلُّ_الصادر, adapters={مُزوّد.name: مُزوّد}, worker_id="W1"
        ).run_once()
        مظروف = مُزوّد.envelopes[0]
        حقول = set(EffectEnvelope.__slots__)
        assert "permit" not in حقول
        assert not any("key" in ح for ح in حقول if ح != "operation_key")
        assert مظروف.authorization_anchor == "LE-anchor-1"

    def test_العامل_لا_يملك_اذنا_ولا_مفتاحا(self):
        """آلةُ التسليمِ تُسلّمُ ما أُدرِجَ بإذنٍ — ولا تُدرِج."""
        حقول = set(OutboxWorker.__slots__)
        assert حقول == {
            "ledger",
            "adapters",
            "worker_id",
            "lease_seconds",
            "max_attempts",
        }
        assert "verifying_key" not in حقول
        assert not hasattr(OutboxWorker, "enqueue")


# ═══════════════════════════════════════════════════════════════════════════
# 9 — لا زعمَ تسليمٍ مرّةً واحدةً بالضبط
# ═══════════════════════════════════════════════════════════════════════════

class Testحدودُالصدق:
    def test_الوحدة_لا_تزعم_مرة_واحدة_بالضبط(self):
        مصدر = Path("core/sovereignty/outbox.py").read_text(encoding="utf-8")
        assert "exactly-once" in مصدر  # مذكورةٌ لتُنفى صراحةً
        assert "AT_LEAST_ONCE_WITH_STABLE_IDEMPOTENCY_IDENTITY" in مصدر

    def test_الفحص_الذاتي_ينفي_الزعم(self, مُدرَج, سجلُّ_الصادر):
        _, مُزوّد = مُدرَج
        عامل = OutboxWorker(
            ledger=سجلُّ_الصادر, adapters={مُزوّد.name: مُزوّد}, worker_id="W1"
        )
        فحص = عامل.self_check()
        assert فحص["claims_exactly_once"] is False
        assert فحص["guarantee"] == "AT_LEAST_ONCE_WITH_STABLE_IDEMPOTENCY_IDENTITY"
        assert فحص["pending"] == 1
        عامل.run_once()
        assert عامل.self_check()["delivered"] == 1

    def test_التسليم_لا_يشهد_له_الا_حالة_واحدة(self):
        """لا استنتاجَ تسليمٍ من `PENDING` ولا من `INDETERMINATE`."""
        assert [س for س in DeliveryStatus if س.certifies_delivery] == [
            DeliveryStatus.DELIVERED
        ]

    def test_الغموض_ليس_نهاية(self):
        assert not DeliveryStatus.INDETERMINATE.is_terminal
        assert DeliveryStatus.DELIVERED.is_terminal
        assert DeliveryStatus.DEAD.is_terminal

    def test_لكل_حالة_عبارة_عربية(self):
        for حالة in DeliveryStatus:
            assert حالة.arabic

    def test_العامل_يرفض_تجهيزا_غير_سليم(self, سجلُّ_الصادر):
        with pytest.raises(OutboxError):
            OutboxWorker(ledger=سجلُّ_الصادر, adapters={}, worker_id=" ")
        with pytest.raises(OutboxError):
            OutboxWorker(ledger=سجلُّ_الصادر, adapters={}, worker_id="W", lease_seconds=0)
        with pytest.raises(OutboxError):
            OutboxWorker(ledger=سجلُّ_الصادر, adapters={}, worker_id="W", max_attempts=0)
        with pytest.raises(OutboxError):
            OutboxWorker(
                ledger=سجلُّ_الصادر, adapters={}, worker_id="W"
            ).drain(limit=0)

    def test_العقد_الزمني_الافتراضي_محدود(self):
        assert 0 < DEFAULT_LEASE_SECONDS <= 300


# ═══════════════════════════════════════════════════════════════════════════
# 10 — المراحلُ السابقةُ لم تُنقَض (16 · 17 · 18)
# ═══════════════════════════════════════════════════════════════════════════

class Testالمراحلُالسابقةُقائمة:
    def test_تفرد_1H_باقٍ_مع_الصندوق(self, tmp_path, صندوق, إذنٌ_نافذ, أثرٌ_خارجيّ, حمولة, سجلُّ_الصادر):
        """المتطلّب 16: `run_once` ما زال ينفّذُ مرّةً — والصادرُ يُدرَجُ داخلَه."""
        سجلُّ_التفرُّد = IdempotencyLedger(path=tmp_path / "IDEMPOTENCY.json")
        حارس = IdempotencyGuard(ledger=سجلُّ_التفرُّد)
        مفتاح = IdempotencyKey(scope="invoice", value="INV-7")
        بصمة = compute_fingerprint(
            scope="invoice",
            action="settle",
            target=TARGET,
            effect_signatures=(أثرٌ_خارجيّ.signature,),
        )
        عدّاد = {"n": 0}
        مُزوّد = مُزوّدٌ_ناجح()

        def نفِّذ() -> str:
            عدّاد["n"] += 1
            enqueue_write_ahead(
                outbox=صندوق,
                idempotency_ledger=سجلُّ_التفرُّد,
                key=مفتاح,
                permit=إذنٌ_نافذ,
                effect=أثرٌ_خارجيّ,
                provider=مُزوّد,
                payload=حمولة,
            )
            return "تمّ"

        أوّل = حارس.run_once(
            key=مفتاح,
            fingerprint=بصمة,
            execute=نفِّذ,
            detect_external=lambda _: True,
        )
        ثانٍ = حارس.run_once(key=مفتاح, fingerprint=بصمة, execute=نفِّذ)
        assert عدّاد["n"] == 1
        assert أوّل.status is OperationStatus.SUCCEEDED
        assert ثانٍ.is_replay is True
        assert أوّل.record.has_external_effect is True
        assert سجلُّ_الصادر.count() == 1

    def test_تعويض_1I_باقٍ(self, tmp_path):
        """المتطلّب 17: التعويضُ يعملُ كما كان — لم يُلمَسْ عقدُه."""
        حارس = CompensationGuard(
            journal=CompensationJournal(path=tmp_path / "COMPENSATION.json"),
            idempotency=IdempotencyGuard(
                ledger=IdempotencyLedger(path=tmp_path / "IDEMPOTENCY.json")
            ),
        )
        أثر = SovereignEffect(kind=EffectKind.WRITE, resource="ledger/row-1")
        عقد = bind_contract(
            actor="EXECUTIVE",
            action="write_row",
            target="ledger",
            declared_effects=(أثر,),
        )
        رجوع: list[str] = []
        خطّة = bind_compensation_plan(
            contract=عقد,
            compensators=(
                Compensator(
                    effect_signature=أثر.signature,
                    apply=lambda: رجوع.append("تراجَع"),
                    description="حذفُ الصفّ",
                ),
            ),
        )
        نتيجة = حارس.compensate(
            contract=عقد,
            plan=خطّة,
            operation_key=IdempotencyKey(scope="op", value="1"),
            applied_signatures=(أثر.signature,),
            reason="فشلٌ جزئيّ",
        )
        assert نتيجة.record.status is CompensationStatus.COMPENSATED
        assert رجوع == ["تراجَع"]

    def test_فشل_1J_المغلق_باقٍ(self):
        """المتطلّب 18: لا شهادةَ تنفيذٍ بلا مرساةٍ ونجاحٍ فعليّ."""
        محاولة = attempt_execution(lambda: "تمّ", audit_anchor="LE-1")
        assert محاولة.completion is ExecutionCompletion.COMPLETED
        assert محاولة.certified is True
        فاشلة = attempt_execution(
            lambda: (_ for _ in ()).throw(RuntimeError("خلل")),
            audit_anchor="LE-1",
        )
        assert فاشلة.completion is ExecutionCompletion.EXECUTION_FAILED
        assert فاشلة.certified is False

    def test_الاثر_الخارجي_ما_زال_ممنوعا_في_المسار_الذري(self, tmp_path, أثرٌ_خارجيّ):
        """عقدُ 1H لم يُنقَض: الأثرُ الخارجيُّ لا يُطبَّقُ في المسارِ المباشر."""
        from core.sovereignty.idempotency import IdempotencyError

        حارس = IdempotencyGuard(
            ledger=IdempotencyLedger(path=tmp_path / "IDEMPOTENCY.json")
        )
        with pytest.raises(IdempotencyError, match="outbox"):
            حارس.run_effects_once(
                key=IdempotencyKey(scope="a", value="b"),
                fingerprint="FP",
                declared_effects=(أثرٌ_خارجيّ.signature,),
                apply_effect=lambda _: None,
            )
