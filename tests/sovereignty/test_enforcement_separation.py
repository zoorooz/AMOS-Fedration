"""الهدف: قياسُ فصلِ موضعِ القرارِ عن موضعِ الإنفاذ — هل يُنفَّذ بإذنٍ لا بسلطة؟

النطاق: `core/sovereignty/enforcement.py` و`SovereignGateway.decide`.
المالك: tests/sovereignty/ — ديوان التدقيق
تاريخ الإنشاء: 2026-08-18
تاريخ آخر تعديل: 2026-08-18

القاعدة 12 تمنع اعتبارَ وجودِ الملفِّ دليلًا على القدرة، والقاعدة 13 تمنع
الاكتفاءَ باختبارِ وحدة. فالقياسُ هنا **من البوابةِ نفسِها** وعلى **قاموسِ حالةٍ
حقيقيّ**: المنعُ يُثبَت بأنّ الحالةَ لم تتغيّر، لا بأنّ استثناءً ارتفع.

والدعوى المُقاسة في 1F ثلاثٌ:
1. موضعُ الإنفاذِ **لا يستطيع** أن يحكم — لا أنّه لا يفعل.
2. القرارُ يُحمَل في أثرٍ يعبُر الحدود، فيُنفَّذ على بُعدٍ بلا محرّك.
3. `decide` و`execute` **لا يمكن** أن يتباعدا.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from core.constitutional_engine.engine import ConstitutionalEngine
from core.constitutional_engine.ledger import ConstitutionalLedger
from core.constitutional_engine.model import ActionRequest, Branch
from core.sovereignty import crown as crown_module
from core.sovereignty.contract import EffectKind, SovereignEffect, bind_contract
from core.sovereignty.enforcement import (
    DEFAULT_PERMIT_TTL_SECONDS,
    PERMIT_DOMAIN,
    ConsumedPermitLedger,
    EnforcementError,
    EnforcementPermit,
    PermitExpiredError,
    PermitInvalidError,
    PermitReplayError,
    PermitScopeError,
    PolicyEnforcementPoint,
    issue_permit,
    sign_permit,
)
from core.sovereignty.gateway import SovereignGateway

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
def سجلُّ_الاستهلاك(tmp_path: Path) -> ConsumedPermitLedger:
    """على القرصِ لا في الذاكرة — وإلّا لم يُقَس منعُ الإعادةِ عبر العمليّات."""
    return ConsumedPermitLedger(tmp_path / "CONSUMED_PERMITS.json")


@pytest.fixture()
def مُنفِّذ(بوابة: SovereignGateway, سجلُّ_الاستهلاك) -> PolicyEnforcementPoint:
    """يُبنى بمفتاحِ التحقّقِ العامِّ وحدَه — لا بالبوابة ولا بمفتاحِ التوقيع."""
    return PolicyEnforcementPoint(
        verifying_key=ed25519.Ed25519PublicKey.from_public_bytes(
            bytes.fromhex(بوابة.verifying_key_hex)
        ),
        consumed=سجلُّ_الاستهلاك,
    )


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


def _أثر(kind: EffectKind = EffectKind.WRITE, resource: str = TARGET) -> SovereignEffect:
    return SovereignEffect(kind=kind, resource=resource, detail="قياس")


def _مُطبِّق(state: dict[str, str]):
    def apply(effect: SovereignEffect) -> None:
        state[effect.resource] = "MUTATED"

    return apply


# ═══════════════════════════════════════════════════════════════════════════
# 1 — موضعُ الإنفاذِ لا يملك أن يحكم
# ═══════════════════════════════════════════════════════════════════════════

class Testالمُنفِّذُلايحكم:
    def test_المنفذ_لا_يحمل_محركا_ولا_بوابة(self, مُنفِّذ):
        """امتناعٌ بنيويٌّ: لا حقلَ فيه يُمكِن الحكمَ أصلًا."""
        حقول = set(PolicyEnforcementPoint.__slots__)
        assert حقول == {"verifying_key", "consumed"}
        assert not hasattr(مُنفِّذ, "_engine")
        assert not hasattr(مُنفِّذ, "_gateway")

    def test_المنفذ_لا_يملك_مفتاح_توقيع(self, مُنفِّذ):
        """من ملك مفتاحَ التوقيعِ أذِنَ لنفسِه. فليس عنده إلّا التحقّق."""
        assert isinstance(مُنفِّذ.verifying_key, ed25519.Ed25519PublicKey)
        assert not isinstance(مُنفِّذ.verifying_key, ed25519.Ed25519PrivateKey)
        assert not hasattr(مُنفِّذ.verifying_key, "sign")

    def test_وحدة_الانفاذ_لا_تستورد_محركا_دستوريا(self):
        """قياسٌ على المصدرِ نفسِه: لا سبيلَ إلى محرّكٍ من هذه الوحدة."""
        مصدر = Path("core/sovereignty/enforcement.py").read_text(encoding="utf-8")
        سطور_الاستيراد = [
            س for س in مصدر.splitlines() if س.startswith(("import ", "from "))
        ]
        نص = "\n".join(سطور_الاستيراد)
        assert "constitutional_engine" not in نص
        assert "gateway" not in نص

    def test_البوابة_لا_تكشف_مفتاح_التوقيع_في_واجهة_عامة(self, بوابة):
        """العامُّ يُصدَّر والخاصُّ يُحجَب — وهذا هو الفصلُ لا وصفُه."""
        عام = [ا for ا in dir(بوابة) if not ا.startswith("_")]
        assert "verifying_key_hex" in عام
        assert not any("permit_key" in ا or "signing" in ا for ا in عام)

    def test_المنفذ_لا_يقبل_اذنا_يصنعه_بنفسه(self, بوابة, مُنفِّذ, حالةُ_الدولة):
        """أخطرُ الحالات: مُنفِّذٌ يحاول أن يأذن لنفسِه بمفتاحٍ من عندِه."""
        مفتاحُ_دخيل = ed25519.Ed25519PrivateKey.generate()
        عقد = bind_contract(
            actor="EXECUTIVE",
            action="credit_account",
            target=TARGET,
            declared_effects=(_أثر(),),
        )
        مُزوَّر = issue_permit(
            contract=عقد,
            request_fingerprint="x",
            decision="ALLOW",
            ledger_entry_hash=None,
            private_key=مفتاحُ_دخيل,
        )
        with pytest.raises(PermitInvalidError):
            مُنفِّذ.enforce(
                مُزوَّر,
                planner=lambda p: (_أثر(),),
                applier=_مُطبِّق(حالةُ_الدولة),
            )
        assert حالةُ_الدولة[TARGET] == "1000"


# ═══════════════════════════════════════════════════════════════════════════
# 2 — القرارُ يُحمَل ويُنفَّذ على بُعد
# ═══════════════════════════════════════════════════════════════════════════

class Testالقرارُيُحمَل:
    def test_اذن_صادر_عن_البوابة_ينفذ_عند_المنفذ(
        self, بوابة, مُنفِّذ, حالةُ_الدولة
    ):
        """القياسُ على الحالة: القاموسُ تغيّر بإذنٍ لا بسلطةٍ عند المُنفِّذ."""
        إذن = بوابة.decide(_طلب(), declared_effects=(_أثر(),))
        مطبَّق = مُنفِّذ.enforce(
            إذن, planner=lambda p: (_أثر(),), applier=_مُطبِّق(حالةُ_الدولة)
        )
        assert حالةُ_الدولة[TARGET] == "MUTATED"
        assert [أ.signature for أ in مطبَّق] == [f"WRITE:{TARGET}"]

    def test_الاذن_يعبر_الحدود_مُسلسَلًا(self, بوابة, مُنفِّذ, حالةُ_الدولة):
        """الاختبارُ الحقيقيُّ للفصل: نصٌّ يعبُر ثمّ يُنفَّذ — لا كائنٌ مشترك."""
        إذن = بوابة.decide(_طلب(), declared_effects=(_أثر(),))
        نص = json.dumps(إذن.as_dict(), ensure_ascii=False)
        مُعاد = EnforcementPermit(
            **{**json.loads(نص), "effect_signatures": tuple(إذن.effect_signatures)}
        )
        مُنفِّذ.enforce(
            مُعاد, planner=lambda p: (_أثر(),), applier=_مُطبِّق(حالةُ_الدولة)
        )
        assert حالةُ_الدولة[TARGET] == "MUTATED"

    def test_الاذن_يحمل_الحكم_والطبقة_وبصمة_الطلب(self, بوابة):
        إذن = بوابة.decide(_طلب(), declared_effects=(_أثر(),))
        assert إذن.decision
        assert إذن.request_fingerprint
        assert إذن.contract_id.startswith("EC-")
        assert إذن.permit_id.startswith("EP-")

    def test_القرار_يُسجَّل_اصدار_اذن_لا_تنفيذا(self, بوابة, حالةُ_الدولة):
        """القاعدة 24: السجلُّ يقول ما جرى. لم تُمَسَّ حالةٌ فلا يُقال «نُفِّذ»."""
        بوابة.decide(_طلب(), declared_effects=(_أثر(),))
        أثر = بوابة.records[-1]
        assert أثر.enforcement == "PERMIT_ISSUED"
        assert أثر.as_dict()["enforcement"] == "PERMIT_ISSUED"
        assert حالةُ_الدولة[TARGET] == "1000"

    def test_التنفيذ_المباشر_يبقى_موسوما_مباشرا(self, بوابة):
        """القاعدة 3: ما كان يعمل يبقى يعمل بالسلوكِ نفسِه."""
        بوابة.execute(_طلب(), lambda: None)
        assert بوابة.records[-1].enforcement == "DIRECT"

    def test_عداد_الاذونات_في_الفحص_الذاتي(self, بوابة):
        assert بوابة.self_check()["permits_issued"] == 0
        بوابة.decide(_طلب(), declared_effects=(_أثر(),))
        assert بوابة.self_check()["permits_issued"] == 1

    def test_اصدار_اذن_لا_يُحسَب_تنفيذا_متعاقدا(self, بوابة):
        """الإذنُ ليس تنفيذًا متعاقدًا — وخلطُهما يُفسِد عدّادَ 1E."""
        قبل = بوابة.self_check()["contracted_executions"]
        بوابة.decide(_طلب(), declared_effects=(_أثر(),))
        assert بوابة.self_check()["contracted_executions"] == قبل


# ═══════════════════════════════════════════════════════════════════════════
# 3 — الإذنُ لا يُوسَّع ولا يُعاد ولا يَبقى
# ═══════════════════════════════════════════════════════════════════════════

class Testحدودُالإذن:
    def test_اثر_خارج_الاذن_لا_يقع(self, بوابة, مُنفِّذ, حالةُ_الدولة):
        """أُذِن بحسابٍ فحاول حسابًا آخر: يُمنَع، ولا يُطبَّق شيءٌ ولو المأذون."""
        إذن = بوابة.decide(_طلب(), declared_effects=(_أثر(),))
        with pytest.raises(PermitScopeError):
            مُنفِّذ.enforce(
                إذن,
                planner=lambda p: (_أثر(), _أثر(resource="treasury/account-B")),
                applier=_مُطبِّق(حالةُ_الدولة),
            )
        assert حالةُ_الدولة[TARGET] == "1000"
        assert حالةُ_الدولة["treasury/account-B"] == "50"

    def test_نوع_اثر_مختلف_على_المورد_نفسه_خارج_الاذن(
        self, بوابة, مُنفِّذ, حالةُ_الدولة
    ):
        """أُذِن بالكتابةِ فحاول الحذف: المَورِدُ واحدٌ والإذنُ ليس واحدًا."""
        إذن = بوابة.decide(_طلب(), declared_effects=(_أثر(),))
        with pytest.raises(PermitScopeError):
            مُنفِّذ.enforce(
                إذن,
                planner=lambda p: (_أثر(kind=EffectKind.DELETE),),
                applier=_مُطبِّق(حالةُ_الدولة),
            )
        assert حالةُ_الدولة[TARGET] == "1000"

    def test_اعادة_استعمال_الاذن_تُمنَع(self, بوابة, مُنفِّذ, حالةُ_الدولة):
        """الإذنُ الواحدُ لفعلٍ واحد — وإلّا صار صكَّ ملكيّة."""
        إذن = بوابة.decide(_طلب(), declared_effects=(_أثر(),))
        مُنفِّذ.enforce(
            إذن, planner=lambda p: (_أثر(),), applier=_مُطبِّق(حالةُ_الدولة)
        )
        حالةُ_الدولة[TARGET] = "1000"
        with pytest.raises(PermitReplayError):
            مُنفِّذ.enforce(
                إذن, planner=lambda p: (_أثر(),), applier=_مُطبِّق(حالةُ_الدولة)
            )
        assert حالةُ_الدولة[TARGET] == "1000"

    def test_منع_الاعادة_يعبر_العمليات_لا_الذاكرة(
        self, بوابة, مُنفِّذ, سجلُّ_الاستهلاك, حالةُ_الدولة
    ):
        """القاعدة 17: مُنفِّذٌ جديدٌ بذاكرةٍ نظيفةٍ يقرأ القرصَ فيرفض."""
        إذن = بوابة.decide(_طلب(), declared_effects=(_أثر(),))
        مُنفِّذ.enforce(
            إذن, planner=lambda p: (_أثر(),), applier=_مُطبِّق(حالةُ_الدولة)
        )
        حالةُ_الدولة[TARGET] = "1000"
        آخَر = PolicyEnforcementPoint(
            verifying_key=مُنفِّذ.verifying_key,
            consumed=ConsumedPermitLedger(سجلُّ_الاستهلاك.path),
        )
        with pytest.raises(PermitReplayError):
            آخَر.enforce(
                إذن, planner=lambda p: (_أثر(),), applier=_مُطبِّق(حالةُ_الدولة)
            )
        assert حالةُ_الدولة[TARGET] == "1000"
        assert سجلُّ_الاستهلاك.count() == 1

    def test_الاذن_المنقضي_يُرفَض(self, بوابة, مُنفِّذ, حالةُ_الدولة):
        إذن = بوابة.decide(_طلب(), declared_effects=(_أثر(),), ttl_seconds=1)
        غدًا = datetime.now(timezone.utc) + timedelta(days=1)
        with pytest.raises(PermitExpiredError):
            مُنفِّذ.enforce(
                إذن,
                planner=lambda p: (_أثر(),),
                applier=_مُطبِّق(حالةُ_الدولة),
                now=غدًا,
            )
        assert حالةُ_الدولة[TARGET] == "1000"
        assert إذن.is_expired(غدًا) is True
        assert إذن.is_expired() is False

    def test_اذن_بعمر_غير_موجب_يُرفَض_عند_الاصدار(self, بوابة):
        """الإذنُ الذي لا ينتهي ليس إذنًا. يُمنَع عند المنبعِ لا عند الاستعمال."""
        with pytest.raises(EnforcementError):
            بوابة.decide(_طلب(), declared_effects=(_أثر(),), ttl_seconds=0)

    def test_العمر_الافتراضي_محدود(self, بوابة):
        إذن = بوابة.decide(_طلب(), declared_effects=(_أثر(),))
        عمر = datetime.fromisoformat(إذن.expires_at) - datetime.fromisoformat(
            إذن.issued_at
        )
        assert عمر == timedelta(seconds=DEFAULT_PERMIT_TTL_SECONDS)


# ═══════════════════════════════════════════════════════════════════════════
# 4 — التزويرُ يُكشَف
# ═══════════════════════════════════════════════════════════════════════════

class Testكشفُالتزوير:
    @pytest.mark.parametrize(
        "حقل,قيمة",
        [
            ("action", "dissolve_state"),
            ("target", "treasury/account-B"),
            ("decision", "OVERRIDDEN"),
            ("actor", "CROWN"),
            ("authority_layer", "CROWN"),
            ("expires_at", "2099-01-01T00:00:00+00:00"),
            ("effect_signatures", ("DELETE:treasury/account-B",)),
        ],
    )
    def test_تحريف_اي_حقل_يبطل_التوقيع(
        self, بوابة, مُنفِّذ, حالةُ_الدولة, حقل, قيمة
    ):
        """كلُّ حقلٍ داخلٌ في التوقيع — لا حقلَ «تجميليّ» خارجَه."""
        إذن = بوابة.decide(_طلب(), declared_effects=(_أثر(),))
        محرَّف = EnforcementPermit(
            **{
                **إذن.as_dict(),
                "effect_signatures": tuple(إذن.effect_signatures),
                حقل: قيمة,
            }
        )
        with pytest.raises(PermitInvalidError):
            مُنفِّذ.enforce(
                محرَّف,
                planner=lambda p: (_أثر(),),
                applier=_مُطبِّق(حالةُ_الدولة),
            )
        assert حالةُ_الدولة[TARGET] == "1000"

    def test_اذن_بلا_توقيع_ليس_اذنا(self, بوابة, مُنفِّذ):
        إذن = بوابة.decide(_طلب(), declared_effects=(_أثر(),))
        بلا = EnforcementPermit(
            **{
                **إذن.as_dict(),
                "effect_signatures": tuple(إذن.effect_signatures),
                "signature_hex": "",
            }
        )
        with pytest.raises(PermitInvalidError, match="بلا توقيع"):
            مُنفِّذ.verify(بلا)

    def test_توقيع_غير_ست_عشري_يُرفَض_ولا_ينهار(self, بوابة, مُنفِّذ):
        """القاعدة 16: خللُ الشكلِ يُرفَع رفضًا صريحًا لا انهيارًا غامضًا."""
        إذن = بوابة.decide(_طلب(), declared_effects=(_أثر(),))
        فاسد = EnforcementPermit(
            **{
                **إذن.as_dict(),
                "effect_signatures": tuple(إذن.effect_signatures),
                "signature_hex": "ليس-ستّ-عشريّ",
            }
        )
        with pytest.raises(PermitInvalidError):
            مُنفِّذ.verify(فاسد)

    def test_مجال_التوقيع_يمنع_خلط_الاذن_بغيره(self, بوابة):
        """توقيعُ إذنٍ لا يصلح توقيعَ مرسوم: المجالُ داخلٌ في الموقَّع."""
        إذن = بوابة.decide(_طلب(), declared_effects=(_أثر(),))
        assert إذن.signing_payload().startswith(PERMIT_DOMAIN)

    def test_مفتاح_تحقق_من_بوابة_اخرى_لا_يقبل(self, بوابة, tmp_path, سجلُّ_الاستهلاك):
        """كلُّ بوابةٍ سلطةٌ قائمةٌ بذاتها — ولا يُقبَل إذنُها عند غيرِها."""
        أخرى = SovereignGateway(
            ConstitutionalEngine(ledger=ConstitutionalLedger(tmp_path / "l2.jsonl"))
        )
        assert أخرى.verifying_key_hex != بوابة.verifying_key_hex
        مُنفِّذُ_الأخرى = PolicyEnforcementPoint(
            verifying_key=ed25519.Ed25519PublicKey.from_public_bytes(
                bytes.fromhex(أخرى.verifying_key_hex)
            ),
            consumed=سجلُّ_الاستهلاك,
        )
        إذن = بوابة.decide(_طلب(), declared_effects=(_أثر(),))
        with pytest.raises(PermitInvalidError):
            مُنفِّذُ_الأخرى.verify(إذن)


# ═══════════════════════════════════════════════════════════════════════════
# 5 — لا إذنَ لممنوع: القرارُ هو القرارُ نفسُه
# ═══════════════════════════════════════════════════════════════════════════

class Testلاإذنَلممنوع:
    def test_الفعل_الملكي_الحصري_لا_يُؤذَن_به_لغير_الملك(self, بوابة, حالةُ_الدولة):
        """القاعدة الذهبيّة: ما امتنع في `execute` يمتنع في `decide` بعينِه."""
        with pytest.raises(Exception) as المرفوع:
            بوابة.decide(
                _طلب(action="amend_constitution", target="core/constitution"),
                declared_effects=(_أثر(resource="core/constitution"),),
            )
        assert not isinstance(المرفوع.value, PermitScopeError)
        assert حالةُ_الدولة[TARGET] == "1000"

    def test_اثر_خارج_نطاق_الهدف_يُمنَع_قبل_الحكم(self, بوابة):
        """بوّابةُ 1E الأولى قائمةٌ: النطاقُ يُفحَص عند الربطِ لا بعده."""
        from core.sovereignty.contract import EffectOutOfScopeError

        with pytest.raises(EffectOutOfScopeError):
            بوابة.decide(
                _طلب(), declared_effects=(_أثر(resource="royal/crown-authority"),)
            )
        assert بوابة.self_check()["permits_issued"] == 0

    def test_decide_وexecute_لا_يتباعدان(self, بوابة, tmp_path):
        """القرارُ واحدٌ بنيويًّا: نفسُ الطلبِ يُعطي نفسَ الحكمِ في الطريقين."""
        أخرى = SovereignGateway(
            ConstitutionalEngine(ledger=ConstitutionalLedger(tmp_path / "l3.jsonl"))
        )
        for action in ("credit_account", "publish_report", "audit_ledger"):
            طلب = _طلب(action=action)
            إذن = بوابة.decide(طلب, declared_effects=(_أثر(),))
            أخرى.execute(_طلب(action=action), lambda: None)
            مباشر = أخرى.records[-1]
            assert إذن.decision == مباشر.decision
            assert إذن.decision_kind == مباشر.decision_kind
            assert إذن.authority_layer == مباشر.authority_layer
            assert إذن.request_fingerprint == مباشر.fingerprint


# ═══════════════════════════════════════════════════════════════════════════
# 6 — سجلُّ الاستهلاكِ وأدواتُ الوحدة
# ═══════════════════════════════════════════════════════════════════════════

class Testسجلُّالاستهلاك:
    def test_سجل_غير_موجود_يُقرَأ_فارغا_لا_ينهار(self, tmp_path):
        سجل = ConsumedPermitLedger(tmp_path / "غير-موجود" / "c.json")
        assert سجل.count() == 0
        assert سجل.is_consumed("EP-x") is False

    def test_الاستهلاك_يُكتَب_على_القرص_ويبقى(self, tmp_path):
        مسار = tmp_path / "c.json"
        سجل = ConsumedPermitLedger(مسار)
        سجل.consume("EP-1")
        assert مسار.exists()
        assert "EP-1" in json.loads(مسار.read_text(encoding="utf-8"))
        assert ConsumedPermitLedger(مسار).is_consumed("EP-1") is True

    def test_استهلاك_مكرر_يُرفَع_ولا_يُبتلَع(self, tmp_path):
        سجل = ConsumedPermitLedger(tmp_path / "c.json")
        سجل.consume("EP-1")
        with pytest.raises(PermitReplayError):
            سجل.consume("EP-1")

    def test_توقيع_يدوي_يطابق_الاصدار(self):
        """`sign_permit` و`issue_permit` طريقٌ واحدٌ لا طريقان."""
        مفتاح = ed25519.Ed25519PrivateKey.generate()
        عقد = bind_contract(
            actor="EXECUTIVE",
            action="credit_account",
            target=TARGET,
            declared_effects=(_أثر(),),
        )
        لحظة = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
        أ = issue_permit(
            contract=عقد,
            request_fingerprint="fp",
            decision="ALLOW",
            ledger_entry_hash="h",
            private_key=مفتاح,
            now=لحظة,
        )
        ب = sign_permit(
            EnforcementPermit(
                **{**أ.as_dict(), "effect_signatures": tuple(أ.effect_signatures),
                   "signature_hex": ""}
            ),
            مفتاح,
        )
        assert أ.signature_hex == ب.signature_hex

    def test_covers_يقيس_البصمة_لا_التفصيل(self, بوابة):
        """التفصيلُ خارجُ البصمةِ بقصدٍ منذ 1E — والإذنُ يتبع العقدَ لا يخالفه."""
        إذن = بوابة.decide(_طلب(), declared_effects=(_أثر(),))
        assert إذن.covers(SovereignEffect(EffectKind.WRITE, TARGET, "تفصيلٌ آخر"))
        assert not إذن.covers(_أثر(kind=EffectKind.DELETE))

    def test_verify_وحدَه_لا_يستهلك(self, بوابة, مُنفِّذ, سجلُّ_الاستهلاك):
        """التحقّقُ فحصٌ لا استهلاك — وإلّا أهلك الفحصُ الإذنَ الصحيح."""
        إذن = بوابة.decide(_طلب(), declared_effects=(_أثر(),))
        مُنفِّذ.verify(إذن)
        مُنفِّذ.verify(إذن)
        assert سجلُّ_الاستهلاك.count() == 0

    def test_الاستهلاك_يسبق_التطبيق(self, بوابة, مُنفِّذ, سجلُّ_الاستهلاك):
        """اختيارٌ مُعلَن: إذنٌ يضيع أهونُ من أثرٍ يُطبَّق مرّتين."""
        إذن = بوابة.decide(_طلب(), declared_effects=(_أثر(),))

        def مُطبِّقٌ_ينهار(effect: SovereignEffect) -> None:
            raise RuntimeError("سقط النظامُ أثناء التطبيق")

        with pytest.raises(RuntimeError):
            مُنفِّذ.enforce(
                إذن, planner=lambda p: (_أثر(),), applier=مُطبِّقٌ_ينهار
            )
        assert سجلُّ_الاستهلاك.is_consumed(إذن.permit_id) is True

    def test_اذن_بلا_اثار_معلنة_لا_يُصدَر_اصلا(self, بوابة, حالةُ_الدولة):
        """قياسٌ كشف أنّ المنعَ أسبقُ ممّا افترضتُ: عقدُ 1E يرفض العقدَ الفارغ.

        فلا حاجةَ إلى رفضٍ ثانٍ عند المُنفِّذ، والإذنُ المفتوحُ ممتنعٌ عند
        المنبعِ لا عند المصبّ. سُجِّلَ ما قِيسَ لا ما أُريد.
        """
        from core.sovereignty.contract import ContractError

        with pytest.raises(ContractError):
            بوابة.decide(_طلب(), declared_effects=())
        assert بوابة.self_check()["permits_issued"] == 0
        assert حالةُ_الدولة[TARGET] == "1000"

    def test_خطة_فارغة_تُنفَّذ_بلا_اثر(self, بوابة, مُنفِّذ, حالةُ_الدولة):
        إذن = بوابة.decide(_طلب(), declared_effects=(_أثر(),))
        assert مُنفِّذ.enforce(
            إذن, planner=lambda p: (), applier=_مُطبِّق(حالةُ_الدولة)
        ) == ()
        assert حالةُ_الدولة[TARGET] == "1000"

    def test_سقوط_الكتابة_لا_يترك_سجلا_نصفيا(self, tmp_path, monkeypatch):
        """نصفُ سجلِّ استهلاكٍ نافذةُ إعادةٍ صامتة. فإمّا كاملٌ وإمّا لا شيء."""
        from core.sovereignty import enforcement as وحدة

        مسار = tmp_path / "c.json"
        سجل = ConsumedPermitLedger(مسار)
        سجل.consume("EP-1")

        def يسقط(*_a, **_k):
            raise OSError("امتلأ القرص")

        monkeypatch.setattr(وحدة.json, "dump", يسقط)
        with pytest.raises(OSError):
            سجل.consume("EP-2")

        assert list(json.loads(مسار.read_text(encoding="utf-8"))) == ["EP-1"]
        assert list(tmp_path.glob("*.tmp")) == []


# ═══════════════════════════════════════════════════════════════════════════
# 7 — الفصلُ يبلُغ الطبقةَ الفدراليّة لا يقف عند النواة
# ═══════════════════════════════════════════════════════════════════════════

class Testالوصولُالفدراليّ:
    """`ConstitutionalAuthorizer` كان حاكمًا ومُنفِّذًا معًا — وهذا مخرجُه."""

    @pytest.fixture()
    def مُصرِّح(self, بوابة):
        from amos_federation.services.executive_core.sovereignty_bridge import (
            ConstitutionalAuthorizer,
        )

        return ConstitutionalAuthorizer(gateway=بوابة)

    def test_موضع_انفاذ_فدرالي_لا_يملك_بوابة(self, مُصرِّح, سجلُّ_الاستهلاك):
        نقطة = مُصرِّح.enforcement_point(consumed=سجلُّ_الاستهلاك)
        assert isinstance(نقطة, PolicyEnforcementPoint)
        assert not hasattr(نقطة, "_gateway")
        assert not hasattr(نقطة, "_engine")

    def test_النواة_التنفيذية_تطلب_اذنا_ثم_تُنفَّذ_به(
        self, مُصرِّح, سجلُّ_الاستهلاك, حالةُ_الدولة
    ):
        """القياسُ على الحالة: تغيّرت بإذنٍ صادرٍ لا بسلطةٍ ذاتيّة."""
        إذن = مُصرِّح.request_permit("credit_account", TARGET, (_أثر(),))
        نقطة = مُصرِّح.enforcement_point(consumed=سجلُّ_الاستهلاك)
        نقطة.enforce(
            إذن, planner=lambda p: (_أثر(),), applier=_مُطبِّق(حالةُ_الدولة)
        )
        assert حالةُ_الدولة[TARGET] == "MUTATED"
        assert إذن.authority_layer == "FEDERAL"

    def test_الاذن_الفدرالي_لا_يتجاوز_ما_أُعلِن(
        self, مُصرِّح, سجلُّ_الاستهلاك, حالةُ_الدولة
    ):
        إذن = مُصرِّح.request_permit("credit_account", TARGET, (_أثر(),))
        نقطة = مُصرِّح.enforcement_point(consumed=سجلُّ_الاستهلاك)
        with pytest.raises(PermitScopeError):
            نقطة.enforce(
                إذن,
                planner=lambda p: (_أثر(kind=EffectKind.DELETE),),
                applier=_مُطبِّق(حالةُ_الدولة),
            )
        assert حالةُ_الدولة[TARGET] == "1000"
