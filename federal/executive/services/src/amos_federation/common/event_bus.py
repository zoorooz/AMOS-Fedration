"""
AMOS-Federation Event Bus
الهدف: نظام أحداث حقيقي مع تخزين دائم واشتراكات
النطاق: common/event_bus
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-15
"""

import contextlib
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Column, DateTime, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from amos_federation.common.database import get_database_url


class EventBase(DeclarativeBase):
    pass


class EventModel(EventBase):
    """جدول الأحداث المنشورة."""

    __tablename__ = "event_store"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String, nullable=False, unique=True)
    subject = Column(String, nullable=False, index=True)
    data = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


class EventBus:
    """ناقل أحداث حقيقي مع تخزين دائم واشتراكات."""

    def __init__(self) -> None:
        url = get_database_url()
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        if url.startswith("postgresql"):
            connect_args = {"sslmode": "require", "connect_timeout": 15}
        self._engine = create_engine(
            url, connect_args=connect_args, pool_pre_ping=True, pool_size=5, max_overflow=10
        )
        EventBase.metadata.create_all(self._engine)
        self._Session = sessionmaker(bind=self._engine, autoflush=False, expire_on_commit=False)
        self._handlers: dict[str, list[Callable[[dict[str, Any]], None]]] = {}

    def subscribe(self, subject: str, handler: Callable[[dict[str, Any]], None]) -> None:
        """اشتراك معالج لـ subject معين."""
        if subject not in self._handlers:
            self._handlers[subject] = []
        self._handlers[subject].append(handler)

    def publish(self, subject: str, data: dict[str, Any]) -> dict[str, Any]:
        """نشر حدث وتخزينه واستدعاء المعالجات."""
        event_id = f"evt-{uuid.uuid4()}"
        event = {
            "event_id": event_id,
            "subject": subject,
            "data": data,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        # تخزين دائم
        session = self._Session()
        try:
            row = EventModel(
                event_id=event_id,
                subject=subject,
                data=json.dumps(data, ensure_ascii=False),
            )
            session.add(row)
            session.commit()
        finally:
            session.close()

        # استدعاء المعالجات المسجّلة
        handlers = self._handlers.get(subject, [])
        # أيضًا فحص wildcards (amos_federation.*)
        for pattern, pattern_handlers in self._handlers.items():
            if pattern.endswith(".*"):
                prefix = pattern[:-2]
                if subject.startswith(prefix + "."):
                    handlers = handlers + pattern_handlers

        for handler in handlers:
            with contextlib.suppress(Exception):
                handler(data)  # لا نوقف النشر بسبب فشل معالج

        return event

    def get_events(self, subject: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """استرجاع الأحداث المخزَّنة."""
        session = self._Session()
        try:
            q = session.query(EventModel)
            if subject:
                q = q.filter(EventModel.subject == subject)
            rows = q.order_by(EventModel.id.desc()).limit(limit).all()
            return [
                {
                    "event_id": r.event_id,
                    "subject": r.subject,
                    "data": json.loads(r.data),
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]
        finally:
            session.close()

    def count(self, subject: str | None = None) -> int:
        """عدد الأحداث."""
        session = self._Session()
        try:
            q = session.query(EventModel)
            if subject:
                q = q.filter(EventModel.subject == subject)
            return q.count()
        finally:
            session.close()


# Singleton
_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    """الحصول على ناقل الأحداث (Singleton)."""
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus


# === عقود الأحداث (Event Contracts) ===

EVENT_CONTRACTS = {
    # انتقال حالة في النواة التنفيذية الفدرالية — كل انتقال يُعلَن بهذا العقد.
    "amos_federation.executive.task_transitioned": {
        "required_fields": ["task_id", "from_state", "to_state"],
        "optional_fields": [
            "audit_id",
            "authority_decision",
            "authority_layer",
            "detail",
        ],
    },
    # نشاط نظام متخصّص (نماذج/تدريب/تقييم/نقد) — أثر بلا تغيير حالة مهمّة.
    "amos_federation.executive.subsystem_activity": {
        "required_fields": ["activity_id", "activity_kind", "fidelity"],
        "optional_fields": [
            "target",
            "task_id",
            "authority_decision",
            "authority_layer",
            "audit_id",
            "execution_effect",
            "payload",
        ],
    },
    # مرحلة من دورة حياة وكيل داخل تنفيذ واحد — منفصلة عن حالة المهمّة بقصد.
    "amos_federation.executive.agent_lifecycle": {
        "required_fields": ["phase", "agent_id", "execution_id"],
        "optional_fields": [
            "task_id",
            "agent_role",
            "audit_id",
            "runtime_fidelity",
            "tool_execution_fidelity",
            "task_state_effect",
            "detail",
        ],
    },
    "amos_federation.task.created": {
        "required_fields": ["task_id", "type", "description"],
        "optional_fields": ["tenant_id", "priority"],
    },
    "amos_federation.task.planned": {
        "required_fields": ["task_id", "plan"],
        "optional_fields": ["agent_id"],
    },
    "amos_federation.agent.assigned": {
        "required_fields": ["task_id", "agent_id"],
        "optional_fields": ["plan"],
    },
    "amos_federation.agent.started": {
        "required_fields": ["agent_id", "task_id"],
        "optional_fields": [],
    },
    "amos_federation.tool.executed": {
        "required_fields": ["tool_id", "agent_id", "result"],
        "optional_fields": ["task_id"],
    },
    "amos_federation.agent.completed": {
        "required_fields": ["agent_id", "task_id", "result"],
        "optional_fields": ["quality_score"],
    },
    "amos_federation.experience.recorded": {
        "required_fields": ["experience_id", "type"],
        "optional_fields": ["agent_id", "task_id", "quality_score"],
    },
    "amos_federation.memory.stored": {
        "required_fields": ["key"],
        "optional_fields": ["value", "keywords"],
    },
    "amos_federation.model.invoked": {
        "required_fields": ["model", "tokens_used"],
        "optional_fields": ["cost_usd", "latency_ms"],
    },
    "amos_federation.critic.reviewed": {
        "required_fields": ["review_id", "quality_score"],
        "optional_fields": ["task_id", "agent_id", "approved"],
    },
    "amos_federation.approval.signed": {
        "required_fields": ["approval_id", "decision"],
        "optional_fields": ["model_id", "signed_by"],
    },
    "amos_federation.policy.checked": {
        "required_fields": ["policy_name", "allowed"],
        "optional_fields": ["violations"],
    },
    # === السجل الفدرالي (R7-A) ===
    #
    # كل عقد هنا يُلزم معرّف الكيان و`actor`، لأن حدث دولة بلا فاعل أثرٌ لا
    # يُحاسَب عليه أحد. و`correlation_id` و`timestamp` عمودان في `EventRecord`
    # يضيفهما الناقل، فلا يُطلبان في الحمولة.
    "amos_federation.registry.institution_registered": {
        "required_fields": ["institution_id", "code", "kind", "actor"],
        "optional_fields": [
            "branch",
            "tenant_id",
            "parent_institution_id",
            "actor_role",
            "session_id",
            "audit_id",
        ],
    },
    "amos_federation.registry.institution_status_changed": {
        "required_fields": ["institution_id", "from_status", "to_status", "actor"],
        "optional_fields": ["code", "reason", "tenant_id", "actor_role", "session_id", "audit_id"],
    },
    "amos_federation.registry.department_created": {
        "required_fields": ["department_id", "institution_id", "code", "actor"],
        "optional_fields": [
            "institution_code",
            "tenant_id",
            "actor_role",
            "session_id",
            "audit_id",
        ],
    },
    "amos_federation.registry.official_appointed": {
        "required_fields": ["official_id", "agent_id", "institution_id", "actor"],
        "optional_fields": [
            "department_id",
            "title",
            "is_head",
            "tenant_id",
            "actor_role",
            "session_id",
            "audit_id",
        ],
    },
    "amos_federation.registry.official_revoked": {
        "required_fields": ["official_id", "agent_id", "reason", "actor"],
        "optional_fields": [
            "institution_id",
            "tenant_id",
            "actor_role",
            "session_id",
            "audit_id",
        ],
    },
    # === عقود السجل الوطني والهوية الكانونية (R7-C) ===
    #
    # لا موضوعٌ جديد خارج مفردة `amos_federation.registry.*` القائمة، ولا ناقل
    # ثانٍ: هذه أحداثٌ على الناقل الدائم نفسه (R7-G). وكل عقدٍ يُلزم معرّف الكيان
    # و`actor` — فالحدث يُتتبَّع إلى ما تغيَّر ومن غيَّره، لا إلى أحدهما.
    "amos_federation.registry.identity_created": {
        "required_fields": ["identity_id", "identity_type", "actor"],
        "optional_fields": [
            "status",
            "tenant_id",
            "actor_role",
            "session_id",
            "audit_id",
        ],
    },
    "amos_federation.registry.identity_status_changed": {
        "required_fields": ["identity_id", "status", "reason", "actor"],
        "optional_fields": [
            "previous_status",
            "tenant_id",
            "actor_role",
            "session_id",
            "audit_id",
        ],
    },
    # ربط المبدأ بهويته — الحدث الذي يجعل «من هو المُنادي؟» قابلًا للتتبّع.
    "amos_federation.registry.principal_linked": {
        "required_fields": ["link_id", "principal_id", "identity_id", "actor"],
        "optional_fields": [
            "binding_source",
            "tenant_id",
            "actor_role",
            "session_id",
            "audit_id",
        ],
    },
    # ربط الوكيل التشغيلي (R3/R4) بهويته — بلا دمج الجدولين.
    "amos_federation.registry.agent_identity_linked": {
        "required_fields": ["link_id", "agent_id", "identity_id", "actor"],
        "optional_fields": ["tenant_id", "actor_role", "session_id", "audit_id"],
    },
    "amos_federation.registry.position_created": {
        "required_fields": ["position_id", "code", "institution_id", "authority_scope", "actor"],
        "optional_fields": [
            "department_id",
            "tenant_id",
            "actor_role",
            "session_id",
            "audit_id",
        ],
    },
    # تقليد منصب: ثلاث إشارات معًا (المسؤول والهوية والمنصب) لأن الإسناد يلزمه
    # الثلاث؛ حدثٌ يحمل اثنتين منها يُنتج سلسلةً ناقصة في التدقيق.
    "amos_federation.registry.position_granted": {
        "required_fields": ["assignment_id", "official_id", "identity_id", "position_id", "actor"],
        "optional_fields": ["tenant_id", "actor_role", "session_id", "audit_id"],
    },
    "amos_federation.registry.position_revoked": {
        "required_fields": ["assignment_id", "official_id", "position_id", "reason", "actor"],
        "optional_fields": [
            "identity_id",
            "tenant_id",
            "actor_role",
            "session_id",
            "audit_id",
        ],
    },
    # منح سلطة أو سحبها — `change` يفرّق بينهما في موضوعٍ واحد، فيُقرأ تاريخ
    # السلطة على منصبٍ واحد بترتيبٍ واحد.
    "amos_federation.registry.authority_changed": {
        "required_fields": ["grant_id", "position_id", "operation", "scope", "change", "actor"],
        "optional_fields": [
            "reason",
            "tenant_id",
            "actor_role",
            "session_id",
            "audit_id",
        ],
    },
    # === عقود الخدمات الحكومية (R7-A، الوحدة 2) ===
    #
    # كل عقد قضية يُلزم `task_id` لأن كل قضية في هذه الدولة لها مهمّة حقيقية في
    # `tasks` (R7-E) — فالحدث يُتتبَّع إلى الكيان والفاعل والمهمّة معًا.
    "amos_federation.gov.service_published": {
        "required_fields": ["service_id", "code", "institution_id", "actor"],
        "optional_fields": ["tenant_id", "actor_role", "session_id", "audit_id"],
    },
    "amos_federation.gov.service_status_changed": {
        "required_fields": ["service_id", "from_status", "to_status", "actor"],
        "optional_fields": ["reason", "tenant_id", "actor_role", "session_id", "audit_id"],
    },
    "amos_federation.gov.case_opened": {
        "required_fields": ["case_id", "reference", "service_id", "task_id", "actor"],
        "optional_fields": [
            "institution_id",
            "applicant_agent_id",
            "tenant_id",
            "actor_role",
            "session_id",
            "audit_id",
        ],
    },
    "amos_federation.gov.case_assigned": {
        "required_fields": ["case_id", "reference", "official_id", "actor"],
        "optional_fields": [
            "institution_id",
            "task_id",
            "tenant_id",
            "actor_role",
            "session_id",
            "audit_id",
        ],
    },
    "amos_federation.gov.case_reviewed": {
        "required_fields": ["case_id", "reference", "task_id", "task_final_state", "actor"],
        "optional_fields": ["terminal", "tenant_id", "actor_role", "session_id", "audit_id"],
    },
    "amos_federation.gov.case_decided": {
        "required_fields": ["case_id", "decision_id", "outcome", "official_id", "actor"],
        "optional_fields": [
            "reference",
            "task_id",
            "task_final_state",
            "tenant_id",
            "actor_role",
            "session_id",
            "audit_id",
        ],
    },
    "amos_federation.gov.case_closed": {
        "required_fields": ["case_id", "reference", "decision_id", "actor"],
        "optional_fields": ["task_id", "tenant_id", "actor_role", "session_id", "audit_id"],
    },
    # === الخزانة الفدرالية (R7-B) — لا ناقل جديد، عقودٌ على الناقل الدائم القائم ===
    "amos_federation.treasury.treasury_established": {
        "required_fields": ["treasury_id", "code", "currency", "actor"],
        "optional_fields": [
            "institution_id",
            "tenant_id",
            "actor_role",
            "session_id",
            "audit_id",
        ],
    },
    "amos_federation.treasury.account_opened": {
        "required_fields": ["account_id", "code", "treasury_id", "kind", "currency", "actor"],
        "optional_fields": ["tenant_id", "actor_role", "session_id", "audit_id"],
    },
    "amos_federation.treasury.budget_created": {
        "required_fields": [
            "budget_id",
            "code",
            "institution_id",
            "period",
            "currency",
            "limit_amount",
            "actor",
        ],
        "optional_fields": ["tenant_id", "actor_role", "session_id", "audit_id"],
    },
    "amos_federation.treasury.allocation_created": {
        "required_fields": [
            "allocation_id",
            "budget_id",
            "account_id",
            "amount",
            "currency",
            "official_id",
            "actor",
        ],
        "optional_fields": ["decision_id", "tenant_id", "actor_role", "session_id", "audit_id"],
    },
    "amos_federation.treasury.transaction_posted": {
        "required_fields": [
            "transaction_id",
            "reference",
            "treasury_id",
            "kind",
            "amount",
            "currency",
            "official_id",
            "actor",
        ],
        "optional_fields": [
            "budget_id",
            "allocation_id",
            "task_id",
            "decision_id",
            "tenant_id",
            "actor_role",
            "session_id",
            "audit_id",
        ],
    },
    "amos_federation.treasury.transaction_reversed": {
        "required_fields": [
            "transaction_id",
            "reference",
            "reverses_transaction_id",
            "amount",
            "currency",
            "official_id",
            "actor",
        ],
        "optional_fields": [
            "reversed_reference",
            "treasury_id",
            "reason",
            "tenant_id",
            "actor_role",
            "session_id",
            "audit_id",
        ],
    },
    # === R7-D: القضاء الفدرالي — مفردةٌ واحدة `amos_federation.judiciary.*` ===
    #
    # ولا يُلمَس `amos_federation.judicial.*` القديم الذي ينشره `JudicialBranch`
    # في `services/governance/federation.py`: ذاك تحكيمٌ غير رسميّ بين الوكلاء
    # (قاضيه نصٌّ حرّ) بلا عقدٍ هنا، وخلطُه بأحداث القضاء الكانوني كان سيجعل
    # مستهلكًا واحدًا يرى النوعين سواءً. فالاسمان مفترقان بقصد.
    #
    # وكل عقدٍ يُلزم معرّف الكيان و`actor`، وأحداثُ القضية تُلزم `case_id`.
    # و`correlation_id` و`timestamp` عمودان في `EventRecord` يضيفهما الناقل.
    "amos_federation.judiciary.court_registered": {
        "required_fields": ["court_id", "code", "jurisdiction", "actor"],
        "optional_fields": [
            "name",
            "level",
            "institution_id",
            "status",
            "tenant_id",
            "actor_role",
            "session_id",
            "audit_id",
        ],
    },
    "amos_federation.judiciary.court_status_changed": {
        "required_fields": ["court_id", "code", "status", "reason", "actor"],
        "optional_fields": [
            "previous_status",
            "tenant_id",
            "actor_role",
            "session_id",
            "audit_id",
        ],
    },
    "amos_federation.judiciary.judge_appointed": {
        "required_fields": ["judge_id", "court_id", "official_id", "identity_id", "actor"],
        "optional_fields": [
            "position_id",
            "title",
            "status",
            "tenant_id",
            "actor_role",
            "session_id",
            "audit_id",
        ],
    },
    "amos_federation.judiciary.judge_status_changed": {
        "required_fields": ["judge_id", "court_id", "status", "reason", "actor"],
        "optional_fields": [
            "previous_status",
            "identity_id",
            "official_id",
            "tenant_id",
            "actor_role",
            "session_id",
            "audit_id",
        ],
    },
    "amos_federation.judiciary.case_opened": {
        "required_fields": ["case_id", "reference", "court_id", "jurisdiction", "actor"],
        "optional_fields": [
            "case_type",
            "status",
            "opened_by_identity_id",
            "tenant_id",
            "actor_role",
            "session_id",
            "audit_id",
        ],
    },
    "amos_federation.judiciary.case_assigned": {
        "required_fields": ["case_id", "judge_id", "court_id", "actor"],
        "optional_fields": [
            "reference",
            "status",
            "identity_id",
            "tenant_id",
            "actor_role",
            "session_id",
            "audit_id",
        ],
    },
    "amos_federation.judiciary.proceeding_recorded": {
        "required_fields": ["proceeding_id", "case_id", "proceeding_type", "sequence", "actor"],
        "optional_fields": [
            "actor_identity_id",
            "status",
            "summary",
            "tenant_id",
            "actor_role",
            "session_id",
            "audit_id",
        ],
    },
    "amos_federation.judiciary.evidence_submitted": {
        "required_fields": ["evidence_id", "case_id", "evidence_type", "actor"],
        "optional_fields": [
            "content_hash",
            "fingerprint_algo",
            "status",
            "submitted_by_identity_id",
            "tenant_id",
            "actor_role",
            "session_id",
            "audit_id",
        ],
    },
    "amos_federation.judiciary.ruling_issued": {
        "required_fields": ["ruling_id", "case_id", "court_id", "judge_id", "decision", "actor"],
        "optional_fields": [
            "stage",
            "status",
            "provenance_class",
            "judge_identity_id",
            "tenant_id",
            "actor_role",
            "session_id",
            "audit_id",
        ],
    },
    "amos_federation.judiciary.ruling_enforced": {
        "required_fields": ["enforcement_id", "ruling_id", "case_id", "kind", "status", "actor"],
        "optional_fields": [
            "task_id",
            "transaction_reference",
            "detail",
            "requested_by_identity_id",
            "tenant_id",
            "actor_role",
            "session_id",
            "audit_id",
        ],
    },
    "amos_federation.judiciary.case_closed": {
        "required_fields": ["case_id", "reference", "reason", "actor"],
        "optional_fields": [
            "previous_status",
            "court_id",
            "status",
            "tenant_id",
            "actor_role",
            "session_id",
            "audit_id",
        ],
    },
    # === R8: الفدرالية والولايات — مفردةٌ واحدة `amos_federation.federation.*` ===
    #
    # لا ناقلَ أحداثٍ جديد ولا مخزنَ تدقيقٍ ثانٍ (R8-K): هذه عقودٌ تُضاف إلى
    # المفردة القائمة، وتُنشَر بـ`record_domain_trace` القائمة (تدقيقٌ ثمّ حدث).
    # وكلُّ حدثٍ يحمل الفاعلَ ودورَه وجلستَه و`audit_id`، و`correlation_id` و
    # `timestamp` عمودان يضيفهما الناقل فلا يُعادان في الحمولة.
    #
    # وما لا حقيقةَ له **لا يُختلق ليُرضي مخطَّطًا** (R8-K): الحقولُ التي قد لا
    # تُعرف — كالهوية والمنصب والمهمّة — اختياريةٌ لا مطلوبة، فلا يُكتب صفرٌ ولا
    # نصٌّ فارغٌ مكانَ معرِّفٍ غائب.
    "amos_federation.federation.government_registered": {
        "required_fields": ["government_id", "code", "level", "actor"],
        "optional_fields": [
            "name",
            "parent_government_id",
            "status",
            "tenant_id",
            "actor_role",
            "session_id",
            "audit_id",
        ],
    },
    "amos_federation.federation.government_status_changed": {
        "required_fields": ["government_id", "code", "status", "reason", "actor"],
        "optional_fields": [
            "previous_status",
            "level",
            "tenant_id",
            "actor_role",
            "session_id",
            "audit_id",
        ],
    },
    "amos_federation.federation.institution_bound": {
        "required_fields": ["binding_id", "government_id", "institution_id", "relation", "actor"],
        "optional_fields": [
            "government_code",
            "government_level",
            "identity_id",
            "tenant_id",
            "actor_role",
            "session_id",
            "audit_id",
        ],
    },
    "amos_federation.federation.relation_recorded": {
        "required_fields": [
            "relation_id",
            "from_kind",
            "from_ref",
            "to_kind",
            "to_ref",
            "relation",
            "actor",
        ],
        "optional_fields": [
            "status",
            "note",
            "identity_id",
            "tenant_id",
            "actor_role",
            "session_id",
            "audit_id",
        ],
    },
    "amos_federation.federation.delegation_granted": {
        "required_fields": ["delegation_id", "from_government_id", "operation", "scope", "actor"],
        "optional_fields": [
            "to_government_id",
            "to_institution_id",
            "max_amount",
            "expires_at",
            "reason",
            "identity_id",
            "tenant_id",
            "actor_role",
            "session_id",
            "audit_id",
        ],
    },
    "amos_federation.federation.delegation_revoked": {
        "required_fields": ["delegation_id", "from_government_id", "operation", "reason", "actor"],
        "optional_fields": [
            "to_government_id",
            "to_institution_id",
            "previous_status",
            "tenant_id",
            "actor_role",
            "session_id",
            "audit_id",
        ],
    },
    "amos_federation.federation.service_scoped": {
        "required_fields": ["scope_id", "service_id", "level", "institution_id", "actor"],
        "optional_fields": [
            "government_id",
            "department_id",
            "identity_id",
            "tenant_id",
            "actor_role",
            "session_id",
            "audit_id",
        ],
    },
    "amos_federation.federation.case_scoped": {
        "required_fields": [
            "scope_id",
            "case_id",
            "level",
            "institution_id",
            "classification",
            "actor",
        ],
        "optional_fields": [
            "government_id",
            "department_id",
            "responsible_official_id",
            "identity_id",
            "position_id",
            "boundary_reason",
            "tenant_id",
            "actor_role",
            "session_id",
            "audit_id",
        ],
    },
    "amos_federation.federation.operation_recorded": {
        "required_fields": [
            "operation_id",
            "kind",
            "level",
            "institution_id",
            "status",
            "classification",
            "actor",
        ],
        "optional_fields": [
            "government_id",
            "department_id",
            "decision_id",
            "case_id",
            "ruling_id",
            "identity_id",
            "position_id",
            "task_id",
            "transaction_reference",
            "detail",
            "tenant_id",
            "actor_role",
            "session_id",
            "audit_id",
        ],
    },
}


def validate_event(subject: str, data: dict[str, Any]) -> tuple[bool, str]:
    """التحقق من مطابقة الحدث لعقدة."""
    contract = EVENT_CONTRACTS.get(subject)
    if contract is None:
        return False, f"لا يوجد عقد للحدث '{subject}'"
    for field in contract["required_fields"]:
        if field not in data:
            return False, f"الحقل المطلوب '{field}' مفقود في حدث '{subject}'"
    return True, "صالح"
