"""
AMOS-Federation Government Services — Domain Models
الهدف: الخدمة الحكومية والقضية والقرار، مرتبطة بالسجل والوكلاء والمهامّ بمفاتيح حقيقية
النطاق: services/government_services
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17 (R7-A، الوحدة 2)

## لماذا هذه الجداول الثلاثة معًا

الدولة تُقاس بما تُقدِّمه لا بما تُعلنه. والخدمة الحكومية ثلاثة أشياء لا واحد:
**خدمة** مُعلَنة تُقدِّمها مؤسسة · **قضية** يفتحها طالب فتُنتج عملًا · **قرار**
يصدر من مسؤول مُقلَّد. فُصلت في ثلاثة جداول لأن دورة حياة كل واحد مختلفة، ورُبطت
بمفاتيح أجنبية لأن قضيةً بلا خدمة أو قرارًا بلا مسؤول عبثٌ لا سجلّ.

## الروابط المرجعية — كلها إلى صفوف قائمة

```
state_institutions ◄── state_services ◄── state_cases ──► tasks
state_departments  ◄──┘                        │  ▲
agents             ◄───────────────────────────┘  │  (applicant_agent_id)
state_officials    ◄── state_cases.assigned_official_id
                   ◄── state_decisions.decided_by_official_id
state_cases        ◄── state_decisions.case_id (فريد: قرارٌ نهائي واحد للقضية)
```

`task_id` مفتاح أجنبي إلى `tasks.id` بقصد (R7-E): القضية لا تُنفِّذ نفسها، بل
تُقدِّم مهمّة إلى العمود التنفيذي القائم. ولو كان الحقل نصًّا حرًّا لأمكن أن تدّعي
قضيةٌ أثرًا تنفيذيًّا لا وجود له.

## ما ليس قيدًا في المخطَّط — يُقال لا يُخفى

- **«لا قرار قبل انتهاء المهمّة»** مفروض في طبقة الخدمة، لا في القاعدة: الشرط
  يقرأ حالة صفٍّ في `tasks` وليس تعبيرًا يقبله `CHECK`.
- **«المسؤول من مؤسسة القضية نفسها»** كذلك — يلزمه `CHECK` عبر جدولين، وهو غير
  محمول بين اللهجتين.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from amos_federation.common.database import Base

# === مفردات الحالات — مصدر واحد للقيد وللتحقق في الخدمة ===

SERVICE_STATUSES: tuple[str, ...] = ("active", "suspended", "retired")

#: دورة حياة القضية. `processing` تعني أن مهمّتها في العمود التنفيذي، و`reviewed`
#: تعني أن المهمّة بلغت حالة نهائية — نجاحًا أو فشلًا، والحالة النهائية مخزَّنة.
CASE_STATUSES: tuple[str, ...] = (
    "submitted",
    "assigned",
    "processing",
    "reviewed",
    "decided",
    "closed",
)

DECISION_OUTCOMES: tuple[str, ...] = ("approved", "rejected", "deferred")

CASE_PRIORITIES: tuple[str, ...] = ("low", "normal", "high", "critical")

GOVERNMENT_TABLES: tuple[str, ...] = ("state_services", "state_cases", "state_decisions")


def _now() -> datetime:
    return datetime.now(UTC)


class ServiceModel(Base):
    """خدمة حكومية مُعلَنة — تُقدِّمها مؤسسة، وقد تُسنَد إلى إدارة فيها."""

    __tablename__ = "state_services"

    id = Column(String, primary_key=True)
    code = Column(String, nullable=False)
    name = Column(String, nullable=False)
    institution_id = Column(
        String, ForeignKey("state_institutions.id", ondelete="RESTRICT"), nullable=False
    )
    department_id = Column(
        String, ForeignKey("state_departments.id", ondelete="RESTRICT"), nullable=True
    )
    description = Column(Text, default="")
    status = Column(String, nullable=False, default="active")
    #: مدّة الاستجابة المُعلَنة بالساعات. تُخزَّن ولا يُدَّعى فرضها: لا مُجدول
    #: يراقبها اليوم، والقول إنها «SLA مُطبَّق» سيكون ادّعاءً بلا منفِّذ.
    sla_hours = Column(Integer, nullable=False, default=72)
    tenant_id = Column(String, nullable=False, default="default")
    created_by = Column(String, nullable=False)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    __table_args__ = (
        UniqueConstraint("institution_id", "code", name="uq_state_services_institution_code"),
        CheckConstraint(
            "status IN ('" + "','".join(SERVICE_STATUSES) + "')",
            name="ck_state_services_status",
        ),
        CheckConstraint("sla_hours > 0", name="ck_state_services_sla_positive"),
        Index("ix_state_services_institution", "institution_id", "status"),
    )


class CaseModel(Base):
    """قضية: طلب خدمة صار عملًا له أثر تنفيذي في `tasks`."""

    __tablename__ = "state_cases"

    id = Column(String, primary_key=True)
    reference = Column(String, nullable=False)
    service_id = Column(
        String, ForeignKey("state_services.id", ondelete="RESTRICT"), nullable=False
    )
    #: مُكرَّر عن الخدمة بقصد: الاستعلامات المؤسسية والفهرسة لا تمرّ بجدول وسيط،
    #: والخدمة لا تنتقل بين المؤسسات (لا مسار يُعدِّل `institution_id` لخدمة).
    institution_id = Column(
        String, ForeignKey("state_institutions.id", ondelete="RESTRICT"), nullable=False
    )
    #: الطالب وكيلٌ في `agents` — لا جدول أشخاص موازٍ، ولا نصًّا حرًّا.
    applicant_agent_id = Column(
        String, ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False
    )
    assigned_official_id = Column(
        String, ForeignKey("state_officials.id", ondelete="RESTRICT"), nullable=True
    )
    #: الأثر التنفيذي (R7-E). مفتاح أجنبي لا نصّ، فلا تدّعي قضيةٌ مهمّةً لا وجود لها.
    task_id = Column(String, ForeignKey("tasks.id", ondelete="RESTRICT"), nullable=False)
    subject = Column(String, nullable=False)
    payload = Column(JSON, default=dict)
    status = Column(String, nullable=False, default="submitted")
    #: حالة المهمّة النهائية كما قالها العمود التنفيذي (`completed` أو `failed`…).
    #: تُخزَّن كما هي: القضية لا تُجمِّل نتيجة تنفيذ ولا تُخفي فشلًا.
    review_state = Column(String, nullable=True)
    priority = Column(String, nullable=False, default="normal")
    tenant_id = Column(String, nullable=False, default="default")
    opened_by = Column(String, nullable=False)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    __table_args__ = (
        UniqueConstraint("tenant_id", "reference", name="uq_state_cases_tenant_reference"),
        CheckConstraint(
            "status IN ('" + "','".join(CASE_STATUSES) + "')",
            name="ck_state_cases_status",
        ),
        CheckConstraint(
            "priority IN ('" + "','".join(CASE_PRIORITIES) + "')",
            name="ck_state_cases_priority",
        ),
        Index("ix_state_cases_institution_status", "institution_id", "status"),
        Index("ix_state_cases_service", "service_id", "status"),
    )


class DecisionModel(Base):
    """قرار نهائي في قضية — من مسؤول مُقلَّد، بسبب مكتوب، ولا يُعدَّل."""

    __tablename__ = "state_decisions"

    id = Column(String, primary_key=True)
    #: فريد: للقضية قرارٌ نهائي واحد. تعديل القرار يلزمه مسار «إعادة نظر» مُعلَن
    #: لا كتابةٌ فوق صفّ — ولا وجود لذلك المسار اليوم، فالقيد يمنع الالتباس.
    case_id = Column(
        String, ForeignKey("state_cases.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    decided_by_official_id = Column(
        String, ForeignKey("state_officials.id", ondelete="RESTRICT"), nullable=False
    )
    #: المبدأ الذي نفَّذ النداء فعلًا — يُخزَّن إلى جانب المسؤول لأن ربط الجلسة
    #: بالمنصب غير ممكن اليوم (الجلسة تحمل اسم مستخدم، والمنصب يشير إلى وكيل).
    #: فتسجيل الاثنين يقول الحقيقة بدل أن يُدَّعى أن الفاعل هو صاحب المنصب.
    decided_by_principal = Column(String, nullable=False)
    outcome = Column(String, nullable=False)
    rationale = Column(Text, nullable=False)
    task_final_state = Column(String, nullable=True)
    tenant_id = Column(String, nullable=False, default="default")
    decided_at = Column(DateTime, default=_now)

    __table_args__ = (
        CheckConstraint(
            "outcome IN ('" + "','".join(DECISION_OUTCOMES) + "')",
            name="ck_state_decisions_outcome",
        ),
        CheckConstraint("length(rationale) > 0", name="ck_state_decisions_rationale_present"),
        Index("ix_state_decisions_official", "decided_by_official_id"),
    )


__all__ = [
    "CASE_PRIORITIES",
    "CASE_STATUSES",
    "DECISION_OUTCOMES",
    "GOVERNMENT_TABLES",
    "SERVICE_STATUSES",
    "CaseModel",
    "DecisionModel",
    "ServiceModel",
]
