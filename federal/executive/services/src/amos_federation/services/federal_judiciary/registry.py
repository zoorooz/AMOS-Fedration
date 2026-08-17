"""
AMOS-Federation Federal Judiciary — Court & Judge Registry
الهدف: المحكمة مؤسسةٌ مُسجَّلة، والقاضي هويةٌ مُقلَّدة — لا سجلَّ محاكمَ ثالث
النطاق: services/federal_judiciary
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17 (R7-D4)

## لا `Court system` ثالث — كيف يُفرَض ذلك

الجردُ (R7-D1) وجد نظامين يمسّان المحاكم: `JudicialBranch` في
`services/governance/federation.py` (قاضٍ نصٌّ حرّ)، و`state_cases` الإدارية في
`government_services`. فما فعلته هذه الوحدة **إعادةُ استعمالٍ لا إنشاء**:

1. المحكمة **لا** تُنشئ مؤسسة: `create_court` يطلب مؤسسةً قائمةً في
   `state_institutions` برمزها، ويفرض أن فرعها `judicial` وحالتها `active`.
   و`INSTITUTION_KINDS` القائمة تحتوي `'court'` أصلًا — فلا مفردةَ نوعٍ جديدة.
2. القاضي **لا** يُنشئ مسؤولًا ولا منصبًا: `appoint_judge` يطلب `official_id`
   من `state_officials` و`position_id` من `state_positions` القائمين (R7-A/R7-C)،
   ثم يفرض التطابق بينهما وبين المحكمة.
3. الهوية **لا** تُنشأ هنا: تُقرأ من ربط الوكيل بالهوية (R7-C5). فإن لم يكن
   لوكيل المسؤول هويةٌ كانونية رُفض التقليد — ولا هويةَ ضمنية.

## الشروط الخمسة لتقليد قاضٍ

| الشرط | لماذا |
| --- | --- |
| المسؤول حالته `appointed` | مسؤولٌ معزولٌ لا يُقلَّد قضاءً |
| لوكيل المسؤول هويةٌ كانونية نشطة | «من هو القاضي؟» يُجاب من صفٍّ لا من اسم |
| المنصب حالته `active` وفي مؤسسة المحكمة | المنصب مصدرُ السلطة، والمحكمة موضعها |
| مؤسسةُ المنصب فرعُها `judicial` | منصبٌ تنفيذيّ لا يقضي، ولو كان في نفس المؤسسة |
| نطاقُ المنصب يساوي نطاق المحكمة | لا ترقيةَ ضمنية بين النطاقات (R7-D3) |

وسقوطُ أيٍّ منها رفضٌ صريحٌ باستثناءٍ يحمل السبب — لا تقليدٌ «جزئيّ».
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from amos_federation.services.federal_judiciary.jurisdiction import (
    assert_known_jurisdiction,
    assert_scope_covers_court,
)
from amos_federation.services.federal_judiciary.models import (
    COURT_LEVELS,
    COURT_STATUSES,
    CourtJudgeModel,
    CourtModel,
)
from amos_federation.services.national_registry.resolver import (
    resolve_agent_identity,
    resolve_positions,
)
from amos_federation.services.state_registry.models import (
    InstitutionModel,
    OfficialModel,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

_JUDICIAL_BRANCH = "judicial"


class JudiciaryError(RuntimeError):
    """خطأُ نطاقٍ قضائيّ — مدخلٌ غير موجود أو حالةٌ لا تسمح."""


class CourtNotFoundError(JudiciaryError):
    """لا محكمة بهذا الرمز أو المعرّف في هذا المستأجر."""


class InvalidCourtError(JudiciaryError):
    """المحكمة موجودةٌ لكنها لا تصلح لهذا الفعل (معلَّقة أو محلولة)."""


class JudgeAppointmentError(JudiciaryError):
    """تقليدُ القضاء مرفوض — سقطت إحدى حلقات السلسلة."""


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None) -> str:
    return value.isoformat() if value else ""


def court_dict(row: CourtModel) -> dict[str, Any]:
    return {
        "id": row.id,
        "code": row.code,
        "name": row.name,
        "level": row.level,
        "jurisdiction": row.jurisdiction,
        "institution_id": row.institution_id,
        "status": row.status,
        "status_reason": row.status_reason or "",
        "tenant_id": row.tenant_id,
        "created_by": row.created_by,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def judge_dict(row: CourtJudgeModel) -> dict[str, Any]:
    return {
        "id": row.id,
        "court_id": row.court_id,
        "official_id": row.official_id,
        "position_id": row.position_id,
        "identity_id": row.identity_id,
        "title": row.title,
        "status": row.status,
        "appointed_by": row.appointed_by,
        "appointed_at": _iso(row.appointed_at),
        "revoked_at": _iso(row.revoked_at),
        "revocation_reason": row.revocation_reason or "",
        "tenant_id": row.tenant_id,
    }


def load_court(session: Session, court_id: str, *, tenant_id: str) -> CourtModel:
    """اقرأ محكمةً بمعرّفها داخل المستأجر — أو ارفع `CourtNotFoundError`."""
    row = session.get(CourtModel, court_id)
    if row is None or row.tenant_id != tenant_id:
        raise CourtNotFoundError(f"لا محكمة بالمعرّف '{court_id}' في مستأجر '{tenant_id}'")
    return row


def load_court_by_code(session: Session, code: str, *, tenant_id: str) -> CourtModel:
    row = session.execute(
        select(CourtModel).where(CourtModel.code == code, CourtModel.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if row is None:
        raise CourtNotFoundError(f"لا محكمة برمز '{code}' في مستأجر '{tenant_id}'")
    return row


def _load_judicial_institution(
    session: Session, code: str, *, tenant_id: str
) -> InstitutionModel:
    """اقرأ مؤسسةً قائمةً واطلب أن تكون قضائيةً نشطة — ولا تُنشئ مؤسسة."""
    row = session.execute(
        select(InstitutionModel).where(
            InstitutionModel.code == code, InstitutionModel.tenant_id == tenant_id
        )
    ).scalar_one_or_none()
    if row is None:
        raise JudiciaryError(f"لا مؤسسة برمز '{code}' في مستأجر '{tenant_id}'")
    if row.branch != _JUDICIAL_BRANCH:
        raise JudiciaryError(
            f"مؤسسة '{code}' فرعُها '{row.branch}' لا '{_JUDICIAL_BRANCH}' — "
            "فلا تُسجَّل محكمةٌ على مؤسسةٍ غير قضائية"
        )
    if row.status != "active":
        raise JudiciaryError(f"مؤسسة '{code}' حالتها '{row.status}' لا 'active'")
    return row


def create_court(
    session: Session,
    *,
    code: str,
    name: str,
    level: str,
    jurisdiction: str,
    institution_code: str,
    created_by: str,
    tenant_id: str,
) -> CourtModel:
    """سجّل محكمةً على مؤسسةٍ قضائيةٍ قائمة.

    Raises:
        JudiciaryError: مؤسسةٌ غير موجودة أو غير قضائية أو غير نشطة، أو درجةٌ
            غير معروفة، أو رمزٌ مستعمَل في المستأجر.
        JurisdictionError: نطاقٌ خارج المفردة.
    """
    assert_known_jurisdiction(jurisdiction)
    if level not in COURT_LEVELS:
        raise JudiciaryError(f"درجةٌ غير معروفة '{level}' — المسموح: {', '.join(COURT_LEVELS)}")
    institution = _load_judicial_institution(session, institution_code, tenant_id=tenant_id)

    existing = session.execute(
        select(CourtModel).where(CourtModel.code == code, CourtModel.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if existing is not None:
        raise JudiciaryError(f"رمز المحكمة '{code}' مستعمَلٌ في مستأجر '{tenant_id}'")

    row = CourtModel(
        id=f"crt-{uuid.uuid4()}",
        code=code,
        name=name,
        level=level,
        jurisdiction=jurisdiction,
        institution_id=institution.id,
        status="active",
        created_by=created_by,
        tenant_id=tenant_id,
    )
    session.add(row)
    session.flush()
    return row


def set_court_status(
    session: Session, *, court_id: str, status: str, reason: str, tenant_id: str
) -> tuple[CourtModel, str]:
    """غيِّر حالة المحكمة وأعِد (الصفّ، الحالة السابقة). لا حذفَ لمحكمة."""
    if status not in COURT_STATUSES:
        raise JudiciaryError(f"حالةٌ غير معروفة '{status}' — المسموح: {', '.join(COURT_STATUSES)}")
    if not reason.strip():
        raise JudiciaryError("تغييرُ حالة محكمةٍ يلزمه سببٌ مكتوب")
    row = load_court(session, court_id, tenant_id=tenant_id)
    previous = row.status
    row.status = status
    row.status_reason = reason
    session.flush()
    return row, previous


def appoint_judge(
    session: Session,
    *,
    court_id: str,
    official_id: str,
    position_id: str,
    title: str,
    appointed_by: str,
    tenant_id: str,
) -> CourtJudgeModel:
    """قلِّد مسؤولًا قائمًا قضاءً في محكمةٍ قائمة — بالشروط الخمسة.

    Raises:
        CourtNotFoundError · InvalidCourtError · JudgeAppointmentError · JurisdictionError
    """
    court = load_court(session, court_id, tenant_id=tenant_id)
    if court.status != "active":
        raise InvalidCourtError(
            f"المحكمة '{court.code}' حالتها '{court.status}' — لا تقليدَ في محكمةٍ غير نشطة"
        )

    official = session.get(OfficialModel, official_id)
    if official is None or official.tenant_id != tenant_id:
        raise JudgeAppointmentError(
            f"لا مسؤول بالمعرّف '{official_id}' في مستأجر '{tenant_id}'"
        )
    if official.status != "appointed":
        raise JudgeAppointmentError(
            f"المسؤول '{official_id}' حالته '{official.status}' لا 'appointed'"
        )

    identity = resolve_agent_identity(session, official.agent_id)
    if identity is None:
        raise JudgeAppointmentError(
            f"لا هوية كانونية لوكيل المسؤول '{official.agent_id}' — "
            "اربِط الوكيل بهويةٍ قبل تقليده قضاءً"
        )
    if identity.status != "active":
        raise JudgeAppointmentError(f"هوية القاضي حالتها '{identity.status}' لا 'active'")

    holdings = {
        holding.position_id: holding
        for holding in resolve_positions(session, identity.id, tenant_id=tenant_id)
    }
    holding = holdings.get(position_id)
    if holding is None:
        raise JudgeAppointmentError(
            f"المنصب '{position_id}' غير مُقلَّدٍ نشطًا لهذه الهوية — "
            "قلِّد المنصب في السجلّ الوطني أوّلًا"
        )
    if holding.official_id != official_id:
        raise JudgeAppointmentError(
            "تقليدُ المنصب يخصّ مسؤولًا آخر — المنصب والمسؤول يجب أن يتطابقا"
        )
    if holding.institution_branch != _JUDICIAL_BRANCH:
        raise JudgeAppointmentError(
            f"المنصب في فرع '{holding.institution_branch}' لا '{_JUDICIAL_BRANCH}'"
        )
    if holding.institution_id != court.institution_id:
        raise JudgeAppointmentError("المنصب في مؤسسةٍ غير مؤسسة المحكمة")
    assert_scope_covers_court(
        position_scope=holding.authority_scope, court_jurisdiction=court.jurisdiction
    )

    active = session.execute(
        select(CourtJudgeModel).where(
            CourtJudgeModel.court_id == court_id,
            CourtJudgeModel.official_id == official_id,
            CourtJudgeModel.status == "active",
        )
    ).scalar_one_or_none()
    if active is not None:
        raise JudgeAppointmentError(
            f"للمسؤول '{official_id}' تقليدُ قضاءٍ نشطٌ في المحكمة '{court.code}' أصلًا"
        )

    row = CourtJudgeModel(
        id=f"jdg-{uuid.uuid4()}",
        court_id=court.id,
        official_id=official_id,
        position_id=position_id,
        identity_id=identity.id,
        title=title,
        status="active",
        appointed_by=appointed_by,
        tenant_id=tenant_id,
    )
    session.add(row)
    session.flush()
    return row


def set_judge_status(
    session: Session, *, judge_id: str, status: str, reason: str, tenant_id: str
) -> tuple[CourtJudgeModel, str]:
    """علِّق تقليدَ قاضٍ أو اعزله — بأثرٍ مكتوبٍ لا بحذف صفّ.

    وأثرُه الآليّ: `resolve_judicial_authority` لا يجد تقليدًا نشطًا، فيُرفَض كل
    عملٍ قضائيّ لهذا القاضي بعد الآن بلا فحصٍ إضافيّ في أيّ مسار.
    """
    if status not in ("active", "suspended", "revoked"):
        raise JudiciaryError(f"حالةُ تقليدٍ غير معروفة '{status}'")
    if not reason.strip():
        raise JudiciaryError("تغييرُ حالة تقليدٍ قضائيّ يلزمه سببٌ مكتوب")
    row = session.get(CourtJudgeModel, judge_id)
    if row is None or row.tenant_id != tenant_id:
        raise JudiciaryError(f"لا تقليدَ قضاءٍ بالمعرّف '{judge_id}' في مستأجر '{tenant_id}'")
    previous = row.status
    row.status = status
    row.revocation_reason = reason
    row.revoked_at = _now() if status == "revoked" else None
    session.flush()
    return row, previous


def list_courts(
    session: Session,
    *,
    tenant_id: str,
    jurisdiction: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[CourtModel]:
    query = select(CourtModel).where(CourtModel.tenant_id == tenant_id)
    if jurisdiction:
        query = query.where(CourtModel.jurisdiction == jurisdiction)
    if status:
        query = query.where(CourtModel.status == status)
    return list(session.execute(query.order_by(CourtModel.code).limit(limit)).scalars())


def list_judges(
    session: Session, *, court_id: str, tenant_id: str, include_inactive: bool = False
) -> list[CourtJudgeModel]:
    query = select(CourtJudgeModel).where(
        CourtJudgeModel.court_id == court_id, CourtJudgeModel.tenant_id == tenant_id
    )
    if not include_inactive:
        query = query.where(CourtJudgeModel.status == "active")
    return list(session.execute(query.order_by(CourtJudgeModel.appointed_at)).scalars())


__all__ = [
    "CourtNotFoundError",
    "InvalidCourtError",
    "JudgeAppointmentError",
    "JudiciaryError",
    "appoint_judge",
    "court_dict",
    "create_court",
    "judge_dict",
    "list_courts",
    "list_judges",
    "load_court",
    "load_court_by_code",
    "set_court_status",
    "set_judge_status",
]
