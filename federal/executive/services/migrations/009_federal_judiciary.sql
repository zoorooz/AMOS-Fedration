-- =============================================================================
-- AMOS-Federation — الهجرة 009: القضاء الفدرالي (R7-D14)
-- الهدف: تسعةُ جداولٍ جديدة بقيودٍ مفروضة — بلا ALTER ولا DROP ولا DELETE
-- المالك: federal/executive/services
-- تاريخ الإنشاء: 2026-08-17
--
-- ## لماذا CREATE TABLE فقط
--
-- `Base.metadata.create_all` لا تُضيف عمودًا إلى جدولٍ موجود، وتاريخُ الهجرات
-- 001…008 قائمٌ ولا يُعاد كتابته الآن. فكل ما تضيفه R7-D جداولٌ جديدة بحتة:
-- تطبيقُها على قاعدةٍ فيها صفوفٌ لا يحتاج `ALTER` ولا يفقد صفًّا، ولا تُلمَس
-- `court_cases` القديمة ولا `state_cases` الإدارية.
--
-- ## الترتيب مقصود
--
-- من الأصل إلى الفرع: المحكمة قبل القاضي، والقاضي قبل القضية (الإسنادُ يشير
-- إليه)، والقضية قبل الأطراف والأدلّة والإجراءات، والحكم قبل تنفيذه. فكل مفتاحٍ
-- أجنبيّ يجد هدفَه موجودًا عند إنشائه.
--
-- ## المفاتيح الأجنبية إلى ما هو قائم
--
--   state_courts.institution_id            → state_institutions.id   (R7-A)
--   state_court_judges.official_id         → state_officials.id      (R7-A)
--   state_court_judges.position_id         → state_positions.id      (R7-C)
--   state_court_judges.identity_id         → state_identities.id     (R7-C)
--   state_case_parties.identity_id         → state_identities.id     (R7-C)
--   state_ruling_enforcements.task_id      → tasks.id                (R2/R4)
--
-- وكلُّها `ON DELETE RESTRICT`: لا يُحذف كيانٌ مُشارٌ إليه من قضيةٍ أو حكم.
-- =============================================================================

-- الخطوة 1: المحكمة — قراءةٌ قضائية لمؤسسةٍ مُسجَّلة، لا سجلُّ مؤسساتٍ ثانٍ.
CREATE TABLE IF NOT EXISTS state_courts (
    id              VARCHAR PRIMARY KEY,
    code            VARCHAR NOT NULL,
    name            VARCHAR NOT NULL,
    level           VARCHAR NOT NULL,
    jurisdiction    VARCHAR NOT NULL,
    institution_id  VARCHAR NOT NULL REFERENCES state_institutions(id) ON DELETE RESTRICT,
    status          VARCHAR NOT NULL DEFAULT 'active',
    status_reason   TEXT DEFAULT '',
    tenant_id       VARCHAR NOT NULL DEFAULT 'default',
    created_by      VARCHAR NOT NULL,
    created_at      TIMESTAMP,
    updated_at      TIMESTAMP,
    CONSTRAINT ck_state_courts_level CHECK (
        level IN ('FIRST_INSTANCE','APPELLATE','SUPREME','SPECIALIZED')
    ),
    -- النطاقُ مجموعةٌ فرعية من AUTHORITY_SCOPES، و DEPARTMENT مُستثنىً بقصد:
    -- لا محاكمَ داخل إدارة. ولا ترقيةَ ضمنية بين هذه القيم في أيّ استعلام.
    CONSTRAINT ck_state_courts_jurisdiction CHECK (
        jurisdiction IN ('FEDERAL','STATE','INSTITUTION')
    ),
    CONSTRAINT ck_state_courts_status CHECK (status IN ('active','suspended','dissolved')),
    CONSTRAINT uq_state_courts_tenant_code UNIQUE (tenant_id, code)
);

CREATE INDEX IF NOT EXISTS ix_state_courts_jurisdiction
    ON state_courts (tenant_id, jurisdiction, status);
CREATE INDEX IF NOT EXISTS ix_state_courts_institution ON state_courts (institution_id);

-- الخطوة 2: تقليدُ القاضي — الحلقةُ التي تُثبت أن «قاضيًا» ليس دورًا ولا اسمًا.
CREATE TABLE IF NOT EXISTS state_court_judges (
    id                 VARCHAR PRIMARY KEY,
    court_id           VARCHAR NOT NULL REFERENCES state_courts(id) ON DELETE RESTRICT,
    official_id        VARCHAR NOT NULL REFERENCES state_officials(id) ON DELETE RESTRICT,
    position_id        VARCHAR NOT NULL REFERENCES state_positions(id) ON DELETE RESTRICT,
    identity_id        VARCHAR NOT NULL REFERENCES state_identities(id) ON DELETE RESTRICT,
    title              VARCHAR NOT NULL DEFAULT 'قاضٍ',
    status             VARCHAR NOT NULL DEFAULT 'active',
    appointed_by       VARCHAR NOT NULL,
    appointed_at       TIMESTAMP,
    revoked_at         TIMESTAMP,
    revocation_reason  TEXT DEFAULT '',
    tenant_id          VARCHAR NOT NULL DEFAULT 'default',
    created_at         TIMESTAMP,
    updated_at         TIMESTAMP,
    CONSTRAINT ck_state_court_judges_status CHECK (status IN ('active','suspended','revoked')),
    CONSTRAINT ck_state_court_judges_revoked_at CHECK (
        (status = 'revoked' AND revoked_at IS NOT NULL)
        OR (status <> 'revoked' AND revoked_at IS NULL)
    )
);

-- فهرسٌ فريدٌ **جزئي**: تقليدٌ نشطٌ واحد لكل (محكمة، مسؤول)، والصفوف المعزولة
-- تبقى تاريخًا. القيدُ الكامل كان سيمنع إعادة التقليد بعد العزل إلّا بحذف التاريخ.
CREATE UNIQUE INDEX IF NOT EXISTS uq_state_court_judges_active
    ON state_court_judges (court_id, official_id) WHERE status = 'active';

CREATE INDEX IF NOT EXISTS ix_state_court_judges_identity
    ON state_court_judges (identity_id, status);
CREATE INDEX IF NOT EXISTS ix_state_court_judges_court
    ON state_court_judges (court_id, status);

-- الخطوة 3: القضية القضائية — دورةُ حياةٍ صريحة، لا `state_cases` الإدارية.
CREATE TABLE IF NOT EXISTS state_legal_cases (
    id                     VARCHAR PRIMARY KEY,
    reference              VARCHAR NOT NULL,
    court_id               VARCHAR NOT NULL REFERENCES state_courts(id) ON DELETE RESTRICT,
    jurisdiction           VARCHAR NOT NULL,
    case_type              VARCHAR NOT NULL,
    subject                TEXT NOT NULL,
    status                 VARCHAR NOT NULL DEFAULT 'opened',
    opened_by_principal    VARCHAR NOT NULL,
    opened_by_identity_id  VARCHAR NOT NULL REFERENCES state_identities(id) ON DELETE RESTRICT,
    assigned_judge_id      VARCHAR REFERENCES state_court_judges(id) ON DELETE RESTRICT,
    assigned_at            TIMESTAMP,
    opened_at              TIMESTAMP,
    closed_at              TIMESTAMP,
    closure_reason         TEXT DEFAULT '',
    tenant_id              VARCHAR NOT NULL DEFAULT 'default',
    created_at             TIMESTAMP,
    updated_at             TIMESTAMP,
    CONSTRAINT ck_state_legal_cases_status CHECK (
        status IN ('opened','filed','assigned','hearing','decided','enforcement','closed')
    ),
    CONSTRAINT ck_state_legal_cases_type CHECK (
        case_type IN ('CIVIL','ADMINISTRATIVE','CONSTITUTIONAL','DISCIPLINARY')
    ),
    CONSTRAINT ck_state_legal_cases_jurisdiction CHECK (
        jurisdiction IN ('FEDERAL','STATE','INSTITUTION')
    ),
    CONSTRAINT ck_state_legal_cases_closed_at CHECK (
        (status = 'closed' AND closed_at IS NOT NULL)
        OR (status <> 'closed' AND closed_at IS NULL)
    ),
    -- الإسنادُ زوجٌ لا ينفكّ: قاضٍ بلا طابعٍ أو طابعٌ بلا قاضٍ كلاهما مرفوض.
    CONSTRAINT ck_state_legal_cases_assignment_pair CHECK (
        (assigned_judge_id IS NULL AND assigned_at IS NULL)
        OR (assigned_judge_id IS NOT NULL AND assigned_at IS NOT NULL)
    ),
    CONSTRAINT uq_state_legal_cases_tenant_reference UNIQUE (tenant_id, reference)
);

CREATE INDEX IF NOT EXISTS ix_state_legal_cases_court ON state_legal_cases (court_id, status);
CREATE INDEX IF NOT EXISTS ix_state_legal_cases_judge
    ON state_legal_cases (assigned_judge_id, status);

-- الخطوة 4: الأطراف — `identity_id` إلزاميّ، فلا طرفَ يُعرَّف بنصّ اسم.
CREATE TABLE IF NOT EXISTS state_case_parties (
    id              VARCHAR PRIMARY KEY,
    case_id         VARCHAR NOT NULL REFERENCES state_legal_cases(id) ON DELETE RESTRICT,
    party_role      VARCHAR NOT NULL,
    identity_id     VARCHAR NOT NULL REFERENCES state_identities(id) ON DELETE RESTRICT,
    institution_id  VARCHAR REFERENCES state_institutions(id) ON DELETE RESTRICT,
    display_label   VARCHAR DEFAULT '',
    added_by        VARCHAR NOT NULL,
    tenant_id       VARCHAR NOT NULL DEFAULT 'default',
    created_at      TIMESTAMP,
    CONSTRAINT ck_state_case_parties_role CHECK (
        party_role IN ('PLAINTIFF','DEFENDANT','INTERVENOR','WITNESS','COUNSEL')
    ),
    CONSTRAINT uq_state_case_parties_case_identity_role UNIQUE (case_id, identity_id, party_role)
);

CREATE INDEX IF NOT EXISTS ix_state_case_parties_case ON state_case_parties (case_id, party_role);
CREATE INDEX IF NOT EXISTS ix_state_case_parties_identity ON state_case_parties (identity_id);

-- الخطوة 5: المطالبات — والمرجعُ القانونيّ **غير محقَّق** بعلمٍ لا بإخفاء.
CREATE TABLE IF NOT EXISTS state_case_claims (
    id                    VARCHAR PRIMARY KEY,
    case_id               VARCHAR NOT NULL REFERENCES state_legal_cases(id) ON DELETE RESTRICT,
    claimant_party_id     VARCHAR NOT NULL REFERENCES state_case_parties(id) ON DELETE RESTRICT,
    claim_type            VARCHAR NOT NULL,
    statement             TEXT NOT NULL,
    legal_basis_kind      VARCHAR NOT NULL DEFAULT 'NONE',
    legal_basis_ref       VARCHAR DEFAULT '',
    legal_basis_verified  BOOLEAN NOT NULL DEFAULT FALSE,
    amount                VARCHAR,
    filed_by              VARCHAR NOT NULL,
    tenant_id             VARCHAR NOT NULL DEFAULT 'default',
    created_at            TIMESTAMP,
    CONSTRAINT ck_state_case_claims_type CHECK (
        claim_type IN ('MONETARY','DECLARATORY','INJUNCTIVE','APPEAL','SANCTION')
    ),
    CONSTRAINT ck_state_case_claims_basis_kind CHECK (
        legal_basis_kind IN ('NONE','CONSTITUTION_ARTICLE','LEGISLATION','DECREE','POLICY')
    ),
    CONSTRAINT ck_state_case_claims_basis_ref CHECK (
        (legal_basis_kind = 'NONE' AND (legal_basis_ref = '' OR legal_basis_ref IS NULL))
        OR (legal_basis_kind <> 'NONE' AND legal_basis_ref <> '')
    ),
    -- لا «مرجعٌ محقَّق» بلا مرجع: العَلَم لا يُرفَع على فراغ.
    CONSTRAINT ck_state_case_claims_verified_needs_basis CHECK (
        NOT legal_basis_verified OR legal_basis_kind <> 'NONE'
    ),
    CONSTRAINT ck_state_case_claims_statement CHECK (length(statement) > 0)
);

CREATE INDEX IF NOT EXISTS ix_state_case_claims_case ON state_case_claims (case_id, claim_type);

-- الخطوة 6: الأدلّة — سجلُّ إيداعٍ مُدقَّق، و**ليس** سلسلة حيازة.
CREATE TABLE IF NOT EXISTS state_case_evidence (
    id                        VARCHAR PRIMARY KEY,
    case_id                   VARCHAR NOT NULL REFERENCES state_legal_cases(id) ON DELETE RESTRICT,
    evidence_type             VARCHAR NOT NULL,
    source                    TEXT NOT NULL,
    content_hash              VARCHAR,
    fingerprint_algo          VARCHAR DEFAULT '',
    submitted_by_principal    VARCHAR NOT NULL,
    submitted_by_identity_id  VARCHAR NOT NULL REFERENCES state_identities(id) ON DELETE RESTRICT,
    submitted_at              TIMESTAMP,
    status                    VARCHAR NOT NULL DEFAULT 'submitted',
    status_reason             TEXT DEFAULT '',
    tenant_id                 VARCHAR NOT NULL DEFAULT 'default',
    created_at                TIMESTAMP,
    updated_at                TIMESTAMP,
    CONSTRAINT ck_state_case_evidence_type CHECK (
        evidence_type IN ('DOCUMENT','RECORD','TESTIMONY','ARTIFACT','AUDIT_ENTRY')
    ),
    CONSTRAINT ck_state_case_evidence_status CHECK (
        status IN ('submitted','admitted','excluded','withdrawn')
    ),
    CONSTRAINT ck_state_case_evidence_source CHECK (length(source) > 0),
    -- بصمةُ sha256 بطولٍ مفروض. و NULL تعني «لا بصمة» ولا تعني «سليم».
    CONSTRAINT ck_state_case_evidence_hash_length CHECK (
        content_hash IS NULL OR length(content_hash) = 64
    ),
    CONSTRAINT ck_state_case_evidence_hash_algo CHECK (
        (content_hash IS NULL AND (fingerprint_algo = '' OR fingerprint_algo IS NULL))
        OR (content_hash IS NOT NULL AND fingerprint_algo <> '')
    )
);

CREATE INDEX IF NOT EXISTS ix_state_case_evidence_case ON state_case_evidence (case_id, status);
CREATE INDEX IF NOT EXISTS ix_state_case_evidence_hash ON state_case_evidence (content_hash);

-- الخطوة 7: الإجراءات — ترتيبٌ مفروضٌ في القاعدة، بديلُ النصّ الحرّ.
CREATE TABLE IF NOT EXISTS state_case_proceedings (
    id                 VARCHAR PRIMARY KEY,
    case_id            VARCHAR NOT NULL REFERENCES state_legal_cases(id) ON DELETE RESTRICT,
    sequence           INTEGER NOT NULL,
    proceeding_type    VARCHAR NOT NULL,
    actor_principal    VARCHAR NOT NULL,
    actor_identity_id  VARCHAR NOT NULL REFERENCES state_identities(id) ON DELETE RESTRICT,
    summary            TEXT NOT NULL,
    record             JSON,
    status             VARCHAR NOT NULL DEFAULT 'recorded',
    occurred_at        TIMESTAMP,
    tenant_id          VARCHAR NOT NULL DEFAULT 'default',
    created_at         TIMESTAMP,
    CONSTRAINT ck_state_case_proceedings_type CHECK (
        proceeding_type IN ('FILING','HEARING','MOTION','REVIEW','RULING')
    ),
    CONSTRAINT ck_state_case_proceedings_status CHECK (status IN ('recorded','superseded')),
    CONSTRAINT ck_state_case_proceedings_sequence CHECK (sequence > 0),
    CONSTRAINT uq_state_case_proceedings_case_sequence UNIQUE (case_id, sequence)
);

CREATE INDEX IF NOT EXISTS ix_state_case_proceedings_case
    ON state_case_proceedings (case_id, proceeding_type);

-- الخطوة 8: الأحكام — حكمٌ واحدٌ قائمٌ لكل مرحلةٍ قضائية، مفروضًا بفهرسٍ جزئيّ.
CREATE TABLE IF NOT EXISTS state_rulings (
    id                   VARCHAR PRIMARY KEY,
    case_id              VARCHAR NOT NULL REFERENCES state_legal_cases(id) ON DELETE RESTRICT,
    court_id             VARCHAR NOT NULL REFERENCES state_courts(id) ON DELETE RESTRICT,
    judge_id             VARCHAR NOT NULL REFERENCES state_court_judges(id) ON DELETE RESTRICT,
    judge_identity_id    VARCHAR NOT NULL REFERENCES state_identities(id) ON DELETE RESTRICT,
    stage                VARCHAR NOT NULL DEFAULT 'FIRST_INSTANCE',
    decision             VARCHAR NOT NULL,
    disposition          TEXT NOT NULL,
    status               VARCHAR NOT NULL DEFAULT 'issued',
    provenance_class     VARCHAR NOT NULL DEFAULT 'PROVEN',
    authority            JSON,
    issued_by_principal  VARCHAR NOT NULL,
    issued_at            TIMESTAMP,
    vacated_at           TIMESTAMP,
    vacatur_reason       TEXT DEFAULT '',
    tenant_id            VARCHAR NOT NULL DEFAULT 'default',
    created_at           TIMESTAMP,
    updated_at           TIMESTAMP,
    CONSTRAINT ck_state_rulings_stage CHECK (stage IN ('FIRST_INSTANCE','APPEAL','FINAL')),
    CONSTRAINT ck_state_rulings_decision CHECK (
        decision IN ('GRANTED','DENIED','PARTIAL','DISMISSED')
    ),
    CONSTRAINT ck_state_rulings_status CHECK (status IN ('issued','enforced','vacated')),
    CONSTRAINT ck_state_rulings_disposition CHECK (length(disposition) > 0),
    CONSTRAINT ck_state_rulings_vacated_at CHECK (
        (status = 'vacated' AND vacated_at IS NOT NULL)
        OR (status <> 'vacated' AND vacated_at IS NULL)
    )
);

-- جوهرُ D10 في سطرين: حكمٌ واحدٌ قائمٌ لكل (قضية، مرحلة). والإلغاء يُخرج الصفّ
-- من الفهرس فيُمكن حكمٌ بديلٌ — بأثرٍ مكتوبٍ لا بحذفٍ للتاريخ.
CREATE UNIQUE INDEX IF NOT EXISTS uq_state_rulings_case_stage_active
    ON state_rulings (case_id, stage) WHERE status IN ('issued','enforced');

CREATE INDEX IF NOT EXISTS ix_state_rulings_case ON state_rulings (case_id, status);
CREATE INDEX IF NOT EXISTS ix_state_rulings_judge ON state_rulings (judge_id, status);

-- الخطوة 9: أثرُ التنفيذ — مهمّةٌ في `tasks` أو مرجعُ حركةٍ في الخزانة، لا ادّعاء.
CREATE TABLE IF NOT EXISTS state_ruling_enforcements (
    id                        VARCHAR PRIMARY KEY,
    ruling_id                 VARCHAR NOT NULL REFERENCES state_rulings(id) ON DELETE RESTRICT,
    case_id                   VARCHAR NOT NULL REFERENCES state_legal_cases(id) ON DELETE RESTRICT,
    kind                      VARCHAR NOT NULL,
    task_id                   VARCHAR REFERENCES tasks(id) ON DELETE RESTRICT,
    transaction_reference     VARCHAR,
    status                    VARCHAR NOT NULL DEFAULT 'requested',
    detail                    TEXT DEFAULT '',
    requested_by_principal    VARCHAR NOT NULL,
    requested_by_identity_id  VARCHAR NOT NULL REFERENCES state_identities(id) ON DELETE RESTRICT,
    requested_at              TIMESTAMP,
    completed_at              TIMESTAMP,
    tenant_id                 VARCHAR NOT NULL DEFAULT 'default',
    created_at                TIMESTAMP,
    updated_at                TIMESTAMP,
    CONSTRAINT ck_state_ruling_enforcements_kind CHECK (kind IN ('TASK','TREASURY')),
    CONSTRAINT ck_state_ruling_enforcements_status CHECK (
        status IN ('requested','executed','failed')
    ),
    -- لا تنفيذٌ مُدَّعىً بلا هدف: مهمّةٌ أو مرجعُ حركة، أو حالةُ فشلٍ صريحة.
    CONSTRAINT ck_state_ruling_enforcements_target CHECK (
        (kind = 'TASK' AND task_id IS NOT NULL)
        OR (kind = 'TREASURY' AND transaction_reference IS NOT NULL)
        OR status = 'failed'
    )
);

CREATE INDEX IF NOT EXISTS ix_state_ruling_enforcements_ruling
    ON state_ruling_enforcements (ruling_id, status);
CREATE INDEX IF NOT EXISTS ix_state_ruling_enforcements_case
    ON state_ruling_enforcements (case_id);

-- =============================================================================
-- ما تُثبته هذه الهجرة على PostgreSQL — رفضٌ حقيقيّ برمزٍ حقيقيّ:
--
--   -- محكمةٌ بنطاق مُختَرع ⇒ 23514 ck_state_courts_jurisdiction
--   -- محكمةٌ بنطاق DEPARTMENT ⇒ 23514 (مُستثنىً بقصد)
--   -- محكمتان بنفس (مستأجر، رمز) ⇒ 23505 uq_state_courts_tenant_code
--   -- محكمةٌ على مؤسسةٍ غير موجودة ⇒ 23503 على `institution_id`
--   -- تقليدان نشطان لنفس (محكمة، مسؤول) ⇒ 23505 uq_state_court_judges_active
--   -- تقليدٌ معزول بلا `revoked_at` ⇒ 23514 ck_state_court_judges_revoked_at
--   -- قضيةٌ بحالةٍ مُختَرعة ⇒ 23514 ck_state_legal_cases_status
--   -- قضيةٌ مُسندةٌ بلا طابع إسناد ⇒ 23514 ck_state_legal_cases_assignment_pair
--   -- قضيةٌ مُغلقةٌ بلا `closed_at` ⇒ 23514 ck_state_legal_cases_closed_at
--   -- قضيتان بنفس المرجع في مستأجر ⇒ 23505 uq_state_legal_cases_tenant_reference
--   -- طرفٌ بلا هوية ⇒ 23502 NOT NULL على `identity_id`
--   -- طرفٌ بهويةٍ غير موجودة ⇒ 23503 على `identity_id`
--   -- مطالبةٌ «محقَّقة» بلا مرجع ⇒ 23514 ck_state_case_claims_verified_needs_basis
--   -- دليلٌ ببصمةٍ قصيرة ⇒ 23514 ck_state_case_evidence_hash_length
--   -- دليلٌ ببصمةٍ بلا خوارزمية ⇒ 23514 ck_state_case_evidence_hash_algo
--   -- إجراءان بنفس الترتيب في قضية ⇒ 23505 uq_state_case_proceedings_case_sequence
--   -- حكمان قائمان لنفس (قضية، مرحلة) ⇒ 23505 uq_state_rulings_case_stage_active
--   -- حكمٌ بمنطوقٍ فارغ ⇒ 23514 ck_state_rulings_disposition
--   -- تنفيذُ TASK بلا مهمّة وبحالة executed ⇒ 23514 ck_state_ruling_enforcements_target
--   -- تنفيذٌ بمهمّةٍ غير موجودة ⇒ 23503 على `task_id`
-- =============================================================================
