"""الهدف: إثبات علوّ السلطة الملكية تنفيذيًّا — معايير E2.1 الخمسة والعشرون.

المالك: tests/sovereignty/ — التاج
تاريخ الإنشاء: 2026-08-16
تاريخ آخر تعديل: 2026-08-16
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from datetime import datetime, timezone

import pytest
import core.sovereignty.crown as crown_mod
from core.constitutional_engine.engine import ConstitutionalEngine
from core.constitutional_engine.ledger import ConstitutionalLedger
from core.constitutional_engine.model import ActionRequest, Branch, CrownEffect
from core.constitutional_engine.rules import RULES
from core.sovereignty.authority import (
    AuthorityLayer,
    SovereigntyModelError,
    assert_no_layer_above_crown,
    classify,
    layer_of_actor,
    supreme_layer,
)
from core.sovereignty.crown import provision_crown
from core.sovereignty.decree import RoyalDecree, sign_decree
from core.sovereignty.gateway import (
    FORBIDDEN_BYPASS_PARAMS,
    RoyalImpersonation,
    SovereignGateway,
    SovereigntyViolation,
)
from core.sovereignty.compensation import Compensator
from core.sovereignty.contract import EffectKind, SovereignEffect
from core.sovereignty.enforcement_boundary import SovereignExecutionBoundary
from core.sovereignty.gateways import (
    AgentGateway,
    LayerEscalationError,
    StateGateway,
    SubordinateGateway,
)
from core.sovereignty.idempotency import IdempotencyKey, IdempotencyLedger
from core.sovereignty.prerogatives import ROYAL_EXCLUSIVE_ACTIONS
from core.sovereignty.security_events import SecurityEventKind
from cryptography.hazmat.primitives import serialization


@pytest.fixture(scope="function")
def crown(monkeypatch, tmp_path):
    key_path = tmp_path / "crown.pem"
    registry = tmp_path / "CROWN_KEYS.json"
    provision_crown(key_path, registry_path=registry)
    monkeypatch.setattr(crown_mod, "CROWN_KEYS_PATH", registry)
    priv = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    return priv, crown_mod.load_crown().key_id


@pytest.fixture(scope="function")
def بوابة(tmp_path):
    المحرك = ConstitutionalEngine(ledger=ConstitutionalLedger(tmp_path / "السجل.jsonl"))
    return SovereignGateway(المحرك)


def مرسوم_صحيح(مفتاح, معرف: str, فعل: str, **حقول) -> RoyalDecree:
    غير_موقع = RoyalDecree(
        decree_id=معرف,
        action=فعل,
        issued_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        key_id=حقول.pop("key_id"),
        **حقول,
    )
    return sign_decree(غير_موقع, مفتاح)


def طلب_ملكي(مرسوم: RoyalDecree, **حقول) -> ActionRequest:
    return ActionRequest(actor=Branch.ROYAL, action=مرسوم.action, royal_decree=مرسوم, **حقول)


class Testمعايير_السلطة_العليا:
    def test_لا_طبقة_فوق_التاج(self) -> None:
        assert supreme_layer() is AuthorityLayer.CROWN, "الطبقة العليا ليست التاج."
        assert_no_layer_above_crown()

    def test_الدستور_لا_ينقض_مرسوما_صحيحا(self, crown, بوابة) -> None:
        مفتاح, معرف_المفتاح = crown
        مرسوم = مرسوم_صحيح(مفتاح, "دستور-1", "amend_constitution", key_id=معرف_المفتاح)
        نُفذ: list[str] = []
        نتيجة = بوابة.execute(طلب_ملكي(مرسوم), lambda: نُفذ.append("تم") or "النتيجة")
        assert نتيجة == "النتيجة", "لم تُعَد نتيجة التنفيذ السيادي."
        assert نُفذ == ["تم"], "نقض الدستور التنفيذ رغم صحة المرسوم."
        assert "A005" in بوابة.records[-1].advisory_articles, "لم تُسجَّل ملاحظة الدستور."

    def test_الفدرالية_لا_تنقض_مرسوما_صحيحا(self, crown, بوابة) -> None:
        مفتاح, معرف_المفتاح = crown
        مرسوم = مرسوم_صحيح(مفتاح, "فدرالية-1", "create_state", key_id=معرف_المفتاح)
        نُفذ: list[str] = []
        بوابة.execute(طلب_ملكي(مرسوم, target="ولاية-أ"), lambda: نُفذ.append("تم"))
        assert نُفذ == ["تم"], "الإجراء الفدرالي نقض مرسوم التاج بدل تسجيل ملاحظته."
        assert "A004" in بوابة.records[-1].advisory_articles, "لم تُسجَّل ملاحظة الفدرالية."

    def test_الولاية_لا_تنقض_مرسوما_صحيحا(self, crown, بوابة) -> None:
        مفتاح, معرف_المفتاح = crown
        مرسوم = مرسوم_صحيح(مفتاح, "ولاية-1", "opt_out_constitution", key_id=معرف_المفتاح)
        نُفذ: list[str] = []
        بوابة.execute(طلب_ملكي(مرسوم, target="ولاية-أ"), lambda: نُفذ.append("تم"))
        assert نُفذ == ["تم"], "قاعدة الولاية منعت مرسومًا ملكيًّا صحيحًا."
        assert "A004" in بوابة.records[-1].advisory_articles, "لم تُسجَّل ملاحظة الولاية."

    def test_المؤسسة_لا_تنقض_مرسوما_صحيحا(self, crown, بوابة) -> None:
        مفتاح, معرف_المفتاح = crown
        مرسوم = مرسوم_صحيح(مفتاح, "مؤسسة-1", "delete_memory", key_id=معرف_المفتاح)
        نُفذ: list[str] = []
        بوابة.execute(طلب_ملكي(مرسوم), lambda: نُفذ.append("تم"))
        assert نُفذ == ["تم"], "قاعدة المؤسسة منعت مرسومًا ملكيًّا صحيحًا."
        assert "A001" in بوابة.records[-1].advisory_articles, "لم تُسجَّل ملاحظة المؤسسة."

    def test_الوكيل_لا_ينقض_مرسوما_صحيحا(self, crown, بوابة) -> None:
        مفتاح, معرف_المفتاح = crown
        مرسوم = مرسوم_صحيح(مفتاح, "وكيل-1", "self_modify", key_id=معرف_المفتاح)
        نُفذ: list[str] = []
        بوابة.execute(طلب_ملكي(مرسوم), lambda: نُفذ.append("تم"))
        assert نُفذ == ["تم"], "قاعدة الوكيل منعت مرسومًا ملكيًّا صحيحًا."
        assert "A001" in بوابة.records[-1].advisory_articles, "لم تُسجَّل الملاحظة الدستورية."

    def test_القضاء_لا_ينقض_مرسوما_صحيحا(self, crown, بوابة) -> None:
        مفتاح, معرف_المفتاح = crown
        مرسوم = مرسوم_صحيح(مفتاح, "قضاء-1", "execute_task", key_id=معرف_المفتاح)
        نُفذ: list[str] = []
        بوابة.execute(طلب_ملكي(مرسوم, criticality="critical"), lambda: نُفذ.append("تم"))
        assert نُفذ == ["تم"], "قيد اختصاص القضاء منع مرسومًا ملكيًّا صحيحًا."
        assert "A003" in بوابة.records[-1].advisory_articles, "لم تُسجَّل ملاحظة القضاء."

    def test_توقيع_غير_صحيح_يرفض_ويسجل_ولا_ينفذ(self, crown, بوابة) -> None:
        مفتاح, معرف_المفتاح = crown
        صحيح = مرسوم_صحيح(مفتاح, "مزور-1", "create_state", key_id=معرف_المفتاح)
        مزور = RoyalDecree.from_dict({**صحيح.to_dict(), "signature_hex": "aa" * 64})
        نُفذ: list[str] = []
        with pytest.raises(RoyalImpersonation) as خطأ:
            بوابة.execute(طلب_ملكي(مزور), lambda: نُفذ.append("تم"))
        assert خطأ.value.event_kind is SecurityEventKind.ROYAL_SIGNATURE_INVALID, "لم يُصنَّف التوقيع المزور."
        assert بوابة.security_log.events[-1].kind is SecurityEventKind.ROYAL_SIGNATURE_INVALID, "لم يُسجَّل التوقيع المزور."
        assert نُفذ == [], "نُفذ فعل بتوقيع غير صحيح."

    def test_أمر_ملكي_بلا_مرسوم_يرفض_ويسجل_ولا_ينفذ(self, بوابة) -> None:
        نُفذ: list[str] = []
        with pytest.raises(RoyalImpersonation) as خطأ:
            بوابة.execute(ActionRequest(actor=Branch.ROYAL, action="create_state"), lambda: نُفذ.append("تم"))
        assert خطأ.value.event_kind is SecurityEventKind.ROYAL_COMMAND_UNSIGNED, "لم يُرفض الأمر غير الموقَّع."
        assert بوابة.security_log.events[-1].kind is SecurityEventKind.ROYAL_COMMAND_UNSIGNED, "لم يُسجَّل الأمر غير الموقَّع."
        assert نُفذ == [], "نُفذ أمر ملكي بلا مرسوم."

    def test_مرسوم_لفعل_آخر_يرفض_ويسجل(self, crown, بوابة) -> None:
        مفتاح, معرف_المفتاح = crown
        مرسوم = مرسوم_صحيح(مفتاح, "توجيه-1", "create_state", key_id=معرف_المفتاح)
        طلب = ActionRequest(actor=Branch.ROYAL, action="dissolve_state", royal_decree=مرسوم)
        with pytest.raises(RoyalImpersonation) as خطأ:
            بوابة.execute(طلب, lambda: "لا ينبغي التنفيذ")
        assert خطأ.value.event_kind is SecurityEventKind.DECREE_ACTION_MISMATCH, "لم يُرفض توجيه المرسوم لفعل آخر."
        assert بوابة.security_log.events[-1].kind is SecurityEventKind.DECREE_ACTION_MISMATCH, "لم يُسجَّل اختلاف الفعل."

    def test_توقيع_صحيح_ينفذ_فعلا(self, crown, بوابة) -> None:
        مفتاح, معرف_المفتاح = crown
        مرسوم = مرسوم_صحيح(مفتاح, "تنفيذ-1", "pardon", key_id=معرف_المفتاح)
        نُفذ: list[str] = []
        نتيجة = بوابة.execute(طلب_ملكي(مرسوم), lambda: نُفذ.append("عفو") or 17)
        assert نُفذ == ["عفو"], "لم تُستدع الدالة المنفذة رغم التوقيع الصحيح."
        assert نتيجة == 17, "لم تُعَد نتيجة الدالة المنفذة."

    def test_لا_راية_تجاوز_مخفية_في_تواقيع_البوابة(self) -> None:
        for اسم in ("execute", "review", "__init__"):
            معاملات = set(inspect.signature(getattr(SovereignGateway, اسم)).parameters)
            assert not معاملات & FORBIDDEN_BYPASS_PARAMS, f"توقيع «{اسم}» يحمل راية تجاوز ممنوعة."

    def test_المسار_التابع_لا_يحتوي_شرطا_ملكيا_مدسوسا(self) -> None:
        مصدر = inspect.getsource(SovereignGateway._execute_subordinate)
        assert "ROYAL" not in مصدر and "CROWN" not in مصدر, "المسار التابع يذكر شرطًا ملكيًّا مدسوسًا."

    def test_المسار_السيادي_بلا_رفع_دستوري(self) -> None:
        مصدر = inspect.getsource(SovereignGateway._execute_sovereign)
        شجرة = ast.parse(textwrap.dedent(مصدر))
        assert not any(isinstance(عقدة, ast.Raise) for عقدة in ast.walk(شجرة)), (
            "المسار السيادي يحتوي رفعًا قد يمنع التنفيذ الدستوري."
        )

    def test_القرار_الفدرالي_العادي_يبقى_مقيدا(self, بوابة) -> None:
        نُفذ: list[str] = []
        with pytest.raises(SovereigntyViolation):
            بوابة.execute(ActionRequest(actor=Branch.EXECUTIVE, action="legislate"), lambda: نُفذ.append("تم"))
        assert نُفذ == [], "مر قرار فدرالي مخالف لاختصاص الفرع."

    def test_قرار_الولاية_يبقى_مقيدا(self, بوابة) -> None:
        نُفذ: list[str] = []
        with pytest.raises(SovereigntyViolation):
            بوابة.execute(ActionRequest(actor=Branch.STATE, action="opt_out_constitution"), lambda: نُفذ.append("تم"))
        assert نُفذ == [], "مر قرار ولاية مخالف للدستور."

    def test_قرار_الوكيل_يبقى_مقيدا(self, بوابة) -> None:
        نُفذ: list[str] = []
        with pytest.raises(SovereigntyViolation):
            بوابة.execute(ActionRequest(actor=Branch.AGENT, action="self_modify"), lambda: نُفذ.append("تم"))
        assert نُفذ == [], "مر قرار وكيل مخالف للدستور."

    def test_التدخل_الملكي_مسجل_قبل_التنفيذ(self, crown, بوابة) -> None:
        مفتاح, معرف_المفتاح = crown
        مرسوم = مرسوم_صحيح(مفتاح, "سجل-1", "pardon", key_id=معرف_المفتاح)
        أحداث_وقت_التنفيذ: list[SecurityEventKind] = []

        def منفذ() -> str:
            أحداث_وقت_التنفيذ.extend(حدث.kind for حدث in بوابة.security_log.events)
            return "تم"

        assert بوابة.execute(طلب_ملكي(مرسوم), منفذ) == "تم", "لم ينفذ التدخل الملكي."
        assert أحداث_وقت_التنفيذ[-1] is SecurityEventKind.SOVEREIGN_INTERVENTION, "لم يُسجَّل التدخل قبل التنفيذ."

    def test_التدخل_الملكي_لا_يحتاج_موافقة_تابع(self, crown, بوابة) -> None:
        مفتاح, معرف_المفتاح = crown
        مرسوم = مرسوم_صحيح(مفتاح, "استقلال-1", "pardon", key_id=معرف_المفتاح)
        معاملات = inspect.signature(SovereignGateway._execute_sovereign).parameters
        assert not {"موافقة", "approval", "approver"} & set(معاملات), "المسار السيادي يقبل موافقة تابعة."
        assert بوابة.execute(طلب_ملكي(مرسوم), lambda: "تم") == "تم", "توقف التدخل السيادي لغياب موافقة تابعة."

    def test_الأصل_عدم_التدخل_والقرار_العادي_لا_يمر_بالسيادي(self, monkeypatch, بوابة) -> None:
        def سيادة_غير_متوقعة(*_وسائط, **_حقول):
            raise AssertionError("استُدعي المسار السيادي لقرار عادي.")

        monkeypatch.setattr(بوابة, "_execute_sovereign", سيادة_غير_متوقعة)
        assert بوابة.execute(ActionRequest(actor=Branch.EXECUTIVE, action="execute_task"), lambda: "عادي") == "عادي", "لم ينفذ القرار العادي."

    def test_التدخل_السيادي_يعمل_لكل_اختصاص_حصري(self, crown) -> None:
        مفتاح, معرف_المفتاح = crown
        بوابة = SovereignGateway()
        نتائج: list[str] = []
        for رقم, فعل in enumerate(sorted(ROYAL_EXCLUSIVE_ACTIONS)):
            مرسوم = مرسوم_صحيح(مفتاح, f"حصري-{رقم}", فعل, key_id=معرف_المفتاح)
            نتيجة = بوابة.execute(طلب_ملكي(مرسوم), lambda فعل=فعل: نتائج.append(فعل) or فعل)
            assert نتيجة == فعل, f"لم يُعَد تنفيذ الاختصاص الحصري «{فعل}»."
        assert set(نتائج) == set(ROYAL_EXCLUSIVE_ACTIONS), "لم ينفذ كل اختصاص ملكي حصري."

    def test_المرسوم_المشوه_ممنوع_عند_تكرار_المحاولة(self, crown, بوابة) -> None:
        مفتاح, معرف_المفتاح = crown
        صحيح = مرسوم_صحيح(مفتاح, "إعادة-1", "pardon", key_id=معرف_المفتاح)
        مشوه = RoyalDecree.from_dict({**صحيح.to_dict(), "signature_hex": "aa" * 64})
        نُفذ: list[str] = []
        for _ in range(2):
            with pytest.raises(RoyalImpersonation) as خطأ:
                بوابة.execute(طلب_ملكي(مشوه), lambda: نُفذ.append("تم"))
            assert خطأ.value.event_kind is SecurityEventKind.ROYAL_SIGNATURE_INVALID, "قُبل المرسوم المشوه عند الإعادة."
        أحداث = [حدث.kind for حدث in بوابة.security_log.events]
        assert أحداث.count(SecurityEventKind.ROYAL_SIGNATURE_INVALID) == 2, "لم تُسجَّل كل محاولة مشوهة."
        assert نُفذ == [], "نُفذ مرسوم مشوه."

    def test_كل_القواعد_محروسة_وعددها_إحدى_وثلاثون(self, بوابة) -> None:
        """كانت ستًّا وعشرين، وأضاف المرسوم AMD-003 خمسًا: R-010-8..10 و R-011-1..2.

        والعددُ مقيَّدٌ عمدًا: زيادةُ قاعدةٍ بلا سندٍ مرسوميٍّ تُسقِط هذا الاختبار.
        """
        assert len(RULES) == 31, "تغيّر عدد القواعد الأمنية عن إحدى وثلاثين."
        assert بوابة.engine.unguarded_articles() == (), "توجد مادة سارية بلا حراسة تنفيذية."

    def test_أثر_التاج_قيمتان_ولا_قاعدة_تنقضه(self) -> None:
        assert set(CrownEffect) == {CrownEffect.ADVISORY, CrownEffect.AUTHENTICITY}, "أضيف أثر مانع ثالث للتاج."
        assert all(not قاعدة.can_veto_sovereign for قاعدة in RULES), "توجد قاعدة تملك نقض قرار سيادي."

    def test_قواعد_الأصالة_محصورة_بدقة(self) -> None:
        قواعد_الأصالة = {قاعدة.rule_id for قاعدة in RULES if قاعدة.guards_royal_authenticity}
        assert قواعد_الأصالة == {"R-010-3", "R-010-5"}, "تغيّرت حدود قواعد إثبات الأصالة."


class Testلا_نقض:
    @pytest.mark.parametrize("صنف_البوابة", [StateGateway, AgentGateway])
    def test_بوابة_تابعة_لا_تحمل_مرسوما_ملكيا(self, crown, بوابة, صنف_البوابة) -> None:
        مفتاح, معرف_المفتاح = crown
        مرسوم = مرسوم_صحيح(مفتاح, "حمل-1", "pardon", key_id=معرف_المفتاح)
        تابع = صنف_البوابة(بوابة)
        with pytest.raises(LayerEscalationError):
            تابع.execute(ActionRequest(actor=Branch.AGENT, action="pardon", royal_decree=مرسوم), lambda: "ممنوع")

    def test_بوابة_تابعة_لا_تترقى_إلى_طبقة_اعلى(self, بوابة) -> None:
        with pytest.raises(LayerEscalationError):
            AgentGateway(بوابة).execute(ActionRequest(actor=Branch.STATE, action="execute_task"), lambda: "ممنوع")

    def test_لا_تبنى_بوابة_تابعة_على_الطبقة_السيادية(self, بوابة) -> None:
        class بوابة_مدعاة(SubordinateGateway):
            layer = AuthorityLayer.CROWN

        with pytest.raises(SovereigntyModelError):
            بوابة_مدعاة(بوابة)

    def test_الفرع_الملكي_وحده_ليس_طبقة_التاج(self) -> None:
        assert layer_of_actor(Branch.ROYAL) is not AuthorityLayer.CROWN, "مجرد فرع ملكي منح طبقة التاج."

    def test_كائن_يشبه_المرسوم_يرفض_كليا(self, بوابة) -> None:
        class مرسوم_مشابه:
            decree_id = "شبيه"
            action = "pardon"

        طلب = ActionRequest(actor=Branch.ROYAL, action="pardon", royal_decree=مرسوم_مشابه())
        with pytest.raises(RoyalImpersonation) as خطأ:
            بوابة.execute(طلب, lambda: "ممنوع")
        assert خطأ.value.event_kind is SecurityEventKind.DECREE_TYPE_INVALID, "قُبل كائن شبيه بالمرسوم."

    def test_التاج_غير_المنصب_يجمد_الاختصاص(self, crown, monkeypatch, tmp_path, بوابة) -> None:
        مفتاح, معرف_المفتاح = crown
        monkeypatch.setattr(crown_mod, "CROWN_KEYS_PATH", tmp_path / "تاج-غائب.json")
        مرسوم = مرسوم_صحيح(مفتاح, "تجميد-1", "create_state", key_id=معرف_المفتاح)
        نُفذ: list[str] = []
        with pytest.raises(RoyalImpersonation) as خطأ:
            بوابة.execute(طلب_ملكي(مرسوم), lambda: نُفذ.append("تم"))
        assert خطأ.value.event_kind is SecurityEventKind.CROWN_UNPROVISIONED, "لم يُجمَّد الاختصاص عند غياب التاج."
        assert بوابة.security_log.events[-1].kind is SecurityEventKind.CROWN_UNPROVISIONED, "لم يُسجَّل غياب التاج."
        assert نُفذ == [], "نُقل الاختصاص أو نُفذ رغم غياب التاج."


class Testتكامل_شامل:
    def test_سلسلة_المرسوم_الصحيح_من_الأصالة_إلى_النتيجة(self, crown, بوابة) -> None:
        مفتاح, معرف_المفتاح = crown
        مرسوم = مرسوم_صحيح(مفتاح, "تكامل-موجب", "create_state", key_id=معرف_المفتاح)
        طلب = طلب_ملكي(مرسوم, target="ولاية-تكامل")
        تصنيف = classify(طلب)
        نُفذ: list[str] = []
        نتيجة = بوابة.execute(طلب, lambda: نُفذ.append("ولاية-تكامل") or {"حالة": "أُنشئت"})
        assert تصنيف.authenticity_verified, "لم تثبت أصالة المرسوم الصحيح."
        assert تصنيف.layer is AuthorityLayer.CROWN, "لم يمنح المرسوم الصحيح طبقة التاج."
        assert نُفذ == ["ولاية-تكامل"], "لم يقع التنفيذ الفعلي في سلسلة التكامل."
        assert نتيجة == {"حالة": "أُنشئت"}, "لم تُعَد نتيجة التنفيذ الفعلي."
        سجل = بوابة.records[-1]
        assert سجل.sovereign and سجل.executed, "لم يُسجَّل التنفيذ كقرار سيادي منفذ."
        assert سجل.authority_layer == AuthorityLayer.CROWN.name, "سجل التدقيق لا يثبت طبقة التاج."
        assert بوابة.security_log.events[-1].kind is SecurityEventKind.SOVEREIGN_INTERVENTION, "غياب حدث تدقيق التدخل السيادي."
        assert "A004" in سجل.advisory_articles, "توقفت السلسلة عند ملاحظة تابع بدل تسجيلها."

    def test_سلسلة_التوقيع_المزور_تنتهي_بالرفض_دون_تنفيذ(self, crown, بوابة) -> None:
        مفتاح, معرف_المفتاح = crown
        صحيح = مرسوم_صحيح(مفتاح, "تكامل-مزور", "pardon", key_id=معرف_المفتاح)
        مزور = RoyalDecree.from_dict({**صحيح.to_dict(), "signature_hex": "aa" * 64})
        نُفذ: list[str] = []
        with pytest.raises(RoyalImpersonation):
            بوابة.execute(طلب_ملكي(مزور), lambda: نُفذ.append("تم"))
        assert بوابة.security_log.events[-1].kind is SecurityEventKind.ROYAL_SIGNATURE_INVALID, "سلسلة الرفض لم تسجل التوقيع المزور."
        assert نُفذ == [], "سلسلة التوقيع المزور وصلت إلى التنفيذ."

    def test_سلسلة_القرار_التابع_تسمح_بالسليم_وتمنع_المخالف(self, بوابة, tmp_path) -> None:
        """هُجِّر في 1N إلى `execute_declared`: التمييزُ نفسُه، عبرَ الحدِّ لا بجانبِه.

        الأثرُ يُعلَن قبلَ وقوعِه ومعوّضُه مربوط، فما كان يُقاسُ على قيمةِ إرجاعٍ
        صار يُقاسُ على الحالةِ نفسِها — وهو قياسٌ أصدق.
        """
        حدّ = SovereignExecutionBoundary(
            gateway=بوابة,
            idempotency_ledger=IdempotencyLedger(path=tmp_path / "ذرّيّة.json"),
        )
        بوابة_ولاية = StateGateway(بوابة, boundary=حدّ)
        نُفذ: list[str] = []
        أثر = SovereignEffect(kind=EffectKind.WRITE, resource="ولاية-أ")
        معوّض = (Compensator(effect_signature=أثر.signature, apply=lambda: None),)

        حصيلة = بوابة_ولاية.execute_declared(
            ActionRequest(actor=Branch.STATE, action="execute_task", target="ولاية-أ"),
            declared_effects=(أثر,),
            applier=lambda _أثر: نُفذ.append("سليم"),
            operation_key=IdempotencyKey(scope="اختبار.تابع", value="سليم"),
            compensators=معوّض,
        )
        with pytest.raises(SovereigntyViolation):
            بوابة_ولاية.execute_declared(
                ActionRequest(actor=Branch.STATE, action="opt_out_constitution", target="ولاية-أ"),
                declared_effects=(أثر,),
                applier=lambda _أثر: نُفذ.append("مخالف"),
                operation_key=IdempotencyKey(scope="اختبار.تابع", value="مخالف"),
                compensators=معوّض,
            )
        assert حصيلة.applied_signatures == (أثر.signature,) and نُفذ == ["سليم"], "البوابات التابعة لم تميز بين القرار السليم والمخالف."
