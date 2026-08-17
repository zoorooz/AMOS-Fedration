# federal_state/

## التعريف
طبقةُ الفدرالية والولايات كما بُنيت في R8: حكومةٌ فدراليةٌ وولاياتٌ ووحداتٌ
وأقسامٌ بمستوياتٍ مفصولةٍ صراحةً، ونطاقٌ يُقاس، وتفويضٌ صريحٌ مؤقَّتٌ قابلٌ للنقض.
وهي **تركيبٌ فوق** المحرّك الكانونيّ لا محرّكٌ ثانٍ.

## النطاق
- `models.py` — الحكومةُ والوحداتُ والنطاقاتُ والتفويضُ، بقيودٍ مفروضةٍ في القاعدة
- `scopes.py` — قاعدةٌ واحدةٌ تُجيب: هل يبلغ نطاقُ هذا المنصبِ هذا الهدفَ بعينه؟
- `delegation.py` — التفويضُ الوحيدُ الذي يجتاز حدَّ الحكومة: صريحٌ مُنطَّقٌ مؤقَّتٌ
  قابلٌ للنقض
- `authorization.py` — مفردةُ صلاحيات الفدرالية والولايات من الأدوار القائمة حصرًا
- `authority.py` — حدُّ الحكومة فوق قرار المحرّك الكانونيّ (تركيبٌ لا محرّكٌ ثانٍ)
- `service.py` — واجهةٌ واحدة: سجلٌّ · حدودٌ · تفويضٌ · نطاقٌ · تنفيذٌ بالنواة

## ما لا تفعله هذه الوحدة
- **لا تستنتج سلطةً من دورٍ ولا لقبٍ ولا اسمٍ ولا عضويةٍ في مؤسسة**
- لا تخلط المستويات: FEDERAL ≠ STATE ≠ INSTITUTION ≠ DEPARTMENT، وولايةٌ ≠ ولاية
- لا محرّكَ تخويلٍ ثانيًا ولا سجلَّ هويةٍ ثانيًا ولا مُنفِّذًا ثانيًا
- لا تمسّ سيادةَ التاج: البوابةُ السياديةُ فوقها ولا تُستنسخ هنا

## المالك
federal/executive/services

## تاريخ الإنشاء
2026-08-17 (R8)

## المراجع
تقرير الجولة: [`R8_FEDERAL_STATE_INTEGRATION.md`](../../../../../../docs/audit/R8_FEDERAL_STATE_INTEGRATION.md)

## تاريخ آخر تعديل
2026-08-17

## المحتويات
- `README.md` — بطاقة هوية هذا المجلد (المادة التاسعة)
- `__init__.py` — AMOS-Federation Federal/State Integration (R8)
- `authority.py` — AMOS-Federation Federal/State Integration — Composed Authority Resolution
- `authorization.py` — AMOS-Federation Federal/State Integration — Permission Vocabulary
- `delegation.py` — AMOS-Federation Federal/State Integration — Explicit Delegation
- `models.py` — AMOS-Federation Federal/State Integration — Domain Model
- `scopes.py` — AMOS-Federation Federal/State Integration — Scope Boundaries
- `service.py` — AMOS-Federation Federal/State Integration — Service Facade
