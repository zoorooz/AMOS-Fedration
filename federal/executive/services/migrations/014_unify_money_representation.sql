-- =============================================================================
-- AMOS-Federation — الهجرة 014: توحيدُ تمثيلِ المبلغ على NUMERIC(20,4)
-- الهدف: أن يكونَ لكلِّ مبلغٍ في المستودعِ تمثيلٌ واحدٌ — NUMERIC(20,4) — لا
--        نصًّا ولا عائمًا ولا عددًا صحيحًا، تنفيذًا للقرارِ البشريِّ في Q-20.
-- النطاق: federal/executive/services/migrations
-- المالك: federal/executive/services
-- تاريخ الإنشاء: 2026-08-20 (Q-20)
-- تعتمد على: 007_state_treasury.sql (مصدرُ عقدِ المال) · 008_national_registry.sql
--            · 009_federal_judiciary.sql · 010_federal_state.sql
-- =============================================================================
--
-- ## بأيِّ سلطةٍ تُعدَّلُ أعمدةٌ قائمة
--
-- بقرارٍ بشريٍّ صريحٍ مُقيَّدٍ قبلَ هذا الملفِّ لا بعدَه:
-- `docs/audit/SOVEREIGN_DECISION_REGISTER.md` § «القرارُ البشريُّ في Q-5» —
-- **Q-20 · الخيارُ 1**: توحيدُ تمثيلِ المبلغِ الآنَ على `numeric` بدقّةٍ مُعلَنة.
--
-- ## لماذا الآنَ لا غدًا
--
-- قِيسَ في القاعدةِ المُهيَّأةِ (PostgreSQL 17.6) قبلَ كتابةِ هذه الهجرة:
--
--   * `state_case_claims`            → 0 صفّ
--   * `state_authority_grants`       → 0 صفّ
--   * `state_government_delegations` → 0 صفّ
--   * `model_cost_log`               → 2 صفًّا، وقيمتاهما `'0.0'` و`'0.0'`
--
-- فكلفةُ التحويلِ اليومَ **لا شيءٌ يُفقَد**: ثلاثةُ جداولَ فارغة، ورابعٌ فيه
-- صفران قيمتُهما صفر. وهذه نافذةٌ تُغلَقُ بأوّلِ صفٍّ ماليٍّ حقيقيّ: بعدَه يصيرُ
-- التحويلُ هجرةَ بياناتٍ تحتاجُ نسخًا احتياطيًّا وإثباتَ تكافؤٍ صفًّا صفًّا.
--
-- ## لماذا كان النصُّ اختيارًا معقولًا، ولماذا لم يبقَ كذلك
--
-- الأعمدةُ الثلاثةُ الأولى كانت `VARCHAR` **عن قصدٍ لا عن سهو**: أرادَ كاتبُها
-- الهروبَ من العائمِ فخزَّنَ المبلغَ نصًّا وقارنَه `Decimal` في بايثون. والهروبُ
-- من العائمِ صائبٌ، لكنَّ ثمنَه أنَّ القاعدةَ لا تعرفُ أنَّ العمودَ مبلغ: فلا
-- `CHECK` على المقدارِ، ولا رفضَ لِـ`'abc'`، ولا ترتيبَ عدديًّا صحيحًا، ولا
-- منعَ لِـ`'1e9'`. فالتصحيحُ **تضييقٌ للمعنى لا توسيعٌ للسماح**: كلُّ ما كان
-- يُقبَلُ ويصحُّ عددًا يبقى مقبولًا، وما كان يُقبَلُ وهو ليس عددًا صار مرفوضًا
-- في القاعدةِ نفسِها لا في بايثون وحدَها.
--
-- ## حدُّ هذه الهجرةِ صريحًا (ما لا تفعله)
--
-- 1. **لا تمسُّ `treasury_reports` و`treasury_transactions`** — وهي `double
--    precision`. لأنَّ Q-17 قضى أنَّ `amos-credit` **وحدةُ قياسٍ تشغيليّةٌ لا
--    مالٌ دستوريّ**، فخروجُها من «المبلغ» احتمالٌ قائمٌ لا يُحسَمُ بهجرة. وهي
--    مقيَّدةٌ سؤالًا مستقلًّا (Q-28) لا مسكوتٌ عنها.
-- 2. **لا تمسُّ `institutions.budget`** (`integer`, 8 صفوفٍ قيمتُها صفر) — لأنَّ
--    الجدولَ **ليس من جداولِ هذا المستودع**: لا ترحيلَ يُعلِنُه ولا نموذجَ
--    يملكُه. ولا يُعدَّلُ ما لا يُملَك.
-- 3. **لا تمسُّ `token_budget`** في `agents` و`agent_population`، ولا
--    `compliance_reports.total_audits`. أوّلُها ميزانيّةُ **رِموزٍ** لا مال،
--    والثاني **عَدَدٌ** لا مبلغ. ومن هاجَرَهما هاجَرَ اسمًا لا معنًى.
--
-- ## أثرٌ يُقال ولا يُخفى
--
-- `state_authority_grants.max_amount` و`state_government_delegations.max_amount`
-- كانا يقبلانِ أيَّ نصّ. وبعدَ هذه الهجرةِ يرفضُهما القاعدةُ إن لم يكونا عددًا.
-- وهذا **مقصود**: حدُّ صرفٍ غيرُ رقميٍّ لا يحرسُ شيئًا، وقراءتُه في `resolver`
-- كانت تسقطُ إلى الرفضِ على كلِّ حال — فصارَ الرفضُ عندَ الكتابةِ لا عندَ القراءة.
-- =============================================================================

BEGIN;

-- === 1 · مطالبةُ الدعوى: مبلغٌ نصًّا → مبلغٌ عشريّ =========================
-- `NULLIF(...,'')` لأنَّ العمودَ كان يقبلُ النصَّ الفارغَ بمعنى «بلا مبلغ».
ALTER TABLE IF EXISTS state_case_claims
    ALTER COLUMN amount TYPE NUMERIC(20,4)
    USING NULLIF(TRIM(amount), '')::NUMERIC(20,4);

ALTER TABLE IF EXISTS state_case_claims
    ADD CONSTRAINT ck_state_case_claims_amount CHECK (
        amount IS NULL OR (amount >= 0 AND amount <= 900000000000)
    );

-- === 2 · حدُّ مِنحةِ الصلاحيّة: نصٌّ → عشريّ ===============================
ALTER TABLE IF EXISTS state_authority_grants
    ALTER COLUMN max_amount TYPE NUMERIC(20,4)
    USING NULLIF(TRIM(max_amount), '')::NUMERIC(20,4);

ALTER TABLE IF EXISTS state_authority_grants
    ADD CONSTRAINT ck_state_authority_grants_max_amount CHECK (
        max_amount IS NULL OR (max_amount >= 0 AND max_amount <= 900000000000)
    );

-- === 3 · حدُّ تفويضِ الحكومة: نصٌّ → عشريّ =================================
ALTER TABLE IF EXISTS state_government_delegations
    ALTER COLUMN max_amount TYPE NUMERIC(20,4)
    USING NULLIF(TRIM(max_amount), '')::NUMERIC(20,4);

ALTER TABLE IF EXISTS state_government_delegations
    ADD CONSTRAINT ck_state_government_delegations_max_amount CHECK (
        max_amount IS NULL OR (max_amount >= 0 AND max_amount <= 900000000000)
    );

-- === 4 · كلفةُ نداءِ النموذج: نصٌّ → عشريّ =================================
-- وهذا مبلغٌ بالدولارِ الحقيقيِّ لا بوحدةٍ تشغيليّة، فهو مالٌ بلا خلاف.
ALTER TABLE IF EXISTS model_cost_log
    ALTER COLUMN cost_usd TYPE NUMERIC(20,4)
    USING COALESCE(NULLIF(TRIM(cost_usd), ''), '0')::NUMERIC(20,4);

ALTER TABLE IF EXISTS model_cost_log
    ALTER COLUMN cost_usd SET DEFAULT 0;

ALTER TABLE IF EXISTS model_cost_log
    ADD CONSTRAINT ck_model_cost_log_cost_usd CHECK (
        cost_usd >= 0 AND cost_usd <= 900000000000
    );

COMMIT;
