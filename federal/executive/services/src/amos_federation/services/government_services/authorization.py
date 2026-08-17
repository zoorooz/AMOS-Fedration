"""
AMOS-Federation Government Services — Domain Authorization Boundary
الهدف: صلاحيات الخدمات والقضايا والقرارات، وسلطةٌ مصدرها منصبٌ قائم لا نصٌّ في طلب
النطاق: services/government_services
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17 (R7-A، الوحدة 2)

## لا حدّ تخويل ثانٍ

`require_domain_permission` و`require_tenant` و`RegistryAuthorizationError` تُستورَد
من `state_registry.authorization` ولا يُعاد كتابتها. حدُّ التخويل للدولة **واحد**،
وهذه الوحدة تضيف إليه صلاحياتها لا مسارًا موازيًا له (R7-C).

والصلاحيات كلها من `DEFAULT_ROLES` المزروعة — ولا صلاحية مُختَرعة:

| العملية              | المطلوب (أيٌّ منها)            | من يملكه فعلًا                |
|----------------------|--------------------------------|--------------------------------|
| قراءة الخدمات/القضايا | `read:all`                     | official · royal · king         |
| إعلان/تعليق خدمة      | `manage:all`                   | royal · king                    |
| فتح قضية             | `write:tasks` · `write:all`    | agent · official · royal · king |
| إسناد قضية           | `manage:agents` · `manage:all` | official · royal · king         |
| معالجة قضية          | `write:tasks` · `write:all`    | agent · official · royal · king |
| إصدار قرار           | `write:tasks` · `write:all` **مع منصب قائم** | مسؤول مُقلَّد (أو `manage:all`) |

## السلطة من المنصب — لا من الدور وحده

القرار لا يكفيه صلاحية: يلزمه **منصبٌ قائم في مؤسسة القضية**. فحصٌ يقرأ صفًّا في
`state_officials` لا يقرأ نصًّا في الطلب (`require_office`). ومن يملك `manage:all`
(الملكي والتاج) يقرّر بسلطة سيادية، ويُسجَّل ذلك في القرار صراحةً بدل أن يُنسَب
القرار إلى منصب لم يشغله أحد.

## حدّ يُقال بصراحة (دَين لا يُخفى)

**ربط المبدأ بالمنصب غير ممكن اليوم.** الجلسة تحمل اسم مستخدم، والمنصب يشير إلى
`agents.id`، ولا جدول يربط الاثنين. فمن يملك `write:tasks` يمكنه إصدار قرار باسم
**أي** مسؤول قائم في تلك المؤسسة. لذلك:

- يُخزَّن في القرار **المسؤول والمبدأ المُنفِّذ معًا** (`decided_by_principal`)،
- ويُسجَّل هذا نقصًا مُصنَّفًا **PARTIAL** في `docs/audit/R7_DOMAIN_BUILD.md`،
- ولا يُدَّعى أن «القرار صادر من صاحب المنصب» بل أن «قرارًا سُجِّل باسم منصب قائم
  ونُفِّذ بمبدأ معلوم».

سدُّه يلزمه سجلّ يربط المستخدم بالوكيل، وهو من نطاق الهوية لا من هذا النطاق.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from amos_federation.services.state_registry.authorization import (
    RegistryAuthorizationError,
    require_domain_permission,
    require_tenant,
)

if TYPE_CHECKING:
    from amos_federation.common.principal import AuthorizationContext

# === الصلاحيات المطلوبة — من `DEFAULT_ROLES` القائمة حصرًا ===

PERMISSIONS_GOV_READ: tuple[str, ...] = ("read:all",)
PERMISSIONS_SERVICE_WRITE: tuple[str, ...] = ("manage:all",)
PERMISSIONS_CASE_OPEN: tuple[str, ...] = ("write:tasks", "write:all")
PERMISSIONS_CASE_ASSIGN: tuple[str, ...] = ("manage:agents", "manage:all")
PERMISSIONS_CASE_PROCESS: tuple[str, ...] = ("write:tasks", "write:all")
PERMISSIONS_CASE_DECIDE: tuple[str, ...] = ("write:tasks", "write:all")

#: سلطة سيادية تُغني عن شرط المنصب — الملكي والتاج.
PERMISSIONS_SOVEREIGN: tuple[str, ...] = ("manage:all",)

#: كل ما تفحصه هذه الوحدة — يحرسه اختبار ساكن يمنع تسرّب مفردة جديدة.
GOVERNMENT_PERMISSIONS: tuple[str, ...] = tuple(
    sorted(
        {
            *PERMISSIONS_GOV_READ,
            *PERMISSIONS_SERVICE_WRITE,
            *PERMISSIONS_CASE_OPEN,
            *PERMISSIONS_CASE_ASSIGN,
            *PERMISSIONS_CASE_PROCESS,
            *PERMISSIONS_CASE_DECIDE,
            *PERMISSIONS_SOVEREIGN,
        }
    )
)


class OfficeAuthorityError(PermissionError):  # noqa: N818 — رفض سلطة، لا عطل
    """القرار يلزمه منصبٌ قائم في مؤسسة القضية — لا دورٌ مناسب فقط."""

    def __init__(self, reason: str, *, official_id: str | None, institution_id: str) -> None:
        self.official_id = official_id
        self.institution_id = institution_id
        super().__init__(
            f"لا سلطة إصدار قرار في المؤسسة '{institution_id}': {reason}"
            f" (المنصب المُدَّعى: {official_id or 'غير مُعطى'})"
        )


def has_sovereign_authority(context: AuthorizationContext) -> bool:
    """أيملك السياق سلطة سيادية تُغني عن شرط المنصب؟"""
    return any(context.has_permission(permission) for permission in PERMISSIONS_SOVEREIGN)


def require_office(
    context: AuthorizationContext,
    official: Any | None,
    *,
    institution_id: str,
) -> None:
    """افرض أن القرار يصدر باسم منصب قائم في مؤسسة القضية نفسها.

    `official` صفُّ `OfficialModel` مقروءًا من القاعدة، أو `None` إن لم يُعطَ منصب.
    الملكي والتاج يمرّان بسلطتهما السيادية بلا منصب، ويُسجَّل ذلك في القرار.

    Raises:
        OfficeAuthorityError: لا منصب، أو منصبٌ معزول، أو منصبٌ في مؤسسة أخرى.
    """
    if official is None:
        if has_sovereign_authority(context):
            return
        raise OfficeAuthorityError(
            "لم يُعطَ منصب، والمبدأ لا يملك سلطة سيادية",
            official_id=None,
            institution_id=institution_id,
        )
    if official.status != "appointed":
        raise OfficeAuthorityError(
            f"المنصب ليس قائمًا (حالته '{official.status}')",
            official_id=official.id,
            institution_id=institution_id,
        )
    if official.institution_id != institution_id:
        raise OfficeAuthorityError(
            f"المنصب في مؤسسة أخرى ('{official.institution_id}')",
            official_id=official.id,
            institution_id=institution_id,
        )


__all__ = [
    "GOVERNMENT_PERMISSIONS",
    "PERMISSIONS_CASE_ASSIGN",
    "PERMISSIONS_CASE_DECIDE",
    "PERMISSIONS_CASE_OPEN",
    "PERMISSIONS_CASE_PROCESS",
    "PERMISSIONS_GOV_READ",
    "PERMISSIONS_SERVICE_WRITE",
    "PERMISSIONS_SOVEREIGN",
    "OfficeAuthorityError",
    "RegistryAuthorizationError",
    "has_sovereign_authority",
    "require_domain_permission",
    "require_office",
    "require_tenant",
]
