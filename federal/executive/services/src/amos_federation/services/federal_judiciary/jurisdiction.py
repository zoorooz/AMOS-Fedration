"""
AMOS-Federation Federal Judiciary — Jurisdiction Boundary
الهدف: النطاق يُطابَق مساواةً صريحة، فلا ترقيةَ فدرالية ولا تجاوزَ ولائيّ
النطاق: services/federal_judiciary
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17 (R7-D3)

## المشكلة التي يحلّها هذا الملفّ

في أنظمةٍ كثيرة يُكتب الاختصاص سلّمًا: `FEDERAL > STATE > INSTITUTION`، ثم تُفحَص
الصلاحية بـ`court.level >= case.level`. وأثرُ ذلك أن **المحكمة الفدرالية تملك
تلقائيًّا كل قضايا الولايات** — وهو ما نُهينا عنه صراحةً. وأثرُه المعاكس أنّ
محكمةَ ولايةٍ يمكن أن تُمرَّر إلى نطاقٍ أوسع بترقيةٍ ضمنية.

فلا مقارنةَ ترتيبٍ هنا ولا `>=`: النطاق **قيمةٌ مُصنَّفة تُساوى**. ودالّةٌ واحدة
`assert_jurisdiction_match` هي البوّابة، ويحرسها اختبارٌ ساكن يمنع ظهور مقارنةٍ
ترتيبية على النطاق في هذه الوحدة.

## أين يُفحَص النطاق فعلًا

1. **إنشاء المحكمة**: نطاقُها من `JURISDICTIONS` حصرًا (قيدُ `CHECK` في القاعدة).
2. **فتح القضية**: نطاقُها يُطابِق نطاقَ محكمتها مساواةً؛ وفي `INSTITUTION` يلزم
   زيادةً أن تكون مؤسسةُ المحكمة **هي** المؤسسة المعنيّة.
3. **حلّ السلطة القضائية**: نطاقُ منصب القاضي يُطابِق نطاقَ المحكمة والقضية.

والثلاثةُ مساواة. ولا رابعَ يخفِّف أحدها.

## ما لا يُدَّعى

لا استئنافَ ولا إحالةَ اختصاصٍ بين المحاكم: نقلُ قضيةٍ من نطاقٍ إلى نطاق يحتاج
إجراءً قضائيًّا مُصمَّمًا (إحالة، ثم قبول، ثم أثر) وهو **دَينٌ معلن** لم يُبنَ.
و`COURT_LEVELS` وصفيّةٌ للتنظيم ولا تُستعمل في أيّ قرار اختصاصٍ في هذه الوحدة.
"""

from __future__ import annotations

from amos_federation.services.federal_judiciary.models import JURISDICTIONS
from amos_federation.services.national_registry.models import AUTHORITY_SCOPES


class JurisdictionError(PermissionError):  # noqa: N818 — رفضُ اختصاص، لا عطل
    """النطاق لا يسمح بهذا الفعل — رفضٌ مقصود يُرفَع إلى المُنادي."""


def assert_known_jurisdiction(jurisdiction: str) -> str:
    """اقبل نطاقًا موجودًا فعلًا في المفردة، وارفض ما عداه.

    والمفردةُ **مجموعةٌ فرعية** من `AUTHORITY_SCOPES` القائمة في R7-C — يحرس ذلك
    تأكيدٌ هنا وليس تعليقًا: لو أُضيف نطاقٌ قضائيّ لا مقابلَ له في مفردة السلطة
    لَصار للمحاكم مفردةُ نطاقٍ ثانية، وذاك بابُ التباعد.
    """
    if jurisdiction not in JURISDICTIONS:
        raise JurisdictionError(
            f"نطاقٌ غير معروف '{jurisdiction}' — المسموح: {', '.join(JURISDICTIONS)}"
        )
    if jurisdiction not in AUTHORITY_SCOPES:  # pragma: no cover — يحرسه اختبارٌ ساكن
        raise JurisdictionError(f"نطاق '{jurisdiction}' ليس من مفردة السلطة القائمة")
    return jurisdiction


def assert_jurisdiction_match(
    *,
    court_jurisdiction: str,
    case_jurisdiction: str,
    court_institution_id: str | None = None,
    case_institution_id: str | None = None,
    what: str = "القضية",
) -> None:
    """اطلب مساواةً صريحة بين نطاق المحكمة ونطاق القضية.

    Args:
        court_jurisdiction: نطاق المحكمة كما هو في `state_courts.jurisdiction`.
        case_jurisdiction: نطاق القضية كما هو في `state_legal_cases.jurisdiction`.
        court_institution_id: مؤسسة المحكمة — يلزم في نطاق `INSTITUTION`.
        case_institution_id: المؤسسة المعنيّة بالقضية — يلزم في نطاق `INSTITUTION`.
        what: اسمُ ما يُفحَص، ليكون نصّ الرفض مفهومًا.

    Raises:
        JurisdictionError: عند اختلاف النطاقين، أو اختلاف المؤسسة في `INSTITUTION`.
    """
    assert_known_jurisdiction(court_jurisdiction)
    assert_known_jurisdiction(case_jurisdiction)
    if court_jurisdiction != case_jurisdiction:
        raise JurisdictionError(
            f"نطاق المحكمة '{court_jurisdiction}' لا يساوي نطاق {what} "
            f"'{case_jurisdiction}' — ولا ترقيةَ ضمنية بين النطاقات"
        )
    if court_jurisdiction == "INSTITUTION":
        if not court_institution_id or not case_institution_id:
            raise JurisdictionError("نطاق INSTITUTION يلزمه مؤسسةٌ محدَّدة للمحكمة وللقضية معًا")
        if court_institution_id != case_institution_id:
            raise JurisdictionError(
                f"محكمةُ المؤسسة '{court_institution_id}' لا تملك اختصاصًا على "
                f"مؤسسةٍ أخرى '{case_institution_id}'"
            )


def assert_scope_covers_court(*, position_scope: str, court_jurisdiction: str) -> None:
    """اطلب أن يكون نطاقُ منصب القاضي **هو نفسه** نطاق محكمته.

    فمنصبٌ نطاقُه `INSTITUTION` لا يُصدر حكمًا في محكمةٍ فدرالية، ومنصبٌ فدراليّ
    لا يجلس تلقائيًّا في محكمة ولاية. وهذا ما يمنع «قاضٍ خارج نطاقه» عمليًّا.
    """
    assert_known_jurisdiction(court_jurisdiction)
    if position_scope != court_jurisdiction:
        raise JurisdictionError(
            f"نطاق المنصب '{position_scope}' لا يساوي نطاق المحكمة "
            f"'{court_jurisdiction}' — ولا ترقيةَ ضمنية"
        )


__all__ = [
    "JurisdictionError",
    "assert_jurisdiction_match",
    "assert_known_jurisdiction",
    "assert_scope_covers_court",
]
