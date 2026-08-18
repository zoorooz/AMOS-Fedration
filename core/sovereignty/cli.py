"""الهدف: واجهة سطر أوامر لنواة السيادة — تنصيب التاج وفحص السيادة وبوابات CI.

المالك: core/sovereignty/ — التاج
تاريخ الإنشاء: 2026-08-16
تاريخ آخر تعديل: 2026-08-16

رموز الخروج: 0 = سليم/مسموح · 2 = مرفوض دستوريًا · 1 = فشل بوابة أو خطأ تشغيلي.
"""

from __future__ import annotations

import argparse
import inspect
import json
import sys
from pathlib import Path

from core.constitutional_engine.model import ActionRequest, Branch
from core.sovereignty.authority import (
    SUBORDINATE_LAYERS,
    AuthorityLayer,
    SovereigntyModelError,
    assert_no_layer_above_crown,
    supreme_layer,
)
from core.sovereignty.crown import (
    ROOT_EXTERNAL_HUMAN,
    CrownError,
    crown_is_provisioned,
    enroll_crown,
    issue_enrollment_challenge,
    load_crown,
    provision_crown,
)
from core.sovereignty.gateways import SUBORDINATE_GATEWAYS
from core.sovereignty.gateway import (
    FORBIDDEN_BYPASS_PARAMS,
    RoyalImpersonation,
    SovereignGateway,
    SovereigntyViolation,
)
from core.sovereignty.prerogatives import (
    FEDERALISM_BYPASS_ACTIONS,
    IMMUNE_CLAUSES,
    ROYAL_AUTHORITY_EROSION_ACTIONS,
    ROYAL_EXCLUSIVE_ACTIONS,
)

_ARTICLE_010 = (
    Path(__file__).resolve().parents[2]
    / "core"
    / "constitution"
    / "articles"
    / "010-royal-sovereignty.md"
)


def _cmd_provision_crown(args: argparse.Namespace) -> int:
    try:
        crown = provision_crown(Path(args.out), holder=args.holder)
    except CrownError as exc:
        print(f"[PROVISION] ✗ {exc}", file=sys.stderr)
        return 1
    print(f"[PROVISION] ✓ نُصِّب التاج — المفتاح «{crown.key_id}» لحامله «{crown.holder}».")
    print("[PROVISION]   المفتاح العام نُشر في royal/crown/CROWN_KEYS.json")
    print(f"[PROVISION]   المفتاح الخاص كُتب في {args.out} بصلاحية 600.")
    print("[PROVISION] ⚠ انقل المفتاح الخاص إلى حرز الملك واحذفه من هذا الجهاز.")
    print("[PROVISION] ⚠ لا نسخة منه في المستودع ولا في أي نظام تشغيلي للدولة.")
    return 0


def _cmd_crown_challenge(args: argparse.Namespace) -> int:
    """أصدِر تحدّيًا يوقّعه الملكُ على جهازِه هو، خارجَ الدولة."""
    try:
        challenge = issue_enrollment_challenge(ttl_seconds=args.ttl)
    except CrownError as exc:
        print(f"[CHALLENGE] ✗ {exc}", file=sys.stderr)
        return 1
    print(f"[CHALLENGE] ✓ التحدّي «{challenge.challenge_id}» صالحٌ حتى {challenge.expires_at}")
    print(f"[CHALLENGE]   البايتات الموقَّعة (hex): {challenge.message.hex()}")
    print("[CHALLENGE]   وقّعها بمفتاحك خارج هذه الدولة، ثمّ نسِّب مفتاحك العام:")
    print("[CHALLENGE]   python -m core.sovereignty.cli crown-enroll "
          "--public-key <hex> --signature <hex>")
    return 0


def _cmd_crown_enroll(args: argparse.Namespace) -> int:
    """نسِّب المفتاحَ العامَّ وحدَه بعد إثباتِ الحيازة."""
    try:
        crown = enroll_crown(
            args.public_key,
            args.signature,
            holder=args.holder,
            keystore_kind=args.keystore_kind,
            witnesses=tuple(args.witness or ()),
        )
    except CrownError as exc:
        print(f"[ENROLL] ✗ {exc}", file=sys.stderr)
        return 1
    print(f"[ENROLL] ✓ نُسِّب جذرٌ بشريٌّ خارجيّ — المفتاح «{crown.key_id}» "
          f"لحامله «{crown.holder}».")
    print("[ENROLL]   المفتاح الخاص لم يدخل هذه الدولةَ قطُّ ولم تره.")
    return 0


def _cmd_crown_status(_args: argparse.Namespace) -> int:
    if not crown_is_provisioned():
        print("[CROWN] التاج غير مُنصَّب — الاختصاص الملكي الحصري مُجمَّد لا منقول.")
        print("[CROWN] التنصيب: python -m core.sovereignty.cli provision-crown --out <مسار خارج المستودع>")
        return 0
    crown = load_crown()
    print(f"[CROWN] ✓ مُنصَّب — المفتاح «{crown.key_id}» · الحامل «{crown.holder}»")
    print(f"[CROWN]   الخوارزمية Ed25519 · التنصيب {crown.provisioned_at}")
    print(f"[CROWN]   أصل الجذر: {crown.root_origin}")
    if not crown.is_external_human_root:
        print("[CROWN] ⚠ الجذرُ ولّدتْه الدولةُ نفسُها — ليس جذرًا بشريًّا. "
              "الدولةُ رأت المفتاحَ الخاصَّ لحظةَ توليدِه.")
    return 0


# قواعد إثبات الأصالة المأذونة — تتوسّع بمرسوم ملكي لا بتعديل برمجي
_AUTHENTICITY_RULES = frozenset({"R-010-3", "R-010-5"})


def _cmd_sovereignty_check(_args: argparse.Namespace) -> int:
    """بوابة CI: هل السيادة الملكية ما زالت محروسة بنيويًا؟"""
    failures: list[str] = []

    if not _ARTICLE_010.exists():
        failures.append("المادة العاشرة مفقودة من الدستور.")

    if crown_is_provisioned():
        crown = load_crown()
        if crown.root_origin != ROOT_EXTERNAL_HUMAN:
            failures.append(
                f"جذرُ الدولةِ مُنصَّبٌ بأصلٍ «{crown.root_origin}» لا "
                f"«{ROOT_EXTERNAL_HUMAN}»: الدولةُ ولّدت مفتاحَ الملك فرأتْه. "
                "المسارُ السياديُّ هو crown-enroll."
            )

    gateway = SovereignGateway()
    if gateway.engine.unguarded_articles():
        failures.append(
            f"مواد بلا حراسة: {', '.join(gateway.engine.unguarded_articles())}"
        )

    coverage = gateway.engine.coverage()
    royal_rules = coverage.get("A010", 0)
    if royal_rules < 7:
        failures.append(f"قواعد المادة العاشرة {royal_rules} والحد الأدنى 7.")

    # لا راية تجاوز في البوابة — تُفحَص من توقيع الدوال نفسها
    for name in ("execute", "review", "__init__"):
        params = set(inspect.signature(getattr(SovereignGateway, name)).parameters)
        leaked = params & FORBIDDEN_BYPASS_PARAMS
        if leaked:
            failures.append(f"SovereignGateway.{name} يقبل راية تجاوز: {sorted(leaked)}")

    for expected in ("royal_sovereignty", "royal_exclusive_authority", "royal_authority_immunity"):
        if expected not in IMMUNE_CLAUSES:
            failures.append(f"النص «{expected}» فُقد من قائمة النصوص المحصَّنة.")

    # ── E2.1: لا طبقة فوق التاج ────────────────────────────────────────────
    try:
        assert_no_layer_above_crown()
    except SovereigntyModelError as exc:
        failures.append(f"نموذج السلطة مختل: {exc}")

    if supreme_layer() is not AuthorityLayer.CROWN:
        failures.append(
            f"الطبقة العليا «{supreme_layer().name}» لا التاج. لا سلطة فوق الملك."
        )

    # لا قاعدة دستورية تمنع التاج — غير قواعد إثبات الأصالة
    binding = [r.rule_id for r in gateway.engine.rules if r.can_veto_sovereign]
    if binding:
        failures.append(
            f"قواعد تملك نقض قرار التاج: {sorted(binding)} — لا نقض يعلو على التاج."
        )

    # قواعد الأصالة محصورة بالاسم: لا يُدسّ نقض موضوعي بثوب «أصالة»
    authenticity = {r.rule_id for r in gateway.engine.rules if r.guards_royal_authenticity}
    if authenticity != _AUTHENTICITY_RULES:
        failures.append(
            f"قواعد الأصالة {sorted(authenticity)} تخالف المحصور "
            f"{sorted(_AUTHENTICITY_RULES)} — كل إضافة هنا تقتضي مرسومًا ملكيًا."
        )

    # مسار التنفيذ السيادي بلا منع دستوري — يُفحص من المصدر نفسه
    sovereign_src = inspect.getsource(SovereignGateway._execute_sovereign)
    for forbidden in ("SovereigntyViolation", "ConstitutionalViolation"):
        if f"raise {forbidden}" in sovereign_src:
            failures.append(
                f"مسار التنفيذ السيادي يرفع {forbidden} — هذا نقض لقرار التاج."
            )

    # ولا شرط مخفي من نوع «إن كان ملكًا فاسمح» في مسار التابعين
    subordinate_src = inspect.getsource(SovereignGateway._execute_subordinate)
    if "ROYAL" in subordinate_src or "CROWN" in subordinate_src:
        failures.append(
            "مسار التابعين يذكر التاج — يُحتمل استثناء مدسوس لا مسارًا صريحًا."
        )

    # البوابات التابعة لا تترقّى
    for gw_cls in SUBORDINATE_GATEWAYS:
        if gw_cls.layer.is_sovereign:
            failures.append(f"البوابة التابعة {gw_cls.__name__} تدّعي الطبقة السيادية.")

    if failures:
        for f in failures:
            print(f"[SOVEREIGNTY] ✗ {f}", file=sys.stderr)
        return 1

    print(f"[SOVEREIGNTY] ✓ المادة العاشرة سارية ومحروسة بـ{royal_rules} قاعدة تنفيذية.")
    print(f"[SOVEREIGNTY] ✓ {len(ROYAL_EXCLUSIVE_ACTIONS)} اختصاصًا ملكيًا حصريًا محميًا.")
    print(f"[SOVEREIGNTY] ✓ {len(ROYAL_AUTHORITY_EROSION_ACTIONS)} فعل تآكل للسلطة مرفوض من كل طرف.")
    print(f"[SOVEREIGNTY] ✓ {len(FEDERALISM_BYPASS_ACTIONS)} فعل تجاوز للفدرالية مرفوض.")
    print(
        f"[SOVEREIGNTY] ✓ {len(IMMUNE_CLAUSES)} نصًا محصَّنًا لا يُعدَّل من أي طرف تابع "
        "(المرسوم الملكي يمسُّه ويُسجَّل حدثًا حرجًا — المادة العاشرة · 3 · 4)."
    )
    print("[SOVEREIGNTY] ✓ البوابة السيادية بلا راية تجاوز واحدة.")
    print(
        f"[SOVEREIGNTY] ✓ الطبقة العليا هي التاج، ودونه من الطبقات التابعة "
        f"{len(SUBORDINATE_LAYERS)}، ولا طبقة فوقه."
    )
    print(
        f"[SOVEREIGNTY] ✓ لا قاعدة تملك نقض قرار التاج من أصل "
        f"{len(gateway.engine.rules)} قاعدة، ومساره بلا منع دستوري."
    )
    print(
        f"[SOVEREIGNTY] ✓ {len(SUBORDINATE_GATEWAYS)} بوابة تابعة مُثبَّتة على طبقتها لا تترقّى."
    )
    print(f"[SOVEREIGNTY]   حالة التاج: {gateway.crown_status()}")
    return 0


def _cmd_gate(args: argparse.Namespace) -> int:
    """تشغيل فعل عبر البوابة السيادية — بلا مرسوم، لعرض المنع."""
    gateway = SovereignGateway()
    request = ActionRequest(
        actor=Branch(args.actor),
        action=args.action,
        target=args.target or "",
    )
    try:
        gateway.execute(request, lambda: "EXECUTED")
    except RoyalImpersonation as exc:
        # انتحال صفة ملكية: ليس نقضًا للملك بل نفيًا لملكية الأمر
        print(f"[GATEWAY] REJECT — إنكار أصالة (A010 · 3 · 2): {exc.reason}")
        print(f"[GATEWAY] حدث أمني مُسجَّل: {exc.event_kind.value}")
        print(
            "[GATEWAY] وهذا نفيٌ لملكية الأمر لا نقضٌ للملك: المرفوض منتحِل لا ملك."
        )
        print("[GATEWAY] لم يُستدعَ المُنفِّذ. الفعل لم يقع.")
        return 2
    except SovereigntyViolation as exc:
        print(exc.verdict.explain())
        print("\n[GATEWAY] لم يُستدعَ المُنفِّذ. الفعل لم يقع.")
        return 2
    record = gateway.records[-1]
    if record.sovereign:
        print(
            f"[GATEWAY] ALLOW — مسار سيادي. ملاحظات دستورية مُسجَّلة لا مانعة: "
            f"{', '.join(record.advisory_articles) or 'لا شيء'}"
        )
    else:
        print("[GATEWAY] ALLOW — نُفِّذ الفعل.")
    return 0


def _cmd_prerogatives(_args: argparse.Namespace) -> int:
    print(
        json.dumps(
            {
                "royal_exclusive_actions": sorted(ROYAL_EXCLUSIVE_ACTIONS),
                "royal_authority_erosion_actions": sorted(ROYAL_AUTHORITY_EROSION_ACTIONS),
                "federalism_bypass_actions": sorted(FEDERALISM_BYPASS_ACTIONS),
                "immune_clauses": sorted(IMMUNE_CLAUSES),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m core.sovereignty.cli",
        description="نواة السيادة — السيادة الملكية كقوة نافذة (E2)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("provision-crown", help="مراسم تنصيب التاج (توليد مفتاح الملك)")
    p.add_argument("--out", required=True, help="مسار المفتاح الخاص — خارج المستودع إلزامًا")
    p.add_argument("--holder", default="الملك", help="حامل التاج")
    p.set_defaults(func=_cmd_provision_crown)

    p = sub.add_parser("crown-challenge",
                       help="أصدِر تحدّي تنسيب يوقّعه الملك خارج الدولة")
    p.add_argument("--ttl", type=int, default=3600, help="مدّة الصلاحية بالثواني")
    p.set_defaults(func=_cmd_crown_challenge)

    p = sub.add_parser("crown-enroll",
                       help="نسِّب المفتاح العام للملك بعد إثبات الحيازة")
    p.add_argument("--public-key", required=True, help="المفتاح العام Ed25519 (hex)")
    p.add_argument("--signature", required=True, help="توقيع التحدّي (hex)")
    p.add_argument("--holder", default="الملك", help="حامل التاج")
    p.add_argument("--keystore-kind", default="offline_human_device",
                   help="بيئة التوقيع كما يُقرّها الملك")
    p.add_argument("--witness", action="append", help="شاهد على المراسم (يتكرّر)")
    p.set_defaults(func=_cmd_crown_enroll)

    p = sub.add_parser("crown-status", help="حالة التاج")
    p.set_defaults(func=_cmd_crown_status)

    p = sub.add_parser("sovereignty-check", help="بوابة CI: حراسة السيادة الملكية")
    p.set_defaults(func=_cmd_sovereignty_check)

    p = sub.add_parser("gate", help="تشغيل فعل عبر البوابة السيادية")
    p.add_argument("--actor", required=True, choices=[b.value for b in Branch])
    p.add_argument("--action", required=True)
    p.add_argument("--target", default="")
    p.set_defaults(func=_cmd_gate)

    p = sub.add_parser("prerogatives", help="طبع مفردات الاختصاص والحصانة")
    p.set_defaults(func=_cmd_prerogatives)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
