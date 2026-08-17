# state_treasury/

## التعريف
نواة المال العام: خزانة → حسابات → موازنة → تخصيص → حركة، وكل حركةٍ لها **طرفان**
في دفترٍ متوازن (`state_ledger_entries`). أوّل نطاق مالي فعليّ في R7-B، مبنيٌّ على
سجلّ الدولة (R7-A) والعمود التنفيذي، بلا نظامٍ موازٍ.

## النطاق
- `money.py` — `Decimal` فقط: `MoneyType` على `NUMERIC(20,4)`، ورفضٌ صريح لـ`float`
- `models.py` — الجداول الستّة على `Base` المشترك: `state_treasuries` · `state_accounts`
  · `state_budgets` · `state_allocations` · `state_transactions` · `state_ledger_entries`
- `authorization.py` — بمفردة الصلاحيات القائمة في `security_roles`، وبمنصبٍ مخوَّل
  في المؤسسة (`state_officials`) لكل عملية تُحرّك مالًا
- `service.py` — العمليات: تخويل ← مستأجر ← منصب ← قاعدة ← تدقيق ← حدث دائم
- `main.py` — نقاط HTTP على المنفذ 8012، بـ`Depends(require_context)`

## ما لا تفعله هذه الوحدة
- **لا رصيد مخزَّن ولا عدّاد صرف**: الأرصدة والمخصَّص والمصروف تُشتقّ من الصفوف
- **لا `balance += amount`**: `_post` هي البوّابة الوحيدة، وتكتب مَدينًا ودائنًا معًا
- **لا `float` ولا `SUM` في SQL على المال**: المجاميع بـ`Decimal` في بايثون
- **لا تعديل تاريخٍ صامت**: التصحيح بحركة عكس (`reversal`)، لا بـ`UPDATE`
- **لا مُنفِّذ مالٍ جديد**: العمل التنفيذي عبر `ExecutiveCore`، ولا كتابة في `tasks`
- لا تقبل دورًا ولا صلاحية ولا مستأجرًا من العميل
- لا ناقل أحداث ولا مخزن تدقيق جديد

## علاقتها بخزانة المرحلة 10
`services/governance/treasury.py` دفترُ حوافزٍ للوكلاء (`treasury_*`, `Float`) وليس
مالًا عامًّا. **جداول `state_*` هي المصدر المعتمد للمال العام**، والقديم بقي كما هو
ولم يُوحَّد — دَينٌ معلَن في `docs/audit/R7B_FEDERAL_TREASURY.md`، لا توحيدٌ مُدَّعى.

## حدود معلَنة
فحص تجاوز التخصيص يقرأ ثم يكتب بلا قفل صفٍّ ⇒ **غير محميّ من التنافس** ·
لا إقفال فتراتٍ ولا قوائم مالية ⇒ المحاسبة الكاملة **PARTIAL** ·
لا قناة دفعٍ ولا تحويل بنكي خارجي ⇒ **UNAVAILABLE**

## المالك
federal/executive/services

## تاريخ الإنشاء
2026-08-17

## تاريخ آخر تعديل
2026-08-17

## المحتويات
- `README.md` — بطاقة هوية هذا المجلد (المادة التاسعة)
- `__init__.py` — AMOS-Federation State Treasury
- `authorization.py` — AMOS-Federation State Treasury — Authorization Boundary
- `main.py` — AMOS-Federation State Treasury — HTTP Interface
- `models.py` — AMOS-Federation State Treasury — Domain Models
- `money.py` — AMOS-Federation State Treasury — Money Primitive
- `service.py` — AMOS-Federation State Treasury — Service Layer
