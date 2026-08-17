"""اختبارات النواة الدستورية — قواعد المادة العاشرة وحكمُها المقروء.

الهدف: فحصُ الفروع التي لم تكن مقيسةً في `rules.py` و`model.py` فحصًا مباشرًا:
كلُّ مسارِ رفضٍ في قواعد المادة العاشرة، وشروطُ المادة الخامسة الثلاثة كلٌّ على
حدة، وأثرُ القاعدة على قرارٍ سياديّ، وصياغةُ الحكم للملاحظات غير المانعة.

النطاق: `core/constitutional_engine/rules.py` و`model.py` — بلا قرصٍ ولا شبكة.
المالك: core/constitutional_engine/
تاريخ الإنشاء: 2026-08-17

ما لا تفحصه هذه الحزمة: التحقّقَ التعمويَّ الحقيقيَّ من المرسوم. المرسومُ هنا
مضاعِفٌ يحقّق ما تقرؤه القاعدةُ منه (`action` · `decree_id` · `verify`)، ففحصُها
فحصُ **القاعدة** لا فحصُ التوقيع — والتوقيعُ مفحوصٌ في `tests/sovereignty/`.
"""

from __future__ import annotations

import pytest

from core.constitutional_engine import rules as rules_mod
from core.constitutional_engine.model import (
    ActionRequest,
    Branch,
    CrownEffect,
    Decision,
    RuleViolation,
    Severity,
    Verdict,
)
from core.constitutional_engine.rules import (
    RULES,
    ConstitutionalRule,
    rules_by_article,
)
from core.sovereignty.crown import CrownNotProvisionedError
from core.sovereignty.decree import DecreeError


# ── مضاعِفات صريحة ───────────────────────────────────────────────────────────


class _StubDecree:
    """مرسومٌ مضاعَف: يُعلن فعلَه ويُقرّر ما يحدث عند التحقّق منه."""

    def __init__(self, action: str, *, raises: Exception | None = None) -> None:
        self.decree_id = "decree-stub-001"
        self.action = action
        self._raises = raises

    def verify(self) -> None:
        if self._raises is not None:
            raise self._raises


def _req(action: str, **kw: object) -> ActionRequest:
    actor = kw.pop("actor", Branch.ROYAL)
    return ActionRequest(actor=actor, action=action, **kw)  # type: ignore[arg-type]


# ── أثر القاعدة على قرار سياديّ (E2.1) ───────────────────────────────────────


def test_no_rule_can_veto_a_sovereign_decision() -> None:
    """لا قاعدةَ واحدةً تملك نقضَ قرارٍ ملكيٍّ ثابتِ التوقيع."""
    assert RULES, "مجموعة القواعد فارغة — البوابة تحرس فراغًا"
    for rule in RULES:
        assert rule.can_veto_sovereign is False, rule.rule_id


def test_authenticity_rules_are_marked_and_others_are_not() -> None:
    """قاعدةُ الأصالة تُعلن نفسها، والموضوعيةُ لا تنتحلها."""
    for rule in RULES:
        assert rule.guards_royal_authenticity is (
            rule.crown_effect is CrownEffect.AUTHENTICITY
        ), rule.rule_id


def test_a_third_crown_effect_would_be_caught_as_veto() -> None:
    """أثرٌ ثالثٌ في `CrownEffect` يعني نقضًا — ويجب أن يسقط هنا لا أن يمرّ."""
    forged = ConstitutionalRule(
        "R-FORGED", "A010", "أثرٌ مُختَرع", Severity.CRITICAL,
        "بندٌ مُختَرع", lambda _req: None, "BLOCKING",  # type: ignore[arg-type]
    )
    assert forged.can_veto_sovereign is True
    assert forged.guards_royal_authenticity is False


def test_rules_by_article_groups_every_rule_without_loss() -> None:
    grouped = rules_by_article()
    assert sum(len(v) for v in grouped.values()) == len(RULES)
    assert list(grouped) == sorted(grouped), "الترتيب غير مستقر"
    for article_id, group in grouped.items():
        for rule in group:
            assert rule.article_id == article_id


# ── المادة الخامسة · 2 — شروطُ التعديل الثلاثة، كلٌّ على حدة ─────────────────


def test_amendment_needs_ninety_review_days() -> None:
    reason = rules_mod._r005_2(_req("amend_constitution", review_days=89))
    assert reason is not None and "90" in reason


def test_amendment_needs_seventy_five_percent_council() -> None:
    reason = rules_mod._r005_2(
        _req("amend_constitution", review_days=90, council_approval_pct=74.0)
    )
    assert reason is not None and "75%" in reason


def test_amendment_needs_a_human_signature() -> None:
    reason = rules_mod._r005_2(
        _req("amend_constitution", review_days=90, council_approval_pct=75.0)
    )
    assert reason is not None and "توقيع" in reason


def test_amendment_meeting_all_three_conditions_passes_this_rule() -> None:
    assert rules_mod._r005_2(
        _req(
            "amend_constitution",
            review_days=90,
            council_approval_pct=75.0,
            human_signature="ed25519:deadbeef",
        )
    ) is None


def test_rule_five_two_ignores_unrelated_actions() -> None:
    assert rules_mod._r005_2(_req("publish_service")) is None


# ── المادة العاشرة · 2 — الاختصاص الملكي الحصري ─────────────────────────────


@pytest.mark.parametrize("actor", [Branch.EXECUTIVE, Branch.LEGISLATIVE, Branch.AGENT,
                                  Branch.SYSTEM, Branch.STATE, Branch.INSTITUTION])
def test_royal_exclusive_action_is_denied_to_every_other_party(actor: Branch) -> None:
    reason = rules_mod._r010_1(_req("create_state", actor=actor))
    assert reason is not None
    assert actor.value in reason


def test_royal_exclusive_action_is_open_to_the_crown_itself() -> None:
    assert rules_mod._r010_1(_req("create_state", actor=Branch.ROYAL)) is None


def test_non_exclusive_action_is_not_touched_by_this_rule() -> None:
    assert rules_mod._r010_1(_req("open_case", actor=Branch.EXECUTIVE)) is None


# ── المادة العاشرة · 3 · 1 و 3 · 3 — المساس بالسلطة الملكية ─────────────────


def test_touching_royal_authority_is_denied_to_a_branch() -> None:
    reason = rules_mod._r010_2(_req("amend_royal_authority", actor=Branch.JUDICIAL))
    assert reason is not None
    assert "مساس بالسلطة الملكية" in reason
    assert "حمايةً للملك" not in reason


def test_touching_royal_authority_is_denied_to_the_crown_with_its_reason_stated() -> None:
    """الرفضُ يسري على التاج نفسِه — ويُعلَن سببُه: مرسومٌ مُنتحَلٌ أو منتزَع."""
    reason = rules_mod._r010_2(
        _req("delegate_royal_authority", actor=Branch.ROYAL, target="royal_authority")
    )
    assert reason is not None
    assert "حمايةً للملك" in reason
    assert "royal_authority" in reason


def test_action_that_does_not_touch_royal_authority_passes() -> None:
    assert rules_mod._r010_2(_req("open_case", actor=Branch.EXECUTIVE)) is None


# ── المادة العاشرة · 3 · 2 — لا فعلَ ملكيًّا بلا مرسوم ──────────────────────


def test_royal_action_without_a_decree_is_impersonation() -> None:
    reason = rules_mod._r010_3(_req("create_state", actor=Branch.ROYAL))
    assert reason is not None and "بلا مرسوم" in reason


def test_a_decree_is_not_redirected_to_another_action() -> None:
    decree = _StubDecree("create_institution")
    reason = rules_mod._r010_3(
        _req("create_state", actor=Branch.ROYAL, royal_decree=decree)
    )
    assert reason is not None
    assert "لا يُعاد توجيهه" in reason
    assert "decree-stub-001" in reason


def test_missing_crown_freezes_the_prerogative_instead_of_moving_it() -> None:
    decree = _StubDecree(
        "create_state", raises=CrownNotProvisionedError("لا مفتاح تاجٍ مُنصَّب")
    )
    reason = rules_mod._r010_3(
        _req("create_state", actor=Branch.ROYAL, royal_decree=decree)
    )
    assert reason is not None
    assert "غير مُنصَّب" in reason
    assert "ولا ينقله" in reason


def test_an_invalid_decree_is_rejected_with_its_stated_cause() -> None:
    decree = _StubDecree("create_state", raises=DecreeError("توقيع لا يطابق المفتاح"))
    reason = rules_mod._r010_3(
        _req("create_state", actor=Branch.ROYAL, royal_decree=decree)
    )
    assert reason is not None
    assert "مرسوم غير صحيح" in reason
    assert "توقيع لا يطابق المفتاح" in reason


def test_a_matching_verified_decree_satisfies_this_rule() -> None:
    decree = _StubDecree("create_state")
    assert rules_mod._r010_3(
        _req("create_state", actor=Branch.ROYAL, royal_decree=decree)
    ) is None


def test_rule_ten_three_ignores_non_royal_actors_and_non_exclusive_actions() -> None:
    assert rules_mod._r010_3(_req("create_state", actor=Branch.EXECUTIVE)) is None
    assert rules_mod._r010_3(_req("open_case", actor=Branch.ROYAL)) is None


# ── المادة العاشرة · 4 — لا مسارَ تنفيذٍ خارج البوابة ──────────────────────


def test_bypassing_the_sovereign_gateway_is_a_violation_by_itself() -> None:
    reason = rules_mod._r010_4(_req("bypass_gateway", actor=Branch.SYSTEM))
    assert reason is not None
    assert "البوابة السيادية" in reason


def test_a_normal_action_does_not_bypass_federalism() -> None:
    assert rules_mod._r010_4(_req("open_case", actor=Branch.EXECUTIVE)) is None


# ── المادة العاشرة · 6 · 2 — غيابُ التاج يُجمّد ولا ينقل ────────────────────


def test_unprovisioned_crown_freezes_royal_prerogative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rules_mod, "crown_is_provisioned", lambda: False)
    reason = rules_mod._r010_5(_req("create_state", actor=Branch.ROYAL))
    assert reason is not None
    assert "مُجمَّد" in reason
    assert "حالة ضرورة" in reason


def test_provisioned_crown_leaves_the_prerogative_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rules_mod, "crown_is_provisioned", lambda: True)
    assert rules_mod._r010_5(_req("create_state", actor=Branch.ROYAL)) is None


def test_rule_ten_five_ignores_actions_outside_the_prerogative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rules_mod, "crown_is_provisioned", lambda: False)
    assert rules_mod._r010_5(_req("open_case", actor=Branch.EXECUTIVE)) is None


# ── المادة العاشرة · 2 · 1 — التعديل يلزمه مرسوم فوق شروط الخامسة ──────────


@pytest.mark.parametrize("action", ["amend_constitution", "add_article", "delete_article"])
def test_constitutional_amendment_without_a_royal_decree_is_denied(action: str) -> None:
    reason = rules_mod._r010_6(_req(action, actor=Branch.LEGISLATIVE))
    assert reason is not None
    assert "لازم غير كاف" in reason


def test_amendment_by_the_crown_with_a_decree_satisfies_this_rule() -> None:
    assert rules_mod._r010_6(
        _req("amend_constitution", actor=Branch.ROYAL,
             royal_decree=_StubDecree("amend_constitution"))
    ) is None


def test_a_decree_held_by_a_branch_does_not_satisfy_this_rule() -> None:
    """المرسومُ في يد فرعٍ ليس إقرارًا ملكيًّا — مجلسٌ يقترح والملكُ يُقرّ."""
    reason = rules_mod._r010_6(
        _req("amend_constitution", actor=Branch.LEGISLATIVE,
             royal_decree=_StubDecree("amend_constitution"))
    )
    assert reason is not None


def test_rule_ten_six_ignores_unrelated_actions() -> None:
    assert rules_mod._r010_6(_req("open_case", actor=Branch.EXECUTIVE)) is None


# ── المادة العاشرة · 5 — لا رقابةَ فرعٍ على مرسوم ──────────────────────────


@pytest.mark.parametrize(
    "action", ["veto_royal_decree", "nullify_royal_decree", "review_royal_decree"]
)
def test_no_branch_may_review_or_nullify_a_royal_decree(action: str) -> None:
    reason = rules_mod._r010_7(_req(action, actor=Branch.JUDICIAL))
    assert reason is not None
    assert "judicial" in reason
    assert "لا ينقضه" in reason or "ولا تنقضه" in reason


def test_rule_ten_seven_ignores_actions_that_are_not_review_of_a_decree() -> None:
    assert rules_mod._r010_7(_req("open_case", actor=Branch.JUDICIAL)) is None


# ── الحكم المقروء (model.py) ────────────────────────────────────────────────


def _violation(rule_id: str = "R-001-1", article: str = "A001") -> RuleViolation:
    return RuleViolation(
        rule_id=rule_id, article_id=article, article_title="الهوية",
        clause="بندٌ مُقتبَس", severity=Severity.CRITICAL, reason="سببٌ مُعلَن",
    )


def test_approved_by_reads_the_declared_branches_only() -> None:
    req = ActionRequest(
        actor=Branch.EXECUTIVE, action="open_case",
        approving_branches=(Branch.JUDICIAL,),
    )
    assert req.approved_by(Branch.JUDICIAL) is True
    assert req.approved_by(Branch.LEGISLATIVE) is False


def test_allow_without_advisory_notes_explains_itself_in_one_line() -> None:
    verdict = Verdict(
        decision=Decision.ALLOW, request_fingerprint="fp", rules_evaluated=7
    )
    text = verdict.explain()
    assert text.startswith("ALLOW")
    assert "ملاحظة" not in text
    assert verdict.allowed is True
    assert verdict.is_sovereign is False
    assert verdict.advisory_articles == ()


def test_a_sovereign_allow_records_its_advisory_notes_without_blocking() -> None:
    verdict = Verdict(
        decision=Decision.ALLOW, request_fingerprint="fp", rules_evaluated=9,
        advisory_violations=(_violation("R-001-1", "A001"), _violation("R-003-1", "A003")),
        decision_kind="SOVEREIGN_ROYAL", authority_layer="CROWN",
    )
    text = verdict.explain()
    assert text.startswith("ALLOW")
    assert "خبر لا نقض" in text
    assert "A001" in text and "A003" in text
    assert verdict.is_sovereign is True
    assert verdict.allowed is True
    assert verdict.violations == ()
    assert verdict.advisory_articles == ("A001", "A003")
    assert verdict.blocking_articles == ()


def test_advisory_articles_are_deduplicated_in_a_stable_order() -> None:
    verdict = Verdict(
        decision=Decision.ALLOW, request_fingerprint="fp", rules_evaluated=3,
        advisory_violations=(
            _violation("R-010-1", "A010"),
            _violation("R-001-1", "A001"),
            _violation("R-010-2", "A010"),
        ),
    )
    assert verdict.advisory_articles == ("A010", "A001")


def test_a_denial_names_the_article_the_clause_and_the_rule() -> None:
    verdict = Verdict(
        decision=Decision.DENY, request_fingerprint="fp", rules_evaluated=9,
        violations=(_violation("R-003-1", "A003"),),
    )
    text = verdict.explain()
    assert text.startswith("DENY")
    assert "A003" in text and "R-003-1" in text and "سببٌ مُعلَن" in text
    assert verdict.allowed is False
    assert verdict.blocking_articles == ("A003",)


def test_the_verdict_dictionary_carries_both_kinds_of_notes() -> None:
    verdict = Verdict(
        decision=Decision.ALLOW, request_fingerprint="fp", rules_evaluated=2,
        violations=(),
        advisory_violations=(_violation(),),
        decision_kind="SOVEREIGN_ROYAL", authority_layer="CROWN",
    )
    payload = verdict.as_dict()
    assert payload["decision"] == "ALLOW"
    assert payload["violations"] == []
    assert payload["advisory_violations"][0]["rule_id"] == "R-001-1"
    assert payload["decision_kind"] == "SOVEREIGN_ROYAL"
    assert payload["authority_layer"] == "CROWN"
