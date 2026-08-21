"""
AMOS-Federation Tests — Q-19 Money Delegation Guard
الهدف: إثباتُ أنَّ كلَّ عمليّةٍ ماليّةٍ لها تفويضٌ مُعلَنٌ مفروضٌ، وأنّه لا وسمَ جملةٍ لخدمة
النطاق: federal/executive/services/tests
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-21 (Q-19)

## ما يحرسُه هذا الملفّ ولماذا هكذا

قرارُ **Q-19** (الخيارُ 2) يُلزِمُ بشيءٍ ويمنعُ شيئًا، فالحرسُ في بابَين:

- **الإلزام:** لكلِّ عمليّةٍ ماليّةٍ تفويضٌ مكتوبٌ باسمِها، و**العمليّةُ التي لا
  تفويضَ لها لا تمرّ**. ولا يُقاسُ ذلك بقراءةِ الجدولِ وحدَه — تُستدعى الدالّةُ
  الحارسةُ فعلًا ويُنتظَرُ رفضُها، ويُقرأُ **نصُّ المصدرِ** ليُثبَتَ أنَّ كلَّ
  موضعِ نداءٍ ماليٍّ يمرُّ بها.
- **المنع:** لا يُنسَخُ نمطُ سابقةِ 2A إلى خدمةٍ ماليّة. فيُفحَصُ مصدرُ خدمتَي
  الخزانةِ والاقتصادِ: لا `ConstitutionalAuthorizer(actor=...)` فيهما ولا ثابتُ
  فاعلٍ على مستوى الوحدة.

وقراءةُ المصدرِ هنا مقصودةٌ لا مُتحايَلٌ بها: القدرةُ المطلوبةُ هي «لا موضعَ نداءٍ
ماليٍّ بلا تفويض»، وهي خاصّيّةُ **الملفِّ كلِّه** لا خاصّيّةُ نداءٍ واحدٍ يُشغَّل.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from amos_federation.common.money_delegation import (
    MONEY_DELEGATIONS,
    TREASURY_BRANCH,
    MoneyDelegation,
    UndeclaredMoneyDelegationError,
    assert_lexicon_agreement,
    declared_money_operations,
    resolve_money_delegation,
)

SRC = Path(__file__).resolve().parents[1] / "src" / "amos_federation"
TREASURY_SRC = SRC / "services" / "state_treasury" / "service.py"
ECONOMY_SRC = SRC / "services" / "national_economy" / "service.py"

#: مواضعُ النداءِ الماليّةُ المقيسةُ في المصدرِ — عمليّةٌ ومدخلٌ لكلِّ موضع.
MEASURED_CALL_SITES: tuple[tuple[str, str], ...] = (
    ("treasury.establish", "establish_treasury"),
    ("treasury.account.open", "open_account"),
    ("treasury.budget.create", "create_budget"),
    ("treasury.allocation.create", "allocate"),
    ("treasury.funding.post", "post_funding"),
    ("treasury.disbursement.post", "disburse"),
    ("treasury.disbursement.post", "execute_decision_disbursement"),
    ("treasury.transaction.reverse", "reverse_transaction"),
    ("economy.expenditure.authorize", "authorize_expenditure"),
    ("economy.transfer.execute", "execute_transfer"),
)


# ── 1 · الجدولُ نفسُه ────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _core_on_path() -> None:
    """اهتدِ إلى النواةِ قبلَ كلِّ اختبارٍ — ولا يُتّكَلُ على ترتيبِ التشغيل.

    قِيسَ أنَّ اختبارًا يستوردُ `core` مباشرةً كانَ ينجحُ **بحظِّ الترتيب**: اختبارٌ
    أسبقُ ينادي `assert_lexicon_agreement()` فيُضيفُ الجذرَ إلى المسار، فيجدُهُ
    التالي مُضافًا. ولمّا بُعثِرَ الترتيبُ سقط. وحارسٌ يعتمدُ على ترتيبٍ عِلّتُهُ
    فيهِ لا في محروسِه، فأُصلِحَ بجذرِه: كلُّ اختبارٍ يبدأُ والنواةُ مُهتدًى إليها.
    """
    assert_lexicon_agreement()


def test_every_delegation_actor_is_treasury() -> None:
    """لا فاعلَ غيرَ الخزانةِ في جدولِ المال — وإلّا فهو نقلُ اختصاصٍ مُقنَّع."""
    for delegation in MONEY_DELEGATIONS:
        assert delegation.actor == TREASURY_BRANCH, delegation.operation


def test_no_delegation_uses_a_scoped_constitutional_action() -> None:
    """الفعلُ الدستوريُّ غيرُ نطاقيٍّ قطعًا — التسميةُ النطاقيّةُ رُفِضَت في Q-18."""
    for delegation in MONEY_DELEGATIONS:
        assert "." not in delegation.constitutional_action, delegation.operation


def test_every_delegation_declares_a_readable_basis() -> None:
    """سندٌ فارغٌ يُقرأُ سهوًا لا قرارًا — فلا يُقبَل."""
    for delegation in MONEY_DELEGATIONS:
        assert delegation.basis.strip(), delegation.operation
        assert len(delegation.basis.strip()) >= 20, delegation.operation


def test_no_duplicate_operation_entrypoint_pair() -> None:
    """تفويضانِ لمدخلٍ واحدٍ يعني سؤالَين عن ريالٍ واحد."""
    keys = [(d.operation, d.entrypoint) for d in MONEY_DELEGATIONS]
    assert len(keys) == len(set(keys))


def test_delegation_is_frozen_so_it_cannot_be_edited_at_runtime() -> None:
    """التفويضُ عقدٌ لا حالةٌ — من أرادَ تغييرَه يُغيّرُ المصدرَ ويُراجَع."""
    delegation = MONEY_DELEGATIONS[0]
    with pytest.raises((AttributeError, TypeError)):
        delegation.actor = "EXECUTIVE"  # type: ignore[misc]


# ── 2 · المطابقةُ لمعجمِ Q-18 (حقيقةٌ واحدةٌ لا حقيقتان) ─────────────────
def test_lexicon_agreement_holds_on_the_real_repository() -> None:
    """الجدولُ يُطابقُ معجمَ Q-18 على المستودعِ الحقيقيِّ لا على نسخةٍ مصنوعة."""
    assert_lexicon_agreement()


def test_every_declared_action_is_a_treasury_exclusive_verb() -> None:
    """كلُّ فعلٍ مُفوَّضٍ محصورٌ بالخزانةِ في المعجمِ الدستوريّ."""
    from core.constitutional_engine.rules import TREASURY_ACTIONS

    for delegation in MONEY_DELEGATIONS:
        assert delegation.constitutional_action in TREASURY_ACTIONS


def test_delegation_and_lexicon_never_disagree_about_an_operation() -> None:
    """لا تقولُ العمليّةُ فعلَين: واحدًا في التفويضِ وآخرَ في جدولِ الترجمة."""
    from core.constitutional_engine.rules import MONEY_OPERATION_LEXICON

    for delegation in MONEY_DELEGATIONS:
        assert MONEY_OPERATION_LEXICON[delegation.operation] == delegation.constitutional_action


# ── 3 · الفرضُ: الرفضُ يقعُ فعلًا ────────────────────────────────────────
def test_resolve_returns_the_declared_delegation_for_each_measured_site() -> None:
    """كلُّ موضعِ نداءٍ ماليٍّ مقيسٍ له تفويضٌ يُحضَرُ فعلًا لا نظريًّا."""
    for operation, entrypoint in MEASURED_CALL_SITES:
        delegation = resolve_money_delegation(operation, entrypoint=entrypoint)
        assert isinstance(delegation, MoneyDelegation)
        assert delegation.operation == operation
        assert delegation.entrypoint == entrypoint
        assert delegation.actor == TREASURY_BRANCH


def test_undeclared_operation_is_refused() -> None:
    """عمليّةٌ ماليّةٌ لم تُعلَن لا تمرّ — وهذا هو نصُّ Q-19 مفروضًا."""
    with pytest.raises(UndeclaredMoneyDelegationError) as excinfo:
        resolve_money_delegation("treasury.secret.drain", entrypoint="drain")
    assert "treasury.secret.drain" in str(excinfo.value)
    assert "Q-19" in str(excinfo.value)


def test_declared_operation_from_an_undeclared_entrypoint_is_refused() -> None:
    """المدخلُ جزءٌ من التفويضِ: عمليّةٌ مُعلَنةٌ من مدخلٍ آخرَ لا تمرّ.

    هذا هو البابُ الذي يُسدُّ به «إعادةُ استعمالِ اسمِ عمليّةٍ مُفوَّضةٍ» في دالّةٍ
    جديدةٍ لم تُراجَع.
    """
    with pytest.raises(UndeclaredMoneyDelegationError):
        resolve_money_delegation("treasury.disbursement.post", entrypoint="quiet_pay")


def test_declared_operations_are_read_from_the_table_not_hardcoded() -> None:
    """قائمةُ العمليّاتِ تُقرأُ من الجدولِ فلا تفترقُ عنه."""
    assert declared_money_operations() == {d.operation for d in MONEY_DELEGATIONS}
    assert declared_money_operations() == {op for op, _ in MEASURED_CALL_SITES}


# ── 4 · قراءةُ المصدر: لا موضعَ ماليًّا بلا تفويض ────────────────────────
def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize(("operation", "entrypoint"), MEASURED_CALL_SITES)
def test_each_measured_call_site_passes_through_the_delegation_gate(
    operation: str, entrypoint: str
) -> None:
    """كلُّ موضعِ نداءٍ ماليٍّ في المصدرِ يمرُّ بالبوّابةِ باسمِه ومدخلِه.

    يُقرأُ نصُّ المصدرِ لأنَّ المطلوبَ خاصّيّةُ الملفِّ لا خاصّيّةُ نداءٍ واحد. ومن
    نزعَ البوّابةَ غدًا من موضعٍ واحدٍ يسقطُ هنا ولو نجحَ كلُّ اختبارٍ حيّ.
    """
    source = _source(ECONOMY_SRC if operation.startswith("economy.") else TREASURY_SRC)
    if entrypoint in {"allocate", "post_funding", "disburse", "reverse_transaction"}:
        # هذه تعبرُ `_authorize_money`، فالمدخلُ يُمرَّرُ إليها معامَلًا.
        pattern = rf'"{re.escape(operation)}",\s*\n\s*entrypoint="{entrypoint}",'
    else:
        pattern = (
            rf"resolve_money_delegation\(\s*\n?\s*\"{re.escape(operation)}\",\s*"
            rf'entrypoint="{entrypoint}"'
        )
    assert re.search(pattern, source), f"{operation} · {entrypoint}"


def test_authorize_money_layer_cannot_be_called_without_an_entrypoint() -> None:
    """طبقةُ التخويلِ تطلبُ المدخلَ إلزامًا، فلا تُنادى بلا تفويضٍ يُحضَر."""
    source = _source(TREASURY_SRC)
    assert re.search(r"def _authorize_money\(", source)
    signature = source[source.index("def _authorize_money(") :][:900]
    assert "entrypoint: str," in signature
    body_start = source.index("if grant_required:", source.index("def _authorize_money("))
    prelude = source[source.index("def _authorize_money(") : body_start]
    assert "resolve_money_delegation(operation, entrypoint=entrypoint)" in prelude


def test_every_money_call_site_count_matches_the_declared_table() -> None:
    """عددُ نداءاتِ البوّابةِ في المصدرِ يساوي عددَ التفويضاتِ المُعلَنة.

    فمن أضافَ تفويضًا ولم يربطْه، أو ربطَ نداءً ولم يُعلِنْه، يسقطُ هنا.
    """
    treasury = _source(TREASURY_SRC).count("resolve_money_delegation(")
    economy = _source(ECONOMY_SRC).count("resolve_money_delegation(")
    # العددُ مقيسٌ لا مُقدَّر: في الخزانةِ أربعةُ نداءاتٍ مباشرةٍ للعمليّاتِ
    # التي لا تعبُرُ طبقةَ التخويل، ونداءٌ واحدٌ داخلَ `_authorize_money` يخدمُ
    # الأربعَ الباقيةَ لأنّها تُمرِّرُ مدخلَها معامَلًا — فخمسة. وفي
    # الاقتصادِ نداءانِ مباشران. وسطرُ الاستيرادِ لا يُعدُّ لأنّه لا يحملُ قوسًا.
    assert treasury == 5
    assert economy == 2
    assert len(MONEY_DELEGATIONS) == len(MEASURED_CALL_SITES) == 10


# ── 5 · المنع: لا وسمَ جملةٍ لخدمةٍ ماليّة (نصُّ Q-19) ───────────────────
@pytest.mark.parametrize("path", [TREASURY_SRC, ECONOMY_SRC])
def test_no_service_wide_treasury_actor_tag(path: Path) -> None:
    """لا خدمةَ ماليّةً مَوسومةً بفاعلِ خزانةٍ على مستوى الوحدةِ أو البناء.

    هذا نصُّ ما منعَه Q-19: سابقةُ 2A بنَتْ مُصرِّحًا واحدًا بفاعلِ خزانةٍ لكائنِ
    التشغيلِ كلِّه. ونسخُ ذلك إلى خدمةٍ ذاتِ سبعِ عمليّاتٍ يُخوِّلُ ما لم يُقرَأ.
    """
    source = _source(path)
    assert "ConstitutionalAuthorizer(" not in source
    assert not re.search(r"^TREASURY_ACTOR\s*=", source, re.MULTILINE)
    assert not re.search(r"actor\s*=\s*[\"']TREASURY[\"']", source)


def test_the_2a_precedent_still_carries_the_wholesale_tag_it_is_measured_not_denied() -> None:
    """سابقةُ 2A ما زالت تحملُ الوسمَ بالجملة — يُقاسُ ولا يُنكَر.

    نقضُ السابقةِ آخرُ الترتيبِ المُلزِمِ ولم يُنفَّذْ بعد. فيُثبَّتُ الواقعُ هنا كما
    هو، فإن نُقِضَ غدًا سقطَ هذا الاختبارُ فنبَّهَ على أنَّ الوثيقةَ تحتاجُ تحديثًا —
    لا أن يُقالَ اليومَ إنَّ النمطَ زالَ وهو قائم.
    """
    runtime = _source(SRC / "services" / "governance" / "state_runtime.py")
    assert 'TREASURY_ACTOR = "TREASURY"' in runtime
    assert "ConstitutionalAuthorizer(actor=TREASURY_ACTOR)" in runtime


# ── 6 · الحدُّ المُعلَن: المُحرِّكُ لم يُوصَلْ بعد (Q-31) ─────────────────
def test_engine_is_not_yet_invoked_in_the_money_path_and_that_is_declared() -> None:
    """لا يُدَّعى ما ليس مفروضًا: مسارُ المالِ لا يستدعي المُحرِّكَ بعد.

    قرارُ **Q-31** حُسِمَ بالخيارِ الثاني (الوصلُ في طبقةِ التخويلِ وحدَها) ويُنفَّذُ
    بعدَ هذا القيد. وحتّى يُنفَّذَ، هذا الاختبارُ يُثبِّتُ الحدَّ صريحًا فلا تُقرأُ
    وثيقةُ Q-19 على أنّها أنجزَت ما لم تُنجِزْه. ومن وصلَ المُحرِّكَ غدًا يسقطُ هنا
    فيُحدِّثُ الوثيقةَ مع الوصلِ — وذلك مقصودٌ لا عَرَض.
    """
    treasury = _source(TREASURY_SRC)
    assert "ActionRequest" not in treasury
    assert "ConstitutionalEngine" not in treasury
