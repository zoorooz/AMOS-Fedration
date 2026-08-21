"""
AMOS-Federation Tests — Q-31 Money Engine Wiring
الهدف: إثباتُ أنَّ المُحرِّكَ الدستوريَّ يُسأَلُ فعلًا قبلَ تحريكِ المالِ وأنَّ الرفضَ يمنع
النطاق: tests — حِرزُ قرارِ Q-31 (الخيارُ الثاني · W-015)
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-21 (Q-31)
تعتمد على: services/executive_core/money_authority.py · common/money_delegation.py

## لماذا حِرزٌ مستقلٌّ لا زيادةٌ في حِرزِ Q-19

حِرزُ Q-19 يُثبِّتُ **وجودَ التفويض**، وهذا الحِرزُ يُثبِّتُ **نفاذَ الحكم**. وهما
دعوَيانِ تسقطُ إحداهما دونَ الأخرى: قد يوجدُ تفويضٌ ولا يُسأَلُ المُحرِّك، وقد
يُسأَلُ المُحرِّكُ فلا يُغلَقُ على رفضِه. ففصلُهما يجعلُ سقوطَ كلٍّ منهما مقروءًا.

## ما يُثبِتُه هذا الحِرز

1. أنَّ المُحرِّكَ **يُسأَلُ حقًّا** — لا أنَّ اسمَ دالّةٍ ذُكِرَ في مصدرٍ.
2. أنَّ غيرَ `ALLOW` **يُغلِقُ** ولا يمرُّ ولا يُصبحُ تنبيهًا.
3. أنَّ الفاعلَ **لا يُحفَظُ** بينَ النداءاتِ — منعُ عَودِ سابقةِ 2A بُنيةً.
4. أنَّ الفعلَ الدستوريَّ يُؤخَذُ من الجدولِ المُعلَنِ لا من نصٍّ يُمرِّرُه منادٍ.
5. **الحدُّ المُعلَن**: أنَّ الفرضَ يشملُ أربعةً من عشرةِ مواضعَ لا كلَّها (Q-32).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

REPO_MARKER = "core/constitutional_engine/rules.py"


def _repo_root() -> Path:
    for parent in [Path(__file__).resolve(), *Path(__file__).resolve().parents]:
        if (parent / REPO_MARKER).exists():
            return parent
    raise AssertionError("لم يُعثَر على جذرِ المستودعِ من موضعِ الاختبار")


@pytest.fixture(autouse=True)
def _core_on_path() -> None:
    """اجعلْ نواةَ الدستورِ قابلةً للاستيرادِ مهما كانَ ترتيبُ الاختبارات.

    هذا هو إصلاحُ W-014 نفسُه ولنفسِ السبب: من دونِه ينجحُ الملفُّ حينَ يُشغَّلُ بعدَ
    ملفٍّ آخرَ هيَّأَ المسارَ، ويسقطُ حينَ يُشغَّلُ أوّلًا — نجاحٌ بحظِّ الترتيبِ لا بحقّ.
    """
    import sys

    root = str(_repo_root())
    if root not in sys.path:
        sys.path.insert(0, root)


@pytest.fixture
def money_authority() -> Any:
    from amos_federation.services.executive_core import money_authority

    return money_authority


# ── 1 · المُحرِّكُ يُسأَلُ حقًّا ────────────────────────────────────────────
def test_engine_is_really_consulted_and_returns_sealed_evidence(money_authority: Any) -> None:
    """نداءٌ واحدٌ مُفوَّضٌ يُنتِجُ أثرًا مُسلسَلًا من المُحرِّكِ لا قيمةً مُختلَقة."""
    evidence = money_authority.require_constitutional_money_authority(
        "treasury.allocation.create",
        entrypoint="allocate",
        target="institution:i-guard",
    )
    assert evidence.decision == "ALLOW"
    assert evidence.action == "allocate_funds"
    assert evidence.target == "institution:i-guard"
    # قواعدُ مُقيَّمةٌ فعلًا: صفرٌ يعني أنَّ المُحرِّكَ لم يعملْ.
    assert evidence.rules_evaluated > 0
    # بصمةُ الطلبِ وقيدُ السجلِّ أثرٌ لا يُنتَجُ إلّا من المُحرِّك.
    assert evidence.request_fingerprint
    assert evidence.ledger_entry_hash


def test_declared_action_comes_from_the_table_not_from_the_caller(money_authority: Any) -> None:
    """المنادي يُسمّي العمليّةَ لا الفعلَ الدستوريَّ — فلا يختارُ ما يُحكَمُ عليه."""
    evidence = money_authority.require_constitutional_money_authority(
        "treasury.disbursement.post",
        entrypoint="disburse",
        target="institution:i-guard",
    )
    assert evidence.action == "disburse_funds"


# ── 2 · الرفضُ يمنعُ ولا يُنبِّه ────────────────────────────────────────────
def test_non_allow_verdict_closes_the_money_path(
    money_authority: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """أيُّ حكمٍ غيرِ `ALLOW` يرفعُ رفضًا — لا تسجيلًا ولا مرورًا بافتراض.

    الحكمُ يُبدَّلُ بالحقنِ لا بتغييرِ قاعدةٍ دستوريّة: فتبديلُ الدستورِ ليختبرَ
    نفسَه بابٌ للتلاعب، والمقصودُ هنا إثباتُ **سلوكِ الإغلاق** لا إثباتُ قاعدة.
    """
    from amos_federation.services.executive_core.sovereignty_bridge import (
        AuthorityEvidence,
        ConstitutionalAuthorizer,
    )

    denied = AuthorityEvidence(
        action="allocate_funds",
        target="institution:i-guard",
        decision="DENY",
        authority_layer="FEDERAL",
        decision_kind="REVIEW",
        request_fingerprint="fp-test",
        ledger_entry_hash="hash-test",
        rules_evaluated=31,
        advisory_violations=("مخالفةٌ مُصطنَعةٌ للاختبار",),
    )
    monkeypatch.setattr(
        ConstitutionalAuthorizer, "review_only", lambda self, *a, **k: denied, raising=True
    )

    with pytest.raises(money_authority.ConstitutionalMoneyDenialError) as raised:
        money_authority.require_constitutional_money_authority(
            "treasury.allocation.create",
            entrypoint="allocate",
            target="institution:i-guard",
        )
    message = str(raised.value)
    assert "treasury.allocation.create" in message
    assert "allocate_funds" in message
    assert "TREASURY" in message
    assert "DENY" in message
    assert raised.value.evidence is denied


def test_denial_is_a_permission_error_not_a_treasury_fault(money_authority: Any) -> None:
    """رفضُ الدستورِ حدٌّ يُحترَمُ لا عطلٌ يُعادُ — فنوعُه من عائلةِ الصلاحيات."""
    assert issubclass(money_authority.ConstitutionalMoneyDenialError, PermissionError)
    assert not issubclass(money_authority.ConstitutionalMoneyDenialError, RuntimeError)


def test_only_allow_passes_and_the_constant_is_not_a_loose_string(money_authority: Any) -> None:
    """`ALLOW` وحدَه يُمرِّر، ومقابلةُ الحكمِ بمساواةٍ صريحةٍ لا باحتواءِ نصّ."""
    assert money_authority.ALLOWED_DECISION == "ALLOW"
    source = Path(money_authority.__file__).read_text(encoding="utf-8")
    assert "!= ALLOWED_DECISION" in source
    assert "in evidence.decision" not in source


# ── 3 · لا حفظَ لفاعلٍ — منعُ عَودِ سابقةِ 2A ──────────────────────────────
def test_gateway_is_shared_but_the_actor_tagged_authorizer_is_never_cached(
    money_authority: Any,
) -> None:
    """البوّابةُ (آلةٌ بلا فاعل) تُحفَظ، والمُصرِّحُ (حاملُ الفاعل) يُبنى كلَّ نداء."""
    first = money_authority._authorizer_for("TREASURY")
    second = money_authority._authorizer_for("TREASURY")
    assert first is not second, "حفظُ مُصرِّحٍ موسومٍ بالخزانةِ هو عينُ سابقةِ 2A"
    assert first.gateway is second.gateway, "بناءُ بوّابةٍ لكلِّ نداءٍ كُلفةٌ بلا سبب"


def test_no_module_level_authorizer_is_constructed(money_authority: Any) -> None:
    """لا مُصرِّحَ يُبنى وقتَ التحميل: الوسمُ بالجملةِ يبدأُ من سطرٍ كهذا."""
    source = Path(money_authority.__file__).read_text(encoding="utf-8")
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        if line.startswith("_") and "ConstitutionalAuthorizer(" in line:
            raise AssertionError(f"مُصرِّحٌ مبنيٌّ في مستوى الوحدة: {line!r}")


# ── 4 · التفويضُ يسبقُ سؤالَ المُحرِّك ──────────────────────────────────────
def test_undeclared_operation_is_refused_before_the_engine_is_asked(
    money_authority: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """عمليّةٌ بلا تفويضٍ لا تصلُ المُحرِّكَ أصلًا — الترتيبُ مقصودٌ لا عَرَض."""
    from amos_federation.common.money_delegation import UndeclaredMoneyDelegationError
    from amos_federation.services.executive_core.sovereignty_bridge import (
        ConstitutionalAuthorizer,
    )

    def _must_not_be_called(self: Any, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("سُئِلَ المُحرِّكُ عن عمليّةٍ بلا تفويضٍ مُعلَن")

    monkeypatch.setattr(ConstitutionalAuthorizer, "review_only", _must_not_be_called, raising=True)
    with pytest.raises(UndeclaredMoneyDelegationError):
        money_authority.require_constitutional_money_authority(
            "treasury.sneaky.move",
            entrypoint="allocate",
            target="institution:i-guard",
        )


def test_declared_operation_through_an_undeclared_entrypoint_is_refused(
    money_authority: Any,
) -> None:
    """عمليّةٌ مُعلَنةٌ من مدخلٍ غيرِ مُعلَنٍ تُرَدُّ — فلا يُستعارُ تفويضُ غيرِ موضعِه."""
    from amos_federation.common.money_delegation import UndeclaredMoneyDelegationError

    with pytest.raises(UndeclaredMoneyDelegationError):
        money_authority.require_constitutional_money_authority(
            "treasury.allocation.create",
            entrypoint="wrong_door",
            target="institution:i-guard",
        )


# ── 5 · الوصلُ قائمٌ في مسارِ التخويلِ فعلًا ────────────────────────────────
def test_authorize_money_calls_the_enforcement_point_before_touching_the_database() -> None:
    """الفرضُ يسبقُ لمسَ القاعدة: موضعُ النداءِ في المصدرِ قبلَ أيِّ استعلام."""
    service = (
        _repo_root()
        / "federal/executive/services/src/amos_federation/services/state_treasury/service.py"
    ).read_text(encoding="utf-8")
    body = service.split("def _authorize_money(", 1)[1]
    enforcement = body.index("require_constitutional_money_authority(")
    for query_marker in ("session.query(", "require_treasury_authority("):
        assert enforcement < body.index(
            query_marker
        ), f"«{query_marker}» يسبقُ فرضَ الحكمِ الدستوريِّ في `_authorize_money`"


def test_treasury_asks_the_single_enforcement_point_and_builds_no_bridge() -> None:
    """الخزانةُ تسألُ نقطةً واحدةً ولا تبني جسرًا سياديًّا ثانيًا لنفسِها."""
    service = (
        _repo_root()
        / "federal/executive/services/src/amos_federation/services/state_treasury/service.py"
    ).read_text(encoding="utf-8")
    # نداءٌ واحدٌ بقوسٍ لا أكثر: واحدٌ لأربعةِ مواضعَ، والاستيرادُ لا يحملُ قوسًا.
    assert service.count("require_constitutional_money_authority(") == 1
    assert service.count("require_constitutional_money_authority") == 2
    assert "ConstitutionalAuthorizer" not in service
    assert "sovereignty_bridge" not in service


# ── 6 · الحدُّ المُعلَن: أربعةٌ من عشرةٍ لا عشرةٌ من عشرة (Q-32) ─────────────
def test_the_enforced_scope_is_declared_as_four_of_ten_sites() -> None:
    """لا يُدَّعى ما ليس مفروضًا: ستّةُ مواضعَ لا تمرُّ بطبقةِ التخويلِ فتبقى بلا حكم.

    هذا القيدُ يحرسُ **صدقَ الدعوى** لا الشِّفرة: فلو وُسِّعَ النطاقُ غدًا سقطَ هنا،
    فيُحدَّثُ العددُ مع الوثيقةِ ومع قرارِ **Q-32** — لا في صمت.
    """
    from amos_federation.common.money_delegation import MONEY_DELEGATIONS

    treasury_src = (
        _repo_root()
        / "federal/executive/services/src/amos_federation/services/state_treasury/service.py"
    ).read_text(encoding="utf-8")
    economy_src = (
        _repo_root()
        / "federal/executive/services/src/amos_federation/services/national_economy/service.py"
    ).read_text(encoding="utf-8")

    # المواضعُ التي تُحضِرُ تفويضَها بنفسِها لا تمرُّ بـ`_authorize_money`، فلا يُسألُ
    # المُحرِّكُ عنها. وسطرُ الاستيرادِ لا يُعدُّ لأنّه لا يحملُ قوسًا.
    direct = treasury_src.count("resolve_money_delegation(") + economy_src.count(
        "resolve_money_delegation("
    )
    assert len(MONEY_DELEGATIONS) == 10
    assert direct == 6, "تغيّرَ عددُ المواضعِ غيرِ المفروضةِ دستوريًّا — حدِّثْ Q-32"
