"""
AMOS-Federation Federal Judiciary — Rulings
الهدف: الحكم قرارٌ مربوطٌ بقضيةٍ وقاضٍ مُثبَت، وحكمٌ واحدٌ لكل مرحلةٍ قضائية
النطاق: services/federal_judiciary
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17 (R7-D10)

## أربعةُ قيودٍ على الحكم، كلٌّ منها مفروض

| القيد | كيف يُفرَض |
| --- | --- |
| لا حكمَ بلا قضية | `case_id` مفتاحٌ أجنبيّ `NOT NULL` إلى `state_legal_cases` |
| لا حكمَ بلا سلطةٍ قضائية | `issue_ruling` تأخذ `JudicialAuthority` مُثبَتةً (`PROVEN`) لا مُنادىً مجهولًا |
| لا حكمين لمرحلةٍ واحدة | فهرسٌ فريدٌ جزئيّ `(case_id, stage)` على `issued`/`enforced` — في القاعدة |
| لا حكمَ يُحذَف | الإلغاء تغييرُ حالةٍ إلى `vacated` بسببٍ مكتوبٍ وطابعٍ زمنيّ |

والقيدُ الثالث مفروضٌ **مرّتين**: قراءةٌ سابقة تُعطي رفضًا مفهومًا
(`DuplicateRulingError`)، والفهرسُ في القاعدة يُغلق الباب حتى لو كُتب صفٌّ من مسارٍ
آخر. فلو حُذف الفحصُ من الكود لَبقي القيد.

## لا منفِّذَ موازٍ في هذا الملفّ

`issue_ruling` تكتب الحكم، وتُقيِّد إجراءً من نوع `RULING`، وتنقل القضية إلى
`decided`. ولا تُقدِّم مهمّةً ولا تُحرِّك مالًا: التنفيذ في `enforcement.py` عبر
`ExecutiveCore` والخزانة القائمين. فالمحكمة تقضي، والتنفيذ لغيرها.

## `PROVEN` شرطٌ لا وصف

`issue_ruling` ترفض تصنيفًا أدنى من `PROVEN`: التخويلُ على مستوى المحكمة
(`PARTIAL`) يكفي للقراءة ولا يكفي لإصدار حكمٍ في قضيةٍ بعينها. فالتصنيف مدخلٌ في
القرار لا حَشوًا في السجلّ.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from amos_federation.services.federal_judiciary.docket import (
    advance_case,
    load_case,
    record_proceeding,
)
from amos_federation.services.federal_judiciary.models import (
    RULING_DECISIONS,
    RULING_STAGES,
    RulingModel,
)
from amos_federation.services.federal_judiciary.registry import JudiciaryError

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from amos_federation.services.federal_judiciary.authority import JudicialAuthority

#: الحالاتُ التي يبقى فيها الحكمُ قائمًا ويحجز مرحلتَه القضائية.
ACTIVE_RULING_STATUSES: tuple[str, ...] = ("issued", "enforced")


class RulingError(JudiciaryError):
    """إصدارُ حكمٍ مرفوض — مدخلٌ غير صالحٍ أو حالةٌ لا تسمح."""


class DuplicateRulingError(RulingError):
    """للقضية حكمٌ قائمٌ في هذه المرحلة القضائية — لا حكمَ ثانٍ."""


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None) -> str:
    return value.isoformat() if value else ""


def ruling_dict(row: RulingModel) -> dict[str, Any]:
    return {
        "id": row.id,
        "case_id": row.case_id,
        "court_id": row.court_id,
        "judge_id": row.judge_id,
        "judge_identity_id": row.judge_identity_id,
        "stage": row.stage,
        "decision": row.decision,
        "disposition": row.disposition,
        "status": row.status,
        "provenance_class": row.provenance_class,
        "authority": row.authority or {},
        "issued_by_principal": row.issued_by_principal,
        "issued_at": _iso(row.issued_at),
        "vacated_at": _iso(row.vacated_at),
        "vacatur_reason": row.vacatur_reason or "",
        "tenant_id": row.tenant_id,
    }


def load_ruling(session: Session, ruling_id: str, *, tenant_id: str) -> RulingModel:
    row = session.get(RulingModel, ruling_id)
    if row is None or row.tenant_id != tenant_id:
        raise RulingError(f"لا حكم بالمعرّف '{ruling_id}' في مستأجر '{tenant_id}'")
    return row


def active_ruling_for_stage(session: Session, *, case_id: str, stage: str) -> RulingModel | None:
    """اقرأ الحكم القائم لمرحلةٍ قضائية إن وُجد — القراءةُ التي تسبق الفهرس."""
    return session.execute(
        select(RulingModel).where(
            RulingModel.case_id == case_id,
            RulingModel.stage == stage,
            RulingModel.status.in_(ACTIVE_RULING_STATUSES),
        )
    ).scalar_one_or_none()


def issue_ruling(
    session: Session,
    *,
    authority: JudicialAuthority,
    decision: str,
    disposition: str,
    tenant_id: str,
    stage: str = "FIRST_INSTANCE",
) -> tuple[RulingModel, Any]:
    """أصدِر حكمًا بسلطةٍ قضائية مُثبَتة، وقيِّد إجراءه، وانقل القضية إلى `decided`.

    Args:
        authority: قرارُ حلّ السلطة القضائية — يلزم `allowed` وتصنيف `PROVEN`.
        decision: من `RULING_DECISIONS`.
        disposition: منطوقُ الحكم — نصٌّ غير فارغ.
        stage: المرحلة القضائية — حكمٌ واحدٌ قائمٌ لكلٍّ منها.

    Returns:
        `(صفُّ الحكم، صفُّ الإجراء المُقيَّد)`.

    Raises:
        RulingError: سلطةٌ غير مُثبَتة، أو مدخلٌ غير صالح.
        DuplicateRulingError: للقضية حكمٌ قائمٌ في هذه المرحلة.
        CaseTransitionError: حالةُ القضية لا تسمح بالانتقال إلى `decided`.
    """
    if not authority.allowed or authority.classification != "PROVEN":
        raise RulingError(
            "إصدارُ الحكم يلزمه سلطةٌ قضائية مُثبَتةٌ بتصنيف PROVEN — "
            f"الحاصل: allowed={authority.allowed} classification={authority.classification}"
        )
    if authority.case_id is None or authority.judge_id is None or authority.court_id is None:
        raise RulingError("قرارُ السلطة ناقصٌ: يلزمه قضيةٌ وقاضٍ ومحكمة")
    if stage not in RULING_STAGES:
        raise RulingError(f"مرحلةٌ غير معروفة '{stage}' — المسموح: {', '.join(RULING_STAGES)}")
    if decision not in RULING_DECISIONS:
        raise RulingError(f"قرارٌ غير معروف '{decision}' — المسموح: {', '.join(RULING_DECISIONS)}")
    if not disposition.strip():
        raise RulingError("منطوقُ الحكم لا يكون فارغًا")

    case = load_case(session, authority.case_id, tenant_id=tenant_id)
    existing = active_ruling_for_stage(session, case_id=case.id, stage=stage)
    if existing is not None:
        raise DuplicateRulingError(
            f"القضية '{case.reference}' لها حكمٌ قائم '{existing.id}' في المرحلة '{stage}' — "
            "لا حكمَ ثانٍ لنفس المرحلة القضائية"
        )

    row = RulingModel(
        id=f"rul-{uuid.uuid4()}",
        case_id=case.id,
        court_id=authority.court_id,
        judge_id=authority.judge_id,
        judge_identity_id=authority.identity_id,
        stage=stage,
        decision=decision,
        disposition=disposition,
        status="issued",
        provenance_class=authority.classification,
        authority=authority.as_dict(),
        issued_by_principal=authority.principal_id,
        tenant_id=tenant_id,
    )
    session.add(row)
    session.flush()

    proceeding = record_proceeding(
        session,
        case_id=case.id,
        proceeding_type="RULING",
        actor_principal=authority.principal_id,
        actor_identity_id=authority.identity_id or "",
        summary=f"حكمٌ في المرحلة '{stage}': {decision}",
        tenant_id=tenant_id,
        record={"ruling_id": row.id, "stage": stage, "decision": decision},
    )
    if case.status != "decided":
        advance_case(session, case_id=case.id, target="decided", tenant_id=tenant_id)
    return row, proceeding


def vacate_ruling(
    session: Session, *, ruling_id: str, reason: str, tenant_id: str
) -> tuple[RulingModel, str]:
    """ألغِ حكمًا بسببٍ مكتوب — تغييرُ حالةٍ لا حذفُ صفّ.

    والحكمُ المُنفَّذ (`enforced`) لا يُلغى في هذه الوحدة: إلغاءُ أثرٍ تنفيذيّ جرى
    يحتاج عكسَ حركةٍ أو إبطالَ مهمّة، وذاك مسارٌ **غير مبنيّ** ويُقال ولا يُموَّه.
    """
    if not reason.strip():
        raise RulingError("إلغاءُ حكمٍ يلزمه سببٌ مكتوب")
    row = load_ruling(session, ruling_id, tenant_id=tenant_id)
    if row.status == "vacated":
        raise RulingError(f"الحكم '{ruling_id}' مُلغىً أصلًا")
    if row.status == "enforced":
        raise RulingError(f"الحكم '{ruling_id}' نُفِّذ — عكسُ أثرٍ تنفيذيّ ليس مبنيًّا في هذه الوحدة")
    previous = row.status
    row.status = "vacated"
    row.vacated_at = _now()
    row.vacatur_reason = reason
    session.flush()
    return row, previous


def mark_ruling_enforced(session: Session, *, ruling_id: str, tenant_id: str) -> RulingModel:
    """علِّم الحكم منفَّذًا — تُناديه `enforcement.py` بعد أثرٍ حقيقيّ فقط."""
    row = load_ruling(session, ruling_id, tenant_id=tenant_id)
    if row.status != "issued":
        raise RulingError(f"الحكم حالته '{row.status}' — لا يُعلَّم منفَّذًا")
    row.status = "enforced"
    session.flush()
    return row


def list_rulings(session: Session, *, case_id: str, tenant_id: str) -> list[RulingModel]:
    return list(
        session.execute(
            select(RulingModel)
            .where(RulingModel.case_id == case_id, RulingModel.tenant_id == tenant_id)
            .order_by(RulingModel.issued_at)
        ).scalars()
    )


__all__ = [
    "ACTIVE_RULING_STATUSES",
    "DuplicateRulingError",
    "RulingError",
    "active_ruling_for_stage",
    "issue_ruling",
    "list_rulings",
    "load_ruling",
    "mark_ruling_enforced",
    "ruling_dict",
    "vacate_ruling",
]
