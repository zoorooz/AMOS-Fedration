-- =============================================================================
-- AMOS-Federation — الهجرة 012: تصحيحُ مراجع القرار الاقتصاديّ
-- الهدف: أن يشير `decision_id` في صفوف الطبقة الاقتصادية إلى سجلِّ القرارات
--        الاقتصادية `state_economic_decisions` لا إلى `state_decisions`.
-- النطاق: federal/executive/services/migrations
-- المالك: federal/executive/services
-- تاريخ الإنشاء: 2026-08-17 (R9-Q)
-- تعتمد على: 011_national_economic_state.sql
-- =============================================================================
--
-- ## لماذا هذه الهجرة موجودة
--
-- الهجرةُ 011 أعلنت `decision_id` في أربعة جداولٍ اقتصاديةٍ مرجعًا إلى
-- `state_decisions` — وهو جدولُ قراراتِ الخدمات الحكومية (R7-A). لكنّ الفعلَ
-- الاقتصاديَّ يُصدر قرارَه في `state_economic_decisions` (R9-N)، فكان العمودُ
-- على مرجعٍ لا يُملأ أبدًا: أيُّ كتابةٍ حقيقيةٍ تُرفَض بـ 23503.
--
-- فهذا **تصحيحُ مرجعٍ** لا إعادةُ كتابةِ تاريخ: لا صفَّ يُحذَف، ولا عمودَ
-- يُسقَط، ولا قيمةَ تُبدَّل. الأعمدةُ كانت `NULL` في كلِّ صفٍّ قائمٍ لأنّ
-- القيدَ القديم منع غيرَ ذلك، فالتحويلُ آمنٌ بالبناء لا بالرجاء.
--
-- ## ما تُضيفه
--
-- | التغيير | الجدول | العمود | المرجعُ الجديد |
-- |---|---|---|---|
-- | إعادةُ قيدٍ مرجعيّ | `state_economic_policies` | `decision_id` | `state_economic_decisions` |
-- | إعادةُ قيدٍ مرجعيّ | `state_expenditure_authorizations` | `decision_id` | `state_economic_decisions` |
-- | إعادةُ قيدٍ مرجعيّ | `state_economic_transfers` | `decision_id` | `state_economic_decisions` |
-- | إعادةُ قيدٍ مرجعيّ | `state_procurements` | `decision_id` | `state_economic_decisions` |
-- | قيدٌ مرجعيٌّ ناقص | `state_economic_programs` | `policy_id` | `state_economic_policies` |
--
-- ## ما **لا** تُضيفه
--
-- لا جدولًا جديدًا، ولا عمودًا جديدًا، ولا مفردةً جديدةً للعمليات، ولا مسًّا
-- بجداول الخزانة ولا بصفوفها. وما لا يستطيع القيدُ فرضَه يبقى على الخدمة:
-- أنّ القرارَ المُشار إليه هو قرارُ **هذا** الصفِّ بعينه لا قرارٌ آخر.
-- =============================================================================

-- الخطوة 1: تحويلُ مراجع `decision_id` الأربعة إلى سجلِّ القرارات الاقتصادية.
-- تُنفَّذ بحلقةٍ واحدةٍ حتى لا يختلف جدولٌ عن أخيه، وباسمٍ صريحٍ للقيد الجديد
-- كي يُقرأ في رسائل الخطأ بلا تخمين.
DO $$
DECLARE
    target RECORD;
    old_constraint TEXT;
BEGIN
    FOR target IN
        SELECT unnest(ARRAY[
            'state_economic_policies',
            'state_expenditure_authorizations',
            'state_economic_transfers',
            'state_procurements'
        ]) AS table_name
    LOOP
        -- أسقِط أيَّ قيدٍ مرجعيٍّ قائمٍ على `decision_id` كيفما سُمِّي.
        FOR old_constraint IN
            SELECT tc.constraint_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
               AND tc.table_schema = kcu.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema = 'public'
              AND tc.table_name = target.table_name
              AND kcu.column_name = 'decision_id'
        LOOP
            EXECUTE format(
                'ALTER TABLE %I DROP CONSTRAINT %I', target.table_name, old_constraint
            );
        END LOOP;

        IF NOT EXISTS (
            SELECT 1
            FROM information_schema.table_constraints
            WHERE table_schema = 'public'
              AND table_name = target.table_name
              AND constraint_name = 'fk_' || target.table_name || '_economic_decision'
        ) THEN
            EXECUTE format(
                'ALTER TABLE %I ADD CONSTRAINT %I '
                'FOREIGN KEY (decision_id) REFERENCES state_economic_decisions (id) '
                'ON DELETE RESTRICT',
                target.table_name,
                'fk_' || target.table_name || '_economic_decision'
            );
        END IF;
    END LOOP;
END $$;

-- الخطوة 2: القيدُ الناقص على سياسةِ البرنامج. برنامجٌ يشير إلى سياسةٍ غير
-- موجودةٍ كان مقبولًا في 011، وهو ما تمنعه هذه الخطوة.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.table_constraints
        WHERE table_schema = 'public'
          AND table_name = 'state_economic_programs'
          AND constraint_name = 'fk_state_economic_programs_policy'
    ) THEN
        ALTER TABLE state_economic_programs
            ADD CONSTRAINT fk_state_economic_programs_policy
            FOREIGN KEY (policy_id) REFERENCES state_economic_policies (id) ON DELETE RESTRICT;
    END IF;
END $$;

-- =============================================================================
-- ما تُرفضه قاعدةُ البيانات بعد 012 (رموزُ SQLSTATE الحقيقية):
--   -- إجازةُ إنفاقٍ تشير إلى قرارٍ غير اقتصاديّ ⇒ 23503 على `decision_id`
--   -- تحويلٌ يشير إلى قرارٍ محذوفٍ أو مُختَرع ⇒ 23503 على `decision_id`
--   -- حذفُ قرارٍ اقتصاديٍّ يشير إليه صفٌّ قائم ⇒ 23503 (ON DELETE RESTRICT)
--   -- برنامجٌ يشير إلى سياسةٍ غير موجودة ⇒ 23503 على `policy_id`
-- وما لا تفرضه: أن يكون القرارُ المُشار إليه قرارَ هذا الصفِّ بعينه.
-- =============================================================================
