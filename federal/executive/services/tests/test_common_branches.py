"""
اختبارات الأفرع للوحدات المشتركة
الهدف: رفع تغطية الأفرع لـ events / database / api_gateway store
النطاق: common + api_gateway
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-15
"""

import json as _json
import pathlib

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from amos_federation.common import auth, database, events
from amos_federation.common.database import (
    DIALECT_POSTGRES,
    DIALECT_SQLITE,
    _is_postgres,
    _pg_connect_args,
    audit_log_ddl,
    db_cursor,
    drop_audit_log_table,
    ensure_audit_log_table,
    get_database_url,
    get_engine,
    reset_engine,
    translate_placeholders,
)
from amos_federation.common.event_schemas import (
    _has_required_fields,
    load_event_schema,
    validate_event,
)
from amos_federation.common.schemas import TaskDetails
from amos_federation.services.api_gateway.store import (
    TASK_DTO_TO_MODEL_FIELDS,
    DatabaseTaskStore,
    InMemoryTaskStore,
    TaskStoreUnavailableError,
    task_details_to_model_kwargs,
    task_model_to_details,
)

# تعريف جدول audit_log لم يعد مكررًا هنا بلهجة SQLite: الاختبارات تستخدم
# نفس الدالتين المستخدمتين في مسار الإنتاج من common.database.
_ensure_audit_log_table = ensure_audit_log_table
_drop_audit_log_table = drop_audit_log_table


# =============================================================================
# events.py
# =============================================================================
class TestEventChainHash:
    def test_compute_chain_hash_is_deterministic(self) -> None:
        data = {"event_id": "e1", "type": "task.created"}
        h1 = events.compute_chain_hash("sha256:prev", data)
        h2 = events.compute_chain_hash("sha256:prev", data)
        assert h1 == h2
        assert h1.startswith("sha256:")

    def test_compute_chain_hash_changes_with_input(self) -> None:
        base = {"event_id": "e1"}
        assert events.compute_chain_hash("a", base) != events.compute_chain_hash("b", base)


class TestEventPublisher:
    """مسار الأحداث على SQLite — يطلب اللهجة صراحةً لا من البيئة المحيطة."""

    def test_get_last_chain_hash_falls_back_to_genesis(self, sqlite_url: str) -> None:
        # No audit_log table in test DB -> except branch -> GENESIS_HASH
        _drop_audit_log_table()
        assert events.get_last_chain_hash() == events.GENESIS_HASH

    @pytest.mark.asyncio
    async def test_publish_uses_fallback_bus_and_skips_audit(self, sqlite_url: str) -> None:
        publisher = events.EventPublisher()
        event_id = await publisher.publish(
            event_type="task.created",
            source="api-gateway",
            data={"task_id": "t-1"},
            actor_type="system",
            actor_id="sys",
        )
        assert event_id  # uuid string returned
        # publisher never connected -> _nc None, _local_bus None -> fallback path

    @pytest.mark.asyncio
    async def test_verify_chain_returns_false_without_audit_table(self, sqlite_url: str) -> None:
        publisher = events.EventPublisher()
        # No audit_log table -> except -> False
        _drop_audit_log_table()
        assert await publisher.verify_chain() is False

    @pytest.mark.asyncio
    async def test_verify_chain_success_with_valid_chain(self, sqlite_url: str) -> None:
        _ensure_audit_log_table()
        try:
            publisher = events.EventPublisher()
            metadata = {"task_id": "t-1"}
            # البصمة تُبنى من نفس التمثيل القانوني الذي يعيد verify_chain بناءه.
            chain_hash = events.compute_chain_hash(
                events.GENESIS_HASH,
                events.canonical_audit_record(
                    event_id="e1",
                    timestamp=None,
                    event_type=None,
                    actor_type=None,
                    actor_id=None,
                    action=None,
                    metadata=metadata,
                ),
            )
            with db_cursor() as cur:
                cur.execute(
                    "INSERT INTO audit_log (event_id, chain_hash, prev_hash, metadata) "
                    "VALUES (?, ?, ?, ?)",
                    ("e1", chain_hash, events.GENESIS_HASH, _json.dumps(metadata)),
                )
            # valid chain -> returns True (covers loop + chain.verified)
            assert await publisher.verify_chain() is True
        finally:
            _drop_audit_log_table()

    @pytest.mark.asyncio
    async def test_verify_chain_detects_broken_chain(self, sqlite_url: str) -> None:
        _ensure_audit_log_table()
        try:
            publisher = events.EventPublisher()
            with db_cursor() as cur:
                cur.execute(
                    "INSERT INTO audit_log (event_id, chain_hash, prev_hash, metadata) "
                    "VALUES (?, ?, ?, ?)",
                    ("e1", "sha256:tampered", events.GENESIS_HASH, "{}"),
                )
            # tampered hash -> returns False (covers chain.broken branch)
            assert await publisher.verify_chain() is False
        finally:
            _drop_audit_log_table()

    def test_get_last_chain_hash_returns_existing_row(self, sqlite_url: str) -> None:
        _ensure_audit_log_table()
        try:
            with db_cursor() as cur:
                cur.execute(
                    "INSERT INTO audit_log (event_id, chain_hash, prev_hash, metadata) "
                    "VALUES (?, ?, ?, ?)",
                    ("e1", "sha256:existinghash", events.GENESIS_HASH, "{}"),
                )
            # existing row -> returns its chain_hash (covers `if row` True branch)
            assert events.get_last_chain_hash() == "sha256:existinghash"
        finally:
            _drop_audit_log_table()


# =============================================================================
# database.py
# =============================================================================
class TestDatabaseHelpers:
    """اختبارات دلالات SQLite — تطلب اللهجة صراحةً ولا تعتمد على البيئة."""

    def test_get_database_url_uses_env(self, sqlite_url: str) -> None:
        assert get_database_url() == sqlite_url
        assert get_database_url().startswith("sqlite")

    def test_get_database_url_default_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AMOS_DATABASE_URL", raising=False)
        url = get_database_url()
        assert url.startswith("sqlite:///")

    def test_is_postgres_false_for_sqlite(self, sqlite_url: str) -> None:
        assert _is_postgres() is False

    def test_is_postgres_true_for_postgres_url(self) -> None:
        # الفرع المقابل يُقاس بتمرير الرابط مباشرة، بلا اتصال شبكي
        assert _is_postgres("postgresql://user:pw@host:5432/db") is True

    def test_pg_connect_args_sqlite_branch(self, sqlite_url: str) -> None:
        # sqlite branch returns check_same_thread=False
        args = _pg_connect_args()
        assert args == {"check_same_thread": False}

    def test_pg_connect_args_postgres_branch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # الافتراضُ يُقاس بعد تنظيف البيئة: هذا الاختبار كان يقرأ بيئةَ المُشغِّل،
        # فلو صدَّر مُشغِّلٌ AMOS_DB_SSLMODE سقط الاختبارُ ولا عيبَ في الكود.
        monkeypatch.delenv("AMOS_DB_SSLMODE", raising=False)
        monkeypatch.delenv("AMOS_DB_CONNECT_TIMEOUT", raising=False)
        args = _pg_connect_args("postgresql://user:pw@host:5432/db")
        assert args["sslmode"] == "require"
        assert args["connect_timeout"] == 15

    def test_get_engine_returns_sqlite_engine(self, sqlite_url: str) -> None:
        try:
            engine = get_engine()
            assert engine is not None
            assert "sqlite" in str(engine.url)
        finally:
            reset_engine()

    def test_db_cursor_sqlite_path(self, sqlite_url: str) -> None:
        with db_cursor() as cur:
            assert cur.dialect == "sqlite"
            cur.execute("CREATE TABLE IF NOT EXISTS _t (id INTEGER)")
            cur.execute("INSERT INTO _t VALUES (1)")
        # context manager commits and closes without error


class TestPlaceholderTranslation:
    """طبقة المحاجيز القانونية — تُختبر بمعزل عن أي اتصال."""

    def test_sqlite_is_untouched(self) -> None:
        sql = "INSERT INTO t (a, b) VALUES (?, ?)"
        assert translate_placeholders(sql, DIALECT_SQLITE) == sql

    def test_postgres_uses_percent_s(self) -> None:
        sql = "INSERT INTO t (a, b) VALUES (?, ?)"
        assert (
            translate_placeholders(sql, DIALECT_POSTGRES) == "INSERT INTO t (a, b) VALUES (%s, %s)"
        )

    def test_postgres_escapes_literal_percent(self) -> None:
        sql = "SELECT * FROM t WHERE a LIKE '%x%' AND b = ?"
        assert (
            translate_placeholders(sql, DIALECT_POSTGRES)
            == "SELECT * FROM t WHERE a LIKE '%x%' AND b = %s"
        )

    def test_postgres_leaves_question_mark_inside_string(self) -> None:
        sql = "SELECT * FROM t WHERE a = 'why?' AND b = ?"
        assert (
            translate_placeholders(sql, DIALECT_POSTGRES)
            == "SELECT * FROM t WHERE a = 'why?' AND b = %s"
        )

    def test_audit_log_ddl_defined_for_both_dialects(self) -> None:
        assert "AUTOINCREMENT" in audit_log_ddl(DIALECT_SQLITE)
        assert "IDENTITY" in audit_log_ddl(DIALECT_POSTGRES)
        # العمود الرتيب موجود في اللهجتين لأن السلسلة ترتّب عليه
        assert "seq" in audit_log_ddl(DIALECT_SQLITE)
        assert "seq" in audit_log_ddl(DIALECT_POSTGRES)


# =============================================================================
# api_gateway/store.py
# =============================================================================
def _make_task() -> TaskDetails:
    return TaskDetails(
        task_id="task-test-1",
        type="analysis",
        description="تحليل تجريبي",
        priority="high",
        status="created",
        domain="finance",
        tenant_id="default",
        created_at="2026-08-15T00:00:00Z",
        result=None,
    )


class TestInMemoryTaskStore:
    def test_create_and_get(self) -> None:
        store = InMemoryTaskStore()
        task = _make_task()
        store.create(task)
        assert store.get("task-test-1") is not None
        assert store.get("missing") is None


class TestTaskModelMapping:
    """قرار E2.2-G: `TaskModel` هو النموذج الدائم الوحيد، والتحويل صريح."""

    def test_dto_task_id_maps_to_model_id(self) -> None:
        # الجوهر: لا يوجد عمود `task_id` في النموذج الدائم — المفتاح هو `id`.
        assert TASK_DTO_TO_MODEL_FIELDS["task_id"] == "id"
        assert "task_id" not in TASK_DTO_TO_MODEL_FIELDS.values()

    def test_mapping_covers_every_persisted_dto_field(self) -> None:
        from amos_federation.common.database import TaskModel

        columns = {c.name for c in TaskModel.__table__.columns}
        for column in TASK_DTO_TO_MODEL_FIELDS.values():
            assert column in columns, column

    def test_round_trip_preserves_identity(self) -> None:
        from amos_federation.common.database import TaskModel

        task = _make_task()
        row = TaskModel(**task_details_to_model_kwargs(task))
        assert row.id == task.task_id
        restored = task_model_to_details(row)
        assert restored.task_id == task.task_id
        assert restored.type == task.type
        assert restored.description == task.description
        assert restored.status == task.status

    def test_missing_domain_and_tenant_get_explicit_defaults(self) -> None:
        task = _make_task().model_copy(update={"domain": None, "tenant_id": None})
        values = task_details_to_model_kwargs(task)
        assert values["domain"] == "general"
        assert values["tenant_id"] == "default"


class TestDatabaseTaskStoreIsSourceOfTruth:
    """الذاكرة ليست مصدر حقيقة: تعذّر القاعدة يُرفع ولا يُخفى."""

    def test_create_then_get_persists_through_the_database(self, sqlite_url: str) -> None:
        store = DatabaseTaskStore()
        task = _make_task()
        store.create(task)
        # قراءة جديدة من نفس مصدر الحقيقة، لا من ذاكرة الكائن.
        fetched = DatabaseTaskStore().get(task.task_id)
        assert fetched is not None
        assert fetched.task_id == task.task_id
        assert fetched.description == task.description

    def test_get_returns_none_for_unknown_task(self, sqlite_url: str) -> None:
        assert DatabaseTaskStore().get("task-does-not-exist") is None

    def test_create_raises_instead_of_silent_memory_fallback(
        self, sqlite_url: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = DatabaseTaskStore()

        def _boom() -> None:
            raise RuntimeError("database unavailable")

        monkeypatch.setattr("amos_federation.services.api_gateway.store.get_session_factory", _boom)
        with pytest.raises(TaskStoreUnavailableError):
            store.create(_make_task())

    def test_get_raises_instead_of_silent_memory_fallback(
        self, sqlite_url: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = DatabaseTaskStore()

        class _BrokenSession:
            def query(self, *_args: object) -> object:
                raise RuntimeError("database unavailable")

            def close(self) -> None:
                return None

        monkeypatch.setattr(
            "amos_federation.services.api_gateway.store.get_session_factory",
            lambda: _BrokenSession,
        )
        with pytest.raises(TaskStoreUnavailableError):
            store.get("task-test-1")


# =============================================================================
# auth.py
# =============================================================================
def _creds(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


class TestAuthTokens:
    def test_create_and_decode_king_token(self) -> None:
        token = auth.create_king_token()
        data = auth.decode_token(token)
        assert data["role"] == auth.ROLE_KING
        assert data["sub"] == "king"

    def test_decode_invalid_token_raises_401(self) -> None:
        with pytest.raises(HTTPException) as exc:
            auth.decode_token("not-a-valid-token")
        assert exc.value.status_code == 401

    def test_require_king_allows_king(self) -> None:
        token = auth.create_king_token()
        data = auth.require_king(credentials=_creds(token))
        assert data["role"] == auth.ROLE_KING

    def test_require_king_rejects_citizen(self) -> None:
        token = auth.create_access_token(subject="u1", scopes=[], role=auth.ROLE_CITIZEN)
        with pytest.raises(HTTPException) as exc:
            auth.require_king(credentials=_creds(token))
        assert exc.value.status_code == 403

    def test_require_king_rejects_missing_credentials(self) -> None:
        with pytest.raises(HTTPException) as exc:
            auth.require_king(credentials=None)
        assert exc.value.status_code == 401

    def test_require_role_checker_king_bypass(self) -> None:
        checker = auth.require_role("admin")
        token = auth.create_king_token()
        data = checker(credentials=_creds(token))
        assert data["role"] == auth.ROLE_KING

    def test_require_role_checker_rejects_unauthorized_role(self) -> None:
        checker = auth.require_role("admin")
        token = auth.create_access_token(subject="u1", scopes=[], role=auth.ROLE_CITIZEN)
        with pytest.raises(HTTPException) as exc:
            checker(credentials=_creds(token))
        assert exc.value.status_code == 403


# =============================================================================
# event_schemas.py
# =============================================================================
class TestEventSchemas:
    def test_load_event_schema_returns_dict(self) -> None:
        schema = load_event_schema("task.created")
        assert schema["type"] == "object"

    def test_validate_event_rejects_non_dict(self) -> None:
        assert validate_event("task.created", "not-a-dict") is False

    def test_validate_event_rejects_wrong_const(self) -> None:
        payload = {
            "event_id": "e1",
            "timestamp": "2026-08-15T00:00:00Z",
            "event_type": "wrong.type",
            "source": "api-gateway",
            "data": {"task_id": "t1", "type": "analysis", "description": "x"},
            "chain_hash": "sha256:" + "a" * 64,
        }
        assert validate_event("task.created", payload) is False

    def test_validate_event_unknown_type_returns_false(self) -> None:
        assert validate_event("unknown.event.type", {"a": 1}) is False

    def test_has_required_fields_non_dict(self) -> None:
        assert _has_required_fields({"required": ["a"]}, 42) is False


class TestConnectArgsHaveOneSource:
    """معاملاتُ الاتّصال تُقرأ من موضعٍ واحد، ولا تُكتَب `sslmode` بيدٍ في مُنشِئٍ.

    ثلاثةُ مُنشِئي محرّكٍ كانوا يكتبون `{"sslmode": "require"}` بأيديهم، فكان
    المستودعُ يُلزم TLS حتى على حاويةٍ محليّةٍ لا TLS لها، فتسقط حزمةُ
    PostgreSQL في CI بـ«server does not support SSL, but SSL was required»
    قبل أن يُنفَّذ اختبارٌ واحد. والحارسُ نصّيٌّ لأنّ العيبَ نصّيٌّ: نسخةٌ رابعةٌ
    مكتوبةٌ بيدٍ تعيد العيبَ ولو نجحت كلُّ الاختبارات السلوكيّة.
    """

    _BUILDERS = (
        "amos_federation/common/event_bus.py",
        "amos_federation/common/durable_event_bus.py",
        "amos_federation/services/royal/main.py",
    )

    def _src_root(self):
        import amos_federation

        return pathlib.Path(amos_federation.__file__).resolve().parent.parent

    def test_only_database_module_names_sslmode(self) -> None:
        root = self._src_root()
        offenders = [
            rel for rel in self._BUILDERS if '"sslmode"' in (root / rel).read_text("utf-8")
        ]
        assert offenders == []

    def test_database_module_is_the_single_source(self) -> None:
        text = (self._src_root() / "amos_federation/common/database.py").read_text("utf-8")
        assert text.count('"sslmode"') == 1

    def test_public_connect_args_honours_sslmode_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AMOS_DB_SSLMODE", "disable")
        args = database.connect_args("postgresql://u:p@localhost:5432/d")
        assert args["sslmode"] == "disable"

    def test_public_connect_args_defaults_to_require_for_postgres(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("AMOS_DB_SSLMODE", raising=False)
        args = database.connect_args("postgresql://u:p@host/d")
        assert args["sslmode"] == "require"

    def test_public_connect_args_gives_sqlite_thread_flag_not_ssl(self) -> None:
        args = database.connect_args("sqlite:///./x.db")
        assert args == {"check_same_thread": False}
