"""
AMOS-Federation Federal/State Integration — Scope Boundaries
الهدف: قاعدةٌ واحدةٌ تُجيب: هل يبلغ نطاقُ هذا المنصبِ هذا الهدفَ بعينه؟
النطاق: services/federal_state
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17 (R8-D)

## لماذا ملفٌّ للحدود وحدها

R8-D تطلب أربعةَ حدودٍ لا واحدًا: فدراليٌّ لا يعني ولائيًّا · ولايةٌ لا تعني
ولايةً أخرى · مؤسسةٌ لا تعني الولايةَ كلَّها · إدارةٌ لا تعني المؤسسةَ كلَّها.
ولو تفرّقت هذه الأربعةُ في `authority.py` و`catalog.py` و`service.py` لتباعدت
نسخُها كما تباعدت مفردتا الأدوار في R6. فهي **دالّةٌ واحدةٌ صافية** (`pure`):
لا جلسةَ ولا كتابة، تأخذ نقطتين وتُرجع حكمًا وسببًا. تناديها كلُّ طبقةٍ أعلى.

## القاعدة صريحةٌ لا سلّمٌ ضمنيّ

`_LEVEL_RANK` تمنع **التوسيع** فقط (إدارةٌ لا تحكم على مستوى مؤسسة)، وهي **ليست**
تصريحًا بأن الأعلى يحكم الأدنى. فبعدها تُفرض مطابقةُ الهدف بعينه:

| نطاق شاغل المنصب | يبلغ | لا يبلغ ولو بدا «أدنى» |
| --- | --- | --- |
| `FEDERAL` | أهدافَ حكومته الفدرالية نفسِها | ولايةً ومؤسساتِها — تلزمه تفويضةٌ صريحة |
| `STATE` | أهدافَ حكومةِ ولايته نفسِها | ولايةً أخرى · الحكومةَ الفدرالية |
| `INSTITUTION` | مؤسستَه وإداراتِها | مؤسسةً أخرى ولو تحت نفس الحكومة |
| `DEPARTMENT` | إدارتَه المُسمّاة | مواردَ مؤسسته على مستواها |

والمؤسسةُ غيرُ المربوطةِ بحكومةٍ (كلُّ صفوف ما قبل R8) هدفُها `government_id`
عدَمٌ — فيُرفض كلُّ حكمٍ فدراليٍّ أو ولائيٍّ عليها **رفضًا مُعلَنًا** (`لا حكومةَ
مربوطة`) لا تخميناً بحكومةٍ افتراضية. وذلك أصلُ تصنيف `UNRESOLVED` في R8-R.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import select

from amos_federation.services.federal_state.models import (
    GovernmentModel,
    InstitutionGovernmentModel,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

#: رتبةُ المدى — لمنع التوسيع وحده. ليست سلطةً هابطة.
_LEVEL_RANK: dict[str, int] = {"DEPARTMENT": 0, "INSTITUTION": 1, "STATE": 2, "FEDERAL": 3}


@dataclass(frozen=True, slots=True)
class ScopePoint:
    """نقطةٌ في بنية الدولة — نطاقُ شاغلِ منصبٍ أو موضعُ هدف.

    Attributes:
        level: أحدُ `SCOPE_LEVELS`.
        government_id: الحكومةُ المعنيّة، أو `None` لمن لا حكومةَ مربوطةً له.
        institution_id: المؤسسة، أو `None` لهدفٍ حكوميٍّ عامّ.
        department_id: الإدارة، ويلزم حضورُها في مستوى `DEPARTMENT`.
    """

    level: str
    government_id: str | None = None
    institution_id: str | None = None
    department_id: str | None = None


@dataclass(frozen=True, slots=True)
class BoundaryVerdict:
    """حكمُ الحدّ ومعه سببُه — السببُ يُكتب في الأثر فيُفحَص لاحقًا."""

    allowed: bool
    reason: str


def government_of_institution(
    session: Session, institution_id: str, *, tenant_id: str
) -> str | None:
    """أعِد حكومةَ مؤسسةٍ قائمةٍ من جدول الربط، أو `None` إن لم تُربط.

    `None` ليست خطأً؛ هي حقيقةُ كلِّ مؤسسةٍ سُجِّلت قبل R8. ومن يقرأها يقول
    `UNRESOLVED` ولا يفترض حكومةً.
    """
    return session.scalar(
        select(InstitutionGovernmentModel.government_id).where(
            InstitutionGovernmentModel.institution_id == institution_id,
            InstitutionGovernmentModel.tenant_id == tenant_id,
        )
    )


def government_chain(session: Session, government_id: str, *, tenant_id: str) -> tuple[str, ...]:
    """أعِد سلسلةَ الحكومة من نفسها صعودًا إلى الجذر الفدراليّ.

    الحدُّ الأقصى للصعود مقصود: قيدُ القاعدة يمنع الأبَ الذاتيّ، ولا يمنع حلقةً
    أطول لو كُتبت بيدٍ خارج هذه الواجهة — فالحلقةُ تُقطَع هنا ولا تُعلَّق العملية.
    """
    chain: list[str] = []
    current: str | None = government_id
    seen: set[str] = set()
    while current and current not in seen and len(chain) < 16:
        seen.add(current)
        chain.append(current)
        current = session.scalar(
            select(GovernmentModel.parent_government_id).where(
                GovernmentModel.id == current, GovernmentModel.tenant_id == tenant_id
            )
        )
    return tuple(chain)


def evaluate_boundary(holder: ScopePoint, target: ScopePoint) -> BoundaryVerdict:
    """هل يبلغ نطاقُ `holder` الهدفَ `target`؟ حكمٌ صافٍ بلا قاعدةِ بيانات.

    الترتيب مقصود: يُرفض التوسيعُ أوّلًا (فرسالةُ «إدارةٌ لا تحكم مؤسسة» أوضحُ من
    «مؤسسةٌ غير مطابقة»)، ثمّ تُفرض المطابقةُ بعينها لكل مستوى.
    """
    if holder.level not in _LEVEL_RANK:
        return BoundaryVerdict(False, f"نطاقٌ مجهول: {holder.level}")
    if target.level not in _LEVEL_RANK:
        return BoundaryVerdict(False, f"مستوى هدفٍ مجهول: {target.level}")
    if _LEVEL_RANK[target.level] > _LEVEL_RANK[holder.level]:
        return BoundaryVerdict(
            False, f"توسيعُ نطاق: منصبٌ بنطاق {holder.level} على هدفٍ بمستوى {target.level}"
        )

    if holder.level == "DEPARTMENT":
        if not holder.department_id:
            return BoundaryVerdict(False, "نطاقُ إدارةٍ بلا إدارةٍ مُسمّاة")
        if target.department_id != holder.department_id:
            return BoundaryVerdict(False, "إدارةٌ لا تبلغ إدارةً أخرى ولا مستوى مؤسستها")
        return BoundaryVerdict(True, "مطابقةُ إدارة")

    if holder.level == "INSTITUTION":
        if not holder.institution_id:
            return BoundaryVerdict(False, "نطاقُ مؤسسةٍ بلا مؤسسةٍ مُسمّاة")
        if target.institution_id != holder.institution_id:
            return BoundaryVerdict(False, "مؤسسةٌ لا تبلغ مؤسسةً أخرى")
        return BoundaryVerdict(True, "مطابقةُ مؤسسة")

    # `STATE` و`FEDERAL`: المطابقةُ على الحكومةِ بعينها. فالفدراليُّ لا يبلغ ولايةً
    # لمجرّد كونها تحته في الشجرة، والولايةُ لا تبلغ سواها — ولا تبلغ الفدرالية.
    if not holder.government_id:
        return BoundaryVerdict(False, f"نطاقُ {holder.level} بلا حكومةٍ مُسمّاة")
    if not target.government_id:
        return BoundaryVerdict(False, "الهدفُ لا حكومةَ مربوطةً له")
    if target.government_id != holder.government_id:
        return BoundaryVerdict(
            False,
            f"حدُّ حكومة: منصبٌ في {holder.government_id} على هدفٍ في {target.government_id}",
        )
    return BoundaryVerdict(True, f"مطابقةُ حكومة على مستوى {holder.level}")


def target_point(
    session: Session,
    *,
    level: str,
    institution_id: str | None,
    department_id: str | None = None,
    government_id: str | None = None,
    tenant_id: str,
) -> ScopePoint:
    """اقرأ موضعَ الهدف من القاعدة — الحكومةُ تُستنبَط من الربط لا من المستدعي.

    لا يُقبل `government_id` من المستدعي إلا حين لا مؤسسةَ في الهدف (هدفٌ حكوميٌّ
    عامّ كإنشاء ولايةٍ أو تفويضٍ بين حكومتين). ومتى وُجدت مؤسسةٌ فحكومتُها من
    `state_institution_governments` حصرًا — فلا يُدّعى انتماءٌ في نداءٍ.
    """
    resolved_government = government_id
    if institution_id:
        resolved_government = government_of_institution(
            session, institution_id, tenant_id=tenant_id
        )
    return ScopePoint(
        level=level,
        government_id=resolved_government,
        institution_id=institution_id,
        department_id=department_id,
    )


__all__ = [
    "BoundaryVerdict",
    "ScopePoint",
    "evaluate_boundary",
    "government_chain",
    "government_of_institution",
    "target_point",
]
