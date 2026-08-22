# =============================================================================
# File:        agents/stubs/registry_check.py
# Purpose:     فحص سجل الوكلاء — قياسٌ حيٌّ لتعداد السكان من قاعدة البيانات
# Owner:       agents/
# Created:     2026-08-15
# Last Modified: 2026-08-22 (W-025)
# Phase:       P3 (Working Nuclei)
# Article 009: هذا الملف يلتزم بالمادة 009 — الشفافية والمراجعة المستمرة.
#              لا يحمل هذا الملف رقمًا ثابتًا ولا نسخةً مؤقّتة: العدد يُقاس لحظة
#              النداء من قاعدة البيانات، وإن لم يكن المصدر مهيَّأً أُعلنت الحالة
#              `unmeasured` — وهي ليست `pass`.
# =============================================================================
"""
أداة فحص سجل الوكلاء (Agents Registry Check).

الهدف: قياسُ حالةِ الإقليمِ من مصدرِ الحقيقةِ الحيِّ لحظةَ النداء، لا اقتباسُ
       ثابتٍ مكتوبٍ في الكود. ما يُقاس: عددُ صفوفِ جدولِ `agent_population` (تعدادُ السكان) وجدولِ `agents`.
النطاق: قراءةُ عدّاداتٍ فقط عبرَ `tools.audit.live_truth`. لا كتابةَ ولا حكم.
المالك: agents/
تاريخ الإنشاء: 2026-08-15
تاريخ آخر تعديل: 2026-08-22

سببُ التغيير (W-025): كان هذا الملفُ يُخزّنُ أرقامًا ثابتةً ويقارنُها بنفسِها،
فكانت البوّابةُ تُصادِقُ على ذاتِها (tautology). القياسُ الحيُّ في 2026-08-22 أظهرَ
أنَّ أرقامًا منها كانت مخالفةً للواقع — والتفصيلُ في
`docs/audit/measurements/domain_truth_snapshot.json` وبندِ السجل W-025.
"""

import os
import sys

# جذرُ المستودعِ على المسار حتى تُحَلَّ `tools.audit.live_truth` عند التشغيلِ المباشر.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from tools.audit.live_truth import check_domain  # noqa: E402


def check():
    """يقيسُ عدّاداتِ إقليمِ `agents` الآن.

    Returns:
        dict: domain، status (`pass` إن قِيسَ الآن، `unmeasured` إن لم يُهيَّأِ
            المصدر، `fail` إن هُيِّئَ وفشلَ القياس)، source، والعدّادات.
    """
    return check_domain("agents", {"count": "agent_population", "identities": "agents"})


if __name__ == "__main__":
    import json

    print(json.dumps(check(), ensure_ascii=False, indent=2))
