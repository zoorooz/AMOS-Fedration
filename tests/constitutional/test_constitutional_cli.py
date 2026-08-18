"""
اختبارات واجهة سطر الأوامر الدستورية — Constitutional CLI Tests (E1)
الهدف: إثبات أن بوابات CI الدستورية تُرجع رمز خروج صحيحًا: 0 عند السلامة، وغير صفر عند المخالفة أو العبث.
النطاق: core/constitutional_engine/cli.py — كل أمر فرعي في مساري النجاح والفشل.
المالك: tests/constitutional/
تاريخ الإنشاء: 2026-08-16
تاريخ آخر تعديل: 2026-08-16

بوابة لا تفشل عند الخطأ ليست بوابة. هذه الاختبارات تُثبت أنها تفشل.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.constitutional_engine.cli import main  # noqa: E402
from core.constitutional_engine.ledger import ConstitutionalLedger  # noqa: E402


class TestVerifyGate:
    def test_verify_passes_on_committed_constitution(self, capsys):
        assert main(["verify"]) == 0
        assert "✓" in capsys.readouterr().out

    def test_coverage_passes_and_lists_every_article(self, capsys):
        assert main(["coverage"]) == 0
        out = capsys.readouterr().out
        for i in range(1, 12):
            assert f"A{i:03d}" in out

    def test_seal_writes_all_eleven(self, capsys):
        """إحدى عشرة مادة بعد المادة الحادية عشرة بالمرسوم AMD-003."""
        assert main(["seal"]) == 0
        out = capsys.readouterr().out
        # إحدى عشرة مادة + الديباجة = اثنا عشر نصًّا مختومًا (التفسير INT-002)
        assert "خُتمت 11 مادة + الديباجة" in out
        assert "12 نصًّا دستوريًّا" in out


class TestEvaluateCommand:
    def test_lawful_action_exits_zero(self, tmp_path: Path, capsys):
        code = main([
            "evaluate", "--actor", "executive", "--action", "orchestrate",
            "--ledger", str(tmp_path / "l.jsonl"),
        ])
        assert code == 0
        assert "ALLOW" in capsys.readouterr().out

    def test_unlawful_action_exits_two_and_names_article(self, tmp_path: Path, capsys):
        code = main([
            "evaluate", "--actor", "executive", "--action", "legislate",
            "--ledger", str(tmp_path / "l.jsonl"),
        ])
        assert code == 2
        out = capsys.readouterr().out
        assert "DENY" in out and "A003" in out and "R-003-1" in out

    def test_json_output_is_machine_readable(self, tmp_path: Path, capsys):
        main([
            "evaluate", "--actor", "system", "--action", "disable_kill_switch",
            "--ledger", str(tmp_path / "l.jsonl"), "--json",
        ])
        payload = json.loads(capsys.readouterr().out)
        assert payload["decision"] == "DENY"
        assert payload["violations"][0]["article_id"] == "A008"
        assert payload["ledger_entry_hash"]

    def test_flags_are_honoured(self, tmp_path: Path, capsys):
        """الموافقة البشرية عبر العلم تقلب الحكم من رفض إلى سماح."""
        led = str(tmp_path / "l.jsonl")
        assert main(["evaluate", "--actor", "executive", "--action", "promote_model", "--ledger", led]) == 2
        capsys.readouterr()
        assert main([
            "evaluate", "--actor", "executive", "--action", "promote_model",
            "--human-approved", "--ledger", led,
        ]) == 0

    def test_every_evaluation_is_written_to_the_ledger(self, tmp_path: Path):
        led_path = tmp_path / "l.jsonl"
        for action in ("orchestrate", "legislate", "adjudicate"):
            main(["evaluate", "--actor", "executive", "--action", action, "--ledger", str(led_path)])
        assert len(ConstitutionalLedger(led_path)) == 3


class TestLedgerVerifyGate:
    def test_passes_on_intact_chain(self, tmp_path: Path, capsys):
        led = ConstitutionalLedger(tmp_path / "l.jsonl")
        led.append({"type": "T"})
        led.append({"type": "T"})
        assert main(["ledger-verify", "--ledger", str(led.path)]) == 0
        assert "✓" in capsys.readouterr().out

    def test_fails_on_tampered_chain(self, tmp_path: Path, capsys):
        led = ConstitutionalLedger(tmp_path / "l.jsonl")
        led.append({"type": "T", "decision": "DENY"})
        rec = json.loads(led.path.read_text(encoding="utf-8").splitlines()[0])
        rec["body"]["decision"] = "ALLOW"
        led.path.write_text(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")

        assert main(["ledger-verify", "--ledger", str(led.path)]) == 1
        assert "✗" in capsys.readouterr().out

    def test_empty_ledger_is_valid(self, tmp_path: Path):
        assert main(["ledger-verify", "--ledger", str(tmp_path / "none.jsonl")]) == 0


class TestParser:
    def test_unknown_command_is_rejected(self):
        with pytest.raises(SystemExit):
            main(["nonsense"])

    def test_subcommand_is_required(self):
        with pytest.raises(SystemExit):
            main([])
