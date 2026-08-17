"""
اختبارات R7-B — الخزانة الفدرالية ودفتر المال العام
الهدف: التحقّق أن المال يتحرّك بطرفين متوازنين، وبحدودٍ مقروءة من الدفتر، وبمنصبٍ مسؤول
النطاق: federal/executive/services
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17 (R7-B)

اختبارات مركَّزة على نطاق واحد. وأهمّها ما يفحص ما يُدَّعى كثيرًا في الأنظمة
المالية ولا يُفرَض:

1. **لا حركة بطرف واحد**: كل حركة لها قيدان متوازنان، مقروءان من القاعدة بعد الكتابة.
2. **لا عدّاد**: الأرصدة والمخصَّص والمصروف تُشتقّ من الصفوف — والعكس لا يعدّل رقمًا.
3. **لا `float` في المال**: `Decimal` وحده، ورفضٌ صريح للعائم في المدخل.
4. **لا مال بلا منصب**: `official_id` مفتاح أجنبي إلزامي، ولا إعفاء سياديّ.
5. **لا تعديل تاريخ**: التصحيح حركةُ عكسٍ، والعكس مرّتين يرفضه قيدٌ في القاعدة.
6. حدود القاعدة نفسها (`CHECK`/`UNIQUE`/`FK`) مفروضة على SQLite أيضًا.

7. **القفل قبل الفحص** (23–29): كل فحصٍ يقرأ ثم يكتب يقفل أصله أولًا، بترتيبٍ
   قانوني واحد وبمهلة محدودة. وهذه الاختبارات تفحص العبارة والترتيب والمهلة
   وترجمة الخطأ — **لا** تفحص التزامن نفسه: SQLite يتجاهل `FOR UPDATE`، فدلالة
   المنع الفعلية تُتحقَّق على PostgreSQL وتُسجَّل في وثيقة R7-B لا هنا.

ما **لا** يفحصه هذا الملفّ ولا يُدَّعى: قناة دفعٍ خارجية، وإقفال فترات، وقوائم
مالية، وتنفيذُ حجزٍ متزامن حقيقي بجلستين.
"""

from __future__ import annotations

import inspect
import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import DBAPIError, IntegrityError

from amos_federation.common.database import get_session_factory, init_db
from amos_federation.common.durable_event_bus import get_durable_event_bus
from amos_federation.common.event_bus import EVENT_CONTRACTS, validate_event
from amos_federation.common.persistent import PersistentAuditStore
from amos_federation.common.principal import (
    DEFAULT_TENANT,
    AuthorizationContext,
    Principal,
    TenantIsolationError,
)
from amos_federation.common.registry import SERVICES
from amos_federation.services.executive_core.agent_identity import register_identity
from amos_federation.services.executive_core.dispatcher import WILDCARD, register_agent
from amos_federation.services.executive_core.engine import reset_executive_core
from amos_federation.services.governance.security import DEFAULT_ROLES
from amos_federation.services.government_services.models import CaseModel, DecisionModel
from amos_federation.services.government_services.service import (
    GovernmentServices,
    get_government_services,
    reset_government_services,
)
from amos_federation.services.national_registry.models import (
    DecisionProvenanceModel,
    TransactionAuthorityModel,
)
from amos_federation.services.national_registry.resolver import ForgedAuthorityError
from amos_federation.services.state_registry.service import (
    StateRegistry,
    get_state_registry,
    reset_state_registry,
)
from amos_federation.services.state_treasury.authorization import (
    OFFICE_BOUND_OPERATIONS,
    TREASURY_PERMISSIONS,
    OfficeAuthorityError,
    RegistryAuthorizationError,
)
from amos_federation.services.state_treasury.main import _http
from amos_federation.services.state_treasury.models import (
    ACCOUNT_KINDS,
    NORMAL_BALANCE,
    TRANSACTION_KINDS,
    TREASURY_TABLES,
    AccountModel,
    AllocationModel,
    BudgetModel,
    LedgerEntryModel,
    TransactionModel,
    TreasuryModel,
)
from amos_federation.services.state_treasury.money import (
    MONEY_MAX,
    MoneyError,
    format_money,
    money_sum,
    normalize_currency,
    to_money,
)
from amos_federation.services.state_treasury.service import (
    DISBURSEMENT_TASK_TYPE,
    EVENT_TRANSACTION_POSTED,
    EVENT_TRANSACTION_REVERSED,
    LOCK_ORDER,
    LOCK_TIMEOUT,
    PG_LOCK_NOT_AVAILABLE,
    TREASURY_EVENTS,
    AllocationExceededError,
    BudgetExceededError,
    CurrencyMismatchError,
    DecisionNotAuthorizingError,
    DuplicateCodeError,
    EntityStateError,
    InsufficientFundsError,
    OfficialNotFoundError,
    StateTreasury,
    TransactionReversedError,
    TreasuryContentionError,
    TreasuryError,
    _row_locks_supported,
    get_state_treasury,
    lock_query,
    reset_state_treasury,
)
from tests.conftest import purge_agents, purge_tasks

SRC = Path(__file__).resolve().parents[1] / "src" / "amos_federation"
TREASURY_SRC = SRC / "services" / "state_treasury"
MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "007_state_treasury.sql"

_ROLE_PERMISSIONS = {role["role_id"]: tuple(role["permissions"]) for role in DEFAULT_ROLES}


def _strip_comments(source: str) -> str:
    """أزِل التعليقات وسلاسل التوثيق قبل أي تأكيد على المصدر.

    الدرس من R6 وR7-A: حرسٌ يبحث عن نصٍّ في المصدر قد يمرّ أو يفشل بسبب **تعليق**
    يشرح الأمر لا بسبب شيفرة تفعله. وهذا الملفّ مملوء بتعليقات تذكر `float`
    و`SUM` لتنفيهما — فلو لم تُنزَع لَفشل الحرس على نفسه.
    """
    no_docstrings = re.sub(r'"""(?:.|\n)*?"""', "", source)
    return "\n".join(line.split("#", 1)[0] for line in no_docstrings.splitlines())


def _context(
    role_id: str,
    *,
    tenant_id: str | None = None,
    expires_at: datetime | None = None,
    username: str = "r7b-user",
) -> AuthorizationContext:
    """سياق `SESSION_VERIFIED` بصلاحيات الدور كما هي مزروعة — لا كما يشتهي الاختبار."""
    return AuthorizationContext.from_principal(
        Principal.from_session_record(
            session_id=f"r7bt-{role_id}-{username}",
            username=f"{username}-{role_id}",
            role_id=role_id,
            permissions=_ROLE_PERMISSIONS[role_id],
            expires_at=expires_at,
            tenant_id=tenant_id,
        )
    )


@pytest.fixture(autouse=True)
def _fresh_state() -> None:
    """قاعدة نظيفة من صفوف النطاق قبل كل اختبار — الملف مشترك بين الاختبارات.

    الترتيب مقصود ومفروض: القيد قبل الحركة، والحركة قبل التخصيص والموازنة
    والخزانة والحساب، لأن كل واحدة تشير إلى ما بعدها بـ`ON DELETE RESTRICT`.
    """
    init_db()
    session = get_session_factory()()
    try:
        # R7-C: إسناد الحركة والقرار يشير إليهما بـ`ON DELETE RESTRICT`، فيُحذف أولًا.
        session.query(TransactionAuthorityModel).delete()
        session.query(DecisionProvenanceModel).delete()
        session.query(LedgerEntryModel).delete()
        # حركات العكس تشير إلى حركاتٍ أخرى في نفس الجدول، وحذفٌ واحدٌ لكل الصفوف
        # يفشل على مفتاحها الأجنبي الذاتي — فتُحذف العواكس أولًا.
        session.query(TransactionModel).filter(
            TransactionModel.reverses_transaction_id.isnot(None)
        ).delete()
        session.flush()
        session.query(TransactionModel).delete()
        session.query(AllocationModel).delete()
        session.query(BudgetModel).delete()
        session.query(AccountModel).delete()
        session.query(TreasuryModel).delete()
        session.query(DecisionModel).delete()
        session.query(CaseModel).delete()
        purge_tasks(session)
        purge_agents(session)
        session.commit()
    finally:
        session.close()
    reset_executive_core()
    reset_state_registry()
    reset_government_services()
    reset_state_treasury()


@pytest.fixture
def registry() -> StateRegistry:
    return get_state_registry()


@pytest.fixture
def gov() -> GovernmentServices:
    return get_government_services()


@pytest.fixture
def treasury() -> StateTreasury:
    return get_state_treasury()


@pytest.fixture
def crown() -> AuthorizationContext:
    """التاج — يملك `*` فيمرّ في كل حدّ عبر `has_permission` نفسها."""
    return _context("king")


def _agent(tenant_id: str = DEFAULT_TENANT) -> str:
    """وكيلٌ حقيقي في `agents` — المنصب يشير إليه بمفتاح أجنبي."""
    agent_id = f"agent-r7bt-{uuid.uuid4().hex[:10]}"
    register_identity(agent_id, f"وكيل {agent_id}", "executor", tenant_id=tenant_id)
    return agent_id


def _worker() -> str:
    """عاملٌ مؤهَّل للتوزيع — بلا واحدٍ كهذا تفشل المهمّة، وهذا سلوك صادق."""
    worker_id = f"worker-r7bt-{uuid.uuid4().hex[:8]}"
    register_agent(worker_id, f"عامل {worker_id}", "worker", allowed_tools=[WILDCARD])
    return worker_id


def _code(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


class Fiscal:
    """مجموعة كيانات مالية جاهزة — مؤسسة وخزانة وحسابات وموازنة ومنصب."""

    def __init__(self, **kwargs: object) -> None:
        self.__dict__.update(kwargs)


def _fiscal(
    treasury: StateTreasury,
    registry: StateRegistry,
    crown: AuthorizationContext,
    *,
    currency: str = "SAR",
    limit_amount: str = "100000.0000",
    funding: str | None = "50000.0000",
) -> Fiscal:
    """ابنِ نطاقًا ماليًّا كاملًا بعملياتٍ حقيقية — لا صفوفًا مزروعة يدويًّا."""
    institution = registry.register_institution(
        context=crown,
        code=_code("INST"),
        name="وزارة المالية",
        kind="ministry",
        branch="executive",
    )
    official = registry.appoint_official(
        context=crown,
        agent_id=_agent(),
        institution_code=institution["code"],
        title="أمين الخزانة",
    )
    trs = treasury.establish_treasury(
        context=crown,
        code=_code("TRS"),
        name="الخزانة العامة",
        currency=currency,
        institution_code=institution["code"],
    )
    cash = treasury.open_account(
        context=crown,
        treasury_code=trs["code"],
        code=_code("CASH"),
        name="الحساب النقدي",
        kind="cash",
        institution_code=institution["code"],
    )
    revenue = treasury.open_account(
        context=crown,
        treasury_code=trs["code"],
        code=_code("REV"),
        name="حساب الإيرادات",
        kind="revenue",
        institution_code=institution["code"],
    )
    expense = treasury.open_account(
        context=crown,
        treasury_code=trs["code"],
        code=_code("EXP"),
        name="حساب المصروفات",
        kind="expense",
        institution_code=institution["code"],
    )
    budget = treasury.create_budget(
        context=crown,
        treasury_code=trs["code"],
        institution_code=institution["code"],
        code=_code("BDG"),
        period="2026",
        limit_amount=limit_amount,
    )
    funded = None
    if funding is not None:
        funded = treasury.post_funding(
            context=crown,
            treasury_code=trs["code"],
            cash_account_code=cash["code"],
            revenue_account_code=revenue["code"],
            amount=funding,
            purpose="تمويل افتتاحي",
            official_id=official["id"],
        )
    return Fiscal(
        institution=institution,
        official=official,
        treasury=trs,
        cash=cash,
        revenue=revenue,
        expense=expense,
        budget=budget,
        funded=funded,
    )


def _allocate(
    treasury: StateTreasury, crown: AuthorizationContext, fiscal: Fiscal, amount: str = "20000.0000"
) -> dict:
    return treasury.allocate(
        context=crown,
        budget_code=fiscal.budget["code"],
        account_code=fiscal.cash["code"],
        purpose="تشغيل",
        amount=amount,
        official_id=fiscal.official["id"],
    )


def _approved_decision(
    gov: GovernmentServices,
    registry: StateRegistry,
    crown: AuthorizationContext,
    fiscal: Fiscal,
) -> dict:
    """قرارٌ حكوميّ موافقٌ حقيقيّ في مؤسسة الموازنة — عبر مسار R7-A كاملًا."""
    _worker()
    service = gov.publish_service(
        context=crown,
        institution_code=fiscal.institution["code"],
        code=_code("SVC"),
        name="اعتماد مصروف",
    )
    case = gov.open_case(
        context=crown,
        institution_code=fiscal.institution["code"],
        service_code=service["code"],
        applicant_agent_id=_agent(),
        subject="طلب اعتماد صرف",
    )
    gov.process_case(context=crown, reference=case["reference"])
    return gov.decide_case(
        context=crown,
        reference=case["reference"],
        outcome="approved",
        rationale="مستوفٍ للشروط",
        official_id=fiscal.official["id"],
    )


# ── 1. تأسيس الخزانة ──────────────────────────────────────────────────────


def test_01_establish_treasury_persists_real_row(
    treasury: StateTreasury, registry: StateRegistry, crown: AuthorizationContext
) -> None:
    """الخزانة صفٌّ حقيقي في القاعدة، بعملةٍ مُوحَّدة وأثرٍ مُدقَّق."""
    institution = registry.register_institution(
        context=crown,
        code=_code("INST"),
        name="وزارة المالية",
        kind="ministry",
        branch="executive",
    )
    result = treasury.establish_treasury(
        context=crown,
        code=_code("TRS"),
        name="الخزانة العامة",
        currency="sar",
        institution_code=institution["code"],
    )
    assert result["currency"] == "SAR", "العملة تُوحَّد إلى ثلاثة أحرف كبيرة"
    assert result["status"] == "active"
    assert result["institution_id"] == institution["id"]
    assert result["audit_id"] and result["event_id"]

    session = get_session_factory()()
    try:
        row = session.query(TreasuryModel).filter(TreasuryModel.id == result["id"]).one()
        assert row.currency == "SAR"
        assert row.established_by == crown.principal_id
    finally:
        session.close()

    with pytest.raises(DuplicateCodeError):
        treasury.establish_treasury(
            context=crown,
            code=result["code"],
            name="خزانة ثانية بنفس الرمز",
            currency="SAR",
            institution_code=institution["code"],
        )


# ── 2. الحسابات ───────────────────────────────────────────────────────────


def test_02_open_account_has_no_stored_balance(
    treasury: StateTreasury, registry: StateRegistry, crown: AuthorizationContext
) -> None:
    """الحساب يُفتح بلا رصيد ابتدائي — ولا عمود رصيد فيه أصلًا."""
    fiscal = _fiscal(treasury, registry, crown, funding=None)

    assert not hasattr(AccountModel, "balance"), "لا عمود رصيد مخزَّن في الحساب"
    columns = {c.name for c in AccountModel.__table__.columns}
    assert "balance" not in columns and "current_balance" not in columns

    for kind in ACCOUNT_KINDS:
        assert kind in NORMAL_BALANCE, f"كل نوع حساب له اتجاه رصيد طبيعي: '{kind}'"

    balance = treasury.account_balance(
        context=crown, treasury_code=fiscal.treasury["code"], account_code=fiscal.cash["code"]
    )
    assert balance["balance"] == "0.0000", "حسابٌ بلا قيود رصيده صفر مشتقٌّ لا مخزَّن"
    assert balance["entries_count"] == 0
    assert balance["currency"] == fiscal.treasury["currency"], "الحساب يرث عملة خزانته"

    with pytest.raises(TreasuryError, match="نوع حساب غير معروف"):
        treasury.open_account(
            context=crown,
            treasury_code=fiscal.treasury["code"],
            code=_code("BAD"),
            name="نوع مخترع",
            kind="crypto-wallet",
        )


# ── 3. الموازنة ───────────────────────────────────────────────────────────


def test_03_budget_totals_are_derived_not_stored(
    treasury: StateTreasury, registry: StateRegistry, crown: AuthorizationContext
) -> None:
    """الموازنة تحمل حدًّا فقط — والمخصَّص والمصروف والمتبقّي مشتقّة من الصفوف."""
    fiscal = _fiscal(treasury, registry, crown, limit_amount="100000")

    columns = {c.name for c in BudgetModel.__table__.columns}
    for forbidden in ("allocated", "spent", "remaining", "available"):
        assert forbidden not in columns, f"عمود مجموع مخزَّن '{forbidden}' يصير مصدر حقيقة ثانيًا"

    balance = treasury.budget_balance(context=crown, budget_code=fiscal.budget["code"])
    assert balance["derived"] is True
    assert balance["limit_amount"] == "100000.0000"
    assert balance["allocated"] == "0.0000"
    assert balance["spent"] == "0.0000"
    assert balance["remaining"] == "100000.0000"

    _allocate(treasury, crown, fiscal, amount="20000")
    after = treasury.budget_balance(context=crown, budget_code=fiscal.budget["code"])
    assert after["allocated"] == "20000.0000", "المخصَّص ظهر من صفّ التخصيص لا من عدّاد"
    assert after["unallocated"] == "80000.0000"
    assert after["spent"] == "0.0000", "التخصيص إذنٌ لا حركة مال"

    with pytest.raises(TreasuryError, match="فترة غير مقبولة"):
        treasury.create_budget(
            context=crown,
            treasury_code=fiscal.treasury["code"],
            institution_code=fiscal.institution["code"],
            code=_code("BDG"),
            period="سنة القادمة",
            limit_amount="1000",
        )


# ── 4. التخصيص ────────────────────────────────────────────────────────────


def test_04_allocation_requires_office_and_respects_budget_limit(
    treasury: StateTreasury, registry: StateRegistry, crown: AuthorizationContext
) -> None:
    """التخصيص يُنسب إلى منصب في مؤسسة الموازنة، ومجموع التخصيصات لا يتجاوز الحدّ."""
    fiscal = _fiscal(treasury, registry, crown, limit_amount="1000")

    allocation = _allocate(treasury, crown, fiscal, amount="600")
    assert allocation["amount"] == "600.0000"
    assert allocation["status"] == "active"
    assert allocation["audit_id"] and allocation["event_id"]

    # ثانيةٌ تمرّ لأن المجموع ما زال تحت الحدّ
    _allocate(treasury, crown, fiscal, amount="400")

    # وثالثةٌ ترفض: المجموع مقروءٌ من الصفوف لا من رقمٍ في الموازنة
    with pytest.raises(BudgetExceededError, match="يتجاوز المتاح في الموازنة"):
        _allocate(treasury, crown, fiscal, amount="1")

    other = registry.register_institution(
        context=crown,
        code=_code("INST"),
        name="وزارة أخرى",
        kind="ministry",
        branch="executive",
    )
    foreign_official = registry.appoint_official(
        context=crown,
        agent_id=_agent(),
        institution_code=other["code"],
        title="مسؤول مؤسسة أخرى",
    )
    with pytest.raises(OfficeAuthorityError):
        treasury.allocate(
            context=crown,
            budget_code=fiscal.budget["code"],
            account_code=fiscal.cash["code"],
            purpose="تخصيص من مؤسسة أخرى",
            amount="1",
            official_id=foreign_official["id"],
        )

    with pytest.raises(OfficialNotFoundError):
        treasury.allocate(
            context=crown,
            budget_code=fiscal.budget["code"],
            account_code=fiscal.cash["code"],
            purpose="تخصيص بمنصب وهمي",
            amount="1",
            official_id="off-ghost",
        )


# ── 5. الحركة: طرفان متوازنان دائمًا ──────────────────────────────────────


def test_05_transaction_writes_two_balanced_ledger_legs(
    treasury: StateTreasury, registry: StateRegistry, crown: AuthorizationContext
) -> None:
    """كل حركة لها قيدان: مَدينٌ ودائن بنفس المبلغ — مقروءان من القاعدة بعد الكتابة."""
    fiscal = _fiscal(treasury, registry, crown, funding="50000")
    funded = fiscal.funded
    assert funded["kind"] == "funding"
    assert funded["status"] == "posted"
    assert funded["amount"] == "50000.0000"
    assert funded["official_id"] == fiscal.official["id"], "لا حركة بلا منصب مسؤول"
    assert funded["posted_by"] == crown.principal_id

    session = get_session_factory()()
    try:
        entries = (
            session.query(LedgerEntryModel)
            .filter(LedgerEntryModel.transaction_id == funded["id"])
            .all()
        )
        assert len(entries) == 2, "لا حركة بطرف واحد"
        directions = sorted(e.direction for e in entries)
        assert directions == ["credit", "debit"]
        debits = money_sum(e.amount for e in entries if e.direction == "debit")
        credits = money_sum(e.amount for e in entries if e.direction == "credit")
        assert debits == credits == Decimal("50000.0000")
        assert all(isinstance(e.amount, Decimal) for e in entries), "المال Decimal من القاعدة"
        debit_leg = next(e for e in entries if e.direction == "debit")
        credit_leg = next(e for e in entries if e.direction == "credit")
        assert debit_leg.account_id == fiscal.cash["id"], "التمويل يُدين النقدي"
        assert credit_leg.account_id == fiscal.revenue["id"], "ويُدائن الإيراد"
    finally:
        session.close()

    cash_balance = treasury.account_balance(
        context=crown, treasury_code=fiscal.treasury["code"], account_code=fiscal.cash["code"]
    )
    assert cash_balance["balance"] == "50000.0000"
    assert cash_balance["normal_balance"] == "debit"

    revenue_balance = treasury.account_balance(
        context=crown, treasury_code=fiscal.treasury["code"], account_code=fiscal.revenue["code"]
    )
    assert revenue_balance["balance"] == "50000.0000", "الإيراد يزيده الدائن"
    assert revenue_balance["normal_balance"] == "credit"

    file = treasury.transaction_file(context=crown, reference=funded["reference"])
    assert file["balanced"] is True
    assert file["total_debits"] == file["total_credits"] == "50000.0000"
    assert file["reversed_by"] is None

    # حركة بطرفٍ واحد مكرَّر مرفوضة في البوّابة الوحيدة للكتابة
    with pytest.raises(TreasuryError, match="ليس إيراديًّا"):
        treasury.post_funding(
            context=crown,
            treasury_code=fiscal.treasury["code"],
            cash_account_code=fiscal.cash["code"],
            revenue_account_code=fiscal.cash["code"],
            amount="1",
            purpose="طرفان من حساب واحد",
            official_id=fiscal.official["id"],
        )


# ── 6. عدم كفاية الرصيد ───────────────────────────────────────────────────


def test_06_disbursement_refused_when_cash_balance_insufficient(
    treasury: StateTreasury, registry: StateRegistry, crown: AuthorizationContext
) -> None:
    """الصرف يتوقّف عند رصيد الحساب الفعلي — لا عند حدّ الموازنة وحده."""
    fiscal = _fiscal(treasury, registry, crown, limit_amount="100000", funding="1000")
    allocation = _allocate(treasury, crown, fiscal, amount="50000")

    with pytest.raises(InsufficientFundsError, match="لا يكفي"):
        treasury.disburse(
            context=crown,
            allocation_id=allocation["id"],
            expense_account_code=fiscal.expense["code"],
            amount="1500",
            purpose="صرف يتجاوز الرصيد",
            official_id=fiscal.official["id"],
        )

    # وبقدر الرصيد يمرّ
    posted = treasury.disburse(
        context=crown,
        allocation_id=allocation["id"],
        expense_account_code=fiscal.expense["code"],
        amount="1000",
        purpose="صرف بقدر الرصيد",
        official_id=fiscal.official["id"],
    )
    assert posted["amount"] == "1000.0000"

    balance = treasury.account_balance(
        context=crown, treasury_code=fiscal.treasury["code"], account_code=fiscal.cash["code"]
    )
    assert balance["balance"] == "0.0000", "الصرف يُدائن النقدي فينزل رصيده"

    session = get_session_factory()()
    try:
        assert (
            session.query(LedgerEntryModel)
            .filter(LedgerEntryModel.transaction_id == posted["id"])
            .count()
            == 2
        )
    finally:
        session.close()

    # حسابٌ مُجمَّد لا يمرّ منه مال — الحالة تُفحص في البوّابة الوحيدة للكتابة.
    # التجميد يُكتب مباشرةً لعدم وجود عملية تجميد في هذه الوحدة (دَين مُعلَن).
    session = get_session_factory()()
    try:
        account = session.query(AccountModel).filter(AccountModel.id == fiscal.cash["id"]).one()
        account.status = "frozen"
        session.commit()
    finally:
        session.close()
    with pytest.raises(EntityStateError, match="frozen"):
        treasury.post_funding(
            context=crown,
            treasury_code=fiscal.treasury["code"],
            cash_account_code=fiscal.cash["code"],
            revenue_account_code=fiscal.revenue["code"],
            amount="10",
            purpose="تمويل إلى حساب مجمَّد",
            official_id=fiscal.official["id"],
        )


# ── 7. تجاوز التخصيص ──────────────────────────────────────────────────────


def test_07_overspending_an_allocation_is_refused(
    treasury: StateTreasury, registry: StateRegistry, crown: AuthorizationContext
) -> None:
    """مجموع المصروف على تخصيص لا يتجاوز مبلغه — والمجموع مقروء من الدفتر."""
    fiscal = _fiscal(treasury, registry, crown, limit_amount="100000", funding="50000")
    allocation = _allocate(treasury, crown, fiscal, amount="1000")

    treasury.disburse(
        context=crown,
        allocation_id=allocation["id"],
        expense_account_code=fiscal.expense["code"],
        amount="700",
        purpose="دفعة أولى",
        official_id=fiscal.official["id"],
    )
    with pytest.raises(AllocationExceededError, match="يتجاوز المتاح في التخصيص"):
        treasury.disburse(
            context=crown,
            allocation_id=allocation["id"],
            expense_account_code=fiscal.expense["code"],
            amount="400",
            purpose="دفعة تتجاوز التخصيص",
            official_id=fiscal.official["id"],
        )

    balance = treasury.budget_balance(context=crown, budget_code=fiscal.budget["code"])
    assert balance["spent"] == "700.0000", "المصروف مشتقٌّ من الحركات القائمة"
    allocation_view = next(a for a in balance["allocations"] if a["id"] == allocation["id"])
    assert allocation_view["spent"] == "700.0000"
    assert allocation_view["available"] == "300.0000"


# ── 8. المبالغ غير الصالحة ────────────────────────────────────────────────


def test_08_invalid_amounts_are_refused_including_float(
    treasury: StateTreasury, registry: StateRegistry, crown: AuthorizationContext
) -> None:
    """الصفر والسالب والعائم والنصّ الفاسد كلّها مرفوضة — والعائم مرفوضٌ بذاته."""
    fiscal = _fiscal(treasury, registry, crown)
    allocation = _allocate(treasury, crown, fiscal, amount="5000")

    for bad in ("0", "-1", "-0.0001", "abc", ""):
        with pytest.raises(MoneyError):
            treasury.disburse(
                context=crown,
                allocation_id=allocation["id"],
                expense_account_code=fiscal.expense["code"],
                amount=bad,
                purpose=f"مبلغ غير صالح {bad!r}",
                official_id=fiscal.official["id"],
            )

    # العائم مرفوض صراحةً ولو كان موجبًا: لا يدخل المال عبر float أبدًا
    with pytest.raises(MoneyError, match="float|عائم"):
        treasury.disburse(
            context=crown,
            allocation_id=allocation["id"],
            expense_account_code=fiscal.expense["code"],
            amount=100.5,
            purpose="مبلغ عائم",
            official_id=fiscal.official["id"],
        )

    with pytest.raises(MoneyError):
        to_money(MONEY_MAX + Decimal("1"))

    # التقريب إلى الزوجي الأقرب (تقريب المصرفيين) وهو المسلك الافتراضي لـDecimal:
    # يُوثَّق هنا لأنه اختيارٌ ماليّ لا تفصيلٌ عارض، وأي تغييرٍ له يغيّر مبالغ.
    assert to_money("1.00005") == Decimal("1.0000"), "النصف يُقرَّب إلى الزوجي"
    assert to_money("1.00015") == Decimal("1.0002")
    assert to_money("1.000149") == Decimal("1.0001")
    assert to_money(7) == Decimal("7.0000"), "العدد الصحيح مقبول"
    with pytest.raises(MoneyError):
        to_money(True)  # noqa: FBT003 - المنطقي ليس مبلغًا ولو كان عددًا في بايثون
    assert money_sum(["0.1", "0.2"]) == Decimal("0.3000"), "جمعٌ بلا خطأ تمثيل عائم"
    assert format_money(Decimal("1")) == "1.0000", "المال يخرج نصًّا بأربع منازل"
    assert money_sum([]) == Decimal("0.0000")


# ── 9. العملة ─────────────────────────────────────────────────────────────


def test_09_currency_is_validated_and_never_implicitly_converted(
    treasury: StateTreasury, registry: StateRegistry, crown: AuthorizationContext
) -> None:
    """العملة ثلاثة أحرف كبيرة، ولا تحويل ضمنيّ بين عملتين.

    ملاحظة صادقة على النطاق: عملة الحساب والموازنة **تُورَّث من الخزانة** ولا
    يُدخلها المستدعي، فمسار «حسابٌ بعملة أخرى في نفس الخزانة» غير قابل للوجود
    عبر الواجهة العامّة. فيُفحص المنعُ في موضعه: في `normalize_currency` وفي
    `_require_same_currency` وفي قيد القاعدة — لا بمسارٍ مُصطنع.
    """
    fiscal = _fiscal(treasury, registry, crown, currency="SAR")
    assert fiscal.cash["currency"] == "SAR"
    assert fiscal.budget["currency"] == "SAR", "الموازنة ترث عملة الخزانة"

    for bad in ("SARX", "sr", "S1R", "", "  ", "ريال"):
        with pytest.raises(MoneyError):
            normalize_currency(bad)
    assert normalize_currency("usd") == "USD"

    with pytest.raises(CurrencyMismatchError):
        StateTreasury._require_same_currency(("الموازنة", "SAR"), ("الحساب", "USD"))

    with pytest.raises(MoneyError):
        treasury.establish_treasury(
            context=crown,
            code=_code("TRS"),
            name="خزانة بعملة فاسدة",
            currency="RIYAL",
        )

    # وقيد القاعدة نفسه يرفض عملة غير مُوحَّدة، بصرف النظر عن الخدمة
    session = get_session_factory()()
    try:
        session.add(
            TreasuryModel(
                id=f"trs-bad-{uuid.uuid4().hex[:8]}",
                code=_code("BADCUR"),
                name="عملة صغيرة",
                currency="sar",
                status="active",
                tenant_id=DEFAULT_TENANT,
                established_by="test",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
    finally:
        session.rollback()
        session.close()


# ── 10. رفض التخويل ───────────────────────────────────────────────────────


def test_10_authorization_is_denied_without_the_required_permission(
    treasury: StateTreasury, registry: StateRegistry, crown: AuthorizationContext
) -> None:
    """المستدعي لا يحدّد سلطته: الصلاحية من الجلسة، ولا تُقبل من الطلب."""
    fiscal = _fiscal(treasury, registry, crown)
    allocation = _allocate(treasury, crown, fiscal, amount="5000")

    citizen = _context("citizen")
    with pytest.raises(RegistryAuthorizationError):
        treasury.establish_treasury(
            context=citizen, code=_code("TRS"), name="خزانة مواطن", currency="SAR"
        )
    with pytest.raises(RegistryAuthorizationError):
        treasury.account_balance(
            context=citizen,
            treasury_code=fiscal.treasury["code"],
            account_code=fiscal.cash["code"],
        )

    # دور `official` يقرأ ولا يصرف. وكان هذا في R7-B رفضَ صلاحية
    # (`RegistryAuthorizationError`)؛ وشدّدته R7-C: هذا المبدأ لا هوية كانونية له
    # وقد مرّر `official_id` مسؤولٍ ليس له، فالرفض صار **رفضَ انتحال**
    # (`ForgedAuthorityError`) — وهو أدقّ وصفًا لا أوسع سماحًا. والاختبار يقبل
    # الاثنين لأن المضمون واحد: لا مال يتحرّك.
    official_ctx = _context("official")
    assert treasury.budget_balance(context=official_ctx, budget_code=fiscal.budget["code"])
    with pytest.raises((RegistryAuthorizationError, ForgedAuthorityError)):
        treasury.disburse(
            context=official_ctx,
            allocation_id=allocation["id"],
            expense_account_code=fiscal.expense["code"],
            amount="10",
            purpose="صرف بدور official",
            official_id=fiscal.official["id"],
        )

    # التاج نفسه لا يصرف بلا منصب: لا إعفاء سياديّ في المال العام
    with pytest.raises(OfficeAuthorityError, match="منصب"):
        treasury.disburse(
            context=crown,
            allocation_id=allocation["id"],
            expense_account_code=fiscal.expense["code"],
            amount="10",
            purpose="صرف سياديّ بلا منصب",
            official_id=None,  # type: ignore[arg-type]
        )

    # حدّ المستأجر
    other_tenant = _context("king", tenant_id="tenant-other", username="other")
    with pytest.raises((TenantIsolationError, TreasuryError)):
        treasury.account_balance(
            context=other_tenant,
            treasury_code=fiscal.treasury["code"],
            account_code=fiscal.cash["code"],
        )


# ── 11. الأثر المُدقَّق والحدث الدائم ──────────────────────────────────────


def test_11_every_money_mutation_leaves_audit_and_event_provenance(
    treasury: StateTreasury, registry: StateRegistry, crown: AuthorizationContext
) -> None:
    """كل تحوّل مالي يخلّف تدقيقًا ثم حدثًا دائمًا، بمعرّفين حقيقيين من المخزنين."""
    for subject in TREASURY_EVENTS:
        assert subject in EVENT_CONTRACTS, f"حدث بلا عقد: {subject}"

    fiscal = _fiscal(treasury, registry, crown, funding="9000")
    allocation = _allocate(treasury, crown, fiscal, amount="4000")
    posted = treasury.disburse(
        context=crown,
        allocation_id=allocation["id"],
        expense_account_code=fiscal.expense["code"],
        amount="1500",
        purpose="مصروف تشغيلي",
        official_id=fiscal.official["id"],
    )

    for entity in (fiscal.treasury, fiscal.cash, fiscal.budget, allocation, fiscal.funded, posted):
        assert entity["audit_id"], "لا كتابة مالية بلا سجلّ تدقيق"
        assert entity["event_id"], "ولا بلا حدث دائم"

    audits = PersistentAuditStore().list_all(200)
    actions = {a["action"] for a in audits}
    for action in (
        "treasury.establish",
        "treasury.account.open",
        "treasury.budget.create",
        "treasury.allocation.create",
        "treasury.funding.post",
        "treasury.disbursement.post",
    ):
        assert action in actions, f"فعلٌ مالي بلا أثر مُدقَّق: {action}"

    events = get_durable_event_bus().get_events(subject=EVENT_TRANSACTION_POSTED, limit=20)
    assert events, "الحركات تُعلَن على الناقل الدائم"
    payload = events[0]["data"]
    for field in ("transaction_id", "official_id", "actor", "audit_id", "amount", "currency"):
        assert field in payload, f"حمولة الحدث تنقص '{field}'"
    ok, message = validate_event(EVENT_TRANSACTION_POSTED, payload)
    assert ok, message


# ── 12. الربط بالمهمّة والقرار ────────────────────────────────────────────


def test_12_disbursement_links_to_real_task_and_decision_rows(
    treasury: StateTreasury,
    registry: StateRegistry,
    gov: GovernmentServices,
    crown: AuthorizationContext,
) -> None:
    """الصرف تنفيذًا لقرار: مهمّةٌ حقيقية في `tasks` أولًا، ولا مال قبل إنجازها."""
    fiscal = _fiscal(treasury, registry, crown, funding="50000")
    decision = _approved_decision(gov, registry, crown, fiscal)
    allocation = treasury.allocate(
        context=crown,
        budget_code=fiscal.budget["code"],
        account_code=fiscal.cash["code"],
        purpose="تنفيذ قرار",
        amount="10000",
        official_id=fiscal.official["id"],
        decision_id=decision["id"],
    )
    assert allocation["decision_id"] == decision["id"], "التخصيص يشير إلى القرار الذي أذن به"

    result = treasury.execute_decision_disbursement(
        context=crown,
        allocation_id=allocation["id"],
        expense_account_code=fiscal.expense["code"],
        amount="2500",
        purpose="تنفيذ قرار صرف",
        official_id=fiscal.official["id"],
        decision_id=decision["id"],
    )
    assert result["task_final_state"] == "completed", "لا مال يتحرّك قبل إنجاز المهمّة"
    assert result["task_id"], "الحركة تحمل معرّف مهمّتها"
    assert result["decision_id"] == decision["id"]

    session = get_session_factory()()
    try:
        row = session.execute(
            text("SELECT type, domain FROM tasks WHERE id = :tid"), {"tid": result["task_id"]}
        ).first()
        assert row is not None, "المهمّة صفٌّ حقيقي في `tasks` لا معرّفٌ مُصطنع"
        assert row[0] == DISBURSEMENT_TASK_TYPE
    finally:
        session.close()

    # قرارٌ مرفوض لا يأذن بمال
    rejected_fiscal = _fiscal(treasury, registry, crown, funding="1000")
    _worker()
    service = gov.publish_service(
        context=crown,
        institution_code=rejected_fiscal.institution["code"],
        code=_code("SVC"),
        name="طلب مرفوض",
    )
    case = gov.open_case(
        context=crown,
        institution_code=rejected_fiscal.institution["code"],
        service_code=service["code"],
        applicant_agent_id=_agent(),
        subject="طلب سيُرفض",
    )
    gov.process_case(context=crown, reference=case["reference"])
    rejected = gov.decide_case(
        context=crown,
        reference=case["reference"],
        outcome="rejected",
        rationale="غير مستوفٍ",
        official_id=rejected_fiscal.official["id"],
    )
    with pytest.raises(DecisionNotAuthorizingError, match="لا يأذن بمال"):
        treasury.allocate(
            context=crown,
            budget_code=rejected_fiscal.budget["code"],
            account_code=rejected_fiscal.cash["code"],
            purpose="تخصيص بقرار مرفوض",
            amount="10",
            official_id=rejected_fiscal.official["id"],
            decision_id=rejected["id"],
        )

    # وحركةٌ بمهمّة غير موجودة يرفضها المفتاح الأجنبي في القاعدة
    with pytest.raises(TreasuryError):
        treasury.disburse(
            context=crown,
            allocation_id=allocation["id"],
            expense_account_code=fiscal.expense["code"],
            amount="10",
            purpose="حركة بمهمّة وهمية",
            official_id=fiscal.official["id"],
            task_id="task-ghost",
        )


# ── 13. عكس الحركة ────────────────────────────────────────────────────────


def test_13_reversal_corrects_without_rewriting_history(
    treasury: StateTreasury, registry: StateRegistry, crown: AuthorizationContext
) -> None:
    """التصحيح حركةُ عكسٍ جديدة: الأصل يبقى، والمجاميع تتغيّر بذاتها لأنها مشتقّة."""
    fiscal = _fiscal(treasury, registry, crown, limit_amount="100000", funding="50000")
    allocation = _allocate(treasury, crown, fiscal, amount="10000")
    posted = treasury.disburse(
        context=crown,
        allocation_id=allocation["id"],
        expense_account_code=fiscal.expense["code"],
        amount="4000",
        purpose="صرف سيُعكس",
        official_id=fiscal.official["id"],
    )
    before = treasury.account_balance(
        context=crown, treasury_code=fiscal.treasury["code"], account_code=fiscal.cash["code"]
    )
    assert before["balance"] == "46000.0000"

    reversal = treasury.reverse_transaction(
        context=crown,
        reference=posted["reference"],
        reason="خطأ في المستند",
        official_id=fiscal.official["id"],
    )
    assert reversal["kind"] == "reversal"
    assert reversal["reverses_transaction_id"] == posted["id"]
    assert reversal["reversed_reference"] == posted["reference"]
    assert reversal["amount"] == posted["amount"], "العكس بنفس المبلغ لا بتقدير"

    session = get_session_factory()()
    try:
        original = session.query(TransactionModel).filter(TransactionModel.id == posted["id"]).one()
        assert original.status == "reversed", "الأصل يُعلَّم لا يُحذف"
        assert to_money(original.amount) == Decimal("4000.0000"), "ومبلغه لم يُكتب فوقه"
        assert (
            session.query(TransactionModel).filter(TransactionModel.id == posted["id"]).count() == 1
        )
    finally:
        session.close()

    after = treasury.account_balance(
        context=crown, treasury_code=fiscal.treasury["code"], account_code=fiscal.cash["code"]
    )
    assert after["balance"] == "50000.0000", "طرفا العكس ألغيا أثر الأصل حسابيًّا"

    budget = treasury.budget_balance(context=crown, budget_code=fiscal.budget["code"])
    assert budget["spent"] == "0.0000", "المصروف نزل بلا تعديل أي عدّاد — لأن لا عدّاد"

    file = treasury.transaction_file(context=crown, reference=posted["reference"])
    assert file["reversed_by"] is not None
    assert file["reversed_by"]["id"] == reversal["id"]

    # لا عكسٌ ثانٍ، ولا عكسٌ لحركة عكس
    with pytest.raises(TransactionReversedError):
        treasury.reverse_transaction(
            context=crown,
            reference=posted["reference"],
            reason="محاولة ثانية",
            official_id=fiscal.official["id"],
        )
    with pytest.raises(TransactionReversedError, match="حركة العكس لا تُعكس"):
        treasury.reverse_transaction(
            context=crown,
            reference=reversal["reference"],
            reason="عكس العكس",
            official_id=fiscal.official["id"],
        )


# ── 14. قيود القاعدة نفسها ────────────────────────────────────────────────


def test_14_database_constraints_are_real_not_comments(
    treasury: StateTreasury, registry: StateRegistry, crown: AuthorizationContext
) -> None:
    """`CHECK` و`UNIQUE` و`FK` مفروضة في القاعدة — تُفحَص بإدخالٍ مباشر يتخطّى الخدمة.

    الفرض على SQLite يشمل المفاتيح الأجنبية عبر `_enforce_sqlite_foreign_keys`.
    وعلى PostgreSQL محقَّقٌ يدويًّا بالجمل المذكورة في ذيل الترحيل 007.
    """
    fiscal = _fiscal(treasury, registry, crown)

    def _tx(**overrides: object) -> TransactionModel:
        base = {
            "id": f"tx-bad-{uuid.uuid4().hex[:10]}",
            "reference": _code("REF"),
            "treasury_id": fiscal.treasury["id"],
            "kind": "funding",
            "status": "posted",
            "amount": Decimal("10.0000"),
            "currency": "SAR",
            "purpose": "إدخال مباشر لفحص القيد",
            "official_id": fiscal.official["id"],
            "posted_by": "test",
            "tenant_id": DEFAULT_TENANT,
        }
        base.update(overrides)
        return TransactionModel(**base)  # type: ignore[arg-type]

    cases = {
        "مبلغ سالب": _tx(amount=Decimal("-1.0000")),
        "مبلغ صفر": _tx(amount=Decimal("0.0000")),
        "نوع حركة مخترع": _tx(kind="airdrop"),
        "حالة حركة مخترعة": _tx(status="pending"),
        "عملة بأربعة أحرف": _tx(currency="SARX"),
        "غرض فارغ": _tx(purpose=""),
        "منصب غير موجود": _tx(official_id="off-ghost"),
        "مهمّة غير موجودة": _tx(task_id="task-ghost"),
        "قرار غير موجود": _tx(decision_id="dec-ghost"),
        "خزانة غير موجودة": _tx(treasury_id="trs-ghost"),
    }
    for label, row in cases.items():
        session = get_session_factory()()
        try:
            session.add(row)
            with pytest.raises(IntegrityError):
                session.commit()
            assert label, "كل حالة موسومة ليظهر أيّها فشل"
        finally:
            session.rollback()
            session.close()

    # اتجاه قيد خارج المفردة
    session = get_session_factory()()
    try:
        session.add(
            LedgerEntryModel(
                id=f"led-bad-{uuid.uuid4().hex[:8]}",
                transaction_id=fiscal.funded["id"],
                account_id=fiscal.cash["id"],
                direction="sideways",
                amount=Decimal("1.0000"),
                currency="SAR",
                tenant_id=DEFAULT_TENANT,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
    finally:
        session.rollback()
        session.close()

    # مرجع مكرَّر في نفس المستأجر
    session = get_session_factory()()
    try:
        session.add(_tx(reference=fiscal.funded["reference"]))
        with pytest.raises(IntegrityError):
            session.commit()
    finally:
        session.rollback()
        session.close()

    # عكسٌ ثانٍ لنفس الحركة يرفضه `unique` على `reverses_transaction_id`
    session = get_session_factory()()
    try:
        session.add(_tx(kind="reversal", reverses_transaction_id=fiscal.funded["id"]))
        session.commit()
        session.add(_tx(kind="reversal", reverses_transaction_id=fiscal.funded["id"]))
        with pytest.raises(IntegrityError):
            session.commit()
    finally:
        session.rollback()
        session.close()

    # حدّ موازنة صفر
    session = get_session_factory()()
    try:
        session.add(
            BudgetModel(
                id=f"bdg-bad-{uuid.uuid4().hex[:8]}",
                code=_code("BDG"),
                treasury_id=fiscal.treasury["id"],
                institution_id=fiscal.institution["id"],
                period="2026",
                currency="SAR",
                limit_amount=Decimal("0.0000"),
                status="open",
                tenant_id=DEFAULT_TENANT,
                created_by="test",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
    finally:
        session.rollback()
        session.close()

    # والترحيل 007 يذكر الجداول الستّة كلّها بأمرِ إنشاءٍ حقيقي
    # التعليقات تُنزَع أولًا: هذا الترحيل يشرح في تعليقاته **لماذا** لا يستعمل
    # `double precision`، فلو فُحص المصدر خامًا لَفشل الحرس على شرحه لا على شيفرته.
    migration = "\n".join(
        line.split("--", 1)[0] for line in MIGRATION.read_text(encoding="utf-8").splitlines()
    )
    for table in TREASURY_TABLES:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in migration, f"جدول بلا ترحيل: {table}"
    assert "numeric(20,4)" in migration.lower(), "المال في الترحيل NUMERIC لا عائم"
    assert "double precision" not in migration.lower(), "عائم في ترحيل المال"
    assert "real" not in re.findall(r"\breal\b", migration.lower())


# ── 15. عدم التكرار ───────────────────────────────────────────────────────


def test_15_idempotency_key_prevents_double_spending(
    treasury: StateTreasury, registry: StateRegistry, crown: AuthorizationContext
) -> None:
    """إعادة نفس الطلب بنفس المفتاح تُعيد نفس الحركة ولا تكتب ثانية."""
    fiscal = _fiscal(treasury, registry, crown, funding="50000")
    allocation = _allocate(treasury, crown, fiscal, amount="10000")
    key = f"idem-{uuid.uuid4().hex[:12]}"

    first = treasury.disburse(
        context=crown,
        allocation_id=allocation["id"],
        expense_account_code=fiscal.expense["code"],
        amount="1200",
        purpose="صرف مرّة واحدة",
        official_id=fiscal.official["id"],
        idempotency_key=key,
    )
    second = treasury.disburse(
        context=crown,
        allocation_id=allocation["id"],
        expense_account_code=fiscal.expense["code"],
        amount="1200",
        purpose="نفس الطلب مُعادًا",
        official_id=fiscal.official["id"],
        idempotency_key=key,
    )
    assert second["id"] == first["id"], "نفس الحركة لا حركة ثانية"
    assert second.get("idempotent") is True

    session = get_session_factory()()
    try:
        assert (
            session.query(TransactionModel).filter(TransactionModel.idempotency_key == key).count()
            == 1
        ), "صفٌّ واحد في القاعدة"
        assert (
            session.query(LedgerEntryModel)
            .filter(LedgerEntryModel.transaction_id == first["id"])
            .count()
            == 2
        ), "طرفان لا أربعة"
    finally:
        session.close()

    spent = treasury.budget_balance(context=crown, budget_code=fiscal.budget["code"])["spent"]
    assert spent == "1200.0000", "المصروف لم يُحسب مرّتين"

    # والقيد في القاعدة نفسها يرفض التكرار حتى بإدخال مباشر
    session = get_session_factory()()
    try:
        session.add(
            TransactionModel(
                id=f"tx-dup-{uuid.uuid4().hex[:8]}",
                reference=_code("REF"),
                treasury_id=fiscal.treasury["id"],
                kind="funding",
                status="posted",
                amount=Decimal("1.0000"),
                currency="SAR",
                purpose="تكرار مفتاح عدم التكرار",
                official_id=fiscal.official["id"],
                posted_by="test",
                idempotency_key=key,
                tenant_id=DEFAULT_TENANT,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
    finally:
        session.rollback()
        session.close()


# ── حرّاس ساكنة — تمنع انحرافًا لا يظهر في نتيجة اختبار ────────────────────


def test_16_no_sql_sum_over_money_in_the_treasury_service() -> None:
    """مجاميع المال في بايثون بـ`Decimal` — لا `SUM` في SQL يمرّ بالعائم."""
    for path in TREASURY_SRC.glob("*.py"):
        code = _strip_comments(path.read_text(encoding="utf-8"))
        assert "func.sum" not in code, f"{path.name}: مجموع مالي في SQL"
        # الممنوع تحديدًا `balance += amount`: تجميعٌ يُكتب في خاصية صفٍّ محفوظ.
        # التجميع في متغيّرٍ محلّي (كما في `money_sum`) مقصود ومطلوب.
        assert not re.search(r"\w+\.\w+\s*[+-]=", code), f"{path.name}: عدّاد على خاصية صفّ"
        assert "float(" not in code, f"{path.name}: تحويل إلى عائم في مسار المال"
        assert "Float" not in code, f"{path.name}: نوع عائم في نموذج مالي"


def test_17_no_parallel_executor_and_no_writes_to_tasks() -> None:
    """لا مُنفِّذ مالٍ جديد، ولا كتابة في `tasks` من هذا النطاق."""
    code = _strip_comments((TREASURY_SRC / "service.py").read_text(encoding="utf-8"))
    assert "get_executive_core" in code, "العمل التنفيذي عبر النواة القائمة"
    for forbidden in ("AgentRuntime", "from amos_federation.services.executive_core.dispatcher"):
        assert forbidden not in code, f"استدعاء موازٍ للنواة: {forbidden}"
    for forbidden in ("INSERT INTO tasks", "UPDATE tasks", "DELETE FROM tasks"):
        assert forbidden not in code, f"كتابة مباشرة في جدول المهامّ: {forbidden}"
    assert "TaskModel" not in code


def test_18_request_models_never_carry_role_permissions_or_tenant() -> None:
    """المستدعي لا يحدّد سلطته: لا `role` ولا `permissions` ولا `tenant_id` في الطلب."""
    code = _strip_comments((TREASURY_SRC / "main.py").read_text(encoding="utf-8"))
    for forbidden in ("role:", "role ", "permissions:", "tenant_id:", "tenant_id ="):
        assert f"    {forbidden}" not in code, f"حقل سلطة في نموذج طلب: {forbidden!r}"
    assert code.count("Depends(require_context)") >= 1
    assert "require_auth" not in code, "الحدّ الجديد يستعمل السياق لا الحرس القديم"


def test_19_permission_vocabulary_is_the_existing_one() -> None:
    """لا صلاحية مُختَرعة: كل ما تفحصه الخزانة موجودٌ في `DEFAULT_ROLES`."""
    known = {perm for role in DEFAULT_ROLES for perm in role["permissions"]} - {"*"}
    for permission in TREASURY_PERMISSIONS:
        assert permission in known, f"صلاحية خارج المفردة القائمة: {permission}"
    assert OFFICE_BOUND_OPERATIONS, "العمليات المربوطة بمنصب مُعلَنة لا مضمرة"
    assert set(TRANSACTION_KINDS) == {"funding", "disbursement", "transfer", "reversal"}


def test_20_service_is_registered_on_its_own_port() -> None:
    """الخزانة خدمةٌ مُعلَنة في السجل بمنفذٍ لا يزاحم غيره."""
    definition = SERVICES["state-treasury"]
    assert definition["port"] == 8012
    ports = [s["port"] for s in SERVICES.values()]
    assert ports.count(8012) == 1, "منفذ مزدوج"
    for subject in (EVENT_TRANSACTION_POSTED, EVENT_TRANSACTION_REVERSED):
        assert subject in EVENT_CONTRACTS

    # والمسارات تُخدَم فعلًا: تُقرأ من مخطَّط OpenAPI للتطبيق المبني، لا من عدّ
    # الدوال في الملفّ — لأن راوترًا غير مُضمَّن يبدو مكتوبًا وهو غير مخدوم.
    from amos_federation.services.state_treasury.main import app

    paths = [p for p in app.openapi()["paths"] if p.startswith("/treasury")]
    assert len(paths) == 13, f"عدد المسارات المخدومة {len(paths)}"
    assert "/treasury/treasuries/{code}/funding" in paths
    assert "/treasury/transactions/{reference}/reversal" in paths


def test_21_no_money_in_floating_point_anywhere_in_models() -> None:
    """كل عمود مالٍ في النماذج `NUMERIC(20,4)` يُقرأ `Decimal`."""
    money_columns = {
        (BudgetModel, "limit_amount"),
        (AllocationModel, "amount"),
        (TransactionModel, "amount"),
        (LedgerEntryModel, "amount"),
    }
    for model, column in money_columns:
        col = model.__table__.columns[column]
        impl = col.type.load_dialect_impl(get_session_factory()().get_bind().dialect)
        assert impl.asdecimal is True, f"{model.__tablename__}.{column} لا يُقرأ Decimal"
        assert impl.scale == 4 and impl.precision == 20


def test_22_utc_timestamps_are_timezone_aware_in_the_service() -> None:
    """أوقات الحركات بـUTC صريحة — لا `datetime.now()` محلّيًّا."""
    code = _strip_comments((TREASURY_SRC / "service.py").read_text(encoding="utf-8"))
    assert "datetime.now(UTC)" in code
    assert re.search(r"datetime\.now\(\s*\)", code) is None, "وقتٌ بلا منطقة زمنية"
    assert datetime.now(UTC).tzinfo is not None


# ── 23–29. القفل: ما يمنع مرور طلبين معًا على نفس الحدّ ────────────────────
#
# SQLite يُسقط `FOR UPDATE` بلا خطأ، فلا يمكن لهذه الاختبارات أن تُظهر منعًا
# فعليًّا للتنافس. فهي تفحص ما **يمكن** فحصه هنا بصدق: أن العبارة تحمل القفل على
# PostgreSQL، وأن الترتيب واحد، وأن المهلة محلّية، وأن الخطأ يُترجم رفضًا قابلًا
# لإعادة المحاولة — ودلالة المنع نفسها محلّها PostgreSQL حقيقيّ.


class _FakeQuery:
    """سلسلة استعلام تسجّل ما طُلب منها بدل أن تنفّذه."""

    def __init__(self, session: _FakeSession, model: object) -> None:
        self._session = session
        self._model = model

    def filter(self, *_args: object) -> _FakeQuery:
        return self

    def order_by(self, *_args: object) -> _FakeQuery:
        return self

    def populate_existing(self) -> _FakeQuery:
        self._session.refreshed.append(self._model)
        return self

    def with_for_update(self) -> _FakeQuery:
        self._session.locked.append(self._model)
        return self

    def all(self) -> list[object]:
        if self._session.raise_code is not None:
            orig = Exception("boom")
            orig.sqlstate = self._session.raise_code  # type: ignore[attr-defined]
            raise DBAPIError("SELECT ... FOR UPDATE", {}, orig)
        return []


class _FakeSession:
    """جلسة تسجّل النداءات، بلهجة قاعدة نختارها — لا اتّصال ولا كتابة."""

    def __init__(self, dialect: str = "postgresql", raise_code: str | None = None) -> None:
        self.dialect_name = dialect
        self.raise_code = raise_code
        self.locked: list[object] = []
        self.refreshed: list[object] = []
        self.executed: list[tuple[str, object]] = []
        self.rolled_back = 0

    def get_bind(self) -> object:
        return SimpleNamespace(dialect=SimpleNamespace(name=self.dialect_name))

    def execute(self, statement: object, params: object = None) -> None:
        self.executed.append((str(statement), params))

    def query(self, model: object) -> _FakeQuery:
        return _FakeQuery(self, model)

    def rollback(self) -> None:
        self.rolled_back += 1


def test_23_lock_statement_carries_for_update_on_postgresql_and_is_dropped_on_sqlite(
    treasury: StateTreasury,
) -> None:
    """نفس الاستعلام: قفلٌ على PostgreSQL، ولا قفل على SQLite — بلا خطأ."""
    session = get_session_factory()()
    try:
        statement = lock_query(session, AllocationModel, {"b", "a"}).statement
        pg = str(statement.compile(dialect=postgresql.dialect()))
        lite = str(statement.compile(dialect=sqlite.dialect()))
        assert "FOR UPDATE" in pg
        assert "FOR UPDATE" not in lite
        # المعرّفات مرتَّبة: ترتيب القفل ثابت داخل الجدول أيضًا لا بحسب ورودها.
        compiled = statement.compile(dialect=postgresql.dialect())
        ids = [v for k, v in sorted(compiled.params.items()) if isinstance(v, str)]
        assert ids == sorted(ids)
        # وفي بيئة الاختبار القفل معطَّل صراحةً لا ضمنًا.
        assert _row_locks_supported(session) is False
    finally:
        session.close()

    # وعلى لهجة SQLite لا تُرسَل ولا عبارة واحدة — لا مهلة ولا قفل.
    fake = _FakeSession(dialect="sqlite")
    StateTreasury()._lock_rows(fake, [(BudgetModel, "bdg-1")])
    assert fake.executed == []
    assert fake.locked == []


def test_24_locks_are_taken_in_one_canonical_order_regardless_of_call_order() -> None:
    """ترتيبٌ واحد لكل المسارات — وإلّا توقّف طلبان معًا على نفس المجموعة."""
    fake = _FakeSession()
    StateTreasury()._lock_rows(
        fake,
        [
            (AccountModel, "acc-2"),
            (TransactionModel, "tx-1"),
            (AccountModel, "acc-1"),
            (AllocationModel, "alc-1"),
            (BudgetModel, "bdg-1"),
        ],
    )
    assert fake.locked == [BudgetModel, AllocationModel, TransactionModel, AccountModel]
    assert fake.locked == [m for m in LOCK_ORDER if m in fake.locked]
    # والصفوف تُقرأ من القاعدة بعد القفل لا من الذاكرة: الانتظار يُقدِّم القديم.
    assert fake.refreshed == fake.locked
    # حسابان في نداء واحد ⇒ استعلام قفل واحد لجدول الحسابات، لا اثنان.
    assert fake.locked.count(AccountModel) == 1


def test_25_lock_timeout_is_bounded_and_local_to_the_transaction() -> None:
    """الطلب العالق يُرفض، ولا يُعلَّق: مهلة محلّية بالمعاملة لا عامّة للاتّصال."""
    fake = _FakeSession()
    StateTreasury()._lock_rows(fake, [(BudgetModel, "bdg-1")])
    assert len(fake.executed) == 1
    statement, params = fake.executed[0]
    assert "set_config" in statement and "lock_timeout" in statement
    assert ":timeout" in statement  # مُمرَّر لا مُدمَج في النصّ
    assert params == {"timeout": LOCK_TIMEOUT}
    assert statement.rstrip().endswith("true)")  # `is_local` ⇒ لا يتسرّب للاتّصال
    assert LOCK_TIMEOUT != "0"


def test_26_a_table_outside_the_lock_order_is_refused_as_a_programming_fault() -> None:
    """جدولٌ بلا موضع في الترتيب يفتح باب التوقّف المتبادل، فيُرفض حالًا."""
    fake = _FakeSession()
    with pytest.raises(TreasuryError) as exc:
        StateTreasury()._lock_rows(fake, [(LedgerEntryModel, "led-1")])
    assert not isinstance(exc.value, TreasuryContentionError)
    assert "LedgerEntryModel" in str(exc.value)
    assert fake.locked == []


def test_27_lock_timeout_becomes_a_retryable_refusal_and_other_errors_are_not_swallowed() -> None:
    """55P03 ⇒ رفضٌ يُعاد. وأي رمزٍ آخر يمرّ كما هو: لا يُبلَع خطأٌ مجهول."""
    fake = _FakeSession(raise_code=PG_LOCK_NOT_AVAILABLE)
    with pytest.raises(TreasuryContentionError) as exc:
        StateTreasury()._lock_rows(fake, [(AllocationModel, "alc-1")])
    assert "state_allocations" in str(exc.value)
    assert fake.rolled_back == 1

    other = _FakeSession(raise_code="40001")  # فشل تسلسل: ليس تعذُّر قفل
    with pytest.raises(DBAPIError):
        StateTreasury()._lock_rows(other, [(AllocationModel, "alc-1")])
    assert other.rolled_back == 0

    # ومسار الترجمة في الواجهة: حالة عابرة قابلة لإعادة المحاولة، لا خطأ طلب.
    response = _http(TreasuryContentionError("مقفول"))
    assert response.status_code == 503
    assert response.headers == {"Retry-After": "1"}
    assert _http(BudgetExceededError("تجاوز")).status_code == 409


def test_28_every_read_then_write_check_locks_before_it_reads() -> None:
    """القفل قبل القراءة لا بعدها — يُفحص موضعه في الشيفرة لا وجوده فقط."""

    def _body(func: object) -> str:
        return _strip_comments(inspect.getsource(func))

    def _before(body: str, first: str, second: str) -> bool:
        i, j = body.find(first), body.find(second)
        assert i != -1, first
        assert j != -1, second
        return i < j

    allocate = _body(StateTreasury.allocate)
    assert _before(allocate, "_lock_rows(", "_allocated_total(")

    disburse = _body(StateTreasury.disburse)
    assert _before(disburse, "_lock_rows(", "_spent_on_allocation(")
    assert _before(disburse, "_lock_rows(", "_account_balance(")

    post = _body(StateTreasury._post)
    assert _before(post, "_lock_rows(", "session.add(tx)")

    reverse = _body(StateTreasury.reverse_transaction)
    assert _before(reverse, "_lock_rows(", 'original.status != "posted"')

    # وبعد القفل تُعاد قراءة الحالة: انتظارُ منافسٍ يُبطِل ما قُرئ قبله.
    assert allocate.count("budget.status") >= 2
    assert disburse.count("allocation.status") >= 2


def test_29_locking_does_not_reintroduce_a_stored_total_or_a_sql_sum() -> None:
    """القفل تسلسلٌ لا عدّاد: لا عمود مجموع دخل، ولا `SUM` في SQL ظهر."""
    source = _strip_comments((SRC / "services" / "state_treasury" / "service.py").read_text())
    assert "func.sum" not in source
    models_source = _strip_comments((SRC / "services" / "state_treasury" / "models.py").read_text())
    for forbidden in ("balance = Column", "spent = Column", "allocated = Column"):
        assert forbidden not in models_source
    # والقفل مأخوذ بـ`FOR UPDATE` تحديدًا: البديل الأضعف لا يمنع إدخال ابنٍ
    # تحت صفٍّ مقفول، فوجودُه هنا يعني ضمانًا أقلّ ممّا تقوله الوثيقة.
    assert "with_for_update()" in source
    assert "FOR NO KEY UPDATE" not in source
