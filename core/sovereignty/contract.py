"""الهدف: عقدُ التنفيذِ السياديّ — ربطُ الأثرِ الواقعِ بالحكمِ الصادرِ ربطًا مقيسًا.

النطاق: `core/sovereignty/` — العقدُ وأثرُه والتحقّقُ منه قبل مسِّ حالةِ الدولة.
المالك: core/sovereignty/ — التاج
تاريخ الإنشاء: 2026-08-18
تاريخ آخر تعديل: 2026-08-18

## الفجوةُ التي تسدُّها هذه الوحدة

كان `SovereignGateway.execute(request, executor)` يستقبل `executor: Callable[[], T]`
**بلا عقدٍ ولا حدٍّ ولا وصف**. فالبوابةُ تُقيّم `request` — «انشر خدمةً على
`svc-a`» — ثمّ تستدعي `executor()`. و`executor` بعد ذلك **حرٌّ تمامًا**: يجوز أن
يحوّل الخزينةَ، أو يمسّ موردًا لم يُذكَر في الطلب، أو ينادي طرفًا خارجيًّا. ولا
فرعَ واحدَ في المستودعِ كان يقارن **ما وقع** بـ**ما أُذِن به**: قياسًا، لا يوجد
في الشجرةِ كلِّها `ExecutionContract` ولا `effect` ولا `post_condition`.

وأخطرُ ما في ذلك أنّ السجلَّ يصير **شاهدَ زورٍ لا شاهدَ صدق**: يكتب
`action="deploy_service"` بينما الذي جرى شيءٌ آخر. فالتدقيقُ يوثّق الطلبَ لا
الأثر، ووثوقُنا به يصير وثوقًا بالنيّةِ لا بالواقع. وهذا مسٌّ بالقاعدةِ العليا 15:
لا يُعلَن شيءٌ مُثبَتًا بدليلٍ يصف غيرَ ما حدث.

## القرار: أثرٌ **مُعلَنٌ ثمّ مُحقَّقٌ ثمّ مُطبَّق** — لا أثرٌ يُكتشَف بعد وقوعه

ثلاثُ بوّاباتٍ متتاليةٍ، والأُولى قبل أيِّ تنفيذٍ أصلًا:

1. **حدُّ النطاقِ عند الربط:** الآثارُ المُعلَنةُ تُقاس على هدفِ الطلب. أثرٌ على
   موردٍ خارجَ الهدفِ يُرفَض **قبل استدعاءِ أيِّ شيء**، فلا يُنفَّذ ثمّ يُكتشَف.
2. **حدُّ العقدِ عند التخطيط:** `planner` دالّةٌ تُرجِع الآثارَ ولا تُطبِّقها. وكلُّ
   أثرٍ تُرجِعه يُقاس على العقد، فما لم يُعلَن **لا يصل إلى الحالةِ أبدًا**.
3. **التطبيقُ بعد التحقّق:** `applier` لا يُستدعى إلّا على أثرٍ مشمولٍ بالعقد.

فالمنعُ هنا **سابقٌ** لا لاحق: المُنفِّذُ لا يملك مسارًا إلى حالةِ الدولةِ إلّا عبر
آثارٍ يفحصُها العقد. وهذا فرقُ «كشفِ التجاوزِ» عن «استحالتِه».

## ما ليس مُثبَتًا — بصراحة

- المسارُ القديمُ `execute()` **باقٍ ويعمل** (القاعدتان 3 و11): تستدعيه اختباراتٌ
  وأدواتٌ وجسرُ النواةِ التنفيذيّة. فالدولةُ اليومَ فيها مسارٌ **بعقدٍ** ومسارٌ
  **بلا عقد**، وعددُ الثاني مُعلَنٌ في الفحصِ الذاتيِّ `uncontracted_executions`
  ولا يُخفى. وتحويلُ كلِّ المُنادينَ عملٌ تالٍ.
- **لا تراجعَ عن أثرٍ طُبِّق.** إن خالف `planner` عقدَه بعد أن طُبِّق أثرٌ سابقٌ
  مشروعٌ، فالمشروعُ باقٍ ولا يُلغى: التعويضُ والذرّيّةُ عملُ 1H و1I. والعقدُ
  يُصرِّح بذلك ولا يزعم ذرّيّةً لا يملكها.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Final, Generic, TypeVar

T = TypeVar("T")

#: فاصلُ النطاق: موردٌ داخلَ هدفٍ يُكتَب `target/child`.
SCOPE_SEPARATOR: Final[str] = "/"


class EffectKind(str, Enum):
    """أنواعُ الأثرِ السياديّ.

    التمييزُ ليس تصنيفًا إداريًّا: `DELETE` و`TRANSFER` لا يُقاسان بـ`READ` في
    التدقيق، ودمجُها في «أثرٍ» واحدٍ يُخفي أخطرَ ما يجري.
    """

    READ = "READ"
    CREATE = "CREATE"
    WRITE = "WRITE"
    DELETE = "DELETE"
    TRANSFER = "TRANSFER"
    EXTERNAL = "EXTERNAL"

    @property
    def is_mutating(self) -> bool:
        return self is not EffectKind.READ

    @property
    def arabic(self) -> str:
        return _EFFECT_ARABIC[self]


_EFFECT_ARABIC: Final[dict[EffectKind, str]] = {
    EffectKind.READ: "قراءة",
    EffectKind.CREATE: "إنشاء",
    EffectKind.WRITE: "كتابة",
    EffectKind.DELETE: "حذف",
    EffectKind.TRANSFER: "تحويل",
    EffectKind.EXTERNAL: "نداءٌ خارجيّ",
}


class ContractError(Exception):
    """خللٌ في العقدِ نفسِه — لا في أثرٍ بعينه."""


class EffectOutOfScopeError(ContractError):
    """أثرٌ مُعلَنٌ على موردٍ خارجَ هدفِ الطلبِ المأذونِ به.

    يُرفَع **عند الربطِ قبل أيِّ تنفيذ**: فالإذنُ بفعلٍ على هدفٍ ليس إذنًا بما
    سواه، ولو كان الفاعلُ والفعلُ نفسَهما.
    """


class ContractBreach(ContractError):
    """`planner` أرجع أثرًا لم يُعلَن في العقد.

    الأثرُ **لم يُطبَّق**: يُرفَع قبل استدعاءِ `applier` عليه. ويحمل الأثرَ
    المخالفَ كاملًا ليُدقَّق لا ليُلخَّص.
    """

    def __init__(self, contract: "ExecutionContract", uncovered: tuple["SovereignEffect", ...]) -> None:
        self.contract = contract
        self.uncovered = uncovered
        وصف = " · ".join(e.signature for e in uncovered)
        super().__init__(
            f"العقدُ «{contract.contract_id}» يأذن بـ{len(contract.declared_effects)} "
            f"أثرًا مُعلَنًا، و`planner` أرجع أثرًا غيرَ مُعلَنٍ: {وصف}. "
            "لم يُطبَّق شيءٌ منه."
        )


@dataclass(frozen=True, slots=True)
class SovereignEffect:
    """أثرٌ واحدٌ على حالةِ الدولة — مُعلَنٌ قبل وقوعِه ومقيسٌ عليه بعدَه.

    `payload_digest` بصمةُ الحمولةِ لا الحمولةُ نفسُها: العقدُ يُدقَّق ولا يُخزَّن
    فيه مضمونٌ قد يكون سرًّا.
    """

    kind: EffectKind
    resource: str
    detail: str = ""
    payload_digest: str | None = None

    def __post_init__(self) -> None:
        if not self.resource.strip():
            raise ContractError(
                "أثرٌ بلا موردٍ مُسمًّى. الأثرُ المُبهَمُ لا يُقاس على عقدٍ فلا يُقبَل."
            )

    @property
    def signature(self) -> str:
        """بصمةُ التطابق: النوعُ والمورد. التفصيلُ توضيحٌ لا شرطُ مطابقة."""
        return f"{self.kind.value}:{self.resource.strip()}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "resource": self.resource.strip(),
            "detail": self.detail,
            "payload_digest": self.payload_digest,
        }


def digest_of_payload(payload: bytes | str) -> str:
    """بصمةُ حمولةٍ — تُوضَع في الأثرِ مكانَ الحمولة."""
    raw = payload.encode("utf-8") if isinstance(payload, str) else payload
    return hashlib.sha256(raw).hexdigest()


def in_scope(resource: str, target: str) -> bool:
    """هل المورد داخلَ هدفِ الطلب؟

    هدفٌ فارغٌ = **لا نطاق**: لا يُشمَل به مورد. وهذا مُغلَقٌ بقصد — طلبٌ بلا
    هدفٍ لا يُقرَأ إذنًا مفتوحًا على الدولةِ كلِّها.
    """
    target = target.strip()
    resource = resource.strip()
    if not target or not resource:
        return False
    return resource == target or resource.startswith(target + SCOPE_SEPARATOR)


@dataclass(frozen=True, slots=True)
class ExecutionContract:
    """عقدٌ يربط حكمًا صادرًا بآثارٍ مُعلَنةٍ محصورةٍ في هدفِ الطلب.

    العقدُ **لا يُوسَّع بعد ربطِه**: `frozen` ليس تجميلًا، بل منعُ إضافةِ أثرٍ
    بعد صدورِ الإذن.
    """

    contract_id: str
    actor: str
    action: str
    target: str
    declared_effects: tuple[SovereignEffect, ...]
    bound_at: str
    authority_layer: str = ""
    decision_kind: str = ""

    @property
    def declared_signatures(self) -> frozenset[str]:
        return frozenset(e.signature for e in self.declared_effects)

    @property
    def mutating_effects(self) -> tuple[SovereignEffect, ...]:
        return tuple(e for e in self.declared_effects if e.kind.is_mutating)

    def covers(self, effect: SovereignEffect) -> bool:
        return effect.signature in self.declared_signatures

    def uncovered(self, effects: tuple[SovereignEffect, ...]) -> tuple[SovereignEffect, ...]:
        """الآثارُ التي لم يُعلَنها العقد — تُرجَع كلُّها لا أوّلُها."""
        return tuple(e for e in effects if not self.covers(e))

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "actor": self.actor,
            "action": self.action,
            "target": self.target,
            "declared_effects": [e.as_dict() for e in self.declared_effects],
            "bound_at": self.bound_at,
            "authority_layer": self.authority_layer,
            "decision_kind": self.decision_kind,
        }


@dataclass(frozen=True, slots=True)
class ExecutionOutcome(Generic[T]):
    """حصيلةُ تنفيذٍ بعقد: القيمةُ، والآثارُ المُطبَّقةُ فعلًا، وعقدُها."""

    contract: ExecutionContract
    value: T
    applied_effects: tuple[SovereignEffect, ...] = field(default=())

    @property
    def applied_signatures(self) -> tuple[str, ...]:
        return tuple(e.signature for e in self.applied_effects)

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract.contract_id,
            "applied_effects": [e.as_dict() for e in self.applied_effects],
        }


def bind_contract(
    *,
    actor: str,
    action: str,
    target: str,
    declared_effects: tuple[SovereignEffect, ...],
    request_fingerprint: str = "",
    authority_layer: str = "",
    decision_kind: str = "",
    now: datetime | None = None,
) -> ExecutionContract:
    """اربطْ عقدًا — ويُرفَض هنا كلُّ أثرٍ خارجَ النطاقِ قبل أيِّ تنفيذ.

    `contract_id` مُشتقٌّ من مضمونِ العقدِ لا من عدّادٍ: عقدانِ بمضمونٍ واحدٍ لهما
    الرقمُ نفسُه، وتغييرُ أثرٍ واحدٍ يُغيّر الرقم. فلا يُنسَب أثرٌ إلى عقدٍ لم يُعلِنه.
    """
    if not declared_effects:
        raise ContractError(
            "عقدٌ بلا أثرٍ مُعلَن. التنفيذُ الذي لا يُعلَن أثرُه لا يُدقَّق، "
            "والعقدُ الفارغُ إذنٌ مفتوحٌ متنكِّرٌ في صورةِ عقد."
        )
    خارجة = tuple(e for e in declared_effects if not in_scope(e.resource, target))
    if خارجة:
        raise EffectOutOfScopeError(
            f"الهدفُ المأذونُ به «{target or '—'}» والآثارُ الآتيةُ خارجَه: "
            + " · ".join(e.signature for e in خارجة)
            + ". الإذنُ بفعلٍ على هدفٍ ليس إذنًا بما سواه."
        )
    moment = (now or datetime.now(timezone.utc)).replace(microsecond=0).isoformat()
    مادّة = "|".join(
        [actor, action, target, request_fingerprint]
        + sorted(e.signature for e in declared_effects)
    )
    return ExecutionContract(
        contract_id="EC-" + hashlib.sha256(مادّة.encode("utf-8")).hexdigest()[:16],
        actor=actor,
        action=action,
        target=target,
        declared_effects=tuple(declared_effects),
        bound_at=moment,
        authority_layer=authority_layer,
        decision_kind=decision_kind,
    )


__all__ = [
    "SCOPE_SEPARATOR",
    "ContractBreach",
    "ContractError",
    "EffectKind",
    "EffectOutOfScopeError",
    "ExecutionContract",
    "ExecutionOutcome",
    "SovereignEffect",
    "bind_contract",
    "digest_of_payload",
    "in_scope",
]
