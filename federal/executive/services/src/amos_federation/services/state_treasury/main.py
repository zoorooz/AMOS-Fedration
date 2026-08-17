"""
AMOS-Federation State Treasury — HTTP Interface
الهدف: نقاط طرفية للمال العام، سلطتها من الرمز والمنصب لا من جسم الطلب
النطاق: services/state_treasury
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17 (R7-B)

## النمط نفسه — لا نمط ثالث

`Depends(require_context)` في كل نقطة، و`create_service_app` من `common/`،
و**لا نموذج طلب في هذا الملفّ يحمل `role` أو `permissions` أو `tenant_id`** —
محروسٌ باختبار ساكن كما في R7-A.

## المال في الحمولة نصٌّ لا عائم

كل مبلغ في نماذج الطلب `str`، وكل مبلغ في الاستجابة نصٌّ بأربع منازل
(`format_money`). ولا يمرّ المال في هذا الملفّ عبر `float` قطعًا: JSON لا يعرف
`Decimal`، فلو قبلنا رقمًا لصار عائمًا قبل أن يصل إلى الخدمة. ومن أرسل رقمًا
عائمًا في JSON يُرفض طلبه بـ400 من `to_money`.

## كل نقطة تُغيّر مالًا تعبر التخويل

الترتيب داخل الخدمة: صلاحية → مستأجر → منصبٌ مخوَّل في المؤسسة → قاعدة →
تدقيق → حدث. وهذا الملفّ لا يفحص صلاحية بنفسه ولا يمرّر دورًا، بل يترجم
أخطاء النطاق إلى رموز HTTP.

## الأخطاء
الجلسة المنتهية 401 · نقص الصلاحية أو انعدام سلطة المنصب أو خرق المستأجر 403 ·
الكيان المفقود 404 · تعارض الرمز أو المرجع 409 · تجاوز الموازنة أو التخصيص أو
عدم كفاية الرصيد أو حالة كيان مانعة أو حركة معكوسة سابقًا 409 · اختلاف العملة
أو مبلغ غير صالح 400 · فشل المهمّة التنفيذية 409.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from amos_federation.common.auth_context import require_context
from amos_federation.common.principal import (
    AuthorizationContext,
    PrincipalUnverifiedError,
    SessionInvalidError,
    TenantIsolationError,
)
from amos_federation.common.registry import SERVICES
from amos_federation.common.service import create_service_app
from amos_federation.services.state_treasury.authorization import (
    OfficeAuthorityError,
    RegistryAuthorizationError,
)
from amos_federation.services.state_treasury.money import MoneyError
from amos_federation.services.state_treasury.service import (
    AccountNotFoundError,
    AllocationExceededError,
    AllocationNotFoundError,
    BudgetExceededError,
    BudgetNotFoundError,
    CurrencyMismatchError,
    DecisionNotAuthorizingError,
    DuplicateCodeError,
    EntityStateError,
    ExecutionFailedError,
    InsufficientFundsError,
    LedgerImbalanceError,
    OfficialNotFoundError,
    TransactionNotFoundError,
    TransactionReversedError,
    TreasuryContentionError,
    TreasuryError,
    TreasuryNotFoundError,
    get_state_treasury,
)

router = APIRouter(prefix="/treasury", tags=["state-treasury"])

Context = Annotated[AuthorizationContext, Depends(require_context)]

# مبلغٌ نصيّ: أرقامٌ وفاصلة عشرية اختيارية. لا أُسّ، ولا إشارة سالبة، ولا عائم.
_AMOUNT = r"^\d{1,12}(\.\d{1,4})?$"


# === نماذج الطلب — بلا دور ولا صلاحيات ولا مستأجر ===


class TreasuryRequest(BaseModel):
    """إنشاء خزانة."""

    code: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=2, max_length=200)
    currency: str = Field(min_length=3, max_length=3)
    institution_code: str | None = None


class AccountRequest(BaseModel):
    """فتح حساب في خزانة."""

    code: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=2, max_length=200)
    kind: str
    institution_code: str | None = None
    department_code: str | None = None


class BudgetRequest(BaseModel):
    """إنشاء موازنة لمؤسسة في فترة."""

    code: str = Field(min_length=2, max_length=64)
    institution_code: str = Field(min_length=2, max_length=64)
    period: str = Field(min_length=4, max_length=16)
    limit_amount: str = Field(pattern=_AMOUNT)
    department_code: str | None = None


class AllocationRequest(BaseModel):
    """تخصيص مبلغ من موازنة إلى حساب."""

    account_code: str = Field(min_length=2, max_length=64)
    purpose: str = Field(min_length=3, max_length=500)
    amount: str = Field(pattern=_AMOUNT)
    official_id: str = Field(min_length=1, max_length=128)
    decision_id: str | None = None


class FundingRequest(BaseModel):
    """تمويل خزانة: مَدين نقدي / دائن إيراد."""

    cash_account_code: str = Field(min_length=2, max_length=64)
    revenue_account_code: str = Field(min_length=2, max_length=64)
    amount: str = Field(pattern=_AMOUNT)
    purpose: str = Field(min_length=3, max_length=500)
    official_id: str = Field(min_length=1, max_length=128)
    reference: str | None = None
    idempotency_key: str | None = Field(default=None, max_length=128)


class DisbursementRequest(BaseModel):
    """صرف من تخصيص: مَدين مصروف / دائن نقدي."""

    expense_account_code: str = Field(min_length=2, max_length=64)
    amount: str = Field(pattern=_AMOUNT)
    purpose: str = Field(min_length=3, max_length=500)
    official_id: str = Field(min_length=1, max_length=128)
    task_id: str | None = None
    decision_id: str | None = None
    reference: str | None = None
    idempotency_key: str | None = Field(default=None, max_length=128)


class DecisionDisbursementRequest(BaseModel):
    """صرف تنفيذًا لقرار حكومي — لا يتحرّك المال إلّا إذا أُنجزت المهمّة."""

    expense_account_code: str = Field(min_length=2, max_length=64)
    amount: str = Field(pattern=_AMOUNT)
    purpose: str = Field(min_length=3, max_length=500)
    official_id: str = Field(min_length=1, max_length=128)
    decision_id: str = Field(min_length=1, max_length=128)
    idempotency_key: str | None = Field(default=None, max_length=128)
    max_steps: int = Field(default=8, gt=0, le=64)


class ReversalRequest(BaseModel):
    """عكس حركة — لا تعديل تاريخٍ، بل حركةٌ مقابلة."""

    reason: str = Field(min_length=3, max_length=500)
    official_id: str = Field(min_length=1, max_length=128)


def _http(exc: Exception) -> HTTPException:
    """ترجمة خطأ نطاق إلى رمز HTTP صادق."""
    if isinstance(exc, SessionInvalidError):
        return HTTPException(status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    if isinstance(
        exc,
        RegistryAuthorizationError
        | OfficeAuthorityError
        | PrincipalUnverifiedError
        | TenantIsolationError,
    ):
        return HTTPException(status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(
        exc,
        TreasuryNotFoundError
        | AccountNotFoundError
        | BudgetNotFoundError
        | AllocationNotFoundError
        | TransactionNotFoundError
        | OfficialNotFoundError,
    ):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, TreasuryContentionError):
        # حالة عابرة لا خطأ في الطلب: صفوفه مقفولة الآن من طلبٍ منافس. تُعاد
        # بـ503 مع `Retry-After` لأن نفس الطلب يمرّ بعد لحظة بلا تعديل.
        return HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc), headers={"Retry-After": "1"}
        )
    if isinstance(
        exc,
        DuplicateCodeError
        | InsufficientFundsError
        | BudgetExceededError
        | AllocationExceededError
        | EntityStateError
        | TransactionReversedError
        | ExecutionFailedError
        | DecisionNotAuthorizingError
        | LedgerImbalanceError,
    ):
        return HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))


_DOMAIN_ERRORS = (
    TreasuryError,
    MoneyError,
    CurrencyMismatchError,
    DecisionNotAuthorizingError,
    RegistryAuthorizationError,
    OfficeAuthorityError,
    SessionInvalidError,
    PrincipalUnverifiedError,
    TenantIsolationError,
)


# === الخزانة والحسابات ===


@router.post("/treasuries", status_code=status.HTTP_201_CREATED)
async def establish_treasury(payload: TreasuryRequest, context: Context) -> dict:
    """أنشئ خزانة."""
    try:
        return get_state_treasury().establish_treasury(
            context=context,
            code=payload.code,
            name=payload.name,
            currency=payload.currency,
            institution_code=payload.institution_code,
        )
    except _DOMAIN_ERRORS as exc:
        raise _http(exc) from exc


@router.post("/treasuries/{code}/accounts", status_code=status.HTTP_201_CREATED)
async def open_account(code: str, payload: AccountRequest, context: Context) -> dict:
    """افتح حسابًا في خزانة."""
    try:
        return get_state_treasury().open_account(
            context=context,
            treasury_code=code,
            code=payload.code,
            name=payload.name,
            kind=payload.kind,
            institution_code=payload.institution_code,
            department_code=payload.department_code,
        )
    except _DOMAIN_ERRORS as exc:
        raise _http(exc) from exc


@router.get("/treasuries/{code}/accounts/{account_code}/balance")
async def account_balance(code: str, account_code: str, context: Context) -> dict:
    """رصيد حساب — مشتقٌّ من قيود الدفتر، لا عمودٌ مخزَّن."""
    try:
        return get_state_treasury().account_balance(
            context=context, treasury_code=code, account_code=account_code
        )
    except _DOMAIN_ERRORS as exc:
        raise _http(exc) from exc


# === الموازنات والتخصيصات ===


@router.post("/treasuries/{code}/budgets", status_code=status.HTTP_201_CREATED)
async def create_budget(code: str, payload: BudgetRequest, context: Context) -> dict:
    """أنشئ موازنة مؤسسة لفترة."""
    try:
        return get_state_treasury().create_budget(
            context=context,
            treasury_code=code,
            institution_code=payload.institution_code,
            code=payload.code,
            period=payload.period,
            limit_amount=payload.limit_amount,
            department_code=payload.department_code,
        )
    except _DOMAIN_ERRORS as exc:
        raise _http(exc) from exc


@router.post("/budgets/{code}/allocations", status_code=status.HTTP_201_CREATED)
async def allocate(code: str, payload: AllocationRequest, context: Context) -> dict:
    """خصِّص مبلغًا من موازنة إلى حساب."""
    try:
        return get_state_treasury().allocate(
            context=context,
            budget_code=code,
            account_code=payload.account_code,
            purpose=payload.purpose,
            amount=payload.amount,
            official_id=payload.official_id,
            decision_id=payload.decision_id,
        )
    except _DOMAIN_ERRORS as exc:
        raise _http(exc) from exc


@router.get("/budgets/{code}/balance")
async def budget_balance(code: str, context: Context) -> dict:
    """حدّ الموازنة والمخصَّص والمصروف والمتبقّي — كلّها مشتقّة."""
    try:
        return get_state_treasury().budget_balance(context=context, budget_code=code)
    except _DOMAIN_ERRORS as exc:
        raise _http(exc) from exc


# === الحركات ===


@router.post("/treasuries/{code}/funding", status_code=status.HTTP_201_CREATED)
async def post_funding(code: str, payload: FundingRequest, context: Context) -> dict:
    """موِّل الخزانة بحركةٍ ذات طرفين."""
    try:
        return get_state_treasury().post_funding(
            context=context,
            treasury_code=code,
            cash_account_code=payload.cash_account_code,
            revenue_account_code=payload.revenue_account_code,
            amount=payload.amount,
            purpose=payload.purpose,
            official_id=payload.official_id,
            reference=payload.reference,
            idempotency_key=payload.idempotency_key,
        )
    except _DOMAIN_ERRORS as exc:
        raise _http(exc) from exc


@router.post("/allocations/{allocation_id}/disbursements", status_code=status.HTTP_201_CREATED)
async def disburse(allocation_id: str, payload: DisbursementRequest, context: Context) -> dict:
    """اصرف من تخصيص."""
    try:
        return get_state_treasury().disburse(
            context=context,
            allocation_id=allocation_id,
            expense_account_code=payload.expense_account_code,
            amount=payload.amount,
            purpose=payload.purpose,
            official_id=payload.official_id,
            task_id=payload.task_id,
            decision_id=payload.decision_id,
            reference=payload.reference,
            idempotency_key=payload.idempotency_key,
        )
    except _DOMAIN_ERRORS as exc:
        raise _http(exc) from exc


@router.post("/allocations/{allocation_id}/executions", status_code=status.HTTP_201_CREATED)
async def execute_decision_disbursement(
    allocation_id: str, payload: DecisionDisbursementRequest, context: Context
) -> dict:
    """اصرف تنفيذًا لقرار: مهمّةٌ في العمود التنفيذي أوّلًا، ثم المال."""
    try:
        return get_state_treasury().execute_decision_disbursement(
            context=context,
            allocation_id=allocation_id,
            expense_account_code=payload.expense_account_code,
            amount=payload.amount,
            purpose=payload.purpose,
            official_id=payload.official_id,
            decision_id=payload.decision_id,
            idempotency_key=payload.idempotency_key,
            max_steps=payload.max_steps,
        )
    except _DOMAIN_ERRORS as exc:
        raise _http(exc) from exc


@router.post("/transactions/{reference}/reversal", status_code=status.HTTP_201_CREATED)
async def reverse_transaction(reference: str, payload: ReversalRequest, context: Context) -> dict:
    """اعكس حركة بحركةٍ مقابلة — بلا تعديلٍ صامتٍ للتاريخ."""
    try:
        return get_state_treasury().reverse_transaction(
            context=context,
            reference=reference,
            reason=payload.reason,
            official_id=payload.official_id,
        )
    except _DOMAIN_ERRORS as exc:
        raise _http(exc) from exc


@router.get("/transactions")
async def list_transactions(
    context: Context,
    treasury_code: str | None = None,
    budget_code: str | None = None,
    limit: int = 50,
) -> dict:
    """اسرد الحركات."""
    try:
        items = get_state_treasury().list_transactions(
            context=context,
            treasury_code=treasury_code,
            budget_code=budget_code,
            limit=limit,
        )
    except _DOMAIN_ERRORS as exc:
        raise _http(exc) from exc
    return {"count": len(items), "transactions": items}


@router.get("/transactions/{reference}/file")
async def transaction_file(reference: str, context: Context) -> dict:
    """ملفّ الحركة: طرفاها وموازنتها وتخصيصها ومهمّتها وقرارها وعكسها."""
    try:
        return get_state_treasury().transaction_file(context=context, reference=reference)
    except _DOMAIN_ERRORS as exc:
        raise _http(exc) from exc


# === الصحة ===


@router.get("/health/summary")
async def treasury_health() -> dict:
    """عدّادات فعلية من القاعدة — بلا مالٍ في الخرج، فلا تحتاج تخويلًا."""
    return get_state_treasury().treasury_health()


_definition = SERVICES["state-treasury"]

app = create_service_app(
    service_name=_definition["name"],
    port=_definition["port"],
    description=_definition["responsibility"],
    routers=[router],
)

__all__ = ["app", "router"]
