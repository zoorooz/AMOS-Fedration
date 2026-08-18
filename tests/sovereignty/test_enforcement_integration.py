"""الهدف: قياسُ وصلِ الإنفاذ — هل صارَ الحدُّ مسارَ التنفيذِ الفعليَّ للمُنادين؟

النطاق: `core/sovereignty/gateways.py` بعد هجرة 1N، وعلاقتُها بحدِّ 1M.
المالك: tests/sovereignty/ — ديوان التدقيق
تاريخ الإنشاء: 2026-08-18
تاريخ آخر تعديل: 2026-08-18

الفرقُ بين هذا الملفِّ وملفِّ 1M: هناك كان المُقاسُ **الحدَّ نفسَه** — هل يُتجاوَزُ
حرسُه؟ وهنا المُقاسُ **المُنادين** — هل صاروا يمرُّون به فعلًا، وهل بقيَ لهم بابٌ
جانبيّ؟ فلا يُعادُ اختبارُ 1E–1K ولا حرسُ 1M، وتُقاسُ ستُّ دعاوى وحدَها:

1. المُنادي المُهجَّر ينفُذ عبرَ الحدّ (لا بجانبِه).
2. تجاوزُ الحدِّ لا يُنتِجُ أثرًا.
3. المُصرَّحُ به يبقى ناجحًا.
4. غيرُ المُصرَّحِ به يبقى مُغلَقًا عندَ الفشل.
5. الأثرُ الخارجيُّ لا يبلُغُ المزوّدَ من مُطبِّقِ المُنادي.
6. لا مسارَ تنفيذٍ ثانيًا بقيَ ولا حرسٌ نُسِخ.

والقياسُ على **حالةٍ حقيقيّةٍ** وسجلّاتٍ على القرص: المنعُ يُثبَتُ بأنَّ الحالةَ لم
تتغيّر، لا بأنَّ استثناءً ارتفع.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import ClassVar

import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519

from core.constitutional_engine.engine import ConstitutionalEngine
from core.constitutional_engine.ledger import ConstitutionalLedger
from core.constitutional_engine.model import ActionRequest, Branch
from core.sovereignty.compensation import Compensator
from core.sovereignty.contract import EffectKind, SovereignEffect
from core.sovereignty.enforcement import ConsumedPermitLedger
from core.sovereignty.enforcement_boundary import (
    MANDATORY_EXTERNAL_STAGES,
    MANDATORY_INTERNAL_STAGES,
    BoundaryStage,
    CompensationNotDeclaredError,
    OperationKeyRequiredError,
    OutboxNotConfiguredError,
    SovereignExecutionBoundary,
    bypass_parameters_of,
)
from core.sovereignty.gateway import (
    FORBIDDEN_BYPASS_PARAMS,
    SovereignGateway,
    SovereigntyViolation,
)
from core.sovereignty.gateways import (
    AgentGateway,
    BoundaryNotConfiguredError,
    FederalGateway,
    LayerEscalationError,
    StateGateway,
    SubordinateGateway,
    UndeclaredExecutionError,
)
from core.sovereignty.idempotency import IdempotencyKey, IdempotencyLedger
from core.sovereignty.outbox import EffectPayload, OutboxLedger, SovereignOutbox

REPO_ROOT = Path(__file__).resolve().parents[2]
TARGET = "state/province-A"
NOTICE = "notifications/citizen-1"


# ═══════════════════════════════════════════════════════════════════════════
# تجهيزات
# ═══════════════════════════════════════════════════════════════════════════


class مزوّدٌ_مُراقَب:
    """مزوّدٌ خارجيٌّ يُفشِلُ الاختبارَ إن نُودي من مسارِ المُنادي."""

    name = "مزوّدٌ-للقياس"
    supports_idempotency = True

    def __init__(self) -> None:
        self.نداءات: list[object] = []

    def deliver(self, envelope: object):
        self.نداءات.append(envelope)
        raise AssertionError("لا يُنادى المزوّدُ من مسارِ التنفيذِ بحال.")


@pytest.fixture()
def حالةُ_الدولة() -> dict[str, str]:
    return {TARGET: "ORIGINAL", NOTICE: "NONE"}


@pytest.fixture()
def بوابة(tmp_path: Path) -> SovereignGateway:
    return SovereignGateway(
        ConstitutionalEngine(ledger=ConstitutionalLedger(tmp_path / "السجل.jsonl"))
    )


@pytest.fixture()
def مزوّد() -> مزوّدٌ_مُراقَب:
    return مزوّدٌ_مُراقَب()


@pytest.fixture()
def صادر(tmp_path: Path, بوابة: SovereignGateway) -> SovereignOutbox:
    return SovereignOutbox(
        ledger=OutboxLedger(tmp_path / "OUTBOX.json"),
        verifying_key=ed25519.Ed25519PublicKey.from_public_bytes(
            bytes.fromhex(بوابة.verifying_key_hex)
        ),
    )


@pytest.fixture()
def حدّ(
    tmp_path: Path, بوابة: SovereignGateway, صادر: SovereignOutbox
) -> SovereignExecutionBoundary:
    return SovereignExecutionBoundary(
        gateway=بوابة,
        idempotency_ledger=IdempotencyLedger(tmp_path / "IDEMPOTENCY.json"),
        outbox=صادر,
        consumed_permits=ConsumedPermitLedger(tmp_path / "CONSUMED.json"),
    )


@pytest.fixture()
def حدٌّ_بلا_صادر(tmp_path: Path, بوابة: SovereignGateway) -> SovereignExecutionBoundary:
    return SovereignExecutionBoundary(
        gateway=بوابة,
        idempotency_ledger=IdempotencyLedger(tmp_path / "IDEMPOTENCY-2.json"),
        consumed_permits=ConsumedPermitLedger(tmp_path / "CONSUMED-2.json"),
    )


@pytest.fixture()
def بوابةُ_ولاية(
    بوابة: SovereignGateway, حدّ: SovereignExecutionBoundary
) -> StateGateway:
    return StateGateway(بوابة, boundary=حدّ)


def _طلب(action: str = "execute_task", target: str = TARGET) -> ActionRequest:
    return ActionRequest(
        actor=Branch.STATE, action=action, target=target, channel="official"
    )


def _أثر(
    kind: EffectKind = EffectKind.WRITE, resource: str = TARGET
) -> SovereignEffect:
    return SovereignEffect(kind=kind, resource=resource, detail="قياسُ الوصل")


def _مفتاح(value: str, scope: str = "1n.integration") -> IdempotencyKey:
    return IdempotencyKey(scope=scope, value=value)


def _معوّض(state: dict[str, str], effect: SovereignEffect) -> Compensator:
    return Compensator(
        effect_signature=effect.signature,
        apply=lambda: state.update({effect.resource: "ORIGINAL"}),
        description="إرجاعُ القيمةِ الأصليّة",
    )


def _مُطبِّق(state: dict[str, str], مُستقبَل: list[SovereignEffect]):
    def apply(effect: SovereignEffect) -> None:
        مُستقبَل.append(effect)
        state[effect.resource] = "MUTATED"

    return apply


# ═══════════════════════════════════════════════════════════════════════════
# 1 — المُنادي المُهجَّر ينفُذ عبرَ الحدّ
# ═══════════════════════════════════════════════════════════════════════════


class Testالمُنادونالمُهجَّرون:
    """`SubordinateGateway` كانت تُمرِّرُ مُنفِّذًا مُبهَمًا — وهذا مخرجُها."""

    def test_التنفيذ_التابع_يمر_بكل_مراحل_الحد(
        self, بوابةُ_ولاية: StateGateway, حالةُ_الدولة: dict[str, str]
    ) -> None:
        """القياسُ على المراحلِ المُسجَّلة: ما مرَّ فعلًا لا ما كان مُخطَّطًا."""
        أثر = _أثر()
        مُستقبَل: list[SovereignEffect] = []
        حصيلة = بوابةُ_ولاية.execute_declared(
            _طلب(),
            declared_effects=(أثر,),
            applier=_مُطبِّق(حالةُ_الدولة, مُستقبَل),
            operation_key=_مفتاح("مرور-كامل"),
            compensators=(_معوّض(حالةُ_الدولة, أثر),),
        )
        assert set(MANDATORY_INTERNAL_STAGES) <= set(حصيلة.stages), (
            f"مرحلةٌ إلزاميّةٌ لم تُمَرّ: {set(MANDATORY_INTERNAL_STAGES) - set(حصيلة.stages)}"
        )
        assert حالةُ_الدولة[TARGET] == "MUTATED", "الأثرُ المُصرَّحُ به لم يقع."
        assert مُستقبَل == [أثر], "المُطبِّقُ لم يستقبل الأثرَ المُعلَنَ وحدَه."
        assert حصيلة.permit_id, "نُفِّذَ بلا إذنٍ مُسجَّل."

    def test_الحد_يمر_من_البوابة_نفسها_لا_من_بوابة_ثانية(
        self, بوابة: SovereignGateway, بوابةُ_ولاية: StateGateway
    ) -> None:
        """هويّةُ الكائنِ هي الدليل: بوابةٌ ثانيةٌ كانت ستعني دستورينِ يفترقان."""
        assert بوابةُ_ولاية.boundary.gateway is بوابة
        assert بوابةُ_ولاية.sovereign_gateway is بوابة

    def test_حرس_الطبقة_يبقى_قبل_الحد_لا_بعده(
        self, بوابة: SovereignGateway, حدّ: SovereignExecutionBoundary
    ) -> None:
        """الترقّي يُرَدُّ قبلَ أن يُبنى عقدٌ أو يُحجَزَ مفتاح — كما كان قبل 1N."""
        وكيل = AgentGateway(بوابة, boundary=حدّ)
        أثر = _أثر()
        with pytest.raises(LayerEscalationError):
            وكيل.execute_declared(
                ActionRequest(actor=Branch.STATE, action="execute_task", target=TARGET),
                declared_effects=(أثر,),
                applier=lambda _أ: None,
                operation_key=_مفتاح("ترقٍّ"),
                compensators=(Compensator(effect_signature=أثر.signature, apply=lambda: None),),
            )

    def test_الاعادة_تُعلَن_ولا_تُعَد_نجاحا_ثانيا(
        self, بوابةُ_ولاية: StateGateway, حالةُ_الدولة: dict[str, str]
    ) -> None:
        """المفتاحُ نفسُه مرّتين: الأثرُ يقعُ مرّةً، والثانيةُ تُعلِنُ نفسَها إعادةً."""
        أثر = _أثر()
        مُستقبَل: list[SovereignEffect] = []
        وسائط = {
            "declared_effects": (أثر,),
            "applier": _مُطبِّق(حالةُ_الدولة, مُستقبَل),
            "operation_key": _مفتاح("مرّةٌ-واحدة"),
            "compensators": (_معوّض(حالةُ_الدولة, أثر),),
        }
        أولى = بوابةُ_ولاية.execute_declared(_طلب(), **وسائط)
        ثانية = بوابةُ_ولاية.execute_declared(_طلب(), **وسائط)
        assert not أولى.is_replay and ثانية.is_replay
        assert len(مُستقبَل) == 1, "طُبِّقَ الأثرُ مرّتين رغمَ وحدةِ المفتاح."


# ═══════════════════════════════════════════════════════════════════════════
# 2 — تجاوزُ الحدِّ لا يُنتِجُ أثرًا
# ═══════════════════════════════════════════════════════════════════════════


class Testالتجاوزلايُنتِجأثرا:
    """المسارُ القديمُ أُغلِق — والإغلاقُ يُقاسُ على الحالةِ لا على الاستثناء."""

    def test_المنفذ_المبهم_يُرفَض_ولا_يُستدعى(
        self, بوابةُ_ولاية: StateGateway, حالةُ_الدولة: dict[str, str]
    ) -> None:
        استُدعي: list[str] = []

        def مُنفِّذٌ_مُبهَم() -> str:
            استُدعي.append("نُفِّذ")
            حالةُ_الدولة[TARGET] = "BYPASSED"
            return "نُفِّذ"

        with pytest.raises(UndeclaredExecutionError):
            بوابةُ_ولاية.execute(_طلب(), مُنفِّذٌ_مُبهَم)
        assert استُدعي == [], "استُدعي المُنفِّذُ المُبهَمُ رغمَ الإغلاق."
        assert حالةُ_الدولة[TARGET] == "ORIGINAL", "تغيّرت الحالةُ بمسارٍ مُغلَق."

    def test_بوابة_بلا_حد_لا_تُنفِّذ(
        self, بوابة: SovereignGateway, حالةُ_الدولة: dict[str, str]
    ) -> None:
        """غيابُ الحدِّ توقُّفٌ لا تجاوز — ولا يُبنى حدٌّ افتراضيٌّ من عندِه."""
        بلا_حدّ = FederalGateway(بوابة)
        أثر = _أثر()
        with pytest.raises(BoundaryNotConfiguredError):
            بلا_حدّ.execute_declared(
                ActionRequest(actor=Branch.EXECUTIVE, action="execute_task", target=TARGET),
                declared_effects=(أثر,),
                applier=_مُطبِّق(حالةُ_الدولة, []),
                operation_key=_مفتاح("بلا-حدّ"),
                compensators=(_معوّض(حالةُ_الدولة, أثر),),
            )
        assert حالةُ_الدولة[TARGET] == "ORIGINAL", "نُفِّذَ فعلٌ بلا حدِّ تنفيذ."

    def test_الاغلاق_يشمل_كل_البوابات_التابعة(
        self, بوابة: SovereignGateway, حدّ: SovereignExecutionBoundary
    ) -> None:
        """لا طبقةَ استُثنِيَت: الإغلاقُ في الأصلِ لا في كلِّ فرعٍ على حِدة."""
        for صنف in (FederalGateway, StateGateway, AgentGateway):
            with pytest.raises(UndeclaredExecutionError):
                صنف(بوابة, boundary=حدّ).execute(
                    ActionRequest(actor=Branch.AGENT, action="execute_task", target=TARGET),
                    lambda: "ممنوع",
                )

    def test_لا_معامل_تجاوز_في_مسار_الهجرة(self) -> None:
        """`bypass_parameters_of` من 1M تُقرأُ على السطحِ الجديدِ نفسِه."""
        متسرّبة = bypass_parameters_of(SubordinateGateway)
        assert not متسرّبة, f"راياتُ تجاوزٍ في مسارِ الهجرة: {متسرّبة}"
        معامَلات = set(inspect.signature(SubordinateGateway.execute_declared).parameters)
        assert not (معامَلات & FORBIDDEN_BYPASS_PARAMS)


# ═══════════════════════════════════════════════════════════════════════════
# 3 + 4 — المُصرَّحُ ينجح، وغيرُ المُصرَّحِ يُغلَق
# ═══════════════════════════════════════════════════════════════════════════


class Testدلالاتالنجاحوالفشلمحفوظة:
    """ما كان ينجحُ ينجح، وما كان يُمنَعُ يُمنَع — بالاستثناءِ نفسِه."""

    def test_المخالفة_الدستورية_تبقى_مانعة(
        self, بوابةُ_ولاية: StateGateway, حالةُ_الدولة: dict[str, str]
    ) -> None:
        أثر = _أثر()
        with pytest.raises(SovereigntyViolation):
            بوابةُ_ولاية.execute_declared(
                _طلب("opt_out_constitution"),
                declared_effects=(أثر,),
                applier=_مُطبِّق(حالةُ_الدولة, []),
                operation_key=_مفتاح("مخالف"),
                compensators=(_معوّض(حالةُ_الدولة, أثر),),
            )
        assert حالةُ_الدولة[TARGET] == "ORIGINAL", "نُفِّذَ فعلٌ مخالفٌ دستوريًّا."

    def test_اثر_بلا_معوض_يُرَد_قبل_اي_اذن(
        self, بوابةُ_ولاية: StateGateway, حالةُ_الدولة: dict[str, str]
    ) -> None:
        """الحرسُ الذي أضافته 1N للمُنادي: أثرٌ مُغيِّرٌ بلا مخرجٍ لا يُدخَل فيه."""
        قبلَ = len(بوابةُ_ولاية.sovereign_gateway.records)
        with pytest.raises(CompensationNotDeclaredError):
            بوابةُ_ولاية.execute_declared(
                _طلب(),
                declared_effects=(_أثر(),),
                applier=_مُطبِّق(حالةُ_الدولة, []),
                operation_key=_مفتاح("بلا-معوّض"),
            )
        assert حالةُ_الدولة[TARGET] == "ORIGINAL"
        assert len(بوابةُ_ولاية.sovereign_gateway.records) == قبلَ, (
            "صدرَ قرارٌ لعقدٍ رُفِضَ قبلَ القرار."
        )

    def test_مفتاح_ليس_مفتاحا_يُرَد_قبل_اي_اذن(
        self, بوابةُ_ولاية: StateGateway, حالةُ_الدولة: dict[str, str]
    ) -> None:
        أثر = _أثر()
        with pytest.raises(OperationKeyRequiredError):
            بوابةُ_ولاية.execute_declared(
                _طلب(),
                declared_effects=(أثر,),
                applier=_مُطبِّق(حالةُ_الدولة, []),
                operation_key="نصٌّ-ليس-مفتاحًا",  # type: ignore[arg-type]
                compensators=(_معوّض(حالةُ_الدولة, أثر),),
            )
        assert حالةُ_الدولة[TARGET] == "ORIGINAL"


# ═══════════════════════════════════════════════════════════════════════════
# 5 — الأثرُ الخارجيُّ لا يبلُغُ المزوّد
# ═══════════════════════════════════════════════════════════════════════════


class Testالأثرالخارجيّلايُسلَّممباشرة:
    """المُنادي المُهجَّرُ لا يستطيعُ أن يمسَّ مزوّدًا، ولو أراد."""

    def test_الاثر_الخارجي_يُرتَّب_في_الصادر_ولا_يبلغ_المطبِّق(
        self, بوابةُ_ولاية: StateGateway, مزوّد: مزوّدٌ_مُراقَب
    ) -> None:
        أثر = _أثر(EffectKind.EXTERNAL, NOTICE)
        مُستقبَل: list[SovereignEffect] = []
        حصيلة = بوابةُ_ولاية.execute_declared(
            _طلب(target=NOTICE),
            declared_effects=(أثر,),
            applier=lambda e: مُستقبَل.append(e),
            operation_key=_مفتاح("خارجيّ"),
            provider=مزوّد,
            payload_of=lambda _e: EffectPayload(data={"نص": "إشعار"}, version=1),
        )
        assert BoundaryStage.EXTERNAL_OUTBOX in حصيلة.stages
        assert set(MANDATORY_EXTERNAL_STAGES) <= set(حصيلة.stages)
        assert حصيلة.enqueued_effect_ids, "لم يُرتَّب الأثرُ الخارجيُّ في الصادر."
        assert مُستقبَل == [], "بلغَ الأثرُ الخارجيُّ مُطبِّقَ المُنادي."
        assert مزوّد.نداءات == [], "نُودي المزوّدُ من مسارِ التنفيذ."

    def test_اثر_خارجي_بلا_صادر_يُرَد_ولا_يُنادى_مزوّد(
        self, بوابة: SovereignGateway, حدٌّ_بلا_صادر: SovereignExecutionBoundary,
        مزوّد: مزوّدٌ_مُراقَب,
    ) -> None:
        ولاية = StateGateway(بوابة, boundary=حدٌّ_بلا_صادر)
        with pytest.raises(OutboxNotConfiguredError):
            ولاية.execute_declared(
                _طلب(target=NOTICE),
                declared_effects=(_أثر(EffectKind.EXTERNAL, NOTICE),),
                applier=lambda _e: None,
                operation_key=_مفتاح("خارجيٌّ-بلا-صادر"),
                provider=مزوّد,
                payload_of=lambda _e: EffectPayload(data={"نص": "إشعار"}, version=1),
            )
        assert مزوّد.نداءات == []


# ═══════════════════════════════════════════════════════════════════════════
# 6 — لا مسارَ تنفيذٍ ثانيًا بقيَ
# ═══════════════════════════════════════════════════════════════════════════


class Testلامسارتنفيذثان:
    """حرسُ الانحدار: بابٌ جانبيٌّ جديدٌ يجب أن يُفشِلَ الاختبار، لا أن يمرّ."""

    #: ملفّاتُ الإنتاجِ التي ما زالت تُنادي `SovereignGateway.execute` مباشرةً،
    #: مقيسةً لا مُقدَّرة. الزيادةُ على هذه القائمةِ تُفشِلُ الاختبار.
    #:
    #: `gateway.py` مالكُ الدالّةِ نفسِها، و`decide` الذي يستدعيه الحدُّ يمرُّ
    #: منها — فليست تجاوزًا بل الأصلُ الذي يقفُ الحدُّ فوقَه.
    مسموحٌ_له: ClassVar[frozenset[str]] = frozenset({
        "core/sovereignty/gateway.py",
        # أدواتُ إثباتٍ وعرضٍ لا تمسُّ حالةً: مُنفِّذُها يُرجِعُ نصًّا ثابتًا.
        # مُقاسةٌ ومُعلَنةٌ حدًّا لنطاقِ 1N، لا مُبرَّرةٌ بادّعاء.
        "core/sovereignty/cli.py",
        "tools/sovereignty/prove_supreme_authority.py",
    })

    def test_لا_منادي_انتاجي_جديد_يستدعي_البوابة_مباشرة(self) -> None:
        مُنادون: set[str] = set()
        for ملف in (REPO_ROOT / "core").rglob("*.py"):
            نص = ملف.read_text(encoding="utf-8")
            if "gateway.execute(" in نص or "_gateway.execute(" in نص:
                مُنادون.add(str(ملف.relative_to(REPO_ROOT)))
        for ملف in (REPO_ROOT / "tools").rglob("*.py"):
            نص = ملف.read_text(encoding="utf-8")
            if "gw.execute(" in نص or "gateway.execute(" in نص:
                مُنادون.add(str(ملف.relative_to(REPO_ROOT)))
        زائد = مُنادون - set(self.مسموحٌ_له)
        assert زائد == set(), (
            f"مُنادٍ جديدٌ يستدعي البوابةَ مباشرةً بلا حدٍّ: {sorted(زائد)}. "
            "التنفيذُ يمرُّ من `SovereignExecutionBoundary` أو لا يمرُّ."
        )

    def test_الجسر_الفدرالي_لا_يستدعي_البوابة_مباشرة(self) -> None:
        """المُنادي الإنتاجيُّ الوحيدُ في `federal/` هُجِّر — والقياسُ على مصدرِه."""
        جسر = (
            REPO_ROOT
            / "federal/executive/services/src/amos_federation/services"
            / "executive_core/sovereignty_bridge.py"
        )
        نص = جسر.read_text(encoding="utf-8")
        assert "self._gateway.execute(" not in نص, (
            "الجسرُ الفدراليُّ عادَ يستدعي `SovereignGateway.execute` مباشرةً."
        )
        assert "self.boundary.execute(" in نص, "الجسرُ لا يمرُّ بحدِّ التنفيذ."

    def test_النواة_التنفيذية_لا_تنادي_المسار_المغلق(self) -> None:
        """`guard` أُغلِق — فلا موضعَ في `executive_core` يناديه."""
        جذر = (
            REPO_ROOT
            / "federal/executive/services/src/amos_federation/services/executive_core"
        )
        مُنادون = [
            str(ملف.relative_to(REPO_ROOT))
            for ملف in جذر.rglob("*.py")
            if "_authorizer.guard(" in ملف.read_text(encoding="utf-8")
        ]
        assert مُنادون == [], f"مُنادٍ للمسارِ المُغلَقِ `guard`: {مُنادون}"

    def test_الحد_لا_يُنسَخ_في_البوابات_التابعة(self) -> None:
        """`execute_declared` تُمرِّرُ ولا تُقرِّر: لا حرسٌ ثانٍ يُكتَبُ هنا."""
        مصدر = inspect.getsource(SubordinateGateway.execute_declared)
        for محرَّم in ("bind_contract", "decide(", "IdempotencyGuard", "enqueue_write_ahead"):
            assert محرَّم not in مصدر, (
                f"نُسِخَ حرسٌ («{محرَّم}») في البوابةِ التابعةِ — حرسانِ يفترقان."
            )
