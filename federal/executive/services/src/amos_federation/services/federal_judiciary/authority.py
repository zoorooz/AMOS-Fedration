"""
AMOS-Federation Federal Judiciary — Judicial Authority Resolution
الهدف: «هل هذا قاضٍ يملك الفصل في هذه القضية؟» يُجاب من صفوفٍ في القاعدة أو يُرفَض
النطاق: services/federal_judiciary
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17 (R7-D9)

## السلسلة المفروضة — ستّ حلقاتٍ لا خمس

    جلسةٌ مُتحقَّقة → هويةٌ كانونية → مسؤولٌ مُقلَّد → منصبٌ نشطٌ في فرعٍ قضائيّ
                   → تقليدُ قضاءٍ نشطٌ في محكمةٍ بعينها → نطاقٌ مطابق → قضيةٌ مُسندة

وكلُّ حلقةٍ صفٌّ يُقرأ:

| الحلقة | من أين تُقرأ | ما يُسقِطها |
| --- | --- | --- |
| الهوية | `state_identity_principals` (R7-C) | لا ربط، أو الهوية معلَّقة/متقاعدة/`unresolved` |
| المنصب | `resolve_positions` (R7-C) | تقليدٌ معزول، أو مسؤولٌ غير `appointed`، أو منصبٌ غير `active` |
| الفرع القضائيّ | `state_institutions.branch` | فرعٌ غير `judicial` — فمنصبٌ تنفيذيّ لا يقضي |
| تقليد القضاء | `state_court_judges` | حالةٌ `suspended`/`revoked`، أو محكمةٌ أخرى |
| المحكمة | `state_courts.status` | محكمةٌ معلَّقة أو محلولة |
| النطاق | مساواةٌ صريحة (`jurisdiction.py`) | نطاقُ منصبٍ لا يساوي نطاق المحكمة والقضية |
| الإسناد | `state_legal_cases.assigned_judge_id` | قضيةٌ مُسندةٌ إلى قاضٍ آخر، أو غير مُسندة |

## `FAIL CLOSED` — لا نتيجةٌ سالبةٌ صامتة

الدالّةُ الافتراضية `require_judicial_authority` **ترفع** `JudicialAuthorityError`
عند سقوط أيّ حلقة، ولا تُعيد `allowed=False` ليتجاهله المُنادي. ومن أراد قراءةً
تشخيصية بلا رفعٍ ينادي `resolve_judicial_authority(..., strict=False)` — وهي
مستعملةٌ في `judiciary_health` وفي الشرح، لا في أيّ مسار كتابة.

## `role="judge"` ليس إثباتًا — وهذا مفروضٌ لا موصوف

لا سلسلةَ نصٍّ `"judge"` تُقرأ من دورٍ ولا من صلاحيةٍ في هذا الملفّ. والدور الذي
يملكه القاضي عمليًّا هو `official` نفسه — وهو ما يملكه كل موظَّفٍ آخر. فما يميّز
القاضي صفُّ تقليدٍ في محكمة، لا كلمةٌ في جلسته. ويحرس ذلك اختبارٌ ساكن.

## التصنيف لا يُرفَع بلا دليل

`classification` من `PROVENANCE_CLASSES` القائمة (R7-C): `PROVEN` حين تُقرأ الحلقات
كلّها بما فيها إسنادُ القضية، و`PARTIAL` حين تُقرأ سلسلةُ القاضي والمحكمة بلا
قضيةٍ مطلوبة (تخويلٌ على مستوى المحكمة)، و`UNRESOLVED` في القراءة غير الصارمة عند
انقطاع السلسلة. ولا `PROVEN` بلا القضية.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from amos_federation.common.principal import DEFAULT_TENANT
from amos_federation.services.federal_judiciary.jurisdiction import (
    JurisdictionError,
    assert_jurisdiction_match,
    assert_scope_covers_court,
)
from amos_federation.services.federal_judiciary.models import (
    CourtJudgeModel,
    CourtModel,
    LegalCaseModel,
)
from amos_federation.services.national_registry.resolver import (
    resolve_identity,
    resolve_positions,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from amos_federation.common.principal import AuthorizationContext

#: الحالاتُ التي يجوز فيها للقاضي المُسند أن يفصل. `opened` و`filed` مُستثنيتان:
#: القضيةُ قبل الإسناد لا قاضيَ لها، فلا حكمَ فيها.
RULABLE_CASE_STATUSES: tuple[str, ...] = ("assigned", "hearing", "decided", "enforcement")


class JudicialAuthorityError(PermissionError):  # noqa: N818 — رفضُ سلطة، لا عطل
    """لا سلطةَ قضائية مُثبَتة — الرفضُ مقصودٌ ويحمل سبب السقوط."""

    def __init__(self, principal_id: str, reason: str) -> None:
        self.principal_id = principal_id
        self.reason = reason
        super().__init__(f"لا سلطة قضائية للمبدأ '{principal_id}': {reason}")


@dataclass(frozen=True, slots=True)
class JudicialAuthority:
    """قرارُ حلّ السلطة القضائية — يُخزَّن مع الحكم ليُراجَع بعد سنة."""

    allowed: bool
    classification: str
    principal_id: str
    identity_id: str | None = None
    official_id: str | None = None
    position_id: str | None = None
    judge_id: str | None = None
    court_id: str | None = None
    case_id: str | None = None
    jurisdiction: str | None = None
    institution_id: str | None = None
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        """حمولةٌ قابلةٌ للتسلسل تُكتب في `state_rulings.authority`."""
        return {
            "allowed": self.allowed,
            "classification": self.classification,
            "principal_id": self.principal_id,
            "identity_id": self.identity_id,
            "official_id": self.official_id,
            "position_id": self.position_id,
            "judge_id": self.judge_id,
            "court_id": self.court_id,
            "case_id": self.case_id,
            "jurisdiction": self.jurisdiction,
            "institution_id": self.institution_id,
            "reason": self.reason,
        }


def _tenant_of(context: AuthorizationContext) -> str:
    return context.tenant_id or DEFAULT_TENANT


def resolve_judicial_authority(
    session: Session,
    context: AuthorizationContext,
    *,
    court_id: str,
    case_id: str | None = None,
    strict: bool = True,
) -> JudicialAuthority:
    """احلّ السلطة القضائية للمبدأ على محكمةٍ (وقضيةٍ إن طُلبت).

    Args:
        session: جلسةٌ مفتوحة — الدالّة تقرأ ولا تكتب ولا تُغلِق.
        context: سياقُ تخويلٍ من جلسةٍ مُتحقَّق منها.
        court_id: المحكمة التي يُدَّعى القضاء فيها.
        case_id: القضية — حين تُمرَّر يُفحَص الإسناد وحالةُ القضية والنطاق.
        strict: `True` (الافتراض) يرفع استثناءً عند السقوط — `FAIL CLOSED`.

    Returns:
        `JudicialAuthority` — `allowed=True` بتصنيف `PROVEN` أو `PARTIAL`.

    Raises:
        JudicialAuthorityError: `strict=True` وانقطعت السلسلة.
    """
    principal_id = context.principal_id
    tenant = _tenant_of(context)

    def deny(reason: str, *, identity_id: str | None = None, **extra: Any) -> JudicialAuthority:
        decision = JudicialAuthority(
            allowed=False,
            classification="UNRESOLVED",
            principal_id=principal_id,
            identity_id=identity_id,
            court_id=court_id,
            case_id=case_id,
            reason=reason,
            **extra,
        )
        if strict:
            raise JudicialAuthorityError(principal_id, reason)
        return decision

    # 1. الهوية الكانونية — لا اسمَ ولا دور.
    identity = resolve_identity(session, context)
    if not identity.resolved or identity.identity_id is None:
        return deny(f"الهوية غير محلولة: {identity.reason}")

    # 2. المحكمة — قائمةٌ ونشطةٌ وفي المستأجر نفسه.
    court = session.get(CourtModel, court_id)
    if court is None or court.tenant_id != tenant:
        return deny(
            f"لا محكمة بالمعرّف '{court_id}' في مستأجر '{tenant}'",
            identity_id=identity.identity_id,
        )
    if court.status != "active":
        return deny(
            f"المحكمة '{court.code}' حالتها '{court.status}' لا 'active'",
            identity_id=identity.identity_id,
        )

    # 3. تقليدُ القضاء — صفٌّ نشطٌ يربط هذه الهوية بهذه المحكمة بالذات.
    judge = session.execute(
        select(CourtJudgeModel).where(
            CourtJudgeModel.court_id == court_id,
            CourtJudgeModel.identity_id == identity.identity_id,
            CourtJudgeModel.tenant_id == tenant,
            CourtJudgeModel.status == "active",
        )
    ).scalar_one_or_none()
    if judge is None:
        return deny(
            f"لا تقليدَ قضاءٍ نشطًا لهذه الهوية في المحكمة '{court.code}'",
            identity_id=identity.identity_id,
        )

    # 4. المنصب — نشطٌ، في فرعٍ قضائيّ، وبنطاقٍ يساوي نطاق المحكمة.
    holdings = {
        holding.position_id: holding
        for holding in resolve_positions(session, identity.identity_id, tenant_id=tenant)
    }
    holding = holdings.get(judge.position_id)
    if holding is None:
        return deny(
            "منصبُ القاضي غير نشطٍ الآن (تقليدٌ معزول أو مسؤولٌ معزول أو منصبٌ ملغى)",
            identity_id=identity.identity_id,
            judge_id=judge.id,
        )
    if holding.institution_branch != "judicial":
        return deny(
            f"منصبُ القاضي في فرع '{holding.institution_branch}' لا 'judicial'",
            identity_id=identity.identity_id,
            judge_id=judge.id,
            position_id=holding.position_id,
        )
    if holding.institution_id != court.institution_id:
        return deny(
            "منصبُ القاضي في مؤسسةٍ غير مؤسسة المحكمة",
            identity_id=identity.identity_id,
            judge_id=judge.id,
            position_id=holding.position_id,
        )
    try:
        assert_scope_covers_court(
            position_scope=holding.authority_scope, court_jurisdiction=court.jurisdiction
        )
    except JurisdictionError as exc:
        return deny(
            str(exc),
            identity_id=identity.identity_id,
            judge_id=judge.id,
            position_id=holding.position_id,
        )

    common: dict[str, Any] = {
        "principal_id": principal_id,
        "identity_id": identity.identity_id,
        "official_id": holding.official_id,
        "position_id": holding.position_id,
        "judge_id": judge.id,
        "court_id": court.id,
        "jurisdiction": court.jurisdiction,
        "institution_id": court.institution_id,
    }

    # 5. بلا قضية: تخويلٌ على مستوى المحكمة — `PARTIAL` بقصدٍ لا تسامحًا.
    if case_id is None:
        return JudicialAuthority(
            allowed=True,
            classification="PARTIAL",
            case_id=None,
            reason="قاضٍ مُقلَّدٌ في محكمةٍ نشطة، ولا قضيةَ مطلوبةً في هذا الفحص",
            **common,
        )

    # 6. القضية — قائمةٌ، في هذه المحكمة، بنطاقٍ مطابق، ومُسندةٌ إلى هذا القاضي.
    case = session.get(LegalCaseModel, case_id)
    if case is None or case.tenant_id != tenant:
        return deny(
            f"لا قضية بالمعرّف '{case_id}' في مستأجر '{tenant}'",
            identity_id=identity.identity_id,
            judge_id=judge.id,
            position_id=holding.position_id,
        )
    if case.court_id != court.id:
        return deny(
            f"القضية '{case.reference}' ليست في المحكمة '{court.code}'",
            identity_id=identity.identity_id,
            judge_id=judge.id,
            position_id=holding.position_id,
        )
    try:
        assert_jurisdiction_match(
            court_jurisdiction=court.jurisdiction,
            case_jurisdiction=case.jurisdiction,
            court_institution_id=court.institution_id,
            case_institution_id=court.institution_id,
        )
    except JurisdictionError as exc:  # pragma: no cover — يمنعه فحصُ الفتح
        return deny(
            str(exc),
            identity_id=identity.identity_id,
            judge_id=judge.id,
            position_id=holding.position_id,
        )
    if case.assigned_judge_id != judge.id:
        return deny(
            f"القضية '{case.reference}' غير مُسندةٍ إلى هذا القاضي",
            identity_id=identity.identity_id,
            judge_id=judge.id,
            position_id=holding.position_id,
        )
    if case.status not in RULABLE_CASE_STATUSES:
        return deny(
            f"حالةُ القضية '{case.status}' لا تسمح بعملٍ قضائيّ فاصل",
            identity_id=identity.identity_id,
            judge_id=judge.id,
            position_id=holding.position_id,
        )

    return JudicialAuthority(
        allowed=True,
        classification="PROVEN",
        case_id=case.id,
        reason="السلسلة كاملة: هوية · مسؤول · منصبٌ قضائيّ · تقليدٌ نشط · محكمة · نطاق · إسناد",
        **common,
    )


def require_judicial_authority(
    session: Session,
    context: AuthorizationContext,
    *,
    court_id: str,
    case_id: str | None = None,
) -> JudicialAuthority:
    """اطلب سلطةً قضائية مُثبَتة — أو ارفع. هذا هو المدخل في مسارات الكتابة."""
    return resolve_judicial_authority(
        session, context, court_id=court_id, case_id=case_id, strict=True
    )


def describe_judicial_chain(
    session: Session, context: AuthorizationContext, *, court_id: str, case_id: str | None = None
) -> dict[str, Any]:
    """اشرح السلسلة كما هي — للتشخيص، بلا رفعٍ وبلا كتابة."""
    return resolve_judicial_authority(
        session, context, court_id=court_id, case_id=case_id, strict=False
    ).as_dict()


__all__ = [
    "RULABLE_CASE_STATUSES",
    "JudicialAuthority",
    "JudicialAuthorityError",
    "describe_judicial_chain",
    "require_judicial_authority",
    "resolve_judicial_authority",
]
