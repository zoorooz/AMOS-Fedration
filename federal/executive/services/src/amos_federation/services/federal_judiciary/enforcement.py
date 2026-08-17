"""
AMOS-Federation Federal Judiciary — Ruling Enforcement Records
الهدف: أثرُ التنفيذ يُكتب بعد تنفيذٍ حقيقيّ في العمود التنفيذي أو الخزانة، لا قبله
النطاق: services/federal_judiciary
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17 (R7-D11/D12)

## المحكمة لا تنفِّذ

هذا الملفّ **لا يُقدِّم مهمّةً ولا يُحرِّك مالًا**. لا يستورد `ExecutiveCore` ولا
`StateTreasury`، ويحرس ذلك اختبارٌ ساكن. وظيفتُه كتابةُ **أثرِ** ما نفَّذه غيرُه:

    الحكم → سلطةٌ قضائية مُثبَتة → FederalJudiciary.enforce_ruling_via_task
          → ExecutiveCore.submit + run  (العمود التنفيذي، R2/R5)
          → `state_ruling_enforcements.task_id` مفتاحٌ أجنبيّ إلى `tasks`

    الحكم → سلطةٌ قضائية مُثبَتة → FederalJudiciary.enforce_ruling_via_treasury
          → StateTreasury.disburse  (بتخويل الخزانة القائم كما هو، R7-B/R7-C)
          → `state_ruling_enforcements.transaction_reference`

ولا `CourtExecutor` ولا مُنفِّذٌ ثالث: الترتيبُ في `service.py` هو نفسُه ترتيبُ
`StateTreasury.execute_decision_disbursement` القائم — تُقدَّم المهمّة وتُشغَّل،
**ولا يُكتب أثرُ تنفيذٍ إلّا إذا بلغت حالةً نهائيةً مقروءة**.

## الحكم سببٌ لا سلطةٌ مالية (R7-D12)

الصرفُ تنفيذًا لحكمٍ يمرّ في `StateTreasury.disburse` كما هي: صلاحيةُ الصرف،
ومِنحةُ السلطة على الموازنة بعينها، وسجلُّ سلطة الحركة. فإن لم يملك مُنادي التنفيذ
سلطةً مالية رُفض الصرف — **والحكمُ لا يمنحها ولا يُسقِط الفحص**. فالحكم يُجيب «لِمَ
يُصرَف؟» ولا يُجيب «مَن يملك الصرف؟».

## ما لا يُدَّعى

`status='executed'` تعني أن مهمّةً بلغت `completed` أو أن حركةً كُتبت في الخزانة.
ولا تعني نفاذًا قانونيًّا خارج النظام، ولا إلزامًا لجهةٍ خارجية، ولا استيفاءً
فعليًّا. وهذا مكتوبٌ في `docs/audit/R7D_FEDERAL_JUDICIARY.md` تحت `UNAVAILABLE`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from amos_federation.services.federal_judiciary.models import (
    ENFORCEMENT_KINDS,
    RulingEnforcementModel,
)
from amos_federation.services.federal_judiciary.registry import JudiciaryError
from amos_federation.services.federal_judiciary.rulings import load_ruling

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class EnforcementError(JudiciaryError):
    """إحالةُ حكمٍ للتنفيذ مرفوضة — حالةُ الحكم أو مدخلُ الأثر لا يصلح."""


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None) -> str:
    return value.isoformat() if value else ""


def enforcement_dict(row: RulingEnforcementModel) -> dict[str, Any]:
    return {
        "id": row.id,
        "ruling_id": row.ruling_id,
        "case_id": row.case_id,
        "kind": row.kind,
        "task_id": row.task_id,
        "transaction_reference": row.transaction_reference,
        "status": row.status,
        "detail": row.detail or "",
        "requested_by_principal": row.requested_by_principal,
        "requested_by_identity_id": row.requested_by_identity_id,
        "requested_at": _iso(row.requested_at),
        "completed_at": _iso(row.completed_at),
        "tenant_id": row.tenant_id,
    }


def assert_enforceable(session: Session, *, ruling_id: str, tenant_id: str) -> Any:
    """اقرأ حكمًا صالحًا للإحالة — `issued` وحدها، لا مُلغىً ولا مُنفَّذًا مرّتين."""
    ruling = load_ruling(session, ruling_id, tenant_id=tenant_id)
    if ruling.status == "vacated":
        raise EnforcementError(f"الحكم '{ruling_id}' مُلغى — لا يُنفَّذ")
    if ruling.status == "enforced":
        raise EnforcementError(f"الحكم '{ruling_id}' نُفِّذ أصلًا — لا تنفيذَ مزدوج")
    return ruling


def record_enforcement(
    session: Session,
    *,
    ruling_id: str,
    case_id: str,
    kind: str,
    status: str,
    requested_by_principal: str,
    requested_by_identity_id: str,
    tenant_id: str,
    task_id: str | None = None,
    transaction_reference: str | None = None,
    detail: str = "",
) -> RulingEnforcementModel:
    """اكتب أثرَ تنفيذٍ جرى — أو أثرَ محاولةٍ فشلت، بلا تجميل.

    Raises:
        EnforcementError: نوعٌ غير معروف، أو نجاحٌ مُدَّعىً بلا هدفٍ حقيقيّ
            (`TASK` بلا `task_id`، أو `TREASURY` بلا مرجع حركة).
    """
    if kind not in ENFORCEMENT_KINDS:
        raise EnforcementError(
            f"نوعُ تنفيذٍ غير معروف '{kind}' — المسموح: {', '.join(ENFORCEMENT_KINDS)}"
        )
    if status not in ("requested", "executed", "failed"):
        raise EnforcementError(f"حالةُ تنفيذٍ غير معروفة '{status}'")
    if status == "executed":
        if kind == "TASK" and not task_id:
            raise EnforcementError("تنفيذٌ بمهمّةٍ بلا `task_id` — لا يُدَّعى تنفيذٌ لا صفَّ له")
        if kind == "TREASURY" and not transaction_reference:
            raise EnforcementError("تنفيذٌ بالخزانة بلا مرجع حركة — لا يُدَّعى صرفٌ لا أثرَ له")

    row = RulingEnforcementModel(
        id=f"enf-{uuid.uuid4()}",
        ruling_id=ruling_id,
        case_id=case_id,
        kind=kind,
        task_id=task_id,
        transaction_reference=transaction_reference,
        status=status,
        detail=detail,
        requested_by_principal=requested_by_principal,
        requested_by_identity_id=requested_by_identity_id,
        completed_at=_now() if status in ("executed", "failed") else None,
        tenant_id=tenant_id,
    )
    session.add(row)
    session.flush()
    return row


def list_enforcements(
    session: Session, *, ruling_id: str, tenant_id: str
) -> list[RulingEnforcementModel]:
    return list(
        session.execute(
            select(RulingEnforcementModel)
            .where(
                RulingEnforcementModel.ruling_id == ruling_id,
                RulingEnforcementModel.tenant_id == tenant_id,
            )
            .order_by(RulingEnforcementModel.requested_at)
        ).scalars()
    )


__all__ = [
    "EnforcementError",
    "assert_enforceable",
    "enforcement_dict",
    "list_enforcements",
    "record_enforcement",
]
