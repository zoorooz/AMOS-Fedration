-- =============================================================================
-- AMOS-Federation — الهجرة 011: الدولة الاقتصادية الوطنية (R9-Q)
-- الهدف: طبقةٌ اقتصاديةٌ **فوق** الخزانة القائمة — بلا دفترٍ ثانٍ ولا محرّك حركاتٍ ثانٍ
-- المالك: federal/executive/services
-- تاريخ الإنشاء: 2026-08-17
--
-- ## ما تفعله هذه الهجرة وما لا تفعله
--
-- تفعل: ثلاثةَ عشرَ جدولًا جديدًا بحتًا، وتوسيعَ مفردةِ العمليات في ثلاثةِ قيود
-- `CHECK` قائمة (`ALTER … DROP CONSTRAINT` ثمّ `ADD CONSTRAINT` بنفس الاسم).
--
-- لا تفعل: لا `DROP TABLE`، ولا `DELETE FROM`، ولا `UPDATE` على صفٍّ تاريخيّ،
-- ولا عمودَ محذوف، ولا حركةَ خزانةٍ تُعاد كتابتُها، ولا جدولَ حركاتٍ ثانيًا،
-- ولا جدولَ أرصدةٍ (الأرصدةُ مُشتقّةٌ في R7-B وتبقى مُشتقّة).
--
-- ## توسيعُ مفردة العمليات — ولماذا `ALTER` هنا مقبولٌ ولم يكن مقبولًا في 010
--
-- 010 لم تكن تحتاج عمليةً جديدة، فامتنعت عن `ALTER` عن حقّ. R9 تحتاج إحدى عشرة
-- عمليةً اقتصادية، والبديلُ عن توسيع المفردة الواحدة هو **مفردةٌ ثانية وجدولُ
-- مِنَحٍ ثانٍ ومحرّكُ تخويلٍ ثانٍ** — وهو بالضبط ما تمنعه R9-M/R9-O. فالتوسيعُ
-- هو الخيار الذي يُبقي المحرّك الكانونيّ واحدًا:
--
--   state_authority_grants.operation        (008)  ck_state_authority_grants_operation
--   state_transaction_authority.operation   (008)  ck_state_transaction_authority_operation
--   state_government_delegations.operation  (010)  ck_state_government_delegations_operation
--
-- الأسماءُ الخمسة القديمة تبقى كما هي — لا صفَّ قائمًا يخالف القيدَ الجديد،
-- فالتوسيعُ إضافةٌ محضة ولا يُبطل بيانًا موجودًا.
--
-- المصدرُ الوحيد لهذه الأسماء في الشيفرة:
-- `services/national_registry/models.py::GRANTABLE_OPERATIONS`
-- = `FISCAL_JUDICIAL_OPERATIONS` + `ECONOMIC_OPERATIONS`. ويحرس اختبارٌ ساكن
-- تطابقَ هذا الملفّ مع تلك المفردة، فلا تتباعد قاعدةٌ عن شيفرة.
--
-- ## الترتيب مقصود
--
-- قطاعٌ → فئة → برنامج → كيانٌ اقتصاديّ عامّ → سياسة → تعريفُ مؤشّر → مصدرُ
-- إيراد → إجازةُ إنفاق → أصلٌ عامّ → التزامٌ عامّ → تحويلٌ (مِنحة/دعم) →
-- مشترياتٌ → قرارٌ اقتصاديّ (يشير إلى كلِّ ما سبق). فكلُّ مفتاحٍ أجنبيّ يجد
-- هدفَه موجودًا عند إنشائه.
--
-- ## المفاتيح الأجنبية إلى ما هو قائم (لا استنساخ لكيانٍ موجود)
--
--   *.government_id            → state_governments.id        (R8 · 010)
--   *.institution_id           → state_institutions.id       (R7-A · 006)
--   *.department_id            → state_departments.id        (R7-A · 006)
--   *.identity_id              → state_identities.id         (R7-C · 008)
--   *.position_id              → state_positions.id          (R7-C · 008)
--   *.budget_id                → state_budgets.id            (R7-B · 007)
--   *.allocation_id            → state_allocations.id        (R7-B · 007)
--   *.decision_id              → state_decisions.id          (R7-A/2)
--   *.operation_id             → state_government_operations.id (R8 · 010)
--   *.task_id                  → tasks.id                    (R2/R4)
--
-- والمالُ لا يُنفَّذ هنا: `state_expenditure_authorizations` و
-- `state_economic_transfers` تحملان `transaction_reference` وهو مرجعُ حركةٍ في
-- `state_transactions` (R7-B) نُفِّذت **بالخزانة**. ولا عمودَ رصيدٍ في أيّ جدول.
--
-- ## دَينٌ معروفٌ يبقى دَينًا
--
-- خللُ سلسلة الهجرات في `004_unify_tasks_schema.sql` على قاعدةٍ جديدة **لم
-- يُصلَح هنا** ولا يُدَّعى إصلاحُه؛ يبقى مُصنَّفًا دَينًا قائمًا كما في R7-C/R7-D/R8.
-- =============================================================================

-- الخطوة 0: توسيعُ مفردة العمليات في القيود الثلاثة القائمة.
-- `DROP CONSTRAINT IF EXISTS` ثمّ `ADD CONSTRAINT` بنفس الاسم — والحَشوُ محميٌّ
-- بفحصِ `pg_constraint` فتُعاد الهجرةُ بلا خطأ.
ALTER TABLE state_authority_grants
    DROP CONSTRAINT IF EXISTS ck_state_authority_grants_operation;
ALTER TABLE state_authority_grants
    ADD CONSTRAINT ck_state_authority_grants_operation CHECK (
        operation IN (
            'treasury.funding.post',
            'treasury.allocation.create',
            'treasury.disbursement.post',
            'treasury.transaction.reverse',
            'gov.case.decide',
            'economy.entity.register',
            'economy.program.create',
            'economy.policy.issue',
            'economy.policy.activate',
            'economy.revenue.register',
            'economy.expenditure.authorize',
            'economy.grant.authorize',
            'economy.subsidy.authorize',
            'economy.asset.register',
            'economy.liability.register',
            'economy.procurement.authorize'
        )
    );

ALTER TABLE state_transaction_authority
    DROP CONSTRAINT IF EXISTS ck_state_transaction_authority_operation;
ALTER TABLE state_transaction_authority
    ADD CONSTRAINT ck_state_transaction_authority_operation CHECK (
        operation IN (
            'treasury.funding.post',
            'treasury.allocation.create',
            'treasury.disbursement.post',
            'treasury.transaction.reverse',
            'gov.case.decide',
            'economy.entity.register',
            'economy.program.create',
            'economy.policy.issue',
            'economy.policy.activate',
            'economy.revenue.register',
            'economy.expenditure.authorize',
            'economy.grant.authorize',
            'economy.subsidy.authorize',
            'economy.asset.register',
            'economy.liability.register',
            'economy.procurement.authorize'
        )
    );

ALTER TABLE state_government_delegations
    DROP CONSTRAINT IF EXISTS ck_state_government_delegations_operation;
ALTER TABLE state_government_delegations
    ADD CONSTRAINT ck_state_government_delegations_operation CHECK (
        operation IN (
            'treasury.funding.post',
            'treasury.allocation.create',
            'treasury.disbursement.post',
            'treasury.transaction.reverse',
            'gov.case.decide',
            'economy.entity.register',
            'economy.program.create',
            'economy.policy.issue',
            'economy.policy.activate',
            'economy.revenue.register',
            'economy.expenditure.authorize',
            'economy.grant.authorize',
            'economy.subsidy.authorize',
            'economy.asset.register',
            'economy.liability.register',
            'economy.procurement.authorize'
        )
    );

-- الخطوة 1: القطاعُ الاقتصاديّ — الجذرُ التصنيفيّ. مملوكٌ لحكومةٍ مُسمّاة
-- (فدرالية أو ولاية)، فلا قطاعَ «بلا مالك» يُنسَب إليه لاحقًا ما يُشتهى.
CREATE TABLE IF NOT EXISTS state_economic_sectors (
    id VARCHAR NOT NULL,
    code VARCHAR NOT NULL,
    name VARCHAR NOT NULL,
    description TEXT DEFAULT '',
    government_id VARCHAR NOT NULL,
    scope_level VARCHAR NOT NULL,
    status VARCHAR NOT NULL DEFAULT 'active',
    created_by VARCHAR NOT NULL,
    created_by_identity_id VARCHAR,
    tenant_id VARCHAR NOT NULL DEFAULT 'default',
    created_at TIMESTAMP WITHOUT TIME ZONE,
    updated_at TIMESTAMP WITHOUT TIME ZONE,
    PRIMARY KEY (id),
    CONSTRAINT uq_state_economic_sectors_tenant_code UNIQUE (tenant_id, code),
    CONSTRAINT ck_state_economic_sectors_scope CHECK (scope_level IN ('FEDERAL','STATE')),
    CONSTRAINT ck_state_economic_sectors_status CHECK (status IN ('active','suspended','closed')),
    CONSTRAINT ck_state_economic_sectors_code_present CHECK (length(code) > 0),
    FOREIGN KEY(government_id) REFERENCES state_governments (id) ON DELETE RESTRICT,
    FOREIGN KEY(created_by_identity_id) REFERENCES state_identities (id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS ix_state_economic_sectors_gov
    ON state_economic_sectors (tenant_id, government_id, status);

-- الخطوة 2: الفئةُ داخل القطاع. الرمزُ فريدٌ **داخل قطاعه** لا وطنيًّا، فلا
-- تُصادِم فئتا قطاعين مختلفين، ولا تُعرَّف فئةٌ بالاسم.
CREATE TABLE IF NOT EXISTS state_economic_categories (
    id VARCHAR NOT NULL,
    sector_id VARCHAR NOT NULL,
    code VARCHAR NOT NULL,
    name VARCHAR NOT NULL,
    description TEXT DEFAULT '',
    status VARCHAR NOT NULL DEFAULT 'active',
    created_by VARCHAR NOT NULL,
    created_by_identity_id VARCHAR,
    tenant_id VARCHAR NOT NULL DEFAULT 'default',
    created_at TIMESTAMP WITHOUT TIME ZONE,
    updated_at TIMESTAMP WITHOUT TIME ZONE,
    PRIMARY KEY (id),
    CONSTRAINT uq_state_economic_categories_sector_code UNIQUE (tenant_id, sector_id, code),
    CONSTRAINT ck_state_economic_categories_status CHECK (status IN ('active','suspended','closed')),
    CONSTRAINT ck_state_economic_categories_code_present CHECK (length(code) > 0),
    FOREIGN KEY(sector_id) REFERENCES state_economic_sectors (id) ON DELETE RESTRICT,
    FOREIGN KEY(created_by_identity_id) REFERENCES state_identities (id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS ix_state_economic_categories_sector
    ON state_economic_categories (tenant_id, sector_id, status);

-- الخطوة 3: البرنامجُ الاقتصاديّ الحكوميّ (R9-B/R9-K). مالكُه مؤسسةٌ **وحكومة**
-- معًا: المؤسسةُ تُنفِّذ والحكومةُ تحكم النطاق، ولا يُستنتَج أحدهما من الآخر.
CREATE TABLE IF NOT EXISTS state_economic_programs (
    id VARCHAR NOT NULL,
    code VARCHAR NOT NULL,
    name VARCHAR NOT NULL,
    purpose TEXT NOT NULL,
    sector_id VARCHAR NOT NULL,
    category_id VARCHAR,
    government_id VARCHAR NOT NULL,
    institution_id VARCHAR NOT NULL,
    department_id VARCHAR,
    scope_level VARCHAR NOT NULL,
    status VARCHAR NOT NULL DEFAULT 'draft',
    policy_id VARCHAR,
    created_by VARCHAR NOT NULL,
    created_by_identity_id VARCHAR,
    created_by_position_id VARCHAR,
    authority_classification VARCHAR NOT NULL,
    tenant_id VARCHAR NOT NULL DEFAULT 'default',
    created_at TIMESTAMP WITHOUT TIME ZONE,
    updated_at TIMESTAMP WITHOUT TIME ZONE,
    PRIMARY KEY (id),
    CONSTRAINT uq_state_economic_programs_tenant_code UNIQUE (tenant_id, code),
    CONSTRAINT ck_state_economic_programs_scope CHECK (
        scope_level IN ('FEDERAL','STATE','INSTITUTION','DEPARTMENT')
    ),
    CONSTRAINT ck_state_economic_programs_status CHECK (
        status IN ('draft','active','suspended','closed')
    ),
    CONSTRAINT ck_state_economic_programs_department CHECK (
        scope_level <> 'DEPARTMENT' OR department_id IS NOT NULL
    ),
    CONSTRAINT ck_state_economic_programs_classification CHECK (
        authority_classification IN ('PROVEN','PARTIAL','UNRESOLVED')
    ),
    CONSTRAINT ck_state_economic_programs_purpose_present CHECK (length(purpose) > 0),
    FOREIGN KEY(sector_id) REFERENCES state_economic_sectors (id) ON DELETE RESTRICT,
    FOREIGN KEY(category_id) REFERENCES state_economic_categories (id) ON DELETE RESTRICT,
    FOREIGN KEY(government_id) REFERENCES state_governments (id) ON DELETE RESTRICT,
    FOREIGN KEY(institution_id) REFERENCES state_institutions (id) ON DELETE RESTRICT,
    FOREIGN KEY(department_id) REFERENCES state_departments (id) ON DELETE RESTRICT,
    FOREIGN KEY(created_by_identity_id) REFERENCES state_identities (id) ON DELETE RESTRICT,
    FOREIGN KEY(created_by_position_id) REFERENCES state_positions (id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS ix_state_economic_programs_owner
    ON state_economic_programs (tenant_id, government_id, institution_id, status);

-- الخطوة 4: الكيانُ الاقتصاديّ العامّ (R9-B). هويتُه **صفٌّ في `state_identities`**
-- لا اسمٌ نصّيّ، فلا كيانَ اقتصاديّ بلا هويةٍ كانونية.
CREATE TABLE IF NOT EXISTS state_public_economic_entities (
    id VARCHAR NOT NULL,
    code VARCHAR NOT NULL,
    name VARCHAR NOT NULL,
    entity_kind VARCHAR NOT NULL,
    identity_id VARCHAR NOT NULL,
    government_id VARCHAR NOT NULL,
    institution_id VARCHAR,
    sector_id VARCHAR,
    status VARCHAR NOT NULL DEFAULT 'active',
    created_by VARCHAR NOT NULL,
    created_by_identity_id VARCHAR,
    authority_classification VARCHAR NOT NULL,
    tenant_id VARCHAR NOT NULL DEFAULT 'default',
    created_at TIMESTAMP WITHOUT TIME ZONE,
    updated_at TIMESTAMP WITHOUT TIME ZONE,
    PRIMARY KEY (id),
    CONSTRAINT uq_state_public_economic_entities_tenant_code UNIQUE (tenant_id, code),
    CONSTRAINT uq_state_public_economic_entities_identity UNIQUE (tenant_id, identity_id),
    CONSTRAINT ck_state_public_economic_entities_kind CHECK (
        entity_kind IN ('STATE_OWNED_ENTERPRISE','PUBLIC_FUND','REGULATORY_BODY','PUBLIC_UTILITY','PUBLIC_AGENCY')
    ),
    CONSTRAINT ck_state_public_economic_entities_status CHECK (
        status IN ('active','suspended','dissolved')
    ),
    CONSTRAINT ck_state_public_economic_entities_classification CHECK (
        authority_classification IN ('PROVEN','PARTIAL','UNRESOLVED')
    ),
    FOREIGN KEY(identity_id) REFERENCES state_identities (id) ON DELETE RESTRICT,
    FOREIGN KEY(government_id) REFERENCES state_governments (id) ON DELETE RESTRICT,
    FOREIGN KEY(institution_id) REFERENCES state_institutions (id) ON DELETE RESTRICT,
    FOREIGN KEY(sector_id) REFERENCES state_economic_sectors (id) ON DELETE RESTRICT,
    FOREIGN KEY(created_by_identity_id) REFERENCES state_identities (id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS ix_state_public_economic_entities_gov
    ON state_public_economic_entities (tenant_id, government_id, status);

-- الخطوة 5: السياسةُ الاقتصادية (R9-D). **وجودُ الصفّ ليس نفاذًا**: القيدُ
-- `ck_state_economic_policies_active_needs_provenance` يمنع حالة `active` بلا
-- سلطةٍ مُثبَتة (هوية + منصب) وبلا `effective_from` وبلا عمليةِ تنفيذٍ مُسجَّلة.
-- والنسخةُ عمودٌ صريح: تعديلُ سياسةٍ نافذة يُنشئ نسخةً ولا يُعيد كتابة تاريخ.
CREATE TABLE IF NOT EXISTS state_economic_policies (
    id VARCHAR NOT NULL,
    code VARCHAR NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    title VARCHAR NOT NULL,
    body TEXT NOT NULL,
    policy_type VARCHAR NOT NULL,
    scope_level VARCHAR NOT NULL,
    government_id VARCHAR NOT NULL,
    owner_institution_id VARCHAR NOT NULL,
    department_id VARCHAR,
    sector_id VARCHAR,
    status VARCHAR NOT NULL DEFAULT 'draft',
    effective_from TIMESTAMP WITHOUT TIME ZONE,
    effective_until TIMESTAMP WITHOUT TIME ZONE,
    issued_by VARCHAR NOT NULL,
    issuing_identity_id VARCHAR,
    issuing_position_id VARCHAR,
    decision_id VARCHAR,
    issue_operation_id VARCHAR,
    activation_operation_id VARCHAR,
    authority_classification VARCHAR NOT NULL,
    tenant_id VARCHAR NOT NULL DEFAULT 'default',
    created_at TIMESTAMP WITHOUT TIME ZONE,
    updated_at TIMESTAMP WITHOUT TIME ZONE,
    revoked_at TIMESTAMP WITHOUT TIME ZONE,
    revoked_reason TEXT DEFAULT '',
    PRIMARY KEY (id),
    CONSTRAINT uq_state_economic_policies_code_version UNIQUE (tenant_id, code, version),
    CONSTRAINT ck_state_economic_policies_type CHECK (
        policy_type IN ('FISCAL','MONETARY_ADVISORY','TRADE','SUBSIDY','TAXATION','PROCUREMENT','SECTORAL')
    ),
    CONSTRAINT ck_state_economic_policies_scope CHECK (
        scope_level IN ('FEDERAL','STATE','INSTITUTION','DEPARTMENT')
    ),
    CONSTRAINT ck_state_economic_policies_status CHECK (
        status IN ('draft','active','suspended','expired','revoked')
    ),
    CONSTRAINT ck_state_economic_policies_department CHECK (
        scope_level <> 'DEPARTMENT' OR department_id IS NOT NULL
    ),
    CONSTRAINT ck_state_economic_policies_version CHECK (version >= 1),
    CONSTRAINT ck_state_economic_policies_classification CHECK (
        authority_classification IN ('PROVEN','PARTIAL','UNRESOLVED')
    ),
    -- النفاذُ يلزمه دليلٌ: مُصدِرٌ بهويةٍ ومنصب، ومدةُ نفاذٍ مبدوءة، وعمليةُ
    -- تنفيذٍ مُسجَّلة في `state_government_operations`. فلا `UPDATE status`
    -- يجعل سياسةً نافذةً بلا سلسلةِ إسناد.
    CONSTRAINT ck_state_economic_policies_active_needs_provenance CHECK (
        status <> 'active'
        OR (
            effective_from IS NOT NULL
            AND issuing_identity_id IS NOT NULL
            AND issuing_position_id IS NOT NULL
            AND activation_operation_id IS NOT NULL
        )
    ),
    CONSTRAINT ck_state_economic_policies_window CHECK (
        effective_until IS NULL OR effective_from IS NULL OR effective_until > effective_from
    ),
    CONSTRAINT ck_state_economic_policies_revoked_at CHECK (
        (status = 'revoked' AND revoked_at IS NOT NULL)
        OR (status <> 'revoked' AND revoked_at IS NULL)
    ),
    FOREIGN KEY(government_id) REFERENCES state_governments (id) ON DELETE RESTRICT,
    FOREIGN KEY(owner_institution_id) REFERENCES state_institutions (id) ON DELETE RESTRICT,
    FOREIGN KEY(department_id) REFERENCES state_departments (id) ON DELETE RESTRICT,
    FOREIGN KEY(sector_id) REFERENCES state_economic_sectors (id) ON DELETE RESTRICT,
    FOREIGN KEY(issuing_identity_id) REFERENCES state_identities (id) ON DELETE RESTRICT,
    FOREIGN KEY(issuing_position_id) REFERENCES state_positions (id) ON DELETE RESTRICT,
    FOREIGN KEY(decision_id) REFERENCES state_decisions (id) ON DELETE RESTRICT,
    FOREIGN KEY(issue_operation_id) REFERENCES state_government_operations (id) ON DELETE RESTRICT,
    FOREIGN KEY(activation_operation_id) REFERENCES state_government_operations (id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS ix_state_economic_policies_scope
    ON state_economic_policies (tenant_id, government_id, scope_level, status);

-- الخطوة 6: تعريفُ المؤشّر الاقتصاديّ (R9-B). **تعريفٌ لا قياس**: لا عمودَ قيمةٍ
-- هنا، فلا يُدَّعى أن النظام يقيس اقتصادًا واقعيًّا بمجرّد وجود تعريف.
CREATE TABLE IF NOT EXISTS state_economic_indicator_definitions (
    id VARCHAR NOT NULL,
    code VARCHAR NOT NULL,
    name VARCHAR NOT NULL,
    unit VARCHAR NOT NULL,
    method TEXT NOT NULL,
    scope_level VARCHAR NOT NULL,
    government_id VARCHAR NOT NULL,
    sector_id VARCHAR,
    measurement_status VARCHAR NOT NULL DEFAULT 'UNAVAILABLE',
    status VARCHAR NOT NULL DEFAULT 'active',
    created_by VARCHAR NOT NULL,
    created_by_identity_id VARCHAR,
    tenant_id VARCHAR NOT NULL DEFAULT 'default',
    created_at TIMESTAMP WITHOUT TIME ZONE,
    updated_at TIMESTAMP WITHOUT TIME ZONE,
    PRIMARY KEY (id),
    CONSTRAINT uq_state_economic_indicator_definitions_tenant_code UNIQUE (tenant_id, code),
    CONSTRAINT ck_state_economic_indicator_definitions_scope CHECK (
        scope_level IN ('FEDERAL','STATE','INSTITUTION','DEPARTMENT')
    ),
    CONSTRAINT ck_state_economic_indicator_definitions_status CHECK (
        status IN ('active','suspended','retired')
    ),
    -- القياسُ الفعليّ غيرُ منفَّذ ولا يُدَّعى: المفردةُ لا تحتوي `REAL`.
    CONSTRAINT ck_state_economic_indicator_definitions_measurement CHECK (
        measurement_status IN ('PARTIAL','UNAVAILABLE')
    ),
    CONSTRAINT ck_state_economic_indicator_definitions_method_present CHECK (length(method) > 0),
    FOREIGN KEY(government_id) REFERENCES state_governments (id) ON DELETE RESTRICT,
    FOREIGN KEY(sector_id) REFERENCES state_economic_sectors (id) ON DELETE RESTRICT,
    FOREIGN KEY(created_by_identity_id) REFERENCES state_identities (id) ON DELETE RESTRICT
);

-- الخطوة 7: مصدرُ الإيراد الحكوميّ (R9-E). **تسجيلٌ لا تحصيل**: لا سكّةَ تحصيلٍ
-- واقعية في النظام، فعمود `collection_status` مفردتُه `PARTIAL`/`UNAVAILABLE`
-- ولا تحتوي `REAL` — لا يُرفَع التصنيفُ بتعديلِ صفّ.
CREATE TABLE IF NOT EXISTS state_revenue_sources (
    id VARCHAR NOT NULL,
    code VARCHAR NOT NULL,
    name VARCHAR NOT NULL,
    revenue_kind VARCHAR NOT NULL,
    basis TEXT NOT NULL,
    government_id VARCHAR NOT NULL,
    institution_id VARCHAR NOT NULL,
    department_id VARCHAR,
    sector_id VARCHAR,
    program_id VARCHAR,
    policy_id VARCHAR,
    revenue_account_id VARCHAR,
    collection_status VARCHAR NOT NULL DEFAULT 'UNAVAILABLE',
    status VARCHAR NOT NULL DEFAULT 'active',
    registered_by VARCHAR NOT NULL,
    registered_by_identity_id VARCHAR,
    registered_by_position_id VARCHAR,
    authority_classification VARCHAR NOT NULL,
    operation_id VARCHAR,
    tenant_id VARCHAR NOT NULL DEFAULT 'default',
    created_at TIMESTAMP WITHOUT TIME ZONE,
    updated_at TIMESTAMP WITHOUT TIME ZONE,
    PRIMARY KEY (id),
    CONSTRAINT uq_state_revenue_sources_tenant_code UNIQUE (tenant_id, code),
    CONSTRAINT ck_state_revenue_sources_kind CHECK (
        revenue_kind IN ('TAX','FEE','LICENSE','SERVICE_CHARGE','FINE','GRANT_RECEIVED','OTHER')
    ),
    CONSTRAINT ck_state_revenue_sources_collection CHECK (
        collection_status IN ('PARTIAL','UNAVAILABLE')
    ),
    CONSTRAINT ck_state_revenue_sources_status CHECK (
        status IN ('active','suspended','closed')
    ),
    CONSTRAINT ck_state_revenue_sources_classification CHECK (
        authority_classification IN ('PROVEN','PARTIAL','UNRESOLVED')
    ),
    CONSTRAINT ck_state_revenue_sources_basis_present CHECK (length(basis) > 0),
    FOREIGN KEY(government_id) REFERENCES state_governments (id) ON DELETE RESTRICT,
    FOREIGN KEY(institution_id) REFERENCES state_institutions (id) ON DELETE RESTRICT,
    FOREIGN KEY(department_id) REFERENCES state_departments (id) ON DELETE RESTRICT,
    FOREIGN KEY(sector_id) REFERENCES state_economic_sectors (id) ON DELETE RESTRICT,
    FOREIGN KEY(program_id) REFERENCES state_economic_programs (id) ON DELETE RESTRICT,
    FOREIGN KEY(policy_id) REFERENCES state_economic_policies (id) ON DELETE RESTRICT,
    FOREIGN KEY(revenue_account_id) REFERENCES state_accounts (id) ON DELETE RESTRICT,
    FOREIGN KEY(registered_by_identity_id) REFERENCES state_identities (id) ON DELETE RESTRICT,
    FOREIGN KEY(registered_by_position_id) REFERENCES state_positions (id) ON DELETE RESTRICT,
    FOREIGN KEY(operation_id) REFERENCES state_government_operations (id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS ix_state_revenue_sources_owner
    ON state_revenue_sources (tenant_id, government_id, institution_id, status);

-- الخطوة 8: إجازةُ الإنفاق (R9-F). حلقةٌ **قبل** الخزانة لا بديلٌ عنها:
-- برنامج → موازنة → تخصيص → إجازةٌ هنا → حركةُ خزانةٍ في `state_transactions`.
-- و`transaction_reference` مرجعُ تلك الحركة، والقيدُ يمنع حالة `executed` بلا
-- مرجعٍ وبلا `operation_id` — فلا «نُفِّذ» بلا أثرٍ يُفحَص. ولا عمودَ رصيد.
CREATE TABLE IF NOT EXISTS state_expenditure_authorizations (
    id VARCHAR NOT NULL,
    reference VARCHAR NOT NULL,
    program_id VARCHAR NOT NULL,
    budget_id VARCHAR NOT NULL,
    allocation_id VARCHAR NOT NULL,
    government_id VARCHAR NOT NULL,
    institution_id VARCHAR NOT NULL,
    department_id VARCHAR,
    scope_level VARCHAR NOT NULL,
    amount NUMERIC(20,4) NOT NULL,
    currency VARCHAR NOT NULL,
    purpose TEXT NOT NULL,
    policy_id VARCHAR,
    status VARCHAR NOT NULL DEFAULT 'authorized',
    authorized_by VARCHAR NOT NULL,
    authorizing_identity_id VARCHAR,
    authorizing_position_id VARCHAR,
    authority_classification VARCHAR NOT NULL,
    grant_id VARCHAR,
    decision_id VARCHAR,
    operation_id VARCHAR,
    transaction_reference VARCHAR,
    correlation_id VARCHAR,
    tenant_id VARCHAR NOT NULL DEFAULT 'default',
    created_at TIMESTAMP WITHOUT TIME ZONE,
    updated_at TIMESTAMP WITHOUT TIME ZONE,
    PRIMARY KEY (id),
    CONSTRAINT uq_state_expenditure_authorizations_tenant_reference UNIQUE (tenant_id, reference),
    CONSTRAINT ck_state_expenditure_authorizations_scope CHECK (
        scope_level IN ('FEDERAL','STATE','INSTITUTION','DEPARTMENT')
    ),
    CONSTRAINT ck_state_expenditure_authorizations_status CHECK (
        status IN ('authorized','executed','failed','reversed')
    ),
    CONSTRAINT ck_state_expenditure_authorizations_amount CHECK (
        amount > 0 AND amount <= 900000000000
    ),
    CONSTRAINT ck_state_expenditure_authorizations_currency CHECK (
        length(currency) = 3 AND currency = upper(currency)
    ),
    CONSTRAINT ck_state_expenditure_authorizations_department CHECK (
        scope_level <> 'DEPARTMENT' OR department_id IS NOT NULL
    ),
    CONSTRAINT ck_state_expenditure_authorizations_classification CHECK (
        authority_classification IN ('PROVEN','PARTIAL','UNRESOLVED')
    ),
    -- «نُفِّذ» يلزمه مرجعُ حركةِ خزانةٍ وأثرُ عمليةٍ. ولا يُقبَل العكس: مرجعُ حركةٍ
    -- على إجازةٍ لم تُنفَّذ يعني حركةً بلا إجازة، وهو ما تمنعه R9-F.
    CONSTRAINT ck_state_expenditure_authorizations_executed CHECK (
        (status IN ('executed','reversed') AND transaction_reference IS NOT NULL AND operation_id IS NOT NULL)
        OR (status NOT IN ('executed','reversed') AND transaction_reference IS NULL)
    ),
    CONSTRAINT ck_state_expenditure_authorizations_purpose_present CHECK (length(purpose) > 0),
    FOREIGN KEY(program_id) REFERENCES state_economic_programs (id) ON DELETE RESTRICT,
    FOREIGN KEY(budget_id) REFERENCES state_budgets (id) ON DELETE RESTRICT,
    FOREIGN KEY(allocation_id) REFERENCES state_allocations (id) ON DELETE RESTRICT,
    FOREIGN KEY(government_id) REFERENCES state_governments (id) ON DELETE RESTRICT,
    FOREIGN KEY(institution_id) REFERENCES state_institutions (id) ON DELETE RESTRICT,
    FOREIGN KEY(department_id) REFERENCES state_departments (id) ON DELETE RESTRICT,
    FOREIGN KEY(policy_id) REFERENCES state_economic_policies (id) ON DELETE RESTRICT,
    FOREIGN KEY(authorizing_identity_id) REFERENCES state_identities (id) ON DELETE RESTRICT,
    FOREIGN KEY(authorizing_position_id) REFERENCES state_positions (id) ON DELETE RESTRICT,
    FOREIGN KEY(grant_id) REFERENCES state_authority_grants (id) ON DELETE RESTRICT,
    FOREIGN KEY(decision_id) REFERENCES state_decisions (id) ON DELETE RESTRICT,
    FOREIGN KEY(operation_id) REFERENCES state_government_operations (id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS ix_state_expenditure_authorizations_program
    ON state_expenditure_authorizations (tenant_id, program_id, status);

CREATE INDEX IF NOT EXISTS ix_state_expenditure_authorizations_transaction
    ON state_expenditure_authorizations (tenant_id, transaction_reference);

-- الخطوة 9: الأصلُ العامّ (R9-G). `registration_class` مفردتُه صفةٌ واحدة:
-- `SYSTEM_REGISTERED`. ولا مفردةَ ملكيةٍ واقعية: `external_ownership_status`
-- لا تحتوي إلا `UNAVAILABLE` — فوجودُ صفٍّ **ليس** ملكيةً في العالم الخارجيّ،
-- والقاعدةُ نفسُها تمنع الادّعاء لا التعليقُ فقط.
CREATE TABLE IF NOT EXISTS state_public_assets (
    id VARCHAR NOT NULL,
    code VARCHAR NOT NULL,
    name VARCHAR NOT NULL,
    asset_class VARCHAR NOT NULL,
    description TEXT DEFAULT '',
    government_id VARCHAR NOT NULL,
    institution_id VARCHAR NOT NULL,
    department_id VARCHAR,
    custodian_identity_id VARCHAR NOT NULL,
    registration_class VARCHAR NOT NULL DEFAULT 'SYSTEM_REGISTERED',
    external_ownership_status VARCHAR NOT NULL DEFAULT 'UNAVAILABLE',
    book_value NUMERIC(20,4),
    currency VARCHAR,
    status VARCHAR NOT NULL DEFAULT 'active',
    registered_by VARCHAR NOT NULL,
    registered_by_identity_id VARCHAR,
    registered_by_position_id VARCHAR,
    authority_classification VARCHAR NOT NULL,
    operation_id VARCHAR,
    tenant_id VARCHAR NOT NULL DEFAULT 'default',
    created_at TIMESTAMP WITHOUT TIME ZONE,
    updated_at TIMESTAMP WITHOUT TIME ZONE,
    PRIMARY KEY (id),
    CONSTRAINT uq_state_public_assets_tenant_code UNIQUE (tenant_id, code),
    CONSTRAINT ck_state_public_assets_class CHECK (
        asset_class IN ('LAND','BUILDING','INFRASTRUCTURE','EQUIPMENT','FINANCIAL','INTANGIBLE')
    ),
    CONSTRAINT ck_state_public_assets_registration CHECK (
        registration_class = 'SYSTEM_REGISTERED'
    ),
    CONSTRAINT ck_state_public_assets_external_ownership CHECK (
        external_ownership_status = 'UNAVAILABLE'
    ),
    CONSTRAINT ck_state_public_assets_status CHECK (
        status IN ('active','suspended','disposed')
    ),
    CONSTRAINT ck_state_public_assets_value CHECK (
        book_value IS NULL OR (book_value >= 0 AND book_value <= 900000000000)
    ),
    CONSTRAINT ck_state_public_assets_currency CHECK (
        currency IS NULL OR (length(currency) = 3 AND currency = upper(currency))
    ),
    CONSTRAINT ck_state_public_assets_value_currency CHECK (
        (book_value IS NULL AND currency IS NULL) OR (book_value IS NOT NULL AND currency IS NOT NULL)
    ),
    CONSTRAINT ck_state_public_assets_classification CHECK (
        authority_classification IN ('PROVEN','PARTIAL','UNRESOLVED')
    ),
    FOREIGN KEY(government_id) REFERENCES state_governments (id) ON DELETE RESTRICT,
    FOREIGN KEY(institution_id) REFERENCES state_institutions (id) ON DELETE RESTRICT,
    FOREIGN KEY(department_id) REFERENCES state_departments (id) ON DELETE RESTRICT,
    FOREIGN KEY(custodian_identity_id) REFERENCES state_identities (id) ON DELETE RESTRICT,
    FOREIGN KEY(registered_by_identity_id) REFERENCES state_identities (id) ON DELETE RESTRICT,
    FOREIGN KEY(registered_by_position_id) REFERENCES state_positions (id) ON DELETE RESTRICT,
    FOREIGN KEY(operation_id) REFERENCES state_government_operations (id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS ix_state_public_assets_owner
    ON state_public_assets (tenant_id, government_id, institution_id, status);

-- الخطوة 10: الالتزامُ العامّ (R9-H). الدائنُ **هويةٌ كانونية مفروضة `NOT NULL`**
-- فلا دائنَ مُختلَقٌ باسمٍ نصّيّ. و`enforceability` مفردتُه `UNAVAILABLE` وحدها:
-- لا نفاذَ قانونيًّا خارجيًّا يُدَّعى من صفٍّ في قاعدةٍ داخلية.
CREATE TABLE IF NOT EXISTS state_public_liabilities (
    id VARCHAR NOT NULL,
    code VARCHAR NOT NULL,
    name VARCHAR NOT NULL,
    liability_class VARCHAR NOT NULL,
    description TEXT DEFAULT '',
    government_id VARCHAR NOT NULL,
    institution_id VARCHAR NOT NULL,
    department_id VARCHAR,
    creditor_identity_id VARCHAR NOT NULL,
    principal_amount NUMERIC(20,4) NOT NULL,
    currency VARCHAR NOT NULL,
    external_enforceability VARCHAR NOT NULL DEFAULT 'UNAVAILABLE',
    due_at TIMESTAMP WITHOUT TIME ZONE,
    status VARCHAR NOT NULL DEFAULT 'outstanding',
    registered_by VARCHAR NOT NULL,
    registered_by_identity_id VARCHAR,
    registered_by_position_id VARCHAR,
    authority_classification VARCHAR NOT NULL,
    operation_id VARCHAR,
    tenant_id VARCHAR NOT NULL DEFAULT 'default',
    created_at TIMESTAMP WITHOUT TIME ZONE,
    updated_at TIMESTAMP WITHOUT TIME ZONE,
    PRIMARY KEY (id),
    CONSTRAINT uq_state_public_liabilities_tenant_code UNIQUE (tenant_id, code),
    CONSTRAINT ck_state_public_liabilities_class CHECK (
        liability_class IN ('BOND','LOAN','PAYABLE','PENSION','GUARANTEE','OTHER')
    ),
    CONSTRAINT ck_state_public_liabilities_enforceability CHECK (
        external_enforceability = 'UNAVAILABLE'
    ),
    CONSTRAINT ck_state_public_liabilities_status CHECK (
        status IN ('outstanding','settled','written_off','disputed')
    ),
    CONSTRAINT ck_state_public_liabilities_amount CHECK (
        principal_amount > 0 AND principal_amount <= 900000000000
    ),
    CONSTRAINT ck_state_public_liabilities_currency CHECK (
        length(currency) = 3 AND currency = upper(currency)
    ),
    CONSTRAINT ck_state_public_liabilities_classification CHECK (
        authority_classification IN ('PROVEN','PARTIAL','UNRESOLVED')
    ),
    FOREIGN KEY(government_id) REFERENCES state_governments (id) ON DELETE RESTRICT,
    FOREIGN KEY(institution_id) REFERENCES state_institutions (id) ON DELETE RESTRICT,
    FOREIGN KEY(department_id) REFERENCES state_departments (id) ON DELETE RESTRICT,
    FOREIGN KEY(creditor_identity_id) REFERENCES state_identities (id) ON DELETE RESTRICT,
    FOREIGN KEY(registered_by_identity_id) REFERENCES state_identities (id) ON DELETE RESTRICT,
    FOREIGN KEY(registered_by_position_id) REFERENCES state_positions (id) ON DELETE RESTRICT,
    FOREIGN KEY(operation_id) REFERENCES state_government_operations (id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS ix_state_public_liabilities_owner
    ON state_public_liabilities (tenant_id, government_id, institution_id, status);

-- الخطوة 11: التحويلُ الاقتصاديّ — مِنحةٌ أو دعم (R9-I). **ليس محرّكَ نقلِ مالٍ
-- بديلًا**: المالُ يتحرّك بحركةِ خزانةٍ في `state_transactions` عبر R7-B،
-- وهذا الصفُّ إجازةٌ ومسارُ إسنادٍ يشير إلى مرجع تلك الحركة. والمستفيدُ هويةٌ
-- كانونية مفروضة، فلا مستفيدَ مُختلَق.
CREATE TABLE IF NOT EXISTS state_economic_transfers (
    id VARCHAR NOT NULL,
    reference VARCHAR NOT NULL,
    transfer_kind VARCHAR NOT NULL,
    program_id VARCHAR NOT NULL,
    beneficiary_identity_id VARCHAR NOT NULL,
    beneficiary_entity_id VARCHAR,
    government_id VARCHAR NOT NULL,
    institution_id VARCHAR NOT NULL,
    department_id VARCHAR,
    scope_level VARCHAR NOT NULL,
    budget_id VARCHAR NOT NULL,
    allocation_id VARCHAR NOT NULL,
    amount NUMERIC(20,4) NOT NULL,
    currency VARCHAR NOT NULL,
    purpose TEXT NOT NULL,
    policy_id VARCHAR,
    status VARCHAR NOT NULL DEFAULT 'authorized',
    authorized_by VARCHAR NOT NULL,
    authorizing_identity_id VARCHAR,
    authorizing_position_id VARCHAR,
    authority_classification VARCHAR NOT NULL,
    expenditure_authorization_id VARCHAR,
    decision_id VARCHAR,
    operation_id VARCHAR,
    transaction_reference VARCHAR,
    correlation_id VARCHAR,
    tenant_id VARCHAR NOT NULL DEFAULT 'default',
    created_at TIMESTAMP WITHOUT TIME ZONE,
    updated_at TIMESTAMP WITHOUT TIME ZONE,
    PRIMARY KEY (id),
    CONSTRAINT uq_state_economic_transfers_tenant_reference UNIQUE (tenant_id, reference),
    CONSTRAINT ck_state_economic_transfers_kind CHECK (
        transfer_kind IN ('GRANT','SUBSIDY')
    ),
    CONSTRAINT ck_state_economic_transfers_scope CHECK (
        scope_level IN ('FEDERAL','STATE','INSTITUTION','DEPARTMENT')
    ),
    CONSTRAINT ck_state_economic_transfers_status CHECK (
        status IN ('authorized','executed','failed','reversed')
    ),
    CONSTRAINT ck_state_economic_transfers_amount CHECK (
        amount > 0 AND amount <= 900000000000
    ),
    CONSTRAINT ck_state_economic_transfers_currency CHECK (
        length(currency) = 3 AND currency = upper(currency)
    ),
    CONSTRAINT ck_state_economic_transfers_department CHECK (
        scope_level <> 'DEPARTMENT' OR department_id IS NOT NULL
    ),
    CONSTRAINT ck_state_economic_transfers_classification CHECK (
        authority_classification IN ('PROVEN','PARTIAL','UNRESOLVED')
    ),
    CONSTRAINT ck_state_economic_transfers_executed CHECK (
        (status IN ('executed','reversed') AND transaction_reference IS NOT NULL AND operation_id IS NOT NULL)
        OR (status NOT IN ('executed','reversed') AND transaction_reference IS NULL)
    ),
    CONSTRAINT ck_state_economic_transfers_purpose_present CHECK (length(purpose) > 0),
    FOREIGN KEY(program_id) REFERENCES state_economic_programs (id) ON DELETE RESTRICT,
    FOREIGN KEY(beneficiary_identity_id) REFERENCES state_identities (id) ON DELETE RESTRICT,
    FOREIGN KEY(beneficiary_entity_id) REFERENCES state_public_economic_entities (id) ON DELETE RESTRICT,
    FOREIGN KEY(government_id) REFERENCES state_governments (id) ON DELETE RESTRICT,
    FOREIGN KEY(institution_id) REFERENCES state_institutions (id) ON DELETE RESTRICT,
    FOREIGN KEY(department_id) REFERENCES state_departments (id) ON DELETE RESTRICT,
    FOREIGN KEY(budget_id) REFERENCES state_budgets (id) ON DELETE RESTRICT,
    FOREIGN KEY(allocation_id) REFERENCES state_allocations (id) ON DELETE RESTRICT,
    FOREIGN KEY(policy_id) REFERENCES state_economic_policies (id) ON DELETE RESTRICT,
    FOREIGN KEY(authorizing_identity_id) REFERENCES state_identities (id) ON DELETE RESTRICT,
    FOREIGN KEY(authorizing_position_id) REFERENCES state_positions (id) ON DELETE RESTRICT,
    FOREIGN KEY(expenditure_authorization_id) REFERENCES state_expenditure_authorizations (id) ON DELETE RESTRICT,
    FOREIGN KEY(decision_id) REFERENCES state_decisions (id) ON DELETE RESTRICT,
    FOREIGN KEY(operation_id) REFERENCES state_government_operations (id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS ix_state_economic_transfers_program
    ON state_economic_transfers (tenant_id, program_id, transfer_kind, status);

-- الخطوة 12: المشترياتُ العامة (R9-J). **تجريدُ واجهةٍ خلفية لا سوق**:
-- `backend` مفردتُه `INTERNAL_ABSTRACTION` وحدها، و`external_market_status`
-- مفردتُه `UNAVAILABLE` وحدها. لا مزوّدٌ خارجيّ ولا مناقصةٌ ولا سوقٌ منفَّذ،
-- ولا نظامَ عقودٍ ثانٍ: العقدُ إن وُجد هو قرارٌ في `state_decisions`.
CREATE TABLE IF NOT EXISTS state_procurements (
    id VARCHAR NOT NULL,
    reference VARCHAR NOT NULL,
    title VARCHAR NOT NULL,
    program_id VARCHAR NOT NULL,
    government_id VARCHAR NOT NULL,
    requesting_institution_id VARCHAR NOT NULL,
    department_id VARCHAR,
    scope_level VARCHAR NOT NULL,
    supplier_identity_id VARCHAR NOT NULL,
    estimated_amount NUMERIC(20,4) NOT NULL,
    currency VARCHAR NOT NULL,
    specification TEXT NOT NULL,
    backend VARCHAR NOT NULL DEFAULT 'INTERNAL_ABSTRACTION',
    external_market_status VARCHAR NOT NULL DEFAULT 'UNAVAILABLE',
    policy_id VARCHAR,
    status VARCHAR NOT NULL DEFAULT 'authorized',
    authorized_by VARCHAR NOT NULL,
    authorizing_identity_id VARCHAR,
    authorizing_position_id VARCHAR,
    authority_classification VARCHAR NOT NULL,
    decision_id VARCHAR,
    expenditure_authorization_id VARCHAR,
    operation_id VARCHAR,
    tenant_id VARCHAR NOT NULL DEFAULT 'default',
    created_at TIMESTAMP WITHOUT TIME ZONE,
    updated_at TIMESTAMP WITHOUT TIME ZONE,
    PRIMARY KEY (id),
    CONSTRAINT uq_state_procurements_tenant_reference UNIQUE (tenant_id, reference),
    CONSTRAINT ck_state_procurements_scope CHECK (
        scope_level IN ('FEDERAL','STATE','INSTITUTION','DEPARTMENT')
    ),
    CONSTRAINT ck_state_procurements_backend CHECK (backend = 'INTERNAL_ABSTRACTION'),
    CONSTRAINT ck_state_procurements_external_market CHECK (external_market_status = 'UNAVAILABLE'),
    CONSTRAINT ck_state_procurements_status CHECK (
        status IN ('authorized','fulfilled','cancelled')
    ),
    CONSTRAINT ck_state_procurements_amount CHECK (
        estimated_amount > 0 AND estimated_amount <= 900000000000
    ),
    CONSTRAINT ck_state_procurements_currency CHECK (
        length(currency) = 3 AND currency = upper(currency)
    ),
    CONSTRAINT ck_state_procurements_department CHECK (
        scope_level <> 'DEPARTMENT' OR department_id IS NOT NULL
    ),
    CONSTRAINT ck_state_procurements_classification CHECK (
        authority_classification IN ('PROVEN','PARTIAL','UNRESOLVED')
    ),
    CONSTRAINT ck_state_procurements_specification_present CHECK (length(specification) > 0),
    FOREIGN KEY(program_id) REFERENCES state_economic_programs (id) ON DELETE RESTRICT,
    FOREIGN KEY(government_id) REFERENCES state_governments (id) ON DELETE RESTRICT,
    FOREIGN KEY(requesting_institution_id) REFERENCES state_institutions (id) ON DELETE RESTRICT,
    FOREIGN KEY(department_id) REFERENCES state_departments (id) ON DELETE RESTRICT,
    FOREIGN KEY(supplier_identity_id) REFERENCES state_identities (id) ON DELETE RESTRICT,
    FOREIGN KEY(policy_id) REFERENCES state_economic_policies (id) ON DELETE RESTRICT,
    FOREIGN KEY(authorizing_identity_id) REFERENCES state_identities (id) ON DELETE RESTRICT,
    FOREIGN KEY(authorizing_position_id) REFERENCES state_positions (id) ON DELETE RESTRICT,
    FOREIGN KEY(decision_id) REFERENCES state_decisions (id) ON DELETE RESTRICT,
    FOREIGN KEY(expenditure_authorization_id) REFERENCES state_expenditure_authorizations (id) ON DELETE RESTRICT,
    FOREIGN KEY(operation_id) REFERENCES state_government_operations (id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS ix_state_procurements_program
    ON state_procurements (tenant_id, program_id, status);

-- الخطوة 13: القرارُ الاقتصاديّ (R9-N). سلسلةُ الإسناد **مكتوبةٌ لا مُستنتَجة**:
-- مبدأ · هوية · منصب · مؤسسة · حكومة · نطاق · مِنحة · تصنيف. وإن انكسرت حلقةٌ
-- فالتصنيفُ `PARTIAL` أو `UNRESOLVED` — يُقال ولا يُختلق. و`task_id` يشير إلى
-- مهمّةٍ حقيقية في `tasks` نفَّذتها النواةُ التنفيذية، فلا «نُفِّذ» بلا مهمّة.
CREATE TABLE IF NOT EXISTS state_economic_decisions (
    id VARCHAR NOT NULL,
    reference VARCHAR NOT NULL,
    operation VARCHAR NOT NULL,
    subject_kind VARCHAR NOT NULL,
    subject_id VARCHAR NOT NULL,
    government_id VARCHAR NOT NULL,
    institution_id VARCHAR NOT NULL,
    department_id VARCHAR,
    scope_level VARCHAR NOT NULL,
    issued_by VARCHAR NOT NULL,
    identity_id VARCHAR,
    official_id VARCHAR,
    position_id VARCHAR,
    grant_id VARCHAR,
    delegation_id VARCHAR,
    provenance_class VARCHAR NOT NULL,
    authority_reason TEXT DEFAULT '',
    status VARCHAR NOT NULL DEFAULT 'issued',
    task_id VARCHAR,
    transaction_reference VARCHAR,
    operation_id VARCHAR,
    correlation_id VARCHAR,
    audit_id VARCHAR,
    event_id VARCHAR,
    tenant_id VARCHAR NOT NULL DEFAULT 'default',
    created_at TIMESTAMP WITHOUT TIME ZONE,
    updated_at TIMESTAMP WITHOUT TIME ZONE,
    PRIMARY KEY (id),
    CONSTRAINT uq_state_economic_decisions_tenant_reference UNIQUE (tenant_id, reference),
    CONSTRAINT ck_state_economic_decisions_operation CHECK (
        operation IN (
            'economy.entity.register',
            'economy.program.create',
            'economy.policy.issue',
            'economy.policy.activate',
            'economy.revenue.register',
            'economy.expenditure.authorize',
            'economy.grant.authorize',
            'economy.subsidy.authorize',
            'economy.asset.register',
            'economy.liability.register',
            'economy.procurement.authorize'
        )
    ),
    CONSTRAINT ck_state_economic_decisions_subject_kind CHECK (
        subject_kind IN ('SECTOR','CATEGORY','PROGRAM','ENTITY','POLICY','REVENUE_SOURCE','EXPENDITURE','TRANSFER','ASSET','LIABILITY','PROCUREMENT')
    ),
    CONSTRAINT ck_state_economic_decisions_scope CHECK (
        scope_level IN ('FEDERAL','STATE','INSTITUTION','DEPARTMENT')
    ),
    CONSTRAINT ck_state_economic_decisions_provenance CHECK (
        provenance_class IN ('PROVEN','PARTIAL','UNRESOLVED')
    ),
    CONSTRAINT ck_state_economic_decisions_status CHECK (
        status IN ('issued','executed','failed')
    ),
    -- `PROVEN` يلزمه سلسلةٌ كاملة: هويةٌ ومسؤولٌ ومنصبٌ ومِنحة. فلا يُكتب
    -- «مُثبَت» على قرارٍ حلقتُه ناقصة.
    CONSTRAINT ck_state_economic_decisions_proven_needs_chain CHECK (
        provenance_class <> 'PROVEN'
        OR (
            identity_id IS NOT NULL
            AND official_id IS NOT NULL
            AND position_id IS NOT NULL
            AND grant_id IS NOT NULL
        )
    ),
    -- «نُفِّذ» يلزمه مهمّةٌ في النواة التنفيذية — لا مسارَ تنفيذٍ بديل.
    CONSTRAINT ck_state_economic_decisions_executed_needs_task CHECK (
        status <> 'executed' OR task_id IS NOT NULL
    ),
    CONSTRAINT ck_state_economic_decisions_department CHECK (
        scope_level <> 'DEPARTMENT' OR department_id IS NOT NULL
    ),
    FOREIGN KEY(government_id) REFERENCES state_governments (id) ON DELETE RESTRICT,
    FOREIGN KEY(institution_id) REFERENCES state_institutions (id) ON DELETE RESTRICT,
    FOREIGN KEY(department_id) REFERENCES state_departments (id) ON DELETE RESTRICT,
    FOREIGN KEY(identity_id) REFERENCES state_identities (id) ON DELETE RESTRICT,
    FOREIGN KEY(official_id) REFERENCES state_officials (id) ON DELETE RESTRICT,
    FOREIGN KEY(position_id) REFERENCES state_positions (id) ON DELETE RESTRICT,
    FOREIGN KEY(grant_id) REFERENCES state_authority_grants (id) ON DELETE RESTRICT,
    FOREIGN KEY(delegation_id) REFERENCES state_government_delegations (id) ON DELETE RESTRICT,
    FOREIGN KEY(task_id) REFERENCES tasks (id) ON DELETE RESTRICT,
    FOREIGN KEY(operation_id) REFERENCES state_government_operations (id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS ix_state_economic_decisions_subject
    ON state_economic_decisions (tenant_id, subject_kind, subject_id);

CREATE INDEX IF NOT EXISTS ix_state_economic_decisions_scope
    ON state_economic_decisions (tenant_id, government_id, scope_level, status);

CREATE INDEX IF NOT EXISTS ix_state_economic_decisions_task
    ON state_economic_decisions (task_id);

-- =============================================================================
-- ما تُثبته هذه الهجرة على PostgreSQL — رفضٌ حقيقيّ برمزٍ حقيقيّ:
--
--   -- مِنحةُ سلطةٍ بعمليةٍ اقتصادية ⇒ تُقبَل (المفردةُ وُسِّعت)
--   -- مِنحةُ سلطةٍ بعمليةٍ مُختَرعة ⇒ 23514 ck_state_authority_grants_operation
--   -- تفويضٌ بعمليةٍ اقتصادية ⇒ يُقبَل · وبعمليةٍ مُختَرعة ⇒ 23514
--   -- قطاعان بنفس (مستأجر، رمز) ⇒ 23505 uq_state_economic_sectors_tenant_code
--   -- قطاعٌ بحكومةٍ غير موجودة ⇒ 23503 على `government_id`
--   -- قطاعٌ بنطاق INSTITUTION ⇒ 23514 ck_state_economic_sectors_scope
--   -- فئتان بنفس (مستأجر، قطاع، رمز) ⇒ 23505 uq_state_economic_categories_sector_code
--   -- برنامجٌ نطاقُه DEPARTMENT بلا إدارة ⇒ 23514 ck_state_economic_programs_department
--   -- برنامجٌ بتصنيف إسنادٍ مُختَرع ⇒ 23514 ck_state_economic_programs_classification
--   -- كيانان اقتصاديّان بنفس الهوية ⇒ 23505 uq_state_public_economic_entities_identity
--   -- كيانٌ اقتصاديّ بلا هوية ⇒ 23502 NOT NULL على `identity_id`
--   -- سياسةٌ `active` بلا منصبٍ أو بلا `effective_from` أو بلا أثرِ تنفيذ
--        ⇒ 23514 ck_state_economic_policies_active_needs_provenance
--   -- سياسةٌ نافذةٌ تنتهي قبل أن تبدأ ⇒ 23514 ck_state_economic_policies_window
--   -- سياسةٌ «منقوضة» بلا طابع ⇒ 23514 ck_state_economic_policies_revoked_at
--   -- نسختان بنفس (مستأجر، رمز، نسخة) ⇒ 23505 uq_state_economic_policies_code_version
--   -- تعريفُ مؤشّرٍ بتصنيف قياسٍ `REAL` ⇒ 23514 ck_..._indicator_definitions_measurement
--   -- مصدرُ إيرادٍ بنوعٍ مُختَرع ⇒ 23514 ck_state_revenue_sources_kind
--   -- مصدرُ إيرادٍ بتحصيلٍ `REAL` ⇒ 23514 ck_state_revenue_sources_collection
--   -- إجازةُ إنفاقٍ بمبلغٍ صفر أو سالب ⇒ 23514 ck_state_expenditure_authorizations_amount
--   -- إجازةٌ `executed` بلا مرجعِ حركة ⇒ 23514 ck_state_expenditure_authorizations_executed
--   -- إجازةٌ `authorized` بمرجعِ حركة ⇒ 23514 ck_state_expenditure_authorizations_executed
--   -- إجازةٌ على تخصيصٍ غير موجود ⇒ 23503 على `allocation_id`
--   -- إجازتان بنفس (مستأجر، مرجع) ⇒ 23505 uq_state_expenditure_authorizations_tenant_reference
--   -- أصلٌ بملكيةٍ خارجية `REGISTERED` ⇒ 23514 ck_state_public_assets_external_ownership
--   -- أصلٌ بصفةِ تسجيلٍ أخرى ⇒ 23514 ck_state_public_assets_registration
--   -- أصلٌ بقيمةٍ بلا عملة ⇒ 23514 ck_state_public_assets_value_currency
--   -- التزامٌ بلا دائنٍ ⇒ 23502 NOT NULL على `creditor_identity_id`
--   -- التزامٌ بدائنٍ غير موجود ⇒ 23503 على `creditor_identity_id`
--   -- التزامٌ بنفاذٍ خارجيّ `ENFORCEABLE` ⇒ 23514 ck_state_public_liabilities_enforceability
--   -- تحويلٌ بنوعٍ غير `GRANT`/`SUBSIDY` ⇒ 23514 ck_state_economic_transfers_kind
--   -- تحويلٌ `executed` بلا مرجعِ حركة ⇒ 23514 ck_state_economic_transfers_executed
--   -- تحويلٌ بمستفيدٍ غير موجود ⇒ 23503 على `beneficiary_identity_id`
--   -- مشترياتٌ بواجهةٍ خارجية ⇒ 23514 ck_state_procurements_backend
--   -- مشترياتٌ بسوقٍ خارجيّ `AVAILABLE` ⇒ 23514 ck_state_procurements_external_market
--   -- مشترياتٌ بلا مزوّدٍ بهوية ⇒ 23502 NOT NULL على `supplier_identity_id`
--   -- قرارٌ `PROVEN` بلا منصبٍ أو مِنحة ⇒ 23514 ck_state_economic_decisions_proven_needs_chain
--   -- قرارٌ `executed` بلا مهمّة ⇒ 23514 ck_state_economic_decisions_executed_needs_task
--   -- قرارٌ بمهمّةٍ غير موجودة ⇒ 23503 على `task_id`
--   -- قرارٌ بعمليةٍ خزانية (لا اقتصادية) ⇒ 23514 ck_state_economic_decisions_operation
-- =============================================================================
