"""الهدف: لا صندوق رملي قبل التخويل — سلسلة كاملة أو فشل مُغلَق.

النطاق: services/tool_registry
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17

السلسلة المحفوظة، بهذا الترتيب لا بغيره:

    Agent → Role → Capability → Permission → Tool → Sandbox

قبل هذه الوحدة كان `execute_tool_with_governance` يفحص الـkill switch ومحرِّك
السياسة ثم **يُنشئ الصندوق فورًا**، بلا أن يعرف من هو الوكيل ولا ما أدواته
المسموحة: كان يكفي أن يسمح الدور بالأداة. فوكيل لا يملك الأداة في
`allowed_tools` كان ينفّذها إن كان دوره يسمح بها عمومًا.

الترتيب المُنفَّذ هنا في `authorize()`، ولا يُنشأ صندوق إلا بعد اكتماله:

1. **Agent** — هوية كانونية موجودة في `agents`. المجهول يُرفَض.
2. **Role** — الدور من الهوية نفسها لا من مُعطى الطلب. دورٌ يأتي من العميل
   يعني تصعيد صلاحية بسطر واحد.
3. **Capability** — حالة دورة الحياة تسمح بالتنفيذ (`employable`). وكيل مُقاعَد
   أو معزول أو موقوف لا ينفّذ ولو كان دوره كافيًا.
4. **Permission** — الأداة في `allowed_tools` للهوية، أو `*` صراحةً.
5. **Tool** — الأداة مسجَّلة في سجلّ الأدوات. لا تنفيذ لأداة غير معرَّفة.
6. **Sandbox** — الآن فقط: `create_sandbox`.

و**FAIL CLOSED** في كل نقطة: الرفض هو الافتراضي، والخطأ أثناء الفحص رفضٌ لا
سماح. `AuthorizationDecision.allowed` تبدأ `False` ولا تصير `True` إلا بعد
اجتياز الحلقات كلها.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from amos_federation.common.principal import (
    DEFAULT_TENANT,
    AuthorizationContext,
    policy_role,
    tenant_matches,
)
from amos_federation.services.tool_registry.providers.contract import (
    ExecutionContext,
    ExecutionRequest,
    ExecutionResult,
    SandboxSpec,
)

_logger = logging.getLogger(__name__)

#: أسماء حلقات السلسلة بترتيبها — تُفحَص في الاختبارات ضدّ إعادة الترتيب.
AUTHORIZATION_CHAIN: tuple[str, ...] = (
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

#: الحلقات التي أضافتها R6 إلى مقدّمة السلسلة — قبلها كانت تبدأ من `agent`.
R6_CHAIN_PREFIX: tuple[str, ...] = ("principal", "session")

#: صلاحية شاملة معروفة في بيانات الهوية.
WILDCARD_PERMISSION = "*"


class AuthorizationDenied(PermissionError):  # noqa: N818 — رفض تخويل، لا عطل
    """التخويل رُفِض — ولا يُنشأ صندوق. تحمل الحلقة التي سقطت وسببها."""

    def __init__(self, stage: str, reason: str, detail: dict[str, Any] | None = None) -> None:
        super().__init__(f"{stage}: {reason}")
        self.stage = stage
        self.reason = reason
        self.detail = detail or {}


@dataclass
class AuthorizationDecision:
    """قرار التخويل — يبدأ رفضًا ولا يُقلَب إلا باكتمال السلسلة."""

    allowed: bool = False
    agent_id: str | None = None
    role: str | None = None
    actor_role: str | None = None
    principal_id: str | None = None
    session_id: str | None = None
    principal_verification: str = "UNVERIFIED"
    principal_kind: str | None = None
    #: مستأجر المُخوِّل ومستأجر المورد — يُقرأ القرار بعدهما لا يُخمَّن.
    tenant_id: str | None = None
    resource_tenant_id: str | None = None
    correlation_id: str | None = None
    tool_id: str | None = None
    lifecycle_state: str | None = None
    stages_passed: tuple[str, ...] = ()
    denied_at: str | None = None
    reason: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "agent_id": self.agent_id,
            "role": self.role,
            "actor_role": self.actor_role,
            "principal_id": self.principal_id,
            "session_id": self.session_id,
            "principal_verification": self.principal_verification,
            "principal_kind": self.principal_kind,
            "tenant_id": self.tenant_id,
            "resource_tenant_id": self.resource_tenant_id,
            "correlation_id": self.correlation_id,
            "tool_id": self.tool_id,
            "lifecycle_state": self.lifecycle_state,
            "stages_passed": list(self.stages_passed),
            "denied_at": self.denied_at,
            "reason": self.reason,
            "detail": self.detail,
        }


def _known_tools() -> tuple[str, ...]:
    """أدوات سجلّ الأدوات — من السجلّ نفسه لا من قائمة موازية.

    فشل قراءة السجلّ يُعامَل قائمةً فارغة، أي رفضًا لكل أداة (fail closed)، لا
    سماحًا عامًّا.
    """
    try:
        from amos_federation.services.tool_registry.catalog import TOOL_CATALOG

        return tuple(TOOL_CATALOG)
    except Exception as exc:  # noqa: BLE001 — تعذُّر القراءة = رفض لا سماح
        _logger.warning("تعذّرت قراءةُ سجلّ الأدوات — الرفضُ لكلّ أداة. %s", exc)
        return ()


def _is_production_env() -> bool:
    """بيئة إنتاجية؟ — يُقرأ عند كل نداء، فتغيُّر البيئة يُلتقَط."""
    import os

    from amos_federation.common.config import PRODUCTION_ENVIRONMENTS

    return os.environ.get("AMOS_ENVIRONMENT", "development").strip().lower() in (
        PRODUCTION_ENVIRONMENTS
    )


def authorize(
    *,
    agent_id: str | None,
    tool_id: str,
    system_state: str | None = None,
    principal: AuthorizationContext | None = None,
) -> AuthorizationDecision:
    """اجتَز سلسلة التخويل كاملة أو ارفع `AuthorizationDenied`.

    لا يُنشأ صندوق في هذه الدالّة بحال — هي فحص محض، وهذا ما يجعل «لا صندوق قبل
    التخويل» قابلًا للحراسة ساكنًا.

    **ولا معامل مستأجر أيضًا بعد R6.1.** كان فيها `tenant_id` يُمرّره المُستدعي
    ويُستعمل في قراءة الهوية — وهو حقل من المُستدعي يدخل قرار تخويل، أي نفس عيب
    `actor_role` في صورة أخفّ. فحُذِف: مستأجر المُخوِّل من `principal` وحده، ومستأجر
    المورد من الهوية الكانونية المُخزَّنة.

    **لا معامل دور في هذه الدالّة، ولا معامل صلاحيات.** هذا مقصود ومحروس ساكنًا:
    قبل R6 كان `actor_role="admin"` كافيًا ليصير المُستدعي مديرًا. الآن الدور
    الفعّال يُشتقّ من `principal` وحده، و`AuthorizationContext` لا تُبنى إلا من
    جلسة مُخزَّنة أو رمز موقَّع أو نداء داخلي مُسمّى — أو من `unverified_context`
    التي تُعلِن عدم التحقّق وتُرفَض في الإنتاج.

    Args:
        principal: سياق التخويل. غيابه يعني مبدأً مجهولًا: يُبنى سياق
            `UNVERIFIED` صريح، ويُرفَض في بيئة إنتاجية. أما إن كان موثوقًا فدوره
            هو ما يراه kill switch ومحرِّك السياسة في حلقة `tool`.

            وهو **لا يوسِّع** منح الهوية بحال: حلقات `agent` و`capability`
            و`permission` تُفحَص على هوية الوكيل الكانونية قبله، فالمحصّلة تقاطع
            لا اتحاد. ودورٌ `king` لا يمنح أداةً ليست في `allowed_tools`.
    """
    from amos_federation.common.principal import unverified_context

    decision = AuthorizationDecision(tool_id=tool_id, agent_id=agent_id)
    passed: list[str] = []

    # 0. Principal — قبل كل شيء: من يطلب؟ والمجهول يُعلَن مجهولًا لا مديرًا.
    context = principal or unverified_context("لا سياق تخويل في الطلب")
    decision.principal_id = context.principal_id
    decision.session_id = context.session_id
    decision.principal_verification = context.verification.value
    decision.principal_kind = context.principal_kind.value
    decision.tenant_id = context.tenant_id or DEFAULT_TENANT
    decision.correlation_id = context.correlation_id
    # الانتهاء يُرفَض في **كل** بيئة لا في الإنتاج وحده: تسامُح التطوير مُبرَّرٌ
    # لمُستدعٍ لم يُهاجَر بعد، ولا مُبرَّر له في جلسة كانت صحيحة ثم ماتت — تلك
    # ليست حالة توافُق بل بيان مدّة يُتجاهَل. R6.1.
    if context.is_expired:
        raise _deny(
            decision,
            "principal",
            f"جلسة السياق '{context.session_id}' منتهية — لا تخويل على جلسة ميّتة",
        )
    if not context.is_trusted and _is_production_env():
        raise _deny(
            decision,
            "principal",
            f"مبدأ غير مُتحقَّق منه في بيئة إنتاجية: {context.reason}",
        )
    passed.append("principal")

    # 0أ. Session — تُعَدّ مُجتازة حين يكون المبدأ مربوطًا بجلسة مُسمّاة. وغيابها
    # لا يُدَّعى اجتيازًا: مبدأ بلا جلسة يمرّ بلا هذه الحلقة، ويظهر ذلك في
    # `stages_passed` فيُقرأ ولا يُخمَّن.
    if context.session_id:
        passed.append("session")

    # 1. Agent — هوية كانونية موجودة.
    if not agent_id:
        raise _deny(decision, "agent", "لا معرّف وكيل في الطلب")
    try:
        from amos_federation.services.executive_core.agent_identity import get_identity

        # القراءة بالمعرّف وحده (وهو مفتاح أولي فريد)، والمستأجر يُفحَص بعدها
        # صراحةً. ولو رُشّحت القراءة بمستأجر السياق لصار عبور الحدود يُردّ بـ«لا
        # هوية للوكيل» — وهذا رفضٌ بسبب كاذب، يُخفي أن الواقع عزل مستأجر.
        identity = get_identity(agent_id)
    except Exception as exc:  # noqa: BLE001 — تعذُّر القراءة = رفض
        raise _deny(decision, "agent", f"تعذّر قراءة الهوية الكانونية: {exc}") from exc
    if identity is None:
        raise _deny(decision, "agent", f"لا هوية كانونية للوكيل '{agent_id}'")
    passed.append("agent")

    # 3. Tenant — عزل المستأجر قبل أي فحص صلاحية، وفي حلقة مُسمّاة لا مدموجة في
    # حلقة الوكيل — أُفرِدت في R6.1 ليُقرأ سبب الرفض على وجهه لا مخلوطًا بـ«لا
    # هوية للوكيل».
    #
    # مستأجر غير مُسمّى في السياق لا يعني «كل المستأجرين». وسياق مستأجر «أ» لا
    # يُخوَّل على وكيل مستأجر «ب» ولو كان دوره king.
    #
    # والسياق غير الموثوق لا تُحسَب له هذه الحلقة مُجتازة: من لم تثبت هويته لا
    # مستأجر له يُقارن، والإنتاج رفضه في الحلقة 0 أصلًا. وغيابها من `stages_passed`
    # يُقرأ في النتيجة، فلا يُدّعى عزلٌ لم يُفحَص.
    decision.resource_tenant_id = identity.tenant_id or DEFAULT_TENANT
    if context.is_trusted:
        if not tenant_matches(context, identity.tenant_id):
            raise _deny(
                decision,
                "tenant",
                f"عزل المستأجر: سياق '{context.tenant_id or DEFAULT_TENANT}' "
                f"لا يملك وكيل '{identity.tenant_id or DEFAULT_TENANT}'",
            )
        passed.append("tenant")

    # 2. Role — من الهوية للوكيل، ومن المبدأ المُتحقَّق منه للسياسة.
    role = identity.role
    if not role:
        raise _deny(decision, "role", "الهوية الكانونية بلا دور")
    decision.role = role
    # الدور الفعّال: من المبدأ إن ثبتت هويته، وإلّا فدور الهوية. ولا يُقرأ من
    # جسم الطلب في أي فرع من هذين.
    decision.actor_role = context.role if (context.is_trusted and context.role) else role
    passed.append("role")

    # 3. Capability — حالة دورة الحياة تسمح بالتنفيذ.
    decision.lifecycle_state = identity.lifecycle_state
    if not identity.employable:
        raise _deny(
            decision,
            "capability",
            f"حالة دورة الحياة '{identity.lifecycle_state}' لا تسمح بالتنفيذ",
        )
    passed.append("capability")

    # 4. Permission — الأداة في أدوات الهوية المسموحة.
    allowed_tools = tuple(identity.allowed_tools)
    permissions = tuple(identity.permissions)
    wildcard = WILDCARD_PERMISSION in allowed_tools or WILDCARD_PERMISSION in permissions
    if not wildcard and tool_id not in allowed_tools:
        raise _deny(
            decision,
            "permission",
            f"الأداة '{tool_id}' ليست في أدوات الوكيل المسموحة",
            {"allowed_tools": list(allowed_tools)},
        )
    passed.append("permission")

    # 5. Tool — الأداة مسجَّلة، ومحرِّك السياسة والـkill switch يسمحان بها.
    known = _known_tools()
    if tool_id not in known:
        raise _deny(
            decision,
            "tool",
            f"الأداة '{tool_id}' غير مسجَّلة في سجلّ الأدوات",
            {"registered_tools": list(known)},
        )
    _enforce_governance(
        decision,
        tool_id=tool_id,
        role=decision.actor_role or role,
        system_state=system_state,
        trusted=context.is_trusted,
    )
    passed.append("tool")

    decision.stages_passed = tuple(passed)
    decision.allowed = True
    return decision


def _enforce_governance(
    decision: AuthorizationDecision,
    *,
    tool_id: str,
    role: str,
    system_state: str | None,
    trusted: bool = False,
) -> None:
    """kill switch ثم محرِّك السياسة — داخل حلقة Tool لا قبل السلسلة.

    Args:
        trusted: هل ثبتت هوية المبدأ؟ الترجمة إلى مفردة محرِّك السياسة تُطبَّق
            **على الموثوق وحده**. وإلّا لصار ادّعاء `role="king"` مترجَمًا إلى
            `admin` فمُصرَّحًا له — أي ثغرة ترفيع صلاحية تفتحها الترجمة نفسها.
            فالدور المُدّعى يمرّ حرفيًّا كما كان قبل R6، ومحرِّك السياسة يرفضه
            لأنه ليس `admin` حرفيًّا.
    """
    from amos_federation.services.governance.canary import (
        enforce_kill_switch,
        get_system_status,
    )
    from amos_federation.services.governance.policy_engine import get_policy_engine

    # الدور الحقيقي يُحفظ في القرار؛ ومحرِّك السياسة يرى مفردته هو.
    evaluated_role = policy_role(role) if trusted else role
    enforce_kill_switch(tool_id, evaluated_role)

    state = system_state or get_system_status()["level"]
    verdict = get_policy_engine().evaluate_tool_access(tool_id, evaluated_role, state)
    if not verdict.get("allowed"):
        raise _deny(
            decision,
            "tool",
            "محرِّك السياسة رفض الأداة لهذا الدور",
            {
                "denied_by": verdict.get("denied_by"),
                "system_state": state,
                "evaluated_role": evaluated_role,
            },
        )


def _deny(
    decision: AuthorizationDecision,
    stage: str,
    reason: str,
    detail: dict[str, Any] | None = None,
) -> AuthorizationDenied:
    decision.allowed = False
    decision.denied_at = stage
    decision.reason = reason
    decision.detail = detail or {}
    return AuthorizationDenied(stage, reason, decision.as_dict())


def execute_authorized_tool(
    *,
    tool_id: str,
    agent_id: str | None,
    code: str = "",
    command: tuple[str, ...] = (),
    task_id: str | None = None,
    correlation_id: str | None = None,
    spec: SandboxSpec | None = None,
    provider: Any = None,
    principal: AuthorizationContext | None = None,
) -> ExecutionResult:
    """المسار الوحيد لتنفيذ أداة في صندوق مزوِّد: تخويل ثم صندوق.

    `authorize()` تُستدعى قبل أي `create_sandbox`؛ ورفضها يرفع
    `AuthorizationDenied` فلا يُنشأ صندوق ولا تُستهلَك موارد مزوِّد.
    """
    # لا معامل مستأجر يُمرَّر: مستأجر المُخوِّل من `principal`، ومستأجر المورد من
    # الهوية المُخزَّنة. حُذِف في R6.1 لأنه كان حقلًا من المُستدعي يدخل قرار تخويل.
    decision = authorize(
        agent_id=agent_id,
        tool_id=tool_id,
        principal=principal,
    )

    from amos_federation.services.tool_registry.providers.selection import execute_in_sandbox

    sandbox_spec = spec or SandboxSpec(tool_id=tool_id)
    context = ExecutionContext(
        tool_id=tool_id,
        agent_id=decision.agent_id,
        task_id=task_id,
        **({"correlation_id": correlation_id} if correlation_id else {}),
    )
    request = ExecutionRequest(code=code, command=command, context=context)
    result = execute_in_sandbox(sandbox_spec, request, provider=provider)
    _publish_execution(result, decision)
    return result


def _publish_execution(result: ExecutionResult, decision: AuthorizationDecision) -> None:
    """أعلِن التنفيذ بنَسَبه وصدقه — فشل الناقل لا يُبطل النتيجة."""
    try:
        from amos_federation.common.event_bus import get_event_bus

        payload = result.as_dict()
        payload["authorization_stages"] = list(decision.stages_passed)
        payload["principal_id"] = decision.principal_id
        payload["principal_verification"] = decision.principal_verification
        get_event_bus().publish("amos_federation.tool.executed", payload)
    except Exception as exc:  # noqa: BLE001 — الناقل قد يكون غير مُهيّأ
        _logger.warning("تعذّر نشرُ حدث tool.executed — %s", exc)
