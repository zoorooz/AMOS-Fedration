"""الهدف: P14 — تدقيقٌ نهائيٌّ يُطابِقُ المستودعَ بالوثيقة. يقيسُ ولا يُصلِحُ."""

import json
import re
import sys
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
D = ROOT / "docs/audit"
# المادةُ التاسعةُ · 2: المُخرَجُ يُعلِنُ هدفَه في ترويستِه، والمفتاحُ أوّلُ ما يُكتَب.
out: dict[str, object] = {
    "$comment": (
        "الهدف: 21 قياسَ مطابقةٍ بينَ ما يقولُه المستودعُ وما تقولُه الوثيقةُ — "
        "مُخرَجُ tools/audit/final_audit.py (P14). يقيسُ ولا يُصلِح، ولا يُقرَأُ "
        "شهادةَ نجاح. المادةُ التاسعةُ · 2."),
}

# 1) الدَّينُ المقيسُ الآن
INV = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs/audit/measurements/write_inventory_p13.json"
inv = json.loads(INV.read_text(encoding="utf-8"))
s = inv["summary"]
debt = len([x for x in inv["sites"] if x["public"] and not x["guarded"] and not x["closed_legacy"]])
out["debt_summary_field"] = s["non_sovereign_write_operations"]
out["debt_recount"] = debt
out["sovereign"] = s["sovereign_write_operations"]
out["closed_legacy"] = s["closed_legacy_paths"]
out["public"] = s["public_write_operations"]
out["total_sites"] = s["write_sites_total"]

# 2) الأرقامُ المذكورةُ في الوثيقةِ المركزيّة
prog = (D / "SOVEREIGN_MIGRATION_PROGRAM.md").read_text(encoding="utf-8")
out["program_mentions_168"] = prog.count("168")
# صيغتانِ للعلامةِ المؤقّتةِ: عبارةُ P14 ورمزُ P15/P16 — عُدَّتِ الأولى وحدَها
# حتى P16 فكانَ العدُّ أعمى عن الثانية، فوُسِّعَ صريحًا لا صامتًا.
# تُعَدُّ العلامةُ في **خليّةِ جدولٍ** لا في شرحٍ نصّيٍّ يذكرُ الرمزَ: وسَّعْنا العدَّ
# في P16 فعَدَّ ذكرَ الرمزِ في § 8.5 علامةً باقيةً (3 لا 2)، فضُيِّقَ صريحًا.
out["program_placeholders"] = (prog.count("يُسجَّلُ عند الدفع")
                               + len(re.findall(r"\|\s*`PENDING_PUSH`\s*\|", prog)))
out["program_todo_markers"] = len(re.findall(r"TODO|FIXME|XXX|<<<|>>>", prog))

# 3) الأسئلةُ في السجلّ
reg = (D / "SOVEREIGN_DECISION_REGISTER.md").read_text(encoding="utf-8")
qs = sorted({int(m) for m in re.findall(r"##\s+\**Q-(\d+)", reg)})
out["questions_headed"] = qs
out["questions_count"] = len(qs)
out["questions_missing_1_to_max"] = [n for n in range(1, (max(qs) if qs else 0) + 1) if n not in qs]

# 4) وجودُ الوثائقِ المُدَّعاة
claimed = [
    "SOVEREIGN_MIGRATION_PROGRAM.md", "SOVEREIGN_DECISION_REGISTER.md",
    "MIGRATION_DEBT_INVENTORY.md", "STATE_RUNTIME_MIGRATION_ANALYSIS.md",
    "AGENT_IDENTITY_MIGRATION_ANALYSIS.md", "TREASURY_MIGRATION_ANALYSIS.md",
    "JUDICIARY_LEGISLATIVE_MIGRATION_ANALYSIS.md",
    "GOVERNANCE_NESTING_MIGRATION_ANALYSIS.md",
    "ROYAL_SYSTEM_LIFE_MIGRATION_ANALYSIS.md",
    "REMAINING_SURFACES_INVENTORY.md", "STAGE_2B_HANDOFF.md",
    "measurements/README.md", "measurements/treasury_gate_matrix.json",
    "measurements/judicial_gate_matrix.json",
    "evidence/README.md", "evidence/evidence_registry.jsonl",
]
out["missing_docs"] = [c for c in claimed if not (D / c).exists()]

# 5) الأدواتُ المُدَّعاة
tools = [
    "tools/audit/sovereign_write_inventory.py", "tools/audit/treasury_gate_probe.py",
    "tools/audit/judicial_gate_probe.py", "tools/governance/evidence_registry.py",
    "tools/governance/truth_audit.py",
    "tools/audit/final_audit.py",
]
out["missing_tools"] = [t for t in tools if not (ROOT / t).exists()]

# 6) الهاشاتُ المذكورةُ في الوثيقةِ: أموجودةٌ في تاريخِ الفرع؟
hashes = sorted(set(re.findall(r"`([0-9a-f]{7})`", prog)))
log = subprocess.run(["git", "log", "--format=%h", "-n", "400"], cwd=ROOT,
                     capture_output=True, text=True).stdout.split()
out["hashes_in_doc"] = hashes
out["hashes_not_in_history"] = [h for h in hashes if h not in log]

# 7) سلسلةُ الدليلِ: أسليمةٌ ولم تُمَسّ؟
lines = [json.loads(x) for x in (D / "evidence/evidence_registry.jsonl").read_text(
    encoding="utf-8").splitlines() if x.strip()]
out["evidence_entries"] = len(lines)
chain_ok, prev = True, None
for e in lines:
    if prev is not None and e.get("prev_hash") not in (prev, None):
        chain_ok = False
        break
    prev = e.get("hash", prev)
out["evidence_chain_consistent"] = chain_ok

# 8) مساراتُ التجاوزِ: هل بقيَ معامَلُ تجاوزٍ في الكتاباتِ المُهاجَرة؟
migrated = [
    "federal/executive/services/src/amos_federation/services/state_registry/service.py",
    "federal/executive/services/src/amos_federation/services/governance/state_runtime.py",
    "federal/executive/services/src/amos_federation/services/government_services/service.py",
    "federal/executive/services/src/amos_federation/services/governance/factories.py",
]
bad = {}
for m in migrated:
    src = (ROOT / m).read_text(encoding="utf-8")
    hits = [f for f in ("force=", "bypass=", "skip_check=", "unchecked=", "override=") if f in src]
    if hits:
        bad[m] = hits
out["bypass_params_in_migrated"] = bad
out["closed_legacy_functions"] = sorted(
    x["function"] for x in inv["sites"] if x["closed_legacy"]
)

# 9) الأفعالُ العابرةُ للحدِّ بأسمائِها
out["sovereign_sites"] = sorted(
    f"{Path(x['path']).name}::{x['function']}" for x in inv["sites"] if x["guarded"]
)

print(json.dumps(out, ensure_ascii=False, indent=2))
