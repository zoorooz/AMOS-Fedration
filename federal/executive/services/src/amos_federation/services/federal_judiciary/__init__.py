"""
AMOS-Federation Federal Judiciary — Package Boundary
الهدف: مدخلٌ واحدٌ للقضاء الفدرالي: محكمةٌ ونطاقٌ وقضيةٌ وحكمٌ وتنفيذٌ مربوطٌ بما هو قائم
النطاق: services/federal_judiciary
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17 (R7-D)

    القانون → النطاق → القضية → الأطراف → المطالبات → الأدلّة → الإجراءات
            → المحكمة/القاضي → الحكم → التنفيذ

وما بُني هنا يقف على ما كان قائمًا ولا يُعيده: المؤسسة والمسؤول من `state_registry`
(R7-A)، والهوية والمنصب وحلُّ السلطة من `national_registry` (R7-C)، والمهمّة من
`executive_core`، والمال من `state_treasury`. و«القانون» في الأعلى ليس مبنيًّا:
المطالبةُ تحمل مرجعًا نصّيًّا **غير محقَّق** ويُقال ذلك في العمود نفسه.
"""

from __future__ import annotations

from amos_federation.services.federal_judiciary.authority import (
    JudicialAuthority,
    JudicialAuthorityError,
    require_judicial_authority,
    resolve_judicial_authority,
)
from amos_federation.services.federal_judiciary.authorization import (
    FEDERAL_JUDICIARY_PERMISSIONS,
)
from amos_federation.services.federal_judiciary.docket import (
    ALLOWED_TRANSITIONS,
    CaseNotFoundError,
    CaseTransitionError,
    EvidenceError,
    PartyIdentityError,
)
from amos_federation.services.federal_judiciary.enforcement import EnforcementError
from amos_federation.services.federal_judiciary.jurisdiction import JurisdictionError
from amos_federation.services.federal_judiciary.models import (
    CASE_STATUSES,
    FEDERAL_JUDICIARY_TABLES,
    JURISDICTIONS,
)
from amos_federation.services.federal_judiciary.registry import (
    CourtNotFoundError,
    InvalidCourtError,
    JudgeAppointmentError,
    JudiciaryError,
)
from amos_federation.services.federal_judiciary.rulings import (
    DuplicateRulingError,
    RulingError,
)
from amos_federation.services.federal_judiciary.service import (
    FederalJudiciary,
    get_federal_judiciary,
    reset_federal_judiciary,
)

__all__ = [
    "ALLOWED_TRANSITIONS",
    "CASE_STATUSES",
    "FEDERAL_JUDICIARY_PERMISSIONS",
    "FEDERAL_JUDICIARY_TABLES",
    "JURISDICTIONS",
    "CaseNotFoundError",
    "CaseTransitionError",
    "CourtNotFoundError",
    "DuplicateRulingError",
    "EnforcementError",
    "EvidenceError",
    "FederalJudiciary",
    "InvalidCourtError",
    "JudgeAppointmentError",
    "JudicialAuthority",
    "JudicialAuthorityError",
    "JudiciaryError",
    "JurisdictionError",
    "PartyIdentityError",
    "RulingError",
    "get_federal_judiciary",
    "require_judicial_authority",
    "reset_federal_judiciary",
    "resolve_judicial_authority",
]
