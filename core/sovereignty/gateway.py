"""الهدف: البوابة السيادية — المسار الوحيد الذي يُنفَّذ من خلاله أي فعل في الدولة.

المالك: core/sovereignty/ — التاج
تاريخ الإنشاء: 2026-08-16
تاريخ آخر تعديل: 2026-08-16

هذه الوحدة تُغلق الدين الأكبر في E1: كان المحرك يحكم ولا يمنع، لأن لا شيء كان
مُلزَمًا بسؤاله. البوابة تجعل السؤال شرط التنفيذ لا خيارًا مجاورًا له.

قرار معماري ملزم: لا توجد — ولن تُضاف — راية تجاوز، ولا وضع تشخيصي،
ولا متغير بيئة، ولا معامل `force`. تجاوز الفدرالية مخالفة دستورية بحد ذاتها
(المادة العاشرة · 4 · 3)، ويحرس ذلك اختبار يفحص توقيع الدوال نفسه.

تصحيح E2.1 — مساران لا مسار واحد:

كان هنا سطر يقول: «لا استثناء لأي فاعل، ولا للملك»، وكان الكود وفيًّا له:
قاعدة أدنى (R-003-3: موافقة فرعين) كانت تنقض مرسومًا ملكيًّا ثابت التوقيع.
وذلك قلبٌ للترتيب: جعل الدستور والفروع سلطةً **فوق** التاج.

والأصلاح ليس «إن كان ملكًا فمرّر» — ذلك باب خفي مرفوض. بل طبقة سلطة من الدرجة
الأولى (`authority.py`): يُصنّف الطلب أولًا بمعيار تشفيري لا بادّعاء، ثم:

- **مسار سيادي**: مرسوم ثابت التوقيع مقابل مفتاح التاج → يُقيَّم دستوريًّا
  ويُسجَّل بالكامل، ثم **يُنفَّذ**. لا قاعدة تملك منعه.
- **مسار تابع**: فدرالي · ولاية · مؤسسة · وكيل → كل قاعدة ملزِمة ومانعة،
  بلا تغيير ولا تخفيف عمّا كان قبل E2.1.

والفدرالية تبقى حقيقية: كل فعل يمرّ من هنا، وكل فعل يُسجَّل، وكل طرف تابع
مقيّد. ولكنها ليست سلطة أعلى من التاج.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from cryptography.hazmat.primitives.asymmetric import ed25519
from typing import Any, TypeVar

from core.constitutional_engine.engine import ConstitutionalEngine, ConstitutionalViolation
from core.constitutional_engine.model import ActionRequest, Verdict
from core.sovereignty.authority import (
    AuthorityClassification,
    AuthorityLayer,
    DecisionKind,
    RoyalAuthenticityError,
    classify,
)
from core.sovereignty.authority_grants import AuthorityGrantRegistry
from core.sovereignty.contract import (
    ContractBreach,
    ExecutionContract,
    ExecutionOutcome,
    SovereignEffect,
    bind_contract,
)
from core.sovereignty.crown import crown_is_provisioned
from core.sovereignty.fail_closed import (
    ExecutionAttempt,
    ExecutionCompletion,
    IncompleteSovereignTransaction,
    attempt_execution,
    require_audit_anchor,
)
from core.sovereignty.enforcement import (
    DEFAULT_PERMIT_TTL_SECONDS,
    EnforcementPermit,
    issue_permit,
)
from core.sovereignty.decree import DecreeRegistry, RoyalDecree
from core.sovereignty.prerogatives import is_royal_exclusive
from core.sovereignty.security_events import SecurityEventKind, SecurityEventLog

T = TypeVar("T")

# أسماء ممنوعة في معاملات البوابة — تُفحَص آليًا في الاختبارات
FORBIDDEN_BYPASS_PARAMS = frozenset(
    {"force", "bypass", "skip_check", "unchecked", "override", "no_verify", "unsafe"}
)


class GatewayError(Exception):
    """خطأ في البوابة السيادية."""


class SovereigntyViolation(GatewayError):
    """رُفض الفعل لمخالفة دستورية: البوابة لم تُنفّذه.

    لا يُرفع أبدًا لقرار سيادي ثابت التوقيع — ويحرس ذلك اختبار مباشر.
    """

    def __init__(self, verdict: Verdict) -> None:
        self.verdict = verdict
        super().__init__(verdict.explain())


class AuthorityWithdrawn(GatewayError):
    """فاعلٌ تابعٌ يحاول فعلًا سحبَ الملكُ صلاحيتَه فيه (المادة العاشرة · 10 · 1).

    ليس حكمًا دستوريًّا: القاعدةُ لم تُخالَف، بل **زال الاختصاصُ** نفسُه. ولذلك
    لا يُقدَّم كـ`SovereigntyViolation` ولا يمرّ في مسارِ التقييم.
    """

    def __init__(self, grant: Any) -> None:
        self.grant = grant
        super().__init__(
            f"سُحِبت صلاحيةُ «{grant.grantee}» في «{grant.capability}» بالمرسوم "
            f"«{grant.decree_id}» بتاريخ {grant.recorded_at}. "
            "لا تُستعاد إلّا بمرسومٍ ملكيٍّ جديد."
        )


class RoyalImpersonation(GatewayError):
    """رُفض الفعل لأن الادّعاء الملكي لم تثبت أصالته.

    وهذا ليس نقضًا للملك، بل رفضٌ لمن لم يُثبت أنه الملك. والخلط بينهما
    هو ما حذّر منه التوجيه: «لا سلطة فوق الملك» لا تعني «لا توثيق».
    """

    def __init__(self, event_kind: SecurityEventKind, reason: str) -> None:
        self.event_kind = event_kind
        self.reason = reason
        super().__init__(f"[{event_kind.value}] {reason}")


@dataclass(frozen=True, slots=True)
class ExecutionRecord:
    """أثر مرور فعل بالبوابة — تُنفَّذ أو لا تُنفَّذ، والأثر يبقى."""

    fingerprint: str
    action: str
    actor: str
    decision: str
    ledger_entry_hash: str | None
    decree_id: str | None = None
    decision_kind: str = ""
    authority_layer: str = ""
    advisory_articles: tuple[str, ...] = ()
    #: ما جرى عند هذا الأثر: تنفيذٌ مباشرٌ `DIRECT` أم إصدارُ إذنٍ
    #: `PERMIT_ISSUED` بلا مسٍّ للحالة. دونَ هذا الحقل كان السجلُ يقول
    #: «نُفِّذ» عن إصدارِ رخصة — وذلك وصفٌ غيرُ صادقٍ لما جرى.
    enforcement: str = "DIRECT"
    #: حالةُ اكتمالِ المعاملةِ السيادية (1J). الافتراضُ **مُغلَقٌ**: أثرٌ لم
    #: يُصرَّح باكتمالِه لا يُقرأ نجاحًا.
    completion: ExecutionCompletion = ExecutionCompletion.NOT_EXECUTED
    #: سببُ الفشلِ أو تعذُّرِ التصديقِ إن وُجِد — يُقرأ ولا يُخمَّن.
    failure_reason: str = ""

    def __post_init__(self) -> None:
        """حالةُ اكتمالٍ مجهولةُ النوعِ تُرفَض — ولا تُؤوَّل تأويلًا متسامحًا.

        فلو قُبِل نصٌّ حرٌّ مكانَ التعداد لعادت الحالةُ الغامضةُ من البابِ
        الخلفيّ. والرفضُ هنا هو الإغلاقُ عند الفشلِ في مستوى العقد نفسِه.
        """
        if not isinstance(self.completion, ExecutionCompletion):
            raise TypeError(
                "completion يجب أن تكون ExecutionCompletion — وصلت "
                f"{type(self.completion).__name__!r}. لا حالةَ اكتمالٍ حرّةَ الصياغة."
            )

    @property
    def executed(self) -> bool:
        """هل اكتمل تنفيذٌ صحيحٌ فعليٌّ؟ مشتقٌّ من `completion` ولا يُضبَط يدويًّا.

        **تغييرُ دلالةٍ مقصودٌ في 1J (Fail-Closed):** لم يبقَ `executed` حقلًا
        يُكتَب عند البناء، فما دام النجاحُ حقلًا بوليًّا حرًّا يبقى ممكنًا أن
        يُكتَب `executed=True` قبل استدعاءِ المُنفِّذِ — وهو ما كان يجري فعلًا.
        وباشتقاقِه صار النجاحُ الكاذبُ ممتنعًا بنيويًّا: لا سبيلَ إلى
        `executed == True` إلّا بحالةِ `COMPLETED`، ولا تُنتَج تلك الحالةُ إلّا
        بعد عودةِ المُنفِّذِ سالمًا ومعه مرتكزٌ تدقيقيٌّ مُثبَّت.

        فهي تعني اليومَ: تنفيذٌ صحيحٌ اكتمل. ولا تعني — ولم يبقَ لها سبيلٌ أن
        تعني — أن التنفيذَ جُرِّب، أو أن مُنفِّذًا استُدعي، أو أن أثرًا جزئيًّا
        وقع، أو أن حدثًا صدر، أو أن إذنًا وُجِد، أو أن التعويضَ متاح، أو أن
        مرحلةً وسيطةً بُلِغت، أو أن استثناءً ابتُلِع، أو أن راجعةً في الذاكرة
        ضُبِطت.
        """
        return self.completion.certifies_execution

    @property
    def sovereign(self) -> bool:
        return self.decision_kind == DecisionKind.SOVEREIGN_ROYAL.value

    def as_dict(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "action": self.action,
            "actor": self.actor,
            "decision": self.decision,
            "executed": self.executed,
            "completion": self.completion.value,
            "failure_reason": self.failure_reason,
            "ledger_entry_hash": self.ledger_entry_hash,
            "decree_id": self.decree_id,
            "decision_kind": self.decision_kind,
            "authority_layer": self.authority_layer,
            "advisory_articles": list(self.advisory_articles),
            "enforcement": self.enforcement,
        }


class SovereignGateway:
    """البوابة السيادية: تُقيّم دستوريًا، ثم تُنفّذ أو تمنع — بهذا الترتيب دائمًا.

    الترتيب ليس تفصيلًا: `execute` لا تستدعي المُنفِّذ قبل صدور حكم `ALLOW`،
    ولا يوجد فرع في الكود يعكس ذلك.
    """

    def __init__(
        self,
        engine: ConstitutionalEngine | None = None,
        *,
        decree_registry: DecreeRegistry | None = None,
        security_log: SecurityEventLog | None = None,
        grant_registry: AuthorityGrantRegistry | None = None,
    ) -> None:
        self._engine = engine or ConstitutionalEngine()
        self._decrees = decree_registry or DecreeRegistry()
        self._records: list[ExecutionRecord] = []
        self._security = security_log or SecurityEventLog(self._engine.ledger)
        self._grants = grant_registry or AuthorityGrantRegistry()
        self._contracts: list[ExecutionContract] = []
        # مواضعُ الأثرِ في `_records` التي جرت تحتَ عقد. الموضعُ لا البصمة: طلبان
        # متطابقان لهما بصمةٌ واحدة، فالعدُّ بالبصمة يُنقِص عددَ ما بلا عقد.
        self._contracted_positions: set[int] = set()
        # نمطُ الإنفاذِ الجاري: يُكتَب في الأثرِ **عند كتابتِه** لا بتعديلٍ لاحق
        # (القاعدة 22). يُبدَّل داخل `decide` وحدَها ويعود في `finally`.
        self._enforcement_mode: str = "DIRECT"
        # مفتاحُ توقيعِ الأذونات. خاصٌّ باسمِه ولا يُصدَّر في واجهةٍ عامّة:
        # من ملكَه أذِنَ لنفسِه، فحجبُه عن موضعِ الإنفاذِ هو الفصلُ نفسُه.
        # وهو عابرٌ مع العمليّة ولا يُحفَظ — حدٌّ مُعلَنٌ في القسم 30.
        self._permit_key = ed25519.Ed25519PrivateKey.generate()
        self._permits: list[str] = []

    # ── الاستعلام ─────────────────────────────────────────────────────────
    @property
    def engine(self) -> ConstitutionalEngine:
        return self._engine

    @property
    def records(self) -> tuple[ExecutionRecord, ...]:
        return tuple(self._records)

    @property
    def security_log(self) -> SecurityEventLog:
        return self._security

    @property
    def grants(self) -> AuthorityGrantRegistry:
        """سجلُّ منحِ الصلاحياتِ وسحبِها — أثرُ المادة العاشرة · 10 التشغيليّ."""
        return self._grants

    @property
    def contracts(self) -> tuple[ExecutionContract, ...]:
        """عقودُ التنفيذِ المربوطةُ في هذه الجلسة — للتدقيقِ لا للتعديل."""
        return tuple(self._contracts)

    @property
    def supreme_authority(self) -> AuthorityLayer:
        """أعلى سلطة تعرفها البوابة — محسوبة من الطبقات لا مكتوبة يدًا."""
        from core.sovereignty.authority import supreme_layer

        return supreme_layer()

    def crown_status(self) -> str:
        return "provisioned" if crown_is_provisioned() else "unprovisioned"

    # ── التقييم ───────────────────────────────────────────────────────────
    def review(self, request: ActionRequest) -> Verdict:
        """حكم دستوري بلا تنفيذ. يُسجَّل في السجل الدستوري كأي حكم.

        المراجعة ليست نقضًا: لا يترتب على حكمها منع لأي قرار سيادي، وإنما
        تُجيب سائلًا وتورِث أثرًا (المادة العاشرة · 7 · 3).
        """
        try:
            classification = classify(request)
        except RoyalAuthenticityError as exc:
            # ادّعاء ملكي لم تثبت أصالته يُراجَع كطرف تابع — والمراجعة لا تنفّذ شيئًا.
            # ويُسجَّل الحدث: المراجعة لا تنفّذ ولا تنقض، لكنها **لا تُخفي** انتحالًا.
            self._security.record(
                exc.event_kind,
                actor=request.actor.value,
                action=request.action,
                target=request.target or "",
                reason=(
                    f"ادّعاء ملكي لم تثبت أصالته أثناء المراجعة: {exc.reason} "
                    "يُراجَع كطرف تابع، ولا يُنفَّذ شيء."
                ),
            )
            return self._engine.evaluate(request)
        return self._engine.evaluate(
            request,
            sovereign=classification.is_sovereign,
            decision_kind=classification.kind.value,
            authority_layer=classification.layer.name,
        )

    # ── التنفيذ ───────────────────────────────────────────────────────────
    def execute(
        self,
        request: ActionRequest,
        executor: Callable[[], T],
    ) -> T:
        """المسار الوحيد للتنفيذ في الدولة.

        خطوة صفر جديدة (E2.1): **تصنيف السلطة**. ولا يُقرّره الطالب ولا حقلٌ
        في الطلب، بل توقيع Ed25519 مقابل مفتاح التاج المُسجّل. ومنه مساران:

        **أ — مسار سيادي** (ثبت أن الفاعل التاج):
          1. أصالة ثابتة أصلًا (وإلا لما وصل هنا).
          2. مرسوم يمسّ بندًا مُنشئًا للسيادة → حدث أمني حرج **يُسجَّل ولا يمنع**.
          3. تقييم دستوري كامل (26 قاعدة) → المخالفات تُدرَج ملاحظات مُسجَّلة.
          4. استهلاك المرسوم (منع إعادة الاستخدام).
          5. أثر تدخّل سيادي في السجل **قبل** التنفيذ.
          6. تنفيذ. ولا فرع في هذا المسار يرفع `SovereigntyViolation`.

        **ب — مسار تابع** (فدرالي · ولاية · مؤسسة · وكيل): كما كان تمامًا —
        تقييم مُلزِم، والمخالفة تمنع التنفيذ. لم يُخفَّف شيء في هذا المسار.

        **ج — ادّعاء ملكي فاشل**: حدث أمني + `RoyalImpersonation` + **لا تنفيذ**.

        ولا معامل يُغيّر هذا الترتيب، ولا راية تجاوز تنقل طلبًا من مسار لمسار.
        """
        decree = request.royal_decree
        decree_id = getattr(decree, "decree_id", None) if decree is not None else None

        # ── الخطوة 0: من الفاعل؟ بمعيار تشفيري لا بادّعائه ────────────────
        try:
            classification = classify(request)
        except RoyalAuthenticityError as exc:
            self._security.record(
                exc.event_kind,
                actor=request.actor.value,
                action=request.action,
                target=request.target or "",
                reason=str(exc),
                decree_id=decree_id,
            )
            raise RoyalImpersonation(exc.event_kind, str(exc)) from exc

        if classification.is_sovereign:
            return self._execute_sovereign(request, executor, classification)
        return self._execute_subordinate(request, executor, classification)

    # ── عقدُ التنفيذِ السياديّ (1E) ──────────────────────────────
    def execute_under_contract(
        self,
        request: ActionRequest,
        *,
        declared_effects: tuple[SovereignEffect, ...],
        planner: Callable[[ExecutionContract], tuple[SovereignEffect, ...]],
        applier: Callable[[SovereignEffect], None],
        value_of: Callable[[tuple[SovereignEffect, ...]], Any] | None = None,
    ) -> ExecutionOutcome[Any]:
        """نفِّذ بعقدٍ: الأثرُ يُعلَن ثمّ يُحقَّق ثمّ يُطبَّق — بهذا الترتيب.

        الفرقُ عن `execute` ليس زيادةَ تدقيقٍ: `execute` تأذن لـ`executor` حرٍّ
        لا حدَّ له ولا وصفَ، وهذه تحصر المُنفِّذَ في آثارٍ أُعلِنَت قبلَ صدورِ
        الإذن وداخلَ هدفِه:

        1. **حدُّ النطاق:** يُربَط العقدُ قبل أيّ شيء، وأثرٌ على موردٍ خارجَ
           هدفِ الطلب يُرفَع `EffectOutOfScopeError` **ولا يُقيَّم الطلبُ أصلًا**.
        2. **الحكمُ الدستوريّ:** يمرّ من `execute` نفسِها — فلا مُنفِّذٌ موازٍ
           ولا تقييمٌ مكرّرٌ ولا مسارٌ ثانٍ للسيادة (القاعدتان 5 و 6).
        3. **حدُّ العقد:** `planner` يُرجِع الآثارَ ولا يُطبّقُها. وما لم يُعلَن
           يُرفَض `ContractBreach` **قبل استدعاءِ `applier` على أيّ أثر**.
        4. **التطبيق:** `applier` لا يُستدعى إلّا على أثرٍ مشمولٍ بالعقد.

        فالمنعُ **سابقٌ** لا لاحق: المُنفِّذُ لا يملك مسارًا إلى حالةِ الدولةِ
        إلّا عبر `applier` الذي تحرسُه البوابة. وهذا فرقُ «كشفِ التجاوز» عن
        «استحالتِه».

        وعند المخالفة **لا يُعدَّل أثرٌ مُثبَّتٌ ولا يُحذَف** (القاعدة 22): يُكتب
        أثرٌ ثانٍ بقرار `CONTRACT_BREACH` وحدثٌ أمنيٌّ حرجٌ، فيرى المُدقّقُ
        الأمرين معًا: إذنًا صدر، ومحاولةً لتجاوزِه تلته.

        **ما لا تزعمُه هذه الدالة:** لا ذرّيّةَ ولا تراجُع. إن خالف `planner`
        بعد أن طُبّقَ أثرٌ مشروعٌ سابقٌ، فالمشروعُ باقٍ ويظهر في
        `ExecutionOutcome.applied_effects` لا يُخفى. التعويضُ عملُ 1H و 1I.
        """
        contract = bind_contract(
            actor=request.actor.value,
            action=request.action,
            target=request.target,
            declared_effects=declared_effects,
        )
        self._contracts.append(contract)
        applied: list[SovereignEffect] = []

        def _guarded() -> tuple[SovereignEffect, ...]:
            produced = tuple(planner(contract))
            uncovered = contract.uncovered(produced)
            if uncovered:
                raise ContractBreach(contract, uncovered)
            for effect in produced:
                applier(effect)
                applied.append(effect)
            return produced

        try:
            produced = self.execute(request, _guarded)
            self._contracted_positions.add(len(self._records) - 1)
        except ContractBreach as breach:
            self._security.record(
                SecurityEventKind.EXECUTION_CONTRACT_BREACH,
                actor=request.actor.value,
                action=request.action,
                target=request.target or "",
                reason=str(breach),
            )
            self._records.append(
                ExecutionRecord(
                    fingerprint=contract.contract_id,
                    action=request.action,
                    actor=request.actor.value,
                    decision="CONTRACT_BREACH",
                    completion=ExecutionCompletion.NOT_EXECUTED,
                    ledger_entry_hash=None,
                )
            )
            raise

        return ExecutionOutcome(
            contract=contract,
            value=value_of(produced) if value_of is not None else produced,
            applied_effects=tuple(applied),
        )

    # ── موضعُ القرار · PDP (1F) ───────────────────────────────────────────
    @property
    def verifying_key_hex(self) -> str:
        """مفتاحُ التحقّقِ العامّ — يُعطى لموضعِ الإنفاذ، ولا يُعطى سواه.

        ولا نظيرَ له للمفتاحِ الخاصّ: من ملك مفتاحَ التوقيعِ ملك أن يأذن لنفسِه،
        فحجبُه هو الفصلُ نفسُه لا تزيينٌ له.
        """
        return self._permit_key.public_key().public_bytes_raw().hex()

    def decide(
        self,
        request: ActionRequest,
        *,
        declared_effects: tuple[SovereignEffect, ...],
        ttl_seconds: int = DEFAULT_PERMIT_TTL_SECONDS,
    ) -> EnforcementPermit:
        """احكمْ ولا تُنفِّذ: يُرجِع إذنًا موقَّعًا يحمِلُه موضعُ الإنفاذ.

        **لا منطقَ قرارٍ جديدٌ هنا ولا حرفٌ منه مكرَّر:** هذه الدالّةُ تمرُّ من
        `execute` نفسِها، وتُمرِّر مُنفِّذًا لا يمسُّ حالةً بل يلتقط أثرَ الحكم.
        فتباعُدُ قرارِ `decide` عن قرارِ `execute` ممتنعٌ **بنيويًّا لا اتّفاقًا**،
        وهذه حراسةُ القاعدتين 5 و6 بالبناءِ لا بالوصيّة.

        وما يمنع `execute` يمنع `decide`: انتحالُ الملكيّة · الصلاحيّةُ المسحوبة ·
        المخالفةُ الدستوريّة — فلا يُصدَر إذنٌ لممنوع.

        ويُكتب الأثرُ بـ`enforcement="PERMIT_ISSUED"` **عند كتابتِه** لا بتعديلٍ
        لاحقٍ (القاعدة 22)، فلا يقول السجلُّ «نُفِّذ» عن رخصةٍ أُصدِرَت.
        """
        contract = bind_contract(
            actor=request.actor.value,
            action=request.action,
            target=request.target,
            declared_effects=declared_effects,
        )
        صندوق: dict[str, ExecutionRecord] = {}

        def _إصدار() -> None:
            """لا يمسُّ حالةً: يلتقط أثرَ الحكمِ عند لحظةِ صدورِه فحسب."""
            صندوق["record"] = self._records[-1]

        self._enforcement_mode = "PERMIT_ISSUED"
        try:
            self.execute(request, _إصدار)
        finally:
            self._enforcement_mode = "DIRECT"

        record = صندوق["record"]
        permit = issue_permit(
            contract=contract,
            request_fingerprint=record.fingerprint,
            decision=record.decision,
            ledger_entry_hash=record.ledger_entry_hash,
            private_key=self._permit_key,
            authority_layer=record.authority_layer,
            decision_kind=record.decision_kind,
            ttl_seconds=ttl_seconds,
        )
        self._permits.append(permit.permit_id)
        return permit

    # ── قاعدةُ 1J: الختمُ بعد التنفيذِ لا قبلَه ─────────────────────────────
    def _run_and_seal(
        self,
        authorized: ExecutionRecord,
        executor: Callable[[], T],
    ) -> T:
        """نفِّذْ ثمّ اختِمْ أثرًا ثانيًا بحقيقةِ ما جرى — لا ادِّعاءَ سابقًا للفعل.

        هذا هو **موضعُ إنفاذِ** Fail-Closed لا أداةٌ اختياريةٌ بجانبِه: كِلا
        مساري التنفيذِ (السياديُّ والتابع) يمرّان من هنا، فلا نسخةَ ثانيةً
        للقاعدةِ تتباعد عن الأولى.

        والترتيبُ مقصودٌ حرفيًّا:

        1. الأثرُ الأوّلُ (`AUTHORIZED`) مُثبَّتٌ سلفًا: يقول «صدر الإذنُ» ولا
           يقول «نُفِّذ». فلو انقطعت العمليةُ في منتصفِ المُنفِّذِ فأقصى ما في
           السجلِّ إذنٌ صدر — ولا ادِّعاءَ نجاحٍ أبدًا. هذا هو الإغلاقُ
           عند الفشلِ **بالبناء** لا بالحراسة.
        2. تُلتقَط نتيجةُ المُنفِّذِ كما هي (`attempt_execution`).
        3. يُلحَق أثرٌ ثانٍ مختومٌ — ولا يُعدَّل الأوّلُ ولا يُحذَف (القاعدة 22).
        4. إن كان فشلًا أُعيد رفعُ الاستثناءِ نفسِه: لا ابتلاعَ، ولا تحويلَ
           للنجاح، ولا تراجُعَ صامتًا إلى قيمةٍ افتراضية.
        """
        attempt: ExecutionAttempt[T] = attempt_execution(
            executor, audit_anchor=authorized.ledger_entry_hash or ""
        )
        self._records.append(
            replace(
                authorized,
                completion=attempt.completion,
                failure_reason=attempt.failure_reason,
            )
        )
        attempt.raise_if_failed()
        return attempt.value

    # ── أ — المسار السيادي ────────────────────────────────────────────────
    def _execute_sovereign(
        self,
        request: ActionRequest,
        executor: Callable[[], T],
        classification: AuthorityClassification,
    ) -> T:
        """تنفيذ قرار سيادي ثابت الأصالة — لا مخرج من هنا إلا التنفيذ.

        يُقرأ هذا التابع كوثيقة: ليس فيه `raise` واحد مشروط بحكم دستوري،
        ولا شرط يمنع الوصول إلى `executor()`. ولو أُضيف لاحقًا لكشفته الاختبارات
        السلبية وفحص المصدر في `test_supreme_authority.py`.
        """
        decree = request.royal_decree
        decree_id = classification.decree_id

        # مرسوم يمسّ سيادة التاج نفسها: أعلى درجات الإشهار، ولا منع.
        if isinstance(decree, RoyalDecree):
            altered = decree.sovereignty_alterations()
            if altered:
                self._security.record(
                    SecurityEventKind.SOVEREIGNTY_ALTERING_DECREE,
                    actor=request.actor.value,
                    action=request.action,
                    target=", ".join(altered),
                    reason=(
                        "مرسوم ملكي ثابت التوقيع يمسّ بنودًا مُنشئة للسيادة: "
                        f"{', '.join(altered)}. يُنفّذ لأنه قرار التاج، ويُسجَّل "
                        "لأن مسّ السيادة لا يمرّ بلا أثر (المادة العاشرة · 3 · 3)."
                    ),
                    decree_id=decree_id,
                )

        # تقييم دستوري كامل — للإخبار والتدقيق، لا للإجازة.
        verdict = self._engine.evaluate(
            request,
            sovereign=True,
            decision_kind=classification.kind.value,
            authority_layer=classification.layer.name,
        )

        if isinstance(decree, RoyalDecree):
            self._decrees.consume(decree)

        self._security.record(
            SecurityEventKind.SOVEREIGN_INTERVENTION,
            actor=request.actor.value,
            action=request.action,
            target=request.target or "",
            reason=(
                "تدخّل سيادي ملكي بمرسوم ثابت التوقيع. "
                f"ملاحظات دستورية مُسجَّلة غير مانعة: "
                f"{', '.join(verdict.advisory_articles) or 'لا شيء'}. "
                "لا يلزم موافقة فرع ولا ولاية ولا مؤسسة ولا وكيل "
                "(المادة العاشرة · 5 · 3)."
            ),
            decree_id=decree_id,
        )

        authorized = ExecutionRecord(
            fingerprint=verdict.request_fingerprint,
            action=request.action,
            actor=request.actor.value,
            decision=verdict.decision.value,
            completion=ExecutionCompletion.AUTHORIZED,
            enforcement=self._enforcement_mode,
            ledger_entry_hash=verdict.ledger_entry_hash,
            decree_id=decree_id,
            decision_kind=classification.kind.value,
            authority_layer=classification.layer.name,
            advisory_articles=verdict.advisory_articles,
        )
        self._records.append(authorized)
        return self._run_and_seal(authorized, executor)

    # ── ب — المسار التابع ─────────────────────────────────────────────────
    def _execute_subordinate(
        self,
        request: ActionRequest,
        executor: Callable[[], T],
        classification: AuthorityClassification,
    ) -> T:
        """تنفيذ قرار تابع — الدستور ملزِم ومانع، ولم يتخفَّف شيء هنا.

        أُضيفت خطوةٌ سابقةٌ للتقييم (1D): **هل بقي الاختصاصُ أصلًا؟** فإن سحبَ
        الملكُ صلاحيةَ هذا الفاعلِ في هذا الفعلِ فلا معنى لتقييمِ فعلٍ لا يملكه:
        يُرفَض رفضًا مُغلَقًا ويُسجَّل، ولا يُستدعى المُنفِّذ.
        """
        decree = request.royal_decree
        decree_id = getattr(decree, "decree_id", None) if decree is not None else None

        withdrawn = self._grants.latest_for(request.actor.value, request.action)
        if withdrawn is not None and withdrawn.is_withdrawn:
            self._security.record(
                SecurityEventKind.WITHDRAWN_AUTHORITY_USE,
                actor=request.actor.value,
                action=request.action,
                target=request.target or "",
                reason=(
                    f"صلاحيةُ «{withdrawn.capability}» مسحوبةٌ بالمرسوم "
                    f"«{withdrawn.decree_id}». الفعلُ يُمنَع قبل التقييم."
                ),
                decree_id=withdrawn.decree_id,
            )
            self._records.append(
                ExecutionRecord(
                    fingerprint="",
                    action=request.action,
                    actor=request.actor.value,
                    decision="AUTHORITY_WITHDRAWN",
                    completion=ExecutionCompletion.NOT_EXECUTED,
                    ledger_entry_hash=None,
                    decree_id=withdrawn.decree_id,
                    decision_kind=classification.kind.value,
                    authority_layer=classification.layer.name,
                )
            )
            raise AuthorityWithdrawn(withdrawn)

        verdict = self._engine.evaluate(
            request,
            sovereign=False,
            decision_kind=classification.kind.value,
            authority_layer=classification.layer.name,
        )

        if not verdict.allowed:
            self._records.append(
                ExecutionRecord(
                    fingerprint=verdict.request_fingerprint,
                    action=request.action,
                    actor=request.actor.value,
                    decision=verdict.decision.value,
                    completion=ExecutionCompletion.NOT_EXECUTED,
                    ledger_entry_hash=verdict.ledger_entry_hash,
                    decree_id=decree_id,
                    decision_kind=classification.kind.value,
                    authority_layer=classification.layer.name,
                )
            )
            raise SovereigntyViolation(verdict)

        # مرتكزُ الأثرِ التدقيقيِّ إلزاميٌّ في المسارِ التابع: الأثرُ الإلزاميُّ
        # الفاشلُ يُغلِق البوابةَ قبل استدعاءِ المُنفِّذ، ولا يُنفَّذ ما لا يُدقَّق.
        try:
            require_audit_anchor(verdict)
        except IncompleteSovereignTransaction as فشل:
            self._records.append(
                ExecutionRecord(
                    fingerprint=verdict.request_fingerprint,
                    action=request.action,
                    actor=request.actor.value,
                    decision=verdict.decision.value,
                    completion=ExecutionCompletion.NOT_EXECUTED,
                    ledger_entry_hash=verdict.ledger_entry_hash,
                    decree_id=decree_id,
                    decision_kind=classification.kind.value,
                    authority_layer=classification.layer.name,
                    failure_reason=فشل.reason,
                )
            )
            raise

        if isinstance(decree, RoyalDecree) and is_royal_exclusive(request.action):
            self._decrees.consume(decree)

        authorized = ExecutionRecord(
            fingerprint=verdict.request_fingerprint,
            action=request.action,
            actor=request.actor.value,
            decision=verdict.decision.value,
            completion=ExecutionCompletion.AUTHORIZED,
            enforcement=self._enforcement_mode,
            ledger_entry_hash=verdict.ledger_entry_hash,
            decree_id=decree_id,
            decision_kind=classification.kind.value,
            authority_layer=classification.layer.name,
        )
        self._records.append(authorized)
        return self._run_and_seal(authorized, executor)


    # ── حراسة ذاتية ───────────────────────────────────────────────────────
    def self_check(self) -> dict[str, Any]:
        """فحص ذاتي: هل البوابة ما زالت البوابة؟"""
        engine_coverage = self._engine.coverage()
        return {
            "crown": self.crown_status(),
            "articles_guarded": len(engine_coverage),
            "unguarded_articles": list(self._engine.unguarded_articles()),
            "rules": sum(engine_coverage.values()),
            "decrees_consumed": len(self._decrees),
            "records": len(self._records),
            "bypass_parameters": [],
            "supreme_authority": self.supreme_authority.name,
            "security_events": len(self._security.events),
            "sovereign_executions": sum(
                1 for r in self._records if r.sovereign and r.executed
            ),
            # 1J: ما لم يكتمل يُعلَن ولا يُخفى داخل عدّادِ النجاح.
            "failed_executions": sum(
                1
                for r in self._records
                if r.completion is ExecutionCompletion.EXECUTION_FAILED
            ),
            "recovery_required": sum(
                1
                for r in self._records
                if r.completion is ExecutionCompletion.RECOVERY_REQUIRED
            ),
            "active_withdrawals": len(self._grants.active_withdrawals()),
            # الدولةُ اليومَ فيها مسارٌ بعقدٍ ومسارٌ بلا عقد، والثاني يُعلَن ولا يُخفى.
            "contracted_executions": len(self._contracts),
            "permits_issued": len(self._permits),
            "uncontracted_executions": sum(
                1
                for i, r in enumerate(self._records)
                if r.executed and i not in self._contracted_positions
            ),
        }


__all__ = [
    "AuthorityWithdrawn",
    "ExecutionAttempt",
    "ExecutionCompletion",
    "IncompleteSovereignTransaction",
    "ContractBreach",
    "ExecutionContract",
    "ExecutionOutcome",
    "SovereignEffect",
    "ExecutionRecord",
    "GatewayError",
    "RoyalImpersonation",
    "SovereignGateway",
    "SovereigntyViolation",
    "ConstitutionalViolation",
    "FORBIDDEN_BYPASS_PARAMS",
]
