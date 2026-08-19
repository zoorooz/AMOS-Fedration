"""
الهدف: اختباراتُ 2B — سياديّةُ الخدماتِ الحكوميّة: تغييرُ حالةِ الخدمة
النطاق: federal/executive/services
تاريخ الإنشاء: 2026-08-18 (المرحلة P5أ من برنامجِ الهجرةِ السياديّة)

هذه الاختباراتُ لا تقولُ «تمّتِ الهجرةُ»؛ كلُّ واحدٍ منها يُثبِتُ دعوى واحدةً بدليلٍ
مقروءٍ من الحدِّ نفسِه: البوابةُ، والمراحلُ الإلزاميّةُ، والتخويلُ، والأثرُ المُعلَنُ،
وخطّةُ التعويضِ وعملُ المُعوِّضِ فعلًا، والفشلُ، والإعادةُ، وإغلاقُ التجاوز، والحرسُ
الساكن، وعدمُ انكسارِ العقدِ القائم.
"""

from __future__ import annotations

import ast
import inspect
import uuid
from pathlib import Path

import pytest

# اقترانٌ **قائمٌ قبلَ هذه المرحلة**: `national_registry.models` يحملُ مفتاحًا أجنبيًّا
# إلى `state_budgets` المُعرَّفِ في `state_treasury.models`، فإن لم تُستورَدِ الثانيةُ
# سقطَ `create_all`. يُستوردُ هنا صريحًا لأنّ الملفَّ يجبُ أن يعملَ وحدَه، والعلّةُ
# مُقيَّدةٌ في الجردِ ومؤجَّلةٌ إلى P12 — لا تُصلَحُ بترتيبِ نماذجَ من تلقاءِ النفس.
import amos_federation.services.state_treasury.models  # noqa: F401
from amos_federation.common.database import TaskModel, get_session_factory, init_db
from amos_federation.common.principal import DEFAULT_TENANT, AuthorizationContext, Principal
from amos_federation.services.executive_core.agent_identity import register_identity
from amos_federation.services.executive_core.engine import reset_executive_core
from amos_federation.services.executive_core.sovereignty_bridge import (
    FORBIDDEN_BYPASS_PARAMS,
    ConstitutionalAuthorizer,
    UndeclaredExecutionError,
)
from amos_federation.services.governance.security import DEFAULT_ROLES
from amos_federation.services.government_services.authorization import RegistryAuthorizationError
from amos_federation.services.government_services.models import CaseModel, DecisionModel, ServiceModel
from amos_federation.services.government_services.service import (
    ACTION_CASE_ASSIGN,
    ACTION_CASE_CLOSE,
    ACTION_CASE_DECIDE,
    ACTION_CASE_OPEN,
    ACTION_SERVICE_PUBLISH,
    ACTION_SERVICE_STATUS,
    SERVICE_PUBLISH_SCOPE,
    SERVICE_STATUS_SCOPE,
    CASE_TASK_TYPE,
    CaseStateError,
    DecisionExistsError,
    DuplicateServiceCodeError,
    GovernmentServiceError,
    GovernmentServices,
    reset_government_services,
)
from amos_federation.services.national_registry.models import DecisionProvenanceModel
from amos_federation.services.state_registry.service import StateRegistry, reset_state_registry
from tests.conftest import purge_agents, purge_tasks

GOV_SERVICE_FILE = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "amos_federation"
    / "services"
    / "government_services"
    / "service.py"
)

_ROLE_PERMISSIONS = {role["role_id"]: tuple(role["permissions"]) for role in DEFAULT_ROLES}


def _context(role_id: str, *, username: str = "p5a") -> AuthorizationContext:
    return AuthorizationContext.from_principal(
        Principal.from_session_record(
            session_id=f"p5a-{role_id}-{username}",
            username=f"{username}-{role_id}",
            role_id=role_id,
            permissions=_ROLE_PERMISSIONS[role_id],
            expires_at=None,
            tenant_id=None,
        )
    )


def _code(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def _mandatory_stages() -> set[str]:
    from core.sovereignty.enforcement_boundary import MANDATORY_INTERNAL_STAGES

    return set(MANDATORY_INTERNAL_STAGES)


def _own_body(func: object) -> str:
    """جسدُ الدالّةِ نفسِها دونَ الدوالِّ المُعشَّشةِ داخلَها.

    لأنَّ حرسًا يبحثُ عن نصٍّ في المصدرِ قد يمرُّ بسببِ سطرٍ في دالّةٍ داخليّةٍ لا
    بسببِ ما تفعلُه الدالّةُ المفحوصةُ نفسُها.
    """
    tree = ast.parse(inspect.getsource(func).lstrip())
    node = tree.body[0]
    lines: list[str] = []
    for stmt in node.body:  # type: ignore[attr-defined]
        if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        lines.append(ast.unparse(stmt))
    return "\n".join(lines)


@pytest.fixture(autouse=True)
def _fresh_state() -> None:
    init_db()
    session = get_session_factory()()
    try:
        session.query(DecisionProvenanceModel).delete()
        session.query(DecisionModel).delete()
        session.query(CaseModel).delete()
        session.query(ServiceModel).delete()
        purge_tasks(session)
        purge_agents(session)
        session.commit()
    finally:
        session.close()
    reset_executive_core()
    reset_state_registry()
    reset_government_services()


class RecordingAuthorizer(ConstitutionalAuthorizer):
    """مُصرِّحٌ حقيقيٌّ يسجِّلُ قراراتَه — لا بديلٌ عن البوابةِ ولا تخطٍّ لها."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.decisions: list[tuple[str, str]] = []
        self.results: list[object] = []

    def guard_declared(self, action, target, **kwargs):  # type: ignore[no-untyped-def]
        self.decisions.append((action, target))
        result = super().guard_declared(action, target, **kwargs)
        self.results.append(result)
        return result


@pytest.fixture
def authorizer(tmp_path: Path) -> RecordingAuthorizer:
    return RecordingAuthorizer(idempotency_ledger_path=tmp_path / "P5A-IDEM.json")


@pytest.fixture
def crown() -> AuthorizationContext:
    return _context("king")


@pytest.fixture
def gov(authorizer: RecordingAuthorizer) -> GovernmentServices:
    return GovernmentServices(authorizer=authorizer)


@pytest.fixture
def published(gov: GovernmentServices, crown: AuthorizationContext) -> dict:
    registry = StateRegistry()
    institution = registry.register_institution(
        context=crown,
        code=_code("INST"),
        name="وزارة الخدمات",
        kind="ministry",
        branch="executive",
    )
    service = gov.publish_service(
        context=crown,
        institution_code=institution["code"],
        code=_code("SVC"),
        name="إصدار وثيقة",
    )
    return {"institution_code": institution["code"], "service": service}


def _status_of(service_id: str) -> str | None:
    session = get_session_factory()()
    try:
        row = session.query(ServiceModel).filter(ServiceModel.id == service_id).first()
        return None if row is None else row.status
    finally:
        session.close()


# ── 1. البوابة ────────────────────────────────────────────────────────────


def test_01_status_change_passes_through_the_gateway(
    gov: GovernmentServices,
    crown: AuthorizationContext,
    published: dict,
    authorizer: RecordingAuthorizer,
) -> None:
    """لا كتابةَ حالةٍ إلّا بقرارِ بوابةٍ على الفعلِ والهدفِ نفسِهما."""
    gov.set_service_status(
        context=crown,
        institution_code=published["institution_code"],
        code=published["service"]["code"],
        status="suspended",
        reason="مراجعةٌ إجراءيّة",
    )
    target = (
        f"services/{DEFAULT_TENANT}/{published['institution_code']}/{published['service']['code']}"
    )
    assert (ACTION_SERVICE_STATUS, target) in authorizer.decisions


def test_02_all_mandatory_internal_stages_are_recorded(
    gov: GovernmentServices,
    crown: AuthorizationContext,
    published: dict,
    authorizer: RecordingAuthorizer,
) -> None:
    """المراحلُ الإلزاميّةُ كلُّها مقطوعةٌ — لا مرحلةٌ تُتخطّى بحجّةِ البساطة."""
    result = gov.set_service_status(
        context=crown,
        institution_code=published["institution_code"],
        code=published["service"]["code"],
        status="suspended",
        reason="مراجعةٌ إجراءيّة",
    )
    assert result["status"] == "suspended"
    outcome = authorizer.results[-1].outcome  # type: ignore[union-attr]
    assert _mandatory_stages() <= set(outcome.stages)


# ── 2. التخويل ────────────────────────────────────────────────────────────


def test_03_local_permission_is_still_required_before_the_boundary(
    gov: GovernmentServices, published: dict
) -> None:
    """الصلاحيّةُ المحلّيّةُ لم تُضعَّفْ: مواطنٌ يُرَدُّ قبلَ أيِّ عبورٍ للحدّ."""
    with pytest.raises(RegistryAuthorizationError):
        gov.set_service_status(
            context=_context("citizen"),
            institution_code=published["institution_code"],
            code=published["service"]["code"],
            status="suspended",
            reason="محاولة",
        )
    assert _status_of(published["service"]["id"]) == "active"


def test_04_pre_boundary_invariants_are_unchanged(
    gov: GovernmentServices,
    crown: AuthorizationContext,
    published: dict,
    authorizer: RecordingAuthorizer,
) -> None:
    """المفردةُ المُقيَّدةُ ولزومُ السببِ يُرَدّانِ قبلَ البوابةِ — لا بعدَها."""
    for status, reason in (("ملغاة", "سبب"), ("suspended", "   ")):
        with pytest.raises(GovernmentServiceError):
            gov.set_service_status(
                context=crown,
                institution_code=published["institution_code"],
                code=published["service"]["code"],
                status=status,
                reason=reason,
            )
    # لا يُقاسُ خلوُّ السجلِّ كلِّه: إعلانُ الخدمةِ في التهيئةِ يعبرُ الحدَّ أيضًا منذ
    # P5ب. والمقصودُ أنَّ فعلَ تغييرِ الحالةِ **لم يُعرَضْ على البوابةِ أصلًا**.
    assert ACTION_SERVICE_STATUS not in [action for action, _ in authorizer.decisions]
    assert _status_of(published["service"]["id"]) == "active"


def test_05_a_retired_service_is_not_revived_through_the_boundary(
    gov: GovernmentServices,
    crown: AuthorizationContext,
    published: dict,
    authorizer: RecordingAuthorizer,
) -> None:
    """الخدمةُ المسحوبةُ لا تُعادُ بتغييرِ حالة — والحدُّ لم يُصبِحْ بابًا خلفيًّا."""
    args = {
        "context": crown,
        "institution_code": published["institution_code"],
        "code": published["service"]["code"],
    }
    gov.set_service_status(**args, status="retired", reason="سحبٌ نهائيّ")
    before = len(authorizer.decisions)
    with pytest.raises(GovernmentServiceError):
        gov.set_service_status(**args, status="active", reason="إحياء")
    assert len(authorizer.decisions) == before
    assert _status_of(published["service"]["id"]) == "retired"


# ── 3. الأثرُ المُعلَن ─────────────────────────────────────────────────────


def test_06_declared_effect_matches_the_applied_row(
    gov: GovernmentServices,
    crown: AuthorizationContext,
    published: dict,
    authorizer: RecordingAuthorizer,
) -> None:
    """الأثرُ المُعلَنُ هو الأثرُ المُطبَّقُ على الهدفِ نفسِه — لا أوسعَ ولا أضيق."""
    gov.set_service_status(
        context=crown,
        institution_code=published["institution_code"],
        code=published["service"]["code"],
        status="suspended",
        reason="مراجعة",
    )
    outcome = authorizer.results[-1].outcome  # type: ignore[union-attr]
    target = (
        f"services/{DEFAULT_TENANT}/{published['institution_code']}/{published['service']['code']}"
    )
    assert [effect.signature for effect in outcome.applied_effects] == [f"WRITE:{target}"]
    assert _status_of(published["service"]["id"]) == "suspended"


# ── 4. التعويض ────────────────────────────────────────────────────────────


def test_07_compensation_plan_covers_the_declared_effect(
    gov: GovernmentServices,
    crown: AuthorizationContext,
    published: dict,
    authorizer: RecordingAuthorizer,
) -> None:
    """لكلِّ أثرٍ مُعلَنٍ مُعوِّضٌ في الخطّة — لا أثرٌ بلا طريقِ رجوع."""
    gov.set_service_status(
        context=crown,
        institution_code=published["institution_code"],
        code=published["service"]["code"],
        status="suspended",
        reason="مراجعة",
    )
    outcome = authorizer.results[-1].outcome  # type: ignore[union-attr]
    for effect in outcome.applied_effects:
        assert outcome.compensation_plan.covers(effect.signature)


def test_08_the_compensator_really_restores_the_previous_status(
    gov: GovernmentServices,
    crown: AuthorizationContext,
    published: dict,
    authorizer: RecordingAuthorizer,
) -> None:
    """المُعوِّضُ يعملُ فعلًا: يُنادى فترجعُ الحالةُ السابقةُ إلى الصفِّ — لا `pass`."""
    gov.set_service_status(
        context=crown,
        institution_code=published["institution_code"],
        code=published["service"]["code"],
        status="suspended",
        reason="مراجعة",
    )
    outcome = authorizer.results[-1].outcome  # type: ignore[union-attr]
    signature = outcome.applied_effects[0].signature
    assert _status_of(published["service"]["id"]) == "suspended"
    outcome.compensation_plan.compensator_for(signature).apply()
    assert _status_of(published["service"]["id"]) == "active"


# ── 5. الفشلُ والإعادة ────────────────────────────────────────────────────


def test_09_failure_inside_the_applier_claims_no_success(
    gov: GovernmentServices, crown: AuthorizationContext, published: dict, monkeypatch
) -> None:
    """إذا سقطَ التطبيقُ فلا نتيجةَ تُعادُ ولا نجاحٌ يُدَّعى.

    ولا يُؤكَّدُ هنا أنَّ الإعادةَ بعدَ فشلٍ ستُمنَع: تلك دعوى غيرُ مضمونةٍ حتّى
    يُحسَمَ Q-12، والمؤكَّدُ ما يُملكُ إثباتُه — أنَّ الحالةَ لم تنقلبْ بلا نتيجة.
    """
    # `core` يُدخَلُ إلى المسارِ عندَ استيرادِ الجسرِ لا قبلَه، فالاستيرادُ داخليّ.
    from core.sovereignty.idempotency import IdempotencyError

    monkeypatch.setattr(
        GovernmentServices,
        "_set_service_status_row",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("سقوطُ الكتابة")),
    )
    with pytest.raises(IdempotencyError):
        gov.set_service_status(
            context=crown,
            institution_code=published["institution_code"],
            code=published["service"]["code"],
            status="suspended",
            reason="مراجعة",
        )
    assert _status_of(published["service"]["id"]) == "active"


def test_10_replay_of_the_same_operation_writes_nothing_new(
    gov: GovernmentServices, crown: AuthorizationContext, published: dict
) -> None:
    """نداءٌ ثانٍ بمفتاحِ العمليّةِ نفسِه إعادةٌ مُعلَنةٌ لا كتابةٌ ثانية."""
    args = {
        "context": crown,
        "institution_code": published["institution_code"],
        "code": published["service"]["code"],
        "status": "suspended",
        "reason": "مراجعة",
    }
    first = gov.set_service_status(**args)
    assert first["replayed"] is False
    second = gov.set_service_status(**args)
    assert second["replayed"] is True
    assert second["operation_key"].startswith(SERVICE_STATUS_SCOPE)
    assert _status_of(published["service"]["id"]) == "suspended"


# ── 6. إغلاقُ التجاوزِ والحرسُ الساكن ──────────────────────────────────────


def test_11_no_bypass_parameter_appears_in_the_migrated_operation(
    gov: GovernmentServices,
) -> None:
    """لا مُعامِلَ تجاوزٍ في العمليّةِ المُهاجَرة — لا في نداءِ الحدِّ ولا حولَه."""
    body = _own_body(GovernmentServices.set_service_status)
    for parameter in FORBIDDEN_BYPASS_PARAMS:
        assert parameter not in body


def test_12_the_operation_writes_no_row_outside_the_boundary(
    gov: GovernmentServices,
) -> None:
    """الحرسُ الساكن: جسدُ العمليّةِ نفسِه لا يُثبِّتُ جلسةً ولا يُسنِدُ حالةً.

    ولا يُكتفى بالنظرِ إلى النصِّ: يُقرأُ الجسدُ بعدَ إسقاطِ الدوالِّ المُعشَّشةِ حتّى
    لا يمرَّ الحرسُ لأنَّ الكتابةَ انتقلتْ إلى `_apply` الذي يُنادى **داخلَ** الحدّ.
    """
    body = _own_body(GovernmentServices.set_service_status)
    assert "session.commit()" not in body
    assert "row.status =" not in body
    assert "guard_declared" in body


def test_13_the_legacy_guard_helper_still_refuses_undeclared_execution() -> None:
    """`guard` القديمُ ما زالَ يسقطُ — فلا طريقٌ ثانٍ يُفتَحُ بجانبِ الحدّ."""
    authorizer = ConstitutionalAuthorizer()
    with pytest.raises(UndeclaredExecutionError):
        authorizer.guard("gov.service.status", "services/probe", lambda: None)

# ── 7. إعلانُ الخدمة (P5ب) ────────────────────────────────────────────────


@pytest.fixture
def institution(crown: AuthorizationContext) -> str:
    registry = StateRegistry()
    return registry.register_institution(
        context=crown,
        code=_code("INST"),
        name="وزارة الخدمات",
        kind="ministry",
        branch="executive",
    )["code"]


def _publish(
    gov: GovernmentServices, crown: AuthorizationContext, institution_code: str, code: str, **kw
) -> dict:
    return gov.publish_service(
        context=crown,
        institution_code=institution_code,
        code=code,
        name="إصدار وثيقة",
        **kw,
    )


def test_14_publishing_passes_through_the_gateway_with_all_stages(
    gov: GovernmentServices,
    crown: AuthorizationContext,
    institution: str,
    authorizer: RecordingAuthorizer,
) -> None:
    """إعلانُ الخدمةِ يعبرُ البوابةَ على فعلِه وهدفِه، وتُقطَعُ المراحلُ الإلزاميّةُ كلُّها."""
    code = _code("SVC")
    result = _publish(gov, crown, institution, code)
    target = f"services/{DEFAULT_TENANT}/{institution}/{code}"
    assert (ACTION_SERVICE_PUBLISH, target) in authorizer.decisions
    outcome = authorizer.results[-1].outcome  # type: ignore[union-attr]
    assert _mandatory_stages() <= set(outcome.stages)
    assert outcome.contract.action == ACTION_SERVICE_PUBLISH
    assert outcome.permit_id, "لا إذنَ في الحصيلة — فالعبورُ غيرُ مُثبَت."
    assert result["status"] == "active"


def test_15_declared_effect_is_the_published_service_and_nothing_wider(
    gov: GovernmentServices,
    crown: AuthorizationContext,
    institution: str,
    authorizer: RecordingAuthorizer,
) -> None:
    """الأثرُ المُعلَنُ هدفُ الخدمةِ نفسُه — لا المؤسسةُ ولا المستأجرُ كلُّه."""
    code = _code("SVC")
    _publish(gov, crown, institution, code)
    outcome = authorizer.results[-1].outcome  # type: ignore[union-attr]
    target = f"services/{DEFAULT_TENANT}/{institution}/{code}"
    assert [effect.signature for effect in outcome.applied_effects] == [f"WRITE:{target}"]
    for effect in outcome.contract.declared_effects:
        assert effect.resource == target or effect.resource.startswith(target + "/")


def test_16_the_compensator_really_deletes_the_created_row(
    gov: GovernmentServices,
    crown: AuthorizationContext,
    institution: str,
    authorizer: RecordingAuthorizer,
) -> None:
    """المُعوِّضُ يعملُ فعلًا: يُنادى فيغيبُ الصفُّ من القاعدة — لا `pass` ولا وعد."""
    code = _code("SVC")
    published = _publish(gov, crown, institution, code)
    outcome = authorizer.results[-1].outcome  # type: ignore[union-attr]
    signature = outcome.applied_effects[0].signature
    assert outcome.compensation_plan.covers(signature)
    assert _status_of(published["id"]) == "active"
    outcome.compensation_plan.compensator_for(signature).apply()
    assert _status_of(published["id"]) is None


def test_17_publishing_invariants_are_refused_before_the_gateway(
    gov: GovernmentServices,
    crown: AuthorizationContext,
    institution: str,
    authorizer: RecordingAuthorizer,
) -> None:
    """مدّةٌ غيرُ موجبةٍ وإدارةٌ غيرُ قائمةٍ ورمزٌ مكرَّرٌ — كلُّها تُرَدُّ قبلَ العبور."""
    code = _code("SVC")
    _publish(gov, crown, institution, code)
    before = len(authorizer.decisions)

    with pytest.raises(GovernmentServiceError):
        _publish(gov, crown, institution, _code("SVC"), sla_hours=0)
    with pytest.raises(GovernmentServiceError):
        _publish(gov, crown, institution, _code("SVC"), department_code="DEPT-LA-WUJUD")
    with pytest.raises(GovernmentServiceError):
        _publish(gov, crown, institution, code)

    assert len(authorizer.decisions) == before


def test_18_the_duplicate_code_contract_is_not_broken_by_the_boundary(
    gov: GovernmentServices, crown: AuthorizationContext, institution: str
) -> None:
    """رمزٌ مكرَّرٌ يُخرِجُ `DuplicateServiceCodeError` نفسَه لا خطأَ ذرّيّةٍ ملفوفًا.

    وهذا هو سببُ الفحصِ الصريحِ قبلَ العبور: عقدٌ قائمٌ لا يُكسَرُ بحجّةِ الهجرة.
    """
    code = _code("SVC")
    _publish(gov, crown, institution, code)
    with pytest.raises(DuplicateServiceCodeError):
        _publish(gov, crown, institution, code)


def test_19_local_permission_is_still_required_for_publishing(
    gov: GovernmentServices, institution: str, authorizer: RecordingAuthorizer
) -> None:
    """مواطنٌ لا يُعلِنُ خدمةً — والحدُّ لم يُصبِحْ طريقًا يتخطّى الصلاحيّةَ المحلّيّة."""
    with pytest.raises(RegistryAuthorizationError):
        _publish(gov, _context("citizen"), institution, _code("SVC"))
    assert authorizer.decisions == []


def test_20_an_identical_publication_is_refused_and_no_second_row_appears(
    gov: GovernmentServices, crown: AuthorizationContext, institution: str
) -> None:
    """نداءٌ ثانٍ مطابقٌ يُرَدُّ بحرسِ الرمزِ المكرَّرِ — والصفُّ يبقى واحدًا.

    ولا يُدَّعى هنا أنَّ الإعادةَ (1H) مرئيّةٌ في هذه العمليّة: حرسُ تكرارِ الرمزِ
    القائمُ **قبلَ** الحدِّ يسبقُ مفتاحَ العمليّة، فالنداءُ المطابقُ يُرَدُّ ولا يبلغُ
    البوابةَ ليُعلَنَ إعادةً. وهذا عقدٌ قائمٌ لا أُلغيه لتظهرَ ميزةُ الإعادة: تعطيلُ
    الحرسِ لإثباتِ دعوى هو ما نُهِيَ عنه صريحًا. فالمُثبَتُ ما يُقاسُ: صفٌّ واحدٌ لا
    صفّان، والمفتاحُ باقٍ حرسًا للسباقِ داخلَ الحدّ لا للعرض.
    """
    code = _code("SVC")
    first = _publish(gov, crown, institution, code)
    assert first["replayed"] is False
    with pytest.raises(DuplicateServiceCodeError):
        _publish(gov, crown, institution, code)
    session = get_session_factory()()
    try:
        rows = session.query(ServiceModel).filter(ServiceModel.code == code).count()
    finally:
        session.close()
    assert rows == 1
    assert SERVICE_PUBLISH_SCOPE  # النطاقُ مُعلَنٌ ومستعملٌ في مفتاحِ العمليّة


def test_21_publishing_writes_no_row_outside_the_boundary(gov: GovernmentServices) -> None:
    """الحرسُ الساكن: جسدُ الإعلانِ نفسِه لا يُضيفُ صفًّا ولا يُثبِّتُ جلسة."""
    body = _own_body(GovernmentServices.publish_service)
    assert "session.add(" not in body
    assert "session.commit()" not in body
    assert "guard_declared" in body
    for parameter in FORBIDDEN_BYPASS_PARAMS:
        assert parameter not in body

# ── 8. فتحُ القضيّة: أثرانِ لا أثرٌ واحد (P5ج) ──────────────────────────────


@pytest.fixture
def applicant() -> str:
    """طالبٌ حقيقيٌّ في `agents` — المفتاحُ الأجنبيُّ يفرضُ ذلك ولا يُخترَع."""
    agent_id = f"agent-p5c-{uuid.uuid4().hex[:10]}"
    register_identity(agent_id, f"وكيل {agent_id}", "executor", tenant_id=DEFAULT_TENANT)
    return agent_id


def _open(
    gov: GovernmentServices,
    crown: AuthorizationContext,
    institution_code: str,
    service_code: str,
    applicant_agent_id: str,
    **kw: object,
) -> dict:
    return gov.open_case(
        context=crown,
        institution_code=institution_code,
        service_code=service_code,
        applicant_agent_id=applicant_agent_id,
        subject="طلب وثيقة",
        **kw,  # type: ignore[arg-type]
    )


def _task_row(task_id: str):  # noqa: ANN202
    session = get_session_factory()()
    try:
        return session.query(TaskModel).filter(TaskModel.id == task_id).first()
    finally:
        session.close()


def test_22_opening_a_case_declares_two_effects_not_one(
    gov: GovernmentServices,
    crown: AuthorizationContext,
    published: dict,
    applicant: str,
    authorizer: RecordingAuthorizer,
) -> None:
    """المهمّةُ والصفُّ أثرانِ مُعلَنانِ — ودمجُهما في واحدٍ يُخفي أخطرَ ما يجري."""
    case = _open(
        gov, crown, published["institution_code"], published["service"]["code"], applicant
    )
    outcome = authorizer.results[-1].outcome  # type: ignore[union-attr]
    target = (
        f"services/{DEFAULT_TENANT}/{published['institution_code']}"
        f"/{published['service']['code']}/cases/{case['reference']}"
    )
    signatures = [effect.signature for effect in outcome.applied_effects]
    assert signatures == [f"CREATE:{target}/task", f"CREATE:{target}"]
    assert _mandatory_stages() <= set(outcome.stages)
    assert outcome.contract.action == ACTION_CASE_OPEN


def test_23_the_task_effect_is_a_real_row_in_tasks(
    gov: GovernmentServices, crown: AuthorizationContext, published: dict, applicant: str
) -> None:
    """أثرُ المهمّةِ صفٌّ حقيقيٌّ في `tasks` — لا «عمليّةٌ» بلا أثر."""
    case = _open(
        gov, crown, published["institution_code"], published["service"]["code"], applicant
    )
    row = _task_row(case["task_id"])
    assert row is not None
    assert row.type == CASE_TASK_TYPE


def test_24_both_compensators_are_planned_and_both_really_reverse(
    gov: GovernmentServices,
    crown: AuthorizationContext,
    published: dict,
    applicant: str,
    authorizer: RecordingAuthorizer,
) -> None:
    """لكلِّ أثرٍ مُعوِّضٌ يعملُ فعلًا: الصفُّ يُحذَفُ والمهمّةُ تُلغى في النواة.

    وإلغاءُ المهمّةِ يمرُّ بـ`ExecutiveCore.cancel` لا بكتابةٍ في `tasks`: تغييرُ صفٍّ
    بيدِنا لا يوقفُ عملًا جاريًا، وآلةُ الحالاتِ هي التي تعرفُ ما يُلغى وما لا يُلغى.
    """
    case = _open(
        gov, crown, published["institution_code"], published["service"]["code"], applicant
    )
    outcome = authorizer.results[-1].outcome  # type: ignore[union-attr]
    plan = outcome.compensation_plan
    for effect in outcome.applied_effects:
        assert plan.covers(effect.signature)

    task_signature, case_signature = (
        effect.signature for effect in outcome.applied_effects
    )
    plan.compensator_for(case_signature).apply()
    session = get_session_factory()()
    try:
        assert session.query(CaseModel).filter(CaseModel.id == case["id"]).first() is None
    finally:
        session.close()

    plan.compensator_for(task_signature).apply()
    assert _task_row(case["task_id"]).status == "cancelled"


def test_25_case_invariants_are_refused_before_the_gateway(
    gov: GovernmentServices,
    crown: AuthorizationContext,
    published: dict,
    applicant: str,
    authorizer: RecordingAuthorizer,
) -> None:
    """أولويّةٌ مجهولةٌ وموضوعٌ فارغٌ وطالبٌ لا وجودَ له — كلُّها قبلَ العبور."""
    args = (gov, crown, published["institution_code"], published["service"]["code"])
    before = len(authorizer.decisions)
    with pytest.raises(GovernmentServiceError):
        _open(*args, applicant, priority="عاجلٌ جدًّا")
    with pytest.raises(GovernmentServiceError):
        gov.open_case(
            context=crown,
            institution_code=published["institution_code"],
            service_code=published["service"]["code"],
            applicant_agent_id=applicant,
            subject="   ",
        )
    with pytest.raises(GovernmentServiceError):
        _open(*args, "agent-la-wujud")
    assert len(authorizer.decisions) == before


def test_26_no_case_row_is_written_outside_the_boundary(gov: GovernmentServices) -> None:
    """الحرسُ الساكن: جسدُ فتحِ القضيّةِ لا يُقدِّمُ مهمّةً ولا يُضيفُ صفًّا بنفسِه."""
    body = _own_body(GovernmentServices.open_case)
    assert "self._core.submit(" not in body
    assert "session.add(" not in body
    assert "session.commit()" not in body
    assert "guard_declared" in body
    for parameter in FORBIDDEN_BYPASS_PARAMS:
        assert parameter not in body


def test_27_the_applier_writes_one_effect_per_call(
    gov: GovernmentServices, crown: AuthorizationContext, published: dict, applicant: str
) -> None:
    """قضيّةٌ واحدةٌ ومهمّةٌ واحدةٌ لكلِّ نداء — لا صفَّانِ ولا مهمّتان.

    وهذه ليست دعوى تجميليّة: المُطبِّقُ يُنادى مرّةً لكلِّ أثرٍ مُعلَن، فمُطبِّقٌ
    يفعلُ كلَّ شيءٍ في نداءٍ واحدٍ كانَ يُدخِلُ الصفَّ مرّتين. وقد قِيسَ ذلك خطأً
    حقيقيًّا قبلَ التصحيح، فبقيَ الاختبارُ حرسًا عليه.
    """
    case = _open(
        gov, crown, published["institution_code"], published["service"]["code"], applicant
    )
    session = get_session_factory()()
    try:
        assert (
            session.query(CaseModel).filter(CaseModel.reference == case["reference"]).count() == 1
        )
        assert session.query(TaskModel).filter(TaskModel.id == case["task_id"]).count() == 1
    finally:
        session.close()


# ── 9. إسنادُ القضيّة (P5د) ────────────────────────────────────────────────


@pytest.fixture
def assignable(gov: GovernmentServices, crown: AuthorizationContext, published: dict, applicant: str) -> dict:
    """قضيّةٌ مفتوحةٌ ومنصبٌ قائمٌ في مؤسستِها — الشرطانِ اللذانِ يفرضُهما النطاق."""
    registry = StateRegistry()
    official = registry.appoint_official(
        context=crown,
        agent_id=applicant,
        institution_code=published["institution_code"],
        title="مدير الخدمة",
    )
    case = _open(
        gov, crown, published["institution_code"], published["service"]["code"], applicant
    )
    return {"case": case, "official_id": official["id"]}


def test_28_assignment_passes_the_gateway_with_its_own_effect(
    gov: GovernmentServices,
    crown: AuthorizationContext,
    assignable: dict,
    authorizer: RecordingAuthorizer,
) -> None:
    """الإسنادُ فعلٌ مُعلَنٌ على هدفِ القضيّةِ — لا كتابةٌ في هامشِ فتحِها."""
    reference = assignable["case"]["reference"]
    result = gov.assign_case(
        context=crown, reference=reference, official_id=assignable["official_id"]
    )
    target = f"cases/{DEFAULT_TENANT}/{reference}"
    assert (ACTION_CASE_ASSIGN, target) in authorizer.decisions
    outcome = authorizer.results[-1].outcome  # type: ignore[union-attr]
    assert _mandatory_stages() <= set(outcome.stages)
    assert [effect.signature for effect in outcome.applied_effects] == [
        f"WRITE:{target}/assignment"
    ]
    assert result["status"] == "assigned"
    assert result["assigned_official_id"] == assignable["official_id"]


def test_29_the_assignment_compensator_restores_the_previous_state(
    gov: GovernmentServices,
    crown: AuthorizationContext,
    assignable: dict,
    authorizer: RecordingAuthorizer,
) -> None:
    """المُعوِّضُ يُعيدُ المنصبَ السابقَ والحالةَ السابقةَ معًا — لا الحالةَ وحدَها.

    ولو أُعيدتِ الحالةُ إلى `submitted` وبقيَ المنصبُ مُسنَدًا لكانَ ذلك «تعويضًا»
    يتركُ أثرًا نصفَ قائمٍ ويُبلِّغُ نجاحًا — وهو ما تمنعُه هذه الدعوى.
    """
    reference = assignable["case"]["reference"]
    gov.assign_case(
        context=crown, reference=reference, official_id=assignable["official_id"]
    )
    outcome = authorizer.results[-1].outcome  # type: ignore[union-attr]
    signature = outcome.applied_effects[0].signature
    outcome.compensation_plan.compensator_for(signature).apply()
    session = get_session_factory()()
    try:
        row = session.query(CaseModel).filter(CaseModel.reference == reference).first()
        assert row.assigned_official_id is None
        assert row.status == "submitted"
    finally:
        session.close()


def test_30_assignment_invariants_are_refused_before_the_gateway(
    gov: GovernmentServices,
    crown: AuthorizationContext,
    assignable: dict,
    authorizer: RecordingAuthorizer,
) -> None:
    """منصبٌ لا وجودَ له، ومواطنٌ بلا صلاحيّة — كلاهما يُرَدُّ قبلَ أيِّ عبور."""
    reference = assignable["case"]["reference"]
    before = len(authorizer.decisions)
    with pytest.raises(GovernmentServiceError):
        gov.assign_case(context=crown, reference=reference, official_id="official-la-wujud")
    with pytest.raises(RegistryAuthorizationError):
        gov.assign_case(
            context=_context("citizen"),
            reference=reference,
            official_id=assignable["official_id"],
        )
    assert len(authorizer.decisions) == before


def test_31_assignment_writes_no_row_outside_the_boundary(gov: GovernmentServices) -> None:
    """الحرسُ الساكن: جسدُ الإسنادِ لا يُسنِدُ منصبًا ولا يُثبِّتُ جلسة."""
    body = _own_body(GovernmentServices.assign_case)
    assert "case.assigned_official_id =" not in body
    assert "session.commit()" not in body
    assert "guard_declared" in body
    for parameter in FORBIDDEN_BYPASS_PARAMS:
        assert parameter not in body


# ── 10. إغلاقُ القضيّة (P5هـ) ──────────────────────────────────────────────


@pytest.fixture
def decided(gov: GovernmentServices, crown: AuthorizationContext, assignable: dict) -> dict:
    """قضيّةٌ صدرَ فيها قرارٌ فعلًا — بمسارٍ كاملٍ لا بصفوفٍ مزروعةٍ يدويًّا.

    والعاملُ المؤهَّلُ شرطُ نجاحِ المعالجة: بلا وكيلٍ يقبلُ المهمّةَ تفشلُ فعلًا، وذلك
    سلوكٌ صادقٌ لا يُحتالُ عليه هنا.
    """
    worker_id = f"worker-2b-{uuid.uuid4().hex[:8]}"
    register_identity(worker_id, f"عامل {worker_id}", "worker", allowed_tools=["*"])
    reference = assignable["case"]["reference"]
    gov.assign_case(context=crown, reference=reference, official_id=assignable["official_id"])
    gov.process_case(context=crown, reference=reference)
    gov.decide_case(
        context=crown,
        reference=reference,
        outcome="approved",
        rationale="استُوفيت الشروط",
        official_id=assignable["official_id"],
    )
    return {"reference": reference, "official_id": assignable["official_id"]}


def test_32_closing_a_case_passes_the_gateway(
    gov: GovernmentServices,
    crown: AuthorizationContext,
    decided: dict,
    authorizer: RecordingAuthorizer,
) -> None:
    """الإغلاقُ فعلٌ مُعلَنٌ بأثرِ إغلاقٍ واحدٍ لا كتابةٌ صامتة."""
    reference = decided["reference"]
    result = gov.close_case(context=crown, reference=reference)
    target = f"cases/{DEFAULT_TENANT}/{reference}"
    assert (ACTION_CASE_CLOSE, target) in authorizer.decisions
    outcome = authorizer.results[-1].outcome  # type: ignore[union-attr]
    assert _mandatory_stages() <= set(outcome.stages)
    assert [effect.signature for effect in outcome.applied_effects] == [
        f"WRITE:{target}/closure"
    ]
    assert result["status"] == "closed"


def test_33_the_closure_compensator_reopens_to_the_previous_status(
    gov: GovernmentServices,
    crown: AuthorizationContext,
    decided: dict,
    authorizer: RecordingAuthorizer,
) -> None:
    """المعكوسُ يُعيدُ الحالةَ السابقةَ (`decided`) لا حالةً مُختارةً بذوقِ الكاتب."""
    reference = decided["reference"]
    gov.close_case(context=crown, reference=reference)
    outcome = authorizer.results[-1].outcome  # type: ignore[union-attr]
    signature = outcome.applied_effects[0].signature
    outcome.compensation_plan.compensator_for(signature).apply()
    session = get_session_factory()()
    try:
        row = session.query(CaseModel).filter(CaseModel.reference == reference).first()
        assert row.status == "decided"
    finally:
        session.close()


def test_34_a_case_without_a_decision_is_refused_before_the_gateway(
    gov: GovernmentServices,
    crown: AuthorizationContext,
    assignable: dict,
    authorizer: RecordingAuthorizer,
) -> None:
    """«لا إغلاقَ بلا قرار» منعٌ نطاقيٌّ سابقٌ للعبور — لا خطأٌ ذرّيٌّ مُغلَّف.

    ولو نُقِلَ الشرطُ إلى داخلِ المُطبِّقِ لصارَ `CaseStateError` مُلتفًّا في
    `IdempotencyError`، فيرى المُنادي فشلًا تقنيًّا حيثُ الحقيقةُ حكمٌ نطاقيّ.
    """
    before = len(authorizer.decisions)
    with pytest.raises(CaseStateError):
        gov.close_case(context=crown, reference=assignable["case"]["reference"])
    assert len(authorizer.decisions) == before


def test_35_closure_writes_no_row_outside_the_boundary(gov: GovernmentServices) -> None:
    """الحرسُ الساكن: جسدُ الإغلاقِ لا يُغيِّرُ حالةً ولا يُثبِّتُ جلسة."""
    body = _own_body(GovernmentServices.close_case)
    assert 'case.status = "closed"' not in body
    assert "session.commit()" not in body
    assert "guard_declared" in body
    for parameter in FORBIDDEN_BYPASS_PARAMS:
        assert parameter not in body


# ── 11. القرارُ النهائيّ (P5و) ─────────────────────────────────────────────


@pytest.fixture
def reviewed(gov: GovernmentServices, crown: AuthorizationContext, assignable: dict) -> dict:
    """قضيّةٌ بلغتْ مراجعتُها حالةً نهائيّةً — شرطُ القرارِ الذي لم يُضعَّفْ."""
    worker_id = f"worker-2b-{uuid.uuid4().hex[:8]}"
    register_identity(worker_id, f"عامل {worker_id}", "worker", allowed_tools=["*"])
    reference = assignable["case"]["reference"]
    gov.assign_case(context=crown, reference=reference, official_id=assignable["official_id"])
    gov.process_case(context=crown, reference=reference)
    return {"reference": reference, "official_id": assignable["official_id"]}


def _decide(gov: GovernmentServices, crown: AuthorizationContext, reviewed: dict) -> dict:
    return gov.decide_case(
        context=crown,
        reference=reviewed["reference"],
        outcome="approved",
        rationale="استُوفيت الشروط",
        official_id=reviewed["official_id"],
    )


def test_36_the_decision_declares_two_effects_and_keeps_its_provenance(
    gov: GovernmentServices,
    crown: AuthorizationContext,
    reviewed: dict,
    authorizer: RecordingAuthorizer,
) -> None:
    """صفُّ القرارِ أثرٌ وحالةُ القضيّةِ أثرٌ آخر — وإسنادُ القرارِ يُكتَبُ مع قرارِه."""
    result = _decide(gov, crown, reviewed)
    target = f"cases/{DEFAULT_TENANT}/{reviewed['reference']}"
    assert (ACTION_CASE_DECIDE, target) in authorizer.decisions
    outcome = authorizer.results[-1].outcome  # type: ignore[union-attr]
    assert _mandatory_stages() <= set(outcome.stages)
    assert [effect.signature for effect in outcome.applied_effects] == [
        f"CREATE:{target}/decision",
        f"WRITE:{target}/status",
    ]
    assert result["case"]["status"] == "decided"
    assert result["provenance"]["decision_id"] == result["id"]


def test_37_both_decision_compensators_really_reverse(
    gov: GovernmentServices,
    crown: AuthorizationContext,
    reviewed: dict,
    authorizer: RecordingAuthorizer,
) -> None:
    """حذفُ القرارِ يحذفُ إسنادَه، والحالةُ تعودُ إلى ما كانت — لا نصفَ تراجع."""
    result = _decide(gov, crown, reviewed)
    outcome = authorizer.results[-1].outcome  # type: ignore[union-attr]
    plan = outcome.compensation_plan
    decision_signature, status_signature = (
        effect.signature for effect in outcome.applied_effects
    )
    plan.compensator_for(status_signature).apply()
    plan.compensator_for(decision_signature).apply()

    session = get_session_factory()()
    try:
        assert (
            session.query(DecisionModel).filter(DecisionModel.id == result["id"]).first() is None
        )
        assert (
            session.query(DecisionProvenanceModel)
            .filter(DecisionProvenanceModel.decision_id == result["id"])
            .first()
            is None
        )
        row = session.query(CaseModel).filter(CaseModel.reference == reviewed["reference"]).first()
        assert row.status == "reviewed"
    finally:
        session.close()


def test_38_decision_authority_checks_still_precede_the_gateway(
    gov: GovernmentServices,
    crown: AuthorizationContext,
    reviewed: dict,
    authorizer: RecordingAuthorizer,
) -> None:
    """نتيجةٌ مجهولةٌ وسببٌ فارغٌ وقرارٌ ثانٍ — كلُّها تُرَدُّ قبلَ أيِّ عبورٍ للحدّ."""
    before = len(authorizer.decisions)
    with pytest.raises(GovernmentServiceError):
        gov.decide_case(
            context=crown,
            reference=reviewed["reference"],
            outcome="مقبولٌ جزئيًّا",
            rationale="سبب",
            official_id=reviewed["official_id"],
        )
    with pytest.raises(GovernmentServiceError):
        gov.decide_case(
            context=crown,
            reference=reviewed["reference"],
            outcome="approved",
            rationale="   ",
            official_id=reviewed["official_id"],
        )
    assert len(authorizer.decisions) == before

    _decide(gov, crown, reviewed)
    after_first = len(authorizer.decisions)
    with pytest.raises(DecisionExistsError):
        _decide(gov, crown, reviewed)
    # القرارُ الثاني يُرَدُّ بحكمِ النطاقِ لا بمفتاحِ الذرّيّة: القرارُ الواحدُ نهائيٌّ
    # لأنَّ القانونَ يقولُه، لا لأنَّ المفتاحَ تكرَّر.
    assert len(authorizer.decisions) == after_first


def test_39_the_decision_writes_no_row_outside_the_boundary(
    gov: GovernmentServices,
) -> None:
    """الحرسُ الساكن: جسدُ القرارِ لا يُنشئُ صفًّا ولا يُثبِّتُ جلسةً بنفسِه."""
    body = _own_body(GovernmentServices.decide_case)
    assert "session.add(" not in body
    assert "session.commit()" not in body
    assert 'case.status = "decided"' not in body
    assert "guard_declared" in body
    for parameter in FORBIDDEN_BYPASS_PARAMS:
        assert parameter not in body
