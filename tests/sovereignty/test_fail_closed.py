"""الهدف: قياسُ الإغلاقِ عند الفشل (1J) — هل تمتنع الدولةُ عن ادِّعاءِ تنفيذٍ لم يكتمل؟

النطاق: `core/sovereignty/fail_closed.py` و`SovereignGateway` — دلالةُ
`ExecutionRecord.executed` وإنفاذُ Fail-Closed في مسارِ التنفيذِ نفسِه.
المالك: tests/sovereignty/ — ديوان التدقيق
تاريخ الإنشاء: 2026-08-18
تاريخ آخر تعديل: 2026-08-18
tags: test, fail-closed, execution-record, sovereignty, regression

## منهجُ الإثبات

القاعدة 12 تمنع اعتبارَ وجودِ الملفِّ دليلًا على القدرة. فالقياسُ هنا **على
حالةِ دولةٍ حقيقيّةٍ وعلى سجلِّ البوابةِ نفسِه**: يُمرَّر مُنفِّذٌ يفشل، ثمّ
يُقاس القاموسُ وتُقرأ الآثار. ولا يُقبَل ادّعاءٌ بأن الحمايةَ قائمةٌ لمجرّد
أنّ صنفًا اسمُه `FailClosed` موجود.

والسؤالُ الذي تجيبه كلُّ حالةٍ هنا واحد: **هل يستطيع السجلُّ أن يقول «نُفِّذ»
عن معاملةٍ لم تكتمل؟** والجوابُ المطلوبُ: لا، ولا بحيلة.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization

from core.constitutional_engine.engine import ConstitutionalEngine
from core.constitutional_engine.ledger import ConstitutionalLedger
from core.constitutional_engine.model import ActionRequest, Branch
from core.sovereignty import crown as crown_module
from core.sovereignty.authority import classify
from core.sovereignty.authority_grants import AuthorityGrantRegistry
from core.sovereignty.compensation import (
    CompensationGuard,
    CompensationJournal,
    CompensationStatus,
    Compensator,
    bind_compensation_plan,
)
from core.sovereignty.contract import EffectKind, SovereignEffect, bind_contract
from core.sovereignty.decree import RoyalDecree, sign_decree
from core.sovereignty.fail_closed import (
    ExecutionCompletion,
    FailClosedError,
    IncompleteSovereignTransaction,
    MandatoryStage,
    attempt_execution,
    audit_anchor_of,
    require_audit_anchor,
)
from core.sovereignty.gateway import (
    AuthorityWithdrawn,
    ContractBreach,
    ExecutionRecord,
    RoyalImpersonation,
    SovereignGateway,
    SovereigntyViolation,
)
from core.sovereignty.idempotency import (
    IdempotencyGuard,
    IdempotencyKey,
    IdempotencyLedger,
    OperationStatus,
    compute_fingerprint,
)

TARGET = "treasury/account-A"


# ═══════════════════════════════════════════════════════════════════════════
# تجهيزات — حالةُ دولةٍ حقيقيّةٌ يُقاس عليها الوقوعُ والامتناع
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture()
def سجلُّ_الصلاحيّات(tmp_path: Path) -> AuthorityGrantRegistry:
    return AuthorityGrantRegistry(path=tmp_path / "AUTHORITY_GRANTS.json")


@pytest.fixture()
def بوابة(tmp_path: Path, سجلُّ_الصلاحيّات: AuthorityGrantRegistry) -> SovereignGateway:
    ledger = ConstitutionalLedger(tmp_path / "ledger.jsonl")
    return SovereignGateway(
        ConstitutionalEngine(ledger=ledger), grant_registry=سجلُّ_الصلاحيّات
    )


@pytest.fixture()
def حالةُ_الدولة() -> dict[str, str]:
    return {"treasury/account-A": "1000", "treasury/account-B": "50"}


@pytest.fixture()
def ملكٌ_مُنصَّب(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    registry = tmp_path / "CROWN_KEYS.json"
    monkeypatch.setattr(crown_module, "CROWN_KEYS_PATH", registry)
    private_out = tmp_path / "vault" / "crown.pem"
    تاج = crown_module.provision_crown(private_out, registry_path=registry)
    private = serialization.load_pem_private_key(private_out.read_bytes(), password=None)
    return private, تاج


def _مرسومٌ_موقَّع(مفتاح, معرف_المفتاح: str, *, action: str, decree_id: str):
    """مرسومٌ ملكيٌّ موقَّعٌ بمفتاحٍ حقيقيّ — لا محاكاةَ توقيع."""
    return sign_decree(
        RoyalDecree(
            decree_id=decree_id,
            action=action,
            target="branch-executive",
            issued_at="2026-08-18T00:00:00+00:00",
            justification="قياسُ الإغلاقِ عند الفشل (1J)",
            key_id=معرف_المفتاح,
        ),
        مفتاح,
    )


def _تصنيفٌ_سياديّ(ملكٌ_مُنصَّب, *, action: str = "revoke_authority"):
    مفتاح, تاج = ملكٌ_مُنصَّب
    مرسوم = _مرسومٌ_موقَّع(
        مفتاح, تاج.key_id, action=action, decree_id="DEC-1J-WITHDRAW"
    )
    return classify(
        ActionRequest(
            actor=Branch.ROYAL,
            action=action,
            target="branch-executive",
            royal_decree=مرسوم,
        )
    )


def _طلب(action: str = "credit_account", target: str = TARGET) -> ActionRequest:
    return ActionRequest(
        actor=Branch.EXECUTIVE, action=action, target=target, channel="official"
    )


class _فشلٌ_مقصود(RuntimeError):
    """فشلٌ يُحاكي انهيارَ المُنفِّذِ بعد صدورِ الإذن."""


def _منفذ_ينهار(حالة: dict[str, str] | None = None):
    """مُنفِّذٌ يمسُّ الحالةَ ثمّ ينهار — أثرٌ جزئيٌّ حقيقيٌّ لا محاكاة."""

    def _تنفيذ() -> str:
        if حالة is not None:
            حالة[TARGET] = "1500"
        raise _فشلٌ_مقصود("انهار المُنفِّذُ بعد أثرٍ جزئيّ.")

    return _تنفيذ


def _ادِّعاءات_النجاح(بوابة: SovereignGateway) -> list[ExecutionRecord]:
    return [r for r in بوابة.records if r.executed]


# ═══════════════════════════════════════════════════════════════════════════
# 1) العقد: دلالةُ `executed` مشتقّةٌ لا مضبوطة (الهدف أ)
# ═══════════════════════════════════════════════════════════════════════════


class Testدلالةُالتنفيذ:
    def test_executed_ليس_حقلًا_يُضبَط_عند_البناء(self) -> None:
        """لا سبيلَ إلى نجاحٍ كاذبٍ لأن الحقلَ نفسَه لم يعد موجودًا.

        هذا هو الفرقُ بين «حراسةٍ» و«امتناعٍ بنيويّ»: الحراسةُ تُنسى، وغيابُ
        الحقلِ لا يُنسى.
        """
        الحقول = {f.name for f in dataclasses.fields(ExecutionRecord)}
        assert "executed" not in الحقول, "عاد النجاحُ حقلًا حرًّا يُكتَب باليد."
        assert "completion" in الحقول
        assert isinstance(ExecutionRecord.executed, property)

    def test_البناءُ_بلا_تصريحٍ_باكتمالٍ_لا_يُقرأ_نجاحًا(self) -> None:
        """الافتراضُ مُغلَق: أثرٌ لم يُصرَّح باكتمالِه ليس تنفيذًا."""
        أثر = ExecutionRecord("f", "a", "executive", "ALLOW", None)
        assert أثر.completion is ExecutionCompletion.NOT_EXECUTED
        assert أثر.executed is False

    @pytest.mark.parametrize(
        "حالة",
        [
            ExecutionCompletion.NOT_EXECUTED,
            ExecutionCompletion.AUTHORIZED,
            ExecutionCompletion.EXECUTION_FAILED,
            ExecutionCompletion.RECOVERY_REQUIRED,
        ],
    )
    def test_لا_حالةَ_غيرُ_الاكتمالِ_تعني_نُفِّذ(self, حالة) -> None:
        """المحاولةُ والإذنُ والفشلُ والاسترداد: أربعتُها ليست نجاحًا."""
        أثر = ExecutionRecord("f", "a", "executive", "ALLOW", "h", completion=حالة)
        assert أثر.executed is False
        assert أثر.as_dict()["executed"] is False

    def test_الاكتمالُ_وحدَه_يعني_نُفِّذ(self) -> None:
        أثر = ExecutionRecord(
            "f", "a", "executive", "ALLOW", "h", completion=ExecutionCompletion.COMPLETED
        )
        assert أثر.executed is True
        assert أثر.as_dict()["completion"] == "COMPLETED"

    def test_حالةُ_اكتمالٍ_نصيّةٌ_تُرفَض_ولا_تُؤوَّل(self) -> None:
        """نصٌّ حرٌّ مكانَ التعدادِ بابٌ خلفيٌّ للغموض — يُغلَق عند العقد."""
        with pytest.raises(TypeError, match="ExecutionCompletion"):
            ExecutionRecord("f", "a", "executive", "ALLOW", "h", completion="COMPLETED")

    def test_الأثرُ_المُثبَّتُ_لا_يُعدَّل(self) -> None:
        """القاعدة 22: يُلحَق أثرٌ ثانٍ ولا يُمَسُّ الأوّل."""
        أثر = ExecutionRecord("f", "a", "executive", "ALLOW", "h")
        with pytest.raises(dataclasses.FrozenInstanceError):
            أثر.completion = ExecutionCompletion.COMPLETED  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════════
# 2) أ — التنفيذُ المكتملُ وحدَه يُصدَّق (المتطلَّب A)
# ═══════════════════════════════════════════════════════════════════════════


class Testالتنفيذُالمكتمل:
    def test_تنفيذٌ_تامٌّ_يُنتِج_executed_True(
        self, بوابة: SovereignGateway, حالةُ_الدولة: dict[str, str]
    ) -> None:
        نتيجة = بوابة.execute(
            _طلب(), lambda: حالةُ_الدولة.__setitem__(TARGET, "1500") or "تمّ"
        )
        assert نتيجة == "تمّ"
        assert حالةُ_الدولة[TARGET] == "1500", "لم يقع الأثرُ فعلًا."
        مختوم = بوابة.records[-1]
        assert مختوم.completion is ExecutionCompletion.COMPLETED
        assert مختوم.executed is True
        assert مختوم.ledger_entry_hash, "اكتمالٌ بلا مرتكزٍ تدقيقيّ."

    def test_الأثرُ_السابقُ_للتنفيذِ_لا_يزعم_نجاحًا(
        self, بوابة: SovereignGateway
    ) -> None:
        """الإذنُ يُثبَّت (القاعدة 22) ولا يُقرأ تنفيذًا."""
        بوابة.execute(_طلب(), lambda: "تمّ")
        إذن, مختوم = بوابة.records[-2], بوابة.records[-1]
        assert إذن.completion is ExecutionCompletion.AUTHORIZED
        assert إذن.executed is False
        assert مختوم.executed is True

    def test_الفحصُ_الذاتيُّ_يعدُّ_المكتملَ_لا_الممرَّ(
        self, بوابة: SovereignGateway
    ) -> None:
        بوابة.execute(_طلب(action="read_account"), lambda: "تمّ")
        with pytest.raises(_فشلٌ_مقصود):
            بوابة.execute(_طلب(action="read_account"), _منفذ_ينهار())
        فحص = بوابة.self_check()
        assert فحص["uncontracted_executions"] == 1, "عُدَّت محاولةٌ فاشلةٌ تنفيذًا."
        assert فحص["failed_executions"] == 1, "الفشلُ لا يُعلَن في الفحصِ الذاتيّ."


# ═══════════════════════════════════════════════════════════════════════════
# 3) ب — فشلُ مرحلةٍ إلزاميّةٍ ⇒ لا ادِّعاءَ نجاح (المتطلَّبات B, D, E, G, H)
# ═══════════════════════════════════════════════════════════════════════════


class Testالإغلاقُعندالفشل:
    def test_انهيارُ_المُنفِّذِ_لا_يترك_ادِّعاءَ_نجاحٍ_واحدًا(
        self, بوابة: SovereignGateway, حالةُ_الدولة: dict[str, str]
    ) -> None:
        """هذه هي الثغرةُ التاريخيّةُ بعينِها (المتطلَّب K).

        قبل 1J كان الأثرُ يُكتَب `executed=True` **قبل** استدعاءِ المُنفِّذ،
        فيبقى في سجلِّ الدولةِ ادّعاءُ نجاحٍ لفعلٍ انهار. لو عاد ذلك الترتيبُ
        لسقطَ هذا الاختبارُ وحدَه أوّلًا.
        """
        with pytest.raises(_فشلٌ_مقصود):
            بوابة.execute(_طلب(), _منفذ_ينهار(حالةُ_الدولة))
        assert _ادِّعاءات_النجاح(بوابة) == [], "السجلُّ يزعم نجاحًا لتنفيذٍ انهار."
        assert بوابة.records[-1].completion is ExecutionCompletion.EXECUTION_FAILED
        assert "_فشلٌ_مقصود" in بوابة.records[-1].failure_reason

    def test_الاستثناءُ_يُعادُ_رفعُه_ولا_يُبتلَع(self, بوابة: SovereignGateway) -> None:
        """القاعدة 9: لا تحويلَ للفشلِ إلى نجاحٍ ولا إلى قيمةٍ افتراضيّة."""
        with pytest.raises(_فشلٌ_مقصود, match="أثرٍ جزئيّ"):
            بوابة.execute(_طلب(), _منفذ_ينهار())

    def test_الاستثناءُ_يُعادُ_بنوعِه_لا_مُترجَمًا(self, بوابة: SovereignGateway) -> None:
        """إخفاءُ نوعِ الفشلِ أوّلُ خطوةٍ نحو النجاحِ الصامت."""
        with pytest.raises(_فشلٌ_مقصود) as محبوس:
            بوابة.execute(_طلب(), _منفذ_ينهار())
        assert not isinstance(محبوس.value, FailClosedError)

    def test_انقطاعُ_العمليّةِ_ليس_نجاحًا(self, بوابة: SovereignGateway) -> None:
        """`BaseException` لا `Exception` وحدَه: الانقطاعُ فشلٌ يُقال لا يُخفى."""

        def _منقطع() -> None:
            raise KeyboardInterrupt("قُطِعت العمليّة")

        with pytest.raises(KeyboardInterrupt):
            بوابة.execute(_طلب(), _منقطع)
        assert _ادِّعاءات_النجاح(بوابة) == []
        assert بوابة.records[-1].completion is ExecutionCompletion.EXECUTION_FAILED

    def test_المنعُ_الدستوريُّ_لا_يُنفَّذ_ولا_يُدَّعى(
        self, بوابة: SovereignGateway, حالةُ_الدولة: dict[str, str]
    ) -> None:
        """المتطلَّب C: الرفضُ الصريحُ إغلاقٌ لا تجاوز."""
        with pytest.raises(SovereigntyViolation):
            بوابة.execute(
                ActionRequest(actor=Branch.AGENT, action="amend_constitution"),
                lambda: حالةُ_الدولة.__setitem__(TARGET, "0"),
            )
        assert حالةُ_الدولة[TARGET] == "1000", "نُفِّذ فعلٌ ممنوع."
        assert _ادِّعاءات_النجاح(بوابة) == []
        assert بوابة.records[-1].completion is ExecutionCompletion.NOT_EXECUTED

    def test_الصلاحيّةُ_المسحوبةُ_إغلاقٌ_قبل_التقييم(
        self, بوابة: SovereignGateway, ملكٌ_مُنصَّب
    ) -> None:
        """سلطةٌ مسحوبةٌ ⇒ لا تنفيذَ ولا ادّعاء."""
        بوابة.grants.withdraw(
            _تصنيفٌ_سياديّ(ملكٌ_مُنصَّب),
            grantee=Branch.EXECUTIVE,
            capability="credit_account",
            reason="قياسُ الإغلاقِ عند سحبِ الصلاحيّة",
        )
        نُفِّذ: list[str] = []
        with pytest.raises(AuthorityWithdrawn):
            بوابة.execute(_طلب(), lambda: نُفِّذ.append("تمّ"))
        assert نُفِّذ == [], "استُدعي المُنفِّذُ رغم سحبِ الصلاحيّة."
        assert _ادِّعاءات_النجاح(بوابة) == []

    def test_ادِّعاءٌ_ملكيٌّ_بلا_أصالةٍ_لا_يُنفَّذ_ولا_يُسجَّل_نجاحًا(
        self, بوابة: SovereignGateway
    ) -> None:
        """المتطلَّب D: حالةٌ إلزاميّةٌ مفقودةٌ (المرسوم) ⇒ إغلاق."""
        نُفِّذ: list[str] = []
        with pytest.raises(RoyalImpersonation):
            بوابة.execute(
                ActionRequest(actor=Branch.ROYAL, action="amend_constitution"),
                lambda: نُفِّذ.append("تمّ"),
            )
        assert نُفِّذ == []
        assert _ادِّعاءات_النجاح(بوابة) == []

    def test_فشلُ_الإثباتِ_الإلزاميِّ_يُغلِق_قبل_التنفيذ(
        self,
        بوابة: SovereignGateway,
        حالةُ_الدولة: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """المتطلَّب E: حكمٌ بلا قيدٍ مُثبَّتٍ لا يُنفَّذ — الذاكرةُ ليست حقيقة."""
        الأصل = بوابة.engine.evaluate

        def _بلا_قيد(*ح, **م):
            return dataclasses.replace(الأصل(*ح, **م), ledger_entry_hash=None)

        monkeypatch.setattr(بوابة.engine, "evaluate", _بلا_قيد)
        with pytest.raises(IncompleteSovereignTransaction) as فشل:
            بوابة.execute(_طلب(), lambda: حالةُ_الدولة.__setitem__(TARGET, "0"))
        assert فشل.value.stage is MandatoryStage.AUDIT_ANCHOR
        assert حالةُ_الدولة[TARGET] == "1000", "نُفِّذ فعلٌ بلا أثرٍ تدقيقيّ."
        assert _ادِّعاءات_النجاح(بوابة) == []
        assert بوابة.records[-1].failure_reason

    def test_انهيارُ_السجلِّ_الدستوريِّ_يمنع_التنفيذ(
        self,
        بوابة: SovereignGateway,
        حالةُ_الدولة: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """فشلُ الإثباتِ الفعليِّ على القرص إغلاقٌ لا مضيٌّ في التنفيذ."""

        def _ينهار(*ح, **م):
            raise OSError("تعذّرت الكتابةُ في السجلّ الدستوريّ")

        monkeypatch.setattr(بوابة.engine.ledger, "append", _ينهار)
        with pytest.raises(OSError):
            بوابة.execute(_طلب(), lambda: حالةُ_الدولة.__setitem__(TARGET, "0"))
        assert حالةُ_الدولة[TARGET] == "1000"
        assert _ادِّعاءات_النجاح(بوابة) == []

    def test_الأثرُ_الجزئيُّ_لا_يتنكَّر_مكتملًا(
        self, بوابة: SovereignGateway, حالةُ_الدولة: dict[str, str]
    ) -> None:
        """المتطلَّب H: خرقُ العقدِ بعد أثرٍ مشروعٍ سابق."""
        مُعلَن = (SovereignEffect(kind=EffectKind.WRITE, resource=TARGET),)
        with pytest.raises(ContractBreach):
            بوابة.execute_under_contract(
                _طلب(),
                declared_effects=مُعلَن,
                planner=lambda _c: (
                    *مُعلَن,
                    SovereignEffect(kind=EffectKind.DELETE, resource="treasury/account-B"),
                ),
                applier=lambda أثر: حالةُ_الدولة.__setitem__(أثر.resource, "MUTATED"),
            )
        assert _ادِّعاءات_النجاح(بوابة) == [], "معاملةٌ مخروقةٌ سُجِّلت مكتملة."
        assert بوابة.records[-1].decision == "CONTRACT_BREACH"
        assert بوابة.self_check()["uncontracted_executions"] == 0


# ═══════════════════════════════════════════════════════════════════════════
# 4) لا نجاحَ صامتًا ولا تراجعَ صامتًا (المتطلَّب F)
# ═══════════════════════════════════════════════════════════════════════════


class Testلاتراجعَصامتًا:
    def test_محاولةٌ_فاشلةٌ_لا_تُرجِع_قيمةً_افتراضيّة(self, بوابة: SovereignGateway) -> None:
        """لا `return None` صامتٌ: الفشلُ يُرفَع فلا يبلغ المتصلُ ما بعدَه."""
        وصل: list[str] = []
        with pytest.raises(_فشلٌ_مقصود):
            بوابة.execute(_طلب(), _منفذ_ينهار())
            وصل.append("بلغَ المتصلُ سطرًا بعد فشلِ التنفيذ")
        assert وصل == [], "الفشلُ تُرجِمَ إلى مضيٍّ عاديٍّ في التنفيذ."

    def test_الفشلُ_لا_يُنتِج_إذنًا_ولا_يُحسَب_تنفيذًا_بعقد(
        self, بوابة: SovereignGateway
    ) -> None:
        """لا مسارَ التفافٍ: الفشلُ لا يُترجَم إلى مسارٍ ناجحٍ آخر."""
        مُعلَن = (SovereignEffect(kind=EffectKind.WRITE, resource=TARGET),)
        with pytest.raises(_فشلٌ_مقصود):
            بوابة.execute_under_contract(
                _طلب(),
                declared_effects=مُعلَن,
                planner=lambda _c: مُعلَن,
                applier=lambda _أ: (_ for _ in ()).throw(_فشلٌ_مقصود("انهار التطبيق")),
            )
        assert بوابة.self_check()["contracted_executions"] == 1
        assert بوابة.self_check()["uncontracted_executions"] == 0
        assert _ادِّعاءات_النجاح(بوابة) == []

    def test_لا_رايةَ_تجاوزٍ_في_وحدةِ_الإغلاق(self) -> None:
        """لا `force` ولا `bypass` ولا `override` — الحمايةُ بنيويّةٌ لا اختياريّة."""
        import inspect

        from core.sovereignty.gateway import FORBIDDEN_BYPASS_PARAMS

        for دالّة in (attempt_execution, require_audit_anchor, audit_anchor_of):
            معاملات = set(inspect.signature(دالّة).parameters)
            assert not معاملات & FORBIDDEN_BYPASS_PARAMS, دالّة.__name__
        معاملات_الختم = set(
            inspect.signature(SovereignGateway._run_and_seal).parameters
        )
        assert not معاملات_الختم & FORBIDDEN_BYPASS_PARAMS


# ═══════════════════════════════════════════════════════════════════════════
# 5) الوحدةُ نفسُها: قاعدةُ الاكتمالِ في موضعٍ واحد
# ═══════════════════════════════════════════════════════════════════════════


class Testوحدةُالإغلاق:
    def test_عودةٌ_سالمةٌ_بمرتكزٍ_تعني_الاكتمال(self) -> None:
        محاولة = attempt_execution(lambda: 42, audit_anchor="h")
        assert محاولة.completion is ExecutionCompletion.COMPLETED
        assert محاولة.certified is True
        assert محاولة.value == 42

    def test_عودةٌ_سالمةٌ_بلا_مرتكزٍ_تعني_استردادًا_لا_نجاحًا(self) -> None:
        """قد يكون أثرٌ وقع — ولا يُصدَّق على ما لا أثرَ تدقيقيَّ له."""
        محاولة = attempt_execution(lambda: 42, audit_anchor="")
        assert محاولة.completion is ExecutionCompletion.RECOVERY_REQUIRED
        assert محاولة.certified is False
        assert محاولة.failure_reason

    def test_الاستثناءُ_يُحفَظ_ولا_يُنفَّذ_إلّا_عند_إعادةِ_الرفع(self) -> None:
        محاولة = attempt_execution(_منفذ_ينهار(), audit_anchor="h")
        assert محاولة.completion is ExecutionCompletion.EXECUTION_FAILED
        assert محاولة.certified is False
        with pytest.raises(_فشلٌ_مقصود):
            محاولة.raise_if_failed()

    def test_مرتكزٌ_من_فراغٍ_لا_يُقبَل(self) -> None:
        class _حكم:
            ledger_entry_hash = "   "

        assert audit_anchor_of(_حكم()) == ""
        with pytest.raises(IncompleteSovereignTransaction):
            require_audit_anchor(_حكم())

    def test_المسارُ_السياديُّ_يمرُّ_من_قاعدةِ_الاكتمالِ_نفسِها(self) -> None:
        """قاعدةٌ واحدةٌ لا نسختان: المساران يستدعيان `_run_and_seal`."""
        import inspect

        for اسم in ("_execute_sovereign", "_execute_subordinate"):
            مصدر = inspect.getsource(getattr(SovereignGateway, اسم))
            assert "_run_and_seal" in مصدر, f"مسارُ «{اسم}» يلتفّ على قاعدةِ الاكتمال."


# ═══════════════════════════════════════════════════════════════════════════
# 6) المسارُ السياديّ: لا يُمنَع الملكُ، ولا يُدَّعى ما لم يكتمل
# ═══════════════════════════════════════════════════════════════════════════


class Testالمسارُالسياديّ:
    def _مرسوم(self, ملكٌ_مُنصَّب, فعل: str = "amend_constitution"):
        مفتاح, تاج = ملكٌ_مُنصَّب
        return sign_decree(
            RoyalDecree(
                decree_id=f"D-1J-{فعل}",
                action=فعل,
                issued_at="2026-08-18T00:00:00+00:00",
                justification="قياسُ الإغلاقِ عند الفشل (1J)",
                key_id=تاج.key_id,
            ),
            مفتاح,
        )

    def test_القرارُ_السياديُّ_التامُّ_يُختَم_مكتملًا(
        self, بوابة: SovereignGateway, ملكٌ_مُنصَّب
    ) -> None:
        مرسوم = self._مرسوم(ملكٌ_مُنصَّب)
        نتيجة = بوابة.execute(
            ActionRequest(actor=Branch.ROYAL, action=مرسوم.action, royal_decree=مرسوم),
            lambda: "أمرٌ ملكيّ",
        )
        assert نتيجة == "أمرٌ ملكيّ"
        assert بوابة.records[-1].sovereign and بوابة.records[-1].executed
        assert بوابة.self_check()["sovereign_executions"] == 1

    def test_انهيارُ_المُنفِّذِ_الملكيِّ_لا_يُسجَّل_تنفيذًا_سياديًّا(
        self, بوابة: SovereignGateway, ملكٌ_مُنصَّب
    ) -> None:
        """علوُّ التاجِ لا يعني أن يكذب السجلُّ نيابةً عنه."""
        مرسوم = self._مرسوم(ملكٌ_مُنصَّب)
        with pytest.raises(_فشلٌ_مقصود):
            بوابة.execute(
                ActionRequest(
                    actor=Branch.ROYAL, action=مرسوم.action, royal_decree=مرسوم
                ),
                _منفذ_ينهار(),
            )
        assert _ادِّعاءات_النجاح(بوابة) == []
        assert بوابة.self_check()["sovereign_executions"] == 0

    def test_المسارُ_السياديُّ_يبقى_بلا_رفعٍ_يمنع_التاج(self) -> None:
        """1J لم تُدخِل مانعًا دستوريًّا في مسارِ الملك — والفحصُ آليٌّ لا وعد."""
        import ast
        import inspect
        import textwrap

        شجرة = ast.parse(
            textwrap.dedent(inspect.getsource(SovereignGateway._execute_sovereign))
        )
        assert not any(isinstance(ع, ast.Raise) for ع in ast.walk(شجرة))

    def test_قرارٌ_ملكيٌّ_بلا_مرتكزٍ_يُنفَّذ_ولا_يُصدَّق(
        self,
        بوابة: SovereignGateway,
        ملكٌ_مُنصَّب,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """التوتّرُ الحقيقيُّ يُحسَم بلا كذبٍ ولا منعٍ للتاج.

        منعُ الملكِ لعطبٍ في السجلِّ ممنوعٌ دستوريًّا (المادة العاشرة)، وادّعاءُ
        اكتمالِ معاملةٍ بلا أثرٍ تدقيقيٍّ كذبٌ. فالمخرجُ الصادقُ: يُنفَّذ الأمرُ
        وتُعلَن الحالةُ `RECOVERY_REQUIRED` — لا نجاحَ ولا منع.
        """
        مرسوم = self._مرسوم(ملكٌ_مُنصَّب)
        الأصل = بوابة.engine.evaluate

        def _بلا_قيد(*ح, **م):
            return dataclasses.replace(الأصل(*ح, **م), ledger_entry_hash=None)

        monkeypatch.setattr(بوابة.engine, "evaluate", _بلا_قيد)
        نتيجة = بوابة.execute(
            ActionRequest(actor=Branch.ROYAL, action=مرسوم.action, royal_decree=مرسوم),
            lambda: "أمرٌ ملكيّ",
        )
        assert نتيجة == "أمرٌ ملكيّ", "مُنِع التاجُ — وهذا نقضٌ للمادة العاشرة."
        مختوم = بوابة.records[-1]
        assert مختوم.completion is ExecutionCompletion.RECOVERY_REQUIRED
        assert مختوم.executed is False
        assert بوابة.self_check()["recovery_required"] == 1


# ═══════════════════════════════════════════════════════════════════════════
# 7) التوافقُ مع 1H و 1I (المتطلَّبان I و J)
# ═══════════════════════════════════════════════════════════════════════════


class Testالتوافقُمعالمراحلِالسابقة:
    def _مفتاح(self) -> IdempotencyKey:
        return IdempotencyKey(scope="sovereignty/1J", value="K-1J")

    def _بصمة(self) -> str:
        return compute_fingerprint(
            scope="sovereignty/1J",
            action="credit_account",
            target=TARGET,
            effect_signatures=(f"WRITE:{TARGET}",),
            actor="executive",
        )

    def test_ذرّيّةُ_1H_سليمةٌ_والتنفيذُ_لا_يتكرَّر(
        self, بوابة: SovereignGateway, حالةُ_الدولة: dict[str, str], tmp_path: Path
    ) -> None:
        """المتطلَّب I: مفتاحٌ واحدٌ ⇒ تنفيذٌ واحدٌ مكتملٌ واحد."""
        حارس = IdempotencyGuard(ledger=IdempotencyLedger(tmp_path / "idem"))
        مفتاح = self._مفتاح()
        بصمة = self._بصمة()
        عدّاد: list[int] = []

        def _عملية() -> str:
            return بوابة.execute(
                _طلب(), lambda: (عدّاد.append(1), حالةُ_الدولة.__setitem__(TARGET, "1500"))[0] or "تمّ"
            )

        أولى = حارس.run_once(key=مفتاح, fingerprint=بصمة, execute=_عملية)
        ثانية = حارس.run_once(key=مفتاح, fingerprint=بصمة, execute=_عملية)
        assert أولى.record.status is OperationStatus.SUCCEEDED
        assert ثانية.is_replay is True
        assert len(عدّاد) == 1, "تكرّر التنفيذُ رغم الذرّيّة."
        assert len(_ادِّعاءات_النجاح(بوابة)) == 1

    def test_فشلُ_التنفيذِ_يُنقَل_إلى_1H_فشلًا_لا_نجاحًا(
        self, بوابة: SovereignGateway, tmp_path: Path
    ) -> None:
        """لا يُختَم مفتاحُ الذرّيّةِ ناجحًا لمعاملةٍ لم تكتمل."""
        حارس = IdempotencyGuard(ledger=IdempotencyLedger(tmp_path / "idem"))
        مفتاح = self._مفتاح()
        بصمة = self._بصمة()
        # 1H يلفُّ الفشلَ في `IdempotencyError` — والمهمُّ لـ1J أن الفشلَ بقي
        # فشلًا في الطبقتين ولم يتحوّل نجاحًا في أيٍّ منهما.
        from core.sovereignty.idempotency import IdempotencyError

        with pytest.raises(IdempotencyError) as محبوس:
            حارس.run_once(
                key=مفتاح,
                fingerprint=بصمة,
                execute=lambda: بوابة.execute(_طلب(), _منفذ_ينهار()),
            )
        assert isinstance(محبوس.value.__cause__, _فشلٌ_مقصود)
        assert حارس.ledger.get(مفتاح).status is not OperationStatus.SUCCEEDED
        assert _ادِّعاءات_النجاح(بوابة) == []

    def test_تعويضُ_1I_يبقى_مرجعًا_للأثرِ_الجزئيّ(
        self, بوابة: SovereignGateway, حالةُ_الدولة: dict[str, str], tmp_path: Path
    ) -> None:
        """المتطلَّب J: 1J لا تُكرِّر التعويضَ ولا تُعطِّلُه — تُسلِّم إليه حالةً صادقة."""
        قبل = dict(حالةُ_الدولة)
        with pytest.raises(_فشلٌ_مقصود):
            بوابة.execute(_طلب(), _منفذ_ينهار(حالةُ_الدولة))
        assert بوابة.records[-1].completion is ExecutionCompletion.EXECUTION_FAILED
        assert حالةُ_الدولة != قبل, "لم يقع أثرٌ جزئيٌّ — فلا معنى لقياسِ التعويض."

        عقد = bind_contract(
            actor="executive",
            action="credit_account",
            target=TARGET,
            declared_effects=(SovereignEffect(kind=EffectKind.WRITE, resource=TARGET),),
        )
        خطة = bind_compensation_plan(
            contract=عقد,
            compensators=(
                Compensator(
                    effect_signature=f"WRITE:{TARGET}",
                    apply=lambda: حالةُ_الدولة.__setitem__(TARGET, قبل[TARGET]),
                    description="إعادةُ الرصيدِ إلى ما كان",
                ),
            ),
        )
        حارس = CompensationGuard(
            journal=CompensationJournal(tmp_path / "comp"),
            idempotency=IdempotencyGuard(ledger=IdempotencyLedger(tmp_path / "idem")),
        )
        حصيلة = حارس.compensate(
            contract=عقد,
            plan=خطة,
            operation_key=self._مفتاح(),
            applied_signatures=(f"WRITE:{TARGET}",),
            reason=بوابة.records[-1].failure_reason,
        )
        assert حصيلة.record.status is CompensationStatus.COMPENSATED
        assert حالةُ_الدولة == قبل, "لم ترجع حالةُ الدولةِ فعلًا."
        assert _ادِّعاءات_النجاح(بوابة) == []
