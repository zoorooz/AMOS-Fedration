-- =============================================================================
-- AMOS-Federation Migration 004 — توحيد مرجعية الجداول الأساسية مع نماذج ORM
-- الهدف: إلغاء تنافس مخطَّطين على نفس الجداول، وجعل نماذج `common/database.py`
--        المرجع الوحيد — وجعل سلسلة الترحيلات تعمل على قاعدةٍ جديدة فعلًا.
-- النطاق: federal/executive/services
-- المالك: ديوان التدقيق
-- تاريخ الإنشاء: 2026-08-16
-- تاريخ آخر تعديل: 2026-08-17 (إصلاح عطل السلسلة على قاعدةٍ جديدة)
-- =============================================================================
--
-- السبب الجذري:
--   كان في المستودع **مخطَّطان متنافسان** لجدول `tasks`:
--     (أ) `migrations/001_init.sql` — مفتاح `id UUID` + عمود `task_id VARCHAR UNIQUE`.
--     (ب) نموذج ORM `TaskModel` في `common/database.py` — مفتاح `id` هو معرّف
--         المهمة نفسه، **ولا يوجد عمود `task_id` إطلاقًا**.
--   وكان `api_gateway/store.py` يكتب SQL خامًا يخاطب `tasks.task_id`، فيفشل على
--   أي قاعدة أُنشئت من ORM ثم **يرجع صامتًا إلى الذاكرة**، فتبدو الكتابة ناجحة
--   وهي لا تُحفظ. أُزيل ذلك المسار الخام في نفس نقطة التفتيش.
--
-- القرار (بأمر المالك، E2.2-G):
--   طبقة قاعدة البيانات هي مصدر الحقيقة الدائم، ونماذج `common/database.py` هي
--   النماذج الدائمة الأساسية. `id` هو المعرّف المنطقيّ. الذاكرة ليست مصدر حقيقة.
--
-- =============================================================================
-- عطلٌ كان هنا وأُصلح (2026-08-17) — سلسلةُ الترحيلات على قاعدةٍ جديدة:
--   كان تطبيقُ السلسلة `001 → 010` على قاعدةٍ فارغةٍ **يفشل** فشلًا مُلاحَظًا:
--     ERROR: foreign key constraint "tasks_parent_task_id_fkey" cannot be
--            implemented — Key columns "parent_task_id" and "id" are of
--            incompatible types: uuid and character varying.
--   لأن `001` يعرّف `tasks.id UUID` ويشير إليه ثلاثةُ أعمدةٍ من نوع UUID
--   (`tasks.parent_task_id` و`experiences.task_id` و`tool_executions.task_id`)،
--   فتغييرُ نوع الأب وحده يرفضه PostgreSQL. ثمّ يفشل `005` فشلًا من الجنس نفسه
--   على `agents.id`. فكان العطلُ عطلَ **صنفٍ** لا عطلَ سطر: كلُّ جدولٍ في `001`
--   له مفتاحٌ UUID وعمودُ معرّفٍ نصّيٍّ مُنفصل، ونماذجُ ORM لا تعرف إلا `id` نصًّا.
--
--   الإصلاح هنا: روتينٌ واحدٌ يُوحِّد `tasks` و`agents` و`tools` و`experiences`
--   بالطريقة الصحيحة — تُلتقَط القيودُ المشيرةُ **قبل** التغيير من
--   `pg_constraint` (اكتشافٌ ديناميّ لا قائمةٌ مكتوبةٌ بيد)، وتُسقَط، وتُحوَّل
--   أعمدتُها إلى نصّ، وتُرحَّل قيمُها إلى المعرّف المنطقيّ **قبل** تغيير الأب،
--   ثمّ تُعاد القيودُ بأسمائها وتعريفها نفسه. ثمّ تُواءَم الأعمدةُ والقيودُ التي
--   تعرّفها النماذج ولا يعرّفها `001`.
--
--   وهذا الملفُّ **جامدُ الأثر (idempotent)**: كلُّ خطوةٍ محروسةٌ بوجود العمود
--   القديم أو بـ`IF NOT EXISTS`، فإعادةُ تطبيقه على نشرةٍ طُبِّق عليها من قبل
--   لا تفعل شيئًا. والقواعدُ المُنشأة من ORM متوافقةٌ أصلًا ولا يغيّرها.
--
-- تحذير: الخطوة 1/د تُسقط أعمدةً بعد نقل قيمها. لا تُطبَّق قبل نسخةٍ احتياطية.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- الخطوة 1: توحيد المفتاح — `id` يحمل المعرّف المنطقيّ، ولا عمودَ معرّفٍ ثانيًا.
-- -----------------------------------------------------------------------------
DO $$
DECLARE
    target RECORD;
    dep    RECORD;
BEGIN
    FOR target IN
        SELECT *
        FROM (VALUES
            ('tasks',       'task_id'),
            ('agents',      'agent_id'),
            ('tools',       'tool_id'),
            ('experiences', 'experience_id')
        ) AS v(tbl, legacy_column)
    LOOP
        -- يُنفَّذ فقط إن كان العمود القديم موجودًا فعلًا.
        CONTINUE WHEN NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name   = target.tbl
              AND column_name  = target.legacy_column
        );

        -- 1/أ: التقاطُ كلِّ قيدٍ أجنبيٍّ أحاديِّ العمود يشير إلى هذا الجدول.
        DROP TABLE IF EXISTS _amos_fk_deps;
        CREATE TEMP TABLE _amos_fk_deps AS
        SELECT
            c.conname                   AS constraint_name,
            n.nspname                   AS dep_schema,
            child.relname               AS dep_table,
            a.attname                   AS dep_column,
            pg_get_constraintdef(c.oid) AS constraint_def
        FROM pg_constraint c
        JOIN pg_class     parent ON parent.oid = c.confrelid
        JOIN pg_class     child  ON child.oid  = c.conrelid
        JOIN pg_namespace n      ON n.oid      = child.relnamespace
        JOIN pg_attribute a      ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
        WHERE c.contype = 'f'
          AND parent.relname = target.tbl
          AND array_length(c.conkey, 1) = 1;

        -- 1/ب: إسقاطُ القيود وتحويلُ أعمدتها إلى نصّ — بلا فقدِ قيمة.
        FOR dep IN SELECT * FROM _amos_fk_deps LOOP
            EXECUTE format(
                'ALTER TABLE %I.%I DROP CONSTRAINT %I',
                dep.dep_schema, dep.dep_table, dep.constraint_name
            );
            EXECUTE format(
                'ALTER TABLE %I.%I ALTER COLUMN %I TYPE VARCHAR(255) USING %I::text',
                dep.dep_schema, dep.dep_table, dep.dep_column, dep.dep_column
            );
        END LOOP;

        -- 1/ج: المفتاحُ كان UUID؛ يصبح نصًّا ليحمل المعرّف المنطقيّ.
        EXECUTE format('ALTER TABLE %I ALTER COLUMN id DROP DEFAULT', target.tbl);
        EXECUTE format(
            'ALTER TABLE %I ALTER COLUMN id TYPE VARCHAR(255) USING id::text',
            target.tbl
        );

        -- 1/د: نقلُ القيم — الأبناءُ أوّلًا وهم ما زالوا يشيرون إلى UUID القديم،
        -- ثمّ الأبُ. والعكسُ يقطع الرابط.
        FOR dep IN SELECT * FROM _amos_fk_deps LOOP
            EXECUTE format(
                'UPDATE %I.%I d SET %I = p.%I FROM %I p '
                'WHERE d.%I = p.id AND p.%I IS NOT NULL',
                dep.dep_schema, dep.dep_table, dep.dep_column, target.legacy_column,
                target.tbl, dep.dep_column, target.legacy_column
            );
        END LOOP;

        EXECUTE format(
            'UPDATE %I SET id = %I WHERE %I IS NOT NULL AND id <> %I',
            target.tbl, target.legacy_column, target.legacy_column, target.legacy_column
        );
        EXECUTE format('ALTER TABLE %I DROP COLUMN %I', target.tbl, target.legacy_column);

        -- 1/هـ: إعادةُ القيود بأسمائها وتعريفها نفسه (كانت NO ACTION فتبقى).
        FOR dep IN SELECT * FROM _amos_fk_deps LOOP
            EXECUTE format(
                'ALTER TABLE %I.%I ADD CONSTRAINT %I %s',
                dep.dep_schema, dep.dep_table, dep.constraint_name, dep.constraint_def
            );
        END LOOP;

        DROP TABLE _amos_fk_deps;
    END LOOP;
END $$;

-- -----------------------------------------------------------------------------
-- الخطوة 2: مواءمة أعمدة `tasks` مع `TaskModel`.
-- -----------------------------------------------------------------------------
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS plan JSONB DEFAULT '[]'::jsonb;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

-- حالةُ المهمّة: مفرداتُ `001` (`pending/assigned/running`) ليست مفرداتَ آلة
-- الحالات الكانونية في `executive_core/states.py`. تُرحَّل القيمُ القديمة إلى
-- مقابلها المُعلَن، ويُستبدَل القيدُ بالمفردات التسع — لا مفردةَ عاشرة.
UPDATE tasks SET status = 'created'    WHERE status = 'pending';
UPDATE tasks SET status = 'dispatched' WHERE status = 'assigned';
UPDATE tasks SET status = 'executing'  WHERE status = 'running';
ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_status_check;
ALTER TABLE tasks DROP CONSTRAINT IF EXISTS ck_tasks_status;
ALTER TABLE tasks ADD  CONSTRAINT ck_tasks_status CHECK (status IN (
    'created', 'authorized', 'planned', 'dispatched', 'executing',
    'completed', 'failed', 'rejected', 'cancelled'
));

-- -----------------------------------------------------------------------------
-- الخطوة 3: مواءمة أعمدة `agents` مع `AgentModel`.
-- -----------------------------------------------------------------------------
ALTER TABLE agents ADD COLUMN IF NOT EXISTS name          VARCHAR(255);
ALTER TABLE agents ADD COLUMN IF NOT EXISTS role          VARCHAR(100);
ALTER TABLE agents ADD COLUMN IF NOT EXISTS allowed_tools JSONB   DEFAULT '[]'::jsonb;
ALTER TABLE agents ADD COLUMN IF NOT EXISTS token_budget  INTEGER DEFAULT 10000;

-- تعبئةٌ من المتاح فعلًا لا باختراع: الاسمُ من البيان إن وُجد وإلّا المعرّف،
-- والدورُ من `agent_type` إن وُجد وإلّا `'unspecified'` معلنًا.
UPDATE agents
   SET name = COALESCE(NULLIF(manifest ->> 'name', ''), id)
 WHERE name IS NULL;
UPDATE agents
   SET role = COALESCE(
           NULLIF((to_jsonb(agents) ->> 'agent_type'), ''),
           'unspecified'
       )
 WHERE role IS NULL;

ALTER TABLE agents ALTER COLUMN name SET NOT NULL;
ALTER TABLE agents ALTER COLUMN role SET NOT NULL;

-- `agent_type` عمودٌ تاريخيٌّ لا تكتبه النماذج ⇒ يبقى الصفُّ محفوظًا ولا يمنع
-- الكتابةَ الكانونية.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'agents' AND column_name = 'agent_type'
    ) THEN
        ALTER TABLE agents ALTER COLUMN agent_type DROP NOT NULL;
    END IF;
END $$;

-- حالةُ الوكيل: النماذجُ تكتب `registered` ابتداءً، وقيدُ `001` كان يرفضها.
ALTER TABLE agents DROP CONSTRAINT IF EXISTS agents_status_check;
ALTER TABLE agents DROP CONSTRAINT IF EXISTS ck_agents_status;
ALTER TABLE agents ADD  CONSTRAINT ck_agents_status CHECK (status IN (
    'registered', 'active', 'paused', 'suspended', 'retired', 'deceased'
));

-- -----------------------------------------------------------------------------
-- الخطوة 4: مواءمة أعمدة `tools` و`experiences` مع نماذجها.
-- -----------------------------------------------------------------------------
ALTER TABLE tools ADD COLUMN IF NOT EXISTS description          TEXT;
ALTER TABLE tools ADD COLUMN IF NOT EXISTS category             VARCHAR(100);
ALTER TABLE tools ADD COLUMN IF NOT EXISTS keywords             JSONB DEFAULT '[]'::jsonb;
ALTER TABLE tools ADD COLUMN IF NOT EXISTS endpoint             VARCHAR(255);
ALTER TABLE tools ADD COLUMN IF NOT EXISTS permissions_required JSONB DEFAULT '[]'::jsonb;
ALTER TABLE tools ADD COLUMN IF NOT EXISTS tenant_id            VARCHAR(100) DEFAULT 'default';

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'tools' AND column_name = 'version'
    ) THEN
        ALTER TABLE tools ALTER COLUMN version DROP NOT NULL;
    END IF;
END $$;

ALTER TABLE experiences ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(100) DEFAULT 'default';

-- -----------------------------------------------------------------------------
-- الخطوة 5: الجداولُ التي تعرّفها النماذج ولا تعرّفها السلسلة إطلاقًا.
-- (سجلُّ التدقيق المتسلسل، والذاكرة، والمراجعات — كانت تُنشأ بـ`create_all` فقط،
--  فقاعدةٌ مبنيّةٌ من السلسلة وحدها كانت تفتقدها.)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_entries (
    id         VARCHAR(255) PRIMARY KEY,
    action     VARCHAR(255) NOT NULL,
    actor      VARCHAR(255) NOT NULL,
    details    JSONB        DEFAULT '{}'::jsonb,
    prev_hash  VARCHAR(128) NOT NULL,
    hash       VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ  DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS memories (
    key        VARCHAR(255) PRIMARY KEY,
    value      TEXT         NOT NULL,
    keywords   JSONB        DEFAULT '[]'::jsonb,
    tenant_id  VARCHAR(100) DEFAULT 'default',
    created_at TIMESTAMPTZ  DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS reviews (
    id            VARCHAR(255) PRIMARY KEY,
    task_id       VARCHAR(255),
    agent_id      VARCHAR(255),
    quality_score DOUBLE PRECISION NOT NULL,
    feedback      TEXT,
    approved      BOOLEAN,
    criteria      JSONB       DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

COMMIT;

-- التحقق بعد التطبيق (يجب أن يعيد صفرًا في كل سطر):
--   SELECT count(*) FROM information_schema.columns
--   WHERE (table_name, column_name) IN
--         (('tasks','task_id'), ('agents','agent_id'),
--          ('tools','tool_id'), ('experiences','experience_id'));
--   SELECT count(*) FROM information_schema.columns
--   WHERE table_name IN ('tasks','agents','tools','experiences')
--     AND column_name = 'id' AND data_type <> 'character varying';
