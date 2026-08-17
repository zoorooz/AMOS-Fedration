"""
AMOS-Federation Federal Judiciary — Authorization Boundary
الهدف: صلاحيات القضاء من المفردة القائمة حصرًا، والسلطة القضائية من تقليدٍ لا من دور
النطاق: services/federal_judiciary
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17 (R7-D9)

## لا حدّ تخويل خامس

`require_domain_permission` و`require_tenant` تُستورَدان كما هما من R7-A، ولا
مفردةَ صلاحياتٍ جديدة: كل اسمٍ في الجدول أدناه موجودٌ في `DEFAULT_ROLES` المزروعة،
ويحرس ذلك اختبارٌ ساكن.

| العملية | المطلوب (أيٌّ منها) | من يملكه فعلًا |
| --- | --- | --- |
| قراءة المحاكم والقضايا والأحكام | `read:all` | official · royal · king |
| إنشاء محكمة · تعليقها | `manage:all` | royal · king |
| تقليد قاضٍ · عزله | `manage:all` | royal · king |
| فتح قضية · إسنادها · قيد إجراء · إيداع دليل | `write:tasks` أو `write:all` أو `manage:all` | official · royal · king |
| إصدار حكم | الأساس أعلاه **زائدًا** سلطةً قضائية مُثبَتة | القاضي المُقلَّد وحده |
| إحالة الحكم للتنفيذ | الأساس أعلاه **زائدًا** سلطةً قضائية مُثبَتة | القاضي المُقلَّد وحده |

## الصلاحية ليست سلطةً قضائية

هذا هو الفرق الذي تقوم عليه الوحدة كلّها. `manage:all` يُنشئ محاكم ويُقلِّد قضاة —
لأن ذلك فعلٌ سياديّ تنظيميّ. ولا يُصدر حكمًا: إصدارُ الحكم يحتاج، فوق الصلاحية،
أن يُحَلّ المبدأ إلى **هويةٍ كانونية مقلَّدةٍ قاضيًا في هذه المحكمة بالذات، في
منصبٍ نشط، بنطاقٍ مطابق، وفي قضيةٍ مُسندةٍ إليه**. فالتاجُ نفسه يمرّ في حدّ
الصلاحية ويُرفَض في حدّ السلطة القضائية إن لم يكن قاضيًا — وذاك مقصود: لا يجوز
لشخصٍ أن ينتحل المحكمة أو القاضي، ولو كان صاحب السيادة.

وهذا **لا** يُنقص السيادة: لا مسارَ في هذه الوحدة يمنح المحكمة نقضًا على أمرٍ
سياديّ صحيح، ولا يجعلها أعلى من التاج. غايتُه أن الحكم القضائيّ يحتاج قاضيًا،
كما أنّ الأمر السياديّ يحتاج التاج. ويحرس ذلك اختبارٌ ساكنٌ يمنع ظهور أيّ نقضٍ
أو تجاوزٍ للسيادة في مصادر هذه الوحدة.
"""

from __future__ import annotations

from amos_federation.services.state_registry.authorization import (
    RegistryAuthorizationError,
    require_domain_permission,
    require_tenant,
)

# === الصلاحيات — من `DEFAULT_ROLES` القائمة حصرًا ===

PERMISSIONS_JUDICIARY_READ: tuple[str, ...] = ("read:all",)
PERMISSIONS_COURT_WRITE: tuple[str, ...] = ("manage:all",)
PERMISSIONS_JUDGE_WRITE: tuple[str, ...] = ("manage:all",)
#: أساسُ العمل القضائيّ اليوميّ — نفسُ أساس مكتب الخزانة (R7-B) بلا اختراع.
PERMISSIONS_DOCKET_WRITE: tuple[str, ...] = ("write:tasks", "write:all", "manage:all")
PERMISSIONS_RULING_WRITE: tuple[str, ...] = ("write:tasks", "write:all", "manage:all")

#: كل ما تفحصه هذه الوحدة — محروسٌ باختبارٍ ساكن يمنع تسرّب مفردةٍ جديدة.
FEDERAL_JUDICIARY_PERMISSIONS: tuple[str, ...] = tuple(
    sorted(
        {
            *PERMISSIONS_JUDICIARY_READ,
            *PERMISSIONS_COURT_WRITE,
            *PERMISSIONS_JUDGE_WRITE,
            *PERMISSIONS_DOCKET_WRITE,
            *PERMISSIONS_RULING_WRITE,
        }
    )
)


__all__ = [
    "FEDERAL_JUDICIARY_PERMISSIONS",
    "PERMISSIONS_COURT_WRITE",
    "PERMISSIONS_DOCKET_WRITE",
    "PERMISSIONS_JUDGE_WRITE",
    "PERMISSIONS_JUDICIARY_READ",
    "PERMISSIONS_RULING_WRITE",
    "RegistryAuthorizationError",
    "require_domain_permission",
    "require_tenant",
]
