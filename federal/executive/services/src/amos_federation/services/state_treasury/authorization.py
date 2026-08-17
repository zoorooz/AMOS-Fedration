"""
AMOS-Federation State Treasury — Authorization Boundary
الهدف: صلاحيات المال العام من المفردة القائمة، والصرف مربوطٌ بمنصب لا بدور فقط
النطاق: services/state_treasury
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17 (R7-B)

## لا حدّ تخويل ثالث

`require_domain_permission` و`require_tenant` و`require_office` تُستورَد كما هي
من R7-A. هذا الملفّ يقول **ما تلزمه كل عملية مالية**، لا كيف يُفحص التخويل.

| العملية               | المطلوب (أيٌّ منها)            | من يملكه فعلًا     | + منصب |
|-----------------------|--------------------------------|---------------------|--------|
| قراءة الخزانة          | `read:all`                     | official·royal·king | لا     |
| تأسيس خزانة/حساب       | `manage:all`                   | royal·king          | لا     |
| إنشاء موازنة           | `manage:all`                   | royal·king          | لا     |
| تخصيص من موازنة        | `manage:all`                   | royal·king          | نعم    |
| تمويل الخزانة (إيراد)  | `manage:all`                   | royal·king          | نعم    |
| صرف من تخصيص           | `write:all` · `manage:all`     | royal·king          | نعم    |
| عكس حركة               | `manage:all`                   | royal·king          | نعم    |

## لماذا «+ منصب» على كل ما يحرّك مالًا

الصلاحية تقول «هذا المبدأ من طبقة موثوقة»، ولا تقول «هذا المال تحت مسؤولية جهة
مُعيَّنة». والمال العام يلزمه الثاني: كل حركة تحمل `official_id` **مفتاحًا أجنبيًّا
غير قابل للإفراغ** إلى منصب قائم في مؤسسة الموازنة. فلا حركة «سيادية مجهولة
الجهة»، ولو كان المُنادي التاج نفسه. وهذا أضيق من قاعدة R7-A (حيث يُعفى السيادي
من شرط المنصب في القرارات) وأضيقه بقصد: القرار يمكن أن يكون سياديًّا محضًا، أمّا
المال فله جهةٌ تُسأل عنه دائمًا.

## دَينٌ مُعلَن لا يُخفى

دور `official` يملك `write:tasks` لا `write:all`، فهو **لا يستطيع الصرف** اليوم.
هذا أثر مباشر لمفردتَي الأدوار غير المُوحَّدتين (دَين R6)، وليس تصميمًا مقصودًا؛
والصادق أن يُقال لا أن تُخترع صلاحية `treasury:spend` ثالثة تحتاج تسوية غدًا.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from amos_federation.services.government_services.authorization import (
    OfficeAuthorityError,
    require_office,
)
from amos_federation.services.state_registry.authorization import (
    RegistryAuthorizationError,
    require_domain_permission,
    require_tenant,
)

if TYPE_CHECKING:
    from amos_federation.common.principal import AuthorizationContext

# === الصلاحيات — من `DEFAULT_ROLES` القائمة حصرًا، ولا واحدة مُختَرعة ===

PERMISSIONS_TREASURY_READ: tuple[str, ...] = ("read:all",)
PERMISSIONS_TREASURY_ESTABLISH: tuple[str, ...] = ("manage:all",)
PERMISSIONS_ACCOUNT_OPEN: tuple[str, ...] = ("manage:all",)
PERMISSIONS_BUDGET_WRITE: tuple[str, ...] = ("manage:all",)
PERMISSIONS_ALLOCATION_WRITE: tuple[str, ...] = ("manage:all",)
PERMISSIONS_FUNDING: tuple[str, ...] = ("manage:all",)
PERMISSIONS_DISBURSE: tuple[str, ...] = ("write:all", "manage:all")
PERMISSIONS_REVERSAL: tuple[str, ...] = ("manage:all",)

#: كل ما تفحصه هذه الوحدة — محروسٌ باختبار ساكن يمنع تسرّب مفردة جديدة.
TREASURY_PERMISSIONS: tuple[str, ...] = tuple(
    sorted(
        {
            *PERMISSIONS_TREASURY_READ,
            *PERMISSIONS_TREASURY_ESTABLISH,
            *PERMISSIONS_ACCOUNT_OPEN,
            *PERMISSIONS_BUDGET_WRITE,
            *PERMISSIONS_ALLOCATION_WRITE,
            *PERMISSIONS_FUNDING,
            *PERMISSIONS_DISBURSE,
            *PERMISSIONS_REVERSAL,
        }
    )
)

#: العمليات التي لا تمرّ بلا منصب قائم في مؤسسة الموازنة — تُقرأ في اختبار ساكن.
OFFICE_BOUND_OPERATIONS: tuple[str, ...] = (
    "treasury.funding.post",
    "treasury.allocation.create",
    "treasury.disbursement.post",
    "treasury.transaction.reverse",
)


def require_treasury_office(
    context: AuthorizationContext,
    official: object | None,
    *,
    institution_id: str,
) -> None:
    """افرض أن الحركة المالية تُنسب إلى منصب قائم في المؤسسة المسؤولة.

    تختلف عن `require_office` في شيء واحد: **لا إعفاء سيادي**. غياب المنصب رفضٌ
    مهما كانت صلاحية المُنادي، لأن العمود `official_id` مفتاحٌ إلزامي في القاعدة —
    فلو أُعفي السيادي لكان الإدخال سيفشل بعد اجتيازه التخويل، وذلك أسوأ من رفضٍ
    صريح: رسالة عطلٍ في مكان قرار.

    Raises:
        OfficeAuthorityError: لا منصب، أو معزول، أو في مؤسسة أخرى.
    """
    if official is None:
        raise OfficeAuthorityError(
            "الحركة المالية تلزمها نسبةٌ إلى منصب قائم — ولا إعفاء سياديّ في المال العام",
            official_id=None,
            institution_id=institution_id,
        )
    require_office(context, official, institution_id=institution_id)


__all__ = [
    "OFFICE_BOUND_OPERATIONS",
    "PERMISSIONS_ACCOUNT_OPEN",
    "PERMISSIONS_ALLOCATION_WRITE",
    "PERMISSIONS_BUDGET_WRITE",
    "PERMISSIONS_DISBURSE",
    "PERMISSIONS_FUNDING",
    "PERMISSIONS_REVERSAL",
    "PERMISSIONS_TREASURY_ESTABLISH",
    "PERMISSIONS_TREASURY_READ",
    "TREASURY_PERMISSIONS",
    "OfficeAuthorityError",
    "RegistryAuthorizationError",
    "require_domain_permission",
    "require_tenant",
    "require_treasury_office",
]
