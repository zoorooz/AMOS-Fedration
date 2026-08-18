"""
اختبارات المصالحة الدستوريّة — المرحلة 1B
الهدف: إثباتُ أنّ أداةَ المصالحة تكشف ما تُوجبه النصوصُ الدستوريّةُ على نفسها، وأنّها
       لا تشهد بسلامةٍ لمجرّد ورودِ لفظٍ في نصّ، ولا تنتحل صفةً ملكيّةً بختمٍ لا تملكه.
النطاق: tests/governance — اختباراتٌ لا تمنح صلاحيّةً ولا تُعلن قدرةً مُثبَتة.
المالك: tests/governance
تاريخ الإنشاء: 2026-08-18
تاريخ آخر تعديل: 2026-08-18

## لِمَ وُجد هذا الملف

الثغرةُ التي يحرسها هذا الملفُّ أُثبتت بالتجربة لا بالتوقّع: أُدخلت
جملةٌ تعكسُ معنى السيادة في نصِّ مرسومٍ ملكيٍّ قائم، ثمّ شُغِّل كلُّ فحصٍ
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
        # ROYAL-LANG-EXEMPT: تبديلٌ مصطنعٌ في دستورٍ وهميٍّ داخل tmp_path، لا تقريرَ معنى
        amd.write_text("# مرسوم ملكي\nالسيادةُ لغيرِ الملك.\n", encoding="utf-8")  # ROYAL-LANG-EXEMPT
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

    def test_التعارضُ_بين_الخامسةِ_والعاشرةِ_مُزالٌ_من_النصّ(self):
        """كان هذا الاختبارُ يُثبِّت بقاءَ التعارض حتى حُسم بالمرسوم `AMD-003`.

        فصار يُثبِّت زوالَه **من النصِّ الدستوريّ نفسِه** لا من وثيقةٍ شارحة:
        نصُّ المادة الخامسة يحمل رُكنَي الحسم، والفحصُ يقرأ النصَّ لا الدعوى.
        وعودةُ التعارضِ يمنعُها `Testتحصينُتعارضِالمادتين`.
        """
        report = recon.Report()
        recon.check_procedure_conflict(report)
        assert [f for f in report.findings if f.code == "RECON-005"] == []
        نص = (REPO_ROOT / "core" / "constitution" / "articles"
              / "005-amendment-process.md").read_text(encoding="utf-8")
        assert recon._conflict_resolved(نص), "رُكنا الحسمِ قائمان في النصّ"
        assert "مسار المقترح التابع" in نص.replace("\u0651", "").replace("\u064f", "")

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


A005_RESOLVED = """# المادة الخامسة — عملية التعديل

## 0. من يملك التعديل
تعديلُ الدستور اختصاصٌ ملكيٌّ حصرًا.

## شروط مسار المقترح التابع
3. فترة مراجعة لا تقل عن 90 يومًا.
4. موافقة 75% من مجلس السياسات.

> **تاريخ الإصدار:** 2026-01-01
"""

A005_UNRESOLVED = """# المادة الخامسة — عملية التعديل

## شروط التعديل
3. فترة مراجعة لا تقل عن 90 يومًا.
4. موافقة 75% من مجلس السياسات.

> **تاريخ الإصدار:** 2026-01-01
"""

A010_TEXT = """# المادة العاشرة — السيادة الملكية

تعديل الدستور حصرٌ للملك ولا تصح من أي طرف آخر بأي أغلبية ولا بأي إجراء.

> **تاريخ الإصدار:** 2026-01-01
"""


def _تعارضاتُ(root: Path) -> list:
    report = recon.Report()
    recon.check_procedure_conflict(report)
    return [f for f in report.findings if f.code == "RECON-005"]


class Testتحصينُتعارضِالمادتين:
    """RECON-005 حُسم بالمرسوم AMD-003 — والحارسُ يمنع عودتَه."""

    def test_نصُّ_الحسمِ_القائمُ_يُسكِتُ_الفحص(
        self, دستورٌ_وهميّ: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        root = دستورٌ_وهميّ
        _patch_paths(monkeypatch, root)
        arts = root / "core" / "constitution" / "articles"
        (arts / "005-amendment-process.md").write_text(A005_RESOLVED, encoding="utf-8")
        (arts / "010-royal-sovereignty.md").write_text(A010_TEXT, encoding="utf-8")
        assert _تعارضاتُ(root) == [], "التعارضُ مُزالٌ من النصِّ نفسِه"

    def test_حذفُ_نصِّ_الحسمِ_يُعيدُ_التعارضَ_صريحًا(
        self, دستورٌ_وهميّ: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        """هذا هو التحصين: لو عادت الصياغةُ القديمة صرخ الفحصُ من جديد."""
        root = دستورٌ_وهميّ
        _patch_paths(monkeypatch, root)
        arts = root / "core" / "constitution" / "articles"
        (arts / "005-amendment-process.md").write_text(A005_UNRESOLVED, encoding="utf-8")
        (arts / "010-royal-sovereignty.md").write_text(A010_TEXT, encoding="utf-8")
        found = _تعارضاتُ(root)
        assert len(found) == 1
        assert found[0].severity == recon.SEVERITY_HUMAN

    def test_رُكنٌ_واحدٌ_من_الحسمِ_لا_يكفي(
        self, دستورٌ_وهميّ: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        """حصرُ التعديلِ وحدَه دون توصيفِ النسبةِ يترك النصَّين متنازعَين."""
        root = دستورٌ_وهميّ
        _patch_paths(monkeypatch, root)
        arts = root / "core" / "constitution" / "articles"
        نصف = A005_RESOLVED.replace("## شروط مسار المقترح التابع", "## شروط التعديل")
        (arts / "005-amendment-process.md").write_text(نصف, encoding="utf-8")
        (arts / "010-royal-sovereignty.md").write_text(A010_TEXT, encoding="utf-8")
        assert len(_تعارضاتُ(root)) == 1

    def test_الدستورُ_الحقيقيُّ_خالٍ_من_التعارض(self):
        report = recon.reconcile()
        assert [f for f in report.findings if f.code == "RECON-005"] == []


class Testمدّةُالمراجعة:
    """RECON-004 — المدّةُ شرطُ مسارِ المقترحِ لا شرطُ المرسومِ الملكيّ."""

    def _هيّئ(self, root: Path, نصُّ_الخامسة: str, نصُّ_المرسوم: str) -> list:
        (root / "core" / "constitution" / "articles"
         / "005-amendment-process.md").write_text(نصُّ_الخامسة, encoding="utf-8")
        (root / "core" / "constitution" / "amendments"
         / "AMD-009-x.md").write_text(نصُّ_المرسوم, encoding="utf-8")
        report = recon.Report()
        recon.check_review_period(report, root)
        return [f for f in report.findings if f.code == "RECON-004"]

    def test_المرسومُ_الملكيُّ_لا_تسري_عليه_المدّة(
        self, دستورٌ_وهميّ: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        root = دستورٌ_وهميّ
        _patch_paths(monkeypatch, root)
        مرسوم = "# المرسوم الملكي AMD-009\n\n> **تاريخ الإصدار:** 2026-01-02\n"
        assert self._هيّئ(root, A005_RESOLVED, مرسوم) == []

    def test_المقترحُ_المؤسّسيُّ_تسري_عليه_المدّة(
        self, دستورٌ_وهميّ: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        """الإعفاءُ للمرسومِ الملكيِّ وحدَه — لا للنصِّ الذي لا يُعلِن سندَه."""
        root = دستورٌ_وهميّ
        _patch_paths(monkeypatch, root)
        مقترح = "# مقترح تعديل من مجلس السياسات\n\n> **تاريخ الإصدار:** 2026-01-02\n"
        found = self._هيّئ(root, A005_RESOLVED, مقترح)
        assert len(found) == 1
        assert "انقضى 1 يومًا" in found[0].measured

    def test_غيابُ_توصيفِ_المسارِ_يُعيدُ_المدّةَ_على_الجميع(
        self, دستورٌ_وهميّ: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        root = دستورٌ_وهميّ
        _patch_paths(monkeypatch, root)
        مرسوم = "# المرسوم الملكي AMD-009\n\n> **تاريخ الإصدار:** 2026-01-02\n"
        assert len(self._هيّئ(root, A005_UNRESOLVED, مرسوم)) == 1

    def test_المدّةُ_لم_تُخفَّض_ولا_أُلغيَت(self):
        """القرارُ المؤسِّس أبقى الشرطَ بمدّتِه — لا يُمَسُّ الرقمُ تحت غطاءِ الإصلاح."""
        assert recon.A005_REVIEW_DAYS == 90
        نص = (REPO_ROOT / "core" / "constitution" / "articles"
              / "005-amendment-process.md").read_text(encoding="utf-8")
        assert "لا تقل عن 90 يومًا" in نص


class Testحارسُالصياغةِالملكيّة:
    """القاعدةُ الذهبيّة: صياغاتٌ محرَّمةٌ لا تعود، ولا تُهرَّب بتشكيل."""

    def _افحص(self, root: Path, name: str, content: str) -> list:
        (root / "core").mkdir(exist_ok=True)
        (root / "core" / name).write_text(content, encoding="utf-8")
        report = recon.Report()
        recon.check_royal_supremacy_language(report, root)
        return [f for f in report.findings if f.code == "RECON-009"]

    # ROYAL-LANG-EXEMPT: عيّناتُ الاختبارِ نفسُها — تُرصَد لتُمنَع، لا لتُقرَّر.
    @pytest.mark.parametrize("جملة", [
        "الملك لا سلطة له على الخزانة.",  # ROYAL-LANG-EXEMPT
        "لا سلطة للملك في هذا الباب.",  # ROYAL-LANG-EXEMPT
        "الملك لا يستطيع رد القرار.",  # ROYAL-LANG-EXEMPT
        "المجلس أعلى من الملك.",  # ROYAL-LANG-EXEMPT
        "قرار المجلس لا يمكن إبطاله.",  # ROYAL-LANG-EXEMPT
    ])
    def test_الصياغةُ_المحرَّمةُ_تُرصَد(self, tmp_path: Path, جملة: str):
        found = self._افحص(tmp_path, "x.md", f"# نص\n{جملة}\n")
        assert len(found) == 1, f"لم تُرصَد: {جملة}"
        assert "الثاني عشر" in found[0].rule

    def test_التشكيلُ_لا_يُهرِّبُ_الصياغة(self, tmp_path: Path):
        """حركةٌ واحدةٌ كانت تكفي للإفلات لو قيس النصُّ بحرفه."""
        assert len(self._افحص(tmp_path, "y.md", "# نص\nالملكُ لا سلطةَ له.\n")) == 1  # ROYAL-LANG-EXEMPT

    def test_السطرُ_الموسومُ_بالاستثناءِ_يُقبَل(self, tmp_path: Path):
        محتوى = f"# نص\nالملك لا سلطة له. <!-- {recon.EXEMPTION_MARKER}: تحريمُها -->\n"  # ROYAL-LANG-EXEMPT
        assert self._افحص(tmp_path, "z.md", محتوى) == []

    def test_النصُّ_السليمُ_لا_يُرصَد(self, tmp_path: Path):
        سليم = "# نص\nالملك صاحب السيادة العليا وله حق الإبطال.\n"
        assert self._افحص(tmp_path, "w.md", سليم) == []

    def test_المستودعُ_الحقيقيُّ_خالٍ_من_الصياغاتِ_المحرَّمة(self):
        """البوّابةُ الفعليّة: لا يُدفَع كودٌ يعيد الصياغةَ المحرَّمة."""
        report = recon.Report()
        recon.check_royal_supremacy_language(report, REPO_ROOT)
        مخالفات = [f"{f.subject} — {f.measured}" for f in report.findings]
        assert مخالفات == [], "صياغاتٌ محرَّمةٌ عادت إلى المستودع"


class Testبصمةٌليستتوقيعًا:
    """ثغرةٌ مُثبَتة: جدولُ بصماتِ SHA-256 كان يُقرأ توقيعًا فيُعفي المرسوم."""

    def test_بصمةُ_ست_عشريّةٍ_وحدَها_ليست_توقيعًا(self):
        نص = "# مرسوم ملكي\n| ملف | " + "a" * 64 + " |\n"
        assert not recon._has_signature_material(نص)

    def test_كتلةٌ_موسومةٌ_بالتوقيعِ_تُقبَل(self):
        نص = "# مرسوم ملكي\nEd25519 signature: " + "b" * 64 + "\n"
        assert recon._has_signature_material(نص)

    def test_مرجعُ_ملفِّ_توقيعٍ_يُقبَل(self):
        assert recon._has_signature_material("انظر ملف التوقيع المرفق")

    def test_مرسومُ_AMD_003_يُعلَنُ_غيرَ_موقَّعٍ_لا_موقَّعًا(self):
        """لا يُصطنع توقيعٌ ولا يُخفى غيابُه — والفحصُ يقولها صريحًا."""
        report = recon.reconcile()
        subjects = [f.subject for f in report.findings if f.code == "RECON-003"]
        assert any("AMD-003" in s for s in subjects), (
            "المرسومُ غيرُ موقَّعٍ Ed25519 وينبغي أن يُرفَع لا أن يُعفى"
        )
