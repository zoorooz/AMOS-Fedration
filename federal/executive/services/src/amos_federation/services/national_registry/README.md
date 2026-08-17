# national_registry/

## التعريف
السجل الوطني للهوية الكانونية: الهوية → المبدأ/الوكيل → المنصب → المؤسسة → نطاق
السلطة. الحلقة التي كانت ناقصة بين جلسةٍ تحمل اسمًا ومنصبٍ يحمل مالًا (R7-C).

## النطاق
- `models.py` — `state_identities` · `state_identity_principals` · `state_identity_agents` ·
  `state_positions` · `state_official_positions` · `state_authority_grants` ·
  `state_decision_provenance` · `state_transaction_authority` على `Base` المشترك
- `resolver.py` — سلسلة السلطة مقروءةً من القاعدة، ونطاقاتٌ بلا ترقية ضمنية
- `authorization.py` — `require_authority`: السلطة من مِنحة على هدفٍ مُسمّى، لا من دور
- `service.py` — إنشاء الهويات وربطها وتقليد المناصب ومنح السلطات: تخويل ← مستأجر
  ← قاعدة ← تدقيق ← حدث دائم

## ما لا تفعله هذه الوحدة
- لا تُنشئ سجلّ وكلاء ثالثًا: `agents` يبقى سجلّ R4 الكانوني، والربط بجدولٍ لا بدمج
- لا تُنشئ ناقل أحداث ولا مخزن تدقيق ولا مُنفِّذ مهامّ جديدًا
- لا تدمج هويتين تلقائيًّا: الغموض حالةٌ (`unresolved`) لا دمجٌ صامت
- لا تحلّ دَين الصرف بترقية صلاحية: لا `write:all` ولا `admin` ولا صلاحية مُختَرعة
- لا تقبل هويةً ولا منصبًا ولا نطاقًا من جسم الطلب
- لا تلمس مصادقة الأمر السيادي (`core/crown`) ولا تُنشئ مسارًا سياديًّا ثانيًا

## المالك
federal/executive/services

## تاريخ الإنشاء
2026-08-17

## تاريخ آخر تعديل
2026-08-17

## المحتويات
- `README.md` — بطاقة هوية هذا المجلد (المادة التاسعة)
- `__init__.py` — AMOS-Federation National Registry
- `authorization.py` — AMOS-Federation National Registry — Authorization Boundary
- `models.py` — AMOS-Federation National Registry — Canonical Identity Domain Model
- `resolver.py` — AMOS-Federation National Registry — Authority Resolver
- `service.py` — AMOS-Federation National Registry — Service Layer
