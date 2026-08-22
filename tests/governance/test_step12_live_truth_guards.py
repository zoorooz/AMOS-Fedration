# -*- coding: utf-8 -*-
"""حرّاسُ الخطوةِ 12 (T3.1) — إثباتُ أنَّ حرّاسَ الأقاليمِ تقيسُ ولا تقتبس.

الهدف: منعُ رجوعِ المخالفةِ التي أُزيلَت في W-025. الاختباراتُ أدناه تُثبِتُ ثلاثةَ
       أشياءَ بالقياسِ لا بالدعوى:
         (١) لا ثابتَ حقيقةٍ على مستوى الوحدةِ في أيِّ حارسِ إقليم — بالقاعدةِ
             نفسِها التي يستعملُها `truth_audit.py` (لا بنسخةٍ منها).
         (٢) بلا مصدرٍ مُهيَّأٍ: الحالةُ `unmeasured` لا `pass`، ومعها سببٌ وتأريخُ
             اللَقطةِ المُقتبَسة.
         (٣) بمصدرٍ مُهيَّأٍ: الأرقامُ تتغيّرُ بتغيُّرِ قاعدةِ البياناتِ (اختبارُ تحوير) —
             فلو عادَ أحدٌ إلى الثوابتِ لسقطَ هذا الاختبار.
النطاق: حرّاسُ الأقاليمِ العشرةُ المربوطةُ بقاعدةِ البيانات، ومشغّلُ الدخان،
       واللَقطةُ المُؤرَّخة، وانحرافُ سجلِّ الأدوات.
المالك: tests/governance
تاريخ الإنشاء: 2026-08-22
تاريخ آخر تعديل: 2026-08-22
"""

from __future__ import annotations

import ast
import importlib
import json
import re
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.audit.live_truth import (  # noqa: E402
    ENV_CANDIDATES,
    SNAPSHOT_PATH,
    SourceNotConfigured,
    check_domain,
    measure_tables,
)

# (اسمُ الإقليم, مسارُ الوحدة, ملفُّ الحارس)
DOMAIN_GUARDS = [
    ("tools", "tools.stubs.registry_check", "tools/stubs/registry_check.py"),
    ("agents", "agents.stubs.registry_check", "agents/stubs/registry_check.py"),
    ("institutions", "institutions.stubs.registry_check", "institutions/stubs/registry_check.py"),
    ("royal", "royal.stubs.guard_check", "royal/stubs/guard_check.py"),
    ("ops", "ops.stubs.audit_check", "ops/stubs/audit_check.py"),
    ("federal", "federal.stubs.treasury_check", "federal/stubs/treasury_check.py"),
    ("core", "core.stubs.memory_check", "core/stubs/memory_check.py"),
    ("runtime", "runtime.stubs.task_event_check", "runtime/stubs/task_event_check.py"),
    ("interfaces", "interfaces.stubs.registry_check", "interfaces/stubs/registry_check.py"),
    ("states", "states.stubs.policy_check", "states/stubs/policy_check.py"),
]

MEASURED_TABLES = (
    "tools", "agent_population", "agents", "institutions", "royal_guards", "king_decrees",
    "audit_entries", "treasury_transactions", "treasury_budgets", "treasury_reports",
    "executive_roles", "memories", "experiences", "tasks", "event_store",
    "interface_registry", "legislations", "compliance_reports",
)


def _clear_source(monkeypatch):
    for key in ENV_CANDIDATES:
        monkeypatch.delenv(key, raising=False)


def _seed_sqlite(path: Path, rows: dict[str, int]) -> str:
    with sqlite3.connect(path) as conn:
        for table in MEASURED_TABLES:
            conn.execute(f'create table if not exists "{table}" (id integer primary key)')
            conn.execute(f'delete from "{table}"')
            for i in range(rows.get(table, 0)):
                conn.execute(f'insert into "{table}" (id) values ({i + 1})')
        conn.commit()
    return f"sqlite:///{path}"


# ---------------------------------------------------------------------------
# (١) لا ثوابتَ حقيقةٍ في الحرّاس — بقاعدةِ محرّكِ التدقيقِ نفسِه
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", [g[2] for g in DOMAIN_GUARDS])
def test_guard_has_no_module_level_truth_constant(path):
    """القاعدةُ مُستوردةٌ من `truth_audit` حتى لا يتباعدَ الحارسُ عن الكاشف."""
    audit = importlib.import_module("tools.governance.truth_audit")
    hint = audit.TRUTH_CONSTANT_HINT

    tree = ast.parse((REPO_ROOT / path).read_text(encoding="utf-8"))
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or getattr(node, "col_offset", 1) != 0:
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name) or not target.id.isupper():
                continue
            if not hint.search(target.id):
                continue
            if isinstance(node.value, (ast.List, ast.Dict, ast.Tuple, ast.Set)):
                offenders.append(target.id)
            elif isinstance(node.value, ast.Constant) and isinstance(node.value.value, (int, float)):
                offenders.append(target.id)
    assert not offenders, f"{path} عاد يحملُ ثوابتَ حقيقة: {offenders}"


@pytest.mark.parametrize("path", [g[2] for g in DOMAIN_GUARDS])
def test_guard_delegates_to_live_measurement(path):
    """كلُّ حارسٍ يمرُّ عبرَ طريقِ القياسِ الواحد — لا طريقَ خاصًّا يتجاوزُه."""
    text = (REPO_ROOT / path).read_text(encoding="utf-8")
    assert "from tools.audit.live_truth import check_domain" in text
    assert "check_domain(" in text


# ---------------------------------------------------------------------------
# (٢) بلا مصدرٍ مُهيَّأ: غيرُ مقيس — وليس ناجحًا
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("domain", "module_path", "_path"), DOMAIN_GUARDS)
def test_unconfigured_source_is_unmeasured_not_pass(monkeypatch, domain, module_path, _path):
    _clear_source(monkeypatch)
    module = importlib.import_module(module_path)
    result = module.check()
    assert result["status"] == "unmeasured", result
    assert result["status"] != "pass"
    assert result["domain"] == domain
    assert result["reason"], "غيابُ المصدرِ يجبُ أن يُعلَنَ بسببٍ مكتوب"
    assert str(result["source"]).startswith("snapshot:")
    assert result["snapshot_measured_at"], "الاقتباسُ بلا تأريخٍ ممنوع"


def test_source_not_configured_is_raised_not_swallowed(monkeypatch):
    _clear_source(monkeypatch)
    with pytest.raises(SourceNotConfigured):
        measure_tables(["tools"])


# ---------------------------------------------------------------------------
# (٣) بمصدرٍ مُهيَّأ: الأرقامُ من القياس — اختبارُ تحوير
# ---------------------------------------------------------------------------


def test_measurement_tracks_the_database(monkeypatch, tmp_path):
    """تحويرٌ: إضافةُ صفٍّ واحدٍ في قاعدةِ البياناتِ يجبُ أن تُغيّرَ الرقمَ المُبلَّغ."""
    db = tmp_path / "truth.db"
    url = _seed_sqlite(db, {"tools": 3, "agent_population": 7, "memories": 2})
    monkeypatch.setenv("AMOS_TRUTH_DB_URL", url)

    first = importlib.import_module("tools.stubs.registry_check").check()
    assert first["status"] == "pass"
    assert first["source"].startswith("live:")
    assert first["count"] == 3
    assert first["measured_at"]

    with sqlite3.connect(db) as conn:
        conn.execute('insert into "tools" (id) values (99)')
        conn.commit()

    second = importlib.import_module("tools.stubs.registry_check").check()
    assert second["count"] == 4, "الرقمُ لم يتبعِ القياس — عودةٌ إلى الثوابت"


def test_agents_guard_reports_population_not_a_constant(monkeypatch, tmp_path):
    db = tmp_path / "truth.db"
    url = _seed_sqlite(db, {"agent_population": 12, "agents": 4})
    monkeypatch.setenv("AMOS_TRUTH_DB_URL", url)
    result = importlib.import_module("agents.stubs.registry_check").check()
    assert result["status"] == "pass"
    assert result["count"] == 12
    assert result["identities"] == 4


def test_missing_table_is_declared_failure_not_pass(monkeypatch, tmp_path):
    """المصدرُ مُهيَّأٌ وفشلَ القياس: الحالةُ `fail` بسببٍ منصوص — لا `pass` ولا صمت."""
    db = tmp_path / "empty.db"
    sqlite3.connect(db).close()
    monkeypatch.setenv("AMOS_TRUTH_DB_URL", f"sqlite:///{db}")
    result = check_domain("tools", {"count": "tools"})
    assert result["status"] == "fail"
    assert result["reason"]


def test_table_name_is_validated_before_query(monkeypatch, tmp_path):
    db = tmp_path / "truth.db"
    monkeypatch.setenv("AMOS_TRUTH_DB_URL", f"sqlite:///{db}")
    with pytest.raises(ValueError):
        measure_tables(["tools; drop table tools"])


# ---------------------------------------------------------------------------
# (٤) مشغّلُ الدخان: «غير مقيس» مرئيٌّ، و`--require-measured` يفشل
# ---------------------------------------------------------------------------


def _run_smoke(args, env_extra=None):
    import os

    env = {k: v for k, v in os.environ.items() if k not in ENV_CANDIDATES}
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "tests" / "smoke" / "run_smoke_tests.py"), *args],
        capture_output=True, text=True, env=env, cwd=str(REPO_ROOT), check=False,
    )


def test_smoke_runner_marks_unmeasured_and_warns():
    proc = _run_smoke([])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "UNMEASURED" in proc.stdout
    assert "«غير مقيس» ليس نجاحًا" in proc.stdout
    assert "PASSED" not in proc.stdout.split("======")[-1] or "غيرَ مقيس" in proc.stdout


def test_smoke_runner_require_measured_fails_without_source():
    proc = _run_smoke(["--require-measured"])
    assert proc.returncode == 1, proc.stdout


def test_smoke_runner_passes_when_measured(tmp_path):
    db = tmp_path / "truth.db"
    url = _seed_sqlite(db, {"tools": 1})
    proc = _run_smoke(["--require-measured"], {"AMOS_TRUTH_DB_URL": url})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "UNMEASURED" not in proc.stdout
    assert "source=live:sqlite" in proc.stdout


# ---------------------------------------------------------------------------
# (٥) اللَقطةُ المُؤرَّخة: مصدرُها وتأريخُها مُعلَنان
# ---------------------------------------------------------------------------


def test_snapshot_declares_purpose_source_and_date():
    data = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    assert "الهدف" in data["$comment"]
    assert data["source"]["kind"]
    assert data["measured_at"]
    datetime.fromisoformat(data["measured_at"])
    assert data["method"]["row_counts"].lower().startswith("select")


def test_snapshot_covers_every_table_the_guards_measure():
    data = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    missing = [t for t in MEASURED_TABLES if t not in data["row_counts"]]
    assert not missing, f"جداولُ يقيسُها الحرّاسُ ولا لَقطةَ لها: {missing}"


# ---------------------------------------------------------------------------
# (٦) انحرافُ سجلِّ الأدوات: الوثيقةُ مقابلَ الجدولِ الحيّ (بندُ القرار Q-33)
# ---------------------------------------------------------------------------


def _yaml_registry_counts() -> dict[str, int]:
    text = (REPO_ROOT / "tools" / "registry" / "tool-index.yaml").read_text(encoding="utf-8")
    return {
        "entries": len(re.findall(r"^\s*-\s+id:", text, re.MULTILINE)),
        "sandbox_required_true": len(re.findall(r"^\s*sandbox_required:\s*true\s*$", text, re.MULTILINE)),
        "sandbox_required_false": len(re.findall(r"^\s*sandbox_required:\s*false\s*$", text, re.MULTILINE)),
    }


def test_tool_registry_yaml_matches_recorded_measurement():
    """إن عُدِّلَ سجلُّ الأدواتِ فليُعَدْ قياسُه وتسجيلُه — لا يُعدَّلُ بصمت."""
    recorded = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))["tool_registry_yaml"]
    measured = _yaml_registry_counts()
    for key, value in measured.items():
        assert recorded[key] == value, (
            f"{key}: الوثيقةُ تقولُ {value} واللَقطةُ تقولُ {recorded[key]} — أعِد القياس"
        )


def test_live_tool_registry_drift_is_recorded_not_hidden():
    """الانحرافُ بينَ سجلِّ الأدواتِ الوثائقيِّ والجدولِ الحيِّ مُسجَّلٌ بأسمائِه."""
    data = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    live = data["tool_registry_live"]
    doc = data["tool_registry_yaml"]
    assert live["entries"] == doc["entries"]
    assert live["sandbox_required_false"] >= doc["sandbox_required_false"]
    assert live["sandbox_false_ids"], "قائمةُ الأدواتِ غيرِ المعزولةِ حيًّا يجبُ أن تُسمّى"
    assert live["yaml_high_or_medium_risk_unisolated_in_live"], (
        "أدواتٌ عالية/متوسطة الخطرِ في الوثيقةِ وغيرُ معزولةٍ حيًّا يجبُ أن تُسمّى"
    )
