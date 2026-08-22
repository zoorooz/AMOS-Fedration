"""الهدف: تقييدُ حالةِ أسطحِ الكتابةِ في `governance/factories.py` إلى المصدرِ — لئلّا تُعادَ هجرةٌ وقعت.

النطاق: `federal/executive/services/src/amos_federation/services/governance/factories.py`
وحدَه: الكتاباتُ العامّةُ الثلاثُ · المساراتُ القديمةُ الثلاثةُ · المُهيِّئُ الخاصُّ
`_init_factory` وسبيلُ الوصولِ إليه · ونصيبُ الملفِّ من دَينِ الهجرة.
المالك: governance/
تاريخ الإنشاء: 2026-08-22
تاريخ آخر تعديل: 2026-08-22

## لماذا هذا الحرسُ موجود (W-024 · T1 · الخطوة 7)

كانت خارطةُ الطريقِ تقولُ لمن يأتي: «ابدأْ بالأسطحِ الثلاثةِ غيرِ المحجوبةِ في
`governance/factories.py`». وقد **قِيسَ اليومَ من المصدرِ** أنَّ تلك الثلاثةَ
هُوجِرَت فعلًا في P13 (`start_production` · `complete_step` · `assign_manager`
كلُّها تعبرُ الحدَّ)، فنصيبُ الملفِّ من الدَّينِ **صِفرٌ**. فخطوةٌ في خارطةٍ تُرسِلُ
عاملًا إلى عملٍ مُنجَزٍ **خطأٌ في الخارطةِ لا عملٌ باقٍ**، وتصحيحُها بلا حرسٍ
يُعيدُها أوَّلَ ما يُعادُ ترتيبُ الوثائق. فهذه الفحوصُ تُقيِّدُ التصحيحَ إلى
الشِّفرةِ: إن رجعَ سطحٌ من الثلاثةِ إلى ما قبلَ الحدِّ سقطَ الفحصُ، وإن بَقيَ
الوصفُ صحيحًا بَقيَت الخارطةُ صادقة.

## القيدُ الباقي يُقاسُ ولا يُخفى

في الملفِّ كتابةٌ رابعةٌ **لم تُهاجَرْ ولا تُحصى في الدَّين**: `_init_factory`
يكتبُ صفَّ مصنعٍ داخلَ `Factory.__init__`، و`get_factory` — وهو المدخلُ العامُّ —
يبني الكائنَ. فالكتابةُ **يُبلَغُ إليها من سطحٍ عامٍّ** ولا تُحصى لأنَّ معيارَ
العدِّ `public == true` على اسمِ الدالّةِ. وهذا الفحصُ يُثبِّتُ الأمرَين معًا:
الكتابةَ وسبيلَها. وهو دليلٌ مقيسٌ في بابِ **Q-25** (جودةُ رقمِ الدَّينِ نفسِه)،
ولا يُغيِّرُ معيارَ العدِّ: تغييرُ المعيارِ قرارٌ ليس لمُنفِّذ.

## حدُّ صدقِ هذا الحرس

بنيويٌّ: شجرةُ تحليلِ المصدرِ وأداةُ الجردِ نفسُها — لا قراءةَ وثائقَ ولا نقلَ
رقمٍ من تحليلٍ سابق. ولا يُثبِتُ أنَّ الحدَّ يمنعُ كتابةً عندَ الرَّدِّ؛ ذاك
قياسٌ حُكميٌّ في حزمةِ الخدماتِ
(`federal/executive/services/tests/test_step7_gate_denial.py`).
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
FACTORIES_PATH = (
    REPO_ROOT
    / "federal"
    / "executive"
    / "services"
    / "src"
    / "amos_federation"
    / "services"
    / "governance"
    / "factories.py"
)
INVENTORY_TOOL = REPO_ROOT / "tools" / "audit" / "sovereign_write_inventory.py"

#: الكتاباتُ العامّةُ الثلاثُ التي هُوجِرَت في P13 — بأسمائِها كما تُنادى.
MIGRATED_PUBLIC_WRITES = ("start_production", "complete_step", "assign_manager")

#: المساراتُ القديمةُ المُقفَلةُ في P13 — تُرفَعُ ولا تُنتِجُ أثرًا.
CLOSED_LEGACY_PATHS = (
    "_start_production_unguarded",
    "_complete_step_unguarded",
    "_assign_manager_unguarded",
)

#: دفترُ لقطاتِ القياسِ المُعلَنِ — مصدرُ خطِّ الأساسِ. لا يُكتَبُ رقمُ الدَّينِ هنا:
#: نسخُه إلى حرسٍ يجعلُه «حقيقةً مثبَّتةً في الشِّفرة»، وهي عينُ المخالفةِ التي
#: يُحصيها `truth_audit`. فيُقرَأُ من مالكِه ويُقارَنُ به.
DEBT_SNAPSHOT_LEDGER = (
    REPO_ROOT / "docs" / "audit" / "measurements" / "decision_gate_ledger.json"
)


def _declared_debt_baseline() -> int:
    """خطُّ الأساسِ المُعلَنُ من آخرِ لقطةٍ مسجَّلةٍ — لا رقمٌ منسوخٌ في هذا الملفّ."""
    snapshots = json.loads(DEBT_SNAPSHOT_LEDGER.read_text(encoding="utf-8"))[
        "snapshots"
    ]
    assert snapshots, "لا لقطةَ قياسٍ مسجَّلةٌ — لا خطَّ أساسٍ يُقارَنُ به"
    return int(snapshots[-1]["debt"])


def _load_inventory_tool() -> ModuleType:
    """تحميلُ أداةِ الجردِ بمسارِها مع تسجيلِها في `sys.modules`.

    التسجيلُ ضروريٌّ لا تجميليّ: الأداةُ تُعرِّفُ `dataclass` بتعليقاتٍ مؤجَّلة،
    وبناؤها يبحثُ عن وحدتِها بالاسم.
    """
    spec = importlib.util.spec_from_file_location(
        "sovereign_write_inventory", INVENTORY_TOOL
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["sovereign_write_inventory"] = module
    spec.loader.exec_module(module)
    return module


def _factories_sites() -> list[Any]:
    tool = _load_inventory_tool()
    sites = tool.collect(REPO_ROOT)
    return [site for site in sites if "governance/factories.py" in site.path]


def _all_debt() -> list[Any]:
    tool = _load_inventory_tool()
    return [
        site
        for site in tool.collect(REPO_ROOT)
        if site.public and not site.guarded and not site.closed_legacy
    ]


def _tree() -> ast.Module:
    return ast.parse(FACTORIES_PATH.read_text(encoding="utf-8"))


def _function(
    tree: ast.Module, class_name: str | None, func_name: str
) -> ast.FunctionDef:
    if class_name is None:
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == func_name:
                return node
        raise AssertionError(f"لا دالّةَ وحدةٍ باسم {func_name}")
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == func_name:
                    return item
    raise AssertionError(f"لا دالّةَ {class_name}.{func_name}")


def _called_methods(func: ast.FunctionDef) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            names.add(node.func.attr)
    return names


# ═══════════════════════════════════════════════════════════════════════════
# S-1 · الخطوةُ 7 لا عملَ باقيًا فيها: نصيبُ الملفِّ من الدَّينِ صِفر
# ═══════════════════════════════════════════════════════════════════════════


def test_factories_file_carries_no_migration_debt() -> None:
    """لا سطحَ كتابةٍ عامًّا غيرَ مَحروسٍ في الملفِّ — فالخطوةُ 7 مُنجَزةٌ لا مُتاحة."""
    debt = [
        s
        for s in _factories_sites()
        if s.public and not s.guarded and not s.closed_legacy
    ]
    assert (
        debt == []
    ), f"ظهرَ دَينٌ في factories.py: {[(s.function, s.line) for s in debt]}"


def test_the_three_public_writes_are_guarded() -> None:
    """الكتاباتُ الثلاثُ عامّةٌ ومَحروسةٌ — هذا ما فعلَه P13 ولا يُعادُ فعلُه."""
    by_name = {s.function: s for s in _factories_sites()}
    for name in MIGRATED_PUBLIC_WRITES:
        assert name in by_name, f"غابَ السطحُ العامُّ {name}"
        assert by_name[name].public is True, f"{name} لم يبقَ عامًّا"
        assert by_name[name].guarded is True, f"{name} لم يبقَ عابرًا للحدّ"


def test_the_three_legacy_paths_stay_closed() -> None:
    """المساراتُ القديمةُ الثلاثةُ مُقفَلةٌ وخاصّةٌ — لا بابَ ثانيًا للكتابة."""
    by_name = {s.function: s for s in _factories_sites()}
    for name in CLOSED_LEGACY_PATHS:
        assert name in by_name, f"غابَ المسارُ المُقفَلُ {name}"
        assert by_name[name].closed_legacy is True, f"{name} لم يبقَ مُقفَلًا"
        assert by_name[name].public is False, f"{name} صارَ عامًّا"


def test_file_write_surfaces_are_exactly_seven() -> None:
    """سبعةُ مواضعِ كتابةٍ في الملفِّ: 3 مَحروسةٌ · 3 مُقفَلةٌ · 1 مُهيِّئٌ خاصّ."""
    sites = _factories_sites()
    assert len(sites) == 7, [(s.function, s.line) for s in sites]
    assert len([s for s in sites if s.guarded]) == 3
    assert len([s for s in sites if s.closed_legacy]) == 3
    assert [s.function for s in sites if not s.guarded and not s.closed_legacy] == [
        "_init_factory"
    ]


def test_total_debt_matches_the_declared_snapshot() -> None:
    """الدَّينُ المقيسُ الآنَ = خطُّ الأساسِ المُعلَنِ في آخرِ لقطةٍ — لا انحرافَ صامتًا.

    وهذا هو الفحصُ الذي يجعلُ رقمَ **168** في قيدِ W-024 حيًّا: إن نقصَ الدَّينُ
    بهجرةٍ أو زادَ بكتابةٍ جديدةٍ سقطَ هذا الفحصُ، فيُعادُ القياسُ وتُسجَّلُ لقطةٌ
    ويُقيَّدُ الفرقُ — لا يُصحَّحُ رقمٌ في وثيقةٍ صامتًا.
    """
    assert len(_all_debt()) == _declared_debt_baseline()


# ═══════════════════════════════════════════════════════════════════════════
# S-2 · القيدُ الباقي: كتابةٌ خاصّةٌ يُبلَغُ إليها من مدخلٍ عامّ (دليلُ Q-25)
# ═══════════════════════════════════════════════════════════════════════════


def test_init_factory_writes_and_is_private() -> None:
    """`_init_factory` يُضيفُ صفًّا ويُثبِتُه، واسمُه خاصٌّ فلا يُحصى في الدَّين."""
    site = {s.function: s for s in _factories_sites()}["_init_factory"]
    assert site.public is False
    assert set(site.writes) >= {"add()", "commit()"}
    assert site.guarded is False and site.closed_legacy is False


def test_constructor_invokes_the_unguarded_initializer() -> None:
    """بناءُ `Factory` نفسُه ينادي المُهيِّئَ — فالكتابةُ في البناءِ لا في فعلٍ مُعلَن."""
    init = _function(_tree(), "Factory", "__init__")
    assert "_init_factory" in _called_methods(init)


def test_public_entry_point_constructs_the_factory() -> None:
    """`get_factory` مدخلٌ عامٌّ يبني الكائنَ — فسبيلُ الكتابةِ عامٌّ ولو كانَ اسمُها خاصًّا."""
    getter = _function(_tree(), None, "get_factory")
    constructed = {
        node.func.id
        for node in ast.walk(getter)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "Factory" in constructed
    assert not getter.name.startswith("_")


def test_initializer_does_not_cross_the_boundary() -> None:
    """المُهيِّئُ لا ينادي المُصرِّحَ ولا الحدَّ — القيدُ يُقاسُ لا يُدَّعى انعدامُه."""
    init_factory = _function(_tree(), "Factory", "_init_factory")
    called = _called_methods(init_factory)
    assert "guard_declared" not in called
    assert "guard" not in called
    source = (
        ast.get_source_segment(FACTORIES_PATH.read_text(encoding="utf-8"), init_factory)
        or ""
    )
    assert "authorizer" not in source


# ═══════════════════════════════════════════════════════════════════════════
# S-3 · الفاعلُ وأسماءُ الأفعالِ مُعلَنةٌ في المصدرِ لا مُستنتَجة
# ═══════════════════════════════════════════════════════════════════════════


def test_factory_actor_and_action_names_are_declared() -> None:
    """`FACTORY_ACTOR` تنفيذيٌّ مُعلَنٌ، وأسماءُ الأفعالِ هي أسماؤها كما تُنادى."""
    tree = _tree()
    constants: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for target in node.targets:
                if isinstance(target, ast.Name) and isinstance(node.value.value, str):
                    constants[target.id] = node.value.value
    assert constants.get("FACTORY_ACTOR") == "EXECUTIVE"
    assert constants.get("ACTION_START_PRODUCTION") == "start_production"
    assert constants.get("ACTION_COMPLETE_STEP") == "complete_step"
    assert constants.get("ACTION_ASSIGN_MANAGER") == "assign_manager"
