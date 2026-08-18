"""الهدف: أثرٌ تشغيليٌّ للمادة العاشرة · 10 — منحُ الصلاحيةِ وسحبُها بمرسومٍ ملكيّ.

النطاق: `core/sovereignty/` — سجلُّ المنحِ السياديِّ وقراءتُه من البوابة.
المالك: core/sovereignty/ — التاج
تاريخ الإنشاء: 2026-08-18
تاريخ آخر تعديل: 2026-08-18

## الفجوةُ التي تسدُّها هذه الوحدة

المادةُ العاشرة · 10 · 1 تُعطي الملكَ أن «يمنح الصلاحيات ويوسّعها ويقلّصها
ويسحبها». وكان `grant_authority` و`revoke_authority` **سلسلتَي حروفٍ في مجموعةٍ
مجمّدةٍ** في `prerogatives.py` وحدها: قياسًا لا انطباعًا، لم يقرأ أيُّ مكوّنٍ في
`core/sovereignty/` حالةَ منحٍ قائمةً قطُّ. فكان النظامُ يعرف **من يحقُّ له** أن
يمنح، ولا يعرف **ماذا يعني** أنّه منع. أي أنّ الملكَ كان مُختصًّا حصريًّا بفعلٍ
لا تملكه الدولةُ أصلًا — وهذا ما تمنعه القاعدةُ العليا 12: وجودُ الاسمِ ليس
وجودَ القدرة.

## القرارُ المعماريّ

لا محرّكَ تخويلٍ ثانٍ ولا طبقةَ سلطةٍ موازية (القاعدتان 5 و6):

- الطبقاتُ هي `AuthorityLayer` نفسُها، والفاعلونَ `Branch` نفسُه، والإثباتُ
  `AuthorityClassification` نفسُه الصادرُ عن `classify()`. هذه الوحدةُ **لا
  تتحقّق من ملكيّةِ أحدٍ بنفسها** — تطلب تصنيفًا ثابتَ الأصالةِ وترفض غيرَه.
- `state_government_delegations` في R8 تفويضٌ **بين تابعٍ وتابع** (حكومةٌ إلى
  مؤسّسة) داخلَ الطبقةِ الفدراليّة. وهذا سجلٌّ **من التاجِ إلى طبقةٍ تابعة**.
  فلا تكرارَ ولا تنافُس: أحدُهما أفقيٌّ والآخرُ رأسيّ.
- مصدرُ الحقيقةِ **على القرصِ لا في الذاكرة** (القاعدة 17)، بكتابةٍ ذرّيّة.

## ما لهذه الوحدةِ من أثرٍ فعليٍّ اليوم — وما ليس لها

**نافذٌ ومقيس:** السحبُ يمنع. تسحبُ الدولةُ صلاحيةً من فاعلٍ تابعٍ بمرسومٍ ملكيٍّ
ثابتِ التوقيع، فتَرفض البوابةُ فعلَه بعد ذلك رفضًا مُغلَقًا مع حدثٍ أمنيٍّ
مُسجَّل. والمنحُ يُعيدُ ما سُحِب. وكلُّ ذلك يلزمه مرسومٌ جديد.

**غيرُ نافذٍ بصراحة:** المنحُ **لا يفتح قدرةً جديدةً لم تكن للفاعل**، لأنّ الدولةَ
لم تُقِم بعدُ سجلَّ أفعالٍ محكومًا بالقدرات — وذاك عملُ 1E و1F. فالمنحُ اليومَ
استعادةٌ لا توسيع، وهذا مكتوبٌ هنا ولا يُدَّعى غيرُه.

## §10 · 2 — الصلاحيةُ الممنوحةُ لا تنقلب حقًّا سياديًّا

لا حقلَ في `AuthorityGrant` يمنع سحبَها: لا `irrevocable` ولا `permanent` ولا
`protected`. والسحبُ لا يستشيرُ أحدًا ولا يقبل اعتراضًا. والاستثناءُ الوحيدُ الذي
يقرّه النصُّ قيدٌ دستوريٌّ صريحٌ في مادّةٍ مختومة، و`CONSTITUTIONAL_CARVE_OUTS`
**فارغةٌ اليومَ قياسًا لا تقديرًا**: لا مادّةَ مختومةً تُنشئ مجالًا لا يدخله
الملك. ويحرسُ فراغَها اختبارٌ مباشر، فإضافةُ استثناءٍ فعلٌ دستوريٌّ مقصودٌ لا
سهوُ مبرمج.

ولا يُسحَب من التاجِ شيءٌ: محاولةُ ذلك ترفع `RoyalAuthorityErosionError` —
«سحبُ صلاحيةٍ من الملك» سلطةٌ فوق الملك، وهي منقوضةٌ نصًّا (المادة العاشرة · 3).
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from core.sovereignty.authority import (
    AuthorityLayer,
    SovereigntyModelError,
)

if TYPE_CHECKING:  # pragma: no cover
    from core.constitutional_engine.model import Branch
    from core.sovereignty.authority import AuthorityClassification

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
GRANTS_PATH: Final[Path] = REPO_ROOT / "royal" / "authority" / "AUTHORITY_GRANTS.json"

#: الرمزُ الجامع: سحبٌ يشمل كلَّ أفعالِ الفاعل لا فعلًا بعينه.
ALL_CAPABILITIES: Final[str] = "*"

#: قيودٌ دستوريّةٌ صريحةٌ تُنشئ مجالًا لا يدخله الملك (المادة العاشرة · 10 · 2).
#: فارغةٌ **قياسًا**: لا مادّةَ مختومةً تنصُّ على ذلك. لا تُملأ إلا بمرسومٍ ملكيٍّ
#: يُعدّل نصًّا مختومًا، ويحرسُ فراغَها اختبارٌ مباشر.
CONSTITUTIONAL_CARVE_OUTS: Final[frozenset[str]] = frozenset()


class AuthorityGrantError(SovereigntyModelError):
    """خللٌ في منحِ صلاحيةٍ أو سحبِها — لا في تنفيذِ فعلٍ بعينه."""


class NonSovereignGrantError(AuthorityGrantError):
    """محاولةُ منحٍ أو سحبٍ من غيرِ قرارٍ سياديٍّ ثابتِ الأصالة."""


class RoyalAuthorityErosionError(AuthorityGrantError):
    """محاولةُ سحبِ صلاحيةٍ من التاجِ نفسِه — سلطةٌ فوق الملكِ منقوضةٌ نصًّا."""


class GrantState(str, Enum):
    """حالةُ المنح. الحالاتُ ثلاثٌ ولا حالةَ رابعةَ صامتة."""

    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"

    @property
    def arabic(self) -> str:
        return "نافذة" if self is GrantState.ACTIVE else "مسحوبة"


@dataclass(frozen=True, slots=True)
class AuthorityGrant:
    """صلاحيةٌ ممنوحةٌ أو مسحوبةٌ لفاعلٍ تابعٍ بمرسومٍ ملكيٍّ واحد.

    لا حقلَ هنا يمنع السحب. غيابُ الحقلِ مقصودٌ ومحروسٌ باختبارٍ يفحص الحقولَ
    نفسَها: فالضمانةُ بنيويّةٌ لا وعدٌ في وثيقة (المادة العاشرة · 10 · 2).
    """

    grant_id: str
    grantee: str
    layer: str
    capability: str
    state: str
    decree_id: str
    recorded_at: str
    reason: str = ""

    @property
    def is_active(self) -> bool:
        return self.state == GrantState.ACTIVE.value

    @property
    def is_withdrawn(self) -> bool:
        return self.state == GrantState.WITHDRAWN.value

    @property
    def is_blanket(self) -> bool:
        """سحبٌ أو منحٌ جامعٌ يشمل كلَّ أفعالِ الفاعل."""
        return self.capability == ALL_CAPABILITIES

    def as_dict(self) -> dict[str, Any]:
        return {
            "grant_id": self.grant_id,
            "grantee": self.grantee,
            "layer": self.layer,
            "capability": self.capability,
            "state": self.state,
            "decree_id": self.decree_id,
            "recorded_at": self.recorded_at,
            "reason": self.reason,
        }


def _now(moment: datetime | None = None) -> str:
    return (moment or datetime.now(timezone.utc)).replace(microsecond=0).isoformat()


def _normalize(capability: str) -> str:
    """يُوحَّد الفعلُ قبل أيِّ مقارنة: فلا يُفلَت السحبُ بفارقِ حالةِ حرف."""
    cleaned = capability.strip().lower()
    if not cleaned:
        raise AuthorityGrantError("الصلاحيةُ فارغةٌ. السحبُ المُبهَم ليس سحبًا.")
    return cleaned


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


@dataclass(slots=True)
class AuthorityGrantRegistry:
    """سجلُّ المنحِ السياديّ — مصدرُ حقيقةٍ على القرص، وقراءةٌ بلا ذاكرةٍ خفيّة.

    كلُّ استعلامٍ يقرأ الملفَّ: فلا تبقى صلاحيةٌ مسحوبةٌ نافذةً في ذاكرةِ عمليّةٍ
    قديمةٍ بعد أن سحبَها الملك (القاعدة 17).
    """

    path: Path = field(default_factory=lambda: GRANTS_PATH)

    # ── القراءة ───────────────────────────────────────────────────────────
    def entries(self) -> tuple[AuthorityGrant, ...]:
        """كلُّ المداخلِ بترتيبِ تسجيلِها. سجلٌّ غيرُ موجودٍ = لا مداخل."""
        if not self.path.exists():
            return ()
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return tuple(AuthorityGrant(**entry) for entry in raw["grants"])

    def latest_for(self, grantee: str, capability: str) -> AuthorityGrant | None:
        """أحدثُ مدخلٍ يحكم هذا الفعلَ لهذا الفاعل.

        الأخصُّ يسبق: مدخلٌ على الفعلِ بعينه يَحكم قبل المدخلِ الجامع. وبين
        المتساوييْن يَحكم الأحدثُ تسجيلًا — فالمرسومُ اللاحقُ يَنسخ السابق.
        """
        capability = _normalize(capability)
        specific: AuthorityGrant | None = None
        blanket: AuthorityGrant | None = None
        for entry in self.entries():
            if entry.grantee != grantee:
                continue
            if entry.capability == capability:
                specific = entry
            elif entry.is_blanket:
                blanket = entry
        return specific or blanket

    def is_withdrawn(self, grantee: str, capability: str) -> bool:
        """هل سُحِبت هذه الصلاحيةُ من هذا الفاعل؟

        الغيابُ يُقرَأ **عدمَ سحبٍ** لا عدمَ منح: الطبقاتُ التابعةُ تعمل بصلاحيّاتِها
        الدستوريّةِ ما لم يسحبْها الملك. ولو قُرئ الغيابُ منعًا لتوقّفت الدولةُ
        كلُّها عند أوّلِ تشغيل — وذلك تعطيلٌ لا حراسة.
        """
        entry = self.latest_for(grantee, capability)
        return entry is not None and entry.is_withdrawn

    def active_withdrawals(self) -> tuple[AuthorityGrant, ...]:
        """السحوبُ النافذةُ الآن — لكلِّ فاعلٍ وفعلٍ أحدثُ مدخلٍ وحده."""
        seen: dict[tuple[str, str], AuthorityGrant] = {}
        for entry in self.entries():
            seen[(entry.grantee, entry.capability)] = entry
        return tuple(e for e in seen.values() if e.is_withdrawn)

    # ── الكتابة: لا تُقبَل إلّا عن قرارٍ سياديٍّ ثابتِ الأصالة ──────────────
    def withdraw(
        self,
        classification: "AuthorityClassification",
        *,
        grantee: "Branch",
        capability: str = ALL_CAPABILITIES,
        reason: str = "",
        now: datetime | None = None,
    ) -> AuthorityGrant:
        """اسحبْ صلاحيةً بمرسومٍ ملكيّ (المادة العاشرة · 10 · 1).

        السحبُ **لا يُعترَض عليه**: ليس في هذا المسارِ فرعٌ يستشير المسحوبَ منه،
        ولا حقلٌ يُبطِله، ولا استثناءٌ إلّا قيدًا دستوريًّا صريحًا لا وجودَ له.
        """
        return self._record(
            classification,
            grantee=grantee,
            capability=capability,
            state=GrantState.WITHDRAWN,
            reason=reason,
            now=now,
        )

    def grant(
        self,
        classification: "AuthorityClassification",
        *,
        grantee: "Branch",
        capability: str = ALL_CAPABILITIES,
        reason: str = "",
        now: datetime | None = None,
    ) -> AuthorityGrant:
        """امنحْ — أو أعِدْ — صلاحيةً بمرسومٍ ملكيّ.

        اليومَ أثرُه **استعادةُ ما سُحِب** لا فتحُ قدرةٍ جديدة، وهذا مكتوبٌ في
        رأسِ الوحدةِ ولا يُدَّعى غيرُه.
        """
        return self._record(
            classification,
            grantee=grantee,
            capability=capability,
            state=GrantState.ACTIVE,
            reason=reason,
            now=now,
        )

    def _record(
        self,
        classification: "AuthorityClassification",
        *,
        grantee: "Branch",
        capability: str,
        state: GrantState,
        reason: str,
        now: datetime | None,
    ) -> AuthorityGrant:
        from core.constitutional_engine.model import Branch  # استيراد متأخر
        from core.sovereignty.authority import layer_of_actor

        if not classification.is_sovereign or not classification.authenticity_verified:
            raise NonSovereignGrantError(
                "منحُ الصلاحيةِ وسحبُها اختصاصٌ ملكيٌّ حصريّ (المادة العاشرة · 2)، "
                f"والتصنيفُ المُقدَّمُ «{classification.kind.value}» غيرُ سياديٍّ "
                "ثابتِ الأصالة. ولا يُقبَل تصنيفٌ يُكتَب يدًا مكانَ تصنيفٍ يُثبَت."
            )
        if classification.decree_id is None:
            raise NonSovereignGrantError(
                "قرارٌ سياديٌّ بلا رقمِ مرسوم. لا تُسجَّل صلاحيّةٌ بلا سندٍ يُراجَع."
            )
        if not isinstance(grantee, Branch):
            raise AuthorityGrantError(
                f"الممنوحُ من نوع «{type(grantee).__name__}» لا `Branch`. "
                "لا يُقبَل نصٌّ حرٌّ مكانَ فاعلٍ معدود."
            )
        if grantee is Branch.ROYAL or layer_of_actor(grantee) is AuthorityLayer.CROWN:
            raise RoyalAuthorityErosionError(
                f"محاولةُ التصرّفِ في صلاحيةِ «{grantee.value}» بوصفِها ممنوحةً من "
                "الدولة. صلاحيةُ الملكِ أصلٌ لا منحةٌ، وسحبُها سلطةٌ فوقه "
                "(المادة العاشرة · 3)."
            )

        capability = _normalize(capability)
        entries = list(self.entries())
        grant = AuthorityGrant(
            grant_id=f"AG-{len(entries) + 1:04d}",
            grantee=grantee.value,
            layer=layer_of_actor(grantee).name,
            capability=capability,
            state=state.value,
            decree_id=classification.decree_id,
            recorded_at=_now(now),
            reason=reason,
        )
        entries.append(grant)
        _atomic_write(
            self.path,
            {
                "الهدف": "سجلُّ منحِ الصلاحياتِ وسحبِها بمرسومٍ ملكيّ",
                "المرجع": "المادة العاشرة · 10",
                "grants": [e.as_dict() for e in entries],
            },
        )
        return grant


__all__ = [
    "ALL_CAPABILITIES",
    "CONSTITUTIONAL_CARVE_OUTS",
    "GRANTS_PATH",
    "AuthorityGrant",
    "AuthorityGrantError",
    "AuthorityGrantRegistry",
    "GrantState",
    "NonSovereignGrantError",
    "RoyalAuthorityErosionError",
]
