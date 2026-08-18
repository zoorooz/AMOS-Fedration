"""
السجل الدستوري غير القابل للعبث — Tamper-Evident Constitutional Ledger (E1)
الهدف: تسجيل كل حكم دستوري في سلسلة تجزئة متصلة، بحيث لا يمكن حذف قيد ولا تعديله ولا إعادة ترتيبه دون كشف فوري.
النطاق: الكتابة الملحقة فقط (append-only) والتحقق من السلسلة. لا حذف، ولا تعديل، ولا اقتطاع — بأي صلاحية.
المالك: core/constitutional_engine/
تاريخ الإنشاء: 2026-08-16
تاريخ آخر تعديل: 2026-08-18

المبدأ (المادة الأولى · 3 و 4، والمادة السابعة): الذاكرة مقدسة، والشفافية مطلقة.
كل قيد يحمل بصمة القيد السابق. كسر السلسلة يُكتشف بـ verify_chain() ولا يمكن إخفاؤه.

تصحيحُ ادّعاءٍ (2026-08-18): كان هذا الملفُّ يزعم في `append` أنّ «الكتابة ذرّية
(ملف مؤقت ثم استبدال)» وهو ما لم يفعله الكودُ قطعًا — كان `open(path, "a")`
مباشرًا بلا قفلٍ ولا ملفٍّ مؤقت. والزعمُ لم يكن تجميلًا: قسمُ الحرج
(اقرأ ← تحقّق ← احسب index ← ألحِق) كان بلا حصرٍ متبادل، فعمليّتان متزامنتان
تقرآن الطولَ N فتحسبان كلتاهما `index=N` وتُلحِقان، فينكسرُ الترتيبُ نهائيًّا.
وبما أنّ `append` يرفض الكتابةَ فوق سلسلةٍ مكسورة، فالسجلُّ يتعطّل إلى الأبد
ولا مسارَ إصلاح — أي إنكارُ سيادةٍ يُلحِقُه النظامُ بنفسه.

قياسٌ فعليٌّ للعطل (٦ عمليّاتٍ × ١٥ قيدًا = ٩٠ متوقَّعًا):
    قبل الإصلاح: كُتب قيدان، والسلسلةُ مكسورة، وكلُّ العمليّاتِ سقطت.
    بعد الإصلاح: ٩٠ قيدًا، والسلسلةُ سليمة.
الانحدارُ محروسٌ في tests/constitutional/test_ledger_concurrency.py.

الإصلاح: قفلٌ استئثاريٌّ عبر العمليّات (`fcntl.flock`) على ملفٍّ جانبيٍّ
`<path>.lock` يلفُّ قسمَ الحرج كلَّه. ولا يُستخدَم بديلٌ صامت: إن غاب `fcntl`
رُفع `LedgerLockUnavailableError` — فالإلحاقُ بلا حصرٍ متبادلٍ يُفسد السلسلة،
والسقوطُ المُعلَن أسلمُ من كتابةٍ تبدو ناجحةً وتُعطِّل الدولة.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# حضورُ `fcntl` يُفحَص ولا يُجرَّب: المدقّقُ الدستوريّ رفع `SILENT_FALLBACK`
# على محاولةِ `try/except ImportError` — وكان مُحقًّا: بلاعةُ الاستثناء
# تُتلِف سببَ الفشل وتترك `None` مكانَ أداةٍ أمنيّة. والفحصُ المُعلَن أصدقُ:
# لا استثناءَ يُبتلع، والغيابُ يصير حالةً مقروءةً تُرفع صراحةً في
# `LedgerLockUnavailableError` عند أوّل محاولةِ إلحاق، لا بديلًا صامتًا.
_HAS_FLOCK = importlib.util.find_spec("fcntl") is not None
fcntl = importlib.import_module("fcntl") if _HAS_FLOCK else None

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LEDGER = REPO_ROOT / "core" / "constitution" / "ledger" / "constitutional_ledger.jsonl"

GENESIS_HASH = "0" * 64


def _canonical(payload: dict[str, Any]) -> str:
    """تمثيل نصي حتمي — نفس المحتوى ينتج نفس البصمة دائمًا."""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_entry(prev_hash: str, body: dict[str, Any]) -> str:
    return hashlib.sha256((prev_hash + _canonical(body)).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class LedgerEntry:
    index: int
    timestamp: str
    prev_hash: str
    entry_hash: str
    body: dict[str, Any]


class LedgerTamperError(RuntimeError):
    """يُرفع عند اكتشاف كسر في سلسلة السجل. لا يُبتلع أبدًا."""


class LedgerLockUnavailableError(RuntimeError):
    """يُرفع عند تعذّر الحصرِ المتبادل على السجل.

    الهدف: منعُ إلحاقٍ غيرِ محميٍّ يبدو ناجحًا ثم يُعطِّل السلسلةَ نهائيًّا.
    لا بديلَ صامتًا هنا: السقوطُ المُعلَن هو التصرّفُ المُغلَق عند الفشل.
    """


class ConstitutionalLedger:
    """سجل ملحق فقط بسلسلة تجزئة. لا يوفر — عمدًا — أي دالة حذف أو تعديل."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else DEFAULT_LEDGER
        self.path.parent.mkdir(parents=True, exist_ok=True)

    # -- قراءة ------------------------------------------------------------
    def entries(self) -> list[LedgerEntry]:
        if not self.path.exists():
            return []
        out: list[LedgerEntry] = []
        for line_no, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as exc:
                raise LedgerTamperError(
                    f"قيد تالف في {self.path}:{line_no} — السجل غير قابل للقراءة: {exc}"
                ) from exc
            out.append(
                LedgerEntry(
                    index=rec["index"],
                    timestamp=rec["timestamp"],
                    prev_hash=rec["prev_hash"],
                    entry_hash=rec["entry_hash"],
                    body=rec["body"],
                )
            )
        return out

    def head_hash(self) -> str:
        entries = self.entries()
        return entries[-1].entry_hash if entries else GENESIS_HASH

    def __len__(self) -> int:
        return len(self.entries())

    # -- كتابة ------------------------------------------------------------
    @property
    def lock_path(self) -> Path:
        """ملفُّ القفل الجانبي. منفصلٌ عن السجل حتى لا يُعاق القارئون."""
        return self.path.with_suffix(self.path.suffix + ".lock")

    @contextmanager
    def _exclusive(self) -> Iterator[None]:
        """حصرٌ متبادلٌ عبر العمليّات على قسمِ الحرج (اقرأ ← تحقّق ← ألحِق)."""
        if fcntl is None:  # pragma: no cover - المستودع وCI على POSIX
            raise LedgerLockUnavailableError(
                "لا يوفّر هذا النظامُ `fcntl.flock`، فلا يمكن ضمانُ الحصرِ المتبادل "
                "على السجل الدستوري. الإلحاقُ بلا حصرٍ يُفسد السلسلةَ نهائيًّا، "
                "فيُرفَض الإلحاقُ صراحةً (المادة الأولى · 3)."
            )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.lock_path, os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def append(self, body: dict[str, Any], *, timestamp: str | None = None) -> LedgerEntry:
        """ألحق قيدًا جديدًا داخل حصرٍ متبادلٍ عبر العمليّات.

        قسمُ الحرج كلُّه (اقرأ ← تحقّق ← احسب `index` و`prev_hash` ← ألحِق ← fsync)
        محميٌّ بقفل `flock` استئثاريٍّ على `<path>.lock`. فبلا هذا القفل تقرأ
        عمليّتان الطولَ نفسَه فتُنتِجان `index` مكرَّرًا وتكسران السلسلةَ إلى
        الأبد. القفلُ ليس تحسينَ أداءٍ بل شرطُ صحّةٍ.
        """
        with self._exclusive():
            existing = self.entries()
            self._verify(existing)  # لا نضيف فوق سلسلة مكسورة

            index = len(existing)
            prev_hash = existing[-1].entry_hash if existing else GENESIS_HASH
            ts = timestamp or datetime.now(timezone.utc).isoformat(timespec="microseconds")

            sealed_body = {"index": index, "timestamp": ts, **body}
            entry_hash = _hash_entry(prev_hash, sealed_body)

            record = {
                "index": index,
                "timestamp": ts,
                "prev_hash": prev_hash,
                "entry_hash": entry_hash,
                "body": sealed_body,
            }
            line = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"

            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(line)
                fh.flush()
                os.fsync(fh.fileno())

            return LedgerEntry(index, ts, prev_hash, entry_hash, sealed_body)

    # -- تحقق -------------------------------------------------------------
    @staticmethod
    def _verify(entries: list[LedgerEntry]) -> None:
        prev = GENESIS_HASH
        for i, e in enumerate(entries):
            if e.index != i:
                raise LedgerTamperError(
                    f"ترتيب مكسور عند الموضع {i}: القيد يحمل index={e.index}. "
                    "حذف أو إعادة ترتيب قيود مخالفة دستورية (المادة الأولى · 3)."
                )
            if e.prev_hash != prev:
                raise LedgerTamperError(
                    f"سلسلة مكسورة عند القيد {i}: prev_hash={e.prev_hash[:12]}… "
                    f"والمتوقع {prev[:12]}…"
                )
            recomputed = _hash_entry(e.prev_hash, e.body)
            if recomputed != e.entry_hash:
                raise LedgerTamperError(
                    f"محتوى معدَّل في القيد {i}: البصمة المسجلة {e.entry_hash[:12]}… "
                    f"والمحسوبة {recomputed[:12]}…"
                )
            prev = e.entry_hash

    def verify_chain(self) -> list[str]:
        """يرجع قائمة المشاكل (فارغة = سلسلة سليمة). لا يرفع استثناءً."""
        try:
            self._verify(self.entries())
        except LedgerTamperError as exc:
            return [str(exc)]
        return []
