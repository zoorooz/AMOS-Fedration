"""
AMOS-Federation Federal/State Integration — Composed Authority Resolution
الهدف: حدُّ الحكومة فوق قرار المحرّك الكانونيّ — تركيبٌ لا محرّكٌ ثانٍ
النطاق: services/federal_state
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17 (R8-D · R8-G)

## محرّكٌ واحد، طبقتان

R8-D تمنع محرّكَ تخويلٍ ثانيًا. فهذه الوحدة **تنادي**
`national_registry.resolver.resolve_authority` (R7-C) ولا تكرّر منطقَه: لا تقرأ
`state_authority_grants` بنفسها، ولا تفحص شغلَ المنصب بنفسها، ولا تعرف كيف تُطابق
مِنحةً بعملية. تأخذ قرارَه كما هو ثمّ تضيف فحصًا واحدًا لا يملكه: **هل الهدفُ في
حكومةِ هذا المنصب؟**

    resolve_authority (R7-C)  →  evaluate_boundary (R8)  →  [تفويضٌ صريح؟]  →  قرار

## الاتّجاه في طبقةٍ واحدة: التضييق

القاعدةُ الثابتة، ويحرسها اختبار: **لا تُحوَّل «مرفوض» إلى «مقبول» إلا بموجب صفِّ
تفويضٍ نشطٍ حاضر**، ولا يُرفَّع تصنيفٌ أبدًا. `_narrow` تأخذ أدنى التصنيفين، فما
كان `PARTIAL` في المحرّك لا يصير `PROVEN` هنا لأيّ سبب.

## ما لا يُقبل من المستدعي

`government_id` **لا يُقرأ من النداء** متى وُجدت مؤسسةٌ في الهدف: يُقرأ من
`state_institution_governments`. و`scope` لا يُقرأ من النداء إطلاقًا: هو
`decision.scope` الصادرُ عن المحرّك من منصبٍ نشطٍ حقيقيّ. و`role` لا يُقرأ ولا
يُفحَص: `role="governor"` و`role="federal_official"` و`role="minister"` لا تدخل
هذا الملفّ في أيّ سطر — محروسٌ باختبارٍ ساكن.

## السيادة كما هي (R8-M)

لا يُنادى `has_sovereign_authority` هنا لتوسيع سلطةٍ حكومية، ولا يُضاف
`role="king"` كطريقِ مصادقة. نموذجُ السيادة (CROWN أعلى سلطة، والأمرُ السياديّ
الصحيح غيرُ مُدَّعي السيادة) يبقى حيث وضعته R6 بلا تغيير: هذه الطبقةُ **تُضيّق
ولا توسّع**، فلا تنقص من CROWN شيئًا ولا تمنحه طريقًا جديدًا.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from amos_federation.services.federal_state.delegation import find_active_delegation
from amos_federation.services.federal_state.scopes import (
    ScopePoint,
    evaluate_boundary,
    government_chain,
    government_of_institution,
    target_point,
)
from amos_federation.services.national_registry.resolver import (
    AuthorityDecision,
    resolve_authority,
)

if TYPE_CHECKING:
    from decimal import Decimal

    from sqlalchemy.orm import Session

    from amos_federation.common.principal import AuthorizationContext

#: ترتيبُ اليقين — للتضييق وحده.
_CLASSIFICATION_RANK: dict[str, int] = {"UNRESOLVED": 0, "PARTIAL": 1, "PROVEN": 2}


def _narrow(base: str, other: str) -> str:
    """أعِد أدنى التصنيفين — فلا تُرفَّع درجةُ يقينٍ في هذه الطبقة أبدًا."""
    if _CLASSIFICATION_RANK.get(other, 0) < _CLASSIFICATION_RANK.get(base, 0):
        return other
    return base


def _delegator_government(
    session: Session, *, holder: ScopePoint, target: ScopePoint, tenant_id: str
) -> str | None:
    """أعِد الحكومةَ التي **تملك** نطاقَ الهدف، فهي وحدها من يصحّ أن تفوّض.

    قاعدتان لا أكثر:

    * هدفٌ في حكومةٍ أخرى → المالكُ حكومةُ الهدف. تفوّض هي داخلًا، ولا يفوّض
      المستدعي نفسَه.
    * هدفٌ بمستوى فدراليٍّ وشاغلُ المنصب دونه → المالكُ الجذرُ الفدراليُّ لسلسلة
      حكومته. فالمستوى الفدراليُّ لا يُنتزَع بالصعود في الشجرة، بل يُعطى.

    وما عدا ذلك `None`: لا مالكَ يُفترَض، فلا تفويضَ يُقرأ.
    """
    if target.government_id and target.government_id != holder.government_id:
        return target.government_id
    if target.level == "FEDERAL" and holder.level != "FEDERAL" and holder.government_id:
        chain = government_chain(session, holder.government_id, tenant_id=tenant_id)
        root = chain[-1] if chain else None
        return root if root and root != holder.government_id else None
    return None


@dataclass(frozen=True, slots=True)
class GovernmentAuthority:
    """قرارُ سلطةٍ حكوميّ: قرارُ المحرّك + حدُّ الحكومة + التفويضُ إن وُجد.

    Attributes:
        allowed: الحكمُ النهائيّ بعد الحدّ.
        classification: `PROVEN` / `PARTIAL` / `UNRESOLVED` — أدنى ما ثبت.
        decision: قرارُ المحرّك الكانونيّ كما صدر، بلا تعديل.
        holder: نطاقُ شاغل المنصب كما استُنبط من القاعدة.
        target: موضعُ الهدف كما استُنبط من القاعدة.
        boundary_reason: سببُ الحكم بلفظه — يُكتب في الأثر فيُفحَص.
        delegation_id: صفُّ التفويض الذي أجاز عبورَ حدِّ الحكومة، إن وُجد.
    """

    allowed: bool
    classification: str
    decision: AuthorityDecision
    holder: ScopePoint
    target: ScopePoint
    boundary_reason: str
    delegation_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def government_id(self) -> str | None:
        """حكومةُ الهدف — لا حكومةُ المستدعي."""
        return self.target.government_id

    def as_dict(self) -> dict[str, Any]:
        """حمولةُ الأثر — قرارُ المحرّك كما هو، وفوقه ما أضافته هذه الطبقة."""
        return {
            **self.decision.as_dict(),
            "government_allowed": self.allowed,
            "government_classification": self.classification,
            "government_boundary_reason": self.boundary_reason,
            "government_holder_scope": self.holder.level,
            "government_holder_government_id": self.holder.government_id,
            "government_target_level": self.target.level,
            "government_target_government_id": self.target.government_id,
            "government_delegation_id": self.delegation_id,
        }


def resolve_government_authority(
    session: Session,
    context: AuthorizationContext,
    operation: str,
    *,
    target_level: str,
    institution_id: str | None,
    department_id: str | None = None,
    government_id: str | None = None,
    budget_id: str | None = None,
    account_id: str | None = None,
    amount: Decimal | None = None,
    claimed_official_id: str | None = None,
    tenant_id: str,
) -> GovernmentAuthority:
    """احلُل سلطةً حكوميةً كاملةَ الأجوبة: مَن · بأيّ منصب · أين · بأيّ نطاق · على ماذا.

    الترتيب مقصود: المحرّكُ الكانونيّ أوّلًا. فمن لم يُثبت هويةً ومنصبًا ومِنحةً
    يُرفض قبل أن نسأل عن حكومةٍ إطلاقًا، ولا يُقرأ جدولُ تفويضٍ لمن لا سلطةَ له.

    Args:
        operation: عمليةٌ من مفردة R7-C — لا اسمَ مُختَرعًا هنا.
        target_level: مستوى الهدف المطلوب الحكمُ عليه (`FEDERAL`…`DEPARTMENT`).
        institution_id: مؤسسةُ الهدف. حكومتُها تُقرأ من الربط لا من النداء.
        government_id: يُقبل **فقط** حين لا مؤسسةَ في الهدف (هدفٌ حكوميٌّ عامّ).
        amount: المبلغُ حين تكون العمليةُ مالية — يُفحَص في المِنحة وفي التفويض.

    Returns:
        `GovernmentAuthority`: مقبولٌ أو مرفوضٌ بسببٍ مُصرَّح، وتصنيفٌ لا يعلو
        تصنيفَ المحرّك أبدًا.
    """
    decision = resolve_authority(
        session,
        context,
        operation,
        institution_id=institution_id,
        department_id=department_id,
        budget_id=budget_id,
        account_id=account_id,
        amount=amount,
        claimed_official_id=claimed_official_id,
    )
    target = target_point(
        session,
        level=target_level,
        institution_id=institution_id,
        department_id=department_id,
        government_id=government_id,
        tenant_id=tenant_id,
    )
    holder_institution = decision.institution_id or institution_id
    holder = ScopePoint(
        level=decision.scope or "",
        government_id=(
            government_of_institution(session, holder_institution, tenant_id=tenant_id)
            if holder_institution
            else None
        ),
        institution_id=holder_institution,
        department_id=department_id,
    )

    if not decision.allowed:
        return GovernmentAuthority(
            allowed=False,
            classification=decision.classification,
            decision=decision,
            holder=holder,
            target=target,
            boundary_reason=f"رفضُ المحرّك الكانونيّ: {decision.reason}",
        )

    verdict = evaluate_boundary(holder, target)
    if verdict.allowed:
        return GovernmentAuthority(
            allowed=True,
            classification=decision.classification,
            decision=decision,
            holder=holder,
            target=target,
            boundary_reason=verdict.reason,
        )

    # الحدُّ رفض. والطريقُ الوحيدُ للعبور صفُّ تفويضٍ نشطٍ حاضر — ولا يوجد طريقٌ
    # بالدور ولا بالعلاقة ولا بموضع الحكومة في الشجرة.
    delegator = _delegator_government(session, holder=holder, target=target, tenant_id=tenant_id)
    if delegator and holder.government_id:
        # يُقرأ التفويضُ إلى حكومةِ شاغل المنصب، ثمّ إلى مؤسستِه بعينها — والأضيقُ
        # مقصودٌ: تفويضٌ لمؤسسةٍ واحدةٍ لا يُعمَّم على ولايتها كلِّها.
        delegation = find_active_delegation(
            session,
            from_government_id=delegator,
            to_government_id=holder.government_id,
            operation=operation,
            scope=target.level,
            amount=amount,
            tenant_id=tenant_id,
        )
        if delegation is None and holder.institution_id:
            delegation = find_active_delegation(
                session,
                from_government_id=delegator,
                to_institution_id=holder.institution_id,
                operation=operation,
                scope=target.level,
                amount=amount,
                tenant_id=tenant_id,
            )
        if delegation is not None:
            return GovernmentAuthority(
                allowed=True,
                classification=decision.classification,
                decision=decision,
                holder=holder,
                target=target,
                boundary_reason=f"عبورُ حدِّ الحكومة بتفويضٍ صريح ({verdict.reason})",
                delegation_id=delegation.id,
            )

    # المؤسسةُ غيرُ المربوطةِ بحكومةٍ ليست «مرفوضةً لأنها غيرُ مؤهَّلة»، بل
    # **غيرُ محلولة**: بنيتُها لم تُسجَّل بعد. والتصنيفُ يقول ذلك بلا تجميل.
    unresolved = not holder.government_id or not target.government_id
    return GovernmentAuthority(
        allowed=False,
        classification=_narrow(decision.classification, "UNRESOLVED")
        if unresolved
        else decision.classification,
        decision=decision,
        holder=holder,
        target=target,
        boundary_reason=verdict.reason,
    )


def require_government_authority(
    session: Session,
    context: AuthorizationContext,
    operation: str,
    **kwargs: Any,
) -> GovernmentAuthority:
    """كالسابقة، لكن ترفع `GovernmentAuthorityError` عند الرفض — fail closed.

    تُستعمَل حيث يتلو التخويلَ كتابةٌ فورية، فيستحيل أن تُنسى قراءةُ `allowed`.
    """
    authority = resolve_government_authority(session, context, operation, **kwargs)
    if not authority.allowed:
        raise GovernmentAuthorityError(operation, authority)
    return authority


class GovernmentAuthorityError(PermissionError):  # noqa: N818 — رفض تخويل، لا عطل
    """رُفض حكمٌ حكوميّ: إمّا رفضُ المحرّك، وإمّا حدُّ الحكومة بلا تفويض."""

    def __init__(self, operation: str, authority: GovernmentAuthority):
        self.operation = operation
        self.authority = authority
        super().__init__(
            f"سلطةٌ حكوميةٌ مرفوضة على {operation}: {authority.boundary_reason}"
            f" [التصنيف: {authority.classification}]"
        )


__all__ = [
    "GovernmentAuthority",
    "GovernmentAuthorityError",
    "require_government_authority",
    "resolve_government_authority",
]
