"""
AMOS-Federation Federal/State Integration (R8)
الهدف: طبقةُ الفدرالية والولايات — بنيةٌ صريحةٌ فوق ما بُني، بلا نظامٍ موازٍ
النطاق: services/federal_state
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17 (R8)

## ما تُضيفه هذه الحزمة وما لا تُضيفه

| تُضيف | **لا** تُضيف |
| --- | --- |
| سجلَّ حكوماتٍ كانونيًّا (فدراليةٌ + ولايات) | سجلَّ مؤسساتٍ ثانيًا (R7-A كما هو) |
| ربطَ مؤسسةٍ بحكومةٍ في جدولٍ رابط | عمودًا جديدًا على جدولٍ قائم |
| حدَّ الحكومة فوق قرار السلطة | محرّكَ تخويلٍ ثانيًا (R7-C وحدها) |
| تفويضًا صريحًا مُنطَّقًا قابلًا للنقض | سلطةً من دورٍ أو علاقةٍ أو موضعٍ في شجرة |
| نطاقَ خدمةٍ وإسنادَ قضيةٍ صريحين | خدماتٍ ولا قضايا جديدة (R7-A/2 كما هي) |
| أثرَ عمليةٍ يشير إلى `tasks.id` | منفِّذًا حكوميًّا موازيًا (`ExecutiveCore` وحدها) |
| قراءةَ موضعِ وكيلٍ بلا سلطة | سجلَّ وكلاءَ ولا سجلَّ سكّانٍ ثانيًا |
| عقودَ أحداثٍ في المفردة القائمة | ناقلَ أحداثٍ جديدًا |

والاستيرادُ من هنا مُقصَّرٌ على الواجهةِ والأخطاء وحلِّ السلطة: مَن يحتاج جدولًا
يستوردُه من `models` صراحةً، فيظهر في المراجعة من يمسّ المخطَّط.
"""

from __future__ import annotations

from amos_federation.services.federal_state.authority import (
    GovernmentAuthority,
    GovernmentAuthorityError,
    require_government_authority,
    resolve_government_authority,
)
from amos_federation.services.federal_state.delegation import DelegationError
from amos_federation.services.federal_state.models import FEDERAL_STATE_TABLES
from amos_federation.services.federal_state.scopes import (
    BoundaryVerdict,
    ScopePoint,
    evaluate_boundary,
)
from amos_federation.services.federal_state.service import (
    DuplicateGovernmentError,
    FederalStateGovernment,
    FederationError,
    GovernmentNotFoundError,
    get_federal_state,
    reset_federal_state,
)

__all__ = [
    "FEDERAL_STATE_TABLES",
    "BoundaryVerdict",
    "DelegationError",
    "DuplicateGovernmentError",
    "FederalStateGovernment",
    "FederationError",
    "GovernmentAuthority",
    "GovernmentAuthorityError",
    "GovernmentNotFoundError",
    "ScopePoint",
    "evaluate_boundary",
    "get_federal_state",
    "require_government_authority",
    "reset_federal_state",
    "resolve_government_authority",
]
