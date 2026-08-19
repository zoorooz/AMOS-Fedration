"""الهدف: P6-A — قياسُ أحكامِ البوابةِ على أفعالِ المالِ المرشَّحة. قياسٌ لا تقدير."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "federal/executive/services/src"))

from core.constitutional_engine.engine import ConstitutionalEngine  # noqa: E402
from core.constitutional_engine.model import ActionRequest, Branch  # noqa: E402

ACTORS = ["EXECUTIVE", "TREASURY", "ROYAL"]

# كلُّ عمليّةٍ عامّةٍ مُغيِّرةٍ في خزانةِ الدولةِ، ومرشَّحُ فعلِها الدستوريّ،
# مع الأفعالِ المعجميّةِ المعروفةِ في `TREASURY_ACTIONS` وقائمةِ منعِ القضاء.
CANDIDATES = [
    "allocate_budget",
    "issue_tokens",
    "allocate_resources",
    "book_expense",
    "disburse_funds",
    "transfer_treasury",
    "treasury.establish",
    "treasury.account.open",
    "treasury.budget.create",
    "treasury.allocate",
    "treasury.funding.post",
    "treasury.disburse",
    "treasury.decision.disburse",
    "treasury.transaction.reverse",
    # الاقتصادُ المركَّبُ يمسُّ الميزانيّاتَ نفسَها
    "economy.expenditure.authorize",
    "economy.transfer.execute",
    "economy.procurement.award",
    # اقتصادُ الوكلاءِ (amos-credit) في governance/treasury
    "reward_task_completion",
    "charge_model_invoke",
    "run_economic_cycle",
]

engine = ConstitutionalEngine()
rows = []
for action in CANDIDATES:
    for actor in ACTORS:
        req = ActionRequest(actor=Branch[actor], action=action, target="probe/treasury")
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

OUT = ROOT / "docs/audit/measurements/treasury_gate_matrix.json"
# المادةُ التاسعةُ · 2: المُخرَجُ يُعلِنُ هدفَه في ترويستِه. وُضِعَ الصَّفُّ تحتَ
# مفتاحِ rows لأنَّ قائمةً عليا لا تحمِلُ ترويسةً؛ والقيمُ لم تُمَسّ.
with open(OUT, "w", encoding="utf-8") as fh:
    json.dump({
        "$comment": (
            "الهدف: حكمُ البوابةِ الدستوريّةِ على أفعالِ المالِ المُرشَّحةِ × الفاعلين — "
            "مُخرَجُ tools/audit/treasury_gate_probe.py (P6-A). قياسٌ لا تقدير، "
            "وليسَ دليلًا سياديًّا ولا نصَّ قرار. المادةُ التاسعةُ · 2."),
        "rows": rows,
    }, fh, ensure_ascii=False, indent=1)

for row in rows:
    mark = "ALLOW " if "allow" in row["decision"].lower() else "*DENY*"
    gate = " HUMAN" if row["human_gated"] else ""
    print(
        f"{mark} {row['actor']:10s} {row['action']:32s} {row['decision']:10s}{gate} "
        f"{','.join(row['rules'])[:70]}"
    )
