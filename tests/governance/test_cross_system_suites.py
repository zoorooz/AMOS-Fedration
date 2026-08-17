"""
اختبارات بوابة الحِزَم عبر الأنظمة (E2.2-G)
الهدف: إثبات أن البوابة تسقط فعلًا حين لا تُجرَّب اللهجة، لا أن تبدو خضراء
النطاق: tests/governance
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-16

اختبارات خفيفة بقصد: تُجرَّب قواعد الحكم وتحليل المخرَج والانحراف الساكن **بلا
تشغيل أي حزمة وبلا شبكة**. تشغيل الحِزَم نفسه مسؤولية الأداة لا مسؤولية هذه
الاختبارات، وتكراره هنا كان سيضاعف الزمن بلا دليل إضافي.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "governance"))

import verify_cross_system_suites as gate  # noqa: E402


class TestSuiteMatrixDeclaration:
    """المصفوفة المُعلنة تغطي الأنظمة المطلوبة في E2.2-G."""

    def test_declares_both_dialects(self) -> None:
        dialects = {suite.dialect for suite in gate.SUITES}
        assert gate.DIALECT_SQLITE in dialects
        assert gate.DIALECT_POSTGRES in dialects

    def test_postgres_suite_forbids_skips(self) -> None:
        pg_suites = [s for s in gate.SUITES if s.dialect == gate.DIALECT_POSTGRES]
        assert pg_suites, "لا حزمة PostgreSQL مُعلنة — الإثبات عبر الأنظمة مستحيل"
        assert all(s.forbid_skips for s in pg_suites)

    def test_every_declared_target_exists(self) -> None:
        missing = [
            f"{s.name}:{t}"
            for s in gate.SUITES
            for t in s.targets
            if not (s.workdir / t).exists()
        ]
        assert missing == []


class TestSummaryParsing:
    """تحليل ملخّص pytest — الأرقام تُقرأ لا تُخمَّن."""

    @pytest.mark.parametrize(
        ("line", "expected"),
        [
            ("729 passed in 37.09s", {"passed": 729}),
            ("725 passed, 25 skipped in 99.64s", {"passed": 725, "skipped": 25}),
            ("2 failed, 189 passed in 319.97s", {"failed": 2, "passed": 189}),
            ("1 error in 0.4s", {"error": 1}),
            ("3 errors in 0.4s", {"error": 3}),
        ],
    )
    def test_parses_summary_variants(self, line: str, expected: dict) -> None:
        counts, matched = gate.parse_summary(f"some output\n{line}\n")
        assert counts == expected
        assert matched == line

    def test_strips_pytest_decoration(self) -> None:
        decorated = "===== 725 passed, 25 skipped in 92.93s (0:01:32) ====="
        counts, matched = gate.parse_summary(decorated)
        assert counts == {"passed": 725, "skipped": 25}
        assert not matched.startswith("=")

    def test_reads_last_summary_when_log_has_several(self) -> None:
        counts, _ = gate.parse_summary(
            "10 passed in 1s\n\n20 passed, 1 skipped in 2s\n"
        )
        assert counts == {"passed": 20, "skipped": 1}

    def test_returns_empty_when_no_summary(self) -> None:
        assert gate.parse_summary("collected nothing useful") == ({}, "")


class TestFailureRules:
    """قواعد السقوط: الخضرة لا تُمنح بالتخطّي."""

    @property
    def _pg(self) -> gate.Suite:
        return next(s for s in gate.SUITES if s.dialect == gate.DIALECT_POSTGRES)

    @property
    def _sqlite(self) -> gate.Suite:
        return next(s for s in gate.SUITES if s.dialect == gate.DIALECT_SQLITE)

    def test_clean_pass_has_no_violation(self) -> None:
        assert gate.evaluate(self._pg, 0, {"passed": 191}) == []

    def test_skips_break_the_postgres_suite(self) -> None:
        # هذا هو جوهر البوابة: رمز خروج 0 وكل الاختبارات مُتخطّاة = سقوط.
        violations = gate.evaluate(self._pg, 0, {"skipped": 19})
        assert violations, "التخطّي الكامل مرّ خضراء — البوابة بلا قيمة"
        assert any("لم تُجرَّب" in v for v in violations)

    def test_skips_allowed_in_sqlite_suite(self) -> None:
        assert gate.evaluate(self._sqlite, 0, {"passed": 725, "skipped": 25}) == []

    def test_zero_passed_is_a_violation(self) -> None:
        assert gate.evaluate(self._sqlite, 0, {}) != []

    def test_failed_and_error_and_exit_code_are_violations(self) -> None:
        violations = gate.evaluate(
            self._sqlite, 1, {"passed": 5, "failed": 2, "error": 1}
        )
        assert len(violations) >= 3


class TestPostgresEnvDetection:
    """كشف بيئة PostgreSQL — العَلَم وحده لا يكفي."""

    def test_requires_flag_and_postgres_url(self) -> None:
        assert gate.postgres_env_present(
            {gate.PG_FLAG_ENV: "1", gate.PG_URL_ENV: "postgresql://u@h/db"}
        )

    @pytest.mark.parametrize(
        "env",
        [
            {},
            {gate.PG_FLAG_ENV: "1"},
            {gate.PG_URL_ENV: "postgresql://u@h/db"},
            {gate.PG_FLAG_ENV: "0", gate.PG_URL_ENV: "postgresql://u@h/db"},
            {gate.PG_FLAG_ENV: "1", gate.PG_URL_ENV: "sqlite:///x.db"},
        ],
    )
    def test_rejects_incomplete_env(self, env: dict) -> None:
        assert gate.postgres_env_present(env) is False

    def test_require_postgres_flag_fails_without_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(gate.PG_FLAG_ENV, raising=False)
        monkeypatch.delenv(gate.PG_URL_ENV, raising=False)
        # لا يُشغَّل شيء: البوابة تسقط قبل أي حزمة.
        assert gate.main(["--require-postgres"]) == 1


class TestStaticDriftCheck:
    """`--check` يكشف غياب الوثيقة أو نقص حزمة فيها بلا تشغيل."""

    def test_check_passes_on_committed_document(self) -> None:
        assert gate.check_drift() == []
        assert gate.main(["--check"]) == 0

    def test_check_detects_missing_document(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        monkeypatch.setattr(gate, "OUTPUT", tmp_path / "absent.md")
        problems = gate.check_drift()
        assert len(problems) == 1
        assert "غائبة" in problems[0]

    def test_check_detects_document_missing_a_suite(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        partial = tmp_path / "partial.md"
        partial.write_text("| `root-core` | لا شيء غيرها |", encoding="utf-8")
        monkeypatch.setattr(gate, "OUTPUT", partial)
        problems = gate.check_drift()
        assert any("services-postgres" in p for p in problems)


class TestGeneratedDocumentHonesty:
    """الوثيقة المولَّدة تقول الحقيقة عن الحزمة الساقطة، ولا تجمّلها."""

    def _result(
        self, suite: gate.Suite, counts: dict, exit_code: int = 0
    ) -> gate.SuiteResult:
        return gate.SuiteResult(
            suite=suite,
            exit_code=exit_code,
            counts=counts,
            duration_s=1.0,
            summary_line="synthetic",
            violations=gate.evaluate(suite, exit_code, counts),
        )

    def test_skipped_postgres_suite_renders_as_fail(self) -> None:
        pg = next(s for s in gate.SUITES if s.dialect == gate.DIALECT_POSTGRES)
        text = gate.render([self._result(pg, {"skipped": 19})], pg_present=False)
        assert "**FAIL**" in text
        assert "غائبة" in text

    def test_passing_suite_renders_as_pass_with_measured_counts(self) -> None:
        sqlite_suite = next(s for s in gate.SUITES if s.dialect == gate.DIALECT_SQLITE)
        text = gate.render(
            [self._result(sqlite_suite, {"passed": 725, "skipped": 25})],
            pg_present=True,
        )
        assert "**PASS**" in text
        assert "725" in text
        assert "مُفعّلة" in text


class TestFailureIsPubliclyObservable:
    """سببُ السقوط يُنشَر في تعليقِ GitHub، لأنّ السجلّ محجوبٌ عن غير الموقّعين.

    سجلُّ الوظيفة لا يُقرأ إلاّ بتسجيلِ دخول، والتعليقاتُ (`::error::`) تُرى
    علنًا. فحارسُ المخرَجِ الذي لا يُقرأ حارسٌ مُعطَّل.
    """

    def _failed(self) -> gate.SuiteResult:
        pg = next(s for s in gate.SUITES if s.dialect == gate.DIALECT_POSTGRES)
        counts = {"passed": 3, "failed": 2}
        return gate.SuiteResult(
            suite=pg,
            exit_code=1,
            counts=counts,
            duration_s=2.0,
            summary_line="2 failed, 3 passed in 4.20s",
            violations=gate.evaluate(pg, 1, counts),
            tail="FAILED tests/test_phase1_postgres.py::test_x - AssertionError\nsecond line",
        )

    def test_annotation_carries_reason_summary_and_output_tail(self) -> None:
        line = gate.annotation(self._failed())
        assert line.startswith("::error title=cross-system services-postgres::")
        assert "رمز الخروج: 1" in line
        assert "2 failed, 3 passed in 4.20s" in line
        assert "AssertionError" in line
        # التعليقُ سطرٌ واحد: أيُّ سطرٍ جديدٍ حقيقيّ يقطعه فيضيع باقيه.
        assert "\n" not in line
        assert line.count("%0A") >= 5

    def test_annotation_does_not_let_output_forge_a_new_command(self) -> None:
        """مخرَجُ pytest قد يحتوي `::` فلا يُترك ليُصنِّع أمرَ مُشغِّلٍ جديدًا."""
        result = self._failed()
        result.tail = "FAILED a::b - ::error::مزيّف"
        line = gate.annotation(result)
        assert line.count("::error") == 1

    def test_run_result_captures_a_tail_by_default_empty_not_missing(self) -> None:
        pg = next(s for s in gate.SUITES if s.dialect == gate.DIALECT_POSTGRES)
        bare = gate.SuiteResult(suite=pg, exit_code=0)
        assert bare.tail == ""
        assert gate.TAIL_LINES > 0
