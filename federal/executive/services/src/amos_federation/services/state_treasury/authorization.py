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

## دَين R7-B وما فعلته R7-C به

كان القول هنا: دور `official` يملك `write:tasks` لا `write:all`، فهو **لا يستطيع
الصرف**. ولم يُحلّ الدَين بمنحه `write:all` ولا `admin` ولا بصلاحية `treasury:spend`
مُختَرعة — مفردة الأدوار بقيت كما هي حرفًا. بل صار للعمليات المالية **مساران**:

1. **مسار الصلاحية (كما كان):** من يملك `manage:all` (أو `write:all` للصرف) يمرّ
   بصلاحيته — ويُصنَّف أثره `PARTIAL` أو `UNRESOLVED` لا `PROVEN`، لأن سلطته من طبقة
   لا من منصب.
2. **مسار المِنحة (R7-C8):** من لا يملك تلك الصلاحيات يمرّ إن — وفقط إن — رُبطت
   هويته الكانونية بمنصبٍ نشط، وكان لذلك المنصب مِنحة سلطة قائمة على **هذه**
   العملية و**هذا** المال بعينه. ويبقى له أقلُ ما يدلّ على أنّه فاعل موقّع
   (`write:tasks`) — فالمواطن لا يصرف ولو مُنحته مِنحة بخطأ إداريّ.

ومن لا مِنحة له ولا صلاحية: يُرفض بـ`RegistryAuthorizationError` كما كان قبل R7-C.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from amos_federation.services.government_services.authorization import (
    OfficeAuthorityError,
    require_office,
)
from amos_federation.services.national_registry.authorization import AuthorityDeniedError
from amos_federation.services.national_registry.resolver import resolve_authority
from amos_federation.services.state_registry.authorization import (
    RegistryAuthorizationError,
    require_domain_permission,
    require_tenant,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from amos_federation.common.principal import AuthorizationContext
    from amos_federation.services.national_registry.resolver import AuthorityDecision

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

#: أقلُ ما يدلّ على فاعلٍ موقّع داخل الدولة — من `DEFAULT_ROLES` لا من اختراع.
#: لا يُخوّل مالًا وحده: معه دائمًا مِنحة سلطة مطابقة تُقرأ من القاعدة.
PERMISSIONS_OFFICE_BASELINE: tuple[str, ...] = ("write:tasks", "write:all", "manage:all")

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


def gate_treasury_operation(
    context: AuthorizationContext,
    action: str,
    required: tuple[str, ...],
) -> bool:
    """البوابة الأولى لعملية مالية — ومتى يلزم ما بعدها مِنحة مقروءة.

    تُنادى قبل فتح الجلسة، فتبقى رسالة «جلستك انتهت» و«لا تملك الصلاحية» قبل
    أيّ قراءة من القاعدة — كما كان في R7-B.

    Returns:
        `False` إن مرّ بصلاحيته التقليدية، و`True` إن مرّ بالحدّ الأدنى وحده
        — فهو مدينٌ بمِنحة سلطة `PROVEN` تُقرأ قبل أن يتحرّك ريال.

    Raises:
        RegistryAuthorizationError: لا صلاحية تقليدية ولا حتّى الحدّ الأدنى.
    """
    context.assert_authorizable()
    if any(context.has_permission(permission) for permission in required):
        return False
    if any(context.has_permission(permission) for permission in PERMISSIONS_OFFICE_BASELINE):
        return True
    raise RegistryAuthorizationError(action, required, context)


def require_treasury_authority(
    session: Session,
    context: AuthorizationContext,
    operation: str,
    *,
    required: tuple[str, ...],
    grant_required: bool,
    institution_id: str,
    department_id: str | None = None,
    budget_id: str | None = None,
    account_id: str | None = None,
    amount: str | int | None = None,
    claimed_official_id: str | None = None,
) -> AuthorityDecision:
    """افرض سلطةً مقروءة على مالٍ بعينه، وأرجِع القرار ليُخزّن كما هو — R7-C8.

    `grant_required=True` معناه أن المُنادي لم يمرّ بصلاحية، فلا يُقبل منه إلاّ
    `PROVEN`: مِنحة قائمة لمنصبٍ يشغله فعلًا تغطّي هذا الهدف. وإن لم تُقرأ فالرفض
    يُرفع بـ`RegistryAuthorizationError` لا بنوعٍ جديد، لأنّ حاله حال من لا صلاحية له:
    لا طريق مشروع أصلًا.

    Raises:
        RegistryAuthorizationError: `grant_required` ولا مِنحة `PROVEN`.
        AuthorityDeniedError: مرّ بالصلاحية ثمّ رُفض لحدّ مِنحة مخصوصة.
        ForgedAuthorityError: ادّعى منصبًا لا يشغله.
    """
    decision = resolve_authority(
        session,
        context,
        operation,
        institution_id=institution_id,
        department_id=department_id,
        budget_id=budget_id,
        account_id=account_id,
        amount=amount,
        claimed_official_id=claimed_official_id,
    )
    if grant_required and not (decision.allowed and decision.classification == "PROVEN"):
        raise RegistryAuthorizationError(operation, required, context)
    if not decision.allowed:
        raise AuthorityDeniedError(decision)
    return decision


__all__ = [
    "OFFICE_BOUND_OPERATIONS",
    "PERMISSIONS_OFFICE_BASELINE",
    "PERMISSIONS_ACCOUNT_OPEN",
    "PERMISSIONS_ALLOCATION_WRITE",
    "PERMISSIONS_BUDGET_WRITE",
    "PERMISSIONS_DISBURSE",
    "PERMISSIONS_FUNDING",
    "PERMISSIONS_REVERSAL",
    "PERMISSIONS_TREASURY_ESTABLISH",
    "PERMISSIONS_TREASURY_READ",
    "TREASURY_PERMISSIONS",
    "AuthorityDeniedError",
    "OfficeAuthorityError",
    "RegistryAuthorizationError",
    "gate_treasury_operation",
    "require_domain_permission",
    "require_tenant",
    "require_treasury_authority",
    "require_treasury_office",
]
