"""
اختبارات المصالحة الدستوريّة — المرحلة 1B
الهدف: إثباتُ أنّ أداةَ المصالحة تكشف ما تُوجبه النصوصُ الدستوريّةُ على نفسها، وأنّها
       لا تشهد بسلامةٍ لمجرّد ورودِ لفظٍ في نصّ، ولا تنتحل صفةً ملكيّةً بختمٍ لا تملكه.
النطاق: tests/governance — اختباراتٌ لا تمنح صلاحيّةً ولا تُعلن قدرةً مُثبَتة.
المالك: tests/governance
تاريخ الإنشاء: 2026-08-18
تاريخ آخر تعديل: 2026-08-18

## لِمَ وُجد هذا الملف

الثغرةُ التي يحرسها هذا الملفُّ أُثبتت بالتجربة لا بالتوقّع: أُدخلت جملةُ
«الملك لا سلطة له على الخزانة» في نصِّ مرسومٍ ملكيٍّ قائم، ثمّ شُغِّل كلُّ فحصٍ
في المستودع — فأعلن `verify_seals` أن لا اختلاف، وأعلن قانونُ الهويّة النجاح.
أي أنّ **تاريخَ الدولةِ الدستوريَّ كان قابلًا لإعادة الكتابةِ بلا أثرٍ واحد**،
وحفظُ السجلِّ دون حذفٍ مبدأٌ لا يقبل التعديل أصلًا (المادة الخامسة).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.governance import constitutional_reconciliation as recon

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def دستورٌ_وهميّ(tmp_path: Path) -> Path:
    """يبني شجرةَ دستورٍ صغيرةً حقيقيّةَ الملفّات لا مُحاكاةً بالتلقيم."""
    root = tmp_path
    (root / "core" / "constitution" / "articles").mkdir(parents=True)
    (root / "core" / "constitution" / "amendments").mkdir(parents=True)
    (root / "core" / "constitution" / "interpretations").mkdir(parents=True)
    (root / "core" / "constitutional_engine").mkdir(parents=True)
    return root


def _patch_paths(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.setattr(recon, "REPO_ROOT", root)
    monkeypatch.setattr(recon, "CONSTITUTION", root / "core" / "constitution")
    monkeypatch.setattr(recon, "ARTICLES_DIR", root / "core" / "constitution" / "articles")
    monkeypatch.setattr(recon, "AMENDMENTS_DIR", root / "core" / "constitution" / "amendments")
    monkeypatch.setattr(
        recon, "INTERPRETATIONS_DIR", root / "core" / "constitution" / "interpretations",
    )
    monkeypatch.setattr(recon, "SEALS_PATH", root / "core" / "constitution" / "ARTICLE_SEALS.json")


class Testسجلُّالتاريخ:
    """السجلُّ التدقيقيُّ يكشف التبديلَ — وغيابُه ليس سكوتًا."""

    def test_تبديلُ_مرسومٍ_بعد_التثبيت_يُكشَف(
        self, دستورٌ_وهميّ: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        root = دستورٌ_وهميّ
        _patch_paths(monkeypatch, root)
        amd = root / "core" / "constitution" / "amendments" / "AMD-001-x.md"
        amd.write_text("# مرسوم ملكي\nالملك صاحب السيادة.\n", encoding="utf-8")
        store = root / "history.json"

        recon.record_history(store, root)
        assert recon.verify_history(store, root) == []

        # تبديلٌ يعكس معنى المرسوم — وهو بالضبط ما كان يمرّ بلا أثر.
        amd.write_text("# مرسوم ملكي\nالملك لا سلطة له.\n", encoding="utf-8")
        problems = recon.verify_history(store, root)
        assert len(problems) == 1
        assert "مُبدَّل" in problems[0]

    def test_حذفُ_نصٍّ_مُثبَّتٍ_يُكشَف(
        self, دستورٌ_وهميّ: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        root = دستورٌ_وهميّ
        _patch_paths(monkeypatch, root)
        amd = root / "core" / "constitution" / "amendments" / "AMD-001-x.md"
        amd.write_text("# مرسوم ملكي\nنصّ.\n", encoding="utf-8")
        store = root / "history.json"
        recon.record_history(store, root)
        amd.unlink()
        assert any("محذوف" in p for p in recon.verify_history(store, root))

    def test_نصٌّ_جديدٌ_غيرُ_مُثبَّتٍ_يُكشَف(
        self, دستورٌ_وهميّ: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        root = دستورٌ_وهميّ
        _patch_paths(monkeypatch, root)
        store = root / "history.json"
        recon.record_history(store, root)
        (root / "core" / "constitution" / "amendments" / "AMD-999-new.md").write_text(
            "# مرسوم ملكي\nمُقحَم.\n", encoding="utf-8",
        )
        assert any("جديد" in p for p in recon.verify_history(store, root))

    def test_غيابُ_السجلِّ_اختلافٌ_لا_سكوت(
        self, دستورٌ_وهميّ: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        """لو أرجع الغيابُ «سليم» لكان تعطيلُ الحارسِ حذفَ ملفٍّ واحد."""
        root = دستورٌ_وهميّ
        _patch_paths(monkeypatch, root)
        problems = recon.verify_history(root / "لا-وجود-له.json", root)
        assert len(problems) == 1
        assert "غائب" in problems[0]


class Testعناصرالمادةالخامسة:
    """المادة الخامسة تُوجب خمسةَ عناصر — تُقاس واحدًا واحدًا."""

    def test_مرسومٌ_ناقصُ_العناصر_يُرفَع_قرارًا_بشريًّا(
        self, دستورٌ_وهميّ: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        root = دستورٌ_وهميّ
        _patch_paths(monkeypatch, root)
        (root / "core" / "constitution" / "amendments" / "AMD-001-x.md").write_text(
            "# مرسوم ملكي\nلا شيء سوى العنوان.\n", encoding="utf-8",
        )
        report = recon.Report()
        recon.check_amendment_elements(report, root)
        codes = {f.code for f in report.findings}
        assert len(codes) == 5, "العناصرُ الخمسةُ كلُّها غائبةٌ فيجب أن تُرفَع خمسًا"
        assert all(f.severity == recon.SEVERITY_HUMAN for f in report.findings), (
            "تصحيحُ مرسومٍ ملكيٍّ فعلٌ ملكيّ — لا يُصنَّف آليًّا"
        )


class Testلاشهادةبالذكر:
    """ورودُ اللفظِ ليس أداءَ الشرط — وهذا خطأٌ ارتُكب فقِيس فصُحِّح."""

    def test_ذكرُ_ed25519_وحدَه_لا_يُعَدُّ_توقيعًا(
        self, دستورٌ_وهميّ: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        root = دستورٌ_وهميّ
        _patch_paths(monkeypatch, root)
        (root / "core" / "constitution" / "amendments" / "AMD-001-x.md").write_text(
            "# مرسوم ملكي\nيجب أن يكون موقّعًا بـ Ed25519.\n", encoding="utf-8",
        )
        report = recon.Report()
        recon.check_royal_decree_signature(report, root)
        assert len(report.findings) == 1, "النصُّ يصف الشرطَ ولا يؤدّيه فوجب رفعُه"
        assert "لا يحمل مادّةَ توقيع" in report.findings[0].measured

    def test_مادّةُ_توقيعٍ_حقيقيّةٌ_لا_تُرفَع(
        self, دستورٌ_وهميّ: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        root = دستورٌ_وهميّ
        _patch_paths(monkeypatch, root)
        (root / "core" / "constitution" / "amendments" / "AMD-001-x.md").write_text(
            "# مرسوم ملكي\nEd25519: " + "a1b2c3d4" * 16 + "\n", encoding="utf-8",
        )
        report = recon.Report()
        recon.check_royal_decree_signature(report, root)
        assert report.findings == []

    def test_ذكرُ_المجلّدِ_في_رسالةٍ_لا_يُعَدُّ_قراءةً(
        self, دستورٌ_وهميّ: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        """الفحصُ الأوّلُ شهد بقدرةٍ مصدرُها جملةٌ عربيّةٌ داخل تعليق."""
        root = دستورٌ_وهميّ
        _patch_paths(monkeypatch, root)
        (root / "core" / "constitution" / "amendments" / "AMD-001-x.md").write_text(
            "# مرسوم ملكي\nنصّ.\n", encoding="utf-8",
        )
        (root / "core" / "constitutional_engine" / "articles.py").write_text(
            'MSG = "لا يُحدَّث هذا الملف إلا بمرسوم تعديل موثق في amendments/."\n',
            encoding="utf-8",
        )
        report = recon.Report()
        recon.check_engine_reads_decrees(report, root)
        assert any(f.code == "RECON-006" for f in report.findings), (
            "ذِكرُ الاسمِ في نصِّ رسالةٍ ليس قراءةً للمجلّد"
        )

    def test_قراءةٌ_فعليّةٌ_لا_تُرفَع(
        self, دستورٌ_وهميّ: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        root = دستورٌ_وهميّ
        _patch_paths(monkeypatch, root)
        (root / "core" / "constitution" / "amendments" / "AMD-001-x.md").write_text(
            "# مرسوم ملكي\nنصّ.\n", encoding="utf-8",
        )
        (root / "core" / "constitutional_engine" / "engine.py").write_text(
            'for p in (BASE / "amendments").glob("*.md"):\n    pass\n', encoding="utf-8",
        )
        report = recon.Report()
        recon.check_engine_reads_decrees(report, root)
        assert not any(
            f.code == "RECON-006" and "amendments" in f.subject for f in report.findings
        )


class Testالمستودعالحقيقيّ:
    """قراءةُ المستودعِ نفسِه — فالحُكمُ على الواقع لا على تجهيزٍ مصنوع."""

    def test_التعارضُ_بين_الخامسةِ_والعاشرةِ_قائمٌ_ويُرفَع(self):
        report = recon.Report()
        recon.check_procedure_conflict(report)
        conflicts = [f for f in report.findings if f.code == "RECON-005"]
        assert len(conflicts) == 1, (
            "الخامسةُ تشترط أغلبيّةً والعاشرةُ تُبطل الأغلبيّة — تعارضٌ قائمٌ في النصّ"
        )
        assert conflicts[0].severity == recon.SEVERITY_HUMAN, "لا يُخترَع لهذا قرار"

    def test_سجلُّ_بصماتِ_التاريخِ_المُلتزَمُ_مطابقٌ_للنصوص(self):
        """يمنع دفعَ تعديلٍ على مرسومٍ دون تثبيتِ بصمتِه في السجلّ."""
        assert recon.verify_history() == []

    def test_السجلُّ_لا_يدّعي_شرعيّةً_ولا_يُسمّي_نفسَه_ختمًا(self):
        """انتحالُ الصفةِ الملكيّةِ ممنوعٌ على الأداةِ الحارسةِ قبل غيرِها."""
        data = json.loads(recon.HISTORY_DIGESTS.read_text(encoding="utf-8"))
        assert "ليس ختمًا دستوريًا" in data["$comment"]
        assert recon.HISTORY_DIGESTS.is_relative_to(REPO_ROOT / "docs" / "audit"), (
            "موضعُه خارج core/constitution كي لا يُقرأ ختمًا"
        )

    def test_سجلٌّ_مشوّهٌ_لا_يُقرأ_سجلًّا_فارغًا(self, tmp_path: Path):
        """`.get(..., {})` كان يجعل تشويهَ الملفِّ طريقًا لتعطيل الحارس صامتًا."""
        bad = tmp_path / "history.json"
        bad.write_text('{"algorithm": "sha256"}\n', encoding="utf-8")
        problems = recon.verify_history(bad, REPO_ROOT)
        assert problems and "مشوّه" in problems[0]

    def test_سجلٌّ_غيرُ_صالحٍ_نحويًّا_يُرفَع(self, tmp_path: Path):
        bad = tmp_path / "history.json"
        bad.write_text("{ليس JSON", encoding="utf-8")
        assert recon.verify_history(bad, REPO_ROOT)
