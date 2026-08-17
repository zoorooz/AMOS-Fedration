"""
AMOS-Federation Durable Event Bus — Phase 2
الهدف: ناقل أحداث دائم فوق PostgreSQL مع consumer offsets, ack, replay
النطاق: common/durable_event_bus
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-15

هذا تطبيق Phase 2-compatible فوق PostgreSQL كبديل تشغيلي لـ NATS JetStream.
يوفر: publish/subscribe durable، consumer offsets/acks، replay،
subjects بصيغة amos_federation.{domain}.{event_type}
NATS الحقيقي مؤجل لحين توفر البنية.
"""

import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Column, DateTime, Index, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from amos_federation.common.database import connect_args, get_database_url


class DurableEventBase(DeclarativeBase):
    pass


class EventRecord(DurableEventBase):
    """جدول الأحداث المنشورة — دائم."""

    __tablename__ = "durable_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String, nullable=False, unique=True, index=True)
    subject = Column(String, nullable=False, index=True)
    event_type = Column(String, nullable=False, index=True)
    data = Column(Text, nullable=False)
    correlation_id = Column(String, nullable=True, index=True)
    causation_id = Column(String, nullable=True)
    schema_version = Column(String, nullable=False, default="1.0")
    created_at = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False, index=True)

    __table_args__ = (Index("ix_durable_events_subject_type", "subject", "event_type"),)


class ConsumerOffset(DurableEventBase):
    """جدول متابعي المستهلكين — يتيح ack و replay."""

    __tablename__ = "event_consumer_offsets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    consumer_name = Column(String, nullable=False, index=True)
    subject = Column(String, nullable=False)
    last_event_id = Column(String, nullable=True)
    last_event_pk = Column(Integer, nullable=True, default=0)
    acked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))

    __table_args__ = (
        Index("ix_consumer_offsets_name_subject", "consumer_name", "subject", unique=True),
    )


class DurableEventBus:
    """ناقل أحداث دائم فوق PostgreSQL — Phase 2 compatible.

    بديل تشغيلي لـ NATS JetStream:
    - publish: يخزن الحدث في DB ثم يستدعي المعالجات
    - subscribe: يسجل معالجًا لموضوع معين
    - poll: يجلب الأحداث غير المستهلكة بعد
    - ack: يؤكد استهلاك حدث
    - replay: يعيد تشغيل الأحداث من نقطة معينة
    """

    def __init__(self) -> None:
        url = get_database_url()
        # المصدر الواحد لمعاملات الاتّصال؛ لا فرعَ لهجةٍ مكرّرًا هنا ولا
        # sslmode مكتوبًا بيد (انظر database.connect_args).
        self._engine = create_engine(
            url,
            connect_args=connect_args(url),
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
        )
        DurableEventBase.metadata.create_all(self._engine)
        self._Session = sessionmaker(bind=self._engine, autoflush=False, expire_on_commit=False)
        self._handlers: dict[str, list[Callable[[dict[str, Any]], None]]] = {}

    def publish(
        self,
        subject: str,
        data: dict[str, Any],
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ) -> dict[str, Any]:
        """نشر حدث دائم — يخزن في DB ويستدعي المعالجات المسجّلة.

        Args:
            subject: بصيغة amos_federation.{domain}.{event_type}
            data: حمولة الحدث
            correlation_id: معرف التتبع (optional)
            causation_id: معرف الحدث المسبب (optional)
        """
        event_id = f"evt-{uuid.uuid4()}"
        parts = subject.split(".")
        event_type = parts[-1] if len(parts) > 1 else subject

        # التحقق من العقد
        from amos_federation.common.event_bus import validate_event

        is_valid, msg = validate_event(subject, data)
        if not is_valid:
            import structlog

            structlog.get_logger().warning("event.contract_violation", subject=subject, message=msg)

        event_record = {
            "event_id": event_id,
            "subject": subject,
            "event_type": event_type,
            "data": data,
            "correlation_id": correlation_id,
            "causation_id": causation_id,
            "schema_version": "1.0",
            "timestamp": datetime.now(UTC).isoformat(),
        }

        # تخزين دائم
        session = self._Session()
        try:
            row = EventRecord(
                event_id=event_id,
                subject=subject,
                event_type=event_type,
                data=json.dumps(data, ensure_ascii=False),
                correlation_id=correlation_id,
                causation_id=causation_id,
            )
            session.add(row)
            session.commit()
        finally:
            session.close()

        # استدعاء المعالجات المسجّلة (in-process)
        handlers = self._get_matching_handlers(subject)
        for handler in handlers:
            try:
                handler(event_record)
            except Exception as e:
                import structlog

                structlog.get_logger().error("event.handler_error", subject=subject, error=str(e))

        return event_record

    def _get_matching_handlers(self, subject: str) -> list[Callable]:
        """جلب المعالجات المطابقة بما فيها wildcards."""
        handlers = list(self._handlers.get(subject, []))
        for pattern, pattern_handlers in self._handlers.items():
            if pattern.endswith(".*"):
                prefix = pattern[:-2]
                if subject.startswith(prefix + "."):
                    handlers.extend(pattern_handlers)
        return handlers

    def subscribe(self, subject: str, handler: Callable[[dict[str, Any]], None]) -> None:
        """تسجيل معالج لموضوع معين. يدعم wildcards (amos_federation.*)."""
        if subject not in self._handlers:
            self._handlers[subject] = []
        self._handlers[subject].append(handler)

    def poll(
        self,
        consumer_name: str,
        subject: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """جلب الأحداث غير المستهلكة بعد من قبل مستهلك معين."""
        session = self._Session()
        try:
            # الحصول على آخر offset للمستهلك
            offset = (
                session.query(ConsumerOffset)
                .filter_by(
                    consumer_name=consumer_name,
                    subject=subject or "*",
                )
                .first()
            )

            last_pk = offset.last_event_pk if offset else 0

            # جلب الأحداث الجديدة
            q = session.query(EventRecord).filter(EventRecord.id > last_pk)
            if subject and subject != "*":
                q = q.filter(EventRecord.subject == subject)
            elif subject is None:
                pass  # كل المواضيع

            rows = q.order_by(EventRecord.id.asc()).limit(limit).all()
            return [
                {
                    "event_id": r.event_id,
                    "subject": r.subject,
                    "event_type": r.event_type,
                    "data": json.loads(r.data),
                    "correlation_id": r.correlation_id,
                    "causation_id": r.causation_id,
                    "schema_version": r.schema_version,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]
        finally:
            session.close()

    def ack(self, consumer_name: str, subject: str, event_id: str) -> bool:
        """تأكيد استهلاك حدث — تحديث offset."""
        session = self._Session()
        try:
            event = session.query(EventRecord).filter_by(event_id=event_id).first()
            if not event:
                return False

            offset = (
                session.query(ConsumerOffset)
                .filter_by(
                    consumer_name=consumer_name,
                    subject=subject,
                )
                .first()
            )

            if offset:
                offset.last_event_id = event_id
                offset.last_event_pk = event.id
                offset.acked_at = datetime.now(UTC)
            else:
                offset = ConsumerOffset(
                    consumer_name=consumer_name,
                    subject=subject,
                    last_event_id=event_id,
                    last_event_pk=event.id,
                    acked_at=datetime.now(UTC),
                )
                session.add(offset)

            session.commit()
            return True
        finally:
            session.close()

    def replay(
        self,
        consumer_name: str,
        subject: str | None = None,
        from_beginning: bool = True,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """إعادة تشغيل الأحداث من نقطة معينة."""
        session = self._Session()
        try:
            q = session.query(EventRecord)
            if subject and subject != "*":
                q = q.filter(EventRecord.subject == subject)

            if not from_beginning:
                offset = (
                    session.query(ConsumerOffset)
                    .filter_by(
                        consumer_name=consumer_name,
                        subject=subject or "*",
                    )
                    .first()
                )
                if offset:
                    q = q.filter(EventRecord.id > offset.last_event_pk)

            rows = q.order_by(EventRecord.id.asc()).limit(limit).all()
            return [
                {
                    "event_id": r.event_id,
                    "subject": r.subject,
                    "event_type": r.event_type,
                    "data": json.loads(r.data),
                    "correlation_id": r.correlation_id,
                    "causation_id": r.causation_id,
                    "schema_version": r.schema_version,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]
        finally:
            session.close()

    def get_events(self, subject: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """استرجاع الأحداث المخزَّنة."""
        session = self._Session()
        try:
            q = session.query(EventRecord)
            if subject:
                q = q.filter(EventRecord.subject == subject)
            rows = q.order_by(EventRecord.id.desc()).limit(limit).all()
            return [
                {
                    "event_id": r.event_id,
                    "subject": r.subject,
                    "event_type": r.event_type,
                    "data": json.loads(r.data),
                    "correlation_id": r.correlation_id,
                    "causation_id": r.causation_id,
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
            q = session.query(EventRecord)
            if subject:
                q = q.filter(EventRecord.subject == subject)
            return q.count()
        finally:
            session.close()

    def list_consumers(self) -> list[dict[str, Any]]:
        """قائمة المستهلكين المسجّلين."""
        session = self._Session()
        try:
            rows = session.query(ConsumerOffset).all()
            return [
                {
                    "consumer_name": r.consumer_name,
                    "subject": r.subject,
                    "last_event_id": r.last_event_id,
                    "last_event_pk": r.last_event_pk,
                    "acked_at": r.acked_at.isoformat() if r.acked_at else None,
                }
                for r in rows
            ]
        finally:
            session.close()


# Singleton
_durable_bus: DurableEventBus | None = None


def get_durable_event_bus() -> DurableEventBus:
    """الحصول على الناقل الدائم (Singleton)."""
    global _durable_bus
    if _durable_bus is None:
        _durable_bus = DurableEventBus()
    return _durable_bus
