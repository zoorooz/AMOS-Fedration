-- =============================================================================
-- AMOS-Federation — الهجرة 013: دليلُ تنفيذِ القرار الاقتصاديّ
-- الهدف: أن يُقبل «نُفِّذ» بدليلٍ من أحد مسارَي التنفيذ القائمَين — مهمّةٌ في
--        النواة التنفيذية أو حركةٌ في الخزانة — لا بمهمّةٍ وحدَها.
-- النطاق: federal/executive/services/migrations
-- المالك: federal/executive/services
-- تاريخ الإنشاء: 2026-08-17 (R9-Q)
-- تعتمد على: 011_national_economic_state.sql · 012_economic_decision_references.sql
-- =============================================================================
--
-- ## لماذا هذه الهجرة موجودة
--
-- الهجرةُ 011 قالت: «نُفِّذ» يلزمه `task_id`. وهذا صحيحٌ لقرارٍ يُنفَّذ بمهمّةٍ
-- في `ExecutiveCore`، وخاطئٌ لقرارِ **صرفٍ**: صرفُ الإنفاق والتحويل يمرّ
-- بواجهة الخزانة القائمة (R7-B) فيُثبِت `transaction_reference` ولا يُنشئ
-- مهمّةً. فكان القيدُ يمنع تسجيلَ صرفٍ نُفِّذ فعلًا، أو يدفع إلى اختراع مهمّةٍ
-- صوريةٍ لإرضائه — وكلاهما كذبٌ في السجلّ.
--
-- فالتصحيحُ **تضييقٌ للمعنى لا توسيعٌ للسماح**: «نُفِّذ» يلزمه دليلٌ من
-- مسارٍ قائمٍ، ويبقى الصفُّ بلا أيّ دليلٍ مرفوضًا كما كان. ولا مسارَ تنفيذٍ
-- ثالثًا يُفتَح: العمودان مرتبطان بجدولَي المهامّ والحركات بقيودٍ مرجعية.
--
-- ## ما تُغيّره
--
-- | القيد | قبل | بعد |
-- |---|---|---|
-- | `ck_state_economic_decisions_executed_needs_task` | `status <> 'executed' OR task_id IS NOT NULL` | يُسقَط |
-- | `ck_state_economic_decisions_executed_needs_evidence` | — | `status <> 'executed' OR task_id IS NOT NULL OR transaction_reference IS NOT NULL` |
--
-- ## ما **لا** تُغيّره
--
-- لا صفَّ يُحذَف ولا قيمةَ تُبدَّل: كلُّ صفٍّ كان مقبولًا قبل 013 يبقى مقبولًا
-- بعدها. ولا يُمَسّ `ck_state_economic_decisions_proven_needs_chain` — إسنادُ
-- السلطة يبقى على ما هو. وما لا يفرضه القيد: أنّ المهمّةَ أو الحركةَ المُشارَ
-- إليها هي تنفيذُ **هذا** القرار بعينه؛ ذلك على الخدمة والأثرِ المُدقَّق.
-- =============================================================================

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.table_constraints
        WHERE table_schema = 'public'
          AND table_name = 'state_economic_decisions'
          AND constraint_name = 'ck_state_economic_decisions_executed_needs_task'
    ) THEN
        ALTER TABLE state_economic_decisions
            DROP CONSTRAINT ck_state_economic_decisions_executed_needs_task;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.table_constraints
        WHERE table_schema = 'public'
          AND table_name = 'state_economic_decisions'
          AND constraint_name = 'ck_state_economic_decisions_executed_needs_evidence'
    ) THEN
        ALTER TABLE state_economic_decisions
            ADD CONSTRAINT ck_state_economic_decisions_executed_needs_evidence CHECK (
                status <> 'executed'
                OR task_id IS NOT NULL
                OR transaction_reference IS NOT NULL
            );
    END IF;
END $$;

-- =============================================================================
-- ما ترفضه قاعدةُ البيانات بعد 013 (رموزُ SQLSTATE الحقيقية):
--   -- قرارٌ `executed` بلا مهمّةٍ وبلا مرجعِ حركة
--        ⇒ 23514 ck_state_economic_decisions_executed_needs_evidence
--   -- قرارٌ بمهمّةٍ غير موجودة ⇒ 23503 على `task_id`
--   -- قرارٌ `PROVEN` بلا منصبٍ أو مِنحة ⇒ 23514 ck_state_economic_decisions_proven_needs_chain
-- =============================================================================
