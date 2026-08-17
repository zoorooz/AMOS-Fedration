"""
AMOS-Federation Database Layer
الهدف: طبقة تخزين دائمة بـ SQLAlchemy (SQLite للبيئة الحالية، PostgreSQL للإنتاج)
النطاق: common/database
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-15
"""

import contextlib
import os
import uuid
from collections.abc import Generator
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """القاعدة لكل النماذج."""

    pass


# === النماذج ===


class AgentModel(Base):
    """جدول الوكلاء."""

    __tablename__ = "agents"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    role = Column(String, nullable=False)
    status = Column(String, default="registered")
    permissions = Column(JSON, default=list)
    allowed_tools = Column(JSON, default=list)
    token_budget = Column(Integer, default=10000)
    tenant_id = Column(String, default="default")
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    updated_at = Column(
        DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class ToolModel(Base):
    """جدول الأدوات."""

    __tablename__ = "tools"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    description = Column(Text, default="")
    category = Column(String, default="general")
    keywords = Column(JSON, default=list)
    endpoint = Column(String, default="")
    permissions_required = Column(JSON, default=list)
    sandbox_required = Column(Boolean, default=False)
    tenant_id = Column(String, default="default")
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


class TaskModel(Base):
    """جدول المهام."""

    __tablename__ = "tasks"

    id = Column(String, primary_key=True)
    type = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    status = Column(String, default="created")
    priority = Column(String, default="normal")
    domain = Column(String, default="general")
    assigned_agent = Column(String, nullable=True)
    plan = Column(JSON, default=list)
    result = Column(JSON, default=dict)
    tenant_id = Column(String, default="default")
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    updated_at = Column(
        DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class MemoryModel(Base):
    """جدول الذاكرة التشغيلية."""

    __tablename__ = "memories"

    key = Column(String, primary_key=True)
    value = Column(Text, nullable=False)
    keywords = Column(JSON, default=list)
    tenant_id = Column(String, default="default")
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


class ExperienceModel(Base):
    """جدول الخبرات."""

    __tablename__ = "experiences"

    id = Column(String, primary_key=True)
    type = Column(String, nullable=False)
    task_id = Column(String, nullable=True)
    agent_id = Column(String, nullable=True)
    model_used = Column(String, nullable=True)
    outcome = Column(JSON, default=dict)
    quality_score = Column(Float, nullable=True)
    provenance = Column(JSON, default=dict)
    tenant_id = Column(String, default="default")
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


class ReviewModel(Base):
    """جدول مراجعات الناقد."""

    __tablename__ = "reviews"

    id = Column(String, primary_key=True)
    task_id = Column(String, nullable=True)
    agent_id = Column(String, nullable=True)
    quality_score = Column(Float, nullable=False)
    feedback = Column(Text, default="")
    approved = Column(Boolean, default=False)
    criteria = Column(JSON, default=dict)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


class AuditEntryModel(Base):
    """جدول سجل التدقيق."""

    __tablename__ = "audit_entries"

    id = Column(String, primary_key=True)
    action = Column(String, nullable=False)
    actor = Column(String, nullable=False)
    details = Column(JSON, default=dict)
    prev_hash = Column(String, nullable=False, default="0" * 64)
    hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


# === إدارة الاتصال ===


def get_database_url() -> str:
    """الحصول على رابط قاعدة البيانات."""
    return os.environ.get(
        "AMOS_DATABASE_URL",
        f"sqlite:///{os.path.join(os.getcwd(), 'amos_federation.db')}",
    )


# === لهجة قاعدة البيانات ===

DIALECT_POSTGRES = "postgresql"
DIALECT_SQLITE = "sqlite"


def db_dialect(url: str | None = None) -> str:
    """المصدر الوحيد لتحديد لهجة قاعدة البيانات الحالية.

    يعيد DIALECT_POSTGRES أو DIALECT_SQLITE. كل قرار يعتمد على اللهجة
    في هذه الطبقة يجب أن يمرّ من هنا، لا من مقارنات نصية متفرقة.
    """
    effective = url if url is not None else get_database_url()
    if effective.startswith("postgresql"):
        return DIALECT_POSTGRES
    return DIALECT_SQLITE


def _is_postgres(url: str | None = None) -> bool:
    return db_dialect(url) == DIALECT_POSTGRES


def _pg_connect_args(url: str | None = None) -> dict:
    """معاملات الاتصال المعتمدة على اللهجة (Supabase يتطلب SSL).

    هذه الدالة هي المصدر الوحيد لمعاملات الاتصال؛ get_engine() يستدعيها
    ولا يكرّر المنطق.
    """
    if not _is_postgres(url):
        return {"check_same_thread": False}
    return {
        "sslmode": os.environ.get("AMOS_DB_SSLMODE", "require"),
        "connect_timeout": int(os.environ.get("AMOS_DB_CONNECT_TIMEOUT", "15")),
    }


def connect_args(url: str | None = None) -> dict:
    """معاملاتُ الاتّصال لكلّ مُنشِئِ محرّكٍ في المشروع — الواجهةُ المُعلنة.

    `_pg_connect_args` تقول عن نفسها إنّها «المصدرُ الوحيد»، وكانت ثلاثةُ
    مواضعٍ تكتب `sslmode: require` بيدها فتُكذّب الدّعوى. فهذه دالةٌ عامّةٌ
    تُستورَد من خارج الوحدة، ليبقى المصدرُ واحدًا فعلًا لا قولًا.

    والمستودع يطلب SSL افتراضًا لأنّ الإنتاج على Supabase يوجبه، وُيخفَّض
    بمتغيّر `AMOS_DB_SSLMODE` وحده — للحاويات المحليّة التي لا TLS لها.
    """
    return _pg_connect_args(url)


def _pool_settings() -> dict:
    """حدود تجمّع الاتصالات — قابلة للضبط لأن الوسطاء المُجمّعين محدودون.

    Supabase session-mode pooler يرفض ما يزيد على 15 عميلًا، فلا يجوز تثبيت
    حجم التجمّع في الكود.
    """
    return {
        "pool_size": int(os.environ.get("AMOS_DB_POOL_SIZE", "5")),
        "max_overflow": int(os.environ.get("AMOS_DB_MAX_OVERFLOW", "10")),
    }


_engine = None
_SessionLocal = None


def _enforce_sqlite_foreign_keys(engine) -> None:
    """شغِّل فرض المفاتيح الأجنبية على SQLite — وإلا كان القيد زخرفة.

    SQLite يقبل `REFERENCES` في المخطَّط ثم **لا يفرضه** إلا إذا رُفع
    `PRAGMA foreign_keys` لكل اتصال. وحتى R6 لم يكن في المستودع أي
    `ForeignKey` في طبقة ORM (`grep` = صفر)، فلم يظهر الفرق. وR7 أدخلت أول
    روابط مرجعية حقيقية (`state_officials.agent_id → agents.id`)، فلو بقي
    الفرض مُطفأً لكان الادّعاء بوجود قيود مرجعية كذبًا: الصفوف اليتيمة تُكتب
    بنجاح.

    والفرض هنا على محرك `common/database` وحده. الوحدات التي تُنشئ محركًا
    خاصًّا بها (`treasury`, `RBACSystem`, `DurableEventBus`) لا يشملها هذا،
    وهو دَينٌ قائم مُسجَّل — لكن جداول R7 كلها على هذا المحرك.
    """
    if db_dialect(str(engine.url)) != DIALECT_SQLITE:
        return

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record):  # pragma: no cover - callback
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()


def get_engine():
    """الحصول على محرك قاعدة البيانات (Singleton)."""
    global _engine
    if _engine is None:
        url = get_database_url()
        _engine = create_engine(
            url,
            connect_args=_pg_connect_args(url),
            echo=False,
            pool_pre_ping=True,
            **_pool_settings(),
        )
        _enforce_sqlite_foreign_keys(_engine)
    return _engine


def reset_engine() -> None:
    """إعادة تعيين المحرك — للاختبارات والتغيير بين SQLite و PostgreSQL."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def get_session_factory():
    """الحصول على مصنع الجلسات (Singleton)."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)
    return _SessionLocal


def init_db() -> None:
    """إنشاء كل الجداول عند الإقلاع."""
    Base.metadata.create_all(get_engine())


def get_db() -> Generator[Session, None, None]:
    """Dependency للحصول على جلسة قاعدة بيانات."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def with_db(func):
    """Decorator لتوفير جلسة DB تلقائيًا."""

    def wrapper(*args, **kwargs):
        session = get_session_factory()()
        try:
            result = func(*args, session=session, **kwargs)
            session.commit()
            return result
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    return wrapper


# === توافق عكسي مع الوحدات القديمة ===


def generate_uuid() -> uuid.UUID:
    """توليد معرّف فريد (توافق عكسي)."""
    return uuid.uuid4()


# === طبقة SQL محايدة اللهجة ===
#
# قاعدة واحدة لكل الكود الذي يستخدم db_cursor():
#   اكتب المحاجيز بالشكل القانوني "?" فقط.
# المغلّف أدناه يترجمها إلى "%s" عند استخدام psycopg2. لا يجوز كتابة
# SQL خاص بلهجة واحدة داخل مسار الإنتاج.

PARAM_PLACEHOLDER = "?"


def translate_placeholders(sql: str, dialect: str) -> str:
    """تحويل المحاجيز القانونية "?" إلى ما تفهمه اللهجة المستهدفة.

    يتجاهل المحاجيز داخل السلاسل النصية المفردة حتى لا يُفسِد القيم الحرفية،
    ويضاعف '%' في PostgreSQL لأن psycopg2 يعتبره حرف تنسيق.
    """
    if dialect != DIALECT_POSTGRES:
        return sql
    out: list[str] = []
    in_string = False
    for char in sql:
        if char == "'":
            in_string = not in_string
            out.append(char)
        elif in_string:
            out.append(char)
        elif char == PARAM_PLACEHOLDER:
            out.append("%s")
        elif char == "%":
            out.append("%%")
        else:
            out.append(char)
    return "".join(out)


def _as_mapping(row):
    """توحيد شكل السجلّ: قاموس في اللهجتين معًا."""
    if row is None:
        return None
    if isinstance(row, dict):
        return row
    return dict(row)


class PortableCursor:
    """مغلّف مؤشر يخفي اختلافات اللهجة عن مستدعيه.

    يقبل محاجيز "?" دائمًا، ويعيد السجلات كقواميس دائمًا.
    """

    def __init__(self, cursor, dialect: str) -> None:
        self._cursor = cursor
        self.dialect = dialect

    def execute(self, sql: str, params=None):
        translated = translate_placeholders(sql, self.dialect)
        if params is None:
            return self._cursor.execute(translated)
        return self._cursor.execute(translated, params)

    def executemany(self, sql: str, seq_of_params):
        translated = translate_placeholders(sql, self.dialect)
        return self._cursor.executemany(translated, seq_of_params)

    def fetchone(self):
        return _as_mapping(self._cursor.fetchone())

    def fetchall(self):
        return [_as_mapping(row) for row in self._cursor.fetchall()]

    def __getattr__(self, name):
        return getattr(self._cursor, name)


@contextlib.contextmanager
def db_cursor():
    """مؤشر محايد اللهجة يعمل على SQLite و PostgreSQL بنفس الـ SQL."""
    db_url = get_database_url()
    dialect = db_dialect(db_url)

    if dialect == DIALECT_POSTGRES:
        import psycopg2
        from psycopg2.extras import RealDictCursor

        pg_args = _pg_connect_args(db_url)
        conn = psycopg2.connect(db_url, **pg_args)
        try:
            yield PortableCursor(conn.cursor(cursor_factory=RealDictCursor), dialect)
            conn.commit()
        finally:
            conn.close()
    else:
        import sqlite3

        db_path = db_url.replace("sqlite:///", "")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield PortableCursor(conn.cursor(), dialect)
            conn.commit()
        finally:
            conn.close()


# === سجل التدقيق (audit_log) — تعريف واحد لللهجتين ===
#
# عمود seq متزايد رتيب وهو الأساس الوحيد لترتيب السلسلة.
# لا يجوز الترتيب بـ id لأنه UUID في PostgreSQL فيُعطي ترتيبًا عشوائيًا.

_AUDIT_LOG_DDL = {
    DIALECT_SQLITE: """
        CREATE TABLE IF NOT EXISTS audit_log (
            seq        INTEGER PRIMARY KEY AUTOINCREMENT,
            id         TEXT,
            event_id   TEXT,
            timestamp  TEXT,
            event_type TEXT,
            actor_type TEXT,
            actor_id   TEXT,
            action     TEXT,
            chain_hash TEXT,
            prev_hash  TEXT,
            metadata   TEXT
        )
    """,
    DIALECT_POSTGRES: """
        CREATE TABLE IF NOT EXISTS audit_log (
            seq        BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            id         UUID DEFAULT gen_random_uuid(),
            event_id   VARCHAR(255),
            timestamp  TEXT,
            event_type VARCHAR(100),
            actor_type VARCHAR(20),
            actor_id   VARCHAR(255),
            action     VARCHAR(255),
            chain_hash VARCHAR(255),
            prev_hash  VARCHAR(255),
            metadata   JSONB
        )
    """,
}


def audit_log_ddl(dialect: str | None = None) -> str:
    """تعريف جدول audit_log المناسب لللهجة الحالية."""
    return _AUDIT_LOG_DDL[dialect or db_dialect()]


def ensure_audit_log_table() -> None:
    """إنشاء جدول audit_log إن لم يوجد — بنفس العقد في اللهجتين."""
    with db_cursor() as cur:
        cur.execute(audit_log_ddl(cur.dialect))


def drop_audit_log_table() -> None:
    """إزالة جدول audit_log — للاختبارات فقط."""
    with db_cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS audit_log")
