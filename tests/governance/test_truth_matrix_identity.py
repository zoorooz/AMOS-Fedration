"""
الهدف: حرسُ حتميّةِ مصفوفةِ الحقيقة — هُويّةُ المستودعِ فيها تُقرأُ من بُعدِه
       (`origin`) لا من اسمِ مجلَّدِه، فلا تسقطُ بوّابةُ الترباسِ بسببِ مسارِ
       استنساخٍ مختلفٍ بلا فرقٍ حقيقيٍّ في المضمون.
النطاق: دالّةُ `_repo_identity()` في `tools/governance/truth_audit.py` وحقلُ
        `repo` في المصفوفةِ المدفوعة. لا يُقاسُ هنا مضمونُ المخالفات.
المالك: tests/governance
تاريخ الإنشاء: 2026-08-19
تاريخ آخر تعديل: 2026-08-19

لماذا يُحرَسُ حقلٌ واحدٌ باختباراتٍ أربعة
--------------------------------------------
المصفوفةُ تُعلِنُ عن نفسِها أنّها حتميّةٌ حتى تُقارَنَ المدفوعةُ بالمولَّدة، وكانَ
هذا الإعلانُ مكسورًا: الحقلُ كان اسمَ المجلَّد. فسقطَتِ البوّابةُ (W-008) على
فرقٍ في المسارِ لا في الحقيقة. وبوّابةٌ تسقطُ لغيرِ سببٍ حقيقيٍّ تُعلَّمُ الناسَ
تجاهُلَها. فيُثبَّتُ هنا أنَّ الهُويّةَ مستقلّةٌ عن المسار، وأنَّ غيابَ البُعدِ
لا يُرفَعُ به خطأ.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "amos_truth_audit", REPO_ROOT / "tools" / "governance" / "truth_audit.py"
)
assert _SPEC and _SPEC.loader
audit = importlib.util.module_from_spec(_SPEC)
sys.modules["amos_truth_audit"] = audit
_SPEC.loader.exec_module(audit)


def _mkrepo(path: Path, remote: str | None) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    if remote is not None:
        subprocess.run(["git", "remote", "add", "origin", remote], cwd=path, check=True)
    return path


def test_الهُويّةُ_من_البُعدِ_لا_من_اسمِ_المجلَّد(tmp_path: Path) -> None:
    """مجلَّدانِ مختلفا الاسمِ لبُعدٍ واحدٍ يُعطيانِ هُويّةً واحدة."""
    a = _mkrepo(tmp_path / "v4", "https://github.com/zoorooz/AMOS-Fedration.git")
    b = _mkrepo(tmp_path / "clone-2", "https://github.com/zoorooz/AMOS-Fedration.git")
    assert audit._repo_identity(a) == "AMOS-Fedration"
    assert audit._repo_identity(a) == audit._repo_identity(b)


def test_صيغةُ_ssh_تُفهَمُ_كصيغةِ_https(tmp_path: Path) -> None:
    repo = _mkrepo(tmp_path / "ssh", "git@github.com:zoorooz/AMOS-Fedration.git")
    assert audit._repo_identity(repo) == "AMOS-Fedration"


def test_مستودعٌ_بلا_بُعدٍ_يرجعُ_لاسمِ_مجلَّده(tmp_path: Path) -> None:
    """غيابُ البُعدِ حالةٌ مشروعةٌ — يُرجَعُ للاسمِ ولا يُرفَعُ خطأ."""
    repo = _mkrepo(tmp_path / "بلا-بُعد", None)
    assert audit._repo_identity(repo) == "بلا-بُعد"


def test_هُويّةُ_هذا_المستودعِ_ثابتةٌ_في_المصفوفةِ_المدفوعة() -> None:
    """ما في المصفوفةِ المدفوعةِ هو ما يُولِّدُه المستودعُ الآنَ من بُعدِه."""
    import json

    pushed = json.loads((REPO_ROOT / "docs" / "audit" / "truth_matrix.json").read_text("utf-8"))
    if audit._repo_identity(REPO_ROOT) == REPO_ROOT.name:
        return  # لا بُعدَ في هذه البيئة — لا حُكمَ يُبنى على غيابٍ
    assert pushed["repo"] == audit._repo_identity(REPO_ROOT)
