"""الهدف: عزلُ مخرَجِ التشغيلِ عن شجرةِ المستودعِ في كلِّ تشغيلِ اختبارات.

النطاق: جذرُ المستودع — يُحمَّل تلقائيًّا قبلَ جمعِ أيِّ اختبار.
المالك: governance/
تاريخ الإنشاء: 2026-08-21
تاريخ آخر تعديل: 2026-08-21

## المشكلةُ المقيسة (O-1N-1)

`ConsumedPermitLedger` موضعُه الافتراضيُّ `royal/authority/CONSUMED_PERMITS.json`
داخلَ الشجرةِ المُتعقَّبة. وقد قيسَ فعلًا — لا افتراضًا — أنَّ
`pytest tests/sovereignty/test_supreme_authority.py` على استنساخٍ نظيفٍ يُنشئُ
ذلك الملفَّ، لأنَّ الحدَّ يُبنى فيه بسجلِّ ذرّيّةٍ في `tmp_path` وبلا سجلِّ أذون،
فيهبِطُ إلى الافتراضيّ. فحالةُ تشغيلٍ تُكتَبُ في المستودعِ نفسِه، وهو ما
تمنعُه بطاقةُ الهويّة وما يُلوِّثُ كلَّ فحصِ انحرافٍ يعتمدُ على نظافةِ الشجرة.

## القرارُ هنا

الموضعُ الافتراضيُّ **لا يُنقَل**: نقلُه تغييرُ عقدِ مرحلةٍ مغلقةٍ (1G) وقرارٌ
بشريٌّ مُعلَنٌ في `PROJECT_STATE.md`. فالمعالجةُ إعلانٌ صريحٌ في البيئةِ لمدى
التشغيلِ وحدَه: كلُّ سجلٍّ يُبنى بلا موضعٍ صريحٍ يكتبُ في مجلدٍ مؤقّتٍ خارجَ
الشجرة. والإعلانُ يُوضَع هنا — في وحدةِ `conftest` الجذريّةِ التي تُحمَّل قبلَ
الجمع — لا في مُثبِّتٍ (fixture)، لأنَّ سجلًّا قد يُبنى في زمنِ الجمعِ نفسِه.

وإن كانت البيئةُ تُعلِن موضعًا سلفًا فهو أَولى: الإعلانُ الصريحُ لا يُنقَض هنا.

## لماذا اسمُ المُتغيّرِ مكتوبٌ حرفًا لا مُستورَدًا

استيرادُ `core.sovereignty.enforcement` هنا يُلزِمُ `cryptography` في **كلِّ**
تشغيلِ pytest، ومنها بوّابةُ سجلِّ الإكمالِ في CI التي تُركِّبُ `pytest` وحدَها.
فكان الاستيرادُ يُسقِطُ بوّابةً لا علاقةَ لها بالسيادةِ بـ`ModuleNotFoundError`.
والحرفُ لا يُترَك بلا حارس: `tests/governance/`
`test_runtime_state_stays_outside_the_tree.py` يُقارنُ هذا الحرفَ بالثابتِ في
الوحدةِ نفسِها، فأيُّ افتراقٍ يُسقِطُ الاختبارَ لا يمرُّ صامتًا.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

#: نسخةٌ حرفيّةٌ من `core.sovereignty.enforcement.CONSUMED_PERMITS_PATH_ENV`
#: — محروسةٌ باختبارٍ يُقارنُ الاثنين (انظر الشرحَ أعلاه).
CONSUMED_PERMITS_PATH_ENV = "AMOS_CONSUMED_PERMITS_PATH"

if not os.environ.get(CONSUMED_PERMITS_PATH_ENV, "").strip():
    موضع = Path(tempfile.mkdtemp(prefix="amos-runtime-permits-"))
    os.environ[CONSUMED_PERMITS_PATH_ENV] = str(موضع / "CONSUMED_PERMITS.json")
