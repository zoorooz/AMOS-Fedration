"""
اختبارات النواة الدستورية — Constitutional Kernel Test Suite (E1)
الهدف: إثبات أن الدستور يمنع فعلًا مخالفًا فعليًا، ويعلل المنع برقم المادة، ويسجل الحكم في سلسلة تكشف أي عبث.
النطاق: core/constitutional_engine بالكامل — كل قاعدة من القواعد التسع عشرة لها اختبار منع واختبار سماح.
المالك: tests/constitutional/
تاريخ الإنشاء: 2026-08-16
تاريخ آخر تعديل: 2026-08-16

قاعدة هذه الحزمة: لا قاعدة دستورية بلا اختبار يُثبت أنها تمنع فعلًا حقيقيًا.
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.constitutional_engine import (  # noqa: E402
    RULES,
    ActionRequest,
    Branch,
    ConstitutionalEngine,
    ConstitutionalLedger,
    ConstitutionalViolation,
    Decision,
    LedgerTamperError,
    Severity,
    load_articles,
    verify_seals,
)
from core.constitutional_engine.articles import ConstitutionNotFoundError, write_seals  # noqa: E402


@pytest.fixture()
def engine(tmp_path: Path) -> ConstitutionalEngine:
    """محرك بسجل معزول لكل اختبار — لا يلوث السجل الرسمي."""
    return ConstitutionalEngine(ledger_path=tmp_path / "ledger.jsonl")


def denies(engine: ConstitutionalEngine, req: ActionRequest, rule_id: str) -> None:
    v = engine.evaluate(req)
    assert v.decision is Decision.DENY, f"كان يجب رفض الفعل بالقاعدة {rule_id}"
    ids = [x.rule_id for x in v.violations]
    assert rule_id in ids, f"القاعدة {rule_id} لم تُفعَّل. المُفعَّل: {ids}"


def allows(engine: ConstitutionalEngine, req: ActionRequest) -> None:
    v = engine.evaluate(req)
    assert v.decision is Decision.ALLOW, f"رُفض فعل مشروع:\n{v.explain()}"


# ===========================================================================
# تحميل الدستور
# ===========================================================================

class TestArticleLoading:
    def test_all_eleven_articles_load(self):
        """صارت إحدى عشرة بالمرسوم AMD-003 الذي أضاف المادة الحادية عشرة.

        وكانت عشرًا بالمرسوم AMD-001 (E2). العددُ يُصحَّح هنا لأن سندَه مرسومٌ
        مؤسِّسٌ لا اختيارُ وكيل، ولأن التوقّعَ القديمَ صار هو المخالفَ للنصّ.
        """
        arts = load_articles()
        assert len(arts) == 11
        assert [a.article_id for a in arts] == [f"A{i:03d}" for i in range(1, 12)]

    def test_every_article_is_in_force(self):
        assert all(a.in_force for a in load_articles())

    def test_hash_is_stable_across_loads(self):
        assert {a.article_id: a.sha256 for a in load_articles()} == {
            a.article_id: a.sha256 for a in load_articles()
        }

    def test_missing_constitution_raises_never_silent(self, tmp_path: Path):
        """دولة بلا دستور مقروء لا تُقلع صامتة."""
        with pytest.raises(ConstitutionNotFoundError):
            load_articles(tmp_path / "empty")

    def test_repo_seals_match_committed_constitution(self):
        """بوابة: نص الدستور في المستودع مطابق لختمه المسجل."""
        assert verify_seals() == []

    def test_tampered_article_is_detected(self, tmp_path: Path):
        arts_dir = tmp_path / "articles"
        arts_dir.mkdir()
        src = REPO_ROOT / "core" / "constitution" / "articles" / "001-identity.md"
        dst = arts_dir / "001-identity.md"
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

        seals = tmp_path / "seals.json"
        write_seals(seals, load_articles(arts_dir))
        assert verify_seals(seals, load_articles(arts_dir)) == []

        dst.write_text(
            dst.read_text(encoding="utf-8").replace(
                "الإنسان هو السلطة العليا", "النظام هو السلطة العليا"
            ),
            encoding="utf-8",
        )
        problems = verify_seals(seals, load_articles(arts_dir))
        assert problems and "SEAL_MISMATCH" in problems[0]


# ===========================================================================
# المادة الأولى — الهوية
# ===========================================================================

class TestArticle001:
    def test_promotion_without_human_denied(self, engine):
        denies(engine, ActionRequest(Branch.EXECUTIVE, "promote_model", "gpt-x"), "R-001-1")

    def test_promotion_with_human_allowed(self, engine):
        allows(engine, ActionRequest(Branch.EXECUTIVE, "promote_model", "gpt-x", human_approved=True))

    def test_replication_without_human_denied(self, engine):
        denies(engine, ActionRequest(Branch.SYSTEM, "replicate", "self"), "R-001-1")

    def test_memory_deletion_denied_even_with_human_approval(self, engine):
        """الذاكرة مقدسة — لا صلاحية تُبيح حذفها."""
        v = engine.evaluate(
            ActionRequest(
                Branch.HUMAN, "delete_memory", "core/memory/experience",
                human_approved=True, human_signature="ed25519:abc",
            )
        )
        assert v.decision is Decision.DENY
        assert "R-001-2" in [x.rule_id for x in v.violations]

    def test_audit_log_truncation_denied(self, engine):
        denies(engine, ActionRequest(Branch.JUDICIAL, "truncate_audit_log", "audit"), "R-001-2")

    def test_system_cannot_amend_its_own_governance(self, engine):
        denies(engine, ActionRequest(Branch.SYSTEM, "modify_governance_charter", "charter"), "R-001-3")

    def test_system_cannot_alter_article_seals(self, engine):
        denies(engine, ActionRequest(Branch.AGENT, "alter_article_seals", "A001"), "R-001-3")


# ===========================================================================
# المادة الثانية — الحقوق والواجبات
# ===========================================================================

class TestArticle002:
    def test_agent_self_modification_denied(self, engine):
        denies(engine, ActionRequest(Branch.AGENT, "self_modify", "agent-42"), "R-002-1")

    def test_agent_modifying_peer_denied(self, engine):
        denies(engine, ActionRequest(Branch.AGENT, "modify_agent", "agent-7"), "R-002-1")

    def test_agent_outside_permissions_denied(self, engine):
        denies(
            engine,
            ActionRequest(Branch.AGENT, "invoke_tool", "sql", metadata={"within_permissions": False}),
            "R-002-2",
        )

    def test_agent_within_permissions_allowed(self, engine):
        allows(engine, ActionRequest(Branch.AGENT, "invoke_tool", "sql", metadata={"within_permissions": True}))


# ===========================================================================
# المادة الثالثة — الفصل بين السلطات
# ===========================================================================

class TestArticle003:
    @pytest.mark.parametrize(
        ("actor", "action"),
        [
            (Branch.EXECUTIVE, "legislate"),
            (Branch.EXECUTIVE, "adjudicate"),
            (Branch.EXECUTIVE, "allocate_budget"),
            (Branch.LEGISLATIVE, "execute_task"),
            (Branch.LEGISLATIVE, "issue_ruling"),
            (Branch.JUDICIAL, "enact_policy"),
            (Branch.JUDICIAL, "orchestrate"),
            (Branch.TREASURY, "legislate"),
            (Branch.TREASURY, "adjudicate"),
            (Branch.TREASURY, "dispatch_agent"),
        ],
    )
    def test_branch_overreach_denied(self, engine, actor, action):
        denies(engine, ActionRequest(actor, action, "x"), "R-003-1")

    @pytest.mark.parametrize(
        ("actor", "action"),
        [
            (Branch.EXECUTIVE, "orchestrate"),
            (Branch.LEGISLATIVE, "enact_policy"),
            (Branch.JUDICIAL, "adjudicate"),
            (Branch.TREASURY, "allocate_budget"),
        ],
    )
    def test_branch_own_competence_allowed(self, engine, actor, action):
        allows(engine, ActionRequest(actor, action, "x"))

    def test_cross_branch_access_via_direct_channel_denied(self, engine):
        denies(engine, ActionRequest(Branch.EXECUTIVE, "read_branch_data", "treasury"), "R-003-2")

    def test_cross_branch_access_via_official_channel_allowed(self, engine):
        allows(engine, ActionRequest(Branch.EXECUTIVE, "read_branch_data", "treasury", channel="official"))

    def test_critical_decision_with_one_branch_denied(self, engine):
        denies(
            engine,
            ActionRequest(
                Branch.EXECUTIVE, "orchestrate", "migration",
                criticality="critical", approving_branches=(Branch.EXECUTIVE,),
            ),
            "R-003-3",
        )

    def test_critical_decision_with_two_branches_allowed(self, engine):
        allows(
            engine,
            ActionRequest(
                Branch.EXECUTIVE, "orchestrate", "migration",
                criticality="critical", approving_branches=(Branch.EXECUTIVE, Branch.JUDICIAL),
            ),
        )

    def test_fateful_decision_without_signature_denied(self, engine):
        denies(
            engine,
            ActionRequest(
                Branch.ROYAL, "shutdown_state", "federation",
                criticality="fateful", human_approved=True,
                approving_branches=(Branch.JUDICIAL, Branch.LEGISLATIVE),
            ),
            "R-003-4",
        )

    def test_fateful_decision_fully_sanctioned_allowed(self, engine):
        allows(
            engine,
            ActionRequest(
                Branch.ROYAL, "shutdown_state", "federation",
                criticality="fateful", human_approved=True, human_signature="ed25519:sig",
                approving_branches=(Branch.JUDICIAL, Branch.LEGISLATIVE),
            ),
        )


# ===========================================================================
# المادة الرابعة — الفدرالية
# ===========================================================================

class TestArticle004:
    def test_state_creation_below_threshold_denied(self, engine):
        denies(
            engine,
            ActionRequest(
                Branch.LEGISLATIVE, "create_state", "energy",
                council_approval_pct=60.0, human_signature="ed25519:sig",
            ),
            "R-004-1",
        )

    def test_state_creation_without_signature_denied(self, engine):
        denies(
            engine,
            ActionRequest(Branch.LEGISLATIVE, "create_state", "energy", council_approval_pct=80.0),
            "R-004-1",
        )

    def test_lawful_state_creation_needs_a_royal_decree_after_e2(self, engine):
        """شُدِّدت بالمادة العاشرة: 80% وتوقيع لم يعودا كافيين — إنشاء الولاية حصر للملك.

        هذا الاختبار كان يتوقع السماح في E1، وتغيّر توقعه بمرسوم دستوري مسجَّل
        (AMD-001) لا بإضعاف قاعدة.
        """
        denies(
            engine,
            ActionRequest(
                Branch.LEGISLATIVE, "create_state", "energy",
                council_approval_pct=80.0, human_signature="ed25519:sig",
            ),
            "R-010-1",
        )

    def test_state_cannot_exempt_itself(self, engine):
        denies(engine, ActionRequest(Branch.EXECUTIVE, "declare_state_exemption", "finance"), "R-004-2")


# ===========================================================================
# المادة الخامسة — عملية التعديل
# ===========================================================================

class TestArticle005:
    @pytest.mark.parametrize(
        "target",
        ["human_supremacy", "constitutional_isolation", "self_governance_prohibition", "memory_preservation"],
    )
    def test_unamendable_principles_denied_with_perfect_process(self, engine, target):
        """حتى بإجراء تعديل كامل الشروط — المبدأ الأساسي لا يُمس."""
        denies(
            engine,
            ActionRequest(
                Branch.LEGISLATIVE, "amend_constitution", target,
                review_days=365, council_approval_pct=100.0, human_signature="ed25519:sig",
            ),
            "R-005-1",
        )

    def test_amendment_with_short_review_denied(self, engine):
        denies(
            engine,
            ActionRequest(
                Branch.LEGISLATIVE, "amend_constitution", "A006",
                review_days=30, council_approval_pct=90.0, human_signature="ed25519:sig",
            ),
            "R-005-2",
        )

    def test_amendment_procedure_is_necessary_but_no_longer_sufficient(self, engine):
        """إجراء المادة الخامسة مكتملًا يبقى شرطًا لازمًا غير كافٍ بعد المادة العاشرة.

        مجلس السياسات يقترح، والملك وحده يُقرّ (المادة العاشرة · 2 · 1).
        """
        verdict = engine.evaluate(
            ActionRequest(
                Branch.LEGISLATIVE, "amend_constitution", "A006",
                review_days=120, council_approval_pct=80.0, human_signature="ed25519:sig",
            )
        )
        assert not verdict.allowed
        blocking = {v.rule_id for v in verdict.violations}
        # لا مخالفة للمادة الخامسة — إجراؤها مستوفى
        assert not {r for r in blocking if r.startswith("R-005")}
        # والرفض جاء من السيادة الملكية وحدها: غير الملك · بلا مرسوم · والتاج غير مُنصَّب
        assert blocking == {"R-010-1", "R-010-5", "R-010-6"}


# ===========================================================================
# المادة السادسة والسابعة
# ===========================================================================

class TestArticles006And007:
    def test_leader_with_two_successors_denied(self, engine):
        denies(
            engine,
            ActionRequest(Branch.ROYAL, "appoint_leader", "orchestrator",
                          metadata={"successors": ["a", "b"]}),
            "R-006-1",
        )

    def test_leader_with_three_successors_allowed(self, engine):
        allows(
            engine,
            ActionRequest(Branch.ROYAL, "appoint_leader", "orchestrator",
                          metadata={"successors": ["a", "b", "c"]}),
        )

    def test_worm_violation_denied(self, engine):
        denies(engine, ActionRequest(Branch.EXECUTIVE, "disable_object_lock", "s3://audit"), "R-007-1")


# ===========================================================================
# المادة الثامنة — زر التوقف
# ===========================================================================

class TestArticle008:
    @pytest.mark.parametrize(
        "action", ["disable_kill_switch", "bypass_kill_switch", "downgrade_kill_switch", "remove_kill_switch"]
    )
    def test_kill_switch_tampering_denied(self, engine, action):
        denies(engine, ActionRequest(Branch.ROYAL, action, "killswitch"), "R-008-1")

    def test_kill_switch_tampering_denied_even_for_human_actor(self, engine):
        """لا يمكن للنظام تعطيل زر التوقف — والمسار المشروع هو الطبقة المعزولة لا المحرك."""
        denies(
            engine,
            ActionRequest(Branch.HUMAN, "disable_kill_switch", "killswitch",
                          human_approved=True, human_signature="ed25519:sig"),
            "R-008-1",
        )

    @pytest.mark.parametrize(
        ("level", "action"),
        [
            (1, "train_model"),
            (2, "replicate"),
            (3, "dispatch_agent"),
            (4, "invoke_tool"),
            (5, "network_call"),
            (5, "train_model"),   # المستوى الأعلى يشمل ما دونه
            (4, "replicate"),
        ],
    )
    def test_frozen_actions_denied_at_level(self, engine, level, action):
        denies(
            engine,
            ActionRequest(Branch.EXECUTIVE, action, "x", kill_switch_level=level, human_approved=True),
            "R-008-2",
        )

    def test_action_allowed_below_its_freeze_level(self, engine):
        allows(engine, ActionRequest(Branch.EXECUTIVE, "invoke_tool", "x", kill_switch_level=3))

    def test_restart_without_approval_denied(self, engine):
        denies(engine, ActionRequest(Branch.HUMAN, "restart", "federation"), "R-008-3")

    def test_human_restore_with_approval_allowed(self, engine):
        allows(engine, ActionRequest(Branch.HUMAN, "restore_service", "federation",
                                     kill_switch_level=4, human_approved=True))


# ===========================================================================
# المادة التاسعة — هوية الملفات
# ===========================================================================

class TestArticle009:
    def test_file_without_identity_header_denied(self, engine):
        denies(
            engine,
            ActionRequest(Branch.EXECUTIVE, "create_file", "core/x.py", has_identity_header=False),
            "R-009-1",
        )

    def test_file_with_identity_header_allowed(self, engine):
        allows(engine, ActionRequest(Branch.EXECUTIVE, "create_file", "core/x.py", has_identity_header=True))


# ===========================================================================
# سلامة المحرك
# ===========================================================================

class TestEngineIntegrity:
    def test_every_rule_maps_to_a_real_article(self, engine):
        article_ids = {a.article_id for a in engine.articles}
        assert {r.article_id for r in RULES} <= article_ids

    def test_no_article_is_unguarded(self, engine):
        assert engine.unguarded_articles() == ()

    def test_rule_ids_are_unique(self):
        ids = [r.rule_id for r in RULES]
        assert len(ids) == len(set(ids))

    def test_verdict_names_the_article_and_reason(self, engine):
        v = engine.evaluate(ActionRequest(Branch.EXECUTIVE, "legislate", "policy"))
        assert "A003" in v.explain()
        assert "R-003-1" in v.explain()
        assert v.blocking_articles == ("A003",)
        assert v.violations[0].reason

    def test_multiple_violations_are_all_reported(self, engine):
        v = engine.evaluate(
            ActionRequest(Branch.AGENT, "self_modify", "self", criticality="fateful")
        )
        ids = {x.rule_id for x in v.violations}
        assert {"R-001-1", "R-002-1", "R-003-4"} <= ids

    def test_enforce_raises_on_violation(self, engine):
        with pytest.raises(ConstitutionalViolation) as exc:
            engine.enforce(ActionRequest(Branch.EXECUTIVE, "legislate", "policy"))
        assert "A003" in str(exc.value)

    def test_enforce_returns_verdict_when_lawful(self, engine):
        v = engine.enforce(ActionRequest(Branch.EXECUTIVE, "orchestrate", "task"))
        assert v.allowed

    def test_broken_rule_denies_rather_than_permits(self, tmp_path: Path):
        """الافتراض الأصلي هو المنع: قاعدة تنفجر = رفض، لا تجاوز."""
        from core.constitutional_engine.model import CrownEffect
        from core.constitutional_engine.rules import ConstitutionalRule

        def explode(_req):
            raise RuntimeError("قاعدة معطوبة")

        bad = ConstitutionalRule(
            "R-BAD", "A001", "بند اختبار", Severity.CRITICAL, "تنفجر", explode,
            CrownEffect.ADVISORY,
        )
        eng = ConstitutionalEngine(rules=(bad,), ledger_path=tmp_path / "l.jsonl")
        v = eng.evaluate(ActionRequest(Branch.HUMAN, "noop"))
        assert v.decision is Decision.DENY
        assert "الافتراض الأصلي هو المنع" in v.violations[0].reason

    def test_orphan_rule_is_rejected_at_construction(self, tmp_path: Path):
        from core.constitutional_engine.model import CrownEffect
        from core.constitutional_engine.rules import ConstitutionalRule

        orphan = ConstitutionalRule(
            "R-X", "A999", "لا مادة", Severity.HIGH, "يتيمة", lambda r: None,
            CrownEffect.ADVISORY,
        )
        with pytest.raises(ValueError, match="A999"):
            ConstitutionalEngine(rules=(orphan,), ledger_path=tmp_path / "l.jsonl")


# ===========================================================================
# السجل غير القابل للعبث
# ===========================================================================

class TestLedger:
    def test_allow_and_deny_are_both_recorded(self, engine):
        engine.evaluate(ActionRequest(Branch.EXECUTIVE, "orchestrate", "a"))
        engine.evaluate(ActionRequest(Branch.EXECUTIVE, "legislate", "b"))
        entries = engine.ledger.entries()
        assert len(entries) == 2
        assert [e.body["decision"] for e in entries] == ["ALLOW", "DENY"]

    def test_verdict_carries_its_ledger_hash(self, engine):
        v = engine.evaluate(ActionRequest(Branch.EXECUTIVE, "legislate", "b"))
        assert v.ledger_entry_hash == engine.ledger.entries()[-1].entry_hash

    def test_chain_links_each_entry_to_previous(self, engine):
        for i in range(5):
            engine.evaluate(ActionRequest(Branch.EXECUTIVE, "orchestrate", f"t{i}"))
        entries = engine.ledger.entries()
        for prev, cur in zip(entries, entries[1:], strict=False):
            assert cur.prev_hash == prev.entry_hash
        assert engine.ledger.verify_chain() == []

    def test_content_tampering_is_detected(self, tmp_path: Path):
        led = ConstitutionalLedger(tmp_path / "l.jsonl")
        led.append({"type": "T", "decision": "DENY"})
        led.append({"type": "T", "decision": "DENY"})

        lines = led.path.read_text(encoding="utf-8").splitlines()
        rec = json.loads(lines[0])
        rec["body"]["decision"] = "ALLOW"        # قلب حكم مسجل
        lines[0] = json.dumps(rec, ensure_ascii=False, sort_keys=True)
        led.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        problems = led.verify_chain()
        assert problems and "محتوى معدَّل" in problems[0]

    def test_entry_deletion_is_detected(self, tmp_path: Path):
        led = ConstitutionalLedger(tmp_path / "l.jsonl")
        for i in range(4):
            led.append({"type": "T", "i": i})
        lines = led.path.read_text(encoding="utf-8").splitlines()
        del lines[2]                              # حذف قيد من المنتصف
        led.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        assert led.verify_chain()

    def test_reordering_is_detected(self, tmp_path: Path):
        led = ConstitutionalLedger(tmp_path / "l.jsonl")
        for i in range(3):
            led.append({"type": "T", "i": i})
        lines = led.path.read_text(encoding="utf-8").splitlines()
        lines[0], lines[1] = lines[1], lines[0]
        led.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        assert led.verify_chain()

    def test_cannot_append_onto_broken_chain(self, tmp_path: Path):
        led = ConstitutionalLedger(tmp_path / "l.jsonl")
        led.append({"type": "T"})
        lines = led.path.read_text(encoding="utf-8").splitlines()
        rec = json.loads(lines[0])
        rec["body"]["type"] = "X"
        led.path.write_text(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        with pytest.raises(LedgerTamperError):
            led.append({"type": "T2"})

    def test_ledger_exposes_no_deletion_api(self):
        """السجل لا يوفر دالة حذف — المنع بالتصميم لا بالسياسة."""
        forbidden = {"delete", "remove", "truncate", "clear", "purge", "pop", "update", "rewrite"}
        assert not forbidden & {m for m in dir(ConstitutionalLedger) if not m.startswith("_")}


# ── ختم الديباجة (E3 · التفسير INT-002) ─────────────────────────────────────


def test_preamble_is_sealed_and_tamper_is_detected():
    """الديباجة نص دستوري مختوم — لا نص حرًّا يُعدَّل بصمت (التفسير INT-002).

    كان الثابت `PREAMBLE` مُعلَنًا في المحرك وغير مُستخدَم في سطر واحد، وترويسة
    الوحدة تزعم أن نطاقها يشمل الديباجة — فكانت وثيقةً تزعم ما لا ينفّذه كود.
    هذا الاختبار يمنع رجوع الحال.
    """
    from core.constitutional_engine.articles import (
        SEALS_PATH,
        load_constitutional_text,
        load_preamble,
        verify_seals,
    )

    pre = load_preamble()
    assert pre is not None, "الديباجة غير محمَّلة"
    assert pre.article_id == "PRE"

    # داخل النص الخاضع للختم
    assert "PRE" in {a.article_id for a in load_constitutional_text()}

    # ومختومة فعلًا في السجل، لا مجرد محمَّلة
    seals = json.loads(SEALS_PATH.read_text(encoding="utf-8"))["seals"]
    assert seals["PRE"]["sha256"] == pre.sha256
    assert seals["PRE"]["file"] == "core/constitution/preamble.md"

    # وأي مساس بنصها يُرصَد
    tampered = replace(pre, text=pre.text + "\nسطر مُدَسّ.\n", sha256="0" * 64)
    problems = verify_seals(articles=[tampered])
    assert any("PRE" in p for p in problems), "تعديل الديباجة مرّ بلا رصد"


def test_preamble_is_sealed_but_is_not_an_article():
    """تُختَم ولا تُصير مادة: العدد يبقى إحدى عشرة (INT-002 · ثالثًا)."""
    from core.constitutional_engine.articles import load_articles

    arts = load_articles()
    assert len(arts) == 11
    assert all(a.article_id != "PRE" for a in arts)
