"""الهدف: قياسُ الإنفاذِ على حدِّ التنفيذ — هل يُتجاوَزُ الحرسُ فعلًا أم لا؟

النطاق: `core/sovereignty/enforcement_boundary.py` وحدَه، وما يفرضُه من 1E–1K.
المالك: tests/sovereignty/ — ديوان التدقيق
تاريخ الإنشاء: 2026-08-18
تاريخ آخر تعديل: 2026-08-18

القاعدةُ 12 تمنعُ اعتبارَ وجودِ الملفِّ دليلًا على القدرة، والقاعدةُ 13 تمنعُ
الاكتفاءَ باختبارِ وحدة. فالقياسُ هنا على **قاموسِ حالةٍ حقيقيّ** وعلى **سجلّاتٍ
على القرص**: المنعُ يُثبَتُ بأنّ الحالةَ لم تتغيّر، لا بأنَّ استثناءً ارتفع.

ولا يُعادُ اختبارُ 1F ولا 1G ولا 1H ولا 1I ولا 1J ولا 1K هنا. المُقاسُ دعوى
واحدة: **مَن حاولَ الوصولَ إلى أثرٍ حقيقيٍّ متجاوزًا حرسًا من هذه الحُرَّاس فشلَ
فعلًا، ولم يُنتِج أثرًا.**
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519

from core.constitutional_engine.engine import ConstitutionalEngine
from core.constitutional_engine.ledger import ConstitutionalLedger
from core.constitutional_engine.model import ActionRequest, Branch
from core.sovereignty.compensation import (
    Compensator,
    IrreversibleEffectError,
    UncompensatableEffectError,
)
from core.sovereignty.contract import EffectKind, SovereignEffect
from core.sovereignty.enforcement import (
    ConsumedPermitLedger,
    PermitInvalidError,
    PermitScopeError,
    PolicyEnforcementPoint,
)
from core.sovereignty.enforcement_boundary import (
    DEFAULT_GUARDED_SCOPE,
    MANDATORY_EXTERNAL_STAGES,
    MANDATORY_INTERNAL_STAGES,
    BoundaryConfigurationError,
    BoundaryStage,
    CompensationNotDeclaredError,
    JurisdictionNotDeclaredError,
    MixedEffectContractError,
    OperationKeyRequiredError,
    OutboxNotConfiguredError,
    SovereignExecutionBoundary,
    StaticEnforcementGuard,
    StaticGuardError,
    bypass_parameters_of,
)
from core.sovereignty.gateway import (
    FORBIDDEN_BYPASS_PARAMS,
    SovereignGateway,
    SovereigntyViolation,
)
from core.sovereignty.idempotency import (
    IdempotencyError,
    IdempotencyKey,
    IdempotencyKeyReuseError,
    IdempotencyLedger,
    OperationStatus,
)
from core.sovereignty.jurisdiction import JudicialAction, JurisdictionError
from core.sovereignty.outbox import (
    DeliveryStatus,
    EffectPayload,
    OutboxLedger,
    SovereignOutbox,
)

TARGET = "treasury/account-A"
CASE = "judiciary/case-1"
NOTICE = "notifications/citizen-1"
REPO_ROOT = Path(__file__).resolve().parents[2]


# ═══════════════════════════════════════════════════════════════════════════
# تجهيزات — حالةٌ حقيقيّةٌ وسجلّاتٌ على القرص، لا مُتتبِّعاتُ استدعاء
# ═══════════════════════════════════════════════════════════════════════════


class مزوّدٌ_مُراقَب:
    """مزوّدٌ خارجيٌّ يُسجّلُ كلَّ نداء، ويُفشِلُ الاختبارَ إن نُودي من الحدّ.

    الحدُّ لا يُسلِّمُ شيئًا إلى مزوّدٍ: التسليمُ شأنُ عاملِ الصادرِ (1K) وحدَه.
    """

    name = "مزوّدٌ-للقياس"
    supports_idempotency = True

    def __init__(self) -> None:
        self.نداءات: list[object] = []

    def deliver(self, envelope: object):
        self.نداءات.append(envelope)
        raise AssertionError("لا يُنادى المزوّدُ من حدِّ التنفيذِ بحال.")


@pytest.fixture()
def حالةُ_الدولة() -> dict[str, str]:
    """حالةٌ حقيقيّةٌ يُقاسُ عليها الوقوعُ والمنع."""
    return {TARGET: "1000", CASE: "OPEN", NOTICE: "NONE"}


@pytest.fixture()
def بوابة(tmp_path: Path) -> SovereignGateway:
    return SovereignGateway(ConstitutionalEngine(ledger=ConstitutionalLedger(tmp_path / "l.jsonl")))


@pytest.fixture()
def سجلُّ_الذرّيّة(tmp_path: Path) -> IdempotencyLedger:
    return IdempotencyLedger(tmp_path / "IDEMPOTENCY.json")


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
    tmp_path: Path,
    بوابة: SovereignGateway,
    سجلُّ_الذرّيّة: IdempotencyLedger,
    صادر: SovereignOutbox,
) -> SovereignExecutionBoundary:
    """حدٌّ كاملُ التهيئة — والسجلّاتُ على القرصِ لا في الذاكرة."""
    return SovereignExecutionBoundary(
        gateway=بوابة,
        idempotency_ledger=سجلُّ_الذرّيّة,
        outbox=صادر,
        consumed_permits=ConsumedPermitLedger(tmp_path / "CONSUMED.json"),
    )


@pytest.fixture()
def حدٌّ_بلا_صادر(
    tmp_path: Path, بوابة: SovereignGateway, سجلُّ_الذرّيّة: IdempotencyLedger
) -> SovereignExecutionBoundary:
    return SovereignExecutionBoundary(
        gateway=بوابة,
        idempotency_ledger=سجلُّ_الذرّيّة,
        consumed_permits=ConsumedPermitLedger(tmp_path / "CONSUMED.json"),
    )


def _طلب(
    action: str = "credit_account",
    target: str = TARGET,
    actor: Branch = Branch.EXECUTIVE,
) -> ActionRequest:
    return ActionRequest(actor=actor, action=action, target=target, channel="official")


def _أثر(
    kind: EffectKind = EffectKind.WRITE, resource: str = TARGET
) -> SovereignEffect:
    return SovereignEffect(kind=kind, resource=resource, detail="قياس")


def _مفتاح(value: str = "op-1", scope: str = "treasury") -> IdempotencyKey:
    return IdempotencyKey(scope=scope, value=value)


def _معوّض(state: dict[str, str], effect: SovereignEffect, قيمة: str = "1000"):
    return Compensator(
        effect_signature=effect.signature,
        apply=lambda: state.update({effect.resource: قيمة}),
        description="إرجاعُ القيمةِ الأصليّة",
    )


def _تطبيقٌ_مُراقَب(state: dict[str, str], مُستقبَل: list[SovereignEffect]):
    """مُطبِّقُ المُنادي — يُسجّلُ ما استقبلَه ويمسُّ الحالةَ فعلًا."""

    def apply(effect: SovereignEffect) -> None:
        مُستقبَل.append(effect)
        state[effect.resource] = "MUTATED"

    return apply


def _طلبٌ_قضائيّ(action: str = "issue_ruling", scope: str = "FEDERAL") -> JudicialAction:
    return JudicialAction(
        action=action,
        court_scope=scope,
        case_scope=scope,
        actor_scope=scope,
        target=CASE,
    )


# ═══════════════════════════════════════════════════════════════════════════
# 1 — إثباتُ التكامل: المسارُ المأذونُ يعبرُ السلسلةَ كاملةً ويُنتِجُ أثرًا
# ═══════════════════════════════════════════════════════════════════════════


class Testإثباتُالتكامل:
    """المأذونُ ينفُذ، والمرفوضُ لا يُنتِجُ أثرًا. والدعوى تُقاسُ على الحالة."""

    def test_المسارُالمأذونُيمرُّبكلِّالمراحلِالمُلزِمةِالداخليّة(
        self, حدّ: SovereignExecutionBoundary, حالةُ_الدولة: dict[str, str]
    ) -> None:
        أثر = _أثر()
        مُستقبَل: list[SovereignEffect] = []
        حصيلة = حدّ.execute(
            _طلب(),
            declared_effects=(أثر,),
            planner=lambda _: (أثر,),
            applier=_تطبيقٌ_مُراقَب(حالةُ_الدولة, مُستقبَل),
            operation_key=_مفتاح(),
            compensators=(_معوّض(حالةُ_الدولة, أثر),),
        )
        for مرحلة in MANDATORY_INTERNAL_STAGES:
            assert حصيلة.passed(مرحلة), f"المرحلةُ المُلزِمةُ «{مرحلة.value}» لم تمرّ."
        assert حالةُ_الدولة[TARGET] == "MUTATED"
        assert مُستقبَل == [أثر]
        assert حصيلة.is_replay is False
        assert حصيلة.compensation_plan is not None

    def test_سندُالتدقيقِموجودٌبعدَالعبور(
        self, حدّ: SovereignExecutionBoundary, بوابة: SovereignGateway, حالةُ_الدولة: dict[str, str]
    ) -> None:
        """لا عبورَ بلا سجلٍّ في البوابةِ وإذنٍ مُستهلَكٍ وعمليّةٍ مُثبَّتة."""
        أثر = _أثر()
        حصيلة = حدّ.execute(
            _طلب(),
            declared_effects=(أثر,),
            planner=lambda _: (أثر,),
            applier=_تطبيقٌ_مُراقَب(حالةُ_الدولة, []),
            operation_key=_مفتاح(),
            compensators=(_معوّض(حالةُ_الدولة, أثر),),
        )
        assert بوابة.records, "لا سجلَّ في البوابةِ بعدَ تنفيذٍ — التدقيقُ أعمى."
        assert حدّ.consumed_permits.is_consumed(حصيلة.permit_id)
        سجلّ = حدّ.idempotency_ledger.get(_مفتاح())
        assert سجلّ is not None
        assert سجلّ.status is OperationStatus.SUCCEEDED

    def test_المسارُالمرفوضُلايُنتِجُأثرًا(
        self, حدّ: SovereignExecutionBoundary, حالةُ_الدولة: dict[str, str]
    ) -> None:
        """الرفضُ الدستوريُّ يمنعُ قبلَ التطبيقِ — والحالةُ شاهدة."""
        أثر = _أثر()
        مُستقبَل: list[SovereignEffect] = []
        with pytest.raises(SovereigntyViolation):
            حدّ.execute(
                _طلب(action="amend_constitution"),
                declared_effects=(أثر,),
                planner=lambda _: (أثر,),
                applier=_تطبيقٌ_مُراقَب(حالةُ_الدولة, مُستقبَل),
                operation_key=_مفتاح(),
                compensators=(_معوّض(حالةُ_الدولة, أثر),),
            )
        assert حالةُ_الدولة[TARGET] == "1000"
        assert مُستقبَل == []
        assert حدّ.consumed_permits.count() == 0

    def test_الأثرُالخارجيُّيمرُّبكلِّمراحلِهالمُلزِمة(
        self, حدّ: SovereignExecutionBoundary, حالةُ_الدولة: dict[str, str]
    ) -> None:
        أثر = _أثر(EffectKind.EXTERNAL, NOTICE)
        مزوّد = مزوّدٌ_مُراقَب()
        حصيلة = حدّ.execute(
            _طلب(action="notify_citizen", target=NOTICE),
            declared_effects=(أثر,),
            planner=lambda _: (أثر,),
            applier=_تطبيقٌ_مُراقَب(حالةُ_الدولة, []),
            operation_key=_مفتاح("op-ext", "notify"),
            provider=مزوّد,
            payload_of=lambda _: EffectPayload(data={"to": "citizen-1"}),
        )
        for مرحلة in MANDATORY_EXTERNAL_STAGES:
            assert حصيلة.passed(مرحلة), f"المرحلةُ المُلزِمةُ «{مرحلة.value}» لم تمرّ."
        assert len(حصيلة.enqueued_effect_ids) == 1


# ═══════════════════════════════════════════════════════════════════════════
# 2 — محاولاتُ تجاوزِ السلطةِ والإذن (1D · 1F)
# ═══════════════════════════════════════════════════════════════════════════


class Testتجاوزُالسلطةِوالإذن:
    """لا وصولَ إلى أثرٍ بلا حكمٍ مأذونٍ وإذنٍ موقَّعٍ من هذه البوابةِ بعينِها."""

    def test_الحدُّلايملكُمفتاحَتوقيع(self, حدّ: SovereignExecutionBoundary) -> None:
        """يملكُ التحقّقَ العامَّ فقط — والامتناعُ بنيويٌّ لا سلوكيّ."""
        assert حدّ.self_check()["signs_permits"] is False
        assert not hasattr(حدّ, "_permit_key")
        assert set(PolicyEnforcementPoint.__slots__) == {"verifying_key", "consumed"}

    def test_إذنٌمنبوابةٍأخرىلايُنفَّذعلىهذاالحدّ(
        self, tmp_path: Path, حدّ: SovereignExecutionBoundary, حالةُ_الدولة: dict[str, str]
    ) -> None:
        """التزويرُ بمفتاحٍ آخرَ لا يعبرُ: الحدُّ يتحقّقُ بمفتاحِ بوابتِه وحدَها."""
        أثر = _أثر()
        غريبة = SovereignGateway(
            ConstitutionalEngine(ledger=ConstitutionalLedger(tmp_path / "غريب.jsonl"))
        )
        إذنٌ_غريب = غريبة.decide(_طلب(), declared_effects=(أثر,))
        with pytest.raises(PermitInvalidError):
            حدّ.policy_enforcement_point.enforce(
                إذنٌ_غريب,
                planner=lambda _: (أثر,),
                applier=_تطبيقٌ_مُراقَب(حالةُ_الدولة, []),
            )
        assert حالةُ_الدولة[TARGET] == "1000"

    def test_أثرٌغيرُمُعلَنٍلايُطبَّق(
        self, حدّ: SovereignExecutionBoundary, حالةُ_الدولة: dict[str, str]
    ) -> None:
        """المُخطِّطُ الذي يُنتِجُ أثرًا خارجَ الإذنِ يُوقَفُ قبلَ أوّلِ تطبيق."""
        مُعلَن = _أثر()
        مُتسلِّل = _أثر(EffectKind.DELETE, TARGET)
        مُستقبَل: list[SovereignEffect] = []
        with pytest.raises(IdempotencyError) as خطأ:
            حدّ.execute(
                _طلب(),
                declared_effects=(مُعلَن,),
                planner=lambda _: (مُعلَن, مُتسلِّل),
                applier=_تطبيقٌ_مُراقَب(حالةُ_الدولة, مُستقبَل),
                operation_key=_مفتاح(),
                compensators=(_معوّض(حالةُ_الدولة, مُعلَن),),
            )
        # حارسُ 1H يلفُّ الرفضَ ولا يُخفيه: السببُ الأصليُّ باقٍ في السلسلة.
        assert isinstance(خطأ.value.__cause__, PermitScopeError)
        assert "لم يُطبَّق شيء" in str(خطأ.value)
        assert مُستقبَل == [], "طُبِّقَ أثرٌ قبلَ فحصِ نطاقِ الإذن."
        assert حالةُ_الدولة[TARGET] == "1000"

    def test_إعادةُالمفتاحِلاتستهلكُإذنًاثانيًا(
        self, حدّ: SovereignExecutionBoundary, حالةُ_الدولة: dict[str, str]
    ) -> None:
        """الذرّيّةُ تسبقُ الإنفاذ: الإعادةُ لا تُنتِجُ إذنًا مُستهلَكًا جديدًا."""
        أثر = _أثر()
        for _ in range(3):
            حدّ.execute(
                _طلب(),
                declared_effects=(أثر,),
                planner=lambda _: (أثر,),
                applier=_تطبيقٌ_مُراقَب(حالةُ_الدولة, []),
                operation_key=_مفتاح(),
                compensators=(_معوّض(حالةُ_الدولة, أثر),),
            )
        assert حدّ.consumed_permits.count() == 1


# ═══════════════════════════════════════════════════════════════════════════
# 3 — محاولاتُ تجاوزِ الاختصاص (1G)
# ═══════════════════════════════════════════════════════════════════════════


class Testتجاوزُالاختصاص:
    """قرارُ الجدارِ غيرُ قابلٍ للتجاهلِ من المُنادي — بنيويًّا لا بالاتّفاق."""

    def test_فعلٌقضائيٌّبلاطلبِاختصاصٍيُرفَض(
        self, حدّ: SovereignExecutionBoundary, حالةُ_الدولة: dict[str, str]
    ) -> None:
        أثر = _أثر(EffectKind.WRITE, CASE)
        مُستقبَل: list[SovereignEffect] = []
        with pytest.raises(JurisdictionNotDeclaredError):
            حدّ.execute(
                _طلب(action="issue_ruling", target=CASE, actor=Branch.JUDICIAL),
                declared_effects=(أثر,),
                planner=lambda _: (أثر,),
                applier=_تطبيقٌ_مُراقَب(حالةُ_الدولة, مُستقبَل),
                operation_key=_مفتاح("op-j", "judiciary"),
                compensators=(_معوّض(حالةُ_الدولة, أثر, "OPEN"),),
            )
        assert حالةُ_الدولة[CASE] == "OPEN"
        assert مُستقبَل == []
        assert حدّ.consumed_permits.count() == 0

    def test_نطاقٌمتعارضٌيُرفَضولايُنتِجُأثرًا(
        self, حدّ: SovereignExecutionBoundary, حالةُ_الدولة: dict[str, str]
    ) -> None:
        """محكمةٌ فدراليّةٌ وقضيّةُ ولايةٍ: تعارضٌ يرفعُه الجدارُ ولا يُبتلَع."""
        أثر = _أثر(EffectKind.WRITE, CASE)
        طلبٌ_قضائيّ = JudicialAction(
            action="issue_ruling",
            court_scope="FEDERAL",
            case_scope="STATE",
            actor_scope="FEDERAL",
            target=CASE,
        )
        with pytest.raises(JurisdictionError):
            حدّ.execute(
                _طلب(action="issue_ruling", target=CASE, actor=Branch.JUDICIAL),
                declared_effects=(أثر,),
                planner=lambda _: (أثر,),
                applier=_تطبيقٌ_مُراقَب(حالةُ_الدولة, []),
                operation_key=_مفتاح("op-j2", "judiciary"),
                judicial_action=طلبٌ_قضائيّ,
                compensators=(_معوّض(حالةُ_الدولة, أثر, "OPEN"),),
            )
        assert حالةُ_الدولة[CASE] == "OPEN"

    def test_أثرٌتنفيذيٌّفيمسارٍقضائيٍّيُرفَض(
        self, حدّ: SovereignExecutionBoundary, حالةُ_الدولة: dict[str, str]
    ) -> None:
        """القضاءُ لا يحوّلُ ولا يحذف — والأثرُ يُفحَصُ قبلَ العقدِ لا بعدَه."""
        أثر = _أثر(EffectKind.TRANSFER, CASE)
        with pytest.raises(JurisdictionError):
            حدّ.execute(
                _طلب(action="issue_ruling", target=CASE, actor=Branch.JUDICIAL),
                declared_effects=(أثر,),
                planner=lambda _: (أثر,),
                applier=_تطبيقٌ_مُراقَب(حالةُ_الدولة, []),
                operation_key=_مفتاح("op-j3", "judiciary"),
                judicial_action=_طلبٌ_قضائيّ(),
            )
        assert حالةُ_الدولة[CASE] == "OPEN"

    def test_المسارُالقضائيُّالسليمُيعبرُويُسجّلُمرحلةَالاختصاص(
        self, حدّ: SovereignExecutionBoundary, حالةُ_الدولة: dict[str, str]
    ) -> None:
        أثر = _أثر(EffectKind.WRITE, CASE)
        حصيلة = حدّ.execute(
            _طلب(action="issue_ruling", target=CASE, actor=Branch.JUDICIAL),
            declared_effects=(أثر,),
            planner=lambda _: (أثر,),
            applier=_تطبيقٌ_مُراقَب(حالةُ_الدولة, []),
            operation_key=_مفتاح("op-j4", "judiciary"),
            judicial_action=_طلبٌ_قضائيّ(),
            compensators=(_معوّض(حالةُ_الدولة, أثر, "OPEN"),),
        )
        assert حصيلة.passed(BoundaryStage.JURISDICTION)
        assert حالةُ_الدولة[CASE] == "MUTATED"


# ═══════════════════════════════════════════════════════════════════════════
# 4 — محاولاتُ تجاوزِ الذرّيّة (1H)
# ═══════════════════════════════════════════════════════════════════════════


class Testتجاوزُالذرّيّة:
    """حارسٌ موجودٌ ⇒ حارسٌ مفروض. ولا مفتاحَ يصطنعُه الحدُّ نيابةً عن المُنادي."""

    def test_تنفيذٌبلامفتاحٍيُرفَضقبلَإصدارِأيِّإذن(
        self, حدّ: SovereignExecutionBoundary, حالةُ_الدولة: dict[str, str]
    ) -> None:
        أثر = _أثر()
        مُستقبَل: list[SovereignEffect] = []
        with pytest.raises(OperationKeyRequiredError):
            حدّ.execute(
                _طلب(),
                declared_effects=(أثر,),
                planner=lambda _: (أثر,),
                applier=_تطبيقٌ_مُراقَب(حالةُ_الدولة, مُستقبَل),
                operation_key="op-1",  # type: ignore[arg-type]
                compensators=(_معوّض(حالةُ_الدولة, أثر),),
            )
        assert مُستقبَل == []
        assert حالةُ_الدولة[TARGET] == "1000"
        assert حدّ.consumed_permits.count() == 0, "صُدِرَ إذنٌ لعمليّةٍ بلا حجز."

    def test_التكرارُبالمفتاحِنفسِهلايُعيدُالتطبيق(
        self, حدّ: SovereignExecutionBoundary, حالةُ_الدولة: dict[str, str]
    ) -> None:
        أثر = _أثر()
        مُستقبَل: list[SovereignEffect] = []
        مُطبِّق = _تطبيقٌ_مُراقَب(حالةُ_الدولة, مُستقبَل)
        لوازم = {
            "declared_effects": (أثر,),
            "planner": lambda _: (أثر,),
            "applier": مُطبِّق,
            "operation_key": _مفتاح(),
            "compensators": (_معوّض(حالةُ_الدولة, أثر),),
        }
        أولى = حدّ.execute(_طلب(), **لوازم)  # type: ignore[arg-type]
        حالةُ_الدولة[TARGET] = "1000"
        ثانية = حدّ.execute(_طلب(), **لوازم)  # type: ignore[arg-type]
        assert أولى.is_replay is False
        assert ثانية.is_replay is True
        assert len(مُستقبَل) == 1, "طُبِّقَ الأثرُ مرّتينِ بالمفتاحِ نفسِه."
        assert حالةُ_الدولة[TARGET] == "1000"

    def test_المفتاحُنفسُهبعمليّةٍمختلفةٍيُرفَض(
        self, حدّ: SovereignExecutionBoundary, حالةُ_الدولة: dict[str, str]
    ) -> None:
        """انتحالُ هويّةِ عمليّةٍ برَدِّ مفتاحِها إلى عملٍ آخرَ — يُرفَعُ لا يُبتلَع."""
        أثر = _أثر()
        حدّ.execute(
            _طلب(),
            declared_effects=(أثر,),
            planner=lambda _: (أثر,),
            applier=_تطبيقٌ_مُراقَب(حالةُ_الدولة, []),
            operation_key=_مفتاح(),
            compensators=(_معوّض(حالةُ_الدولة, أثر),),
        )
        آخر = _أثر(EffectKind.CREATE, TARGET)
        with pytest.raises(IdempotencyKeyReuseError):
            حدّ.execute(
                _طلب(action="debit_account"),
                declared_effects=(آخر,),
                planner=lambda _: (آخر,),
                applier=_تطبيقٌ_مُراقَب(حالةُ_الدولة, []),
                operation_key=_مفتاح(),
                compensators=(_معوّض(حالةُ_الدولة, آخر),),
            )


# ═══════════════════════════════════════════════════════════════════════════
# 5 — محاولاتُ تجاوزِ التعويض (1I — ربطًا لا استعادة)
# ═══════════════════════════════════════════════════════════════════════════


class Testتجاوزُالتعويض:
    """المُعلَنُ من متطلَّبِ التعويضِ غيرُ قابلٍ للتجاهل. ولا استعادةَ تُبنى هنا."""

    def test_أثرٌمُغيِّرٌبلاخطّةٍيُرفَض(
        self, حدّ: SovereignExecutionBoundary, حالةُ_الدولة: dict[str, str]
    ) -> None:
        أثر = _أثر()
        مُستقبَل: list[SovereignEffect] = []
        with pytest.raises(CompensationNotDeclaredError):
            حدّ.execute(
                _طلب(),
                declared_effects=(أثر,),
                planner=lambda _: (أثر,),
                applier=_تطبيقٌ_مُراقَب(حالةُ_الدولة, مُستقبَل),
                operation_key=_مفتاح(),
            )
        assert مُستقبَل == []
        assert حالةُ_الدولة[TARGET] == "1000"

    def test_خطّةٌناقصةُالتغطيةِيرفعُها1Iنفسُه(
        self, حدّ: SovereignExecutionBoundary, حالةُ_الدولة: dict[str, str]
    ) -> None:
        """لا يُعادُ فحصُ التغطيةِ في 1M — يُستدعى حرسُ 1I ولا يُنسَخُ منطقُه."""
        أوّل = _أثر(EffectKind.WRITE, TARGET)
        ثانٍ = _أثر(EffectKind.CREATE, TARGET)
        with pytest.raises(UncompensatableEffectError):
            حدّ.execute(
                _طلب(),
                declared_effects=(أوّل, ثانٍ),
                planner=lambda _: (أوّل, ثانٍ),
                applier=_تطبيقٌ_مُراقَب(حالةُ_الدولة, []),
                operation_key=_مفتاح(),
                compensators=(_معوّض(حالةُ_الدولة, أوّل),),
            )
        assert حالةُ_الدولة[TARGET] == "1000"

    def test_قراءةٌمحضةٌلاتحتاجُمعوّضًا(
        self, حدّ: SovereignExecutionBoundary, حالةُ_الدولة: dict[str, str]
    ) -> None:
        """ما لا يُغيِّرُ حالةً لا يُعكَس — ولا يُفرَضُ عليه ما لا معنى له."""
        أثر = _أثر(EffectKind.READ, TARGET)
        حصيلة = حدّ.execute(
            _طلب(action="read_account"),
            declared_effects=(أثر,),
            planner=lambda _: (أثر,),
            applier=lambda _: None,
            operation_key=_مفتاح("op-read"),
        )
        assert حصيلة.compensation_plan is None
        assert not حصيلة.passed(BoundaryStage.COMPENSATION_PLAN)

    def test_عقدٌيخلطُالخارجيَّبالداخليِّيُرفَض(
        self, حدّ: SovereignExecutionBoundary, حالةُ_الدولة: dict[str, str]
    ) -> None:
        """لا ضمانَ لعقدٍ لا تُغطّيه خطّةُ 1I ولا ترتيبُ 1K — فالرفضُ قبلَ التنفيذ."""
        داخليّ = _أثر(EffectKind.WRITE, TARGET)
        خارجيّ = _أثر(EffectKind.EXTERNAL, TARGET)
        with pytest.raises(MixedEffectContractError):
            حدّ.execute(
                _طلب(),
                declared_effects=(داخليّ, خارجيّ),
                planner=lambda _: (داخليّ, خارجيّ),
                applier=_تطبيقٌ_مُراقَب(حالةُ_الدولة, []),
                operation_key=_مفتاح(),
                compensators=(_معوّض(حالةُ_الدولة, داخليّ),),
            )
        assert حالةُ_الدولة[TARGET] == "1000"

    def test_خطّةُ1Iترفضُالعقدَالخارجيَّوحدَها(self) -> None:
        """سندُ قرارِ الرفضِ أعلاه: 1I نفسُها ترفضُ ربطَ خطّةٍ بعقدٍ خارجيّ."""
        from core.sovereignty.contract import bind_contract

        خارجيّ = _أثر(EffectKind.EXTERNAL, TARGET)
        عقد = bind_contract(
            actor=Branch.EXECUTIVE, action="notify", target=TARGET, declared_effects=(خارجيّ,)
        )
        from core.sovereignty.compensation import bind_compensation_plan

        with pytest.raises(IrreversibleEffectError):
            bind_compensation_plan(
                contract=عقد,
                compensators=(
                    Compensator(effect_signature=خارجيّ.signature, apply=lambda: None),
                ),
            )


# ═══════════════════════════════════════════════════════════════════════════
# 6 — محاولاتُ تجاوزِ الصادر (1K)
# ═══════════════════════════════════════════════════════════════════════════


class Testتجاوزُالصادر:
    """الأثرُ الخارجيُّ لا يصلُ مزوّدًا إلّا من الصادر — والمنعُ بنيويٌّ لا فحصٌ لاحق."""

    def test_مُطبِّقُالمُنادِيلايستقبلُأثرًاخارجيًّاأبدًا(
        self, حدّ: SovereignExecutionBoundary, حالةُ_الدولة: dict[str, str]
    ) -> None:
        أثر = _أثر(EffectKind.EXTERNAL, NOTICE)
        مزوّد = مزوّدٌ_مُراقَب()
        مُستقبَل: list[SovereignEffect] = []
        حصيلة = حدّ.execute(
            _طلب(action="notify_citizen", target=NOTICE),
            declared_effects=(أثر,),
            planner=lambda _: (أثر,),
            applier=_تطبيقٌ_مُراقَب(حالةُ_الدولة, مُستقبَل),
            operation_key=_مفتاح("op-ext", "notify"),
            provider=مزوّد,
            payload_of=lambda _: EffectPayload(data={"to": "citizen-1"}),
        )
        assert مُستقبَل == [], "استقبلَ مُطبِّقُ المُنادي أثرًا خارجيًّا."
        assert مزوّد.نداءات == [], "نُودي المزوّدُ من حدِّ التنفيذ."
        assert حالةُ_الدولة[NOTICE] == "NONE"
        assert len(حصيلة.enqueued_effect_ids) == 1

    def test_أثرٌخارجيٌّبلاصادرٍمُهيَّأٍلايُنفَّذ(
        self, حدٌّ_بلا_صادر: SovereignExecutionBoundary, حالةُ_الدولة: dict[str, str]
    ) -> None:
        أثر = _أثر(EffectKind.EXTERNAL, NOTICE)
        مُستقبَل: list[SovereignEffect] = []
        with pytest.raises(OutboxNotConfiguredError):
            حدٌّ_بلا_صادر.execute(
                _طلب(action="notify_citizen", target=NOTICE),
                declared_effects=(أثر,),
                planner=lambda _: (أثر,),
                applier=_تطبيقٌ_مُراقَب(حالةُ_الدولة, مُستقبَل),
                operation_key=_مفتاح("op-ext", "notify"),
            )
        assert مُستقبَل == []
        assert حدٌّ_بلا_صادر.consumed_permits.count() == 0

    def test_أثرٌخارجيٌّبلامزوّدٍأوحمولةٍلايُنفَّذ(
        self, حدّ: SovereignExecutionBoundary, حالةُ_الدولة: dict[str, str]
    ) -> None:
        أثر = _أثر(EffectKind.EXTERNAL, NOTICE)
        with pytest.raises(OutboxNotConfiguredError):
            حدّ.execute(
                _طلب(action="notify_citizen", target=NOTICE),
                declared_effects=(أثر,),
                planner=lambda _: (أثر,),
                applier=_تطبيقٌ_مُراقَب(حالةُ_الدولة, []),
                operation_key=_مفتاح("op-ext2", "notify"),
                provider=مزوّدٌ_مُراقَب(),
            )
        assert حدّ.consumed_permits.count() == 0

    def test_الإدراجُسابقٌلتثبيتِالنجاحِوالتسليمُلميقع(
        self, حدّ: SovereignExecutionBoundary, صادر: SovereignOutbox, حالةُ_الدولة: dict[str, str]
    ) -> None:
        """ترتيبُ 1K مفروضٌ من الحدّ: سجلٌّ مُعلَّقٌ وعمليّةٌ ناجحةٌ ولا تسليم."""
        أثر = _أثر(EffectKind.EXTERNAL, NOTICE)
        حدّ.execute(
            _طلب(action="notify_citizen", target=NOTICE),
            declared_effects=(أثر,),
            planner=lambda _: (أثر,),
            applier=_تطبيقٌ_مُراقَب(حالةُ_الدولة, []),
            operation_key=_مفتاح("op-ext3", "notify"),
            provider=مزوّدٌ_مُراقَب(),
            payload_of=lambda _: EffectPayload(data={"to": "citizen-1"}),
        )
        سجلّات = صادر.ledger.all_records()
        assert len(سجلّات) == 1
        assert سجلّات[0].status is DeliveryStatus.PENDING
        assert سجلّات[0].status.certifies_delivery is False
        عمليّة = حدّ.idempotency_ledger.get(_مفتاح("op-ext3", "notify"))
        assert عمليّة is not None
        assert عمليّة.status is OperationStatus.SUCCEEDED


# ═══════════════════════════════════════════════════════════════════════════
# 7 — الإغلاقُ عندَ الفشل (1J) على الحدّ
# ═══════════════════════════════════════════════════════════════════════════


class Testالإغلاقُعندَالفشل:
    """لا يُدَّعى نجاحٌ لم يقع — والفشلُ يُسجَّلُ ولا يُبتلَع."""

    def test_فشلُالتطبيقِلايُثبَّتُنجاحًا(
        self, حدّ: SovereignExecutionBoundary, حالةُ_الدولة: dict[str, str]
    ) -> None:
        أثر = _أثر()

        def مُطبِّقٌ_يفشل(_: SovereignEffect) -> None:
            raise RuntimeError("انقطاعُ خدمةٍ أثناءَ التطبيق")

        with pytest.raises(IdempotencyError):
            حدّ.execute(
                _طلب(),
                declared_effects=(أثر,),
                planner=lambda _: (أثر,),
                applier=مُطبِّقٌ_يفشل,
                operation_key=_مفتاح("op-fail"),
                compensators=(_معوّض(حالةُ_الدولة, أثر),),
            )
        سجلّ = حدّ.idempotency_ledger.get(_مفتاح("op-fail"))
        assert سجلّ is not None
        assert سجلّ.status is not OperationStatus.SUCCEEDED
        assert حالةُ_الدولة[TARGET] == "1000"


# ═══════════════════════════════════════════════════════════════════════════
# 8 — لا معامَلَ تجاوزٍ: بنيويًّا لا بالإقرار
# ═══════════════════════════════════════════════════════════════════════════


class Testلامعامَلَتجاوز:
    """المعامَلُ الذي لا يوجدُ لا يُستعمَل — والقياسُ على التوقيعِ لا على النيّة."""

    def test_الحدُّبلامعامَلِتجاوزٍواحد(self) -> None:
        assert bypass_parameters_of(SovereignExecutionBoundary) == frozenset()

    def test_كلُّدالّةٍفيالوحدةِبلامعامَلِتجاوز(self) -> None:
        وحدة = REPO_ROOT / "core" / "sovereignty" / "enforcement_boundary.py"
        شجرة = ast.parse(وحدة.read_text(encoding="utf-8"))
        مخالفة: list[str] = []
        for node in ast.walk(شجرة):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            args = node.args
            for a in (*args.posonlyargs, *args.args, *args.kwonlyargs):
                if a.arg in FORBIDDEN_BYPASS_PARAMS:
                    مخالفة.append(f"{node.name}:{a.arg}")
        assert مخالفة == []

    def test_الإقرارُوالقياسُمنمصدرٍواحد(self, حدّ: SovereignExecutionBoundary) -> None:
        assert حدّ.self_check()["bypass_parameters"] == []

    # ─── تضييقُ المسحِ لا يُفقِدُ تغطيةً: مطلوبٌ إثباتًا لا دعوى ───

    def test_معامَلُالتجاوزِفي__init_subclass__يُرصَد(self) -> None:
        """استثناءُ `object` ليسَ إعفاءً بالاسمِ: ما يُعلِنُه المشروعُ يُفحَص."""

        class مُعلِنٌ:
            def __init_subclass__(cls, bypass: bool = False, **kw: object) -> None:
                super().__init_subclass__(**kw)  # type: ignore[arg-type]

        assert "bypass" in bypass_parameters_of(مُعلِنٌ)

    def test_معامَلُالتجاوزِالموروثُعنأصلٍفيالمشروعِيُرصَد(self) -> None:
        """المسحُ يمشي سلسلةَ الوراثةِ كلَّها، فلا يَنجو متجاوزٌ بالتوريثِ."""

        class أصلٌ:
            def يُنفِّذ(self, force: bool = False) -> None: ...

        class فرعٌ(أصلٌ): ...

        assert "force" in bypass_parameters_of(فرعٌ)

    def test_مالاتُقرَأُبصمتُهُمنأعضاءِالمشروعِيُرفَض(self) -> None:
        """عقدُ الإغلاقِ عندَ الفشلِ قائمٌ: لا ابتلاعَ صامتًا لما لا تُقرَأُ بصمتُه."""

        class عمياءُ:
            # قيمةٌ ليستْ بصمةً تجعلُ `inspect.signature` يرفعُ — بلا اعتمادٍ
            # على إصدارِ المفسِّرِ: الرفعُ `ValueError` في 3.12 و`TypeError` في 3.14.
            __signature__ = "not-a-signature"

            def __call__(self) -> None: ...

        class حاملٌ:
            عمياء = عمياءُ()

        with pytest.raises(StaticGuardError):
            bypass_parameters_of(حاملٌ)

    def test_صنفٌعاديٌلايُرفَضُرفضًاكاذبًا(self) -> None:
        """مبنيّاتُ `object` لا تحملُ تجاوزًا، وبعضُها بلا بصمةٍ في 3.12."""

        class فارغٌ: ...

        assert bypass_parameters_of(فارغٌ) == frozenset()

    def test_تنفيذُالحدِّلايقبلُدالّةًحُرّةًبلاآثارٍمُعلَنة(self) -> None:
        """الفرقُ عن `gateway.execute`: لا `Callable[[], T]` مُعتِمةً هنا."""
        توقيع = inspect.signature(SovereignExecutionBoundary.execute)
        for لازم in ("declared_effects", "planner", "applier", "operation_key"):
            assert لازم in توقيع.parameters
            assert توقيع.parameters[لازم].kind is inspect.Parameter.KEYWORD_ONLY
        assert "executor" not in توقيع.parameters


# ═══════════════════════════════════════════════════════════════════════════
# 9 — الحرسُ الساكن: الفرضُ على المصدر
# ═══════════════════════════════════════════════════════════════════════════


class Testالحرسُالساكن:
    """أربعُ قواعدَ لها أسنانٌ حقيقيّةٌ، ونطاقٌ مُعلَنٌ لا مُدَّعًى."""

    def test_النطاقُالمُصرَّحُخالٍمنالمخالفات(self) -> None:
        مخالفات = StaticEnforcementGuard().scan(REPO_ROOT)
        assert [str(m) for m in مخالفات] == []

    @pytest.mark.parametrize(
        ("نص", "قاعدة"),
        [
            ("def act(*, force=False):\n    pass\n", "R1_BYPASS_PARAM"),
            ("def act(*, bypass=None):\n    pass\n", "R1_BYPASS_PARAM"),
            ("provider.deliver(envelope)\n", "R2_DIRECT_PROVIDER_DELIVER"),
            ("ledger.mark_succeeded(key=k)\n", "R3_UNGUARDED_SUCCESS_CLAIM"),
            (
                "ledger.transition(key=k, new_status=OperationStatus.SUCCEEDED)\n",
                "R3_UNGUARDED_SUCCESS_CLAIM",
            ),
            (
                "try:\n    x()\nexcept SovereigntyViolation:\n    pass\n",
                "R4_SWALLOWED_GUARD",
            ),
            (
                "try:\n    x()\nexcept (PermitInvalidError, OutboxError):\n    ...\n",
                "R4_SWALLOWED_GUARD",
            ),
        ],
    )
    def test_لكلِّقاعدةٍأسنان(self, نص: str, قاعدة: str) -> None:
        حرس = StaticEnforcementGuard()
        مخالفات = حرس._scan_tree(ast.parse(نص), "مُصطنَع.py")
        assert [m.rule for m in مخالفات] == [قاعدة]

    @pytest.mark.parametrize(
        "نص",
        [
            # تخفيضُ حالةٍ بعدَ تعويضٍ ناجحٍ — نقيضُ التجاوزِ لا صورتُه
            "ledger.transition(key=k, new_status=OperationStatus.FAILED_RETRYABLE)\n",
            # ابتلاعُ استثناءٍ ليس حرسًا — خارجَ نطاقِ القاعدة
            "try:\n    x()\nexcept ValueError:\n    pass\n",
            # التعامُلُ مع استثناءِ حرسٍ لا ابتلاعُه
            "try:\n    x()\nexcept SovereigntyViolation:\n    raise\n",
            "def act(*, permit=None):\n    pass\n",
        ],
    )
    def test_لاإشارةَكاذبةٌإلىماليسَتجاوزًا(self, نص: str) -> None:
        مخالفات = StaticEnforcementGuard()._scan_tree(ast.parse(نص), "مُصطنَع.py")
        assert مخالفات == []

    def test_الحرسُيرفضُنطاقًاغيرَموجود(self) -> None:
        """الحرسُ الذي يفحصُ فراغًا يُنتِجُ خلوًّا كاذبًا — فالرفضُ صريح."""
        with pytest.raises(StaticGuardError):
            StaticEnforcementGuard(scope=("لا/يوجد",)).scan(REPO_ROOT)

    def test_الحرسُيُعلِنُحدودَهولايزعمُحراسةَالمشروعِكلِّه(self) -> None:
        تقرير = StaticEnforcementGuard().self_check(REPO_ROOT)
        assert تقرير["claims_whole_repository_guarded"] is False
        assert تقرير["detects_indirect_calls"] is False
        assert تقرير["guarded_scope"] == list(DEFAULT_GUARDED_SCOPE)
        assert تقرير["clean"] is True
        assert int(تقرير["files_scanned"]) > 0  # type: ignore[call-overload]

    def test_الإعفاءاتُمُعلَنةٌلامخفيّة(self) -> None:
        تقرير = StaticEnforcementGuard().self_check(REPO_ROOT)
        إعفاءات = تقرير["declared_exemptions"]
        assert isinstance(إعفاءات, dict)
        assert إعفاءات["R2_DIRECT_PROVIDER_DELIVER"] == ["core/sovereignty/outbox.py"]


# ═══════════════════════════════════════════════════════════════════════════
# 10 — إثباتٌ خصميّ: تعطيلُ حرسٍ يُسقِطُ اختبارَه
# ═══════════════════════════════════════════════════════════════════════════


class Testإثباتٌخصميّ:
    """الحرسُ هو ما يمنع — لا الترتيبُ ولا الحظّ.

    كلُّ اختبارٍ هنا يُعطّلُ حرسًا واحدًا ثمَّ يُثبِتُ أنَّ التجاوزَ **صار
    ممكنًا**. فلو حُذِفَ الحرسُ من الكودِ لسقطَ اختبارُ المنعِ المقابل، ولو
    أُعيدَ لعادت الحماية. وهذا هو معنى «الحرسُ مفروض».
    """

    def test_تعطيلُحرسِالمفتاحِيُتيحُتنفيذًابلاذرّيّة(
        self,
        حدّ: SovereignExecutionBoundary,
        حالةُ_الدولة: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        أثر = _أثر()
        monkeypatch.setattr(
            SovereignExecutionBoundary, "_guard_operation_key", lambda self, key: None
        )
        with pytest.raises(Exception) as خطأ:
            حدّ.execute(
                _طلب(),
                declared_effects=(أثر,),
                planner=lambda _: (أثر,),
                applier=_تطبيقٌ_مُراقَب(حالةُ_الدولة, []),
                operation_key="op-1",  # type: ignore[arg-type]
                compensators=(_معوّض(حالةُ_الدولة, أثر),),
            )
        # لم يُرفَع خطأُ الحدِّ بعدَ التعطيل — بل انكسرَ المسارُ أعمقَ بلا حراسة.
        assert not isinstance(خطأ.value, OperationKeyRequiredError)

    def test_تعطيلُحرسِالاختصاصِيُتيحُفعلًاقضائيًّابلافحص(
        self,
        حدّ: SovereignExecutionBoundary,
        حالةُ_الدولة: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        أثر = _أثر(EffectKind.WRITE, CASE)
        monkeypatch.setattr(
            SovereignExecutionBoundary, "_guard_jurisdiction", lambda self, r, e, j: ()
        )
        حصيلة = حدّ.execute(
            _طلب(action="issue_ruling", target=CASE, actor=Branch.JUDICIAL),
            declared_effects=(أثر,),
            planner=lambda _: (أثر,),
            applier=_تطبيقٌ_مُراقَب(حالةُ_الدولة, []),
            operation_key=_مفتاح("op-adv-j", "judiciary"),
            compensators=(_معوّض(حالةُ_الدولة, أثر, "OPEN"),),
        )
        assert not حصيلة.passed(BoundaryStage.JURISDICTION)
        assert حالةُ_الدولة[CASE] == "MUTATED", "الحرسُ المُعطَّلُ ما زالَ يمنع — لم يُقَس."

    def test_تعطيلُحرسِالتعويضِيُتيحُأثرًامُغيِّرًابلاخطّة(
        self,
        حدّ: SovereignExecutionBoundary,
        حالةُ_الدولة: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        أثر = _أثر()
        monkeypatch.setattr(
            SovereignExecutionBoundary,
            "_guard_compensation",
            lambda self, contract, compensators: (None, ()),
        )
        حدّ.execute(
            _طلب(),
            declared_effects=(أثر,),
            planner=lambda _: (أثر,),
            applier=_تطبيقٌ_مُراقَب(حالةُ_الدولة, []),
            operation_key=_مفتاح("op-adv-c"),
        )
        assert حالةُ_الدولة[TARGET] == "MUTATED"

    def test_تعطيلُالتوزيعِالمحروسِيُسلِّمُالأثرَالخارجيَّللمُنادي(
        self,
        حدّ: SovereignExecutionBoundary,
        حالةُ_الدولة: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """أخطرُ تجاوزٍ: لو لم يُوجَد التوزيعُ لَوصلَ الأثرُ الخارجيُّ إلى المُنادي."""
        أثر = _أثر(EffectKind.EXTERNAL, NOTICE)
        مُستقبَل: list[SovereignEffect] = []
        monkeypatch.setattr(
            SovereignExecutionBoundary,
            "_route_effect",
            lambda self, **kwargs: kwargs["applier"],
        )
        حدّ.execute(
            _طلب(action="notify_citizen", target=NOTICE),
            declared_effects=(أثر,),
            planner=lambda _: (أثر,),
            applier=_تطبيقٌ_مُراقَب(حالةُ_الدولة, مُستقبَل),
            operation_key=_مفتاح("op-adv-x", "notify"),
            provider=مزوّدٌ_مُراقَب(),
            payload_of=lambda _: EffectPayload(data={"to": "citizen-1"}),
        )
        assert مُستقبَل == [أثر], "التوزيعُ المُعطَّلُ ما زالَ يمنع — لم يُقَس."
        assert حالةُ_الدولة[NOTICE] == "MUTATED"


# ═══════════════════════════════════════════════════════════════════════════
# 11 — حدودُ الدعوى: ما لا يفرضُه هذا الحدّ
# ═══════════════════════════════════════════════════════════════════════════


class Testحدودُالدعوى:
    """الصدقُ في الحدِّ نفسِه: ما لا يُفرَضُ يُعلَن، ولا يُدَّعى فرضٌ شامل."""

    def test_الحدُّلايزعمُحراسةَالمشروعِكلِّه(self, حدّ: SovereignExecutionBoundary) -> None:
        assert حدّ.self_check()["claims_whole_repository_guarded"] is False

    def test_مسٌّمباشرٌللحالةِيتجاوزُالحدَّفعلًا(self, حالةُ_الدولة: dict[str, str]) -> None:
        """حدٌّ مُعلَنٌ لا ثغرةٌ مخفيّة: بايثون لا تملكُ عزلَ قدرات.

        مَن استوردَ مُغيِّرَ حالةٍ ونادَاه مباشرةً لم يمرَّ بالحدّ. وهذا يُقاسُ
        هنا صراحةً لئلّا يُقرأَ نجاحُ الاختباراتِ فرضًا شاملًا. والحرسُ الساكنُ
        يُضيّقُ هذا الباب على النطاقِ المُصرَّحِ به، ولا يُغلِقُه في كلِّ المشروع.
        """
        حالةُ_الدولة[TARGET] = "MUTATED_WITHOUT_BOUNDARY"
        assert حالةُ_الدولة[TARGET] == "MUTATED_WITHOUT_BOUNDARY"

    def test_الحدُّلايُبنىبلاسجلِّذرّيّةٍحقيقيّ(self, بوابة: SovereignGateway) -> None:
        with pytest.raises(BoundaryConfigurationError):
            SovereignExecutionBoundary(gateway=بوابة, idempotency_ledger=None)  # type: ignore[arg-type]

    def test_الرفضُيُعَدُّولايُخفى(
        self, حدّ: SovereignExecutionBoundary, حالةُ_الدولة: dict[str, str]
    ) -> None:
        أثر = _أثر()
        with pytest.raises(CompensationNotDeclaredError):
            حدّ.execute(
                _طلب(),
                declared_effects=(أثر,),
                planner=lambda _: (أثر,),
                applier=_تطبيقٌ_مُراقَب(حالةُ_الدولة, []),
                operation_key=_مفتاح(),
            )
        assert حدّ.self_check()["rejections"] == {BoundaryStage.COMPENSATION_PLAN.value: 1}
