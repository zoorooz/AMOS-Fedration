"""
AMOS-Federation — اختبارُ توحيدِ تمثيلِ المبلغ (Q-20)
الهدف: أن يُثبَّتَ قرارُ Q-20 بحيث لا يُنتقَضَ صمتًا: كلُّ عمودٍ ماليٍّ يملكُه
       هذا المستودعُ تمثيلُه `NUMERIC(20,4)` عبرَ `MoneyType`، والهجرةُ 014
       تُعلِنُ التحويلَ نصًّا صريحًا، والمستثنياتُ مستثناةٌ بعلّةٍ لا بسهو.
النطاق: federal/executive/services/tests
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-20 (Q-20)
تاريخ آخر تعديل: 2026-08-20 (Q-20)

## لماذا اختبارٌ ساكنٌ لا حيٌّ فقط

لأنَّ الانتقاضَ المُحتمَلَ ليس خطأً في التشغيلِ بل **رجوعٌ في التصريح**: أن
يكتبَ آتٍ `Column(String)` لمبلغٍ جديدٍ فيمرَّ لأنَّ كلَّ الاختباراتِ الحيّةِ
تنجح. فالحرسُ هنا يقرأُ التصريحَ نفسَه: أنواعَ الأعمدةِ في `metadata`، ونصَّ
الهجرةِ على القرص. ومن أرادَ نقضَ Q-20 فعليه أن يُسقِطَ هذا الملفَّ صراحةً،
وذلك أثرٌ يُرى في المُراجعةِ لا يمرُّ في الظلّ.
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Numeric

from amos_federation.common.money import MONEY_MAX, MONEY_SCALE, MoneyType, to_money

MIGRATION = (
    Path(__file__).resolve().parents[1] / "migrations" / "014_unify_money_representation.sql"
)

#: الأعمدةُ التي وحَّدَها القرار — (الجدول، العمود، أيُسمَحُ بالغياب).
UNIFIED_MONEY_COLUMNS: tuple[tuple[str, str, bool], ...] = (
    ("state_case_claims", "amount", True),
    ("state_authority_grants", "max_amount", True),
    ("state_government_delegations", "max_amount", True),
    ("model_cost_log", "cost_usd", False),
)

#: أعمدةٌ اسمُها ماليٌّ ومعناها ليس مالًا — لا تُهاجَرُ، وهذا مُثبَّتٌ لا مُفترَض.
NOT_MONEY_BY_MEANING: tuple[tuple[str, str, str], ...] = (
    ("agents", "token_budget", "ميزانيّةُ رِموزٍ لا مال"),
    ("agent_population", "token_budget", "ميزانيّةُ رِموزٍ لا مال"),
    ("compliance_reports", "total_audits", "عَدَدٌ لا مبلغ"),
)


def _column(table_name: str, column_name: str):
    """يجدُ العمودَ في `metadata` بعدَ تحميلِ كلِّ النماذجِ المعنيّة."""
    import amos_federation.services.federal_state.models  # noqa: F401
    import amos_federation.services.model_gateway.model_layer as _model_layer  # noqa: F401
    from amos_federation.common.database import Base

    table = Base.metadata.tables.get(table_name)
    if table is None:
        # `model_cost_log` يعيشُ على قاعدةٍ تعريفيّةٍ أخرى في بوّابةِ النماذج.
        for obj in vars(_model_layer).values():
            if getattr(obj, "__tablename__", None) == table_name:
                table = obj.__table__
                break
    assert table is not None, f"لا جدولَ باسم {table_name} في أيِّ قاعدةٍ تعريفيّة"
    assert column_name in table.c, f"لا عمودَ {column_name} في {table_name}"
    return table.c[column_name]


# ============================================================================
# 1 · التصريحُ نفسُه
# ============================================================================


@pytest.mark.parametrize(("table", "column", "nullable"), UNIFIED_MONEY_COLUMNS)
def test_01_unified_columns_declare_the_money_type(table: str, column: str, nullable: bool) -> None:
    """كلُّ عمودٍ وحَّدَه Q-20 نوعُه `MoneyType` لا نصًّا ولا عائمًا ولا صحيحًا."""
    col = _column(table, column)
    assert isinstance(col.type, MoneyType), (
        f"{table}.{column} نوعُه {type(col.type).__name__} لا MoneyType — "
        "وهذا نقضٌ لِـQ-20: للمبلغِ تمثيلٌ واحدٌ لا أربعة"
    )
    assert (
        col.nullable is nullable
    ), f"{table}.{column} احتمالُ غيابِه تغيَّر — وغيابُ المبلغِ معنًى لا تفصيلٌ فنّيّ"


@pytest.mark.parametrize(("table", "column", "_nullable"), UNIFIED_MONEY_COLUMNS)
def test_02_unified_columns_carry_the_declared_precision(
    table: str, column: str, _nullable: bool
) -> None:
    """الدقّةُ مُعلَنةٌ لا ضِمنيّة: `NUMERIC(20,4)` تحتَ `MoneyType`."""
    impl = _column(table, column).type.impl
    assert isinstance(impl, Numeric), f"{table}.{column} تحقيقُه ليس Numeric"
    assert impl.scale == MONEY_SCALE, f"{table}.{column} منازلُه {impl.scale} لا {MONEY_SCALE}"
    assert impl.precision == 20, f"{table}.{column} دقّتُه {impl.precision} لا 20"
    assert impl.asdecimal is True, f"{table}.{column} يُقرأُ عائمًا — وهذا هو الخطأُ عينُه"


@pytest.mark.parametrize(("table", "column", "why"), NOT_MONEY_BY_MEANING)
def test_03_a_money_looking_name_is_not_migrated_by_its_name(
    table: str, column: str, why: str
) -> None:
    """ما اسمُه ماليٌّ ومعناه ليس مالًا يبقى كما هو — الهجرةُ للمعنى لا للاسم."""
    import amos_federation.services.federal_state.models  # noqa: F401
    from amos_federation.common.database import Base

    tbl = Base.metadata.tables.get(table)
    if tbl is None or column not in tbl.c:
        pytest.skip(f"{table}.{column} ليس في هذه القاعدةِ التعريفيّة")
    assert not isinstance(tbl.c[column].type, MoneyType), (
        f"{table}.{column} هُوجِرَ إلى MoneyType وهو {why} — " "ومن هاجرَ اسمًا لا معنًى أفسدَ المعنيَين"
    )


# ============================================================================
# 2 · الهجرةُ على القرص
# ============================================================================


def test_04_the_migration_file_exists_and_declares_its_identity() -> None:
    """الهجرةُ 014 موجودةٌ وتُعلِنُ هدفَها ومالكَها — مادةُ 009."""
    assert MIGRATION.is_file(), "الهجرةُ 014 غائبةٌ — فالتحويلُ في النماذجِ بلا سَنَدٍ في القاعدة"
    text = MIGRATION.read_text(encoding="utf-8")
    for field in ("الهدف:", "النطاق:", "المالك:", "تاريخ الإنشاء:"):
        assert field in text, f"الهجرةُ 014 لا تُعلِنُ «{field}»"


@pytest.mark.parametrize(("table", "column", "_nullable"), UNIFIED_MONEY_COLUMNS)
def test_05_the_migration_alters_every_unified_column(
    table: str, column: str, _nullable: bool
) -> None:
    """لكلِّ عمودٍ وحَّدَه القرارُ سطرُ تحويلٍ صريحٌ في الهجرة."""
    text = MIGRATION.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"ALTER TABLE IF EXISTS {table}\s+ALTER COLUMN {column} TYPE NUMERIC\(20,4\)",
        re.MULTILINE,
    )
    assert pattern.search(text), f"لا سطرَ تحويلٍ لـ{table}.{column} في الهجرة 014"
    assert "::NUMERIC(20,4)" in text, "التحويلُ بلا `USING ... ::NUMERIC` قد يفشلُ على نصٍّ قائم"


@pytest.mark.parametrize(("table", "column", "_nullable"), UNIFIED_MONEY_COLUMNS)
def test_06_every_unified_column_gains_a_bound_check(
    table: str, column: str, _nullable: bool
) -> None:
    """التحويلُ بلا `CHECK` يُبدِّلُ التمثيلَ ولا يحرسُ المقدار."""
    text = MIGRATION.read_text(encoding="utf-8")
    assert f"ck_{table}_{column}" in text, f"لا قيدَ مقدارٍ لـ{table}.{column}"
    assert str(int(MONEY_MAX)) in text, (
        f"حدُّ المالِ الأعلى {MONEY_MAX} غيرُ مذكورٍ في الهجرة — " "فالقيدُ إمّا أوسعُ من العقدِ أو أضيق"
    )


def test_07_the_migration_does_not_touch_what_it_declared_untouched() -> None:
    """المستثنياتُ مستثناةٌ فعلًا: لا `ALTER` لِـamos-credit ولا لِـ`institutions`."""
    text = MIGRATION.read_text(encoding="utf-8")
    alter_lines = [ln for ln in text.splitlines() if ln.strip().startswith("ALTER TABLE")]
    forbidden = ("treasury_reports", "treasury_transactions", "institutions ", "agents ")
    for line in alter_lines:
        for name in forbidden:
            assert name not in line, (
                f"الهجرةُ 014 تمسُّ «{name.strip()}» وقد أعلنَت أنّها لا تمسُّه — "
                "والحدُّ المُعلَنُ المخروقُ أسوأُ من غيرِ المُعلَن"
            )
    # وتُعلِنُ العلّةَ لا تسكتُ عنها.
    assert "Q-17" in text, "استثناءُ amos-credit بلا سَنَدٍ في Q-17 يصيرُ سهوًا"
    assert "Q-28" in text, "استثناءٌ بلا سؤالٍ مُقيَّدٍ هو صمتٌ لا قرار"


# ============================================================================
# 3 · العقدُ حيًّا
# ============================================================================


def test_08_the_money_gate_still_refuses_float() -> None:
    """بابُ المالِ يرفضُ العائمَ — وهذا هو أصلُ Q-20 لا فرعُه."""
    with pytest.raises(Exception):  # noqa: B017 — MoneyError نوعُه من الوحدةِ نفسِها
        to_money(1.5)  # type: ignore[arg-type]
    assert to_money("1.5") == Decimal("1.5000")
    assert to_money(Decimal("2")) == Decimal("2.0000")


def test_09_the_old_import_path_is_the_same_object_not_a_copy() -> None:
    """بابُ الخزانةِ القديمُ يفتحُ على المصدرِ الواحد — لا عقدَين لمالٍ واحد."""
    from amos_federation.common import money as canonical
    from amos_federation.services.state_treasury import money as legacy_door

    assert legacy_door.MoneyType is canonical.MoneyType, "بابانِ لعقدَين — وهذا انشقاقٌ لا توافق"
    assert legacy_door.MONEY_MAX == canonical.MONEY_MAX
    assert legacy_door.to_money is canonical.to_money
    for name in canonical.__all__:
        assert hasattr(legacy_door, name), f"البابُ القديمُ لا يُصدِّرُ {name} — كسرٌ صامتٌ لمستوردٍ قائم"
