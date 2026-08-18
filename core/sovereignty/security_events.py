"""الهدف: تسجيل الأحداث الأمنية السيادية في سجل غير قابل للعبث عند كل ادّعاء ملكي فاشل.

المالك: core/sovereignty/ — التاج
تاريخ الإنشاء: 2026-08-16
تاريخ آخر تعديل: 2026-08-16

المبدأ الذي تخدمه هذه الوحدة: **الرفض ليس صمتًا.** حين يُقدَّم أمر باسم الملك بلا
مفتاحه، فالمهم ليس أن يُرفَض فقط، بل أن يبقى أثر المحاولة — لأن المحاولة نفسها
خبرٌ أمني: إما خلل في مُنادٍ، وإما محاولة انتحال.

وتمييز لازم لا يُخلط: هذا السجل **يشهد ولا يحكم**. التسجيل ليس نقضًا (المادة
العاشرة · 7 · 3)، ولا يوجد في هذه الوحدة مسار واحد يمنع تنفيذ قرار سيادي ثابت.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from core.constitutional_engine.ledger import ConstitutionalLedger

_LOG = logging.getLogger("amos.sovereignty.security")


class SecurityEventSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    NOTICE = "NOTICE"


class SecurityEventKind(str, Enum):
    """أنواع الأحداث الأمنية السيادية.

    الأربعة الأولى ادّعاءات ملكية فاشلة. والخامس أثر تدخّل سيادي ناجح — يُسجَّل
    لأن التدخّل الشرعي يجب أن يكون **مرئيًّا** لا خفيًّا. والسادس محاولة طرف تابع
    أن يُنشئ نقضًا على التاج. والأخير استعمالُ صلاحيةٍ سحبَها الملكُ بمرسوم
    (المادة العاشرة · 10 · 1): ليس مخالفةً لقاعدةٍ بل تصرُّفًا بلا اختصاص.
    """

    ROYAL_COMMAND_UNSIGNED = "ROYAL_COMMAND_UNSIGNED"
    ROYAL_SIGNATURE_INVALID = "ROYAL_SIGNATURE_INVALID"
    DECREE_ACTION_MISMATCH = "DECREE_ACTION_MISMATCH"
    DECREE_TYPE_INVALID = "DECREE_TYPE_INVALID"
    DECREE_PRESENTED_BY_NON_ROYAL = "DECREE_PRESENTED_BY_NON_ROYAL"
    CROWN_UNPROVISIONED = "CROWN_UNPROVISIONED"
    SOVEREIGN_INTERVENTION = "SOVEREIGN_INTERVENTION"
    SOVEREIGNTY_ALTERING_DECREE = "SOVEREIGNTY_ALTERING_DECREE"
    SUBORDINATE_VETO_ATTEMPT = "SUBORDINATE_VETO_ATTEMPT"
    WITHDRAWN_AUTHORITY_USE = "WITHDRAWN_AUTHORITY_USE"
    EXECUTION_CONTRACT_BREACH = "EXECUTION_CONTRACT_BREACH"

    @property
    def severity(self) -> SecurityEventSeverity:
        return _SEVERITY[self]

    @property
    def is_rejection(self) -> bool:
        """هل هذا الحدث ناتج عن رفض؟ (التدخّل السيادي الناجح ليس رفضًا)"""
        return self not in {
            SecurityEventKind.SOVEREIGN_INTERVENTION,
            SecurityEventKind.SOVEREIGNTY_ALTERING_DECREE,
        }


_SEVERITY: dict[SecurityEventKind, SecurityEventSeverity] = {
    SecurityEventKind.ROYAL_COMMAND_UNSIGNED: SecurityEventSeverity.CRITICAL,
    SecurityEventKind.ROYAL_SIGNATURE_INVALID: SecurityEventSeverity.CRITICAL,
    SecurityEventKind.DECREE_ACTION_MISMATCH: SecurityEventSeverity.CRITICAL,
    SecurityEventKind.DECREE_TYPE_INVALID: SecurityEventSeverity.CRITICAL,
    SecurityEventKind.DECREE_PRESENTED_BY_NON_ROYAL: SecurityEventSeverity.CRITICAL,
    SecurityEventKind.CROWN_UNPROVISIONED: SecurityEventSeverity.HIGH,
    SecurityEventKind.SOVEREIGN_INTERVENTION: SecurityEventSeverity.NOTICE,
    SecurityEventKind.SOVEREIGNTY_ALTERING_DECREE: SecurityEventSeverity.CRITICAL,
    SecurityEventKind.SUBORDINATE_VETO_ATTEMPT: SecurityEventSeverity.HIGH,
    SecurityEventKind.WITHDRAWN_AUTHORITY_USE: SecurityEventSeverity.HIGH,
    # مُنفِّذٌ حاول أثرًا لم يأذن به العقدُ الذي نُفِّذ تحته — أي أنّ الإذنَ
    # صدر لفعلٍ وأُريدَ به غيرُه. خطرٌ بقدرِ انتحالِ الصفة: في الأوّلِ مُدّعٍ
    # لا يملك الإذن، وفي هذا مأذونٌ تجاوز حدَّ إذنِه — والثاني أخفى أثرًا.
    SecurityEventKind.EXECUTION_CONTRACT_BREACH: SecurityEventSeverity.CRITICAL,
}


@dataclass(frozen=True, slots=True)
class SecurityEvent:
    """حدث أمني واحد — مُسجَّل في السجل الدستوري بسلسلة تجزئته."""

    kind: SecurityEventKind
    severity: SecurityEventSeverity
    actor: str
    action: str
    target: str
    reason: str
    recorded_at: str
    decree_id: str | None = None
    ledger_entry_hash: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "severity": self.severity.value,
            "actor": self.actor,
            "action": self.action,
            "target": self.target,
            "reason": self.reason,
            "recorded_at": self.recorded_at,
            "decree_id": self.decree_id,
            "ledger_entry_hash": self.ledger_entry_hash,
        }


class SecurityEventLog:
    """سجل الأحداث الأمنية — يكتب في السجل الدستوري نفسه (سلسلة تجزئة واحدة).

    وحدة السجل مقصودة: حدثٌ أمني في ملف منفصل يُحذَف وحده. وفي السلسلة الواحدة
    يكشف حذفه تحقّقُ السلسلة.
    """

    def __init__(self, ledger: ConstitutionalLedger | None = None) -> None:
        self._ledger = ledger if ledger is not None else ConstitutionalLedger()
        self._events: list[SecurityEvent] = []

    @property
    def events(self) -> tuple[SecurityEvent, ...]:
        return tuple(self._events)

    def rejections(self) -> tuple[SecurityEvent, ...]:
        return tuple(e for e in self._events if e.kind.is_rejection)

    def record(
        self,
        kind: SecurityEventKind | str,
        *,
        actor: str,
        action: str,
        reason: str,
        target: str = "",
        decree_id: str | None = None,
    ) -> SecurityEvent:
        """سجّل حدثًا أمنيًّا. يرفع عند نوع غير معروف — لا يُبتلع نوع مجهول."""
        resolved = SecurityEventKind(kind) if isinstance(kind, str) else kind
        event = SecurityEvent(
            kind=resolved,
            severity=resolved.severity,
            actor=actor,
            action=action,
            target=target,
            reason=reason,
            recorded_at=datetime.now(timezone.utc).isoformat(),
            decree_id=decree_id,
        )
        entry = self._ledger.append({"type": "SECURITY_EVENT", **event.as_dict()})
        event = SecurityEvent(**{**event.as_dict(), "kind": resolved,
                                "severity": resolved.severity,
                                "ledger_entry_hash": entry.entry_hash})
        self._events.append(event)
        log = _LOG.critical if resolved.severity is SecurityEventSeverity.CRITICAL else _LOG.warning
        log("حدث أمني سيادي [%s] الفاعل «%s» الفعل «%s»: %s",
            resolved.value, actor, action, reason)
        return event


__all__ = [
    "SecurityEvent",
    "SecurityEventKind",
    "SecurityEventLog",
    "SecurityEventSeverity",
]
