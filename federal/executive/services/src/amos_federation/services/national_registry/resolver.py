"""
AMOS-Federation National Registry — Authority Resolver
الهدف: سلسلةٌ مقروءة من القاعدة: مبدأ ← هوية ← مسؤول ← منصب ← مؤسسة ← نطاق ← عملية
النطاق: services/national_registry
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17 (R7-C6 · R7-C7)

## المُنادي لا يقرّر سلطته

الدوالّ هنا **لا تقبل** `identity_id` ولا `position_id` ولا نطاقًا من المُستدعي.
مدخلها: سياق تخويل مُتحقَّق منه (`AuthorizationContext`) + العملية المطلوبة +
أهدافها الفعلية (مؤسسة · إدارة · موازنة · حساب). وكل حلقة تُقرأ صفًّا:

    context.principal_id
      → state_identity_principals   (مبدأ ← هوية)      R7-C3
      → state_identities            (نشِطة؟)            R7-C2
      → state_identity_agents       (هوية ← وكيل)       R7-C5
      → state_officials             (وكيل ← تقليد قائم)  R7-A
      → state_official_positions    (تقليد ← منصب)      R7-C4
      → state_positions             (منصب ← مؤسسة)      R7-C4
      → state_authority_grants      (منصب ← عملية+هدف)   R7-C7/C8

و`official_id` إن أُعطي فليس مصدر سلطة بل **ادّعاءٌ يُتحقَّق منه**: إن لم يكن من
مناصب هوية المُنادي رُفض بـ`ForgedAuthorityError`. هذا هو الفرق العملي بين R7-B
وR7-C: كان المُنادي يُمرّر `official_id` أيّ مسؤول قائم فيُقبل.

## النطاقات ليست سلّمًا (R7-C7)

لا ترقية ضمنية بين النطاقات، والقواعد مفروضة في `_grant_covers`:

| المِنحة | تُغطّي | لا تُغطّي |
| --- | --- | --- |
| `DEPARTMENT` | موارد الإدارة المُسمّاة فقط | موارد المؤسسة التي لا إدارة لها |
| `INSTITUTION` | موارد المؤسسة وكل إداراتها | مؤسسة أخرى ولو كانت ابنتها |
| `STATE` | مؤسسات الولاية غير الخزانية | مؤسسة فرعها `treasury` |
| `FEDERAL` | المؤسسة المُسمّاة في المِنحة | ما لم تُسمَّ مؤسستُه |

- **سلطة فدرالية ليست سلطة ولاية تلقائيًّا**: مِنحة `FEDERAL` تُسمّي مؤسستها
  كسائر المِنَح (قيد `ck_state_authority_grants_target`)، فلا تفتح مؤسسةً أخرى.
- **سلطة ولاية ليست سلطة خزانة فدرالية تلقائيًّا**: مِنحة `STATE` على مؤسسة
  فرعها `treasury` تُرفض بنصٍّ صريح ولو كانت المؤسسة هي المُسمّاة.
- **سلطة إدارة ليست سلطة المؤسسة كلها**: مِنحة `DEPARTMENT` تُرفض على موردٍ
  `department_id IS NULL` (مورد على مستوى المؤسسة) لا تُعتبر «أعمّ فتُقبل».
- **الدور وحده لا يحدّد نطاقًا**: لا سطر هنا يقرأ `context.role` لاستنتاج نطاق.

## fail closed

كل مسار لم يجد صفًّا يُرجع `allowed=False` وسببًا بالعربية. ولا فرعٌ واحد يُرجع
`True` عند نقص بيانات. والتصنيف يُشتَق من الأدلة المقروءة فقط:

- `PROVEN` — هوية + تقليد قائم + منصب + مِنحة مطابقة، كلها صفوف.
- `PARTIAL` — الهوية معروفة، وأُجيزت العملية بصلاحية دور سيادية بلا مِنحة مطابقة.
- `UNRESOLVED` — لا هوية كانونية للمبدأ. يُقال ولا يُختلق.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from amos_federation.common.database import AgentModel
from amos_federation.common.principal import DEFAULT_TENANT, assert_tenant
from amos_federation.services.national_registry.models import (
    GRANTABLE_OPERATIONS,
    AuthorityGrantModel,
    IdentityAgentModel,
    IdentityModel,
    IdentityPrincipalModel,
    OfficialPositionModel,
    PositionModel,
)
from amos_federation.services.state_registry.models import (
    InstitutionModel,
    OfficialModel,
)

_logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from amos_federation.common.principal import AuthorizationContext


def _tenant_of(context: AuthorizationContext) -> str:
    """مستأجر السياق مُطبَّعًا — غياب المستأجر يعني `default` لا `NULL`.

    الصفوف تُكتب دائمًا بمستأجرٍ صريح (`_tenant_of` في الخدمات)، فلو قارنّا
    عمودًا مكتوبًا بـ`'default'` بسياقٍ حقله `None` لَما طابق شيءٌ شيئًا، ولَبدا
    كأن لا هوية لأحد — رفضٌ صامتٌ لسببٍ خطأ. التطبيع هنا في مكانٍ واحد.
    """
    return context.tenant_id or DEFAULT_TENANT


class IdentityResolutionError(PermissionError):  # noqa: N818 — رفض سلطة، لا عطل
    """لا هوية كانونية للمبدأ — والعملية تلزمها هوية مُثبتة."""

    def __init__(self, principal_id: str, reason: str) -> None:
        self.principal_id = principal_id
        super().__init__(f"لا هوية كانونية للمبدأ '{principal_id}': {reason}")


class ForgedAuthorityError(PermissionError):  # noqa: N818 — رفض سلطة، لا عطل
    """ادّعى المُنادي منصبًا لا يشغله — أو سلطةً لا مِنحة لها."""

    def __init__(self, reason: str, *, principal_id: str, claimed: str | None = None) -> None:
        self.principal_id = principal_id
        self.claimed = claimed
        super().__init__(
            f"سلطة غير مُثبتة للمبدأ '{principal_id}': {reason}"
            f" (المُدَّعى: {claimed or 'غير مُعطى'})"
        )



def has_sovereign_authority(context: Any) -> bool:
    """يفحص السيادة بتحميلٍ متأخّر لكسر حلقة استيرادٍ حقيقية.

    الحلقة كانت: `national_registry.resolver` → `government_services` (حزمةً،
    فيُنفَّذ `__init__` فيها) → `government_services.service` →
    `national_registry.authorization` → `national_registry.resolver` وهي بعدُ
    نصفَ مُهيّأة، فيرتفع `ImportError: cannot import name 'AuthorityDecision'`.

    ولم تكن الحلقةُ ظاهرةً لأنّ أحدًا لم يستورد `national_registry` **أولًا**:
    كلُّ مسارٍ قائمٍ يمرّ بـ`government_services` أو `state_registry` قبله فيكتمل
    التحميلُ ثمّ لا تُغلق الحلقة. وأوّلُ مستهلكٍ يبدأ من هذه الحزمة يكسر.

    والتأخيرُ هنا لا يغيّر سلوكًا: نفسُ الدالّة، ونفسُ النتيجة، وبعد أوّل نداءٍ
    تكون الوحدةُ في `sys.modules` فلا كلفةَ تحميلٍ متكرّرة.
    """
    from amos_federation.services.government_services.authorization import (
        has_sovereign_authority as _has_sovereign_authority,
    )

    return _has_sovereign_authority(context)


@dataclass(frozen=True, slots=True)
class IdentityResolution:
    """نتيجة ربط مبدأ بهويته الكانونية — بلا اختلاق عند الغياب."""

    principal_id: str
    identity_id: str | None
    identity_type: str | None
    identity_status: str | None
    agent_id: str | None
    resolved: bool
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "principal_id": self.principal_id,
            "identity_id": self.identity_id,
            "identity_type": self.identity_type,
            "identity_status": self.identity_status,
            "agent_id": self.agent_id,
            "resolved": self.resolved,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class AuthorityDecision:
    """قرار سلطة كامل الأثر — يُخزَّن كما هو في جدول الإسناد."""

    allowed: bool
    classification: str
    operation: str
    principal_id: str
    identity_id: str | None = None
    official_id: str | None = None
    position_id: str | None = None
    grant_id: str | None = None
    scope: str | None = None
    institution_id: str | None = None
    reason: str = ""
    targets: dict[str, Any] = field(default_factory=dict)
    #: كل ما فُحص من مِنَح ولم يُطابق، وسببُ عدم المطابقة — للتشخيص لا للتخويل.
    rejected_grants: tuple[tuple[str, str], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "classification": self.classification,
            "operation": self.operation,
            "principal_id": self.principal_id,
            "identity_id": self.identity_id,
            "official_id": self.official_id,
            "position_id": self.position_id,
            "grant_id": self.grant_id,
            "scope": self.scope,
            "institution_id": self.institution_id,
            "reason": self.reason,
            "targets": dict(self.targets),
        }


@dataclass(frozen=True, slots=True)
class PositionHolding:
    """منصبٌ يشغله المبدأ فعلًا — تقليدٌ نشط + منصبٌ نشط + مؤسسته."""

    assignment_id: str
    official_id: str
    position_id: str
    position_code: str
    institution_id: str
    institution_branch: str
    department_id: str | None
    authority_scope: str


def resolve_identity(
    session: Session,
    context: AuthorizationContext,
    *,
    required: bool = False,
) -> IdentityResolution:
    """اقرأ هوية المبدأ الكانونية من القاعدة — R7-C3.

    لا تقرأ اسم عرض ولا دورًا: المدخل `context.principal_id` وحده، وهو من الجلسة
    المُتحقَّق منها لا من جسم الطلب. والهوية المُعلَّقة أو المتقاعدة أو
    `unresolved` **لا تُعَدّ محلولة**، وتُذكَر حالتها في السبب.

    Args:
        required: إن كان `True` فالغياب استثناءٌ لا نتيجةٌ سالبة.

    Raises:
        IdentityResolutionError: `required=True` ولا هوية نشطة.
        TenantIsolationError: صفُّ الربط في مستأجر آخر.
    """
    principal_id = context.principal_id
    link = session.execute(
        select(IdentityPrincipalModel).where(
            IdentityPrincipalModel.principal_id == principal_id,
            IdentityPrincipalModel.tenant_id == _tenant_of(context),
        )
    ).scalar_one_or_none()

    if link is None:
        resolution = IdentityResolution(
            principal_id=principal_id,
            identity_id=None,
            identity_type=None,
            identity_status=None,
            agent_id=None,
            resolved=False,
            reason="لا صفَّ ربطٍ بين هذا المبدأ وأيّ هوية كانونية",
        )
        if required:
            raise IdentityResolutionError(principal_id, resolution.reason)
        return resolution

    assert_tenant(context, link.tenant_id)

    identity = session.get(IdentityModel, link.identity_id)
    if identity is None:  # pragma: no cover — يمنعه مفتاحٌ أجنبي RESTRICT
        reason = "صفُّ الربط يشير إلى هوية غير موجودة"
        if required:
            raise IdentityResolutionError(principal_id, reason)
        return IdentityResolution(principal_id, None, None, None, None, False, reason)

    agent_link = session.execute(
        select(IdentityAgentModel).where(IdentityAgentModel.identity_id == identity.id)
    ).scalar_one_or_none()

    if identity.status != "active":
        reason = f"الهوية موجودة وحالتها '{identity.status}' — لا تُعَدّ محلولة"
        resolution = IdentityResolution(
            principal_id=principal_id,
            identity_id=identity.id,
            identity_type=identity.identity_type,
            identity_status=identity.status,
            agent_id=agent_link.agent_id if agent_link else None,
            resolved=False,
            reason=reason,
        )
        if required:
            raise IdentityResolutionError(principal_id, reason)
        return resolution

    return IdentityResolution(
        principal_id=principal_id,
        identity_id=identity.id,
        identity_type=identity.identity_type,
        identity_status=identity.status,
        agent_id=agent_link.agent_id if agent_link else None,
        resolved=True,
        reason="هويةٌ نشطة مربوطةٌ بصفٍّ في `state_identity_principals`",
    )


def resolve_agent_identity(session: Session, agent_id: str) -> IdentityModel | None:
    """اقرأ هوية وكيلٍ تشغيليّ — R7-C5، بلا دمج الجدولين."""
    link = session.execute(
        select(IdentityAgentModel).where(IdentityAgentModel.agent_id == agent_id)
    ).scalar_one_or_none()
    if link is None:
        return None
    return session.get(IdentityModel, link.identity_id)


def resolve_positions(
    session: Session,
    identity_id: str,
    *,
    tenant_id: str,
) -> tuple[PositionHolding, ...]:
    """اقرأ كل منصبٍ يشغله صاحب هذه الهوية فعلًا — R7-C4.

    ثلاثة شروط مجتمعة: التقليد `active`، وسجلّ المسؤول `appointed`، والمنصب
    `active`. فسقوط أيٍّ منها يُخرج المنصب من القائمة — وهو ما يجعل «عزل المنصب
    ⇒ منع» أثرًا آليًّا لا فحصًا إضافيًّا.
    """
    rows = session.execute(
        select(OfficialPositionModel, OfficialModel, PositionModel, InstitutionModel)
        .join(OfficialModel, OfficialModel.id == OfficialPositionModel.official_id)
        .join(PositionModel, PositionModel.id == OfficialPositionModel.position_id)
        .join(InstitutionModel, InstitutionModel.id == PositionModel.institution_id)
        .where(
            OfficialPositionModel.identity_id == identity_id,
            OfficialPositionModel.status == "active",
            OfficialPositionModel.tenant_id == tenant_id,
            OfficialModel.status == "appointed",
            PositionModel.status == "active",
        )
    ).all()

    return tuple(
        PositionHolding(
            assignment_id=assignment.id,
            official_id=official.id,
            position_id=position.id,
            position_code=position.code,
            institution_id=institution.id,
            institution_branch=institution.branch,
            department_id=position.department_id,
            authority_scope=position.authority_scope,
        )
        for assignment, official, position, institution in rows
    )


def _amount_within(grant_max: str | None, amount: str | int | None) -> tuple[bool, str]:
    """أيدخل المبلغ في حدّ المِنحة؟ مقارنةٌ عشرية لا عائمة."""
    if grant_max is None or amount is None:
        return True, ""
    try:
        limit = Decimal(str(grant_max))
        value = Decimal(str(amount))
    except (ArithmeticError, ValueError) as exc:  # pragma: no cover — قيمة غير رقمية
        _logger.warning(
            "حدُّ مِنحةٍ أو مبلغٌ غيرُ رقميّ grant_max=%s amount=%s — %s",
            grant_max,
            amount,
            exc,
        )
        return False, "حدّ المِنحة أو المبلغ ليس عددًا صالحًا — الرفض هو الافتراض"
    if value > limit:
        return False, f"المبلغ {value} يتجاوز حدّ المِنحة {limit}"
    return True, ""


def _grant_covers(
    grant: AuthorityGrantModel,
    holding: PositionHolding,
    targets: dict[str, Any],
) -> tuple[bool, str]:
    """أتُغطّي هذه المِنحة هذه العملية على هذا الهدف؟ — R7-C7، بلا ترقية ضمنية."""
    if grant.status != "active":
        return False, f"المِنحة حالتها '{grant.status}'"

    institution_id = targets.get("institution_id")
    department_id = targets.get("department_id")

    # كل هدفٍ مُسمّى في المِنحة يجب أن يطابق الهدف الفعلي. والهدف غير المُسمّى في
    # المِنحة لا يُفسَّر «أيّ هدف» بل يتركه لقاعدة النطاق أدناه.
    for column, key in (
        ("institution_id", "institution_id"),
        ("department_id", "department_id"),
        ("budget_id", "budget_id"),
        ("account_id", "account_id"),
    ):
        granted = getattr(grant, column)
        actual = targets.get(key)
        if granted is not None and granted != actual:
            return False, f"هدف المِنحة {column}='{granted}' لا يطابق '{actual}'"

    if grant.scope == "DEPARTMENT":
        if grant.department_id is None:
            return False, "مِنحة إدارية بلا إدارة مُسمّاة"
        if department_id is None:
            return (
                False,
                "سلطة إدارة لا تُغطّي موردًا على مستوى المؤسسة — "
                "لا ترقية من الإدارة إلى المؤسسة",
            )
        if grant.department_id != department_id:
            return False, "المورد في إدارة أخرى"
    elif grant.scope == "INSTITUTION":
        if grant.institution_id != institution_id:
            return False, "المورد في مؤسسة أخرى — سلطة المؤسسة لا تمتدّ إلى غيرها"
    elif grant.scope == "STATE":
        if grant.institution_id != institution_id:
            return False, "سلطة الولاية مُقيَّدة بالمؤسسة المُسمّاة في المِنحة"
        if targets.get("institution_branch") == "treasury":
            return (
                False,
                "سلطة ولاية ليست سلطة خزانة فدرالية — الخزانة تلزمها مِنحة خزانية صريحة",
            )
    elif grant.scope == "FEDERAL":
        if grant.institution_id != institution_id:
            return (
                False,
                "سلطة فدرالية ليست سلطة على كل مؤسسة — تُقيَّد بمؤسسة المِنحة",
            )
    else:  # pragma: no cover — يمنعه `ck_state_authority_grants_scope`
        return False, f"نطاق غير معروف '{grant.scope}'"

    # نطاق المنصب لا يُوسَّع بمِنحة أوسع منه: المِنحة أثرٌ للمنصب لا بديلٌ عنه.
    if grant.position_id != holding.position_id:  # pragma: no cover — مُفلترٌ في الاستعلام
        return False, "المِنحة لمنصب آخر"

    ok, why = _amount_within(grant.max_amount, targets.get("amount"))
    if not ok:
        return False, why

    return True, "مِنحةٌ نشطة مطابقةٌ للعملية وللهدف وللنطاق"


def resolve_authority(
    session: Session,
    context: AuthorizationContext,
    operation: str,
    *,
    institution_id: str,
    department_id: str | None = None,
    budget_id: str | None = None,
    account_id: str | None = None,
    amount: str | int | None = None,
    claimed_official_id: str | None = None,
) -> AuthorityDecision:
    """احسم سلطة المبدأ على عمليةٍ مُسمّاة وهدفٍ مُسمّى — R7-C6.

    Args:
        operation: من `GRANTABLE_OPERATIONS` حصرًا — لا اسم مُختَرع يمرّ.
        claimed_official_id: منصبٌ يدّعيه المُنادي. **ليس مصدر سلطة**: إن لم يكن
            من مناصب هويته رُفع `ForgedAuthorityError`.

    Returns:
        `AuthorityDecision` — والرفض قرارٌ موصوف لا استثناء، ليُسجَّل كما هو.

    Raises:
        ValueError: عملية خارج المفردة — خطأ برمجة لا رفض سلطة.
        ForgedAuthorityError: ادّعاء منصبٍ لا يشغله المُنادي.
    """
    if operation not in GRANTABLE_OPERATIONS:
        raise ValueError(
            f"عملية غير معروفة '{operation}' — المفردة: {list(GRANTABLE_OPERATIONS)}"
        )

    institution = session.get(InstitutionModel, institution_id)
    branch = institution.branch if institution is not None else None
    targets: dict[str, Any] = {
        "institution_id": institution_id,
        "department_id": department_id,
        "budget_id": budget_id,
        "account_id": account_id,
        "institution_branch": branch,
    }
    if amount is not None:
        targets["amount"] = str(amount)

    identity = resolve_identity(session, context)

    if not identity.resolved:
        if claimed_official_id is not None:
            # هوية مجهولة + ادّعاء منصب = بالضبط الثغرة التي جاءت R7-C لسدّها.
            # ولا يُستثنى منها سياديّ: من أراد أن يمرّ بصلاحيته فلا يدّعِ منصبًا.
            raise ForgedAuthorityError(
                "ادّعاء منصبٍ من مبدأٍ لا هوية كانونية له",
                principal_id=context.principal_id,
                claimed=claimed_official_id,
            )
        # لا هوية ⇒ لا سلسلة. والسيادي لا يُستثنى من الحقيقة: يُقال إنه مرّ
        # بصلاحيته لا بهويته، ويُصنَّف الأثر `UNRESOLVED` لا `PROVEN`.
        allowed = has_sovereign_authority(context)
        return AuthorityDecision(
            allowed=allowed,
            classification="UNRESOLVED",
            operation=operation,
            principal_id=context.principal_id,
            institution_id=institution_id,
            reason=(
                f"{identity.reason} — "
                + (
                    "أُجيزت بصلاحية سيادية بلا سلسلة إسناد"
                    if allowed
                    else "ولا صلاحية سيادية تُجيزها"
                )
            ),
            targets=targets,
        )

    holdings = resolve_positions(session, identity.identity_id or "", tenant_id=_tenant_of(context))

    if claimed_official_id is not None and claimed_official_id not in {
        holding.official_id for holding in holdings
    }:
        raise ForgedAuthorityError(
            "المنصب المُدَّعى ليس من مناصب هوية المُنادي",
            principal_id=context.principal_id,
            claimed=claimed_official_id,
        )

    candidates = [h for h in holdings if h.institution_id == institution_id]
    if claimed_official_id is not None:
        candidates = [h for h in candidates if h.official_id == claimed_official_id]

    rejected: list[tuple[str, str]] = []

    for holding in candidates:
        grants = session.execute(
            select(AuthorityGrantModel).where(
                AuthorityGrantModel.position_id == holding.position_id,
                AuthorityGrantModel.operation == operation,
                AuthorityGrantModel.tenant_id == _tenant_of(context),
            )
        ).scalars()
        for grant in grants:
            ok, why = _grant_covers(grant, holding, targets)
            if ok:
                return AuthorityDecision(
                    allowed=True,
                    classification="PROVEN",
                    operation=operation,
                    principal_id=context.principal_id,
                    identity_id=identity.identity_id,
                    official_id=holding.official_id,
                    position_id=holding.position_id,
                    grant_id=grant.id,
                    scope=grant.scope,
                    institution_id=institution_id,
                    reason=why,
                    targets=targets,
                )
            rejected.append((grant.id, why))

    # وصلنا هنا: الهوية معروفة ولا مِنحة تُغطّي. السيادي يمرّ بصلاحيته — ويُصنَّف
    # `PARTIAL` صراحةً لأن سلطته ليست من منصب. وغيره يُرفض ولا يُمنَح `write:all`.
    if has_sovereign_authority(context):
        holding = candidates[0] if candidates else None
        return AuthorityDecision(
            allowed=True,
            classification="PARTIAL",
            operation=operation,
            principal_id=context.principal_id,
            identity_id=identity.identity_id,
            official_id=holding.official_id if holding else None,
            position_id=holding.position_id if holding else None,
            scope=None,
            institution_id=institution_id,
            reason="أُجيزت بصلاحية سيادية — لا مِنحة سلطةٍ مطابقةٍ لهذا الهدف",
            targets=targets,
            rejected_grants=tuple(rejected),
        )

    if not holdings:
        reason = "الهوية لا تشغل أيّ منصب قائم"
    elif not candidates:
        reason = f"لا منصب لهذه الهوية في المؤسسة '{institution_id}'"
    elif rejected:
        reason = "مِنَح المنصب لا تُغطّي هذا الهدف: " + " · ".join(
            f"{gid}: {why}" for gid, why in rejected
        )
    else:
        reason = f"لا مِنحة سلطةٍ للمنصب على العملية '{operation}'"

    return AuthorityDecision(
        allowed=False,
        # الهوية ثابتة والمنصب أو المِنحة ناقص ⇒ `PARTIAL`، لا `UNRESOLVED`:
        # نعرف من هو، ولا نعرف بأيّ سلطةٍ يفعل هذا — والفرق يُقال.
        classification="PARTIAL",
        operation=operation,
        principal_id=context.principal_id,
        identity_id=identity.identity_id,
        official_id=candidates[0].official_id if candidates else None,
        position_id=candidates[0].position_id if candidates else None,
        institution_id=institution_id,
        reason=reason,
        targets=targets,
        rejected_grants=tuple(rejected),
    )


def resolve_official_for_principal(
    session: Session,
    context: AuthorizationContext,
    *,
    institution_id: str,
    claimed_official_id: str | None = None,
) -> OfficialModel | None:
    """اقرأ سجلّ المسؤول الذي **يملكه** المُنادي في هذه المؤسسة — لا الذي يدّعيه.

    يُستعمل في مسارات القرار والمال بدل قبول `official_id` من الطلب. والغياب
    `None` صريح يتولّى رفضه حدُّ التخويل القائم (`require_office` /
    `require_treasury_office`) بلا مسار تخويل ثانٍ هنا.

    Raises:
        ForgedAuthorityError: ادّعى منصبًا ليس من مناصب هويته.
    """
    identity = resolve_identity(session, context)
    if not identity.resolved:
        if claimed_official_id is not None:
            # هوية مجهولة + ادّعاء منصب = بالضبط الثغرة التي جاءت R7-C لسدّها.
            raise ForgedAuthorityError(
                "ادّعاء منصبٍ من مبدأٍ لا هوية كانونية له",
                principal_id=context.principal_id,
                claimed=claimed_official_id,
            )
        return None

    holdings = resolve_positions(session, identity.identity_id or "", tenant_id=_tenant_of(context))
    if claimed_official_id is not None and claimed_official_id not in {
        h.official_id for h in holdings
    }:
        raise ForgedAuthorityError(
            "المنصب المُدَّعى ليس من مناصب هوية المُنادي",
            principal_id=context.principal_id,
            claimed=claimed_official_id,
        )

    matches = [h for h in holdings if h.institution_id == institution_id]
    if claimed_official_id is not None:
        matches = [h for h in matches if h.official_id == claimed_official_id]
    if not matches:
        return None
    return session.get(OfficialModel, matches[0].official_id)


def describe_chain(
    session: Session,
    context: AuthorizationContext,
) -> dict[str, Any]:
    """صِف سلسلة السلطة كما تُقرأ اليوم — للتدقيق والتوثيق، لا للتخويل."""
    identity = resolve_identity(session, context)
    chain: dict[str, Any] = {
        "principal": context.principal_id,
        "verification": getattr(context.verification, "value", str(context.verification)),
        "identity": identity.as_dict(),
        "agent": None,
        "positions": [],
    }
    if identity.agent_id:
        agent = session.get(AgentModel, identity.agent_id)
        if agent is not None:
            chain["agent"] = {"id": agent.id, "name": agent.name, "status": agent.status}
    if identity.resolved:
        chain["positions"] = [
            {
                "official_id": h.official_id,
                "position_id": h.position_id,
                "position_code": h.position_code,
                "institution_id": h.institution_id,
                "institution_branch": h.institution_branch,
                "department_id": h.department_id,
                "authority_scope": h.authority_scope,
            }
            for h in resolve_positions(
                session, identity.identity_id or "", tenant_id=_tenant_of(context)
            )
        ]
    return chain


__all__ = [
    "AuthorityDecision",
    "ForgedAuthorityError",
    "IdentityResolution",
    "IdentityResolutionError",
    "PositionHolding",
    "describe_chain",
    "resolve_agent_identity",
    "resolve_authority",
    "resolve_identity",
    "resolve_official_for_principal",
    "resolve_positions",
]
