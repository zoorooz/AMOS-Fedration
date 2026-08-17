-- =============================================================================
-- AMOS-Federation Migration 007 — الخزانة الفدرالية ودفتر المال العام (R7-B)
-- الهدف: جداول الخزانة والحساب والموازنة والتخصيص والحركة والقيد، بمفاتيح مفروضة.
-- النطاق: federal/executive/services
-- المالك: federal/executive/services
-- تاريخ الإنشاء: 2026-08-17
-- =============================================================================
--
-- قابلة لإعادة التطبيق: كل جملة `IF NOT EXISTS`، لا `DROP` ولا تعديل عمود قائم.
-- تعتمد على 005 (`state_institutions`/`state_departments`/`state_officials`)
-- وعلى 006 (`state_decisions`) وعلى 001/004 (`tasks`). تطبيقها قبلها يفشل بمفتاح
-- مفقود — وهذا مقصود: لا مال عامّ بلا مؤسسة ولا منصب.
--
-- === المال: NUMERIC(20,4) لا double precision ===
--
-- خزانة المرحلة 10 (`treasury_transactions`/`treasury_budgets`/`treasury_reports`)
-- تستعمل `double precision`، وهي دفتر حوافز للوكلاء لا مالٌ عامّ. هذه الجداول
-- (`state_*`) هي المصدر المعتمد للمال العام، وكل مبلغ فيها `NUMERIC(20,4)`
-- يُقرأ ويُكتب `Decimal`. والقديم لم يُوحَّد ولا يُدَّعى توحيده (دَين مُعلَن).
--
-- === لا رصيد مخزَّن ===
--
-- لا عمود `balance` في `state_accounts`، ولا `allocated`/`spent`/`remaining` في
-- `state_budgets`. كلّها مشتقّة من `state_ledger_entries` و`state_allocations`
-- عند كل قراءة، فلا عدّاد يتباعد عن الدفتر بصمت.
--
-- === ما لا يستطيع المخطَّط فرضه — يُقال لا يُخفى ===
--
--  * «مجموع مَدين الحركة = مجموع دائنها»: `CHECK` لا يرى صفوف جدول تابع.
--    مفروضٌ في `service.py::_post` (بوّابة كتابةٍ واحدة)، ومفحوصٌ باختبارٍ
--    يقرأ القاعدة بعد الكتابة.
--  * «لا صرف يتجاوز التخصيص» و«لا تخصيص يتجاوز الموازنة»: مجاميع فوق جداول
--    أخرى. مفروضة في الخدمة، وغير محميّة من التنافس (لا `SELECT … FOR UPDATE`).
--  * «عملة القيد = عملة حسابه»: قيدٌ عبر جدولين. مفروضٌ في الخدمة.
--
-- تنبيه على SQLite: `PRAGMA foreign_keys=ON` لازم لكل اتصال، ويفرضه
-- `common/database.py::_enforce_sqlite_foreign_keys`. PostgreSQL يفرضها دائمًا.
-- =============================================================================

BEGIN;

-- الخطوة 1: الخزانة. وعاءٌ بعملة واحدة، وقد تتبع مؤسسة (وزارة مالية) أو لا.
CREATE TABLE IF NOT EXISTS state_treasuries (
    id              VARCHAR PRIMARY KEY,
    code            VARCHAR NOT NULL,
    name            VARCHAR NOT NULL,
    institution_id  VARCHAR REFERENCES state_institutions(id) ON DELETE RESTRICT,
    currency        VARCHAR NOT NULL,
    status          VARCHAR NOT NULL DEFAULT 'active',
    tenant_id       VARCHAR NOT NULL DEFAULT 'default',
    established_by  VARCHAR NOT NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_state_treasuries_tenant_code UNIQUE (tenant_id, code),
    CONSTRAINT ck_state_treasuries_status CHECK (
        status IN ('active','frozen','closed')
    ),
    CONSTRAINT ck_state_treasuries_currency CHECK (
        length(currency) = 3 AND currency = upper(currency)
    )
);

-- الخطوة 2: الحسابات. `kind` يحدّد اتجاه الرصيد الطبيعي، ولا عمود رصيد هنا.
CREATE TABLE IF NOT EXISTS state_accounts (
    id              VARCHAR PRIMARY KEY,
    code            VARCHAR NOT NULL,
    name            VARCHAR NOT NULL,
    treasury_id     VARCHAR NOT NULL REFERENCES state_treasuries(id) ON DELETE RESTRICT,
    institution_id  VARCHAR REFERENCES state_institutions(id) ON DELETE RESTRICT,
    department_id   VARCHAR REFERENCES state_departments(id) ON DELETE RESTRICT,
    kind            VARCHAR NOT NULL,
    currency        VARCHAR NOT NULL,
    status          VARCHAR NOT NULL DEFAULT 'open',
    tenant_id       VARCHAR NOT NULL DEFAULT 'default',
    opened_by       VARCHAR NOT NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_state_accounts_treasury_code UNIQUE (treasury_id, code),
    CONSTRAINT ck_state_accounts_kind CHECK (
        kind IN ('cash','reserve','revenue','expense')
    ),
    CONSTRAINT ck_state_accounts_status CHECK (
        status IN ('open','frozen','closed')
    ),
    CONSTRAINT ck_state_accounts_currency CHECK (
        length(currency) = 3 AND currency = upper(currency)
    )
);

CREATE INDEX IF NOT EXISTS ix_state_accounts_treasury
    ON state_accounts (treasury_id, kind);

-- الخطوة 3: الموازنات. لمؤسسة إلزامًا، ولفترة، وبحدٍّ أعلى موجب.
-- `uq_state_budgets_institution_period_code` يمنع موازنتين بنفس الرمز لنفس
-- المؤسسة في نفس الفترة — وهو القيد الذي يحمي «فترة الموازنة» من التكرار.
CREATE TABLE IF NOT EXISTS state_budgets (
    id              VARCHAR PRIMARY KEY,
    code            VARCHAR NOT NULL,
    treasury_id     VARCHAR NOT NULL REFERENCES state_treasuries(id) ON DELETE RESTRICT,
    institution_id  VARCHAR NOT NULL REFERENCES state_institutions(id) ON DELETE RESTRICT,
    department_id   VARCHAR REFERENCES state_departments(id) ON DELETE RESTRICT,
    period          VARCHAR NOT NULL,
    currency        VARCHAR NOT NULL,
    limit_amount    NUMERIC(20,4) NOT NULL,
    status          VARCHAR NOT NULL DEFAULT 'open',
    tenant_id       VARCHAR NOT NULL DEFAULT 'default',
    created_by      VARCHAR NOT NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_state_budgets_tenant_code UNIQUE (tenant_id, code),
    CONSTRAINT uq_state_budgets_institution_period_code UNIQUE (institution_id, period, code),
    CONSTRAINT ck_state_budgets_status CHECK (
        status IN ('draft','open','closed')
    ),
    CONSTRAINT ck_state_budgets_currency CHECK (
        length(currency) = 3 AND currency = upper(currency)
    ),
    CONSTRAINT ck_state_budgets_limit CHECK (
        limit_amount > 0 AND limit_amount <= 900000000000
    )
);

CREATE INDEX IF NOT EXISTS ix_state_budgets_institution_period
    ON state_budgets (institution_id, period);

-- الخطوة 4: التخصيصات. إذنُ صرفٍ بحدٍّ من موازنة إلى حساب، وقد يأذن به قرار.
CREATE TABLE IF NOT EXISTS state_allocations (
    id           VARCHAR PRIMARY KEY,
    budget_id    VARCHAR NOT NULL REFERENCES state_budgets(id) ON DELETE RESTRICT,
    account_id   VARCHAR NOT NULL REFERENCES state_accounts(id) ON DELETE RESTRICT,
    purpose      VARCHAR NOT NULL,
    amount       NUMERIC(20,4) NOT NULL,
    currency     VARCHAR NOT NULL,
    status       VARCHAR NOT NULL DEFAULT 'active',
    decision_id  VARCHAR REFERENCES state_decisions(id) ON DELETE RESTRICT,
    tenant_id    VARCHAR NOT NULL DEFAULT 'default',
    created_by   VARCHAR NOT NULL,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_state_allocations_status CHECK (
        status IN ('active','revoked')
    ),
    CONSTRAINT ck_state_allocations_currency CHECK (
        length(currency) = 3 AND currency = upper(currency)
    ),
    CONSTRAINT ck_state_allocations_amount CHECK (
        amount > 0 AND amount <= 900000000000
    )
);

CREATE INDEX IF NOT EXISTS ix_state_allocations_budget
    ON state_allocations (budget_id, status);

-- الخطوة 5: الحركات — إضافة فقط. `official_id NOT NULL`: لا مال عامّ يتحرّك بلا
-- منصبٍ مسؤول. و`reverses_transaction_id` فريد: عكسٌ واحد لكل حركة لا أكثر.
-- و`uq_state_transactions_tenant_idempotency` هو ما يجعل عدم التكرار قيدًا في
-- القاعدة لا فحصًا في الذاكرة: تنافُس طلبين بنفس المفتاح يرفضه القيد.
-- ملاحظة على NULL في القيد الفريد: NULL ≠ NULL في SQL، فالحركات بلا مفتاح
-- عدم تكرار لا تتعارض — وهو المقصود.
CREATE TABLE IF NOT EXISTS state_transactions (
    id                       VARCHAR PRIMARY KEY,
    reference                VARCHAR NOT NULL,
    treasury_id              VARCHAR NOT NULL REFERENCES state_treasuries(id) ON DELETE RESTRICT,
    kind                     VARCHAR NOT NULL,
    status                   VARCHAR NOT NULL DEFAULT 'posted',
    amount                   NUMERIC(20,4) NOT NULL,
    currency                 VARCHAR NOT NULL,
    purpose                  TEXT    NOT NULL,
    budget_id                VARCHAR REFERENCES state_budgets(id) ON DELETE RESTRICT,
    allocation_id            VARCHAR REFERENCES state_allocations(id) ON DELETE RESTRICT,
    institution_id           VARCHAR REFERENCES state_institutions(id) ON DELETE RESTRICT,
    task_id                  VARCHAR REFERENCES tasks(id) ON DELETE RESTRICT,
    decision_id              VARCHAR REFERENCES state_decisions(id) ON DELETE RESTRICT,
    official_id              VARCHAR NOT NULL REFERENCES state_officials(id) ON DELETE RESTRICT,
    posted_by                VARCHAR NOT NULL,
    reverses_transaction_id  VARCHAR UNIQUE
                                 REFERENCES state_transactions(id) ON DELETE RESTRICT,
    idempotency_key          VARCHAR,
    correlation_id           VARCHAR,
    tenant_id                VARCHAR NOT NULL DEFAULT 'default',
    created_at               TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_state_transactions_tenant_reference UNIQUE (tenant_id, reference),
    CONSTRAINT uq_state_transactions_tenant_idempotency UNIQUE (tenant_id, idempotency_key),
    CONSTRAINT ck_state_transactions_kind CHECK (
        kind IN ('funding','disbursement','transfer','reversal')
    ),
    CONSTRAINT ck_state_transactions_status CHECK (
        status IN ('posted','reversed')
    ),
    CONSTRAINT ck_state_transactions_currency CHECK (
        length(currency) = 3 AND currency = upper(currency)
    ),
    CONSTRAINT ck_state_transactions_amount CHECK (
        amount > 0 AND amount <= 900000000000
    ),
    CONSTRAINT ck_state_transactions_purpose_present CHECK (length(purpose) > 0)
);

CREATE INDEX IF NOT EXISTS ix_state_transactions_allocation
    ON state_transactions (allocation_id, status);

CREATE INDEX IF NOT EXISTS ix_state_transactions_budget
    ON state_transactions (budget_id, status);

CREATE INDEX IF NOT EXISTS ix_state_transactions_treasury
    ON state_transactions (treasury_id, created_at);

-- الخطوة 6: القيود — طرفا كل حركة. لا يُعدَّل ولا يُحذف صفٌّ منها.
CREATE TABLE IF NOT EXISTS state_ledger_entries (
    id              VARCHAR PRIMARY KEY,
    transaction_id  VARCHAR NOT NULL REFERENCES state_transactions(id) ON DELETE RESTRICT,
    account_id      VARCHAR NOT NULL REFERENCES state_accounts(id) ON DELETE RESTRICT,
    direction       VARCHAR NOT NULL,
    amount          NUMERIC(20,4) NOT NULL,
    currency        VARCHAR NOT NULL,
    tenant_id       VARCHAR NOT NULL DEFAULT 'default',
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_state_ledger_entries_direction CHECK (
        direction IN ('debit','credit')
    ),
    CONSTRAINT ck_state_ledger_entries_currency CHECK (
        length(currency) = 3 AND currency = upper(currency)
    ),
    CONSTRAINT ck_state_ledger_entries_amount CHECK (
        amount > 0 AND amount <= 900000000000
    )
);

CREATE INDEX IF NOT EXISTS ix_state_ledger_entries_account
    ON state_ledger_entries (account_id, direction);

CREATE INDEX IF NOT EXISTS ix_state_ledger_entries_transaction
    ON state_ledger_entries (transaction_id);

COMMIT;

-- =============================================================================
-- تحقّق يدوي (يُنفَّذ على PostgreSQL حقيقي، لا SQLite). كل جملة فاشلة تُجهض
-- المعاملة، فتُنفَّذ واحدة في كل نداء ثم تُحذف صفوف التحقّق كلّها بعدها:
--
--   -- مبلغ سالب أو صفر ⇒ 23514 ck_state_transactions_amount
--   INSERT INTO state_transactions (id, reference, treasury_id, kind, amount,
--       currency, purpose, official_id, posted_by, tenant_id)
--   VALUES ('t-neg','R-NEG','<tre>','funding',-5,'SAR','x','<off>','p','default');
--
--   -- عملة بأربعة أحرف أو بحرف صغير ⇒ 23514 ck_state_transactions_currency
--   -- نوع حركة خارج المفردة ⇒ 23514 ck_state_transactions_kind
--   -- مرجع مكرَّر في نفس المستأجر ⇒ 23505 uq_state_transactions_tenant_reference
--   -- نفس `idempotency_key` مرتين ⇒ 23505 uq_state_transactions_tenant_idempotency
--   -- عكسٌ ثانٍ لنفس الحركة ⇒ 23505 على `reverses_transaction_id`
--   -- حركة بمنصب غير موجود ⇒ 23503 على `official_id`
--   -- حركة بمهمّة غير موجودة ⇒ 23503 على `task_id`
--   -- اتجاه قيد غير 'debit'/'credit' ⇒ 23514 ck_state_ledger_entries_direction
--   -- حدّ موازنة صفر ⇒ 23514 ck_state_budgets_limit
--   -- موازنتان بنفس (مؤسسة، فترة، رمز) ⇒ 23505
--       uq_state_budgets_institution_period_code
--   -- حذف حساب له قيد ⇒ 23503 RESTRICT
-- =============================================================================
