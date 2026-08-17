-- =============================================================================
-- AMOS-Federation Migration 006 — الخدمات الحكومية والقضايا والقرارات (R7-A، الوحدة 2)
-- الهدف: جداول الخدمة والقضية والقرار، مربوطة بالسجل وبجدول المهامّ بمفاتيح مفروضة.
-- النطاق: federal/executive/services
-- المالك: federal/executive/services
-- تاريخ الإنشاء: 2026-08-17
-- =============================================================================
--
-- قابلة لإعادة التطبيق: كل جملة `IF NOT EXISTS`، لا `DROP` ولا تعديل عمود قائم.
-- تعتمد على 005 (`state_institutions` و`state_departments` و`state_officials`)
-- وعلى 001/004 (`agents` و`tasks`). تطبيقها قبلهما يفشل بمفتاح مفقود — وهذا
-- مقصود: لا جدول قضايا بلا مؤسسة ولا مهمّة.
--
-- الرابطة الجوهرية هنا: `state_cases.task_id → tasks.id NOT NULL`. أي قضية في
-- هذه الدولة لها صفٌّ حقيقي في جدول المهامّ (R7-E)، فلا «عملية حكومية» بلا أثر
-- تنفيذي يمكن تتبّعه في العمود التنفيذي نفسه.
--
-- تنبيه على SQLite: `PRAGMA foreign_keys=ON` لازم لكل اتصال، ويفرضه
-- `common/database.py::_enforce_sqlite_foreign_keys`. PostgreSQL يفرضها دائمًا.
-- =============================================================================

BEGIN;

-- الخطوة 1: الخدمات. الخدمة تحت مؤسسة، وقد تُنسَب إلى إدارة فيها.
CREATE TABLE IF NOT EXISTS state_services (
    id              VARCHAR PRIMARY KEY,
    code            VARCHAR NOT NULL,
    name            VARCHAR NOT NULL,
    institution_id  VARCHAR NOT NULL REFERENCES state_institutions(id) ON DELETE RESTRICT,
    department_id   VARCHAR REFERENCES state_departments(id) ON DELETE RESTRICT,
    description     TEXT    DEFAULT '',
    status          VARCHAR NOT NULL DEFAULT 'active',
    sla_hours       INTEGER NOT NULL DEFAULT 72,
    tenant_id       VARCHAR NOT NULL DEFAULT 'default',
    created_by      VARCHAR NOT NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_state_services_institution_code UNIQUE (institution_id, code),
    CONSTRAINT ck_state_services_status CHECK (
        status IN ('active','suspended','retired')
    ),
    CONSTRAINT ck_state_services_sla_positive CHECK (sla_hours > 0)
);

CREATE INDEX IF NOT EXISTS ix_state_services_institution
    ON state_services (institution_id, status);

-- الخطوة 2: القضايا. الطالب وكيل قائم، والمهمّة صفٌّ قائم، والمنصب المُسنَد إليه
-- منصبٌ قائم — ثلاث روابط مفروضة لا نصوص حرّة.
CREATE TABLE IF NOT EXISTS state_cases (
    id                    VARCHAR PRIMARY KEY,
    reference             VARCHAR NOT NULL,
    service_id            VARCHAR NOT NULL REFERENCES state_services(id) ON DELETE RESTRICT,
    institution_id        VARCHAR NOT NULL REFERENCES state_institutions(id) ON DELETE RESTRICT,
    applicant_agent_id    VARCHAR NOT NULL REFERENCES agents(id) ON DELETE RESTRICT,
    assigned_official_id  VARCHAR REFERENCES state_officials(id) ON DELETE RESTRICT,
    task_id               VARCHAR NOT NULL REFERENCES tasks(id) ON DELETE RESTRICT,
    subject               VARCHAR NOT NULL,
    payload               JSON,
    status                VARCHAR NOT NULL DEFAULT 'submitted',
    review_state          VARCHAR,
    priority              VARCHAR NOT NULL DEFAULT 'normal',
    tenant_id             VARCHAR NOT NULL DEFAULT 'default',
    opened_by             VARCHAR NOT NULL,
    created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_state_cases_tenant_reference UNIQUE (tenant_id, reference),
    CONSTRAINT ck_state_cases_status CHECK (
        status IN ('submitted','assigned','processing','reviewed','decided','closed')
    ),
    CONSTRAINT ck_state_cases_priority CHECK (
        priority IN ('low','normal','high','critical')
    )
);

CREATE INDEX IF NOT EXISTS ix_state_cases_institution_status
    ON state_cases (institution_id, status);

CREATE INDEX IF NOT EXISTS ix_state_cases_service
    ON state_cases (service_id, status);

-- الخطوة 3: القرارات. قرارٌ واحد لكل قضية (`case_id` فريد)، ومُسبَّبٌ إلزامًا،
-- ويحمل المنصبَ والمبدأَ المُنفِّذ معًا لأن ربطهما غير ممكن اليوم (دَين مُعلَن).
CREATE TABLE IF NOT EXISTS state_decisions (
    id                       VARCHAR PRIMARY KEY,
    case_id                  VARCHAR NOT NULL UNIQUE
                                 REFERENCES state_cases(id) ON DELETE RESTRICT,
    decided_by_official_id   VARCHAR NOT NULL REFERENCES state_officials(id) ON DELETE RESTRICT,
    decided_by_principal     VARCHAR NOT NULL,
    outcome                  VARCHAR NOT NULL,
    rationale                TEXT    NOT NULL,
    task_final_state         VARCHAR,
    tenant_id                VARCHAR NOT NULL DEFAULT 'default',
    decided_at               TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_state_decisions_outcome CHECK (
        outcome IN ('approved','rejected','deferred')
    ),
    CONSTRAINT ck_state_decisions_rationale_present CHECK (length(rationale) > 0)
);

CREATE INDEX IF NOT EXISTS ix_state_decisions_official
    ON state_decisions (decided_by_official_id);

COMMIT;

-- =============================================================================
-- تحقّق يدوي (يُنفَّذ على PostgreSQL حقيقي، لا SQLite):
--
--   -- قضية بمهمّة غير موجودة ⇒ 23503
--   INSERT INTO state_cases (id, reference, service_id, institution_id,
--       applicant_agent_id, task_id, subject, status, priority, tenant_id, opened_by)
--   VALUES ('c1','R1','<svc>','<inst>','<agent>','task-ghost','x','submitted','normal','default','p');
--
--   -- حالة قضية خارج المفردة ⇒ 23514 ck_state_cases_status
--   -- مرجع مكرَّر في نفس المستأجر ⇒ 23505 uq_state_cases_tenant_reference
--   -- قرارٌ ثانٍ لنفس القضية ⇒ 23505 على `case_id`
--   -- حذف خدمة لها قضية ⇒ 23503 RESTRICT
-- =============================================================================
