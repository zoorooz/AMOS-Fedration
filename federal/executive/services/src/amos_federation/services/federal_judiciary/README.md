# federal_judiciary/

## التعريف
القضاءُ الفدراليُّ كما بُني في R7-D: محكمةٌ مُسجَّلةٌ، ونطاقٌ يُطابَق مساواةً
صريحة، وقضيةٌ لها دورةُ حياةٍ مفروضة، وحكمٌ منسوبٌ إلى قاضٍ مُقلَّد، وأثرُ تنفيذٍ
لا يُكتب إلّا بعد تنفيذٍ حقيقيٍّ في العمود التنفيذيّ أو الخزانة.

## النطاق
- `models.py` — الجداولُ على `Base` المشترك بقيودٍ مفروضةٍ في القاعدة
- `registry.py` — المحكمةُ مؤسسةٌ في السجلّ القائم، والقاضي هويةٌ مُقلَّدة
- `jurisdiction.py` — مطابقةُ النطاق بالمساواة، فلا ترقيةَ فدرالية ولا تجاوزَ ولائيّ
- `authority.py` — «هل هذا قاضٍ يملك الفصل في هذه القضية؟» يُجاب من صفوفٍ أو يُرفَض
- `authorization.py` — الصلاحياتُ من المفردة الكانونية حصرًا
- `docket.py` — الأطرافُ بهويّاتٍ لا بأسماء، والإجراءاتُ مُرتَّبةٌ مفروضة
- `rulings.py` — حكمٌ واحدٌ لكل مرحلةٍ قضائية
- `enforcement.py` — أثرُ التنفيذ بعد الفعل لا قبله
- `service.py` — حدُّ التخويل والجلسة والأثر لكل عملٍ قضائيّ

## ما لا تفعله هذه الوحدة
- لا محرّكَ تخويلٍ ثانيًا: الحكمُ يُطلب من الحدّ الكانونيّ القائم
- لا مُنفِّذًا ثانيًا: العملُ التنفيذيُّ عبر `ExecutiveCore` وحدَه
- لا دفترَ مالٍ ثانيًا: التنفيذُ الماليُّ عبر `StateTreasury` وحدَها
- لا تقبل دورًا ولا صلاحيةً ولا مستأجرًا من العميل
- **ولا تدّعي نفاذًا قانونيًّا خارج هذا النظام** — الأثرُ سجلٌّ داخليٌّ لا إلزامٌ في
  العالم الواقعيّ

## المالك
federal/executive/services

## تاريخ الإنشاء
2026-08-17 (R7-D)

## المراجع
تقرير الجولة: [`R7D_FEDERAL_JUDICIARY.md`](../../../../../../docs/audit/R7D_FEDERAL_JUDICIARY.md)

## تاريخ آخر تعديل
2026-08-17

## المحتويات
- `README.md` — بطاقة هوية هذا المجلد (المادة التاسعة)
- `__init__.py` — AMOS-Federation Federal Judiciary — Package Boundary
- `authority.py` — AMOS-Federation Federal Judiciary — Judicial Authority Resolution
- `authorization.py` — AMOS-Federation Federal Judiciary — Authorization Boundary
- `docket.py` — AMOS-Federation Federal Judiciary — Docket: Cases, Parties, Claims, Evidence, Proceedings
- `enforcement.py` — AMOS-Federation Federal Judiciary — Ruling Enforcement Records
- `jurisdiction.py` — AMOS-Federation Federal Judiciary — Jurisdiction Boundary
- `models.py` — AMOS-Federation Federal Judiciary — Domain Model
- `registry.py` — AMOS-Federation Federal Judiciary — Court & Judge Registry
- `rulings.py` — AMOS-Federation Federal Judiciary — Rulings
- `service.py` — AMOS-Federation Federal Judiciary — Service Facade
