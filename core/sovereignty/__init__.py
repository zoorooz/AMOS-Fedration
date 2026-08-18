"""الهدف: نواة السيادة (E2) — السيادة الملكية كقوة نافذة لا كنص في وثيقة.

المالك: core/sovereignty/ — التاج
تاريخ الإنشاء: 2026-08-16
تاريخ آخر تعديل: 2026-08-18

التصدير هنا **متأخر** (PEP 562) بقصد معماري: النواة الدستورية تستورد
`core.sovereignty.prerogatives` و`core.sovereignty.crown` لتُنفّذ المادة العاشرة،
والبوابة تستورد النواة الدستورية. استيراد مبكر هنا يُغلق الحلقة ويُعطّل الاثنين.
اتجاه الاعتماد الوحيد المسموح: prerogatives/crown → (لا شيء) ثم rules → ثم gateway.
"""

from __future__ import annotations

from typing import Any

# لا إعادة استيراد هنا حتى للمُدقِّقات: أسماء التصدير تُحل عبر __getattr__ من
# الوحدات المباشرة (`core.sovereignty.crown` وغيرها)، وهو المسار الموصى به أيضًا
# للاستيراد الصريح داخل الشيفرة.

_EXPORTS: dict[str, str] = {
    # prerogatives — بلا أي اعتماد
    "FEDERALISM_BYPASS_ACTIONS": "prerogatives",
    "IMMUNE_CLAUSES": "prerogatives",
    "ROYAL_AUTHORITY_EROSION_ACTIONS": "prerogatives",
    "ROYAL_EXCLUSIVE_ACTIONS": "prerogatives",
    "bypasses_federalism": "prerogatives",
    "immune_clauses_touched": "prerogatives",
    "is_royal_exclusive": "prerogatives",
    "touches_royal_authority": "prerogatives",
    # crown
    "Crown": "crown",
    "CrownError": "crown",
    "CrownNotProvisionedError": "crown",
    "CrownTamperError": "crown",
    "crown_is_provisioned": "crown",
    "load_crown": "crown",
    "provision_crown": "crown",
    "enroll_crown": "crown",
    "issue_enrollment_challenge": "crown",
    "load_enrollment_challenge": "crown",
    "EnrollmentChallenge": "crown",
    "CrownEnrollmentError": "crown",
    "CrownImpersonationError": "crown",
    "ROOT_EXTERNAL_HUMAN": "crown",
    "ROOT_STATE_GENERATED": "crown",
    # decree
    "DecreeError": "decree",
    "DecreeRegistry": "decree",
    "DecreeReplayError": "decree",
    "DecreeSignatureError": "decree",
    "RoyalDecree": "decree",
    "sign_decree": "decree",
    # authority_grants — أثرُ المادة العاشرة · 10 التشغيليّ
    "ALL_CAPABILITIES": "authority_grants",
    "CONSTITUTIONAL_CARVE_OUTS": "authority_grants",
    "AuthorityGrant": "authority_grants",
    "AuthorityGrantError": "authority_grants",
    "AuthorityGrantRegistry": "authority_grants",
    "GrantState": "authority_grants",
    "NonSovereignGrantError": "authority_grants",
    "RoyalAuthorityErosionError": "authority_grants",
    # gateway — يعتمد على النواة الدستورية
    "AuthorityWithdrawn": "gateway",
    "ExecutionRecord": "gateway",
    "GatewayError": "gateway",
    "SovereignGateway": "gateway",
    "SovereigntyViolation": "gateway",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module 'core.sovereignty' has no attribute '{name}'")
    from importlib import import_module

    value = getattr(import_module(f"core.sovereignty.{module_name}"), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return __all__
