#!/usr/bin/env python3
"""الهدف: إثبات E2.2-G تنفيذيًّا — تشغيل الحِزَم المطلوبة عبر الأنظمة وقياسها.

المشكلة التي تحلّها هذه الأداة ليست «تشغيل الاختبارات»؛ فذلك يفعله `pytest`.
المشكلة أن **الحزمة الخضراء لا تقول أي نظام جُرِّب**. حزمة الخدمات تمرّ خضراء
تمامًا حين تتخطّى كل اختبارات PostgreSQL بصمت — فتبدو «الحِزَم الكاملة عبر
الأنظمة» منجَزة وهي لم تلمس PostgreSQL إطلاقًا. هذه ثقة كاذبة من النوع الذي
يمنعه ميثاق المستودع.

فالأداة تفعل ثلاثة أشياء لا يفعلها `pytest` وحده:

1. **تُعلن مصفوفة الحِزَم صراحةً** (`SUITES`): ما يُشغَّل، من أي مجلد، وأي لهجة
   SQL يُفترض أن يُجرِّب. لا حزمة مطلوبة تُنسى بالسهو.
2. **تتحقّق أن اللهجة جُرِّبت فعلًا لا أنها تُخطّيت.** حزمة موسومة
   `POSTGRES` تسقط إن ظهر فيها **أي** تخطٍّ، لأن التخطّي هنا معناه أن
   PostgreSQL لم يُلمَس. لا يمكن للأداة أن تكون خضراء وPostgreSQL غير مُجرَّب.
3. **تكتب وثيقة دليل مولَّدة** فيها الأرقام المقيسة لحظة التشغيل، لا أرقامًا
   منقولة بيد.

ما لا تفعله بقصد: لا تخفّض عتبة، ولا تُسكت اختبارًا، ولا تُصلح فشلًا. تقيس
وتُبلّغ وتسقط برمز غير صفري.

الاستخدام:
    python tools/governance/verify_cross_system_suites.py
        يشغّل الحِزَم كلها ويكتب الوثيقة. يسقط عند أي فشل أو لهجة غير مُجرَّبة.

    python tools/governance/verify_cross_system_suites.py --require-postgres
        يسقط أيضًا إن كانت بيئة PostgreSQL غائبة أصلًا (لا يقبل «تُخطّيت بعذر»).

    python tools/governance/verify_cross_system_suites.py --check
        فحص انحراف ساكن بلا تشغيل: الوثيقة موجودة، وتذكر كل حزمة مُعلنة،
        وملفات الحِزَم المُعلنة ما زالت موجودة. صالح لـCI السريع.

النطاق: tools/governance
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-16
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICES_DIR = REPO_ROOT / "federal" / "executive" / "services"
OUTPUT = REPO_ROOT / "docs" / "audit" / "CROSS_SYSTEM_SUITE_MATRIX.md"

# اللهجات المُعلنة. `NONE` تعني حزمة لا تمسّ طبقة SQL المزدوجة.
DIALECT_NONE = "NONE"
DIALECT_SQLITE = "SQLITE"
DIALECT_POSTGRES = "POSTGRES"

# متغيّرات البيئة التي تُفعّل مسار PostgreSQL الحقيقي.
PG_FLAG_ENV = "AMOS_RUN_POSTGRES_TESTS"
PG_URL_ENV = "AMOS_TEST_DATABASE_URL"


@dataclass(frozen=True)
class Suite:
    """حزمة مُعلنة: ماذا تُشغَّل، من أين، وأي لهجة تُجرِّب."""

    name: str
    workdir: Path
    targets: tuple[str, ...]
    dialect: str
    purpose: str
    # حزمة `POSTGRES` لا يُسمح فيها بأي تخطٍّ: التخطّي = لهجة لم تُجرَّب.
    forbid_skips: bool = False
    # أعلام بيئة تُنزَع قبل التشغيل، فتُقاس اللهجة المقصودة لا ما ورثته البيئة.
    unset_env: tuple[str, ...] = ()


# =============================================================================
# مصفوفة الحِزَم المطلوبة في E2.2-G — مُعلنة لا مُستنبَطة
# =============================================================================
SUITES: tuple[Suite, ...] = (
    Suite(
        name="root-core",
        workdir=REPO_ROOT,
        targets=("tests",),
        dialect=DIALECT_NONE,
        purpose="نواة الدستور والسيادة والتاج والحكم — لا تمسّ طبقة SQL المزدوجة",
    ),
    Suite(
        name="services-sqlite",
        workdir=SERVICES_DIR,
        targets=("tests",),
        dialect=DIALECT_SQLITE,
        purpose="حزمة خدمات الاتحاد الكاملة على لهجة SQLite (التركيب الافتراضي)",
        # يُنزَع عَلَم PostgreSQL قصدًا: هذه الحزمة تقيس التركيب الافتراضي وحده،
        # فلا تُنسَب خضرتها إلى PostgreSQL بالوراثة من بيئة المشغِّل.
        unset_env=(PG_FLAG_ENV,),
    ),
    Suite(
        name="services-postgres",
        workdir=SERVICES_DIR,
        targets=(
            "tests/test_phase1_postgres.py",
            "tests/test_phase1_postgres_events.py",
        ),
        dialect=DIALECT_POSTGRES,
        purpose="إثبات لهجة PostgreSQL على قاعدة حقيقية — لا تُقبل خضرة بالتخطّي",
        forbid_skips=True,
    ),
)

# عددُ أسطر المخرَج التي تُنشر في تعليق السقوط.
TAIL_LINES = 40

# أنماط ملخّص pytest: «5 passed, 2 skipped in 1.23s» وما يشبهه.
_SUMMARY_TOKEN = re.compile(
    r"(\d+)\s+(passed|failed|skipped|error|errors|xfailed|xpassed)"
)


@dataclass
class SuiteResult:
    """نتيجة مقيسة لحزمة واحدة — كل رقم فيها من مخرَج تشغيل فعلي."""

    suite: Suite
    exit_code: int
    counts: dict[str, int] = field(default_factory=dict)
    duration_s: float = 0.0
    summary_line: str = ""
    violations: list[str] = field(default_factory=list)
    # آخِرُ سطور مخرَج pytest الفعليّ: تُنشر في تعليق GitHub عند السقوط،
    # لأنّ سجلّ الوظيفة لا يُقرأ إلاّ بدخول، أمّا التعليقات فتُرى علنًا.
    tail: str = ""

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.violations


def parse_summary(output: str) -> tuple[dict[str, int], str]:
    """استخراج عدّادات pytest من آخر سطر ملخّص في المخرَج.

    يُقرأ من الأسفل إلى الأعلى لأن آخر سطر ملخّص هو ملخّص الجولة، وما قبله قد
    يكون ملخّص جولة سابقة في السجل نفسه.
    """
    for raw in reversed([ln for ln in output.splitlines() if ln.strip()]):
        # يُنزَع زخرف «=====» الذي يحيط ملخّص pytest، فيبقى النص وحده.
        line = raw.strip().strip("=").strip()
        tokens = _SUMMARY_TOKEN.findall(line)
        if not tokens:
            continue
        counts: dict[str, int] = {}
        for value, kind in tokens:
            key = "error" if kind == "errors" else kind
            counts[key] = counts.get(key, 0) + int(value)
        return counts, line
    return {}, ""


def postgres_env_present(env: dict[str, str] | None = None) -> bool:
    """هل بيئة PostgreSQL الحقيقية مُفعّلة أصلًا؟"""
    source = os.environ if env is None else env
    return source.get(PG_FLAG_ENV) == "1" and source.get(PG_URL_ENV, "").startswith(
        "postgresql"
    )


def evaluate(suite: Suite, exit_code: int, counts: dict[str, int]) -> list[str]:
    """قواعد السقوط. مفصولة عن التشغيل لتكون قابلة للاختبار بلا شبكة."""
    violations: list[str] = []
    if exit_code != 0:
        violations.append(f"رمز خروج {exit_code}")
    if counts.get("failed"):
        violations.append(f"{counts['failed']} اختبارًا ساقطًا")
    if counts.get("error"):
        violations.append(f"{counts['error']} خطأ جمع/تهيئة")
    if not counts.get("passed"):
        violations.append("لا اختبار ناجح واحد — الحزمة لم تُشغَّل فعلًا")
    if suite.forbid_skips and counts.get("skipped"):
        violations.append(
            f"{counts['skipped']} اختبارًا مُتخطّى في حزمة لهجة "
            f"{suite.dialect} — التخطّي هنا يعني أن اللهجة لم تُجرَّب"
        )
    return violations


def run_suite(suite: Suite) -> SuiteResult:
    """تشغيل حزمة واحدة وقياسها. لا يحقن عَلَمًا؛ ينزع فقط ما أعلنته الحزمة."""
    started = time.monotonic()
    env = dict(os.environ)
    for name in suite.unset_env:
        env.pop(name, None)
    proc = subprocess.run(  # noqa: S603 - أوامر ثابتة مُعلنة في SUITES
        [
            sys.executable,
            "-m",
            "pytest",
            *suite.targets,
            "-q",
            "--no-header",
            "-p",
            "no:cacheprovider",
        ],
        cwd=suite.workdir,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    duration = time.monotonic() - started
    merged = proc.stdout + "\n" + proc.stderr
    counts, line = parse_summary(merged)
    lines = [ln.rstrip() for ln in merged.splitlines() if ln.strip()]
    return SuiteResult(
        suite=suite,
        exit_code=proc.returncode,
        counts=counts,
        duration_s=duration,
        summary_line=line,
        violations=evaluate(suite, proc.returncode, counts),
        tail="\n".join(lines[-TAIL_LINES:]),
    )


def annotation(result: SuiteResult) -> str:
    """سطرُ `::error::` واحد يحمل سببَ السقوط ومخرَجه الفعليّ.

    GitHub يعرض التعليقات لكلّ زائر ولو لم يدخل، ويحجب سجلّ الوظيفة عن
    غير الموقّعين. فإنّ لم يُنشَر السببُ هنا بقي الفشلُ غيرَ مرصود، والفشلُ
    الذي لا يُرى لا يُصلَح.
    """
    parts = [
        f"الحزمة {result.suite.name} ({result.suite.dialect}) سقطت",
        f"رمز الخروج: {result.exit_code}",
        f"العدّادات: {result.counts or 'لا ملخّص مقروء'}",
        f"ملخّص pytest: {result.summary_line or 'لا سطر ملخّص'}",
    ]
    parts.extend(f"مخالفة: {v}" for v in result.violations)
    parts.append("آخِرُ المخرَج:")
    parts.extend(result.tail.splitlines())
    body = "%0A".join(part.replace("::", ": ") for part in parts)
    return f"::error title=cross-system {result.suite.name}::{body}"


def render(results: list[SuiteResult], *, pg_present: bool) -> str:
    """توليد وثيقة الدليل. كل رقم فيها من `results` لا من نص مكتوب بيد."""
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# مصفوفة الحِزَم عبر الأنظمة — E2.2-G",
        "",
        "الهدف: بيان **أي حزمة شُغِّلت وأي لهجة SQL جُرِّبت فعلًا**، لأن الحزمة",
        "الخضراء وحدها لا تقول ذلك: حزمة خدمات الاتحاد تمرّ خضراء تمامًا وهي",
        "تتخطّى كل اختبارات PostgreSQL بصمت.",
        "",
        "هذه الوثيقة **مولَّدة** بـ",
        "[`tools/governance/verify_cross_system_suites.py`]"
        "(../../tools/governance/verify_cross_system_suites.py)",
        "وأرقامها مقيسة لحظة التوليد. تحريرها يدويًّا لا يغيّر شيئًا في الواقع.",
        "",
        f"آخر توليد: **{stamp}**",
        "",
        f"بيئة PostgreSQL الحقيقية لحظة التوليد: "
        f"**{'مُفعّلة' if pg_present else 'غائبة'}**"
        f" (`{PG_FLAG_ENV}` + `{PG_URL_ENV}`)",
        "",
        "## الحِزَم المُعلنة ونتائجها المقيسة",
        "",
        "| الحزمة | اللهجة | ناجح | ساقط | مُتخطّى | ثوانٍ | الحال |",
        "|---|---|---|---|---|---|---|",
    ]
    for result in results:
        counts = result.counts
        state = "PASS" if result.ok else "FAIL"
        lines.append(
            f"| `{result.suite.name}` | `{result.suite.dialect}` "
            f"| {counts.get('passed', 0)} | {counts.get('failed', 0)} "
            f"| {counts.get('skipped', 0)} | {result.duration_s:.1f} | **{state}** |"
        )

    lines += ["", "## ما تعنيه كل حزمة", ""]
    for result in results:
        targets = " · ".join(f"`{t}`" for t in result.suite.targets)
        workdir = _display_path(result.suite.workdir) or "."
        lines += [
            f"### `{result.suite.name}`",
            "",
            f"- الغرض: {result.suite.purpose}",
            f"- المجلد: `{workdir}`",
            f"- الهدف: {targets}",
            f"- ملخّص pytest الفعلي: `{result.summary_line or 'لا ملخّص'}`",
        ]
        if result.suite.forbid_skips:
            lines.append("- **التخطّي ممنوع في هذه الحزمة** — التخطّي يعني لهجة لم تُجرَّب.")
        if result.violations:
            lines.append(f"- **مخالفات:** {' · '.join(result.violations)}")
        lines.append("")

    lines += [
        "## ما لا تُثبِته هذه الوثيقة",
        "",
        "- لا تُثبِت أن CI شغّل شيئًا. تُثبِت ما شُغِّل حيث شُغِّلت الأداة.",
        "- لا تُثبِت أن كل شيفرة الخدمات جُرِّبت على PostgreSQL؛ تُثبِت أن حِزَم",
        "  اللهجة المُعلنة جُرِّبت عليه بلا تخطٍّ.",
        "- لا تقيس تغطية. التغطية بوابات أخرى مستقلة.",
        "",
    ]
    return "\n".join(lines)


def _display_path(path: Path) -> str:
    """مسار للعرض: نسبي إن كان داخل المستودع، وإلا مطلق كما هو.

    الشرط صريح وليس `try/except`: ابتلاع استثناء هنا مخالفة `SILENT_FALLBACK`
    في مدقّق الحقيقة ولو كان الاستثناء متوقّعًا — والمدقّق محقّ بنيويًّا.
    """
    if path.is_relative_to(REPO_ROOT):
        return str(path.relative_to(REPO_ROOT))
    return str(path)


def check_drift() -> list[str]:
    """فحص ساكن بلا تشغيل: الوثيقة موجودة وتذكر كل حزمة، والأهداف موجودة."""
    problems: list[str] = []
    if not OUTPUT.exists():
        return [f"الوثيقة المولَّدة غائبة: {_display_path(OUTPUT)}"]
    text = OUTPUT.read_text(encoding="utf-8")
    for suite in SUITES:
        if f"`{suite.name}`" not in text:
            problems.append(f"الوثيقة لا تذكر الحزمة المُعلنة `{suite.name}`")
        for target in suite.targets:
            path = suite.workdir / target
            if not path.exists():
                problems.append(f"هدف مُعلن غير موجود: `{suite.name}` → `{target}`")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="إثبات الحِزَم عبر الأنظمة (E2.2-G)")
    parser.add_argument(
        "--check", action="store_true", help="فحص انحراف ساكن بلا تشغيل"
    )
    parser.add_argument(
        "--require-postgres",
        action="store_true",
        help="السقوط إن كانت بيئة PostgreSQL غائبة أصلًا",
    )
    args = parser.parse_args(argv)

    if args.check:
        problems = check_drift()
        for problem in problems:
            print(f"  ✗ {problem}")
        if problems:
            print(f"[CROSS-SYSTEM] ✗ انحراف: {len(problems)} مخالفة.")
            return 1
        print("[CROSS-SYSTEM] ✓ الوثيقة المولَّدة مطابقة للمصفوفة المُعلنة.")
        return 0

    pg_present = postgres_env_present()
    if args.require_postgres and not pg_present:
        print(
            f"[CROSS-SYSTEM] ✗ بيئة PostgreSQL غائبة ({PG_FLAG_ENV}/{PG_URL_ENV}) "
            "— لا يجوز ادّعاء إثبات عبر الأنظمة."
        )
        return 1

    results: list[SuiteResult] = []
    for suite in SUITES:
        print(f"[CROSS-SYSTEM] ▶ {suite.name} ({suite.dialect}) …", flush=True)
        result = run_suite(suite)
        results.append(result)
        counts = result.counts
        print(
            f"    {'✓' if result.ok else '✗'} passed={counts.get('passed', 0)} "
            f"failed={counts.get('failed', 0)} skipped={counts.get('skipped', 0)} "
            f"({result.duration_s:.1f}s)",
            flush=True,
        )
        for violation in result.violations:
            print(f"      ✗ {violation}")
        if not result.ok:
            print(annotation(result), flush=True)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(render(results, pg_present=pg_present), encoding="utf-8")
    print(f"[CROSS-SYSTEM] كُتبت: {OUTPUT}")

    failed = [r for r in results if not r.ok]
    if failed:
        print(
            f"[CROSS-SYSTEM] ✗ سقطت {len(failed)} حزمة: {', '.join(r.suite.name for r in failed)}"
        )
        return 1
    exercised = sorted({r.suite.dialect for r in results} - {DIALECT_NONE})
    print(
        f"[CROSS-SYSTEM] ✓ كل الحِزَم المُعلنة خضراء. اللهجات المُجرَّبة: {', '.join(exercised)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
