#!/usr/bin/env python3
"""بوابةُ إعادةِ الجردِ بينَ موجاتِ القرارِ البشريّ.

بوابةُ **إجراءٍ** لا بوابةُ سيادة: لا تُخوِّلُ كتابةً ولا تمنعُها، ولا تُنتِجُ دليلًا
سياديًّا، ولا تحلُّ محلَّ `docs/audit/evidence/evidence_registry.jsonl`.

مصادرُ الحقيقة:
  - نصُّ أيِّ قرارٍ وحالتُه → `docs/audit/SOVEREIGN_DECISION_REGISTER.md` (وحدَه).
  - خريطةُ الموجاتِ        → كتلةُ ```decision-waves``` في
    `docs/audit/SOVEREIGN_DECISION_PACKAGE.md` (وحدَها).
  - `measurements/decision_gate_ledger.json` مخزنُ **قياسٍ** فقط: لا نصَّ قرارٍ فيه ولا
    حالةً، وإذا خالفَ السجلَّ فالسجلُّ هو الحاكم.

الاستعمال:
  python tools/audit/decision_gate.py --map              # يُعيدُ توليدَ خريطةِ الموجاتِ المقيسة
  python tools/audit/decision_gate.py --measure          # يقيسُ الدَّينَ الآنَ ولا يكتبُ شيئًا
  python tools/audit/decision_gate.py --record Q-11      # يُسجِّلُ لقطةً منسوبةً إلى قرارٍ أُغلِق
  python tools/audit/decision_gate.py --gate W1          # يفتحُ موجةً أو يسقطُ مُعلِنًا الناقص

رموزُ الخروج: 0 = مرَّ · 1 = سقطَ (ناقصٌ أو انحرافٌ) · 2 = خطأُ استعمال.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "docs/audit"
PACKAGE = AUDIT / "SOVEREIGN_DECISION_PACKAGE.md"
REGISTER = AUDIT / "SOVEREIGN_DECISION_REGISTER.md"
LEDGER = AUDIT / "measurements/decision_gate_ledger.json"
WAVE_MAP = AUDIT / "measurements/decision_wave_map.json"
INVENTORY_TOOL = ROOT / "tools/audit/sovereign_write_inventory.py"

# تقسيمُ الأسطحِ على الموجاتِ — مقيسٌ في الحزمةِ § 1 ومجموعُه الدَّينُ كلُّه.
W1_PATHS = ("federal_judiciary", "governance/federation.py", "national_registry")
W2_PATHS = ("state_treasury", "governance/treasury.py", "national_economy")
W1_EXTRA = {("government_services/service.py", "process_case")}
W2_EXTRA = {("federal_state/service.py", "execute_scoped_disbursement"),
            ("model_gateway/model_layer.py", "log_cost")}


def _fail(msg: str) -> None:
    print(f"سقطتِ البوابة: {msg}")
    sys.exit(1)


def read_waves() -> dict[str, list[str]]:
    """يقرأُ خريطةَ الموجاتِ من كتلةِ الحزمةِ نفسِها — لا نسخةَ ثانيةً في الشيفرة."""
    if not PACKAGE.exists():
        _fail(f"وثيقةُ الحزمةِ غائبة: {PACKAGE.relative_to(ROOT)}")
    m = re.search(r"```decision-waves\n(.*?)```", PACKAGE.read_text(encoding="utf-8"), re.S)
    if not m:
        _fail("كتلةُ `decision-waves` غائبةٌ من وثيقةِ الحزمة")
    waves: dict[str, list[str]] = {}
    for line in m.group(1).strip().splitlines():
        if not line.strip():
            continue
        wave, _, ids = line.partition(":")
        waves[wave.strip()] = [q.strip() for q in ids.split(",") if q.strip()]
    return waves


def registered_questions() -> set[str]:
    """كلُّ سؤالٍ له عنوانٌ في السجلّ — للتحقُّقِ أنَّ الحزمةَ لا تخترعُ سؤالًا."""
    text = REGISTER.read_text(encoding="utf-8")
    return {f"Q-{n}" for n in re.findall(r"^##\s+\**Q-(\d+)", text, re.M)}


def measure() -> dict:
    """يُشغِّلُ أداةَ الجردِ ويستخرجُ الأرقامَ — لا رقمَ من ذاكرةٍ ولا من وثيقة."""
    out = AUDIT / "measurements/.decision_gate_probe.json"
    proc = subprocess.run(
        [sys.executable, str(INVENTORY_TOOL), "--json", str(out)],
        cwd=ROOT, capture_output=True, text=True,
    )
    if proc.returncode != 0 or not out.exists():
        _fail(f"أداةُ الجردِ لم تُكمِلْ: {proc.stderr.strip()[:400]}")
    inv = json.loads(out.read_text(encoding="utf-8"))
    out.unlink(missing_ok=True)
    sites = inv["sites"]
    debt = [s for s in sites if s["public"] and not s["guarded"] and not s["closed_legacy"]]
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True).stdout.strip()
    return {
        "debt": len(debt),
        "sovereign": sum(1 for s in sites if s["guarded"]),
        "closed_legacy": sum(1 for s in sites if s["closed_legacy"]),
        "write_sites_total": len(sites),
        "git_head": head,
        "waves": wave_counts(debt),
    }


def wave_counts(debt: list[dict]) -> dict[str, int]:
    counts = {"W1": 0, "W2": 0, "W3": 0}
    for s in debt:
        path, func = s["path"], s["function"]
        tail = lambda pairs: any(p in path and func == f for p, f in pairs)  # noqa: E731
        if any(p in path for p in W1_PATHS) or tail(W1_EXTRA):
            counts["W1"] += 1
        elif any(p in path for p in W2_PATHS) or tail(W2_EXTRA):
            counts["W2"] += 1
        else:
            counts["W3"] += 1
    return counts


def load_ledger() -> list[dict]:
    if not LEDGER.exists():
        return []
    return json.loads(LEDGER.read_text(encoding="utf-8"))["snapshots"]


def save_ledger(snapshots: list[dict]) -> None:
    LEDGER.write_text(json.dumps({
        "note": ("مخزنُ قياسٍ لا مصدرُ حقيقةٍ للقرارات. لا نصَّ قرارٍ فيه ولا حالةً. "
                 "مصدرُ الحقيقةِ SOVEREIGN_DECISION_REGISTER.md، وإن خالفَه فالسجلُّ الحاكم."),
        "snapshots": snapshots,
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def cmd_map() -> None:
    m = measure()
    WAVE_MAP.write_text(json.dumps({
        "note": "تقسيمُ الدَّينِ على موجاتِ القرارِ — مجموعُه الدَّينُ كلُّه بلا تكرار.",
        "debt": m["debt"], "waves": m["waves"], "git_head": m["git_head"],
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    total = sum(m["waves"].values())
    print(json.dumps(m, ensure_ascii=False, indent=1))
    if total != m["debt"]:
        _fail(f"التقسيمُ ناقصٌ: مجموعُ الموجاتِ {total} والدَّينُ {m['debt']}")
    print(f"التقسيمُ تامّ: {' + '.join(str(v) for v in m['waves'].values())} = {m['debt']}")


def cmd_measure() -> None:
    print(json.dumps(measure(), ensure_ascii=False, indent=1))


def cmd_record(decision: str) -> None:
    waves = read_waves()
    known = {q for ids in waves.values() for q in ids}
    if decision not in known:
        _fail(f"{decision} ليسَ في خريطةِ موجاتِ الحزمة")
    if decision not in registered_questions():
        _fail(f"{decision} لا عنوانَ له في السجلّ — لا تُسجَّلُ لقطةٌ لسؤالٍ غيرِ مُدوَّن")
    snapshots = load_ledger()
    if any(s["decision"] == decision for s in snapshots):
        _fail(f"{decision} له لقطةٌ مسجَّلةٌ سابقًا — لا تُكتَبُ لقطةٌ فوقَ أخرى")
    snap = measure()
    snap["decision"] = decision
    snap["recorded_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    snapshots.append(snap)
    save_ledger(snapshots)
    print(f"سُجِّلتْ لقطةُ {decision}: الدَّينُ {snap['debt']} · العابراتُ "
          f"{snap['sovereign']} · الرأسُ {snap['git_head']}")
    print("تذكيرٌ: القرارُ نفسُه يُدوَّنُ في SOVEREIGN_DECISION_REGISTER.md لا هنا.")


def cmd_gate(wave: str) -> None:
    waves = read_waves()
    if wave not in waves:
        print(f"موجةٌ غيرُ معروفة: {wave} — المعروفُ {', '.join(waves)}")
        sys.exit(2)
    snapshots = load_ledger()
    recorded = {s["decision"] for s in snapshots}
    order = list(waves)
    missing_prior: list[str] = []
    for earlier in order[:order.index(wave)]:
        missing_prior += [q for q in waves[earlier] if q not in recorded]
    missing_own = [q for q in waves[wave] if q not in recorded]
    now = measure()

    print(f"الموجة {wave}: الدَّينُ المقيسُ الآن {now['debt']} · الرأسُ {now['git_head']}")
    if missing_prior:
        _fail("موجةٌ سابقةٌ لم تُغلَقْ — قراراتٌ بلا لقطةٍ: " + " · ".join(missing_prior))
    if missing_own:
        _fail(f"قراراتُ {wave} بلا لقطةٍ مسجَّلة: " + " · ".join(missing_own))
    if not snapshots:
        _fail("لا لقطةَ واحدةً في السجلّ — لا تُفتَحُ موجةٌ بلا جردٍ مسجَّل")
    last = snapshots[-1]
    if last["debt"] != now["debt"]:
        _fail(f"انحرافٌ صامتٌ: آخرُ لقطةٍ ({last['decision']}) دَينُها {last['debt']} "
              f"والمقيسُ الآنَ {now['debt']} — يُعادُ الجردُ وتُسجَّلُ لقطةٌ قبلَ الفتح")
    print(f"مرَّتِ البوابة: {wave} مفتوحةٌ · آخرُ لقطةٍ {last['decision']} "
          f"عند {last['recorded_at']}")


def main() -> None:
    ap = argparse.ArgumentParser(description="بوابةُ إعادةِ الجردِ بينَ موجاتِ القرار")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--map", action="store_true", help="إعادةُ توليدِ خريطةِ الموجاتِ المقيسة")
    g.add_argument("--measure", action="store_true", help="قياسٌ بلا كتابة")
    g.add_argument("--record", metavar="Q-NN", help="تسجيلُ لقطةٍ لقرارٍ أُغلِق")
    g.add_argument("--gate", metavar="Wn", help="فتحُ موجةٍ أو السقوطُ مُعلِنًا الناقص")
    a = ap.parse_args()
    if a.map:
        cmd_map()
    elif a.measure:
        cmd_measure()
    elif a.record:
        cmd_record(a.record)
    else:
        cmd_gate(a.gate)


if __name__ == "__main__":
    main()
