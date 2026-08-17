"""
AMOS-Federation Federal/State Integration — Permission Vocabulary
الهدف: حدُّ التخويل لعمليات الفدرالية والولايات من مفردة الأدوار القائمة حصرًا
النطاق: services/federal_state
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17 (R8-B)

## لا مفردةَ صلاحياتٍ ثانية

هذه الوحدة **لا تعرّف صلاحيةً جديدة**؛ تُعيد تصدير `require_domain_permission` و
`require_tenant` و`RegistryAuthorizationError` من `state_registry` (R7-A) وتسمّي
أيَّ صلاحياتِ `DEFAULT_ROLES` القائمة تلزم كلَّ عملية — كما فعلت R7-D حرفًا.

## طبقتان لا واحدة

الصلاحيةُ هنا **إذنُ استعمالِ الواجهة** (هل لهذا المبدأ أن يكتب في سجلّ الحكومات
إطلاقًا؟)، وهي **ليست** سلطةَ الحكم على مورد. سلطةُ المورد تُحلّ في `authority.py`
بمناداة `national_registry.resolve_authority` — محرّكِ التخويل الوحيد. فمن يملك
`manage:all` يستطيع مناداةَ الواجهة، ويُرفض مع ذلك إن لم يكن يشغل منصبًا بنطاقٍ
يشمل الحكومةَ المستهدفة. و`role="governor"` أو `role="minister"` لا يمنح شيئًا في
أيّ من الطبقتين.
"""

from __future__ import annotations

from amos_federation.services.state_registry.authorization import (
    RegistryAuthorizationError,
    require_domain_permission,
    require_tenant,
)

# === الصلاحيات — من `DEFAULT_ROLES` القائمة حصرًا ===

PERMISSIONS_FEDERATION_READ: tuple[str, ...] = ("read:all",)
#: إنشاءُ حكومةٍ أو تغييرُ حالتها أو ربطُ مؤسسةٍ بها — أثرٌ بنيويّ دائم.
PERMISSIONS_GOVERNMENT_WRITE: tuple[str, ...] = ("manage:all",)
#: العلاقاتُ وصفيّة، ومع ذلك كتابتُها تُغيّر قراءةَ البنية — فنفس الحدّ.
PERMISSIONS_RELATION_WRITE: tuple[str, ...] = ("manage:all",)
#: التفويضُ يوسّع مدى فاعلٍ آخر — أضيقُ ما نملك، بلا استثناء.
PERMISSIONS_DELEGATION_WRITE: tuple[str, ...] = ("manage:all",)
#: عملُ الحكومة اليوميّ: نطاقُ خدمةٍ وإسنادُ قضية — نفسُ أساس R7-D بلا اختراع.
PERMISSIONS_SCOPE_WRITE: tuple[str, ...] = ("write:tasks", "write:all", "manage:all")
PERMISSIONS_OPERATION_WRITE: tuple[str, ...] = ("write:tasks", "write:all", "manage:all")

#: كل ما تفحصه هذه الوحدة — محروسٌ باختبارٍ ساكن يمنع تسرّب مفردةٍ جديدة.
FEDERAL_STATE_PERMISSIONS: tuple[str, ...] = tuple(
    sorted(
        {
            *PERMISSIONS_FEDERATION_READ,
            *PERMISSIONS_GOVERNMENT_WRITE,
            *PERMISSIONS_RELATION_WRITE,
            *PERMISSIONS_DELEGATION_WRITE,
            *PERMISSIONS_SCOPE_WRITE,
            *PERMISSIONS_OPERATION_WRITE,
        }
    )
)


__all__ = [
    "FEDERAL_STATE_PERMISSIONS",
    "PERMISSIONS_DELEGATION_WRITE",
    "PERMISSIONS_FEDERATION_READ",
    "PERMISSIONS_GOVERNMENT_WRITE",
    "PERMISSIONS_OPERATION_WRITE",
    "PERMISSIONS_RELATION_WRITE",
    "PERMISSIONS_SCOPE_WRITE",
    "RegistryAuthorizationError",
    "require_domain_permission",
    "require_tenant",
]
