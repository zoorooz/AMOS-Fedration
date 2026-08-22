"""
AMOS-Federation Tests — Q-32 Money Enforcement Surface
الهدف: تقييدُ سطحِ فرضِ المالِ كما قِيسَ في موجزِ Q-32 فيسقطُ الحرسُ إن تغيّرَ الواقعُ لا الوثيقة
النطاق: tests — حِرزُ موجزِ Q-32 (قياسٌ لا قرار · W-021)
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-22 (Q-32)
تعتمد على: services/state_treasury/service.py · services/national_economy/service.py · services/governance/treasury.py

## لماذا حِرزٌ لموجزٍ لا لقرار

Q-32 **مسألةٌ سياديّةٌ لم تُحسَمْ بعد**، ولا يجوزُ لمُنفِّذٍ أن يخترعَ حسمَها. لكنَّ
الموجزَ الذي يُعرَضُ على صاحبِ القرارِ **دعوى قابلةٌ للبَلى**: يُقاسُ اليومَ فيُقرأُ
غدًا وقد تغيَّرَ المصدرُ من تحتِه، فيُتَّخَذُ قرارٌ سياديٌّ على رقمٍ ميّت. فهذا
الحرسُ يُقيِّدُ **كلَّ رقمٍ في الموجزِ** إلى موضعِه في الشِّفرة: من غيَّرَ سطحَ الفرضِ
أسقطَ الحرسَ، فيُعادُ قياسُ الموجزِ قبلَ عرضِه لا بعدَه.

## ما يُثبِتُه هذا الحرس

1. **كتابةُ حركةِ المالِ موضعٌ واحدٌ** في خزانةِ الدولةِ (`_post`)، ولا يُنادى إلّا
   من ثلاثةِ مداخلَ، وكلُّها تعبُرُ طبقةَ التخويلِ `_authorize_money`.
2. **الستّةُ غيرُ العابرةِ ما هي حقًّا**: ثلاثةُ إنشاءِ أوعيةٍ · التزامٌ واحدٌ لا
   يُحرِّكُ مالًا · ومُغلِّفانِ يُسنِدانِ الحركةَ نفسَها إلى `disburse` المحروس.
3. **حدُّ Q-17 مقصودٌ لا منسيّ**: خزانةُ الرصيدِ التشغيليِّ (`amos-credit`) خارجَ
   سؤالِ المُحرِّكِ بحكمِ Q-17، فلا تُقرأُ ضمنَ Q-32.
4. **العددانِ 4 و 6 مُقيَّدان**: من زادَ موضعًا ماليًّا نسيَ فرضَه أسقطَ الحرس.

## الحدُّ المُعلَنُ لهذا الحرس

هذا الحرسُ يقيسُ **بنيةَ المصدرِ** (شجرةَ التحليلِ لا نصًّا حرفيًّا)، ولا يُثبتُ
**نفاذَ الحكمِ** في زمنِ التشغيل — ذاكَ حرسُ Q-31 وحدَه
(`test_q31_money_engine_wiring.py`). واجتماعُهما هو الدليل: هذا يُثبِتُ **أينَ**
يُفرَضُ، وذاكَ يُثبِتُ **أنَّه يُفرَضُ فعلًا**.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_MARKER = "core/constitutional_engine/rules.py"

#: المداخلُ الأربعةُ التي قِيسَ أنّها تعبُرُ طبقةَ التخويلِ فيُسألُ المُحرِّكُ عندها.
ENFORCED_ENTRYPOINTS = frozenset({"allocate", "post_funding", "disburse", "reverse_transaction"})

#: الستّةُ التي لا تعبُرُها — مُصنَّفةً بما تفعلُه حقًّا لا بما يُظَنُّ أنّها تفعلُه.
CONTAINER_ENTRYPOINTS = frozenset({"establish_treasury", "open_account", "create_budget"})
OBLIGATION_ENTRYPOINTS = frozenset({"authorize_expenditure"})
WRAPPER_ENTRYPOINTS = frozenset({"execute_decision_disbursement", "execute_transfer"})


def _repo_root() -> Path:
    for parent in [Path(__file__).resolve(), *Path(__file__).resolve().parents]:
        if (parent / REPO_MARKER).exists():
            return parent
    raise AssertionError("لم يُعثَر على جذرِ المستودعِ من موضعِ الاختبار")


def _services_dir() -> Path:
    return _repo_root() / "federal/executive/services/src/amos_federation/services"


def _functions(path: Path) -> dict[str, ast.FunctionDef]:
    """كلُّ دالّةٍ في الملفِّ باسمِها — تُقرأُ من شجرةِ التحليلِ لا بتعبيرٍ نمطيّ.

    القراءةُ من الشجرةِ مقصودةٌ: البحثُ النصّيُّ يُخطئُ حينَ يُقسَّمُ نداءٌ على
    سطرَين أو يُذكَرُ اسمٌ في تعليق، فيصيرُ الحرسُ يقيسُ نصًّا لا بنية.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: dict[str, ast.FunctionDef] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            found[node.name] = node  # type: ignore[assignment]
    return found


def _calls_in(node: ast.AST) -> set[str]:
    """أسماءُ النداءاتِ داخلَ الدالّةِ — `self.x` و`obj.x` و`x` سواءً في الاسمِ الأخير."""
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Attribute):
                names.add(func.attr)
            elif isinstance(func, ast.Name):
                names.add(func.id)
    return names


def _qualified_calls_in(node: ast.AST) -> set[str]:
    """النداءاتُ بصاحبِها حينَ يكونُ اسمًا بسيطًا: `self.disburse` · `treasury.disburse`."""
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
            owner = child.func.value
            if isinstance(owner, ast.Name):
                names.add(f"{owner.id}.{child.func.attr}")
    return names


@pytest.fixture(scope="module")
def treasury_functions() -> dict[str, ast.FunctionDef]:
    return _functions(_services_dir() / "state_treasury/service.py")


@pytest.fixture(scope="module")
def economy_functions() -> dict[str, ast.FunctionDef]:
    return _functions(_services_dir() / "national_economy/service.py")


class TestA1MovementWriteIsOnePlaceAndItIsGuarded:
    """الدعوى الأولى: كلُّ حركةِ مالٍ تُكتَبُ من موضعٍ واحدٍ، وكلُّ منادِيه محروس."""

    def test_the_movement_writer_is_called_from_exactly_three_entrypoints(
        self, treasury_functions: dict[str, ast.FunctionDef]
    ) -> None:
        callers = {
            name
            for name, node in treasury_functions.items()
            if not name.startswith("_") and "self._post" in _qualified_calls_in(node)
        }
        assert callers == {"post_funding", "disburse", "reverse_transaction"}, (
            "تغيَّرَ مَن يكتبُ حركةَ مالٍ في خزانةِ الدولةِ — "
            f"المقيسُ اليومَ: {sorted(callers)}. ويُعادُ قياسُ موجزِ Q-32 قبلَ عرضِه."
        )

    def test_every_movement_writer_passes_the_authorization_layer(
        self, treasury_functions: dict[str, ast.FunctionDef]
    ) -> None:
        for name in ("post_funding", "disburse", "reverse_transaction"):
            assert "_authorize_money" in _calls_in(treasury_functions[name]), (
                f"المدخلُ «{name}» يكتبُ حركةَ مالٍ ولا يعبُرُ طبقةَ التخويلِ — " "فالمُحرِّكُ لا يُسألُ عنه."
            )

    def test_the_allocation_that_cuts_the_ceiling_is_guarded_too(
        self, treasury_functions: dict[str, ast.FunctionDef]
    ) -> None:
        """التخصيصُ لا يكتبُ حركةً ولكنّه يقطعُ من السقفِ نصيبًا مُلزِمًا، فهو الرابع."""
        assert "_authorize_money" in _calls_in(treasury_functions["allocate"])

    def test_the_authorization_layer_asks_the_engine_before_touching_the_database(
        self, treasury_functions: dict[str, ast.FunctionDef]
    ) -> None:
        calls = _calls_in(treasury_functions["_authorize_money"])
        assert (
            "require_constitutional_money_authority" in calls
        ), "طبقةُ التخويلِ لا تسألُ المُحرِّكَ — وهذا نقضُ Q-31 لا حدُّ Q-32."

    def test_the_enforced_entrypoints_are_exactly_four(
        self, treasury_functions: dict[str, ast.FunctionDef]
    ) -> None:
        enforced = {
            name
            for name, node in treasury_functions.items()
            if not name.startswith("_") and "_authorize_money" in _calls_in(node)
        }
        assert enforced == set(ENFORCED_ENTRYPOINTS), (
            f"عددُ المواضعِ المفروضةِ تغيَّرَ: {sorted(enforced)} — "
            "والرقمُ «أربعةٌ من عشرة» مكتوبٌ في وثائقَ سياديّةٍ فيُصحَّحُ معه."
        )


class TestA2WhatTheSixReallyAre:
    """الدعوى الثانية: الستّةُ غيرُ العابرةِ ليست ستَّ ثقوبٍ في الحدِّ — تُقاسُ لا تُعَدّ."""

    def test_none_of_the_six_passes_the_authorization_layer(
        self,
        treasury_functions: dict[str, ast.FunctionDef],
        economy_functions: dict[str, ast.FunctionDef],
    ) -> None:
        for name in ("establish_treasury", "open_account", "create_budget"):
            assert "_authorize_money" not in _calls_in(treasury_functions[name])
        assert "_authorize_money" not in _calls_in(
            treasury_functions["execute_decision_disbursement"]
        )
        for name in ("authorize_expenditure", "execute_transfer"):
            assert "_authorize_money" not in _calls_in(economy_functions[name])

    def test_the_three_container_operations_write_no_movement(
        self, treasury_functions: dict[str, ast.FunctionDef]
    ) -> None:
        """إنشاءُ خزانةٍ أو حسابٍ أو موازنةٍ يُنشئُ وعاءً ولا ينقلُ مبلغًا."""
        for name in sorted(CONTAINER_ENTRYPOINTS):
            calls = _qualified_calls_in(treasury_functions[name])
            assert "self._post" not in calls, f"«{name}» يكتبُ حركةَ مالٍ — فالتصنيفُ خاطئ."
            assert "self.disburse" not in calls

    def test_the_obligation_moves_no_money_and_declares_it(
        self, economy_functions: dict[str, ast.FunctionDef]
    ) -> None:
        """إجازةُ الإنفاقِ التزامٌ لا حركة: حالتُها `authorized` ولا تُنادي صرفًا."""
        node = economy_functions["authorize_expenditure"]
        calls = _qualified_calls_in(node)
        assert not {
            c for c in calls if c.endswith(".disburse")
        }, "إجازةُ الإنفاقِ صارت تصرفُ مالًا — فهي حركةٌ لا التزامٌ، ويتغيّرُ حكمُ Q-32."
        statuses = {
            kw.value.value
            for child in ast.walk(node)
            if isinstance(child, ast.Call)
            for kw in child.keywords
            if kw.arg == "status" and isinstance(kw.value, ast.Constant)
        }
        assert "authorized" in statuses, "حالةُ الإجازةِ لم تبقَ `authorized` — يُعادُ القياس."

    def test_the_obligation_is_later_executed_through_the_guarded_treasury(
        self, economy_functions: dict[str, ast.FunctionDef]
    ) -> None:
        """تنفيذُ الإجازةِ — لا الإجازةُ — هو الحركة، وهو يمرُّ بخزانةِ الدولةِ المحروسة.

        فالثقبُ في Q-32 زمنُ **الالتزام** لا زمنُ الحركة: يُلتزَمُ بلا سؤالٍ ثمّ
        يُنفَّذُ الالتزامُ بسؤال. ومَن أرادَ سدَّه فليَسأَلْ عندَ الالتزام.
        """
        assert "treasury.disburse" in _qualified_calls_in(
            economy_functions["execute_expenditure"]
        ), "تنفيذُ الإجازةِ لم يبقَ ماضيًا بخزانةِ الدولةِ — فصارَ الالتزامُ والحركةُ بلا حرس."

    def test_the_two_wrappers_hand_the_movement_to_the_guarded_disbursement(
        self,
        treasury_functions: dict[str, ast.FunctionDef],
        economy_functions: dict[str, ast.FunctionDef],
    ) -> None:
        """المُغلِّفانِ لا يملكانِ دفترًا ثانيًا: حركتُهما تمرُّ من `disburse` المحروس.

        وهذا هو تصحيحُ الدعوى التي كُتِبَت في W-015: «ثلاثةٌ تُحرِّكُ مالًا ولا
        يُسألُ المُحرِّكُ عنها» — والمقيسُ أنَّ الحركةَ نفسَها **مسؤولٌ عنها**،
        وأنَّ غيرَ المفروضِ هو **سندُ المُغلِّفِ** لا الحركة.
        """
        assert "self.disburse" in _qualified_calls_in(
            treasury_functions["execute_decision_disbursement"]
        ), "صرفُ القرارِ صارَ يكتبُ حركةً بنفسِه — فقد صارَ ثقبًا حقيقيًّا في الحدّ."
        assert "treasury.disburse" in _qualified_calls_in(
            economy_functions["execute_transfer"]
        ), "صرفُ التحويلِ صارَ لا يمرُّ بخزانةِ الدولةِ — فقد صارَ دفترًا ثانيًا للمال."

    def test_the_six_are_six_no_more_no_less(self) -> None:
        assert (
            len(CONTAINER_ENTRYPOINTS | OBLIGATION_ENTRYPOINTS | WRAPPER_ENTRYPOINTS) == 6
        ), "تصنيفُ الستّةِ في هذا الحرسِ لم يبقَ ستّةً — فالموجزُ والحرسُ افترقا."

    def test_the_ten_declared_delegations_split_four_and_six(self) -> None:
        """الجدولُ المُعلَنُ في Q-19 هو مصدرُ العددِ العشرةِ — لا عدٌّ يدويّ."""
        from amos_federation.common.money_delegation import MONEY_DELEGATIONS

        entrypoints = {d.entrypoint for d in MONEY_DELEGATIONS}
        assert len(MONEY_DELEGATIONS) == 10
        assert entrypoints & set(ENFORCED_ENTRYPOINTS) == set(ENFORCED_ENTRYPOINTS)
        unenforced = entrypoints - set(ENFORCED_ENTRYPOINTS)
        assert unenforced == (
            CONTAINER_ENTRYPOINTS | OBLIGATION_ENTRYPOINTS | WRAPPER_ENTRYPOINTS
        ), f"الستّةُ غيرُ المفروضةِ تغيَّرَت: {sorted(unenforced)}"


class TestA3TheOperationalCreditTreasuryIsOutOfScopeByDecision:
    """الدعوى الثالثة: خزانةُ `amos-credit` خارجَ Q-32 بحكمِ Q-17 لا بسهوٍ."""

    def test_the_credit_treasury_has_no_constitutional_wiring_and_that_is_the_ruling(
        self,
    ) -> None:
        source = (_services_dir() / "governance/treasury.py").read_text(encoding="utf-8")
        for token in (
            "ConstitutionalAuthorizer",
            "money_authority",
            "resolve_money_delegation",
        ):
            assert token not in source, (
                f"وُصِلَ «{token}» بخزانةِ الرصيدِ التشغيليِّ — وذاكَ يخالفُ Q-17 "
                "الذي قضى أنَّ `amos-credit` ليس مالًا دستوريًّا، ويُقرَّرُ سياديًّا لا اجتهادًا."
            )

    def test_the_credit_treasury_writes_through_one_recorder(self) -> None:
        functions = _functions(_services_dir() / "governance/treasury.py")
        recorders = {
            name for name, node in functions.items() if "_record_transaction" in _calls_in(node)
        }
        recorders.discard("_record_transaction")
        assert len(recorders) >= 6, (
            "قلَّ عددُ مواضعِ الكتابةِ في خزانةِ الرصيدِ التشغيليِّ — "
            f"المقيسُ: {sorted(recorders)}. ورقمُ الموجزِ يُعادُ قياسُه."
        )


class TestA4DeclaredLimitOfThisGuard:
    """الحدُّ المُعلَن: هذا الحرسُ يقيسُ البنيةَ ولا يُثبِتُ نفاذَ الحكم."""

    def test_this_guard_does_not_prove_runtime_enforcement(self) -> None:
        """يُثبَّتُ الحدُّ بوجودِ حرسِ Q-31 مسؤولًا عن الدعوى الأخرى لا بنصٍّ في وثيقة."""
        assert (
            Path(__file__).parent / "test_q31_money_engine_wiring.py"
        ).is_file(), "غابَ حرسُ Q-31 — فصارَ هذا الحرسُ وحدَه، وقياسُ البنيةِ لا يُغني عن قياسِ النفاذ."
