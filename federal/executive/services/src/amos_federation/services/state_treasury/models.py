"""
AMOS-Federation State Treasury — Domain Models
الهدف: مصدر حقيقة واحد للمال العام: خزانة · حساب · موازنة · تخصيص · حركة · قيد
النطاق: services/state_treasury
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17 (R7-B)

## المصدر القانوني للمال — واحد لا اثنان

في المستودع خزانةٌ سابقة: `treasury_transactions` / `treasury_budgets` /
`treasury_reports` (Phase 10). ما بُني هناك **اقتصاد حوافز داخلي للوكلاء**
بعملة `amos-credit`: مكافأة إكمال مهمّة، كلفة نداء نموذج. وهو شيء آخر غير المال
العام: بلا مفتاح أجنبي واحد، وبلا مؤسسة ولا موازنة، وبـ`double precision`.

فالقرار المُعلَن هنا: **هذه الجداول (`state_*`) هي المصدر القانوني للمال العام**،
والقديمة تبقى كما هي سجلَّ حوافز غير قانونيّ للمال، لا تُلمس في هذه الوحدة ولا
يُدَّعى توحيدها. وذلك دَينٌ مُعلَن في وثيقة R7-B لا صمتٌ عنه.

## الكيانات وروابطها — كلها إلى صفوف قائمة

```
state_treasuries
   ├── state_accounts ──────► state_institutions / state_departments (اختياري)
   ├── state_budgets ───────► state_institutions (إلزامي) / state_departments
   │        └── state_allocations ──► state_accounts
   │                    └──► state_decisions (اختياري: تخصيص أذن به قرار)
   └── state_transactions ──► state_budgets / state_allocations (اختياري)
              ├──► tasks (اختياري: حركة نتجت عن تنفيذ مهمّة)
              ├──► state_decisions (اختياري: حركة نفَّذت قرارًا)
              ├──► state_officials (إلزامي: لا صرف بلا منصب)
              ├──► state_transactions (عكسٌ لحركة سابقة، واحدٌ لكل حركة)
              └── state_ledger_entries (طرفان على الأقلّ، مجموعهما متوازن)
```

## القيد المزدوج — ما هو حقيقي وما ليس بعد

كل حركة تُكتب **طرفين** في `state_ledger_entries`: مَدينٌ ودائن بنفس المبلغ
والعملة. فالتوازن ليس نيّةً مستقبلية: بنية الجدول لا تعرف «حركة بطرف واحد»،
وطبقة الخدمة ترفض أي حركة لا يتوازن طرفاها.

وما **ليس** مكتملًا ولا يُدَّعى: دليل حسابات كامل بأنواعه، وإقفال الفترات،
وميزان المراجعة وقائمة الدخل والمركز المالي. المصنَّف `REAL` هو الدفتر المتوازن،
والمصنَّف `PARTIAL` هو المحاسبة المزدوجة الكاملة (وثيقة R7-B §محاسبة).

## ما لا يُعدَّل

`state_transactions` و`state_ledger_entries` جداول **إضافة فقط**. التصحيح يُكتب
حركة عكسية جديدة (`kind='reversal'`) تشير إلى الأصل، ولا يُحذف صفّ ولا يُعاد
كتابة مبلغ. التعديل الوحيد المسموح على حركة قائمة هو `status: posted → reversed`
— وهو علامةٌ على وجود عكسٍ لها لا إعادةَ كتابةٍ لتاريخها.

## ما ليس قيدًا في المخطَّط — يُقال لا يُخفى

- **«لا صرف يتجاوز التخصيص»** و**«لا تخصيص يتجاوز الموازنة»**: مفروضان في طبقة
  الخدمة، لأن كلًّا منهما مجموعٌ فوق صفوفٍ في جدول آخر، وهذا ما لا يقبله `CHECK`.
  والمجاميع **مشتقّة من الدفتر** لا مخزَّنة، فلا عدّاد يمكن أن يكذب.
- **«طرفا الحركة متوازنان»**: يلزمه `CHECK` على مجموعِ صفوفٍ تابعة، وهو غير ممكن
  في `CHECK` محمول. مفروضٌ في الخدمة، ومفحوصٌ باختبار يقرأ القاعدة بعد الكتابة.
- **«عملة القيد = عملة حسابه»**: يلزمه `CHECK` عبر جدولين. مفروضٌ في الخدمة.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)

from amos_federation.common.database import Base
from amos_federation.services.state_treasury.money import (
    MoneyType,
    currency_check,
    positive_money_check,
)

# === المفردات — مصدر واحد للقيد في القاعدة وللتحقّق في الخدمة ===

TREASURY_STATUSES: tuple[str, ...] = ("active", "frozen", "closed")

#: نوع الحساب يحدّد اتجاه رصيده الطبيعي (انظر `NORMAL_BALANCE`).
ACCOUNT_KINDS: tuple[str, ...] = ("cash", "reserve", "revenue", "expense")

ACCOUNT_STATUSES: tuple[str, ...] = ("open", "frozen", "closed")

BUDGET_STATUSES: tuple[str, ...] = ("draft", "open", "closed")

ALLOCATION_STATUSES: tuple[str, ...] = ("active", "revoked")

#: `funding` إيراد يدخل الخزانة · `disbursement` صرف من تخصيص ·
#: `transfer` نقل بين حسابين · `reversal` عكس حركة سابقة.
TRANSACTION_KINDS: tuple[str, ...] = ("funding", "disbursement", "transfer", "reversal")

TRANSACTION_STATUSES: tuple[str, ...] = ("posted", "reversed")

ENTRY_DIRECTIONS: tuple[str, ...] = ("debit", "credit")

#: اتجاه الرصيد الطبيعي لكل نوع حساب — اصطلاح محاسبي لا اختيار حرّ:
#: الأصول والمصروفات يزيدها المَدين، والإيرادات يزيدها الدائن.
NORMAL_BALANCE: dict[str, str] = {
    "cash": "debit",
    "reserve": "debit",
    "expense": "debit",
    "revenue": "credit",
}

TREASURY_TABLES: tuple[str, ...] = (
    "state_treasuries",
    "state_accounts",
    "state_budgets",
    "state_allocations",
    "state_transactions",
    "state_ledger_entries",
)


def _now() -> datetime:
    return datetime.now(UTC)


def _in_check(column: str, values: tuple[str, ...]) -> str:
    return column + " IN ('" + "','".join(values) + "')"


class TreasuryModel(Base):
    """خزانة: وعاء المال العام بعملة واحدة، له حسابات وموازنات."""

    __tablename__ = "state_treasuries"

    id = Column(String, primary_key=True)
    code = Column(String, nullable=False)
    name = Column(String, nullable=False)
    #: خزانة الدولة قد تكون تابعة لمؤسسة (وزارة مالية) أو مركزية بلا مؤسسة.
    institution_id = Column(
        String, ForeignKey("state_institutions.id", ondelete="RESTRICT"), nullable=True
    )
    currency = Column(String, nullable=False)
    status = Column(String, nullable=False, default="active")
    tenant_id = Column(String, nullable=False, default="default")
    established_by = Column(String, nullable=False)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_state_treasuries_tenant_code"),
        CheckConstraint(_in_check("status", TREASURY_STATUSES), name="ck_state_treasuries_status"),
        CheckConstraint(currency_check(), name="ck_state_treasuries_currency"),
    )


class AccountModel(Base):
    """حساب في خزانة — لا رصيد مخزَّن فيه: الرصيد مشتقّ من الدفتر."""

    __tablename__ = "state_accounts"

    id = Column(String, primary_key=True)
    code = Column(String, nullable=False)
    name = Column(String, nullable=False)
    treasury_id = Column(
        String, ForeignKey("state_treasuries.id", ondelete="RESTRICT"), nullable=False
    )
    institution_id = Column(
        String, ForeignKey("state_institutions.id", ondelete="RESTRICT"), nullable=True
    )
    department_id = Column(
        String, ForeignKey("state_departments.id", ondelete="RESTRICT"), nullable=True
    )
    kind = Column(String, nullable=False)
    currency = Column(String, nullable=False)
    status = Column(String, nullable=False, default="open")
    tenant_id = Column(String, nullable=False, default="default")
    opened_by = Column(String, nullable=False)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    __table_args__ = (
        UniqueConstraint("treasury_id", "code", name="uq_state_accounts_treasury_code"),
        CheckConstraint(_in_check("kind", ACCOUNT_KINDS), name="ck_state_accounts_kind"),
        CheckConstraint(_in_check("status", ACCOUNT_STATUSES), name="ck_state_accounts_status"),
        CheckConstraint(currency_check(), name="ck_state_accounts_currency"),
        Index("ix_state_accounts_treasury", "treasury_id", "kind"),
    )


class BudgetModel(Base):
    """موازنة مؤسسة لفترة: حدٌّ أعلى مُعلَن، لا رصيد ولا عدّاد صرف.

    `limit_amount` هو الرقم الوحيد الذي يُدخله المستدعي. و`allocated` و`spent`
    و`remaining` **لا أعمدة لها**: تُحسب من `state_allocations` والدفتر عند كل
    قراءة. عمودٌ مخزَّن لها كان سيصير مصدر حقيقة ثانيًا يتباعد عن الدفتر بصمت.
    """

    __tablename__ = "state_budgets"

    id = Column(String, primary_key=True)
    code = Column(String, nullable=False)
    treasury_id = Column(
        String, ForeignKey("state_treasuries.id", ondelete="RESTRICT"), nullable=False
    )
    #: الموازنة لمؤسسة دائمًا — مالٌ عامّ بلا جهة مسؤولة عنه لا معنى له.
    institution_id = Column(
        String, ForeignKey("state_institutions.id", ondelete="RESTRICT"), nullable=False
    )
    department_id = Column(
        String, ForeignKey("state_departments.id", ondelete="RESTRICT"), nullable=True
    )
    #: فترة الموازنة بصيغة `YYYY` أو `YYYY-MM` أو `YYYY-Qn` — مفروضة في الخدمة.
    period = Column(String, nullable=False)
    currency = Column(String, nullable=False)
    limit_amount = Column(MoneyType, nullable=False)
    status = Column(String, nullable=False, default="open")
    tenant_id = Column(String, nullable=False, default="default")
    created_by = Column(String, nullable=False)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_state_budgets_tenant_code"),
        UniqueConstraint(
            "institution_id", "period", "code", name="uq_state_budgets_institution_period_code"
        ),
        CheckConstraint(_in_check("status", BUDGET_STATUSES), name="ck_state_budgets_status"),
        CheckConstraint(currency_check(), name="ck_state_budgets_currency"),
        CheckConstraint(positive_money_check("limit_amount"), name="ck_state_budgets_limit"),
        Index("ix_state_budgets_institution_period", "institution_id", "period"),
    )


class AllocationModel(Base):
    """تخصيص من موازنة إلى حساب: إذنُ صرفٍ بحدٍّ، لا حركة مال.

    التخصيص لا يُحرّك قرشًا — يأذن. والصرف حركة في الدفتر تشير إلى هذا التخصيص،
    فيُقاس المصروف عليه من الدفتر لا من عدّاد فيه.
    """

    __tablename__ = "state_allocations"

    id = Column(String, primary_key=True)
    budget_id = Column(String, ForeignKey("state_budgets.id", ondelete="RESTRICT"), nullable=False)
    #: الحساب الذي يُصرَف منه هذا التخصيص (حساب نقدي في خزانة الموازنة).
    account_id = Column(
        String, ForeignKey("state_accounts.id", ondelete="RESTRICT"), nullable=False
    )
    purpose = Column(String, nullable=False)
    amount = Column(MoneyType, nullable=False)
    currency = Column(String, nullable=False)
    status = Column(String, nullable=False, default="active")
    #: القرار الحكومي الذي أذن بالتخصيص إن وُجد (R7-A ⇄ R7-B).
    decision_id = Column(
        String, ForeignKey("state_decisions.id", ondelete="RESTRICT"), nullable=True
    )
    tenant_id = Column(String, nullable=False, default="default")
    created_by = Column(String, nullable=False)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    __table_args__ = (
        CheckConstraint(
            _in_check("status", ALLOCATION_STATUSES), name="ck_state_allocations_status"
        ),
        CheckConstraint(currency_check(), name="ck_state_allocations_currency"),
        CheckConstraint(positive_money_check("amount"), name="ck_state_allocations_amount"),
        Index("ix_state_allocations_budget", "budget_id", "status"),
    )


class TransactionModel(Base):
    """حركة مالية: رأسُ عمليةٍ لها طرفان في الدفتر. إضافة فقط."""

    __tablename__ = "state_transactions"

    id = Column(String, primary_key=True)
    reference = Column(String, nullable=False)
    treasury_id = Column(
        String, ForeignKey("state_treasuries.id", ondelete="RESTRICT"), nullable=False
    )
    kind = Column(String, nullable=False)
    status = Column(String, nullable=False, default="posted")
    amount = Column(MoneyType, nullable=False)
    currency = Column(String, nullable=False)
    purpose = Column(Text, nullable=False)
    budget_id = Column(String, ForeignKey("state_budgets.id", ondelete="RESTRICT"), nullable=True)
    allocation_id = Column(
        String, ForeignKey("state_allocations.id", ondelete="RESTRICT"), nullable=True
    )
    institution_id = Column(
        String, ForeignKey("state_institutions.id", ondelete="RESTRICT"), nullable=True
    )
    #: الأثر التنفيذي إن كانت الحركة نتيجة تنفيذ مهمّة (R7-B §5). اختياري
    #: بقصد: التمويل السيادي عملية مالية مستقلّة لا مهمّة لها.
    task_id = Column(String, ForeignKey("tasks.id", ondelete="RESTRICT"), nullable=True)
    #: القرار الحكومي الذي نفَّذته هذه الحركة إن وُجد.
    decision_id = Column(
        String, ForeignKey("state_decisions.id", ondelete="RESTRICT"), nullable=True
    )
    #: المنصب الذي تحرَّك المال باسمه — إلزامي: لا مال عامّ بلا مسؤول عنه.
    official_id = Column(
        String, ForeignKey("state_officials.id", ondelete="RESTRICT"), nullable=False
    )
    #: المبدأ الذي نفَّذ النداء فعلًا. يُخزَّن إلى جانب المنصب لأن ربط الجلسة
    #: بالمنصب غير ممكن اليوم (دَين مُعلَن من R7-A) — فيُقال الاثنان لا يُدَّعى واحد.
    posted_by = Column(String, nullable=False)
    #: الحركة التي تعكسها هذه الحركة. فريد: عكسٌ واحد لكل حركة، فلا يُعكَس مرّتين.
    reverses_transaction_id = Column(
        String, ForeignKey("state_transactions.id", ondelete="RESTRICT"), nullable=True, unique=True
    )
    #: مفتاح عدم التكرار: إعادة نفس الطلب بنفس المفتاح تُعيد نفس الحركة ولا
    #: تُنشئ ثانية. فريدٌ في القاعدة لا في الذاكرة — تنافُس عمليتين يرفضه القيد.
    idempotency_key = Column(String, nullable=True)
    correlation_id = Column(String, nullable=True)
    tenant_id = Column(String, nullable=False, default="default")
    created_at = Column(DateTime, default=_now)

    __table_args__ = (
        UniqueConstraint("tenant_id", "reference", name="uq_state_transactions_tenant_reference"),
        UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_state_transactions_tenant_idempotency"
        ),
        CheckConstraint(_in_check("kind", TRANSACTION_KINDS), name="ck_state_transactions_kind"),
        CheckConstraint(
            _in_check("status", TRANSACTION_STATUSES), name="ck_state_transactions_status"
        ),
        CheckConstraint(currency_check(), name="ck_state_transactions_currency"),
        CheckConstraint(positive_money_check("amount"), name="ck_state_transactions_amount"),
        CheckConstraint("length(purpose) > 0", name="ck_state_transactions_purpose_present"),
        Index("ix_state_transactions_allocation", "allocation_id", "status"),
        Index("ix_state_transactions_budget", "budget_id", "status"),
        Index("ix_state_transactions_treasury", "treasury_id", "created_at"),
    )


class LedgerEntryModel(Base):
    """قيدٌ واحد: طرفٌ من حركة على حساب واحد باتجاه واحد. لا يُعدَّل ولا يُحذف."""

    __tablename__ = "state_ledger_entries"

    id = Column(String, primary_key=True)
    transaction_id = Column(
        String, ForeignKey("state_transactions.id", ondelete="RESTRICT"), nullable=False
    )
    account_id = Column(
        String, ForeignKey("state_accounts.id", ondelete="RESTRICT"), nullable=False
    )
    direction = Column(String, nullable=False)
    amount = Column(MoneyType, nullable=False)
    currency = Column(String, nullable=False)
    tenant_id = Column(String, nullable=False, default="default")
    created_at = Column(DateTime, default=_now)

    __table_args__ = (
        CheckConstraint(
            _in_check("direction", ENTRY_DIRECTIONS), name="ck_state_ledger_entries_direction"
        ),
        CheckConstraint(currency_check(), name="ck_state_ledger_entries_currency"),
        CheckConstraint(positive_money_check("amount"), name="ck_state_ledger_entries_amount"),
        Index("ix_state_ledger_entries_account", "account_id", "direction"),
        Index("ix_state_ledger_entries_transaction", "transaction_id"),
    )


__all__ = [
    "ACCOUNT_KINDS",
    "ACCOUNT_STATUSES",
    "ALLOCATION_STATUSES",
    "BUDGET_STATUSES",
    "ENTRY_DIRECTIONS",
    "NORMAL_BALANCE",
    "TRANSACTION_KINDS",
    "TRANSACTION_STATUSES",
    "TREASURY_STATUSES",
    "TREASURY_TABLES",
    "AccountModel",
    "AllocationModel",
    "BudgetModel",
    "LedgerEntryModel",
    "TransactionModel",
    "TreasuryModel",
]
