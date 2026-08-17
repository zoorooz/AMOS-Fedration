"""
AMOS-Federation National Registry
الهدف: السجل الوطني للهوية الكانونية — الحلقة التي تربط الجلسة بالمنصب بالمال
النطاق: services/national_registry
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17 (R7-C)
"""

from amos_federation.services.national_registry.resolver import (
    AuthorityDecision,
    ForgedAuthorityError,
    IdentityResolution,
    IdentityResolutionError,
    resolve_authority,
    resolve_identity,
    resolve_official_for_principal,
)
from amos_federation.services.national_registry.service import (
    NationalRegistry,
    get_national_registry,
    reset_national_registry,
)

__all__ = [
    "AuthorityDecision",
    "ForgedAuthorityError",
    "IdentityResolution",
    "IdentityResolutionError",
    "NationalRegistry",
    "get_national_registry",
    "reset_national_registry",
    "resolve_authority",
    "resolve_identity",
    "resolve_official_for_principal",
]
