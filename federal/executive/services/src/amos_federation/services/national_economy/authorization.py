"""
AMOS-Federation National Economy — Economic Authorization Surface
الهدف: تخويلُ الأفعال الاقتصادية بالمحرّك الكانونيّ وحدَه، وبحدِّ الحكومة فوقه
النطاق: services/national_economy
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17 (R9-C · R9-M)

## لا محرّكَ تخويلٍ ثانٍ

هذا الملفّ **لا يحكم** بنفسه. كلُّ حكمٍ هنا نداءٌ إلى:

    national_registry.resolver.resolve_authority     ← الهوية · المنصب · المِنحة
    federal_state.authority.resolve_government_authority ← حدُّ الحكومة · التفويض

فما يُضيفه هو ثلاثةُ أشياءَ لا يعرفها المحرّكُ الكانونيّ:

1. أن العمليةَ المطلوبة **اقتصاديةٌ** — من `ECONOMIC_OPERATIONS` لا من غيرها.
2. أيُّ نوعِ موضوعٍ تخصُّ كلُّ عملية (`OPERATION_SUBJECT_KINDS`) — فلا تُجاز
   مِنحةٌ بعملية دعمٍ ولا أصلٌ بعملية التزام.
3. صلاحياتُ المجال الفاصلة بين قراءةٍ وبنيةٍ وتنفيذٍ ماليّ.

## لا سلطةَ من دورٍ ولا من اسم

لا يُقرأ `context.role` هنا ولا `context.principal_id` كمصدرِ سلطة. الصلاحيةُ
(`require_domain_permission`) بوّابةُ **مجالٍ** لا سلطةَ اقتصادية: من يملك
`manage:all` ولا منصبَ له ولا مِنحةَ يُرفض في `require_economic_authority`.
والعكسُ صحيح: من له مِنحةٌ ولا صلاحيةَ مجالٍ يُرفض قبل أن نسأل القاعدة.

## ما لا يُفعل هنا

- لا `admin` ولا `write:all` ولا صلاحيةٌ عامّة تُمنَح لتمرير اختبار.
- لا `claimed_official_id` من المستدعي يُقبل كإثبات: يُمرَّر إلى المحرّك
  الكانونيّ ليُفحَص هناك، ويرفع `ForgedAuthorityError` إن لم يكن مملوكًا.
- لا تصنيفٌ يُرقّى: تصنيفُ النتيجة هو تصنيفُ المحرّك أو أدنى منه.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from amos_federation.services.federal_state.authority import (
    GovernmentAuthority,
    GovernmentAuthorityError,
    require_government_authority,
    resolve_government_authority,
)
from amos_federation.services.national_registry.models import ECONOMIC_OPERATIONS
from amos_federation.services.state_registry.authorization import (
    RegistryAuthorizationError,
    require_domain_permission,
    require_tenant,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from amos_federation.common.principal import AuthorizationContext

#: قراءةُ سجلّ الاقتصاد الوطنيّ.
PERMISSIONS_ECONOMY_READ: tuple[str, ...] = ("read:all",)

#: بنيةُ السجلّ: قطاعٌ · فئةٌ · كيانٌ عامّ · تعريفُ مؤشّر. تغييرُ البنية ليس
#: عملًا تشغيليًّا، فلا يكفيه `write:tasks`.
PERMISSIONS_ECONOMY_STRUCTURE_WRITE: tuple[str, ...] = ("manage:all",)

#: السياسةُ الاقتصادية — إصدارًا ونفاذًا.
PERMISSIONS_ECONOMY_POLICY_WRITE: tuple[str, ...] = ("manage:all",)

#: الأفعالُ التشغيلية الاقتصادية: برنامجٌ · إيرادٌ · إنفاقٌ · تحويلٌ · أصلٌ ·
#: التزامٌ · مشتريات. تشغيليةٌ فتقبل `write:tasks`، ولا واحدةَ منها تُنفَّذ
#: بلا سلطةٍ مُحلَّلة بعد البوّابة.
PERMISSIONS_ECONOMY_EXECUTE: tuple[str, ...] = ("write:tasks", "write:all", "manage:all")

#: كلُّ ما تحتاجه هذه الوحدة — يُقرأ في فحوص الصلاحيات، ولا `admin` فيه.
NATIONAL_ECONOMY_PERMISSIONS: tuple[str, ...] = tuple(
    sorted(
        {
            *PERMISSIONS_ECONOMY_READ,
            *PERMISSIONS_ECONOMY_STRUCTURE_WRITE,
            *PERMISSIONS_ECONOMY_POLICY_WRITE,
            *PERMISSIONS_ECONOMY_EXECUTE,
        }
    )
)

#: نوعُ الموضوع المسموح لكلِّ عملية — القاعدةُ تعرف المفردتين ولا تعرف الربطَ
#: بينهما، فيُفرض هنا. ومَن أراد إجازةَ دعمٍ بعملية مِنحةٍ يُرفض باسمِ العملية.
OPERATION_SUBJECT_KINDS: dict[str, str] = {
    "economy.entity.register": "ENTITY",
    "economy.program.create": "PROGRAM",
    "economy.policy.issue": "POLICY",
    "economy.policy.activate": "POLICY",
    "economy.revenue.register": "REVENUE_SOURCE",
    "economy.expenditure.authorize": "EXPENDITURE",
    "economy.grant.authorize": "TRANSFER",
    "economy.subsidy.authorize": "TRANSFER",
    "economy.asset.register": "ASSET",
    "economy.liability.register": "LIABILITY",
    "economy.procurement.authorize": "PROCUREMENT",
}

#: نوعُ التحويل لكلِّ عمليةِ تحويل — مِنحةٌ ودعمٌ لا يتبادلان.
TRANSFER_OPERATION_KINDS: dict[str, str] = {
    "economy.grant.authorize": "GRANT",
    "economy.subsidy.authorize": "SUBSIDY",
}


class EconomicAuthorizationError(PermissionError):  # noqa: N818 — رفضُ تخويل، لا عطل
    """رُفض فعلٌ اقتصاديّ: عمليةٌ غيرُ اقتصادية أو موضوعٌ لا يوافق العملية."""

    def __init__(self, operation: str, reason: str) -> None:
        self.operation = operation
        self.reason = reason
        super().__init__(f"فعلٌ اقتصاديٌّ مرفوض على {operation}: {reason}")


def assert_economic_operation(operation: str) -> None:
    """العمليةُ يجب أن تكون من المفردة الاقتصادية الكانونية — لا اسمَ مُختَرعًا.

    Raises:
        EconomicAuthorizationError: إن لم تكن العمليةُ في `ECONOMIC_OPERATIONS`.
    """
    if operation not in ECONOMIC_OPERATIONS:
        raise EconomicAuthorizationError(operation, "ليست عمليةً اقتصادية في المفردة الكانونية")


def assert_subject_kind(operation: str, subject_kind: str) -> None:
    """نوعُ الموضوع يجب أن يوافق العملية — وإلّا فالإجازةُ على غير موضوعها.

    Raises:
        EconomicAuthorizationError: إن خالف النوعُ ما تخصُّه العملية.
    """
    assert_economic_operation(operation)
    expected = OPERATION_SUBJECT_KINDS[operation]
    if subject_kind != expected:
        raise EconomicAuthorizationError(
            operation, f"موضوعُ العملية يجب أن يكون '{expected}' لا '{subject_kind}'"
        )


def require_economic_authority(
    session: Session,
    context: AuthorizationContext,
    operation: str,
    **kwargs: Any,
) -> GovernmentAuthority:
    """احلُل سلطةً اقتصاديةً بالمحرّك الكانونيّ وحدَه، وارفعْ عند الرفض.

    لا حكمَ جديدًا في هذه الدالّة: تتحقّق أن العمليةَ اقتصادية، ثمّ تُسلّم
    الأمرَ إلى `require_government_authority` — فالهويةُ والمنصبُ والمِنحةُ
    وحدُّ الحكومة والتفويضُ كلُّها تُحسَم حيث كانت تُحسَم قبل R9.

    Raises:
        EconomicAuthorizationError: العمليةُ ليست اقتصادية.
        GovernmentAuthorityError: رُفضت السلطةُ أو الحدُّ الحكوميّ.
        ForgedAuthorityError: ادّعى المستدعي منصبًا لا يملكه.
    """
    assert_economic_operation(operation)
    return require_government_authority(session, context, operation, **kwargs)


def preview_economic_authority(
    session: Session,
    context: AuthorizationContext,
    operation: str,
    **kwargs: Any,
) -> GovernmentAuthority:
    """كالسابقة بلا رفعٍ — للقراءة والعرض فقط، ولا كتابةَ تتلوها."""
    assert_economic_operation(operation)
    return resolve_government_authority(session, context, operation, **kwargs)


__all__ = [
    "NATIONAL_ECONOMY_PERMISSIONS",
    "OPERATION_SUBJECT_KINDS",
    "PERMISSIONS_ECONOMY_EXECUTE",
    "PERMISSIONS_ECONOMY_POLICY_WRITE",
    "PERMISSIONS_ECONOMY_READ",
    "PERMISSIONS_ECONOMY_STRUCTURE_WRITE",
    "TRANSFER_OPERATION_KINDS",
    "EconomicAuthorizationError",
    "GovernmentAuthority",
    "GovernmentAuthorityError",
    "RegistryAuthorizationError",
    "assert_economic_operation",
    "assert_subject_kind",
    "preview_economic_authority",
    "require_domain_permission",
    "require_economic_authority",
    "require_tenant",
]
