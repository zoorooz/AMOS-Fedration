"""
AMOS-Federation State Treasury — Money Primitive (إعادةُ تصدير)
الهدف: إبقاءُ المسارِ القديمِ صالحًا بعدَ رفعِ مفردةِ المالِ إلى `common/money.py`
       في Q-20، فلا يُكسَرُ مستوردٌ قائمٌ ولا يُنسَخُ عقدٌ مرّتين.
النطاق: services/state_treasury
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17 (R7-B)
تاريخ آخر تعديل: 2026-08-20 (Q-20)

## لماذا ملفٌّ لا يحملُ منطقًا

لأنَّ نسخَ العقدِ في موضعَين هو الطريقُ إلى عقدَين مختلفَين. فالمصدرُ الوحيدُ
`amos_federation.common.money`، وهذا الملفُّ بابٌ إليه لا نسخةٌ منه. ومن أرادَ
تعديلَ دقّةِ المالِ أو حدِّه فليُعدِّلْه هناك؛ فلا شيءَ هنا يُعدَّل.
"""

from __future__ import annotations

from amos_federation.common.money import (  # noqa: F401 — إعادةُ تصديرٍ مقصودة
    CURRENCY_LENGTH,
    MONEY_MAX,
    MONEY_QUANT,
    MONEY_SCALE,
    MoneyError,
    MoneyType,
    currency_check,
    format_money,
    money_sum,
    normalize_currency,
    positive_money_check,
    require_positive,
    to_money,
)

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
