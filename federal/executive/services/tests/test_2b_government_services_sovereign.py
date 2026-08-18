"""
اختباراتُ 2B — سياديّةُ الخدماتِ الحكوميّة: تغييرُ حالةِ الخدمة
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
from amos_federation.common.database import get_session_factory, init_db
from amos_federation.common.principal import DEFAULT_TENANT, AuthorizationContext, Principal
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
    ACTION_SERVICE_STATUS,
    SERVICE_STATUS_SCOPE,
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
    assert authorizer.decisions == []
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
