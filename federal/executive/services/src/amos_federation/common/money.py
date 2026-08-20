"""
AMOS-Federation State Treasury — Money Primitive
الهدف: مالٌ بـDecimal دقيق، ونوع عمود واحد لكل مبلغ في الدولة
النطاق: common — مفردةٌ مشتركةٌ لا مِلكَ خدمةٍ واحدة
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17 (R7-B)
تاريخ آخر تعديل: 2026-08-20 (Q-20)

## لماذا نُقِلَ هذا الملفُّ من `services/state_treasury` إلى `common`

وُلِدَ في خزانةِ الدولةِ لأنّها كانت وحدَها تعرفُ المال. ثمّ حُسِمَ **Q-20** بأن
يكونَ لكلِّ مبلغٍ تمثيلٌ واحد، فصارَ العقدُ لازمًا لأربعِ خدماتٍ: القضاءُ
(`state_case_claims.amount`) والسجلُّ (`state_authority_grants.max_amount`)
والولايةُ (`state_government_delegations.max_amount`) وبوّابةُ النماذج
(`model_cost_log.cost_usd`). واستيرادُه من موضعِه القديمِ كان يُشعِلُ
استيرادًا دائريًّا حقيقيًّا (`state_treasury/__init__` يجرُّ الخدمةَ كلَّها،
وهي تجرُّ `government_services`، وهي تعودُ إلى `national_registry`).

فالنقلُ **رفعُ مفردةٍ إلى موضعِها الصحيح** لا تفكيكُ خدمة: المضمونُ لم يتغيّرْ
حرفًا، والمسارُ القديمُ يبقى صالحًا بإعادةِ تصديرٍ صريحةٍ في
`services/state_treasury/money.py` كي لا يُكسَرَ ما يستوردُ منه.

## لماذا ليس `Float`

في المستودع خزانةٌ سابقة (Phase 10، `services/governance/treasury.py`) تخزّن المال
في `Float`، وفي PostgreSQL صار العمود `double precision`. هذا خطأ لا رأي: جمع
`0.1 + 0.2` في العائم لا يساوي `0.3`، وميزانيةُ دولة لا تُبنى على تقريب. فلا يُلمس
ذلك الجدول القديم في هذه الوحدة (ليس هذا نطاقها)، **ولا يُبنى الجديد بخطئه**.

## ما يفعله هذا الملفّ

- `MoneyType`: عمود `NUMERIC(20, 4)` حقيقي في PostgreSQL، والقيمة في بايثون
  `Decimal` مُقرَّبة إلى أربع منازل دائمًا، ذهابًا وعودة.
- `to_money`: البوّابة الوحيدة لتحويل مدخلٍ إلى مبلغ. تقبل `Decimal` و`int`
  و`str`، و**ترفض `float` صراحةً** — فلا يتسرّب العائم من واجهةٍ أو اختبار.
- `money_sum`: جمع مبالغ بـ`Decimal`.

## حدٌّ يُقال ولا يُخفى

SQLite لا يملك نوعًا عشريًّا حقيقيًّا؛ يخزّن `NUMERIC` عائمًا مزدوجًا. فالدقّة
المطلقة مضمونة على **PostgreSQL** (المصدر التشغيلي)، وعلى SQLite تُضمَن ضمن حدّ
المقدار المفروض أدناه: `MONEY_MAX × 10⁴ < 2⁵³`. لذلك `MONEY_MAX` ليس رقمًا
تجميليًّا، بل هو ما يجعل الدقّة قابلة للبرهان في اللهجتين، وهو مفروض بقيد `CHECK`
في القاعدة لا بفحصٍ في بايثون وحده.

## لا `SUM` على المال في SQL

مجاميع المال تُحسب في بايثون فوق `Decimal` (`money_sum`)، لا بـ`func.sum`: على
SQLite كان المجموع سيمرّ بالعائم فيُنتج `1234.5599999999999` في تقرير موازنة.
وهذا محروسٌ باختبار ساكن يمنع `func.sum` في خدمة الخزانة.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

from sqlalchemy import Numeric
from sqlalchemy.types import TypeDecorator

#: أربع منازل عشرية — تكفي العملات ذات المنزلتين وتترك مجالًا لأسعار الوحدة.
MONEY_SCALE = 4
MONEY_QUANT = Decimal(1).scaleb(-MONEY_SCALE)  # Decimal("0.0001")

#: الحدّ الأعلى للمبلغ الواحد: 9×10¹¹. وهو مشتقّ لا مُختار:
#: 9e11 × 10⁴ = 9e15 < 2⁵³ ≈ 9.007e15، فيبقى كل مبلغ قابلًا للتمثيل تمامًا حتى
#: على SQLite. ومفروض بـ`CHECK` في كل عمود مبلغ.
MONEY_MAX = Decimal("900000000000")

CURRENCY_LENGTH = 3


class MoneyError(ValueError):
    """مبلغ غير مقبول — نوعًا أو مقدارًا."""


def to_money(value: Any, *, field: str = "amount") -> Decimal:
    """حوِّل مدخلًا إلى مبلغ `Decimal` بأربع منازل، أو ارفضه.

    `float` مرفوض بقصد: قبولُه يعني إدخال خطأ التمثيل من الحدّ الخارجي، ثم
    الاعتذار عنه في التقارير. من يملك عائمًا يحوّله نصًّا أولًا وهو يعلم أنه يقرّب.

    Raises:
        MoneyError: عائم، أو نوع غير مفهوم، أو مقدار خارج الحدّ.
    """
    if isinstance(value, bool):
        raise MoneyError(f"{field}: قيمة منطقية ليست مبلغًا")
    if isinstance(value, float):
        raise MoneyError(f"{field}: العائم غير مقبول للمال — مرِّر Decimal أو نصًّا مثل '12.3400'")
    if isinstance(value, Decimal):
        amount = value
    elif isinstance(value, int):
        amount = Decimal(value)
    elif isinstance(value, str):
        try:
            amount = Decimal(value.strip())
        except InvalidOperation as exc:
            raise MoneyError(f"{field}: نصٌّ ليس عددًا عشريًّا: '{value}'") from exc
    else:
        raise MoneyError(f"{field}: نوع غير مقبول للمال: {type(value).__name__}")

    if not amount.is_finite():
        raise MoneyError(f"{field}: مبلغ غير منتهٍ")
    quantized = amount.quantize(MONEY_QUANT)
    if abs(quantized) > MONEY_MAX:
        raise MoneyError(f"{field}: المقدار يتجاوز الحدّ المسموح {MONEY_MAX}")
    return quantized


def require_positive(value: Any, *, field: str = "amount") -> Decimal:
    """مبلغٌ موجب حصرًا — الصفر والسالب مرفوضان في الحركة المالية.

    السالب يُعبَّر عنه باتجاه القيد (`debit`/`credit`) لا بإشارة المبلغ. ولو سُمح
    بالإشارتين لصار للحركة الواحدة تمثيلان، واختلّ كل مجموع.
    """
    amount = to_money(value, field=field)
    if amount <= 0:
        raise MoneyError(f"{field}: المبلغ يجب أن يكون موجبًا (وُجد {amount})")
    return amount


def money_sum(values: Iterable[Any]) -> Decimal:
    """اجمع مبالغ بـ`Decimal` — لا عائم في أي خطوة."""
    total = Decimal(0)
    for value in values:
        total += to_money(value)
    return total.quantize(MONEY_QUANT)


def format_money(value: Any) -> str:
    """نصٌّ ثابت المنازل، صالحٌ للحمولة والحدث والتقرير.

    الحمولات تحمل المال نصًّا لا عددًا: `json` لا يعرف `Decimal`، وتحويله إلى
    `float` في الحدث كان سيُعيد الخطأ الذي طُرد من القاعدة.
    """
    return f"{to_money(value):.{MONEY_SCALE}f}"


def normalize_currency(value: str, *, field: str = "currency") -> str:
    """رمز عملة من ثلاثة أحرف كبيرة (ISO-4217 شكلًا لا تحقّقًا من قائمة).

    لا قائمة عملات مُغلقة هنا: التحقّق من وجود العملة فعلًا يلزمه مصدرٌ خارجي،
    وادّعاؤه اليوم كان سيكون تحقّقًا وهميًّا. المفروض هو الشكل، في القاعدة أيضًا.
    """
    code = (value or "").strip().upper()
    if len(code) != CURRENCY_LENGTH or not code.isalpha() or not code.isascii():
        raise MoneyError(f"{field}: رمز العملة يجب أن يكون ثلاثة أحرف لاتينية، وُجد '{value}'")
    return code


class MoneyType(TypeDecorator):  # type: ignore[type-arg]
    """عمود مبلغ: `NUMERIC(20, 4)` في القاعدة، و`Decimal` في بايثون دائمًا."""

    impl = Numeric(20, MONEY_SCALE, asdecimal=True)
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> Decimal | None:
        if value is None:
            return None
        return to_money(value)

    def process_result_value(self, value: Any, dialect: Any) -> Decimal | None:
        """التقريب عند القراءة يجعل SQLite يعيد ما كُتب لا تقريبَ عائمٍ له."""
        if value is None:
            return None
        if isinstance(value, float):  # SQLite: NUMERIC مخزَّن عائمًا
            return Decimal(repr(value)).quantize(MONEY_QUANT)
        return to_money(value)


#: تعبير `CHECK` مشترك لكل عمود مبلغ موجب — نصٌّ واحد فلا تتباعد الصياغات.
def positive_money_check(column: str) -> str:
    """قيد: موجبٌ وداخل الحدّ. يعمل حرفيًّا في PostgreSQL وSQLite."""
    return f"{column} > 0 AND {column} <= {MONEY_MAX}"


def currency_check(column: str = "currency") -> str:
    """قيد شكل العملة — ثلاثة أحرف كبيرة، بتعبير تقبله اللهجتان."""
    return f"length({column}) = {CURRENCY_LENGTH} AND {column} = upper({column})"


__all__ = [
    "CURRENCY_LENGTH",
    "MONEY_MAX",
    "MONEY_QUANT",
    "MONEY_SCALE",
    "MoneyError",
    "MoneyType",
    "currency_check",
    "format_money",
    "money_sum",
    "normalize_currency",
    "positive_money_check",
    "require_positive",
    "to_money",
]
