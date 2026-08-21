"""الهدف: فصلُ موضعِ القرارِ عن موضعِ الإنفاذ — إذنٌ يُحمَل، ومُنفِّذٌ لا يحكم.

النطاق: `core/sovereignty/` — إذنُ الإنفاذِ والتحقّقُ منه واستهلاكُه.
المالك: core/sovereignty/ — التاج
تاريخ الإنشاء: 2026-08-18
تاريخ آخر تعديل: 2026-08-21

## الفجوةُ التي تسدُّها هذه الوحدة

`PDP` و`PEP` غيرُ موجودَين في المستودعِ قطُّ: كلُّ ما يَظهر بحثًا عن `PEP` هو
`PEP 562` في تعليقاتِ الاستيرادِ المتأخّر. وقياسًا على `gateway.py`، القرارُ
والإنفاذُ **نداءان متتاليان في التابعِ نفسِه**: `self._engine.evaluate(...)` ثمّ
`executor()`، ولا شيءَ بينهما.

ويترتّب على ذلك ثلاثةُ حدودٍ حقيقيّة:

1. **لا يوجد أثرُ قرارٍ يُحمَل.** فمن أراد أن يُنفِّذ لزمه أن يملك بوابةً كاملةً
   بمحرّكٍ دستوريّ — أي أنّ **كلَّ نقطةِ إنفاذٍ تصير نقطةَ قرار**. وهذا ما وقع
   فعلًا: `ConstitutionalAuthorizer` في النواةِ التنفيذيّةِ الفدراليّة يبني
   `SovereignGateway()` لنفسِه، فهو الحاكمُ والمُنفِّذُ معًا.
2. **لا فرقَ بين «أحمل إذنًا» و«أملك أن آذن».** ولا سبيلَ لقياسِ الفرق.
3. **لا إنفاذَ على بُعد.** المُنفِّذُ يجري **داخل** البوابة، فلا عمليّةَ أخرى ولا
   خدمةَ أخرى ولا وقتَ لاحقٌ يمكنه أن يُنفِّذ قرارًا صدر.

و`Verdict` وحدَه لا يصلح إذنًا: لا ينتهي، ولا يُستهلَك، ولا يرتبط بالآثارِ
المأذونِ بها، ولا يُكشَف تزويرُه ولا إعادةُ استعمالِه.

## القرار: إذنٌ مُوقَّعٌ بـEd25519 يحمله المُنفِّذُ ولا يستطيع صناعتَه

- **القرارُ** يبقى في `SovereignGateway.decide` — وهي تمرُّ من `execute` نفسِها
  حرفيًّا، فلا محرّكَ ثانيَ ولا منطقَ قرارٍ مكرّرٌ يمكن أن يتباعد عنها (5 و6).
- **الإنفاذُ** هنا في `PolicyEnforcementPoint`: **لا محرّكَ فيه ولا مفتاحَ توقيع**
  — يملك مفتاحَ تحقّقٍ عامًّا فحسب. فهو **لا يستطيع** أن يُصدِر إذنًا لنفسِه، لا
  لأنّه لا يفعل بل لأنّه لا يملك ما يفعل به.
- والإذنُ **يُستهلَك على القرص** لا في الذاكرة (القاعدة 17)، فإعادةُ استعمالِه
  تُكشَف عبر العمليّاتِ لا داخل عمليّةٍ واحدة.
- ونطاقُ الإذنِ هو **عقدُ 1E نفسُه**: بصماتُ الآثارِ المُعلَنة. فلا مفهومَ نطاقٍ
  ثانٍ موازٍ (القاعدة 6).

## ما ليس مُثبَتًا — بصراحة

- **مفتاحُ التوقيعِ عابرٌ مع العمليّة.** يُولَّد عند إنشاء البوابةِ ولا يُحفَظ،
  فإذنٌ صدر قبل إعادةِ التشغيلِ لا يُقبَل بعدها. وهذا **مُغلَقٌ لا مفتوح** (يُرفَض
  لا يُقبَل)، لكنّه ليس إدارةَ مفاتيحَ حقيقيّة: ربطُ مفتاحِ القرارِ بجذرِ التاج
  عملٌ تالٍ.
- **لا شيءَ يُلزِم أحدًا بسلوكِ هذا الطريق.** `execute` المباشرةُ باقيةٌ تعمل، وهذا
  فصلٌ **متاحٌ** لا **مفروض**. الفرضُ يلزمه حرسٌ ساكنٌ (1M).
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Final

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ed25519

from core.sovereignty.contract import ExecutionContract, SovereignEffect

#: مجالُ التوقيع — يمنع أن يُقرَأ توقيعُ إذنٍ توقيعَ مرسومٍ أو تحدّي تنسيب.
PERMIT_DOMAIN: Final[bytes] = b"AMOS-FEDERATION/ENFORCEMENT-PERMIT/v1"

#: عمرُ الإذنِ الافتراضيّ. قصيرٌ بقصد: الإذنُ رخصةُ لحظةٍ لا صكُّ ملكيّة.
DEFAULT_PERMIT_TTL_SECONDS: Final[int] = 300

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
CONSUMED_PERMITS_PATH: Final[Path] = (
    REPO_ROOT / "royal" / "authority" / "CONSUMED_PERMITS.json"
)

#: مُتغيّرُ بيئةٍ يُعلِن موضعَ سجلِّ الأذونِ المُستهلَكةِ عندَ التشغيل.
#:
#: الموضعُ الافتراضيُّ أعلاه **لم يُنقَل**: هو عقدُ مرحلةٍ مغلقةٍ (1G)، ونقلُه
#: قرارٌ بشريٌّ مُعلَنٌ في `PROJECT_STATE.md`. لكنَّ الافتراضيَّ داخلَ الشجرةِ
#: المُتعقَّبة، فكلُّ تشغيلٍ لا يُصرِّحُ بموضعِه يكتبُ حالةَ تشغيلٍ في المستودعِ
#: نفسِه — وقد قيسَ ذلك فعلًا: `pytest tests/sovereignty/test_supreme_authority.py`
#: كان يُنشئُ `royal/authority/CONSUMED_PERMITS.json` في شجرةٍ نظيفة. فالمخرَجُ
#: يُوجَّه بإعلانٍ صريحٍ في البيئةِ، ويبقى الافتراضيُّ كما هو لمن لا يُعلِن.
CONSUMED_PERMITS_PATH_ENV: Final[str] = "AMOS_CONSUMED_PERMITS_PATH"


def consumed_permits_path() -> Path:
    """موضعُ سجلِّ الأذون: المُعلَنُ في البيئةِ إن أُعلِن، وإلّا الافتراضيُّ نفسُه.

    يُقرَأُ عندَ كلِّ بناءٍ لا عندَ الاستيراد: قراءةٌ عندَ الاستيرادِ تُجمِّدُ
    الموضعَ على أوّلِ لحظةٍ استُورِدَت فيها الوحدة، فيصيرُ الإعلانُ اللاحقُ بلا
    أثرٍ — وهو سقوطٌ صامتٌ لا يُقبَل (القاعدة 16).
    """
    مُعلَن = os.environ.get(CONSUMED_PERMITS_PATH_ENV, "").strip()
    return Path(مُعلَن) if مُعلَن else CONSUMED_PERMITS_PATH


class EnforcementError(Exception):
    """خللٌ في الإنفاذ — يُرفَع ولا يُبتلَع (القاعدة 16)."""


class PermitInvalidError(EnforcementError):
    """توقيعُ الإذنِ لا يطابق مضمونَه — تزويرٌ أو تحريفٌ بعد الإصدار."""


class PermitExpiredError(EnforcementError):
    """انقضى عمرُ الإذن. الرخصةُ الفائتةُ ليست رخصة."""


class PermitReplayError(EnforcementError):
    """إذنٌ استُهلِك من قبل. الإذنُ الواحدُ لفعلٍ واحد."""


class PermitScopeError(EnforcementError):
    """المُنفِّذُ حاول أثرًا لم يأذن به الإذن."""


def _canonical(payload: dict[str, Any]) -> bytes:
    """تمثيلٌ واحدٌ لا لبسَ فيه — وإلّا صار ترتيبُ المفاتيحِ ثغرةَ توقيع."""
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    """كتابةٌ ذرّيّة: إمّا السجلُّ القديمُ كاملًا أو الجديدُ كاملًا، ولا نصفَ سجلّ."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
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


@dataclass(frozen=True, slots=True)
class EnforcementPermit:
    """إذنُ إنفاذٍ صادرٌ عن موضعِ القرارِ ومحمولٌ إلى موضعِ الإنفاذ.

    كلُّ حقلٍ هنا **داخلٌ في التوقيع**: تغييرُ حرفٍ واحدٍ يُبطِله. ولا حقلَ يقوله
    المُنفِّذُ عن نفسِه.
    """

    permit_id: str
    actor: str
    action: str
    target: str
    contract_id: str
    effect_signatures: tuple[str, ...]
    decision: str
    authority_layer: str
    decision_kind: str
    request_fingerprint: str
    ledger_entry_hash: str | None
    issued_at: str
    expires_at: str
    signature_hex: str = ""

    def content(self) -> dict[str, Any]:
        """المضمونُ المُوقَّع — بلا التوقيعِ نفسِه بداهةً."""
        return {
            "permit_id": self.permit_id,
            "actor": self.actor,
            "action": self.action,
            "target": self.target,
            "contract_id": self.contract_id,
            "effect_signatures": list(self.effect_signatures),
            "decision": self.decision,
            "authority_layer": self.authority_layer,
            "decision_kind": self.decision_kind,
            "request_fingerprint": self.request_fingerprint,
            "ledger_entry_hash": self.ledger_entry_hash,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
        }

    def signing_payload(self) -> bytes:
        return PERMIT_DOMAIN + b"|" + _canonical(self.content())

    def is_expired(self, now: datetime | None = None) -> bool:
        moment = now or datetime.now(timezone.utc)
        return moment > datetime.fromisoformat(self.expires_at)

    def covers(self, effect: SovereignEffect) -> bool:
        return effect.signature in self.effect_signatures

    def as_dict(self) -> dict[str, Any]:
        return {**self.content(), "signature_hex": self.signature_hex}


def sign_permit(
    permit: EnforcementPermit, private_key: ed25519.Ed25519PrivateKey
) -> EnforcementPermit:
    """وقّعْ إذنًا. يُستدعى من موضعِ القرارِ وحدَه — وهو وحده يملك المفتاح."""
    signature = private_key.sign(permit.signing_payload())
    return EnforcementPermit(**{**permit.as_dict(), "signature_hex": signature.hex(),
                                "effect_signatures": tuple(permit.effect_signatures)})


def issue_permit(
    *,
    contract: ExecutionContract,
    request_fingerprint: str,
    decision: str,
    ledger_entry_hash: str | None,
    private_key: ed25519.Ed25519PrivateKey,
    authority_layer: str = "",
    decision_kind: str = "",
    ttl_seconds: int = DEFAULT_PERMIT_TTL_SECONDS,
    now: datetime | None = None,
) -> EnforcementPermit:
    """أصدِرْ إذنًا موقَّعًا من عقدٍ مربوطٍ وحكمٍ صادر.

    نطاقُ الإذنِ هو نطاقُ العقدِ نفسُه ولا يزيد عليه حرفًا: لا يملك مُصدِرُ الإذنِ
    أن يوسّع ما أُعلِن.

    أمّا `authority_layer` و`decision_kind` فيُؤخذان من **الحكمِ الصادر** لا من
    العقد: العقدُ يُربَط قبل الحكمِ ليُفحَص نطاقُه، فلا يعلم طبقةَ سلطةٍ بعدُ.
    ووضعُ صفرِ العقدِ مكانَ الحكمِ كذبٌ صامتٌ في وثيقةٍ موقَّعة.
    """
    if ttl_seconds <= 0:
        raise EnforcementError(
            "إذنٌ بعمرٍ غيرِ موجَب. الإذنُ الذي لا ينتهي صكُّ ملكيّةٍ لا رخصةُ لحظة."
        )
    moment = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    غير_موقَّع = EnforcementPermit(
        permit_id=f"EP-{contract.contract_id[3:]}-{int(moment.timestamp())}",
        actor=contract.actor,
        action=contract.action,
        target=contract.target,
        contract_id=contract.contract_id,
        effect_signatures=tuple(sorted(contract.declared_signatures)),
        decision=decision,
        authority_layer=authority_layer or contract.authority_layer,
        decision_kind=decision_kind or contract.decision_kind,
        request_fingerprint=request_fingerprint,
        ledger_entry_hash=ledger_entry_hash,
        issued_at=moment.isoformat(),
        expires_at=(moment + timedelta(seconds=ttl_seconds)).isoformat(),
    )
    return sign_permit(غير_موقَّع, private_key)


@dataclass(slots=True)
class ConsumedPermitLedger:
    """سجلُّ الأذوناتِ المُستهلَكة — على القرصِ لا في الذاكرة (القاعدة 17).

    ولو كان في الذاكرةِ لصارت إعادةُ الاستعمالِ ممكنةً بعمليّةٍ ثانية، وهذا هو
    الطريقُ الذي يُهاجَم به عمليًّا.
    """

    path: Path = field(default_factory=consumed_permits_path)

    def _load(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        return dict(json.loads(self.path.read_text(encoding="utf-8")))

    def is_consumed(self, permit_id: str) -> bool:
        return permit_id in self._load()

    def consume(self, permit_id: str, *, now: datetime | None = None) -> None:
        """استهلِكْ إذنًا. الاستهلاكُ المكرَّرُ يُرفَع ولا يُبتلَع."""
        سجل = self._load()
        if permit_id in سجل:
            raise PermitReplayError(
                f"الإذنُ «{permit_id}» استُهلِك في {سجل[permit_id]}. "
                "الإذنُ الواحدُ لفعلٍ واحد."
            )
        سجل[permit_id] = (now or datetime.now(timezone.utc)).replace(
            microsecond=0
        ).isoformat()
        _atomic_write(self.path, سجل)

    def count(self) -> int:
        return len(self._load())


@dataclass(slots=True)
class PolicyEnforcementPoint:
    """موضعُ الإنفاذ: يُنفِّذ بإذنٍ ولا يحكم بشيء.

    **ما لا يملكه هذا الصنفُ هو تعريفُه:** لا `ConstitutionalEngine` ولا
    `SovereignGateway` ولا مفتاحَ توقيع. يملك مفتاحَ تحقّقٍ عامًّا وسجلَّ استهلاك.
    فامتناعُه عن الحكمِ **بنيويٌّ لا سلوكيّ**.
    """

    verifying_key: ed25519.Ed25519PublicKey
    consumed: ConsumedPermitLedger = field(default_factory=ConsumedPermitLedger)

    # ── التحقّق ───────────────────────────────────────────────────────────
    def verify(self, permit: EnforcementPermit, *, now: datetime | None = None) -> None:
        """تحقّقْ من الإذنِ بلا استهلاك. يرفع عند أوّلِ خللٍ ولا يُرجِع رايةً."""
        if not permit.signature_hex:
            raise PermitInvalidError("إذنٌ بلا توقيع. غيرُ الموقَّعِ ليس إذنًا.")
        try:
            self.verifying_key.verify(
                bytes.fromhex(permit.signature_hex), permit.signing_payload()
            )
        except (InvalidSignature, ValueError) as exc:
            raise PermitInvalidError(
                f"توقيعُ الإذنِ «{permit.permit_id}» لا يطابق مضمونَه — "
                "تزويرٌ أو تحريفٌ بعد الإصدار."
            ) from exc
        if permit.is_expired(now):
            raise PermitExpiredError(
                f"انقضى الإذنُ «{permit.permit_id}» في {permit.expires_at}."
            )
        if self.consumed.is_consumed(permit.permit_id):
            raise PermitReplayError(
                f"الإذنُ «{permit.permit_id}» استُهلِك من قبل."
            )

    # ── الإنفاذ ───────────────────────────────────────────────────────────
    def enforce(
        self,
        permit: EnforcementPermit,
        *,
        planner: Callable[[EnforcementPermit], tuple[SovereignEffect, ...]],
        applier: Callable[[SovereignEffect], None],
        now: datetime | None = None,
    ) -> tuple[SovereignEffect, ...]:
        """أنفِذْ تحت إذن: تحقّقٌ ثمّ استهلاكٌ ثمّ فحصُ نطاقٍ ثمّ تطبيق.

        الاستهلاكُ **قبل** التطبيق بقصد: لو استُهلِك بعده لأمكن أن يُطبَّق أثرٌ
        ثمّ يسقط تثبيتُ الاستهلاك، فيُعاد الإذنُ مرّةً أخرى ويُطبَّق الأثرُ
        مرّتين. والخسارةُ في الاتّجاهِ الآخر إذنٌ ضاع — وضياعُ إذنٍ أهونُ من
        أثرٍ مكرّر. وهذا اختيارٌ مُغلَقٌ صراحةً لا سهو.

        وفحصُ النطاقِ يسبق تطبيقَ أوّلِ أثر، كما في عقدِ 1E: `planner` يُخطّط
        و`applier` وحدَه يمسّ الحالة.
        """
        self.verify(permit, now=now)
        self.consumed.consume(permit.permit_id, now=now)

        produced = tuple(planner(permit))
        خارجة = tuple(e for e in produced if not permit.covers(e))
        if خارجة:
            raise PermitScopeError(
                f"الإذنُ «{permit.permit_id}» يأذن بـ"
                + " · ".join(permit.effect_signatures)
                + "، وحاول المُنفِّذُ: "
                + " · ".join(e.signature for e in خارجة)
                + ". لم يُطبَّق شيء."
            )
        for effect in produced:
            applier(effect)
        return produced


__all__ = [
    "CONSUMED_PERMITS_PATH",
    "CONSUMED_PERMITS_PATH_ENV",
    "DEFAULT_PERMIT_TTL_SECONDS",
    "PERMIT_DOMAIN",
    "ConsumedPermitLedger",
    "EnforcementError",
    "EnforcementPermit",
    "PermitExpiredError",
    "PermitInvalidError",
    "PermitReplayError",
    "PermitScopeError",
    "PolicyEnforcementPoint",
    "consumed_permits_path",
    "issue_permit",
    "sign_permit",
]
