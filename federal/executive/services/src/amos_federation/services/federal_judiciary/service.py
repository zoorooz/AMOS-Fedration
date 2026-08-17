"""
AMOS-Federation Federal Judiciary — Service Facade
الهدف: حدُّ التخويل والجلسة والأثر لكل عملٍ قضائيّ، وتكاملٌ مع العمود التنفيذي والخزانة
النطاق: services/federal_judiciary
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17 (R7-D11/D12/D15)

## ما تفعله هذه الطبقة وما لا تفعله

تفعل أربعةً لكل عملية، بهذا الترتيب:

1. **الصلاحية**: `require_domain_permission` من مفردة `DEFAULT_ROLES` القائمة.
2. **الهوية**: `resolve_identity(..., required=True)` — فالفاعلُ يُعرَف من جلسته
   لا من حقلٍ في طلبه. ولا وسيطَ `identity_id` في أيّ دالّةٍ عامّة هنا يخصّ
   **الفاعل**؛ و`identity_id` في `add_party` يخصّ **الطرف** ويُقرأ من القاعدة.
3. **العمل**: نداءُ وحدةِ النطاق (`registry`/`docket`/`rulings`/`enforcement`)
   داخل جلسةٍ واحدة، ثم `commit`.
4. **الأثر**: `record_domain_trace` — تدقيقٌ ثم حدثٌ دائم، بالترتيب القائم (R7-G).
   والأثرُ يُكتب **بعد** `commit`: فلا حدثٌ عن كتابةٍ لم تثبت.

ولا تفعل: لا تُنشئ مؤسسةً ولا مسؤولًا ولا منصبًا ولا هوية (كلُّها في R7-A/R7-C)،
ولا تكتب حركةً مالية (الخزانة)، ولا تُشغِّل وكيلًا (العمود التنفيذي).

## تكاملُ التنفيذ — ترتيبٌ لا يُقلَب (R7-D11)

    require_judicial_authority  →  ExecutiveCore.submit  →  ExecutiveCore.run
                                →  حالةٌ نهائيةٌ مقروءة  →  أثرُ تنفيذٍ يُكتب

والجلسةُ تُغلَق قبل نداء العمود التنفيذي ثم تُفتَح جلسةٌ ثانية للكتابة — وهو نفسُ
ما تفعله `StateTreasury.execute_decision_disbursement` القائمة، لأن العمود يكتب في
`tasks` بجلسته الخاصّة ولا تُرى كتابتُه من جلسةٍ مفتوحةٍ قبلها.

وإن لم تبلغ المهمّةُ `completed` كُتب أثرٌ بحالة `failed` وبقي الحكم `issued`
ورُفع `EnforcementError`. فالفشلُ مكتوبٌ لا مُترجَمٌ إلى نجاح.

## تكاملُ الخزانة — الحكم سببٌ لا سلطة (R7-D12)

`enforce_ruling_via_treasury` تُنادي `StateTreasury.disburse` **كما هي**: بصلاحيتها
ومِنحةِ سلطتها وسجلِّ سلطة حركتها. فإن رفضت الخزانة، انتشر الرفضُ ولم يُلتَفّ عليه،
وكُتب أثرٌ `failed`. ولا مسارَ في هذا الملفّ يمرّر أمرًا ماليًّا بلا `disburse`.

## السيادة (R7-D13)

لا نموذجَ سيادةٍ يُلمَس هنا: لا نقضَ للمحكمة على أمرٍ سياديّ، ولا تعطيلَ لأمر،
ولا مسارَ يجعل الدستور طريقًا لتجريد التاج. وفي المقابل: إصدارُ حكمٍ يلزمه قاضٍ
مُثبَت، والتاجُ نفسه يُرفَض إن لم يكن قاضيًا — لأن انتحال المحكمة ممنوعٌ على
الجميع. والأمران معًا محروسان باختبارين ساكنين.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from amos_federation.common.database import get_session_factory, init_db
from amos_federation.common.principal import DEFAULT_TENANT
from amos_federation.services.executive_core.engine import get_executive_core
from amos_federation.services.federal_judiciary import docket, enforcement, registry, rulings
from amos_federation.services.federal_judiciary.authority import (
    JudicialAuthority,
    JudicialAuthorityError,
    describe_judicial_chain,
    require_judicial_authority,
)
from amos_federation.services.federal_judiciary.authorization import (
    PERMISSIONS_COURT_WRITE,
    PERMISSIONS_DOCKET_WRITE,
    PERMISSIONS_JUDGE_WRITE,
    PERMISSIONS_JUDICIARY_READ,
    PERMISSIONS_RULING_WRITE,
    require_domain_permission,
    require_tenant,
)
from amos_federation.services.federal_judiciary.enforcement import EnforcementError
from amos_federation.services.federal_judiciary.models import (
    FEDERAL_JUDICIARY_TABLES,
    CaseEvidenceModel,
    CourtJudgeModel,
    CourtModel,
    LegalCaseModel,
    RulingModel,
)
from amos_federation.services.national_registry.resolver import resolve_identity
from amos_federation.services.state_registry.trace import record_domain_trace

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from amos_federation.common.principal import AuthorizationContext

#: نوعُ مهمّة تنفيذ الحكم ونطاقُها في العمود التنفيذي — اسمان ثابتان لا مُختَلقان
#: في كل نداء، على نمط `DISBURSEMENT_TASK_TYPE` القائم في الخزانة.
RULING_TASK_TYPE = "judiciary.ruling.enforce"
RULING_TASK_DOMAIN = "judiciary"


class FederalJudiciary:
    """القضاء الفدرالي: محاكمُ وقضاةٌ وقضايا وأحكامٌ وتنفيذُها — بحدٍّ واحد لكلٍّ."""

    def __init__(self, executive_core: Any | None = None) -> None:
        init_db()
        #: العمود التنفيذي القائم — يُمرَّر للاختبار ولا يُنشأ منفِّذٌ موازٍ.
        self._core = executive_core or get_executive_core()

    # ── أدوات داخلية ─────────────────────────────────────────────────────

    def _session(self) -> Session:
        return get_session_factory()()

    def _tenant_of(self, context: AuthorizationContext) -> str:
        return context.tenant_id or DEFAULT_TENANT

    def _record(
        self,
        context: AuthorizationContext,
        action: str,
        subject: str,
        entity: dict[str, Any],
    ) -> dict[str, Any]:
        return record_domain_trace(context, action, subject, entity)

    def _identity_of(self, session: Session, context: AuthorizationContext) -> str:
        """هويةُ الفاعل الكانونية من جلسته — أو رفضٌ. لا هويةَ من جسم الطلب."""
        resolution = resolve_identity(session, context, required=True)
        return str(resolution.identity_id)

    # ── 1. المحاكم (R7-D4) ───────────────────────────────────────────────

    def register_court(
        self,
        *,
        context: AuthorizationContext,
        code: str,
        name: str,
        level: str,
        jurisdiction: str,
        institution_code: str,
    ) -> dict[str, Any]:
        """سجّل محكمةً على مؤسسةٍ قضائيةٍ قائمة — فعلٌ تنظيميّ بـ`manage:all`."""
        require_domain_permission(context, "judiciary.court.register", PERMISSIONS_COURT_WRITE)
        session = self._session()
        try:
            row = registry.create_court(
                session,
                code=code,
                name=name,
                level=level,
                jurisdiction=jurisdiction,
                institution_code=institution_code,
                created_by=context.principal_id,
                tenant_id=self._tenant_of(context),
            )
            payload = registry.court_dict(row)
            session.commit()
        finally:
            session.close()
        trace = self._record(
            context,
            "judiciary.court.register",
            "amos_federation.judiciary.court_registered",
            {
                "court_id": payload["id"],
                "code": payload["code"],
                "jurisdiction": payload["jurisdiction"],
                "name": payload["name"],
                "level": payload["level"],
                "institution_id": payload["institution_id"],
                "status": payload["status"],
                "tenant_id": payload["tenant_id"],
            },
        )
        return {**payload, **trace}

    def set_court_status(
        self, *, context: AuthorizationContext, court_id: str, status: str, reason: str
    ) -> dict[str, Any]:
        """علِّق محكمةً أو حُلَّها — بسببٍ مكتوب، ولا حذفَ صفّ."""
        require_domain_permission(context, "judiciary.court.status", PERMISSIONS_COURT_WRITE)
        session = self._session()
        try:
            row, previous = registry.set_court_status(
                session,
                court_id=court_id,
                status=status,
                reason=reason,
                tenant_id=self._tenant_of(context),
            )
            require_tenant(context, row.tenant_id)
            payload = registry.court_dict(row)
            session.commit()
        finally:
            session.close()
        trace = self._record(
            context,
            "judiciary.court.status",
            "amos_federation.judiciary.court_status_changed",
            {
                "court_id": payload["id"],
                "code": payload["code"],
                "status": payload["status"],
                "reason": reason,
                "previous_status": previous,
                "tenant_id": payload["tenant_id"],
            },
        )
        return {**payload, "previous_status": previous, **trace}

    # ── 2. القضاة (R7-D4/D9) ─────────────────────────────────────────────

    def appoint_judge(
        self,
        *,
        context: AuthorizationContext,
        court_id: str,
        official_id: str,
        position_id: str,
        title: str = "قاضٍ",
    ) -> dict[str, Any]:
        """قلِّد مسؤولًا قائمًا قضاءً في محكمة — بالشروط الخمسة في `registry.py`."""
        require_domain_permission(context, "judiciary.judge.appoint", PERMISSIONS_JUDGE_WRITE)
        session = self._session()
        try:
            row = registry.appoint_judge(
                session,
                court_id=court_id,
                official_id=official_id,
                position_id=position_id,
                title=title,
                appointed_by=context.principal_id,
                tenant_id=self._tenant_of(context),
            )
            payload = registry.judge_dict(row)
            session.commit()
        finally:
            session.close()
        trace = self._record(
            context,
            "judiciary.judge.appoint",
            "amos_federation.judiciary.judge_appointed",
            {
                "judge_id": payload["id"],
                "court_id": payload["court_id"],
                "official_id": payload["official_id"],
                "identity_id": payload["identity_id"],
                "position_id": payload["position_id"],
                "title": payload["title"],
                "status": payload["status"],
                "tenant_id": payload["tenant_id"],
            },
        )
        return {**payload, **trace}

    def set_judge_status(
        self, *, context: AuthorizationContext, judge_id: str, status: str, reason: str
    ) -> dict[str, Any]:
        """علِّق قاضيًا أو اعزله — وأثرُه أن سلطته القضائية تسقط آليًّا."""
        require_domain_permission(context, "judiciary.judge.status", PERMISSIONS_JUDGE_WRITE)
        session = self._session()
        try:
            row, previous = registry.set_judge_status(
                session,
                judge_id=judge_id,
                status=status,
                reason=reason,
                tenant_id=self._tenant_of(context),
            )
            require_tenant(context, row.tenant_id)
            payload = registry.judge_dict(row)
            session.commit()
        finally:
            session.close()
        trace = self._record(
            context,
            "judiciary.judge.status",
            "amos_federation.judiciary.judge_status_changed",
            {
                "judge_id": payload["id"],
                "court_id": payload["court_id"],
                "status": payload["status"],
                "reason": reason,
                "previous_status": previous,
                "identity_id": payload["identity_id"],
                "official_id": payload["official_id"],
                "tenant_id": payload["tenant_id"],
            },
        )
        return {**payload, "previous_status": previous, **trace}

    # ── 3. القضايا ودورة حياتها (R7-D5) ──────────────────────────────────

    def open_case(
        self,
        *,
        context: AuthorizationContext,
        court_id: str,
        case_type: str,
        subject: str,
        reference: str,
    ) -> dict[str, Any]:
        """افتح قضيةً — ونطاقُها من محكمتها، وفاتحُها من جلسته لا من طلبه."""
        require_domain_permission(context, "judiciary.case.open", PERMISSIONS_DOCKET_WRITE)
        session = self._session()
        try:
            identity_id = self._identity_of(session, context)
            row = docket.open_case(
                session,
                court_id=court_id,
                case_type=case_type,
                subject=subject,
                reference=reference,
                opened_by_principal=context.principal_id,
                opened_by_identity_id=identity_id,
                tenant_id=self._tenant_of(context),
            )
            payload = docket.case_dict(row)
            session.commit()
        finally:
            session.close()
        trace = self._record(
            context,
            "judiciary.case.open",
            "amos_federation.judiciary.case_opened",
            {
                "case_id": payload["id"],
                "reference": payload["reference"],
                "court_id": payload["court_id"],
                "jurisdiction": payload["jurisdiction"],
                "case_type": payload["case_type"],
                "status": payload["status"],
                "opened_by_identity_id": payload["opened_by_identity_id"],
                "tenant_id": payload["tenant_id"],
            },
        )
        return {**payload, **trace}

    def file_case(self, *, context: AuthorizationContext, case_id: str) -> dict[str, Any]:
        """`opened → filed` مع قيدِ إجراءٍ من نوع `FILING`."""
        require_domain_permission(context, "judiciary.case.file", PERMISSIONS_DOCKET_WRITE)
        session = self._session()
        try:
            identity_id = self._identity_of(session, context)
            row = docket.file_case(session, case_id=case_id, tenant_id=self._tenant_of(context))
            require_tenant(context, row.tenant_id)
            proceeding = docket.record_proceeding(
                session,
                case_id=row.id,
                proceeding_type="FILING",
                actor_principal=context.principal_id,
                actor_identity_id=identity_id,
                summary=f"قيدُ القضية '{row.reference}' رسميًّا",
                tenant_id=self._tenant_of(context),
            )
            payload = docket.case_dict(row)
            proceeding_payload = docket.proceeding_dict(proceeding)
            session.commit()
        finally:
            session.close()
        self._publish_proceeding(context, proceeding_payload)
        return {**payload, "proceeding": proceeding_payload}

    def assign_case(
        self, *, context: AuthorizationContext, case_id: str, judge_id: str
    ) -> dict[str, Any]:
        """`filed → assigned` بقاضٍ نشطٍ في محكمة القضية بالذات."""
        require_domain_permission(context, "judiciary.case.assign", PERMISSIONS_DOCKET_WRITE)
        session = self._session()
        try:
            row = docket.assign_case(
                session, case_id=case_id, judge_id=judge_id, tenant_id=self._tenant_of(context)
            )
            require_tenant(context, row.tenant_id)
            payload = docket.case_dict(row)
            session.commit()
        finally:
            session.close()
        trace = self._record(
            context,
            "judiciary.case.assign",
            "amos_federation.judiciary.case_assigned",
            {
                "case_id": payload["id"],
                "judge_id": payload["assigned_judge_id"],
                "court_id": payload["court_id"],
                "reference": payload["reference"],
                "status": payload["status"],
                "tenant_id": payload["tenant_id"],
            },
        )
        return {**payload, **trace}

    def open_hearing(self, *, context: AuthorizationContext, case_id: str) -> dict[str, Any]:
        """`assigned → hearing` مع قيدِ إجراءٍ من نوع `HEARING`."""
        require_domain_permission(context, "judiciary.case.hearing", PERMISSIONS_DOCKET_WRITE)
        session = self._session()
        try:
            identity_id = self._identity_of(session, context)
            row = docket.open_hearing(session, case_id=case_id, tenant_id=self._tenant_of(context))
            require_tenant(context, row.tenant_id)
            proceeding = docket.record_proceeding(
                session,
                case_id=row.id,
                proceeding_type="HEARING",
                actor_principal=context.principal_id,
                actor_identity_id=identity_id,
                summary=f"افتتاحُ جلسةٍ في القضية '{row.reference}'",
                tenant_id=self._tenant_of(context),
            )
            payload = docket.case_dict(row)
            proceeding_payload = docket.proceeding_dict(proceeding)
            session.commit()
        finally:
            session.close()
        self._publish_proceeding(context, proceeding_payload)
        return {**payload, "proceeding": proceeding_payload}

    def close_case(
        self, *, context: AuthorizationContext, case_id: str, reason: str
    ) -> dict[str, Any]:
        """`decided|enforcement → closed` بسببٍ مكتوب."""
        require_domain_permission(context, "judiciary.case.close", PERMISSIONS_DOCKET_WRITE)
        session = self._session()
        try:
            row, previous = docket.close_case(
                session, case_id=case_id, reason=reason, tenant_id=self._tenant_of(context)
            )
            require_tenant(context, row.tenant_id)
            payload = docket.case_dict(row)
            session.commit()
        finally:
            session.close()
        trace = self._record(
            context,
            "judiciary.case.close",
            "amos_federation.judiciary.case_closed",
            {
                "case_id": payload["id"],
                "reference": payload["reference"],
                "reason": reason,
                "previous_status": previous,
                "court_id": payload["court_id"],
                "status": payload["status"],
                "tenant_id": payload["tenant_id"],
            },
        )
        return {**payload, "previous_status": previous, **trace}

    # ── 4. الأطراف والمطالبات (R7-D6) ────────────────────────────────────

    def add_party(
        self,
        *,
        context: AuthorizationContext,
        case_id: str,
        party_role: str,
        identity_id: str,
        institution_id: str | None = None,
        display_label: str = "",
    ) -> dict[str, Any]:
        """أضِف طرفًا بهويةٍ كانونية مقروءةٍ من القاعدة — لا باسمٍ نصّيّ.

        `identity_id` هنا هوية **الطرف** لا هوية الفاعل: هوية الفاعل تُحَلّ من
        جلسته دائمًا. والفرقُ مقصود — والطرفُ قد يكون شخصًا لا جلسةَ له.
        """
        require_domain_permission(context, "judiciary.party.add", PERMISSIONS_DOCKET_WRITE)
        session = self._session()
        try:
            self._identity_of(session, context)
            row = docket.add_party(
                session,
                case_id=case_id,
                party_role=party_role,
                identity_id=identity_id,
                added_by=context.principal_id,
                tenant_id=self._tenant_of(context),
                institution_id=institution_id,
                display_label=display_label,
            )
            payload = docket.party_dict(row)
            session.commit()
        finally:
            session.close()
        return payload

    def add_claim(
        self,
        *,
        context: AuthorizationContext,
        case_id: str,
        claimant_party_id: str,
        claim_type: str,
        statement: str,
        legal_basis_kind: str = "NONE",
        legal_basis_ref: str = "",
        amount: str | None = None,
    ) -> dict[str, Any]:
        """أضِف مطالبةً — ومرجعُها القانونيّ يبقى **غير محقَّق** بعلمٍ (دَينٌ معلن)."""
        require_domain_permission(context, "judiciary.claim.add", PERMISSIONS_DOCKET_WRITE)
        session = self._session()
        try:
            self._identity_of(session, context)
            row = docket.add_claim(
                session,
                case_id=case_id,
                claimant_party_id=claimant_party_id,
                claim_type=claim_type,
                statement=statement,
                filed_by=context.principal_id,
                tenant_id=self._tenant_of(context),
                legal_basis_kind=legal_basis_kind,
                legal_basis_ref=legal_basis_ref,
                amount=amount,
            )
            payload = docket.claim_dict(row)
            session.commit()
        finally:
            session.close()
        return payload

    # ── 5. الأدلّة (R7-D7) ───────────────────────────────────────────────

    def submit_evidence(
        self,
        *,
        context: AuthorizationContext,
        case_id: str,
        evidence_type: str,
        source: str,
        content_hash: str | None = None,
        fingerprint_algo: str = "",
    ) -> dict[str, Any]:
        """أودِع دليلًا — سجلُّ إيداعٍ مُدقَّق، لا سلسلةَ حيازةٍ مُدَّعاة."""
        require_domain_permission(context, "judiciary.evidence.submit", PERMISSIONS_DOCKET_WRITE)
        session = self._session()
        try:
            identity_id = self._identity_of(session, context)
            row = docket.submit_evidence(
                session,
                case_id=case_id,
                evidence_type=evidence_type,
                source=source,
                submitted_by_principal=context.principal_id,
                submitted_by_identity_id=identity_id,
                tenant_id=self._tenant_of(context),
                content_hash=content_hash,
                fingerprint_algo=fingerprint_algo,
            )
            payload = docket.evidence_dict(row)
            session.commit()
        finally:
            session.close()
        trace = self._record(
            context,
            "judiciary.evidence.submit",
            "amos_federation.judiciary.evidence_submitted",
            {
                "evidence_id": payload["id"],
                "case_id": payload["case_id"],
                "evidence_type": payload["evidence_type"],
                "content_hash": payload["content_hash"],
                "fingerprint_algo": payload["fingerprint_algo"],
                "status": payload["status"],
                "submitted_by_identity_id": payload["submitted_by_identity_id"],
                "tenant_id": payload["tenant_id"],
            },
        )
        return {**payload, **trace}

    def set_evidence_status(
        self, *, context: AuthorizationContext, evidence_id: str, status: str, reason: str
    ) -> dict[str, Any]:
        """اقبل الدليل أو استبعِده أو اسحبه — بأثرٍ مكتوبٍ لا بحذف."""
        require_domain_permission(context, "judiciary.evidence.status", PERMISSIONS_DOCKET_WRITE)
        session = self._session()
        try:
            row, previous = docket.set_evidence_status(
                session,
                evidence_id=evidence_id,
                status=status,
                reason=reason,
                tenant_id=self._tenant_of(context),
            )
            require_tenant(context, row.tenant_id)
            payload = docket.evidence_dict(row)
            session.commit()
        finally:
            session.close()
        return {**payload, "previous_status": previous}

    # ── 6. الإجراءات (R7-D8) ─────────────────────────────────────────────

    def record_proceeding(
        self,
        *,
        context: AuthorizationContext,
        case_id: str,
        proceeding_type: str,
        summary: str,
        record: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """قيِّد إجراءً بترتيبٍ مفروضٍ في القاعدة.

        و`RULING` ممنوعٌ من هذا المدخل: قيدُ إجراءِ حكمٍ يجري داخل `issue_ruling`
        وحدها مع الحكم نفسه. ولو سُمح هنا لَأمكن قيدُ «حكمٍ» بلا حكم.
        """
        require_domain_permission(context, "judiciary.proceeding.record", PERMISSIONS_DOCKET_WRITE)
        if proceeding_type == "RULING":
            raise docket.JudiciaryError(
                "إجراءُ نوع 'RULING' يُقيَّد مع الحكم في `issue_ruling` وحدها"
            )
        session = self._session()
        try:
            identity_id = self._identity_of(session, context)
            row = docket.record_proceeding(
                session,
                case_id=case_id,
                proceeding_type=proceeding_type,
                actor_principal=context.principal_id,
                actor_identity_id=identity_id,
                summary=summary,
                tenant_id=self._tenant_of(context),
                record=record,
            )
            payload = docket.proceeding_dict(row)
            session.commit()
        finally:
            session.close()
        trace = self._publish_proceeding(context, payload)
        return {**payload, **trace}

    def _publish_proceeding(
        self, context: AuthorizationContext, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self._record(
            context,
            "judiciary.proceeding.record",
            "amos_federation.judiciary.proceeding_recorded",
            {
                "proceeding_id": payload["id"],
                "case_id": payload["case_id"],
                "proceeding_type": payload["proceeding_type"],
                "sequence": payload["sequence"],
                "actor_identity_id": payload["actor_identity_id"],
                "status": payload["status"],
                "summary": payload["summary"],
                "tenant_id": payload["tenant_id"],
            },
        )

    # ── 7. الأحكام (R7-D10) ──────────────────────────────────────────────

    def issue_ruling(
        self,
        *,
        context: AuthorizationContext,
        case_id: str,
        decision: str,
        disposition: str,
        stage: str = "FIRST_INSTANCE",
    ) -> dict[str, Any]:
        """أصدِر حكمًا — يلزمه سلطةٌ قضائية مُثبَتة، والتاجُ نفسه لا يُستثنى.

        Raises:
            JudicialAuthorityError: المُنادي ليس قاضيًا مُقلَّدًا في محكمة القضية،
                أو منصبُه غير نشط، أو نطاقُه لا يطابق، أو القضية غير مُسندةٍ إليه.
            DuplicateRulingError: للقضية حكمٌ قائمٌ في هذه المرحلة.
        """
        require_domain_permission(context, "judiciary.ruling.issue", PERMISSIONS_RULING_WRITE)
        session = self._session()
        try:
            case = docket.load_case(session, case_id, tenant_id=self._tenant_of(context))
            require_tenant(context, case.tenant_id)
            authority = require_judicial_authority(
                session, context, court_id=case.court_id, case_id=case.id
            )
            row, proceeding = rulings.issue_ruling(
                session,
                authority=authority,
                decision=decision,
                disposition=disposition,
                tenant_id=self._tenant_of(context),
                stage=stage,
            )
            payload = rulings.ruling_dict(row)
            proceeding_payload = docket.proceeding_dict(proceeding)
            session.commit()
        finally:
            session.close()
        self._publish_proceeding(context, proceeding_payload)
        trace = self._record(
            context,
            "judiciary.ruling.issue",
            "amos_federation.judiciary.ruling_issued",
            {
                "ruling_id": payload["id"],
                "case_id": payload["case_id"],
                "court_id": payload["court_id"],
                "judge_id": payload["judge_id"],
                "decision": payload["decision"],
                "stage": payload["stage"],
                "status": payload["status"],
                "provenance_class": payload["provenance_class"],
                "judge_identity_id": payload["judge_identity_id"],
                "tenant_id": payload["tenant_id"],
            },
        )
        return {**payload, "proceeding": proceeding_payload, **trace}

    def vacate_ruling(
        self, *, context: AuthorizationContext, ruling_id: str, reason: str
    ) -> dict[str, Any]:
        """ألغِ حكمًا غير مُنفَّذ بسلطةٍ قضائية في محكمته — تغييرُ حالةٍ لا حذف."""
        require_domain_permission(context, "judiciary.ruling.vacate", PERMISSIONS_RULING_WRITE)
        session = self._session()
        try:
            ruling = rulings.load_ruling(session, ruling_id, tenant_id=self._tenant_of(context))
            require_tenant(context, ruling.tenant_id)
            require_judicial_authority(
                session, context, court_id=ruling.court_id, case_id=ruling.case_id
            )
            row, previous = rulings.vacate_ruling(
                session, ruling_id=ruling_id, reason=reason, tenant_id=self._tenant_of(context)
            )
            payload = rulings.ruling_dict(row)
            session.commit()
        finally:
            session.close()
        return {**payload, "previous_status": previous}

    # ── 8. تنفيذُ الحكم عبر العمود التنفيذي (R7-D11) ─────────────────────

    def enforce_ruling_via_task(
        self,
        *,
        context: AuthorizationContext,
        ruling_id: str,
        description: str = "",
        max_steps: int = 8,
    ) -> dict[str, Any]:
        """أحِل حكمًا إلى التنفيذ عبر `ExecutiveCore` — ولا تُنفِّذ المحكمةُ بنفسها.

        الترتيب: سلطةٌ قضائية → إغلاقُ الجلسة → `submit` → `run` → حالةٌ نهائية →
        أثرٌ يُكتب. وإن لم تبلغ المهمّة `completed` كُتب أثرٌ `failed` ورُفع
        `EnforcementError` وبقي الحكم `issued`.
        """
        require_domain_permission(context, "judiciary.ruling.enforce", PERMISSIONS_RULING_WRITE)
        tenant = self._tenant_of(context)
        session = self._session()
        try:
            ruling = enforcement.assert_enforceable(session, ruling_id=ruling_id, tenant_id=tenant)
            require_tenant(context, ruling.tenant_id)
            authority = require_judicial_authority(
                session, context, court_id=ruling.court_id, case_id=ruling.case_id
            )
            case_id = ruling.case_id
            identity_id = str(authority.identity_id)
            summary = description or f"تنفيذ الحكم {ruling.id}: {ruling.decision}"
        finally:
            session.close()

        task = self._core.submit(
            RULING_TASK_TYPE, summary, domain=RULING_TASK_DOMAIN, tenant_id=tenant
        )
        outcome = self._core.run(task["id"], max_steps=max_steps)
        final_state = outcome.get("final_state")

        session = self._session()
        try:
            if final_state != "completed":
                failed = enforcement.record_enforcement(
                    session,
                    ruling_id=ruling_id,
                    case_id=case_id,
                    kind="TASK",
                    status="failed",
                    requested_by_principal=context.principal_id,
                    requested_by_identity_id=identity_id,
                    tenant_id=tenant,
                    task_id=task["id"],
                    detail=f"المهمّة انتهت بحالة '{final_state}'",
                )
                failed_payload = enforcement.enforcement_dict(failed)
                session.commit()
                self._publish_enforcement(context, failed_payload)
                raise EnforcementError(
                    f"مهمّةُ تنفيذ الحكم '{task['id']}' انتهت بحالة '{final_state}' — "
                    "الحكم باقٍ 'issued' والأثرُ مكتوبٌ 'failed'"
                )
            row = enforcement.record_enforcement(
                session,
                ruling_id=ruling_id,
                case_id=case_id,
                kind="TASK",
                status="executed",
                requested_by_principal=context.principal_id,
                requested_by_identity_id=identity_id,
                tenant_id=tenant,
                task_id=task["id"],
                detail=f"المهمّة بلغت '{final_state}'",
            )
            rulings.mark_ruling_enforced(session, ruling_id=ruling_id, tenant_id=tenant)
            case = docket.load_case(session, case_id, tenant_id=tenant)
            if case.status == "decided":
                docket.advance_case(session, case_id=case_id, target="enforcement", tenant_id=tenant)
            payload = enforcement.enforcement_dict(row)
            session.commit()
        finally:
            session.close()
        trace = self._publish_enforcement(context, payload)
        return {**payload, "task_final_state": final_state, **trace}

    # ── 9. تنفيذُ الحكم عبر الخزانة (R7-D12) ─────────────────────────────

    def enforce_ruling_via_treasury(
        self,
        *,
        context: AuthorizationContext,
        ruling_id: str,
        treasury: Any,
        allocation_id: str,
        expense_account_code: str,
        amount: Any,
        purpose: str,
        official_id: str,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """أحِل حكمًا إلى صرفٍ عبر `StateTreasury.disburse` كما هي — بلا تجاوزٍ.

        `treasury` يُمرَّر صراحةً ولا يُستورَد هنا: فالخزانةُ خدمةٌ قائمة بحدودها،
        وهذه الدالّة تُناديها كأيّ مُنادٍ آخر. فإن رفضت لنقص صلاحيةٍ أو مِنحة،
        انتشر الرفض وكُتب أثرٌ `failed` — **والحكمُ لا يمنح سلطةً مالية**.
        """
        require_domain_permission(context, "judiciary.ruling.enforce", PERMISSIONS_RULING_WRITE)
        tenant = self._tenant_of(context)
        session = self._session()
        try:
            ruling = enforcement.assert_enforceable(session, ruling_id=ruling_id, tenant_id=tenant)
            require_tenant(context, ruling.tenant_id)
            authority = require_judicial_authority(
                session, context, court_id=ruling.court_id, case_id=ruling.case_id
            )
            case_id = ruling.case_id
            identity_id = str(authority.identity_id)
        finally:
            session.close()

        try:
            transaction = treasury.disburse(
                context=context,
                allocation_id=allocation_id,
                expense_account_code=expense_account_code,
                amount=amount,
                purpose=purpose,
                official_id=official_id,
                idempotency_key=idempotency_key,
            )
        except Exception as exc:
            session = self._session()
            try:
                failed = enforcement.record_enforcement(
                    session,
                    ruling_id=ruling_id,
                    case_id=case_id,
                    kind="TREASURY",
                    status="failed",
                    requested_by_principal=context.principal_id,
                    requested_by_identity_id=identity_id,
                    tenant_id=tenant,
                    detail=f"{type(exc).__name__}: {exc}",
                )
                failed_payload = enforcement.enforcement_dict(failed)
                session.commit()
            finally:
                session.close()
            self._publish_enforcement(context, failed_payload)
            raise

        session = self._session()
        try:
            row = enforcement.record_enforcement(
                session,
                ruling_id=ruling_id,
                case_id=case_id,
                kind="TREASURY",
                status="executed",
                requested_by_principal=context.principal_id,
                requested_by_identity_id=identity_id,
                tenant_id=tenant,
                transaction_reference=transaction["reference"],
                detail=f"حركةُ خزانة '{transaction['reference']}'",
            )
            rulings.mark_ruling_enforced(session, ruling_id=ruling_id, tenant_id=tenant)
            case = docket.load_case(session, case_id, tenant_id=tenant)
            if case.status == "decided":
                docket.advance_case(session, case_id=case_id, target="enforcement", tenant_id=tenant)
            payload = enforcement.enforcement_dict(row)
            session.commit()
        finally:
            session.close()
        trace = self._publish_enforcement(context, payload)
        return {**payload, "transaction": transaction, **trace}

    def _publish_enforcement(
        self, context: AuthorizationContext, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self._record(
            context,
            "judiciary.ruling.enforce",
            "amos_federation.judiciary.ruling_enforced",
            {
                "enforcement_id": payload["id"],
                "ruling_id": payload["ruling_id"],
                "case_id": payload["case_id"],
                "kind": payload["kind"],
                "status": payload["status"],
                "task_id": payload["task_id"],
                "transaction_reference": payload["transaction_reference"],
                "detail": payload["detail"],
                "requested_by_identity_id": payload["requested_by_identity_id"],
                "tenant_id": payload["tenant_id"],
            },
        )

    # ── 10. قراءات (R7-D17) ──────────────────────────────────────────────

    def get_court(self, *, context: AuthorizationContext, court_id: str) -> dict[str, Any]:
        require_domain_permission(context, "judiciary.court.read", PERMISSIONS_JUDICIARY_READ)
        session = self._session()
        try:
            row = registry.load_court(session, court_id, tenant_id=self._tenant_of(context))
            require_tenant(context, row.tenant_id)
            return registry.court_dict(row)
        finally:
            session.close()

    def list_courts(
        self,
        *,
        context: AuthorizationContext,
        jurisdiction: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        require_domain_permission(context, "judiciary.court.read", PERMISSIONS_JUDICIARY_READ)
        session = self._session()
        try:
            rows = registry.list_courts(
                session,
                tenant_id=self._tenant_of(context),
                jurisdiction=jurisdiction,
                status=status,
                limit=limit,
            )
            return [registry.court_dict(row) for row in rows]
        finally:
            session.close()

    def list_judges(
        self, *, context: AuthorizationContext, court_id: str, include_inactive: bool = False
    ) -> list[dict[str, Any]]:
        require_domain_permission(context, "judiciary.judge.read", PERMISSIONS_JUDICIARY_READ)
        session = self._session()
        try:
            rows = registry.list_judges(
                session,
                court_id=court_id,
                tenant_id=self._tenant_of(context),
                include_inactive=include_inactive,
            )
            return [registry.judge_dict(row) for row in rows]
        finally:
            session.close()

    def case_file(self, *, context: AuthorizationContext, case_id: str) -> dict[str, Any]:
        """ملفُّ القضية كاملًا: القضية وأطرافُها ومطالباتُها وأدلّتُها وإجراءاتُها وأحكامُها."""
        require_domain_permission(context, "judiciary.case.read", PERMISSIONS_JUDICIARY_READ)
        tenant = self._tenant_of(context)
        session = self._session()
        try:
            case = docket.load_case(session, case_id, tenant_id=tenant)
            require_tenant(context, case.tenant_id)
            parties = [
                docket.party_dict(row)
                for row in session.query(docket.CasePartyModel)
                .filter(docket.CasePartyModel.case_id == case.id)
                .all()
            ]
            claims = [
                docket.claim_dict(row)
                for row in session.query(docket.CaseClaimModel)
                .filter(docket.CaseClaimModel.case_id == case.id)
                .all()
            ]
            evidence = [
                docket.evidence_dict(row)
                for row in session.query(CaseEvidenceModel)
                .filter(CaseEvidenceModel.case_id == case.id)
                .all()
            ]
            proceedings = [
                docket.proceeding_dict(row)
                for row in docket.list_proceedings(session, case_id=case.id, tenant_id=tenant)
            ]
            case_rulings = [
                rulings.ruling_dict(row)
                for row in rulings.list_rulings(session, case_id=case.id, tenant_id=tenant)
            ]
            enforcements = [
                enforcement.enforcement_dict(row)
                for ruling in case_rulings
                for row in enforcement.list_enforcements(
                    session, ruling_id=ruling["id"], tenant_id=tenant
                )
            ]
            return {
                "case": docket.case_dict(case),
                "parties": parties,
                "claims": claims,
                "evidence": evidence,
                "proceedings": proceedings,
                "rulings": case_rulings,
                "enforcements": enforcements,
            }
        finally:
            session.close()

    def judicial_chain(
        self, *, context: AuthorizationContext, court_id: str, case_id: str | None = None
    ) -> dict[str, Any]:
        """اشرح سلسلة السلطة القضائية كما هي — بلا رفعٍ وبلا كتابة (تشخيص)."""
        require_domain_permission(context, "judiciary.authority.read", PERMISSIONS_JUDICIARY_READ)
        session = self._session()
        try:
            return describe_judicial_chain(session, context, court_id=court_id, case_id=case_id)
        finally:
            session.close()

    def judiciary_health(self, *, context: AuthorizationContext) -> dict[str, Any]:
        """عددٌ مقروءٌ من الصفوف — لا مقياسٌ مُصطنع."""
        require_domain_permission(context, "judiciary.health.read", PERMISSIONS_JUDICIARY_READ)
        tenant = self._tenant_of(context)
        session = self._session()
        try:
            return {
                "tables": list(FEDERAL_JUDICIARY_TABLES),
                "courts": session.query(CourtModel).filter(CourtModel.tenant_id == tenant).count(),
                "active_courts": session.query(CourtModel)
                .filter(CourtModel.tenant_id == tenant, CourtModel.status == "active")
                .count(),
                "active_judges": session.query(CourtJudgeModel)
                .filter(CourtJudgeModel.tenant_id == tenant, CourtJudgeModel.status == "active")
                .count(),
                "cases": session.query(LegalCaseModel)
                .filter(LegalCaseModel.tenant_id == tenant)
                .count(),
                "open_cases": session.query(LegalCaseModel)
                .filter(LegalCaseModel.tenant_id == tenant, LegalCaseModel.status != "closed")
                .count(),
                "rulings": session.query(RulingModel)
                .filter(RulingModel.tenant_id == tenant)
                .count(),
                "enforced_rulings": session.query(RulingModel)
                .filter(RulingModel.tenant_id == tenant, RulingModel.status == "enforced")
                .count(),
                "tenant_id": tenant,
            }
        finally:
            session.close()


_JUDICIARY: FederalJudiciary | None = None


def get_federal_judiciary() -> FederalJudiciary:
    """المُفردة الوحيدة — على نمط `get_national_registry` القائم."""
    global _JUDICIARY
    if _JUDICIARY is None:
        _JUDICIARY = FederalJudiciary()
    return _JUDICIARY


def reset_federal_judiciary() -> None:
    """أعِد التصفير — للاختبارات وحدها، على النمط القائم في بقيّة النطاقات."""
    global _JUDICIARY
    _JUDICIARY = None


__all__ = [
    "RULING_TASK_DOMAIN",
    "RULING_TASK_TYPE",
    "EnforcementError",
    "FederalJudiciary",
    "JudicialAuthority",
    "JudicialAuthorityError",
    "get_federal_judiciary",
    "reset_federal_judiciary",
]
