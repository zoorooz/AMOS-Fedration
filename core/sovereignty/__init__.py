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
    # contract — عقدُ التنفيذِ السياديّ (1E)
    "ContractBreach": "contract",
    "ContractError": "contract",
    "EffectKind": "contract",
    "EffectOutOfScopeError": "contract",
    "ExecutionContract": "contract",
    "ExecutionOutcome": "contract",
    "SovereignEffect": "contract",
    "bind_contract": "contract",
    "digest_of_payload": "contract",
    "in_scope": "contract",
    # enforcement — فصلُ موضعِ القرارِ عن موضعِ الإنفاذ (1F)
    "ConsumedPermitLedger": "enforcement",
    "EnforcementError": "enforcement",
    "EnforcementPermit": "enforcement",
    "PermitExpiredError": "enforcement",
    "PermitInvalidError": "enforcement",
    "PermitReplayError": "enforcement",
    "PermitScopeError": "enforcement",
    "PolicyEnforcementPoint": "enforcement",
    "issue_permit": "enforcement",
    # jurisdiction — جدارُ الاختصاصِ القضائيّ (1G)
    "FORBIDDEN_JUDICIAL_ACTIONS": "jurisdiction",
    "JUDICIAL_ACTIONS": "jurisdiction",
    "JUDICIAL_EFFECT_KINDS": "jurisdiction",
    "JUDICIAL_SCOPES": "jurisdiction",
    "JudicialAction": "jurisdiction",
    "JudicialOverreachError": "jurisdiction",
    "JurisdictionError": "jurisdiction",
    "JurisdictionWall": "jurisdiction",
    "NON_JUDICIAL_EFFECT_KINDS": "jurisdiction",
    "NON_JUDICIAL_SCOPE": "jurisdiction",
    "ROYAL_JUDICIAL_PREROGATIVES": "jurisdiction",
    "RoyalSupremacyViolationError": "jurisdiction",
    "WALL": "jurisdiction",
    # idempotency — حمايةُ الذرّيّةِ ومنعُ تكرارِ الأثر (1H)
    "DEFAULT_MAX_ATTEMPTS": "idempotency",
    "IDEMPOTENCY_DOMAIN": "idempotency",
    "IdempotencyConflictError": "idempotency",
    "IdempotencyError": "idempotency",
    "IdempotencyGuard": "idempotency",
    "IdempotencyKey": "idempotency",
    "IdempotencyKeyReuseError": "idempotency",
    "IdempotencyLedger": "idempotency",
    "IdempotencyRecord": "idempotency",
    "OperationNotRecoverableError": "idempotency",
    "OperationResult": "idempotency",
    "OperationStatus": "idempotency",
    "compute_fingerprint": "idempotency",
    # compensation — التعويضُ عن الأثرِ المُطبَّق (1I)
    "COMPENSATION_DOMAIN": "compensation",
    "IRREVERSIBLE_EFFECT_KINDS": "compensation",
    "CompensationError": "compensation",
    "CompensationGuard": "compensation",
    "CompensationJournal": "compensation",
    "CompensationOutcome": "compensation",
    "CompensationPlan": "compensation",
    "CompensationRecord": "compensation",
    "CompensationRequired": "compensation",
    "CompensationScopeError": "compensation",
    "CompensationStatus": "compensation",
    "Compensator": "compensation",
    "IrreversibleEffectError": "compensation",
    "UncompensatableEffectError": "compensation",
    "bind_compensation_plan": "compensation",
    "compute_compensation_id": "compensation",
    "effects_of": "compensation",
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
    "ExecutionAttempt": "fail_closed",
    "ExecutionCompletion": "fail_closed",
    "FailClosedError": "fail_closed",
    "IncompleteSovereignTransaction": "fail_closed",
    "MandatoryStage": "fail_closed",
    "attempt_execution": "fail_closed",
    "audit_anchor_of": "fail_closed",
    "require_audit_anchor": "fail_closed",
    "GatewayError": "gateway",
    "SovereignGateway": "gateway",
    "SovereigntyViolation": "gateway",
    # enforcement_boundary — حدُّ التنفيذِ السياديّ والحرسُ الساكن (1M)
    # يعتمد على gateway وعلى كلِّ حُرَّاسِ 1E–1K، فموضعُه آخرُ السلسلة.
    "BoundaryConfigurationError": "enforcement_boundary",
    "BoundaryOutcome": "enforcement_boundary",
    "BoundaryStage": "enforcement_boundary",
    "CompensationNotDeclaredError": "enforcement_boundary",
    "DEFAULT_GUARDED_SCOPE": "enforcement_boundary",
    "DEFINING_MODULES": "enforcement_boundary",
    "EnforcementBoundaryError": "enforcement_boundary",
    "GUARD_EXCEPTION_NAMES": "enforcement_boundary",
    "JurisdictionNotDeclaredError": "enforcement_boundary",
    "MANDATORY_EXTERNAL_STAGES": "enforcement_boundary",
    "MANDATORY_INTERNAL_STAGES": "enforcement_boundary",
    "MixedEffectContractError": "enforcement_boundary",
    "OperationKeyRequiredError": "enforcement_boundary",
    "OutboxNotConfiguredError": "enforcement_boundary",
    "SUCCESS_CLAIM_METHODS": "enforcement_boundary",
    "SovereignExecutionBoundary": "enforcement_boundary",
    "StaticEnforcementGuard": "enforcement_boundary",
    "StaticFinding": "enforcement_boundary",
    "StaticGuardError": "enforcement_boundary",
    "TERMINAL_SUCCESS_STATUS": "enforcement_boundary",
    "bypass_parameters_of": "enforcement_boundary",
}

__all__ = sorted(_EXPORTS)  # noqa: PLE0605 — sorted() returns list at runtime


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
