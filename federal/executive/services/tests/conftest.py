# AMOS-Federation test configuration
# الهدف: ضمان بيئة اختبار نظيفة ومنع Flaky Tests
# النطاق: federal/executive/services/tests
# المالك: federal/executive/services
# تاريخ الإنشاء: 2026-08-15

"""Pytest configuration for AMOS-Federation tests.

Forces a clean test database state before each session to prevent
flaky tests caused by stale SQLite files. Never touches production DB.
"""

import contextlib
import os
import shutil
from pathlib import Path

import pytest

# Force test environment
os.environ["AMOS_ENVIRONMENT"] = "test"

# قرار معماري (E2.2-G):
# قاعدة الاختبار الافتراضية هي SQLite دائمًا، للحزمة كلها، بلا استثناء.
# AMOS_RUN_POSTGRES_TESTS=1 لم يعد يحوّل كل الاختبارات إلى PostgreSQL: الاختبارات
# المكتوبة لدلالات SQLite لا تقبل هذا التحويل، وتحويلها قسرًا كان يُنتج فشلًا
# زائفًا وإرهاقًا لتجمّع اتصالات المزوّد. من يريد PostgreSQL يطلبه صراحةً عبر
# التجهيزة postgres_url أدناه.
SQLITE_TEST_URL = "sqlite:///amos_federation_test.db"
os.environ["AMOS_DATABASE_URL"] = SQLITE_TEST_URL

os.environ.setdefault("AMOS_JWT_SECRET", "test_secret_at_least_32_characters_long")
os.environ.setdefault("AMOS_CLAUDE_API_KEY", "test_key_not_real")

# Test-only database file (never touch production files)
TEST_DB_FILE = "amos_federation_test.db"


def postgres_tests_enabled() -> bool:
    """اختبارات PostgreSQL مفعّلة صراحةً فقط عند توفر العَلَم والرابط معًا."""
    return os.environ.get("AMOS_RUN_POSTGRES_TESTS") == "1" and os.environ.get(
        "AMOS_TEST_DATABASE_URL", ""
    ).startswith("postgresql")


@pytest.fixture
def sqlite_url(monkeypatch: pytest.MonkeyPatch) -> str:
    """تثبيت لهجة SQLite صراحةً لهذا الاختبار.

    الاختبارات التي تؤكّد دلالات SQLite تستخدم هذه التجهيزة بدلًا من الاعتماد على
    البيئة المحيطة، فتصبح نتيجتها مستقلة عن أي متغيّر خارجي.
    """
    from amos_federation.common import database

    monkeypatch.setenv("AMOS_DATABASE_URL", SQLITE_TEST_URL)
    database.reset_engine()
    yield SQLITE_TEST_URL
    database.reset_engine()


@pytest.fixture
def postgres_url(monkeypatch: pytest.MonkeyPatch) -> str:
    """تحويل هذا الاختبار وحده إلى PostgreSQL الحقيقي، ثم إعادة البيئة كما كانت.

    يتخطّى الاختبار إن لم تكن اختبارات PostgreSQL مفعّلة صراحةً.
    """
    if not postgres_tests_enabled():
        pytest.skip(
            "Set AMOS_RUN_POSTGRES_TESTS=1 and AMOS_TEST_DATABASE_URL=postgresql://... to run"
        )
    from amos_federation.common import database

    url = os.environ["AMOS_TEST_DATABASE_URL"]
    monkeypatch.setenv("AMOS_DATABASE_URL", url)
    database.reset_engine()
    yield url
    database.reset_engine()


# ── تنظيف الوكلاء مع رسمهم المرجعي (R7-A) ────────────────────────────────
# منذ R7 صار في القاعدة رسمٌ مرجعي مفروض فعلًا: `state_officials.agent_id`
# يشير إلى `agents.id` بـ`ON DELETE RESTRICT`، والفرض مُشغَّل في SQLite أيضًا.
# فـ`DELETE FROM agents` المجرَّد لم يعد يمرّ حين يكون هناك مسؤولٌ مُقلَّد —
# وهذا هو القيد يعمل، لا عيبًا فيه. الحلّ حذف التابع قبل المتبوع، من مكان واحد،
# حتى لا يُكرَّر الترتيب في ثمانية ملفات وينساه تاسعٌ غدًا.
# الترتيب مقصود: القرار يشير إلى القضية والمنصب، والقضية تشير إلى المنصب والوكيل،
# والمنصب يشير إلى الوكيل. فالحذف من الأخصّ إلى الأعمّ وإلّا رفضه قيدٌ مرجعي مفروض.
# ومنذ R7-B دخل المال في الرسم: `state_transactions` تشير إلى `state_officials`
# و`tasks` و`state_decisions`، و`state_ledger_entries` تشير إلى الحركات. فصار
# الأخصّ هو القيد ثم الحركة، وقبل القرار لا بعده.
#: جداولُ القضاء الفدرالي (R7-D) — من الفرع إلى الأصل.
#:
#: `state_court_judges.official_id` يشير إلى `state_officials`، و
#: `state_ruling_enforcements.task_id` يشير إلى `tasks`، وكلاهما
#: `ON DELETE RESTRICT`. فحذفُ المسؤولين أو المهامّ قبل هذه الصفوف يرفضه قيدٌ
#: مفروض — لا عيبًا بل عملَ القيد. والترتيب هنا هو ترتيبُ الحذف الصحيح، ومكانُه
#: هذا الملفّ وحده حتى لا يُكرَّر في كل ملفّ اختبار.
JUDICIARY_TABLES: tuple[str, ...] = (
    "state_ruling_enforcements",
    "state_rulings",
    "state_case_proceedings",
    "state_case_evidence",
    "state_case_claims",
    "state_case_parties",
    "state_legal_cases",
    "state_court_judges",
    "state_courts",
)


AGENT_DEPENDENT_TABLES: tuple[str, ...] = (
    # R7-D: القضاء أوّلًا — تقليدُ القاضي يشير إلى `state_officials`.
    *JUDICIARY_TABLES,
    # R7-C: إسناد القرار والحركة يشير إلى صفوفهما بمفتاحٍ مفروض، وشغل المناصب
    # يشير إلى `state_officials` — فالحذف يبدأ من الفروع لا من الأصول.
    "state_transaction_authority",
    "state_decision_provenance",
    "state_ledger_entries",
    "state_transactions",
    "state_allocations",
    "state_decisions",
    "state_cases",
    "state_official_positions",
    "state_officials",
)


#: ما يشير إلى `tasks` بمفتاح مفروض — القضايا وقراراتها (R7-A، الوحدة 2)
#: وحركات الخزانة (R7-B). كل قضية تحمل `task_id NOT NULL`، وكل حركةٍ نتجت عن
#: تنفيذ مهمّة تحمل `task_id`، فحذف صفوف المهامّ قبلها يرفضه القيد.
#: و`state_allocations` قبل `state_decisions` لأن التخصيص قد يشير إلى قرار.
TASK_DEPENDENT_TABLES: tuple[str, ...] = (
    # R7-D: أثرُ تنفيذ الحكم يحمل `task_id` بمفتاحٍ مفروض.
    *JUDICIARY_TABLES,
    "state_transaction_authority",
    "state_decision_provenance",
    "state_ledger_entries",
    "state_transactions",
    "state_allocations",
    "state_decisions",
    "state_cases",
)


def _delete_existing(session, tables: tuple[str, ...]) -> None:  # noqa: ANN001
    """احذف من الجداول الموجودة فقط — بعض الاختبارات تعمل على مخطَّط جزئي."""
    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy import text as sa_text

    inspector = sa_inspect(session.get_bind())
    for table in tables:
        if inspector.has_table(table):
            session.execute(sa_text(f"DELETE FROM {table}"))  # noqa: S608 — أسماء ثابتة


def purge_tasks(session) -> None:  # noqa: ANN001 — Session من SQLAlchemy
    """احذف المهامّ وما يشير إليها بالترتيب الذي يقبله قيدٌ مرجعي مفروض."""
    from sqlalchemy import text as sa_text

    _delete_existing(session, TASK_DEPENDENT_TABLES)
    session.execute(sa_text("DELETE FROM tasks"))


def purge_agents(session) -> None:  # noqa: ANN001 — Session من SQLAlchemy
    """احذف الوكلاء وما يشير إليهم بالترتيب الذي يقبله قيدٌ مرجعي مفروض."""
    from sqlalchemy import text as sa_text

    _delete_existing(session, AGENT_DEPENDENT_TABLES)
    session.execute(sa_text("DELETE FROM agents"))


def _cleanup_test_db(workspace: Path) -> None:
    """Remove only the test database file, never production files."""
    for db_file in workspace.glob(TEST_DB_FILE):
        with contextlib.suppress(OSError):
            db_file.unlink()
    # Also clean test-related journal files
    for pattern in (TEST_DB_FILE + "-*", TEST_DB_FILE + "-wal", TEST_DB_FILE + "-shm"):
        for f in workspace.glob(pattern):
            with contextlib.suppress(OSError):
                f.unlink()
    # Clean egg-info cache if present
    for egg_dir in workspace.glob("*.egg-info"):
        with contextlib.suppress(OSError):
            shutil.rmtree(egg_dir, ignore_errors=True)


def pytest_sessionstart(session):
    """Clean up test database before test session starts."""
    workspace = Path(__file__).resolve().parent.parent
    _cleanup_test_db(workspace)


def pytest_sessionfinish(session, exitstatus):
    """Clean up test database after test session ends."""
    workspace = Path(__file__).resolve().parent.parent
    _cleanup_test_db(workspace)
