#!/usr/bin/env python3
"""
بوابة سجلّ الإكمال — Completion Ledger Gate

الهدف: أن تكون «قاعدةُ التوثيقِ قبلَ الدفع» قاعدةً **مُنفَذَةً** لا وصيّةً مكتوبة.
       تفشل هذه البوابة إذا مسّ التزامٌ ملفًّا خاضعًا للقاعدة ولم يُحدِّث
       `docs/audit/COMPLETION_LEDGER.md` بمدخلِ عملٍ جديدٍ في السجلّ نفسِه.
النطاق: مجموعةُ التغييرِ (المُدرَجُ للالتزام، أو مدى التزاماتٍ، أو التزامٌ واحد).
        لا تحكم هذه الأداةُ على مضمونِ العمل ولا على صوابِه — تحكم على وجودِ
        قيدِه فقط. الحكمُ على المضمون لديوانِ التدقيق.
المالك: tools/governance — ديوان التدقيق، بتفويضٍ من المجلس التأسيسي
تاريخ الإنشاء: 2026-08-19
تاريخ آخر تعديل: 2026-08-19

لماذا أداةٌ لا فقرةٌ في وثيقة
-----------------------------
المستودعُ كلُّه مبنيٌّ على قاعدةِ `DONE = Capability Proven`. وقاعدةٌ توجب
التوثيقَ قبلَ الدفعِ ولا يحرسُها إلّا نصٌّ في ملفٍّ هي **قاعدةٌ غيرُ مُنفَذَة**:
تُنسى في أوّلِ التزامٍ عاجل، ولا يُقاسُ خرقُها. فتُنفَّذ هنا بوّابةً لها رمزُ
خروجٍ، تصلحُ خطوةً في `pre-commit` وخطوةً في التكامل المستمرّ.

المخالفات
---------
  LEDGER_MISSING        سجلّ الإكمال غير موجود في المستودع
  LEDGER_NOT_UPDATED    تغيَّر ملفٌّ خاضعٌ للقاعدة ولم يتغيّر السجلّ معه
  LEDGER_NOT_EXTENDED   تغيَّر السجلُّ بلا مدخلِ عملٍ جديدٍ (`| W-…`) مُضاف
  LEDGER_STALE_BASE     المدخلُ «الجديد» موجودٌ أصلاً في `origin/main` — الأساسُ بائد
  LEDGER_SECTION_MISSING السجلُّ فقدَ قسمًا من أقسامِه الإلزاميّة
  DUPLICATE_WORK_ID     مُعرِّفُ عملٍ (`W-…`) مُكرَّرٌ في السجلّ

الاستخدام
---------
    python tools/governance/check_completion_ledger.py --staged
    python tools/governance/check_completion_ledger.py --range origin/main..HEAD
    python tools/governance/check_completion_ledger.py --commit HEAD
    python tools/governance/check_completion_ledger.py --self-check
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

LEDGER_PATH = "docs/audit/COMPLETION_LEDGER.md"

# ── ما لا يُلزِمُ قيدًا ────────────────────────────────────────────────────────
#
# مخرجاتٌ مولَّدةٌ آليًّا: تتغيّر بإعادةِ التوليدِ لا بعملٍ بشريّ، فإلزامُها بقيدٍ
# يُنتِجُ قيودًا فارغةً تُفسِدُ السجلَّ بدلًا من أن تُوثِّقَه. والسجلُّ نفسُه معفًى
# بحكمِ المنطق: لا يُلزَمُ بأن يوثِّقَ تحديثَه لنفسِه.
EXEMPT_EXACT = frozenset({
    LEDGER_PATH,
    "docs/audit/TRUTH_MATRIX.md",
    "docs/audit/truth_matrix.json",
    "docs/audit/truth_baseline.json",
    "docs/audit/CROWN_TRUTH_MATRIX.md",
    "docs/audit/CROSS_SYSTEM_SUITE_MATRIX.md",
    "docs/audit/constitution_history_digests.json",
    "docs/security/CROWN_THREAT_MODEL.md",
})

EXEMPT_PREFIXES = ("docs/audit/measurements/", "docs/audit/backups/")

EXEMPT_SUFFIXES = (".lock", ".egg-info", ".pyc")

REQUIRED_SECTIONS = (
    "## 1 · ما هذه الوثيقة وما ليست",
    "## 2 · القاعدةُ الملزمة",
    "## 3 · خطُّ الأساسِ المقيس",
    "## 5 · تعريفُ 100٪",
    "## 6 · خريطةُ الطريق",
    "## 8 · سجلُّ العملِ المنفَّذ",
    "## 9 · المتبقّي بالأرقام",
)

WORK_ID_RE = re.compile(r"^\|\s*(W-\d{3})\s*\|")
# re.MULTILINE لازمٌ لا زينة: يُطبَّقُ على نصِّ الفارقِ كاملًا لا سطرًا سطرًا.
ADDED_WORK_ID_RE = re.compile(r"^\+\|\s*(W-\d{3})\s*\|", re.MULTILINE)


# ── قراءةُ مجموعةِ التغيير ────────────────────────────────────────────────────


def _git(*args: str) -> str:
    """نداءُ git من جذرِ المستودع. سببُ الفشلِ يُنقَل ولا يُبتلع."""
    out = subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    if out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} → {out.returncode}: {out.stderr.strip()}")
    return out.stdout


def changed_paths(mode: str, ref: str | None) -> list[str]:
    if mode == "staged":
        raw = _git("diff", "--cached", "--name-only", "--diff-filter=ACMRD")
    elif mode == "range":
        raw = _git("diff", "--name-only", "--diff-filter=ACMRD", str(ref))
    else:  # commit
        raw = _git("show", "--pretty=format:", "--name-only", "--diff-filter=ACMRD", str(ref))
    return sorted({line.strip() for line in raw.splitlines() if line.strip()})


def ledger_diff(mode: str, ref: str | None) -> str:
    if mode == "staged":
        return _git("diff", "--cached", "--unified=0", "--", LEDGER_PATH)
    if mode == "range":
        return _git("diff", "--unified=0", str(ref), "--", LEDGER_PATH)
    return _git("show", "--pretty=format:", "--unified=0", str(ref), "--", LEDGER_PATH)


def upstream_work_ids(remote_ref: str = "origin/main") -> set[str] | None:
    """مُعرّفاتُ العملِ الموجودةُ في السجلِّ المنشور، أو `None` إن تَعَذَّرَ قراءتُه.

    لا يُعدُّ غيابُ البُعدِ مخالفةً: مستودعٌ بلا بُعدٍ حالةٌ مشروعة. ولا يُبتلَعُ
    هنا استثناءٌ: الغيابُ يُستبانُ بسؤالٍ صريحٍ قبلَ القراءة، فأيُّ فشلٍ بعدهُ
    خللٌ حقيقيٌّ يُرفَعُ ولا يُستَر.
    """
    probe = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{remote_ref}:{LEDGER_PATH}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        return None
    text = _git("show", f"{remote_ref}:{LEDGER_PATH}")
    return {m.group(1) for line in text.splitlines() if (m := WORK_ID_RE.match(line))}


def is_governed(path: str) -> bool:
    """هل هذا الملفُّ يُلزِمُ صاحبَه بقيدٍ في السجلّ؟"""
    if path in EXEMPT_EXACT:
        return False
    if path.startswith(EXEMPT_PREFIXES):
        return False
    if path.endswith(EXEMPT_SUFFIXES):
        return False
    return True


# ── الفحوص ───────────────────────────────────────────────────────────────────


def check_ledger_shape(text: str) -> list[dict[str, str]]:
    """السجلُّ سليمُ الشكل: أقسامُه الإلزاميّةُ قائمةٌ ومعرِّفاتُه غيرُ مُكرَّرة."""
    violations: list[dict[str, str]] = []
    for section in REQUIRED_SECTIONS:
        if section not in text:
            violations.append({
                "kind": "LEDGER_SECTION_MISSING",
                "detail": f"القسم «{section}» غير موجود في السجلّ",
            })
    seen: set[str] = set()
    for line in text.splitlines():
        m = WORK_ID_RE.match(line)
        if not m:
            continue
        wid = m.group(1)
        if wid in seen:
            violations.append({
                "kind": "DUPLICATE_WORK_ID",
                "detail": f"مُعرِّفُ العمل {wid} مُكرَّرٌ — كلُّ قيدٍ مُعرِّفٌ واحدٌ لا يُعاد",
            })
        seen.add(wid)
    return violations


def check_change_set(mode: str, ref: str | None) -> list[dict[str, str]]:
    paths = changed_paths(mode, ref)
    governed = [p for p in paths if is_governed(p)]
    if not governed:
        return []

    violations: list[dict[str, str]] = []
    if LEDGER_PATH not in paths:
        sample = "، ".join(governed[:5]) + ("، …" if len(governed) > 5 else "")
        violations.append({
            "kind": "LEDGER_NOT_UPDATED",
            "detail": (
                f"{len(governed)} ملفًّا خاضعًا للقاعدة تغيَّرَ بلا تحديثِ السجلّ "
                f"({sample}) — القاعدةُ الملزمة § 2"
            ),
        })
        return violations

    added = ADDED_WORK_ID_RE.findall(ledger_diff(mode, ref))
    if not added:
        violations.append({
            "kind": "LEDGER_NOT_EXTENDED",
            "detail": (
                "السجلُّ ضمنَ التغييرِ لكن بلا مدخلِ عملٍ جديد (سطرٌ مُضافٌ يبدأ "
                "بـ`| W-###`) — لمسُ الملفِّ ليس توثيقًا"
            ),
        })
        return violations

    # فخُّ الأساسِ البائد: إن كان `HEAD` المحلّيُّ متأخّرًا عن المنشور، ظهرَت
    # قيودٌ مدفوعةٌ أصلاً «مُضافةً» في الفارق، فتمرُّ البوّابةُ بلا توثيقٍ جديد.
    if mode == "staged":
        upstream = upstream_work_ids()
        if upstream is not None:
            stale = sorted(set(added) & upstream)
            if stale and not (set(added) - upstream):
                violations.append({
                    "kind": "LEDGER_STALE_BASE",
                    "detail": (
                        f"المداخلُ المُعلَنةُ جديدةً ({'، '.join(stale)}) "
                        "موجودةٌ أصلاً في `origin/main` — أساسُ المقارنةِ بائد. "
                        "زامِل المنشورَ (`git fetch && git rebase origin/main`) ثمّ أعدِ الفحص"
                    ),
                })
    return violations


def run(mode: str, ref: str | None, shape_only: bool) -> list[dict[str, str]]:
    ledger = REPO_ROOT / LEDGER_PATH
    if not ledger.exists():
        return [{
            "kind": "LEDGER_MISSING",
            "detail": f"{LEDGER_PATH} غير موجود — لا سجلَّ إكمالٍ يُوثَّقُ فيه",
        }]

    violations = check_ledger_shape(ledger.read_text(encoding="utf-8"))
    if not shape_only:
        violations += check_change_set(mode, ref)
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description="بوابة سجلّ الإكمال — التوثيقُ قبلَ الدفع")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--staged", action="store_true", help="فحصُ ما أُدرِجَ للالتزام (الافتراضيّ)")
    group.add_argument("--range", dest="rng", metavar="A..B", help="فحصُ مدى التزامات")
    group.add_argument("--commit", metavar="SHA", help="فحصُ التزامٍ واحد")
    group.add_argument(
        "--self-check",
        action="store_true",
        help="فحصُ شكلِ السجلِّ وحدَه بلا مجموعةِ تغيير",
    )
    args = parser.parse_args()

    if args.rng:
        mode, ref = "range", args.rng
    elif args.commit:
        mode, ref = "commit", args.commit
    else:
        mode, ref = "staged", None

    try:
        violations = run(mode, ref, shape_only=bool(args.self_check))
    except RuntimeError as exc:  # سببُ الفشلِ يُعلَنُ ولا يُبتلع
        print(f"[LEDGER GATE] تعذّرت القراءةُ من git: {exc}", file=sys.stderr)
        return 2

    if not violations:
        print("[LEDGER GATE] ✓ التوثيقُ مقيَّدٌ مع العمل — لا مخالفة.")
        return 0

    print(f"[LEDGER GATE] ✗ مخالفات: {len(violations)}")
    for v in violations:
        print(f"  {v['kind']}: {v['detail']}")
    print(f"\n  القاعدةُ الملزمة: {LEDGER_PATH} § 2")
    return 1


if __name__ == "__main__":
    sys.exit(main())
