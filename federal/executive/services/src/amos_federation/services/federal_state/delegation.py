"""
AMOS-Federation Federal/State Integration — Explicit Delegation
الهدف: التفويضُ الوحيدُ الذي يجتاز حدَّ الحكومة — صريحٌ مُنطَّقٌ مؤقَّتٌ قابلٌ للنقض
النطاق: services/federal_state
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17 (R8-H)

## الفرق بين العلاقة والتفويض

`state_government_relations` تقول «هذه الولايةُ تنتمي إلى الفدرالية» و**لا تمنح
شيئًا**. و`state_government_delegations` تقول «الحكومةُ (س) تُفوِّض الحكومةَ (ع)
عمليةَ `treasury.disbursement.post` بنطاق `INSTITUTION` بحدٍّ (ك) حتى تاريخِ (ت)»
— وهي وحدُها ما يقرأه `authority.py` ليجتاز حدَّ الحكومة.

## أربعةُ شروطٍ يُفحَص كلٌّ منها في القراءة لا في الكتابة وحدها

1. **صريح**: صفٌّ بمُفوِّضٍ وهدفٍ وعمليةٍ مُسمَّياتٍ بمفاتيحَ أجنبية.
2. **مُنطَّق**: `scope` و`max_amount` — والقراءةُ ترفض ما تجاوز الحدَّ.
3. **مؤقَّت**: `expires_at` — والمنتهي **لا يُقبل** ولو بقيت حالتُه `active`، فلا
   نعتمد على مُهمَلٍ دوريّ ليصدُق الفحص.
4. **قابلٌ للنقض**: `revoke` تكتب `revoked` وطابعًا وسببًا — ولا تحذف صفًّا.

## ما لا يفعله هذا الملفّ

لا يمنح تفويضٌ سلطةً لمن لا سلطةَ له أصلًا. التفويضُ يُقرأ **بعد** أن يُثبت
المحرّكُ الكانونيّ أن المبدأ يشغل منصبًا بصلاحيةِ العملية؛ فأثرُه الوحيد أن
يُجيز عبورَ حدِّ الحكومة. ومن لا منصبَ له يُرفض ولو كانت الولاياتُ كلُّها
مُفوَّضة — وذلك محروسٌ باختبار.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

from sqlalchemy import select

from amos_federation.services.federal_state.models import (
    DELEGABLE_OPERATIONS,
    SCOPE_LEVELS,
    GovernmentDelegationModel,
)

_logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class DelegationError(ValueError):
    """طلبُ تفويضٍ غير صالحٍ بنيويًّا — لا رفضَ تخويل."""


def _now() -> datetime:
    return datetime.now(UTC)


def _as_aware(value: datetime | None) -> datetime | None:
    """SQLite تُعيد طوابعَ بلا منطقةٍ زمنية؛ فالمقارنةُ تلزمها توحيدٌ صريح."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def new_delegation_id() -> str:
    return f"dlg-{uuid.uuid4().hex[:12]}"


def validate_delegation_request(
    *,
    operation: str,
    scope: str,
    to_government_id: str | None,
    to_institution_id: str | None,
    from_government_id: str,
) -> None:
    """افحص طلبَ التفويض قبل أيّ كتابة — نفسُ ما تفرضه القاعدة، برسائلَ مفهومة.

    القيدُ في القاعدة هو الحدُّ الأخير، وهذا الفحصُ خدمةٌ للمستدعي لا بديلٌ عنه:
    كلُّ ما يُفحص هنا مفروضٌ هناك أيضًا (`ck_state_government_delegations_*`).
    """
    if operation not in DELEGABLE_OPERATIONS:
        raise DelegationError(f"عمليةٌ غيرُ قابلةٍ للتفويض: {operation}")
    if scope not in SCOPE_LEVELS:
        raise DelegationError(f"نطاقٌ مجهول: {scope}")
    if bool(to_government_id) == bool(to_institution_id):
        raise DelegationError("التفويضُ يلزمه هدفٌ واحدٌ بعينه: حكومةٌ أو مؤسسة، لا الاثنان ولا لا شيء")
    if to_government_id and to_government_id == from_government_id:
        raise DelegationError("لا تفويضَ لحكومةٍ من نفسها")


def _within_amount(delegation: GovernmentDelegationModel, amount: Decimal | None) -> bool:
    if delegation.max_amount is None or amount is None:
        return delegation.max_amount is None
    try:
        return amount <= Decimal(str(delegation.max_amount))
    except (InvalidOperation, ValueError) as exc:
        _logger.warning(
            "سقفُ تفويضٍ غيرُ رقميّ delegation_id=%s — %s الرفضُ هو الافتراض",
            getattr(delegation, "id", None),
            exc,
        )
        return False


def find_active_delegation(
    session: Session,
    *,
    from_government_id: str,
    to_government_id: str | None = None,
    to_institution_id: str | None = None,
    operation: str,
    scope: str | None = None,
    amount: Decimal | None = None,
    tenant_id: str,
    now: datetime | None = None,
) -> GovernmentDelegationModel | None:
    """اقرأ تفويضًا نشطًا يُجيز هذه العمليةَ بعينها، أو `None`.

    الترشيحُ في القاعدة على المفاتيح والحالة، والفحصُ الدقيق (الانتهاء والنطاق
    والحدّ المالي) في بايثون لأنه يخلط أنواعًا؛ والنتيجةُ واحدةٌ: **لا شيء يُقبل
    إلا بموجب صفٍّ حاضرٍ نشطٍ غير منتهٍ يشمل النطاقَ والمبلغ**.
    """
    moment = now or _now()
    conditions = [
        GovernmentDelegationModel.tenant_id == tenant_id,
        GovernmentDelegationModel.from_government_id == from_government_id,
        GovernmentDelegationModel.operation == operation,
        GovernmentDelegationModel.status == "active",
    ]
    if to_government_id:
        conditions.append(GovernmentDelegationModel.to_government_id == to_government_id)
    if to_institution_id:
        conditions.append(GovernmentDelegationModel.to_institution_id == to_institution_id)
    candidates = session.scalars(select(GovernmentDelegationModel).where(*conditions)).all()
    for delegation in candidates:
        expires_at = _as_aware(delegation.expires_at)
        if expires_at is not None and expires_at <= moment:
            continue
        if scope is not None and delegation.scope != scope:
            continue
        if not _within_amount(delegation, amount):
            continue
        return delegation
    return None


__all__ = [
    "DelegationError",
    "find_active_delegation",
    "new_delegation_id",
    "validate_delegation_request",
]
