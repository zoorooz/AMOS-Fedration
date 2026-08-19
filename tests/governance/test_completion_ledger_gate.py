"""
الهدف: إثباتُ أنّ بوابةَ سجلِّ الإكمالِ تُنفِذُ القاعدةَ الملزمةَ فعلًا — تسقطُ عند
       دفعِ عملٍ بلا قيد، وعند لمسِ السجلِّ بلا مدخلٍ جديد، وتمرُّ عند القيدِ الصحيح.
النطاق: سلوكُ `tools/governance/check_completion_ledger.py` وحدَه. لا يُقاسُ هنا
        مضمونُ السجلّ — الأداةُ تُقاسُ بسلوكِها لا بما تُنتِجُه من نصوص.
المالك: tests/governance
تاريخ الإنشاء: 2026-08-20
تاريخ آخر تعديل: 2026-08-20

لماذا تُختبَرُ البوابةُ لا نتيجتُها
-----------------------------------
بوابةٌ تمرُّ دائمًا ليست بوابة. فتُثبَّتُ هنا **حدودُها**: أنّها تسقطُ فعلًا،
وأنّ إعفاءَ المخرجاتِ المولَّدةِ لا يتوسّعُ إلى الكود، وأنّ لمسَ السجلِّ بمسافةٍ
بيضاءَ لا يُعَدُّ توثيقًا.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = REPO_ROOT / "tools" / "governance" / "check_completion_ledger.py"
LEDGER_REL = "docs/audit/COMPLETION_LEDGER.md"


def _load_tool():
    spec = importlib.util.spec_from_file_location("check_completion_ledger", TOOL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _load_tool()


# ── الأداةُ قائمةٌ وسجلُّها قائم ───────────────────────────────────────────────


def test_الأداةُ_والسجلُّ_موجودان() -> None:
    assert TOOL_PATH.is_file(), "بوابةُ سجلِّ الإكمالِ غيرُ موجودة"
    assert (REPO_ROOT / LEDGER_REL).is_file(), "سجلُّ الإكمالِ غيرُ موجود"


def test_السجلُّ_الحقيقيُّ_سليمُ_الشكل() -> None:
    """كلُّ قسمٍ إلزاميٍّ قائم، ولا مُعرِّفَ عملٍ مُكرَّر."""
    text = (REPO_ROOT / LEDGER_REL).read_text(encoding="utf-8")
    assert gate.check_ledger_shape(text) == []


def test_الاستدعاءُ_الذاتيُّ_يمرُّ_على_المستودع() -> None:
    out = subprocess.run(
        [sys.executable, str(TOOL_PATH), "--self-check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.returncode == 0, out.stdout + out.stderr


# ── حدودُ الشكل ──────────────────────────────────────────────────────────────


def test_غيابُ_قسمٍ_إلزاميٍّ_يُرصَد() -> None:
    text = (REPO_ROOT / LEDGER_REL).read_text(encoding="utf-8")
    mutilated = text.replace("## 8 · سجلُّ العملِ المنفَّذ", "## 8 · شيءٌ آخر")
    kinds = {v["kind"] for v in gate.check_ledger_shape(mutilated)}
    assert "LEDGER_SECTION_MISSING" in kinds


def test_تكرارُ_مُعرِّفِ_العملِ_يُرصَد() -> None:
    text = "\n".join([*gate.REQUIRED_SECTIONS, "| W-001 | أ |", "| W-001 | ب |"])
    kinds = {v["kind"] for v in gate.check_ledger_shape(text)}
    assert "DUPLICATE_WORK_ID" in kinds


# ── حدودُ الإعفاء ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        "docs/audit/TRUTH_MATRIX.md",
        "docs/audit/truth_matrix.json",
        "docs/audit/CROWN_TRUTH_MATRIX.md",
        LEDGER_REL,
        "federal/executive/services/requirements.lock",
    ],
)
def test_المخرجاتُ_المولَّدةُ_معفاة(path: str) -> None:
    assert gate.is_governed(path) is False


@pytest.mark.parametrize(
    "path",
    [
        "core/constitutional_engine/engine.py",
        "federal/executive/services/src/amos_federation/governance/factories.py",
        "docs/audit/PHASE_E_ROADMAP.md",
        "tools/governance/truth_audit.py",
        ".github/workflows/ci.yml",
    ],
)
def test_الإعفاءُ_لا_يتوسَّعُ_إلى_العملِ_الحقيقيّ(path: str) -> None:
    assert gate.is_governed(path) is True


# ── السلوكُ على مستودعٍ زائل ─────────────────────────────────────────────────


def _mkrepo(tmp_path: Path, ledger_body: str) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    ledger = tmp_path / LEDGER_REL
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(ledger_body, encoding="utf-8")
    (tmp_path / "src").mkdir(exist_ok=True)
    (tmp_path / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    return tmp_path


_BODY = "\n".join([*gate.REQUIRED_SECTIONS, "| W-000 | تأسيس |", ""])


def _stage(repo: Path, rel: str, content: str) -> None:
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", rel], cwd=repo, check=True)


def test_كودٌ_بلا_قيدٍ_يسقط(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _mkrepo(tmp_path, _BODY)
    monkeypatch.setattr(gate, "REPO_ROOT", repo)
    _stage(repo, "src/a.py", "x = 2\n")
    kinds = {v["kind"] for v in gate.run("staged", None, shape_only=False)}
    assert kinds == {"LEDGER_NOT_UPDATED"}


def test_لمسُ_السجلِّ_بلا_مدخلٍ_جديدٍ_يسقط(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _mkrepo(tmp_path, _BODY)
    monkeypatch.setattr(gate, "REPO_ROOT", repo)
    _stage(repo, "src/a.py", "x = 2\n")
    _stage(repo, LEDGER_REL, _BODY + "\nمسافةٌ بيضاءُ لا توثيق\n")
    kinds = {v["kind"] for v in gate.run("staged", None, shape_only=False)}
    assert kinds == {"LEDGER_NOT_EXTENDED"}


def test_قيدٌ_جديدٌ_مع_الكودِ_يمرُّ(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _mkrepo(tmp_path, _BODY)
    monkeypatch.setattr(gate, "REPO_ROOT", repo)
    _stage(repo, "src/a.py", "x = 2\n")
    _stage(repo, LEDGER_REL, _BODY + "| W-001 | عملٌ مُقيَّد |\n")
    assert gate.run("staged", None, shape_only=False) == []


def test_تغييرُ_مخرجٍ_مولَّدٍ_وحدَه_لا_يُلزِمُ_قيدًا(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _mkrepo(tmp_path, _BODY)
    monkeypatch.setattr(gate, "REPO_ROOT", repo)
    _stage(repo, "docs/audit/TRUTH_MATRIX.md", "# مولَّد\n")
    assert gate.run("staged", None, shape_only=False) == []


def test_غيابُ_السجلِّ_يُرصَد(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _mkrepo(tmp_path, _BODY)
    monkeypatch.setattr(gate, "REPO_ROOT", repo)
    (repo / LEDGER_REL).unlink()
    kinds = {v["kind"] for v in gate.run("staged", None, shape_only=False)}
    assert kinds == {"LEDGER_MISSING"}
