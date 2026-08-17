# state_registry/

## التعريف
السجل الفدرالي: المؤسسة → الإدارة → المسؤول، بصفوف مترابطة بمفاتيح أجنبية مفروضة.
أول نطاق دولة (domain) يُبنى فوق العمود التنفيذي في R7-A.

## النطاق
- `models.py` — `state_institutions` · `state_departments` · `state_officials` على `Base` المشترك
- `authorization.py` — حدّ التخويل بمفردة الصلاحيات القائمة في `security_roles`، لا مفردة جديدة
- `service.py` — عمليات السجل: تخويل ← مستأجر ← قاعدة ← تدقيق ← حدث دائم
- `main.py` — نقاط HTTP بـ`Depends(require_context)`، وبلا `role` في أي نموذج طلب

## ما لا تفعله هذه الوحدة
- لا تُنشئ هوية موازية: `state_officials.agent_id` مفتاح أجنبي إلى `agents.id`
- لا تُنشئ ناقل أحداث ولا مخزن تدقيق جديدًا
- لا تقبل دورًا ولا صلاحية ولا مستأجرًا من العميل

## المالك
federal/executive/services

## تاريخ الإنشاء
2026-08-17

## تاريخ آخر تعديل
2026-08-17

## المحتويات
- `README.md` — بطاقة هوية هذا المجلد (المادة التاسعة)
- `__init__.py` — AMOS-Federation State Registry
- `authorization.py` — AMOS-Federation State Registry — Domain Authorization Boundary
- `main.py` — AMOS-Federation State Registry — HTTP Interface
- `models.py` — AMOS-Federation State Registry — Domain Model
- `service.py` — AMOS-Federation State Registry — Service Layer
- `trace.py` — AMOS-Federation State Domains — Audit + Event Trace
