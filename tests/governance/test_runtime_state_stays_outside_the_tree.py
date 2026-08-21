"""الهدف: إثباتُ أنَّ حالةَ التشغيلِ لا تُكتَبُ في شجرةِ المستودعِ المُتعقَّبة.

النطاق: `conftest.py` الجذريّ و`core.sovereignty.enforcement` — موضعُ سجلِّ الأذون.
المالك: governance/
تاريخ الإنشاء: 2026-08-21
تاريخ آخر تعديل: 2026-08-21

## ما يحرسُه هذا الملفّ (O-1N-1)

قِيسَ — لا افتُرِض — أنَّ تشغيلَ `tests/sovereignty/test_supreme_authority.py` على
استنساخٍ نظيفٍ كان يُنشئُ `royal/authority/CONSUMED_PERMITS.json` داخلَ الشجرةِ
المُتعقَّبة. والمعالجةُ ثلاثةُ حدودٍ يحرسُها هذا الملفُّ بثلاثةِ أوجه:

1. اسمُ مُتغيّرِ البيئةِ في `conftest` الجذريِّ يطابقُ الثابتَ في الوحدة.
2. البيئةُ في كلِّ تشغيلٍ تُعلِنُ موضعًا **خارجَ** الشجرة.
3. سجلٌّ يُبنى بلا موضعٍ صريحٍ يكتبُ خارجَ الشجرةِ فعلًا — لا نظريًّا.

والوجهُ الرابعُ يحرسُ الحدَّ العكسيّ: الموضعُ الافتراضيُّ **لم يُنقَل**. نقلُه
تغييرُ عقدِ مرحلةٍ مغلقةٍ (1G) وقرارٌ بشريٌّ مُعلَنٌ في `PROJECT_STATE.md`، فلو
نُقِلَ يومًا بلا قرارٍ سقطَ هذا الاختبارُ وأُعلِنَ النقلُ ولم يمرَّ صامتًا.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from core.sovereignty.enforcement import (
    CONSUMED_PERMITS_PATH,
    CONSUMED_PERMITS_PATH_ENV,
    ConsumedPermitLedger,
    consumed_permits_path,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _داخل_الشجرة(مسار: Path) -> bool:
    """هل المسارُ داخلَ شجرةِ المستودعِ المُتعقَّبة؟"""
    return REPO_ROOT in مسار.resolve().parents


def test_اسم_متغير_الموضع_في_conftest_يطابق_الثابت_في_الوحدة() -> None:
    """الحرفُ المكتوبُ في `conftest` لا يفترقُ عن الثابتِ الذي يقرأُه الكود.

    يُقرَأُ الملفُ نصًّا ولا يُستورَد: اسمُ الوحدةِ `conftest` مشفوعٌ في
    المستودعِ (`tests/crown/conftest.py` منها)، فاستيرادٌ بالاسمِ يُمسِكُ أيَّها
    جُمِعَ أوّلًا — وقد وقَعَ فعلًا فأسقطَ الحارسَ لا لخللٍ بل للبسِ الاسم.
    """
    نص = (REPO_ROOT / "conftest.py").read_text(encoding="utf-8")
    assert f'CONSUMED_PERMITS_PATH_ENV = "{CONSUMED_PERMITS_PATH_ENV}"' in نص, (
        "اسمُ مُتغيّرِ البيئةِ في conftest الجذريِّ فارقَ الثابتَ في "
        "core.sovereignty.enforcement — فالإعلانُ لا يصلُ إلى الكود."
    )


def test_البيئة_تُعلن_موضع_سجل_الأذون_خارج_الشجرة() -> None:
    """كلُّ تشغيلِ اختباراتٍ يُعلِنُ موضعًا، والموضعُ خارجَ المستودع."""
    موضع = consumed_permits_path()
    assert موضع != CONSUMED_PERMITS_PATH, (
        "لم يُعلَن موضعٌ للتشغيل، فالسجلُّ يهبِطُ إلى الافتراضيِّ داخلَ الشجرة."
    )
    assert not _داخل_الشجرة(موضع), f"موضعُ التشغيلِ داخلَ الشجرةِ المُتعقَّبة: {موضع}"


def test_سجل_يُبنى_بلا_موضع_صريح_يكتب_خارج_الشجرة() -> None:
    """الاستهلاكُ الفعليُّ يُنشئُ ملفًّا خارجَ المستودعِ ولا يُنشئُ الملفَّ المُتعقَّب."""
    سجل = ConsumedPermitLedger()
    معرّف = f"حارس-{uuid.uuid4().hex}"
    سجل.consume(معرّف)

    assert سجل.is_consumed(معرّف), "الاستهلاكُ لم يُثبَت، فالحارسُ لا يقيسُ شيئًا."
    assert سجل.path.exists(), f"السجلُّ لم يُكتَب في {سجل.path}."
    assert not _داخل_الشجرة(سجل.path), (
        f"سجلُّ الأذونِ كُتِبَ داخلَ الشجرةِ المُتعقَّبة: {سجل.path}"
    )
    assert not CONSUMED_PERMITS_PATH.exists(), (
        f"مخرَجُ تشغيلٍ ظهرَ في المسارِ المُتعقَّب: {CONSUMED_PERMITS_PATH}. "
        "إن كان أثرًا قديمًا من تشغيلٍ سابقٍ فامسحْه، فالحارسُ يقيسُ نظافةَ الشجرة."
    )


def test_الموضع_الافتراضي_المُعلن_لم_يُنقل(monkeypatch: pytest.MonkeyPatch) -> None:
    """بلا إعلانٍ في البيئةِ يبقى الافتراضيُّ كما هو — عقدُ 1G لم يُمَسّ."""
    monkeypatch.delenv(CONSUMED_PERMITS_PATH_ENV, raising=False)
    assert consumed_permits_path() == CONSUMED_PERMITS_PATH
    assert _داخل_الشجرة(CONSUMED_PERMITS_PATH), (
        "الموضعُ الافتراضيُّ خرجَ من الشجرة: هذا تغييرُ عقدِ مرحلةٍ مغلقةٍ (1G) "
        "وقرارٌ بشريٌّ، فيُعلَن في PROJECT_STATE.md ويُقيَّد في سجلِّ الإكمال."
    )
