"""الهدف: حرسُ معجمِ المالِ الدستوريِّ بعدَ قرارِ Q-18 — أفعالُ المالِ حصرٌ للخزانة.

النطاق: `core/constitutional_engine/rules.py` — `TREASURY_ACTIONS` وجدولُ الترجمةِ
والاستثناءُ المُعلَن، وحكمُ البوابةِ الفعليُّ على كلِّ فعلٍ ماليٍّ × كلِّ فاعل.
المالك: tests/governance/
تاريخ الإنشاء: 2026-08-21
تاريخ آخر تعديل: 2026-08-21

قاعدةُ هذا الملفّ: يقيسُ من المصدرِ لا من وثيقة. فلا يُثبّتُ عددًا حُفِظَ في
مِلفٍّ، بل يستدعي المُحرِّكَ فيقرأُ حكمَه. ومن نقضَ Q-18 غدًا يسقطُ هنا لا في مراجعة.
"""

from __future__ import annotations

import pytest

from core.constitutional_engine.engine import ConstitutionalEngine
from core.constitutional_engine.model import ActionRequest, Branch
from core.constitutional_engine.rules import (
    MONEY_OPERATION_LEXICON,
    NON_CONSTITUTIONAL_MONEY_ACTIONS,
    TREASURY_ACTIONS,
    _assert_money_lexicon_canonical,
)
from core.sovereignty.jurisdiction import FORBIDDEN_JUDICIAL_ACTIONS

# الأفعالُ التي أوجبَ قرارُ Q-18 إدخالَها المعجم — تُسمَّى هنا صريحةً لا مُشتقّة،
# فالاختبارُ الذي يشتقُّ توقُّعَه من المصدرِ لا يقيسُ شيئًا.
Q18_ADDED_ACTIONS = (
    "disburse_funds",
    "transfer_treasury",
    "establish_treasury",
    "open_account",
    "create_budget",
    "allocate_funds",
    "post_funding",
    "reverse_transaction",
    "authorize_expenditure",
    "execute_transfer",
    "award_procurement",
)

Q18_PRE_EXISTING_ACTIONS = (
    "allocate_budget",
    "issue_tokens",
    "allocate_resources",
    "book_expense",
)

NON_TREASURY_BRANCHES = (Branch.EXECUTIVE, Branch.LEGISLATIVE, Branch.JUDICIAL)


@pytest.fixture(scope="module")
def engine() -> ConstitutionalEngine:
    return ConstitutionalEngine()


def _verdict_name(engine: ConstitutionalEngine, actor: Branch, action: str) -> str:
    verdict = engine.evaluate(
        ActionRequest(actor=actor, action=action, target="test/q18")
    )
    decision = getattr(verdict, "decision", verdict)
    return getattr(decision, "value", str(decision))


# ── ١. المعجمُ يحتوي ما قرَّرَه القرارُ السياديّ ───────────────────────────────


@pytest.mark.parametrize("action", Q18_ADDED_ACTIONS)
def test_q18_added_action_is_in_lexicon(action: str) -> None:
    """كلُّ فعلٍ أوجبَه Q-18 موجودٌ في المعجم — لا نيّةٌ بلا نصّ."""
    assert action in TREASURY_ACTIONS, f"الفعلُ «{action}» أوجبَه Q-18 وليسَ في المعجم"


@pytest.mark.parametrize("action", Q18_PRE_EXISTING_ACTIONS)
def test_pre_q18_action_survives(action: str) -> None:
    """توسيعُ المعجمِ لا يحذفُ منه — التضييقُ يُضيفُ ولا يُسقِط."""
    assert action in TREASURY_ACTIONS


def test_lexicon_grew_and_did_not_shrink() -> None:
    """المعجمُ خمسةَ عشرَ فعلًا بعدَ Q-18، لا أقلّ — عددٌ مُعلَنٌ يُكسَرُ إن تراجعَ أحد."""
    assert len(TREASURY_ACTIONS) == 15, (
        f"المعجمُ {len(TREASURY_ACTIONS)} فعلًا. من زادَ أو نقصَ فعليه تعديلُ Q-18 "
        "في سجلِّ القراراتِ السياديّةِ وقيدُ عملٍ في سجلِّ الإنجاز، لا تعديلُ الرقمِ هنا."
    )


# ── ٢. حكمُ البوابةِ الفعليُّ لا المُتوقَّع ─────────────────────────────────────


@pytest.mark.parametrize("action", Q18_ADDED_ACTIONS + Q18_PRE_EXISTING_ACTIONS)
@pytest.mark.parametrize("actor", NON_TREASURY_BRANCHES)
def test_money_action_denied_to_non_treasury_branch(
    engine: ConstitutionalEngine, action: str, actor: Branch
) -> None:
    """لا فرعَ غيرُ الخزانةِ يُحرِّكُ مالًا — يُقاسُ بالاستدعاءِ لا بالقراءة."""
    assert (
        _verdict_name(engine, actor, action) == "DENY"
    ), f"الفاعلُ «{actor.value}» مرَّ بفعلِ المالِ «{action}». R-003-1 لم يُطبَّق."


@pytest.mark.parametrize("action", Q18_ADDED_ACTIONS + Q18_PRE_EXISTING_ACTIONS)
def test_money_action_allowed_to_treasury(
    engine: ConstitutionalEngine, action: str
) -> None:
    """التضييقُ لا يُعطِّلُ الخزانةَ نفسَها — وإلّا كانَ الإصلاحُ تعطيلًا."""
    assert _verdict_name(engine, Branch.TREASURY, action) == "ALLOW"


# ── ٣. منعُ التسميةِ النطاقيّةِ بنيةً لا وصيّةً ────────────────────────────────


@pytest.mark.parametrize("action", sorted(TREASURY_ACTIONS))
def test_no_scoped_name_in_lexicon(action: str) -> None:
    """لا اسمَ نطاقيًّا في معجمِ المال — «تحييدُ فعلٍ حصريٍّ» مرفوضٌ نصًّا."""
    assert "." not in action, f"الفعلُ «{action}» مُسمًّى باسمٍ نطاقيّ — مرفوضٌ بـQ-18"


def test_import_guard_rejects_scoped_money_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """الحرسُ يرفعُ فعلًا حينَ يُدسُّ اسمٌ نطاقيّ — حرسٌ يُختبَرُ لا حرسٌ يُدَّعى."""
    import core.constitutional_engine.rules as rules_module

    monkeypatch.setattr(
        rules_module, "TREASURY_ACTIONS", TREASURY_ACTIONS | {"treasury.disburse"}
    )
    with pytest.raises(ValueError, match="نطاقيّ"):
        _assert_money_lexicon_canonical()


def test_import_guard_rejects_lexicon_overlap(monkeypatch: pytest.MonkeyPatch) -> None:
    """لا فعلَ مالٍ يكونُ دستوريًّا ومُستثنًى في آنٍ واحد."""
    import core.constitutional_engine.rules as rules_module

    monkeypatch.setattr(
        rules_module, "NON_CONSTITUTIONAL_MONEY_ACTIONS", frozenset({"disburse_funds"})
    )
    with pytest.raises(ValueError, match="المُستثنى"):
        _assert_money_lexicon_canonical()


def test_import_guard_rejects_unknown_translation_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """جدولُ الترجمةِ لا يُحيلُ إلى فعلٍ خارجَ المعجم — وإلّا كانَ إحالةً إلى لا شيء."""
    import core.constitutional_engine.rules as rules_module

    monkeypatch.setattr(
        rules_module,
        "MONEY_OPERATION_LEXICON",
        {**MONEY_OPERATION_LEXICON, "treasury.ghost": "spend_without_law"},
    )
    with pytest.raises(ValueError, match="ليست في المعجم"):
        _assert_money_lexicon_canonical()


# ── ٤. الاستثناءُ مُعلَنٌ ومُبرَّرٌ بقرارٍ سابق ─────────────────────────────────


@pytest.mark.parametrize("action", sorted(NON_CONSTITUTIONAL_MONEY_ACTIONS))
def test_amos_credit_action_stays_out_of_lexicon(action: str) -> None:
    """amos-credit وحدةُ قياسٍ تشغيليّةٌ بقرارِ Q-17، فلا تدخلُ معجمَ المالِ الدستوريّ."""
    assert action not in TREASURY_ACTIONS


def test_excluded_set_is_not_empty() -> None:
    """الاستثناءُ مُثبَتٌ صريحًا — الاستثناءُ الفارغُ يُقرأُ سهوًا لا قرارًا."""
    assert NON_CONSTITUTIONAL_MONEY_ACTIONS


# ── ٥. سدُّ الثُغرةِ المقيسةِ في اختصاصِ القضاء ────────────────────────────────


@pytest.mark.parametrize(
    "action", ("allocate_budget", "disburse_funds", "transfer_treasury")
)
def test_judicially_forbidden_money_action_is_also_lexical(action: str) -> None:
    """ما مُنِعَ على القضاءِ اسمًا صارَ ممنوعًا على التنفيذِ حكمًا — الثُغرةُ سُدَّت.

    كانَ `disburse_funds` و`transfer_treasury` ممنوعَين على القضاءِ في
    `jurisdiction.py` وغائبَين عن المعجم، فمرَّا للتنفيذِ بحكمِ `ALLOW`.
    """
    assert action in FORBIDDEN_JUDICIAL_ACTIONS
    assert action in TREASURY_ACTIONS


# ── ٦. جدولُ الترجمةِ يُغطّي كلَّ عمليّةٍ مُغيِّرةٍ مُعلَنة ────────────────────


@pytest.mark.parametrize(
    "operation",
    (
        "treasury.establish",
        "treasury.account.open",
        "treasury.budget.create",
        "treasury.allocation.create",
        "treasury.funding.post",
        "treasury.disbursement.post",
        "treasury.decision.disburse",
        "treasury.transaction.reverse",
    ),
)
def test_declared_treasury_operation_has_lexical_verb(operation: str) -> None:
    """كلُّ اسمِ عمليّةٍ تُمرِّرُه خدمةُ الخزانةِ له فعلٌ معجميٌّ مُعلَن.

    الإعلانُ لا يُغني عن الفرضِ — والفرضُ مرهونٌ بحسمِ فاعلِ الخزانةِ في Q-19.
    """
    assert operation in MONEY_OPERATION_LEXICON
    assert MONEY_OPERATION_LEXICON[operation] in TREASURY_ACTIONS


def test_lexicon_translation_is_not_scoped_on_the_target_side() -> None:
    """طرفُ الجدولِ الأيمنُ أسماءٌ قانونيّةٌ لا نطاقيّة — وإلّا كانتِ الترجمةُ دورانًا."""
    for source, target in MONEY_OPERATION_LEXICON.items():
        assert "." not in target, f"«{source}» يُترجَمُ إلى اسمٍ نطاقيٍّ «{target}»"
