#!/usr/bin/env python3
"""
المصالحة الدستوريّة — Constitutional Reconciliation (المرحلة 1B)
الهدف: قياسُ التزام النصوص الدستوريّة القائمة ببعضها، وكشفُ ما تُخالف فيه المراسيمُ
       الموادَّ التي تحكمها، وفرزُ ما يُصلَح آليًّا عمّا لا يملك قرارَه إلّا إنسان.
النطاق: tools/governance — لا يستورده كودُ التشغيل، ولا يمنح صلاحيّةً، ولا يُصدِر مرسومًا.
المالك: tools/governance
تاريخ الإنشاء: 2026-08-18
تاريخ آخر تعديل: 2026-08-18

## لِمَ وُجد هذا الملف

المرحلة 1B تُوجب المصالحةَ بين النصوص الدستوريّة قبل بناء أيّ سلطةٍ فوقها؛ إذ
لا يُبنى نموذجُ سلطةٍ (1D) على دستورٍ يناقض نفسَه، فيرث التناقضَ تنفيذًا.

والفحصُ الذي كان قائمًا يختم الموادَّ العشرَ والديباجةَ ويتحقّق من بصماتها
(`articles.verify_seals`)، وهو سليمٌ فيما يغطّيه. لكنّه لا يقرأ حرفًا من
`amendments/` ولا `interpretations/` — والقياسُ أثبت أنّ **لا سطرَ كودٍ واحدًا
في المستودع كلِّه** يقرأ هذين المجلّدين. فالمراسيمُ التي أنشأت السيادةَ الملكيّة
غيرُ مفحوصةٍ ولا مختومة.

وهذا الملفُّ **لا يُصدِر حكمًا دستوريًّا ولا يُنشئ نصًّا**. يقرأ النصوصَ القائمةَ
ويقيس التزامَها بما تُوجبه هي على نفسها، ويصنّف كلَّ خللٍ في واحدةٍ من فئتين:

* `MECHANICAL` — نقصٌ يُسدّ بالتنفيذ بلا قرارٍ سياديّ (كغياب فحصٍ للسلامة).
* `HUMAN_DECISION_REQUIRED` — تعارضٌ أو مخالفةٌ لا يملك حسمَها إلّا صاحبُ
  السلطة. ولا يُخترَع لها قرارٌ هنا، ولا تُخفى لتحسين التقرير.

والتقريرُ يُظهِر المخالفةَ ولا يُصلحها من تلقاء نفسه: تصحيحُ مرسومٍ ملكيٍّ فعلٌ
ملكيٌّ (المادة العاشرة · 2 · 1)، فلو «أصلحته» الأداةُ لكانت هي انتحالًا للصفة
التي بُنيت لتكشفه.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CONSTITUTION = REPO_ROOT / "core" / "constitution"
ARTICLES_DIR = CONSTITUTION / "articles"
AMENDMENTS_DIR = CONSTITUTION / "amendments"
INTERPRETATIONS_DIR = CONSTITUTION / "interpretations"
SEALS_PATH = CONSTITUTION / "ARTICLE_SEALS.json"

# ملفّاتٌ إداريّةٌ لا تحمل نصًّا دستوريًّا.
NON_NORMATIVE = {"README.md", "NUCLEUS.md"}

SEVERITY_MECHANICAL = "MECHANICAL"
SEVERITY_HUMAN = "HUMAN_DECISION_REQUIRED"

# المادة الخامسة · «سجل التعديلات» تُعدّد خمسةَ عناصرَ واجبةً في كلّ تعديل.
# الأنماطُ أدناه تبحث عن **وجود العنصر**، لا عن صحّته؛ فغيابُ العنصرِ نفسِه
# مخالفةٌ قاطعةٌ تُقاس، أمّا صحّةُ توقيعٍ موجودٍ فشأنُ التحقّق التعمويّ (1C).
A005_REQUIRED_ELEMENTS: tuple[tuple[str, str, str], ...] = (
    ("النص الكامل قبل وبعد", r"قبل التعديل|النص قبل|before|قبل\s*/\s*بعد", "A005-E1"),
    ("بصمة SHA-256 للنسختين", r"sha-?256|بصمة", "A005-E2"),
    ("التوقيع الزمني", r"التوقيع الزمني|timestamp|الطابع الزمني", "A005-E3"),
    ("أسماء الموافقين", r"الموافقون|أسماء الموافقين|approvers", "A005-E4"),
    ("التوقيع الرقمي البشري", r"ed25519|التوقيع الرقمي|signature", "A005-E5"),
)

# المادة العاشرة · 3 · 2: كلُّ فعلٍ ملكيٍّ يحمل مرسومًا موقّعًا Ed25519 يُتحقَّق
# منه مقابل مفتاح التاج العام.
RE_ROYAL_ACT = re.compile(r"مرسوم\s*ملكي|المرسوم\s*الملكي|royal\s*decree", re.IGNORECASE)
RE_ED25519 = re.compile(r"ed25519", re.IGNORECASE)
# مادّةُ توقيعٍ فعليّةٌ: قيمةٌ سِتّ عشريّةٌ أو base64 بطولٍ معقول، أو إحالةٌ صريحةٌ
# إلى ملفِّ توقيعٍ مُرافق. والتمييزُ لازمٌ: أوّلُ صياغةٍ اكتفت بورودِ لفظِ
# «Ed25519» فأعلنت المرسومَين سليمَين، والحالُ أنّ اللفظَ ورد في **وصفِ الشرطِ**
# لا في تنفيذه — فصار الفحصُ يشهد بالتوقيعِ لأنّ النصَّ ذكر أنّه يجب أن يُوقَّع.
# مادّةُ التوقيع لا تُعرَف بشكلِها وحدَه: بصمةُ SHA-256 ستّونَ حرفًا وأربعةٌ من
# ست عشريّةٍ أيضًا، فمرسومٌ يوثّق بصماتَ ما قبلَ التعديلِ وما بعدَه كان يمرّ
# بوصفِه «موقّعًا» وهو غيرُ موقّع. فلا يُعتدُّ بالمادّةِ إلا إذا نُسبت إلى
# التوقيعِ صراحةً على السطرِ نفسِه، أو كانت مرجعَ ملفِّ توقيعٍ مستقلّ.
RE_SIGNATURE_LABEL = re.compile(r"توقيع|signature|sig\b|Ed25519", re.IGNORECASE)
RE_SIGNATURE_BLOB = re.compile(r"[0-9a-fA-F]{64,}|[A-Za-z0-9+/]{60,}={0,2}")
RE_SIGNATURE_REFERENCE = re.compile(r"\.sig\b|signature_file|ملف التوقيع")
# نصٌّ يُعلِن صريحًا أنّ توقيعَه لم يُستوفَ — إعلانٌ لا يُعَدُّ توقيعًا أبدًا.
RE_SIGNATURE_PENDING = re.compile(r"SIGNATURE_REQUIRED|التوقيعُ?\s+الرقميُّ?\s+مُعلَّق")


def _has_signature_material(text: str) -> bool:
    """هل يحمل النصُّ مادّةَ توقيعٍ يُتحقَّق منها — لا مجرّدَ سلسلةٍ طويلة؟

    الشرطُ: مرجعُ ملفِّ توقيعٍ مستقلّ، أو كتلةٌ توقيعيّةٌ **موسومةٌ بالتوقيعِ على
    سطرِها**. وبصمةُ SHA-256 في جدولِ «ما قبل / ما بعد» ليست توقيعًا.
    """
    if RE_SIGNATURE_REFERENCE.search(text):
        return True
    for line in text.split("\n"):
        if RE_SIGNATURE_BLOB.search(line) and RE_SIGNATURE_LABEL.search(line):
            return True
    return False
RE_ISSUE_DATE = re.compile(r"تاريخ الإصدار\D*(\d{4})-(\d{2})-(\d{2})")

# المادة الخامسة · 3: فترةُ مراجعةٍ لا تقلّ عن تسعين يومًا.
A005_REVIEW_DAYS = 90


@dataclass(frozen=True)
class Finding:
    """مخالفةٌ مقيسةٌ بنصِّها ومرجعِها — لا انطباعَ ولا تلخيص."""

    code: str
    severity: str
    subject: str
    rule: str
    measured: str

    def as_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "severity": self.severity,
            "subject": self.subject,
            "rule": self.rule,
            "measured": self.measured,
        }


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    sealed_files: set[str] = field(default_factory=set)
    normative_unsealed: list[str] = field(default_factory=list)

    def add(self, f: Finding) -> None:
        self.findings.append(f)

    @property
    def human_decisions(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == SEVERITY_HUMAN]

    @property
    def mechanical(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == SEVERITY_MECHANICAL]


def _normative_files(directory: Path) -> list[Path]:
    """النصوصُ ذاتُ الأثرِ في مجلّدٍ — دون ملفّات الإدارة."""
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.glob("*.md") if p.name not in NON_NORMATIVE)


def _sealed_paths(seals_path: Path = SEALS_PATH) -> set[str]:
    if not seals_path.is_file():
        return set()
    data = json.loads(seals_path.read_text(encoding="utf-8"))
    return {entry["file"] for entry in data.get("seals", {}).values()}


def digest_of(path: Path) -> str:
    """بصمةٌ بالتطبيع نفسِه الذي تُعلنه بطاقةُ الأختام، فتُقارَن بها."""
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    body = "\n".join(line.rstrip() for line in text.split("\n")).strip()
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def check_seal_coverage(report: Report, root: Path = REPO_ROOT) -> None:
    """كلُّ نصٍّ ذي أثرٍ دستوريٍّ يجب أن يكون مختومًا — وإلّا عُدِّل صامتًا.

    الأختامُ اليومَ تغطّي الديباجةَ والموادَّ العشر. أمّا المراسيمُ والتفاسيرُ
    فلا خَتمَ لها، مع أنّها هي التي أنشأت السيادةَ الملكيّةَ وحدّدت نطاقَ
    المادة التاسعة. فيمكن تبديلُ نصِّ مرسومٍ ملكيٍّ كاملًا ويبقى كلُّ فحصٍ
    في المستودعِ أخضرَ — أي أنّ **تاريخَ الدولةِ الدستوريَّ قابلٌ لإعادة
    الكتابةِ بلا أثر**، وحفظُ السجلّ دون حذفٍ مبدأٌ لا يقبل التعديل أصلًا
    (المادة الخامسة · ما لا يمكن تعديله · 4).
    """
    sealed = _sealed_paths()
    report.sealed_files = sealed
    for directory in (AMENDMENTS_DIR, INTERPRETATIONS_DIR):
        for path in _normative_files(directory):
            rel = path.relative_to(root).as_posix()
            if rel in sealed:
                continue
            report.normative_unsealed.append(rel)
            report.add(Finding(
                code="RECON-001",
                severity=SEVERITY_MECHANICAL,
                subject=rel,
                rule="المادة الخامسة · ما لا يمكن تعديله · 4 — حفظ السجل دون حذف",
                measured="نصٌّ دستوريُّ الأثر غيرُ مشمولٍ ببطاقة الأختام؛ تعديلُه لا يُكتشَف",
            ))


def check_amendment_elements(report: Report, root: Path = REPO_ROOT) -> None:
    """المادة الخامسة تُوجب خمسةَ عناصرَ في كلِّ تعديل — تُقاس واحدًا واحدًا."""
    for path in _normative_files(AMENDMENTS_DIR):
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(root).as_posix()
        for label, pattern, code in A005_REQUIRED_ELEMENTS:
            if re.search(pattern, text, re.IGNORECASE):
                continue
            report.add(Finding(
                code=f"RECON-002/{code}",
                severity=SEVERITY_HUMAN,
                subject=rel,
                rule=f"المادة الخامسة · سجل التعديلات — «{label}»",
                measured="العنصرُ غائبٌ عن نصّ المرسوم",
            ))


def check_royal_decree_signature(report: Report, root: Path = REPO_ROOT) -> None:
    """المادة العاشرة · 3 · 2: لا فعلَ ملكيًّا بلا مرسومٍ موقّعٍ Ed25519.

    وغيابُ التوقيعِ ليس نقصًا شكليًّا: المادةُ نفسُها (3 · 4) تُقرّ أنّ الحمايةَ
    من المرسوم المُنتحَل موضعُها **المفتاحُ والسجلُّ والخلافة** لا نقضٌ يعلو على
    التاج. فإذا سقط التوقيعُ سقطت الحمايةُ كلُّها، ولم يبقَ ما يميّز مرسومًا
    ملكيًّا من نصٍّ كتبه أيُّ طرفٍ في المستودع.
    """
    for path in _normative_files(AMENDMENTS_DIR):
        text = path.read_text(encoding="utf-8")
        if not RE_ROYAL_ACT.search(text):
            continue
        if not RE_SIGNATURE_PENDING.search(text) and _has_signature_material(text):
            continue
        mentions = bool(RE_ED25519.search(text))
        report.add(Finding(
            code="RECON-003",
            severity=SEVERITY_HUMAN,
            subject=path.relative_to(root).as_posix(),
            rule="المادة العاشرة · 3 · 2 — كل فعل ملكي بمرسوم موقّع Ed25519",
            measured=(
                "يذكر النصُّ شرطَ التوقيع ولا يحمل مادّةَ توقيعٍ يُتحقَّق منها"
                if mentions else
                "المرسومُ يُعلِن نفسَه فعلًا ملكيًّا ولا يحمل توقيعًا ولا مرجعَ تحقّق"
            ),
        ))


class MalformedIssueDate(ValueError):
    """تاريخٌ مكتوبٌ لا يُقرأ — وليس تاريخًا غائبًا."""


def _issue_date(path: Path) -> date | None:
    """يُرجِع None للغائب، ويرفع استثناءً للمكتوبِ الفاسد.

    والتمييزُ بينهما هو المقصود: أوّلُ صياغةٍ ردّت `None` للحالتَين،
    فكان تاريخٌ مثل `2026-13-45` يُسقِط فحصَ التسعين يومًا بأكملِه بلا
    أثر— فيصير تجاوزُ فترةِ المراجعةِ مسألةَ رقمٍ مكتوبٍ خطأً.
    """
    m = RE_ISSUE_DATE.search(path.read_text(encoding="utf-8"))
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError as exc:
        raise MalformedIssueDate(f"{path.name}: {m.group(0)!r} — {exc}") from exc


def _issue_date_or_finding(
    path: Path, report: Report, root: Path,
) -> date | None:
    """يقيس التاريخَ ويرفع الفسادَ مخالفةً بدلَ أن يبتلعَه."""
    try:
        return _issue_date(path)
    except MalformedIssueDate as exc:
        report.add(Finding(
            code="RECON-007",
            severity=SEVERITY_HUMAN,
            subject=path.relative_to(root).as_posix(),
            rule="المادة الخامسة · 3 — تاريخٌ يُحتسَب منه أجلُ المراجعة",
            measured=f"تاريخُ الإصدار مكتوبٌ ولا يُقرأ فلا يصحّ حسابُ أجلٍ منه: {exc}",
        ))
        return None


ROYAL_DECREE_MARKER = re.compile(r"المرسوم\s+الملكي|مرسومٌ\s+ملكي")


def _is_royal_decree(text: str) -> bool:
    """هل هذا النصُّ مرسومٌ ملكيٌّ أم مقترحٌ مؤسّسيّ؟

    الفرقُ ليس شكليًّا: مدّةُ التسعين يومًا شرطُ مسارِ المقترحِ التابع، والمرسومُ
    الملكيُّ يُعدِّل مباشرةً (المادة الخامسة · 0 · 3). فإن لم يُميَّز النوعان
    طُبِّق قيدُ المؤسّساتِ على السلطةِ التي أنشأتها.
    """
    return bool(ROYAL_DECREE_MARKER.search(text))


def check_review_period(report: Report, root: Path = REPO_ROOT) -> None:
    """المادة الخامسة · 3: فترةُ مراجعةٍ لا تقلّ عن تسعين يومًا قبل التعديل.

    **مُراجَعٌ بالمرسوم `AMD-003` (RECON-004):** الشرطُ باقٍ بمدّتِه كما هو على
    **مسارِ المقترحِ التابع** — لم يُلغَ ولم تُخفَّض مدّتُه — ونُصَّ صريحًا أنّه
    لا يسري على المرسوم الملكيّ. فصار الفحصُ يقيسُ المدّةَ على المقترحاتِ
    المؤسّسيّة، ويقيسُ على المرسومِ الملكيِّ ما يليقُ به: إعلانَ سندِه الملكيِّ
    صريحًا. ولو حُذف نصُّ التوصيفِ من المادة الخامسة عاد الفحصُ إلى قياسِ المدّةِ
    على الجميع كما كان.
    """
    a005 = ARTICLES_DIR / "005-amendment-process.md"
    base = _issue_date_or_finding(a005, report, root) if a005.is_file() else None
    if base is None:
        # سكوتٌ هنا يُلغي فحصَ المدّةِ كلَّه دون أن يعلم أحدٌ.
        report.add(Finding(
            code="RECON-008",
            severity=SEVERITY_MECHANICAL,
            subject="core/constitution/articles/005-amendment-process.md",
            rule=f"المادة الخامسة · 3 — مراجعة ≥ {A005_REVIEW_DAYS} يومًا",
            measured="لا يُقرأ تاريخُ إصدارِ المادة، ففحصُ فترةِ المراجعةِ مُعطَّلٌ لا ناجح",
        ))
        return
    a005_text = a005.read_text(encoding="utf-8")
    royal_track_scoped = _conflict_resolved(a005_text)
    for path in _normative_files(AMENDMENTS_DIR):
        issued = _issue_date_or_finding(path, report, root)
        if issued is None:
            continue
        if royal_track_scoped and _is_royal_decree(path.read_text(encoding="utf-8")):
            continue  # مرسومٌ ملكيٌّ — المدّةُ شرطُ المقترحِ لا شرطُ المرسوم
        elapsed = (issued - base).days
        if elapsed >= A005_REVIEW_DAYS:
            continue
        report.add(Finding(
            code="RECON-004",
            severity=SEVERITY_HUMAN,
            subject=path.relative_to(root).as_posix(),
            rule=f"المادة الخامسة · شروط التعديل · 3 — مراجعة ≥ {A005_REVIEW_DAYS} يومًا",
            measured=f"انقضى {elapsed} يومًا بين صدور المادة الخامسة وصدور المرسوم",
        ))


RESOLUTION_MARKERS: tuple[tuple[str, str], ...] = (
    # (وصفُ الرُّكن، نمطُه) — الحسمُ لا يُستنتج من كلمةٍ واحدةٍ عابرة.
    ("حصرُ التعديل في الملك", r"اختصاص\S*\s+ملكي\S*\s+حصر"),
    ("توصيفُ النسبة مسارًا للمقترح", r"مسار\S*\s+المقترح"),
)


def _conflict_resolved(a005_text: str) -> bool:
    """هل يحمل نصُّ المادة الخامسة نفسُه حسمَ التعارض؟

    لا يكفي أن يُقال في وثيقةٍ خارجيّةٍ إنّ التعارضَ حُلّ — القرارُ المؤسِّس أوجب
    **إزالتَه من النصِّ الدستوريّ نفسِه**. فالفحصُ يقرأ النصَّ لا الوثيقة، ويطلب
    رُكنَي الحسمِ معًا: حصرَ التعديلِ في الملك، وتوصيفَ النسبةِ مسارًا للمقترح.
    فإن غاب أحدُهما فالتعارضُ عائدٌ ويُرفَع من جديد.
    """
    return all(re.search(pat, a005_text) for _, pat in RESOLUTION_MARKERS)


# صياغاتٌ حرّمها القرارُ المؤسِّس (البند الثاني عشر) والمادة الحادية عشرة · 4.
# تُقاس على نصٍّ منزوعِ التشكيلِ حتى لا تُفلت بحركةٍ واحدة.
FORBIDDEN_ROYAL_PHRASES: tuple[tuple[str, str], ...] = (
    ("F-01", r"الملك\s+لا\s+سلطة\s+له"),
    ("F-02", r"لا\s+سلطة\s+للملك"),
    ("F-03", r"الملك\s+لا\s+يملك\s+سلطة"),
    ("F-04", r"الملك\s+لا\s+يستطيع"),
    ("F-05", r"المجلس\s+أعلى\s+من\s+الملك"),
    ("F-06", r"قرار\s+المجلس\s+لا\s+يمكن\s+إبطاله"),
    ("F-07", r"السيادة\s+لغير\s+الملك"),
)

EXEMPTION_MARKER = "ROYAL-LANG-EXEMPT"

_DIACRITICS = re.compile(r"[\u064B-\u0652\u0670\u0640]")


def _strip_diacritics(text: str) -> str:
    """التشكيلُ زينةٌ للقارئ ومهربٌ للمخالف — يُنزَع قبل القياس."""
    return _DIACRITICS.sub("", text)


def check_royal_supremacy_language(report: Report, root: Path = REPO_ROOT) -> None:
    """حارسٌ يمنع عودةَ الصياغاتِ التي حرّمها القرارُ المؤسِّس.

    القاعدةُ الذهبيّة (البند الثاني عشر) تُحرِّم أن يُقال في نصوصِ الدولة ولا
    وثائقِها ولا اختباراتِها إنّ الملكَ لا سلطةَ له، أو أنّه غيرُ قادرٍ، أو أنّ  # ROYAL-LANG-EXEMPT
    المجلسَ أعلى منه، أو أنّ قرارَه لا يُبطَل — **إلا باستثناءٍ دستوريٍّ صريح**.

    والاستثناءُ لا يكون سكوتًا ولا استحسانًا: يُعلَن على السطرِ نفسِه بعلامةٍ
    `ROYAL-LANG-EXEMPT` مع سببِها، فيبقى مقروءًا في المراجعة. وبهذا يُفرَّق بين
    نصٍّ **يُقرِّر** الصياغةَ المحرَّمة ونصٍّ **يُحرِّمها أو يسجّل تاريخَها**.
    """
    for path in _language_subjects(root):
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            # سكوتٌ هنا يُعطِّل الحارسَ على هذا الملفِّ دون أن يعلم أحد: ملفٌّ
            # يتعذّر قراءتُه هو ملفٌّ **غيرُ مفحوصٍ** لا ملفٌّ سليم. يُرفَع.
            report.add(Finding(
                code="RECON-009",
                severity=SEVERITY_MECHANICAL,
                subject=path.relative_to(root).as_posix(),
                rule="القرار المؤسِّس · البند الثاني عشر — حارسُ الصياغة",
                measured=f"تعذّرت قراءةُ الملفِّ فلم يُفحَص: {type(exc).__name__}",
            ))
            continue
        for lineno, line in enumerate(raw.split("\n"), start=1):
            if EXEMPTION_MARKER in line:
                continue
            measured = _strip_diacritics(line)
            for code, pattern in FORBIDDEN_ROYAL_PHRASES:
                if not re.search(pattern, measured):
                    continue
                report.add(Finding(
                    code="RECON-009",
                    severity=SEVERITY_MECHANICAL,
                    subject=f"{path.relative_to(root).as_posix()}:{lineno}",
                    rule=(
                        "القرار المؤسِّس · البند الثاني عشر والمادة الحادية عشرة · 4 "
                        f"— صياغةٌ محرَّمة {code}"
                    ),
                    measured=measured.strip()[:160],
                ))


def _language_subjects(root: Path) -> list[Path]:
    """نصوصُ الدولةِ ووثائقُها واختباراتُها — لا مجلّداتُ الأدواتِ الخارجيّة."""
    subjects: list[Path] = []
    for folder in ("core", "docs", "royal", "tools", "tests", "federal"):
        base = root / folder
        if not base.is_dir():
            continue
        for suffix in ("*.md", "*.py", "*.json"):
            subjects.extend(
                p for p in base.rglob(suffix)
                if p.is_file() and "__pycache__" not in p.parts
            )
    return sorted(subjects)


def check_procedure_conflict(report: Report) -> None:
    """تعارضٌ نصّيٌّ صريحٌ بين إجراءَي تعديلٍ لا يجتمعان.

    المادة الخامسة تشترط لتعديل الدستور موافقةَ **٧٥٪ من مجلس السياسات**.
    والمادة العاشرة · 2 تحصر تعديلَ الدستور في الملك وتنصّ أنّه «لا تصح من أي
    طرف آخر **بأي أغلبية ولا بأي إجراء**» — وموافقةُ ٧٥٪ أغلبيّةٌ بنصّها.

    فالنصّان يصفان مسارَين متنافيَين للفعل نفسِه: أحدُهما يُوجب الأغلبيّةَ
    والآخرُ يُبطلها. ولا يُحسَم هذا بقراءةٍ ولا بترجيحٍ من أداة: أيُّهما ناسخٌ
    للآخر قرارٌ سياديّ. ولذلك يُرفَع كما هو ولا يُخترَع له حلّ.

    **حُسِم بالمرسوم `AMD-003`** (2026-08-18): نسبةُ الأغلبيّة آليّةُ قرارٍ داخلَ
    المجلس لرفعِ مقترحٍ إلى الملك، والتعديلُ اختصاصٌ ملكيٌّ حصرًا. فصار هذا
    الفحصُ **حارسًا لا مُبلِّغًا**: يسكت وحدَ ما دام نصُّ الحسم قائمًا في المادة
    الخامسة، ويعود يصرخ إن حُذف النصُّ فعادت الأغلبيّةُ تُقرأ إجازةً للتعديل.
    وهذا هو التحصينُ المنصوصُ في المادة الحادية عشرة · 3 · 6.
    """
    a005 = ARTICLES_DIR / "005-amendment-process.md"
    a010 = ARTICLES_DIR / "010-royal-sovereignty.md"
    if not (a005.is_file() and a010.is_file()):
        return
    t5 = a005.read_text(encoding="utf-8")
    t10 = a010.read_text(encoding="utf-8")
    majority_required = bool(re.search(r"موافقة\s*\d+\s*%\s*من\s*مجلس", t5))
    majority_void = bool(re.search(r"بأي\s*أغلبية", t10))
    if majority_required and majority_void and not _conflict_resolved(t5):
        report.add(Finding(
            code="RECON-005",
            severity=SEVERITY_HUMAN,
            subject="A005 ↔ A010",
            rule="تعارضُ إجراءَي تعديل الدستور",
            measured=(
                "الخامسةُ تشترط موافقةَ أغلبيّةٍ من مجلس السياسات، "
                "والعاشرةُ تُبطل التعديلَ بأي أغلبيةٍ وتحصره في الملك"
            ),
        ))


def check_engine_reads_decrees(report: Report, root: Path = REPO_ROOT) -> None:
    """نصٌّ لا يقرؤه محرّكٌ ليس قدرةً تشغيليّة — وجودُ الملفِّ ليس وجودَ القدرة."""
    engine_dir = root / "core" / "constitutional_engine"
    if not engine_dir.is_dir():
        return
    # يُقرأ كلُّ سطرٍ وحدَه: المطلوبُ قراءةٌ فعليّةٌ للمجلّد لا ورودُ اسمِه.
    # وأوّلُ صياغةٍ بحثت في النصِّ كلِّه فأعلنت أنّ المحرّكَ يقرأ `amendments/`،
    # والحالُ أنّ الاسمَ ورد داخل **نصِّ رسالةٍ** في بطاقة الأختام: «لا يُحدَّث
    # هذا الملف إلا بمرسوم تعديل موثق في amendments/». فشهد الفحصُ بقدرةٍ
    # مصدرُها جملةٌ عربيّةٌ في تعليق — وهو عينُ ما جاء يكشفه.
    fs_call = re.compile(r"\b(glob|iterdir|rglob|open|read_text|listdir|scandir|Path)\b")
    lines = [
        line
        for p in engine_dir.glob("*.py")
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines()
    ]
    for name, folder in (("amendments", AMENDMENTS_DIR), ("interpretations", INTERPRETATIONS_DIR)):
        if not _normative_files(folder):
            continue
        if any(name in line and fs_call.search(line) for line in lines):
            continue
        report.add(Finding(
            code="RECON-006",
            severity=SEVERITY_MECHANICAL,
            subject=f"core/constitution/{name}/",
            rule="القاعدة 12 — وجودُ الملفِّ ليس دليلًا على وجود القدرة",
            measured="المحرّكُ الدستوريُّ لا يقرأ هذا المجلّد؛ فأثرُه التشغيليُّ صفر",
        ))


# سجلُّ بصماتٍ **تدقيقيٌّ لا دستوريٌّ**. وموضعُه خارج `core/constitution/`
# عن قصد: ختمُ الدستور فعلٌ ملكيٌّ حصرٌا (المادة العاشرة · 2 · 5)، وبطاقةُ
# الأختام تشترط لتحديثِها مرسومًا موثّقًا. فلو كتبت هذه الأداةُ أختامًا للمراسيم
# لانتحلت صفةً ملكيّةً تحرّمُها المادةُ العاشرة · 3 · 2 — فتصيرُ الأداةُ الحارسةُ
# أوّلَ من يخرق. فهذا السجلُّ يقول «رأيتُ النصَّ هكذا بتاريخِ كذا» ولا يقول
# «هذا النصُّ مُصدَّق»؛ يكشف التبديلَ ولا يمنح شرعيّةً.
HISTORY_DIGESTS = REPO_ROOT / "docs" / "audit" / "constitution_history_digests.json"


def _history_subjects(root: Path = REPO_ROOT) -> list[Path]:
    return _normative_files(AMENDMENTS_DIR) + _normative_files(INTERPRETATIONS_DIR)


def record_history(path: Path = HISTORY_DIGESTS, root: Path = REPO_ROOT) -> dict:
    """يثبّت بصمةَ كلِّ نصٍّ تاريخيٍّ ليُكشَف تبديلُه لاحقًا."""
    entries = {
        p.relative_to(root).as_posix(): digest_of(p) for p in _history_subjects(root)
    }
    payload = {
        "$comment": (
            "سجل بصمات تدقيقي للمراسيم والتفاسير. ليس ختمًا دستوريًا ولا يمنح شرعية؛ "
            "ختم الدستور فعل ملكي حصرًا (المادة العاشرة · 2 · 5). وظيفته كشف التبديل لا إجازته."
        ),
        "algorithm": "sha256",
        "normalization": "LF endings, trailing whitespace stripped, document stripped",
        "digests": entries,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def verify_history(path: Path = HISTORY_DIGESTS, root: Path = REPO_ROOT) -> list[str]:
    """يُرجِع وصفًا لكلِّ اختلافٍ — وغيابُ السجلِّ نفسِه اختلافٌ لا سكوت."""
    if not path.is_file():
        return ["سجلُّ بصمات التاريخ الدستوريّ غائبٌ — لا يُعرَف أُبُدِّل نصٌّ أم لا"]
    # لا `‏.get("digests", {})‏`: ملفٌ مشوّهٌ كان سيُقرأ سجلًّا فارغًا فيَخرُج
    # التحقّقُ سليمًا ولا نصٌّ مفحوص— وهذا سقوطٌ صامتٌ يجعل تعطيلَ الحارس
    # تشويهَ ملفٍ. رصده مُدقّقُ الحقيقة في أوّلِ تشغيلٍ بعد كتابتِه.
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"سجلُّ البصمات غيرُ مقروء: {exc}"]
    if not isinstance(loaded, dict) or "digests" not in loaded:
        return ["سجلُّ البصمات بلا حقل digests — ملفٌ مشوّهٌ لا سجلٌّ فارغ"]
    recorded = loaded["digests"]
    current = {p.relative_to(root).as_posix(): digest_of(p) for p in _history_subjects(root)}
    problems: list[str] = []
    for rel, dig in sorted(recorded.items()):
        if rel not in current:
            problems.append(f"محذوفٌ بعد التثبيت: {rel}")
        elif current[rel] != dig:
            problems.append(f"مُبدَّلٌ بعد التثبيت: {rel}")
    for rel in sorted(set(current) - set(recorded)):
        problems.append(f"نصٌّ جديدٌ غيرُ مُثبَّت: {rel}")
    return problems


def reconcile(root: Path = REPO_ROOT) -> Report:
    report = Report()
    check_seal_coverage(report, root)
    check_amendment_elements(report, root)
    check_royal_decree_signature(report, root)
    check_review_period(report, root)
    check_procedure_conflict(report)
    check_engine_reads_decrees(report, root)
    check_royal_supremacy_language(report, root)
    return report


def _render(report: Report) -> str:
    lines = ["[RECONCILE] المصالحة الدستوريّة — المرحلة 1B", ""]
    lines.append(f"  مخالفاتٌ تُسَدُّ بالتنفيذ : {len(report.mechanical)}")
    lines.append(f"  قراراتٌ لا تُتَّخَذ آليًّا : {len(report.human_decisions)}")
    lines.append("")
    for group, title in (
        (report.human_decisions, "HUMAN DECISION REQUIRED — لا يُخترَع لها قرار"),
        (report.mechanical, "MECHANICAL — تُنفَّذ بلا قرارٍ سياديّ"),
    ):
        if not group:
            continue
        lines.append(f"── {title} ──")
        for f in group:
            lines.append(f"  [{f.code}] {f.subject}")
            lines.append(f"      المرجع : {f.rule}")
            lines.append(f"      المقيس : {f.measured}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="قياسُ اتّساق النصوص الدستوريّة — لا يُصدِر مرسومًا ولا يُصلِح نصًّا",
    )
    parser.add_argument("--json", action="store_true", help="مخرَجٌ بصيغة JSON")
    parser.add_argument(
        "--record-history", action="store_true",
        help="ثبّت بصمات المراسيم والتفاسير (سجلٌ تدقيقيٌّ لا ختمٌ ملكيٌّ)",
    )
    parser.add_argument(
        "--verify-history", action="store_true",
        help="تحقّق أنّ نصوص التاريخ الدستوريّ لم تُبدَّل",
    )
    parser.add_argument(
        "--fail-on-mechanical",
        action="store_true",
        help="اخرج بخطأ إن بقيت مخالفةٌ يمكن سدُّها بالتنفيذ",
    )
    args = parser.parse_args(argv)

    if args.record_history:
        payload = record_history()
        print(f"ثُبِّتت {len(payload['digests'])} بصمةً في {HISTORY_DIGESTS.name}")
        return 0

    if args.verify_history:
        problems = verify_history()
        if problems:
            for p in problems:
                print(f"  ✗ {p}")
            return 1
        print("نصوص التاريخ الدستوريّ مطابقةٌ لما ثُبِّت.")
        return 0

    report = reconcile()
    if args.json:
        print(json.dumps(
            {
                "human_decision_required": [f.as_dict() for f in report.human_decisions],
                "mechanical": [f.as_dict() for f in report.mechanical],
                "normative_unsealed": report.normative_unsealed,
            },
            ensure_ascii=False, indent=2,
        ))
    else:
        print(_render(report))

    # القراراتُ البشريّةُ **لا تُسقِط البناء**: إسقاطُه بها يدفع إلى إخفائها أو
    # اختلاقِ قرارٍ لإسكاتها، وكلاهما أسوأُ من بقائها ظاهرةً مُحصاة.
    if args.fail_on_mechanical and report.mechanical:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
