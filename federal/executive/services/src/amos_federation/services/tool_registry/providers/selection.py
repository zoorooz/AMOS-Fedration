"""الهدف: اختيار المزوِّد وسقوطٌ مُعلَن — لا سقوط صامت أبدًا.

النطاق: services/tool_registry/providers
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17

الإعداد:

- `AMOS_SANDBOX_PROVIDER` = `local` | `modal` | `e2b` | `simulation`
  (الافتراضي `local` — لا تغيير سلوكٍ لمن لم يُعِدّ شيئًا).
- `AMOS_SANDBOX_FALLBACK_PROVIDER` — بديل اختياري.
- `AMOS_SANDBOX_FALLBACK_ENABLED` — يجب أن تكون `1`/`true` **صراحةً**. تسمية
  بديلٍ وحدها لا تُشغِّل السقوط.

ثلاث قواعد تُنفَّذ هنا لا في التوثيق:

1. **لا سقوط غير مُعلَن.** كل نتيجة أتت من بديل تحمل `fallback_from` و
   `fallback_reason`، ويُنشَر حدث `amos_federation.sandbox.fallback`.
2. **لا سقوط إلى محاكاة.** `simulation` مستثنى من كل مسار سقوط، حتى إن سُمّي
   بديلًا: يُرفَض عند البناء لا عند الاستعمال.
3. **الغياب لا يُبدَّل بنجاح.** إن كان الأساس والبديل غير متاحين تُرفَع
   `ProviderUnavailableError` بأسباب المزوِّدين معًا. الطلب يفشل، ولا يُرجَع
   مخرَج يبدو ناجحًا.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from amos_federation.services.tool_registry.providers.contract import (
    ExecutionRequest,
    ExecutionResult,
    ProviderAvailability,
    ProviderUnavailableError,
    SandboxProvider,
    SandboxProviderError,
    SandboxSpec,
)
from amos_federation.services.tool_registry.providers.e2b_provider import E2BProvider
from amos_federation.services.tool_registry.providers.local_provider import (
    LocalSubprocessProvider,
)
from amos_federation.services.tool_registry.providers.modal_provider import ModalProvider
from amos_federation.services.tool_registry.providers.simulation_provider import (
    SimulationProvider,
)

_logger = logging.getLogger(__name__)

#: المزوِّد الافتراضي حين لا إعداد — سلوك ما قبل R5 نفسه.
DEFAULT_PROVIDER = "local"

#: مزوِّدات لا يجوز السقوط إليها بحال. المحاكاة ليست بديلًا عن تنفيذ حقيقي.
NON_FALLBACK_PROVIDERS: frozenset[str] = frozenset({"simulation"})

_BUILDERS: dict[str, Any] = {
    "local": LocalSubprocessProvider,
    "modal": ModalProvider,
    "e2b": E2BProvider,
    "simulation": SimulationProvider,
}

#: أسماء المزوِّدات المعروفة — تُستعمل في رسائل الخطأ والتقارير.
KNOWN_PROVIDERS: tuple[str, ...] = tuple(_BUILDERS)


class UnknownProviderError(SandboxProviderError):
    """اسم مزوِّد غير معروف في الإعداد — يُرفَض ولا يُستبدَل بالافتراضي بصمت."""


class FallbackNotPermittedError(SandboxProviderError):
    """بديل غير جائز: مزوِّد محاكاة، أو سقوط غير مُفعَّل صراحةً."""


def build_provider(name: str) -> SandboxProvider:
    """ابنِ مزوِّدًا بالاسم. الاسم المجهول خطأ لا افتراضي صامت."""
    key = (name or "").strip().lower()
    builder = _BUILDERS.get(key)
    if builder is None:
        raise UnknownProviderError(
            f"مزوِّد غير معروف: '{name}' — المعروف: {', '.join(KNOWN_PROVIDERS)}"
        )
    return builder()


@dataclass(frozen=True)
class SandboxSelection:
    """الإعداد المقروء من البيئة، مُصرَّحًا به بالكامل."""

    primary: str
    fallback: str | None
    fallback_enabled: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "primary_provider": self.primary,
            "fallback_provider": self.fallback,
            "fallback_enabled": self.fallback_enabled,
        }


def _flag(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def read_selection(env: dict[str, str] | None = None) -> SandboxSelection:
    """اقرأ الإعداد من البيئة وتحقّق منه — لا قيمة مجهولة تمرّ."""
    source = os.environ if env is None else env
    primary = (source.get("AMOS_SANDBOX_PROVIDER") or DEFAULT_PROVIDER).strip().lower()
    if primary not in _BUILDERS:
        raise UnknownProviderError(
            f"AMOS_SANDBOX_PROVIDER غير معروف: '{primary}' — المعروف: {', '.join(KNOWN_PROVIDERS)}"
        )

    fallback_raw = (source.get("AMOS_SANDBOX_FALLBACK_PROVIDER") or "").strip().lower()
    fallback = fallback_raw or None
    if fallback and fallback not in _BUILDERS:
        raise UnknownProviderError(f"AMOS_SANDBOX_FALLBACK_PROVIDER غير معروف: '{fallback}'")
    if fallback in NON_FALLBACK_PROVIDERS:
        raise FallbackNotPermittedError(
            f"'{fallback}' لا يجوز أن يكون بديلًا — المحاكاة ليست سقوطًا عن تنفيذ حقيقي"
        )
    if fallback == primary:
        raise FallbackNotPermittedError("البديل نفس الأساس — سقوط بلا معنى")

    enabled_key = "AMOS_SANDBOX_FALLBACK_ENABLED"
    enabled = (
        _flag(enabled_key)
        if env is None
        else (source.get(enabled_key) or "").strip().lower() in {"1", "true", "yes", "on"}
    )
    return SandboxSelection(primary=primary, fallback=fallback, fallback_enabled=enabled)


def availability_report(env: dict[str, str] | None = None) -> dict[str, Any]:
    """تقرير توفُّر لكل مزوِّد معروف — بلا إنشاء صندوق واحد.

    يُستعمل في نقاط الصحّة: مزوِّد ناقص الاعتماد يظهر `UNAVAILABLE` باسم
    المتغيّر الناقص، لا مخفيًّا ولا مُقنَّعًا بمحاكاة.
    """
    selection = read_selection(env)
    providers: dict[str, Any] = {}
    for name in KNOWN_PROVIDERS:
        try:
            state = build_provider(name).availability()
        except SandboxProviderError as exc:  # pragma: no cover - بناء لا يفشل عادةً
            state = ProviderAvailability(
                provider=name,
                available=False,
                fidelity="UNAVAILABLE",
                reason=str(exc),
            )
        providers[name] = state.as_dict()
    return {
        "selection": selection.as_dict(),
        "providers": providers,
        "real_providers_available": sorted(
            name
            for name, state in providers.items()
            if state["available"] and state["execution_fidelity"] == "REAL"
        ),
    }


@dataclass
class ProviderResolution:
    """المزوِّد الذي سيُستعمل فعلًا، ومَن سقط قبله وبأي سبب."""

    provider: SandboxProvider
    fallback_from: str | None = None
    fallback_reason: str | None = None


def resolve_provider(env: dict[str, str] | None = None) -> ProviderResolution:
    """اختر المزوِّد المتاح وفق الإعداد، وأعلِن السقوط إن وقع.

    Raises:
        ProviderUnavailableError: إن لم يتوفّر الأساس ولا بديل جائز مُفعَّل.
    """
    selection = read_selection(env)
    primary = build_provider(selection.primary)
    primary_state = primary.availability()
    if primary_state.available:
        return ProviderResolution(provider=primary)

    reason = _describe(primary_state)

    if not selection.fallback:
        raise ProviderUnavailableError(
            f"المزوِّد '{selection.primary}' غير متاح ({reason}) ولا بديل مُعَدّ"
        )
    if not selection.fallback_enabled:
        raise ProviderUnavailableError(
            f"المزوِّد '{selection.primary}' غير متاح ({reason})؛ "
            f"البديل '{selection.fallback}' مُسمّى لكن AMOS_SANDBOX_FALLBACK_ENABLED غير مُفعَّل — "
            "لا سقوط بلا إذن صريح"
        )

    fallback = build_provider(selection.fallback)
    fallback_state = fallback.availability()
    if not fallback_state.available:
        raise ProviderUnavailableError(
            f"لا مزوِّد متاح: '{selection.primary}' ({reason}) "
            f"و'{selection.fallback}' ({_describe(fallback_state)})"
        )

    _publish_fallback(selection.primary, selection.fallback, reason)
    return ProviderResolution(
        provider=fallback,
        fallback_from=selection.primary,
        fallback_reason=reason,
    )


def _describe(state: ProviderAvailability) -> str:
    if state.missing_credentials:
        return f"اعتماد ناقص: {', '.join(state.missing_credentials)}"
    if state.missing_package:
        return f"حزمة غائبة: {state.missing_package}"
    return state.reason or "غير متاح"


def _publish_fallback(source: str, target: str, reason: str) -> None:
    """أعلِن السقوط في ناقل الأحداث — فشل النشر لا يُبطل الإعلان في النتيجة."""
    try:
        from amos_federation.common.event_bus import get_event_bus

        get_event_bus().publish(
            "amos_federation.sandbox.fallback",
            {"from_provider": source, "to_provider": target, "reason": reason},
        )
    except Exception as exc:  # noqa: BLE001 — الناقل قد يكون غير مُهيّأ في الاختبارات
        _logger.warning("تعذّر نشرُ حدث sandbox.fallback — %s", exc)


def execute_in_sandbox(
    spec: SandboxSpec,
    request: ExecutionRequest,
    *,
    provider: SandboxProvider | None = None,
    env: dict[str, str] | None = None,
) -> ExecutionResult:
    """دورة حياة كاملة: اختيار ثم إنشاء ثم تنفيذ ثم إنهاء ثم تنظيف.

    `terminate` و`cleanup` في `finally`: صندوق يُترك قائمًا بعد فشل تنفيذ هو
    تسريب موارد عند مزوِّد يُحاسَب بالثانية.
    """
    if provider is not None:
        resolution = ProviderResolution(provider=provider)
    else:
        resolution = resolve_provider(env)

    active = resolution.provider
    handle = active.create_sandbox(spec)
    try:
        result = active.execute(handle, request)
    finally:
        active.terminate(handle)
        active.cleanup(handle)

    if resolution.fallback_from:
        from dataclasses import replace

        result = replace(
            result,
            fallback_from=resolution.fallback_from,
            fallback_reason=resolution.fallback_reason,
        )
    return result
