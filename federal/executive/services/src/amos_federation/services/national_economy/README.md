# national_economy/

## التعريف
الدولةُ الاقتصاديةُ الوطنية: قطاعٌ → برنامجٌ → سياسةٌ → إجازةُ إنفاقٍ → قرارٌ →
صرفُ خزانةٍ → أثرٌ مُدقَّق. طبقةٌ **فوق** الخزانة القائمة (R7-B) والنواة
التنفيذية والسجلّ الوطنيّ (R7-C) وحدِّ الحكومة (R8) — لا موازيةٌ لها.

## النطاق
- `models.py` — ثلاثةَ عشرَ جدولًا على `Base` المشترك: `state_economic_sectors`
  · `state_economic_categories` · `state_economic_programs` ·
  `state_public_economic_entities` · `state_economic_policies` ·
  `state_economic_indicator_definitions` · `state_revenue_sources` ·
  `state_expenditure_authorizations` · `state_public_assets` ·
  `state_public_liabilities` · `state_economic_transfers` ·
  `state_procurements` · `state_economic_decisions`
- `authorization.py` — بوّابةُ مجالٍ وأربعُ مجموعاتِ صلاحيات، وربطُ العملية
  بنوع موضوعها، ثمّ تسليمُ الحكم إلى `require_government_authority` (R8)
- `service.py` — تسعةَ عشرَ فعلًا عامًّا، كلُّها بمسارٍ واحد: صلاحيةٌ ← سلطةٌ
  مُحلَّلةٌ ← صفٌّ ← قرارٌ اقتصاديٌّ ← مهمّةٌ في `ExecutiveCore` ← عمليةٌ
  حكوميةٌ مُثبَتة ← أثرٌ مُدقَّقٌ وحدثٌ دائم
- `__init__.py` — سطحُ التصدير المُعلَن لهذه الوحدة

## ما لا تفعله هذه الوحدة
- **لا دفترَ مالٍ ثانيًا**: لا `state_economic_*` جدولُ حركاتٍ ولا رصيدٌ مخزَّن؛
  المالُ في جداول الخزانة وحدَها، وهذه الطبقةُ تشير إليها بـ`transaction_reference`
- **لا محرّكَ حركاتٍ ثانيًا**: الصرفُ عبر `StateTreasury.disburse` بقفلها
- **لا محرّكَ تخويلٍ ثانيًا**: الهويةُ والمنصبُ والمِنحةُ وحدُّ الحكومة تُحسَم
  في `national_registry` و`federal_state` كما كانت قبل R9
- **لا مُنفِّذَ ثانيًا**: لا `economic_executor` ولا `policy_executor`؛ العملُ
  التنفيذيُّ عبر `ExecutiveCore.submit/run` وحدَه
- **لا ناقلَ أحداثٍ ولا مخزنَ تدقيقٍ ثانيًا**: `common/event_bus` القائم
- **لا سلطةَ من دورٍ ولا اسمٍ ولا عضويةِ مؤسسة**، ولا `claimed_official_id`
  يُقبل من المستدعي إثباتًا
- **لا مِلكيةَ حقيقيةَ تُدَّعى** لأصلٍ لأنّ صفًّا وُجد، ولا **نفاذَ قانونيَّ
  خارجيَّ** لالتزام، ولا دائنَ مُختَرعًا
- **لا جبايةَ ضرائبَ حقيقية** ولا قنواتَ دفعٍ خارجية ولا سوقَ مشترياتٍ خارجيًّا
- لا بنكَ مركزيًّا ولا مصرفيةَ تجارية ولا شبكةَ مدفوعات — خارج نطاق R9

## المالك
federal/executive/services

## تاريخ الإنشاء
2026-08-17

## تاريخ آخر تعديل
2026-08-17

## المراجع
- تقرير الجولة: [`../../../../../../docs/audit/R9_NATIONAL_ECONOMIC_STATE.md`](../../../../../../docs/audit/R9_NATIONAL_ECONOMIC_STATE.md)
- الخزانة الكانونية: [`../state_treasury/README.md`](../state_treasury/README.md)
- الهجرات: `../../../../migrations/011_national_economic_state.sql` ·
  `012_economic_decision_references.sql` · `013_economic_decision_execution_evidence.sql`

## المحتويات
- `README.md` — بطاقة هوية هذا المجلد (المادة التاسعة)
- `__init__.py` — AMOS-Federation National Economy — الدولةُ الاقتصادية الوطنية (R9)
- `authorization.py` — AMOS-Federation National Economy — Economic Authorization Surface
- `models.py` — AMOS-Federation National Economy — Economic State Domain Model
- `service.py` — AMOS-Federation National Economy — Economic State Service
