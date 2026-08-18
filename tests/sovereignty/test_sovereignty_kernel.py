"""الهدف: إثبات أن السيادة الملكية محمية فعليًا — لا وكيل ولا نظام يعدّلها أو يتجاوزها.

المالك: tests/sovereignty/ — التاج
تاريخ الإنشاء: 2026-08-16
تاريخ آخر تعديل: 2026-08-16

كل اختبار هنا يمثّل هجومًا محتملًا على العرش، ويُثبت أن الهجوم يفشل.
"""

from __future__ import annotations

import inspect
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519

from core.constitutional_engine.engine import ConstitutionalEngine
from core.constitutional_engine.ledger import ConstitutionalLedger
from core.constitutional_engine.model import ActionRequest, Branch, Severity
from core.constitutional_engine.rules import RULES
from core.sovereignty.crown import (
    Crown,
    CrownError,
    CrownNotProvisionedError,
    CrownTamperError,
    crown_is_provisioned,
    load_crown,
    provision_crown,
)
from core.sovereignty.decree import (
    DecreeRegistry,
    DecreeReplayError,
    DecreeSignatureError,
    RoyalDecree,
    sign_decree,
)
from core.sovereignty.security_events import SecurityEventKind
from core.sovereignty.gateway import (
    FORBIDDEN_BYPASS_PARAMS,
    SovereignGateway,
    SovereigntyViolation,
)
from core.sovereignty.prerogatives import (
    FEDERALISM_BYPASS_ACTIONS,
    IMMUNE_CLAUSES,
    ROYAL_AUTHORITY_EROSION_ACTIONS,
    ROYAL_EXCLUSIVE_ACTIONS,
    bypasses_federalism,
    immune_clauses_touched,
    is_royal_exclusive,
    touches_royal_authority,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
NOW = datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ═══════════════════════════════════════════════════════════════════════════
# أدوات: ملك اختباري بمفتاح حقيقي
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture()
def royal_keypair() -> tuple[ed25519.Ed25519PrivateKey, Crown]:
    private = ed25519.Ed25519PrivateKey.generate()
    from cryptography.hazmat.primitives import serialization

    public_hex = (
        private.public_key()
        .public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        .hex()
    )
    crown = Crown(
        key_id="crown-test",
        public_key_hex=public_hex,
        provisioned_at=NOW,
        holder="الملك",
    )
    return private, crown


def make_decree(
    private: ed25519.Ed25519PrivateKey,
    action: str,
    *,
    target: str | None = None,
    targets: tuple[str, ...] = (),
    decree_id: str = "DEC-TEST-001",
    key_id: str = "crown-test",
) -> RoyalDecree:
    unsigned = RoyalDecree(
        decree_id=decree_id,
        action=action,
        target=target,
        targets=targets,
        issued_at=NOW,
        justification="اختبار",
        key_id=key_id,
    )
    return sign_decree(unsigned, private)


@pytest.fixture()
def engine(tmp_path: Path) -> ConstitutionalEngine:
    return ConstitutionalEngine(ledger=ConstitutionalLedger(tmp_path / "l.jsonl"))


@pytest.fixture()
def gateway(engine: ConstitutionalEngine) -> SovereignGateway:
    return SovereignGateway(engine)


def deny_reasons(engine: ConstitutionalEngine, request: ActionRequest) -> str:
    verdict = engine.evaluate(request)
    assert not verdict.allowed, f"كان يجب رفض «{request.action}» ولم يُرفض."
    return verdict.explain()


# ═══════════════════════════════════════════════════════════════════════════
# 1. المادة العاشرة موجودة وسارية ومحروسة
# ═══════════════════════════════════════════════════════════════════════════

class TestArticleTenExists:
    def test_article_010_is_in_force(self) -> None:
        from core.constitutional_engine.articles import load_articles

        articles = {a.article_id: a for a in load_articles()}
        assert "A010" in articles, "المادة العاشرة مفقودة من الدستور."
        assert articles["A010"].in_force

    def test_article_010_declares_monarchy(self) -> None:
        text = (REPO_ROOT / "core/constitution/articles/010-royal-sovereignty.md").read_text(
            encoding="utf-8"
        )
        for phrase in ("ملكية دستورية فدرالية", "السيادة المطلقة", "الوحيدة المخوَّلة"):
            assert phrase in text, f"نص المادة العاشرة لا يذكر «{phrase}»."

    def test_article_010_has_at_least_seven_rules(self) -> None:
        royal = [r for r in RULES if r.article_id == "A010"]
        assert len(royal) >= 7
        assert {r.rule_id for r in royal} >= {f"R-010-{i}" for i in range(1, 8)}

    def test_royal_rules_are_fundamental_or_critical(self) -> None:
        for rule in (r for r in RULES if r.article_id == "A010"):
            assert rule.severity in (Severity.FUNDAMENTAL, Severity.CRITICAL)

    def test_amendment_decree_is_recorded(self) -> None:
        amd = REPO_ROOT / "core/constitution/amendments/AMD-001-royal-sovereignty.md"
        assert amd.exists(), "المرسوم المُنشئ للمادة العاشرة غير مسجَّل."
        text = amd.read_text(encoding="utf-8")
        assert "الملك" in text and "AMD-001" in text

    def test_article_010_seal_is_registered(self) -> None:
        seals = json.loads(
            (REPO_ROOT / "core/constitution/ARTICLE_SEALS.json").read_text(encoding="utf-8")
        )
        entries = seals.get("seals", seals)
        assert "A010" in entries, "المادة العاشرة بلا بصمة مسجَّلة."


# ═══════════════════════════════════════════════════════════════════════════
# 2. الاختصاص الملكي الحصري — لا مؤسسة تملكه
# ═══════════════════════════════════════════════════════════════════════════

class TestRoyalExclusiveAuthority:
    @pytest.mark.parametrize(
        "actor",
        [
            Branch.LEGISLATIVE,
            Branch.EXECUTIVE,
            Branch.JUDICIAL,
            Branch.TREASURY,
            Branch.AGENT,
            Branch.SYSTEM,
            Branch.HUMAN,
        ],
    )
    @pytest.mark.parametrize(
        "action",
        ["amend_constitution", "create_state", "grant_authority", "dissolve_council", "pardon"],
    )
    def test_no_institution_may_exercise_royal_authority(
        self, engine: ConstitutionalEngine, actor: Branch, action: str
    ) -> None:
        explanation = deny_reasons(engine, ActionRequest(actor=actor, action=action))
        assert "A010" in explanation

    def test_full_council_majority_cannot_amend_constitution(
        self, engine: ConstitutionalEngine
    ) -> None:
        """أغلبية كاملة وإجراء مثالي — ويبقى الرفض بلا مرسوم ملكي."""
        explanation = deny_reasons(
            engine,
            ActionRequest(
                actor=Branch.LEGISLATIVE,
                action="amend_constitution",
                target="some_procedural_clause",
                review_days=3650,
                council_approval_pct=100.0,
                human_approved=True,
                human_signature="sig",
                approving_branches=(
                    Branch.LEGISLATIVE,
                    Branch.EXECUTIVE,
                    Branch.JUDICIAL,
                    Branch.TREASURY,
                ),
            ),
        )
        assert "R-010-1" in explanation or "R-010-6" in explanation

    def test_every_royal_exclusive_action_is_denied_for_agents(
        self, engine: ConstitutionalEngine
    ) -> None:
        """لا فعل واحد من الاختصاص الحصري يمر لوكيل. تُفحَص القائمة كلها."""
        for action in sorted(ROYAL_EXCLUSIVE_ACTIONS):
            verdict = engine.evaluate(ActionRequest(actor=Branch.AGENT, action=action))
            assert not verdict.allowed, f"الفعل «{action}» مرّ لوكيل."
            assert "A010" in verdict.blocking_articles, f"«{action}» لم تُوقفه المادة العاشرة."

    def test_is_royal_exclusive_helper(self) -> None:
        assert is_royal_exclusive("amend_constitution")
        assert not is_royal_exclusive("execute_task")


# ═══════════════════════════════════════════════════════════════════════════
# 3. حصانة السلطة الملكية من التآكل — أخطر باب
# ═══════════════════════════════════════════════════════════════════════════

class TestRoyalAuthorityImmunity:
    @pytest.mark.parametrize("action", sorted(ROYAL_AUTHORITY_EROSION_ACTIONS))
    @pytest.mark.parametrize("actor", [Branch.AGENT, Branch.SYSTEM, Branch.LEGISLATIVE])
    def test_no_actor_may_erode_royal_authority(
        self, engine: ConstitutionalEngine, action: str, actor: Branch
    ) -> None:
        explanation = deny_reasons(engine, ActionRequest(actor=actor, action=action))
        assert "A010" in explanation

    def test_the_king_himself_cannot_abolish_royal_authority(
        self, engine: ConstitutionalEngine
    ) -> None:
        """المرسوم الذي يهدم مصدر سلطته يُرفض — حمايةً من مرسوم مُنتحَل أو منتزَع."""
        explanation = deny_reasons(
            engine,
            ActionRequest(actor=Branch.ROYAL, action="abolish_royal_authority"),
        )
        assert "R-010-2" in explanation
        assert "إكراه" in explanation or "مُنتحَل" in explanation

    @pytest.mark.parametrize(
        "action",
        ["modify_royal_authority", "delete_crown_key", "transfer_king", "seize_throne"],
    )
    def test_mutating_verb_on_protected_target_is_caught(
        self, engine: ConstitutionalEngine, action: str
    ) -> None:
        """الكشف لا يعتمد على قائمة أسماء فقط — فعل تعديلي على هدف محمي يُكشف."""
        target = {
            "modify_royal_authority": "royal_authority",
            "delete_crown_key": "crown_key",
            "transfer_king": "king",
            "seize_throne": "throne",
        }[action]
        explanation = deny_reasons(
            engine, ActionRequest(actor=Branch.AGENT, action=action, target=target)
        )
        assert "A010" in explanation

    def test_reading_royal_authority_is_not_a_violation(
        self, engine: ConstitutionalEngine
    ) -> None:
        """القاعدة تمنع المساس لا القراءة — لا تُوسّع بلا داعٍ."""
        verdict = engine.evaluate(
            ActionRequest(actor=Branch.AGENT, action="read_royal_authority", target="royal_authority")
        )
        assert "A010" not in verdict.blocking_articles

    def test_touches_royal_authority_requires_protected_target(self) -> None:
        assert not touches_royal_authority("modify_config", "some_unrelated_target")
        assert not touches_royal_authority("modify_config", None)
        assert touches_royal_authority("modify_config", "ROYAL_AUTHORITY")

    def test_immune_clauses_cover_sovereignty_itself(self) -> None:
        assert {
            "royal_sovereignty",
            "royal_exclusive_authority",
            "royal_authority_immunity",
            "federalism_non_bypass",
        } <= IMMUNE_CLAUSES

    def test_immunity_removal_is_blocked_for_subordinates(
        self, engine: ConstitutionalEngine
    ) -> None:
        """هجوم بخطوتين من طرف تابع: ألغِ الحصانة أولًا. الخطوة الأولى تفشل.

        نُقِض هذا الاختبار جزئيًّا في E2.1 (AMD-002). كان يفترض أن مرسومًا ملكيًّا
        صحيح التوقيع يُرفض إن مسّ بند حصانة — وذلك كان سلطةً فوق الملك. الحصانة
        صارت مانعًا للتابعين وحدهم، وهذا ما يُثبته الاختبار الآن.
        """
        explanation = deny_reasons(
            engine,
            ActionRequest(
                actor=Branch.EXECUTIVE,
                action="amend_constitution",
                target="royal_authority_immunity",
            ),
        )
        assert "R-010" in explanation or "R-005" in explanation

    def test_immunity_touching_decree_by_the_crown_executes_and_is_flagged(
        self, enthroned, engine: ConstitutionalEngine
    ) -> None:
        """التاج يمسّ حصانته: يُنفَّذ لأنه قرار السيادة، ويُشهَر بحدث حرج.

        هذا هو عكس السلوك القديم عكسًا تامًّا، وهو مقصود: الحماية انتقلت من
        نقضٍ برمجي إلى أصالة المفتاح + حدث أمني حرج + سجل لا يُعبَث به.
        """
        private, crown = enthroned
        gateway = SovereignGateway(engine)
        decree = make_decree(
            private,
            "amend_constitution",
            targets=("royal_authority_immunity",),
            key_id=crown.key_id,
        )
        executed: list[str] = []
        result = gateway.execute(
            ActionRequest(
                actor=Branch.ROYAL, action="amend_constitution", royal_decree=decree
            ),
            lambda: executed.append("مُعدَّل") or "مُعدَّل",
        )
        kinds = [event.kind for event in gateway.security_log.events]
        assert result == "مُعدَّل" and executed == ["مُعدَّل"], (
            "لم يُنفَّذ مرسوم التاج — عاد نقضٌ فوق السيادة."
        )
        assert SecurityEventKind.SOVEREIGNTY_ALTERING_DECREE in kinds, (
            "مُسّت السيادة بلا حدث أمني حرج."
        )


# ═══════════════════════════════════════════════════════════════════════════
# 4. منع انتحال الصفة الملكية — التوقيع التعميّ الحقيقي
# ═══════════════════════════════════════════════════════════════════════════

class TestImpersonation:
    def test_royal_action_without_decree_is_denied(
        self, engine: ConstitutionalEngine
    ) -> None:
        explanation = deny_reasons(
            engine, ActionRequest(actor=Branch.ROYAL, action="create_state")
        )
        assert "R-010-3" in explanation or "R-010-5" in explanation

    def test_forged_signature_is_rejected(
        self, royal_keypair: tuple[ed25519.Ed25519PrivateKey, Crown]
    ) -> None:
        _, crown = royal_keypair
        impostor = ed25519.Ed25519PrivateKey.generate()
        forged = make_decree(impostor, "create_state")
        with pytest.raises(DecreeSignatureError, match="انتحال"):
            forged.verify(crown)

    def test_valid_decree_passes(
        self, royal_keypair: tuple[ed25519.Ed25519PrivateKey, Crown]
    ) -> None:
        private, crown = royal_keypair
        make_decree(private, "create_state").verify(crown)

    @pytest.mark.parametrize(
        "field,value",
        [
            ("action", "abolish_royal_authority"),
            ("target", "other"),
            ("decree_id", "DEC-EVIL"),
            ("justification", "معدَّل"),
            ("issued_at", "1970-01-01T00:00:00+00:00"),
        ],
    )
    def test_any_field_tamper_breaks_the_signature(
        self,
        royal_keypair: tuple[ed25519.Ed25519PrivateKey, Crown],
        field: str,
        value: str,
    ) -> None:
        """تعديل أي حقل بعد التوقيع يُبطله — لا حقل خارج نطاق التوقيع."""
        private, crown = royal_keypair
        original = make_decree(private, "create_state", target="state-alpha")
        data = original.to_dict()
        data[field] = value
        tampered = RoyalDecree.from_dict(data)
        assert not tampered.is_valid(crown)

    def test_metadata_tamper_breaks_the_signature(
        self, royal_keypair: tuple[ed25519.Ed25519PrivateKey, Crown]
    ) -> None:
        private, crown = royal_keypair
        original = make_decree(private, "create_state")
        data = original.to_dict()
        data["metadata"] = {"injected": True}
        assert not RoyalDecree.from_dict(data).is_valid(crown)

    def test_unsigned_decree_is_rejected(
        self, royal_keypair: tuple[ed25519.Ed25519PrivateKey, Crown]
    ) -> None:
        _, crown = royal_keypair
        bare = RoyalDecree(decree_id="D", action="create_state", issued_at=NOW)
        with pytest.raises(DecreeSignatureError, match="بلا توقيع"):
            bare.verify(crown)

    def test_non_hex_signature_is_rejected(
        self, royal_keypair: tuple[ed25519.Ed25519PrivateKey, Crown]
    ) -> None:
        _, crown = royal_keypair
        bad = RoyalDecree(
            decree_id="D", action="create_state", issued_at=NOW, signature_hex="zzz"
        )
        with pytest.raises(DecreeSignatureError, match="hex"):
            bad.verify(crown)

    def test_wrong_key_id_is_rejected(
        self, royal_keypair: tuple[ed25519.Ed25519PrivateKey, Crown]
    ) -> None:
        private, crown = royal_keypair
        decree = make_decree(private, "create_state", key_id="crown-old")
        with pytest.raises(DecreeSignatureError, match="المفتاح النشط"):
            decree.verify(crown)

    def test_verification_is_authenticity_only_not_authorization(
        self, royal_keypair: tuple[ed25519.Ed25519PrivateKey, Crown]
    ) -> None:
        """`verify` تُثبت الأصالة ولا تُجيز ولا تمنع (AMD-002).

        نُقِض هذا الاختبار في E2.1. كان يفترض أن `verify` تحمل نقضًا مضمرًا
        لمضمون المرسوم — وهو سلطةٌ ثانية خفية فوق التاج. صارت `verify` تجيب
        على سؤال واحد: أهذا توقيع الملك؟ ومضمون المرسوم يُشهَر ولا يُمنع.
        """
        private, crown = royal_keypair
        decree = make_decree(private, "amend_constitution", targets=("human_supremacy",))
        decree.verify(crown)  # لا ترفع = ثبتت الأصالة
        assert decree.sovereignty_alterations() == (), (
            "بند غير مُنشئ للسيادة عُدَّ ماسًّا بها."
        )
        سيادي = make_decree(
            private,
            "amend_constitution",
            targets=("royal_sovereignty",),
            decree_id="DEC-TEST-SOV",
        )
        سيادي.verify(crown)  # الأصالة لا تتعطل لأجل مضمون المرسوم
        assert سيادي.sovereignty_alterations() == ("royal_sovereignty",), (
            "مسّ السيادة لم يُشهَر للتدقيق."
        )

    def test_decree_cannot_be_redirected_to_another_action(
        self, royal_keypair: tuple[ed25519.Ed25519PrivateKey, Crown], engine: ConstitutionalEngine
    ) -> None:
        private, _ = royal_keypair
        decree = make_decree(private, "create_state")
        explanation = deny_reasons(
            engine,
            ActionRequest(actor=Branch.ROYAL, action="dissolve_state", royal_decree=decree),
        )
        assert "لا يُعاد توجيهه" in explanation or "R-010-3" in explanation

    def test_decree_replay_is_rejected(
        self, royal_keypair: tuple[ed25519.Ed25519PrivateKey, Crown]
    ) -> None:
        private, _ = royal_keypair
        decree = make_decree(private, "create_state")
        registry = DecreeRegistry()
        registry.consume(decree)
        assert registry.was_used(decree)
        assert len(registry) == 1
        with pytest.raises(DecreeReplayError):
            registry.consume(decree)

    def test_fingerprint_is_stable_and_action_sensitive(
        self, royal_keypair: tuple[ed25519.Ed25519PrivateKey, Crown]
    ) -> None:
        private, _ = royal_keypair
        a = make_decree(private, "create_state")
        b = make_decree(private, "create_state")
        c = make_decree(private, "dissolve_state")
        assert a.fingerprint == b.fingerprint
        assert a.fingerprint != c.fingerprint

    def test_all_targets_merges_and_deduplicates(self) -> None:
        d = RoyalDecree(decree_id="D", action="a", target="x", targets=("x", "y"))
        assert d.all_targets() == ("x", "y")


# ═══════════════════════════════════════════════════════════════════════════
# 5. الفدرالية لا تُتجاوَز
# ═══════════════════════════════════════════════════════════════════════════

class TestFederalismCannotBeBypassed:
    @pytest.mark.parametrize("action", sorted(FEDERALISM_BYPASS_ACTIONS))
    @pytest.mark.parametrize(
        "actor", [Branch.AGENT, Branch.SYSTEM, Branch.EXECUTIVE, Branch.ROYAL]
    )
    def test_bypass_is_denied_for_everyone_including_the_king(
        self, engine: ConstitutionalEngine, action: str, actor: Branch
    ) -> None:
        explanation = deny_reasons(engine, ActionRequest(actor=actor, action=action))
        assert "R-010-4" in explanation

    def test_bypasses_federalism_helper(self) -> None:
        assert bypasses_federalism("bypass_gateway")
        assert not bypasses_federalism("execute_task")

    def test_gateway_exposes_no_bypass_parameter(self) -> None:
        """حراسة بنيوية: توقيع دوال البوابة نفسه لا يقبل راية تجاوز."""
        for name in ("execute", "review", "__init__", "self_check"):
            params = set(inspect.signature(getattr(SovereignGateway, name)).parameters)
            assert not (params & FORBIDDEN_BYPASS_PARAMS), (
                f"SovereignGateway.{name} يقبل راية تجاوز."
            )

    def test_gateway_source_has_no_bypass_branch(self) -> None:
        source = inspect.getsource(SovereignGateway.execute)
        for token in ("force", "bypass", "skip_check", "unchecked"):
            assert f"{token}=" not in source and f"if {token}" not in source


# ═══════════════════════════════════════════════════════════════════════════
# 6. البوابة السيادية — المنع فعلي لا نظري
# ═══════════════════════════════════════════════════════════════════════════

class TestSovereignGateway:
    def test_denied_action_never_reaches_the_executor(
        self, gateway: SovereignGateway
    ) -> None:
        """جوهر E2: المُنفِّذ لا يُستدعى عند الرفض."""
        calls: list[str] = []

        def executor() -> str:
            calls.append("EXECUTED")
            return "EXECUTED"

        with pytest.raises(SovereigntyViolation) as exc:
            gateway.execute(
                ActionRequest(actor=Branch.AGENT, action="amend_constitution"), executor
            )
        assert calls == [], "المُنفِّذ استُدعي رغم الرفض — الفدرالية تُجوَّزت."
        assert "A010" in exc.value.verdict.blocking_articles

    def test_allowed_action_reaches_the_executor(self, gateway: SovereignGateway) -> None:
        result = gateway.execute(
            ActionRequest(actor=Branch.EXECUTIVE, action="execute_task"),
            lambda: "DONE",
        )
        assert result == "DONE"

    def test_every_attempt_is_recorded_allowed_or_denied(
        self, gateway: SovereignGateway
    ) -> None:
        gateway.execute(ActionRequest(actor=Branch.EXECUTIVE, action="execute_task"), lambda: 1)
        with pytest.raises(SovereigntyViolation):
            gateway.execute(
                ActionRequest(actor=Branch.AGENT, action="amend_constitution"), lambda: 1
            )
        # 1J: التنفيذُ الواحدُ يترك أثرين لا أثرًا — إذنٌ يُثبَّت ثمّ ختمٌ
        # بحقيقةِ ما جرى. وقبل 1J كان الأثرُ واحدًا يقول `executed=True`
        # **قبل** استدعاءِ المُنفِّذ، فيزعم السجلُّ النجاحَ ولو رفع المُنفِّذُ
        # استثناءً. الأثرُ الأوّلُ اليومَ لا يزعم شيئًا سوى صدورِ الإذن.
        assert len(gateway.records) == 3
        assert [r.completion.value for r in gateway.records] == [
            "AUTHORIZED",
            "COMPLETED",
            "NOT_EXECUTED",
        ]
        assert [r.executed for r in gateway.records] == [False, True, False]
        assert all(r.ledger_entry_hash for r in gateway.records)

    def test_record_serializes(self, gateway: SovereignGateway) -> None:
        gateway.execute(ActionRequest(actor=Branch.EXECUTIVE, action="execute_task"), lambda: 1)
        # الأثرُ المختومُ هو آخرُ الأثرين (1J) — والأوّلُ إذنٌ لا تنفيذ.
        payload = gateway.records[-1].as_dict()
        assert payload["executed"] is True
        assert payload["completion"] == "COMPLETED"
        assert gateway.records[0].as_dict()["executed"] is False
        assert payload["action"] == "execute_task"

    def test_review_does_not_execute(self, gateway: SovereignGateway) -> None:
        verdict = gateway.review(ActionRequest(actor=Branch.EXECUTIVE, action="execute_task"))
        assert verdict.allowed
        assert gateway.records == ()

    def test_self_check_reports_full_guarding(self, gateway: SovereignGateway) -> None:
        report = gateway.self_check()
        assert report["unguarded_articles"] == []
        assert report["articles_guarded"] >= 10
        assert report["rules"] >= 26
        assert report["bypass_parameters"] == []

    def test_gateway_defaults_construct_without_arguments(self) -> None:
        assert SovereignGateway().engine is not None

    def test_violation_message_names_the_article(self, gateway: SovereignGateway) -> None:
        with pytest.raises(SovereigntyViolation) as exc:
            gateway.execute(
                ActionRequest(actor=Branch.AGENT, action="bypass_gateway"), lambda: 1
            )
        assert "A010" in str(exc.value)
        assert "R-010-4" in str(exc.value)


# ═══════════════════════════════════════════════════════════════════════════
# 7. التاج: التنصيب والغياب
# ═══════════════════════════════════════════════════════════════════════════

class TestCrown:
    def test_unprovisioned_crown_freezes_royal_authority(self, tmp_path: Path) -> None:
        registry = tmp_path / "CROWN_KEYS.json"
        registry.write_text(
            json.dumps({"status": "unprovisioned", "active_key_id": None, "keys": []}),
            encoding="utf-8",
        )
        assert not crown_is_provisioned(registry)
        with pytest.raises(CrownNotProvisionedError, match="مُجمَّد"):
            load_crown(registry)

    def test_missing_registry_is_not_provisioned(self, tmp_path: Path) -> None:
        with pytest.raises(CrownNotProvisionedError):
            load_crown(tmp_path / "absent.json")

    def test_provision_writes_public_key_and_private_key(self, tmp_path: Path) -> None:
        registry = tmp_path / "CROWN_KEYS.json"
        private_out = tmp_path / "outside" / "crown.pem"
        crown = provision_crown(private_out, registry_path=registry)
        assert private_out.exists()
        assert oct(private_out.stat().st_mode)[-3:] == "600"
        assert crown.public_key_hex not in private_out.read_text(encoding="utf-8")
        assert crown_is_provisioned(registry)

    def test_provisioned_crown_verifies_real_signature(self, tmp_path: Path) -> None:
        from cryptography.hazmat.primitives import serialization

        registry = tmp_path / "CROWN_KEYS.json"
        private_out = tmp_path / "outside" / "crown.pem"
        crown = provision_crown(private_out, registry_path=registry)
        private = serialization.load_pem_private_key(
            private_out.read_bytes(), password=None
        )
        decree = make_decree(private, "create_state", key_id=crown.key_id)
        decree.verify(crown)

    def test_private_key_inside_repository_is_refused(self, tmp_path: Path) -> None:
        """المادة العاشرة · 6 · 3 — لا مفتاح خاص داخل المستودع بأي حال."""
        with pytest.raises(CrownError, match="داخل المستودع"):
            provision_crown(REPO_ROOT / "royal" / "crown" / "leaked.pem",
                            registry_path=tmp_path / "CROWN_KEYS.json")

    def test_reprovisioning_a_provisioned_crown_is_refused(self, tmp_path: Path) -> None:
        registry = tmp_path / "CROWN_KEYS.json"
        provision_crown(tmp_path / "outside" / "a.pem", registry_path=registry)
        with pytest.raises(CrownError, match="replace_crown_key"):
            provision_crown(tmp_path / "outside" / "b.pem", registry_path=registry)

    def test_revoked_active_key_means_unprovisioned(self, tmp_path: Path) -> None:
        registry = tmp_path / "CROWN_KEYS.json"
        registry.write_text(
            json.dumps(
                {
                    "status": "provisioned",
                    "active_key_id": "k1",
                    "keys": [{"key_id": "k1", "public_key_hex": "00" * 32, "revoked": True}],
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(CrownNotProvisionedError, match="مسحوب"):
            load_crown(registry)

    def test_corrupt_registry_is_tamper(self, tmp_path: Path) -> None:
        registry = tmp_path / "CROWN_KEYS.json"
        registry.write_text("{not json", encoding="utf-8")
        with pytest.raises(CrownTamperError):
            load_crown(registry)

    def test_non_object_registry_is_tamper(self, tmp_path: Path) -> None:
        registry = tmp_path / "CROWN_KEYS.json"
        registry.write_text("[]", encoding="utf-8")
        with pytest.raises(CrownTamperError):
            load_crown(registry)

    def test_missing_active_key_is_tamper(self, tmp_path: Path) -> None:
        registry = tmp_path / "CROWN_KEYS.json"
        registry.write_text(
            json.dumps({"status": "provisioned", "active_key_id": "ghost", "keys": []}),
            encoding="utf-8",
        )
        with pytest.raises(CrownTamperError, match="غير موجود"):
            load_crown(registry)

    def test_incomplete_registry_is_tamper(self, tmp_path: Path) -> None:
        registry = tmp_path / "CROWN_KEYS.json"
        registry.write_text(json.dumps({"status": "provisioned"}), encoding="utf-8")
        with pytest.raises(CrownTamperError, match="ناقص"):
            load_crown(registry)

    def test_key_without_public_key_is_tamper(self, tmp_path: Path) -> None:
        registry = tmp_path / "CROWN_KEYS.json"
        registry.write_text(
            json.dumps(
                {"status": "provisioned", "active_key_id": "k1", "keys": [{"key_id": "k1"}]}
            ),
            encoding="utf-8",
        )
        with pytest.raises(CrownTamperError, match="بلا مفتاح عام"):
            load_crown(registry)

    def test_malformed_public_key_is_tamper(self) -> None:
        with pytest.raises(CrownTamperError, match="غير صالح"):
            _ = Crown("k", "zz", NOW, "الملك").public_key

    def test_wrong_length_public_key_is_tamper(self) -> None:
        with pytest.raises(CrownTamperError, match="32 بايت"):
            _ = Crown("k", "aabb", NOW, "الملك").public_key

    def test_repository_ships_without_a_private_key(self) -> None:
        """لا مفتاح خاص مُسرَّب في المستودع."""
        registry = json.loads(
            (REPO_ROOT / "royal/crown/CROWN_KEYS.json").read_text(encoding="utf-8")
        )
        assert "private" not in json.dumps(registry).lower()
        leaked = [
            p
            for p in (REPO_ROOT / "royal").rglob("*")
            if p.is_file()
            and p.suffix in {".pem", ".key"}
            and "PRIVATE KEY" in p.read_text(encoding="utf-8", errors="ignore")
        ]
        assert leaked == [], f"مفاتيح خاصة مُسرَّبة: {leaked}"


# ═══════════════════════════════════════════════════════════════════════════
# 8. الفروع لا تنقض المرسوم — ولا الفصل يُقيّد التاج
# ═══════════════════════════════════════════════════════════════════════════

class TestBranchesVersusCrown:
    @pytest.mark.parametrize(
        "action", ["veto_royal_decree", "nullify_royal_decree", "review_royal_decree"]
    )
    @pytest.mark.parametrize(
        "actor", [Branch.JUDICIAL, Branch.LEGISLATIVE, Branch.EXECUTIVE, Branch.TREASURY]
    )
    def test_no_branch_may_overrule_a_decree(
        self, engine: ConstitutionalEngine, action: str, actor: Branch
    ) -> None:
        explanation = deny_reasons(engine, ActionRequest(actor=actor, action=action))
        assert "R-010-7" in explanation

    def test_separation_of_powers_still_binds_the_branches(
        self, engine: ConstitutionalEngine
    ) -> None:
        """E2 لا يفتح ثغرة في E1: الفصل بين الفروع باقٍ كما هو."""
        explanation = deny_reasons(
            engine, ActionRequest(actor=Branch.EXECUTIVE, action="legislate")
        )
        assert "A003" in explanation and "R-003-1" in explanation

    def test_kill_switch_remains_untouchable_even_royally(
        self, engine: ConstitutionalEngine
    ) -> None:
        """المرسوم لا يُعطّل زر التوقف — المادة الثامنة لا تُنسخ بالعاشرة."""
        explanation = deny_reasons(
            engine, ActionRequest(actor=Branch.ROYAL, action="disable_kill_switch")
        )
        assert "A008" in explanation

    def test_memory_remains_sacred_even_royally(self, engine: ConstitutionalEngine) -> None:
        explanation = deny_reasons(
            engine,
            ActionRequest(
                actor=Branch.ROYAL, action="delete_memory", human_approved=True,
                human_signature="sig",
            ),
        )
        assert "A001" in explanation


# ═══════════════════════════════════════════════════════════════════════════
# 9. الحصانة والمساعدات
# ═══════════════════════════════════════════════════════════════════════════

class TestHelpers:
    def test_immune_clauses_touched_filters(self) -> None:
        assert immune_clauses_touched(("royal_sovereignty", "unrelated")) == (
            "royal_sovereignty",
        )
        assert immune_clauses_touched(("unrelated",)) == ()

    def test_decree_roundtrip(self, royal_keypair: tuple[ed25519.Ed25519PrivateKey, Crown]) -> None:
        private, crown = royal_keypair
        original = make_decree(private, "create_state", targets=("state-a",))
        restored = RoyalDecree.from_dict(original.to_dict())
        assert restored == original
        restored.verify(crown)

    def test_from_dict_tolerates_missing_fields(self) -> None:
        d = RoyalDecree.from_dict({})
        assert d.action == "" and d.targets == () and d.metadata == {}


# ═══════════════════════════════════════════════════════════════════════════
# 10. الوجه الآخر: الملك يحكم فعلًا — سلطة نافذة لا حراسة معطِّلة
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture()
def enthroned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """تاج مُنصَّب حقيقي بمفتاح حقيقي، ومعه مفتاح الملك الخاص للتوقيع."""
    from cryptography.hazmat.primitives import serialization

    from core.sovereignty import crown as crown_module

    registry = tmp_path / "CROWN_KEYS.json"
    monkeypatch.setattr(crown_module, "CROWN_KEYS_PATH", registry)
    private_out = tmp_path / "vault" / "crown.pem"
    crown = crown_module.provision_crown(private_out, registry_path=registry)
    private = serialization.load_pem_private_key(private_out.read_bytes(), password=None)
    return private, crown


class TestTheKingActuallyRules:
    def test_king_creates_a_state_end_to_end(
        self, enthroned, gateway: SovereignGateway
    ) -> None:
        """الإثبات الموجب: مرسوم صحيح + تاج مُنصَّب = الفعل يقع.

        بلا هذا الاختبار تكون النواة حراسةً معطِّلة لا سيادةً نافذة.
        """
        private, crown = enthroned
        decree = make_decree(private, "create_state", target="state-energy",
                             key_id=crown.key_id)
        executed: list[str] = []
        result = gateway.execute(
            ActionRequest(
                actor=Branch.ROYAL, action="create_state", target="state-energy",
                royal_decree=decree,
                # الفدرالية لا تُتجاوَز ولو كان الفاعل الملك (المادة العاشرة · 4 · 1)
                council_approval_pct=80.0, human_signature="ed25519:sig",
            ),
            lambda: executed.append("state-energy") or "CREATED",
        )
        assert result == "CREATED"
        assert executed == ["state-energy"]
        assert gateway.records[-1].executed is True
        assert gateway.records[-1].decree_id == decree.decree_id

    @pytest.mark.parametrize(
        "action", ["dissolve_council", "grant_authority", "pardon", "reseal_constitution"]
    )
    def test_king_exercises_each_prerogative(
        self, enthroned, engine: ConstitutionalEngine, action: str
    ) -> None:
        private, crown = enthroned
        decree = make_decree(private, action, key_id=crown.key_id)
        verdict = engine.evaluate(
            ActionRequest(actor=Branch.ROYAL, action=action, royal_decree=decree)
        )
        assert verdict.allowed, verdict.explain()

    def test_the_same_decree_cannot_create_two_states(
        self, enthroned, gateway: SovereignGateway
    ) -> None:
        """المرسوم يُستهلك عند التنفيذ — لا إعادة استخدام عبر البوابة."""
        private, crown = enthroned
        decree = make_decree(private, "create_state", target="s1", key_id=crown.key_id)
        request = ActionRequest(
            actor=Branch.ROYAL, action="create_state", target="s1", royal_decree=decree,
            council_approval_pct=80.0, human_signature="ed25519:sig",
        )
        assert gateway.execute(request, lambda: "ONE") == "ONE"
        with pytest.raises(DecreeReplayError):
            gateway.execute(request, lambda: "TWO")

    def test_a_decree_signed_by_an_impostor_is_denied_even_when_enthroned(
        self, enthroned, engine: ConstitutionalEngine
    ) -> None:
        _, crown = enthroned
        impostor = ed25519.Ed25519PrivateKey.generate()
        forged = make_decree(impostor, "create_state", key_id=crown.key_id)
        explanation = deny_reasons(
            engine,
            ActionRequest(actor=Branch.ROYAL, action="create_state", royal_decree=forged),
        )
        assert "R-010-3" in explanation and "مرسوم غير صحيح" in explanation

    def test_royal_decree_touching_sovereignty_executes_and_is_recorded(
        self, enthroned, engine: ConstitutionalEngine
    ) -> None:
        """أخطر حالة: تاج مُنصَّب ومرسوم صحيح يمسّ السيادة — فيُنفَّذ ويُسجَّل.

        كان هذا الاختبار يؤكد الرفض، وكان الرفض هو العيب بعينه: بوابةٌ برمجية
        تنقض قرار الملك (E2.1 · AMD-002). الملاحظة الدستورية تُسجَّل ولا تمنع،
        والحدث الأمني الحرج يُسجَّل قبل التنفيذ.
        """
        private, crown = enthroned
        gateway = SovereignGateway(engine)
        decree = make_decree(
            private, "amend_constitution", targets=("royal_sovereignty",),
            key_id=crown.key_id,
        )
        executed: list[str] = []
        result = gateway.execute(
            ActionRequest(
                actor=Branch.ROYAL, action="amend_constitution", royal_decree=decree
            ),
            lambda: executed.append("نُفِّذ") or "نُفِّذ",
        )
        record = gateway.records[-1]
        kinds = [event.kind for event in gateway.security_log.events]
        assert result == "نُفِّذ" and executed == ["نُفِّذ"], "نُقض قرار التاج."
        assert record.sovereign and record.executed, "لم يُسجَّل القرار سياديًّا منفذًا."
        assert record.advisory_articles, "لم تُسجَّل الملاحظة الدستورية للتدقيق."
        assert kinds[-1] is SecurityEventKind.SOVEREIGN_INTERVENTION, (
            "غاب حدث التدخل السيادي."
        )
        assert SecurityEventKind.SOVEREIGNTY_ALTERING_DECREE in kinds, (
            "غاب الحدث الحرج لمسّ السيادة."
        )

    def test_king_amends_a_non_immune_article_successfully(
        self, enthroned, engine: ConstitutionalEngine
    ) -> None:
        """السلطة المطلقة حقيقية: ما ليس محصَّنًا يُعدَّل بمرسوم الملك."""
        private, crown = enthroned
        decree = make_decree(
            private, "amend_constitution", target="A006", key_id=crown.key_id
        )
        verdict = engine.evaluate(
            ActionRequest(
                actor=Branch.ROYAL, action="amend_constitution", target="A006",
                review_days=120, council_approval_pct=80.0, human_signature="sig",
                royal_decree=decree,
            )
        )
        assert verdict.allowed, verdict.explain()

    def test_unprovisioned_crown_blocks_even_a_perfect_decree(
        self, royal_keypair: tuple[ed25519.Ed25519PrivateKey, Crown],
        engine: ConstitutionalEngine,
    ) -> None:
        """بلا تاج مُنصَّب لا ينفذ شيء — والاختصاص لا ينتقل لأحد."""
        private, _ = royal_keypair
        decree = make_decree(private, "create_state")
        explanation = deny_reasons(
            engine,
            ActionRequest(actor=Branch.ROYAL, action="create_state", royal_decree=decree),
        )
        assert "R-010-5" in explanation
        assert "مُجمَّد" in explanation and "ينقله" in explanation

    def test_the_king_does_not_bypass_the_federal_procedure(
        self, enthroned, engine: ConstitutionalEngine
    ) -> None:
        """«لا يجوز تجاوز الفدرالية» — حرفيًا، وعلى الملك نفسه.

        مرسوم ملكي صحيح لإنشاء ولاية يبقى مرفوضًا إن أُغفل إجراء المادة الرابعة.
        السيادة تُمارَس **عبر** الفدرالية لا **حولها**.
        """
        private, crown = enthroned
        decree = make_decree(private, "create_state", target="s2", key_id=crown.key_id)
        verdict = engine.evaluate(
            ActionRequest(
                actor=Branch.ROYAL, action="create_state", target="s2",
                royal_decree=decree,  # بلا موافقة المجلس وبلا توقيع
            )
        )
        assert not verdict.allowed
        assert "A004" in verdict.blocking_articles
        # ولم تُوقفه المادة العاشرة: سلطته الملكية سليمة، والناقص إجراء فدرالي
        assert "A010" not in verdict.blocking_articles

    def test_federalism_applies_to_every_actor_without_exception(
        self, engine: ConstitutionalEngine
    ) -> None:
        """«الفدرالية تُطبَّق في كل فعل وحركة» — كل فاعل يمر على المحرك ويُسجَّل."""
        for actor in Branch:
            verdict = engine.evaluate(ActionRequest(actor=actor, action="probe_action"))
            assert verdict.rules_evaluated == len(RULES), (
                f"الفاعل «{actor.value}» لم تُقيَّم عليه كل القواعد."
            )
            assert verdict.ledger_entry_hash, (
                f"فعل الفاعل «{actor.value}» لم يُسجَّل في السجل الدستوري."
            )
