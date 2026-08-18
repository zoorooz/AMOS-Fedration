"""الهدف: قياسُ عقدِ التنفيذِ السياديّ — هل يُمنَع الأثرُ غيرُ المأذونِ به فعلًا؟

النطاق: `core/sovereignty/contract.py` و`SovereignGateway.execute_under_contract`.
المالك: tests/sovereignty/ — ديوان التدقيق
تاريخ الإنشاء: 2026-08-18
تاريخ آخر تعديل: 2026-08-18

القاعدة 12 تمنع اعتبارَ وجودِ الملفِّ دليلًا على القدرة، والقاعدة 13 تمنع
الاكتفاءَ باختبارِ وحدةٍ يستدعي دالّةً مباشرة. فالقياسُ هنا **من البوابةِ
نفسِها**: تُبنى حالةُ دولةٍ حقيقيّةٌ (قاموسُ موارد)، ويُمرَّر مُنفِّذٌ يحاول
مسَّها، ثمّ **يُقاس القاموس** بعد ذلك. المنعُ يُثبَت بأنّ الحالةَ لم تتغيّر —
لا بأنّ استثناءً ارتفع.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization

from core.constitutional_engine.engine import ConstitutionalEngine
from core.constitutional_engine.ledger import ConstitutionalLedger
from core.constitutional_engine.model import ActionRequest, Branch
from core.sovereignty import crown as crown_module
from core.sovereignty.contract import (
    ContractBreach,
    ContractError,
    EffectKind,
    EffectOutOfScopeError,
    ExecutionContract,
    SovereignEffect,
    bind_contract,
    digest_of_payload,
    in_scope,
)
from core.sovereignty.gateway import FORBIDDEN_BYPASS_PARAMS, SovereignGateway
from core.sovereignty.security_events import SecurityEventKind, SecurityEventSeverity

TARGET = "treasury/account-A"


# ═══════════════════════════════════════════════════════════════════════════
# تجهيزات
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture()
def ملكٌ_مُنصَّب(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """تاجٌ حقيقيٌّ في مسارٍ مؤقّت — لا يمسُّ سجلَّ الدولةِ الحقيقيَّ بحال."""
    registry = tmp_path / "CROWN_KEYS.json"
    monkeypatch.setattr(crown_module, "CROWN_KEYS_PATH", registry)
    private_out = tmp_path / "vault" / "crown.pem"
    crown_module.provision_crown(private_out, registry_path=registry)
    return serialization.load_pem_private_key(private_out.read_bytes(), password=None)


@pytest.fixture()
def بوابة(tmp_path: Path) -> SovereignGateway:
    ledger = ConstitutionalLedger(tmp_path / "ledger.jsonl")
    return SovereignGateway(ConstitutionalEngine(ledger=ledger))


@pytest.fixture()
def حالةُ_الدولة() -> dict[str, str]:
    """حالةٌ حقيقيّةٌ يُقاس عليها الوقوعُ والمنع — لا مُتتبِّعُ استدعاءات."""
    return {
        "treasury/account-A": "1000",
        "treasury/account-B": "50",
        "royal/crown-authority": "ABSOLUTE",
    }


def _طلب(action: str = "credit_account", target: str = TARGET) -> ActionRequest:
    return ActionRequest(
        actor=Branch.EXECUTIVE,
        action=action,
        target=target,
        channel="official",
    )


def _مُطبِّق(state: dict[str, str]):
    """المُطبِّقُ الوحيدُ الذي يملك مسًّا بالحالة — البوابةُ وحدها تستدعيه."""

    def apply(effect: SovereignEffect) -> None:
        if effect.kind is EffectKind.DELETE:
            state.pop(effect.resource, None)
        elif effect.kind is not EffectKind.READ:
            state[effect.resource] = effect.detail or "MUTATED"

    return apply


# ═══════════════════════════════════════════════════════════════════════════
# 1) الأثرُ نفسُه: لا أثرَ مُبهَم
# ═══════════════════════════════════════════════════════════════════════════

class Testالأثرُالسياديّ:
    def test_أثرٌ_بلا_موردٍ_يُرفَض(self) -> None:
        with pytest.raises(ContractError):
            SovereignEffect(kind=EffectKind.WRITE, resource="   ")

    def test_الأثرُ_غيرُ_قابلٍ_للتعديلِ_بعد_إنشائه(self) -> None:
        أثر = SovereignEffect(kind=EffectKind.WRITE, resource=TARGET)
        with pytest.raises((AttributeError, TypeError)):
            أثر.resource = "treasury/account-B"  # type: ignore[misc]

    def test_القراءةُ_وحدَها_غيرُ_ماسّة(self) -> None:
        assert EffectKind.READ.is_mutating is False
        for kind in EffectKind:
            if kind is not EffectKind.READ:
                assert kind.is_mutating is True

    def test_لكلِّ_نوعٍ_اسمٌ_عربيّ(self) -> None:
        assert all(EffectKind(k).arabic for k in EffectKind)

    def test_البصمةُ_تميّز_النوعَ_عن_المورد(self) -> None:
        كتابة = SovereignEffect(kind=EffectKind.WRITE, resource=TARGET)
        حذف = SovereignEffect(kind=EffectKind.DELETE, resource=TARGET)
        assert كتابة.signature != حذف.signature

    def test_التفصيلُ_لا_يُغيّر_البصمة(self) -> None:
        """وإلّا صار كلُّ اختلافٍ في وصفٍ نصّيٍّ خرقًا للعقد، فيُعطَّل العقد."""
        a = SovereignEffect(kind=EffectKind.WRITE, resource=TARGET, detail="1100")
        b = SovereignEffect(kind=EffectKind.WRITE, resource=TARGET, detail="1200")
        assert a.signature == b.signature

    def test_بصمةُ_الحمولةِ_تُخزَّن_لا_الحمولة(self) -> None:
        بصمة = digest_of_payload("سرٌّ سياديّ")
        assert len(بصمة) == 64 and "سرّ" not in بصمة
        assert digest_of_payload(b"x") == digest_of_payload("x")


# ═══════════════════════════════════════════════════════════════════════════
# 2) النطاق: الإذنُ بهدفٍ ليس إذنًا بما سواه
# ═══════════════════════════════════════════════════════════════════════════

class Testحدُّالنطاق:
    def test_المورد_نفسُه_داخلَ_النطاق(self) -> None:
        assert in_scope(TARGET, TARGET) is True

    def test_الفرعُ_داخلَ_النطاق(self) -> None:
        assert in_scope(f"{TARGET}/balance", TARGET) is True

    def test_الجارُ_المُتشابهُ_اسمًا_خارجَ_النطاق(self) -> None:
        """`account-A2` ليس فرعًا من `account-A` — والبادئةُ وحدها فخٌّ معروف."""
        assert in_scope("treasury/account-A2", TARGET) is False

    def test_هدفٌ_فارغٌ_لا_يشمل_شيئًا(self) -> None:
        assert in_scope("treasury/account-A", "") is False

    def test_ربطُ_عقدٍ_بأثرٍ_خارجَ_الهدفِ_يُرفَض(self) -> None:
        with pytest.raises(EffectOutOfScopeError):
            bind_contract(
                actor="EXECUTIVE",
                action="credit_account",
                target=TARGET,
                declared_effects=(
                    SovereignEffect(kind=EffectKind.WRITE, resource="treasury/account-B"),
                ),
            )

    def test_عقدٌ_بلا_أثرٍ_مُعلَنٍ_يُرفَض(self) -> None:
        """العقدُ الفارغُ إذنٌ مفتوحٌ متنكّرٌ في صورةِ عقد."""
        with pytest.raises(ContractError):
            bind_contract(actor="EXECUTIVE", action="a", target=TARGET, declared_effects=())

    def test_رقمُ_العقدِ_مُشتقٌّ_من_مضمونِه(self) -> None:
        كيف = dict(actor="EXECUTIVE", action="credit_account", target=TARGET)
        أ = bind_contract(
            **كيف,
            declared_effects=(SovereignEffect(kind=EffectKind.WRITE, resource=TARGET),),
        )
        ب = bind_contract(
            **كيف,
            declared_effects=(SovereignEffect(kind=EffectKind.WRITE, resource=TARGET),),
        )
        ج = bind_contract(
            **كيف,
            declared_effects=(SovereignEffect(kind=EffectKind.DELETE, resource=TARGET),),
        )
        assert أ.contract_id == ب.contract_id
        assert أ.contract_id != ج.contract_id

    def test_العقدُ_لا_يُوسَّع_بعد_ربطِه(self) -> None:
        عقد = bind_contract(
            actor="EXECUTIVE",
            action="a",
            target=TARGET,
            declared_effects=(SovereignEffect(kind=EffectKind.WRITE, resource=TARGET),),
        )
        with pytest.raises((AttributeError, TypeError)):
            عقد.declared_effects = ()  # type: ignore[misc]

    def test_الآثارُ_الماسّةُ_تُميَّز_عن_القراءة(self) -> None:
        عقد = bind_contract(
            actor="EXECUTIVE",
            action="a",
            target=TARGET,
            declared_effects=(
                SovereignEffect(kind=EffectKind.READ, resource=TARGET),
                SovereignEffect(kind=EffectKind.WRITE, resource=f"{TARGET}/balance"),
            ),
        )
        assert len(عقد.declared_effects) == 2
        assert len(عقد.mutating_effects) == 1


# ═══════════════════════════════════════════════════════════════════════════
# 3) القياسُ من البوابة: هل تغيّرت حالةُ الدولة؟
# ═══════════════════════════════════════════════════════════════════════════

class Testالتنفيذُبعقدٍمنالبوابة:
    def test_الأثرُ_المُعلَنُ_يقع_فعلًا(
        self, بوابة: SovereignGateway, حالةُ_الدولة: dict[str, str]
    ) -> None:
        مُعلَن = (SovereignEffect(kind=EffectKind.WRITE, resource=TARGET, detail="1100"),)
        حصيلة = بوابة.execute_under_contract(
            _طلب(),
            declared_effects=مُعلَن,
            planner=lambda _c: مُعلَن,
            applier=_مُطبِّق(حالةُ_الدولة),
        )
        assert حالةُ_الدولة[TARGET] == "1100"
        assert حصيلة.applied_signatures == (f"WRITE:{TARGET}",)
        assert حصيلة.contract.contract_id.startswith("EC-")

    def test_أثرٌ_غيرُ_مُعلَنٍ_لا_يمسُّ_الحالة(
        self, بوابة: SovereignGateway, حالةُ_الدولة: dict[str, str]
    ) -> None:
        """جوهرُ 1E: مأذونٌ له بحسابٍ حاول حسابًا آخر — فلم يقع شيء."""
        مُعلَن = (SovereignEffect(kind=EffectKind.WRITE, resource=TARGET, detail="1100"),)
        مُهرَّب = SovereignEffect(
            kind=EffectKind.TRANSFER, resource="treasury/account-B", detail="0"
        )
        with pytest.raises(ContractBreach):
            بوابة.execute_under_contract(
                _طلب(),
                declared_effects=مُعلَن,
                planner=lambda _c: (*مُعلَن, مُهرَّب),
                applier=_مُطبِّق(حالةُ_الدولة),
            )
        assert حالةُ_الدولة["treasury/account-B"] == "50"

    def test_المنعُ_سابقٌ_فلا_يقع_حتّى_الأثرُ_المشروعُ_المرافق(
        self, بوابة: SovereignGateway, حالةُ_الدولة: dict[str, str]
    ) -> None:
        """`planner` يُخطّط ولا يُطبّق، فالفحصُ يسبق تطبيقَ أوّلِ أثرٍ في الحزمة."""
        مُعلَن = (SovereignEffect(kind=EffectKind.WRITE, resource=TARGET, detail="1100"),)
        with pytest.raises(ContractBreach):
            بوابة.execute_under_contract(
                _طلب(),
                declared_effects=مُعلَن,
                planner=lambda _c: (
                    *مُعلَن,
                    SovereignEffect(kind=EffectKind.DELETE, resource="treasury/account-B"),
                ),
                applier=_مُطبِّق(حالةُ_الدولة),
            )
        assert حالةُ_الدولة[TARGET] == "1000"

    def test_سلطةُ_التاجِ_لا_تُمَسُّ_عبر_تنفيذٍ_تنفيذيّ(
        self, بوابة: SovereignGateway, حالةُ_الدولة: dict[str, str]
    ) -> None:
        with pytest.raises(ContractBreach):
            بوابة.execute_under_contract(
                _طلب(),
                declared_effects=(SovereignEffect(kind=EffectKind.WRITE, resource=TARGET),),
                planner=lambda _c: (
                    SovereignEffect(kind=EffectKind.WRITE, resource="royal/crown-authority"),
                ),
                applier=_مُطبِّق(حالةُ_الدولة),
            )
        assert حالةُ_الدولة["royal/crown-authority"] == "ABSOLUTE"

    def test_إعلانُ_أثرٍ_خارجَ_الهدفِ_يُرفَض_قبل_التقييمِ_الدستوريّ(
        self, بوابة: SovereignGateway, حالةُ_الدولة: dict[str, str]
    ) -> None:
        """لا حكمَ ولا أثرَ في السجل: الرفضُ عند الربطِ لا بعد التنفيذ."""
        with pytest.raises(EffectOutOfScopeError):
            بوابة.execute_under_contract(
                _طلب(),
                declared_effects=(
                    SovereignEffect(kind=EffectKind.WRITE, resource="treasury/account-B"),
                ),
                planner=lambda _c: (),
                applier=_مُطبِّق(حالةُ_الدولة),
            )
        assert بوابة.records == ()
        assert بوابة.contracts == ()
        assert بوابة.security_log.events == ()

    def test_المُطبِّقُ_لا_يُستدعى_على_أثرٍ_غيرِ_مشمول(
        self, بوابة: SovereignGateway
    ) -> None:
        مطبَّقة: list[str] = []
        مُعلَن = (SovereignEffect(kind=EffectKind.WRITE, resource=TARGET),)
        with pytest.raises(ContractBreach):
            بوابة.execute_under_contract(
                _طلب(),
                declared_effects=مُعلَن,
                planner=lambda _c: (
                    SovereignEffect(kind=EffectKind.DELETE, resource="treasury/account-B"),
                ),
                applier=lambda e: مطبَّقة.append(e.signature),
            )
        assert مطبَّقة == []

    def test_العقدُ_يصل_إلى_المُخطِّطِ_ليقرأ_حدودَه(self, بوابة: SovereignGateway) -> None:
        مرئيّ: list[ExecutionContract] = []
        مُعلَن = (SovereignEffect(kind=EffectKind.READ, resource=TARGET),)
        بوابة.execute_under_contract(
            _طلب(action="read_account"),
            declared_effects=مُعلَن,
            planner=lambda c: (مرئيّ.append(c), مُعلَن)[1],
            applier=lambda _e: None,
        )
        assert مرئيّ and مرئيّ[0].target == TARGET

    def test_القيمةُ_المُرجَعةُ_تُشتقُّ_من_الآثارِ_لا_من_المُنفِّذ(
        self, بوابة: SovereignGateway
    ) -> None:
        مُعلَن = (SovereignEffect(kind=EffectKind.READ, resource=TARGET),)
        حصيلة = بوابة.execute_under_contract(
            _طلب(action="read_account"),
            declared_effects=مُعلَن,
            planner=lambda _c: مُعلَن,
            applier=lambda _e: None,
            value_of=lambda effects: len(effects),
        )
        assert حصيلة.value == 1

    def test_مُخطِّطٌ_لا_يفعل_شيئًا_مسموحٌ_به_ويُعلَن_صراحة(
        self, بوابة: SovereignGateway
    ) -> None:
        """الإذنُ ليس إلزامًا: عدمُ الفعلِ يُسجَّل بآثارٍ مُطبَّقةٍ صفر، لا يُخفى."""
        حصيلة = بوابة.execute_under_contract(
            _طلب(),
            declared_effects=(SovereignEffect(kind=EffectKind.WRITE, resource=TARGET),),
            planner=lambda _c: (),
            applier=lambda _e: None,
        )
        assert حصيلة.applied_effects == ()


# ═══════════════════════════════════════════════════════════════════════════
# 4) الأثرُ التدقيقيّ: المخالفةُ تُكتَب ولا تُبتلَع
# ═══════════════════════════════════════════════════════════════════════════

class Testالأثرُالتدقيقيّ:
    def _خرق(self, بوابة: SovereignGateway) -> None:
        with pytest.raises(ContractBreach):
            بوابة.execute_under_contract(
                _طلب(),
                declared_effects=(SovereignEffect(kind=EffectKind.WRITE, resource=TARGET),),
                planner=lambda _c: (
                    SovereignEffect(kind=EffectKind.DELETE, resource="treasury/account-B"),
                ),
                applier=lambda _e: None,
            )

    def test_الخرقُ_يُسجَّل_حدثًا_أمنيًّا_حرجًا(self, بوابة: SovereignGateway) -> None:
        self._خرق(بوابة)
        حدث = بوابة.security_log.events[-1]
        assert حدث.kind is SecurityEventKind.EXECUTION_CONTRACT_BREACH
        assert حدث.severity is SecurityEventSeverity.CRITICAL

    def test_الخرقُ_يُثبَّت_في_السجلِّ_الدستوريِّ_لا_في_الذاكرةِ_فحسب(
        self, بوابة: SovereignGateway
    ) -> None:
        """القاعدة 17: مصدرُ الحقيقةِ التشغيليُّ ليس الذاكرة."""
        self._خرق(بوابة)
        assert بوابة.security_log.events[-1].ledger_entry_hash

    def test_الخرقُ_يُكتَب_أثرًا_في_سجلِّ_البوابة(self, بوابة: SovereignGateway) -> None:
        self._خرق(بوابة)
        أخير = بوابة.records[-1]
        assert أخير.decision == "CONTRACT_BREACH"
        assert أخير.executed is False

    def test_رسالةُ_الخرقِ_تُسمّي_الأثرَ_المخالفَ_ولا_تُلمِّح(
        self, بوابة: SovereignGateway
    ) -> None:
        with pytest.raises(ContractBreach, match="treasury/account-B"):
            بوابة.execute_under_contract(
                _طلب(),
                declared_effects=(SovereignEffect(kind=EffectKind.WRITE, resource=TARGET),),
                planner=lambda _c: (
                    SovereignEffect(kind=EffectKind.DELETE, resource="treasury/account-B"),
                ),
                applier=lambda _e: None,
            )

    def test_أثرُ_الإذنِ_السابقُ_لا_يُعدَّل_عند_الخرق(self, بوابة: SovereignGateway) -> None:
        """القاعدة 22: الأثرُ المُثبَّتُ لا يُمَسّ — يُلحَق به أثرٌ ثانٍ فحسب.

        وهذا يكشف حدًّا حقيقيًّا: البوابةُ تكتب أثرَ `executed=True` **قبل**
        استدعاءِ المُنفِّذ. فالسجلُّ يقول «نُفِّذ» ثمّ يقول «خُرِق العقد» — ولا
        يُصحَّح الأوّلُ بحذفٍ. تصحيحُ دلالةِ `executed` عملُ 1I (Fail-Closed).
        """
        self._خرق(بوابة)
        قرارات = [r.decision for r in بوابة.records]
        assert قرارات[-1] == "CONTRACT_BREACH"
        assert len(قرارات) >= 2

    def test_الفحصُ_الذاتيُّ_يُعلن_ما_نُفِّذ_بلا_عقد(
        self, بوابة: SovereignGateway, حالةُ_الدولة: dict[str, str]
    ) -> None:
        """لا يُخفى بقاءُ المسارِ القديم: يُعَدُّ ويُعلَن."""
        بوابة.execute(_طلب(action="read_account"), lambda: "EXECUTED")
        assert بوابة.self_check()["uncontracted_executions"] == 1
        assert بوابة.self_check()["contracted_executions"] == 0

        مُعلَن = (SovereignEffect(kind=EffectKind.WRITE, resource=TARGET),)
        بوابة.execute_under_contract(
            _طلب(),
            declared_effects=مُعلَن,
            planner=lambda _c: مُعلَن,
            applier=_مُطبِّق(حالةُ_الدولة),
        )
        فحص = بوابة.self_check()
        assert فحص["contracted_executions"] == 1
        assert فحص["uncontracted_executions"] == 1

    def test_طلبان_متطابقان_يُعدّان_اثنين_لا_واحدًا(self, بوابة: SovereignGateway) -> None:
        """البصمةُ تتكرّر عند تطابقِ الطلب، فالعدُّ بالموضعِ لا بالبصمة."""
        for _ in range(2):
            بوابة.execute(_طلب(action="read_account"), lambda: "EXECUTED")
        assert بوابة.self_check()["uncontracted_executions"] == 2


# ═══════════════════════════════════════════════════════════════════════════
# 5) مقاومةُ التجاوز
# ═══════════════════════════════════════════════════════════════════════════

class Testمقاومةُالتجاوز:
    def test_لا_معامل_تجاوزٍ_في_التوقيع(self) -> None:
        import inspect

        for fn in (SovereignGateway.execute_under_contract, bind_contract):
            params = set(inspect.signature(fn).parameters)
            assert not (params & FORBIDDEN_BYPASS_PARAMS), fn.__name__

    def test_المنعُ_الدستوريُّ_يسبق_العقد(
        self, بوابة: SovereignGateway, حالةُ_الدولة: dict[str, str]
    ) -> None:
        """فعلٌ ملكيٌّ خالصٌ من فرعٍ تابعٍ يُمنَع ولو كان عقدُه سليمًا تمامًا."""
        from core.sovereignty.gateway import SovereigntyViolation

        طلب = ActionRequest(
            actor=Branch.EXECUTIVE,
            action="amend_constitution",
            target=TARGET,
            channel="official",
        )
        مُعلَن = (SovereignEffect(kind=EffectKind.WRITE, resource=TARGET),)
        with pytest.raises(SovereigntyViolation) as exc:
            بوابة.execute_under_contract(
                طلب,
                declared_effects=مُعلَن,
                planner=lambda _c: مُعلَن,
                applier=_مُطبِّق(حالةُ_الدولة),
            )
        assert not isinstance(exc.value, ContractBreach)
        assert حالةُ_الدولة[TARGET] == "1000"
        assert بوابة.records[-1].executed is False

    def test_العقودُ_تُقرَأ_ولا_تُعدَّل_من_خارجِ_البوابة(
        self, بوابة: SovereignGateway
    ) -> None:
        مُعلَن = (SovereignEffect(kind=EffectKind.READ, resource=TARGET),)
        بوابة.execute_under_contract(
            _طلب(action="read_account"),
            declared_effects=مُعلَن,
            planner=lambda _c: مُعلَن,
            applier=lambda _e: None,
        )
        قبل = len(بوابة.contracts)
        assert isinstance(بوابة.contracts, tuple)
        with pytest.raises((AttributeError, TypeError)):
            بوابة.contracts.append(None)  # type: ignore[attr-defined]
        assert len(بوابة.contracts) == قبل

    def test_العقدُ_والحصيلةُ_يُسردان_للتدقيق(self, بوابة: SovereignGateway) -> None:
        """أثرٌ لا يُسرَد لا يُدقَّق — فالسردُ جزءٌ من القدرة لا زينة."""
        مُعلَن = (
            SovereignEffect(
                kind=EffectKind.WRITE,
                resource=TARGET,
                detail="1100",
                payload_digest=digest_of_payload("1100"),
            ),
        )
        حصيلة = بوابة.execute_under_contract(
            _طلب(),
            declared_effects=مُعلَن,
            planner=lambda _c: مُعلَن,
            applier=lambda _e: None,
        )
        سرد_العقد = حصيلة.contract.as_dict()
        assert سرد_العقد["target"] == TARGET
        assert سرد_العقد["declared_effects"][0]["kind"] == "WRITE"
        assert سرد_العقد["declared_effects"][0]["payload_digest"]
        سرد_الحصيلة = حصيلة.as_dict()
        assert سرد_الحصيلة["contract_id"] == حصيلة.contract.contract_id
        assert len(سرد_الحصيلة["applied_effects"]) == 1

    def test_وحدةُ_العقدِ_لا_تُنفّذ_شيئًا_بنفسِها(self) -> None:
        """القاعدة 5: لا Engine ثالث. `contract.py` وصفٌ وقياسٌ لا مُنفِّذ."""
        نص = Path("core/sovereignty/contract.py").read_text(encoding="utf-8")
        for ممنوع in ("subprocess", "os.system", "def execute(", "requests."):
            assert ممنوع not in نص, ممنوع

    def test_التصديرُ_من_حزمةِ_السيادةِ_قائم(self) -> None:
        import core.sovereignty as pkg

        for name in ("SovereignEffect", "ExecutionContract", "bind_contract", "EffectKind"):
            assert getattr(pkg, name) is not None
            assert name in pkg.__all__


# ═══════════════════════════════════════════════════════════════════════════
# 6) المسارُ القديمُ باقٍ يعمل (القاعدتان 3 و 11)
# ═══════════════════════════════════════════════════════════════════════════

class Testعدمُهدمالأصول:
    def test_execute_القديمةُ_ما_زالت_تعمل(self, بوابة: SovereignGateway) -> None:
        assert بوابة.execute(_طلب(action="read_account"), lambda: "EXECUTED") == "EXECUTED"

    def test_الجسرُ_الفدراليُّ_ما_زال_يمرُّ_من_البوابة(self, ملكٌ_مُنصَّب) -> None:
        """`ConstitutionalAuthorizer.guard` يعتمد `execute(request, executor)`."""
        import inspect

        sig = inspect.signature(SovereignGateway.execute)
        assert list(sig.parameters)[1:3] == ["request", "executor"]
