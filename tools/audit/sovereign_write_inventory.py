#!/usr/bin/env python3
"""جردُ الكتاباتِ الإنتاجيّةِ وحالتُها من الحدِّ السياديّ — قياسٌ لا تقدير.

الهدف: أداةُ قياسٍ **قابلةٌ للإعادة** يُبنى عليها عددُ دَينِ الهجرةِ في كلِّ مرحلةٍ
من برنامجِ الهجرةِ السياديّة، فلا يُقال «بقيَ كذا» بلا دليلٍ يُعاد توليدُه.
النطاق: تحليلٌ ساكنٌ (AST) لملفّاتِ الإنتاجِ وحدَها — لا يشغّلُ شيئًا ولا يكتبُ في
قاعدةِ بيانات، ولا يُصدِرُ حكمًا دستوريًّا (ذاك عملُ البوّابةِ لا عملُ أداةِ جرد).

الاستعمال:
    python tools/audit/sovereign_write_inventory.py            # ملخّصٌ نصّيّ
    python tools/audit/sovereign_write_inventory.py --json OUT # ملخّصٌ + تفصيلٌ JSON
    python tools/audit/sovereign_write_inventory.py --service \
        federal/executive/services/src/amos_federation/services/state_registry

الحدود المُعلَنة:
- يقيسُ **مواضعَ** الكتابةِ في المصدر، لا عددَ الكتاباتِ في التشغيل.
- «عمليّةٌ عامّةٌ مُغيِّرة» = دالّةٌ عامّةٌ في صنفٍ أو وحدةٍ إنتاجيّةٍ يقعُ في جسمِها
  `add/add_all/commit/delete/merge` **على مُستقبِلِ تخزينٍ** (جلسة · اتّصال · مستودع)
  أو SQL خامٌّ تغييريّ. ونداءُ `set.add` أو `@router.delete` ليس كتابةً في قاعدةٍ،
  وعدُّه كتابةً تضخيمٌ يُفسِدُ الحكمَ كما يُفسِدُه النقص.
- المعاوناتُ الخاصّة (`_name`) لا تُعدُّ عمليّاتٍ مستقلّة. وكتابتُها **تُنسَبُ**
  إلى العمليّةِ العامّةِ التي تُناديها في الوحدةِ نفسِها (تتبُّعٌ ساكنٌ للاستدعاء،
  عمقٌ غيرُ محدود، دورانٌ محميّ). وبلا هذا النسبِ يكونُ المقياسُ مضلِّلًا: عمليّةٌ
  هُوجِرت هجرةً صحيحةً — فصارت كتابتُها في معاونٍ يُنادى من داخلِ الحدِّ — تسقطُ من
  العدِّ كأنّها لم تكنْ، فلا تُرى سياديّةً ولا مُتجاوِزة (قِيسَ هذا فعلًا في P1أ).
- «تعبرُ الحدَّ» = يقعُ `guard_declared(` في جسدِ العمليّةِ العامّةِ نفسِها. ولا
  يكفي أن يعبرَ معاونُها: الإعلانُ مسؤوليّةُ العمليّةِ لا مسؤوليّةُ أداةِ قياس.
- معاونٌ خاصٌّ يكتبُ ولا تصلُ إليه عمليّةٌ عامّةٌ في وحدتِه يُحصى موضعًا مستقلًّا
  ولا يُسقَط، لأنّ الكتابةَ التي لا يُعرَفُ مدخلُها أخطرُ لا أهون.
- كونُ الدالّةِ «مُغيِّرةً» لا يعني وجوبَ هجرتِها: الوجوبُ حكمٌ دستوريٌّ يُقرَّر في
  سجلِّ القرارات، وهذه الأداةُ تعدُّ فقط.
- **المقيسُ كودُ المستودعِ وحدَه**: البيئاتُ الافتراضيّةُ (بعلامةِ `pyvenv.cfg`) وشجرُ
  التبعيّاتِ المُورَّدةِ (`site-packages` وأمثالُها) تُقطَعُ من المشيِ لا تُرشَّحُ ملفًّا
  ملفًّا. وهذا شرطُ صحّةٍ لا تحسينُ سرعةٍ: مسارُ التهيئةِ المُوثَّقُ ينشئُ `.venv` في
  جذرِ المستودع، فكانَ الجردُ قبلَ W-022 يقيسُ **755** موضعًا بدلَ **168** لمن تبِعَ
  الوثيقةَ، فتسقطُ عليه بوّابةُ `decision_gate` بدعوى «انحرافٍ صامت». والحرسُ:
  `tests/governance/test_measurement_ignores_environments.py`.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
from collections.abc import Iterator
from dataclasses import asdict, dataclass, replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

#: ما يُستثنى من عدِّ الإنتاج — الاختباراتُ ليست إنتاجًا، والذاكرةُ المؤقّتةُ ليست مصدرًا.
SKIP_DIR_NAMES = frozenset(
    {"__pycache__", ".git", "tests", "test", "node_modules", "backups"}
)

#: مجلَّداتُ تبعيّاتٍ مُورَّدةٍ — كودُ غيرِنا ليس دَينَنا السياديّ.
#:
#: تُستثنى بأسمائِها لأنّ هذه الأسماءُ **اصطلاحُ أدواتِ الحزمِ نفسِها** لا اسمًا
#: قد يختارُه مشروعٌ لوحدةٍ من وحداتِه.
VENDOR_DIR_NAMES = frozenset(
    {"site-packages", "dist-packages", ".tox", ".nox", ".eggs"}
)

#: علامةُ البيئةِ الافتراضيّةِ — بنيويّةٌ لا اسميّة (PEP 405).
#:
#: لا تُستثنى البيئةُ باسمِ مجلَّدِها (`.venv` · `venv` · `env` …) لأنّ الاسمَ
#: اختيارُ مَن أنشأَها، ومنعُ الاسمِ يُسقِطُ وحدةَ مشروعٍ سُمِّيَت به. والعلامةُ
#: الحاسمةُ ملفُّ `pyvenv.cfg` الذي يكتبُه `venv` في جذرِ البيئةِ وحدَها.
VENV_MARKER = "pyvenv.cfg"

#: نداءاتُ جلسةِ SQLAlchemy التي تُنتِجُ أثرًا كتابيًّا.
WRITE_CALLS = frozenset({"add", "add_all", "commit", "delete", "merge"})

#: أسماءُ المُستقبِلاتِ التي يُعتَدُّ بكتابتِها — قياسٌ v3.
#:
#: بلا هذا القيدِ يُحسَبُ `seen.add(...)` و`report.add(...)` و`router.delete(...)`
#: كتاباتٍ في قاعدةِ البيانات، وهي ليست كذلك. وقد قيسَ أثرُ الخللِ فعلًا: عمليّةٌ
#: في `state_registry/main.py` كانت تُعَدُّ «متجاوزةً» وسببُها الوحيدُ مُزخرِفُ
#: مسارٍ اسمُه `@router.delete(...)` — لا كتابةَ فيه أصلًا. والرقمُ المتضخِّمُ
#: يُفسِدُ الحكمَ كما يُفسِدُه الرقمُ المنقوص.
WRITE_RECEIVER_TOKENS = frozenset(
    {
        "session",
        "sessions",
        "conn",
        "connection",
        "cursor",
        "engine",
        "db",
        "database",
        "repo",
        "repository",
    }
)


def _is_persistence_receiver(receiver: ast.expr) -> bool:
    """هل المُستقبِلُ جلسةَ تخزينٍ لا مجموعةً في الذاكرةِ ولا مُزخرِفَ مسار؟

    القياسُ على أسماءِ التعبيرِ لا على أنواعِه: أداةُ جردٍ ساكنةٌ لا مُحلِّلُ أنواع،
    وهذا حدٌّ مُعلَنٌ لا نقصٌ مسكوتٌ عنه.
    """
    tokens: set[str] = set()
    for node in ast.walk(receiver):
        if isinstance(node, ast.Name):
            tokens.add(node.id.lower().lstrip("_"))
        elif isinstance(node, ast.Attribute):
            tokens.add(node.attr.lower().lstrip("_"))
    return any(
        token in WRITE_RECEIVER_TOKENS or token.endswith("_session") for token in tokens
    )


#: كلماتُ SQL الخامِّ التغييريّة.
SQL_WRITE_KEYWORDS = (
    "INSERT ",
    "UPDATE ",
    "DELETE FROM",
    "CREATE TABLE",
    "ALTER TABLE",
)

#: علامةُ عبورِ الحدِّ السياديّ.
GUARD_MARKER = "guard_declared("

#: علامةُ إغلاقِ مسارٍ قديم (1N/2A): يُرفَعُ ولا يكتب.
CLOSED_MARKER = "UndeclaredExecutionError"


@dataclass(frozen=True)
class WriteSite:
    """موضعُ كتابةٍ واحدٌ في المصدر."""

    path: str
    owner: str
    function: str
    line: int
    public: bool
    writes: tuple[str, ...]
    guarded: bool
    closed_legacy: bool
    #: كتابةٌ وصلت من معاونٍ خاصٍّ لا من جسدِ العمليّةِ نفسِها — يُصرَّحُ بها ولا تُخفى.
    writes_via: tuple[str, ...] = ()


class _WriteVisitor(ast.NodeVisitor):
    def __init__(self, path: str, source: str) -> None:
        self._path = path
        self._source = source
        self._classes: list[str] = []
        self.sites: list[WriteSite] = []
        #: خريطةُ الاستدعاءِ داخلَ الوحدة: دالّةٌ ← أسماءُ ما تُناديه.
        self.calls: dict[str, set[str]] = {}

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        self._classes.append(node.name)
        self.generic_visit(node)
        self._classes.pop()

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        segment = ast.get_source_segment(self._source, node) or ""
        writes: set[str] = set()
        called: set[str] = self.calls.setdefault(node.name, set())
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                target = sub.func
                if isinstance(target, ast.Name):
                    called.add(target.id)
                elif isinstance(target, ast.Attribute):
                    called.add(target.attr)
            if (
                isinstance(sub, ast.Call)
                and isinstance(sub.func, ast.Attribute)
                and sub.func.attr in WRITE_CALLS
                and _is_persistence_receiver(sub.func.value)
            ):
                writes.add(f"{sub.func.attr}()")
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                upper = sub.value.upper()
                if any(keyword in upper for keyword in SQL_WRITE_KEYWORDS):
                    writes.add("raw-sql-write")
        closed = CLOSED_MARKER in segment
        if closed and not writes:
            # مسارٌ قديمٌ **مُغلَق**: يُرفَعُ ولا يكتب. عدُّه واجبٌ لأنّه دليلُ إغلاقٍ،
            # وإسقاطُه بحجّةِ «لا كتابةَ فيه» يُخفي أهمَّ ما أُنجِز.
            self.sites.append(
                WriteSite(
                    path=self._path,
                    owner=self._classes[-1] if self._classes else "-",
                    function=node.name,
                    line=node.lineno,
                    public=not node.name.startswith("_"),
                    writes=(),
                    guarded=False,
                    closed_legacy=True,
                )
            )
        if writes:
            self.sites.append(
                WriteSite(
                    path=self._path,
                    owner=self._classes[-1] if self._classes else "-",
                    function=node.name,
                    line=node.lineno,
                    public=not node.name.startswith("_"),
                    writes=tuple(sorted(writes)),
                    guarded=GUARD_MARKER in segment,
                    closed_legacy=closed,
                )
            )
        self.generic_visit(node)

    visit_FunctionDef = _visit_function  # type: ignore[assignment]
    visit_AsyncFunctionDef = _visit_function  # type: ignore[assignment]


def is_production_file(relative: Path) -> bool:
    """هل الملفُّ إنتاجيٌّ؟ الاختباراتُ والتبعيّاتُ والذاكرةُ المؤقّتةُ ليست إنتاجًا."""
    parts = set(relative.parts)
    if parts & SKIP_DIR_NAMES or parts & VENDOR_DIR_NAMES:
        return False
    name = relative.name
    return not (
        name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py"
    )


def is_environment_root(directory: Path) -> bool:
    """هل هذا المجلَّدُ جذرَ بيئةٍ افتراضيّة؟ — بعلامتِها البنيويّةِ لا باسمِها."""
    return (directory / VENV_MARKER).is_file()


def iter_source_files(base: Path) -> Iterator[Path]:
    """امْشِ تحتَ `base` وأعطِ ملفّاتِ `.py` التي يجوزُ أن تُقاسَ.

    البيئةُ الافتراضيّةُ **تُقطَعُ من الجذرِ** لا يُرشَّحُ ملفُّها ملفًّا: بيئةٌ
    واحدةٌ فيها عشراتُ الآلافِ من الملفّاتِ، فالمشيُ فيها كلفةٌ بلا فائدةٍ فوقَ
    كونِه تضخيمًا للعدّ. وسببُ وجودِ هذا القطعِ مقيسٌ لا متوقَّع: مسارُ التهيئةِ
    المُعتمَدُ (`tools/dev/bootstrap.sh` · T0.2) يُنشئُ `.venv` **في جذرِ
    المستودع**، فكانَ من تبِعَ الوثيقةَ يقيسُ دَينًا مُتضخِّمًا (755 موضعًا بدلَ
    168) وتسقطُ عليه بوّابةُ `decision_gate` بدعوى «انحرافٍ صامت» — أي أنَّ
    الأداةَ كانت تُعاقِبُ مَن هيّأَ بيئتَه بالطريقةِ المُوثَّقة.
    """
    collected: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(base):
        current = Path(dirpath)
        if VENV_MARKER in filenames:
            dirnames[:] = []
            continue
        dirnames[:] = [
            name
            for name in dirnames
            if name not in SKIP_DIR_NAMES and name not in VENDOR_DIR_NAMES
        ]
        collected.extend(current / name for name in filenames if name.endswith(".py"))
    return iter(sorted(collected))


def attribute_helper_writes(
    sites: list[WriteSite], calls: dict[str, set[str]]
) -> list[WriteSite]:
    """انسبْ كتابةَ المعاونينِ الخاصّينِ إلى العمليّةِ العامّةِ التي تُناديهم.

    وحدةُ العملِ ملفٌّ واحد. والتتبُّعُ عبرَ الأسماءِ لا عبرَ الأنواع: أداةُ جردٍ
    ساكنةٌ لا مُحلِّلُ أنواع، وهذا حدٌّ مُعلَنٌ لا نقصٌ مسكوتٌ عنه.
    """
    writers = {site.function for site in sites if site.writes}
    helper_writers = {name for name in writers if name.startswith("_")}
    if not helper_writers:
        return sites

    def reaches(entry: str) -> set[str]:
        """أيُّ معاونينِ كاتبينِ تصلُ إليهم `entry` — بعمقٍ وبحمايةٍ من الدوران."""
        seen: set[str] = set()
        stack = list(calls.get(entry, ()))
        found: set[str] = set()
        while stack:
            name = stack.pop()
            if name in seen or not name.startswith("_"):
                continue
            seen.add(name)
            if name in helper_writers:
                found.add(name)
            stack.extend(calls.get(name, ()))
        return found

    attributed: dict[str, set[str]] = {}
    for site in sites:
        if site.public:
            attributed[site.function] = reaches(site.function)
    reached = {name for names in attributed.values() for name in names}

    resolved: list[WriteSite] = []
    for site in sites:
        if site.public:
            via = tuple(sorted(attributed.get(site.function, ())))
            resolved.append(replace(site, writes_via=via) if via else site)
        elif site.function in reached and site.writes:
            # مُحصًى في عمليّتِه العامّة — وعدُّه ثانيًا تضخيمٌ للرقم لا دقّةٌ فيه.
            continue
        else:
            resolved.append(site)
    return resolved


def synthesize_public_sites(
    sites: list[WriteSite],
    calls: dict[str, set[str]],
    path: str,
    source: str,
    tree: ast.AST,
) -> list[WriteSite]:
    """أضِفْ عمليّاتٍ عامّةً تكتبُ **بمعاونِها** ولا كتابةَ في جسدِها.

    هذه بعينُها الحالةُ التي كان المقياسُ يُسقِطها: `set_institution_status` بعدَ
    هجرتِها في P1أ.
    """
    writer_helpers = {s.function for s in sites if s.writes and not s.public}
    known = {s.function for s in sites}
    added: list[WriteSite] = []
    classes: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                    classes[child.name] = node.name
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if node.name.startswith("_") or node.name in known:
            continue
        seen: set[str] = set()
        stack = list(calls.get(node.name, ()))
        via: set[str] = set()
        while stack:
            name = stack.pop()
            if name in seen or not name.startswith("_"):
                continue
            seen.add(name)
            if name in writer_helpers:
                via.add(name)
            stack.extend(calls.get(name, ()))
        if not via:
            continue
        segment = ast.get_source_segment(source, node) or ""
        added.append(
            WriteSite(
                path=path,
                owner=classes.get(node.name, "-"),
                function=node.name,
                line=node.lineno,
                public=True,
                writes=(),
                guarded=GUARD_MARKER in segment,
                closed_legacy=CLOSED_MARKER in segment and GUARD_MARKER not in segment,
                writes_via=tuple(sorted(via)),
            )
        )
    return added


def collect(root: Path, subtree: Path | None = None) -> list[WriteSite]:
    """اجمعْ مواضعَ الكتابةِ كلَّها تحتَ `root` (أو تحتَ `subtree` منه)."""
    base = root / subtree if subtree else root
    sites: list[WriteSite] = []
    for path in iter_source_files(base):
        relative = path.relative_to(root)
        if not is_production_file(relative):
            continue
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (SyntaxError, UnicodeDecodeError):
            continue
        visitor = _WriteVisitor(str(relative), source)
        visitor.visit(tree)
        module_sites = visitor.sites + synthesize_public_sites(
            visitor.sites, visitor.calls, str(relative), source, tree
        )
        sites.extend(attribute_helper_writes(module_sites, visitor.calls))
    return sites


#: مناطقُ القياس — الفصلُ مقصود: «خدماتٌ» ليست كـ«أدوات» ولا كـ«نواة».
AREAS: tuple[tuple[str, str], ...] = (
    ("services", "federal/executive/services/src/amos_federation/services/"),
    ("service_common", "federal/executive/services/src/amos_federation/common/"),
    ("federal_other", "federal/"),
    ("core", "core/"),
    ("tools", "tools/"),
)


def area_of(path: str) -> str:
    """أيُّ منطقةٍ يقعُ فيها الموضع؟ أوّلُ بادئةٍ مطابقةٍ تحكم."""
    for name, prefix in AREAS:
        if path.startswith(prefix):
            return name
    return "other"


def summarize(sites: list[WriteSite]) -> dict[str, object]:
    """الملخّصُ العدديُّ — ولا تُخفى فيه التفرقةُ بين العامِّ والخاصّ."""
    public = [s for s in sites if s.public]
    by_file: dict[str, int] = {}
    for site in public:
        if not site.guarded and not site.closed_legacy:
            by_file[site.path] = by_file.get(site.path, 0) + 1
    by_area: dict[str, dict[str, int]] = {}
    for site in public:
        bucket = by_area.setdefault(
            area_of(site.path), {"public": 0, "sovereign": 0, "non_sovereign": 0}
        )
        bucket["public"] += 1
        if site.guarded:
            bucket["sovereign"] += 1
        elif not site.closed_legacy:
            bucket["non_sovereign"] += 1
    return {
        "write_sites_total": len(sites),
        "by_area": by_area,
        "public_write_operations": len(public),
        "sovereign_write_operations": sum(1 for s in public if s.guarded),
        "closed_legacy_paths": sum(1 for s in sites if s.closed_legacy),
        "non_sovereign_write_operations": sum(
            1 for s in public if not s.guarded and not s.closed_legacy
        ),
        "non_sovereign_by_file": dict(
            sorted(by_file.items(), key=lambda kv: (-kv[1], kv[0]))
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="جردُ الكتاباتِ الإنتاجيّةِ وحالتِها السياديّة"
    )
    parser.add_argument("--root", default=str(REPO_ROOT), help="جذرُ المستودع")
    parser.add_argument("--service", default=None, help="مسارٌ فرعيٌّ نسبيٌّ لقصرِ الجرد")
    parser.add_argument("--json", dest="json_out", default=None, help="ملفُّ تفصيلٍ JSON")
    parser.add_argument(
        "--fail-if-any", action="store_true", help="اخرجْ بخطأٍ إن بقيت كتابةٌ متجاوزة"
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    subtree = Path(args.service) if args.service else None
    sites = collect(root, subtree)
    summary = summarize(sites)

    print("== جردُ الكتاباتِ الإنتاجيّة ==")
    print(f"  جذرُ القياس            : {subtree or '.'}")
    print(f"  مواضعُ كتابةٍ (كلُّها)   : {summary['write_sites_total']}")
    print(f"  عمليّاتٌ عامّةٌ مُغيِّرة   : {summary['public_write_operations']}")
    print(f"  منها تعبرُ الحدَّ        : {summary['sovereign_write_operations']}")
    print(f"  مساراتٌ قديمةٌ مُغلَقة    : {summary['closed_legacy_paths']}")
    print(f"  **لا تعبرُ الحدَّ**       : {summary['non_sovereign_write_operations']}")
    by_area = summary["by_area"]
    assert isinstance(by_area, dict)
    if by_area:
        print("  التوزيعُ على المناطق (عامّة / سياديّة / متجاوزة):")
        for area, counts in sorted(by_area.items()):
            print(
                f"    {area:16s} {counts['public']:4d} / {counts['sovereign']:3d} /"
                f" {counts['non_sovereign']:4d}"
            )
    non_sovereign_by_file = summary["non_sovereign_by_file"]
    assert isinstance(non_sovereign_by_file, dict)
    if non_sovereign_by_file:
        print("  التوزيعُ على الملفّات:")
        for path, count in non_sovereign_by_file.items():
            print(f"    {count:4d}  {path}")

    if args.json_out:
        # المادةُ التاسعةُ · 2: المُخرَجُ يُعلِنُ هدفَه في ترويستِه.
        payload = {
            "$comment": (
                "الهدف: جردُ مواضعِ الكتابةِ في المستودعِ وتصنيفُ ما عبرَ الحدَّ "
                "السّياديَّ وما لم يعبُر— مُخرَجُ "
                "tools/audit/sovereign_write_inventory.py --json. ومنه يُشتَقُّ رقمُ "
                "الدَّينِ وحدَه. المادةُ التاسعةُ · 2."
            ),
            "summary": summary,
            "sites": [asdict(s) for s in sites],
        }
        Path(args.json_out).write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(f"  التفصيلُ محفوظٌ في: {args.json_out}")

    if args.fail_if_any and summary["non_sovereign_write_operations"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
