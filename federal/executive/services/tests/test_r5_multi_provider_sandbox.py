"""اختبارات R5 — صندوق رملي متعدّد المزوِّدات.

الهدف: فحصُ عقدِ مزوِّداتِ الصندوقِ الرمليِّ ودورةِ حياتِه وحدودِه دونَ الادِّعاءِ
بأنَّ خدمةً حقيقيةً شُغِّلت.

النطاق: services/tool_registry/providers + authorized_execution
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17

ما تفحصه هذه الحزمة وما لا تفحصه — يُقال هنا لا في التقرير:

- **تُفحَص:** العقد، اختيار المزوِّد، دورة الحياة وترتيبها، المهلة، فصل
  `stdout`/`stderr`، صدق رمز الخروج، الإنهاء والتنظيف، رفض التخويل، حدّ الأسرار،
  سياسة الشبكة، النَسَب، مفردات الصدق، انتشار الفشل، والحرس الساكن.
- **لا تُفحَص:** تنفيذ حقيقي على Modal أو E2B. لم تُوجَد اعتمادات حقيقية في هذه
  الجولة، فحالة ذلك **UNOBSERVED** ولا يُدّعى غيرها. مضاعِفات SDK هنا تفحص
  **العقد** لا الخدمة، وهي مُسمّاة `_Fake*` بقصد.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amos_federation.services.executive_core.fidelity import ExecutionFidelity  # noqa: E402
from amos_federation.services.tool_registry.providers import (  # noqa: E402  # noqa: E402
    PROVIDER_CONTRACT_METHODS,
    REQUIRED_METADATA_FIELDS,
    ExecutionContext,
    ExecutionRequest,
    ProviderUnavailableError,
    SandboxNotCreatedError,
    SandboxProvider,
    SandboxSpec,
    SandboxTerminatedError,
    network,
    secrets,
    selection,
)
from amos_federation.services.tool_registry.providers.e2b_provider import E2BProvider  # noqa: E402
from amos_federation.services.tool_registry.providers.local_provider import (  # noqa: E402
    LocalSubprocessProvider,
)
from amos_federation.services.tool_registry.providers.modal_provider import (  # noqa: E402
    ModalProvider,
)
from amos_federation.services.tool_registry.providers.simulation_provider import (  # noqa: E402
    SimulationProvider,
)

_SERVICES_ROOT = Path(__file__).resolve().parents[1] / "src/amos_federation/services"


def _spec(**overrides: Any) -> SandboxSpec:
    base: dict[str, Any] = {"tool_id": "python_execute", "timeout_seconds": 8}
    base.update(overrides)
    return SandboxSpec(**base)


def _request(code: str, **overrides: Any) -> ExecutionRequest:
    context = ExecutionContext(tool_id="python_execute", agent_id="agent-t", task_id="task-t")
    return ExecutionRequest(code=code, context=context, **overrides)


def _strip_comments_and_strings(source: str) -> str:
    """أزِل التعليقات وسلاسل التوثيق حتى لا يمرّ الحرس الساكن بحكم التوثيق."""
    source = re.sub(r'""".*?"""', "", source, flags=re.S)
    source = re.sub(r"'''.*?'''", "", source, flags=re.S)
    return "\n".join(line for line in source.splitlines() if not line.strip().startswith("#"))


# === 1. عقد المزوِّد =====================================================


def test_every_provider_implements_the_same_lifecycle_contract() -> None:
    """كل مزوِّد يحقّق العقد نفسه: إنشاء، تنفيذ، إنهاء، تنظيف، وتوفُّر مُعلَن."""
    providers = [
        LocalSubprocessProvider(),
        ModalProvider(),
        E2BProvider(),
        SimulationProvider(),
    ]
    for provider in providers:
        assert isinstance(provider, SandboxProvider)
        for method in PROVIDER_CONTRACT_METHODS:
            assert callable(getattr(provider, method)), f"{provider.name} ينقصه {method}"
        state = provider.availability()
        assert state.provider == provider.name
        assert state.fidelity in {f.value for f in ExecutionFidelity}
        # المزوِّد غير المتاح يلزمه سبب مُسمّى — الغياب بلا سبب إعلانٌ فارغ.
        if not state.available:
            assert state.reason


# === 2. مُهيّئ Modal =====================================================


class _FakeModalProc:
    def __init__(self, stdout: str, stderr: str, code: int) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self._code = code
        self.env: dict[str, str] = {}

    def wait(self) -> int:
        return self._code


class _FakeModalSandbox:
    def __init__(self) -> None:
        self.object_id = "sb-modal-fake"
        self.terminated = False
        self.last_env: dict[str, str] = {}

    def exec(self, *argv: str, env: dict[str, str], timeout: int) -> _FakeModalProc:
        self.last_env = env
        return _FakeModalProc(f"modal-ran::{argv[-1][:20]}", "", 0)

    def terminate(self) -> None:
        self.terminated = True


class _FakeModalSDK:
    """مضاعِف SDK — يفحص **العقد** لا خدمة Modal. لا يُدّعى أنه تنفيذ حقيقي."""

    def __init__(self) -> None:
        self.sandbox = _FakeModalSandbox()
        sdk = self

        class _App:
            @staticmethod
            def lookup(name: str, create_if_missing: bool = False) -> str:
                return f"app::{name}"

        class _Image:
            @staticmethod
            def from_registry(tag: str) -> str:
                return f"image::{tag}"

        class _Sandbox:
            @staticmethod
            def create(**kwargs: Any) -> _FakeModalSandbox:
                sdk.create_kwargs = kwargs
                return sdk.sandbox

        self.App = _App
        self.Image = _Image
        self.Sandbox = _Sandbox
        self.create_kwargs: dict[str, Any] = {}


def test_modal_adapter_honours_the_contract_on_a_declared_fake_sdk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """مُهيّئ Modal يُنشئ ويُنفّذ ويُنهي عبر SDK — بمخرَج موحَّد ونَسَب كامل.

    هذا اختبار **عقد**. تنفيذ حقيقي على Modal حالته UNOBSERVED.
    """
    monkeypatch.setenv("MODAL_TOKEN_ID", "token-id-placeholder")
    monkeypatch.setenv("MODAL_TOKEN_SECRET", "token-secret-placeholder")
    provider = ModalProvider()
    fake = _FakeModalSDK()
    monkeypatch.setattr(provider, "_load_sdk", lambda: fake)

    assert provider.availability().available is True
    handle = provider.create_sandbox(_spec())
    assert handle.provider == "modal"
    assert handle.sandbox_id == "sb-modal-fake"
    # DENY يجب أن يصل إلى المزوِّد كحبس شبكي لا كتصريح فقط.
    assert fake.create_kwargs["block_network"] is True

    result = provider.execute(handle, _request("print(1)"))
    assert result.exit_code == 0
    assert "modal-ran" in result.stdout
    assert result.provider == "modal"
    assert result.execution_fidelity == ExecutionFidelity.REAL.value

    provider.terminate(handle)
    assert fake.sandbox.terminated is True
    provider.cleanup(handle)
    provider.cleanup(handle)  # متكرِّر بلا خطأ


# === 3. مُهيّئ E2B ======================================================


class _FakeE2BCommands:
    def __init__(self, outer: _FakeE2BSandbox) -> None:
        self._outer = outer

    def run(self, command: str, envs: dict[str, str], timeout: int) -> Any:
        self._outer.last_env = envs

        class _Result:
            stdout = f"e2b-ran::{command}"
            stderr = ""
            exit_code = 0

        return _Result()


class _FakeE2BSandbox:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.sandbox_id = "sb-e2b-fake"
        self.killed = False
        self.last_env: dict[str, str] = {}
        self.commands = _FakeE2BCommands(self)

    def run_code(self, code: str, envs: dict[str, str], timeout: int) -> Any:
        self.last_env = envs

        class _Logs:
            stdout = [f"e2b-code::{code}"]
            stderr: list[str] = []

        class _Execution:
            logs = _Logs()
            error = None

        return _Execution()

    def kill(self) -> None:
        self.killed = True


def test_e2b_adapter_honours_the_contract_on_a_declared_fake_sdk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """مُهيّئ E2B يقرأ `logs.stdout`/`logs.stderr` ويُعطي رمز خروج ويُنهي.

    اختبار **عقد**؛ تنفيذ حقيقي على E2B حالته UNOBSERVED.
    """
    monkeypatch.setenv("E2B_API_KEY", "e2b-key-placeholder")
    provider = E2BProvider()
    created: list[_FakeE2BSandbox] = []

    def _factory(**kwargs: Any) -> _FakeE2BSandbox:
        native = _FakeE2BSandbox(**kwargs)
        created.append(native)
        return native

    monkeypatch.setattr(provider, "_load_sdk", lambda: _factory)

    assert provider.availability().available is True
    handle = provider.create_sandbox(_spec())
    assert handle.provider == "e2b"
    assert handle.sandbox_id == "sb-e2b-fake"

    result = provider.execute(handle, _request("print(2)"))
    assert result.exit_code == 0
    assert "e2b-code::print(2)" in result.stdout
    assert result.execution_fidelity == ExecutionFidelity.REAL.value

    provider.terminate(handle)
    assert created[0].killed is True
    provider.cleanup(handle)


# === 4. اختيار المزوِّد ==================================================


def test_provider_selection_reads_config_and_rejects_unknown_names() -> None:
    """`SANDBOX_PROVIDER` يحكم الاختيار، والاسم المجهول خطأ لا افتراضي صامت."""
    assert selection.read_selection({}).primary == "local"
    assert selection.read_selection({"AMOS_SANDBOX_PROVIDER": "modal"}).primary == "modal"
    assert selection.read_selection({"AMOS_SANDBOX_PROVIDER": "E2B"}).primary == "e2b"

    with pytest.raises(selection.UnknownProviderError):
        selection.read_selection({"AMOS_SANDBOX_PROVIDER": "kubernetes"})
    with pytest.raises(selection.UnknownProviderError):
        selection.build_provider("kubernetes")

    assert isinstance(selection.build_provider("modal"), ModalProvider)
    assert isinstance(selection.build_provider("e2b"), E2BProvider)


# === 5. اعتمادات ناقصة =================================================


def test_missing_credentials_are_unavailable_and_never_simulation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """الاعتماد الناقص يُسمّى، والحالة UNAVAILABLE — لا محاكاة ولا زعم REAL."""
    monkeypatch.delenv("MODAL_TOKEN_ID", raising=False)
    monkeypatch.delenv("MODAL_TOKEN_SECRET", raising=False)
    monkeypatch.delenv("E2B_API_KEY", raising=False)

    modal_state = ModalProvider().availability()
    assert modal_state.available is False
    assert modal_state.fidelity == ExecutionFidelity.UNAVAILABLE.value
    assert set(modal_state.missing_credentials) == {"MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET"}

    e2b_state = E2BProvider().availability()
    assert e2b_state.available is False
    assert e2b_state.fidelity == ExecutionFidelity.UNAVAILABLE.value
    assert e2b_state.missing_credentials == ("E2B_API_KEY",)

    # الأسماء تُذكَر، والقيم لا تُذكَر أبدًا.
    monkeypatch.setenv("MODAL_TOKEN_ID", "super-secret-value")
    partial = ModalProvider().availability()
    assert "super-secret-value" not in str(partial.as_dict())
    assert partial.missing_credentials == ("MODAL_TOKEN_SECRET",)

    # ولا يُنشأ صندوق: الغياب يُرفَع صراحةً.
    monkeypatch.delenv("MODAL_TOKEN_ID", raising=False)
    with pytest.raises(ProviderUnavailableError):
        ModalProvider().create_sandbox(_spec())


# === 6. مزوِّد غير متاح بلا سقوط صامت ===================================


def test_unavailable_primary_fails_loudly_without_silent_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """مزوِّد غير متاح يُسقِط الطلب صراحةً؛ ولا يُستبدَل بغيره بلا إذن."""
    monkeypatch.delenv("MODAL_TOKEN_ID", raising=False)
    monkeypatch.delenv("MODAL_TOKEN_SECRET", raising=False)

    with pytest.raises(ProviderUnavailableError, match="MODAL_TOKEN"):
        selection.resolve_provider({"AMOS_SANDBOX_PROVIDER": "modal"})

    # بديل مُسمّى لكن غير مُفعَّل ⇒ لا سقوط، ورسالة تقول ذلك.
    with pytest.raises(ProviderUnavailableError, match="FALLBACK_ENABLED"):
        selection.resolve_provider(
            {
                "AMOS_SANDBOX_PROVIDER": "modal",
                "AMOS_SANDBOX_FALLBACK_PROVIDER": "local",
            }
        )

    # والمحاكاة لا تكون بديلًا بحال، ولو فُعِّل السقوط.
    with pytest.raises(selection.FallbackNotPermittedError):
        selection.read_selection(
            {
                "AMOS_SANDBOX_PROVIDER": "modal",
                "AMOS_SANDBOX_FALLBACK_PROVIDER": "simulation",
                "AMOS_SANDBOX_FALLBACK_ENABLED": "1",
            }
        )


# === 7. سقوط صريح مُعلَن ================================================


def test_explicit_fallback_is_permitted_and_always_declared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """السقوط المسموح يُسجَّل في النتيجة باسم المصدر وسببه — لا يمرّ مجهولًا."""
    monkeypatch.delenv("E2B_API_KEY", raising=False)
    env = {
        "AMOS_SANDBOX_PROVIDER": "e2b",
        "AMOS_SANDBOX_FALLBACK_PROVIDER": "local",
        "AMOS_SANDBOX_FALLBACK_ENABLED": "true",
    }
    resolution = selection.resolve_provider(env)
    assert resolution.provider.name == "local"
    assert resolution.fallback_from == "e2b"
    assert "E2B_API_KEY" in (resolution.fallback_reason or "")

    result = selection.execute_in_sandbox(_spec(), _request("print('ok')"), env=env)
    assert result.provider == "local"
    assert result.fallback_from == "e2b"
    assert result.fallback_reason
    assert result.as_dict()["fallback_from"] == "e2b"


# === 8. ترتيب دورة الحياة ==============================================


def test_lifecycle_order_is_enforced_not_assumed() -> None:
    """لا تنفيذ بمقبض مزوِّد آخر، ولا تنفيذ في صندوق مُنهىً."""
    local = LocalSubprocessProvider()
    other = SimulationProvider()
    handle = local.create_sandbox(_spec())

    # مقبض ليس لهذا المزوِّد.
    with pytest.raises(SandboxNotCreatedError):
        other.execute(handle, _request("print(1)"))

    local.terminate(handle)
    with pytest.raises(SandboxTerminatedError):
        local.execute(handle, _request("print(1)"))
    local.cleanup(handle)


# === 9. المهلة ==========================================================


def test_timeout_is_reported_as_timeout_not_as_success() -> None:
    """المهلة تُعلَن `timed_out` بلا رمز خروج مُخترَع، والنتيجة ليست ناجحة."""
    local = LocalSubprocessProvider()
    handle = local.create_sandbox(_spec(timeout_seconds=1))
    try:
        result = local.execute(handle, _request("import time\ntime.sleep(20)"))
    finally:
        local.cleanup(handle)

    assert result.timed_out is True
    assert result.exit_code is None
    assert result.succeeded is False
    assert "timeout" in (result.error or "")


# === 10. فصل المخرَج ====================================================


def test_stdout_and_stderr_are_separated_not_merged() -> None:
    """المجرىان منفصلان — دمجهما يُخفي الفشل داخل مخرَج ناجح."""
    local = LocalSubprocessProvider()
    handle = local.create_sandbox(_spec())
    try:
        result = local.execute(
            handle,
            _request("import sys\nsys.stdout.write('OUT')\nsys.stderr.write('ERR')"),
        )
    finally:
        local.cleanup(handle)

    assert "OUT" in result.stdout
    assert "ERR" not in result.stdout
    assert "ERR" in result.stderr
    assert "OUT" not in result.stderr


# === 11. رمز الخروج =====================================================


def test_exit_code_is_real_and_never_invented_as_zero() -> None:
    """رمز الخروج غير الصفري يُنقَل كما هو، والمجهول `None` لا صفرًا."""
    local = LocalSubprocessProvider()
    handle = local.create_sandbox(_spec())
    try:
        failing = local.execute(handle, _request("import sys\nsys.exit(7)"))
        passing = local.execute(handle, _request("print('fine')"))
    finally:
        local.cleanup(handle)

    assert failing.exit_code == 7
    assert failing.succeeded is False
    assert passing.exit_code == 0
    assert passing.succeeded is True

    # المزوِّد الذي لا يعطي رمزًا لا يُخترَع له صفر.
    class _Silent:
        pass

    assert ModalProvider._exit_code(_Silent()) is None


# === 12. الإنهاء والتنظيف ===============================================


def test_terminate_and_cleanup_release_resources_and_are_idempotent() -> None:
    """التنظيف يحذف مساحة العمل فعلًا، وتكراره لا يرفع خطأ."""
    local = LocalSubprocessProvider()
    handle = local.create_sandbox(_spec())
    workspace = Path(str(handle.native))
    assert workspace.is_dir()

    local.terminate(handle)
    local.terminate(handle)
    assert handle.terminated is True

    local.cleanup(handle)
    local.cleanup(handle)
    assert workspace.exists() is False
    assert handle.native is None


# === 13. رفض التخويل — fail closed ======================================


def test_authorization_denial_fails_closed_before_any_sandbox_exists() -> None:
    """أداة غير مسموحة للوكيل تُرفَض، ولا يُنشأ صندوق — بأي مزوِّد."""
    from amos_federation.services.tool_registry.authorized_execution import (
        AUTHORIZATION_CHAIN,
        AuthorizationDecision,
        AuthorizationDenied,
        authorize,
        execute_authorized_tool,
    )

    # الترتيب نفسه محروس: الصندوق آخر الحلقات لا أوّلها.
    #
    # R6 أضافت `principal` و`session` إلى مقدّمة السلسلة: قبلها كانت تبدأ
    # من `agent`، أي أن أوّل سؤال كان «أيّ وكيل؟» لا «من يطلب؟».
    # وR6.1 أدخلت `tenant` بعد `agent`: بعد أن يُعرَف الوكيل يُسأل «أفي مستأجري؟»
    # قبل أن يُسأل عن دوره — فحدُّ المستأجر أوسع من حدّ الدور ويُقدَّم عليه.
    assert AUTHORIZATION_CHAIN == (
        "principal",
        "session",
        "agent",
        "tenant",
        "role",
        "capability",
        "permission",
        "tool",
        "sandbox",
    )
    # المبدأ قبل الوكيل، والوكيل قبل الأداة — لا يُعاد الترتيب.
    assert AUTHORIZATION_CHAIN.index("principal") < AUTHORIZATION_CHAIN.index("agent")
    assert AUTHORIZATION_CHAIN.index("permission") < AUTHORIZATION_CHAIN.index("sandbox")
    assert AUTHORIZATION_CHAIN.index("tenant") < AUTHORIZATION_CHAIN.index("role")
    # القرار يبدأ رفضًا لا سماحًا.
    assert AuthorizationDecision().allowed is False

    # وكيل مجهول ⇒ رفض عند أول حلقة.
    with pytest.raises(AuthorizationDenied) as unknown:
        authorize(agent_id="agent-does-not-exist", tool_id="python_execute")
    assert unknown.value.stage == "agent"

    with pytest.raises(AuthorizationDenied):
        authorize(agent_id=None, tool_id="python_execute")

    # وكيل حقيقي بأداة ليست في أدواته ⇒ رفض عند `permission`، ولا صندوق.
    from amos_federation.services.executive_core.agent_identity import register_identity

    identity = register_identity(
        agent_id=f"agent-r5-{uuid4().hex[:10]}",
        name="وكيل اختبار R5",
        role="analyst",
        permissions=["task:execute"],
        allowed_tools=["text_summary"],
    )
    created: list[str] = []

    class _TattleProvider(SimulationProvider):
        def create_sandbox(self, spec: SandboxSpec):  # type: ignore[override]
            created.append(spec.tool_id)
            return super().create_sandbox(spec)

    with pytest.raises(AuthorizationDenied) as denied:
        execute_authorized_tool(
            tool_id="python_execute",
            agent_id=identity.agent_id,
            code="print(1)",
            provider=_TattleProvider(),
        )
    assert denied.value.stage == "permission"
    assert created == [], "أُنشئ صندوق قبل اكتمال التخويل"


# === 14. عزل الأسرار ====================================================


def test_sandbox_never_inherits_host_secrets() -> None:
    """بيئة الصندوق تُبنى من الفراغ: لا DB ولا Supabase ولا تاج ولا مزوِّد."""
    # truth-audit: not-a-secret — قيمٌ مُختَرَعةٌ لاختبارٍ سلبيّ: الغرضُ إثباتُ أن
    # الصندوق لا يُورّث أيًّا منها. لا سرَّ حقيقيًّا هنا.
    hostile = {
        "AMOS_DATABASE_URL": "postgresql://u:p@h/db",
        "DATABASE_URL": "postgresql://u:p@h/db",
        "SUPABASE_SERVICE_ROLE_KEY": "sb-secret",
        "JWT_SECRET": "jwt-secret",
        "KING_LOGIN_SECRET": "crown-secret",
        "GITHUB_TOKEN": "gh-secret",
        "MODAL_TOKEN_SECRET": "modal-secret",
        "E2B_API_KEY": "e2b-secret",
        "CLAUDE_API_KEY": "model-secret",
        "TOOL_PUBLIC_SETTING": "safe-value",
    }
    env, plan = secrets.build_sandbox_env((), source=hostile)
    assert secrets.leaked_secret_names(env) == ()
    assert plan.injected == ()
    for value in hostile.values():
        assert value not in env.values() or value == "safe-value"
    assert "safe-value" not in env.values()

    # قائمة السماح الصريحة وحدها تُمرِّر، والمحجوب يُرفَض ولو سُمّي.
    env, plan = secrets.build_sandbox_env(("TOOL_PUBLIC_SETTING",), source=hostile)
    assert env["TOOL_PUBLIC_SETTING"] == "safe-value"
    assert plan.injected == ("TOOL_PUBLIC_SETTING",)
    with pytest.raises(secrets.SecretBoundaryViolation):
        secrets.build_sandbox_env(("AMOS_DATABASE_URL",), source=hostile)
    with pytest.raises(secrets.SecretBoundaryViolation):
        SandboxSpec(tool_id="t", secret_allowlist=("GITHUB_TOKEN",)) and (
            LocalSubprocessProvider().create_sandbox(
                SandboxSpec(tool_id="t", secret_allowlist=("GITHUB_TOKEN",))
            )
        )

    # وتنفيذ حقيقي لا يرى شيئًا من ذلك.
    os.environ["AMOS_R5_LEAK_PROBE"] = "leak-me"
    try:
        local = LocalSubprocessProvider()
        handle = local.create_sandbox(_spec())
        try:
            result = local.execute(
                handle,
                _request(
                    "import os\n"
                    "print('PROBE=', os.environ.get('AMOS_R5_LEAK_PROBE'))\n"
                    "print('DB=', os.environ.get('AMOS_DATABASE_URL'))\n"
                    "print('PYPATH=', repr(os.environ.get('PYTHONPATH')))"
                ),
            )
        finally:
            local.cleanup(handle)
    finally:
        os.environ.pop("AMOS_R5_LEAK_PROBE", None)

    assert "leak-me" not in result.stdout
    assert "PROBE= None" in result.stdout
    assert "DB= None" in result.stdout
    assert "PYPATH= ''" in result.stdout


# === 15. سياسة الشبكة ===================================================


def test_network_policy_is_explicit_and_denies_by_default() -> None:
    """`DENY` افتراضًا، و`ALLOWLIST` بمضيفين مُسمّين، ولا فرضٌ مزعوم."""
    assert _spec().network_policy == "DENY"

    denied = network.evaluate("DENY", provider="modal", host="example.com")
    assert denied.allowed is False and denied.reason

    empty = network.evaluate("ALLOWLIST", provider="modal", host="example.com")
    assert empty.allowed is False, "ALLOWLIST بلا مضيف يجب أن تُعامَل DENY"

    ok = network.evaluate(
        "ALLOWLIST", provider="modal", host="api.example.com", allowed_hosts=("api.example.com",)
    )
    assert ok.allowed is True
    blocked = network.evaluate(
        "ALLOWLIST", provider="modal", host="evil.example.com", allowed_hosts=("api.example.com",)
    )
    assert blocked.allowed is False

    with pytest.raises(network.NetworkPolicyViolation):
        network.normalize_policy("maybe")

    # لا يُزعم فرضٌ لا يملكه المزوِّد.
    # R6: صار المزوِّد المحلّي يفرض DENY بـnamespace شبكي حين تسمح البيئة.
    # فالقيمة تعتمد على القدرة المقيسة، ولا يُثبَّت أحد الاحتمالين تعسُّفًا.
    local_enforcement = network.enforcement_for("local", "DENY")
    assert local_enforcement in {"DECLARED_ONLY", "NAMESPACE_ENFORCED"}
    if network.isolation_available():
        assert local_enforcement == "NAMESPACE_ENFORCED"
    else:
        assert local_enforcement == "DECLARED_ONLY"
    # ALLOWLIST تبقى مُعلَنة فقط: العزل يقطع الشبكة ولا يُرشِّح مضيفًا.
    assert network.enforcement_for("local", "ALLOWLIST") == "DECLARED_ONLY"
    assert network.enforcement_for("modal") == "PROVIDER_ENFORCED"
    assert network.enforcement_for("e2b") == "PROVIDER_ENFORCED"


# === 16. النَسَب =========================================================


def test_every_result_carries_full_unified_provenance() -> None:
    """كل نتيجة تحمل الحقول الثمانية كاملة عند كل مزوِّد."""
    context = ExecutionContext(
        tool_id="python_execute",
        agent_id="agent-prov",
        task_id="task-prov",
        execution_id="exec-fixed",
        correlation_id="corr-fixed",
    )
    request = ExecutionRequest(code="print('p')", context=context)

    local = LocalSubprocessProvider()
    handle = local.create_sandbox(_spec())
    try:
        result = local.execute(handle, request)
    finally:
        local.cleanup(handle)

    payload = result.as_dict()
    for field in REQUIRED_METADATA_FIELDS:
        assert field in payload, f"حقل نَسَب مفقود: {field}"
        assert payload[field] is not None
    assert payload["execution_id"] == "exec-fixed"
    assert payload["correlation_id"] == "corr-fixed"
    assert payload["task_id"] == "task-prov"
    assert payload["agent_id"] == "agent-prov"
    assert payload["provider"] == "local"

    # ومعرّفات تُولَّد تلقائيًّا إن لم تُمرَّر — لا تنفيذ مجهول النَسَب.
    generated = ExecutionContext(tool_id="python_execute")
    assert generated.execution_id.startswith("exec-")
    assert generated.correlation_id.startswith("corr-")


# === 17. مفردات الصدق ===================================================


def test_fidelity_vocabulary_is_enforced_and_simulation_is_never_a_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """REAL و SIMULATION و UNAVAILABLE — ولا انحدار صامت من الغياب إلى المحاكاة."""
    assert {f.value for f in ExecutionFidelity} == {"REAL", "SIMULATION", "UNAVAILABLE"}
    assert LocalSubprocessProvider().fidelity is ExecutionFidelity.REAL
    assert ModalProvider().fidelity is ExecutionFidelity.REAL
    assert E2BProvider().fidelity is ExecutionFidelity.REAL
    assert SimulationProvider().fidelity is ExecutionFidelity.SIMULATION

    # المحاكاة محظورة في الإنتاج حظرًا غير قابل للتعطيل.
    monkeypatch.setenv("AMOS_ENVIRONMENT", "production")
    monkeypatch.setenv("AMOS_SANDBOX_ALLOW_SIMULATION", "1")
    blocked = SimulationProvider().availability()
    assert blocked.available is False
    assert blocked.fidelity == ExecutionFidelity.UNAVAILABLE.value
    with pytest.raises(ProviderUnavailableError):
        SimulationProvider().create_sandbox(_spec())

    # وفي بيئة الاختبار: متاحة، لكن كل نتيجة تُعلن SIMULATION بسبب مُسمّى.
    monkeypatch.setenv("AMOS_ENVIRONMENT", "test")
    provider = SimulationProvider()
    handle = provider.create_sandbox(_spec())
    try:
        result = provider.execute(handle, _request("print(1)"))
    finally:
        provider.cleanup(handle)
    assert result.execution_fidelity == ExecutionFidelity.SIMULATION.value
    assert result.fidelity_reason

    # ولا مسار سقوط يهبط إلى المحاكاة.
    assert "simulation" in selection.NON_FALLBACK_PROVIDERS


# === 18. انتشار الفشل ===================================================


def test_provider_failure_propagates_and_is_never_masked_as_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """فشل المزوِّد يُنقَل بسببه: لا exit_code صفر ولا SIMULATION تُغطّيه."""
    monkeypatch.setenv("MODAL_TOKEN_ID", "id-placeholder")
    monkeypatch.setenv("MODAL_TOKEN_SECRET", "secret-placeholder")

    class _ExplodingSandbox(_FakeModalSandbox):
        def exec(self, *argv: str, env: dict[str, str], timeout: int) -> Any:
            raise RuntimeError("modal upstream 503")

    fake = _FakeModalSDK()
    fake.sandbox = _ExplodingSandbox()
    provider = ModalProvider()
    monkeypatch.setattr(provider, "_load_sdk", lambda: fake)

    handle = provider.create_sandbox(_spec())
    try:
        result = provider.execute(handle, _request("print(1)"))
    finally:
        provider.cleanup(handle)

    assert result.succeeded is False
    assert result.exit_code is None
    assert "modal upstream 503" in (result.error or "")
    assert result.execution_fidelity != ExecutionFidelity.SIMULATION.value

    # وحتى إعلان صدق غير REAL بلا سبب يُرفَض في بناء النتيجة نفسه.
    local = LocalSubprocessProvider()
    local_handle = local.create_sandbox(_spec())
    try:
        with pytest.raises(ValueError, match="سبب"):
            local.result(
                local_handle,
                _request("print(1)"),
                stdout="",
                stderr="",
                exit_code=0,
                fidelity=ExecutionFidelity.SIMULATION,
            )
    finally:
        local.cleanup(local_handle)


# === 19. الحرس الساكن ===================================================


def test_static_guards_forbid_provider_leakage_and_runtime_coupling() -> None:
    """حرس ساكن ضدّ الانحدار المعماري — يفحص المصدر لا النوايا."""
    modal_adapter = _SERVICES_ROOT / "tool_registry/providers/modal_provider.py"
    e2b_adapter = _SERVICES_ROOT / "tool_registry/providers/e2b_provider.py"

    modules = {
        path: _strip_comments_and_strings(path.read_text(encoding="utf-8"))
        for path in _SERVICES_ROOT.rglob("*.py")
    }

    # 1 و2. لا استيراد Modal أو E2B خارج مُهيّئه.
    modal_pattern = re.compile(r"^\s*(?:import\s+modal|from\s+modal[\s.]+)", re.M)
    e2b_pattern = re.compile(r"^\s*(?:import\s+e2b|from\s+e2b[\w.]*\s+)", re.M)
    for path, source in modules.items():
        if modal_pattern.search(source):
            assert path == modal_adapter, f"استيراد modal خارج مُهيّئه: {path}"
        if e2b_pattern.search(source):
            assert path == e2b_adapter, f"استيراد e2b خارج مُهيّئه: {path}"

    # 3. بيئة تشغيل الوكلاء لا تُنشئ صندوق مزوِّد ولا تستورد طبقة المزوِّدات.
    for path, source in modules.items():
        if "agent_runtime/" not in path.as_posix():
            continue
        assert "providers" not in source, f"{path} يلمس طبقة المزوِّدات"
        assert "create_sandbox" not in source, f"{path} يُنشئ صندوق مزوِّد"

    # 4. لا صندوق قبل التخويل: مسار التخويل يُنشئ الصندوق بعد `authorize` فقط.
    auth_source = (_SERVICES_ROOT / "tool_registry/authorized_execution.py").read_text(
        encoding="utf-8"
    )
    stripped_auth = _strip_comments_and_strings(auth_source)
    assert stripped_auth.index("authorize(") < stripped_auth.index("execute_in_sandbox")
    # ودالّة الفحص نفسها لا تُنشئ صندوقًا بحال.
    authorize_body = stripped_auth[
        stripped_auth.index("def authorize(") : stripped_auth.index("def _enforce_governance(")
    ]
    assert "create_sandbox" not in authorize_body
    assert "execute_in_sandbox" not in authorize_body

    # 5. لا تسريب أسرار: بيئة الصندوق لا تُبنى من `os.environ` مباشرةً.
    for name in ("local_provider.py", "modal_provider.py", "e2b_provider.py"):
        source = modules[_SERVICES_ROOT / f"tool_registry/providers/{name}"]
        assert "build_sandbox_env" in source, f"{name} لا يمرّ بحدّ الأسرار"
        assert "dict(os.environ)" not in source
        assert "os.environ.copy()" not in source
        assert "env=os.environ" not in source

    # 6. لا سقوط غير مُعلَن: كل مسار سقوط يمرّ بـ`fallback_from`.
    selection_source = modules[_SERVICES_ROOT / "tool_registry/providers/selection.py"]
    assert "fallback_from" in selection_source
    assert "fallback_enabled" in selection_source

    # 7. لا تجاوز لسجلّ الأدوات: التخويل يقرأ `TOOL_CATALOG` نفسه.
    assert "TOOL_CATALOG" in stripped_auth
