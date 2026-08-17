"""طبقة مزوِّدات الصندوق الرملي — العقد وحده هو ما يُستورَد من خارجها.

الهدف: حصرُ مزوِّداتِ التنفيذِ المعزولِ خلفَ عقدٍ واحدٍ مُعلَن، فلا يرتبطُ مُستورِدٌ
بمكتبةِ مزوِّدٍ بعينه.

النطاق: services/tool_registry/providers
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17

المستورِد من خارج هذه الحزمة يأخذ `SandboxProvider` و`SandboxSpec` و
`ExecutionRequest` و`execute_in_sandbox`. ولا يستورد `modal` ولا `e2b` — هما
محبوسان في `modal_provider.py` و`e2b_provider.py`، ويحرس ذلك اختبار ساكن.
"""

from amos_federation.services.tool_registry.providers.contract import (
    PROVIDER_CONTRACT_METHODS,
    REQUIRED_METADATA_FIELDS,
    ExecutionContext,
    ExecutionRequest,
    ExecutionResult,
    ProviderAvailability,
    ProviderCredentialsMissingError,
    ProviderExecutionError,
    ProviderUnavailableError,
    SandboxHandle,
    SandboxNotCreatedError,
    SandboxProvider,
    SandboxProviderError,
    SandboxSpec,
    SandboxTerminatedError,
    SandboxTimeoutError,
)

__all__ = [
    "PROVIDER_CONTRACT_METHODS",
    "REQUIRED_METADATA_FIELDS",
    "ExecutionContext",
    "ExecutionRequest",
    "ExecutionResult",
    "ProviderAvailability",
    "ProviderCredentialsMissingError",
    "ProviderExecutionError",
    "ProviderUnavailableError",
    "SandboxHandle",
    "SandboxNotCreatedError",
    "SandboxProvider",
    "SandboxProviderError",
    "SandboxSpec",
    "SandboxTerminatedError",
    "SandboxTimeoutError",
    "availability_report",
    "execute_in_sandbox",
    "resolve_provider",
]


def __getattr__(name: str) -> object:
    """استيراد مؤجَّل لطبقة الاختيار — يمنع دور استيراد ويبقي الحزمة رخيصة."""
    if name in {"availability_report", "execute_in_sandbox", "resolve_provider"}:
        from amos_federation.services.tool_registry.providers import selection

        return getattr(selection, name)
    raise AttributeError(name)
