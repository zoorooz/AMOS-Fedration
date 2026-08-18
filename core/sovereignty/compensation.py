"""الهدف: التعويضُ السياديّ — أثرٌ طُبِّقَ ثمّ خالفَ العقدَ يُعكَسُ لا يُترَك.

النطاق: `core/sovereignty/` — عكسُ الأثرِ المُطبَّقِ وإرجاعُ حالةِ الدولةِ إلى ما
قبلَ عمليّةٍ لم تكتمل.
المالك: core/sovereignty/ — التاج
تاريخ الإنشاء: 2026-08-18
تاريخ آخر تعديل: 2026-08-18

## الفجوةُ التي تسدُّها هذه الوحدة — كما قِيسَت

بعدَ 1E (العقد) و1F (الإذن) و1G (الاختصاص) و1H (الذرّيّة)، المسارُ السياديُّ
**يمنعُ تكرارَ الأثرِ ولا يعكسُه**. وهذا مُصرَّحٌ به في مصدرِ 1E نفسِه:

> «**لا تراجعَ عن أثرٍ طُبِّق.** إن خالف `planner` عقدَه بعد أن طُبِّق أثرٌ سابقٌ
> مشروعٌ، فالمشروعُ باقٍ ولا يُلغى.»

وفي 1H، الفشلُ الجزئيُّ يُسجَّلُ في `RECOVERY_REQUIRED` مع قائمةِ الآثارِ
المُطبَّقة — وهذا **تشخيصٌ لا علاج**: الدولةُ تعرفُ أنّها في حالةٍ نصفيّة،
ولا تملكُ فعلًا يُخرجُها منها. فالحالةُ تبقى معلّقةً إلى تدخّلٍ بشريّ في كلِّ
فشلٍ جزئيّ، مهما كان الأثرُ قابلًا للعكسِ بذاته.

أربعةُ حدودٍ غائبة قبلَ هذه الوحدة:

| # | الحدُّ | أثرُه الملموس |
|---|-------|---------------|
| 1 | لا عكسَ لأثرٍ طُبِّق | تحويلٌ نُفِّذَ ثمّ خالفَ العقدَ يبقى نافذًا |
| 2 | لا إعلانَ مسبقًا لقابليّةِ العكس | لا يُعرَفُ إلّا بعدَ الفشلِ أنّ الأثرَ لا يُعكَس |
| 3 | لا حدَّ للتعويضِ نفسِه | «التراجعُ» قد يمسَّ موردًا خارجَ العقد |
| 4 | لا تمييزَ بين «عُوِّضَ» و«تعذّرَ التعويض» | الدولةُ تدّعي سلامةً لا تملكُ دليلَها |

## القرار الهندسيّ: **التعويضُ يُعلَنُ قبلَ التنفيذِ أو لا تنفيذ**

القاعدةُ المُنفَّذة هنا: **لا يُطبَّقُ أثرٌ مُغيِّرٌ لم يُعلَن له معكوسُه.**
فالخطّةُ التعويضيّةُ تُربَطُ بالعقدِ **قبلَ** أيِّ تنفيذ، وكلُّ أثرٍ مُغيِّرٍ في
العقدِ يجبُ أن يقابلَه معوّضٌ مسجَّل. أثرٌ بلا معوّضٍ يُرفَضُ عندَ الربطِ لا عندَ
الفشل — فالمنعُ سابقٌ لا لاحق، كما في `bind_contract`.

وهذا مقصودٌ لذاتِه: الدولةُ لا تدخلُ في فعلٍ لا تعرفُ كيف تخرجُ منه.

### لماذا لا يُبنى محرّكُ تنفيذٍ ثانٍ؟

`CompensationGuard` **يلفُّ** `IdempotencyGuard.run_effects_once` القائم ولا
يستبدلُه. لا يقرّرُ سلطةً، ولا يُصدِرُ إذنًا، ولا يمسُّ `gateway.py` ولا
`enforcement.py` ولا `jurisdiction.py` ولا `contract.py` ولا `idempotency.py`.
الإضافةُ إضافةٌ لا استبدال — كما في 1F و1G و1H.

### الأثرُ الخارجيُّ لا يُدَّعى له عكس

`EffectKind.EXTERNAL` **لا يُقبَلُ معوّضًا**. نداءٌ خارجيٌّ وقع لا يُسحَب،
وادّعاءُ «rollback» له كذبٌ في مستوى المعمار. فالخطّةُ ترفضُه عندَ الربط،
والمسارُ الذرّيُّ (1H) يرفضُه أصلًا.

## ما ليس مُثبَتًا — بصراحة

- **متاحٌ لا مفروض.** كما في 1F و1G و1H، لا شيءَ اليومَ يُلزِمُ كلَّ مسارٍ
  سياديٍّ بربطِ خطّةٍ تعويضيّة. الفرضُ يلزمه حرسٌ ساكنٌ (1M).
  **الحالة: AVAILABLE / VERIFIED / NOT YET ENFORCED.**
- **لا تعويضَ موزَّعًا.** السجلُّ ملفٌّ محليّ، كسجلِّ 1H.
- **لا تعويضَ للأثرِ الخارجيّ** — مرفوضٌ صراحةً لا مُهمَلٌ صمتًا.
- **فشلُ المعوّضِ نفسِه لا يُعوَّض.** لو فشلَ معوّضٌ، تُسجَّلُ الحالةُ
  `COMPENSATION_FAILED` وتُعلَنُ الآثارُ التي بقيت نافذةً بأسمائها. ولا يُزعمُ
  خروجٌ من الحالةِ النصفيّة: يلزمُ قرارٌ بشريّ.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from threading import RLock
from typing import Any, Final

from core.sovereignty.contract import (
    EffectKind,
    ExecutionContract,
    SovereignEffect,
    in_scope,
)
from core.sovereignty.idempotency import (
    IdempotencyError,
    IdempotencyGuard,
    IdempotencyKey,
    OperationStatus,
)

#: مجالُ بصمةِ التعويض — يمنعُ خلطَها ببصمةِ الذرّيّةِ أو الإذنِ أو العقد.
COMPENSATION_DOMAIN: Final[bytes] = b"AMOS-FEDERATION/COMPENSATION/v1"

#: أنواعُ الأثرِ التي لا يُقبَلُ لها معوّضٌ بحالٍ — لا يُدَّعى عكسُها.
IRREVERSIBLE_EFFECT_KINDS: Final[frozenset[EffectKind]] = frozenset(
    {EffectKind.EXTERNAL}
)


class CompensationStatus(str, Enum):
    """حالاتُ التعويض — لا `UNKNOWN` ولا حالةٌ ضمنيّة.

    الفرقُ بين `COMPENSATED` و`PARTIALLY_COMPENSATED` و`COMPENSATION_FAILED`
    ليس تدرّجًا وصفيًّا: الأولى تعني أنّ حالةَ الدولةِ رجعت، والأخريانِ تعنيانِ
    أنّ أثرًا ما زال نافذًا وأنّ الدولةَ **لا تدّعي** سلامتَها.
    """

    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPENSATED = "COMPENSATED"
    PARTIALLY_COMPENSATED = "PARTIALLY_COMPENSATED"
    COMPENSATION_FAILED = "COMPENSATION_FAILED"
    IRREVERSIBLE = "IRREVERSIBLE"

    @property
    def state_is_clean(self) -> bool:
        """هل رجعت حالةُ الدولةِ إلى ما قبلَ العمليّة؟

        `NOT_REQUIRED` نظيفةٌ لأنّه لم يُطبَّق شيء. وما عداها ممّا ليس
        `COMPENSATED` يعني أثرًا باقيًا.
        """
        return self in (
            CompensationStatus.NOT_REQUIRED,
            CompensationStatus.COMPENSATED,
        )

    @property
    def requires_human(self) -> bool:
        """هل تلزمُ يدٌ بشريّةٌ للخروجِ من هذه الحالة؟"""
        return self in (
            CompensationStatus.PARTIALLY_COMPENSATED,
            CompensationStatus.COMPENSATION_FAILED,
            CompensationStatus.IRREVERSIBLE,
        )

    @property
    def arabic(self) -> str:
        return _COMPENSATION_ARABIC[self]


_COMPENSATION_ARABIC: Final[dict[CompensationStatus, str]] = {
    CompensationStatus.NOT_REQUIRED: "لا تعويضَ مطلوبًا",
    CompensationStatus.PENDING: "تعويضٌ مُعلَّق",
    CompensationStatus.IN_PROGRESS: "تعويضٌ جارٍ",
    CompensationStatus.COMPENSATED: "عُوِّضَ كاملًا",
    CompensationStatus.PARTIALLY_COMPENSATED: "عُوِّضَ جزئيًّا",
    CompensationStatus.COMPENSATION_FAILED: "فشلَ التعويض",
    CompensationStatus.IRREVERSIBLE: "أثرٌ لا يُعكَس",
}


class CompensationError(Exception):
    """خللٌ في طبقةِ التعويض — يُرفَع ولا يُبتلَع."""


class UncompensatableEffectError(CompensationError):
    """أثرٌ مُغيِّرٌ مُعلَنٌ في العقدِ بلا معوّضٍ مسجَّل.

    يُرفَع **عندَ ربطِ الخطّةِ قبلَ أيِّ تنفيذ**: الدولةُ لا تدخلُ في فعلٍ لا
    تعرفُ كيف تخرجُ منه.
    """


class IrreversibleEffectError(CompensationError):
    """محاولةُ تسجيلِ معوّضٍ لأثرٍ لا يُعكَس (`EXTERNAL`).

    نداءٌ خارجيٌّ وقع لا يُسحَب. وادّعاءُ عكسِه كذبٌ في مستوى المعمار، فيُمنَع
    عندَ التسجيلِ لا عندَ الفشل.
    """


class CompensationScopeError(CompensationError):
    """معوّضٌ يمسُّ موردًا خارجَ هدفِ العقد.

    التعويضُ ليس بابًا خلفيًّا للسلطة: ما لم يُؤذَن بمسِّه عندَ التنفيذِ لا
    يُمَسُّ عندَ التراجع.
    """


def _atomic_write(path: Path, payload: Mapping[str, Any]) -> None:
    """كتابةٌ ذرّيّة: إمّا السجلُّ القديمُ كاملًا أو الجديدُ كاملًا."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(  # noqa: SIM115 — إدارةٌ يدويّةٌ للإغلاقِ الذرّيّ
        "w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp"
    )
    try:
        with handle as stream:
            json.dump(dict(payload), stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(handle.name, path)
    except BaseException:
        Path(handle.name).unlink(missing_ok=True)
        raise


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def compute_compensation_id(
    *,
    contract_id: str,
    operation_key: str,
    applied_signatures: tuple[str, ...],
) -> str:
    """هويّةُ تعويضٍ مُشتقّةٌ من مضمونِه لا من عدّاد.

    تعويضانِ لنفسِ العقدِ ونفسِ المفتاحِ ونفسِ الآثارِ المُطبَّقةِ لهما الهويّةُ
    نفسُها — وهو شرطُ كونِ التعويضِ ذرّيًّا لا مضاعَفًا.
    """
    مادّة = "|".join([contract_id, operation_key, *sorted(applied_signatures)])
    digest = hashlib.sha256(COMPENSATION_DOMAIN + مادّة.encode("utf-8")).hexdigest()
    return "CMP-" + digest[:20]


@dataclass(frozen=True, slots=True)
class Compensator:
    """معكوسُ أثرٍ واحد — مُعلَنٌ قبلَ التنفيذِ لا مُرتجَلٌ بعدَ الفشل.

    `apply` دالّةٌ بلا وسائط تُرجِعُ الحالةَ إلى ما قبلَ الأثر. و`description`
    ليست تجميلًا: تُكتَبُ في سجلِّ التعويضِ ليُقرأَ ما جرى لا ليُخمَّن.
    """

    effect_signature: str
    apply: Callable[[], None]
    description: str = ""

    def __post_init__(self) -> None:
        if not self.effect_signature.strip():
            raise CompensationError(
                "معوّضٌ بلا أثرٍ مُسمًّى. المعوّضُ المُبهَمُ لا يُنسَبُ إلى أثرٍ فلا يُقبَل."
            )
        if not callable(self.apply):
            raise CompensationError(
                f"معوّضُ «{self.effect_signature}» ليس فعلًا قابلًا للاستدعاء."
            )


@dataclass(frozen=True, slots=True)
class CompensationPlan:
    """خطّةُ تعويضٍ مربوطةٌ بعقدٍ — مُغلَقةٌ بعدَ الربط.

    `frozen` منعُ إضافةِ معوّضٍ بعدَ صدورِ الإذنِ وبدءِ التنفيذ: الخطّةُ التي
    تُقاسُ عليها العمليّةُ هي التي رُبِطَت قبلَها.
    """

    contract_id: str
    target: str
    compensators: tuple[Compensator, ...]
    bound_at: str

    @property
    def covered_signatures(self) -> frozenset[str]:
        return frozenset(c.effect_signature for c in self.compensators)

    def covers(self, signature: str) -> bool:
        return signature in self.covered_signatures

    def compensator_for(self, signature: str) -> Compensator:
        for c in self.compensators:
            if c.effect_signature == signature:
                return c
        raise UncompensatableEffectError(
            f"لا معوّضَ مسجَّلٌ للأثرِ «{signature}» في خطّةِ العقد «{self.contract_id}»."
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "target": self.target,
            "compensators": [
                {"effect_signature": c.effect_signature, "description": c.description}
                for c in self.compensators
            ],
            "bound_at": self.bound_at,
        }


def bind_compensation_plan(
    *,
    contract: ExecutionContract,
    compensators: tuple[Compensator, ...],
    now: datetime | None = None,
) -> CompensationPlan:
    """اربطْ خطّةَ تعويضٍ بعقد — ويُرفَضُ هنا كلُّ نقصٍ قبلَ أيِّ تنفيذ.

    ثلاثةُ حدودٍ تُفحَصُ عندَ الربط، وكلُّها **سابقةٌ** للتنفيذ:

    1. **أثرٌ لا يُعكَس** (`EXTERNAL`) مُعلَنٌ في العقد -> `IrreversibleEffectError`.
       لا خطّةَ تعويضٍ لعقدٍ فيه أثرٌ خارجيّ، ولا يُدَّعى له عكس.
    2. **أثرٌ مُغيِّرٌ بلا معوّض** -> `UncompensatableEffectError`.
       الدولةُ لا تدخلُ في فعلٍ لا تعرفُ كيف تخرجُ منه.
    3. **معوّضٌ لأثرٍ خارجَ العقد** -> `CompensationScopeError`.
       التعويضُ ليس بابًا خلفيًّا لمسِّ ما لم يُؤذَن بمسِّه.

    والأثرُ من نوعِ `READ` لا يحتاجُ معوّضًا: قراءةٌ لا تُغيِّرُ حالةً فلا تُعكَس.
    """
    خارجيّة = tuple(
        e for e in contract.declared_effects if e.kind in IRREVERSIBLE_EFFECT_KINDS
    )
    if خارجيّة:
        raise IrreversibleEffectError(
            f"العقدُ «{contract.contract_id}» يُعلِنُ أثرًا لا يُعكَس: "
            + " · ".join(e.signature for e in خارجيّة)
            + ". النداءُ الخارجيُّ إذا وقعَ لا يُسحَب، ولا تُربَطُ له خطّةُ تعويضٍ "
            "تزعمُ عكسَه. يلزمه outbox منفصلٌ وقرارٌ بشريّ."
        )

    مسجَّلة = {c.effect_signature for c in compensators}
    مكرَّرة = [
        sig for sig in مسجَّلة
        if sum(1 for c in compensators if c.effect_signature == sig) > 1
    ]
    if مكرَّرة:
        raise CompensationError(
            "معوّضانِ لأثرٍ واحد: " + " · ".join(sorted(مكرَّرة))
            + ". الأثرُ الواحدُ له معكوسٌ واحد، وإلّا صارَ التعويضُ مضاعَفًا."
        )

    مُعلَنة = contract.declared_signatures
    غريبة = tuple(sorted(مسجَّلة - set(مُعلَنة)))
    if غريبة:
        raise CompensationScopeError(
            f"العقدُ «{contract.contract_id}» لا يُعلِنُ هذه الآثارَ ولها معوّضات: "
            + " · ".join(غريبة)
            + ". ما لم يُؤذَن بمسِّه عندَ التنفيذِ لا يُمَسُّ عندَ التراجع."
        )

    خارج_النطاق = tuple(
        sorted(
            sig for sig in مسجَّلة
            if not in_scope(sig.split(":", 1)[-1], contract.target)
        )
    )
    if خارج_النطاق:
        raise CompensationScopeError(
            f"الهدفُ المأذونُ به «{contract.target or '—'}» والمعوّضاتُ الآتيةُ خارجَه: "
            + " · ".join(خارج_النطاق)
            + ". التعويضُ محكومٌ بنطاقِ العقدِ كالتنفيذِ سواءً بسواء."
        )

    ناقصة = tuple(
        sorted(e.signature for e in contract.mutating_effects if e.signature not in مسجَّلة)
    )
    if ناقصة:
        raise UncompensatableEffectError(
            f"العقدُ «{contract.contract_id}» يُعلِنُ آثارًا مُغيِّرةً بلا معوّضٍ مسجَّل: "
            + " · ".join(ناقصة)
            + ". لا يُطبَّقُ أثرٌ مُغيِّرٌ لم يُعلَن له معكوسُه."
        )

    moment = (now or datetime.now(timezone.utc)).replace(microsecond=0).isoformat()
    return CompensationPlan(
        contract_id=contract.contract_id,
        target=contract.target,
        compensators=tuple(compensators),
        bound_at=moment,
    )


@dataclass(slots=True)
class CompensationRecord:
    """سجلُّ تعويضٍ واحد — إضافيٌّ فقط، لا حذفَ ولا تعديلَ لما مضى."""

    compensation_id: str
    contract_id: str
    operation_key: str
    status: CompensationStatus
    opened_at: str
    applied_signatures: tuple[str, ...] = ()
    compensated_signatures: tuple[str, ...] = ()
    failed_signatures: tuple[str, ...] = ()
    residual_signatures: tuple[str, ...] = ()
    steps: list[dict[str, Any]] = field(default_factory=list)
    reason: str = ""
    closed_at: str | None = None

    @property
    def state_is_clean(self) -> bool:
        return self.status.state_is_clean

    @property
    def requires_human(self) -> bool:
        return self.status.requires_human

    def as_dict(self) -> dict[str, Any]:
        return {
            "compensation_id": self.compensation_id,
            "contract_id": self.contract_id,
            "operation_key": self.operation_key,
            "status": self.status.value,
            "opened_at": self.opened_at,
            "applied_signatures": list(self.applied_signatures),
            "compensated_signatures": list(self.compensated_signatures),
            "failed_signatures": list(self.failed_signatures),
            "residual_signatures": list(self.residual_signatures),
            "steps": list(self.steps),
            "reason": self.reason,
            "closed_at": self.closed_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CompensationRecord:
        return cls(
            compensation_id=data["compensation_id"],
            contract_id=data["contract_id"],
            operation_key=data["operation_key"],
            status=CompensationStatus(data["status"]),
            opened_at=data["opened_at"],
            applied_signatures=tuple(data.get("applied_signatures", [])),
            compensated_signatures=tuple(data.get("compensated_signatures", [])),
            failed_signatures=tuple(data.get("failed_signatures", [])),
            residual_signatures=tuple(data.get("residual_signatures", [])),
            steps=list(data.get("steps", [])),
            reason=data.get("reason", ""),
            closed_at=data.get("closed_at"),
        )


@dataclass(slots=True)
class CompensationJournal:
    """سجلُّ التعويضِ على القرص — يبقى بعدَ سقوطِ العمليّة.

    كلُّ خطوةٍ تُكتَبُ ذرّيًّا **قبلَ** استدعاءِ المعوّضِ وبعدَه. فلو انقطعت
    العمليّةُ في منتصفِ التعويض، بقيَ في السجلِّ أيُّ معوّضٍ كان قيدَ التنفيذ،
    فلا تُقرأُ الحالةُ الناقصةُ نجاحًا.
    """

    path: Path
    _lock: RLock = field(default_factory=RLock, repr=False, compare=False)

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            return dict(json.loads(self.path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, ValueError) as exc:
            raise CompensationError(
                f"سجلُّ التعويضِ في «{self.path}» تالفٌ ولا يُمكنُ قراءتُه."
            ) from exc

    def _save(self, records: Mapping[str, dict[str, Any]]) -> None:
        _atomic_write(self.path, records)

    def get(self, compensation_id: str) -> CompensationRecord | None:
        data = self._load().get(compensation_id)
        return CompensationRecord.from_dict(data) if data else None

    def open(
        self,
        *,
        compensation_id: str,
        contract_id: str,
        operation_key: str,
        applied_signatures: tuple[str, ...],
        reason: str,
        now: str | None = None,
    ) -> CompensationRecord:
        """افتحْ سجلَّ تعويضٍ — أو أرجِعِ القائمَ إن كان مفتوحًا من قبل."""
        with self._lock:
            records = self._load()
            existing = records.get(compensation_id)
            if existing is not None:
                return CompensationRecord.from_dict(existing)
            record = CompensationRecord(
                compensation_id=compensation_id,
                contract_id=contract_id,
                operation_key=operation_key,
                status=CompensationStatus.PENDING,
                opened_at=now or _now_iso(),
                applied_signatures=tuple(applied_signatures),
                residual_signatures=tuple(applied_signatures),
                reason=reason,
            )
            records[compensation_id] = record.as_dict()
            self._save(records)
            return record

    def step(
        self,
        *,
        compensation_id: str,
        status: CompensationStatus,
        entry: Mapping[str, Any],
        compensated: tuple[str, ...] | None = None,
        failed: tuple[str, ...] | None = None,
        residual: tuple[str, ...] | None = None,
        closed: bool = False,
    ) -> CompensationRecord:
        """سجّلْ خطوةً — إضافةٌ فقط، والخطواتُ السابقةُ لا تُمَسّ."""
        with self._lock:
            records = self._load()
            data = records.get(compensation_id)
            if data is None:
                raise CompensationError(
                    f"لا سجلَّ تعويضٍ بالهويّة «{compensation_id}»."
                )
            record = CompensationRecord.from_dict(data)
            record.status = status
            record.steps = [*record.steps, {**dict(entry), "at": _now_iso()}]
            if compensated is not None:
                record.compensated_signatures = tuple(compensated)
            if failed is not None:
                record.failed_signatures = tuple(failed)
            if residual is not None:
                record.residual_signatures = tuple(residual)
            if closed:
                record.closed_at = _now_iso()
            records[compensation_id] = record.as_dict()
            self._save(records)
            return record

    def count(self) -> int:
        return len(self._load())

    def all_records(self) -> list[CompensationRecord]:
        return [CompensationRecord.from_dict(d) for d in self._load().values()]

    def unclean_records(self) -> list[CompensationRecord]:
        """السجلّاتُ التي بقيَ فيها أثرٌ نافذ — الدولةُ تُعلِنُ دَينَها ولا تُخفيه."""
        return [r for r in self.all_records() if not r.state_is_clean]


@dataclass(frozen=True, slots=True)
class CompensationOutcome:
    """حصيلةُ تعويضٍ: ما رجعَ، وما بقيَ، وهل الحالةُ نظيفة."""

    record: CompensationRecord
    original_failure: str

    @property
    def status(self) -> CompensationStatus:
        return self.record.status

    @property
    def state_is_clean(self) -> bool:
        return self.record.state_is_clean

    @property
    def requires_human(self) -> bool:
        return self.record.requires_human

    @property
    def residual_signatures(self) -> tuple[str, ...]:
        return self.record.residual_signatures


class CompensationRequired(CompensationError):
    """العمليّةُ فشلت وعُوِّضَ أثرُها — يُرفَعُ ليُقرأَ لا ليُبتلَع.

    يحملُ الحصيلةَ كاملةً: لو كانت `state_is_clean` فالدولةُ رجعت، وإلّا
    فالأثرُ الباقي مُعلَنٌ بأسمائِه.
    """

    def __init__(self, outcome: CompensationOutcome) -> None:
        self.outcome = outcome
        rec = outcome.record
        if rec.state_is_clean:
            وصف = "وعُوِّضَ أثرُها كاملًا فرجعتِ الحالة"
        else:
            وصف = (
                "ولم يُعوَّض كلُّ أثرِها. الباقي نافذًا: "
                + (" · ".join(rec.residual_signatures) or "—")
                + ". يلزمُ قرارٌ بشريّ"
            )
        super().__init__(
            f"العمليّةُ «{rec.operation_key}» على العقد «{rec.contract_id}» فشلت "
            f"({outcome.original_failure}) {وصف}. الحالة: {rec.status.value}."
        )


@dataclass(slots=True)
class CompensationGuard:
    """حارسُ التعويض — يلفُّ المسارَ الذرّيَّ القائمَ ولا يستبدلُه.

    لا يملكُ `force` ولا `bypass` ولا `override`، ولا يُصدِرُ إذنًا، ولا يقرّرُ
    سلطة. عملُه واحد: أن يعكسَ ما طُبِّقَ بمعوّضاتٍ أُعلِنَت قبلَ التنفيذ، أو أن
    يُعلِنَ صراحةً أنّه لم يستطع.
    """

    journal: CompensationJournal
    idempotency: IdempotencyGuard

    # ── التعويضُ المباشر ────────────────────────────────────────────────────

    def compensate(
        self,
        *,
        contract: ExecutionContract,
        plan: CompensationPlan,
        operation_key: IdempotencyKey,
        applied_signatures: tuple[str, ...],
        reason: str,
    ) -> CompensationOutcome:
        """اعكسِ الآثارَ المُطبَّقةَ بترتيبٍ عكسيّ (LIFO).

        الترتيبُ العكسيُّ ليس تفضيلًا أسلوبيًّا: أثرٌ بُنيَ فوقَ أثرٍ سابقٍ يجبُ
        أن يُزالَ قبلَه، وإلّا عُوِّضَ الأساسُ وبقيَ ما فوقَه معلّقًا.

        والتعويضُ **ذرّيٌّ بذاتِه**: هويّتُه مُشتقّةٌ من مضمونِه، وإعادةُ
        استدعائِه على تعويضٍ مُغلَقٍ تُرجِعُ الحصيلةَ نفسَها ولا تُعيدُ عكسَ شيء.
        """
        if plan.contract_id != contract.contract_id:
            raise CompensationScopeError(
                f"الخطّةُ مربوطةٌ بالعقد «{plan.contract_id}» والعمليّةُ على "
                f"العقد «{contract.contract_id}». لا تُستعارُ خطّةُ عقدٍ لعقدٍ آخر."
            )

        applied = tuple(applied_signatures)
        comp_id = compute_compensation_id(
            contract_id=contract.contract_id,
            operation_key=operation_key.composite,
            applied_signatures=applied,
        )

        if not applied:
            record = self.journal.open(
                compensation_id=comp_id,
                contract_id=contract.contract_id,
                operation_key=operation_key.composite,
                applied_signatures=(),
                reason=reason,
            )
            record = self.journal.step(
                compensation_id=comp_id,
                status=CompensationStatus.NOT_REQUIRED,
                entry={"note": "لا أثرَ مُطبَّقًا — لا تعويضَ مطلوبًا"},
                compensated=(),
                failed=(),
                residual=(),
                closed=True,
            )
            return CompensationOutcome(record=record, original_failure=reason)

        existing = self.journal.get(comp_id)
        if existing is not None and existing.closed_at is not None:
            # تعويضٌ مُغلَقٌ لا يُعادُ تنفيذُه — وإلّا صارَ التعويضُ مضاعَفًا.
            return CompensationOutcome(record=existing, original_failure=reason)

        record = self.journal.open(
            compensation_id=comp_id,
            contract_id=contract.contract_id,
            operation_key=operation_key.composite,
            applied_signatures=applied,
            reason=reason,
        )

        غيرُ_مشمول = tuple(sorted(s for s in applied if not plan.covers(s)))
        if غيرُ_مشمول:
            record = self.journal.step(
                compensation_id=comp_id,
                status=CompensationStatus.IRREVERSIBLE,
                entry={
                    "note": "أثرٌ مُطبَّقٌ بلا معوّضٍ في الخطّة",
                    "uncovered": list(غيرُ_مشمول),
                },
                compensated=(),
                failed=list(غيرُ_مشمول),
                residual=applied,
                closed=True,
            )
            return CompensationOutcome(record=record, original_failure=reason)

        self.journal.step(
            compensation_id=comp_id,
            status=CompensationStatus.IN_PROGRESS,
            entry={"note": "بدءُ التعويضِ بترتيبٍ عكسيّ", "order": list(reversed(applied))},
        )

        compensated: list[str] = []
        failed: list[str] = []
        residual: list[str] = list(applied)

        for sig in reversed(applied):
            compensator = plan.compensator_for(sig)
            # يُكتَبُ قبلَ الاستدعاء: لو انقطعتِ العمليّةُ هنا بقيَ الأثرُ مُعلَنًا
            self.journal.step(
                compensation_id=comp_id,
                status=CompensationStatus.IN_PROGRESS,
                entry={
                    "compensating": sig,
                    "description": compensator.description,
                },
            )
            try:
                compensator.apply()
            except Exception as exc:  # noqa: BLE001 — يُسجَّلُ ويُعلَنُ لا يُبتلَع
                failed.append(sig)
                self.journal.step(
                    compensation_id=comp_id,
                    status=CompensationStatus.IN_PROGRESS,
                    entry={
                        "compensation_failed": sig,
                        "error": str(exc),
                    },
                    compensated=tuple(compensated),
                    failed=tuple(failed),
                    residual=tuple(residual),
                )
                continue
            compensated.append(sig)
            residual.remove(sig)
            self.journal.step(
                compensation_id=comp_id,
                status=CompensationStatus.IN_PROGRESS,
                entry={"compensated": sig},
                compensated=tuple(compensated),
                failed=tuple(failed),
                residual=tuple(residual),
            )

        if not failed:
            final_status = CompensationStatus.COMPENSATED
        elif compensated:
            final_status = CompensationStatus.PARTIALLY_COMPENSATED
        else:
            final_status = CompensationStatus.COMPENSATION_FAILED

        record = self.journal.step(
            compensation_id=comp_id,
            status=final_status,
            entry={
                "note": "انتهاءُ التعويض",
                "compensated_count": len(compensated),
                "failed_count": len(failed),
            },
            compensated=tuple(compensated),
            failed=tuple(failed),
            residual=tuple(residual),
            closed=True,
        )
        return CompensationOutcome(record=record, original_failure=reason)

    # ── المعاملةُ السياديّةُ الكاملة ─────────────────────────────────────────

    def run_compensated_transaction(
        self,
        *,
        contract: ExecutionContract,
        plan: CompensationPlan,
        key: IdempotencyKey,
        fingerprint: str,
        apply_effect: Callable[[str], None],
    ) -> Any:
        """نفِّذْ آثارَ العقدِ ذرّيًّا، وإن فشلَ التنفيذُ فاعكسْ ما طُبِّق.

        هذه هي القدرةُ الجديدةُ التي تضيفُها 1I: **معاملةٌ سياديّةٌ إمّا أن تتمَّ
        كاملةً أو لا تترك أثرًا** — بدل الحالةِ النصفيّةِ التي كانت 1H تُشخِّصُها
        ولا تُعالجُها.

        - نجاحٌ -> `OperationResult` من 1H كما هي، ولا يُفتَحُ سجلُّ تعويض.
        - فشلٌ -> يُعوَّضُ ما طُبِّقَ ثمّ يُرفَعُ `CompensationRequired` حاملًا
          الحصيلة. ولا يُبتلَعُ الفشلُ ولا يُقلَبُ نجاحًا.

        والتنفيذُ نفسُه يبقى على `IdempotencyGuard.run_effects_once`: لا محرّكَ
        ثانيًا ولا مسارَ تنفيذٍ موازٍ.
        """
        if plan.contract_id != contract.contract_id:
            raise CompensationScopeError(
                f"الخطّةُ مربوطةٌ بالعقد «{plan.contract_id}» والعمليّةُ على "
                f"العقد «{contract.contract_id}». لا تُستعارُ خطّةُ عقدٍ لعقدٍ آخر."
            )

        declared = tuple(e.signature for e in contract.mutating_effects)
        try:
            return self.idempotency.run_effects_once(
                key=key,
                fingerprint=fingerprint,
                declared_effects=declared,
                apply_effect=apply_effect,
            )
        except IdempotencyError as exc:
            record = self.idempotency.get_status(key)
            applied = tuple(record.applied_effect_signatures) if record else ()
            outcome = self.compensate(
                contract=contract,
                plan=plan,
                operation_key=key,
                applied_signatures=applied,
                reason=str(exc),
            )
            if outcome.state_is_clean and record is not None:
                # الحالةُ رجعت: العمليّةُ لم تعد «تتطلّبُ استعادةً يدويّة»،
                # ويُسجَّلُ ذلك في سجلِّ الذرّيّةِ نفسِه لا في سجلٍّ موازٍ.
                self.idempotency.ledger.transition(
                    key=key,
                    new_status=OperationStatus.FAILED_RETRYABLE,
                    applied_effect_signatures=(),
                    failure_reason=str(exc),
                    attempt={
                        "compensated": True,
                        "compensation_id": outcome.record.compensation_id,
                        "at": _now_iso(),
                    },
                )
            raise CompensationRequired(outcome) from exc

    # ── القراءة ─────────────────────────────────────────────────────────────

    def outstanding_debt(self) -> tuple[CompensationRecord, ...]:
        """ما بقيَ من أثرٍ لم يُعوَّض — دَينُ الدولةِ مُعلَنٌ لا مُخفًى."""
        return tuple(self.journal.unclean_records())


def effects_of(signatures: tuple[str, ...]) -> tuple[SovereignEffect, ...]:
    """أعِدْ بناءَ آثارٍ من بصماتِها — للقراءةِ والتدقيقِ لا للتنفيذ."""
    out: list[SovereignEffect] = []
    for sig in signatures:
        kind_raw, _, resource = sig.partition(":")
        try:
            kind = EffectKind(kind_raw)
        except ValueError as exc:
            raise CompensationError(
                f"بصمةُ أثرٍ غيرُ معروفةٍ: «{sig}»."
            ) from exc
        out.append(SovereignEffect(kind=kind, resource=resource))
    return tuple(out)


__all__ = [
    "COMPENSATION_DOMAIN",
    "IRREVERSIBLE_EFFECT_KINDS",
    "CompensationError",
    "CompensationGuard",
    "CompensationJournal",
    "CompensationOutcome",
    "CompensationPlan",
    "CompensationRecord",
    "CompensationRequired",
    "CompensationScopeError",
    "CompensationStatus",
    "Compensator",
    "IrreversibleEffectError",
    "UncompensatableEffectError",
    "bind_compensation_plan",
    "compute_compensation_id",
    "effects_of",
]
