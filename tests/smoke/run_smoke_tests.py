# =============================================================================
# File:        tests/smoke/run_smoke_tests.py
# Purpose:     مشغّل اختبارات الدخان لكل النطاقات الـ12 — يفحص كل stub ويطبع جدولًا
# Owner:       tests/
# Created:     2026-08-15
# Last Modified: 2026-08-22 (W-025)
# Phase:       P3 (Working Nuclei)
# Article 009: هذا الملف يلتزم بالمادة 009 — الشفافية والمراجعة المستمرة.
#              يفصل هذا المشغّل بين ثلاث حالات: قِيسَ ونجح، وقِيسَ وفشل، ولم
#              يُقَس. «غير مقيس» ليس نجاحًا ولا يُعَدُّ منه.
# =============================================================================
"""
مشغّل اختبارات الدخان (Smoke Test Runner).

الهدف: استيرادُ كلِّ حارسِ إقليمٍ واستدعاءُ `check()` والإبلاغُ عن حالةِ كلِّ
       إقليمٍ بثلاثِ حالاتٍ مُتمايزة:
         pass       — قِيسَ الآنَ من مصدرِ الحقيقةِ ونجح.
         unmeasured — لا مصدرَ حقيقةٍ مُهيَّأً؛ الأرقامُ مُقتبَسةٌ من لَقطةٍ مُؤرَّخة.
         fail/error — قِيسَ وفشل، أو انكسرَ الحارسُ نفسُه.
النطاق: 12 إقليمًا. لا يقرأُ قاعدةَ البياناتِ بنفسِه — الحرّاسُ يفعلون.
المالك: tests/
تاريخ الإنشاء: 2026-08-15
تاريخ آخر تعديل: 2026-08-22

رموزُ الخروج:
    0  لا إقليمَ فاشلًا (يجوزُ وجودُ أقاليمَ غيرِ مقيسةٍ — وتُطبَعُ صريحًا).
    1  إقليمٌ واحدٌ فاشلٌ على الأقل.
    1  مع `--require-measured`: إن وُجِدَ إقليمٌ واحدٌ غيرُ مقيس.

سببُ التغيير (W-025): كانت البوّابةُ تقارنُ ثوابتَ الحارسِ بنفسِها فتُصادِقُ على
ذاتِها. صار الحكمُ الآنَ من القياس، وصار «غير مقيس» حالةً مرئيّةً لا تُخفى تحت
راية النجاح. البوّاباتُ التي تشترطُ إثباتًا (D-4/D-7) تُشغِّلُ `--require-measured`.
"""

import argparse
import importlib
import sys
import os

# Ensure the project root is on sys.path so domain stub packages resolve
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# --- Registry of all 12 domain stubs ---
# Each tuple: (domain label, module path, function name)
DOMAIN_STUBS = [
    ("tools", "tools.stubs.registry_check", "check"),
    ("agents", "agents.stubs.registry_check", "check"),
    ("institutions", "institutions.stubs.registry_check", "check"),
    ("royal", "royal.stubs.guard_check", "check"),
    ("ops", "ops.stubs.audit_check", "check"),
    ("federal", "federal.stubs.treasury_check", "check"),
    ("core", "core.stubs.memory_check", "check"),
    ("runtime", "runtime.stubs.task_event_check", "check"),
    ("interfaces", "interfaces.stubs.registry_check", "check"),
    ("states", "states.stubs.policy_check", "check"),
    ("docs", "docs.stubs.docs_check", "check"),
    ("tests", "tests.stubs.tests_check", "check"),
]


def run_all():
    """Run smoke checks for all 12 domains.

    Returns:
        tuple: (results list, overall pass boolean)
    """
    results = []
    all_pass = True

    for domain, module_path, func_name in DOMAIN_STUBS:
        try:
            mod = importlib.import_module(module_path)
            check_fn = getattr(mod, func_name)
            result = check_fn()
            status = result.get("status", "fail")
            if status not in ("pass", "unmeasured"):
                all_pass = False
            results.append((domain, status, result))
        except Exception as exc:  # noqa: BLE001
            all_pass = False
            results.append((domain, "error", {"error": str(exc)}))

    return results, all_pass


def print_summary_table(results):
    """Print a formatted summary table of all domain checks."""
    header = f"{'Domain':<16} {'Status':<8} {'Detail'}"
    sep = "-" * len(header)
    print()
    print("=" * 64)
    print("  AMOS-Federation P3 Smoke Tests — Summary")
    print("=" * 64)
    print(header)
    print(sep)

    for domain, status, result in results:
        # Build a short detail string from the result dict
        detail_parts = []
        for key in ("count", "guards", "decrees", "memories", "experiences",
                    "tasks", "events", "transactions", "budgets",
                    "executive_roles", "nucleus_files", "schemas", "registries",
                    "legislations", "compliance_reports"):
            if key in result:
                detail_parts.append(f"{key}={result[key]}")
        if "source" in result:
            detail_parts.append(f"source={result['source']}")
        if "note" in result:
            detail_parts.append(result["note"])
        if "reason" in result and status not in ("pass", "unmeasured"):
            detail_parts.append(result["reason"])
        if "error" in result:
            detail_parts.append(f"error={result['error']}")
        detail = ", ".join(detail_parts) if detail_parts else "-"
        marker = {"pass": "PASS", "unmeasured": "UNMEASURED"}.get(status, "FAIL")
        print(f"{domain:<16} {marker:<12} {detail}")

    print(sep)
    measured = sum(1 for _, s, _ in results if s == "pass")
    unmeasured = sum(1 for _, s, _ in results if s == "unmeasured")
    failed = sum(1 for _, s, _ in results if s not in ("pass", "unmeasured"))
    total = len(results)
    print(f"  {measured}/{total} أقاليمُ قِيسَت ونجحت | {unmeasured} غيرُ مقيسة | {failed} فاشلة")
    if unmeasured:
        print("  تنبيه: «غير مقيس» ليس نجاحًا — الأرقامُ أعلاه مُقتبَسةٌ من لَقطةٍ مُؤرَّخة،")
        print("  ولا تُقبَلُ دليلًا في بوّابةٍ تشترطُ إثباتًا. هيِّئ AMOS_TRUTH_DB_URL،")
        print("  أو شغِّلْ بـ --require-measured لتفشلَ البوّابةُ عندَ غيابِ القياس.")
    print("=" * 64)


def main(argv=None):
    """Entry point: run all smoke tests and exit with appropriate code."""
    parser = argparse.ArgumentParser(description="بوّابةُ الدخانِ لكلِّ الأقاليم")
    parser.add_argument(
        "--require-measured",
        action="store_true",
        help="افشَلْ إن وُجِدَ إقليمٌ واحدٌ غيرُ مقيسٍ (تشترطُه بوّاباتُ الإثبات D-4/D-7)",
    )
    args = parser.parse_args(argv)

    results, all_pass = run_all()
    print_summary_table(results)
    unmeasured = [d for d, s, _ in results if s == "unmeasured"]

    if not all_pass:
        print("\nSome smoke tests FAILED.")
        return 1
    if unmeasured and args.require_measured:
        print("\nغيرُ مقيسٍ ومطلوبٌ قياسُه: " + ", ".join(unmeasured))
        return 1
    if unmeasured:
        print("\nلا إقليمَ فاشلًا — وبقيَ " + str(len(unmeasured)) + " إقليمًا غيرَ مقيس.")
        return 0
    print("\nAll smoke tests PASSED (measured).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
