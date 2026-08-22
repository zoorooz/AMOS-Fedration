"""الهدف: إثباتُ أنَّ قياسَ الدَّينِ السياديِّ لا يتغيَّرُ بوجودِ بيئةٍ افتراضيّةٍ في الشجرة.

النطاق: `tools/audit/sovereign_write_inventory.py` — دالّةُ المشيِ والترشيحِ وحدَها.
المالك: governance/
تاريخ الإنشاء: 2026-08-22
تاريخ آخر تعديل: 2026-08-22

## ما يحرسُه هذا الملفّ (W-022 · T0)

مسارُ التهيئةِ المُوثَّقُ (`tools/dev/bootstrap.sh`) يُنشئُ البيئةَ في `‎.venv` **داخلَ
جذرِ المستودع**. وكانت أداةُ الجردِ تمشي في كلِّ `*.py` تحتَ الجذر، فتقيسُ كودَ
التبعيّاتِ كأنَّه كودُنا: قِيسَ فعلًا 755 موضعَ دَينٍ بدلَ 168، فتسقطُ بوّابةُ
`decision_gate --gate W1` بدعوى «انحرافٍ صامت» على مَن هيّأَ بيئتَه بالطريقةِ
المُعتمَدة. وهذا خللُ قياسٍ لا خللُ مستودَع، وأخطرُ ما فيه أنَّه **يُضخِّمُ** الرقمَ
فيبدو المشروعُ أسوأَ مما هو، كما قد يُخفي عكسُه ما هو أسوأ.

والحُكمُ الذي يحرسُه هذا الملفُّ ثلاثةُ بنودٍ لا بندٌ واحد:

1. **عدمُ التأثُّر**: إضافةُ بيئةٍ افتراضيّةٍ إلى الشجرةِ لا تُغيِّرُ عددَ المواضعِ
   المقيسةِ ولا مساراتِها.
2. **العلامةُ بنيويّةٌ لا اسميّة**: الاستثناءُ بـ`pyvenv.cfg` (PEP 405) لا باسمِ
   المجلَّد، فمجلَّدٌ اسمُه `‎.venv` بلا علامةٍ يبقى مقيسًا (وإلّا صارَ الاسمُ
   بابًا لإخفاءِ كودٍ إنتاجيٍّ من العدّ)، ومجلَّدُ بيئةٍ باسمٍ آخرَ يُستثنى.
3. **التبعيّاتُ المُورَّدة**: `site-packages` وما شابهَها تُستثنى وإن لم تُصحَبْ بعلامة.

ولا يقيسُ هذا الحارسُ المستودعَ نفسَه ولا يُنشئُ بيئةً فيه: الحارسُ يبني شجرةً
مؤقّتةً كاملةَ الاحتياجِ في `tmp_path` ثمَّ يقيسُها، فلا يعتمدُ على ترتيبِ
الاختباراتِ ولا يُلوِّثُ شجرةَ العمل.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = REPO_ROOT / "tools" / "audit" / "sovereign_write_inventory.py"

#: وحدةٌ إنتاجيّةٌ فيها موضعُ كتابةٍ واحدٌ عامٌّ — أصغرُ ما يُقاس.
PRODUCTION_MODULE = '''"""وحدةُ خدمةٍ للاختبار."""


class Registry:
    def save(self, session, row):
        session.add(row)
        session.commit()
'''

#: كودُ تبعيّةٍ فيه ثلاثةُ مواضعِ كتابةٍ — لو قِيسَ لظهرَ في العدّ.
DEPENDENCY_MODULE = '''"""كودُ حزمةٍ خارجيّةٍ لا يملكُه المستودع."""


class Vendor:
    def flush(self, session, row):
        session.add(row)
        session.merge(row)
        session.commit()
'''


def _load_tool() -> ModuleType:
    """حمِّلِ الأداةَ من مسارِها — بلا اعتمادٍ على `sys.path` ولا على وحدةٍ مُثبَّتة.

    وتُسجَّلُ الوحدةُ في `sys.modules` قبلَ تنفيذِها لأنَّ فيها `dataclass` ووحدةَ
    `dataclasses` تقرأُ فضاءَ أسماءِ الوحدةِ من هناك لحلِّ التعليقاتِ المؤجَّلة.
    """
    name = "amos_sovereign_write_inventory_under_test"
    spec = importlib.util.spec_from_file_location(name, TOOL_PATH)
    assert spec is not None and spec.loader is not None, f"لا يُحمَّلُ: {TOOL_PATH}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _make_environment(root: Path) -> None:
    """أنشئْ بيئةً افتراضيّةً مُصغَّرةً: علامةٌ في الجذرِ وكودُ تبعيّةٍ تحتَها.

    ويُكتبُ ملفٌّ **خارجَ** `site-packages` أيضًا ليكونَ قطعُ البيئةِ من جذرِها
    محمولًا عليه في الحُكم: لو اكتَفى الاستبعادُ باسمِ `site-packages` لمرَّ هذا
    الحارسُ من غيرِ أن يكونَ القطعُ موجودًا — وحارسٌ يمرُّ بلا حراسةٍ خُدعة.
    """
    _write(root / "pyvenv.cfg", "home = /usr/bin\nversion = 3.12.13\n")
    _write(
        root / "lib" / "python3.12" / "site-packages" / "vendor" / "core.py",
        DEPENDENCY_MODULE,
    )
    _write(root / "lib" / "python3.12" / "_vendor_shim.py", DEPENDENCY_MODULE)


def _make_project(root: Path) -> None:
    _write(root / "svc" / "registry.py", PRODUCTION_MODULE)


def test_a_virtual_environment_in_the_tree_does_not_change_the_measurement(
    tmp_path: Path,
) -> None:
    """الرقمُ والمساراتُ سواءٌ قبلَ البيئةِ وبعدَها — وإلّا فالقياسُ يعاقبُ التهيئة."""
    tool = _load_tool()
    project = tmp_path / "repo"
    _make_project(project)

    before = tool.collect(project)
    _make_environment(project / ".venv")
    after = tool.collect(project)

    fingerprint = [(s.path, s.function, s.line) for s in before]
    assert fingerprint == [(s.path, s.function, s.line) for s in after], (
        "تغيَّرَ القياسُ بمجرَّدِ إنشاءِ بيئةٍ افتراضيّةٍ في الشجرة: "
        f"{len(before)} ← {len(after)}"
    )
    assert len(before) == 1, f"شجرةُ الاختبارِ فيها موضعٌ واحدٌ، والمقيسُ {len(before)}"
    assert not [s for s in after if "pyvenv" in s.path or "site-packages" in s.path]


def test_the_environment_is_known_by_its_marker_not_by_its_name(tmp_path: Path) -> None:
    """مجلَّدٌ اسمُه `‎.venv` بلا علامةٍ يُقاس، ومجلَّدُ بيئةٍ باسمٍ آخرَ يُستثنى."""
    tool = _load_tool()

    named_but_not_an_environment = tmp_path / "a"
    _write(named_but_not_an_environment / ".venv" / "module.py", PRODUCTION_MODULE)
    counted = tool.collect(named_but_not_an_environment)
    assert len(counted) == 1, (
        "استُثنيَ كودٌ إنتاجيٌّ لأنَّ اسمَ مجلَّدِه `‎.venv` — والاسمُ لا يُخوِّلُ "
        "إخفاءَ كتابةٍ من العدّ"
    )

    an_environment_by_another_name = tmp_path / "b"
    _make_project(an_environment_by_another_name)
    _make_environment(an_environment_by_another_name / "tooling-env")
    assert (
        len(tool.collect(an_environment_by_another_name)) == 1
    ), "قِيسَت بيئةٌ افتراضيّةٌ لأنَّ اسمَها ليس `‎.venv` — والعلامةُ هي الحُكم"

    assert (
        tool.is_environment_root(an_environment_by_another_name / "tooling-env") is True
    )
    assert tool.is_environment_root(named_but_not_an_environment / ".venv") is False


def test_vendored_dependencies_are_excluded_without_any_marker(tmp_path: Path) -> None:
    """`site-packages` مُورَّدةٌ بلا `pyvenv.cfg` تبقى خارجَ العدِّ، وترشيحُ المسارِ يوافقُ المشي."""
    tool = _load_tool()
    project = tmp_path / "repo"
    _make_project(project)
    _write(project / "vendor" / "site-packages" / "pkg" / "core.py", DEPENDENCY_MODULE)

    assert len(tool.collect(project)) == 1, "قِيسَت تبعيّةٌ مُورَّدةٌ داخلَ `site-packages`"
    assert tool.is_production_file(Path("vendor/site-packages/pkg/core.py")) is False
    assert tool.is_production_file(Path("svc/registry.py")) is True
