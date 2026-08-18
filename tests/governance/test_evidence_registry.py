"""
اختبارُ سجلِّ الأدلّة — Evidence Registry (المرحلة 1L)
الهدف: إثباتُ أنّ السجلَّ يجمع الدليلَ ولا يصنعه، وأنّه لا يقبل إعلانًا يدويًّا،
       وأنّ الغيابَ يُرفَع صريحًا ولا يُقرأ نجاحًا، وأنّ القيدَ لا يُعدَّل بعد تثبيته.
النطاق: tools/governance/evidence_registry.py
المالك: tools/governance
تاريخ الإنشاء: 2026-08-18
تاريخ آخر تعديل: 2026-08-18

ما تحرسه هذه الاختبارات — ثلاثةُ منوعاتٍ لا تحسيناتٍ:
  ١) لا إعلانَ يدويًّا: قيدٌ بلا مُنتِجٍ ولا مخرَجٍ مبصومٍ يُرفَض.
  ٢) لا بديلَ صامتًا: غيابُ الدليل يرفع `EvidenceAbsent`، ولا يُرجِع قيمةً خالية
     تُقرأ سهوًا نجاحًا.
  ٣) لا تعديلَ بعد التثبيت: تحريرُ قيدٍ يكسر السلسلةَ ويُكشَف، ولا يُلحَق فوقها.

وتحرس كذلك أنّ نسبةَ الاختبار إلى الإقليم تُبنى على **موقعِ الملفّ** لا على
ورودِ اسمِ الإقليم في نصِّه — وهو العطلُ الذي أنشأ هذا السجلَّ أصلًا.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.governance.evidence_registry import (
    GENESIS_HASH,
    EvidenceAbsent,
    EvidenceIntegrityError,
    EvidenceRegistry,
    _domains_imported_by,
    collect_from_coverage_xml,
    collect_from_junit,
    compute_hash,
)

VALID = dict(
    kind="TEST_RUN",
    domain="core",
    capability="core: حزمةُ الاختبارات",
    verdict="PASS",
    producer="pytest --junitxml",
    produced_at="2026-08-18T00:00:00+00:00",
    source_artifact="reports/junit.xml",
    source_digest="a" * 64,
)


@pytest.fixture()
def reg(tmp_path: Path) -> EvidenceRegistry:
    return EvidenceRegistry(tmp_path / "evidence.jsonl")


class Testلاإعلانيدوي:
    """الدليلُ يُجمَع من مخرَجِ آلةٍ ولا يُعلَن باليد."""

    def test_قيدٌ_بلا_مُنتِجٍ_يُرفَض(self, reg: EvidenceRegistry):
        payload = {**VALID, "producer": ""}
        with pytest.raises(ValueError, match="producer"):
            reg.append(**payload)

    def test_قيدٌ_بلا_مخرَجٍ_مبصومٍ_يُرفَض(self, reg: EvidenceRegistry):
        with pytest.raises(ValueError, match="source_digest"):
            reg.append(**{**VALID, "source_digest": ""})
        with pytest.raises(ValueError, match="source_artifact"):
            reg.append(**{**VALID, "source_artifact": ""})

    def test_نوعُ_دليلٍ_مُختلَقٌ_يُرفَض(self, reg: EvidenceRegistry):
        """الأنواعُ مغلقةٌ قصدًا: نوعٌ جديدٌ يلزمه مُلقِّطٌ يقرأ آلةً حقيقيّة."""
        with pytest.raises(ValueError, match="نوعُ دليلٍ غيرُ معروف"):
            reg.append(**{**VALID, "kind": "IT_WORKS_TRUST_ME"})

    def test_حكمٌ_مُختلَقٌ_يُرفَض(self, reg: EvidenceRegistry):
        with pytest.raises(ValueError, match="حكمٌ غيرُ معروف"):
            reg.append(**{**VALID, "verdict": "PROVEN"})


class Testلابديلصامت:
    """الغيابُ يُرفَع صريحًا ولا يُقرأ نجاحًا."""

    def test_الغيابُ_يرفع_استثناءً_لا_يُرجِع_خاليًا(self, reg: EvidenceRegistry):
        with pytest.raises(EvidenceAbsent):
            reg.latest("TEST_RUN", "core")

    def test_الغيابُ_ليس_نجاحًا(self, reg: EvidenceRegistry):
        assert reg.has_passing("TEST_RUN", "core") is False

    def test_الدليلُ_الساقطُ_ليس_نجاحًا(self, reg: EvidenceRegistry):
        reg.append(**{**VALID, "verdict": "FAIL"})
        assert reg.has_passing("TEST_RUN", "core") is False

    def test_الخلاصةُ_تُصرِّح_بالغياب_ولا_تسكت_عنه(self, reg: EvidenceRegistry):
        reg.append(**VALID)
        summary = reg.summary()
        assert summary["core"]["TEST_RUN"] == "PASS"
        # إقليمٌ بلا دليلٍ يُكتَب `ABSENT` صراحةً، لا فراغًا يُقرأ رضًا
        assert summary["royal"]["TEST_RUN"] == "ABSENT"
        assert summary["core"]["RECOVERY_DRILL"] == "ABSENT"


class Testلاتعديلبعدالتثبيت:
    """القيدُ المُثبَّت لا يُحرَّر، والتحريرُ يُكشَف ويمنع الإلحاق."""

    def test_السلسلةُ_سليمةٌ_بعد_إلحاقٍ_متعدّد(self, reg: EvidenceRegistry):
        for i in range(5):
            reg.append(**{**VALID, "detail": {"i": i}})
        assert reg.verify_chain() == []
        recs = reg.records()
        assert [r.index for r in recs] == list(range(5))
        assert recs[0].prev_hash == GENESIS_HASH
        for a, b in zip(recs, recs[1:]):
            assert b.prev_hash == a.entry_hash

    def test_تحريرُ_قيدٍ_يُكشَف(self, reg: EvidenceRegistry):
        reg.append(**VALID)
        reg.append(**{**VALID, "verdict": "FAIL"})

        lines = reg.path.read_text(encoding="utf-8").splitlines()
        rec = json.loads(lines[1])
        rec["verdict"] = "PASS"  # قلبُ حكمٍ ساقطٍ إلى ناجح
        lines[1] = json.dumps(rec, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":"))
        reg.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        assert reg.verify_chain() != [], "قلبُ الحكمِ لم يُكشَف."

    def test_لا_يُلحَق_فوق_سلسلةٍ_مكسورة(self, reg: EvidenceRegistry):
        """الإغلاقُ عند الفشل: سجلٌّ مكسورٌ يرفض النموَّ فوق كسره."""
        reg.append(**VALID)
        lines = reg.path.read_text(encoding="utf-8").splitlines()
        rec = json.loads(lines[0])
        rec["detail"] = {"مُحرَّف": True}
        lines[0] = json.dumps(rec, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":"))
        reg.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        with pytest.raises(EvidenceIntegrityError):
            reg.append(**VALID)

    def test_البصمةُ_محتومةٌ_لا_تتغيّر_بترتيب_المفاتيح(self):
        a = compute_hash({"x": 1, "y": {"b": 2, "a": 3}})
        b = compute_hash({"y": {"a": 3, "b": 2}, "x": 1})
        assert a == b


class Testالنسبةإلىالإقليم:
    """الدليلُ يُنسَب بما يستورده الملفُّ فعلًا، لا بموقعِه ولا بنصِّه.

    وكانت النسبةُ أوّلَ مرّةٍ مبنيّةً على المسار بافتراضِ اصطلاحِ
    `tests/<إقليم>/`. والاصطلاحُ القائمُ في هذا المستودع `tests/constitutional/`
    و`tests/crown/` و`tests/sovereignty/` — أسماءُ فصولٍ لا أقاليم. فلم يُنسَب
    اختبارٌ واحدٌ من ٨٣٨، وكان الافتراضُ خطأً قِيس فصُحِّح.
    """

    def test_الاستيرادُ_الحقيقيُّ_يشهد(self, tmp_path: Path):
        f = tmp_path / "test_a.py"
        f.write_text(
            "from core.constitutional_engine.ledger import ConstitutionalLedger\n"
            "import royal.crown.guard\n",
            encoding="utf-8")
        assert _domains_imported_by(f) == frozenset({"core", "royal"})

    def test_ورودُ_الاسمِ_في_تعليقٍ_أو_نصٍّ_لا_يشهد(self, tmp_path: Path):
        """`ast` لا `grep`: كلمةٌ في تعليقٍ أو نصٍّ ليست استيرادًا."""
        f = tmp_path / "test_b.py"
        f.write_text(
            "# import core\n"
            'DOC = "from federal.x import y"\n'
            "import os\n",
            encoding="utf-8")
        assert _domains_imported_by(f) == frozenset()

    def test_ملفٌّ_غيرُ_موجودٍ_لا_يُنسَب_ولا_يُسقِط(self, tmp_path: Path):
        assert _domains_imported_by(tmp_path / "غائب.py") == frozenset()

    def test_ملفٌّ_لا_يُحلَّل_يُسقِط_ولا_يُبتلَع(self, tmp_path: Path):
        """إغلاقٌ عند الفشل: خطأُ التحليل يصعد ولا يُقرأ «لا دليل»."""
        f = tmp_path / "test_c.py"
        f.write_text("def broken( :\n", encoding="utf-8")
        with pytest.raises(SyntaxError):
            _domains_imported_by(f)

    def test_ورودُ_اسمِ_الإقليم_في_النصّ_لا_يشهد_له(self, tmp_path: Path):
        """جوهرُ العطل: نصٌّ فيه كلمةُ `core` لا يُنتِج دليلًا لـ`core`.

        قبل هذا السجلّ كان المدقّقُ يعدّ ورودَ الكلمةِ شهادةَ اختبار، فكان
        تعليقٌ واحدٌ يكفي لإصدار شهادةٍ لإقليمٍ كامل.
        """
        xml = tmp_path / "junit.xml"
        xml.write_text(
            '<testsuite name="s" timestamp="2026-08-18T00:00:00" tests="1">'
            '<testcase classname="somewhere.unmapped" name="mentions core royal federal"'
            ' file="scripts/helper_test.py"/>'
            "</testsuite>",
            encoding="utf-8",
        )
        collected, _ = collect_from_junit(xml, repo_root=tmp_path)
        assert collected == [], "نصٌّ فيه أسماءُ الأقاليم أنتج دليلًا — العطلُ عاد."


@pytest.fixture
def مستودعٌ_وهميّ(tmp_path: Path) -> Path:
    """شجرةٌ فيها ملفّا اختبارٍ يستوردان `core` فعلًا.

    النسبةُ تُقرأ من الاستيرادِ الحقيقيّ، فلا يكفي مسارٌ مُصطنَعٌ في XML: يلزم
    ملفٌّ على القرص يقول `import core`. وهذا قيدٌ مقصود — الدليلُ يلزمه واقع.
    """
    d = tmp_path / "tests" / "core"
    d.mkdir(parents=True)
    for n in ("test_a.py", "test_b.py"):
        (d / n).write_text("import core\n", encoding="utf-8")
    return tmp_path


class Testالتلقيطمنمخرجحقيقي:
    """المُلقِّطات تقرأ حكمَ الآلة ولا تُنشئ حكمًا من عندها."""

    def test_اختبارٌ_ساقطٌ_يُنتِج_حكمًا_ساقطًا(self, مستودعٌ_وهميّ: Path):
        tmp_path = مستودعٌ_وهميّ
        xml = tmp_path / "junit.xml"
        xml.write_text(
            '<testsuite name="s" timestamp="2026-08-18T00:00:00">'
            '<testcase classname="tests.core.a" name="ok" file="tests/core/test_a.py"/>'
            '<testcase classname="tests.core.b" name="bad" file="tests/core/test_b.py">'
            '<failure message="boom">trace</failure></testcase>'
            "</testsuite>",
            encoding="utf-8",
        )
        collected, meta = collect_from_junit(xml, repo_root=tmp_path)
        assert len(collected) == 1
        item = collected[0]
        assert item.domain == "core"
        assert item.verdict == "FAIL", "سقوطُ اختبارٍ لم يُنقل إلى الحكم."
        assert item.detail == {"passed": 1, "failed": 1, "skipped": 0}
        assert meta["produced_at"] == "2026-08-18T00:00:00"

    def test_نجاحٌ_كاملٌ_يُنتِج_حكمًا_ناجحًا(self, مستودعٌ_وهميّ: Path):
        tmp_path = مستودعٌ_وهميّ
        xml = tmp_path / "junit.xml"
        xml.write_text(
            '<testsuite name="s" timestamp="2026-08-18T00:00:00">'
            '<testcase classname="tests.core.a" name="ok" file="tests/core/test_a.py"/>'
            '<testcase classname="tests.core.b" name="ok2" file="tests/core/test_b.py"/>'
            "</testsuite>",
            encoding="utf-8",
        )
        collected, _ = collect_from_junit(xml, repo_root=tmp_path)
        assert collected[0].verdict == "PASS"

    def test_تخطٍّ_وحده_ليس_نجاحًا(self, مستودعٌ_وهميّ: Path):
        """حزمةٌ كلُّها متخطّاةٌ لا تشهد بشيء — التخطّي ليس اختبارًا شُغِّل."""
        tmp_path = مستودعٌ_وهميّ
        xml = tmp_path / "junit.xml"
        xml.write_text(
            '<testsuite name="s" timestamp="2026-08-18T00:00:00">'
            '<testcase classname="tests.core.a" name="s" file="tests/core/test_a.py">'
            '<skipped message="no db"/></testcase>'
            "</testsuite>",
            encoding="utf-8",
        )
        collected, _ = collect_from_junit(xml, repo_root=tmp_path)
        assert collected[0].verdict == "FAIL", "حزمةٌ متخطّاةٌ بالكامل عُدَّت نجاحًا."

    def test_التغطيةُ_دون_الحدِّ_تُنتِج_حكمًا_ساقطًا(self, tmp_path: Path):
        xml = tmp_path / "coverage.xml"
        xml.write_text(
            f'<coverage><sources><source>{tmp_path}</source></sources>'
            '<packages><package><classes>'
            '<class filename="core/a.py"><lines>'
            '<line number="1" condition-coverage="50% (1/2)"/>'
            '<line number="2" condition-coverage="0% (0/2)"/>'
            "</lines></class></classes></package></packages></coverage>",
            encoding="utf-8",
        )
        collected, _ = collect_from_coverage_xml(xml, repo_root=tmp_path)
        assert len(collected) == 1
        assert collected[0].domain == "core"
        assert collected[0].verdict == "FAIL"
        assert collected[0].detail["branch_coverage_pct"] == 25.0

    def test_التغطيةُ_فوق_الحدِّ_تُنتِج_حكمًا_ناجحًا(self, tmp_path: Path):
        xml = tmp_path / "coverage.xml"
        xml.write_text(
            f'<coverage><sources><source>{tmp_path}</source></sources>'
            '<packages><package><classes>'
            '<class filename="core/a.py"><lines>'
            '<line number="1" condition-coverage="100% (4/4)"/>'
            '<line number="2" condition-coverage="75% (3/4)"/>'
            "</lines></class></classes></package></packages></coverage>",
            encoding="utf-8",
        )
        collected, _ = collect_from_coverage_xml(xml, repo_root=tmp_path)
        assert collected[0].verdict == "PASS"
        assert collected[0].detail["branch_coverage_pct"] == 87.5


    def test_الحكمُ_يُؤخَذ_من_رمزِ_خروجِ_البوّابة_لا_من_حسابٍ_محلّي(self, tmp_path: Path):
        """المقياسُ المحسوبُ محلّيًّا ليس هو المقياسَ الذي أُعلِن الحدُّ له.

        `--cov-fail-under` تحكم بمجموعِ السطورِ والفروع، وهذا المُلقِّطُ يحسب
        معدَّلَ الفروعِ وحدَه. وقد بلغ الفرقُ في `core.crown` نحوَ ثماني نقاط
        (86.75٪ فروعًا مقابل 94.48٪ مجموعًا)، فمقارنةُ الحدِّ بالمقياسِ الخطأ
        أنتجت سقوطًا لا وجودَ له. فالحكمُ من الآلةِ التي أُعلِن لها الحدّ.
        """
        xml = tmp_path / "coverage.xml"
        xml.write_text(
            f'<coverage><sources><source>{tmp_path}</source></sources>'
            '<packages><package><classes>'
            '<class filename="core/a.py"><lines>'
            '<line number="1" condition-coverage="50% (1/2)"/>'
            "</lines></class></classes></package></packages></coverage>",
            encoding="utf-8",
        )
        # معدَّلُ الفروعِ 50٪ ودون أيِّ حدٍّ معقول، ومع ذلك اجتازت البوّابةُ
        # فعلًا (رمزُ خروجٍ صفر) — فالحكمُ نجاحٌ ومصدرُه مُعلَن.
        collected, _ = collect_from_coverage_xml(
            xml, repo_root=tmp_path, threshold=90.0, scope="core.x", gate_verdict="PASS")
        assert collected[0].verdict == "PASS"
        assert collected[0].detail["verdict_source"] == "gate_exit_code"
        assert collected[0].detail["branch_coverage_pct"] == 50.0

    def test_بلا_بوّابةٍ_يُعلَن_أنّ_الحكمَ_محسوبٌ_محلّيًّا(self, tmp_path: Path):
        xml = tmp_path / "coverage.xml"
        xml.write_text(
            f'<coverage><sources><source>{tmp_path}</source></sources>'
            '<packages><package><classes>'
            '<class filename="core/a.py"><lines>'
            '<line number="1" condition-coverage="50% (1/2)"/>'
            "</lines></class></classes></package></packages></coverage>",
            encoding="utf-8",
        )
        collected, _ = collect_from_coverage_xml(xml, repo_root=tmp_path)
        assert collected[0].detail["verdict_source"] == "recomputed_branch_rate"


class Testالقفلجانبي:
    """القفلُ في ملفٍّ منفصلٍ فلا يدخل بايتٌ منه إلى السجل."""

    def test_ملفُّ_القفل_لا_يُلوِّث_السجل(self, reg: EvidenceRegistry):
        reg.append(**VALID)
        assert reg.lock_path != reg.path
        assert reg.lock_path.exists()
        assert len(reg.records()) == 1
        assert reg.verify_chain() == []
