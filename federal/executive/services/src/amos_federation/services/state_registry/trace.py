"""
AMOS-Federation State Domains — Audit + Event Trace
الهدف: أثرٌ واحد لكل كتابة في نطاقات الدولة: تدقيق ثم حدث دائم، بهذا الترتيب
النطاق: services/state_registry
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17 (R7-A، الوحدة 2)

## لماذا ملفّ مستقلّ

الوحدة 1 كتبت هذا الترتيب داخل `StateRegistry._record`. ولمّا جاءت الوحدة 2
(الخدمات والقضايا والقرارات) كان أمامنا نسخُه أو استخراجُه. النسخ يعني ترتيبين
يتباعدان مع الوقت، وهو بذرة الخلل الذي دفعناه في R6 مع مفردتي الأدوار. فاستُخرج
هنا: **دالّة واحدة يستعملها كل نطاق دولة**، بلا مخزن جديد ولا ناقل جديد — تُنادي
`PersistentAuditStore` و`get_durable_event_bus()` القائمين (R7-G).

## الترتيب مقصود

    PersistentAuditStore.append  →  DurableEventBus.publish

سلسلة التدقيق هي السجلّ الذي لا يُعدَّل، والحدث إعلانٌ عنها يحمل `audit_id`. ولو
نُشر الحدث أولًا لأمكن أن يوجد إعلانٌ عن أثرٍ لا سجلّ له.

## ما يحمله كل حدث (R7-G)

الكيان (معرّفه في الحمولة) · الفاعل (`actor`) · دور الفاعل وجلسته ·
`audit_id` · و`task_id` حيث توجد مهمّة. و`correlation_id` و`timestamp` عمودان في
`EventRecord` يضيفهما الناقل، فلا يُعادان في الحمولة.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from amos_federation.common.durable_event_bus import get_durable_event_bus
from amos_federation.common.persistent import PersistentAuditStore

if TYPE_CHECKING:
    from amos_federation.common.principal import AuthorizationContext

_AUDIT = PersistentAuditStore()


def record_domain_trace(
    context: AuthorizationContext,
    action: str,
    subject: str,
    entity: dict[str, Any],
) -> dict[str, Any]:
    """اكتب أثرًا مُدقَّقًا لعملية نطاق ثم أعلنه حدثًا دائمًا.

    Args:
        context: سياق التخويل — منه الفاعل ودوره وجلسته وارتباطه.
        action: اسم الفعل في سلسلة التدقيق (`registry.official.appoint`…).
        subject: موضوع الحدث الدائم — يجب أن يكون له عقد في `EVENT_CONTRACTS`.
        entity: حمولة الكيان (معرّفاته وما يلزم لتتبّعه).

    Returns:
        `{"audit_id": ..., "event_id": ...}` — معرّفان حقيقيان من المخزنين، لا
        قيمتان مُصطنعتان. من ينادي يُرجعهما للمستدعي فيصير الأثر قابلًا للفحص.
    """
    audit = _AUDIT.append(action, context.principal_id, {**entity, "role": context.role})
    payload = {
        **entity,
        "actor": context.principal_id,
        "actor_role": context.role,
        "session_id": context.session_id,
        "audit_id": audit["audit_id"],
    }
    event = get_durable_event_bus().publish(subject, payload, correlation_id=context.correlation_id)
    return {"audit_id": audit["audit_id"], "event_id": event["event_id"]}


__all__ = ["record_domain_trace"]
