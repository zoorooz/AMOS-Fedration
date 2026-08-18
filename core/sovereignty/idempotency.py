"""الهدف: الذرّيّةُ ومنعُ تكرارِ الأثر — عمليّةٌ واحدةٌ تُنتِجُ أثرًا واحدًا.

النطاق: `core/sovereignty/` — حارسُ الذرّيّةِ فوقَ المسارِ السياديّ القائم.
المالك: core/sovereignty/ — التاج
تاريخ الإنشاء: 2026-08-18
تاريخ آخر تعديل: 2026-08-18
tags: idempotency, atomicity, retry, recovery, sovereignty

## الفجوةُ التي تسدُّها هذه الوحدة

بعد 1E (العقد) و1F (الإذن) و1G (الاختصاص)، لا يزال المسارُ السياديّ عاريًا من
حمايةٍ ضدّ التكرار: لو أُعيدَ الطلبُ نفسُه مرّتين — تسلسليًّا أو متزامنًا —
لطُبِّقَ الأثرُ مرّتين. ولو فشلتِ العمليّةُ في منتصفِها لبقيتِ الدولةُ في حالةٍ
غيرِ معرّفة. ولا علاقةَ بين الإذنِ المُستهلَك (1F) والعمليّةِ ككلّ: الإذنُ يمنع
إعادةَ استعمالِ الإذن، لا إعادةَ استعمالِ النتيجة.

## القرار: حارسٌ يلفُّ المسارَ القائم — لا محرّكٌ موازٍ

لا يُبنى هنا محرّكُ قرارٍ ثانٍ ولا مسارُ تنفيذٍ بديل. الحارسُ `IdempotencyGuard`
يأخذُ العمليّةَ السياديّةَ القائمةَ (قرار → إذن → تنفيذ) ويحميها من التكرارِ
بثلاثِ طبقات:

1. **الحجزُ قبلَ التنفيذ:** مفتاحُ الذرّيّةِ يُحجَز على القرص قبلَ أن يبدأَ التنفيذ.
   فلو وصلَ الطلبُ نفسُه مرّتين، رُفض الثاني بالحجزِ لا بالنتيجة.
2. **تثبيتُ النتيجة:** بعدَ نجاحِ التنفيذ، تُكتَبُ النتيجةُ وبصمتُها على القرص.
   فإعادةُ الطلبِ تجدُ النتيجةَ وتُعيدُها دون تنفيذ.
3. **استعادةُ الانقطاع:** لو انقطعتِ العمليّةُ بين الحجزِ والتثبيت، يُمكنُ
   استعادةُ حالتِها: `INTERRUPTED` لا `UNKNOWN`.

## ما ليس مُثبَتًا — بصراحة

- **الحارسُ متاحٌ لا مفروض.** كما في 1F و1G، لا شيءَ يُلزِمُ المسارَ بالمرورِ
  عبره. الفرضُ يلزمه حرسٌ ساكنٌ (1M).
- **الأثرُ الخارجيُّ لا يُلغى.** `EffectKind.EXTERNAL` لا يمكنُ التراجعُ عنه
  ذرّيًّا. الحارسُ يسجّلُه ويمنعُ تكرارَه، لكنّه لا يزعمُ rollback له.
- **لا توزيعٍ بين العمليّات.** السجلُّ ملفٌّ محليّ. التوزيعُ بين العُقَد عملٌ تالٍ.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from threading import RLock
from typing import Any, Final, Generic, TypeVar

T = TypeVar("T")

#: مجالُ بصمةِ العمليّة — يمنعُ خلطَ بصمةِ ذرّيّةٍ ببصمةِ إذنٍ أو عقد.
IDEMPOTENCY_DOMAIN: Final[bytes] = b"AMOS-FEDERATION/IDEMPOTENCY/v1"

#: أقصى عددِ محاولاتٍ لإعادةِ العمليّةِ قبل الإعلانِ بالفشلِ النهائيّ.
DEFAULT_MAX_ATTEMPTS: Final[int] = 3


class OperationStatus(str, Enum):
    """حالاتُ العمليّةِ الذرّيّة — لا `UNKNOWN`.

    كلُّ حالةٍ معرّفةٌ صراحةً: لا يوجدُ مسارٌ ينتهي بالعمليّةِ في حالةٍ غامضة.
    الانتقالُ بين الحالاتِ أحاديّ الاتّجاه: لا رجوعَ من `SUCCEEDED` إلى `RUNNING`.
    """

    RESERVED = "RESERVED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_FINAL = "FAILED_FINAL"
    INTERRUPTED = "INTERRUPTED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    EXTERNAL_PENDING = "EXTERNAL_PENDING"

    @property
    def is_terminal(self) -> bool:
        """هل انتهتِ العمليّة؟ الحالاتُ النهائيّةُ لا تقبلُ إعادةَ محاولة."""
        return self in (
            OperationStatus.SUCCEEDED,
            OperationStatus.FAILED_FINAL,
        )

    @property
    def is_recoverable(self) -> bool:
        """هل يمكنُ استعادةُ العمليّةِ من هذه الحالة؟"""
        return self in (
            OperationStatus.INTERRUPTED,
            OperationStatus.RECOVERY_REQUIRED,
            OperationStatus.FAILED_RETRYABLE,
        )

    @property
    def arabic(self) -> str:
        return _STATUS_ARABIC[self]


_STATUS_ARABIC: Final[dict[OperationStatus, str]] = {
    OperationStatus.RESERVED: "محجوزة",
    OperationStatus.RUNNING: "جارية",
    OperationStatus.SUCCEEDED: "ناجحة",
    OperationStatus.FAILED_RETRYABLE: "فاشلةٌ قابلةٌ للإعادة",
    OperationStatus.FAILED_FINAL: "فاشلةٌ نهائيًّا",
    OperationStatus.INTERRUPTED: "منقطعة",
    OperationStatus.RECOVERY_REQUIRED: "تتطلّبُ استعادة",
    OperationStatus.EXTERNAL_PENDING: "أثرٌ خارجيٌّ معلّق",
}


class IdempotencyError(Exception):
    """خللٌ في حمايةِ الذرّيّة — يُرفَع ولا يُبتلَع."""


class IdempotencyKeyReuseError(IdempotencyError):
    """مفتاحُ ذرّيّةٍ أُعيدَ استعمالُه ببصمةٍ مختلفة.

    المفتاحُ الواحدُ يربطُ بعمليّةٍ واحدة. استعمالُه لعمليّةٍ مختلفةٍ تزويرٌ
    للهويّة.
    """


class IdempotencyConflictError(IdempotencyError):
    """تعارضُ تزامنٍ: عمليّتانِ تحاولانِ الحجزَ على المفتاحِ نفسه في آنٍ واحد."""


class OperationNotRecoverableError(IdempotencyError):
    """محاولةُ استعادةِ عمليّةٍ في حالةٍ لا تقبلُ الاستعادة."""


def _canonical(payload: dict[str, Any]) -> bytes:
    """تمثيلٌ واحدٌ لا لبسَ فيه — وإلّا صار ترتيبُ المفاتيحِ ثغرة."""
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    """كتابةٌ ذرّيّة: إمّا السجلُّ القديمُ كاملًا أو الجديدُ كاملًا."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(  # noqa: SIM115 — إدارةٌ يدويّةٌ للإغلاقِ الذرّيّ
        "w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp"
    )
    try:
        with handle as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(handle.name, path)
    except BaseException:
        Path(handle.name).unlink(missing_ok=True)
        raise


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def compute_fingerprint(
    *,
    scope: str,
    action: str,
    target: str,
    effect_signatures: tuple[str, ...] | frozenset[str],
    actor: str = "",
    payload_digest: str = "",
) -> str:
    """بصمةُ العمليّةِ — ما يجعلُ عمليّتين «هما العمليّةُ نفسُها».

    البصمةُ تشملُ النطاقَ والفعلَ والهدفَ والآثارَ والفاعلَ. فلو تغيّرَ أيُّها
    لكانت عمليّةً مختلفةً ولو تشابهَت الأسماء.
    """
    مادّة = "|".join([
        scope,
        action,
        target,
        actor,
        payload_digest,
        *sorted(effect_signatures),
    ])
    return "FP-" + hashlib.sha256(مادّة.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True, slots=True)
class IdempotencyKey:
    """مفتاحُ ذرّيّةٍ — ثابتٌ للعمليّة، محميٌّ من إعادةِ الاستعمال الخاطئ.

    المفتاحُ مكوّنٌ من نطاقٍ وقيمة: المفتاحُ نفسُه في نطاقينِ مختلفينِ يُشيرُ
    إلى عمليّتينِ مختلفتين. وهذا يمنعُ تصادمًا عرضيًّا بين وحداتٍ مستقلّة.
    """

    scope: str
    value: str

    def __post_init__(self) -> None:
        if not self.scope.strip():
            raise IdempotencyError(
                "مفتاحُ ذرّيّةٍ بلا نطاق. النطاقُ يمنعُ التصادمَ بين الوحدات."
            )
        if not self.value.strip():
            raise IdempotencyError(
                "مفتاحُ ذرّيّةٍ بلا قيمة. المفتاحُ الفارغُ ليس مفتاحًا."
            )

    @property
    def composite(self) -> str:
        """الشكلُ المركَّبُ للفهرسة: `scope:value`."""
        return f"{self.scope}:{self.value}"


@dataclass(slots=True)
class IdempotencyRecord:
    """سجلُّ عمليّةٍ ذرّيّة — إضافيٌّ فقط، لا حذفَ ولا تعديل.

    كلُّ محاولةٍ تُضافُ إلى `attempts`، ولا تُحذفُ المحاولاتُ السابقة. فالسجلُّ
    التاريخيُّ قابلٌ لإعادةِ البناء: لو سُئلَ «ماذا حدث؟» يُجيبُ بالتسلسلِ كاملًا.
    """

    key: IdempotencyKey
    fingerprint: str
    status: OperationStatus
    reserved_at: str
    attempts: list[dict[str, Any]] = field(default_factory=list)
    transitions: list[dict[str, Any]] = field(default_factory=list)
    result_digest: str | None = None
    applied_effect_signatures: tuple[str, ...] = ()
    failure_reason: str | None = None
    recovered_at: str | None = None
    succeeded_at: str | None = None
    has_external_effect: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key.composite,
            "scope": self.key.scope,
            "value": self.key.value,
            "fingerprint": self.fingerprint,
            "status": self.status.value,
            "reserved_at": self.reserved_at,
            "attempts": list(self.attempts),
            "transitions": list(self.transitions),
            "result_digest": self.result_digest,
            "applied_effect_signatures": list(self.applied_effect_signatures),
            "failure_reason": self.failure_reason,
            "recovered_at": self.recovered_at,
            "succeeded_at": self.succeeded_at,
            "has_external_effect": self.has_external_effect,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IdempotencyRecord:
        return cls(
            key=IdempotencyKey(scope=data["scope"], value=data["value"]),
            fingerprint=data["fingerprint"],
            status=OperationStatus(data["status"]),
            reserved_at=data["reserved_at"],
            attempts=list(data.get("attempts", [])),
            transitions=list(data.get("transitions", [])),
            result_digest=data.get("result_digest"),
            applied_effect_signatures=tuple(data.get("applied_effect_signatures", [])),
            failure_reason=data.get("failure_reason"),
            recovered_at=data.get("recovered_at"),
            succeeded_at=data.get("succeeded_at"),
            has_external_effect=data.get("has_external_effect", False),
        )


@dataclass(slots=True)
class IdempotencyLedger:
    """سجلُّ الذرّيّةِ على القرص — يبقى بعدَ سقوطِ العمليّة.

    كلُّ سجلٍّ يُكتَبُ ذرّيًّا على القرصِ قبلَ أن تُكمَلَ العمليّة. فلو انقطعت
    العمليّةُ، يبقى السجلُّ شاهدًا على ما جرى. ولو أُعيدَ تشغيلُ النظام، يقرأُ
    السجلُّ ما كانَ ويستعيدُ الحالاتِ الوسيطة.
    """

    path: Path
    _lock: RLock = field(default_factory=RLock, repr=False, compare=False)

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            return dict(json.loads(self.path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, ValueError) as exc:
            raise IdempotencyError(
                f"سجلُّ الذرّيّةِ في «{self.path}» تالفٌ ولا يُمكنُ قراءتُه."
            ) from exc

    def _save(self, records: dict[str, dict[str, Any]]) -> None:
        _atomic_write(self.path, records)

    def _record_key(self, key: IdempotencyKey) -> str:
        return key.composite

    def get(self, key: IdempotencyKey) -> IdempotencyRecord | None:
        """اقرأْ سجلًّا. لا قفلَ هنا — القراءةُ فقط."""
        records = self._load()
        data = records.get(self._record_key(key))
        return IdempotencyRecord.from_dict(data) if data else None

    def reserve(
        self,
        *,
        key: IdempotencyKey,
        fingerprint: str,
        now: str | None = None,
    ) -> IdempotencyRecord:
        """احجزْ مفتاحًا قبلَ التنفيذ.

        - لو لم يكن المفتاحُ موجودًا: أنشئه بحالة `RESERVED` وأرجِعه.
        - لو كان موجودًا بنفسِ البصمة: أرجِع السجلَّ القائم (نعيدُ النتيجةَ لاحقًا).
        - لو كان موجودًا ببصمةٍ مختلفة: ارفض — إعادةُ استعمالٍ خاطئة.
        """
        with self._lock:
            records = self._load()
            rkey = self._record_key(key)
            existing = records.get(rkey)

            if existing is not None:
                record = IdempotencyRecord.from_dict(existing)
                if record.fingerprint != fingerprint:
                    raise IdempotencyKeyReuseError(
                        f"المفتاحُ «{key.composite}» مُستعمَلٌ ببصمةٍ مختلفة. "
                        "المفتاحُ الواحدُ لعمليّةٍ واحدة."
                    )
                return record

            moment = now or _now_iso()
            record = IdempotencyRecord(
                key=key,
                fingerprint=fingerprint,
                status=OperationStatus.RESERVED,
                reserved_at=moment,
            )
            records[rkey] = record.as_dict()
            self._save(records)
            return record

    def transition(
        self,
        *,
        key: IdempotencyKey,
        new_status: OperationStatus,
        attempt: dict[str, Any] | None = None,
        result_digest: str | None = None,
        applied_effect_signatures: tuple[str, ...] | None = None,
        failure_reason: str | None = None,
        has_external_effect: bool = False,
        now: str | None = None,
    ) -> IdempotencyRecord:
        """انقلِ السجلَّ إلى حالةٍ جديدة — انتقالٌ أحاديٌّ مسجَّل.

        لا يُسمحُ بالانتقالِ من حالةٍ نهائيّةٍ إلى حالةٍ سابقة: النجاحُ لا يتراجع.
        """
        with self._lock:
            records = self._load()
            rkey = self._record_key(key)
            existing = records.get(rkey)
            if existing is None:
                raise IdempotencyError(
                    f"المفتاحُ «{key.composite}» غيرُ محجوز. لا انتقالَ بلا حجز."
                )
            record = IdempotencyRecord.from_dict(existing)

            if record.status.is_terminal and new_status != record.status:
                raise IdempotencyError(
                    f"العمليّةُ «{key.composite}» في حالةٍ نهائيّة «{record.status.value}». "
                    "لا انتقالَ من النهائي."
                )

            moment = now or _now_iso()
            old_status = record.status
            record.status = new_status
            record.transitions.append({
                "from": old_status.value,
                "to": new_status.value,
                "at": moment,
                "is_retry": len(record.attempts) > 1,
            })
            if attempt is not None:
                record.attempts.append(attempt)
            if result_digest is not None:
                record.result_digest = result_digest
            if applied_effect_signatures is not None:
                record.applied_effect_signatures = applied_effect_signatures
            if failure_reason is not None:
                record.failure_reason = failure_reason
            if has_external_effect:
                record.has_external_effect = True
            if new_status == OperationStatus.SUCCEEDED:
                record.succeeded_at = moment
            if new_status in (OperationStatus.INTERRUPTED, OperationStatus.RECOVERY_REQUIRED):
                record.recovered_at = moment

            records[rkey] = record.as_dict()
            self._save(records)
            return record

    def mark_running(
        self, *, key: IdempotencyKey, attempt: dict[str, Any] | None = None,
        now: str | None = None,
    ) -> IdempotencyRecord:
        return self.transition(
            key=key,
            new_status=OperationStatus.RUNNING,
            attempt=attempt,
            now=now,
        )

    def mark_succeeded(
        self,
        *,
        key: IdempotencyKey,
        result_digest: str,
        applied_effect_signatures: tuple[str, ...] = (),
        has_external_effect: bool = False,
        now: str | None = None,
    ) -> IdempotencyRecord:
        return self.transition(
            key=key,
            new_status=OperationStatus.SUCCEEDED,
            result_digest=result_digest,
            applied_effect_signatures=applied_effect_signatures,
            has_external_effect=has_external_effect,
            now=now,
        )

    def mark_failed(
        self,
        *,
        key: IdempotencyKey,
        reason: str,
        retryable: bool = True,
        attempt: dict[str, Any] | None = None,
        now: str | None = None,
    ) -> IdempotencyRecord:
        status = OperationStatus.FAILED_RETRYABLE if retryable else OperationStatus.FAILED_FINAL
        return self.transition(
            key=key,
            new_status=status,
            failure_reason=reason,
            attempt=attempt,
            now=now,
        )

    def mark_interrupted(
        self, *, key: IdempotencyKey, now: str | None = None,
    ) -> IdempotencyRecord:
        return self.transition(
            key=key,
            new_status=OperationStatus.INTERRUPTED,
            now=now,
        )

    def recover(
        self, *, key: IdempotencyKey, now: str | None = None,
    ) -> IdempotencyRecord:
        """استعِدْ عمليّةً منقطعة — انقلها إلى `RECOVERY_REQUIRED`."""
        with self._lock:
            records = self._load()
            rkey = self._record_key(key)
            existing = records.get(rkey)
            if existing is None:
                raise IdempotencyError(
                    f"المفتاحُ «{key.composite}» غيرُ موجود. لا استعادةَ بلا سجل."
                )
            record = IdempotencyRecord.from_dict(existing)
            if not record.status.is_recoverable:
                raise OperationNotRecoverableError(
                    f"العمليّةُ «{key.composite}» في حالة «{record.status.value}» "
                    "لا تقبلُ الاستعادة."
                )
            moment = now or _now_iso()
            record.status = OperationStatus.RECOVERY_REQUIRED
            record.recovered_at = moment
            records[rkey] = record.as_dict()
            self._save(records)
            return record

    def count(self) -> int:
        return len(self._load())

    def all_records(self) -> list[IdempotencyRecord]:
        records = self._load()
        return [IdempotencyRecord.from_dict(v) for v in records.values()]


@dataclass(slots=True)
class OperationResult(Generic[T]):
    """نتيجةُ عمليّةٍ تحتَ الحارس: القيمةُ أو السبب، وهل هي تنفيذٌ أم إعادة.

    `is_replay` يميّزُ بين «نفّذتُ الآن» و«وجدتُ نتيجةً سابقة»: التدقيقُ يفرّق.
    """

    value: T | None
    status: OperationStatus
    is_replay: bool
    record: IdempotencyRecord
    failure_reason: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.status is OperationStatus.SUCCEEDED


def _digest_result(value: Any) -> str:
    """بصمةُ نتيجةٍ — لتثبيتِها ومقارنتها لاحقًا."""
    if value is None:
        raw = b"null"
    elif isinstance(value, bytes):
        raw = value
    elif isinstance(value, str):
        raw = value.encode("utf-8")
    else:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return "RD-" + hashlib.sha256(raw).hexdigest()[:24]


@dataclass(slots=True)
class IdempotencyGuard:
    """حارسُ الذرّيّة — يلفُّ المسارَ السياديّ ويحميه من التكرار.

    لا يقررُ، ولا يأذن، ولا يُنفّذ. يأخذُ العمليّةَ القائمةَ ويحميها:
    - `reserve`: يحجزُ المفتاحَ على القرص.
    - `run_once`: ينفّذُ العمليّةَ مرّةً واحدة، أو يُعيدُ النتيجةَ إن وُجدت.
    - `recover`: يستعيدُ عمليّةً منقطعة.

    لا يملكُ `force` ولا `bypass` ولا `override`: الحمايةُ بنيويّةٌ لا اختياريّة.
    """

    ledger: IdempotencyLedger
    _key_locks: dict[str, RLock] = field(default_factory=dict, repr=False, compare=False)
    _key_locks_guard: RLock = field(default_factory=RLock, repr=False, compare=False)

    def _get_key_lock(self, composite: str) -> RLock:
        """قفلٌ لكلِّ مفتاح — يمنعُ سباقاتِ التزامنِ على المفتاحِ نفسِه."""
        with self._key_locks_guard:
            if composite not in self._key_locks:
                self._key_locks[composite] = RLock()
            return self._key_locks[composite]

    def _reserve_or_replay(
        self,
        *,
        key: IdempotencyKey,
        fingerprint: str,
    ) -> tuple[IdempotencyRecord, bool]:
        """حجزٌ أو إعادةُ نتيجة. تُرجِعُ (السجلّ، هل هي إعادةٌ)."""
        existing = self.ledger.get(key)
        if existing is not None:
            if existing.fingerprint != fingerprint:
                raise IdempotencyKeyReuseError(
                    f"المفتاحُ «{key.composite}» مُستعمَلٌ ببصمةٍ مختلفة."
                )
            if existing.status is OperationStatus.SUCCEEDED:
                return existing, True
            if existing.status.is_recoverable:
                # استعادةٌ ثمّ إعادةُ محاولة
                self.ledger.recover(key=key)
                return self.ledger.get(key) or existing, False
            if existing.status is OperationStatus.RUNNING:
                raise IdempotencyConflictError(
                    f"العمليّةُ «{key.composite}» جاريةٌ في مكانٍ آخر."
                )
            # RESERVED أو RECOVERY_REQUIRED: تابع
            return existing, False

        # حجزٌ جديد
        record = self.ledger.reserve(key=key, fingerprint=fingerprint)
        return record, False

    def run_once(
        self,
        *,
        key: IdempotencyKey,
        fingerprint: str,
        execute: Callable[[], T],
        extract_effect_signatures: Callable[[T], tuple[str, ...]] | None = None,
        detect_external: Callable[[T], bool] | None = None,
    ) -> OperationResult[T]:
        """نفِّذْ عمليّةً مرّةً واحدة — أو أعدِ النتيجةَ السابقة.

        `execute` هي الدالّةُ السياديّةُ القائمة: قرارٌ → إذنٌ → تنفيذ.
        الحارسُ لا يُعدّلُها ولا يُغلِّفُها في مسارٍ بديل. يحميها فقط.

        `extract_effect_signatures`: تستخرجُ بصماتِ الآثارِ المُطبَّقة من النتيجة
        لتُسجَّلَ في السجلّ. `detect_external`: تكتشفُ الأثرَ الخارجيَّ فلا يُزعمُ
        rollback له.
        """
        key_lock = self._get_key_lock(key.composite)
        with key_lock:
            return self._run_once_inner(
                key=key,
                fingerprint=fingerprint,
                execute=execute,
                extract_effect_signatures=extract_effect_signatures,
                detect_external=detect_external,
            )

    def _run_once_inner(
        self,
        *,
        key: IdempotencyKey,
        fingerprint: str,
        execute: Callable[[], T],
        extract_effect_signatures: Callable[[T], tuple[str, ...]] | None = None,
        detect_external: Callable[[T], bool] | None = None,
    ) -> OperationResult[T]:
        """المنطقُ الداخليّ تحت قفل المفتاح."""
        record, is_replay = self._reserve_or_replay(
            key=key, fingerprint=fingerprint,
        )

        if is_replay:
            return OperationResult(
                value=None,  # لا قيمةَ مُخزَّنة — اقرأْ result_digest من السجلّ
                status=OperationStatus.SUCCEEDED,
                is_replay=True,
                record=record,
            )

        # انتقالٌ إلى RUNNING
        self.ledger.mark_running(
            key=key,
            attempt={"started_at": _now_iso()},
        )

        try:
            value = execute()
        except Exception as exc:
            self.ledger.mark_failed(
                key=key,
                reason=str(exc),
                retryable=True,
                attempt={"failed_at": _now_iso(), "error": str(exc)},
            )
            raise IdempotencyError(
                f"العمليّةُ «{key.composite}» فشلت: {exc}"
            ) from exc

        # نجاح: ثبّتِ النتيجة
        result_digest = _digest_result(value)
        effect_sigs: tuple[str, ...] = ()
        if extract_effect_signatures is not None:
            effect_sigs = extract_effect_signatures(value)
        has_external = False
        if detect_external is not None:
            has_external = detect_external(value)

        updated = self.ledger.mark_succeeded(
            key=key,
            result_digest=result_digest,
            applied_effect_signatures=effect_sigs,
            has_external_effect=has_external,
        )

        return OperationResult(
            value=value,
            status=OperationStatus.SUCCEEDED,
            is_replay=False,
            record=updated,
        )

    def recover(self, *, key: IdempotencyKey) -> IdempotencyRecord:
        """استعِدْ عمليّةً منقطعة — للفحصِ اليدويّ أو إعادةِ المحاولة."""
        return self.ledger.recover(key=key)

    def run_effects_once(
        self,
        *,
        key: IdempotencyKey,
        fingerprint: str,
        declared_effects: tuple[str, ...],
        apply_effect: Callable[[str], None],
    ) -> OperationResult[None]:
        """نفِّذْ آثارًا مُعلَنةً مع تتبّعِ كلِّ أثرٍ — لا إعادةَ لأثرٍ طُبِّق.

        هذه الطريقةُ تتعاملُ مع الفشلِ الجزئيّ: لو طُبِّقَ أثرٌ A ثمّ فشلَ الأثرُ B،
        يُسجَّلُ A في `applied_effect_signatures`، وتنتقلُ العمليّةُ إلى
        `RECOVERY_REQUIRED` لا `FAILED_RETRYABLE`. وعندَ إعادةِ المحاولة، تُتخطّى
        الآثارُ التي طُبِّقَت.

        لا تقبلُ آثارًا خارجيّة (`EXTERNAL`): الأثرُ الخارجيُّ يحتاجُ outbox
        منفصل، ولا يُزعمُ له rollback. هذا عملٌ تالٍ.
        """
        from core.sovereignty.contract import EffectKind

        for sig in declared_effects:
            if sig.startswith(EffectKind.EXTERNAL.value + ":"):
                raise IdempotencyError(
                    f"الأثرُ «{sig}» خارجيّ. الأثرُ الخارجيُّ يحتاجُ outbox منفصل — "
                    "لا يُعالَجُ في المسارِ الذرّيّ المباشر."
                )

        key_lock = self._get_key_lock(key.composite)
        with key_lock:
            existing = self.ledger.get(key)
            if existing is not None:
                if existing.fingerprint != fingerprint:
                    raise IdempotencyKeyReuseError(
                        f"المفتاحُ «{key.composite}» مُستعمَلٌ ببصمةٍ مختلفة."
                    )
                if existing.status is OperationStatus.SUCCEEDED:
                    return OperationResult(
                        value=None,
                        status=OperationStatus.SUCCEEDED,
                        is_replay=True,
                        record=existing,
                    )
                if existing.status is OperationStatus.RUNNING:
                    raise IdempotencyConflictError(
                        f"العمليّةُ «{key.composite}» جاريةٌ في مكانٍ آخر."
                    )
                if not existing.status.is_recoverable:
                    raise IdempotencyError(
                        f"العمليّةُ «{key.composite}» في حالةٍ نهائيّة."
                    )
                # استعادة: تابع من حيث توقّف
                self.ledger.recover(key=key)
            else:
                self.ledger.reserve(key=key, fingerprint=fingerprint)

            self.ledger.mark_running(
                key=key,
                attempt={"started_at": _now_iso(), "mode": "effects"},
            )

            # الآثارُ التي طُبِّقَت سابقًا (في محاولةٍ فاشلة)
            current = self.ledger.get(key) or self.ledger.reserve(
                key=key, fingerprint=fingerprint,
            )
            already_applied = set(current.applied_effect_signatures)

            applied: list[str] = list(already_applied)
            pending_effect: str | None = None

            try:
                for sig in declared_effects:
                    if sig in already_applied:
                        continue  # لا إعادةَ تطبيق
                    # سجّلْ الأثرَ كـ«قيدِ التطبيق» قبلَ التنفيذ — لو فشلَ،
                    # يُعلمُ عمليّةُ الاستعادةِ أنّ هذا الأثرَ قد يكونُ طُبِّقَ
                    pending_effect = sig
                    self.ledger.transition(
                        key=key,
                        new_status=OperationStatus.RUNNING,
                        attempt={"effect_starting": sig, "at": _now_iso()},
                    )
                    apply_effect(sig)
                    # الأثرُ نُفِّذَ بنجاح — سجّلْه كـ«مُطبَّق»
                    pending_effect = None
                    applied.append(sig)
                    self.ledger.transition(
                        key=key,
                        new_status=OperationStatus.RUNNING,
                        applied_effect_signatures=tuple(applied),
                        attempt={"effect_applied": sig, "at": _now_iso()},
                    )
            except Exception as exc:
                # فشلٌ جزئيّ: بعضُ الآثارِ طُبِّقَ، وبعضُها لا
                # لو كان هناك أثرٌ قيدَ التطبيق، فقد يكونُ طُبِّقَ فعلًا
                recovery_msg = (
                    f"العمليّةُ «{key.composite}» فشلت بعدَ {len(applied)} أثر. "
                    f"الآثارُ المُطبَّقة: {', '.join(applied)}. "
                )
                if pending_effect is not None:
                    recovery_msg += (
                        f"الأثرُ «{pending_effect}» كان قيدَ التطبيقِ عندَ الفشل — "
                        "قد يكونُ طُبِّقَ فعلًا. يتطلّبُ فحصًا يدويًّا. "
                    )
                recovery_msg += "العمليّةُ في حالة `RECOVERY_REQUIRED`."
                self.ledger.transition(
                    key=key,
                    new_status=OperationStatus.RECOVERY_REQUIRED,
                    applied_effect_signatures=tuple(applied),
                    failure_reason=str(exc),
                    attempt={"failed_at": _now_iso(), "error": str(exc),
                             "applied_so_far": list(applied),
                             "pending_effect": pending_effect},
                )
                raise IdempotencyError(recovery_msg) from exc

            updated = self.ledger.mark_succeeded(
                key=key,
                result_digest=_digest_result(None),
                applied_effect_signatures=tuple(applied),
                has_external_effect=False,
            )

            return OperationResult(
                value=None,
                status=OperationStatus.SUCCEEDED,
                is_replay=False,
                record=updated,
            )

    def get_status(self, key: IdempotencyKey) -> IdempotencyRecord | None:
        """حالةُ عمليّةٍ — للقراءةِ بلا أثرٍ جانبيّ."""
        return self.ledger.get(key)


__all__ = [
    "DEFAULT_MAX_ATTEMPTS",
    "IDEMPOTENCY_DOMAIN",
    "IdempotencyConflictError",
    "IdempotencyError",
    "IdempotencyGuard",
    "IdempotencyKey",
    "IdempotencyKeyReuseError",
    "IdempotencyLedger",
    "IdempotencyRecord",
    "OperationNotRecoverableError",
    "OperationResult",
    "OperationStatus",
    "compute_fingerprint",
]
