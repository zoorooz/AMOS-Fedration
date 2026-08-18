"""الهدف: وصل الخدمات الفدرالية بالبوابة السيادية — تنفيذٌ لا يمرّ بها لا يقع.

النطاق: federal/executive/services — النواة التنفيذية
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-16
تاريخ آخر تعديل: 2026-08-18

الدَّين الذي تُغلقه هذه الوحدة (وُصف في E2.3-A):

    لا ملف واحد تحت `federal/` كان يستورد `core.sovereignty` ولا
    `core.constitutional_engine`. أي أن التاج والدستور مُثبتان باختباراتهما
    **معزولين**، والمسار التشغيلي الحقيقي (بوابة API → منسّق → وكيل → أداة) كان
    يمرّ **بجانبهما** لا بهما. البوابة تقول عن نفسها إنها «المسار الوحيد الذي
    يُنفَّذ من خلاله أي فعل في الدولة»، ولم يكن أحد في الخدمات يسألها.

القرار المعماري: حدٌّ صريح (`SovereignAuthorizer`) + مُنفِّذ حقيقي واحد
(`ConstitutionalAuthorizer`) يستدعي `SovereignGateway.execute` فعلًا. ولا مُنفِّذ
ثانٍ «للتطوير» يسمح بالمرور: غياب النواة السيادية يعني **توقّف التنفيذ**
(`SovereigntyUnavailableError`)، لا تجاوزها. الفشل المغلق (fail-closed) هو الشكل
الوحيد المقبول هنا؛ الفشل المفتوح كان سيجعل الوحدة كلها زينة.

وممنوع في هذا الحدّ — ويحرسه اختبار يفحص توقيع الدوال نفسه — أي معامل
`force` أو `bypass` أو `override` أو ما يشبهها.

ما غيّرته المرحلة 1N (وصلُ الإنفاذ):

    كان `guard` يستدعي `SovereignGateway.execute` مباشرةً بمُنفِّذٍ **مُبهَم**
    (`Callable[[], T]`)، فتمرُّ السلطةُ والإذنُ (1D · 1F · 1J) ولا يمرُّ شيءٌ
    آخر: لا عقدُ آثارٍ مُعلَنة (1E)، ولا ذرّيّةٌ (1H)، ولا خطّةُ تعويضٍ (1I)،
    ولا توجيهُ الأثرِ الخارجيِّ إلى الصادر (1K). أي أنّ البوابةَ كانت تُسأل
    «هل يجوز؟» ولا تُسأل «ماذا سيقع بالضبط؟».

    فأُغلِق `guard` وحُلَّ محلَّه `guard_declared`: المُنادي يُعلِن آثارَه
    ومفتاحَ عمليّتِه ومعوّضاتِه، والتنفيذُ يمرُّ من
    `SovereignExecutionBoundary` وحدَه. والإغلاقُ صريحٌ لا صامت:
    `UndeclaredExecutionError` تُرفَع بنصٍّ يدلُّ على البديل، فلا يبقى مسارُ
    تنفيذٍ ثانٍ يُمرِّر مُنفِّذًا لا يعرفُ الحدُّ ما يفعله.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable

T = TypeVar("T")

#: أسماء معاملات ممنوعة في هذا الحدّ — مطابقة لما تمنعه البوابة السيادية نفسها.
FORBIDDEN_BYPASS_PARAMS = frozenset(
    {"force", "bypass", "skip_check", "unchecked", "override", "no_verify", "unsafe"}
)


class UndeclaredExecutionError(RuntimeError):
    """تنفيذٌ بمُنفِّذٍ مُبهَمٍ لا يعبرُ حدَّ التنفيذِ السياديّ — فلا يقع.

    ليس خطأً تقنيًّا يُعاد المحاولةُ بعده: هو رفضُ الحدِّ أن يأذن لما لا يعرفُ
    آثارَه. البديلُ `guard_declared` لا معامَلُ تجاوزٍ.
    """


class SovereigntyUnavailableError(RuntimeError):
    """النواة السيادية غير قابلة للاستيراد — فلا تنفيذ.

    هذا ليس تحذيرًا يُتجاوَز: إن لم يكن الدستور حاضرًا فلا سلطة تُجيز الفعل،
    والنواة التنفيذية تتوقّف بدلًا من أن تنفّذ بلا إذن.
    """


@dataclass(frozen=True)
class AuthorityEvidence:
    """أثر دستوري لانتقال واحد — يُخزَّن في سجل التدقيق كدليل لا كادّعاء."""

    action: str
    target: str
    decision: str
    authority_layer: str
    decision_kind: str
    request_fingerprint: str
    ledger_entry_hash: str | None
    rules_evaluated: int
    advisory_violations: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "target": self.target,
            "decision": self.decision,
            "authority_layer": self.authority_layer,
            "decision_kind": self.decision_kind,
            "request_fingerprint": self.request_fingerprint,
            "ledger_entry_hash": self.ledger_entry_hash,
            "rules_evaluated": self.rules_evaluated,
            "advisory_violations": list(self.advisory_violations),
        }


@dataclass(frozen=True)
class GuardedResult:
    """نتيجة فعل نُفِّذ عبر حدّ التنفيذ السياديّ، مقرونة بأثره الدستوري.

    `outcome` حصيلةُ الحدّ (`BoundaryOutcome`) كما هي، بلا إعادةِ تسميةٍ ولا
    تلخيصٍ يُخفي مرحلةً لم تُمَرّ. و`is_replay` تُقرأ منها لا تُخترَع هنا:
    الإعادةُ ليست نجاحًا ثانيًا، والمُنادي يجب أن يراها.
    """

    value: Any
    evidence: AuthorityEvidence
    outcome: Any | None = None

    @property
    def is_replay(self) -> bool:
        """هل كانت هذه إعادةً لعمليّةٍ مُثبَّتةٍ سابقًا؟ (سجلّ 1H)"""
        return bool(getattr(self.outcome, "is_replay", False))


class SovereignAuthorizer(Protocol):
    """الحدّ الذي تعتمد عليه النواة التنفيذية.

    `guard_declared` هو مسارُ التنفيذِ الوحيد بعد 1N: الآثارُ تُعلَن قبل وقوعِها،
    فيقدرُ الحدُّ أن يمنعَ ما لم يُعلَن. ولا معامل يعكس هذا الترتيب.
    """

    def guard_declared(
        self,
        action: str,
        target: str,
        *,
        declared_effects: tuple[Any, ...],
        applier: Callable[[Any], Any],
        operation_key: Any,
        compensators: tuple[Any, ...] = (),
        metadata: dict[str, Any] | None = None,
    ) -> GuardedResult: ...

    def review_only(
        self,
        action: str,
        target: str,
        metadata: dict[str, Any] | None = None,
    ) -> AuthorityEvidence: ...


def locate_repo_root(start: Path | None = None) -> Path:
    """إيجاد جذر المستودع بالبحث عن النواة السيادية نفسها لا بعدّ المجلدات.

    عدّ `parents[n]` يكسر بأي نقل للمجلد. البحث عن `core/sovereignty/gateway.py`
    يبقى صحيحًا ما بقيت النواة موجودة، ويسقط صريحًا إن غابت.
    """
    here = (start or Path(__file__).resolve()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "core" / "sovereignty" / "gateway.py").is_file():
            return candidate
    raise SovereigntyUnavailableError(
        "لم يُعثر على النواة السيادية (core/sovereignty/gateway.py) في أي جدّ للمسار: " f"{here}"
    )


class ConstitutionalAuthorizer:
    """المُنفِّذ الحقيقي: يستدعي `SovereignGateway` في `core/` فعلًا.

    الفاعل هو الفرع التنفيذي (`Branch.EXECUTIVE`) — أي **طرف تابع** بمنطق E2.1:
    كل قاعدة دستورية مُلزِمة ومانعة عليه، ولا يملك مسارًا سياديًّا. وهذا مقصود:
    النواة التنفيذية ليست التاج، ولا يجوز أن تتصرّف كأنها هو.
    """

    #: متغيّرُ البيئةِ الذي يُحدِّد موضعَ سجلِّ الذرّيّة (1H) للنواة التنفيذية.
    LEDGER_PATH_ENV = "AMOS_EXECUTIVE_IDEMPOTENCY_LEDGER"

    #: الموضعُ الافتراضيُّ داخلَ `.runtime/` — مُستثنًى من الدفعِ في `.gitignore`.
    DEFAULT_LEDGER_RELPATH = ".runtime/sovereignty/executive_core_idempotency.json"

    def __init__(
        self,
        gateway: Any | None = None,
        *,
        channel: str = "official",
        boundary: Any | None = None,
        idempotency_ledger_path: Any | None = None,
    ) -> None:
        self._channel = channel
        self._gateway = gateway if gateway is not None else self._build_gateway()
        self._ledger_path = idempotency_ledger_path
        self._boundary = boundary

    # ── الاستيراد الحقيقي للنواة السيادية ─────────────────────────────────
    @staticmethod
    def _ensure_core_importable() -> Path:
        root = locate_repo_root()
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        return root

    @classmethod
    def _build_gateway(cls) -> Any:
        cls._ensure_core_importable()
        try:
            from core.sovereignty.gateway import SovereignGateway
        except ImportError as exc:  # النواة موجودة على القرص لكن استيرادها فشل
            raise SovereigntyUnavailableError(
                f"تعذّر استيراد البوابة السيادية، فلا تنفيذ: {exc}"
            ) from exc
        return SovereignGateway()

    @property
    def gateway(self) -> Any:
        return self._gateway

    # ── حدُّ التنفيذِ السياديّ · 1M/1N ────────────────────────────────────
    def _ledger_location(self) -> Path:
        """موضعُ سجلِّ الذرّيّة: صريحٌ ثمّ بيئةٌ ثمّ افتراضٌ داخل المستودع.

        لا يُخترَع مسارٌ مطلقٌ في الشيفرة: الافتراضُ نسبيٌّ لجذرِ المستودع الذي
        يُعثَر عليه بوجودِ النواةِ السيادية نفسِها.
        """
        if self._ledger_path is not None:
            return Path(self._ledger_path)
        from os import environ

        chosen = environ.get(self.LEDGER_PATH_ENV, "").strip()
        if chosen:
            return Path(chosen)
        return locate_repo_root() / self.DEFAULT_LEDGER_RELPATH

    def _build_boundary(self) -> Any:
        """ابنِ حدَّ التنفيذِ حولَ البوابةِ نفسِها — لا بوابةً ثانية.

        غيابُ النواةِ أو تعذّرُ تهيئةِ السجلِّ يعني **توقّفَ التنفيذ**
        (`SovereigntyUnavailableError`) لا تجاوزَ الحدّ.
        """
        self._ensure_core_importable()
        try:
            from core.sovereignty.enforcement import ConsumedPermitLedger
            from core.sovereignty.enforcement_boundary import SovereignExecutionBoundary
            from core.sovereignty.idempotency import IdempotencyLedger
        except ImportError as exc:
            raise SovereigntyUnavailableError(
                f"تعذّر استيراد حدِّ التنفيذِ السياديّ، فلا تنفيذ: {exc}"
            ) from exc
        location = self._ledger_location()
        try:
            location.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise SovereigntyUnavailableError(
                f"تعذّر تهيئةُ موضعِ سجلِّ الذرّيّة «{location}»، فلا تنفيذ: {exc}"
            ) from exc
        # سجلُّ الأذونِ المُستهلَكةِ يُوضَع بجانبِ سجلِّ الذرّيّةِ في موضعِ التشغيل،
        # لا في موضعِه الافتراضيِّ داخلَ الشجرةِ المُتعقَّبة: كتابةُ حالةِ تشغيلٍ
        # في ملفٍّ مُتعقَّبٍ تُلوِّثُ المستودعَ وتُخالفُ بطاقةَ الهويّة.
        return SovereignExecutionBoundary(
            gateway=self._gateway,
            idempotency_ledger=IdempotencyLedger(path=location),
            consumed_permits=ConsumedPermitLedger(
                path=location.parent / "executive_core_consumed_permits.json"
            ),
        )

    @property
    def boundary(self) -> Any:
        """حدُّ التنفيذ — يُبنى عند أول حاجةٍ ويُحفَظ، أو يسقط صريحًا."""
        if self._boundary is None:
            self._boundary = self._build_boundary()
        return self._boundary

    def crown_status(self) -> str:
        """حالة التاج كما تراها البوابة نفسها (`provisioned` / `unprovisioned`)."""
        return str(self._gateway.crown_status())

    def supreme_authority(self) -> str:
        """أعلى سلطة تعرفها البوابة — تُقرأ منها لا تُكتب هنا."""
        return str(
            getattr(self._gateway.supreme_authority, "name", self._gateway.supreme_authority)
        )

    # ── بناء الطلب ────────────────────────────────────────────────────────
    def _request(self, action: str, target: str, metadata: dict[str, Any] | None):
        self._ensure_core_importable()
        from core.constitutional_engine.model import ActionRequest, Branch

        return ActionRequest(
            actor=Branch.EXECUTIVE,
            action=action,
            target=target,
            channel=self._channel,
            metadata=dict(metadata or {}),
        )

    @staticmethod
    def _evidence_from_verdict(action: str, target: str, verdict: Any) -> AuthorityEvidence:
        """أثر من حكم دستوري (مسار المراجعة بلا تنفيذ)."""
        return AuthorityEvidence(
            action=action,
            target=target,
            decision=str(getattr(verdict.decision, "value", verdict.decision)),
            authority_layer=verdict.authority_layer,
            decision_kind=verdict.decision_kind,
            request_fingerprint=verdict.request_fingerprint,
            ledger_entry_hash=verdict.ledger_entry_hash,
            rules_evaluated=verdict.rules_evaluated,
            advisory_violations=tuple(
                getattr(v, "rule_id", str(v)) for v in verdict.advisory_violations
            ),
        )

    @staticmethod
    def _evidence_from_record(action: str, target: str, record: Any) -> AuthorityEvidence:
        """أثر من سجل البوابة نفسه (مسار التنفيذ).

        `ExecutionRecord` هو ما تكتبه البوابة فعلًا، وليس فيه عدد القواعد
        المُقيَّمة — فلا يُخترَع له رقم: يُترك `rules_evaluated = 0` ويُقرأ العدد
        من السجل الدستوري لمن أراده. الاختراع هنا كان سيصبح رقمًا يُقتبَس لاحقًا.
        """
        return AuthorityEvidence(
            action=action,
            target=target,
            decision=str(record.decision),
            authority_layer=record.authority_layer,
            decision_kind=record.decision_kind,
            request_fingerprint=record.fingerprint,
            ledger_entry_hash=record.ledger_entry_hash,
            rules_evaluated=0,
            advisory_violations=tuple(record.advisory_articles),
        )

    # ── المسار الوحيد للتنفيذ · 1N ────────────────────────────────────────
    def guard_declared(
        self,
        action: str,
        target: str,
        *,
        declared_effects: tuple[Any, ...],
        applier: Callable[[Any], Any],
        operation_key: Any,
        compensators: tuple[Any, ...] = (),
        metadata: dict[str, Any] | None = None,
    ) -> GuardedResult:
        """نفِّذْ عبر حدِّ التنفيذِ السياديّ — أو لا تنفُذ.

        الفرقُ عن `guard` المُغلَق ليس شكليًّا: الحدُّ يعرفُ الآثارَ قبلَ وقوعِها،
        فيربطُ عقدًا (1E) وخطّةَ تعويضٍ (1I) ومفتاحَ ذرّيّةٍ (1H)، ويُوجِّهُ الأثرَ
        الخارجيَّ إلى الصادرِ (1K) بلا أن يمسَّه `applier` هنا.

        قيمةُ المُنادي تُلتقَط من `applier` نفسِه — الحدُّ لا يُرجِعُها ولا يجوز
        أن يُرجِعَها: هو يعرفُ الأثرَ لا محتوى العمليّة.

        `SovereigntyViolation` و`RoyalImpersonation` واستثناءاتُ الحدِّ كلُّها
        تُترك ترتفع كما هي: منعٌ دستوريٌّ ليس فشلًا تقنيًّا يُبتلع.
        """
        request = self._request(action, target, metadata)
        captured: list[Any] = []

        def _apply(effect: Any) -> None:
            captured.append(applier(effect))

        outcome = self.boundary.execute(
            request,
            declared_effects=tuple(declared_effects),
            planner=lambda _permit: tuple(declared_effects),
            applier=_apply,
            operation_key=operation_key,
            compensators=tuple(compensators),
        )
        records = self._gateway.records
        if not records:  # pragma: no cover - البوابة تسجّل كل قرار
            raise SovereigntyUnavailableError(
                "صدرَ إذنٌ بلا أثرٍ في سجل البوابة — أثرٌ مفقود يعني تدقيقًا مفقودًا"
            )
        return GuardedResult(
            value=captured[0] if len(captured) == 1 else tuple(captured),
            evidence=self._evidence_from_record(action, target, records[-1]),
            outcome=outcome,
        )

    def guard(
        self,
        action: str,
        target: str,
        executor: Callable[[], T],
        metadata: dict[str, Any] | None = None,
    ) -> GuardedResult:
        """مسارٌ **مُغلَق** منذ 1N — يُرفَع دائمًا ولا يُنفَّذ شيء.

        بقاءُ التوقيعِ مقصود: مُنادٍ قديمٌ يجب أن يرى رفضًا صريحًا يدلُّه على
        البديل، لا `AttributeError` غامضًا ولا — أسوأ — تنفيذًا يمرُّ بجانبِ
        الحدّ. و`executor` لا يُستدعى قطُّ هنا.
        """
        raise UndeclaredExecutionError(
            f"مُنفِّذٌ مُبهَمٌ للفعل «{action}» على «{target}» "
            f"({getattr(executor, '__name__', type(executor).__name__)}) "
            "لا يعبرُ حدَّ التنفيذِ السياديّ: الحدُّ لا يأذنُ لما لا يعرفُ آثارَه. "
            "استعملْ `guard_declared` بآثارٍ مُعلَنةٍ ومفتاحِ عمليّةٍ ومعوّضات. "
            f"(بيانات: {sorted((metadata or {}).keys())})"
        )

    # ── فصل القرار عن الإنفاذ · 1F ────────────────────────────────────────
    def request_permit(
        self,
        action: str,
        target: str,
        declared_effects: tuple[Any, ...],
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        """اطلب إذن إنفاذ موقّعًا بدل أن تُنفّذ بنفسك.

        هذا مخرج النواة التنفيذية من كونها حاكمة ومُنفّذة معًا: تطلب الإذن ولا
        تصنعه، ثم تُسلّمه إلى موضع إنفاذ لا يملك بوابة.
        """
        return self._gateway.decide(
            self._request(action, target, metadata),
            declared_effects=declared_effects,
        )

    def enforcement_point(self, consumed: Any | None = None) -> Any:
        """ابنِ موضع إنفاذ لا يحمل بوابة ولا محرّكًا ولا مفتاح توقيع.

        يُعطى مفتاح التحقّق العامّ وحده، فما يخرج من هنا **لا يستطيع** أن يأذن
        لنفسه — امتناع بنيوي لا وعد سلوكي.
        """
        self._ensure_core_importable()
        from core.sovereignty.enforcement import (
            ConsumedPermitLedger,
            PolicyEnforcementPoint,
        )
        from cryptography.hazmat.primitives.asymmetric import ed25519

        return PolicyEnforcementPoint(
            verifying_key=ed25519.Ed25519PublicKey.from_public_bytes(
                bytes.fromhex(self._gateway.verifying_key_hex)
            ),
            consumed=consumed if consumed is not None else ConsumedPermitLedger(),
        )

    def review_only(
        self,
        action: str,
        target: str,
        metadata: dict[str, Any] | None = None,
    ) -> AuthorityEvidence:
        """حكم دستوري بلا تنفيذ — يُستخدَم لتقييم مهمّة قبل قبولها."""
        verdict = self._gateway.review(self._request(action, target, metadata))
        return self._evidence_from_verdict(action, target, verdict)


# ── مُنشِئاتُ الإعلانِ · وصلٌ لا اختراع ──────────────────────────────────────
#
# النواةُ التنفيذيةُ تحت `federal/` لا تستوردُ `core` وقتَ التحميل (المسارُ يُضاف
# وقتَ التشغيل). فهذه ثلاثُ دوالٍّ **تُمرِّرُ** إلى أنواعِ 1E و1H و1I كما هي، ولا
# تُعيدُ تعريفَ مفهومٍ ولا تُخزِّنُ حالة: لو نُسِخَت الأنواعُ هنا لصار في الدولةِ
# مفهومانِ لـ«الأثر» يفترقان.


def _core_sovereignty(module: str) -> Any:
    """استوردْ وحدةً من النواةِ السيادية بعد ضمانِ وجودِها على المسار."""
    ConstitutionalAuthorizer._ensure_core_importable()
    from importlib import import_module

    try:
        return import_module(f"core.sovereignty.{module}")
    except ImportError as exc:
        raise SovereigntyUnavailableError(
            f"تعذّر استيراد «core.sovereignty.{module}»، فلا إعلانَ أثرٍ ولا تنفيذ: {exc}"
        ) from exc


def declared_effect(kind: str, resource: str, detail: str = "") -> Any:
    """أثرٌ مُعلَنٌ واحد (1E) — `kind` من مفردات `EffectKind` لا نصٌّ حرّ."""
    contract = _core_sovereignty("contract")
    return contract.SovereignEffect(
        kind=contract.EffectKind(kind), resource=resource, detail=detail
    )


def operation_key(scope: str, value: str) -> Any:
    """مفتاحُ ذرّيّةٍ (1H) — نطاقٌ وقيمةٌ، فلا تصادمَ بين الوحدات."""
    return _core_sovereignty("idempotency").IdempotencyKey(scope=scope, value=value)


def compensator(effect_signature: str, apply: Callable[[], None], description: str = "") -> Any:
    """معوّضُ أثرٍ واحد (1I) — مُعلَنٌ قبلَ التنفيذِ لا مُرتجَلٌ بعدَ الفشل."""
    return _core_sovereignty("compensation").Compensator(
        effect_signature=effect_signature, apply=apply, description=description
    )


def get_authorizer() -> ConstitutionalAuthorizer:
    """المُصرِّح الافتراضي للنواة التنفيذية — حقيقي دائمًا أو يسقط صريحًا."""
    return ConstitutionalAuthorizer()
