"""الهدف: قياسُ أثرِ المادة العاشرة · 10 — سحبُ الصلاحيةِ يمنع فعلًا، ومنحُها يعيده.

النطاق: `core/sovereignty/authority_grants.py` وحقنُها في `SovereignGateway`.
المالك: tests/sovereignty/ — ديوان التدقيق
تاريخ الإنشاء: 2026-08-18
تاريخ آخر تعديل: 2026-08-18

لا يفحصُ هذا الملفُّ وجودَ دالّةٍ ولا صحّةَ توقيعِها فحسبُ (القاعدة 12): يبني
ملكًا بمفتاحٍ حقيقيّ، ويوقّع مرسومًا حقيقيًّا، ويُمرِّر الفعلَ من **البوابةِ
نفسِها** التي تنفّذ بها الدولةُ، ويقيس هل وقعَ الفعلُ أم مُنِع.
"""

from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from core.constitutional_engine.engine import ConstitutionalEngine
from core.constitutional_engine.ledger import ConstitutionalLedger
from core.constitutional_engine.model import ActionRequest, Branch
from core.sovereignty import crown as crown_module
from core.sovereignty.authority import classify
from core.sovereignty.authority_grants import (
    ALL_CAPABILITIES,
    CONSTITUTIONAL_CARVE_OUTS,
    AuthorityGrant,
    AuthorityGrantRegistry,
    GrantState,
    NonSovereignGrantError,
    RoyalAuthorityErosionError,
)
from core.sovereignty.decree import RoyalDecree, sign_decree
from core.sovereignty.gateway import AuthorityWithdrawn, SovereignGateway

NOW = "2026-08-18T00:00:00+00:00"


# ═══════════════════════════════════════════════════════════════════════════
# تجهيزات: ملكٌ مُنصَّبٌ بمفتاحٍ حقيقيّ، وسجلٌّ في مسارٍ مؤقّت
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture()
def ملكٌ_مُنصَّب(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """تاجٌ حقيقيٌّ في مسارٍ مؤقّت — لا يمسُّ سجلَّ الدولةِ الحقيقيَّ بحال."""
    registry = tmp_path / "CROWN_KEYS.json"
    monkeypatch.setattr(crown_module, "CROWN_KEYS_PATH", registry)
    private_out = tmp_path / "vault" / "crown.pem"
    crown = crown_module.provision_crown(private_out, registry_path=registry)
    private = serialization.load_pem_private_key(
        private_out.read_bytes(), password=None
    )
    return private, crown


@pytest.fixture()
def سجل(tmp_path: Path) -> AuthorityGrantRegistry:
    return AuthorityGrantRegistry(path=tmp_path / "AUTHORITY_GRANTS.json")


@pytest.fixture()
def بوابة(tmp_path: Path, سجل: AuthorityGrantRegistry) -> SovereignGateway:
    engine = ConstitutionalEngine(ledger=ConstitutionalLedger(tmp_path / "l.jsonl"))
    return SovereignGateway(engine, grant_registry=سجل)


def _مرسوم(
    private: ed25519.Ed25519PrivateKey,
    action: str,
    *,
    key_id: str,
    decree_id: str = "DEC-AG-001",
    target: str | None = None,
) -> RoyalDecree:
    unsigned = RoyalDecree(
        decree_id=decree_id,
        action=action,
        target=target,
        issued_at=NOW,
        justification="قياسُ أثرِ المادة العاشرة · 10",
        key_id=key_id,
    )
    return sign_decree(unsigned, private)


def _تصنيفٌ_سياديّ(ملكٌ_مُنصَّب, *, action: str = "revoke_authority", decree_id="DEC-AG-001"):
    private, crown = ملكٌ_مُنصَّب
    decree = _مرسوم(private, action, key_id=crown.key_id, decree_id=decree_id)
    request = ActionRequest(
        actor=Branch.ROYAL,
        action=action,
        target="branch-executive",
        royal_decree=decree,
    )
    return classify(request)


# ═══════════════════════════════════════════════════════════════════════════
# 1. القدرةُ نفسُها: السحبُ يمنع، والمنحُ يُعيد
# ═══════════════════════════════════════════════════════════════════════════

class Testالسحبُيمنعفعلًا:
    def test_الفعلُ_يقع_قبل_السحب(self, بوابة: SovereignGateway) -> None:
        """خطُّ الأساس. بلا هذا الاختبار لا يُعرَف أن المنعَ لاحقًا سببُه السحب."""
        وقع: list[str] = []
        بوابة.execute(
            ActionRequest(actor=Branch.EXECUTIVE, action="deploy_service",
                          target="svc-a"),
            lambda: وقع.append("نُفِّذ"),
        )
        assert وقع == ["نُفِّذ"]

    def test_السحبُ_يمنع_الفعلَ_ولا_يُستدعى_المنفِّذ(
        self, بوابة: SovereignGateway, ملكٌ_مُنصَّب
    ) -> None:
        """القياسُ الجوهريُّ لـ1D: أثرٌ تشغيليٌّ لا اسمٌ في مجموعة."""
        بوابة.grants.withdraw(
            _تصنيفٌ_سياديّ(ملكٌ_مُنصَّب),
            grantee=Branch.EXECUTIVE,
            capability="deploy_service",
            reason="إعادةُ هيكلة",
        )
        وقع: list[str] = []
        with pytest.raises(AuthorityWithdrawn):
            بوابة.execute(
                ActionRequest(actor=Branch.EXECUTIVE, action="deploy_service",
                              target="svc-a"),
                lambda: وقع.append("نُفِّذ"),
            )
        assert وقع == [], "المنفِّذُ استُدعي بعد سحبِ الصلاحية — المنعُ شكليّ."

    def test_السحبُ_خاصٌّ_بفعلِه_لا_يعمُّ_غيرَه(
        self, بوابة: SovereignGateway, ملكٌ_مُنصَّب
    ) -> None:
        """سحبُ فعلٍ ليس تعطيلَ فاعل. ولو عمَّ لكان السحبُ عقوبةً عمياء."""
        بوابة.grants.withdraw(
            _تصنيفٌ_سياديّ(ملكٌ_مُنصَّب),
            grantee=Branch.EXECUTIVE,
            capability="deploy_service",
        )
        وقع: list[str] = []
        بوابة.execute(
            ActionRequest(actor=Branch.EXECUTIVE, action="publish_report",
                          target="rep-1"),
            lambda: وقع.append("نُفِّذ"),
        )
        assert وقع == ["نُفِّذ"]

    def test_السحبُ_خاصٌّ_بفاعلِه_لا_يعمُّ_الطبقةَ(
        self, بوابة: SovereignGateway, ملكٌ_مُنصَّب
    ) -> None:
        بوابة.grants.withdraw(
            _تصنيفٌ_سياديّ(ملكٌ_مُنصَّب),
            grantee=Branch.EXECUTIVE,
            capability="deploy_service",
        )
        وقع: list[str] = []
        بوابة.execute(
            ActionRequest(actor=Branch.LEGISLATIVE, action="deploy_service",
                          target="svc-a"),
            lambda: وقع.append("نُفِّذ"),
        )
        assert وقع == ["نُفِّذ"]

    def test_السحبُ_الجامعُ_يعمُّ_كلَّ_أفعالِ_الفاعل(
        self, بوابة: SovereignGateway, ملكٌ_مُنصَّب
    ) -> None:
        """المادة العاشرة · 10 · 1 تُبيح إيقافَ مؤسّسةٍ لا فعلٍ واحدٍ منها."""
        بوابة.grants.withdraw(
            _تصنيفٌ_سياديّ(ملكٌ_مُنصَّب),
            grantee=Branch.INSTITUTION,
            capability=ALL_CAPABILITIES,
            reason="إيقافُ مؤسّسة",
        )
        for فعل in ("publish_report", "deploy_service", "open_case"):
            with pytest.raises(AuthorityWithdrawn):
                بوابة.execute(
                    ActionRequest(actor=Branch.INSTITUTION, action=فعل, target="t"),
                    lambda: None,
                )

    def test_المنحُ_يُعيد_ما_سُحِب_بمرسومٍ_جديد(
        self, بوابة: SovereignGateway, ملكٌ_مُنصَّب
    ) -> None:
        """الاستعادةُ لا تكون بحذفِ سجلٍّ بل بمرسومٍ لاحقٍ يُسجَّل مثلَ سابقِه."""
        بوابة.grants.withdraw(
            _تصنيفٌ_سياديّ(ملكٌ_مُنصَّب, decree_id="DEC-AG-010"),
            grantee=Branch.EXECUTIVE,
            capability="deploy_service",
        )
        بوابة.grants.grant(
            _تصنيفٌ_سياديّ(ملكٌ_مُنصَّب, action="grant_authority",
                          decree_id="DEC-AG-011"),
            grantee=Branch.EXECUTIVE,
            capability="deploy_service",
        )
        وقع: list[str] = []
        بوابة.execute(
            ActionRequest(actor=Branch.EXECUTIVE, action="deploy_service",
                          target="svc-a"),
            lambda: وقع.append("نُفِّذ"),
        )
        assert وقع == ["نُفِّذ"]
        assert len(بوابة.grants.entries()) == 2, "الاستعادةُ محَتِ الأثرَ السابق."

    def test_الأخصُّ_يسبق_الجامعَ(
        self, بوابة: SovereignGateway, ملكٌ_مُنصَّب
    ) -> None:
        """إيقافُ مؤسّسةٍ مع استثناءِ فعلٍ واحدٍ يجب أن يكون مُعبَّرًا عنه."""
        بوابة.grants.withdraw(
            _تصنيفٌ_سياديّ(ملكٌ_مُنصَّب, decree_id="DEC-AG-020"),
            grantee=Branch.INSTITUTION,
            capability=ALL_CAPABILITIES,
        )
        بوابة.grants.grant(
            _تصنيفٌ_سياديّ(ملكٌ_مُنصَّب, action="grant_authority",
                          decree_id="DEC-AG-021"),
            grantee=Branch.INSTITUTION,
            capability="publish_report",
        )
        وقع: list[str] = []
        بوابة.execute(
            ActionRequest(actor=Branch.INSTITUTION, action="publish_report",
                          target="r"),
            lambda: وقع.append("نُفِّذ"),
        )
        assert وقع == ["نُفِّذ"]
        with pytest.raises(AuthorityWithdrawn):
            بوابة.execute(
                ActionRequest(actor=Branch.INSTITUTION, action="open_case",
                              target="c"),
                lambda: None,
            )


# ═══════════════════════════════════════════════════════════════════════════
# 2. لا سحبَ ولا منحَ إلّا عن قرارٍ سياديٍّ ثابتِ الأصالة
# ═══════════════════════════════════════════════════════════════════════════

class Testلامنحَبلامرسوم:
    def test_تصنيفٌ_تابعٌ_لا_يمنح_ولا_يسحب(
        self, سجل: AuthorityGrantRegistry
    ) -> None:
        تابع = classify(
            ActionRequest(actor=Branch.EXECUTIVE, action="revoke_authority",
                          target="x")
        )
        with pytest.raises(NonSovereignGrantError):
            سجل.withdraw(تابع, grantee=Branch.INSTITUTION, capability="open_case")
        assert سجل.entries() == (), "كُتِب سجلٌّ عن قرارٍ غيرِ سياديّ."

    def test_تصنيفٌ_مُنتحَلٌ_يدًا_لا_يُقبَل(self, سجل: AuthorityGrantRegistry) -> None:
        """لا يُقبَل تصنيفٌ يُكتَب حقلًا مكانَ تصنيفٍ يُثبَت تعميًّا."""
        from core.sovereignty.authority import (
            AuthorityClassification,
            AuthorityLayer,
            DecisionKind,
        )

        مُنتحَل = AuthorityClassification(
            kind=DecisionKind.SOVEREIGN_ROYAL,
            layer=AuthorityLayer.CROWN,
            claimed_royal=True,
            authenticity_verified=False,  # لم يُثبَت
            decree_id="DEC-FAKE",
            reason="ادّعاء",
        )
        with pytest.raises(NonSovereignGrantError):
            سجل.withdraw(مُنتحَل, grantee=Branch.INSTITUTION, capability="open_case")

    def test_قرارٌ_سياديٌّ_بلا_رقمِ_مرسومٍ_لا_يُسجَّل(
        self, سجل: AuthorityGrantRegistry
    ) -> None:
        from core.sovereignty.authority import (
            AuthorityClassification,
            AuthorityLayer,
            DecisionKind,
        )

        بلا_سند = AuthorityClassification(
            kind=DecisionKind.SOVEREIGN_ROYAL,
            layer=AuthorityLayer.CROWN,
            claimed_royal=True,
            authenticity_verified=True,
            decree_id=None,
            reason="بلا سند",
        )
        with pytest.raises(NonSovereignGrantError):
            سجل.withdraw(بلا_سند, grantee=Branch.INSTITUTION, capability="open_case")

    def test_ممنوحٌ_ليس_فاعلًا_معدودًا_يُرفَض(
        self, سجل: AuthorityGrantRegistry, ملكٌ_مُنصَّب
    ) -> None:
        from core.sovereignty.authority_grants import AuthorityGrantError

        with pytest.raises(AuthorityGrantError):
            سجل.withdraw(
                _تصنيفٌ_سياديّ(ملكٌ_مُنصَّب),
                grantee="executive",  # type: ignore[arg-type]
                capability="open_case",
            )

    def test_صلاحيةٌ_فارغةٌ_تُرفَض(
        self, سجل: AuthorityGrantRegistry, ملكٌ_مُنصَّب
    ) -> None:
        from core.sovereignty.authority_grants import AuthorityGrantError

        with pytest.raises(AuthorityGrantError):
            سجل.withdraw(
                _تصنيفٌ_سياديّ(ملكٌ_مُنصَّب),
                grantee=Branch.EXECUTIVE,
                capability="   ",
            )


# ═══════════════════════════════════════════════════════════════════════════
# 3. القاعدةُ الذهبيّة: لا سلطةَ فوق الملك، ولا سحبَ منه
# ═══════════════════════════════════════════════════════════════════════════

class Testلاسحبَمنالتاج:
    @pytest.mark.parametrize("فاعل", [Branch.ROYAL])
    def test_سحبُ_صلاحيةِ_الملكِ_يُرفَض(
        self, سجل: AuthorityGrantRegistry, ملكٌ_مُنصَّب, فاعل: Branch
    ) -> None:
        with pytest.raises(RoyalAuthorityErosionError):
            سجل.withdraw(
                _تصنيفٌ_سياديّ(ملكٌ_مُنصَّب), grantee=فاعل,
                capability=ALL_CAPABILITIES,
            )
        assert سجل.entries() == ()

    def test_منحُ_الملكِ_صلاحيةً_يُرفَض_أيضًا(
        self, سجل: AuthorityGrantRegistry, ملكٌ_مُنصَّب
    ) -> None:
        """صلاحيةُ الملكِ أصلٌ لا منحةٌ: ومَن يمنح يستطيع أن يمنع."""
        with pytest.raises(RoyalAuthorityErosionError):
            سجل.grant(
                _تصنيفٌ_سياديّ(ملكٌ_مُنصَّب, action="grant_authority"),
                grantee=Branch.ROYAL,
                capability="pardon",
            )

    def test_المسارُ_السياديُّ_لا_يقرأ_سجلَّ_السحبِ_أصلًا(
        self, بوابة: SovereignGateway, ملكٌ_مُنصَّب
    ) -> None:
        """قياسٌ لا وعد: مرسومٌ ملكيٌّ ينفُذ ولو كان لفعلٍ مسحوبٍ من غيرِه."""
        private, crown = ملكٌ_مُنصَّب
        بوابة.grants.withdraw(
            _تصنيفٌ_سياديّ(ملكٌ_مُنصَّب, decree_id="DEC-AG-030"),
            grantee=Branch.EXECUTIVE,
            capability="create_state",
        )
        decree = _مرسوم(private, "create_state", key_id=crown.key_id,
                        decree_id="DEC-AG-031", target="state-x")
        وقع: list[str] = []
        بوابة.execute(
            ActionRequest(actor=Branch.ROYAL, action="create_state",
                          target="state-x", royal_decree=decree),
            lambda: وقع.append("نُفِّذ"),
        )
        assert وقع == ["نُفِّذ"], "سُحِبت صلاحيةٌ فمنعت الملكَ — سلطةٌ فوق التاج."


# ═══════════════════════════════════════════════════════════════════════════
# 4. §10 · 2 — الممنوحُ لا ينقلب حقًّا سياديًّا مستقلًّا
# ═══════════════════════════════════════════════════════════════════════════

class Testلاحقَّسياديًّامنمنحة:
    def test_لا_حقلَ_يمنع_السحب(self) -> None:
        """ضمانةٌ بنيويّة: لو وُجد حقلٌ كهذا لصار للمؤسّسةِ حقٌّ في وجه الملك."""
        أسماء = {f.name for f in fields(AuthorityGrant)}
        ممنوعة = {
            "irrevocable", "permanent", "protected", "immutable",
            "non_withdrawable", "sovereign", "independent", "locked",
        }
        assert أسماء & ممنوعة == set(), f"حقولٌ تُنشئ حقًّا سياديًّا: {أسماء & ممنوعة}"

    def test_الاستثناءاتُ_الدستوريّةُ_فارغةٌ_قياسًا(self) -> None:
        """لا مادّةَ مختومةً تُنشئ مجالًا لا يدخله الملك — فلا تُخترَع واحدة."""
        assert CONSTITUTIONAL_CARVE_OUTS == frozenset()

    def test_السحبُ_ينفُذ_مهما_تكرّر_المنحُ_قبله(
        self, سجل: AuthorityGrantRegistry, ملكٌ_مُنصَّب
    ) -> None:
        """لا «تحصينَ بالتكرار»: آخرُ مرسومٍ هو النافذ، ولو كان سحبًا."""
        for رقم in range(3):
            سجل.grant(
                _تصنيفٌ_سياديّ(ملكٌ_مُنصَّب, action="grant_authority",
                              decree_id=f"DEC-AG-04{رقم}"),
                grantee=Branch.EXECUTIVE,
                capability="deploy_service",
            )
        سجل.withdraw(
            _تصنيفٌ_سياديّ(ملكٌ_مُنصَّب, decree_id="DEC-AG-049"),
            grantee=Branch.EXECUTIVE,
            capability="deploy_service",
        )
        assert سجل.is_withdrawn(Branch.EXECUTIVE.value, "deploy_service") is True

    def test_حالاتُ_المنحِ_اثنتان_ولا_حالةَ_صامتة(self) -> None:
        assert {s.value for s in GrantState} == {"ACTIVE", "WITHDRAWN"}


# ═══════════════════════════════════════════════════════════════════════════
# 5. مصدرُ الحقيقةِ على القرص — لا في ذاكرةِ عمليّة
# ═══════════════════════════════════════════════════════════════════════════

class Testمصدرُالحقيقةعلىالقرص:
    def test_السحبُ_يُقرَأ_من_عمليّةٍ_أخرى(
        self, tmp_path: Path, ملكٌ_مُنصَّب
    ) -> None:
        """سجلٌّ ثانٍ على المسارِ نفسِه يرى السحبَ بلا أيِّ حالةٍ مشتركةٍ بينهما."""
        مسار = tmp_path / "AUTHORITY_GRANTS.json"
        AuthorityGrantRegistry(path=مسار).withdraw(
            _تصنيفٌ_سياديّ(ملكٌ_مُنصَّب),
            grantee=Branch.EXECUTIVE,
            capability="deploy_service",
        )
        آخر = AuthorityGrantRegistry(path=مسار)
        assert آخر.is_withdrawn(Branch.EXECUTIVE.value, "deploy_service") is True

    def test_سجلٌّ_غيرُ_موجودٍ_لا_يمنع_ولا_ينفجر(self, tmp_path: Path) -> None:
        """الغيابُ عدمُ سحبٍ لا عدمُ منح: وإلّا توقّفت الدولةُ عند أوّلِ تشغيل."""
        فارغ = AuthorityGrantRegistry(path=tmp_path / "لا-يوجد.json")
        assert فارغ.entries() == ()
        assert فارغ.is_withdrawn("executive", "deploy_service") is False

    def test_الملفُّ_نصٌّ_عربيٌّ_مقروءٌ_بمرجعِه(
        self, tmp_path: Path, ملكٌ_مُنصَّب
    ) -> None:
        مسار = tmp_path / "AUTHORITY_GRANTS.json"
        AuthorityGrantRegistry(path=مسار).withdraw(
            _تصنيفٌ_سياديّ(ملكٌ_مُنصَّب),
            grantee=Branch.EXECUTIVE,
            capability="deploy_service",
        )
        محتوى = json.loads(مسار.read_text(encoding="utf-8"))
        assert محتوى["المرجع"] == "المادة العاشرة · 10"
        assert محتوى["grants"][0]["decree_id"] == "DEC-AG-001"
        assert محتوى["grants"][0]["state"] == "WITHDRAWN"

    def test_الفحصُ_الذاتيُّ_يُعلن_السحوبَ_النافذة(
        self, بوابة: SovereignGateway, ملكٌ_مُنصَّب
    ) -> None:
        assert بوابة.self_check()["active_withdrawals"] == 0
        بوابة.grants.withdraw(
            _تصنيفٌ_سياديّ(ملكٌ_مُنصَّب),
            grantee=Branch.EXECUTIVE,
            capability="deploy_service",
        )
        assert بوابة.self_check()["active_withdrawals"] == 1


# ═══════════════════════════════════════════════════════════════════════════
# 6. الأثرُ مُسجَّل: المنعُ يُرى ولا يكون صامتًا
# ═══════════════════════════════════════════════════════════════════════════

class Testالمنعُمرئيّ:
    def test_حدثٌ_أمنيٌّ_يُسجَّل_عند_استعمالِ_صلاحيةٍ_مسحوبة(
        self, بوابة: SovereignGateway, ملكٌ_مُنصَّب
    ) -> None:
        from core.sovereignty.security_events import SecurityEventKind

        بوابة.grants.withdraw(
            _تصنيفٌ_سياديّ(ملكٌ_مُنصَّب),
            grantee=Branch.EXECUTIVE,
            capability="deploy_service",
        )
        with pytest.raises(AuthorityWithdrawn):
            بوابة.execute(
                ActionRequest(actor=Branch.EXECUTIVE, action="deploy_service",
                              target="svc-a"),
                lambda: None,
            )
        أنواع = [e.kind for e in بوابة.security_log.events]
        assert SecurityEventKind.WITHDRAWN_AUTHORITY_USE in أنواع

    def test_المنعُ_يُدوَّن_في_سجلِّ_التنفيذِ_غيرَ_مُنفَّذ(
        self, بوابة: SovereignGateway, ملكٌ_مُنصَّب
    ) -> None:
        بوابة.grants.withdraw(
            _تصنيفٌ_سياديّ(ملكٌ_مُنصَّب),
            grantee=Branch.EXECUTIVE,
            capability="deploy_service",
        )
        with pytest.raises(AuthorityWithdrawn):
            بوابة.execute(
                ActionRequest(actor=Branch.EXECUTIVE, action="deploy_service",
                              target="svc-a"),
                lambda: None,
            )
        أثر = بوابة.records[-1]
        assert أثر.executed is False
        assert أثر.decision == "AUTHORITY_WITHDRAWN"

    def test_المنعُ_ليس_حكمًا_دستوريًّا_مُخالفًا(
        self, بوابة: SovereignGateway, ملكٌ_مُنصَّب
    ) -> None:
        """زوالُ الاختصاصِ ليس مخالفةَ قاعدة، والخلطُ بينهما يُفسِد التحقيق."""
        from core.sovereignty.gateway import SovereigntyViolation

        بوابة.grants.withdraw(
            _تصنيفٌ_سياديّ(ملكٌ_مُنصَّب),
            grantee=Branch.EXECUTIVE,
            capability="deploy_service",
        )
        with pytest.raises(AuthorityWithdrawn) as مرفوع:
            بوابة.execute(
                ActionRequest(actor=Branch.EXECUTIVE, action="deploy_service",
                              target="svc-a"),
                lambda: None,
            )
        assert not isinstance(مرفوع.value, SovereigntyViolation)
        assert مرفوع.value.grant.capability == "deploy_service"

    def test_السحبُ_لا_يُفلَت_بفارقِ_حالةِ_حرف(
        self, بوابة: SovereignGateway, ملكٌ_مُنصَّب
    ) -> None:
        بوابة.grants.withdraw(
            _تصنيفٌ_سياديّ(ملكٌ_مُنصَّب),
            grantee=Branch.EXECUTIVE,
            capability="Deploy_Service",
        )
        assert بوابة.grants.is_withdrawn(Branch.EXECUTIVE.value,
                                        "deploy_service") is True


# ═══════════════════════════════════════════════════════════════════════════
# 7. لا معاملَ تجاوزٍ في الواجهةِ الجديدة
# ═══════════════════════════════════════════════════════════════════════════

class Testلاتجاوزَفيالواجهة:
    @pytest.mark.parametrize("اسمُ_الدالّة", ["withdraw", "grant"])
    def test_لا_معاملَ_تجاوزٍ(self, اسمُ_الدالّة: str) -> None:
        import inspect

        from core.sovereignty.gateway import FORBIDDEN_BYPASS_PARAMS

        معاملات = set(
            inspect.signature(getattr(AuthorityGrantRegistry, اسمُ_الدالّة))
            .parameters
        )
        assert معاملات & FORBIDDEN_BYPASS_PARAMS == set()

    def test_البوابةُ_الحقيقيّةُ_تُنشَأ_بسجلٍّ_على_القرص(self) -> None:
        """بوابةٌ بلا معاملٍ تقرأ سجلَّ الدولةِ الحقيقيَّ لا سجلًّا في الذاكرة."""
        from core.sovereignty.authority_grants import GRANTS_PATH

        assert SovereignGateway().grants.path == GRANTS_PATH
