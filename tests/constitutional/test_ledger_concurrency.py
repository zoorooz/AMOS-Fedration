"""
اختبار تزامن السجل الدستوري — Constitutional Ledger Concurrency (E1)
الهدف: إثبات أن الإلحاق المتزامن عبر عمليّاتٍ متعددة لا يكسر سلسلة التجزئة، وأن السجل لا يمكن تعطيله بالتزامن.
النطاق: core/constitutional_engine/ledger.py — قسم الحرج (اقرأ ← تحقّق ← ألحِق) وحده.
المالك: core/constitutional_engine/
تاريخ الإنشاء: 2026-08-18
تاريخ آخر تعديل: 2026-08-18

السببُ الذي أنشأ هذا الملف — عطلٌ مقيسٌ لا مفترَض:
    شُغِّلت حزمتا الاختبارات (جذر المستودع + الخدمات الفدرالية) بالتوازي على
    السجل الافتراضي نفسه، فسقط ٨٧ اختبارًا بـ `LedgerTamperError` واحد.
    والسببُ ليس عبثًا بشريًّا بل أنّ `append` كان بلا حصرٍ متبادل: عمليّتان
    تقرآن الطولَ N فتحسبان كلتاهما `index=N`، فينكسرُ الترتيبُ نهائيًّا.
    وبما أنّ `append` يرفض الكتابةَ فوق سلسلةٍ مكسورة، فالسجلُّ يتعطّل إلى
    الأبد — إنكارُ سيادةٍ يُلحِقُه النظامُ بنفسه بلا خصمٍ خارجي.

قياسُ العطل قبل الإصلاح (٦ عمليّاتٍ × ١٥ قيدًا = ٩٠ متوقَّعًا):
    كُتب قيدان فقط، والسلسلةُ مكسورة، وسقطت العمليّاتُ الستُّ كلُّها.

ما يحرسه هذا الملف: أنّ السلسلةَ تبقى سليمةً وكاملةً تحت التزامن، وأنّ
الحصرَ المتبادل شرطُ صحّةٍ لا تحسينُ أداء، وأنّ الحراسةَ ضدّ العبث لم تُخفَّف
لتمرير التزامن.
"""

from __future__ import annotations

import json
import multiprocessing as mp
from pathlib import Path

import pytest

from core.constitutional_engine.ledger import (
    GENESIS_HASH,
    ConstitutionalLedger,
    LedgerTamperError,
)

# ستُّ عمليّاتٍ × خمسةَ عشرَ قيدًا — العددُ نفسُه الذي أعاد إنتاجَ العطل قبل الإصلاح.
PROCESSES = 6
APPENDS_PER_PROCESS = 15
EXPECTED_TOTAL = PROCESSES * APPENDS_PER_PROCESS


def _append_batch(args: tuple[str, int]) -> tuple[int, str]:
    """يُلحِق دفعةَ قيودٍ من عمليّةٍ مستقلّة. يُرجع (العدد المُلحَق، الخطأ إن وقع)."""
    path, worker_id = args
    ledger = ConstitutionalLedger(Path(path))
    appended = 0
    for seq in range(APPENDS_PER_PROCESS):
        try:
            ledger.append({"actor": f"worker-{worker_id}", "seq": seq})
            appended += 1
        except Exception as exc:  # noqa: BLE001 - الخطأُ يُعاد ولا يُبتلع
            return appended, f"{type(exc).__name__}: {exc}"
    return appended, ""


class Testالإلحاقالمتزامن:
    """الإلحاقُ من عمليّاتٍ متعدّدةٍ لا يكسر السلسلةَ ولا يفقد قيدًا."""

    def test_ستُّ_عمليّاتٍ_متزامنةٍ_تُنتِج_سلسلةً_سليمةً_كاملة(self, tmp_path: Path):
        """٩٠ قيدًا من ٦ عمليّات: لا فقدَ، ولا تكرارَ index، ولا كسرَ سلسلة."""
        ledger_path = tmp_path / "concurrent_ledger.jsonl"
        args = [(str(ledger_path), i) for i in range(PROCESSES)]

        # `spawn` مقصود: يضمن عمليّاتٍ مستقلّةً فعلًا لا نسخًا تشترك حالةَ الأب،
        # فالعطلُ الأصلي كان بين عمليّاتٍ لا خيوط.
        with mp.get_context("spawn").Pool(PROCESSES) as pool:
            results = pool.map(_append_batch, args)

        errors = [err for _, err in results if err]
        assert not errors, f"سقطت عمليّاتٌ أثناء الإلحاق المتزامن: {errors}"

        total_appended = sum(count for count, _ in results)
        assert total_appended == EXPECTED_TOTAL, (
            f"أُلحِق {total_appended} قيدًا والمتوقَّع {EXPECTED_TOTAL} — فُقِد قيدٌ تحت التزامن."
        )

        ledger = ConstitutionalLedger(ledger_path)
        assert ledger.verify_chain() == [], "السلسلةُ مكسورةٌ بعد إلحاقٍ متزامن."

        entries = ledger.entries()
        assert len(entries) == EXPECTED_TOTAL, (
            f"السجلُّ يحمل {len(entries)} قيدًا والمتوقَّع {EXPECTED_TOTAL}."
        )
        # الترتيبُ متّصلٌ بلا ثغرةٍ ولا تكرار — هذا بعينه ما انكسر قبل الإصلاح.
        assert [e.index for e in entries] == list(range(EXPECTED_TOTAL))

    def test_كلُّ_قيدٍ_يشير_إلى_بصمة_سابقه_تحت_التزامن(self, tmp_path: Path):
        """سلسلةُ التجزئة متّصلةٌ حلقةً حلقةً، لا مجرّدَ عدٍّ صحيح."""
        ledger_path = tmp_path / "chain_links.jsonl"
        with mp.get_context("spawn").Pool(PROCESSES) as pool:
            pool.map(_append_batch, [(str(ledger_path), i) for i in range(PROCESSES)])

        entries = ConstitutionalLedger(ledger_path).entries()
        prev = GENESIS_HASH
        for entry in entries:
            assert entry.prev_hash == prev, f"حلقةٌ مقطوعةٌ عند القيد {entry.index}."
            prev = entry.entry_hash

    def test_كلُّ_القيود_المُلحَقة_موجودةٌ_ولا_عمليّةَ_صامتةُ_الفقد(self, tmp_path: Path):
        """كلُّ عمليّةٍ يظهر لها ١٥ قيدًا — لا رابحَ يكتب وخاسرَ يُبتلع صمتًا."""
        ledger_path = tmp_path / "no_lost_writes.jsonl"
        with mp.get_context("spawn").Pool(PROCESSES) as pool:
            pool.map(_append_batch, [(str(ledger_path), i) for i in range(PROCESSES)])

        entries = ConstitutionalLedger(ledger_path).entries()
        for worker_id in range(PROCESSES):
            actor = f"worker-{worker_id}"
            count = sum(1 for e in entries if e.body.get("actor") == actor)
            assert count == APPENDS_PER_PROCESS, (
                f"العمليّة {actor} كتبت {count} قيدًا والمتوقَّع {APPENDS_PER_PROCESS}."
            )


class Testالحراسةلمتُخفَّف:
    """الحصرُ المتبادل أُضيف دون إضعافِ كشفِ العبث."""

    def test_العبثُ_اليدويُّ_ما_زال_يُكتشَف(self, tmp_path: Path):
        """تعديلُ جسمِ قيدٍ بعد كتابته يُكشَف — القفلُ لم يُسكِت المدقّق."""
        ledger_path = tmp_path / "tamper_still_caught.jsonl"
        ledger = ConstitutionalLedger(ledger_path)
        for i in range(3):
            ledger.append({"actor": "royal", "seq": i})
        assert ledger.verify_chain() == []

        # العبثُ يُجرى على البنية لا على النصّ: استبدالُ نصٍّ حرفيٍّ يعتمد على
        # فواصل `json.dumps` فيمرّ الاختبارُ أو يسقط لسببٍ لا علاقةَ له بالعبث.
        lines = ledger_path.read_text(encoding="utf-8").splitlines()
        record = json.loads(lines[1])
        record["body"]["seq"] = 999  # الجسمُ تغيّر والبصمةُ المسجّلة لم تتغيّر
        lines[1] = json.dumps(record, ensure_ascii=False, sort_keys=True)
        ledger_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        assert ledger.verify_chain() != [], "عبثٌ بالمحتوى لم يُكتشَف."
        with pytest.raises(LedgerTamperError):
            ledger.append({"actor": "royal", "seq": 3})

    def test_ملفُّ_القفل_جانبيٌّ_لا_يُلوِّث_السجل(self, tmp_path: Path):
        """القفلُ في ملفٍّ منفصل، فلا يدخل بايتٌ واحدٌ منه إلى السجل."""
        ledger_path = tmp_path / "lock_is_sidecar.jsonl"
        ledger = ConstitutionalLedger(ledger_path)
        ledger.append({"actor": "royal", "seq": 0})

        assert ledger.lock_path != ledger.path
        assert ledger.lock_path.exists(), "لم يُنشَأ ملفُّ القفل."
        assert len(ledger.entries()) == 1
        assert ledger.verify_chain() == []
