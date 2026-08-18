#!/usr/bin/env python3
"""
سجلُّ الأدلّة — Evidence Registry (المرحلة 1L)
الهدف: جمعُ أدلّةٍ آليّةِ المنشأ على قدرات الدولة، وحفظُها غيرَ قابلةٍ للتعديل، وتقديمُها
       للمدقّق الدستوريّ ليقرّر هو حالةَ القدرة — فالسجلُّ يجمع ولا يحكم.
النطاق: tools/governance — لا يستورده كودُ التشغيل، ولا يمنح صلاحيّةً، ولا يعلن حالة.
المالك: tools/governance
تاريخ الإنشاء: 2026-08-18
تاريخ آخر تعديل: 2026-08-18

## لِمَ وُجد هذا الملف — عطلٌ مقيسٌ في المدقّق نفسه

`truth_audit.py` كان يقرّر عمودَي «مُختبَر» و«منشور» هكذا حرفيًّا:

    rep.test_refs = len(re.findall(rf"\\b{dom}\\b", self.test_corpus))
    rep.deployed  = bool(re.search(rf"\\b{dom}\\b", self.deploy_corpus))

أي أنّ الإقليم يُعَدُّ **مُختبَرًا** لأنّ اسمَه ظهر ككلمةٍ في نصِّ ملفّات الاختبار،
و**منشورًا** لأنّ اسمَه ظهر في نصِّ Dockerfile أو CI. فكتابةُ كلمة `core` في
تعليقٍ داخل أيّ اختبارٍ تكفي لإصدار شهادةِ «مُختبَر» لإقليمٍ كامل، بلا اختبارٍ
واحدٍ شُغِّل ولا نجح. وهذا ليس قياسًا ضعيفًا بل **تصنيعُ حقيقة**: المدقّقُ
يُنتِج الدليلَ الذي يحكم به، فيصير الحكمُ دورًا مغلقًا لا يمسّ الواقع.

القياسُ الذي أثبت العطل: `core` وحدها ترد آلافَ المرّات في مجموعة الاختبارات
بحكم كونها اسمَ حزمةٍ في كلّ سطر استيراد — فالعدّادُ لا يقيس تغطيةً بل شعبيّةَ
كلمة. ولا يمكن لإقليمٍ أن يخسر عمودَ «مُختبَر» أبدًا، فالعمودُ بلا قيمةٍ إخباريّة.

## المبدأ الذي يحكم هذا الملف

الدليلُ **يُجمَع** من مُخرَجاتِ آلاتٍ شُغِّلت فعلًا (تقارير pytest، تقارير
التغطية، تحقّقُ سلاسلِ التجزئة، آثارُ التشغيل، بيانُ النشر)، ثمّ يُقيَّد بصمةً
محتومةً في سجلٍّ متسلسلِ التجزئة لا يُعدَّل بعد التثبيت. والمدقّقُ الدستوريُّ
هو وحده من يقرأ السجلَّ ويقرّر الحالة.

ثلاثةُ منوعاتٍ صريحة:
  ١) **لا إعلانَ يدويًّا**: كلُّ دليلٍ يحمل حقلَ `producer` وطريقةَ إنتاجه، ولا
     توجد واجهةٌ تقول «اعتبر هذا مُختبَرًا». مصدرُ كلِّ قيدٍ ملفُّ مخرجاتٍ آليّ.
  ٢) **لا بديلَ صامتًا**: غيابُ الدليل ليس نجاحًا ولا فشلًا مجهولًا، بل
     `EvidenceAbsent` صريح — والمدقّقُ يقرأه إغلاقًا للقدرة لا تجاهلًا لها.
  ٣) **لا تعديلَ بعد التثبيت**: كلُّ قيدٍ يرتبط ببصمة سابقه، فأيُّ تحريرٍ لاحقٍ
     يكسر السلسلةَ ويُكشَف بـ`verify_chain()`.

## ما لا يفعله هذا الملف

لا يقول PROVEN، ولا يحسب نسبةَ إنجاز، ولا يمنح صلاحيّة، ولا يُصلح عطلًا.
هو ميزانٌ يزن ما وُضع فيه، ولا يخلق ما لم يوضع.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib
import importlib.util
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# القفلُ يُفحَص ولا يُجرَّب — الاستثناءُ المُبتلَع يُتلِف سببَ الفشل.

_HAS_FLOCK = importlib.util.find_spec("fcntl") is not None
fcntl = importlib.import_module("fcntl") if _HAS_FLOCK else None

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY = REPO_ROOT / "docs" / "audit" / "evidence" / "evidence_registry.jsonl"

GENESIS_HASH = "0" * 64

# الأقاليم الاثنا عشر — تُقرأ من المدقّق كي لا يتشعّب مصدرُ الحقيقة.
DOMAINS = ["core", "royal", "federal", "states", "institutions", "agents",
           "interfaces", "runtime", "ops", "tools", "docs", "tests"]


# ---------------------------------------------------------------------------
# أنواعُ الدليل — مغلقةٌ قصدًا
# ---------------------------------------------------------------------------
# كلُّ نوعٍ هنا له مُنتِجٌ آليٌّ واحدٌ معروف. وإضافةُ نوعٍ جديدٍ تعني كتابةَ
# مُلقِّطٍ (collector) يقرأ مخرجاتِ آلةٍ حقيقيّة — لا حقلًا نصيًّا يُملأ يدويًّا.
EVIDENCE_KINDS = {
    "TEST_RUN":        "تشغيلُ اختباراتٍ فعليٌّ مع أسماء الاختبارات ونتائجها",
    "COVERAGE":        "تغطيةُ فروعٍ مقيسةٌ من مخرَج coverage",
    "CHAIN_VERIFY":    "تحقّقُ سلسلةِ تجزئةٍ على سجلٍّ حقيقي",
    "RUNTIME_TRACE":   "أثرُ تشغيلٍ مسجَّلٌ من نظامٍ يعمل",
    "PERSISTENCE":     "قراءةٌ بعد كتابةٍ على مخزنٍ دائمٍ حقيقي",
    "SECURITY_CHECK":  "فحصٌ أمنيٌّ شُغِّل ونتيجتُه",
    "DEPLOYMENT":      "بيانُ نشرٍ يشهد أنّ الشيء شُغِّل في بيئةٍ ما",
    "RECOVERY_DRILL":  "تمرينُ استرجاعٍ نُفِّذ ونتيجتُه",
}

VERDICTS = ("PASS", "FAIL", "INCONCLUSIVE")


class EvidenceIntegrityError(RuntimeError):
    """يُرفع عند كسرِ سلسلةِ الأدلّة — دليلٌ عُدِّل بعد تثبيته.

    لا يُعالَج بإعادة الكتابة: سجلُّ أدلّةٍ يُصلَّح بالكتابة فوقه ليس سجلَّ أدلّة.
    """


class EvidenceLockUnavailableError(RuntimeError):
    """يُرفع عند تعذّرِ الحصرِ المتبادل على سجلِّ الأدلّة.

    السببُ مقيسٌ في السجلِّ الدستوريّ: إلحاقٌ متزامنٌ بلا حصرٍ يكسر السلسلةَ
    نهائيًّا. فالسقوطُ المُعلَن هو التصرّفُ المُغلَق عند الفشل.
    """


class EvidenceAbsent(LookupError):
    """لا دليلَ على ما سُئل عنه.

    وليس هذا فشلًا في القدرة ولا نجاحًا لها: هو **غيابُ معرفة**. ويُرفع صريحًا
    كي لا يُقرأ الغيابُ ضمنًا نجاحًا — وهو أصلُ كلِّ ثقةٍ كاذبة.
    """


@dataclass(frozen=True)
class EvidenceRecord:
    """قيدُ دليلٍ واحدٌ غيرُ قابلٍ للتعديل بعد التثبيت."""

    index: int
    kind: str
    domain: str
    capability: str
    verdict: str
    producer: str          # الأمرُ أو الأداةُ التي أنتجت الدليل
    produced_at: str       # زمنُ إنتاج الدليل بحسب مُنتِجه
    source_artifact: str   # مسارُ ملفِّ المخرجات الذي قُرئ
    source_digest: str     # بصمةُ ذلك الملفّ — تربط القيدَ بمخرَجٍ بعينه
    detail: dict[str, Any]
    prev_hash: str
    entry_hash: str

    def payload(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("entry_hash")
        return d


def _canonical(obj: Any) -> str:
    """تمثيلٌ محتومٌ للتجزئة — الترتيبُ مثبَّتٌ فلا تختلف البصمةُ بين جهازٍ وآخر."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def compute_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def file_digest(path: Path) -> str:
    """بصمةُ ملفِّ المخرجات — بها يُربَط القيدُ بمخرَجٍ بعينه لا بمزاعمَ عنه."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class EvidenceRegistry:
    """سجلٌّ متسلسلُ التجزئةٍ للأدلّة، إلحاقيٌّ فقط.

    البنيةُ مأخوذةٌ قصدًا من `ConstitutionalLedger` — بما فيها الحصرُ المتبادل
    الذي أُصلح فيه بعد قياسِ عطلِ تزامنٍ حقيقيّ — كي لا يُبنى نمطُ سجلٍّ ثانٍ
    مخالفٍ للأوّل، ولا يُعاد اكتشافُ العطل نفسِه في مكانٍ ثانٍ.
    """

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else DEFAULT_REGISTRY

    # -- الحصرُ المتبادل ----------------------------------------------------
    @property
    def lock_path(self) -> Path:
        return self.path.with_name(self.path.name + ".lock")

    @contextmanager
    def _exclusive(self) -> Iterator[None]:
        if fcntl is None:  # pragma: no cover - المستودع وCI على POSIX
            raise EvidenceLockUnavailableError(
                "لا يوفّر هذا النظامُ `fcntl.flock`، فلا يمكن ضمانُ الحصرِ المتبادل "
                "على سجلِّ الأدلّة. الإلحاقُ بلا حصرٍ يكسر السلسلةَ نهائيًّا، "
                "فيُرفَض الإلحاقُ صراحةً."
            )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.lock_path, os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    # -- القراءة ------------------------------------------------------------
    def records(self) -> list[EvidenceRecord]:
        if not self.path.exists():
            return []
        out: list[EvidenceRecord] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                out.append(EvidenceRecord(**json.loads(line)))
        return out

    def verify_chain(self) -> list[str]:
        """يُرجع قائمةَ الكسور. القائمةُ الفارغةُ تعني سلسلةً سليمة."""
        problems: list[str] = []
        prev = GENESIS_HASH
        for i, rec in enumerate(self.records()):
            if rec.index != i:
                problems.append(f"القيد {i}: ترتيبٌ مخالف (index={rec.index})")
            if rec.prev_hash != prev:
                problems.append(f"القيد {i}: حلقةٌ مقطوعةٌ عن سابقه")
            if compute_hash(rec.payload()) != rec.entry_hash:
                problems.append(f"القيد {i}: محتوىً عُدِّل بعد التثبيت")
            prev = rec.entry_hash
        return problems

    # -- الإلحاق ------------------------------------------------------------
    def append(
        self,
        *,
        kind: str,
        domain: str,
        capability: str,
        verdict: str,
        producer: str,
        produced_at: str,
        source_artifact: str,
        source_digest: str,
        detail: dict[str, Any] | None = None,
    ) -> EvidenceRecord:
        """يُثبِّت قيدَ دليلٍ واحدًا. يرفض القيدَ المخالفَ للنوعِ أو الحكمِ المعروف."""
        if kind not in EVIDENCE_KINDS:
            raise ValueError(
                f"نوعُ دليلٍ غيرُ معروف: {kind!r}. "
                f"الأنواعُ المسموحة: {sorted(EVIDENCE_KINDS)}"
            )
        if verdict not in VERDICTS:
            raise ValueError(f"حكمٌ غيرُ معروف: {verdict!r}. المسموح: {VERDICTS}")
        if not producer or not source_artifact or not source_digest:
            # قيدٌ بلا مُنتِجٍ ولا مخرَجٍ مبصومٍ هو إعلانٌ يدويّ — وهو ممنوع.
            raise ValueError(
                "كلُّ قيدٍ يلزمه `producer` و`source_artifact` و`source_digest`: "
                "الدليلُ يُجمَع من مخرَجِ آلةٍ ولا يُعلَن يدويًّا."
            )

        with self._exclusive():
            existing = self.records()
            problems = self._verify(existing)
            if problems:
                raise EvidenceIntegrityError(
                    "سلسلةُ الأدلّة مكسورةٌ، فلا يُلحَق فوقها: " + "؛ ".join(problems[:3])
                )
            prev = existing[-1].entry_hash if existing else GENESIS_HASH
            payload = {
                "index": len(existing),
                "kind": kind,
                "domain": domain,
                "capability": capability,
                "verdict": verdict,
                "producer": producer,
                "produced_at": produced_at,
                "source_artifact": source_artifact,
                "source_digest": source_digest,
                "detail": detail or {},
                "prev_hash": prev,
            }
            rec = EvidenceRecord(**payload, entry_hash=compute_hash(payload))
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(_canonical(asdict(rec)) + "\n")
            return rec

    @staticmethod
    def _verify(records: list[EvidenceRecord]) -> list[str]:
        problems: list[str] = []
        prev = GENESIS_HASH
        for i, rec in enumerate(records):
            if rec.index != i or rec.prev_hash != prev \
                    or compute_hash(rec.payload()) != rec.entry_hash:
                problems.append(f"القيد {i}")
            prev = rec.entry_hash
        return problems

    # -- الاستعلام (ما يقرأه المدقّق) --------------------------------------
    def verdict_of(self, kind: str, domain: str) -> str:  # noqa: D401
        """حكمُ أحدثِ دليلٍ من نوعٍ لإقليم، أو `"ABSENT"` إن لم يوجد دليل.

        هذه هي الاستعلامةُ الأساسُ، و`"ABSENT"` قيمةٌ صريحةٌ من مجالِ القيم لا
        فراغٌ ولا `None`. ولا يُبتلع هنا استثناءٌ: الغيابُ يُقرَّر بالفحص لا
        بالتقاطِ خطأ — فبلاعةُ الاستثناء تخفي فشلَ مصدرِ الحقيقة كما تخفي غيابَه.
        """
        matches = [r for r in self.records() if r.kind == kind and r.domain == domain]
        if not matches:
            return "ABSENT"
        # لكلِّ قدرةٍ آخرُ حكمٍ لها: فإصلاحٌ لاحقٌ يرفع سقوطًا سابقًا، ولا
        # يُحكَم على الإقليمِ بأثرِ قيدٍ عُولج.
        latest_per_capability: dict[str, str] = {}
        for r in matches:
            latest_per_capability[r.capability] = r.verdict
        verdicts = set(latest_per_capability.values())
        # أيُّ سقوطٍ يُسقِط الإقليمَ كلَّه — إغلاقٌ عند الفشل: مجالٌ واحدٌ ساقطٌ
        # لا يُغطّيه نجاحُ غيرِه، ولا يُختار أحدُ الحكمَين بالأحدثيّةِ وحدها.
        if "FAIL" in verdicts:
            return "FAIL"
        if "INCONCLUSIVE" in verdicts:
            return "INCONCLUSIVE"
        return "PASS" if "PASS" in verdicts else "ABSENT"

    def latest(self, kind: str, domain: str) -> EvidenceRecord:
        """أحدثُ دليلٍ من نوعٍ لإقليم. يرفع `EvidenceAbsent` إن لم يوجد.

        الغيابُ يُرفَع ولا يُرجَع `None`: قيمةٌ خاليةٌ تُقرأ سهوًا نجاحًا،
        والاستثناءُ لا يُقرأ إلّا غيابًا. ومَن أراد الغيابَ قيمةً لا استثناءً
        فليستعمل `verdict_of`.
        """
        matches = [r for r in self.records() if r.kind == kind and r.domain == domain]
        if not matches:
            raise EvidenceAbsent(f"لا دليلَ {kind} للإقليم {domain}")
        return matches[-1]

    def has_passing(self, kind: str, domain: str) -> bool:
        """هل يوجد دليلٌ **ناجحٌ** من هذا النوع؟ الغيابُ = لا، والسقوطُ = لا."""
        return self.verdict_of(kind, domain) == "PASS"

    def summary(self) -> dict[str, dict[str, str]]:
        """خلاصةٌ لكلِّ إقليمٍ ونوع: الحكمُ الأحدث، أو `ABSENT` صريحًا."""
        return {
            dom: {kind: self.verdict_of(kind, dom) for kind in sorted(EVIDENCE_KINDS)}
            for dom in DOMAINS
        }


# ---------------------------------------------------------------------------
# المُلقِّطات — تقرأ مخرَجاتِ آلاتٍ شُغِّلت فعلًا
# ---------------------------------------------------------------------------
# كلُّ مُلقِّطٍ يقرأ ملفَ مخرجاتٍ أنتجته أداةٌ أخرى، ويبصمه، ويستخرج منه
# نسبةَ الأقاليم. ولا يُنتِج مُلقِّطٌ حكمًا من عنده: الحكمُ في المخرَج.

@dataclass
class Collected:
    """ما استخرجه مُلقِّطٌ قبل تثبيته في السجل."""

    kind: str
    domain: str
    capability: str
    verdict: str
    detail: dict[str, Any] = field(default_factory=dict)


def collect_from_junit(xml_path: Path,
                       repo_root: Path | None = None,
                       kind: str = "TEST_RUN",
                       ) -> tuple[list[Collected], dict[str, str]]:
    """يقرأ تقريرَ JUnit XML من pytest ويُنسِب كلَّ اختبارٍ إلى إقليمه.

    النسبةُ تُبنى على **ما يستورده ملفُّ الاختبار فعلًا**، لا على ورودِ اسمِ
    الإقليم في نصِّه ولا على موقعِه في الشجرة. فملفٌّ يقول
    `from core.constitutional_engine.ledger import ...` يشهد لإقليم `core`
    شهادةً حقيقيّةً: ذلك السطرُ يُنفَّذ، والشيفرةُ المستوردةُ تُشغَّل. أمّا ورودُ
    كلمةِ `core` في تعليقٍ فلا يشهد لشيء.

    ولا تُبنى النسبةُ على المسار: اصطلاحُ هذا المستودع `tests/constitutional/`
    و`tests/crown/` و`tests/sovereignty/` — وهي أسماءُ **فصولٍ** لا أسماءُ
    أقاليم، فلا يُستخرج منها إقليمٌ ألبتّة. (وقد افترضتُ أوّلَ مرّةٍ أنّ
    الاصطلاحَ `tests/<إقليم>/` فلم يُنسَب اختبارٌ واحدٌ من ٨٣٨، وكان الافتراضُ
    خطأً قابلًا للقياس فقيس.)

    والاختبارُ الذي يستورد أقاليمَ عدّةً يشهد لكلٍّ منها: فهو يُشغِّلها جميعًا.

    يُرجع (قائمةَ الملتقَط، بياناتِ المُنتِج).
    """
    repo_root = repo_root or REPO_ROOT
    tree = ET.parse(xml_path)
    root = tree.getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))

    # إقليم ← (ناجح، ساقط، متخطّى)
    tally: dict[str, list[int]] = {d: [0, 0, 0] for d in DOMAINS}
    timestamp = ""
    for suite in suites:
        timestamp = suite.get("timestamp") or timestamp
        for case in suite.iter("testcase"):
            doms = _domains_of_testcase(case, repo_root)
            if not doms:
                continue
            failed = any(case.find(t) is not None for t in ("failure", "error"))
            skipped = case.find("skipped") is not None
            slot = 1 if failed else (2 if skipped else 0)
            for dom in doms:
                tally[dom][slot] += 1

    collected: list[Collected] = []
    for dom, (passed, failed, skipped) in tally.items():
        if passed + failed + skipped == 0:
            continue  # لا دليلَ لهذا الإقليم — ولا يُختلق قيدٌ يقول ذلك
        collected.append(Collected(
            kind=kind,
            domain=dom,
            capability=f"{dom}: حزمةُ الاختبارات",
            verdict="PASS" if failed == 0 and passed > 0 else "FAIL",
            detail={"passed": passed, "failed": failed, "skipped": skipped},
        ))
    return collected, {"produced_at": timestamp or _now()}


# ملفّاتُ اختبارٍ وردت في التقرير ولم توجد على القرص — تُجمَع لتُبلَّغ صريحةً
# في نهاية التثبيت، فلا يُطوى نقصُ النسبة في صمت.
_ATTRIBUTION_GAPS: set[str] = set()


@lru_cache(maxsize=None)
def _package_domain_index(repo_root: Path) -> frozenset[tuple[str, str]]:
    """خريطةُ «اسمِ حزمةٍ عليا ← إقليم»، مبنيّةٌ من الشجرة لا من افتراض.

    حزمةُ الخدمات تُستورَد باسم `amos_federation` لا `federal`، لأنّها مُثبَّتةٌ
    من `federal/executive/services/src/`. فلو اكتُفي بمطابقةِ اسمِ الاستيراد
    بأسماء الأقاليم لسقطت ٥٧٥ استيرادةً في حزمةِ الخدمات كلِّها بلا نسبة، وهو
    ما وقع فعلًا قبل هذا الفهرس.

    والخريطةُ تُشتَقُّ بالبحث عن `<اسم>/__init__.py` في الشجرة ثمّ أخذِ أوّلِ
    مقطعٍ من مسارِه: فالموضعُ الحقيقيُّ للحزمة هو ما يُحدّد إقليمَها، ولا
    يُكتَب اسمٌ بيدٍ في جدولٍ يَبلى مع أوّلِ نقلٍ للمجلّد.
    """
    pairs: set[tuple[str, str]] = set()
    for init in repo_root.rglob("__init__.py"):
        rel = init.relative_to(repo_root).parts
        if len(rel) < 2 or any(x in {".git", "node_modules", ".venv"} for x in rel):
            continue
        if rel[0] in DOMAINS:
            pairs.add((init.parent.name, rel[0]))
    return frozenset(pairs)


def _resolve_domain(name: str, repo_root: Path) -> str | None:
    """إقليمُ حزمةٍ عليا: مباشرةً إن كان اسمُها إقليمًا، أو عبر الفهرس."""
    if name in DOMAINS:
        return name
    hits = {dom for pkg, dom in _package_domain_index(repo_root) if pkg == name}
    # اسمٌ يقع في إقليمين لا يُنسَب لأحدهما رجمًا بالغيب: الغموضُ يُترَك غيابًا.
    return next(iter(hits)) if len(hits) == 1 else None


@lru_cache(maxsize=None)
def _domains_imported_by(module_path: Path,
                         index_root: Path | None = None) -> frozenset[str]:
    """الأقاليمُ التي يستوردها ملفُّ اختبارٍ — تُقرأ بتحليل الشجرة لا بالتنقيب النصّي.

    التحليلُ عبر `ast` لا `grep`: سطرٌ داخل نصٍّ أو تعليقٍ يقول `import core`
    ليس استيرادًا، والمحلّلُ وحده يفرّق بين ما يُنفَّذ وما يُقرأ.
    """
    if not module_path.is_file():
        # الغيابُ يُبلَّغ ولا يُبتلَع: ملفُّ اختبارٍ ورد في تقرير JUnit ثمّ لم
        # يوجد على القرص يعني تقريرًا لا يطابق المستودع، وذلك خللٌ في مصدرِ
        # الدليل لا تفصيلٌ يُطوى.
        _ATTRIBUTION_GAPS.add(str(module_path))
        return frozenset()

    # لا `try/except SyntaxError` هنا قصدًا: ملفُّ اختبارٍ نفّذه pytest فعلًا
    # لا بدّ أن يكون قابلًا للتحليل، فإن لم يكن فالتقريرُ والمستودعُ مختلفان،
    # وابتلاعُ الخطأ يُنتِج نسبةً ناقصةً تُقرأ «لا دليل» بدل «الدليلُ معطوب».
    # فليصعد الخطأُ عاليًا ويُسقِط التثبيتَ — إغلاقٌ عند الفشل.
    tree = ast.parse(module_path.read_text(encoding="utf-8"))

    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])

    # جذرُ **الفهرس** جذرُ المستودع دائمًا، وهو غيرُ جذرِ حلِّ مسارات
    # الاختبار: حزمةُ الخدمات تُشغَّل من `federal/executive/services`، فلو
    # بُني الفهرسُ من ذلك الجذر لكان أوّلُ مقطعٍ `src` أو `tests` فلا يُطابِق
    # إقليمًا، ولسقطت نسبةُ ١١٤٩ اختبارًا. الجذران وظيفتان مختلفتان.
    resolved = {_resolve_domain(n, index_root or REPO_ROOT) for n in roots}
    return frozenset(d for d in resolved if d is not None)


def _domains_of_testcase(case: ET.Element, repo_root: Path) -> frozenset[str]:
    """أقاليمُ حالةِ اختبارٍ واحدة، عبر ملفِّها المُستخرَج من `file` أو `classname`."""
    rel = case.get("file")
    if not rel:
        cn = case.get("classname", "")
        if not cn:
            return frozenset()
        # `tests.crown.test_x.TestY` ← الصنفُ يُسقَط، والباقي مسارُ وحدة
        parts = cn.split(".")
        while parts and parts[-1][:1].isupper():
            parts.pop()
        if not parts:
            return frozenset()
        rel = "/".join(parts) + ".py"
    return _domains_imported_by(repo_root / rel, REPO_ROOT)


def _domain_of_covered_file(fname: str, sources: list[str],
                            repo_root: Path) -> str | None:
    """إقليمُ ملفٍّ مُغطّى، بحلِّ مسارِه النسبيِّ مقابلَ كلِّ `<source>`."""
    norm = fname.replace("\\", "/")
    for src in sources:
        cand = Path(src) / norm
        if not cand.is_relative_to(repo_root):
            continue
        first = cand.relative_to(repo_root).parts[0]
        if first in DOMAINS:
            return first
    return None


def collect_from_coverage_xml(xml_path: Path,
                              repo_root: Path | None = None,
                              threshold: float | None = None,
                              scope: str | None = None,
                              gate_verdict: str | None = None,
                              ) -> tuple[list[Collected], dict[str, str]]:
    """يقرأ تغطيةَ Cobertura ويحسب تغطيةَ الفروعِ لكلّ إقليمٍ من أسماء الملفّات."""
    root = ET.parse(xml_path).getroot()
    repo_root = repo_root or REPO_ROOT
    # العتبةُ تُمرَّر صريحةً ولا تُفترَض. وكانت مثبَّتةً 80٪ لكلِّ إقليمٍ، فأنتج
    # ذلك حكمًا كاذبًا: قِيست تغطيةُ `core` مُجمَّعةً بـ`--cov=core --cov=tools`
    # فجاءت 69.85٪ فحُكم عليها بالسقوطِ «مقابلَ حدِّ CI»، والحالُ أنّ CI لا
    # يقيس هذا المجموعَ أصلًا: يقيس `core.constitutional_engine` و
    # `core.sovereignty` و`core.crown` كلًّا على حدةٍ بحدِّ **90٪**، وثلاثتُها
    # تجتازه (95.21٪ · 94.20٪ · 94.48٪). فحدٌّ مخترَعٌ على مجموعٍ لا يقيسه أحدٌ
    # أنتج «ارتدادًا» لا وجودَ له — وهذا هو تصنيعُ الحقيقةِ عينُه الذي بُني
    # هذا السجلُّ لإبطاله، فوقعتُ فيه فقُيس فصُحِّح.
    #
    # وثانيةً: العددُ المحسوبُ هنا من `condition-coverage` هو **معدَّلُ الفروع
    # وحدَه**، وليس هو العددَ الذي تحكم به `--cov-fail-under`؛ فتلك تحكم
    # بمجموعِ السطورِ والفروعِ معًا. فجاء الفرقُ ملموسًا: 86.75٪ فروعًا مقابل
    # 94.48٪ مجموعًا لـ`core.crown`. فمقارنةُ حدٍّ مُعلَنٍ لمقياسٍ بمقياسٍ آخرَ
    # تُنتِج سقوطًا مخترَعًا.
    #
    # فالحكمُ يُؤخَذ من **رمزِ خروجِ البوّابةِ نفسِها** عبر `gate_verdict` حين
    # يُمرَّر، ويبقى العددُ المحسوبُ منشورًا باسمِه الصحيحِ للعلم. ولا يُحكَم
    # بالحسابِ المحلّيِّ إلّا حين لا تُمرَّر بوّابةٌ، ويُعلَن ذلك في
    # `verdict_source` كي يُعرَف مصدرُ كلِّ حكم.
    thr = 80.0 if threshold is None else threshold
    # أسماءُ الملفّات في Cobertura **نسبيّةٌ إلى `<source>`** لا إلى جذرِ
    # المستودع: تقريرُ `--cov=core` يكتب `constitutional_engine/ledger.py`،
    # وتقريرُ حزمةِ الخدمات يكتب `common/auth.py`. فمطابقةُ البادئة بأسماء
    # الأقاليم مباشرةً لا تُطابِق شيئًا — وهو ما وقع قبل هذا الحلّ.
    sources = [s.text for s in root.iter("source") if s.text]
    agg: dict[str, list[int]] = {d: [0, 0] for d in DOMAINS}  # [مغطّى، كلّي]
    for cls in root.iter("class"):
        fname = cls.get("filename", "")
        dom = _domain_of_covered_file(fname, sources, repo_root)
        if dom is None:
            continue
        for line in cls.iter("line"):
            cond = line.get("condition-coverage")
            if not cond:
                continue
            m = re.search(r"\((\d+)/(\d+)\)", cond)
            if m:
                agg[dom][0] += int(m.group(1))
                agg[dom][1] += int(m.group(2))

    collected: list[Collected] = []
    for dom, (covered, total) in agg.items():
        if total == 0:
            continue
        pct = round(100.0 * covered / total, 2)
        collected.append(Collected(
            kind="COVERAGE",
            domain=dom,
            capability=f"{dom}: تغطيةُ الفروع",
            # الحدُّ ٨٠٪ ليس اختيارًا جديدًا: هو الحدُّ المكتوبُ في بوّابةِ CI
            # القائمة (`--cov-fail-under=80`)، فلا يُستحدث معيارٌ موازٍ.
            verdict=gate_verdict or ("PASS" if pct >= thr else "FAIL"),
            detail={"branch_coverage_pct": pct, "covered": covered, "total": total,
                    "threshold": thr, "scope": scope or "<غير مُسمّى>",
                    "metric": "branch_rate_from_condition_coverage",
                    "verdict_source": ("gate_exit_code" if gate_verdict
                                       else "recomputed_branch_rate")},
        ))
    return collected, {"produced_at": _now()}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


COLLECTORS = {
    "junit": collect_from_junit,
    "coverage": collect_from_coverage_xml,
}


# ---------------------------------------------------------------------------
# واجهةُ الأوامر
# ---------------------------------------------------------------------------
def cmd_ingest(args: argparse.Namespace) -> int:
    artifact = Path(args.artifact)
    if not artifact.exists():
        print(f"لا يوجد ملفُّ مخرجات: {artifact}", file=sys.stderr)
        return 2
    # جذرُ حلِّ المسارات: مسارات JUnit نسبيّةٌ إلى `rootdir` الذي شُغِّل منه
    # pytest، وحزمةُ الخدمات تُشغَّل من مجلّدها لا من جذرِ المستودع. فبلا هذا
    # الخيار لا يُنسَب من ١١٤٩ اختبارًا واحدٌ، لأنّ الملفّاتَ تُطلَب في موضعٍ
    # لا توجد فيه.
    base = Path(args.rootdir).resolve() if args.rootdir else REPO_ROOT
    collector = COLLECTORS[args.format]
    if args.format == "coverage":
        gate = None
        if args.gate_exit is not None:
            # رمزُ الخروجِ حكمٌ صادرٌ عن الآلة: صفرٌ نجاحٌ وغيرُه سقوط.
            gate = "PASS" if args.gate_exit == 0 else "FAIL"
        collected, meta = collector(artifact, base, args.threshold, args.scope, gate)
    else:
        collected, meta = collector(artifact, base, args.kind)
    if args.domain:
        # النسبةُ بالاستيرادِ تصلح لدليلِ اختبارٍ ولا تصلح لدليلِ ثباتٍ أو أمن:
        # تشغيلُ حزمةِ الخدماتِ ضدّ PostgreSQL حقيقيّةٍ نُسِب أوّلًا إلى `core`
        # و`tests` أيضًا لأنّ بعضَ حالاتِه تستوردهما، فصار ظاهرُه أنّ ثباتَ
        # `core` مُثبَتٌ ضدّ محرّكٍ حقيقيٍّ وهو لم يمسَّ قاعدةَ البياناتِ أصلًا.
        # فالإقليمُ يُسمّى صريحًا لهذه الأصناف، ولا يُستنتَج.
        collected = [c for c in collected if c.domain == args.domain]
        if not collected:
            print(f"لا قيدَ للإقليمِ {args.domain} في هذا المخرَج.", file=sys.stderr)
            return 1

    # الفجواتُ تُبلَّغ قبل أيِّ خروجٍ مبكّر: «لم يُستخرج دليل» و«لم يُوجَد
    # الملفّ» رسالتان مختلفتان، والخلطُ بينهما يُخفي خطأَ إعدادٍ في صورةِ
    # غيابِ دليلٍ مشروع.
    if _ATTRIBUTION_GAPS:
        print(f"[EVIDENCE] تحذير: {len(_ATTRIBUTION_GAPS)} ملفَّ اختبارٍ في التقرير "
              f"غيرُ موجودٍ تحت {base}، فلم يُنسَب. أمثلة: "
              + "، ".join(sorted(_ATTRIBUTION_GAPS)[:3])
              + " — راجِع `--rootdir`.", file=sys.stderr)

    if not collected:
        # لا يُثبَّت قيدٌ فارغ: سجلٌّ يمتلئ بأدلّةٍ فارغةٍ يخفي غيابَ الدليل.
        print("لم يُستخرج أيُّ دليلٍ من هذا المخرَج — لا يُثبَّت شيء.", file=sys.stderr)
        return 3

    reg = EvidenceRegistry(Path(args.registry) if args.registry else None)
    digest = file_digest(artifact)
    producer = args.producer or f"{args.format}:{artifact.name}"
    # `is_relative_to` فحصٌ لا استثناء: التقاطُ `ValueError` هنا يبتلع خطأً
    # ويخفي حالةً، والفحصُ الصريحُ يقولها.
    resolved = artifact.resolve()
    rel = (str(resolved.relative_to(REPO_ROOT))
           if resolved.is_relative_to(REPO_ROOT) else str(resolved))

    for c in collected:
        reg.append(kind=c.kind, domain=c.domain, capability=c.capability,
                   verdict=c.verdict, producer=producer,
                   produced_at=meta.get("produced_at", _now()),
                   source_artifact=rel, source_digest=digest, detail=c.detail)
    print(f"ثُبِّت {len(collected)} قيدَ دليلٍ من {rel}")
    print(f"بصمةُ المخرَج: {digest[:16]}…")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    reg = EvidenceRegistry(Path(args.registry) if args.registry else None)
    problems = reg.verify_chain()
    n = len(reg.records())
    if problems:
        print(f"سلسلةُ الأدلّة مكسورة ({len(problems)} كسرًا) في {n} قيدًا:")
        for p in problems[:20]:
            print("  -", p)
        return 1
    print(f"سلسلةُ الأدلّة سليمة: {n} قيدًا.")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    reg = EvidenceRegistry(Path(args.registry) if args.registry else None)
    if reg.verify_chain():
        print("سلسلةُ الأدلّة مكسورة — لا يُقرأ تقريرٌ من سجلٍّ مكسور.", file=sys.stderr)
        return 1
    data = reg.summary()
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    kinds = sorted(EVIDENCE_KINDS)
    print("| الإقليم | " + " | ".join(kinds) + " |")
    print("|---" * (len(kinds) + 1) + "|")
    for dom, row in data.items():
        print(f"| {dom} | " + " | ".join(row[k] for k in kinds) + " |")
    print("\n`ABSENT` تعني غيابَ الدليل، لا فشلَ القدرة ولا نجاحَها.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="سجلُّ الأدلّة — يجمع الدليلَ ولا يحكم بالحالة.")
    ap.add_argument("--registry", help="مسارُ سجلِّ الأدلّة (الافتراضيُّ في docs/audit/evidence)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_in = sub.add_parser("ingest", help="يُثبِّت أدلّةً من مخرَجِ آلة")
    p_in.add_argument("--format", required=True, choices=sorted(COLLECTORS))
    p_in.add_argument("--artifact", required=True, help="ملفُّ المخرجات المُنتَج")
    p_in.add_argument("--producer", help="وصفُ المُنتِج (الأمرُ الذي شُغِّل)")
    p_in.add_argument("--rootdir", help="جذرُ حلِّ مسارات الاختبار (افتراضُه جذرُ المستودع)")
    p_in.add_argument("--threshold", type=float, help="حدُّ التغطية المُعلَن (للتغطية فقط)")
    p_in.add_argument("--scope", help="نطاقُ القياس كما شُغِّل، مثل core.crown")
    p_in.add_argument("--gate-exit", type=int, help="رمزُ خروجِ أمرِ البوّابة — الحكمُ منه لا من حسابٍ محلّي")
    p_in.add_argument("--domain", help="قصرُ القيدِ على إقليمٍ مُسمّى — واجبٌ لغيرِ TEST_RUN")
    p_in.add_argument("--kind", default="TEST_RUN", choices=sorted(EVIDENCE_KINDS),

                      help="تصنيفُ الدليلِ — التشغيلُ نفسُه قد يكون دليلَ ثباتٍ لا اختبارٍ فقط")

    p_in.set_defaults(func=cmd_ingest)

    p_vf = sub.add_parser("verify", help="يتحقّق من سلامةِ سلسلةِ الأدلّة")
    p_vf.set_defaults(func=cmd_verify)

    p_rp = sub.add_parser("report", help="يعرض خلاصةَ الأدلّة المتوفّرة")
    p_rp.add_argument("--json", action="store_true")
    p_rp.set_defaults(func=cmd_report)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
