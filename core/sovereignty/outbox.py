# ---------------------------------------------------------------------------
# الهدف: صندوقُ الصادرِ الدائم — تثبيتُ الأثرِ الخارجيِّ على القرصِ قبلَ إرساله،
#        وتسليمُه مرّةً واحدةً على الأقلّ بهويّةٍ ثابتة، وتمثيلُ الغموضِ صراحةً
#        حين لا تُعرَفُ نتيجةُ النداءِ الخارجيّ.
# النطاق: المرحلة 1K — الأثرُ الخارجيُّ وحدَه. لا سلطةَ، ولا تعويض، ولا استئنافَ
#        تدفّقِ الاستعادة، ولا مراقبةً كمرحلة.
# المالك: الوكيلُ المُنفِّذ · اتّحادُ AMOS
# تاريخ الإنشاء: 2026-08-18
# تاريخ آخر تعديل: 2026-08-18
# ---------------------------------------------------------------------------
"""صندوقُ الصادرِ السياديّ (Durable External Effects Outbox).

**المشكلةُ التي يحلُّها:** قبلَ هذه المرحلةِ كانت الدولةُ تُثبِّتُ حالتَها محلّيًّا
ثمّ تصمتُ عن الأثرِ الخارجيّ. فكان «سُجِّلَ محلّيًّا» يُقرَأُ ضمنًا «نُفِّذَ
خارجيًّا»، وكان سقوطُ العمليّةِ يُفقِدُ الأثرَ الخارجيَّ من الوجودِ المُدقَّق.
وقد نصَّ عقدُ 1H على ذلك حرفًا: «الأثرُ الخارجيُّ يحتاجُ outbox منفصل».

**ما يُثبِتُه هذا الملفّ:**

- الأثرُ الخارجيُّ يُثبَّتُ على القرصِ (`OutboxLedger`) قبلَ أيِّ نداء. فبعدَ
  السقوطِ يبقى موجودًا ويُكتشَف.
- التسليمُ عملٌ حقيقيٌّ لا بنيةُ بيانات: `OutboxWorker` يحجزُ بعقدٍ زمنيٍّ
  (lease) دائم، ثمّ يُسلّم، ثمّ يُثبِّتُ النتيجة.
- الحجزُ المهجورُ يُستعاد: العاملُ الساقطُ لا يُجمِّدُ الأثرَ إلى الأبد.
- **الغموضُ لا يُكذَب:** إن سقطت العمليّةُ بينَ النداءِ وتثبيتِ نتيجتِه، فالحالةُ
  `INDETERMINATE` — لا `DELIVERED` ولا `FAILED`. لأنّ الأثرَ **قد** وقع.
- الهويّةُ المنطقيّةُ للأثرِ ثابتةٌ عبرَ المحاولات (`effect_id`)، وتُرسَلُ إلى
  المُزوّدِ كرقمِ تفرُّدٍ (idempotency token) فلا تُنشئُ الإعادةُ أثرًا ثانيًا حيث
  يدعمُ المُزوّدُ التفرُّد.

**ما لا يملكُه هذا الملفّ — وهو تعريفُه:** لا مفتاحَ توقيع، ولا محرّكًا دستوريًّا،
ولا بوّابةً سياديّة، ولا سجلَّ مِنَحٍ. الصندوقُ **آلةُ تنفيذٍ لا آلةُ سلطة**:
يطلبُ إذنًا موقَّعًا صادرًا من موضعِ القرار (`EnforcementPermit`)، ويتحقّقُ منه،
ولا يُصدِرُه ولا يُوسِّعُه. ولا يملكُ `force` ولا `bypass` ولا `override`.

**حدُّ الذرّيّةِ الحقيقيُّ — مُعلَنٌ لا مُخفًى:** حالةُ العمليّةِ في سجلِّ 1H وسجلُّ
الصادرِ ملفّانِ منفصلانِ على القرص. فلا توجدُ ذرّيّةٌ حقيقيّةٌ عبرَهما، ولن
نتصنّعَها. والمُعتمَدُ هو **ترتيبُ الديمومة (write-ahead)**: سجلُّ الصادرِ يُكتَبُ
قبلَ أن تُثبَّتَ العمليّةُ ناجحةً. فالنافذةُ الوحيدةُ الممكنةُ هي «سجلُّ صادرٍ
موجودٌ لعمليّةٍ لم تكتمل» — وهي حالةٌ تُكتشَفُ صراحةً بـ`orphaned_effects`. أمّا
النافذةُ الخطرةُ العكسيّةُ («عمليّةٌ ناجحةٌ بلا سجلِّ صادر») فمرفوضةٌ بنيويًّا:
`enqueue_write_ahead` يرفعُ `OutboxOrderingError` إن كانت العمليّةُ قد نجحت.

**الحدُّ الآخرُ المُعلَن:** لا نزعمُ تسليمًا مرّةً واحدةً بالضبط (exactly-once).
المُثبَتُ هو **مرّةً واحدةً على الأقلّ + هويّةُ تفرُّدٍ ثابتة**. وحيثُ لا يدعمُ
المُزوّدُ التفرُّدَ يُسجَّلُ ذلك في السجلِّ نفسِه (`provider_supports_idempotency`)
ويبقى الأثرُ الغامضُ غامضًا ولا يُعادُ إرسالُه تلقائيًّا.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from threading import RLock
from typing import Any, Final, Protocol, runtime_checkable

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ed25519

from core.sovereignty.contract import EffectKind, SovereignEffect
from core.sovereignty.enforcement import EnforcementPermit
from core.sovereignty.idempotency import (
    IdempotencyKey,
    IdempotencyLedger,
    OperationStatus,
)

OUTBOX_DOMAIN: Final[bytes] = b"AMOS-FEDERATION/OUTBOX/v1"
PAYLOAD_SCHEMA_VERSION: Final[int] = 1
MAX_PAYLOAD_BYTES: Final[int] = 16_384
DEFAULT_LEASE_SECONDS: Final[int] = 30
DEFAULT_MAX_DELIVERY_ATTEMPTS: Final[int] = 3
MAX_ERROR_DETAIL_CHARS: Final[int] = 400

#: أسماءُ مفاتيحٍ لا تُحفَظُ في حمولةٍ دائمةٍ بحالٍ — السرُّ لا يُخزَّن.
FORBIDDEN_PAYLOAD_KEY_TOKENS: Final[tuple[str, ...]] = (
    "secret",
    "token",
    "password",
    "passwd",
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "private_key",
    "privatekey",
    "access_key",
    "session_key",
    "signing_key",
    "bearer",
)

#: بصماتُ قيمٍ تُشبهُ الأسرارَ المعروفة — تُرفَضُ ولو كان المفتاحُ بريئًا.
SECRET_VALUE_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{12,}"),
    re.compile(r"\bsb_(?:publishable|secret)_[A-Za-z0-9._\-]{8,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}"),
    re.compile(r"\bsk-[A-Za-z0-9]{16,}"),
    re.compile(r"\bpostgres(?:ql)?://[^\s:]+:[^\s@]+@"),
)


# ── الأخطاء ────────────────────────────────────────────────────────────────
class OutboxError(Exception):
    """خللٌ في صندوقِ الصادر."""


class OutboxAuthorityError(OutboxError):
    """محاولةُ إدراجِ أثرٍ بلا إذنٍ صالحٍ سابقٍ — الصندوقُ لا يأذن."""


class OutboxPayloadError(OutboxError):
    """حمولةٌ لا تصلحُ للتثبيتِ الدائم."""


class OutboxSecretMaterialError(OutboxPayloadError):
    """موادُّ سرّيّةٌ في حمولةٍ دائمة — تُرفَضُ قبلَ أن تُكتَب."""


class OutboxStateError(OutboxError):
    """انتقالُ حالةٍ غيرُ مشروعٍ في سجلِّ الصادر."""


class OutboxOrderingError(OutboxError):
    """إدراجٌ بعدَ تثبيتِ نجاحِ العمليّة — يخرقُ ترتيبَ الديمومة."""


class OutboxClaimError(OutboxError):
    """حجزٌ متعارضٌ على أثرٍ واحد."""


class ProviderDeliveryError(Exception):
    """فشلٌ يُقرُّ المُزوّدُ بأنّه وقعَ **قبلَ** أن يُحدِثَ أثرًا خارجيًّا."""


class ProviderIndeterminateError(Exception):
    """نتيجةٌ مجهولة: المُزوّدُ لا يعرفُ هل وقعَ الأثرُ أم لا."""


# ── أدواتُ القرصِ والزمن (بالانضباطِ نفسِه المُستعمَلِ في 1E و1H) ────────────
def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(moment: datetime | None = None) -> str:
    return (moment or _now()).isoformat()


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _canonical(payload: Any) -> bytes:
    """تمثيلٌ قانونيٌّ حاسم — البصمةُ لا تتغيّرُ بترتيبِ المفاتيح."""
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _atomic_write(path: Path, payload: Mapping[str, Any]) -> None:
    """كتابةٌ ذرّيّةٌ مع `fsync` — إمّا الملفُّ القديمُ كاملًا أو الجديدُ كاملًا.

    الكتابةُ المباشرةُ تترك ملفًّا نصفَ مكتوبٍ عندَ السقوط، وذلك أسوأُ من
    الخسارة: سجلٌّ تالفٌ يُقرأُ حقيقةً.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False
        ) as handle:
            tmp_name = handle.name
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
        tmp_name = None
    except BaseException:
        if tmp_name is not None and os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def _safe_detail(text: str) -> str:
    """نصُّ خطأٍ آمنٌ للتثبيت: محدودُ الطول ومُنقّىً من موادَّ سرّيّةٍ معروفة."""
    cleaned = text
    for pattern in SECRET_VALUE_PATTERNS:
        cleaned = pattern.sub("[REDACTED]", cleaned)
    if len(cleaned) > MAX_ERROR_DETAIL_CHARS:
        cleaned = cleaned[:MAX_ERROR_DETAIL_CHARS] + "…"
    return cleaned


# ── الحمولة ────────────────────────────────────────────────────────────────
_ALLOWED_SCALARS = (str, int, float, bool, type(None))


def _validate_node(node: Any, *, trail: str) -> None:
    if isinstance(node, Mapping):
        for key, value in node.items():
            if not isinstance(key, str):
                raise OutboxPayloadError(
                    f"مفتاحٌ غيرُ نصّيٍّ في «{trail}». الحمولةُ الدائمةُ نصّيّةُ "
                    "المفاتيحِ حتمًا وإلّا لم تكن قانونيّةَ التمثيل."
                )
            lowered = key.lower()
            for token in FORBIDDEN_PAYLOAD_KEY_TOKENS:
                if token in lowered:
                    raise OutboxSecretMaterialError(
                        f"المفتاحُ «{trail}.{key}» يشيرُ إلى مادّةٍ سرّيّة. "
                        "الصندوقُ لا يُخزّنُ سرًّا ولو طُلِبَ منه."
                    )
            _validate_node(value, trail=f"{trail}.{key}")
        return
    if isinstance(node, (list, tuple)):
        for index, value in enumerate(node):
            _validate_node(value, trail=f"{trail}[{index}]")
        return
    if isinstance(node, _ALLOWED_SCALARS):
        if isinstance(node, str):
            for pattern in SECRET_VALUE_PATTERNS:
                if pattern.search(node):
                    raise OutboxSecretMaterialError(
                        f"قيمةُ «{trail}» تطابقُ نمطَ سرٍّ معروف. لا تُثبَّت."
                    )
        return
    raise OutboxPayloadError(
        f"القيمةُ في «{trail}» من نوع `{type(node).__name__}`. الحمولةُ الدائمةُ "
        "تقبلُ النصَّ والعددَ والمنطقيَّ والفراغَ والقوائمَ والخرائطَ فقط — "
        "ولا يُسلسَلُ كائنٌ اعتباطيّ."
    )


@dataclass(frozen=True, slots=True)
class EffectPayload:
    """حمولةُ أثرٍ خارجيّ: مُنسَّخةٌ، حاسمةُ التمثيل، محدودةُ الحجم، بلا سرّ.

    `version` ليس ترفًا: الأثرُ يبقى في السجلِّ بعدَ تغيُّرِ الكود، ومَن يقرأُه
    بعدَ سنةٍ يحتاجُ أن يعرفَ بأيِّ عقدٍ كُتِب.
    """

    data: Mapping[str, Any]
    version: int = PAYLOAD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.version < 1:
            raise OutboxPayloadError("نسخةُ الحمولةِ يجب أن تكون موجَبة.")
        if not isinstance(self.data, Mapping):
            raise OutboxPayloadError("الحمولةُ خريطةٌ مُسمّاةٌ لا قيمةٌ حُرّة.")
        _validate_node(dict(self.data), trail="payload")
        raw = _canonical(self.canonical_data())
        if len(raw) > MAX_PAYLOAD_BYTES:
            raise OutboxPayloadError(
                f"حجمُ الحمولةِ {len(raw)} بايت يتجاوزُ الحدَّ {MAX_PAYLOAD_BYTES}. "
                "السجلُّ الدائمُ ليس مستودعَ ملفّات."
            )

    def canonical_data(self) -> dict[str, Any]:
        return json.loads(json.dumps(self.data, ensure_ascii=False, sort_keys=True))

    @property
    def digest(self) -> str:
        return "PD-" + hashlib.sha256(
            OUTBOX_DOMAIN + b"|" + _canonical(
                {"version": self.version, "data": self.canonical_data()}
            )
        ).hexdigest()[:24]

    def as_dict(self) -> dict[str, Any]:
        return {"version": self.version, "data": self.canonical_data()}


# ── الحالةُ الدائمة ────────────────────────────────────────────────────────
class DeliveryStatus(str, Enum):
    """حالاتُ تسليمِ الأثرِ الخارجيّ — منفصلةٌ عن حالةِ العمليّةِ السياديّة.

    دمجُ الحالتينِ في منطقيٍّ واحدٍ هو الكذبةُ التي تُبنى عليها الأنظمة: نجاحُ
    المعاملةِ محلّيًّا لا يقولُ شيئًا عن وقوعِ النداءِ الخارجيّ.

    و`INDETERMINATE` ليست حالةً زائدة: هي الحالةُ الوحيدةُ الصادقةُ حينَ يسقطُ
    العاملُ وهو داخلَ النداء. تصنيفُها `FAILED` كذبٌ قد يُضاعِفُ الأثر، وتصنيفُها
    `DELIVERED` كذبٌ قد يُسقِطُه.
    """

    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    DELIVERED = "DELIVERED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    DEAD = "DEAD"
    INDETERMINATE = "INDETERMINATE"

    @property
    def is_terminal(self) -> bool:
        """هل انتهى الأمرُ نهائيًّا؟ الغموضُ **ليس** نهايةً: يبقى مفتوحًا."""
        return self in (DeliveryStatus.DELIVERED, DeliveryStatus.DEAD)

    @property
    def certifies_delivery(self) -> bool:
        """لا شيءَ يشهدُ بالتسليمِ إلّا `DELIVERED` — ولا استنتاجَ من غيرِه."""
        return self is DeliveryStatus.DELIVERED

    @property
    def is_ambiguous(self) -> bool:
        return self is DeliveryStatus.INDETERMINATE

    @property
    def arabic(self) -> str:
        return _DELIVERY_ARABIC[self]


_DELIVERY_ARABIC: Final[dict[DeliveryStatus, str]] = {
    DeliveryStatus.PENDING: "معلَّقٌ للإرسال",
    DeliveryStatus.CLAIMED: "محجوزٌ لعامل",
    DeliveryStatus.DELIVERED: "سُلِّمَ بتأكيد",
    DeliveryStatus.FAILED_RETRYABLE: "فشلَ ويقبلُ الإعادة",
    DeliveryStatus.DEAD: "فشلٌ نهائيّ · صندوقُ الموتى",
    DeliveryStatus.INDETERMINATE: "نتيجةٌ مجهولة · قد يكونُ وقع",
}


class DeliveryOutcome(str, Enum):
    """ما يقولُه المُزوّدُ عن نداءٍ واحد."""

    SUCCESS = "SUCCESS"
    DUPLICATE = "DUPLICATE"
    RETRYABLE_FAILURE = "RETRYABLE_FAILURE"
    PERMANENT_FAILURE = "PERMANENT_FAILURE"
    INDETERMINATE = "INDETERMINATE"


@dataclass(frozen=True, slots=True)
class DeliveryReceipt:
    """إيصالُ نداءٍ واحد — يُثبَّتُ في السجلِّ ولا يُلخَّصُ في منطقيّ."""

    outcome: DeliveryOutcome
    provider_reference: str = ""
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome.value,
            "provider_reference": self.provider_reference,
            "detail": _safe_detail(self.detail),
        }


@dataclass(frozen=True, slots=True)
class EffectEnvelope:
    """ما يُعطى للمُحوّلِ الخارجيّ — ولا شيءَ غيرَه.

    لا إذنَ موقَّعًا ولا مفتاحًا ولا سجلًّا: المُحوّلُ ينقلُ ولا يقرّر.
    """

    effect_id: str
    idempotency_token: str
    operation_key: str
    effect_signature: str
    provider: str
    payload_version: int
    payload: Mapping[str, Any]
    attempt: int
    attempt_id: str
    authorization_anchor: str
    correlation_id: str = ""


@runtime_checkable
class ProviderAdapter(Protocol):
    """حدُّ النظامِ الخارجيّ: `Outbox → ExternalEffect → Adapter → External`.

    `supports_idempotency` إقرارٌ يُثبَّتُ في السجلِّ لحظةَ الإدراج: عليه يُبنى
    قرارُ إعادةِ المحاولةِ بعدَ الغموض. مُزوّدٌ لا يدعمُ التفرُّدَ لا يُعادُ
    نداؤه على أثرٍ غامضٍ — والدولةُ تُصرِّحُ بذلك ولا تُخفيه.
    """

    name: str
    supports_idempotency: bool

    def deliver(self, envelope: EffectEnvelope) -> DeliveryReceipt: ...


# ── السجلُّ الدائم ──────────────────────────────────────────────────────────
@dataclass(slots=True)
class OutboxRecord:
    """سجلُّ أثرٍ خارجيٍّ واحد — كلُّ ما يحتاجُه المُدقّقُ بعدَ السقوط."""

    effect_id: str
    operation_key: str
    effect_signature: str
    provider: str
    provider_supports_idempotency: bool
    status: DeliveryStatus
    payload_version: int
    payload: dict[str, Any]
    payload_digest: str
    permit_id: str
    authorization_anchor: str
    created_at: str
    updated_at: str
    attempt_count: int = 0
    attempts: list[dict[str, Any]] = field(default_factory=list)
    transitions: list[dict[str, Any]] = field(default_factory=list)
    claimed_by: str | None = None
    claimed_at: str | None = None
    lease_expires_at: str | None = None
    in_flight_attempt_id: str | None = None
    delivered_at: str | None = None
    provider_reference: str | None = None
    failure_reason: str | None = None
    terminal_reason: str | None = None
    correlation_id: str = ""

    @property
    def idempotency_token(self) -> str:
        """هويّةُ التفرُّدِ المُرسَلةُ للمُزوّد — ثابتةٌ عبرَ كلِّ المحاولات."""
        return self.effect_id

    @property
    def requires_human_resolution(self) -> bool:
        """غموضٌ لا يقبلُ إعادةً آليّة: لا بدَّ من فصلٍ بشريّ."""
        return (
            self.status is DeliveryStatus.INDETERMINATE
            and not self.provider_supports_idempotency
        )

    def is_claimable(self, *, now: datetime | None = None) -> bool:
        """هل يجوزُ حجزُه الآن؟ الغامضُ يُعادُ فقط إن كان المُزوّدُ متفرِّدًا."""
        moment = now or _now()
        if self.status in (DeliveryStatus.PENDING, DeliveryStatus.FAILED_RETRYABLE):
            return True
        if self.status is DeliveryStatus.INDETERMINATE:
            return self.provider_supports_idempotency
        if self.status is DeliveryStatus.CLAIMED:
            return (
                self.lease_expires_at is not None
                and moment > _parse_iso(self.lease_expires_at)
            )
        return False

    def as_dict(self) -> dict[str, Any]:
        return {
            "effect_id": self.effect_id,
            "operation_key": self.operation_key,
            "effect_signature": self.effect_signature,
            "provider": self.provider,
            "provider_supports_idempotency": self.provider_supports_idempotency,
            "status": self.status.value,
            "payload_version": self.payload_version,
            "payload": self.payload,
            "payload_digest": self.payload_digest,
            "permit_id": self.permit_id,
            "authorization_anchor": self.authorization_anchor,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "attempt_count": self.attempt_count,
            "attempts": self.attempts,
            "transitions": self.transitions,
            "claimed_by": self.claimed_by,
            "claimed_at": self.claimed_at,
            "lease_expires_at": self.lease_expires_at,
            "in_flight_attempt_id": self.in_flight_attempt_id,
            "delivered_at": self.delivered_at,
            "provider_reference": self.provider_reference,
            "failure_reason": self.failure_reason,
            "terminal_reason": self.terminal_reason,
            "correlation_id": self.correlation_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> OutboxRecord:
        return cls(
            effect_id=data["effect_id"],
            operation_key=data["operation_key"],
            effect_signature=data["effect_signature"],
            provider=data["provider"],
            provider_supports_idempotency=bool(
                data["provider_supports_idempotency"]
            ),
            status=DeliveryStatus(data["status"]),
            payload_version=int(data["payload_version"]),
            payload=dict(data["payload"]),
            payload_digest=data["payload_digest"],
            permit_id=data["permit_id"],
            authorization_anchor=data["authorization_anchor"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            attempt_count=int(data.get("attempt_count", 0)),
            attempts=list(data.get("attempts", [])),
            transitions=list(data.get("transitions", [])),
            claimed_by=data.get("claimed_by"),
            claimed_at=data.get("claimed_at"),
            lease_expires_at=data.get("lease_expires_at"),
            in_flight_attempt_id=data.get("in_flight_attempt_id"),
            delivered_at=data.get("delivered_at"),
            provider_reference=data.get("provider_reference"),
            failure_reason=data.get("failure_reason"),
            terminal_reason=data.get("terminal_reason"),
            correlation_id=data.get("correlation_id", ""),
        )


def compute_effect_id(
    *,
    operation_key: str,
    effect_signature: str,
    provider: str,
    payload_digest: str,
) -> str:
    """هويّةٌ منطقيّةٌ حاسمةٌ للأثرِ الخارجيّ — لا عشوائيّةَ ولا زمن.

    ثباتُها هو ما يجعلُ الإعادةَ إعادةً لا أثرًا جديدًا. ولذلك لا يدخلُ فيها
    وقتٌ ولا رقمُ محاولةٍ ولا مُعرِّفٌ عشوائيّ.
    """
    material = _canonical(
        {
            "operation_key": operation_key,
            "effect_signature": effect_signature,
            "provider": provider,
            "payload_digest": payload_digest,
        }
    )
    return "OB-" + hashlib.sha256(OUTBOX_DOMAIN + b"|" + material).hexdigest()[:24]


@dataclass(slots=True)
class OutboxLedger:
    """سجلُّ الصادرِ على القرص — مصدرُ الحقيقةِ لحالةِ الأثرِ الخارجيّ.

    ليس مخزنَ ذاكرةٍ ولا طابورًا وهميًّا: ملفٌّ يُكتَبُ ذرّيًّا ويُقرأُ بعدَ
    إعادةِ التشغيل. وكلُّ انتقالٍ يُثبَّتُ **قبلَ** الفعلِ الذي يعقبُه.
    """

    path: Path
    _lock: RLock = field(default_factory=RLock, repr=False, compare=False)

    # ── قراءةٌ وكتابة ──────────────────────────────────────────────────
    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            return dict(json.loads(self.path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, ValueError) as exc:
            raise OutboxError(
                f"سجلُّ الصادرِ في «{self.path}» تالفٌ ولا يُقرأ. "
                "لا نُكمِلُ على سجلٍّ مشكوكٍ فيه."
            ) from exc

    def _save(self, records: Mapping[str, dict[str, Any]]) -> None:
        _atomic_write(self.path, records)

    def _write(self, record: OutboxRecord) -> OutboxRecord:
        records = self._load()
        records[record.effect_id] = record.as_dict()
        self._save(records)
        return record

    def get(self, effect_id: str) -> OutboxRecord | None:
        data = self._load().get(effect_id)
        return OutboxRecord.from_dict(data) if data else None

    def require(self, effect_id: str) -> OutboxRecord:
        record = self.get(effect_id)
        if record is None:
            raise OutboxStateError(f"لا سجلَّ للأثرِ «{effect_id}».")
        return record

    def all_records(self) -> list[OutboxRecord]:
        return [OutboxRecord.from_dict(v) for v in self._load().values()]

    def count(self) -> int:
        return len(self._load())

    def by_status(self, status: DeliveryStatus) -> list[OutboxRecord]:
        return [r for r in self.all_records() if r.status is status]

    def for_operation(self, operation_key: str) -> list[OutboxRecord]:
        return sorted(
            (r for r in self.all_records() if r.operation_key == operation_key),
            key=lambda r: r.effect_id,
        )

    def ambiguous(self) -> list[OutboxRecord]:
        return self.by_status(DeliveryStatus.INDETERMINATE)

    def dead_letters(self) -> list[OutboxRecord]:
        return self.by_status(DeliveryStatus.DEAD)

    # ── الانتقالات ────────────────────────────────────────────────────
    def _transition(
        self,
        record: OutboxRecord,
        new_status: DeliveryStatus,
        *,
        moment: str,
        note: str = "",
    ) -> None:
        if record.status.is_terminal and new_status is not record.status:
            raise OutboxStateError(
                f"الأثرُ «{record.effect_id}» في حالةٍ نهائيّة "
                f"«{record.status.value}». لا انتقالَ من النهائي."
            )
        record.transitions.append(
            {
                "from": record.status.value,
                "to": new_status.value,
                "at": moment,
                "note": note,
            }
        )
        record.status = new_status
        record.updated_at = moment

    def enqueue(
        self,
        *,
        effect_id: str,
        operation_key: str,
        effect_signature: str,
        provider: str,
        provider_supports_idempotency: bool,
        payload: EffectPayload,
        permit_id: str,
        authorization_anchor: str,
        correlation_id: str = "",
        now: str | None = None,
    ) -> OutboxRecord:
        """أدرِجْ أثرًا — أو أعِدِ القائمَ إن كانت الهويّةُ نفسَها.

        الإدراجُ المكرَّرُ للهويّةِ الواحدةِ **لا يُنشئُ سجلًّا ثانيًا**: هذا هو
        أوّلُ صفٍّ في الدفاعِ عن عدمِ التكرار.
        """
        with self._lock:
            records = self._load()
            existing = records.get(effect_id)
            if existing is not None:
                previous = OutboxRecord.from_dict(existing)
                if previous.payload_digest != payload.digest:
                    raise OutboxStateError(
                        f"الأثرُ «{effect_id}» مُدرَجٌ ببصمةِ حمولةٍ مختلفة. "
                        "هويّةٌ واحدةٌ لحمولتينِ تعني خللًا في الاستدعاء."
                    )
                return previous
            moment = now or _iso()
            record = OutboxRecord(
                effect_id=effect_id,
                operation_key=operation_key,
                effect_signature=effect_signature,
                provider=provider,
                provider_supports_idempotency=provider_supports_idempotency,
                status=DeliveryStatus.PENDING,
                payload_version=payload.version,
                payload=payload.canonical_data(),
                payload_digest=payload.digest,
                permit_id=permit_id,
                authorization_anchor=authorization_anchor,
                created_at=moment,
                updated_at=moment,
                correlation_id=correlation_id,
                transitions=[
                    {
                        "from": "—",
                        "to": DeliveryStatus.PENDING.value,
                        "at": moment,
                        "note": "إدراجٌ دائمٌ قبلَ أيِّ نداء",
                    }
                ],
            )
            return self._write(record)

    def claim(
        self,
        *,
        effect_id: str,
        worker_id: str,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        now: datetime | None = None,
    ) -> OutboxRecord:
        """احجِزْ أثرًا بعقدٍ زمنيٍّ **مُثبَّتٍ على القرص**.

        العقدُ الزمنيُّ هو ما يجعلُ سقوطَ العاملِ قابلًا للاستعادة بلا مُنسِّقٍ
        مركزيّ. ولو كان الحجزُ في الذاكرةِ لضاعَ الأثرُ بلا وارث.
        """
        if lease_seconds <= 0:
            raise OutboxClaimError("عقدُ الحجزِ الزمنيُّ يجب أن يكونَ موجَبًا.")
        if not worker_id.strip():
            raise OutboxClaimError("حجزٌ بلا هويّةِ عامل. الحجزُ المجهولُ لا يُحاسَب.")
        moment = (now or _now()).replace(microsecond=0)
        with self._lock:
            record = self.require(effect_id)
            if not record.is_claimable(now=moment):
                raise OutboxClaimError(
                    f"الأثرُ «{effect_id}» غيرُ قابلٍ للحجزِ الآن "
                    f"(الحالة: {record.status.value})."
                )
            was_expired_claim = record.status is DeliveryStatus.CLAIMED
            self._transition(
                record,
                DeliveryStatus.CLAIMED,
                moment=_iso(moment),
                note=(
                    f"حجزٌ لـ{worker_id}"
                    + (" بعدَ انقضاءِ حجزٍ سابق" if was_expired_claim else "")
                ),
            )
            record.claimed_by = worker_id
            record.claimed_at = _iso(moment)
            record.lease_expires_at = _iso(moment + timedelta(seconds=lease_seconds))
            record.in_flight_attempt_id = None
            return self._write(record)

    def begin_attempt(
        self,
        *,
        effect_id: str,
        worker_id: str,
        now: datetime | None = None,
    ) -> OutboxRecord:
        """ثبِّتْ «محاولةً قيدَ الطيران» **قبلَ** نداءِ المُزوّد.

        هذه السطورُ هي ما يمنعُ الكذبَ عندَ السقوطِ داخلَ النداء: لو مات العاملُ
        بعدَ هذا التثبيتِ وقبلَ الإيصال، وجدَ المُستعيدُ محاولةً معلَّقةً فقرَّر
        `INDETERMINATE` لا `PENDING`. أمّا لو لم نُثبِّتْ شيئًا فكلُّ سقوطٍ يُقرأُ
        «لم يُرسَلْ بعدُ» — وهو تخمينٌ قد يُضاعِفُ أثرًا خارجيًّا.
        """
        moment = (now or _now()).replace(microsecond=0)
        with self._lock:
            record = self.require(effect_id)
            if record.status is not DeliveryStatus.CLAIMED:
                raise OutboxStateError(
                    f"لا محاولةَ إلّا على أثرٍ محجوز. «{effect_id}» في "
                    f"«{record.status.value}»."
                )
            if record.claimed_by != worker_id:
                raise OutboxClaimError(
                    f"الأثرُ «{effect_id}» محجوزٌ لـ«{record.claimed_by}» "
                    f"لا لـ«{worker_id}»."
                )
            if record.in_flight_attempt_id is not None:
                raise OutboxStateError(
                    f"للأثرِ «{effect_id}» محاولةٌ قيدَ الطيرانِ لم تُحسَم."
                )
            record.attempt_count += 1
            attempt_id = f"AT-{record.effect_id[3:]}-{record.attempt_count}"
            record.in_flight_attempt_id = attempt_id
            record.attempts.append(
                {
                    "attempt_id": attempt_id,
                    "attempt": record.attempt_count,
                    "worker_id": worker_id,
                    "started_at": _iso(moment),
                    "outcome": None,
                }
            )
            record.updated_at = _iso(moment)
            return self._write(record)

    def _settle_attempt(
        self,
        record: OutboxRecord,
        *,
        receipt: DeliveryReceipt,
        moment: str,
    ) -> None:
        attempt_id = record.in_flight_attempt_id
        for attempt in record.attempts:
            if attempt.get("attempt_id") == attempt_id:
                attempt["outcome"] = receipt.outcome.value
                attempt["finished_at"] = moment
                attempt["provider_reference"] = receipt.provider_reference
                attempt["detail"] = _safe_detail(receipt.detail)
        record.in_flight_attempt_id = None

    def record_result(
        self,
        *,
        effect_id: str,
        worker_id: str,
        receipt: DeliveryReceipt,
        max_attempts: int = DEFAULT_MAX_DELIVERY_ATTEMPTS,
        now: datetime | None = None,
    ) -> OutboxRecord:
        """ثبِّتْ نتيجةَ نداءٍ — التسليمُ لا يُزعَمُ إلّا بإيصالٍ من المُزوّد."""
        moment = _iso((now or _now()).replace(microsecond=0))
        with self._lock:
            record = self.require(effect_id)
            if record.in_flight_attempt_id is None:
                raise OutboxStateError(
                    f"لا محاولةَ قيدَ الطيرانِ للأثرِ «{effect_id}» — "
                    "لا نتيجةَ بلا نداءٍ مُثبَّت."
                )
            if record.claimed_by != worker_id:
                raise OutboxClaimError(
                    f"نتيجةٌ من «{worker_id}» لأثرٍ محجوزٍ لـ«{record.claimed_by}»."
                )
            self._settle_attempt(record, receipt=receipt, moment=moment)

            if receipt.outcome in (
                DeliveryOutcome.SUCCESS,
                DeliveryOutcome.DUPLICATE,
            ):
                self._transition(
                    record,
                    DeliveryStatus.DELIVERED,
                    moment=moment,
                    note=(
                        "تأكيدُ المُزوّد"
                        if receipt.outcome is DeliveryOutcome.SUCCESS
                        else "المُزوّدُ أقرَّ بتكرارٍ — الأثرُ واقعٌ مرّةً واحدة"
                    ),
                )
                record.delivered_at = moment
                record.provider_reference = receipt.provider_reference or None
                record.failure_reason = None
                record.claimed_by = None
                record.lease_expires_at = None
            elif receipt.outcome is DeliveryOutcome.INDETERMINATE:
                self._transition(
                    record,
                    DeliveryStatus.INDETERMINATE,
                    moment=moment,
                    note="نتيجةٌ مجهولةٌ من المُزوّد — لا تُصنَّفُ نجاحًا ولا فشلًا",
                )
                record.failure_reason = _safe_detail(receipt.detail)
                record.claimed_by = None
                record.lease_expires_at = None
            elif receipt.outcome is DeliveryOutcome.PERMANENT_FAILURE:
                self._transition(
                    record,
                    DeliveryStatus.DEAD,
                    moment=moment,
                    note="فشلٌ نهائيٌّ مُقَرٌّ من المُزوّد",
                )
                record.failure_reason = _safe_detail(receipt.detail)
                record.terminal_reason = "PERMANENT_FAILURE"
                record.claimed_by = None
                record.lease_expires_at = None
            else:  # RETRYABLE_FAILURE
                exhausted = record.attempt_count >= max_attempts
                self._transition(
                    record,
                    DeliveryStatus.DEAD if exhausted else DeliveryStatus.FAILED_RETRYABLE,
                    moment=moment,
                    note=(
                        f"استُنفِدَت المحاولاتُ ({record.attempt_count}/{max_attempts})"
                        if exhausted
                        else "فشلٌ يقبلُ الإعادة"
                    ),
                )
                record.failure_reason = _safe_detail(receipt.detail)
                if exhausted:
                    record.terminal_reason = "MAX_ATTEMPTS_EXHAUSTED"
                record.claimed_by = None
                record.lease_expires_at = None
            return self._write(record)

    def reclaim_expired(self, *, now: datetime | None = None) -> list[OutboxRecord]:
        """استعِدِ الحجوزَ المهجورة — وميّزْ بينَ نوعينِ من الهجر.

        - حجزٌ انقضى **بلا** محاولةٍ قيدَ الطيران: لم يُنادَ أحدٌ بعدُ ⇒ `PENDING`.
        - حجزٌ انقضى **ومعه** محاولةٌ قيدَ الطيران: العاملُ سقطَ داخلَ النداء ⇒
          `INDETERMINATE`. لأنّ الأثرَ قد يكونُ وقع.

        وهذا التمييزُ هو الفرقُ بينَ استعادةٍ صادقةٍ وطابورٍ يُعيدُ إرسالَ ما
        أُرسِلَ فعلًا.
        """
        moment = (now or _now()).replace(microsecond=0)
        recovered: list[OutboxRecord] = []
        with self._lock:
            for record in self.all_records():
                if record.status is not DeliveryStatus.CLAIMED:
                    continue
                if record.lease_expires_at is None:
                    continue
                if moment <= _parse_iso(record.lease_expires_at):
                    continue
                abandoned_worker = record.claimed_by
                if record.in_flight_attempt_id is not None:
                    for attempt in record.attempts:
                        if attempt.get("attempt_id") == record.in_flight_attempt_id:
                            attempt["outcome"] = DeliveryOutcome.INDETERMINATE.value
                            attempt["finished_at"] = _iso(moment)
                            attempt["detail"] = (
                                "سقطَ العاملُ داخلَ النداء — النتيجةُ مجهولة"
                            )
                    record.in_flight_attempt_id = None
                    self._transition(
                        record,
                        DeliveryStatus.INDETERMINATE,
                        moment=_iso(moment),
                        note=(
                            f"انقضى حجزُ «{abandoned_worker}» ومحاولتُه قيدَ الطيران"
                        ),
                    )
                    record.failure_reason = (
                        "عاملٌ مهجورٌ داخلَ النداء: لا يُعرَفُ هل وقعَ الأثر."
                    )
                else:
                    self._transition(
                        record,
                        DeliveryStatus.PENDING,
                        moment=_iso(moment),
                        note=f"انقضى حجزُ «{abandoned_worker}» قبلَ أيِّ نداء",
                    )
                record.claimed_by = None
                record.lease_expires_at = None
                recovered.append(self._write(record))
        return recovered

    def next_claimable(self, *, now: datetime | None = None) -> OutboxRecord | None:
        """الأثرُ التاليُ المستحقُّ — بترتيبِ الإدراجِ لا بالعشوائيّة."""
        moment = (now or _now()).replace(microsecond=0)
        pool = [r for r in self.all_records() if r.is_claimable(now=moment)]
        if not pool:
            return None
        return min(pool, key=lambda r: (r.created_at, r.effect_id))


# ── الإدراجُ تحتَ إذنٍ سابق ────────────────────────────────────────────────
def _verify_authorization(
    *,
    permit: EnforcementPermit,
    verifying_key: ed25519.Ed25519PublicKey,
    effect: SovereignEffect,
    now: datetime | None = None,
) -> None:
    """تحقّقْ من إذنٍ **صادرٍ سابقًا** — ولا تُصدِرْ إذنًا.

    الصندوقُ لا يملكُ مفتاحًا خاصًّا، فلا يستطيعُ بنيويًّا أن يخلقَ سلطة. وكلُّ
    ما يفعلُه هنا هو رفضُ ما لم يُؤذَنْ به: توقيعٌ فاسد، إذنٌ منقضٍ، حكمٌ ليس
    `ALLOW`، أو أثرٌ خارجَ نطاقِ الإذن.

    ولا يستهلكُ الإذن: الاستهلاكُ عملُ `PolicyEnforcementPoint` لحظةَ التنفيذ،
    وقد وقعَ قبلَ الوصولِ إلى هنا.
    """
    if effect.kind is not EffectKind.EXTERNAL:
        raise OutboxError(
            f"الأثرُ «{effect.signature}» ليس خارجيًّا. صندوقُ الصادرِ للأثرِ "
            "الخارجيِّ وحدَه، ولا يُستعمَلُ مسارًا موازيًا للأثرِ المحلّيّ."
        )
    if not permit.signature_hex:
        raise OutboxAuthorityError("إذنٌ بلا توقيع. غيرُ الموقَّعِ ليس إذنًا.")
    try:
        verifying_key.verify(
            bytes.fromhex(permit.signature_hex), permit.signing_payload()
        )
    except (InvalidSignature, ValueError) as exc:
        raise OutboxAuthorityError(
            f"توقيعُ الإذنِ «{permit.permit_id}» لا يطابقُ مضمونَه — "
            "تزويرٌ أو تحريفٌ بعدَ الإصدار."
        ) from exc
    if permit.decision != "ALLOW":
        raise OutboxAuthorityError(
            f"حكمُ الإذنِ «{permit.permit_id}» هو «{permit.decision}». "
            "الصندوقُ لا يُحوِّلُ المنعَ إلى إذن."
        )
    if permit.is_expired(now):
        raise OutboxAuthorityError(
            f"انقضى الإذنُ «{permit.permit_id}» في {permit.expires_at}."
        )
    if not permit.covers(effect):
        raise OutboxAuthorityError(
            f"الإذنُ «{permit.permit_id}» لا يشملُ «{effect.signature}». "
            "لا توسيعَ لنطاقٍ مُعلَن."
        )


@dataclass(slots=True)
class SovereignOutbox:
    """واجهةُ الإدراج: أثرٌ خارجيٌّ لا يدخلُ السجلَّ إلّا بإذنٍ موقَّعٍ سابق.

    `verifying_key` مفتاحُ تحقّقٍ عامٌّ لا مفتاحُ توقيع. وهذا الفرقُ هو الحدُّ
    بينَ التنفيذِ والسلطة.
    """

    ledger: OutboxLedger
    verifying_key: ed25519.Ed25519PublicKey

    def enqueue(
        self,
        *,
        permit: EnforcementPermit,
        effect: SovereignEffect,
        operation_key: str,
        provider: ProviderAdapter,
        payload: EffectPayload,
        correlation_id: str = "",
        now: datetime | None = None,
    ) -> OutboxRecord:
        """أدرِجْ أثرًا خارجيًّا تحتَ إذنٍ متحقَّقٍ منه."""
        _verify_authorization(
            permit=permit, verifying_key=self.verifying_key, effect=effect, now=now
        )
        if not operation_key.strip():
            raise OutboxError(
                "أثرٌ بلا مفتاحِ عمليّة. الأثرُ الذي لا يُنسَبُ لعمليّةٍ لا يُدقَّق."
            )
        effect_id = compute_effect_id(
            operation_key=operation_key,
            effect_signature=effect.signature,
            provider=provider.name,
            payload_digest=payload.digest,
        )
        return self.ledger.enqueue(
            effect_id=effect_id,
            operation_key=operation_key,
            effect_signature=effect.signature,
            provider=provider.name,
            provider_supports_idempotency=bool(provider.supports_idempotency),
            payload=payload,
            permit_id=permit.permit_id,
            authorization_anchor=permit.ledger_entry_hash or "",
            correlation_id=correlation_id,
            now=_iso((now or _now()).replace(microsecond=0)),
        )


def enqueue_write_ahead(
    *,
    outbox: SovereignOutbox,
    idempotency_ledger: IdempotencyLedger,
    key: IdempotencyKey,
    permit: EnforcementPermit,
    effect: SovereignEffect,
    provider: ProviderAdapter,
    payload: EffectPayload,
    correlation_id: str = "",
    now: datetime | None = None,
) -> OutboxRecord:
    """أدرِجْ الأثرَ الخارجيَّ **قبلَ** تثبيتِ نجاحِ العمليّة.

    لا ذرّيّةَ حقيقيّةً بينَ ملفَّينِ على القرص، ولن نتصنّعَها. والذي يُفرَضُ هنا
    هو الترتيب: إن كانت العمليّةُ قد ثُبِّتَت `SUCCEEDED` فالإدراجُ مرفوض
    (`OutboxOrderingError`). فالنافذةُ الوحيدةُ الباقيةُ هي «سجلُّ صادرٍ بلا
    عمليّةٍ مكتملة» — وهي تُكتشَفُ بـ`orphaned_effects` ولا تُقرأُ تسليمًا.
    """
    record = idempotency_ledger.get(key)
    if record is None:
        raise OutboxOrderingError(
            f"العمليّةُ «{key.composite}» غيرُ محجوزةٍ في سجلِّ التفرُّد. "
            "لا أثرَ خارجيًّا قبلَ وجودِ عمليّةٍ تحملُه."
        )
    if record.status is OperationStatus.SUCCEEDED:
        raise OutboxOrderingError(
            f"العمليّةُ «{key.composite}» ثُبِّتَت ناجحةً قبلَ إدراجِ أثرِها "
            "الخارجيّ. هذا يخرقُ ترتيبَ الديمومةِ: السجلُّ يُكتَبُ أوّلًا."
        )
    if record.status is OperationStatus.FAILED_FINAL:
        raise OutboxOrderingError(
            f"العمليّةُ «{key.composite}» فاشلةٌ نهائيًّا. لا أثرَ خارجيًّا لها."
        )
    return outbox.enqueue(
        permit=permit,
        effect=effect,
        operation_key=key.composite,
        provider=provider,
        payload=payload,
        correlation_id=correlation_id,
        now=now,
    )


def orphaned_effects(
    *,
    ledger: OutboxLedger,
    idempotency_ledger: IdempotencyLedger,
) -> list[OutboxRecord]:
    """آثارٌ خارجيّةٌ مُثبَّتةٌ لعمليّاتٍ لم تكتمل — الحدُّ المُعلَنُ لا المُخفى."""
    statuses = {
        record.key.composite: record.status
        for record in idempotency_ledger.all_records()
    }
    return [
        effect
        for effect in ledger.all_records()
        if statuses.get(effect.operation_key) is not OperationStatus.SUCCEEDED
    ]


# ── التسويةُ المشتركة ──────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class ExternalSettlement:
    """قراءةٌ مشتركةٌ بينَ حالةِ العمليّةِ وحالةِ آثارِها الخارجيّة.

    وجودُها هو الجوابُ على الكذبةِ الأصليّة: «نجحَ محلّيًّا» لا يُساوي «وقعَ
    خارجيًّا». وهنا يُقرآنِ معًا ولا يُدمَجانِ في منطقيٍّ واحد.
    """

    operation_key: str
    operation_status: OperationStatus
    effects: tuple[OutboxRecord, ...]

    @property
    def delivered(self) -> tuple[OutboxRecord, ...]:
        return tuple(e for e in self.effects if e.status.certifies_delivery)

    @property
    def outstanding(self) -> tuple[OutboxRecord, ...]:
        return tuple(e for e in self.effects if not e.status.is_terminal)

    @property
    def ambiguous(self) -> tuple[OutboxRecord, ...]:
        return tuple(e for e in self.effects if e.status.is_ambiguous)

    @property
    def dead(self) -> tuple[OutboxRecord, ...]:
        return tuple(e for e in self.effects if e.status is DeliveryStatus.DEAD)

    @property
    def externally_settled(self) -> bool:
        """كلُّ أثرٍ خارجيٍّ سُلِّمَ بتأكيد — لا استنتاجَ ولا تسامح."""
        return bool(self.effects) and all(
            e.status.certifies_delivery for e in self.effects
        )

    @property
    def claims_completion(self) -> bool:
        """هل يجوزُ للدولةِ أن تقولَ «تمَّ» بلا كذب؟"""
        return (
            self.operation_status is OperationStatus.SUCCEEDED
            and self.externally_settled
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "operation_key": self.operation_key,
            "operation_status": self.operation_status.value,
            "operation_status_arabic": self.operation_status.arabic,
            "effects": [
                {
                    "effect_id": e.effect_id,
                    "status": e.status.value,
                    "status_arabic": e.status.arabic,
                    "attempt_count": e.attempt_count,
                    "requires_human_resolution": e.requires_human_resolution,
                }
                for e in self.effects
            ],
            "externally_settled": self.externally_settled,
            "claims_completion": self.claims_completion,
            "ambiguous_count": len(self.ambiguous),
        }


def settlement_of(
    *,
    ledger: OutboxLedger,
    idempotency_ledger: IdempotencyLedger,
    key: IdempotencyKey,
) -> ExternalSettlement:
    """اقرأْ حالةَ عمليّةٍ وآثارِها الخارجيّةِ معًا."""
    record = idempotency_ledger.get(key)
    if record is None:
        raise OutboxError(
            f"العمليّةُ «{key.composite}» غيرُ موجودةٍ في سجلِّ التفرُّد."
        )
    return ExternalSettlement(
        operation_key=key.composite,
        operation_status=record.status,
        effects=tuple(ledger.for_operation(key.composite)),
    )


# ── العامل ─────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class DeliveryReport:
    """حصيلةُ دورةٍ واحدةٍ من عملِ العامل."""

    record: OutboxRecord
    receipt: DeliveryReceipt


@dataclass(slots=True)
class OutboxWorker:
    """آلةُ التسليم: يستعيدُ المهجور، يحجزُ، يُثبِّتُ محاولةً، يُنادي، يُثبِّتُ النتيجة.

    الترتيبُ مقصودٌ حرفًا: **التثبيتُ قبلَ النداء**. ولو نادى ثمّ ثبَّتَ لكان كلُّ
    سقوطٍ داخلَ النداءِ يُقرأُ «لم يُرسَل» — وهو التزويرُ الذي تُبنى عليه
    الإرسالاتُ المكرَّرة.

    ولا يملكُ العاملُ إذنًا ولا مفتاحَ توقيع: يُسلّمُ ما أُدرِجَ بإذن، ولا يُدرِج.
    """

    ledger: OutboxLedger
    adapters: Mapping[str, ProviderAdapter]
    worker_id: str
    lease_seconds: int = DEFAULT_LEASE_SECONDS
    max_attempts: int = DEFAULT_MAX_DELIVERY_ATTEMPTS

    def __post_init__(self) -> None:
        if not self.worker_id.strip():
            raise OutboxError("عاملٌ بلا هويّة. الحجزُ المجهولُ لا يُحاسَب.")
        if self.lease_seconds <= 0:
            raise OutboxError("عقدُ الحجزِ الزمنيُّ يجب أن يكونَ موجَبًا.")
        if self.max_attempts < 1:
            raise OutboxError("حدُّ المحاولاتِ يجب أن يكونَ واحدًا على الأقلّ.")

    def _adapter_for(self, record: OutboxRecord) -> ProviderAdapter:
        adapter = self.adapters.get(record.provider)
        if adapter is None:
            raise OutboxError(
                f"لا مُحوّلَ للمُزوّدِ «{record.provider}». لا نُصنِّفُ الأثرَ "
                "فاشلًا لغيابِ مُحوّلٍ عندنا: العجزُ عجزُنا لا فشلُ المُزوّد."
            )
        return adapter

    def _call_provider(
        self, adapter: ProviderAdapter, envelope: EffectEnvelope
    ) -> DeliveryReceipt:
        """نادِ المُزوّدَ وحوِّلْ كلَّ نتيجةٍ إلى إيصالٍ صريح.

        القاعدةُ في الاستثناءات: ما أقرَّ المُزوّدُ بأنّه فشلَ قبلَ الأثرِ يُعادُ
        (`ProviderDeliveryError`)، وكلُّ استثناءٍ آخرَ **مجهولُ النتيجة** — لأنّ
        الطلبَ قد يكونُ وصلَ ووقعَ أثرُه. الافتراضُ الآمنُ هو الغموضُ لا الفشل.
        """
        try:
            receipt = adapter.deliver(envelope)
        except ProviderDeliveryError as exc:
            return DeliveryReceipt(
                outcome=DeliveryOutcome.RETRYABLE_FAILURE, detail=str(exc)
            )
        except ProviderIndeterminateError as exc:
            return DeliveryReceipt(
                outcome=DeliveryOutcome.INDETERMINATE, detail=str(exc)
            )
        except Exception as exc:  # noqa: BLE001 — يُصنَّفُ غموضًا لا يُبتلَع
            return DeliveryReceipt(
                outcome=DeliveryOutcome.INDETERMINATE,
                detail=f"استثناءٌ غيرُ مُصنَّفٍ من المُحوّل: {exc}",
            )
        if not isinstance(receipt, DeliveryReceipt):
            raise OutboxError(
                f"المُحوّلُ «{adapter.name}» أعادَ ما ليس إيصالًا. "
                "لا نستنتجُ نجاحًا من قيمةٍ مجهولةِ الشكل."
            )
        return receipt

    def run_once(self, *, now: datetime | None = None) -> DeliveryReport | None:
        """دورةٌ واحدة: استعادةٌ ثمّ حجزٌ ثمّ تثبيتٌ ثمّ نداءٌ ثمّ تثبيتُ النتيجة."""
        moment = (now or _now()).replace(microsecond=0)
        self.ledger.reclaim_expired(now=moment)
        candidate = self.ledger.next_claimable(now=moment)
        if candidate is None:
            return None
        adapter = self._adapter_for(candidate)
        claimed = self.ledger.claim(
            effect_id=candidate.effect_id,
            worker_id=self.worker_id,
            lease_seconds=self.lease_seconds,
            now=moment,
        )
        in_flight = self.ledger.begin_attempt(
            effect_id=claimed.effect_id, worker_id=self.worker_id, now=moment
        )
        envelope = EffectEnvelope(
            effect_id=in_flight.effect_id,
            idempotency_token=in_flight.idempotency_token,
            operation_key=in_flight.operation_key,
            effect_signature=in_flight.effect_signature,
            provider=in_flight.provider,
            payload_version=in_flight.payload_version,
            payload=dict(in_flight.payload),
            attempt=in_flight.attempt_count,
            attempt_id=in_flight.in_flight_attempt_id or "",
            authorization_anchor=in_flight.authorization_anchor,
            correlation_id=in_flight.correlation_id,
        )
        receipt = self._call_provider(adapter, envelope)
        settled = self.ledger.record_result(
            effect_id=in_flight.effect_id,
            worker_id=self.worker_id,
            receipt=receipt,
            max_attempts=self.max_attempts,
            now=moment,
        )
        return DeliveryReport(record=settled, receipt=receipt)

    def drain(
        self, *, limit: int = 50, now: datetime | None = None
    ) -> tuple[DeliveryReport, ...]:
        """أفرِغْ ما يُستحَقُّ الآن — بحدٍّ أعلى صريحٍ لا بحلقةٍ مفتوحة."""
        if limit < 1:
            raise OutboxError("حدُّ التفريغِ يجب أن يكونَ واحدًا على الأقلّ.")
        reports: list[DeliveryReport] = []
        for _ in range(limit):
            report = self.run_once(now=now)
            if report is None:
                break
            reports.append(report)
        return tuple(reports)

    def self_check(self) -> dict[str, Any]:
        """ما تعرفُه آلةُ التسليمِ عن نفسِها — بلا تجميلٍ ولا استنتاج."""
        records = self.ledger.all_records()
        return {
            "worker_id": self.worker_id,
            "total": len(records),
            "pending": sum(1 for r in records if r.status is DeliveryStatus.PENDING),
            "claimed": sum(1 for r in records if r.status is DeliveryStatus.CLAIMED),
            "delivered": sum(
                1 for r in records if r.status is DeliveryStatus.DELIVERED
            ),
            "retryable": sum(
                1 for r in records if r.status is DeliveryStatus.FAILED_RETRYABLE
            ),
            "dead": sum(1 for r in records if r.status is DeliveryStatus.DEAD),
            "indeterminate": sum(
                1 for r in records if r.status is DeliveryStatus.INDETERMINATE
            ),
            "requires_human_resolution": sum(
                1 for r in records if r.requires_human_resolution
            ),
            "claims_exactly_once": False,
            "guarantee": "AT_LEAST_ONCE_WITH_STABLE_IDEMPOTENCY_IDENTITY",
        }


def external_effect_of(
    *, resource: str, detail: str = "", payload: EffectPayload | None = None
) -> SovereignEffect:
    """أثرٌ خارجيٌّ مبنيٌّ على عقدِ 1E نفسِه — لا نموذجَ أثرٍ موازيًا."""
    return SovereignEffect(
        kind=EffectKind.EXTERNAL,
        resource=resource,
        detail=detail,
        payload_digest=payload.digest if payload is not None else None,
    )


__all__ = [
    "DEFAULT_LEASE_SECONDS",
    "DEFAULT_MAX_DELIVERY_ATTEMPTS",
    "FORBIDDEN_PAYLOAD_KEY_TOKENS",
    "MAX_PAYLOAD_BYTES",
    "OUTBOX_DOMAIN",
    "PAYLOAD_SCHEMA_VERSION",
    "DeliveryOutcome",
    "DeliveryReceipt",
    "DeliveryReport",
    "DeliveryStatus",
    "EffectEnvelope",
    "EffectPayload",
    "ExternalSettlement",
    "OutboxAuthorityError",
    "OutboxClaimError",
    "OutboxError",
    "OutboxLedger",
    "OutboxOrderingError",
    "OutboxPayloadError",
    "OutboxRecord",
    "OutboxSecretMaterialError",
    "OutboxStateError",
    "OutboxWorker",
    "ProviderAdapter",
    "ProviderDeliveryError",
    "ProviderIndeterminateError",
    "SovereignOutbox",
    "compute_effect_id",
    "enqueue_write_ahead",
    "external_effect_of",
    "orphaned_effects",
    "settlement_of",
]
