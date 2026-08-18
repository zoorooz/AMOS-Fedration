"""الهدف: بوابات الطبقات التابعة — كل طبقة لها بوابتها المُثبَّتة على طبقتها.

المالك: core/sovereignty/ — التاج
تاريخ الإنشاء: 2026-08-16
تاريخ آخر تعديل: 2026-08-18

قبل E2.1 كانت التبعية ضمنية: بوابة واحدة، والفاعل حقلٌ في الطلب. والضمني لا
يُختبَر. هذه الوحدة تجعل التبعية **صريحة ومُثبَّتة**: بوابة الولاية ولاية، ولا
تصير تاجًا بأي معامل ولا بأي حقل ولا بأي وراثة.

وثلاثة قيود تحرسها اختبارات مباشرة:

1. **لا ترقّي**: بوابة تابعة ترفض أي طلب يُقدَّم بطبقة أعلى من طبقتها.
2. **لا نقض**: لا تملك بوابة تابعة منع قرار سيادي — ليس فيها مسار إلى ذلك أصلًا.
3. **لا تخفيف**: القيود الدستورية على الطبقة التابعة كما هي قبل E2.1 تمامًا.

والفدرالية بهذا تبقى حقيقية لا شكلية: الطبقات التابعة مقيَّدة فعلًا، وكل فعل
يمرّ من البوابة، وكل فعل يُسجَّل. وهي مع ذلك ليست سلطة فوق التاج.

ما غيّرته المرحلة 1N (وصلُ الإنفاذ):

    كانت هذه الوحدة تقول عن نفسها إنّ «كلَّ تنفيذٍ يمرُّ من
    `SovereignGateway.execute` نفسِها فلا مسارَ تنفيذٍ ثانٍ». والقولُ كان صحيحًا
    في السلطةِ (1D) والإذنِ (1F) والإغلاقِ عندَ الفشل (1J)، وناقصًا في ما بعدَها:
    مُنفِّذٌ مُبهَمٌ (`Callable[[], T]`) لا يُعلِن أثرًا، فلا عقدَ (1E) يُقاسُ
    عليه، ولا ذرّيّةَ (1H) تمنعُ تكرارَه، ولا خطّةَ تعويضٍ (1I) تُخرِج الدولةَ
    منه، ولا توجيهَ أثرٍ خارجيٍّ إلى الصادر (1K).

    فصارَ `execute_declared` هو مسارَ التنفيذ، ويمرُّ من
    `SovereignExecutionBoundary` وحدَه — والحدُّ نفسُه يمرُّ من البوابةِ
    (`gateway.decide` → `gateway.execute`)، فلا مسارَ ثانيًا أُنشِئ ولا حرسٌ
    نُسِخ. و`execute` القديمةُ **أُغلِقَت** برفعٍ صريح، والتوقيعُ باقٍ ليرى
    المُنادي القديمُ رفضًا يدلُّه على البديل لا تنفيذًا يمرُّ بجانبِ الحدّ.

    وحدُّ التنفيذِ **يُحقَن ولا يُبنى هنا**: سجلُّ الذرّيّة موضعٌ على القرص،
    وموضعُه قرارُ نشرٍ لا افتراضُ مكتبة. فبوابةٌ تابعةٌ بلا حدٍّ محقونٍ لا تُنفِّذ
    (`BoundaryNotConfiguredError`) — إغلاقٌ لا تجاوز.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypeVar

from core.constitutional_engine.model import ActionRequest, Verdict
from core.sovereignty.authority import (
    AuthorityLayer,
    SovereigntyModelError,
    layer_of_actor,
)
from core.sovereignty.gateway import SovereignGateway

if TYPE_CHECKING:  # pragma: no cover - أنواعٌ للتوثيق لا تُحمَّل وقتَ التشغيل
    from core.sovereignty.compensation import Compensator
    from core.sovereignty.contract import SovereignEffect
    from core.sovereignty.enforcement import EnforcementPermit
    from core.sovereignty.enforcement_boundary import (
        BoundaryOutcome,
        SovereignExecutionBoundary,
    )
    from core.sovereignty.idempotency import IdempotencyKey

T = TypeVar("T")


class LayerEscalationError(SovereigntyModelError):
    """طرف تابع حاول التقدّم بطلب من طبقة أعلى من طبقته."""


class UndeclaredExecutionError(SovereigntyModelError):
    """مُنفِّذٌ مُبهَمٌ بلا آثارٍ مُعلَنةٍ — لا يعبرُ حدَّ التنفيذِ فلا يقع.

    ليس عيبًا في المُنادي وحدَه: هو رفضُ الدولةِ أن تأذنَ لفعلٍ لا تعرفُ ماذا
    سيمسُّ. البديلُ `execute_declared`، ولا معامَلَ تجاوزٍ بينهما.
    """


class BoundaryNotConfiguredError(SovereigntyModelError):
    """بوابةٌ تابعةٌ بلا حدِّ تنفيذٍ محقون — فلا تنفيذ.

    الإغلاقُ مقصود: بناءُ حدٍّ افتراضيٍّ هنا كان سيخترعُ موضعَ سجلِّ ذرّيّةٍ من
    عندِه، فتصيرُ الذرّيّةُ وعدًا في الذاكرةِ لا ضمانًا على القرص.
    """


class SubordinateGateway:
    """أساس البوابات التابعة. لا تُستعمل مباشرة — تُستعمل إحدى بناتها.

    وهي **غلاف** على البوابة السيادية لا بديل عنها: كل تنفيذ يمرّ من
    `SovereignGateway.execute` نفسها، فلا يوجد مسار تنفيذ ثانٍ في الدولة
    (المادة العاشرة · 4). ودورها الوحيد أن تمنع الترقّي قبل التسليم.
    """

    layer: AuthorityLayer  # تُثبَّت في كل بنت، ولا تُمرَّر معامَلًا

    def __init__(
        self,
        gateway: SovereignGateway | None = None,
        *,
        boundary: SovereignExecutionBoundary | None = None,
    ) -> None:
        if not hasattr(type(self), "layer"):
            raise SovereigntyModelError(
                f"«{type(self).__name__}» بلا طبقة مُثبَّتة. لا بوابة بلا طبقة."
            )
        if self.layer.is_sovereign:
            raise SovereigntyModelError(
                "لا تُبنى بوابة تابعة على الطبقة السيادية. السيادة ليست طبقة "
                "تُورَّث، بل تُثبَت بمرسوم موقَّع."
            )
        self._gateway = gateway or SovereignGateway()
        self._boundary = boundary

    # ── الحراسة ───────────────────────────────────────────────────────────
    def _assert_no_escalation(self, request: ActionRequest) -> None:
        """طبقة الفاعل يجب أن تكون طبقة هذه البوابة أو أدنى منها.

        الأدنى مقبول: الفدرالي يُقدّم طلبًا باسم وكيل. والأعلى مرفوض دائمًا،
        وأعلى الجميع التاج — فلا تُقدَّم قرارات التاج من بوابة تابعة.
        """
        actor_layer = layer_of_actor(request.actor)
        if actor_layer < self.layer:
            raise LayerEscalationError(
                f"بوابة «{self.layer.arabic}» تلقّت طلبًا من طبقة "
                f"«{actor_layer.arabic}» وهي أعلى منها. الترقّي عبر البوابات ممنوع: "
                "الطبقة تُنسَب للفاعل ولا تُنتزَع من البوابة."
            )
        if request.royal_decree is not None:
            raise LayerEscalationError(
                f"بوابة «{self.layer.arabic}» لا تحمل مرسومًا ملكيًّا. القرار "
                "السيادي مساره البوابة السيادية وحدها، ولا يُوسَّط بطرف تابع."
            )

    # ── الاستعمال ─────────────────────────────────────────────────────────
    def review(self, request: ActionRequest) -> Verdict:
        """حكم دستوري مُلزِم بلا تنفيذ."""
        self._assert_no_escalation(request)
        return self._gateway.review(request)

    # ── التنفيذ عبر الحدّ · 1N ────────────────────────────────────────────
    @property
    def boundary(self) -> SovereignExecutionBoundary:
        """حدُّ التنفيذِ المحقون — أو رفضٌ صريح.

        لا يُبنى هنا افتراضيًّا: انظر شرحَ `BoundaryNotConfiguredError`.
        """
        if self._boundary is None:
            raise BoundaryNotConfiguredError(
                f"بوابة «{self.layer.arabic}» بلا حدِّ تنفيذٍ محقون، فلا تنفيذ. "
                "يُحقَن `SovereignExecutionBoundary` ببوابتِه وسجلِّ ذرّيّتِه عندَ "
                "البناء: `"
                + type(self).__name__
                + "(boundary=...)`."
            )
        return self._boundary

    def execute_declared(
        self,
        request: ActionRequest,
        *,
        declared_effects: tuple[SovereignEffect, ...],
        applier: Callable[[SovereignEffect], None],
        operation_key: IdempotencyKey,
        planner: Callable[[EnforcementPermit], tuple[SovereignEffect, ...]] | None = None,
        compensators: tuple[Compensator, ...] = (),
        **boundary_options: Any,
    ) -> BoundaryOutcome:
        """تنفيذٌ تابعٌ عبرَ حدِّ التنفيذ — الدستورُ مُلزِمٌ والآثارُ مُعلَنة.

        حرسُ الطبقةِ يُطبَّق **أوّلًا** كما كان: بوابةٌ تابعةٌ لا تُوسِّط طلبًا
        أعلى منها ولا تحملُ مرسومًا، ثمّ يتولّى الحدُّ بقيّةَ الحرس.

        `planner` اختياريّ: افتراضُه إعادةُ الآثارِ المُعلَنةِ نفسِها — وهو ما
        يفعلُه المُنادي الأمين. ومن أراد خطّةً أدقَّ سلّمها، وعقدُ 1E يقيسُها.

        وما بقيَ من معامَلاتِ الحدّ (`judicial_action` · `provider` · `payload_of`
        · `correlation_id`) يُمرَّر كما هو بلا تفسيرٍ هنا: التفسيرُ في 1M، وتكرارُه
        هنا كان سيُنتِج تفسيرينِ يفترقان.
        """
        self._assert_no_escalation(request)
        return self.boundary.execute(
            request,
            declared_effects=declared_effects,
            planner=planner or (lambda _permit: tuple(declared_effects)),
            applier=applier,
            operation_key=operation_key,
            compensators=compensators,
            **boundary_options,
        )

    def execute(self, request: ActionRequest, executor: Callable[[], T]) -> T:
        """مسارٌ **مُغلَق** منذ 1N — يُرفَع دائمًا ولا يُستدعى `executor` قطُّ.

        حرسُ الطبقةِ يُطبَّق قبلَ الرفض، فالترقّي يُرى ترقّيًا لا «مسارًا مغلقًا»:
        بوابةٌ تابعةٌ تلقّت طلبًا سياديًّا تُجيبُ عن الترقّي أوّلًا.
        """
        self._assert_no_escalation(request)
        raise UndeclaredExecutionError(
            f"بوابة «{self.layer.arabic}» تلقّت مُنفِّذًا مُبهَمًا للفعل "
            f"«{request.action}» على «{request.target}» "
            f"({getattr(executor, '__name__', type(executor).__name__)}). "
            "حدُّ التنفيذِ لا يأذنُ لما لا يعرفُ آثارَه: استعملْ "
            "`execute_declared` بآثارٍ مُعلَنةٍ ومفتاحِ عمليّةٍ ومعوّضات."
        )

    @property
    def sovereign_gateway(self) -> SovereignGateway:
        return self._gateway

    def __repr__(self) -> str:
        return f"<{type(self).__name__} layer={self.layer.name}>"


class FederalGateway(SubordinateGateway):
    """بوابة السلطة الفدرالية — الفروع الأربعة (المادة الثالثة)."""

    layer = AuthorityLayer.FEDERAL


class StateGateway(SubordinateGateway):
    """بوابة الولاية — تابعة للفدرالية وللتاج (المادة الرابعة)."""

    layer = AuthorityLayer.STATE


class InstitutionGateway(SubordinateGateway):
    """بوابة المؤسسة — تابعة لولايتها وللفدرالية وللتاج."""

    layer = AuthorityLayer.INSTITUTION


class AgentGateway(SubordinateGateway):
    """بوابة الوكيل — أضيق الطبقات صلاحية (المادة الثانية)."""

    layer = AuthorityLayer.AGENT


SUBORDINATE_GATEWAYS: tuple[type[SubordinateGateway], ...] = (
    FederalGateway,
    StateGateway,
    InstitutionGateway,
    AgentGateway,
)


__all__ = [
    "SUBORDINATE_GATEWAYS",
    "AgentGateway",
    "BoundaryNotConfiguredError",
    "FederalGateway",
    "InstitutionGateway",
    "LayerEscalationError",
    "StateGateway",
    "SubordinateGateway",
    "UndeclaredExecutionError",
]
