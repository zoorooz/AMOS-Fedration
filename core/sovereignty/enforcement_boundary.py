"""الهدف: حدُّ التنفيذِ السياديّ — فرضُ القدراتِ القائمةِ (1F–1K) على مسارِ التنفيذ.

النطاق: مرحلةُ ربطٍ وإنفاذٍ فقط. لا إعادةَ بناءٍ لأيِّ مرحلةٍ سابقة.
المالك: core/sovereignty/ — التاج
تاريخ الإنشاء: 2026-08-18
تاريخ آخر تعديل: 2026-08-18

# المشكلةُ المقيسة — لا المُفترَضة

كلُّ مسارِ تنفيذٍ في الدولةِ يمرُّ فعلًا من `SovereignGateway.execute`، فالهويّةُ
والسلطةُ (1D) والإغلاقُ عندَ الفشلِ (1J) مفروضانِ. لكنَّ البوابةَ تستقبلُ
`executor: Callable[[], T]` — أي **إغلاقًا مُعتِمًا**. وبعدَ إذنِ السلطةِ يُنادى
هذا الإغلاقُ بلا أيِّ قيد. وقياسًا على المصدرِ لا تخمينًا: `gateway.py` لا
يستوردُ `jurisdiction` ولا `idempotency` ولا `compensation` ولا `outbox`. فالنتيجة:

- **1F** الإذنُ الموقَّع: يُصدَر بـ`decide()` في مسارٍ **موازٍ** لا يلزمُ `execute()`.
- **1G** جدارُ الاختصاص: غيرُ مُستدعًى في مسارِ التنفيذِ أصلًا.
- **1H** الذرّيّة: لا شيءَ يُلزِمُ بمفتاح.
- **1I** التعويض: لا شيءَ يُلزِمُ بربطِ خطّةٍ قبلَ التنفيذ.
- **1K** الصادر: للإغلاقِ المُعتِمِ أن ينادي مزوّدًا خارجيًّا مباشرةً.

وهذا هو ما سمّاه `PROJECT_STATE.md` ثلاثَ مرّاتٍ: «الفرضُ يلزمه حرسٌ ساكن (1M)».

# نقطةُ الفرضِ المُختارة — ولماذا هي هي

لم يُعَد تصميمُ أيِّ مُنفِّذ، ولم يُنقَل ملفٌّ واحد. نقطةُ الفرضِ هي **حدُّ
الإغلاقِ المُعتِم نفسُه**: مَن يعبرُ هذا الحدَّ لا يُسلِّمُ دالّةً حُرّةً تمسُّ
الحالة، بل يُسلِّمُ **خطّةً مُعلَنة**: آثارًا مُعلَنةً، ومُخطِّطًا، ومُطبِّقًا،
ومفتاحَ ذرّيّة. والحدُّ وحدَه يملكُ التوزيع. فالحمايةُ بنيويّةٌ لا سلوكيّة:
المُطبِّقُ الذي يُسلِّمه المُنادي **لا يستقبلُ أثرًا خارجيًّا أبدًا** — لا لأنّه
مُهذَّب، بل لأنّ الحدَّ لا يُمرِّرُه إليه ويُدرجُه في الصادرِ (1K) بدلًا من ذلك.

    Caller → SovereignExecutionBoundary
             → 1G الاختصاص → 1E العقد → 1I خطّةُ التعويض
             → 1D السلطة + 1F الإذن + 1J الإغلاق (عبرَ `gateway.decide`)
             → 1H الذرّيّة → توزيعٌ محروس → 1K الصادرُ للأثرِ الخارجيّ
             → Execution

# ما لا يملكُه هذا الحدّ

لا `force` ولا `bypass` ولا `skip_check` ولا `override`: مُحقَّقٌ بفحصِ التواقيعِ
في `self_check` وباختبارٍ مباشر. ولا يُحوّلُ `DENY` إلى `ALLOW`؛ ولا يملكُ مفتاحَ
توقيعٍ (يملكُ مفتاحَ تحقّقٍ عامًّا فقط)؛ ولا يُعيدُ اختراعَ PDP؛ ولا يبني جدولةً
للصادر؛ ولا يبني استعادةً ولا تعويضًا تشغيليًّا — يفرضُ **ربطَ** الخطّةِ فقط.

# الحرسُ الساكن

الفرضُ الزمنيُّ لا يكفي وحدَه: لغةُ بايثون لا تملكُ عزلَ قدرات، ومَن استوردَ
مُغيِّرَ حالةٍ مباشرةً تجاوزَ كلَّ شيء. لذلك يُضافُ `StaticEnforcementGuard`:
فحصٌ شجريٌّ (AST) على **نطاقٍ مُعلَنٍ منشور** يرفضُ الأنماطَ التي تُنتِجُ
تجاوزًا. والنطاقُ يُعلَن ويُقاس، ولا يُدَّعى أنَّ كلَّ كودِ المشروعِ محروس.
"""

from __future__ import annotations

import ast
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Final

from cryptography.hazmat.primitives.asymmetric import ed25519

from core.constitutional_engine.model import ActionRequest
from core.sovereignty.compensation import (
    CompensationPlan,
    Compensator,
    bind_compensation_plan,
)
from core.sovereignty.contract import (
    EffectKind,
    ExecutionContract,
    SovereignEffect,
    bind_contract,
)
from core.sovereignty.enforcement import (
    ConsumedPermitLedger,
    EnforcementPermit,
    PolicyEnforcementPoint,
)
from core.sovereignty.gateway import FORBIDDEN_BYPASS_PARAMS, SovereignGateway
from core.sovereignty.idempotency import (
    IdempotencyGuard,
    IdempotencyKey,
    IdempotencyLedger,
    OperationResult,
    compute_fingerprint,
)
from core.sovereignty.jurisdiction import (
    JUDICIAL_ACTIONS,
    WALL,
    JudicialAction,
    JurisdictionWall,
)
from core.sovereignty.outbox import (
    EffectPayload,
    ProviderAdapter,
    SovereignOutbox,
    enqueue_write_ahead,
)

# ─────────────────────────────────────────────────────────────────────────────
# الأخطاء — كلُّها رفضٌ صريحٌ يُرفَع، ولا رايةَ منطقيّةً ولا ابتلاع
# ─────────────────────────────────────────────────────────────────────────────


class EnforcementBoundaryError(Exception):
    """أساسُ أخطاءِ حدِّ التنفيذ — الرفضُ يُرفَع ولا يُرجَع قيمةً."""


class JurisdictionNotDeclaredError(EnforcementBoundaryError):
    """فعلٌ قضائيٌّ بلا طلبِ اختصاصٍ مُعلَن — لا عبورَ بلا فحصِ الجدار (1G)."""


class OperationKeyRequiredError(EnforcementBoundaryError):
    """تنفيذٌ بلا مفتاحِ ذرّيّة — الذرّيّةُ (1H) ليست اختياريّة."""


class CompensationNotDeclaredError(EnforcementBoundaryError):
    """أثرٌ مُغيِّرٌ قابلٌ للعكسِ بلا خطّةِ تعويضٍ مربوطة (1I)."""


class MixedEffectContractError(EnforcementBoundaryError):
    """عقدٌ يخلطُ أثرًا خارجيًّا بأثرٍ مُغيِّرٍ داخليّ.

    خطّةُ التعويضِ (1I) ترفضُ العقودَ التي فيها أثرٌ خارجيّ، وترتيبُ الصادرِ (1K)
    لا يُغطّي أثرًا داخليًّا. فالخلطُ يُنتِجُ عقدًا لا يملكُ الحدُّ له ضمانًا،
    والإغلاقُ عندَ الفشلِ يوجبُ الرفضَ قبلَ التنفيذِ لا الادّعاءَ بعدَه.
    """


class OutboxNotConfiguredError(EnforcementBoundaryError):
    """أثرٌ خارجيٌّ مُعلَنٌ وحدُّ التنفيذِ بلا صادرٍ أو مزوّدٍ أو حمولة (1K)."""


class BoundaryConfigurationError(EnforcementBoundaryError):
    """تهيئةُ الحدِّ ناقصةٌ أو غيرُ متّسقة — يُرفَع عندَ البناءِ لا عندَ التنفيذ."""


class StaticGuardError(EnforcementBoundaryError):
    """خللٌ في تشغيلِ الحرسِ الساكنِ نفسِه — لا في المشروعِ المفحوص."""


# ─────────────────────────────────────────────────────────────────────────────
# مراحلُ الحرسِ — مُعلَنةٌ ومُرتَّبة، ويُسجَّلُ ما جرى منها فعلًا
# ─────────────────────────────────────────────────────────────────────────────


class BoundaryStage(Enum):
    """مراحلُ الحرسِ على حدِّ التنفيذ — الترتيبُ مقصودٌ لا عرَضيّ.

    الاختصاصُ أوّلًا لأنّ ما لا يملكُه الفاعلُ أصلًا لا يُتعاقَدُ عليه. والعقدُ
    قبلَ الإذنِ لأنّ الإذنَ يُوقَّعُ على آثارٍ مُعلَنة. والذرّيّةُ تلفُّ التطبيقَ
    لا القرار، فالقرارُ لا يُعادُ بل يُصدَر. والصادرُ آخرًا: لا يُدرَجُ أثرٌ
    خارجيٌّ إلّا بإذنٍ موقَّعٍ سابقٍ وعمليّةٍ محجوزةٍ غيرِ مُثبَّتةِ النجاح.
    """

    JURISDICTION = "JURISDICTION"                # 1G
    CONTRACT = "CONTRACT"                        # 1E
    COMPENSATION_PLAN = "COMPENSATION_PLAN"      # 1I — ربطٌ فقط
    IDENTITY_AUTHORITY = "IDENTITY_AUTHORITY"    # 1D
    FAIL_CLOSED = "FAIL_CLOSED"                  # 1J
    PERMIT = "PERMIT"                            # 1F
    IDEMPOTENCY = "IDEMPOTENCY"                  # 1H
    EXTERNAL_OUTBOX = "EXTERNAL_OUTBOX"          # 1K


#: المراحلُ التي لا يجوزُ لأيِّ تنفيذٍ داخليٍّ مُغيِّرٍ أن يمرَّ بلا واحدةٍ منها.
MANDATORY_INTERNAL_STAGES: Final[tuple[BoundaryStage, ...]] = (
    BoundaryStage.CONTRACT,
    BoundaryStage.COMPENSATION_PLAN,
    BoundaryStage.IDENTITY_AUTHORITY,
    BoundaryStage.FAIL_CLOSED,
    BoundaryStage.PERMIT,
    BoundaryStage.IDEMPOTENCY,
)

#: المراحلُ التي لا يجوزُ لأثرٍ خارجيٍّ أن يمرَّ بلا واحدةٍ منها.
MANDATORY_EXTERNAL_STAGES: Final[tuple[BoundaryStage, ...]] = (
    BoundaryStage.CONTRACT,
    BoundaryStage.IDENTITY_AUTHORITY,
    BoundaryStage.FAIL_CLOSED,
    BoundaryStage.PERMIT,
    BoundaryStage.IDEMPOTENCY,
    BoundaryStage.EXTERNAL_OUTBOX,
)


@dataclass(frozen=True, slots=True)
class BoundaryOutcome:
    """حصيلةُ عبورِ الحدّ — سندٌ للتدقيقِ لا تزيينٌ للنتيجة.

    `stages` تُسجّلُ ما مرَّ فعلًا لا ما كان مُخطَّطًا: الاختبارُ يُثبِتُ سلسلةَ
    الحرسِ منها، والمُدقّقُ يقرأُ أينَ توقّفَ المسارُ المرفوض.
    """

    contract: ExecutionContract
    permit_id: str
    operation_key: str
    applied_effects: tuple[SovereignEffect, ...]
    enqueued_effect_ids: tuple[str, ...]
    stages: tuple[BoundaryStage, ...]
    is_replay: bool
    compensation_plan: CompensationPlan | None = None

    @property
    def applied_signatures(self) -> tuple[str, ...]:
        return tuple(e.signature for e in self.applied_effects)

    def passed(self, stage: BoundaryStage) -> bool:
        return stage in self.stages

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract.contract_id,
            "permit_id": self.permit_id,
            "operation_key": self.operation_key,
            "applied_effects": [e.signature for e in self.applied_effects],
            "enqueued_effect_ids": list(self.enqueued_effect_ids),
            "stages": [s.value for s in self.stages],
            "is_replay": self.is_replay,
            "compensation_bound": self.compensation_plan is not None,
        }


# ─────────────────────────────────────────────────────────────────────────────
# حدُّ التنفيذِ السياديّ
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class SovereignExecutionBoundary:
    """المدخلُ الوحيدُ المحروسُ إلى أثرٍ حقيقيّ — تركيبٌ لا اختراع.

    كلُّ حرسٍ هنا مُستدعًى من مرحلتِه: `bind_contract` من 1E، و`WALL` من 1G،
    و`bind_compensation_plan` من 1I، و`gateway.decide` من 1D/1F/1J،
    و`IdempotencyGuard` من 1H، و`enqueue_write_ahead` من 1K. ولم يُنسَخْ منها
    منطقٌ ولم يُعَدْ بناؤه: نسخُ الحرسِ يُنتِجُ حرسينِ يفترقان.

    **ما لا يملكُه هذا الصنف:** مفتاحَ توقيعٍ (يملكُ التحقّقَ العامَّ من البوابة)،
    ومسارًا يمسُّ الحالةَ من نفسِه (المُطبِّقُ من المُنادي والمزوّدُ من الصادر)،
    ومعامَلَ تجاوزٍ واحدًا.
    """

    gateway: SovereignGateway
    idempotency_ledger: IdempotencyLedger
    outbox: SovereignOutbox | None = None
    wall: JurisdictionWall = field(default_factory=lambda: WALL)
    consumed_permits: ConsumedPermitLedger = field(default_factory=ConsumedPermitLedger)
    _pep: PolicyEnforcementPoint | None = field(default=None, init=False, repr=False)
    _executions: int = field(default=0, init=False, repr=False)
    _rejections: dict[str, int] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.idempotency_ledger, IdempotencyLedger):
            raise BoundaryConfigurationError(
                "حدُّ التنفيذِ بلا سجلِّ ذرّيّةٍ حقيقيّ. الذرّيّةُ (1H) شرطُ عبورٍ "
                "لا خِيار، ولا يُبنى الحدُّ بلا سجلٍّ يحجزُ عليه."
            )
        # مفتاحُ تحقّقٍ عامٌّ من البوابةِ — ولا يُصنَعُ هنا مفتاحُ توقيعٍ أبدًا.
        verifying = ed25519.Ed25519PublicKey.from_public_bytes(
            bytes.fromhex(self.gateway.verifying_key_hex)
        )
        self._pep = PolicyEnforcementPoint(
            verifying_key=verifying, consumed=self.consumed_permits
        )

    # ── الفحصُ الذاتي ──────────────────────────────────────────────────────
    @property
    def policy_enforcement_point(self) -> PolicyEnforcementPoint:
        if self._pep is None:  # pragma: no cover — يُبنى في __post_init__ دائمًا
            raise BoundaryConfigurationError("موضعُ الإنفاذِ لم يُبنَ.")
        return self._pep

    def self_check(self) -> dict[str, object]:
        """تقريرُ حالةِ الحدّ — مُعلَنٌ لا مخفيّ، ومقيسٌ لا مُدَّعًى."""
        return {
            "mandatory_internal_stages": [s.value for s in MANDATORY_INTERNAL_STAGES],
            "mandatory_external_stages": [s.value for s in MANDATORY_EXTERNAL_STAGES],
            "bypass_parameters": sorted(bypass_parameters_of(type(self))),
            "outbox_configured": self.outbox is not None,
            "executions": self._executions,
            "rejections": dict(self._rejections),
            "permits_consumed": self.consumed_permits.count(),
            "signs_permits": False,
            "claims_whole_repository_guarded": False,
        }

    # ── المسارُ المحروس ────────────────────────────────────────────────────
    def execute(
        self,
        request: ActionRequest,
        *,
        declared_effects: tuple[SovereignEffect, ...],
        planner: Callable[[EnforcementPermit], tuple[SovereignEffect, ...]],
        applier: Callable[[SovereignEffect], None],
        operation_key: IdempotencyKey,
        compensators: tuple[Compensator, ...] = (),
        judicial_action: JudicialAction | None = None,
        provider: ProviderAdapter | None = None,
        payload_of: Callable[[SovereignEffect], EffectPayload] | None = None,
        correlation_id: str = "",
    ) -> BoundaryOutcome:
        """اعبُرْ الحدَّ — أو لا تنفُذ. ولا معامَلَ ثالثًا بينَ الاثنين.

        المُنادي لا يُسلِّمُ `Callable[[], T]` حُرّةً كما في `gateway.execute`، بل
        يُسلِّمُ خطّةً مُعلَنة. والفرقُ ليس شكليًّا: الحدُّ يعرفُ ما سيُطبَّقُ قبلَ
        أن يُطبَّق، فيقدرُ أن يمنعَ، وأن يُوجّهَ الأثرَ الخارجيَّ إلى الصادرِ بلا
        أن يمسَّه مُطبِّقُ المُنادي.

        وترتيبُ الرفعِ مقصود: كلُّ فحصٍ يفشلُ يرفعُ استثناءَ مرحلتِه، ولا يُلتقَطُ
        هنا استثناءُ حرسٍ قطُّ — الابتلاعُ هو التجاوزُ بعينِه.
        """
        stages: list[BoundaryStage] = []

        # ① 1G — الاختصاص: ما لا يملكُه الفاعلُ لا يُتعاقَدُ عليه
        stages.extend(self._guard_jurisdiction(request, declared_effects, judicial_action))

        # ② 1E — العقد: آثارٌ مُعلَنةٌ محصورةٌ في الهدف
        contract = self._guard_contract(request, declared_effects)
        stages.append(BoundaryStage.CONTRACT)

        # ③ 1I — خطّةُ التعويض: ربطٌ قبلَ التنفيذ، لا استعادةً بعدَه
        plan, external_effects = self._guard_compensation(contract, compensators)
        if plan is not None:
            stages.append(BoundaryStage.COMPENSATION_PLAN)

        # ④ 1K — تهيئةُ الصادرِ تُفحَصُ قبلَ أيِّ إذنٍ أو حجزٍ أو تطبيق
        if external_effects:
            self._guard_outbox_configured(external_effects, provider, payload_of)

        # ⑤ 1H — المفتاح: يُفحَصُ قبلَ إصدارِ الإذنِ فلا يُصدَرُ إذنٌ بلا حجز
        self._guard_operation_key(operation_key)

        # ⑥ 1D + 1F + 1J — السلطةُ والإذنُ والإغلاق: عبرَ البوابةِ نفسِها
        permit = self.gateway.decide(request, declared_effects=declared_effects)
        stages.extend(
            (
                BoundaryStage.IDENTITY_AUTHORITY,
                BoundaryStage.FAIL_CLOSED,
                BoundaryStage.PERMIT,
            )
        )

        # ⑦ 1H — الذرّيّةُ تلفُّ التطبيق
        enqueued: list[str] = []
        applied_holder: list[tuple[SovereignEffect, ...]] = []

        def _under_permit() -> tuple[str, ...]:
            """ما يُرجَعُ للحارسِ بصماتٌ نصّيّةٌ لا كائنات.

            سجلُّ 1H يُثبِّتُ بصمةَ النتيجةِ بـ`json`، والكائنُ غيرُ القابلِ
            للتمثيلِ يُفشِلُ التثبيت. والبصماتُ هي ما يُقارَنُ عندَ الإعادةِ
            أصلًا، فلا يُفقَدُ شيءٌ بإرجاعِها.
            """
            produced = self.policy_enforcement_point.enforce(
                permit,
                planner=planner,
                applier=self._route_effect(
                    permit=permit,
                    operation_key=operation_key,
                    applier=applier,
                    provider=provider,
                    payload_of=payload_of,
                    correlation_id=correlation_id,
                    enqueued=enqueued,
                ),
            )
            applied_holder.append(produced)
            return tuple(e.signature for e in produced)

        fingerprint = compute_fingerprint(
            scope=operation_key.scope,
            action=request.action,
            target=request.target,
            effect_signatures=tuple(sorted(contract.declared_signatures)),
            actor=request.actor,
        )
        external_prefix = EffectKind.EXTERNAL.value + ":"
        result: OperationResult[tuple[str, ...]] = IdempotencyGuard(
            ledger=self.idempotency_ledger
        ).run_once(
            key=operation_key,
            fingerprint=fingerprint,
            execute=_under_permit,
            extract_effect_signatures=lambda sigs: tuple(sigs or ()),
            detect_external=lambda sigs: any(
                s.startswith(external_prefix) for s in (sigs or ())
            ),
        )
        stages.append(BoundaryStage.IDEMPOTENCY)
        if enqueued:
            stages.append(BoundaryStage.EXTERNAL_OUTBOX)

        applied = applied_holder[0] if applied_holder else ()
        self._executions += 1
        return BoundaryOutcome(
            contract=contract,
            permit_id=permit.permit_id,
            operation_key=operation_key.composite,
            applied_effects=tuple(applied),
            enqueued_effect_ids=tuple(enqueued),
            stages=tuple(stages),
            is_replay=result.is_replay,
            compensation_plan=plan,
        )

    # ── الحرسُ واحدًا واحدًا ───────────────────────────────────────────────
    def _record_rejection(self, stage: BoundaryStage) -> None:
        self._rejections[stage.value] = self._rejections.get(stage.value, 0) + 1

    def _guard_jurisdiction(
        self,
        request: ActionRequest,
        declared_effects: tuple[SovereignEffect, ...],
        judicial_action: JudicialAction | None,
    ) -> tuple[BoundaryStage, ...]:
        """1G: الفعلُ القضائيُّ لا يعبرُ بلا فحصِ الجدار، ولا يحملُ أثرًا تنفيذيًّا.

        والجدارُ يرفعُ استثناءَه، ولا يُلتقَطُ هنا: فقرارُ الجدارِ غيرُ قابلٍ
        للتجاهلِ من المُنادي بنيويًّا، لا بالاتّفاق.
        """
        is_judicial = request.action in JUDICIAL_ACTIONS
        if is_judicial and judicial_action is None:
            self._record_rejection(BoundaryStage.JURISDICTION)
            raise JurisdictionNotDeclaredError(
                f"الفعلُ «{request.action}» قضائيٌّ ولم يُقدَّم له طلبُ اختصاصٍ "
                "مُعلَن. الجدارُ لا يُفحَصُ بالنيّة، ولا يعبرُ فعلٌ قضائيٌّ بلا "
                "نطاقِ محكمةٍ ونطاقِ قضيّةٍ ونطاقِ منصبٍ مُصرَّحٍ بها."
            )
        if judicial_action is None:
            return ()
        self.wall.evaluate(judicial_action)
        for effect in declared_effects:
            self.wall.assert_effect_judicial(effect)
        return (BoundaryStage.JURISDICTION,)

    def _guard_contract(
        self, request: ActionRequest, declared_effects: tuple[SovereignEffect, ...]
    ) -> ExecutionContract:
        """1E: لا تنفيذَ بلا عقدٍ، ولا عقدَ بأثرٍ خارجَ الهدف."""
        return bind_contract(
            actor=request.actor,
            action=request.action,
            target=request.target,
            declared_effects=declared_effects,
        )

    def _guard_compensation(
        self, contract: ExecutionContract, compensators: tuple[Compensator, ...]
    ) -> tuple[CompensationPlan | None, tuple[SovereignEffect, ...]]:
        """1I: ما لا تعرفُ الدولةُ كيفَ تخرجُ منه لا تدخلُه — ربطًا لا استعادة.

        الخلطُ مرفوض: خطّةُ 1I ترفضُ العقدَ الذي فيه أثرٌ خارجيّ، وترتيبُ 1K لا
        يُغطّي أثرًا داخليًّا. فعقدٌ يجمعُهما لا ضمانَ له، والرفضُ قبلَ التنفيذِ
        أصدقُ من ادّعاءٍ بعدَه.
        """
        external = tuple(
            e for e in contract.declared_effects if e.kind is EffectKind.EXTERNAL
        )
        reversible_mutating = tuple(
            e for e in contract.mutating_effects if e.kind is not EffectKind.EXTERNAL
        )
        if external and reversible_mutating:
            self._record_rejection(BoundaryStage.COMPENSATION_PLAN)
            raise MixedEffectContractError(
                "العقدُ يخلطُ أثرًا خارجيًّا ("
                + " · ".join(e.signature for e in external)
                + ") بأثرٍ مُغيِّرٍ داخليّ ("
                + " · ".join(e.signature for e in reversible_mutating)
                + "). لا خطّةَ تعويضٍ لعقدٍ فيه أثرٌ خارجيّ، ولا ترتيبَ صادرٍ "
                "لأثرٍ داخليّ. يُفصَلُ العقدانِ ويُنفَّذُ كلٌّ بضمانِه."
            )
        if not reversible_mutating:
            return None, external
        if not compensators:
            self._record_rejection(BoundaryStage.COMPENSATION_PLAN)
            raise CompensationNotDeclaredError(
                "العقدُ يُعلِنُ أثرًا مُغيِّرًا قابلًا للعكسِ ("
                + " · ".join(e.signature for e in reversible_mutating)
                + ") ولا خطّةَ تعويضٍ مربوطة. الدولةُ لا تدخلُ فعلًا لا تعرفُ "
                "كيفَ تخرجُ منه."
            )
        # النقصُ في التغطيةِ يرفعه 1I نفسُه — ولا يُعادُ فحصُه هنا.
        return bind_compensation_plan(contract=contract, compensators=compensators), external

    def _guard_outbox_configured(
        self,
        external_effects: tuple[SovereignEffect, ...],
        provider: ProviderAdapter | None,
        payload_of: Callable[[SovereignEffect], EffectPayload] | None,
    ) -> None:
        """1K: الأثرُ الخارجيُّ بلا صادرٍ لا يُنفَّذُ — ولا يُنادى مزوّدٌ مباشرةً."""
        ناقص = [
            اسم
            for اسم, قيمة in (
                ("outbox", self.outbox),
                ("provider", provider),
                ("payload_of", payload_of),
            )
            if قيمة is None
        ]
        if ناقص:
            self._record_rejection(BoundaryStage.EXTERNAL_OUTBOX)
            raise OutboxNotConfiguredError(
                "العقدُ يُعلِنُ أثرًا خارجيًّا ("
                + " · ".join(e.signature for e in external_effects)
                + ") وحدُّ التنفيذِ ينقصُه: "
                + " · ".join(ناقص)
                + ". الأثرُ الخارجيُّ مسارُه الصادرُ (1K) وحدَه، ولا يُسلَّمُ إلى "
                "مُطبِّقِ المُنادي بحالٍ."
            )

    def _guard_operation_key(self, operation_key: Any) -> None:
        """1H: لا عبورَ بلا مفتاحِ ذرّيّةٍ حقيقيّ — ولا يُصطنَعُ مفتاحٌ هنا.

        اصطناعُ مفتاحٍ داخلَ الحدِّ يُبطِلُ الذرّيّةَ من حيثُ يبدو أنّه يحفظُها:
        مفتاحٌ مُشتَقٌّ من الطلبِ يتغيّرُ بتغيُّرِ حمولةٍ لا تُغيِّرُ العمليّةَ،
        فتُنفَّذُ مرّتين. فالمفتاحُ من المُنادي، ونقصُه رفضٌ.
        """
        if not isinstance(operation_key, IdempotencyKey):
            self._record_rejection(BoundaryStage.IDEMPOTENCY)
            raise OperationKeyRequiredError(
                "تنفيذٌ بلا مفتاحِ ذرّيّةٍ (`IdempotencyKey`). الذرّيّةُ (1H) شرطُ "
                "عبورٍ لا خِيار، والحدُّ لا يصطنعُ مفتاحًا نيابةً عن المُنادي."
            )

    def _route_effect(
        self,
        *,
        permit: EnforcementPermit,
        operation_key: IdempotencyKey,
        applier: Callable[[SovereignEffect], None],
        provider: ProviderAdapter | None,
        payload_of: Callable[[SovereignEffect], EffectPayload] | None,
        correlation_id: str,
        enqueued: list[str],
    ) -> Callable[[SovereignEffect], None]:
        """التوزيعُ المحروس — هنا يصيرُ المنعُ بنيويًّا لا سلوكيًّا.

        مُطبِّقُ المُنادي **لا يُنادى قطُّ** على أثرٍ خارجيّ: لا فحصًا بعدَه ولا
        تحذيرًا، بل لا يُمرَّرُ إليه. والأثرُ الخارجيُّ يُدرَجُ في الصادرِ قبلَ
        تثبيتِ نجاحِ العمليّة (`enqueue_write_ahead`)، فالترتيبُ مفروضٌ من 1K.
        """

        def route(effect: SovereignEffect) -> None:
            if effect.kind is not EffectKind.EXTERNAL:
                applier(effect)
                return
            if self.outbox is None or provider is None or payload_of is None:
                # لا يُبلَغُ هذا الموضعُ عبرَ `execute` — الفحصُ سابقٌ للإذن.
                # ويبقى مغلقًا لأنّ التوزيعَ قد يُستدعى من مسارٍ آخرَ لاحقًا.
                self._record_rejection(BoundaryStage.EXTERNAL_OUTBOX)
                raise OutboxNotConfiguredError(
                    f"الأثرُ الخارجيُّ «{effect.signature}» بلا صادرٍ مُهيَّأ. "
                    "لا تسليمَ مباشرًا إلى مزوّدٍ بحال."
                )
            record = enqueue_write_ahead(
                outbox=self.outbox,
                idempotency_ledger=self.idempotency_ledger,
                key=operation_key,
                permit=permit,
                effect=effect,
                provider=provider,
                payload=payload_of(effect),
                correlation_id=correlation_id,
            )
            enqueued.append(record.effect_id)

        return route


# ─────────────────────────────────────────────────────────────────────────────
# الحرسُ الساكن — الفرضُ المعماريُّ على المصدرِ لا على النيّة
# ─────────────────────────────────────────────────────────────────────────────


def bypass_parameters_of(subject: object) -> frozenset[str]:
    """معامَلاتُ التجاوزِ في صنفٍ أو دالّة — تُقاسُ بالتوقيعِ لا تُدَّعى.

    تُستعمَلُ في `self_check` وفي الاختبارِ معًا: الإقرارُ والقياسُ من مصدرٍ
    واحدٍ فلا يفترقان.
    """
    import inspect

    found: set[str] = set()
    members: Iterable[tuple[str, Any]]
    if isinstance(subject, type):
        members = inspect.getmembers(subject, callable)
    elif callable(subject):
        members = [(getattr(subject, "__name__", "<callable>"), subject)]
    else:
        raise StaticGuardError("يُفحَصُ صنفٌ أو دالّة، لا قيمةٌ أخرى.")
    for name, member in members:
        if isinstance(member, type):
            # `__class__` وما شابهَه صنفٌ لا دالّةَ نفاذٍ؛ لا بصمةَ تجاوزٍ فيه.
            continue
        try:
            signature = inspect.signature(member)
        except (TypeError, ValueError) as سبب:
            # لا ابتلاعَ صامتًا: ما لا تُقرَأُ بصمتُه لا يُدَّعى خلوُّه من التجاوز.
            raise StaticGuardError(
                f"لم تُقرَأ بصمةُ «{name}» فلا يُقرَّرُ خلوُّها من معاملِ تجاوز."
            ) from سبب
        found |= {p for p in signature.parameters if p in FORBIDDEN_BYPASS_PARAMS}
    return frozenset(found)


#: النطاقُ المحروسُ افتراضًا — مُعلَنٌ ومنشور. وما خرجَ عنه **غيرُ محروس**،
#: ولا يُدَّعى خلافُ ذلك.
DEFAULT_GUARDED_SCOPE: Final[tuple[str, ...]] = ("core/sovereignty",)

#: الوحداتُ التي **تُعرِّفُ** الأوّليّاتَ فيُسمَحُ لها بما يُمنَعُ على غيرِها.
#: الإعفاءُ مُعلَنٌ لا مخفيّ: مَن يُعرِّفُ الصادرَ يملكُ نداءَ المزوّد.
DEFINING_MODULES: Final[Mapping[str, frozenset[str]]] = {
    "R2_DIRECT_PROVIDER_DELIVER": frozenset({"core/sovereignty/outbox.py"}),
    "R3_UNGUARDED_SUCCESS_CLAIM": frozenset({"core/sovereignty/idempotency.py"}),
}

#: أسماءُ استثناءاتِ الحرسِ التي يُعَدُّ ابتلاعُها تجاوزًا صريحًا.
GUARD_EXCEPTION_NAMES: Final[frozenset[str]] = frozenset(
    {
        "CompensationError",
        "CompensationScopeError",
        "ContractBreach",
        "ContractError",
        "EnforcementBoundaryError",
        "EnforcementError",
        "FailClosedError",
        "IdempotencyError",
        "IncompleteSovereignTransaction",
        "JurisdictionError",
        "OutboxError",
        "PermitExpiredError",
        "PermitInvalidError",
        "PermitReplayError",
        "PermitScopeError",
        "SovereigntyViolation",
    }
)

#: طرائقُ **ادّعاءِ النجاح** على سجلِّ الذرّيّة. وهذا هو موضعُ الخطرِ بالتحديد:
#: مَن ثبَّتَ «نجَحَت» خارجَ الحارسِ أبطلَ الذرّيّةَ، لأنَّ العمليّةَ تُقرَأُ بعدَ
#: ذلك منتهيةً فلا تُعادُ ولا تُستعادُ.
#:
#: **قرارٌ مُعلَنٌ لا إعفاءٌ صامت:** أوّلُ صياغةٍ لهذه القاعدةِ رصدَت كلَّ مسٍّ
#: للسجلّ، فأشارت إلى `compensation.py:789`. وقُرِئَ الموضعُ: هو تخفيضُ حالةٍ من
#: `RECOVERY_REQUIRED` إلى `FAILED_RETRYABLE` بعدَ تعويضٍ ناجحٍ ثمَّ رفعُ استثناء
#: — أي نقيضُ التجاوز. فلم يُعفَ الملفُّ (الإعفاءُ يُعمي القاعدةَ عن مسٍّ لاحقٍ
#: فيه)، بل صُوِّبَت القاعدةُ إلى ما تقصدُه فعلًا: ادّعاءُ النجاح.
SUCCESS_CLAIM_METHODS: Final[frozenset[str]] = frozenset({"mark_succeeded"})

#: الحالةُ التي يُعَدُّ الانتقالُ إليها خارجَ الحارسِ ادّعاءَ نجاح.
TERMINAL_SUCCESS_STATUS: Final[str] = "SUCCEEDED"


@dataclass(frozen=True, slots=True)
class StaticFinding:
    """مخالفةٌ ساكنةٌ واحدة — موضعٌ وقاعدةٌ وسبب، لا تقديرَ ولا تلميح."""

    rule: str
    path: str
    line: int
    detail: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line} [{self.rule}] {self.detail}"


@dataclass(frozen=True, slots=True)
class StaticEnforcementGuard:
    """الحرسُ الساكن: يفحصُ شجرةَ المصدرِ فيرفضُ أنماطَ التجاوزِ قبلَ تشغيلِها.

    وأربعُ قواعدَ لها أسنانٌ حقيقيّة:

    - `R1_BYPASS_PARAM`: دالّةٌ في النطاقِ تُعلِنُ معامَلَ تجاوزٍ
      (`force` · `bypass` · `skip_check` · `override` …). المعامَلُ الذي لا يوجدُ
      لا يُستعمَل.
    - `R2_DIRECT_PROVIDER_DELIVER`: نداءُ `.deliver(...)` خارجَ وحدةِ الصادر —
      أي تسليمٌ خارجيٌّ لا يمرُّ من 1K.
    - `R3_UNGUARDED_SUCCESS_CLAIM`: تثبيتُ «نجَحَت» على سجلِّ الذرّيّةِ خارجَ 1H —
      إبطالٌ للذرّيّةِ من حيثُ يبدو تسجيلًا بريئًا.
    - `R4_SWALLOWED_GUARD`: `except` لاستثناءِ حرسٍ جسمُه `pass`/`...` — ابتلاعُ
      الرفضِ هو التجاوزُ بعينِه، وأخطرُه أنّه يبدو نجاحًا.

    **حدُّ هذا الحرسِ مُعلَن:** يفحصُ النطاقَ المُصرَّحَ به في `scope` فقط. ولا
    يُدَّعى أنَّ كلَّ كودِ المشروعِ محروسٌ لمجرّدِ خلوِّ هذا الفحص. ولا يفحصُ
    نداءً غيرَ مباشرٍ (`getattr`) ولا تركيبًا زمنيًّا: الفحصُ الساكنُ ساكنٌ.
    """

    scope: tuple[str, ...] = DEFAULT_GUARDED_SCOPE
    include_tests: bool = False

    def files(self, root: Path) -> tuple[Path, ...]:
        """ملفّاتُ النطاقِ — مُرتَّبةٌ ليكونَ التقريرُ حاسمَ الترتيب."""
        found: list[Path] = []
        for حزمة in self.scope:
            base = root / حزمة
            if not base.exists():
                raise StaticGuardError(
                    f"النطاقُ المُصرَّحُ «{حزمة}» غيرُ موجودٍ تحتَ «{root}». "
                    "الحرسُ الذي يفحصُ فراغًا يُنتِجُ خلوًّا كاذبًا."
                )
            found.extend(p for p in base.rglob("*.py") if "__pycache__" not in p.parts)
        if not found:
            raise StaticGuardError("النطاقُ المُصرَّحُ بلا ملفّاتِ بايثون.")
        return tuple(sorted(found))

    def scan(self, root: Path) -> tuple[StaticFinding, ...]:
        """افحصْ النطاقَ وأعِدْ كلَّ مخالفة. الخلوُّ = تسلسلٌ فارغٌ لا `None`."""
        findings: list[StaticFinding] = []
        for path in self.files(root):
            rel = path.relative_to(root).as_posix()
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            findings.extend(self._scan_tree(tree, rel))
        return tuple(findings)

    # ── القواعد ───────────────────────────────────────────────────────────
    def _scan_tree(self, tree: ast.AST, rel: str) -> list[StaticFinding]:
        findings: list[StaticFinding] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                findings.extend(self._rule_bypass_param(node, rel))
            elif isinstance(node, ast.Call):
                findings.extend(self._rule_direct_calls(node, rel))
            elif isinstance(node, ast.ExceptHandler):
                findings.extend(self._rule_swallowed_guard(node, rel))
        return findings

    def _rule_bypass_param(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef, rel: str
    ) -> list[StaticFinding]:
        args = node.args
        names = [
            a.arg
            for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)
            if a.arg in FORBIDDEN_BYPASS_PARAMS
        ]
        return [
            StaticFinding(
                rule="R1_BYPASS_PARAM",
                path=rel,
                line=node.lineno,
                detail=(
                    f"الدالّةُ «{node.name}» تُعلِنُ معامَلَ تجاوزٍ «{name}». "
                    "المعامَلُ الذي لا يوجدُ لا يُستعمَل."
                ),
            )
            for name in names
        ]

    def _rule_direct_calls(self, node: ast.Call, rel: str) -> list[StaticFinding]:
        func = node.func
        if not isinstance(func, ast.Attribute):
            return []
        name = func.attr
        if name == "deliver" and not self._exempt("R2_DIRECT_PROVIDER_DELIVER", rel):
            return [
                StaticFinding(
                    rule="R2_DIRECT_PROVIDER_DELIVER",
                    path=rel,
                    line=node.lineno,
                    detail=(
                        "نداءُ `.deliver(...)` خارجَ وحدةِ الصادر. الأثرُ الخارجيُّ "
                        "مسارُه الصادرُ (1K) وحدَه."
                    ),
                )
            ]
        if self._claims_success(name, node) and not self._exempt(
            "R3_UNGUARDED_SUCCESS_CLAIM", rel
        ):
            return [
                StaticFinding(
                    rule="R3_UNGUARDED_SUCCESS_CLAIM",
                    path=rel,
                    line=node.lineno,
                    detail=(
                        f"ادّعاءُ نجاحِ عمليّةٍ بـ`.{name}(...)` خارجَ وحدةِ 1H. "
                        "مَن ثبَّتَ النجاحَ بلا حارسٍ أبطلَ الذرّيّة: تُقرَأُ "
                        "العمليّةُ منتهيةً فلا تُعادُ ولا تُستعادُ."
                    ),
                )
            ]
        return []

    @staticmethod
    def _claims_success(name: str, node: ast.Call) -> bool:
        """هل هذا النداءُ يُثبِّتُ «نجَحَت»؟ قياسٌ على النصِّ لا على الاسمِ وحدَه."""
        if name in SUCCESS_CLAIM_METHODS:
            return True
        if name != "transition":
            return False
        for kw in node.keywords:
            if kw.arg != "new_status":
                continue
            value = kw.value
            if isinstance(value, ast.Attribute) and value.attr == TERMINAL_SUCCESS_STATUS:
                return True
        return False

    def _rule_swallowed_guard(self, node: ast.ExceptHandler, rel: str) -> list[StaticFinding]:
        swallowed = all(
            isinstance(stmt, ast.Pass)
            or (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant))
            for stmt in node.body
        )
        if not swallowed:
            return []
        caught = self._caught_names(node.type)
        guard_names = sorted(caught & GUARD_EXCEPTION_NAMES)
        if not guard_names:
            return []
        return [
            StaticFinding(
                rule="R4_SWALLOWED_GUARD",
                path=rel,
                line=node.lineno,
                detail=(
                    "ابتلاعُ استثناءِ حرسٍ (" + " · ".join(guard_names) + ") بجسمٍ "
                    "فارغ. الرفضُ المُبتلَعُ يبدو نجاحًا، وهو التجاوزُ بعينِه."
                ),
            )
        ]

    @staticmethod
    def _caught_names(node: ast.expr | None) -> frozenset[str]:
        if node is None:
            return frozenset()
        parts: Sequence[ast.expr]
        parts = node.elts if isinstance(node, ast.Tuple) else [node]
        names: set[str] = set()
        for part in parts:
            if isinstance(part, ast.Name):
                names.add(part.id)
            elif isinstance(part, ast.Attribute):
                names.add(part.attr)
        return frozenset(names)

    def _exempt(self, rule: str, rel: str) -> bool:
        return rel in DEFINING_MODULES.get(rule, frozenset())

    # ── التقرير ───────────────────────────────────────────────────────────
    def self_check(self, root: Path) -> dict[str, object]:
        """تقريرُ الحرسِ الساكن — يُعلِنُ نطاقَه وإعفاءاتِه وحدودَه."""
        findings = self.scan(root)
        return {
            "guarded_scope": list(self.scope),
            "files_scanned": len(self.files(root)),
            "rules": [
                "R1_BYPASS_PARAM",
                "R2_DIRECT_PROVIDER_DELIVER",
                "R3_UNGUARDED_SUCCESS_CLAIM",
                "R4_SWALLOWED_GUARD",
            ],
            "declared_exemptions": {k: sorted(v) for k, v in DEFINING_MODULES.items()},
            "findings": [str(f) for f in findings],
            "clean": not findings,
            "claims_whole_repository_guarded": False,
            "detects_indirect_calls": False,
        }


__all__ = [
    "DEFAULT_GUARDED_SCOPE",
    "DEFINING_MODULES",
    "GUARD_EXCEPTION_NAMES",
    "MANDATORY_EXTERNAL_STAGES",
    "MANDATORY_INTERNAL_STAGES",
    "SUCCESS_CLAIM_METHODS",
    "TERMINAL_SUCCESS_STATUS",
    "BoundaryConfigurationError",
    "BoundaryOutcome",
    "BoundaryStage",
    "CompensationNotDeclaredError",
    "EnforcementBoundaryError",
    "JurisdictionNotDeclaredError",
    "MixedEffectContractError",
    "OperationKeyRequiredError",
    "OutboxNotConfiguredError",
    "SovereignExecutionBoundary",
    "StaticEnforcementGuard",
    "StaticFinding",
    "StaticGuardError",
    "bypass_parameters_of",
]
