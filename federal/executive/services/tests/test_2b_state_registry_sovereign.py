"""الهدف: إثباتُ هجرةِ عائلةِ `state_registry` إلى حدِّ التنفيذِ السياديّ (2B · P1)

النطاق: `StateRegistry.set_institution_status` (P1أ) — ويُضافُ إليها ما يُهاجَرُ لاحقًا
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-18
تاريخ آخر تعديل: 2026-08-18

هذا الملفُّ لا يُعيدُ اختبارَ 1F–1N ولا يقيسُ تصميمًا، ولا يكتفي بوجودِ استثناء:
القياسُ على **الأثرِ في قاعدةِ البيانات** وعلى **مراحلِ حصيلةِ الحدّ**.

الدعاوى المقيسةُ لكلِّ عمليّةٍ مُهاجَرة:

- S-1 البوّابة: العمليّةُ تعبرُ الحدَّ فعلًا، وحُكمُ البوّابةِ مقروءٌ لا مظنون.
- S-2 المراحل: مراحلُ الحدِّ الإلزاميّةُ كلُّها مرَّت.
- S-3 التخويل: منعُ التخويلِ المحلّيِّ ومنعُ البوّابةِ — كلاهما بلا أثرٍ في القاعدة.
- S-4 الأثر: الحالةُ تتغيّرُ فعلًا في الصفّ، والأثرُ المُعلَنُ تحتَ الهدفِ نفسِه.
- S-5 التعويض: المعوّضُ **عكسٌ حقيقيٌّ** يعيدُ الحالةَ السابقة، لا `pass`.
- S-6 الفشل: الفشلُ داخلَ المُطبِّقِ يُغلِقُ ولا يُدَّعى نجاحًا.
- S-7 الإعادة: مفتاحٌ واحدٌ لا يُنتِجُ أثرًا ثانيًا ولا حدثًا ثانيًا.
- S-8 إغلاقُ التجاوز: لا مسارَ كتابةٍ عامًّا للحالةِ بجانبِ الحدّ.
- S-9 الإنفاذُ الساكن: لا معامَلَ تجاوزٍ ولا بدائيّةٍ سياديّةٍ جديدة.
- S-10 الانحدار: الفحوصُ القائمةُ قبلَ الهجرةِ ما زالت تمنعُ ما كانت تمنعُه.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from amos_federation.common.database import get_session_factory, init_db
from amos_federation.common.principal import (
    DEFAULT_TENANT,
    AuthorizationContext,
    Principal,
)
from amos_federation.services.executive_core.sovereignty_bridge import (
    ConstitutionalAuthorizer,
    GuardedResult,
)
from amos_federation.services.state_registry import service as registry_module
from amos_federation.services.state_registry.models import InstitutionModel
from amos_federation.services.state_registry.service import (
    ACTION_INSTITUTION_STATUS,
    InstitutionNotEmptyError,
    RegistryError,
    StateRegistry,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

_KING_PERMISSIONS = ("*",)
_CITIZEN_PERMISSIONS = ("read:public",)


def _context(role_id: str, permissions: tuple[str, ...]) -> AuthorizationContext:
    """سياقٌ مُتحقَّقٌ منه بدورٍ وصلاحيّاتٍ صريحة — لا ادّعاءَ دورٍ من الطلب."""
    return AuthorizationContext.from_principal(
        Principal.from_session_record(
            session_id=f"2b-{role_id}",
            username=f"user-{role_id}",
            role_id=role_id,
            permissions=permissions,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            tenant_id=DEFAULT_TENANT,
        )
    )


class RecordingAuthorizer(ConstitutionalAuthorizer):
    """المُصرِّحُ نفسُه، يُسجِّلُ حصائلَ الحدِّ ليُقاسَ ما مرَّ فعلًا.

    ليس بدائيّةً جديدةً ولا مسارًا ثانيًا: وراثةٌ لا تلمسُ منطقَ التصريح، غرضُها
    أن يقرأَ الاختبارُ `BoundaryOutcome.stages` من نداءِ الإنتاجِ نفسِه.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.results: list[GuardedResult] = []

    def guard_declared(self, *args: Any, **kwargs: Any) -> GuardedResult:
        result = super().guard_declared(*args, **kwargs)
        self.results.append(result)
        return result


@pytest.fixture(autouse=True)
def _fresh_db() -> None:
    init_db()


@pytest.fixture
def registry(tmp_path: Path) -> tuple[StateRegistry, RecordingAuthorizer]:
    authorizer = RecordingAuthorizer(idempotency_ledger_path=tmp_path / "REG-2B-IDEM.json")
    return StateRegistry(authorizer=authorizer), authorizer


@pytest.fixture
def code() -> str:
    return f"INST-2B-{uuid.uuid4().hex[:8].upper()}"


@pytest.fixture
def institution(registry: tuple[StateRegistry, RecordingAuthorizer], code: str) -> Iterator[str]:
    """مؤسسةٌ نشطةٌ مُؤسَّسةٌ بالمسارِ السياديِّ المُثبَتِ في 2A — لا بحقنٍ في الجدول."""
    service, authorizer = registry
    service.register_institution(
        context=_context("king", _KING_PERMISSIONS),
        code=code,
        name="مؤسسةُ قياسٍ",
        kind="ministry",
        branch="executive",
        mandate="قياسُ هجرةِ تغييرِ الحالة",
    )
    authorizer.results.clear()
    yield code


def _status_of(code: str) -> str | None:
    """الحالةُ من القاعدةِ لا من القيمةِ المُرجَعة — القياسُ على الأثر."""
    session = get_session_factory()()
    try:
        row = session.query(InstitutionModel).filter(InstitutionModel.code == code).first()
        return None if row is None else row.status
    finally:
        session.close()


def _id_of(code: str) -> str:
    session = get_session_factory()()
    try:
        return session.query(InstitutionModel).filter(InstitutionModel.code == code).first().id
    finally:
        session.close()


def _real_denial_verdict() -> Any:
    """حكمُ رفضٍ **حقيقيٌّ** من المحرِّكِ الدستوريِّ نفسِه — لا نصٌّ مُصطنَع.

    يُقرأُ على فعلٍ حصريٍّ لفاعلٍ لا يملكُه (المادة الثالثة · R-003-1)، ويُستعمَلُ
    ليُقاسَ **تصرّفُ الخدمةِ عندَ الرفض**، لا ليُقاسَ الدستورُ من جديد.
    """
    from core.constitutional_engine.engine import ConstitutionalEngine
    from core.constitutional_engine.model import ActionRequest, Branch

    return ConstitutionalEngine().evaluate(
        ActionRequest(actor=Branch.EXECUTIVE, action="allocate_budget", target="probe"),
        record=False,
    )


def _mandatory_stages() -> set[Any]:
    from core.sovereignty.enforcement_boundary import MANDATORY_INTERNAL_STAGES

    return set(MANDATORY_INTERNAL_STAGES)


# ═══════════════════════════════════════════════════════════════════════════
# S-1 · S-2 · S-4 — العبورُ والمراحلُ والأثرُ الحقيقيّ
# ═══════════════════════════════════════════════════════════════════════════


class TestStatusChangeCrossesTheBoundary:
    def test_status_change_writes_row_and_passes_mandatory_stages(
        self,
        registry: tuple[StateRegistry, RecordingAuthorizer],
        institution: str,
    ) -> None:
        """تغييرُ الحالةِ أثرٌ حقيقيٌّ وقعَ **داخلَ** الحدِّ بمراحلِه كلِّها."""
        service, authorizer = registry
        assert _status_of(institution) == "active"

        result = service.set_institution_status(
            context=_context("king", _KING_PERMISSIONS),
            code=institution,
            status="suspended",
            reason="قياسُ العبور",
        )

        assert _status_of(institution) == "suspended", "لم يقعْ أثرٌ في القاعدة."
        assert result["from_status"] == "active"
        assert result["replayed"] is False
        assert len(authorizer.results) == 1, "لم تعبرْ العمليّةُ الحدَّ ولا مرّةً واحدة."

        outcome = authorizer.results[0].outcome
        assert _mandatory_stages() <= set(outcome.stages), (
            f"مرحلةٌ إلزاميّةٌ لم تُمَرّ: {_mandatory_stages() - set(outcome.stages)}"
        )

    def test_declared_effect_stays_within_the_target(
        self,
        registry: tuple[StateRegistry, RecordingAuthorizer],
        institution: str,
    ) -> None:
        """الأثرُ المُعلَنُ تحتَ الهدفِ نفسِه — لا أثرٌ يتسلّلُ إلى موردٍ آخر."""
        service, authorizer = registry
        service.set_institution_status(
            context=_context("king", _KING_PERMISSIONS),
            code=institution,
            status="suspended",
            reason="قياسُ نطاقِ الأثر",
        )
        evidence = authorizer.results[0].evidence
        target = f"institutions/{DEFAULT_TENANT}/{institution}"
        assert evidence.action == ACTION_INSTITUTION_STATUS
        assert evidence.target == target
        # حُكمُ البوّابةِ يُقرأُ لا يُفترَض. وكونُه `ALLOW` لفاعلٍ تنفيذيٍّ نتيجةُ
        # أنَّ الفعلَ مُنطَّقٌ لا حصريٌّ في المادة الثالثة — وهذه حساسيّةُ Q-2
        # المُسجَّلةُ في سجلِّ القرارات، لا اكتشافٌ جديدٌ يُحسَمُ هنا.
        assert evidence.decision == "ALLOW"


# ═══════════════════════════════════════════════════════════════════════════
# S-3 — التخويلُ: منعُ الطبقةِ المحلّيّةِ ومنعُ البوّابةِ بلا أثر
# ═══════════════════════════════════════════════════════════════════════════


class TestUnauthorizedChangesNothing:
    def test_local_authorization_denial_leaves_status_untouched(
        self,
        registry: tuple[StateRegistry, RecordingAuthorizer],
        institution: str,
    ) -> None:
        """التخويلُ المحلّيُّ طبقةٌ أولى لم تُضعَّف ولم تُنقَل إلى الحدّ."""
        service, authorizer = registry
        with pytest.raises(PermissionError):
            service.set_institution_status(
                context=_context("citizen", _CITIZEN_PERMISSIONS),
                code=institution,
                status="suspended",
                reason="محاولةُ مواطن",
            )
        assert _status_of(institution) == "active", "تغيّرت الحالةُ بلا تخويل."
        assert len(authorizer.results) == 0, "عبرت العمليّةُ الحدَّ قبلَ التخويلِ المحلّيّ."

    def test_gateway_denial_leaves_status_untouched(
        self,
        registry: tuple[StateRegistry, RecordingAuthorizer],
        institution: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """حينَ تحكمُ البوّابةُ بالرفضِ لا يقعُ أثر — والكتابةُ داخلَ الحدِّ لا بجانبِه.

        الرفضُ يُحاكى في موضعِه الحقيقيّ (`gateway.decide` — 1D/1F/1J)، لا
        بتعطيلِ الحدِّ ولا باستبدالِه: فالمقيسُ أنَّ الخدمةَ **لا تكتبُ** إذا
        رفضت البوّابة، وهو ما لم يكن مضمونًا قبلَ الهجرة.
        """
        from core.sovereignty.gateway import SovereigntyViolation

        service, authorizer = registry
        gateway = authorizer.boundary.gateway
        # حكمُ الرفضِ **حقيقيٌّ** لا نصٌّ مُصطنَع: يُقرأُ من المحرِّكِ الدستوريِّ
        # نفسِه على فعلٍ حصريٍّ لفاعلٍ لا يملكُه (المادة الثالثة · R-003-1)، ثمّ
        # يُجعَلُ حكمَ هذا النداء. فالمقيسُ هو تصرّفُ الخدمةِ عند الرفض.
        denial = _real_denial_verdict()
        assert denial.decision.name == "DENY", "لم يُقرأْ حكمُ رفضٍ حقيقيٌّ من الدستور."

        def _deny(*_args: Any, **_kwargs: Any) -> None:
            raise SovereigntyViolation(denial)

        monkeypatch.setattr(gateway, "decide", _deny)
        with pytest.raises(SovereigntyViolation):
            service.set_institution_status(
                context=_context("king", _KING_PERMISSIONS),
                code=institution,
                status="dissolved",
                reason="رفضٌ متوقَّع",
            )
        assert _status_of(institution) == "active", "وقعَ أثرٌ رغمَ رفضِ البوّابة."


# ═══════════════════════════════════════════════════════════════════════════
# S-5 — التعويضُ عكسٌ حقيقيّ
# ═══════════════════════════════════════════════════════════════════════════


class TestCompensationIsReal:
    def test_compensator_restores_the_previous_status(
        self,
        registry: tuple[StateRegistry, RecordingAuthorizer],
        institution: str,
    ) -> None:
        """المعوّضُ يُعيدُ الحالةَ السابقةَ في الصفِّ فعلًا — لا يسجّلُ نيّةً."""
        service, _ = registry
        service.set_institution_status(
            context=_context("king", _KING_PERMISSIONS),
            code=institution,
            status="suspended",
            reason="قياسُ التعويض",
        )
        assert _status_of(institution) == "suspended"

        # العكسُ متاحٌ بالأداةِ نفسِها التي رُبِطت معوّضًا في خطّةِ التعويضِ (1I).
        assert service._set_institution_status_row(_id_of(institution), "active") is True  # noqa: SLF001
        assert _status_of(institution) == "active", "المعوّضُ لم يعكسْ شيئًا."

    def test_compensation_plan_covers_the_declared_effect(
        self,
        registry: tuple[StateRegistry, RecordingAuthorizer],
        institution: str,
    ) -> None:
        """خطّةُ التعويضِ تغطّي بصمةَ الأثرِ المُعلَن — لا أثرٌ بلا عكسٍ مربوط."""
        service, authorizer = registry
        service.set_institution_status(
            context=_context("king", _KING_PERMISSIONS),
            code=institution,
            status="suspended",
            reason="قياسُ خطّةِ التعويض",
        )
        outcome = authorizer.results[0].outcome
        plan = outcome.compensation_plan
        assert plan is not None, "لم تُبنَ خطّةُ تعويضٍ للأثر."
        applied = set(outcome.applied_signatures)
        assert applied, "لم يُطبَّقْ أثرٌ — فالقياسُ على تغطيتِه لا معنى له."
        assert applied <= plan.covered_signatures, (
            f"أثرٌ واقعٌ بلا معوّضٍ مربوط: {applied - plan.covered_signatures}"
        )
        # والمعوّضُ المربوطُ ليس وصفًا: يُنادى فعلًا فيعيدُ الحالةَ السابقة.
        entry = plan.compensator_for(next(iter(applied)))
        assert entry.apply() is True
        assert _status_of(institution) == "active", "المعوّضُ المربوطُ لم يعكسْ شيئًا."


# ═══════════════════════════════════════════════════════════════════════════
# S-6 — الفشلُ يُغلِقُ ولا يُدَّعى نجاحًا
# ═══════════════════════════════════════════════════════════════════════════


class TestFailureIsFailClosed:
    def test_failure_inside_applier_does_not_claim_success(
        self,
        registry: tuple[StateRegistry, RecordingAuthorizer],
        institution: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """سقوطُ التدقيقِ بعدَ وقوعِ الأثر: إغلاقٌ صريحٌ ولا حصيلةَ نجاح.

        وهذا قياسُ سلوكٍ **قائمٍ** من 1M/1N لا سلوكٍ جديد: الحدُّ يُغلِقُ على
        الفشلِ ولا يُشغِّلُ المعوّضَ تلقائيًّا، فالأثرُ يبقى واقعًا والعمليّةُ
        غيرَ مُثبَّتةٍ ناجحة — دَينٌ مُعلَنٌ لا إنجازٌ يُزعَم.
        """
        from core.sovereignty.idempotency import IdempotencyError

        service, authorizer = registry

        def _explode(*_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError("سقوطُ التدقيقِ بعدَ وقوعِ الأثر")

        monkeypatch.setattr(registry_module, "record_domain_trace", _explode)
        with pytest.raises((IdempotencyError, RuntimeError)) as failure:
            service.set_institution_status(
                context=_context("king", _KING_PERMISSIONS),
                code=institution,
                status="suspended",
                reason="فشلٌ بعدَ الأثر",
                change_id="s6",
            )
        assert "نجَح" not in str(failure.value), "ادُّعيَ نجاحٌ في نصِّ الفشل."
        assert _status_of(institution) == "suspended", (
            "الأثرُ لم يقعْ قبلَ الفشلِ — فالقياسُ التالي لا معنى له."
        )
        assert len(authorizer.results) == 0, "أُرجِعت حصيلةُ نجاحٍ من نداءٍ فاشل."

        # والعمليّةُ لم تُثبَّت ناجحةً: محاولةُ إعادتِها تُغلِقُ صريحًا (1F/1H)
        # ولا تُنتِجُ أثرًا ثانيًا ولا تُرجِعُ «إعادةً» صامتة.
        monkeypatch.undo()
        with pytest.raises(IdempotencyError):
            service.set_institution_status(
                context=_context("king", _KING_PERMISSIONS),
                code=institution,
                status="suspended",
                reason="فشلٌ بعدَ الأثر",
                change_id="s6",
            )


# ═══════════════════════════════════════════════════════════════════════════
# S-7 — الإعادةُ لا تُنتِجُ أثرًا ثانيًا
# ═══════════════════════════════════════════════════════════════════════════


class TestReplayProducesNoSecondEffect:
    def test_same_change_key_changes_status_once(
        self,
        registry: tuple[StateRegistry, RecordingAuthorizer],
        institution: str,
    ) -> None:
        """مفتاحٌ واحدٌ = أثرٌ واحد: الإعادةُ تُعلَنُ إعادةً ولا تُعيدُ الكتابة."""
        service, authorizer = registry
        king = _context("king", _KING_PERMISSIONS)
        first = service.set_institution_status(
            context=king,
            code=institution,
            status="suspended",
            reason="مرّةٌ واحدة",
            change_id="s7",
        )
        assert first["replayed"] is False
        assert _status_of(institution) == "suspended"

        # عُدَّت الحالةُ يدويًّا إلى `active` بأداةِ الصفِّ نفسِها ليُقاسَ أنَّ
        # الإعادةَ **لا تكتب**: لو أعادت الكتابةَ لعادت `suspended`.
        service._set_institution_status_row(_id_of(institution), "active")  # noqa: SLF001

        second = service.set_institution_status(
            context=king,
            code=institution,
            status="suspended",
            reason="مرّةٌ واحدة",
            change_id="s7",
        )
        assert second["replayed"] is True, "لم تُعلَنِ الإعادةُ إعادةً."
        assert _status_of(institution) == "active", "أُنتِجَ أثرٌ ثانٍ لمفتاحٍ واحد."

    def test_distinct_operations_on_distinct_targets_are_not_replays(
        self,
        registry: tuple[StateRegistry, RecordingAuthorizer],
    ) -> None:
        """تغييرانِ على مؤسستينِ مختلفتينِ عمليّتانِ مختلفتانِ لا إعادةٌ واحدة."""
        service, _ = registry
        king = _context("king", _KING_PERMISSIONS)
        codes = []
        for _ in range(2):
            code = f"INST-2B-{uuid.uuid4().hex[:8].upper()}"
            service.register_institution(
                context=king,
                code=code,
                name="مؤسسةُ قياسٍ",
                kind="ministry",
                branch="executive",
            )
            codes.append(code)
        for code in codes:
            result = service.set_institution_status(
                context=king, code=code, status="suspended", reason="قياسُ الاستقلال"
            )
            assert result["replayed"] is False, "عُدَّت عمليّةٌ على هدفٍ آخرَ إعادةً."
            assert _status_of(code) == "suspended"

    def test_permit_identity_has_one_second_granularity(self) -> None:
        """**قيدٌ مكتشَفٌ لا إنجازٌ**: هويّةُ الإذنِ (1F) دقّتُها ثانيةٌ واحدة.

        قياسٌ **حتميٌّ** على النواةِ نفسِها لا رهنَ توقيتِ تشغيل:

        - بصمةُ الأثرِ `kind:resource` — والتفصيلُ مُستثنًى بنصِّ المصدر، فأثرانِ
          يختلفانِ في التفصيلِ وحدَه بصمتُهما واحدة.
        - `contract_id = sha256(actor|action|target|fingerprint|بصماتُ الآثار)` —
          فعقدانِ بمضمونٍ واحدٍ رقمُهما واحد.
        - `permit_id = EP-{contract_id}-{ثانية}` — فالإذنانِ في الثانيةِ نفسِها
          إذنٌ واحد، وسجلُّ الأذونِ المُستهلَكةِ يرفضُ الثاني.

        الأثرُ في البرنامج: عمليّتانِ سياديّتانِ **مختلفتانِ** على الفاعلِ والفعلِ
        والهدفِ والموردِ نفسِها في الثانيةِ نفسِها لا تمرّانِ معًا، ولو اختلفَ
        مفتاحُ الذرّيّةِ (1H). وهو قيدٌ **قائمٌ منذ 2A** لا أحدثَته هجرةُ P1أ:
        قِيسَ على `state_runtime.allocate_budget` فسلكَ السلوكَ نفسَه. ومُسجَّلٌ
        قرارًا سياديًّا معلَّقًا (Q-11) في
        `docs/audit/SOVEREIGN_DECISION_REGISTER.md`، لأنَّ تغييرَ هويّةِ الإذنِ
        تغييرٌ في عقدِ 1F لا يجوزُ لمُنفِّذٍ أن يُقرِّرَه.
        """
        from datetime import datetime

        from cryptography.hazmat.primitives.asymmetric import ed25519

        from core.sovereignty.contract import EffectKind, SovereignEffect, bind_contract
        from core.sovereignty.enforcement import issue_permit

        target = f"institutions/{DEFAULT_TENANT}/INST-PROBE"
        shape = {
            "actor": "EXECUTIVE",
            "action": ACTION_INSTITUTION_STATUS,
            "target": target,
            "request_fingerprint": "fp",
        }

        def _effect(detail: str) -> SovereignEffect:
            return SovereignEffect(
                kind=EffectKind.WRITE, resource=f"{target}/status", detail=detail
            )

        first = bind_contract(declared_effects=(_effect("active ← suspended"),), **shape)
        second = bind_contract(declared_effects=(_effect("suspended ← active"),), **shape)
        assert first.contract_id == second.contract_id, (
            "تغيّرَ رقمُ العقدِ بتغيّرِ التفصيل — فوصفُ القيدِ أعلاه صارَ غيرَ صحيح."
        )

        moment = datetime.fromisoformat("2026-08-18T12:00:00+00:00")
        key = ed25519.Ed25519PrivateKey.generate()
        permits = [
            issue_permit(
                contract=contract,
                request_fingerprint="fp",
                decision="ALLOW",
                ledger_entry_hash=None,
                private_key=key,
                now=moment,
            ).permit_id
            for contract in (first, second)
        ]
        assert permits[0] == permits[1], (
            "اختلفَ الإذنانِ في الثانيةِ نفسِها — فالقيدُ المُوثَّقُ لم يعدْ قائمًا."
        )

    def test_two_distinct_transitions_on_one_target_show_the_constraint(
        self,
        registry: tuple[StateRegistry, RecordingAuthorizer],
        institution: str,
    ) -> None:
        """أثرُ القيدِ على المسارِ الإنتاجيّ — بفرعيهِ صريحينِ لا بأحدِهما.

        الفرعُ الأوّلُ (إعادةٌ في الثانيةِ نفسِها): تُرفَضُ ولا يقعُ أثرٌ ثانٍ.
        الفرعُ الثاني (ثانيةٌ جديدة): تمرُّ ويقعُ الأثر. وكِلا الفرعينِ مقيسٌ،
        فلا يُثبَّتُ ادّعاءٌ يصحُّ بالتوقيتِ وحدَه — وهذا الخللُ بعينُه صُحِّحَ في
        اختبارِ G-7 من 2A بعدَ أن تبيّنَ أنّه كان ينجحُ بالتوقيت.
        """
        from core.sovereignty.idempotency import IdempotencyError

        service, _ = registry
        king = _context("king", _KING_PERMISSIONS)
        service.set_institution_status(
            context=king, code=institution, status="suspended", reason="أوّل"
        )
        assert _status_of(institution) == "suspended"
        try:
            second = service.set_institution_status(
                context=king, code=institution, status="active", reason="ثانٍ"
            )
        except IdempotencyError as refusal:
            assert "استُهلِك" in str(refusal), (
                "الرفضُ لم يكنْ لاستهلاكِ الإذن — فوصفُ القيدِ صارَ غيرَ صحيح."
            )
            assert _status_of(institution) == "suspended", "وقعَ أثرٌ رغمَ رفضِ الإذن."
        else:
            assert second["replayed"] is False
            assert _status_of(institution) == "active"


# ═══════════════════════════════════════════════════════════════════════════
# S-8 · S-9 — إغلاقُ التجاوزِ والإنفاذُ الساكن
# ═══════════════════════════════════════════════════════════════════════════


class TestNoBypassPathRemains:
    def test_institution_status_is_mutated_from_one_function_only(self) -> None:
        """كتابةُ حالةِ **المؤسسةِ** في دالّةٍ واحدةٍ فقط — قياسٌ بالبنيةِ لا بالنصّ.

        العدُّ النصّيُّ لا يكفي: `revoke_official` يكتبُ حالةَ **مسؤولٍ** لا حالةَ
        مؤسسة، فخلطُهما يُنتِجُ إنذارًا كاذبًا أو طمأنينةً كاذبة. فيُقاسُ الأمرُ
        بشجرةِ المصدر: أيُّ دالّةٍ تُسنِدُ `status` على صفِّ مؤسسة.
        """
        import ast

        source = Path(registry_module.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        writers: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            segment = ast.get_source_segment(source, node) or ""
            if "row.status = status" in segment or 'row.status = "dissolved"' in segment:
                writers.append(node.name)
        assert writers == ["_set_institution_status_row"], (
            f"مواضعُ كتابةٍ لحالةِ المؤسسةِ غيرُ متوقَّعة: {writers}"
        )

    def test_no_public_status_write_outside_the_guarded_operation(self) -> None:
        """المسارُ العامُّ الوحيدُ لتغييرِ الحالةِ هو العمليّةُ التي تعبرُ الحدَّ."""
        source = Path(registry_module.__file__).read_text(encoding="utf-8")
        # الكتابةُ الوحيدةُ في معاونةٍ **خاصّةٍ** (تبدأُ بشُرطةٍ سفليّة)، وتُنادى
        # من المُطبِّقِ داخلَ الحدِّ ومن المعوّض. فلا دالّةَ عامّةٌ تكتبُ الحالة.
        assert re.search(r"def _set_institution_status_row\(", source)
        guarded_call = source.index("ACTION_INSTITUTION_STATUS,\n            target,")
        assert guarded_call > 0, "لا نداءَ محروسًا لفعلِ تغييرِ الحالة."

    def test_no_forbidden_bypass_parameter_in_the_migrated_operation(self) -> None:
        """لا معامَلَ تجاوزٍ أُدخِل لتسهيلِ الهجرة."""
        import inspect

        from amos_federation.services.executive_core.sovereignty_bridge import (
            FORBIDDEN_BYPASS_PARAMS,
        )

        signature = inspect.signature(StateRegistry.set_institution_status)
        assert not (set(signature.parameters) & FORBIDDEN_BYPASS_PARAMS)

    def test_no_new_sovereignty_primitive_was_defined(self) -> None:
        """لم تُخلَقْ بدائيّةٌ سياديّةٌ جديدةٌ لتسهيلِ الهجرة."""
        source = Path(registry_module.__file__).read_text(encoding="utf-8")
        for name in re.findall(r"^class\s+(\w+)", source, flags=re.MULTILINE):
            assert not re.search(
                r"Boundary|Authorizer|Gateway|Idempotenc|Compensat|Jurisdiction", name
            ), f"بدائيّةٌ سياديّةٌ جديدة: {name}"


# ═══════════════════════════════════════════════════════════════════════════
# S-10 — الانحدار: ما كان يُمنَعُ ما زالَ يُمنَع
# ═══════════════════════════════════════════════════════════════════════════


class TestPreMigrationRulesStillHold:
    def test_unknown_status_is_still_refused_before_the_boundary(
        self,
        registry: tuple[StateRegistry, RecordingAuthorizer],
        institution: str,
    ) -> None:
        service, authorizer = registry
        with pytest.raises(RegistryError):
            service.set_institution_status(
                context=_context("king", _KING_PERMISSIONS),
                code=institution,
                status="نصفُ نشطة",
                reason="حالةٌ مجهولة",
            )
        assert _status_of(institution) == "active"
        assert len(authorizer.results) == 0, "عبرَ فحصُ النطاقِ إلى الحدِّ بلا داعٍ."

    def test_dissolved_institution_is_not_revived(
        self,
        registry: tuple[StateRegistry, RecordingAuthorizer],
        institution: str,
    ) -> None:
        service, _ = registry
        king = _context("king", _KING_PERMISSIONS)
        service.set_institution_status(
            context=king, code=institution, status="dissolved", reason="حلٌّ نظيف"
        )
        assert _status_of(institution) == "dissolved"
        with pytest.raises(RegistryError):
            service.set_institution_status(
                context=king, code=institution, status="active", reason="محاولةُ إحياء"
            )
        assert _status_of(institution) == "dissolved", "أُحيِيت مؤسسةٌ محلولة."

    def test_dissolve_is_refused_while_an_active_department_remains(
        self,
        registry: tuple[StateRegistry, RecordingAuthorizer],
        institution: str,
    ) -> None:
        service, _ = registry
        king = _context("king", _KING_PERMISSIONS)
        service.create_department(
            context=king,
            institution_code=institution,
            code=f"DEP-{uuid.uuid4().hex[:6].upper()}",
            name="إدارةٌ نشطة",
        )
        with pytest.raises(InstitutionNotEmptyError):
            service.set_institution_status(
                context=king, code=institution, status="dissolved", reason="حلٌّ غيرُ نظيف"
            )
        assert _status_of(institution) == "active", "حُلَّت مؤسسةٌ تحتها إدارةٌ نشطة."
