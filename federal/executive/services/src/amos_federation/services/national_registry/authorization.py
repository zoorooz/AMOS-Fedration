"""
AMOS-Federation National Registry — Authorization Boundary
الهدف: صلاحيات السجل الوطني من المفردة القائمة، والسلطة تُفرَض من مِنحةٍ لا من دور
النطاق: services/national_registry
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17 (R7-C6)

## لا حدّ تخويل رابع

`require_domain_permission` و`require_tenant` و`RegistryAuthorizationError` تُستورَد
كما هي من R7-A. وهذا الملفّ يقول **ما تلزمه كل عملية سجلّ هوية**، ثم يضيف فرضًا
واحدًا جديدًا: `require_authority` — الذي لا يسأل «أيّ دورٍ أنت؟» بل «أيّ مِنحة
سلطةٍ تُغطّي هذا المال بالتحديد؟».

| العملية | المطلوب (أيٌّ منها) | من يملكه فعلًا |
| --- | --- | --- |
| قراءة الهويات والمناصب | `read:all` | official · royal · king |
| إنشاء هوية · ربط مبدأ · ربط وكيل | `manage:all` | royal · king |
| إنشاء منصب · تقليده · عزله | `manage:all` | royal · king |
| منح سلطة · سحبها | `manage:all` | royal · king |

ولا صلاحية مُختَرعة: كل اسمٍ أعلاه من `DEFAULT_ROLES` المزروعة، ويحرس ذلك اختبارٌ
ساكن. وإنشاء الهوية سياديٌّ بقصد — فمن يملك إنشاء الهويات يملك تعريف «من هو من»،
وتلك سلطةٌ لا تُوزَّع على دور `official`.

## لا حلّ للدَين بترقية صلاحية

دَين R7-B: دور `official` يملك `write:tasks` لا `write:all`، فلا يستطيع الصرف.
وحلّه هنا **ليس** إعطاءه `write:all` ولا `admin` ولا صلاحية `treasury:spend`
مُختَرعة. الحلّ أن السلطة على مالٍ بعينه تأتي من صفٍّ في `state_authority_grants`
يربط منصبه بموازنةٍ بعينها. فبقيت مفردة الأدوار كما هي، وصار للمسؤول طريقٌ مشروع
إلى موازنته وحدها — ولا شيء غيرها.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from amos_federation.services.state_registry.authorization import (
    RegistryAuthorizationError,
    require_domain_permission,
    require_tenant,
)

# `AuthorityDecision` وحدَه يُستعمل تلميحَ نوع. و`ForgedAuthorityError` اسمٌ مُعاد
# تصديره وقت التشغيل عبر `__getattr__` أدناه، فلا يُستورد هنا — استيرادُ اسمٍ
# تشغيليٍ في كتلة التحقّق من الأنواع تناقضٌ ترفعه بوابة الفحص (ruff · TCH004).
if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from amos_federation.common.principal import AuthorizationContext
    from amos_federation.services.national_registry.resolver import AuthorityDecision

#: أسماءٌ تُعاد من `resolver` بتحميلٍ متأخّر — انظر `__getattr__` في آخر الوحدة.
_RESOLVER_REEXPORTS: tuple[str, ...] = ("AuthorityDecision", "ForgedAuthorityError")


def __getattr__(name: str) -> Any:
    """أعِد تصديرَ أسماء `resolver` بلا استيرادٍ وقت التحميل — كسرُ حلقةٍ حقيقية.

    الحلقة: هذه الوحدة → `resolver` → `government_services` (حزمةً) →
    `government_services.service` → هذه الوحدة، فتُطلب `AuthorityDecision` من
    `resolver` وهو بعدُ نصفَ مُهيّأ فيرتفع `ImportError`. ولم تظهر لأنّ كلّ مسارٍ
    قائمٍ كان يحمّل `government_services` أو `state_registry` أولًا.

    و`__getattr__` على مستوى الوحدة (PEP 562) يحفظ العقد الظاهر: يبقى
    `from ...authorization import AuthorityDecision` عاملًا كما كان، ويُدفع
    الاستيرادُ إلى أوّل استعمالٍ فعليّ بعد اكتمال التحميل.
    """
    if name in _RESOLVER_REEXPORTS:
        from amos_federation.services.national_registry import resolver

        return getattr(resolver, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# === الصلاحيات — من `DEFAULT_ROLES` القائمة حصرًا ===

PERMISSIONS_IDENTITY_READ: tuple[str, ...] = ("read:all",)
PERMISSIONS_IDENTITY_WRITE: tuple[str, ...] = ("manage:all",)
PERMISSIONS_PRINCIPAL_LINK: tuple[str, ...] = ("manage:all",)
PERMISSIONS_AGENT_LINK: tuple[str, ...] = ("manage:all",)
PERMISSIONS_POSITION_WRITE: tuple[str, ...] = ("manage:all",)
PERMISSIONS_ASSIGNMENT_WRITE: tuple[str, ...] = ("manage:all",)
PERMISSIONS_GRANT_WRITE: tuple[str, ...] = ("manage:all",)

#: كل ما تفحصه هذه الوحدة — محروسٌ باختبار ساكن يمنع تسرّب مفردة جديدة.
NATIONAL_REGISTRY_PERMISSIONS: tuple[str, ...] = tuple(
    sorted(
        {
            *PERMISSIONS_IDENTITY_READ,
            *PERMISSIONS_IDENTITY_WRITE,
            *PERMISSIONS_PRINCIPAL_LINK,
            *PERMISSIONS_AGENT_LINK,
            *PERMISSIONS_POSITION_WRITE,
            *PERMISSIONS_ASSIGNMENT_WRITE,
            *PERMISSIONS_GRANT_WRITE,
        }
    )
)


class AuthorityDeniedError(PermissionError):  # noqa: N818 — رفض سلطة، لا عطل
    """لا مِنحة سلطةٍ تُغطّي هذه العملية على هذا الهدف — والرفض هو الافتراض."""

    def __init__(self, decision: AuthorityDecision) -> None:
        self.decision = decision
        self.operation = decision.operation
        self.classification = decision.classification
        targets = {
            key: value
            for key, value in decision.targets.items()
            if value is not None and key != "institution_branch"
        }
        super().__init__(
            f"لا سلطة للمبدأ '{decision.principal_id}' على العملية "
            f"'{decision.operation}' بأهداف {targets}: {decision.reason}"
        )


def require_authority(
    session: Session,
    context: AuthorizationContext,
    operation: str,
    *,
    institution_id: str,
    department_id: str | None = None,
    budget_id: str | None = None,
    account_id: str | None = None,
    amount: str | int | None = None,
    claimed_official_id: str | None = None,
) -> AuthorityDecision:
    """افرض سلطةً مُثبتةً من القاعدة على عمليةٍ وهدفٍ مُسمّيين — R7-C6.

    يُرجع القرار عند الإجازة ليُخزَّن كما هو في جدول الإسناد، ويرفع استثناءً عند
    المنع. والقرار نفسه محسوبٌ في `resolver` — فلا منطق نطاقٍ ثانٍ هنا.

    Raises:
        AuthorityDeniedError: لا مِنحة تُغطّي، ولا صلاحية سيادية.
        ForgedAuthorityError: ادّعى المُنادي منصبًا لا يشغله.
        ValueError: عملية خارج المفردة — خطأ برمجة لا رفض سلطة.
    """
    from amos_federation.services.national_registry.resolver import resolve_authority

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
    if not decision.allowed:
        raise AuthorityDeniedError(decision)
    return decision


__all__ = [
    "NATIONAL_REGISTRY_PERMISSIONS",
    "PERMISSIONS_AGENT_LINK",
    "PERMISSIONS_ASSIGNMENT_WRITE",
    "PERMISSIONS_GRANT_WRITE",
    "PERMISSIONS_IDENTITY_READ",
    "PERMISSIONS_IDENTITY_WRITE",
    "PERMISSIONS_POSITION_WRITE",
    "PERMISSIONS_PRINCIPAL_LINK",
    "AuthorityDeniedError",
    "RegistryAuthorizationError",
    "require_authority",
    "require_domain_permission",
    "require_tenant",
    # والأسماءُ المُعادةُ من `resolver` تُضمّ أدناه من مصدرٍ واحد لا بنسخة ثانية،
    # فلا ينقطع أحدُهما عن `__getattr__`.
    *_RESOLVER_REEXPORTS,
]
