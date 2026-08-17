-- =============================================================================
-- AMOS-Federation Migration 008 — السجل الوطني والهوية الكانونية (R7-C)
-- الهدف: هويةٌ كانونية تُربط بها الجلسة والوكيل والمنصب، وسلطةٌ على هدفٍ مُسمّى
-- النطاق: federal/executive/services
-- المالك: federal/executive/services
-- تاريخ الإنشاء: 2026-08-17
-- =============================================================================
--
-- قابلة لإعادة التطبيق: كل جملة `IF NOT EXISTS`. لا `DROP` ولا تعديل عمود قائم،
-- فتطبيقها مرتين لا يفقد صفًّا ولا يفشل.
--
-- ## لا `ALTER TABLE` على جدولٍ قائم — بقصد
--
-- كان أمامنا طريقان لربط الهوية بالقرار والحركة: عمودٌ جديد على `state_decisions`
-- و`state_transactions`، أو جدولا إسنادٍ مستقلّان. اختيرَ الثاني لسببين مقيسين:
--
-- 1. `Base.metadata.create_all` **لا تُضيف عمودًا إلى جدول موجود**. فلو أُضيف
--    عمود لاحتاجت كل نشرةٍ قائمة `ALTER` يدويًّا — وهو ما دفعناه في R6.1 مع
--    `security_sessions.tenant_id` ولا نكرّره طوعًا.
-- 2. الإسناد سجلٌّ مستقلّ: قرارٌ واحد له صفُّ إسنادٍ واحد، وحركةٌ واحدة لها صفُّ
--    سلطةٍ واحد، ومفتاحاهما الأوّليّان هما `decision_id` و`transaction_id` نفسها.
--    فلا يمكن أن يوجد إسنادان متضاربان لقرارٍ واحد.
--
-- الأثر: تطبيق هذه الهجرة على قاعدةٍ فيها قرارات وحركات لا يغيّر صفًّا واحدًا منها،
-- والقرارات السابقة تبقى بلا صفِّ إسناد — وهذا **هو** الجواب الصادق: لا يُختلق لها
-- إسنادٌ بأثرٍ رجعيّ. تُقرأ ناقصة الإسناد كما هي.
--
-- تنبيه على SQLite: `PRAGMA foreign_keys=ON` لازم لكل اتصال وإلا لم تُفرض
-- المفاتيح. يفرضه `common/database.py::_enforce_sqlite_foreign_keys`. PostgreSQL
-- يفرضها دائمًا. والفهرس الفريد الجزئي (`WHERE status = 'active'`) مدعومٌ في
-- الاثنين — فُحص على PostgreSQL 18 وعلى SQLite معًا.
-- =============================================================================

BEGIN;

-- الخطوة 1: الهوية الكانونية. لا عمود اسمٍ يُعرِّف: `label` للعرض ولا قيد فريد
-- عليه بقصد، والتعريف بالمعرّف وبالروابط في الخطوتين 2 و3.
CREATE TABLE IF NOT EXISTS state_identities (
    id             VARCHAR PRIMARY KEY,
    identity_type  VARCHAR NOT NULL,
    status         VARCHAR NOT NULL DEFAULT 'active',
    label          VARCHAR DEFAULT '',
    status_reason  TEXT    DEFAULT '',
    tenant_id      VARCHAR NOT NULL DEFAULT 'default',
    created_by     VARCHAR NOT NULL,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_state_identities_type CHECK (
        identity_type IN ('PERSON','AGENT','ORGANIZATION','INSTITUTION','SYSTEM')
    ),
    -- `unresolved` حالةٌ صريحة: هويةٌ أُنشئت ولم يثبت مرجعها. تُقال ولا تُدمَج.
    CONSTRAINT ck_state_identities_status CHECK (
        status IN ('active','suspended','retired','unresolved')
    )
);

CREATE INDEX IF NOT EXISTS ix_state_identities_tenant_type
    ON state_identities (tenant_id, identity_type, status);

-- الخطوة 2: المبدأ ← الهوية. `principal_id` هو `security_sessions.username` نفسه،
-- ولا مفتاح أجنبي إليه لأن `security_sessions` يسكن خريطة تعريف منفصلة
-- (`SecurityBase`) — يُقال ولا يُموَّه. والمفروض فعلًا: مبدأٌ واحد لا يحمل هويتين.
CREATE TABLE IF NOT EXISTS state_identity_principals (
    id              VARCHAR PRIMARY KEY,
    principal_id    VARCHAR NOT NULL,
    identity_id     VARCHAR NOT NULL REFERENCES state_identities(id) ON DELETE RESTRICT,
    binding_source  VARCHAR NOT NULL DEFAULT 'ADMIN',
    tenant_id       VARCHAR NOT NULL DEFAULT 'default',
    linked_by       VARCHAR NOT NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_state_identity_principals_tenant_principal UNIQUE (tenant_id, principal_id)
);

CREATE INDEX IF NOT EXISTS ix_state_identity_principals_identity
    ON state_identity_principals (identity_id);

-- الخطوة 3: الوكيل ← الهوية. الوكيل **لا يُدمَج** في جدول الهوية: `agents` يبقى
-- سجلّ R4 الكانوني بدورة حياته وصلاحياته. العلاقة واحدٌ لواحد من الطرفين.
CREATE TABLE IF NOT EXISTS state_identity_agents (
    id           VARCHAR PRIMARY KEY,
    agent_id     VARCHAR NOT NULL REFERENCES agents(id) ON DELETE RESTRICT,
    identity_id  VARCHAR NOT NULL REFERENCES state_identities(id) ON DELETE RESTRICT,
    tenant_id    VARCHAR NOT NULL DEFAULT 'default',
    linked_by    VARCHAR NOT NULL,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_state_identity_agents_agent UNIQUE (agent_id),
    CONSTRAINT uq_state_identity_agents_identity UNIQUE (identity_id)
);

-- الخطوة 4: المنصب — مصدر السلطة المؤسسية، مستقلٌّ عن شاغله. وجودُه لا يعني وجود
-- شاغل، وعزلُ شاغله لا يُلغيه.
CREATE TABLE IF NOT EXISTS state_positions (
    id               VARCHAR PRIMARY KEY,
    code             VARCHAR NOT NULL,
    title            VARCHAR NOT NULL,
    institution_id   VARCHAR NOT NULL REFERENCES state_institutions(id) ON DELETE RESTRICT,
    department_id    VARCHAR REFERENCES state_departments(id) ON DELETE RESTRICT,
    authority_scope  VARCHAR NOT NULL,
    status           VARCHAR NOT NULL DEFAULT 'active',
    mandate          TEXT    DEFAULT '',
    tenant_id        VARCHAR NOT NULL DEFAULT 'default',
    created_by       VARCHAR NOT NULL,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_state_positions_institution_code UNIQUE (institution_id, code),
    -- النطاقات **ليست سلّمًا**: لا واحدٌ منها يُرقّي إلى آخر تلقائيًّا (R7-C7).
    CONSTRAINT ck_state_positions_scope CHECK (
        authority_scope IN ('FEDERAL','STATE','INSTITUTION','DEPARTMENT')
    ),
    CONSTRAINT ck_state_positions_status CHECK (status IN ('active','suspended','abolished')),
    -- نطاق الإدارة يلزمه إدارة، وما فوقه لا يحملها — قيدٌ في القاعدة لا تعليق،
    -- فلا منصبٌ «إداريّ» بلا إدارة يمرّ من كاتبٍ مباشر في الجدول.
    CONSTRAINT ck_state_positions_department_scope CHECK (
        (authority_scope = 'DEPARTMENT' AND department_id IS NOT NULL)
        OR (authority_scope <> 'DEPARTMENT' AND department_id IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS ix_state_positions_institution
    ON state_positions (institution_id, status);

-- الخطوة 5: تقليد مسؤولٍ منصبًا، ونسبته إلى هويته. ثلاث إشارات في صفٍّ واحد،
-- فصار «الهوية X تشغل المنصب Y في المؤسسة Z» صفًّا مقروءًا لا استنتاجًا.
CREATE TABLE IF NOT EXISTS state_official_positions (
    id                 VARCHAR PRIMARY KEY,
    official_id        VARCHAR NOT NULL REFERENCES state_officials(id) ON DELETE RESTRICT,
    identity_id        VARCHAR NOT NULL REFERENCES state_identities(id) ON DELETE RESTRICT,
    position_id        VARCHAR NOT NULL REFERENCES state_positions(id) ON DELETE RESTRICT,
    status             VARCHAR NOT NULL DEFAULT 'active',
    assigned_by        VARCHAR NOT NULL,
    assigned_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    revoked_at         TIMESTAMP,
    revocation_reason  TEXT DEFAULT '',
    tenant_id          VARCHAR NOT NULL DEFAULT 'default',
    CONSTRAINT ck_state_official_positions_status CHECK (status IN ('active','revoked')),
    CONSTRAINT ck_state_official_positions_revoked_at CHECK (
        (status = 'revoked' AND revoked_at IS NOT NULL)
        OR (status <> 'revoked' AND revoked_at IS NULL)
    )
);

-- فهرسٌ فريدٌ **جزئي**: تقليدٌ نشطٌ واحد لكل (مسؤول، منصب)، والصفوف المعزولة تبقى
-- تاريخًا. القيد الكامل كان سيمنع إعادة التقليد بعد العزل — فيُحذف التاريخ ليمرّ
-- التقليد، وذلك ما لا نفعله.
CREATE UNIQUE INDEX IF NOT EXISTS uq_state_official_positions_active
    ON state_official_positions (official_id, position_id) WHERE status = 'active';

CREATE INDEX IF NOT EXISTS ix_state_official_positions_identity
    ON state_official_positions (identity_id, status);
CREATE INDEX IF NOT EXISTS ix_state_official_positions_position
    ON state_official_positions (position_id, status);

-- الخطوة 6: مِنحة السلطة — «المنصب P يملك العملية O في النطاق S على الهدف T».
-- والهدف مفاتيح أجنبية حقيقية، فلا مِنحة على موازنةٍ أو حسابٍ لا وجود له.
--
-- `operation` أسماء عمليات مفحوصةٌ **أصلًا** في `state_treasury/authorization.py`
-- و`government_services` — لا صلاحيات جديدة تُضاف إلى `security_roles`. الصلاحية
-- تقول «من أيّ طبقة أنت»، والمِنحة تقول «على أيّ مال بالتحديد».
CREATE TABLE IF NOT EXISTS state_authority_grants (
    id                 VARCHAR PRIMARY KEY,
    position_id        VARCHAR NOT NULL REFERENCES state_positions(id) ON DELETE RESTRICT,
    operation          VARCHAR NOT NULL,
    scope              VARCHAR NOT NULL,
    institution_id     VARCHAR REFERENCES state_institutions(id) ON DELETE RESTRICT,
    department_id      VARCHAR REFERENCES state_departments(id) ON DELETE RESTRICT,
    budget_id          VARCHAR REFERENCES state_budgets(id) ON DELETE RESTRICT,
    account_id         VARCHAR REFERENCES state_accounts(id) ON DELETE RESTRICT,
    max_amount         VARCHAR,
    status             VARCHAR NOT NULL DEFAULT 'active',
    granted_by         VARCHAR NOT NULL,
    granted_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    revoked_at         TIMESTAMP,
    revocation_reason  TEXT DEFAULT '',
    tenant_id          VARCHAR NOT NULL DEFAULT 'default',
    CONSTRAINT ck_state_authority_grants_operation CHECK (
        operation IN (
            'treasury.funding.post',
            'treasury.allocation.create',
            'treasury.disbursement.post',
            'treasury.transaction.reverse',
            'gov.case.decide'
        )
    ),
    CONSTRAINT ck_state_authority_grants_scope CHECK (
        scope IN ('FEDERAL','STATE','INSTITUTION','DEPARTMENT')
    ),
    CONSTRAINT ck_state_authority_grants_status CHECK (status IN ('active','revoked')),
    -- كل نطاق يلزمه هدفه: بلا هدفٍ لا مِنحة (fail closed في المخطَّط نفسه).
    CONSTRAINT ck_state_authority_grants_target CHECK (
        (scope = 'DEPARTMENT' AND department_id IS NOT NULL)
        OR (scope IN ('INSTITUTION','STATE','FEDERAL') AND institution_id IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS ix_state_authority_grants_position
    ON state_authority_grants (position_id, status, operation);
CREATE INDEX IF NOT EXISTS ix_state_authority_grants_budget
    ON state_authority_grants (budget_id, status);

-- الخطوة 7: إسناد القرار. مفتاحه الأوّليّ هو `decision_id` نفسه، فلا إسنادان
-- متضاربان لقرارٍ واحد. والقرارات السابقة لهذه الهجرة تبقى بلا صفٍّ هنا — تُقرأ
-- ناقصة الإسناد ولا يُختلق لها إسنادٌ بأثرٍ رجعيّ.
CREATE TABLE IF NOT EXISTS state_decision_provenance (
    decision_id       VARCHAR PRIMARY KEY REFERENCES state_decisions(id) ON DELETE RESTRICT,
    principal_id      VARCHAR NOT NULL,
    identity_id       VARCHAR REFERENCES state_identities(id) ON DELETE RESTRICT,
    official_id       VARCHAR REFERENCES state_officials(id) ON DELETE RESTRICT,
    position_id       VARCHAR REFERENCES state_positions(id) ON DELETE RESTRICT,
    institution_id    VARCHAR NOT NULL REFERENCES state_institutions(id) ON DELETE RESTRICT,
    provenance_class  VARCHAR NOT NULL,
    reason            TEXT DEFAULT '',
    session_id        VARCHAR,
    correlation_id    VARCHAR,
    tenant_id         VARCHAR NOT NULL DEFAULT 'default',
    recorded_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    -- التصنيف لا يُرفَع بلا دليل: `PROVEN` تلزمه الحلقات كلها صفوفًا مقروءة.
    CONSTRAINT ck_state_decision_provenance_class CHECK (
        provenance_class IN ('PROVEN','PARTIAL','UNRESOLVED')
    )
);

CREATE INDEX IF NOT EXISTS ix_state_decision_provenance_identity
    ON state_decision_provenance (identity_id);

-- الخطوة 8: سلطة الحركة المالية. «بأيّ سلطةٍ صُرِف هذا المال؟» يصير استعلامًا:
-- `grant_id` يشير إلى المِنحة التي أجازتها بعينها. والحركة التي مرّت بصلاحية دورٍ
-- سيادية بلا مِنحة تُسجَّل أيضًا مُصنَّفةً `PARTIAL` — لا تُخفى ولا تُرفَّع.
CREATE TABLE IF NOT EXISTS state_transaction_authority (
    transaction_id   VARCHAR PRIMARY KEY REFERENCES state_transactions(id) ON DELETE RESTRICT,
    principal_id     VARCHAR NOT NULL,
    identity_id      VARCHAR REFERENCES state_identities(id) ON DELETE RESTRICT,
    official_id      VARCHAR NOT NULL REFERENCES state_officials(id) ON DELETE RESTRICT,
    position_id      VARCHAR REFERENCES state_positions(id) ON DELETE RESTRICT,
    grant_id         VARCHAR REFERENCES state_authority_grants(id) ON DELETE RESTRICT,
    operation        VARCHAR NOT NULL,
    scope            VARCHAR,
    authority_class  VARCHAR NOT NULL,
    reason           TEXT DEFAULT '',
    targets          JSON,
    session_id       VARCHAR,
    correlation_id   VARCHAR,
    tenant_id        VARCHAR NOT NULL DEFAULT 'default',
    recorded_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_state_transaction_authority_class CHECK (
        authority_class IN ('PROVEN','PARTIAL','UNRESOLVED')
    ),
    CONSTRAINT ck_state_transaction_authority_operation CHECK (
        operation IN (
            'treasury.funding.post',
            'treasury.allocation.create',
            'treasury.disbursement.post',
            'treasury.transaction.reverse',
            'gov.case.decide'
        )
    )
);

CREATE INDEX IF NOT EXISTS ix_state_transaction_authority_grant
    ON state_transaction_authority (grant_id);
CREATE INDEX IF NOT EXISTS ix_state_transaction_authority_identity
    ON state_transaction_authority (identity_id);

COMMIT;

-- =============================================================================
-- تحقّق يدوي (يُنفَّذ على PostgreSQL حقيقي، لا SQLite). كل جملة فاشلة تُجهض
-- المعاملة، فتُنفَّذ واحدة في كل نداء ثم تُحذف صفوف التحقّق كلّها بعدها:
--
--   -- نوع هوية خارج المفردة ⇒ 23514 ck_state_identities_type
--   INSERT INTO state_identities (id, identity_type, created_by)
--   VALUES ('idn-x','CITIZEN','p');
--
--   -- حالة هوية خارج المفردة ⇒ 23514 ck_state_identities_status
--   -- مبدأٌ واحد بهويتين في نفس المستأجر ⇒ 23505
--       uq_state_identity_principals_tenant_principal
--   -- وكيلٌ واحد بهويتين ⇒ 23505 uq_state_identity_agents_agent
--   -- هويةٌ واحدة لوكيلين ⇒ 23505 uq_state_identity_agents_identity
--   -- ربطُ هوية غير موجودة ⇒ 23503 على `identity_id`
--   -- ربطُ وكيل غير موجود ⇒ 23503 على `agent_id`
--   -- منصبٌ بنطاق DEPARTMENT بلا إدارة ⇒ 23514 ck_state_positions_department_scope
--   -- منصبٌ بنطاق FEDERAL مع إدارة ⇒ 23514 ck_state_positions_department_scope
--   -- منصبان بنفس (مؤسسة، رمز) ⇒ 23505 uq_state_positions_institution_code
--   -- تقليدان نشطان لنفس (مسؤول، منصب) ⇒ 23505 uq_state_official_positions_active
--   -- تقليدٌ معزول بلا `revoked_at` ⇒ 23514 ck_state_official_positions_revoked_at
--   -- مِنحةٌ بعملية مُختَرعة ⇒ 23514 ck_state_authority_grants_operation
--   -- مِنحةٌ بنطاق INSTITUTION بلا مؤسسة ⇒ 23514 ck_state_authority_grants_target
--   -- مِنحةٌ على موازنة غير موجودة ⇒ 23503 على `budget_id`
--   -- إسنادُ قرارٍ بتصنيف مُختَرع ⇒ 23514 ck_state_decision_provenance_class
--   -- إسنادان لقرارٍ واحد ⇒ 23505 على المفتاح الأوّليّ `decision_id`
--   -- سلطةُ حركةٍ بلا مسؤول ⇒ 23502 NOT NULL على `official_id`
-- =============================================================================
