"""الهدف: مزوِّد Modal — الملفّ **الوحيد** في المستودع الذي يستورد `modal`.

النطاق: services/tool_registry/providers
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17

قاعدة العزل، وهي محروسة باختبار ساكن لا بالاتفاق: كلمة `modal` كاستيراد لا
تظهر إلا هنا. أي وحدة أخرى — وبيئة تشغيل الوكلاء أولها — تتعامل مع
`SandboxProvider` وحده، فاستبدال Modal بغيره لا يلمس سطرًا خارج هذا الملفّ.

الاستيراد **داخل الدوالّ** لا في رأس الملفّ. لأن `modal` اعتماد اختياري: من لم
يختره لا يجب أن يسقط نظامه عند استيراد وحدة المزوِّدات، ومن اختاره ولم يثبّت
الحزمة يجب أن يقرأ `UNAVAILABLE` بسبب مُسمّى لا `ImportError` عند الإقلاع.

**حالة الصدق:** المُهيّئ نفسه **IMPLEMENTED**، وعقده **VERIFIED** باختبارات
تعاقدية على مضاعِف مُعلَن. أما تنفيذ حقيقي على Modal فهو **UNOBSERVED**: لم
يُرصَد في هذه الجولة لأن `MODAL_TOKEN_ID` و`MODAL_TOKEN_SECRET` لم يكونا
متغيّري بيئة حقيقيّين في بيئة التنفيذ. طريق الرصد الحقيقي في
`docs/audit/R5_MULTI_PROVIDER_SANDBOX.md`.

اعتمادات Modal تُستعمل في **عملية المضيف** عند مخاطبة الخدمة، ولا تُمرَّر داخل
الصندوق: `secrets.FORBIDDEN_SECRET_PATTERNS` تحجب `MODAL_TOKEN` عن بيئة الصندوق
حتى لو وُضِعت في قائمة السماح.
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

#: متغيّرات البيئة التي يلزمها Modal — تُسمّى ولا تُقرأ قيمها في أي سجل.
MODAL_CREDENTIAL_VARS: tuple[str, ...] = ("MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET")

#: صورة التنفيذ الافتراضية. تُضبَط بـ`AMOS_MODAL_IMAGE`.
DEFAULT_MODAL_IMAGE = "python:3.12-slim"


class ModalProvider(SandboxProvider):
    """صندوق رملي على Modal عبر `modal.Sandbox`."""

    name = "modal"
    fidelity = ExecutionFidelity.REAL

    def __init__(self, image: str | None = None, app_name: str = "amos-federation-sandbox") -> None:
        # لا استيراد ولا اتصال هنا بقصد: بناء الكائن يجب أن يكون رخيصًا وآمنًا.
        self.image = image or os.environ.get("AMOS_MODAL_IMAGE", DEFAULT_MODAL_IMAGE)
        self.app_name = app_name

    # --- التوفُّر -------------------------------------------------------

    def missing_credentials(self) -> tuple[str, ...]:
        """أسماء الاعتمادات الناقصة — الأسماء وحدها، لا القيم."""
        return tuple(name for name in MODAL_CREDENTIAL_VARS if not os.environ.get(name))

    def availability(self) -> ProviderAvailability:
        missing = self.missing_credentials()
        if missing:
            return ProviderAvailability(
                provider=self.name,
                available=False,
                fidelity=ExecutionFidelity.UNAVAILABLE.value,
                reason="اعتمادات Modal غائبة — لا يُدّعى REAL ولا يُستبدَل بمحاكاة",
                missing_credentials=missing,
            )
        client = self._load_sdk()
        if client is None:
            return ProviderAvailability(
                provider=self.name,
                available=False,
                fidelity=ExecutionFidelity.UNAVAILABLE.value,
                reason="حزمة modal غير مثبَّتة في بيئة التنفيذ",
                missing_package="modal",
            )
        return ProviderAvailability(
            provider=self.name,
            available=True,
            fidelity=self.fidelity.value,
            reason="اعتمادات Modal موجودة والحزمة مثبَّتة",
        )

    def _load_sdk(self) -> Any:
        """استيراد مؤجَّل للحزمة — غيابها `UNAVAILABLE` لا انهيار إقلاع."""
        try:
            import modal
        except ImportError as exc:
            _logger.warning("حزمةُ Modal غائبة — المزوِّد UNAVAILABLE. %s", exc)
            return None
        return modal

    # --- دورة الحياة ---------------------------------------------------

    def create_sandbox(self, spec: SandboxSpec) -> SandboxHandle:
        self.assert_usable()
        network.normalize_policy(spec.network_policy)
        secrets.assert_allowlist_is_safe(spec.secret_allowlist)

        sdk = self._load_sdk()
        if sdk is None:  # pragma: no cover - assert_usable سبقته
            raise ProviderExecutionError("modal غير متاح بعد فحص التوفُّر")

        # فحص قائمة السماح قبل الإنشاء: بيئة التنفيذ تُبنى في `execute` لكل طلب.
        secrets.build_sandbox_env(spec.secret_allowlist)
        app = sdk.App.lookup(self.app_name, create_if_missing=True)
        image = sdk.Image.from_registry(self.image)
        native = sdk.Sandbox.create(
            app=app,
            image=image,
            timeout=spec.timeout_seconds,
            block_network=spec.network_policy == "DENY",
        )
        return SandboxHandle(
            sandbox_id=str(getattr(native, "object_id", None) or f"modal-{uuid.uuid4().hex[:12]}"),
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
        argv = list(request.command) or ["python3", "-c", request.code]
        timeout = request.timeout_seconds or spec.timeout_seconds

        started = time.monotonic()
        try:
            proc = handle.native.exec(*argv, env=env, timeout=timeout)
            stdout = self._drain(getattr(proc, "stdout", ""))
            stderr = self._drain(getattr(proc, "stderr", ""))
            exit_code = self._exit_code(proc)
        except Exception as exc:  # noqa: BLE001 — يُنشَر كفشل حقيقي لا يُكتَم
            return self.result(
                handle,
                request,
                stdout="",
                stderr=str(exc),
                exit_code=None,
                duration_ms=int((time.monotonic() - started) * 1000),
                secrets_injected=plan.injected,
                error=f"modal_execution_failed: {exc}",
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
    def _drain(stream: Any) -> str:
        """اقرأ مجرى Modal بأي شكل جاء — نصًّا أو قابلًا للقراءة أو مُكرِّرًا."""
        if stream is None:
            return ""
        if isinstance(stream, str):
            return stream
        if isinstance(stream, bytes):
            return stream.decode("utf-8", errors="replace")
        read = getattr(stream, "read", None)
        if callable(read):
            value = read()
            if isinstance(value, bytes):
                return value.decode("utf-8", errors="replace")
            return str(value)
        try:
            return "".join(
                chunk.decode("utf-8", errors="replace") if isinstance(chunk, bytes) else str(chunk)
                for chunk in stream
            )
        except TypeError as exc:
            _logger.warning("مَجرى مخرجاتٍ غيرُ قابلٍ للتكرار — %s", exc)
            return str(stream)

    @staticmethod
    def _exit_code(proc: Any) -> int | None:
        """رمز الخروج الحقيقي — و`None` إن لم يُعطِه المزوِّد. لا صفر مُخترَع."""
        wait = getattr(proc, "wait", None)
        if callable(wait):
            value = wait()
            if isinstance(value, int):
                return value
        for attribute in ("returncode", "exit_code"):
            value = getattr(proc, attribute, None)
            if isinstance(value, int):
                return value
        return None

    def terminate(self, handle: SandboxHandle) -> None:
        if handle.provider != self.name or handle.terminated:
            return
        native = handle.native
        terminate = getattr(native, "terminate", None)
        if callable(terminate):
            # الإنهاء لا يفشل الطلب — الصندوق قد يكون مات عند المزوِّد أصلًا.
            with contextlib.suppress(Exception):
                terminate()
        handle.terminated = True

    def cleanup(self, handle: SandboxHandle) -> None:
        if handle.provider != self.name:
            return
        self.terminate(handle)
        handle.native = None
