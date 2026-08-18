"""P7 — قياسُ أحكامِ البوابةِ على الأفعالِ القضائيّةِ والتشريعيّة. قياسٌ لا تقدير."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "federal/executive/services/src"))

from core.constitutional_engine.engine import ConstitutionalEngine  # noqa: E402
from core.constitutional_engine.model import ActionRequest, Branch  # noqa: E402

ACTORS = ["EXECUTIVE", "JUDICIAL", "LEGISLATIVE", "ROYAL"]

# كلُّ عمليّةٍ عامّةٍ مُغيِّرةٍ في خزانةِ الدولةِ، ومرشَّحُ فعلِها الدستوريّ،
# مع الأفعالِ المعجميّةِ المعروفةِ في `TREASURY_ACTIONS` وقائمةِ منعِ القضاء.
CANDIDATES = [
    "adjudicate",
    "issue_ruling",
    "vacate_ruling",
    "admit_evidence",
    "register_judgment",
    "refer_case",
    "admit_case",
    "recuse_judge",
    "create_court",
    "appoint_judge",
    "register_court",
    "set_court_status",
    "set_judge_status",
    "file_case",
    "assign_case",
    "open_hearing",
    "close_case",
    "add_party",
    "add_claim",
    "submit_evidence",
    "set_evidence_status",
    "record_proceeding",
    "record_enforcement",
    "enforce_ruling",
    "pardon",
    "overturn_judicial_ruling",
    "legislate",
    "enact_policy",
    "amend_policy",
    "repeal_policy",
    "suspend_policy",
    "vote",
]

engine = ConstitutionalEngine()
rows = []
for action in CANDIDATES:
    for actor in ACTORS:
        req = ActionRequest(actor=Branch[actor], action=action, target="probe/judiciary")
        try:
            verdict = engine.evaluate(req)
            decision = getattr(verdict, "decision", verdict)
            name = getattr(decision, "value", str(decision))
            rules = []
            for attr in ("violations", "reasons", "findings"):
                value = getattr(verdict, attr, None)
                if value:
                    rules = [
                        getattr(v, "rule_id", None) or getattr(v, "reason", None) or str(v)
                        for v in value
                    ]
                    break
            human = bool(getattr(verdict, "requires_human_approval", False))
            rows.append(
                {
                    "action": action,
                    "actor": actor,
                    "decision": name,
                    "human_gated": human,
                    "rules": rules[:3],
                }
            )
        except Exception as exc:  # noqa: BLE001
            rows.append(
                {
                    "action": action,
                    "actor": actor,
                    "decision": f"EXC:{type(exc).__name__}",
                    "human_gated": False,
                    "rules": [str(exc)[:100]],
                }
            )

OUT = ROOT / "docs/audit/measurements/judicial_gate_matrix.json"
with open(OUT, "w", encoding="utf-8") as fh:
    json.dump(rows, fh, ensure_ascii=False, indent=1)

for row in rows:
    mark = "ALLOW " if "allow" in row["decision"].lower() else "*DENY*"
    gate = " HUMAN" if row["human_gated"] else ""
    print(
        f"{mark} {row['actor']:10s} {row['action']:32s} {row['decision']:10s}{gate} "
        f"{','.join(row['rules'])[:70]}"
    )
