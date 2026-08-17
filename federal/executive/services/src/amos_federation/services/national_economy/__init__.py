"""
AMOS-Federation National Economy — الدولةُ الاقتصادية الوطنية (R9)
الهدف: طبقةُ الاقتصاد الحكوميّ **فوق** الخزانة والنواة والسجلّ القائمين
النطاق: services/national_economy
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17

## ما تُضيفه هذه الوحدة وما **لا** تُضيفه

| تُضيف | **لا** تُضيف |
| --- | --- |
| ١٣ جدولًا اقتصاديًّا بهجرةٍ صريحة (011) | جدولَ حركاتٍ ولا أرصدةً مخزّنة |
| ١١ عمليةً اقتصاديةً في مفردة R7-C القائمة | محرّكَ تخويلٍ ثانيًا |
| قرارًا اقتصاديًّا بإسنادٍ مُصرَّح (`state_economic_decisions`) | جدولَ قراراتٍ حكوميةٍ ثانيًا |
| ١٤ عقدَ حدثٍ في `common/event_bus` القائم | ناقلَ أحداثٍ ثانيًا |
| نداءً لواجهة `StateTreasury` **المُمرَّرة** | خزانةً ولا دفترًا ولا قفلَ صفوفٍ بديلًا |
| نوعَ مهمّةٍ واحدًا في `ExecutiveCore` | `economic_executor` ولا `policy_executor` |
| أثرَ عمليةٍ في `state_government_operations` القائم | جدولَ عملياتٍ ثانيًا |

## القدراتُ وتصنيفُها الصادق

| القدرة | التصنيف | لماذا |
| --- | --- | --- |
| تنفيذُ الصرف بالخزانة | REAL | `treasury.disburse` القائمة بأقفالها |
| التنفيذُ بالنواة التنفيذية | REAL | `submit` ثمّ `run` على الطابور نفسِه |
| تحصيلُ الإيراد | UNAVAILABLE | لا قناةَ دفعٍ ولا مُكلَّفَ في R9 |
| قياسُ المؤشّرات | UNAVAILABLE | تعريفٌ بلا مُحرِّكِ قياس |
| ملكيةُ الأصول خارجيًّا | UNAVAILABLE | الصفُّ يقول `SYSTEM_REGISTERED` فقط |
| نفاذُ الالتزامات خارجيًّا | UNAVAILABLE | لا جهةَ إنفاذٍ خارجيةً موصولة |
| سوقُ المشتريات | UNAVAILABLE | `INTERNAL_ABSTRACTION` بقيدِ قاعدة |

هذه التصنيفاتُ مُقيَّدةٌ في المخطَّط بمفرداتٍ لا تحتوي `REAL`، فلا يستطيع كودٌ
لاحقٌ أن يُرقّيها بنصٍّ أفضل — يلزمه هجرةٌ تُراجَع.
"""

from __future__ import annotations

from amos_federation.services.national_economy.authorization import (
    NATIONAL_ECONOMY_PERMISSIONS,
    OPERATION_SUBJECT_KINDS,
    TRANSFER_OPERATION_KINDS,
    EconomicAuthorizationError,
    assert_economic_operation,
    assert_subject_kind,
    preview_economic_authority,
    require_economic_authority,
)
from amos_federation.services.national_economy.models import (
    NATIONAL_ECONOMY_TABLES,
    EconomicCategoryModel,
    EconomicDecisionModel,
    EconomicIndicatorDefinitionModel,
    EconomicPolicyModel,
    EconomicProgramModel,
    EconomicSectorModel,
    EconomicTransferModel,
    ExpenditureAuthorizationModel,
    ProcurementModel,
    PublicAssetModel,
    PublicEconomicEntityModel,
    PublicLiabilityModel,
    RevenueSourceModel,
)
from amos_federation.services.national_economy.service import (
    DuplicateEconomicEntityError,
    EconomicEntityNotFoundError,
    EconomicStateError,
    NationalEconomy,
    get_national_economy,
    reset_national_economy,
)

__all__ = [
    "NATIONAL_ECONOMY_PERMISSIONS",
    "NATIONAL_ECONOMY_TABLES",
    "OPERATION_SUBJECT_KINDS",
    "TRANSFER_OPERATION_KINDS",
    "DuplicateEconomicEntityError",
    "EconomicAuthorizationError",
    "EconomicCategoryModel",
    "EconomicDecisionModel",
    "EconomicEntityNotFoundError",
    "EconomicIndicatorDefinitionModel",
    "EconomicPolicyModel",
    "EconomicProgramModel",
    "EconomicSectorModel",
    "EconomicStateError",
    "EconomicTransferModel",
    "ExpenditureAuthorizationModel",
    "NationalEconomy",
    "ProcurementModel",
    "PublicAssetModel",
    "PublicEconomicEntityModel",
    "PublicLiabilityModel",
    "RevenueSourceModel",
    "assert_economic_operation",
    "assert_subject_kind",
    "get_national_economy",
    "preview_economic_authority",
    "require_economic_authority",
    "reset_national_economy",
]
