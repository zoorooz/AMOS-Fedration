"""
AMOS-Federation Common — Money Delegation
الهدف: لا يتحرّكُ مالٌ عامٌّ إلّا بتفويضٍ مُعلَنٍ لفاعلِ الخزانةِ عندَ عمليّتِه بعينِها
النطاق: common — مفردةٌ مشتركةٌ بينَ خزانةِ الدولةِ والاقتصادِ الوطنيّ
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-21 (Q-19)
تعتمد على: core/constitutional_engine/rules.py — معجمُ المالِ المحسومُ في Q-18

## لماذا تفويضٌ لكلِّ عمليّةٍ لا وسمٌ لخدمةٍ كاملة

حُسِمَ **Q-19** بالخيارِ الثاني: «فاعلُ الخزانةِ لكلِّ عمليّةٍ على حِدَةٍ بتفويضٍ
مُعلَن». والقرارُ يُلزِمُ نصًّا بشيءٍ ويمنعُ نصًّا شيئًا:

- **يُلزِمُ** بأن يكونَ لكلِّ عمليّةٍ ماليّةٍ تفويضٌ **مكتوبٌ باسمِها** يقولُ: أيُّ
  فعلٍ دستوريٍّ تُمارِسُه، وبأيِّ فاعلٍ، ومن أيِّ مدخلٍ في الشِّفرة.
- **ويمنعُ** «نقلَ الاختصاصِ بالجملة»: لا تُوسَمُ خدمةٌ كاملةٌ بفاعلِ خزانةٍ.

وهذا عينُ ما فعلتْه سابقةُ **2A** في `governance/state_runtime.py`: بنَتْ
`ConstitutionalAuthorizer(actor=TREASURY_ACTOR)` **مرّةً واحدةً لكائنِ التشغيلِ
كلِّه**، فصارَ كلُّ ما يمرُّ من ذلك الكائنِ خزانةً بحكمِ البناءِ لا بحكمِ عمليّةٍ
مُعلَنة. ولو نُسِخَ ذلك النمطُ إلى خدمةِ خزانةِ الدولةِ (1795 سطرًا · 7 عمليّاتٍ
مُغيِّرة) لكانَ **وسمًا بالجملةِ** يُخوِّلُ ما لم يُقرَأْ.

فالفاعلُ هنا لا يُبنى مع الخدمة، بل **يُستخرَجُ من جدولٍ عندَ كلِّ نداءٍ**، ومن
نادى بعمليّةٍ لا تفويضَ لها **يُرَدُّ رفضًا صريحًا** لا يمرُّ بافتراض.

## الحدُّ المُعلَنُ لهذه الوحدة (لا يُدَّعى ما ليس مفروضًا)

هذه الوحدةُ تُثبتُ **وجودَ التفويضِ** شرطًا لتحريكِ المال، ولا تُقدِّمُ الفاعلَ
إلى المُحرِّكِ الدستوريِّ بعد. وتقديمُه هو **Q-31** المحسومُ بالخيارِ الثاني
(الوصلُ في طبقةِ التخويلِ وحدَها)، ويُنفَّذُ بعدَ هذا القيدِ لا معه — فمن قرأَ هذا
الملفَّ اليومَ فليعلمْ أنَّ الحكمَ الدستوريَّ لم يُستدعَ منه بعد.

## لماذا الحرسُ على مرحلتَين

فحوصُ الاتّساقِ الذاتيِّ (لا فاعلَ غريبٌ · لا تكرارَ مدخلٍ · لا سندَ فارغٌ · لا
اسمَ نطاقيٌّ لفعلٍ دستوريّ) تُجرى عندَ **استيرادِ** الوحدةِ لأنّها لا تحتاجُ شيئًا
خارجَها. أمّا مطابقةُ الجدولِ لمعجمِ Q-18 فتحتاجُ `core/`، وهذه الوحدةُ في
`common/` تُستوردُ في سياقاتٍ لا يكونُ فيها جذرُ المستودعِ على المسار — فربطُ
استيرادِها بنجاحِ استيرادِ النواةِ يُسقِطُ خدماتٍ لا علاقةَ لها بالمال. فأُخِّرَتْ
المطابقةُ إلى **أوّلِ نداءٍ فعليٍّ** على `resolve_money_delegation` وحُفِظَتْ
نتيجتُها، فلا تتحرّكُ ريالٌ واحدةٌ قبلَ أن تُطابَقَ بالمعجمِ ولو مرّة. والاختبارُ
الحاكمُ يستدعي المطابقةَ صريحًا فلا تبقى مرهونةً بمسارِ تشغيل.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

__all__ = [
    "MONEY_DELEGATIONS",
    "TREASURY_BRANCH",
    "MoneyDelegation",
    "UndeclaredMoneyDelegationError",
    "assert_lexicon_agreement",
    "declared_money_operations",
    "resolve_money_delegation",
]

#: الفرعُ الدستوريُّ الذي يملكُ أفعالَ المالِ — يُعلَنُ صادقًا ولا يُقنَّعُ باسمٍ آخر.
TREASURY_BRANCH: Final[str] = "TREASURY"


class UndeclaredMoneyDelegationError(RuntimeError):
    """تحريكُ مالٍ بعمليّةٍ لا تفويضَ مُعلَنًا لها — رفضٌ صريحٌ لا مرورٌ بافتراض."""


@dataclass(frozen=True, slots=True)
class MoneyDelegation:
    """تفويضُ عمليّةٍ ماليّةٍ واحدةٍ — يُقرأُ ولا يُستنبَط.

    - ``operation``: اسمُ العمليّةِ كما تُمرِّرُه الخدمةُ إلى حدِّ التخويلِ (مفتاحُ
      مطابقةِ مِنَحِ R7-C). يبقى نطاقيًّا لأنّه **عقدُ بيانات** لا فعلٌ دستوريّ.
    - ``constitutional_action``: الفعلُ الدستوريُّ من معجمِ Q-18 — غيرُ نطاقيٍّ
      قطعًا، فالتسميةُ النطاقيّةُ لفعلِ مالٍ مرفوضةٌ نصًّا.
    - ``entrypoint``: اسمُ الدالّةِ في الخدمةِ التي تُمارِسُ الفعل. مُعلَنٌ لأنَّ
      عمليّةً واحدةً قد تُنادى من مدخلَين، فيُفوَّضُ كلُّ مدخلٍ على حِدَة.
    - ``actor``: الفاعلُ المُعلَنُ — خزانةٌ دائمًا، ويحرسُه فحصُ الاستيراد.
    - ``basis``: سندُ التفويضِ بالعربيّةِ. لا يُقبَلُ فارغًا: تفويضٌ بلا سندٍ
      يُقرأُ غدًا سهوًا لا قرارًا.
    """

    operation: str
    constitutional_action: str
    entrypoint: str
    actor: str
    basis: str


MONEY_DELEGATIONS: Final[tuple[MoneyDelegation, ...]] = (
    # ── خزانةُ الدولة · services/state_treasury/service.py ──────────────
    MoneyDelegation(
        operation="treasury.establish",
        constitutional_action="establish_treasury",
        entrypoint="establish_treasury",
        actor=TREASURY_BRANCH,
        basis="إنشاءُ وعاءِ المالِ العامِّ نفسِه — لا فعلَ خزانةٍ أسبقُ منه.",
    ),
    MoneyDelegation(
        operation="treasury.account.open",
        constitutional_action="open_account",
        entrypoint="open_account",
        actor=TREASURY_BRANCH,
        basis="فتحُ حسابٍ داخلَ الخزانةِ توزيعٌ لوعائِها، فهو من اختصاصِها.",
    ),
    MoneyDelegation(
        operation="treasury.budget.create",
        constitutional_action="create_budget",
        entrypoint="create_budget",
        actor=TREASURY_BRANCH,
        basis="الموازنةُ سقفُ الصرفِ المُعلَن، وسنُّها فعلُ خزانةٍ لا فعلُ إدارة.",
    ),
    MoneyDelegation(
        operation="treasury.allocation.create",
        constitutional_action="allocate_funds",
        entrypoint="allocate",
        actor=TREASURY_BRANCH,
        basis="التخصيصُ يقطعُ من سقفِ الموازنةِ نصيبًا مُلزِمًا، فهو تحريكُ مال.",
    ),
    MoneyDelegation(
        operation="treasury.funding.post",
        constitutional_action="post_funding",
        entrypoint="post_funding",
        actor=TREASURY_BRANCH,
        basis="إيرادٌ يزيدُ رصيدَ الخزانةِ — والزيادةُ حركةُ مالٍ كالنقص.",
    ),
    MoneyDelegation(
        operation="treasury.disbursement.post",
        constitutional_action="disburse_funds",
        entrypoint="disburse",
        actor=TREASURY_BRANCH,
        basis="الصرفُ أصلُ فعلِ الخزانةِ، وهو ممنوعٌ على القضاءِ اسمًا في الاختصاص.",
    ),
    MoneyDelegation(
        operation="treasury.disbursement.post",
        constitutional_action="disburse_funds",
        entrypoint="execute_decision_disbursement",
        actor=TREASURY_BRANCH,
        basis=(
            "صرفٌ تنفيذًا لقرارٍ — مدخلٌ ثانٍ للعمليّةِ نفسِها، فيُفوَّضُ على حِدَةٍ "
            "لأنَّ سندَ القرارِ لا يُغني عن تفويضِ الخزانة."
        ),
    ),
    MoneyDelegation(
        operation="treasury.transaction.reverse",
        constitutional_action="reverse_transaction",
        entrypoint="reverse_transaction",
        actor=TREASURY_BRANCH,
        basis="العكسُ حركةُ مالٍ معاكسةٌ لا إلغاءُ سجلّ، فيلزمُه تفويضُ الحركةِ نفسِها.",
    ),
    # ── الاقتصادُ الوطنيّ · services/national_economy/service.py ────────
    MoneyDelegation(
        operation="economy.expenditure.authorize",
        constitutional_action="authorize_expenditure",
        entrypoint="authorize_expenditure",
        actor=TREASURY_BRANCH,
        basis="إذنُ الإنفاقِ يُلزِمُ مالًا عامًّا قبلَ صرفِه، فهو فعلُ خزانةٍ بحكمِ Q-18.",
    ),
    MoneyDelegation(
        operation="economy.transfer.execute",
        constitutional_action="execute_transfer",
        entrypoint="execute_transfer",
        actor=TREASURY_BRANCH,
        basis="التحويلُ نقلُ مالٍ عامٍّ بينَ جهتَين، والنقلُ حركةٌ لا إجراءٌ إداريّ.",
    ),
)

_BY_KEY: Final[dict[tuple[str, str], MoneyDelegation]] = {
    (d.operation, d.entrypoint): d for d in MONEY_DELEGATIONS
}

_LEXICON_AGREED: bool = False


def declared_money_operations() -> frozenset[str]:
    """أسماءُ العمليّاتِ التي لها تفويضٌ مُعلَن — تُقرأُ من الجدولِ لا تُعدَّدُ يدويًّا."""
    return frozenset(d.operation for d in MONEY_DELEGATIONS)


def _ensure_core_importable() -> Path:
    """أضِفْ جذرَ المستودعِ إلى المسارِ بالبحثِ عن النواةِ نفسِها لا بعدِّ المجلّدات.

    عدُّ ``parents[n]`` يكسرُ بأيِّ نقلٍ للمجلَّد. والبحثُ عن ملفٍّ من النواةِ يبقى
    صحيحًا ما بقيت النواةُ، ويسقطُ صريحًا إن غابت.
    """
    here = Path(__file__).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "core" / "constitutional_engine" / "rules.py").is_file():
            if str(candidate) not in sys.path:
                sys.path.insert(0, str(candidate))
            return candidate
    raise UndeclaredMoneyDelegationError(
        "لم يُعثر على معجمِ المالِ الدستوريِّ (core/constitutional_engine/rules.py) "
        f"في أيِّ جدٍّ للمسار: {here} — ولا يُفوَّضُ مالٌ بمعجمٍ غائب."
    )


def assert_lexicon_agreement() -> None:
    """طابِقْ جدولَ التفويضِ بمعجمِ Q-18 — حقيقةٌ واحدةٌ لا حقيقتان.

    يسقطُ إن أعلنَ تفويضٌ فعلًا ليس في ``TREASURY_ACTIONS``، أو أعلنَ لعمليّةٍ
    فعلًا يخالفُ ما يقولُه ``MONEY_OPERATION_LEXICON`` لها. فلا يُصحَّحُ الجدولانِ
    كلٌّ على حِدَةٍ فيفترقا.
    """
    global _LEXICON_AGREED
    if _LEXICON_AGREED:
        return
    _ensure_core_importable()
    from core.constitutional_engine.rules import (  # noqa: PLC0415
        MONEY_OPERATION_LEXICON,
        TREASURY_ACTIONS,
    )

    for delegation in MONEY_DELEGATIONS:
        if delegation.constitutional_action not in TREASURY_ACTIONS:
            raise UndeclaredMoneyDelegationError(
                f"التفويضُ «{delegation.operation}» يُحيلُ إلى فعلٍ ليس في معجمِ "
                f"الخزانة: «{delegation.constitutional_action}»."
            )
        expected = MONEY_OPERATION_LEXICON.get(delegation.operation)
        if expected is None:
            raise UndeclaredMoneyDelegationError(
                f"العمليّةُ «{delegation.operation}» مُفوَّضةٌ ولا يعرفُها جدولُ "
                "ترجمةِ Q-18 — فالتفويضُ يسبقُ المعجمَ وذلك انفصالُ حقيقتَين."
            )
        if expected != delegation.constitutional_action:
            raise UndeclaredMoneyDelegationError(
                f"اختلافُ حقيقتَين للعمليّةِ «{delegation.operation}»: التفويضُ "
                f"يقولُ «{delegation.constitutional_action}» ومعجمُ Q-18 يقولُ "
                f"«{expected}»."
            )
    _LEXICON_AGREED = True


def resolve_money_delegation(operation: str, *, entrypoint: str) -> MoneyDelegation:
    """أحضِرْ تفويضَ هذه العمليّةِ من هذا المدخل — أو ارفضْ.

    هذا هو الشرطُ الذي جعلَه Q-19 سابقًا لكلِّ تحريكِ مال: من أضافَ غدًا عمليّةً
    ماليّةً ونسيَ تفويضَها **لا تمرُّ** — لا لأنَّ اختبارًا يشتكي، بل لأنَّ المسارَ
    نفسَه يُغلَق. والرفضُ يُسمّي العمليّةَ والمدخلَ فلا يُبحَثُ عن موضعِ العلّة.
    """
    assert_lexicon_agreement()
    delegation = _BY_KEY.get((operation, entrypoint))
    if delegation is None:
        raise UndeclaredMoneyDelegationError(
            f"تحريكُ مالٍ بلا تفويضٍ مُعلَن: العمليّةُ «{operation}» من المدخلِ "
            f"«{entrypoint}». وقرارُ Q-19 يُلزِمُ بتفويضٍ مكتوبٍ لكلِّ عمليّةٍ "
            "ماليّةٍ على حِدَة — فأعلِنْه في `MONEY_DELEGATIONS` ولا تُمرِّرْه ضمنًا."
        )
    return delegation


def _assert_delegations_self_consistent() -> None:
    """احرسْ اتّساقَ الجدولِ عندَ الاستيراد — بما لا يحتاجُ النواةَ.

    أربعةُ فحوصٍ، ولكلِّ واحدٍ بابٌ يسدُّه: فاعلٌ غيرُ الخزانةِ (نقلُ اختصاصٍ
    مُقنَّع) · مدخلٌ مُكرَّرٌ لعمليّةٍ (تفويضانِ متناقضانِ لريالٍ واحد) · فعلٌ
    دستوريٌّ باسمٍ نطاقيّ (هروبٌ من `DENY` رُفِضَ نصًّا في Q-18) · سندٌ فارغٌ
    (تفويضٌ لا يُقرأُ سببُه).
    """
    seen: set[tuple[str, str]] = set()
    for delegation in MONEY_DELEGATIONS:
        if delegation.actor != TREASURY_BRANCH:
            raise ValueError(
                f"تفويضُ «{delegation.operation}» بفاعلٍ غيرِ الخزانة: "
                f"«{delegation.actor}» — وأفعالُ المالِ اختصاصُ الخزانةِ وحدَها."
            )
        key = (delegation.operation, delegation.entrypoint)
        if key in seen:
            raise ValueError(
                f"تفويضانِ لمدخلٍ واحد: «{delegation.operation}» من "
                f"«{delegation.entrypoint}» — فأيُّهما يُسأَلُ عن الريال؟"
            )
        seen.add(key)
        if "." in delegation.constitutional_action:
            raise ValueError(
                f"فعلٌ دستوريٌّ باسمٍ نطاقيٍّ في التفويض: "
                f"«{delegation.constitutional_action}» — والتسميةُ النطاقيّةُ "
                "لفعلِ مالٍ مرفوضةٌ نصًّا في Q-18."
            )
        if not delegation.basis.strip():
            raise ValueError(
                f"تفويضٌ بلا سند: «{delegation.operation}» من "
                f"«{delegation.entrypoint}» — والسندُ الفارغُ يُقرأُ سهوًا لا قرارًا."
            )


_assert_delegations_self_consistent()
