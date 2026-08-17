# migrations/

## التعريف
ملفات SQL migrations لقاعدة البيانات. تُنفذ تلقائيًا عند بدء PostgreSQL.

## النطاق
- `001_init.sql`: إنشاء 10 جداول أساسية
- `002_seed.sql`: بيانات أولية (وكلاء، أدوات، دستور)
- `003_audit_log_seq.sql`: متتالية سجلّ التدقيق
- `004_unify_tasks_schema.sql`: توحيد مخطّط `tasks` — **فيه عيبٌ تاريخيٌّ مُعلَن**
  في `docs/audit/ACTIVE_EXECUTION_STATE.md`، ولا يُوسَم مُنجَزًا
- `005_state_registry.sql`: سجلّ الدولة (مؤسّسات · مناصب · مسؤولون)
- `006_government_services.sql`: الخدمات الحكومية والقضايا والقرارات
- `007_state_treasury.sql`: المال العام — خزانة · حسابات · موازنة · تخصيص ·
  حركات · دفتر متوازن. **المصدرُ المعتمدُ الوحيدُ للمال**
- `008_national_registry.sql`: السجلّ الوطنيّ للهوية والمناصب ومِنَح السلطة
- `009_federal_judiciary.sql`: القضاء الفدرالي
- `010_federal_state.sql`: الحكومة الفدرالية/الولاية والانتماء والتفويض
- `011_national_economic_state.sql`: الطبقة الاقتصادية — 13 جدولًا
  (`state_economic_*` · `state_public_*` · `state_revenue_sources` ·
  `state_expenditure_authorizations` · `state_procurements`) + 3 `ALTER`
  لتوسيع مفردة العمليات. **لا دفترَ مالٍ ثانيًا ولا جدولَ حركاتٍ ثانيًا**
- `012_economic_decision_references.sql`: تصحيحُ 5 قيودٍ مرجعيةٍ في 011 —
  `decision_id` في السياسة والإجازة والتحويل والمشتريات يشير إلى
  `state_economic_decisions` لا إلى `state_decisions`، وقيدُ
  `state_economic_programs.policy_id` الناقص
- `013_economic_decision_execution_evidence.sql`: «نُفِّذ» يلزمه دليلٌ من مسارٍ
  قائم — مهمّةٌ في النواة التنفيذية **أو** مرجعُ حركةٍ خزانية

## المبدأ
الهجراتُ صريحةٌ ومتراكمة: لا تُحرَّر هجرةٌ بعد دفعها، ولا يُحذَف تاريخٌ.
التصحيحُ بهجرةٍ تالية مُعلَنة (كما في 012 و013 تصحيحًا لـ011).

## المالك
federal/executive/services

## تاريخ الإنشاء
2026-08-15

## تاريخ آخر تعديل
2026-08-17

## المحتويات
- `001_init.sql` — مخطّط أو استعلام قاعدة بيانات
- `002_seed.sql` — مخطّط أو استعلام قاعدة بيانات
- `003_audit_log_seq.sql` — مخطّط أو استعلام قاعدة بيانات
- `004_unify_tasks_schema.sql` — مخطّط أو استعلام قاعدة بيانات
- `005_state_registry.sql` — مخطّط أو استعلام قاعدة بيانات
- `006_government_services.sql` — مخطّط أو استعلام قاعدة بيانات
- `007_state_treasury.sql` — مخطّط أو استعلام قاعدة بيانات
- `008_national_registry.sql` — مخطّط أو استعلام قاعدة بيانات
- `009_federal_judiciary.sql` — مخطّط أو استعلام قاعدة بيانات
- `010_federal_state.sql` — مخطّط أو استعلام قاعدة بيانات
- `011_national_economic_state.sql` — مخطّط أو استعلام قاعدة بيانات
- `012_economic_decision_references.sql` — مخطّط أو استعلام قاعدة بيانات
- `013_economic_decision_execution_evidence.sql` — مخطّط أو استعلام قاعدة بيانات
- `README.md` — بطاقة هوية هذا المجلد (المادة التاسعة)
