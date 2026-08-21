"""
AMOS-Federation State Treasury — Service Layer
الهدف: عمليات المال العام فوق دفترٍ متوازن، ومجاميعها مشتقّة من الدفتر لا مخزَّنة
النطاق: services/state_treasury
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17 (R7-B)

## الترتيب في كل كتابة — هو نفسه ترتيب R7-A

    require_domain_permission → require_tenant → [require_treasury_office]
      → قاعدة البيانات (حركة + طرفاها في معاملة واحدة)
      → record_domain_trace (تدقيق ثم حدث دائم)

## لا رصيد مخزَّن، ولا عدّاد صرف

`account_balance` و`budget_balance` **تُحسَبان من الصفوف** في كل نداء:

- رصيد الحساب = مجموع القيود باتجاه رصيده الطبيعي − مجموع القيود بالاتجاه المقابل.
- الموازنة: `allocated` من `state_allocations` النشطة، و`spent` من حركات الصرف
  `posted` المشيرة إلى تخصيصاتها، و`remaining = limit − spent`.

ولذلك لا يمكن أن «يكذب عدّاد»: لا عدّاد. والعكس (`reversal`) لا يحتاج تعديل أي
مجموع، لأن الحركة الأصلية تصير `reversed` فتخرج من مجموع المصروف، وطرفَا العكس
يلغيان طرفَي الأصل في رصيد الحساب حسابيًّا.

## القيد المزدوج عمليًّا

`_post` هي البوّابة **الوحيدة** لكتابة أي حركة، وهي تكتب دائمًا طرفين: مَدينًا
ودائنًا بنفس المبلغ والعملة، وترفض ما لا يتوازن (`LedgerImbalanceError`). فلا
مسارٌ في هذا الملفّ يزيد رصيدًا بطرف واحد.

| العملية      | مَدين            | دائن            |
|--------------|------------------|-----------------|
| `funding`    | حساب نقدي        | حساب إيراد      |
| `disbursement` | حساب مصروف     | حساب نقدي       |
| `transfer`   | الحساب المستقبِل | الحساب المُرسِل  |
| `reversal`   | مقلوب الأصل      | مقلوب الأصل     |

## لا `SUM` في SQL على المال

كل المجاميع تُحسب في بايثون بـ`Decimal` (`money_sum`)، لأن `SUM` على SQLite يمرّ
بالعائم. وهذا محروسٌ باختبار ساكن يمنع `func.sum` في هذا الملفّ.

## الأثر التنفيذي (R7-B §7)

`execute_decision_disbursement` **تُقدِّم مهمّة إلى `ExecutiveCore` وتُشغّلها**، ولا
يتحرّك المال إلّا إذا بلغت المهمّة `completed`. فشلُ المهمّة ⇒ لا حركة، ورفعُ
`ExecutionFailedError` بالحالة النهائية كما قالها العمود التنفيذي. لا مُنفِّذ
مالٍ خاصّ بهذا النطاق، ولا كتابة في جدول `tasks` من هنا.

## حدود تُقال ولا تُخفى

- **التنافس على تجاوز الحدّ:** الفحوص تقرأ ثم تكتب، فتُقفل أصولها أولًا
  (`_lock_rows`) بترتيبٍ قانوني واحد وبمهلة محدودة. وهذا **على PostgreSQL
  وحده**: SQLite يتجاهل `FOR UPDATE`. ما زال بلا مستوى عزل مرتفع ولا إعادة
  محاولة تلقائية: الطلب العالق يُرفض بـ`TreasuryContentionError` ليُعاد.
- **لا إقفال فترات ولا قوائم مالية** — الدفتر متوازن، والمحاسبة الكاملة ليست هنا.
- **لا تحويل بنكي خارجي ولا قناة دفع** — ولا محاكاةَ واحدةٍ تُسمّى حقيقية.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from amos_federation.common.database import get_session_factory, init_db
from amos_federation.common.money_delegation import resolve_money_delegation
from amos_federation.common.principal import DEFAULT_TENANT
from amos_federation.services.executive_core.engine import get_executive_core
from amos_federation.services.government_services.models import CaseModel, DecisionModel
from amos_federation.services.national_registry.models import TransactionAuthorityModel
from amos_federation.services.national_registry.resolver import (
    AuthorityDecision,
    resolve_official_for_principal,
)
from amos_federation.services.state_registry.models import (
    DepartmentModel,
    InstitutionModel,
    OfficialModel,
)
from amos_federation.services.state_registry.trace import record_domain_trace
from amos_federation.services.state_treasury.authorization import (
    PERMISSIONS_ACCOUNT_OPEN,
    PERMISSIONS_ALLOCATION_WRITE,
    PERMISSIONS_BUDGET_WRITE,
    PERMISSIONS_DISBURSE,
    PERMISSIONS_FUNDING,
    PERMISSIONS_REVERSAL,
    PERMISSIONS_TREASURY_ESTABLISH,
    PERMISSIONS_TREASURY_READ,
    gate_treasury_operation,
    require_domain_permission,
    require_tenant,
    require_treasury_authority,
    require_treasury_office,
)
from amos_federation.services.state_treasury.models import (
    ACCOUNT_KINDS,
    NORMAL_BALANCE,
    AccountModel,
    AllocationModel,
    BudgetModel,
    LedgerEntryModel,
    TransactionModel,
    TreasuryModel,
)
from amos_federation.services.state_treasury.money import (
    MoneyError,
    format_money,
    money_sum,
    normalize_currency,
    require_positive,
    to_money,
)

if TYPE_CHECKING:
    from decimal import Decimal

    from amos_federation.common.principal import AuthorizationContext

# === أسماء الأحداث — لكل واحد عقد في `EVENT_CONTRACTS` ===

EVENT_TREASURY_ESTABLISHED = "amos_federation.treasury.treasury_established"
EVENT_ACCOUNT_OPENED = "amos_federation.treasury.account_opened"
EVENT_BUDGET_CREATED = "amos_federation.treasury.budget_created"
EVENT_ALLOCATION_CREATED = "amos_federation.treasury.allocation_created"
EVENT_TRANSACTION_POSTED = "amos_federation.treasury.transaction_posted"
EVENT_TRANSACTION_REVERSED = "amos_federation.treasury.transaction_reversed"

TREASURY_EVENTS: tuple[str, ...] = (
    EVENT_TREASURY_ESTABLISHED,
    EVENT_ACCOUNT_OPENED,
    EVENT_BUDGET_CREATED,
    EVENT_ALLOCATION_CREATED,
    EVENT_TRANSACTION_POSTED,
    EVENT_TRANSACTION_REVERSED,
)

#: نوع المهمّة الذي تُقدِّمه هذه الوحدة إلى العمود التنفيذي — اسم واحد لا يتفرّع.
DISBURSEMENT_TASK_TYPE = "treasury.disbursement.execute"
DISBURSEMENT_TASK_DOMAIN = "treasury"

#: مهلة انتظار القفل: نرفض بعدها بدل الانتظار غير المحدود على طلبٍ عالق.
LOCK_TIMEOUT = "3s"

#: رمز PostgreSQL لتعذُّر القفل (يشمل انتهاء `lock_timeout`).
PG_LOCK_NOT_AVAILABLE = "55P03"

#: ترتيب القفل القانوني: من الأعمّ إلى الأخصّ، ولا تُقفل جداول بترتيبٍ آخر.
#: طلبان يقفلان نفس المجموعة بترتيبين متعاكسين يتوقّفان معًا (deadlock)، فيُثبَّت
#: ترتيبٌ واحد لكل المسارات ويُحرَس باختبار.
LOCK_ORDER: tuple[Any, ...] = (BudgetModel, AllocationModel, TransactionModel, AccountModel)


def lock_query(session: Any, model: Any, ids: set[str] | list[str]) -> Any:
    """استعلام القفل نفسه الذي تستعمله الخدمة — مُفرَدٌ ليكون قابلًا للفحص.

    `populate_existing` ضرورية لا تحسينًا: بعد انتظارٍ حتى التزم المنافس، ما في
    الذاكرة صار قديمًا، فتُقرأ الصفوف المقفولة من القاعدة لا من الهوية المحفوظة.
    والمعرّفات مرتَّبة ليكون ترتيب القفل داخل الجدول ثابتًا أيضًا.
    """
    return (
        session.query(model)
        .filter(model.id.in_(sorted(ids)))
        .order_by(model.id)
        .populate_existing()
        .with_for_update()
    )


def _row_locks_supported(session: Any) -> bool:
    """`FOR UPDATE` يُصرَّف على PostgreSQL فقط.

    SQLite **يتجاهله بلا خطأ** (يُسقطه المُصرِّف)، فلا فائدة في إرساله هناك ولا
    ضرر: وهو محرك الاختبارات لا الإنتاج، ويُسلسل الكتابة بقفل ملفٍّ واحد أصلًا.
    ولهذا يبقى ضمان عدم التجاوز عند التنافس **خاصًّا بـPostgreSQL** — يُقال ولا
    يُعمَّم على كل محرك.
    """
    return session.get_bind().dialect.name == "postgresql"


#: صيغ فترة الموازنة المقبولة: سنة · شهر · ربع.
_PERIOD_PATTERN = re.compile(r"^\d{4}(-(0[1-9]|1[0-2])|-Q[1-4])?$")


# === أخطاء النطاق ===


class TreasuryError(RuntimeError):
    """أصل أخطاء الخزانة — كلها رفعٌ صريح لا قيمة فارغة."""


class TreasuryNotFoundError(TreasuryError):
    """لا خزانة بهذا الرمز في مستأجر السياق."""


class AccountNotFoundError(TreasuryError):
    """لا حساب بهذا الرمز في هذه الخزانة."""


class BudgetNotFoundError(TreasuryError):
    """لا موازنة بهذا الرمز في مستأجر السياق."""


class AllocationNotFoundError(TreasuryError):
    """لا تخصيص بهذا المعرّف."""


class TransactionNotFoundError(TreasuryError):
    """لا حركة بهذا المرجع في مستأجر السياق."""


class OfficialNotFoundError(TreasuryError):
    """لا منصب بهذا المعرّف."""


class DuplicateCodeError(TreasuryError):
    """الرمز مستعمل (خزانة أو حساب أو موازنة) في نطاقه."""


class CurrencyMismatchError(TreasuryError):
    """عملتان مختلفتان في عملية واحدة — لا تحويل ضمنيّ ولا سعر صرف في النظام."""


class InsufficientFundsError(TreasuryError):
    """رصيد الحساب النقدي لا يكفي — لا سحب على المكشوف بلا سياسة صريحة."""


class BudgetExceededError(TreasuryError):
    """مجموع التخصيصات يتجاوز حدّ الموازنة."""


class AllocationExceededError(TreasuryError):
    """المصروف على التخصيص يتجاوز مبلغه."""


class LedgerImbalanceError(TreasuryError):
    """طرفا الحركة غير متوازنين — عطلٌ برمجي لا حالة عمل."""


class TreasuryContentionError(TreasuryError):
    """تعذّر قفل الصفوف في المهلة — طلبٌ منافس يمسكها الآن.

    ليس عطلًا: هو الرفض الصريح بدل الانتظار غير المحدود، وبدل المرور معًا
    وتجاوز الحدّ. يُعاد الطلب فيمرّ بعد أن يُغلق المنافس.
    """


class EntityStateError(TreasuryError):
    """العملية لا تجوز على الكيان في حالته الحالية (مجمَّد/مغلق/ملغى)."""


class TransactionReversedError(TreasuryError):
    """الحركة معكوسة بالفعل — لا عكس للعكس، ولا عكسان لحركة."""


class ExecutionFailedError(TreasuryError):
    """مهمّة الصرف لم تكتمل في العمود التنفيذي — فلا مال يتحرّك."""


class DecisionNotAuthorizingError(TreasuryError):
    """القرار المُحال إليه غير موجود أو ليس موافقةً — لا يأذن بمال."""


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


class StateTreasury:
    """الخزانة الفدرالية للمال العام: خزائن وحسابات وموازنات وتخصيصات ودفتر."""

    def __init__(self, executive_core: Any | None = None) -> None:
        init_db()
        #: النواة المشتركة القائمة — لا نواة ولا مُنفِّذ ثانٍ في هذا النطاق.
        self._core = executive_core if executive_core is not None else get_executive_core()

    # ── أدوات داخلية ─────────────────────────────────────────────────────

    def _session(self):
        return get_session_factory()()

    @staticmethod
    def _tenant_of(context: AuthorizationContext) -> str:
        return context.tenant_id or DEFAULT_TENANT

    def _treasury_row(self, session, context: AuthorizationContext, code: str) -> TreasuryModel:
        tenant = self._tenant_of(context)
        row = (
            session.query(TreasuryModel)
            .filter(TreasuryModel.code == code, TreasuryModel.tenant_id == tenant)
            .first()
        )
        if row is None:
            raise TreasuryNotFoundError(f"لا خزانة برمز '{code}' في مستأجر '{tenant}'")
        require_tenant(context, row.tenant_id)
        return row

    def _account_row(
        self, session, context: AuthorizationContext, treasury_id: str, code: str
    ) -> AccountModel:
        row = (
            session.query(AccountModel)
            .filter(AccountModel.treasury_id == treasury_id, AccountModel.code == code)
            .first()
        )
        if row is None:
            raise AccountNotFoundError(f"لا حساب برمز '{code}' في هذه الخزانة")
        require_tenant(context, row.tenant_id)
        return row

    def _budget_row(self, session, context: AuthorizationContext, code: str) -> BudgetModel:
        tenant = self._tenant_of(context)
        row = (
            session.query(BudgetModel)
            .filter(BudgetModel.code == code, BudgetModel.tenant_id == tenant)
            .first()
        )
        if row is None:
            raise BudgetNotFoundError(f"لا موازنة برمز '{code}' في مستأجر '{tenant}'")
        require_tenant(context, row.tenant_id)
        return row

    def _allocation_row(
        self, session, context: AuthorizationContext, allocation_id: str
    ) -> AllocationModel:
        row = session.query(AllocationModel).filter(AllocationModel.id == allocation_id).first()
        if row is None:
            raise AllocationNotFoundError(f"لا تخصيص بمعرّف '{allocation_id}'")
        require_tenant(context, row.tenant_id)
        return row

    def _institution_row(
        self, session, context: AuthorizationContext, code: str
    ) -> InstitutionModel:
        tenant = self._tenant_of(context)
        row = (
            session.query(InstitutionModel)
            .filter(InstitutionModel.code == code, InstitutionModel.tenant_id == tenant)
            .first()
        )
        if row is None:
            raise TreasuryNotFoundError(f"لا مؤسسة برمز '{code}' في مستأجر '{tenant}'")
        require_tenant(context, row.tenant_id)
        return row

    def _official_row(
        self, session, context: AuthorizationContext, official_id: str | None
    ) -> OfficialModel | None:
        if official_id is None:
            return None
        row = session.query(OfficialModel).filter(OfficialModel.id == official_id).first()
        if row is None:
            raise OfficialNotFoundError(f"لا منصب بمعرّف '{official_id}'")
        require_tenant(context, row.tenant_id)
        return row

    def _authorize_money(
        self,
        session,
        context: AuthorizationContext,
        operation: str,
        *,
        entrypoint: str,
        required: tuple[str, ...],
        grant_required: bool,
        institution_id: str,
        claimed_official_id: str | None,
        budget_id: str | None = None,
        account_id: str | None = None,
        amount: Any | None = None,
    ) -> tuple[OfficialModel | None, AuthorityDecision]:
        """من يحرّك هذا المال، وبأيّ سلطة؟ — مكانٌ واحد يُجاب فيه (R7-C6/C8).

        مساران، وترتيبهما مقصود:

        - **مسار المِنحة** (`grant_required`): السلطة تُحسم أوّلًا من القاعدة، والمنصب
          يُقرأ **من قرار السلطة نفسه** لا من جسم الطلب. فمن لا مِنحة له يُرفض
          رفض تخويل واضحًا، قبل أن يُسأل عن منصب أصلًا.
        - **مسار الصلاحية** (سيادي): المنصب يُقرأ كما كان في R7-B — توافقًا تامًا
          مع ما كان يمرّ قبل R7-C — ثمّ يُسجّل أثرُه `PARTIAL`/`UNRESOLVED` لا `PROVEN`.
          ولا يُمرّر له `claimed_official_id` إلى المُحلّل: سلطته ليست من هوية،
          فلا يُقاس ادّعاءه بمناصب هويةٍ لا يُشترط أن توجد.
        """
        # Q-19: التفويضُ يُحضَرُ قبلَ أيِّ فحصٍ آخرَ ويسبقُ لمسَ القاعدة. فعمليّةٌ
        # ماليّةٌ بلا تفويضٍ مُعلَنٍ لا تصلُ حدَّ التخويلِ أصلًا — تُغلَقُ هنا.
        resolve_money_delegation(operation, entrypoint=entrypoint)
        if grant_required:
            decision = require_treasury_authority(
                session,
                context,
                operation,
                required=required,
                grant_required=True,
                institution_id=institution_id,
                budget_id=budget_id,
                account_id=account_id,
                amount=None if amount is None else str(amount),
                claimed_official_id=claimed_official_id,
            )
            official = resolve_official_for_principal(
                session,
                context,
                institution_id=institution_id,
                claimed_official_id=decision.official_id,
            )
            require_treasury_office(context, official, institution_id=institution_id)
            return official, decision

        official = self._official_row(session, context, claimed_official_id)
        require_treasury_office(context, official, institution_id=institution_id)
        decision = require_treasury_authority(
            session,
            context,
            operation,
            required=required,
            grant_required=False,
            institution_id=institution_id,
            department_id=official.department_id if official is not None else None,
            budget_id=budget_id,
            account_id=account_id,
            amount=None if amount is None else str(amount),
            claimed_official_id=None,
        )
        return official, decision

    @staticmethod
    def _record_transaction_authority(
        session,
        context: AuthorizationContext,
        *,
        transaction: TransactionModel,
        decision: AuthorityDecision,
    ) -> None:
        """اربط الحركة بسلسلة سلطتها في صفّ جانبيّ مفتاحُه الحركة — R7-C8.

        صفّ واحد لكل حركة (`transaction_id` مفتاح أوّليّ)، فلا إسنادان متناقضان
        لريالٍ واحد. والقرار يُخزّن كما حُسم لا كما يُرجى: `PROVEN` حين أجازته
        مِنحة منصب، و`PARTIAL`/`UNRESOLVED` حين مرّ بصلاحية سيادية — فلا تُخفى
        حركةٌ سيادية ولا تُرفّع إلى إسنادٍ لم يُقرأ.
        """
        session.add(
            TransactionAuthorityModel(
                transaction_id=transaction.id,
                principal_id=context.principal_id,
                identity_id=decision.identity_id,
                official_id=transaction.official_id,
                position_id=decision.position_id,
                grant_id=decision.grant_id,
                scope=decision.scope,
                operation=decision.operation,
                authority_class=decision.classification,
                reason=decision.reason,
                targets={
                    **decision.targets,
                    "transaction_reference": transaction.reference,
                    "amount": str(transaction.amount),
                    "currency": transaction.currency,
                },
                session_id=context.session_id,
                correlation_id=context.correlation_id,
                tenant_id=transaction.tenant_id,
            )
        )

    def _transaction_row(
        self, session, context: AuthorizationContext, reference: str
    ) -> TransactionModel:
        tenant = self._tenant_of(context)
        row = (
            session.query(TransactionModel)
            .filter(
                TransactionModel.reference == reference,
                TransactionModel.tenant_id == tenant,
            )
            .first()
        )
        if row is None:
            raise TransactionNotFoundError(f"لا حركة بمرجع '{reference}' في مستأجر '{tenant}'")
        require_tenant(context, row.tenant_id)
        return row

    @staticmethod
    def _require_same_currency(*pairs: tuple[str, str]) -> None:
        """كل زوج (اسم، عملة) يجب أن يتّفق مع الأول — لا تحويل ضمنيّ."""
        if not pairs:
            return
        base_name, base = pairs[0]
        for name, currency in pairs[1:]:
            if currency != base:
                raise CurrencyMismatchError(
                    f"عملة {name} ('{currency}') لا تساوي عملة {base_name} ('{base}')"
                )

    # ── القفل: تسلسل الفحوص المقروءة من الصفوف ────────────────────────────

    def _lock_rows(self, session, targets: list[tuple[Any, str | None]]) -> None:
        """اقفل صفوف الفحص قبل قراءتها، بالترتيب القانوني وحده.

        الفحوص كلّها مجاميعُ صفوفٍ لا أعمدة مخزَّنة، فلا يوجد صفٌّ واحد يتضارب
        عليه طلبان بطبيعته. فيُتَّخذ الصفُّ **الأب** نقطةَ تسلسل: الموازنة قبل
        قراءة المخصَّص، والتخصيص قبل قراءة المصروف، والحساب قبل قراءة رصيده.

        ولماذا `FOR UPDATE` تحديدًا: إدخالُ ابنٍ (تخصيص، حركة، قيد) يأخذ
        `FOR KEY SHARE` على أبيه لفحص المفتاح الأجنبي، و`FOR UPDATE` يتضارب مع
        `FOR KEY SHARE`، فينتظر كل من يريد الكتابة تحت صفٍّ مقفول — لا الفاحصون
        وحدهم. و`FOR NO KEY UPDATE` **لا** يتضارب معه، فلا يكفي هنا.

        والمهلة محدودة: `lock_timeout` محلّي للمعاملة، فالطلب العالق يُرفض
        بـ`TreasuryContentionError` بدل أن يُعلَّق بلا نهاية.
        """
        if not _row_locks_supported(session):
            return
        wanted: dict[Any, set[str]] = {}
        for model, row_id in targets:
            if row_id is not None:
                wanted.setdefault(model, set()).add(row_id)
        if not wanted:
            return
        stray = sorted(m.__name__ for m in wanted if m not in LOCK_ORDER)
        if stray:
            # عطلٌ برمجي لا حالة تشغيل: جدولٌ بلا موضع في الترتيب يفتح باب
            # التوقّف المتبادل، فيُرفض هنا بدل أن يظهر تحت الحمل.
            raise TreasuryError(f"جدول بلا موضع في ترتيب القفل: {', '.join(stray)}")

        session.execute(
            text("SELECT set_config('lock_timeout', :timeout, true)"),
            {"timeout": LOCK_TIMEOUT},
        )
        for model in LOCK_ORDER:
            ids = wanted.get(model)
            if not ids:
                continue
            try:
                lock_query(session, model, ids).all()
            except DBAPIError as exc:
                orig = exc.orig
                code = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
                if code != PG_LOCK_NOT_AVAILABLE:
                    raise
                session.rollback()
                raise TreasuryContentionError(
                    f"تعذّر قفل صفوف '{model.__tablename__}' خلال {LOCK_TIMEOUT} — "
                    "طلبٌ منافس يمسكها؛ أعِد المحاولة"
                ) from exc

    # ── مجاميع مشتقّة من الصفوف ───────────────────────────────────────────

    def _account_balance(self, session, account: AccountModel) -> Decimal:
        """رصيد الحساب من قيوده — باتجاه رصيده الطبيعي."""
        normal = NORMAL_BALANCE[account.kind]
        rows = (
            session.query(LedgerEntryModel).filter(LedgerEntryModel.account_id == account.id).all()
        )
        plus = money_sum(row.amount for row in rows if row.direction == normal)
        minus = money_sum(row.amount for row in rows if row.direction != normal)
        return to_money(plus - minus)

    def _allocated_total(self, session, budget_id: str) -> Decimal:
        rows = (
            session.query(AllocationModel)
            .filter(AllocationModel.budget_id == budget_id, AllocationModel.status == "active")
            .all()
        )
        return money_sum(row.amount for row in rows)

    def _spent_on_allocation(self, session, allocation_id: str) -> Decimal:
        """المصروف على تخصيص = حركات الصرف القائمة (`posted`) المشيرة إليه.

        المعكوسة صارت `reversed` فخرجت، وحركة العكس نوعها `reversal` فلا تُحسب
        صرفًا. فلا يحتاج العكس تعديل أي رقم مخزَّن — لأن لا رقم مخزَّنًا.
        """
        rows = (
            session.query(TransactionModel)
            .filter(
                TransactionModel.allocation_id == allocation_id,
                TransactionModel.kind == "disbursement",
                TransactionModel.status == "posted",
            )
            .all()
        )
        return money_sum(row.amount for row in rows)

    def _spent_on_budget(self, session, budget_id: str) -> Decimal:
        rows = (
            session.query(TransactionModel)
            .filter(
                TransactionModel.budget_id == budget_id,
                TransactionModel.kind == "disbursement",
                TransactionModel.status == "posted",
            )
            .all()
        )
        return money_sum(row.amount for row in rows)

    # ── التمثيل ───────────────────────────────────────────────────────────

    @staticmethod
    def _treasury_dict(row: TreasuryModel) -> dict[str, Any]:
        return {
            "id": row.id,
            "code": row.code,
            "name": row.name,
            "institution_id": row.institution_id,
            "currency": row.currency,
            "status": row.status,
            "tenant_id": row.tenant_id,
            "established_by": row.established_by,
            "created_at": _iso(row.created_at),
        }

    @staticmethod
    def _account_dict(row: AccountModel) -> dict[str, Any]:
        return {
            "id": row.id,
            "code": row.code,
            "name": row.name,
            "treasury_id": row.treasury_id,
            "institution_id": row.institution_id,
            "department_id": row.department_id,
            "kind": row.kind,
            "currency": row.currency,
            "status": row.status,
            "tenant_id": row.tenant_id,
            "opened_by": row.opened_by,
            "created_at": _iso(row.created_at),
        }

    @staticmethod
    def _budget_dict(row: BudgetModel) -> dict[str, Any]:
        return {
            "id": row.id,
            "code": row.code,
            "treasury_id": row.treasury_id,
            "institution_id": row.institution_id,
            "department_id": row.department_id,
            "period": row.period,
            "currency": row.currency,
            "limit_amount": format_money(row.limit_amount),
            "status": row.status,
            "tenant_id": row.tenant_id,
            "created_by": row.created_by,
            "created_at": _iso(row.created_at),
        }

    @staticmethod
    def _allocation_dict(row: AllocationModel) -> dict[str, Any]:
        return {
            "id": row.id,
            "budget_id": row.budget_id,
            "account_id": row.account_id,
            "purpose": row.purpose,
            "amount": format_money(row.amount),
            "currency": row.currency,
            "status": row.status,
            "decision_id": row.decision_id,
            "tenant_id": row.tenant_id,
            "created_by": row.created_by,
            "created_at": _iso(row.created_at),
        }

    @staticmethod
    def _transaction_dict(row: TransactionModel) -> dict[str, Any]:
        return {
            "id": row.id,
            "reference": row.reference,
            "treasury_id": row.treasury_id,
            "kind": row.kind,
            "status": row.status,
            "amount": format_money(row.amount),
            "currency": row.currency,
            "purpose": row.purpose,
            "budget_id": row.budget_id,
            "allocation_id": row.allocation_id,
            "institution_id": row.institution_id,
            "task_id": row.task_id,
            "decision_id": row.decision_id,
            "official_id": row.official_id,
            "posted_by": row.posted_by,
            "reverses_transaction_id": row.reverses_transaction_id,
            "idempotency_key": row.idempotency_key,
            "tenant_id": row.tenant_id,
            "created_at": _iso(row.created_at),
        }

    @staticmethod
    def _entry_dict(row: LedgerEntryModel) -> dict[str, Any]:
        return {
            "id": row.id,
            "transaction_id": row.transaction_id,
            "account_id": row.account_id,
            "direction": row.direction,
            "amount": format_money(row.amount),
            "currency": row.currency,
            "created_at": _iso(row.created_at),
        }

    # ── البوّابة الوحيدة لكتابة حركة ───────────────────────────────────────

    def _post(
        self,
        session,
        *,
        context: AuthorizationContext,
        treasury: TreasuryModel,
        kind: str,
        amount: Decimal,
        currency: str,
        purpose: str,
        debit_account: AccountModel,
        credit_account: AccountModel,
        official: OfficialModel,
        reference: str | None = None,
        budget_id: str | None = None,
        allocation_id: str | None = None,
        institution_id: str | None = None,
        task_id: str | None = None,
        decision_id: str | None = None,
        reverses_transaction_id: str | None = None,
        idempotency_key: str | None = None,
        authority: AuthorityDecision,
    ) -> tuple[TransactionModel, list[LedgerEntryModel]]:
        """اكتب حركة وطرفيها في معاملة واحدة — لا حركة بطرف واحد ولا بلا توازن.

        لا يُنادى هذا من خارج الملفّ: كل عملية مالية تمرّ به، فيبقى للتوازن مكانٌ
        واحد يُفحص فيه بدل أن يُعاد في كل عملية ويُنسى في واحدة.
        """
        if debit_account.id == credit_account.id:
            raise LedgerImbalanceError("طرفا الحركة لا يجوز أن يكونا حسابًا واحدًا")
        # الحسابان يُقفلان قبل فحص حالتهما وقبل كتابة القيود: كل قيدٍ يشير إلى
        # حساب، فقفلُ الحساب يُسلسل كل من يغيّر رصيده — ومنه فاحصُ الكفاية.
        self._lock_rows(
            session, [(AccountModel, debit_account.id), (AccountModel, credit_account.id)]
        )
        for account in (debit_account, credit_account):
            if account.status != "open":
                raise EntityStateError(f"الحساب '{account.code}' حالته '{account.status}'")
        self._require_same_currency(
            ("الحركة", currency),
            ("الخزانة", treasury.currency),
            (f"الحساب المَدين '{debit_account.code}'", debit_account.currency),
            (f"الحساب الدائن '{credit_account.code}'", credit_account.currency),
        )

        tenant = self._tenant_of(context)
        tx_reference = reference or f"TX-{uuid.uuid4().hex[:12].upper()}"
        tx = TransactionModel(
            id=f"tx-{uuid.uuid4()}",
            reference=tx_reference,
            treasury_id=treasury.id,
            kind=kind,
            status="posted",
            amount=amount,
            currency=currency,
            purpose=purpose,
            budget_id=budget_id,
            allocation_id=allocation_id,
            institution_id=institution_id,
            task_id=task_id,
            decision_id=decision_id,
            official_id=official.id,
            posted_by=context.principal_id,
            reverses_transaction_id=reverses_transaction_id,
            idempotency_key=idempotency_key,
            correlation_id=context.correlation_id,
            tenant_id=tenant,
        )
        entries = [
            LedgerEntryModel(
                id=f"led-{uuid.uuid4()}",
                transaction_id=tx.id,
                account_id=debit_account.id,
                direction="debit",
                amount=amount,
                currency=currency,
                tenant_id=tenant,
            ),
            LedgerEntryModel(
                id=f"led-{uuid.uuid4()}",
                transaction_id=tx.id,
                account_id=credit_account.id,
                direction="credit",
                amount=amount,
                currency=currency,
                tenant_id=tenant,
            ),
        ]
        debits = money_sum(e.amount for e in entries if e.direction == "debit")
        credits = money_sum(e.amount for e in entries if e.direction == "credit")
        if debits != credits or debits != amount:
            raise LedgerImbalanceError(
                f"حركة غير متوازنة: مَدين {debits} · دائن {credits} · مبلغ {amount}"
            )

        try:
            # الحركة تُغسل قبل طرفيها: القيد يشير إليها بمفتاح أجنبي، وترتيب
            # الإدخال في غسلةٍ واحدة ليس مضمونًا حين لا تُعرَّف relationship()،
            # فيُفرض الترتيب صراحةً بدل الاعتماد على استنتاج المُخطِّط.
            session.add(tx)
            session.flush()
            for entry in entries:
                session.add(entry)
            session.flush()
            # إسناد السلطة يُكتب في **نفس** المعاملة — فلا حركة ملتزمة بلا من أجازها.
            self._record_transaction_authority(session, context, transaction=tx, decision=authority)
            session.flush()
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise TreasuryError(f"تعذّر إدخال الحركة '{tx_reference}': {exc.orig}") from exc
        return tx, entries

    def _existing_idempotent(
        self, session, context: AuthorizationContext, idempotency_key: str | None
    ) -> TransactionModel | None:
        if not idempotency_key:
            return None
        return (
            session.query(TransactionModel)
            .filter(
                TransactionModel.tenant_id == self._tenant_of(context),
                TransactionModel.idempotency_key == idempotency_key,
            )
            .first()
        )

    # ── 1. تأسيس خزانة ────────────────────────────────────────────────────

    def establish_treasury(
        self,
        *,
        context: AuthorizationContext,
        code: str,
        name: str,
        currency: str,
        institution_code: str | None = None,
    ) -> dict[str, Any]:
        """أسِّس خزانة بعملة واحدة، تابعةً لمؤسسة أو مركزية."""
        resolve_money_delegation("treasury.establish", entrypoint="establish_treasury")
        require_domain_permission(context, "treasury.establish", PERMISSIONS_TREASURY_ESTABLISH)
        currency_code = normalize_currency(currency)
        if not name.strip():
            raise TreasuryError("الخزانة تلزمها تسمية")

        session = self._session()
        try:
            institution_id = None
            if institution_code:
                institution_id = self._institution_row(session, context, institution_code).id
            row = TreasuryModel(
                id=f"trs-{uuid.uuid4()}",
                code=code,
                name=name,
                institution_id=institution_id,
                currency=currency_code,
                status="active",
                tenant_id=self._tenant_of(context),
                established_by=context.principal_id,
            )
            session.add(row)
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise DuplicateCodeError(f"رمز الخزانة '{code}' مستعمل: {exc.orig}") from exc
            entity = self._treasury_dict(row)
        finally:
            session.close()

        trace = record_domain_trace(
            context,
            "treasury.establish",
            EVENT_TREASURY_ESTABLISHED,
            {
                "treasury_id": entity["id"],
                "code": entity["code"],
                "currency": entity["currency"],
                "institution_id": entity["institution_id"],
                "tenant_id": entity["tenant_id"],
            },
        )
        return {**entity, **trace}

    # ── 2. فتح حساب ───────────────────────────────────────────────────────

    def open_account(
        self,
        *,
        context: AuthorizationContext,
        treasury_code: str,
        code: str,
        name: str,
        kind: str,
        institution_code: str | None = None,
        department_code: str | None = None,
    ) -> dict[str, Any]:
        """افتح حسابًا في خزانة — بلا رصيد ابتدائي: الرصيد من الدفتر لا من مدخل."""
        resolve_money_delegation("treasury.account.open", entrypoint="open_account")
        require_domain_permission(context, "treasury.account.open", PERMISSIONS_ACCOUNT_OPEN)
        if kind not in ACCOUNT_KINDS:
            raise TreasuryError(f"نوع حساب غير معروف: '{kind}' — المسموح {list(ACCOUNT_KINDS)}")
        if not name.strip():
            raise TreasuryError("الحساب تلزمه تسمية")

        session = self._session()
        try:
            treasury = self._treasury_row(session, context, treasury_code)
            if treasury.status != "active":
                raise EntityStateError(f"الخزانة '{treasury_code}' حالتها '{treasury.status}'")
            institution_id = None
            if institution_code:
                institution_id = self._institution_row(session, context, institution_code).id
            department_id = None
            if department_code:
                department = (
                    session.query(DepartmentModel)
                    .filter(
                        DepartmentModel.code == department_code,
                        DepartmentModel.institution_id == institution_id,
                    )
                    .first()
                )
                if department is None:
                    raise AccountNotFoundError(
                        f"لا إدارة برمز '{department_code}' في المؤسسة المعطاة"
                    )
                require_tenant(context, department.tenant_id)
                department_id = department.id

            row = AccountModel(
                id=f"acc-{uuid.uuid4()}",
                code=code,
                name=name,
                treasury_id=treasury.id,
                institution_id=institution_id,
                department_id=department_id,
                kind=kind,
                currency=treasury.currency,
                status="open",
                tenant_id=self._tenant_of(context),
                opened_by=context.principal_id,
            )
            session.add(row)
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise DuplicateCodeError(
                    f"رمز الحساب '{code}' مستعمل في هذه الخزانة: {exc.orig}"
                ) from exc
            entity = self._account_dict(row)
        finally:
            session.close()

        trace = record_domain_trace(
            context,
            "treasury.account.open",
            EVENT_ACCOUNT_OPENED,
            {
                "account_id": entity["id"],
                "code": entity["code"],
                "treasury_id": entity["treasury_id"],
                "kind": entity["kind"],
                "currency": entity["currency"],
                "tenant_id": entity["tenant_id"],
            },
        )
        return {**entity, **trace}

    # ── 3. موازنة ─────────────────────────────────────────────────────────

    def create_budget(
        self,
        *,
        context: AuthorizationContext,
        treasury_code: str,
        institution_code: str,
        code: str,
        period: str,
        limit_amount: Any,
        department_code: str | None = None,
    ) -> dict[str, Any]:
        """أنشئ موازنة مؤسسة لفترة — حدٌّ أعلى فقط، بلا مجاميع يدخلها المستدعي."""
        resolve_money_delegation("treasury.budget.create", entrypoint="create_budget")
        require_domain_permission(context, "treasury.budget.create", PERMISSIONS_BUDGET_WRITE)
        if not _PERIOD_PATTERN.match(period or ""):
            raise TreasuryError(
                f"فترة غير مقبولة: '{period}' — الصيغ المقبولة YYYY أو YYYY-MM أو YYYY-Qn"
            )
        limit = require_positive(limit_amount, field="limit_amount")

        session = self._session()
        try:
            treasury = self._treasury_row(session, context, treasury_code)
            if treasury.status != "active":
                raise EntityStateError(f"الخزانة '{treasury_code}' حالتها '{treasury.status}'")
            institution = self._institution_row(session, context, institution_code)
            department_id = None
            if department_code:
                department = (
                    session.query(DepartmentModel)
                    .filter(
                        DepartmentModel.code == department_code,
                        DepartmentModel.institution_id == institution.id,
                    )
                    .first()
                )
                if department is None:
                    raise BudgetNotFoundError(
                        f"لا إدارة برمز '{department_code}' في المؤسسة '{institution_code}'"
                    )
                require_tenant(context, department.tenant_id)
                department_id = department.id

            row = BudgetModel(
                id=f"bdg-{uuid.uuid4()}",
                code=code,
                treasury_id=treasury.id,
                institution_id=institution.id,
                department_id=department_id,
                period=period,
                currency=treasury.currency,
                limit_amount=limit,
                status="open",
                tenant_id=self._tenant_of(context),
                created_by=context.principal_id,
            )
            session.add(row)
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise DuplicateCodeError(f"رمز الموازنة '{code}' مستعمل: {exc.orig}") from exc
            entity = self._budget_dict(row)
        finally:
            session.close()

        trace = record_domain_trace(
            context,
            "treasury.budget.create",
            EVENT_BUDGET_CREATED,
            {
                "budget_id": entity["id"],
                "code": entity["code"],
                "institution_id": entity["institution_id"],
                "period": entity["period"],
                "currency": entity["currency"],
                "limit_amount": entity["limit_amount"],
                "tenant_id": entity["tenant_id"],
            },
        )
        return {**entity, **trace}

    # ── 4. تخصيص ──────────────────────────────────────────────────────────

    def allocate(
        self,
        *,
        context: AuthorizationContext,
        budget_code: str,
        account_code: str,
        purpose: str,
        amount: Any,
        official_id: str,
        decision_id: str | None = None,
    ) -> dict[str, Any]:
        """خصِّص مبلغًا من موازنة إلى حساب — إذنُ صرفٍ لا حركة مال.

        المجموع المخصَّص يُقرأ من الصفوف، فلا يمكن أن تتجاوز التخصيصات الحدَّ ولو
        دخلت على دفعات. والتخصيص يُنسب إلى منصب قائم في مؤسسة الموازنة.
        """
        grant_required = gate_treasury_operation(
            context, "treasury.allocation.create", PERMISSIONS_ALLOCATION_WRITE
        )
        allocation_amount = require_positive(amount, field="amount")
        if not purpose.strip():
            raise TreasuryError("التخصيص يلزمه غرض مكتوب")

        session = self._session()
        try:
            budget = self._budget_row(session, context, budget_code)
            if budget.status != "open":
                raise EntityStateError(f"الموازنة '{budget_code}' حالتها '{budget.status}'")
            account = self._account_row(session, context, budget.treasury_id, account_code)
            official, authority = self._authorize_money(
                session,
                context,
                "treasury.allocation.create",
                entrypoint="allocate",
                required=PERMISSIONS_ALLOCATION_WRITE,
                grant_required=grant_required,
                institution_id=budget.institution_id,
                claimed_official_id=official_id,
                budget_id=budget.id,
                account_id=account.id,
                amount=allocation_amount,
            )
            self._require_same_currency(
                ("الموازنة", budget.currency), (f"الحساب '{account_code}'", account.currency)
            )
            if decision_id is not None:
                self._assert_authorizing_decision(session, context, decision_id, budget)

            # صفّ الموازنة يُقفل قبل قراءة المخصَّص، فتخصيصان متزامنان لا يريان
            # نفس «المتاح» ثم يمرّان معًا. والحالة تُعاد قراءتها بعد القفل: قد
            # طال الانتظار حتى التزم المنافس، فما قُرئ قبله صار قديمًا.
            self._lock_rows(session, [(BudgetModel, budget.id)])
            if budget.status != "open":
                raise EntityStateError(f"الموازنة '{budget_code}' حالتها '{budget.status}'")

            allocated = self._allocated_total(session, budget.id)
            limit = to_money(budget.limit_amount)
            if allocated + allocation_amount > limit:
                raise BudgetExceededError(
                    f"التخصيص {allocation_amount} يتجاوز المتاح في الموازنة "
                    f"'{budget_code}': الحدّ {limit} · المخصَّص {allocated}"
                )

            row = AllocationModel(
                id=f"alc-{uuid.uuid4()}",
                budget_id=budget.id,
                account_id=account.id,
                purpose=purpose,
                amount=allocation_amount,
                currency=budget.currency,
                status="active",
                decision_id=decision_id,
                tenant_id=self._tenant_of(context),
                created_by=context.principal_id,
            )
            session.add(row)
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise TreasuryError(f"تعذّر إدخال التخصيص: {exc.orig}") from exc
            entity = self._allocation_dict(row)
            entity["budget_code"] = budget.code
        finally:
            session.close()

        trace = record_domain_trace(
            context,
            "treasury.allocation.create",
            EVENT_ALLOCATION_CREATED,
            {
                "allocation_id": entity["id"],
                "budget_id": entity["budget_id"],
                "account_id": entity["account_id"],
                "amount": entity["amount"],
                "currency": entity["currency"],
                "decision_id": entity["decision_id"],
                "official_id": official_id,
                "tenant_id": entity["tenant_id"],
            },
        )
        return {**entity, **trace}

    def _assert_authorizing_decision(
        self,
        session,
        context: AuthorizationContext,
        decision_id: str,
        budget: BudgetModel,
    ) -> DecisionModel:
        """القرار يأذن بالمال فقط إن كان موجودًا وموافقةً وفي مؤسسة الموازنة."""
        decision = session.query(DecisionModel).filter(DecisionModel.id == decision_id).first()
        if decision is None:
            raise DecisionNotAuthorizingError(f"لا قرار بمعرّف '{decision_id}'")
        require_tenant(context, decision.tenant_id)
        if decision.outcome != "approved":
            raise DecisionNotAuthorizingError(
                f"القرار '{decision_id}' نتيجته '{decision.outcome}' — لا يأذن بمال"
            )
        case = session.query(CaseModel).filter(CaseModel.id == decision.case_id).first()
        if case is None or case.institution_id != budget.institution_id:
            raise DecisionNotAuthorizingError(
                f"القرار '{decision_id}' في مؤسسة أخرى غير مؤسسة الموازنة"
            )
        return decision

    # ── 5. تمويل الخزانة (إيراد) ──────────────────────────────────────────

    def post_funding(
        self,
        *,
        context: AuthorizationContext,
        treasury_code: str,
        cash_account_code: str,
        revenue_account_code: str,
        amount: Any,
        purpose: str,
        official_id: str,
        reference: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """أدخِل إيرادًا إلى الخزانة: مَدينٌ نقديّ ودائنٌ إيراديّ.

        الخزانة بلا مؤسسة لا تُموَّل: لا جهة تُسأل عن المال، و`official_id` يجب
        أن يكون منصبًا في مؤسسة الخزانة نفسها.
        """
        grant_required = gate_treasury_operation(
            context, "treasury.funding.post", PERMISSIONS_FUNDING
        )
        funding_amount = require_positive(amount, field="amount")
        if not purpose.strip():
            raise TreasuryError("الحركة تلزمها غرض مكتوب")

        session = self._session()
        try:
            existing = self._existing_idempotent(session, context, idempotency_key)
            if existing is not None:
                return {**self._transaction_dict(existing), "idempotent": True}

            treasury = self._treasury_row(session, context, treasury_code)
            if treasury.status != "active":
                raise EntityStateError(f"الخزانة '{treasury_code}' حالتها '{treasury.status}'")
            if treasury.institution_id is None:
                raise TreasuryError(f"الخزانة '{treasury_code}' بلا مؤسسة — لا تُموَّل بلا جهة مسؤولة")
            cash = self._account_row(session, context, treasury.id, cash_account_code)
            revenue = self._account_row(session, context, treasury.id, revenue_account_code)
            official, authority = self._authorize_money(
                session,
                context,
                "treasury.funding.post",
                entrypoint="post_funding",
                required=PERMISSIONS_FUNDING,
                grant_required=grant_required,
                institution_id=treasury.institution_id,
                claimed_official_id=official_id,
                account_id=cash.id,
                amount=funding_amount,
            )
            if cash.kind not in ("cash", "reserve"):
                raise TreasuryError(f"الحساب '{cash_account_code}' ليس نقديًّا ({cash.kind})")
            if revenue.kind != "revenue":
                raise TreasuryError(f"الحساب '{revenue_account_code}' ليس إيراديًّا ({revenue.kind})")

            tx, entries = self._post(
                session,
                context=context,
                treasury=treasury,
                kind="funding",
                amount=funding_amount,
                currency=treasury.currency,
                purpose=purpose,
                debit_account=cash,
                credit_account=revenue,
                official=official,
                authority=authority,
                reference=reference,
                institution_id=treasury.institution_id,
                idempotency_key=idempotency_key,
            )
            entity = self._transaction_dict(tx)
            entity["entries"] = [self._entry_dict(e) for e in entries]
        finally:
            session.close()

        trace = record_domain_trace(
            context,
            "treasury.funding.post",
            EVENT_TRANSACTION_POSTED,
            self._posted_event_payload(entity, official_id),
        )
        return {**entity, **trace}

    @staticmethod
    def _posted_event_payload(entity: dict[str, Any], official_id: str) -> dict[str, Any]:
        return {
            "transaction_id": entity["id"],
            "reference": entity["reference"],
            "treasury_id": entity["treasury_id"],
            "kind": entity["kind"],
            "amount": entity["amount"],
            "currency": entity["currency"],
            "budget_id": entity["budget_id"],
            "allocation_id": entity["allocation_id"],
            "task_id": entity["task_id"],
            "decision_id": entity["decision_id"],
            "official_id": official_id,
            "tenant_id": entity["tenant_id"],
        }

    # ── 6. صرف من تخصيص ───────────────────────────────────────────────────

    def disburse(
        self,
        *,
        context: AuthorizationContext,
        allocation_id: str,
        expense_account_code: str,
        amount: Any,
        purpose: str,
        official_id: str,
        task_id: str | None = None,
        decision_id: str | None = None,
        reference: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """اصرف من تخصيص: مَدينٌ مصروف ودائنٌ نقديّ.

        ثلاثة حدود مفروضة قبل أي كتابة: التخصيص نشط · المصروف عليه + المبلغ ≤
        مبلغه · ورصيد الحساب النقدي يكفي. وكلها مقروءة من الصفوف لا من عدّاد.
        """
        grant_required = gate_treasury_operation(
            context, "treasury.disbursement.post", PERMISSIONS_DISBURSE
        )
        spend = require_positive(amount, field="amount")
        if not purpose.strip():
            raise TreasuryError("الحركة تلزمها غرض مكتوب")

        session = self._session()
        try:
            existing = self._existing_idempotent(session, context, idempotency_key)
            if existing is not None:
                return {**self._transaction_dict(existing), "idempotent": True}

            allocation = self._allocation_row(session, context, allocation_id)
            if allocation.status != "active":
                raise EntityStateError(f"التخصيص حالته '{allocation.status}' — لا صرف عليه")
            budget = session.query(BudgetModel).filter(BudgetModel.id == allocation.budget_id).one()
            require_tenant(context, budget.tenant_id)
            if budget.status != "open":
                raise EntityStateError(f"الموازنة '{budget.code}' حالتها '{budget.status}'")
            treasury = (
                session.query(TreasuryModel).filter(TreasuryModel.id == budget.treasury_id).one()
            )
            if treasury.status != "active":
                raise EntityStateError(f"الخزانة '{treasury.code}' حالتها '{treasury.status}'")

            official, authority = self._authorize_money(
                session,
                context,
                "treasury.disbursement.post",
                entrypoint="disburse",
                required=PERMISSIONS_DISBURSE,
                grant_required=grant_required,
                institution_id=budget.institution_id,
                claimed_official_id=official_id,
                budget_id=budget.id,
                account_id=allocation.account_id,
                amount=spend,
            )
            if decision_id is not None:
                self._assert_authorizing_decision(session, context, decision_id, budget)

            cash = (
                session.query(AccountModel).filter(AccountModel.id == allocation.account_id).one()
            )
            expense = self._account_row(session, context, treasury.id, expense_account_code)
            if expense.kind != "expense":
                raise TreasuryError(
                    f"الحساب '{expense_account_code}' ليس حساب مصروف ({expense.kind})"
                )
            self._require_same_currency(
                ("التخصيص", allocation.currency),
                (f"الحساب '{expense_account_code}'", expense.currency),
            )

            # الحدود الثلاثة تُقرأ من الصفوف، فتُقفل أصولها أولًا وبالترتيب
            # القانوني: موازنة ← تخصيص ← حسابان. بهذا لا يمرّ صرفان متزامنان
            # على نفس التخصيص أو نفس الرصيد بقراءةٍ واحدة قديمة.
            self._lock_rows(
                session,
                [
                    (BudgetModel, budget.id),
                    (AllocationModel, allocation.id),
                    (AccountModel, cash.id),
                    (AccountModel, expense.id),
                ],
            )
            if allocation.status != "active":
                raise EntityStateError(f"التخصيص حالته '{allocation.status}' — لا صرف عليه")
            if budget.status != "open":
                raise EntityStateError(f"الموازنة '{budget.code}' حالتها '{budget.status}'")

            spent = self._spent_on_allocation(session, allocation.id)
            allocated = to_money(allocation.amount)
            if spent + spend > allocated:
                raise AllocationExceededError(
                    f"الصرف {spend} يتجاوز المتاح في التخصيص: المخصَّص {allocated} · "
                    f"المصروف {spent} · المتاح {to_money(allocated - spent)}"
                )
            balance = self._account_balance(session, cash)
            if spend > balance:
                raise InsufficientFundsError(
                    f"رصيد الحساب '{cash.code}' {balance} لا يكفي لصرف {spend}"
                )

            tx, entries = self._post(
                session,
                context=context,
                treasury=treasury,
                kind="disbursement",
                amount=spend,
                currency=allocation.currency,
                purpose=purpose,
                debit_account=expense,
                credit_account=cash,
                official=official,
                authority=authority,
                reference=reference,
                budget_id=budget.id,
                allocation_id=allocation.id,
                institution_id=budget.institution_id,
                task_id=task_id,
                decision_id=decision_id,
                idempotency_key=idempotency_key,
            )
            entity = self._transaction_dict(tx)
            entity["entries"] = [self._entry_dict(e) for e in entries]
        finally:
            session.close()

        trace = record_domain_trace(
            context,
            "treasury.disbursement.post",
            EVENT_TRANSACTION_POSTED,
            self._posted_event_payload(entity, official_id),
        )
        return {**entity, **trace}

    # ── 7. الصرف تنفيذًا لقرار حكومي، عبر العمود التنفيذي ─────────────────

    def execute_decision_disbursement(
        self,
        *,
        context: AuthorizationContext,
        allocation_id: str,
        expense_account_code: str,
        amount: Any,
        purpose: str,
        official_id: str,
        decision_id: str,
        idempotency_key: str | None = None,
        max_steps: int = 8,
    ) -> dict[str, Any]:
        """نفِّذ صرفًا أذن به قرارٌ حكومي: مهمّة في النواة أولًا، ثم المال.

        الترتيب مقصود ولا يُقلَب: تُقدَّم مهمّة إلى `ExecutiveCore` وتُشغَّل، **ولا
        تُكتب حركة إلّا إذا بلغت `completed`**. فإن فشلت فلا مال تحرَّك، ويُرفع
        `ExecutionFailedError` بالحالة النهائية كما قالها العمود التنفيذي —
        لا تُجمَّل ولا تُترجَم إلى نجاح.

        وتُخزَّن `task_id` مفتاحًا أجنبيًّا في الحركة، فالحركة لا تدّعي تنفيذًا لا
        صفَّ له في `tasks`.
        """
        resolve_money_delegation(
            "treasury.disbursement.post", entrypoint="execute_decision_disbursement"
        )
        require_domain_permission(context, "treasury.disbursement.post", PERMISSIONS_DISBURSE)
        spend = require_positive(amount, field="amount")

        session = self._session()
        try:
            existing = self._existing_idempotent(session, context, idempotency_key)
            if existing is not None:
                return {**self._transaction_dict(existing), "idempotent": True}
            allocation = self._allocation_row(session, context, allocation_id)
            budget = session.query(BudgetModel).filter(BudgetModel.id == allocation.budget_id).one()
            require_tenant(context, budget.tenant_id)
            self._assert_authorizing_decision(session, context, decision_id, budget)
        finally:
            session.close()

        task = self._core.submit(
            DISBURSEMENT_TASK_TYPE,
            f"تنفيذ صرف {spend} {allocation.currency} تنفيذًا للقرار {decision_id}: {purpose}",
            domain=DISBURSEMENT_TASK_DOMAIN,
            tenant_id=self._tenant_of(context),
        )
        outcome = self._core.run(task["id"], max_steps=max_steps)
        final_state = outcome.get("final_state")
        if final_state != "completed":
            raise ExecutionFailedError(
                f"مهمّة الصرف '{task['id']}' انتهت بحالة '{final_state}' — لا حركة مالية"
            )

        result = self.disburse(
            context=context,
            allocation_id=allocation_id,
            expense_account_code=expense_account_code,
            amount=spend,
            purpose=purpose,
            official_id=official_id,
            task_id=task["id"],
            decision_id=decision_id,
            idempotency_key=idempotency_key,
        )
        return {**result, "task_final_state": final_state}

    # ── 8. عكس حركة ───────────────────────────────────────────────────────

    def reverse_transaction(
        self,
        *,
        context: AuthorizationContext,
        reference: str,
        reason: str,
        official_id: str,
    ) -> dict[str, Any]:
        """اعكس حركة بحركةٍ مقلوبة جديدة — لا حذف ولا كتابة فوق التاريخ.

        الأصل يبقى كما هو، وتُعلَّم حالته `reversed` إشارةً إلى وجود عكسٍ له. وقيد
        `unique` على `reverses_transaction_id` يمنع عكسين لحركة واحدة في القاعدة
        نفسها، لا في الذاكرة.
        """
        grant_required = gate_treasury_operation(
            context, "treasury.transaction.reverse", PERMISSIONS_REVERSAL
        )
        if not reason.strip():
            raise TreasuryError("العكس يلزمه سبب مكتوب")

        session = self._session()
        try:
            original = self._transaction_row(session, context, reference)
            # الأصل يُقفل قبل قراءة حالته: عكسان متزامنان يقرآن 'posted' معًا،
            # فيرفض القيدُ الفريد الثاني بخطأ سلامة. مع القفل يقرأ الثاني
            # 'reversed' فيُرفض برسالة العمل الصحيحة.
            self._lock_rows(session, [(TransactionModel, original.id)])
            if original.status != "posted":
                raise TransactionReversedError(
                    f"الحركة '{reference}' حالتها '{original.status}' — لا تُعكس"
                )
            if original.kind == "reversal":
                raise TransactionReversedError("حركة العكس لا تُعكس — تُعكَس الحركة الأصلية")

            treasury = (
                session.query(TreasuryModel).filter(TreasuryModel.id == original.treasury_id).one()
            )
            entries = (
                session.query(LedgerEntryModel)
                .filter(LedgerEntryModel.transaction_id == original.id)
                .all()
            )
            debit_entry = next(e for e in entries if e.direction == "debit")
            credit_entry = next(e for e in entries if e.direction == "credit")
            # المقلوب: ما كان مَدينًا يصير دائنًا، فيلغي الأثر حسابيًّا.
            new_debit = (
                session.query(AccountModel).filter(AccountModel.id == credit_entry.account_id).one()
            )
            new_credit = (
                session.query(AccountModel).filter(AccountModel.id == debit_entry.account_id).one()
            )

            institution_id = original.institution_id
            if institution_id is None:
                raise TreasuryError(f"الحركة '{reference}' بلا مؤسسة — لا يمكن نسبة عكسها إلى منصب")
            official, authority = self._authorize_money(
                session,
                context,
                "treasury.transaction.reverse",
                entrypoint="reverse_transaction",
                required=PERMISSIONS_REVERSAL,
                grant_required=grant_required,
                institution_id=institution_id,
                claimed_official_id=official_id,
                budget_id=original.budget_id,
                amount=to_money(original.amount),
            )

            reversal, reversal_entries = self._post(
                session,
                context=context,
                treasury=treasury,
                kind="reversal",
                amount=to_money(original.amount),
                currency=original.currency,
                purpose=f"عكس الحركة {original.reference}: {reason}",
                debit_account=new_debit,
                credit_account=new_credit,
                official=official,
                authority=authority,
                budget_id=original.budget_id,
                allocation_id=original.allocation_id,
                institution_id=institution_id,
                decision_id=original.decision_id,
                reverses_transaction_id=original.id,
            )
            original.status = "reversed"
            session.commit()
            entity = self._transaction_dict(reversal)
            entity["entries"] = [self._entry_dict(e) for e in reversal_entries]
            entity["reversed_reference"] = original.reference
        finally:
            session.close()

        trace = record_domain_trace(
            context,
            "treasury.transaction.reverse",
            EVENT_TRANSACTION_REVERSED,
            {
                "transaction_id": entity["id"],
                "reference": entity["reference"],
                "reverses_transaction_id": entity["reverses_transaction_id"],
                "reversed_reference": entity["reversed_reference"],
                "treasury_id": entity["treasury_id"],
                "amount": entity["amount"],
                "currency": entity["currency"],
                "official_id": official_id,
                "reason": reason,
                "tenant_id": entity["tenant_id"],
            },
        )
        return {**entity, **trace}

    # ── القراءات ──────────────────────────────────────────────────────────

    def account_balance(
        self, *, context: AuthorizationContext, treasury_code: str, account_code: str
    ) -> dict[str, Any]:
        """رصيد حساب — محسوبٌ من قيوده في كل نداء."""
        require_domain_permission(context, "treasury.read", PERMISSIONS_TREASURY_READ)
        session = self._session()
        try:
            treasury = self._treasury_row(session, context, treasury_code)
            account = self._account_row(session, context, treasury.id, account_code)
            rows = (
                session.query(LedgerEntryModel)
                .filter(LedgerEntryModel.account_id == account.id)
                .all()
            )
            debits = money_sum(r.amount for r in rows if r.direction == "debit")
            credits = money_sum(r.amount for r in rows if r.direction == "credit")
            balance = self._account_balance(session, account)
            return {
                **self._account_dict(account),
                "normal_balance": NORMAL_BALANCE[account.kind],
                "total_debits": format_money(debits),
                "total_credits": format_money(credits),
                "balance": format_money(balance),
                "entries_count": len(rows),
            }
        finally:
            session.close()

    def budget_balance(self, *, context: AuthorizationContext, budget_code: str) -> dict[str, Any]:
        """موازنة: الحدّ والمخصَّص والمصروف والمتبقّي — كلها مشتقّة لا مخزَّنة."""
        require_domain_permission(context, "treasury.read", PERMISSIONS_TREASURY_READ)
        session = self._session()
        try:
            budget = self._budget_row(session, context, budget_code)
            limit = to_money(budget.limit_amount)
            allocated = self._allocated_total(session, budget.id)
            spent = self._spent_on_budget(session, budget.id)
            allocations = (
                session.query(AllocationModel).filter(AllocationModel.budget_id == budget.id).all()
            )
            return {
                **self._budget_dict(budget),
                "allocated": format_money(allocated),
                "unallocated": format_money(to_money(limit - allocated)),
                "spent": format_money(spent),
                "remaining": format_money(to_money(limit - spent)),
                "allocations": [
                    {
                        **self._allocation_dict(row),
                        "spent": format_money(self._spent_on_allocation(session, row.id)),
                        "available": format_money(
                            to_money(
                                to_money(row.amount) - self._spent_on_allocation(session, row.id)
                            )
                        ),
                    }
                    for row in allocations
                ],
                "derived": True,
            }
        finally:
            session.close()

    def list_transactions(
        self,
        *,
        context: AuthorizationContext,
        treasury_code: str | None = None,
        budget_code: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """حركات المستأجر، الأحدث أولًا."""
        require_domain_permission(context, "treasury.read", PERMISSIONS_TREASURY_READ)
        session = self._session()
        try:
            query = session.query(TransactionModel).filter(
                TransactionModel.tenant_id == self._tenant_of(context)
            )
            if treasury_code:
                treasury = self._treasury_row(session, context, treasury_code)
                query = query.filter(TransactionModel.treasury_id == treasury.id)
            if budget_code:
                budget = self._budget_row(session, context, budget_code)
                query = query.filter(TransactionModel.budget_id == budget.id)
            rows = (
                query.order_by(TransactionModel.created_at.desc())
                .limit(max(1, min(limit, 500)))
                .all()
            )
            return [self._transaction_dict(row) for row in rows]
        finally:
            session.close()

    def transaction_file(self, *, context: AuthorizationContext, reference: str) -> dict[str, Any]:
        """ملفّ حركة: رأسها وطرفاها ومَن عكسها إن عُكست."""
        require_domain_permission(context, "treasury.read", PERMISSIONS_TREASURY_READ)
        session = self._session()
        try:
            row = self._transaction_row(session, context, reference)
            entries = (
                session.query(LedgerEntryModel)
                .filter(LedgerEntryModel.transaction_id == row.id)
                .all()
            )
            reversal = (
                session.query(TransactionModel)
                .filter(TransactionModel.reverses_transaction_id == row.id)
                .first()
            )
            debits = money_sum(e.amount for e in entries if e.direction == "debit")
            credits = money_sum(e.amount for e in entries if e.direction == "credit")
            return {
                "transaction": self._transaction_dict(row),
                "entries": [self._entry_dict(e) for e in entries],
                "balanced": debits == credits,
                "total_debits": format_money(debits),
                "total_credits": format_money(credits),
                "reversed_by": self._transaction_dict(reversal) if reversal else None,
            }
        finally:
            session.close()

    def treasury_health(self) -> dict[str, Any]:
        """عدّادات فعلية من القاعدة — لا أرقام محفوظة في الذاكرة."""
        session = self._session()
        try:
            return {
                "treasuries": session.query(TreasuryModel).count(),
                "accounts": session.query(AccountModel).count(),
                "budgets": session.query(BudgetModel).count(),
                "allocations": session.query(AllocationModel).count(),
                "transactions": session.query(TransactionModel).count(),
                "ledger_entries": session.query(LedgerEntryModel).count(),
                "money_backend": "NUMERIC(20,4) / Decimal",
                "double_entry": "balanced two-leg ledger (full accounting: PARTIAL)",
            }
        finally:
            session.close()


# === نسخة مشتركة ===

_TREASURY: StateTreasury | None = None


def get_state_treasury() -> StateTreasury:
    """النسخة المشتركة — لا خزانة ثانية في العملية."""
    global _TREASURY  # noqa: PLW0603 — نسخة واحدة مقصودة، كما في بقية الخدمات
    if _TREASURY is None:
        _TREASURY = StateTreasury()
    return _TREASURY


def reset_state_treasury() -> None:
    """إعادة التهيئة — للاختبارات حصرًا."""
    global _TREASURY  # noqa: PLW0603 — إعادة تهيئة مقصودة للاختبارات
    _TREASURY = None


__all__ = [
    "DISBURSEMENT_TASK_DOMAIN",
    "DISBURSEMENT_TASK_TYPE",
    "EVENT_ACCOUNT_OPENED",
    "EVENT_ALLOCATION_CREATED",
    "EVENT_BUDGET_CREATED",
    "EVENT_TRANSACTION_POSTED",
    "EVENT_TRANSACTION_REVERSED",
    "EVENT_TREASURY_ESTABLISHED",
    "TREASURY_EVENTS",
    "AccountNotFoundError",
    "AllocationExceededError",
    "AllocationNotFoundError",
    "BudgetExceededError",
    "TreasuryContentionError",
    "lock_query",
    "BudgetNotFoundError",
    "CurrencyMismatchError",
    "DecisionNotAuthorizingError",
    "DuplicateCodeError",
    "EntityStateError",
    "ExecutionFailedError",
    "InsufficientFundsError",
    "LedgerImbalanceError",
    "MoneyError",
    "OfficialNotFoundError",
    "StateTreasury",
    "TransactionNotFoundError",
    "TransactionReversedError",
    "TreasuryError",
    "TreasuryNotFoundError",
    "get_state_treasury",
    "reset_state_treasury",
]
