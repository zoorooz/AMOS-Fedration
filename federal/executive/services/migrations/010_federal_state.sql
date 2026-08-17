-- =============================================================================
-- AMOS-Federation — الهجرة 010: الفدرالية والولايات (R8-O)
-- الهدف: سبعةُ جداولٍ جديدة بقيودٍ مفروضة — بلا ALTER ولا DROP ولا DELETE
-- المالك: federal/executive/services
-- تاريخ الإنشاء: 2026-08-17
--
-- ## لماذا CREATE TABLE فقط
--
-- `create_all` لا تُضيف عمودًا إلى جدولٍ موجود ولا تُعدّل قيدًا، ولا يُعتمد عليها
-- لتغيير مخطَّطٍ راسخ (R8-O). وكلُّ ما تضيفه R8 جداولٌ جديدة بحتة: لا عمودَ على
-- `state_institutions` ولا على `state_services` ولا على `state_cases`، ولا صفَّ
-- يُحذف، ولا `state_authority_grants.operation` يُوسَّع. فتطبيقُها على قاعدةٍ فيها
-- بياناتٌ لا يفقد صفًّا واحدًا.
--
-- ## الترتيب مقصود
--
-- من الأصل إلى الفرع: الحكومةُ قبل الربط، والربطُ قبل التفويض (يشير إليهما)،
-- ثمّ نطاقُ الخدمة، فإسنادُ القضية، فأثرُ العملية الذي يشير إلى كلِّ ما سبق
-- وإلى `tasks`. فكلُّ مفتاحٍ أجنبيّ يجد هدفَه موجودًا عند إنشائه.
--
-- ## المفاتيح الأجنبية إلى ما هو قائم
--
--   state_institution_governments.institution_id → state_institutions.id  (R7-A)
--   state_service_scopes.service_id              → state_services.id      (R7-A/2)
--   state_case_scopes.case_id                    → state_cases.id         (R7-A/2)
--   state_case_scopes.responsible_official_id    → state_officials.id     (R7-A)
--   state_case_scopes.position_id                → state_positions.id     (R7-C)
--   *.identity_id                                → state_identities.id    (R7-C)
--   state_government_operations.decision_id      → state_decisions.id     (R7-A/2)
--   state_government_operations.ruling_id        → state_rulings.id       (R7-D)
--   state_government_operations.task_id          → tasks.id               (R2/R4)
--
-- وكلُّها `ON DELETE RESTRICT`: لا يُحذف كيانٌ مُشارٌ إليه من إسنادٍ أو أثر، فلا
-- يُهدم تاريخٌ بحلِّ حكومةٍ أو تعليقِ مؤسسة (الحلُّ حالةٌ لا حذف).
--
-- ## دَينٌ معروفٌ يبقى دَينًا
--
-- خللُ سلسلة الهجرات في `004_unify_tasks_schema.sql` على قاعدةٍ جديدة **لم
-- يُصلَح هنا** ولا يُدَّعى إصلاحُه؛ يبقى مُصنَّفًا دَينًا قائمًا كما في R7-C/R7-D.
-- =============================================================================

-- الخطوة 1: الحكومة — فدراليةٌ أو ولاية في شجرةٍ واحدة. `ck_..._parent` يجعل
-- «الولايةُ يلزمها أصلٌ فدراليّ» قيدًا لا نيّة، و`uq_..._tenant_code` يمنع
-- ولايتين برمزٍ واحدٍ تحت التزامن. و`federal_states` القديم (Phase-12) لا يُلمَس.
CREATE TABLE IF NOT EXISTS state_governments (
    id VARCHAR NOT NULL,
    code VARCHAR NOT NULL,
    name VARCHAR NOT NULL,
    level VARCHAR NOT NULL,
    parent_government_id VARCHAR,
    status VARCHAR NOT NULL DEFAULT 'active',
    status_reason TEXT DEFAULT '',
    tenant_id VARCHAR NOT NULL DEFAULT 'default',
    created_by VARCHAR NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE,
    updated_at TIMESTAMP WITHOUT TIME ZONE,
    PRIMARY KEY (id),
    CONSTRAINT uq_state_governments_tenant_code UNIQUE (tenant_id, code),
    CONSTRAINT ck_state_governments_level CHECK (level IN ('FEDERAL','STATE')),
    CONSTRAINT ck_state_governments_status CHECK (status IN ('active','suspended','dissolved')),
    CONSTRAINT ck_state_governments_parent CHECK ((level = 'FEDERAL' AND parent_government_id IS NULL) OR (level = 'STATE' AND parent_government_id IS NOT NULL)),
    CONSTRAINT ck_state_governments_not_self_parent CHECK (parent_government_id IS NULL OR parent_government_id <> id),
    FOREIGN KEY(parent_government_id) REFERENCES state_governments (id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS ix_state_governments_parent ON state_governments (parent_government_id);

CREATE INDEX IF NOT EXISTS ix_state_governments_tenant_level ON state_governments (tenant_id, level);

-- الخطوة 2: ربطُ مؤسسةٍ قائمةٍ بحكومتها — جدولٌ رابطٌ لا عمودٌ جديد على
-- `state_institutions`. والفريدُ على (مستأجر، مؤسسة) يمنع الانتماءَ المزدوج.
-- ومؤسسةٌ بلا صفٍّ هنا: `UNRESOLVED` معلنًا — وهو حالُ كلِّ صفوفِ ما قبل R8.
CREATE TABLE IF NOT EXISTS state_institution_governments (
    id VARCHAR NOT NULL,
    government_id VARCHAR NOT NULL,
    institution_id VARCHAR NOT NULL,
    relation VARCHAR NOT NULL DEFAULT 'belongs_to',
    assigned_by VARCHAR NOT NULL,
    assigned_by_identity_id VARCHAR,
    tenant_id VARCHAR NOT NULL DEFAULT 'default',
    created_at TIMESTAMP WITHOUT TIME ZONE,
    updated_at TIMESTAMP WITHOUT TIME ZONE,
    PRIMARY KEY (id),
    CONSTRAINT uq_state_institution_governments_institution UNIQUE (tenant_id, institution_id),
    CONSTRAINT ck_state_institution_governments_relation CHECK (relation IN ('belongs_to','administers')),
    FOREIGN KEY(government_id) REFERENCES state_governments (id) ON DELETE RESTRICT,
    FOREIGN KEY(institution_id) REFERENCES state_institutions (id) ON DELETE RESTRICT,
    FOREIGN KEY(assigned_by_identity_id) REFERENCES state_identities (id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS ix_state_institution_governments_government ON state_institution_governments (government_id);

-- الخطوة 3: العلاقاتُ الإدارية — **وصفٌ لا صلاحية**. لا سطرَ في `authority.py`
-- يقرأ هذا الجدولَ ليمنح شيئًا، ويحرس ذلك اختبارٌ ساكن.
CREATE TABLE IF NOT EXISTS state_government_relations (
    id VARCHAR NOT NULL,
    from_kind VARCHAR NOT NULL,
    from_ref VARCHAR NOT NULL,
    to_kind VARCHAR NOT NULL,
    to_ref VARCHAR NOT NULL,
    relation VARCHAR NOT NULL,
    status VARCHAR NOT NULL DEFAULT 'active',
    note TEXT DEFAULT '',
    created_by VARCHAR NOT NULL,
    created_by_identity_id VARCHAR,
    tenant_id VARCHAR NOT NULL DEFAULT 'default',
    created_at TIMESTAMP WITHOUT TIME ZONE,
    updated_at TIMESTAMP WITHOUT TIME ZONE,
    revoked_at TIMESTAMP WITHOUT TIME ZONE,
    revoked_reason TEXT DEFAULT '',
    PRIMARY KEY (id),
    CONSTRAINT ck_state_government_relations_from_kind CHECK (from_kind IN ('GOVERNMENT','INSTITUTION','DEPARTMENT')),
    CONSTRAINT ck_state_government_relations_to_kind CHECK (to_kind IN ('GOVERNMENT','INSTITUTION','DEPARTMENT')),
    CONSTRAINT ck_state_government_relations_relation CHECK (relation IN ('governs','belongs_to','administers','delegates','scopes','reports_to')),
    CONSTRAINT ck_state_government_relations_status CHECK (status IN ('active','revoked')),
    CONSTRAINT ck_state_government_relations_not_self CHECK (NOT (from_kind = to_kind AND from_ref = to_ref)),
    CONSTRAINT ck_state_government_relations_revoked_at CHECK ((status = 'revoked' AND revoked_at IS NOT NULL) OR (status <> 'revoked' AND revoked_at IS NULL)),
    FOREIGN KEY(created_by_identity_id) REFERENCES state_identities (id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS ix_state_government_relations_from ON state_government_relations (from_kind, from_ref, status);

CREATE INDEX IF NOT EXISTS ix_state_government_relations_to ON state_government_relations (to_kind, to_ref, status);

-- الخطوة 4: التفويضُ — الطريقُ **الوحيد** لعبور حدِّ الحكومة: صريحٌ (مفاتيحُ
-- أجنبية) · مُنطَّقٌ (`scope` و`max_amount`) · مؤقَّتٌ (`expires_at`) · قابلٌ
-- للنقض (`revoked` + طابعٌ مفروضٌ بقيد). والعملياتُ من مفردة R7-C حصرًا.
CREATE TABLE IF NOT EXISTS state_government_delegations (
    id VARCHAR NOT NULL,
    from_government_id VARCHAR NOT NULL,
    to_government_id VARCHAR,
    to_institution_id VARCHAR,
    operation VARCHAR NOT NULL,
    scope VARCHAR NOT NULL,
    max_amount VARCHAR,
    status VARCHAR NOT NULL DEFAULT 'active',
    reason TEXT DEFAULT '',
    granted_by VARCHAR NOT NULL,
    granted_by_identity_id VARCHAR,
    tenant_id VARCHAR NOT NULL DEFAULT 'default',
    created_at TIMESTAMP WITHOUT TIME ZONE,
    updated_at TIMESTAMP WITHOUT TIME ZONE,
    expires_at TIMESTAMP WITHOUT TIME ZONE,
    revoked_at TIMESTAMP WITHOUT TIME ZONE,
    revoked_reason TEXT DEFAULT '',
    PRIMARY KEY (id),
    CONSTRAINT ck_state_government_delegations_operation CHECK (operation IN ('treasury.funding.post','treasury.allocation.create','treasury.disbursement.post','treasury.transaction.reverse','gov.case.decide')),
    CONSTRAINT ck_state_government_delegations_scope CHECK (scope IN ('FEDERAL','STATE','INSTITUTION','DEPARTMENT')),
    CONSTRAINT ck_state_government_delegations_status CHECK (status IN ('active','revoked','expired')),
    CONSTRAINT ck_state_government_delegations_target CHECK ((to_government_id IS NOT NULL AND to_institution_id IS NULL) OR (to_government_id IS NULL AND to_institution_id IS NOT NULL)),
    CONSTRAINT ck_state_government_delegations_not_self CHECK (to_government_id IS NULL OR to_government_id <> from_government_id),
    CONSTRAINT ck_state_government_delegations_revoked_at CHECK ((status = 'revoked' AND revoked_at IS NOT NULL) OR (status <> 'revoked' AND revoked_at IS NULL)),
    FOREIGN KEY(from_government_id) REFERENCES state_governments (id) ON DELETE RESTRICT,
    FOREIGN KEY(to_government_id) REFERENCES state_governments (id) ON DELETE RESTRICT,
    FOREIGN KEY(to_institution_id) REFERENCES state_institutions (id) ON DELETE RESTRICT,
    FOREIGN KEY(granted_by_identity_id) REFERENCES state_identities (id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS ix_state_government_delegations_lookup ON state_government_delegations (tenant_id, from_government_id, operation, status);

-- الخطوة 5: نطاقُ خدمةٍ قائمة — ملكيةٌ صريحة. `FEDERAL`/`STATE` يلزمهما حكومةٌ
-- مُسمّاة، و`DEPARTMENT` تلزمه إدارةٌ مُسمّاة. ولا خدمةَ جديدةٌ ولا منفِّذٌ خاصّ.
CREATE TABLE IF NOT EXISTS state_service_scopes (
    id VARCHAR NOT NULL,
    service_id VARCHAR NOT NULL,
    level VARCHAR NOT NULL,
    government_id VARCHAR,
    institution_id VARCHAR NOT NULL,
    department_id VARCHAR,
    created_by VARCHAR NOT NULL,
    created_by_identity_id VARCHAR,
    tenant_id VARCHAR NOT NULL DEFAULT 'default',
    created_at TIMESTAMP WITHOUT TIME ZONE,
    updated_at TIMESTAMP WITHOUT TIME ZONE,
    PRIMARY KEY (id),
    CONSTRAINT uq_state_service_scopes_service UNIQUE (tenant_id, service_id),
    CONSTRAINT ck_state_service_scopes_level CHECK (level IN ('FEDERAL','STATE','INSTITUTION','DEPARTMENT')),
    CONSTRAINT ck_state_service_scopes_department CHECK ((level = 'DEPARTMENT' AND department_id IS NOT NULL) OR (level <> 'DEPARTMENT' AND department_id IS NULL)),
    CONSTRAINT ck_state_service_scopes_government CHECK ((level IN ('FEDERAL','STATE') AND government_id IS NOT NULL) OR (level IN ('INSTITUTION','DEPARTMENT'))),
    FOREIGN KEY(service_id) REFERENCES state_services (id) ON DELETE RESTRICT,
    FOREIGN KEY(government_id) REFERENCES state_governments (id) ON DELETE RESTRICT,
    FOREIGN KEY(institution_id) REFERENCES state_institutions (id) ON DELETE RESTRICT,
    FOREIGN KEY(department_id) REFERENCES state_departments (id) ON DELETE RESTRICT,
    FOREIGN KEY(created_by_identity_id) REFERENCES state_identities (id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS ix_state_service_scopes_scope ON state_service_scopes (tenant_id, level, government_id);

-- الخطوة 6: إسنادُ قضيةٍ قائمة. `ck_..._proven_needs_chain` يمنع كتابةَ `PROVEN`
-- بلا منصبٍ وهويةٍ وحكومة — فالإسنادُ لا يُلفَّق، والناقصُ يُقال `PARTIAL`/`UNRESOLVED`.
CREATE TABLE IF NOT EXISTS state_case_scopes (
    id VARCHAR NOT NULL,
    case_id VARCHAR NOT NULL,
    level VARCHAR NOT NULL,
    government_id VARCHAR,
    institution_id VARCHAR NOT NULL,
    department_id VARCHAR,
    responsible_official_id VARCHAR,
    opened_by VARCHAR NOT NULL,
    opened_by_identity_id VARCHAR,
    position_id VARCHAR,
    classification VARCHAR NOT NULL,
    authority JSON,
    tenant_id VARCHAR NOT NULL DEFAULT 'default',
    created_at TIMESTAMP WITHOUT TIME ZONE,
    updated_at TIMESTAMP WITHOUT TIME ZONE,
    PRIMARY KEY (id),
    CONSTRAINT uq_state_case_scopes_case UNIQUE (tenant_id, case_id),
    CONSTRAINT ck_state_case_scopes_level CHECK (level IN ('FEDERAL','STATE','INSTITUTION','DEPARTMENT')),
    CONSTRAINT ck_state_case_scopes_classification CHECK (classification IN ('PROVEN','PARTIAL','UNRESOLVED')),
    CONSTRAINT ck_state_case_scopes_proven_needs_chain CHECK (classification <> 'PROVEN' OR (position_id IS NOT NULL AND opened_by_identity_id IS NOT NULL AND government_id IS NOT NULL)),
    CONSTRAINT ck_state_case_scopes_department CHECK ((level = 'DEPARTMENT' AND department_id IS NOT NULL) OR (level <> 'DEPARTMENT' AND department_id IS NULL)),
    FOREIGN KEY(case_id) REFERENCES state_cases (id) ON DELETE RESTRICT,
    FOREIGN KEY(government_id) REFERENCES state_governments (id) ON DELETE RESTRICT,
    FOREIGN KEY(institution_id) REFERENCES state_institutions (id) ON DELETE RESTRICT,
    FOREIGN KEY(department_id) REFERENCES state_departments (id) ON DELETE RESTRICT,
    FOREIGN KEY(responsible_official_id) REFERENCES state_officials (id) ON DELETE RESTRICT,
    FOREIGN KEY(opened_by_identity_id) REFERENCES state_identities (id) ON DELETE RESTRICT,
    FOREIGN KEY(position_id) REFERENCES state_positions (id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS ix_state_case_scopes_scope ON state_case_scopes (tenant_id, level, government_id);

-- الخطوة 7: أثرُ العملية الحكومية: قرارٌ → سلطةٌ → تنفيذ. `task_id` مفتاحٌ أجنبيّ
-- إلى `tasks.id` القائم — فالتنفيذُ عبر `ExecutiveCore` وحدها، ولا جدولَ مهامٍّ
-- موازٍ. و«نُفِّذ» ادّعاءٌ يلزمه مرجعٌ: مهمّةٌ أو مرجعُ حركةٍ في الخزانة.
CREATE TABLE IF NOT EXISTS state_government_operations (
    id VARCHAR NOT NULL,
    kind VARCHAR NOT NULL,
    level VARCHAR NOT NULL,
    government_id VARCHAR,
    institution_id VARCHAR NOT NULL,
    department_id VARCHAR,
    decision_id VARCHAR,
    case_id VARCHAR,
    ruling_id VARCHAR,
    identity_id VARCHAR,
    position_id VARCHAR,
    classification VARCHAR NOT NULL,
    authority JSON,
    task_id VARCHAR,
    transaction_reference VARCHAR,
    status VARCHAR NOT NULL DEFAULT 'requested',
    detail TEXT DEFAULT '',
    requested_by VARCHAR NOT NULL,
    tenant_id VARCHAR NOT NULL DEFAULT 'default',
    created_at TIMESTAMP WITHOUT TIME ZONE,
    updated_at TIMESTAMP WITHOUT TIME ZONE,
    PRIMARY KEY (id),
    CONSTRAINT ck_state_government_operations_kind CHECK (kind IN ('TASK','TREASURY')),
    CONSTRAINT ck_state_government_operations_level CHECK (level IN ('FEDERAL','STATE','INSTITUTION','DEPARTMENT')),
    CONSTRAINT ck_state_government_operations_status CHECK (status IN ('requested','executed','failed')),
    CONSTRAINT ck_state_government_operations_classification CHECK (classification IN ('PROVEN','PARTIAL','UNRESOLVED')),
    CONSTRAINT ck_state_government_operations_task_target CHECK (status <> 'executed' OR kind <> 'TASK' OR task_id IS NOT NULL),
    CONSTRAINT ck_state_government_operations_treasury_target CHECK (status <> 'executed' OR kind <> 'TREASURY' OR transaction_reference IS NOT NULL),
    FOREIGN KEY(government_id) REFERENCES state_governments (id) ON DELETE RESTRICT,
    FOREIGN KEY(institution_id) REFERENCES state_institutions (id) ON DELETE RESTRICT,
    FOREIGN KEY(department_id) REFERENCES state_departments (id) ON DELETE RESTRICT,
    FOREIGN KEY(decision_id) REFERENCES state_decisions (id) ON DELETE RESTRICT,
    FOREIGN KEY(case_id) REFERENCES state_cases (id) ON DELETE RESTRICT,
    FOREIGN KEY(ruling_id) REFERENCES state_rulings (id) ON DELETE RESTRICT,
    FOREIGN KEY(identity_id) REFERENCES state_identities (id) ON DELETE RESTRICT,
    FOREIGN KEY(position_id) REFERENCES state_positions (id) ON DELETE RESTRICT,
    FOREIGN KEY(task_id) REFERENCES tasks (id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS ix_state_government_operations_decision ON state_government_operations (decision_id);

CREATE INDEX IF NOT EXISTS ix_state_government_operations_scope ON state_government_operations (tenant_id, level, government_id);

CREATE INDEX IF NOT EXISTS ix_state_government_operations_task ON state_government_operations (task_id);

-- =============================================================================
-- ما تُثبته هذه الهجرة على PostgreSQL — رفضٌ حقيقيّ برمزٍ حقيقيّ:
--
--   -- حكومتان بنفس (مستأجر، رمز) ⇒ 23505 uq_state_governments_tenant_code
--   -- ولايةٌ بلا أصلٍ فدراليّ ⇒ 23514 ck_state_governments_parent
--   -- حكومةٌ فدرالية بأصل ⇒ 23514 ck_state_governments_parent
--   -- حكومةٌ أصلُها نفسُها ⇒ 23514 ck_state_governments_not_self_parent
--   -- حكومةٌ بمستوىً مُختَرع ⇒ 23514 ck_state_governments_level
--   -- مؤسسةٌ مربوطةٌ بحكومتين ⇒ 23505 uq_state_institution_governments_institution
--   -- ربطٌ بحكومةٍ غير موجودة ⇒ 23503 على `government_id`
--   -- علاقةُ كيانٍ بنفسه ⇒ 23514 ck_state_government_relations_not_self
--   -- علاقةٌ «منقوضة» بلا طابع ⇒ 23514 ck_state_government_relations_revoked_at
--   -- تفويضٌ بعمليةٍ خارج مفردة R7-C ⇒ 23514 ck_state_government_delegations_operation
--   -- تفويضٌ بهدفين ⇒ 23514 ck_state_government_delegations_target
--   -- تفويضٌ بلا هدف ⇒ 23514 ck_state_government_delegations_target
--   -- تفويضُ حكومةٍ لنفسها ⇒ 23514 ck_state_government_delegations_not_self
--   -- تفويضٌ «منقوض» بلا طابع ⇒ 23514 ck_state_government_delegations_revoked_at
--   -- نطاقٌ فدراليٌّ بلا حكومة ⇒ 23514 ck_state_service_scopes_government
--   -- نطاقُ إدارةٍ بلا إدارة ⇒ 23514 ck_state_service_scopes_department
--   -- خدمتان بنطاقين ⇒ 23505 uq_state_service_scopes_service
--   -- إسنادُ `PROVEN` بلا منصبٍ أو هويةٍ أو حكومة ⇒ 23514 ck_state_case_scopes_proven_needs_chain
--   -- قضيةٌ بإسنادين ⇒ 23505 uq_state_case_scopes_case
--   -- إسنادٌ بتصنيفٍ مُختَرع ⇒ 23514 ck_state_case_scopes_classification
--   -- عمليةُ TASK «نُفِّذت» بلا مهمّة ⇒ 23514 ck_state_government_operations_task_target
--   -- عمليةُ TREASURY «نُفِّذت» بلا مرجعِ حركة ⇒ 23514 ck_state_government_operations_treasury_target
--   -- عمليةٌ بمهمّةٍ غير موجودة ⇒ 23503 على `task_id`
-- =============================================================================
