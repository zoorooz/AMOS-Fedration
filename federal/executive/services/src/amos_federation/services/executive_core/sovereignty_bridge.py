"""الهدف: وصل الخدمات الفدرالية بالبوابة السيادية — تنفيذٌ لا يمرّ بها لا يقع.

النطاق: federal/executive/services — النواة التنفيذية
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-16
تاريخ آخر تعديل: 2026-08-16

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
    """نتيجة فعل نُفِّذ عبر البوابة، مقرونة بأثره الدستوري."""

    value: Any
    evidence: AuthorityEvidence


class SovereignAuthorizer(Protocol):
    """الحدّ الذي تعتمد عليه النواة التنفيذية.

    `guard` تُقيَّم دستوريًّا **قبل** استدعاء `executor`، فإن مُنِعت لم يُستدعَ
    المُنفِّذ إطلاقًا. لا معامل يعكس هذا الترتيب.
    """

    def guard(
        self,
        action: str,
        target: str,
        executor: Callable[[], T],
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

    def __init__(self, gateway: Any | None = None, *, channel: str = "official") -> None:
        self._channel = channel
        self._gateway = gateway if gateway is not None else self._build_gateway()

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

    # ── المسار الوحيد للتنفيذ ─────────────────────────────────────────────
    def guard(
        self,
        action: str,
        target: str,
        executor: Callable[[], T],
        metadata: dict[str, Any] | None = None,
    ) -> GuardedResult:
        """تنفيذ فعل عبر البوابة السيادية، مع إرجاع أثره الدستوري.

        `SovereigntyViolation` و`RoyalImpersonation` تُترك ترتفع كما هي: منع
        دستوري ليس فشلًا تقنيًّا يُبتلع، بل قرار يجب أن يراه المُنادي.
        """
        request = self._request(action, target, metadata)
        value = self._gateway.execute(request, executor)
        records = self._gateway.records
        if not records:  # pragma: no cover - البوابة تسجّل كل تنفيذ
            raise SovereigntyUnavailableError(
                "نُفِّذ فعل بلا أثر في سجل البوابة — أثرٌ مفقود يعني تدقيقًا مفقودًا"
            )
        return GuardedResult(
            value=value,
            evidence=self._evidence_from_record(action, target, records[-1]),
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


def get_authorizer() -> ConstitutionalAuthorizer:
    """المُصرِّح الافتراضي للنواة التنفيذية — حقيقي دائمًا أو يسقط صريحًا."""
    return ConstitutionalAuthorizer()
