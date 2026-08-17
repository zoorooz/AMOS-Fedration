"""الهدف: مزوِّد E2B — الملفّ **الوحيد** في المستودع الذي يستورد `e2b`.

النطاق: services/tool_registry/providers
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17

نفس قاعدة العزل المفروضة على مزوِّد Modal، ومحروسة بالاختبار الساكن نفسه:
كلمة `e2b` كاستيراد لا تظهر خارج هذا الملفّ. والاستيراد مؤجَّل داخل الدوالّ،
فغياب الحزمة `UNAVAILABLE` بسبب مُسمّى لا `ImportError` عند الإقلاع.

E2B و Modal ليسا نسخة واحدة باسمين، والفرق يظهر في هذا الملفّ: E2B يعطي
`Sandbox(...)` مع `commands.run(...)` التي تُرجع كائنًا فيه `stdout`/`stderr`/
`exit_code` جاهزة، ويُمرَّر المفتاح إليه صراحةً بـ`api_key`. ولذلك لا يُشتَقّ
هذا الملفّ من ملفّ Modal ولا يُختصَر إلى «نفس الشيء».

**حالة الصدق:** المُهيّئ **IMPLEMENTED**، وعقده **VERIFIED** باختبارات تعاقدية
على مضاعِف مُعلَن، وتنفيذٌ حقيقي على E2B **UNOBSERVED** في هذه الجولة لأن
`E2B_API_KEY` لم يكن متغيّر بيئة حقيقيًّا في بيئة التنفيذ.

`E2B_API_KEY` محجوب عن **داخل** الصندوق بـ`secrets.FORBIDDEN_SECRET_PATTERNS`:
هو اعتماد عملية المضيف عند مخاطبة E2B، لا سرٌّ تراه الأداة.
"""

from __future__ import annotations

import contextlib
import logging
import os
import time
import uuid
from typing import Any

from amos_federation.services.executive_core.fidelity import ExecutionFidelity
from amos_federation.services.tool_registry.providers import network, secrets
from amos_federation.services.tool_registry.providers.contract import (
    ExecutionRequest,
    ExecutionResult,
    ProviderAvailability,
    ProviderExecutionError,
    SandboxHandle,
    SandboxProvider,
    SandboxSpec,
)

_logger = logging.getLogger(__name__)

#: متغيّر البيئة الذي يلزمه E2B — يُسمّى ولا تُقرأ قيمته في أي سجل.
E2B_CREDENTIAL_VARS: tuple[str, ...] = ("E2B_API_KEY",)

#: قالب البيئة الافتراضي. يُضبَط بـ`AMOS_E2B_TEMPLATE`.
DEFAULT_E2B_TEMPLATE = "base"


class E2BProvider(SandboxProvider):
    """صندوق رملي على E2B عبر `e2b_code_interpreter` أو `e2b`."""

    name = "e2b"
    fidelity = ExecutionFidelity.REAL

    def __init__(self, template: str | None = None) -> None:
        self.template = template or os.environ.get("AMOS_E2B_TEMPLATE", DEFAULT_E2B_TEMPLATE)

    # --- التوفُّر -------------------------------------------------------

    def missing_credentials(self) -> tuple[str, ...]:
        return tuple(name for name in E2B_CREDENTIAL_VARS if not os.environ.get(name))

    def availability(self) -> ProviderAvailability:
        missing = self.missing_credentials()
        if missing:
            return ProviderAvailability(
                provider=self.name,
                available=False,
                fidelity=ExecutionFidelity.UNAVAILABLE.value,
                reason="مفتاح E2B غائب — لا يُدّعى REAL ولا يُستبدَل بمحاكاة",
                missing_credentials=missing,
            )
        factory = self._load_sdk()
        if factory is None:
            return ProviderAvailability(
                provider=self.name,
                available=False,
                fidelity=ExecutionFidelity.UNAVAILABLE.value,
                reason="حزمة e2b غير مثبَّتة في بيئة التنفيذ",
                missing_package="e2b",
            )
        return ProviderAvailability(
            provider=self.name,
            available=True,
            fidelity=self.fidelity.value,
            reason="مفتاح E2B موجود والحزمة مثبَّتة",
        )

    def _load_sdk(self) -> Any:
        """أعِد صنف `Sandbox` من أي حزمة E2B متاحة، أو `None`.

        تُجرَّب `e2b_code_interpreter` أولًا لأنها الحزمة الموصى بها للتنفيذ، ثم
        `e2b` الأساسية. المحاولتان صريحتان: تخمين اسم الحزمة الواحد يجعل الغياب
        يبدو غيابًا للخدمة.
        """
        try:
            from e2b_code_interpreter import Sandbox
        except ImportError:
            try:
                from e2b import Sandbox  # type: ignore[no-redef]
            except ImportError as exc:
                _logger.warning("حزمةُ E2B غائبة — المزوِّد UNAVAILABLE. %s", exc)
                return None
        return Sandbox

    # --- دورة الحياة ---------------------------------------------------

    def create_sandbox(self, spec: SandboxSpec) -> SandboxHandle:
        self.assert_usable()
        network.normalize_policy(spec.network_policy)
        secrets.assert_allowlist_is_safe(spec.secret_allowlist)

        sandbox_cls = self._load_sdk()
        if sandbox_cls is None:  # pragma: no cover - assert_usable سبقته
            raise ProviderExecutionError("e2b غير متاح بعد فحص التوفُّر")

        native = sandbox_cls(
            template=self.template,
            api_key=os.environ.get("E2B_API_KEY"),
            timeout=spec.timeout_seconds,
        )
        return SandboxHandle(
            sandbox_id=str(getattr(native, "sandbox_id", None) or f"e2b-{uuid.uuid4().hex[:12]}"),
            provider=self.name,
            spec=spec,
            native=native,
        )

    def execute(self, handle: SandboxHandle, request: ExecutionRequest) -> ExecutionResult:
        self._guard_handle(handle)
        spec = handle.spec
        env, plan = secrets.build_sandbox_env(
            spec.secret_allowlist,
            extra={
                "AMOS_SANDBOX_ID": handle.sandbox_id,
                "AMOS_SANDBOX_PROVIDER": self.name,
                "AMOS_SANDBOX_NETWORK_POLICY": spec.network_policy,
            },
        )
        timeout = request.timeout_seconds or spec.timeout_seconds
        command = " ".join(request.command) if request.command else None

        started = time.monotonic()
        try:
            if command is None:
                proc = handle.native.run_code(request.code, envs=env, timeout=timeout)
            else:
                proc = handle.native.commands.run(command, envs=env, timeout=timeout)
            stdout, stderr, exit_code = self._read(proc)
        except Exception as exc:  # noqa: BLE001 — يُنشَر كفشل حقيقي لا يُكتَم
            return self.result(
                handle,
                request,
                stdout="",
                stderr=str(exc),
                exit_code=None,
                duration_ms=int((time.monotonic() - started) * 1000),
                secrets_injected=plan.injected,
                error=f"e2b_execution_failed: {exc}",
            )

        return self.result(
            handle,
            request,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            duration_ms=int((time.monotonic() - started) * 1000),
            secrets_injected=plan.injected,
        )

    @staticmethod
    def _read(proc: Any) -> tuple[str, str, int | None]:
        """اقرأ مخرَج E2B بشكليه: `CommandResult` أو `Execution` مع `logs`.

        رمز الخروج يُقرأ إن أعطاه المزوِّد؛ وإن غاب فـ`None`، إلا أن وجود خطأ
        تنفيذ مُعلَن في `Execution.error` يُعطى `1` لأنه فشل مُثبَت لا مجهول.
        """
        logs = getattr(proc, "logs", None)
        if logs is not None:
            stdout = "".join(getattr(logs, "stdout", []) or [])
            stderr = "".join(getattr(logs, "stderr", []) or [])
            error = getattr(proc, "error", None)
            if error is not None:
                stderr = (stderr + "\n" + str(error)).strip()
                return stdout, stderr, 1
            return stdout, stderr, 0

        stdout = str(getattr(proc, "stdout", "") or "")
        stderr = str(getattr(proc, "stderr", "") or "")
        exit_code = getattr(proc, "exit_code", None)
        return stdout, stderr, exit_code if isinstance(exit_code, int) else None

    def terminate(self, handle: SandboxHandle) -> None:
        if handle.provider != self.name or handle.terminated:
            return
        native = handle.native
        for method in ("kill", "close"):
            candidate = getattr(native, method, None)
            if callable(candidate):
                # الإنهاء لا يفشل الطلب — الصندوق قد يكون مات عند المزوِّد أصلًا.
                with contextlib.suppress(Exception):
                    candidate()
                break
        handle.terminated = True

    def cleanup(self, handle: SandboxHandle) -> None:
        if handle.provider != self.name:
            return
        self.terminate(handle)
        handle.native = None
