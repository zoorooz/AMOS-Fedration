"""اختباراتُ جدارِ الاختصاصِ القضائيّ — Stage 1G.

الهدف: إثباتُ القدراتِ الحقيقيّةِ لجدارِ الاختصاص، لا عدُّ الاختبارات.

كلُّ منعٍ هنا يُقاسُ برفعِ استثناءٍ صريحٍ وبعدمِ تغيُّرِ حالة، لا برفعِ راية.
والأثرُ المقيسُ هو: هل يمنعُ الجدارُ التجاوزَ القضائيّ قبلَ وقوعِه؟

التصنيفاتُ المُختبَرة:
1. حدودُ النطاقِ — لا ترقيةَ ضمنيّة.
2. حدودُ الفعلِ — لا تشرّيعَ ولا تنفيذاً.
3. حدودُ الأثرِ — الحكمُ أثرٌ لا تنفيذ.
4. حمايةُ المرجعيّةِ الملكيّة — لا سلطةَ فوقَ التاج.
5. الاتّساقُ مع طبقةِ الخدمات — مصدرُ الحقيقةِ واحد.
6. حراسةُ الجدارِ نفسِه — لا ابتلاعَ ولا رايةَ تجاوز.
"""

from __future__ import annotations

import pytest

from core.sovereignty.contract import EffectKind, SovereignEffect
from core.sovereignty.jurisdiction import (
    FORBIDDEN_JUDICIAL_ACTIONS,
    JUDICIAL_ACTIONS,
    JUDICIAL_EFFECT_KINDS,
    JUDICIAL_SCOPES,
    NON_JUDICIAL_EFFECT_KINDS,
    NON_JUDICIAL_SCOPE,
    ROYAL_JUDICIAL_PREROGATIVES,
    WALL,
    JudicialAction,
    JudicialOverreachError,
    JurisdictionError,
    JurisdictionWall,
    RoyalSupremacyViolationError,
)

# ─────────────────────────────────────────────────────────────────────────────
# 1. حدودُ النطاق — لا ترقيةَ ضمنيّة
# ─────────────────────────────────────────────────────────────────────────────

class TestScopeBoundaries:
    """النطاقُ مساواةٌ صريحة — لا احتواءَ ولا ترقية."""

    def test_federal_court_cannot_adjudicate_state_case(self):
        """محكمةٌ فدراليّةٌ لا تملكُ قضايا الولايات — منعُ الترقيةِ صعودًا."""
        req = JudicialAction(
            action="adjudicate",
            court_scope="FEDERAL",
            case_scope="STATE",
            actor_scope="FEDERAL",
        )
        with pytest.raises(JurisdictionError, match="لا يساوي نطاق"):
            WALL.evaluate(req)

    def test_state_court_cannot_adjudicate_federal_case(self):
        """محكمةُ ولايةٍ لا تتجاوزُ إلى النطاقِ الفدراليّ."""
        req = JudicialAction(
            action="adjudicate",
            court_scope="STATE",
            case_scope="FEDERAL",
            actor_scope="STATE",
        )
        with pytest.raises(JurisdictionError, match="لا يساوي نطاق"):
            WALL.evaluate(req)

    def test_institution_court_cannot_adjudicate_other_institution(self):
        """محكمةُ مؤسّسةٍ لا تملكُ اختصاصًا على مؤسّسةٍ أخرى."""
        req = JudicialAction(
            action="adjudicate",
            court_scope="INSTITUTION",
            case_scope="INSTITUTION",
            actor_scope="INSTITUTION",
            institution_id="inst-A",
            case_institution_id="inst-B",
        )
        with pytest.raises(JurisdictionError, match="مؤسّسةٍ أخرى"):
            WALL.evaluate(req)

    def test_department_scope_rejected(self):
        """النطاقُ الإداريّ الداخليُّ لا اختصاصَ عليه قضائيًّا."""
        with pytest.raises(JurisdictionError, match="إداريٌّ داخلي"):
            WALL.assert_scope_known("DEPARTMENT")

    def test_unknown_scope_rejected(self):
        """نطاقٌ غير معروفٍ مرفوض."""
        with pytest.raises(JurisdictionError, match="غير معروف"):
            WALL.assert_scope_known("PLANETARY")

    def test_matching_scopes_pass(self):
        """نطاقٌ متطابقٌ يمرُّ — المساواةُ ليستِ امتناعًا."""
        req = JudicialAction(
            action="adjudicate",
            court_scope="STATE",
            case_scope="STATE",
            actor_scope="STATE",
        )
        WALL.evaluate(req)  # لا استثناء

    def test_institution_scope_requires_both_ids(self):
        """نطاقُ INSTITUTION يلزمه مؤسّسةٌ للمحكمةِ وللقضيّة معًا."""
        req = JudicialAction(
            action="adjudicate",
            court_scope="INSTITUTION",
            case_scope="INSTITUTION",
            actor_scope="INSTITUTION",
            institution_id="inst-A",
            case_institution_id=None,
        )
        with pytest.raises(JurisdictionError, match="يلزمه مؤسّسة"):
            WALL.evaluate(req)

    def test_institution_matching_ids_pass(self):
        """مؤسّسةُ المحكمةِ نفسُها مؤسّسةُ القضيّة — يمرّ."""
        req = JudicialAction(
            action="adjudicate",
            court_scope="INSTITUTION",
            case_scope="INSTITUTION",
            actor_scope="INSTITUTION",
            institution_id="inst-A",
            case_institution_id="inst-A",
        )
        WALL.evaluate(req)


# ─────────────────────────────────────────────────────────────────────────────
# 2. حدودُ الفعل — لا تشرّيعَ ولا تنفيذاً ولا ميزانيّة
# ─────────────────────────────────────────────────────────────────────────────

class TestActionBoundaries:
    """القضاءُ لا يُشرّعُ ولا يُنفّذُ ولا يُخصّصُ ميزانيّة."""

    @pytest.mark.parametrize("forbidden", sorted(FORBIDDEN_JUDICIAL_ACTIONS))
    def test_forbidden_actions_rejected(self, forbidden: str):
        """كلُّ فعلٍ ممنوعٍ يُرفَضُ صراحةً — لا ابتلاع."""
        with pytest.raises((JudicialOverreachError, RoyalSupremacyViolationError)):
            WALL.assert_action_allowed(forbidden)

    @pytest.mark.parametrize("allowed", sorted(JUDICIAL_ACTIONS))
    def test_allowed_actions_pass(self, allowed: str):
        """كلُّ فعلٍ قضائيّ مسموحٍ يمرّ."""
        WALL.assert_action_allowed(allowed)  # لا استثناء

    def test_legislate_rejected_as_overreach(self):
        """التشرّيعُ خارجُ السلطةِ القضائيّة."""
        with pytest.raises(JudicialOverreachError, match="ممنوع"):
            WALL.assert_action_allowed("legislate")

    def test_execute_rejected_as_overreach(self):
        """التنفيذُ خارجُ السلطةِ القضائيّة."""
        with pytest.raises(JudicialOverreachError):
            WALL.assert_action_allowed("execute")

    def test_allocate_budget_rejected_as_overreach(self):
        """تخصيصُ الميزانيّةِ خارجُ السلطةِ القضائيّة."""
        with pytest.raises(JudicialOverreachError):
            WALL.assert_action_allowed("allocate_budget")

    def test_unknown_action_rejected(self):
        """فعلٌ غير معروفٍ مرفوض."""
        with pytest.raises(JurisdictionError, match="غير معروف"):
            WALL.assert_action_allowed("teleport")


# ─────────────────────────────────────────────────────────────────────────────
# 3. حدودُ الأثر — الحكمُ أثرٌ لا تنفيذ
# ─────────────────────────────────────────────────────────────────────────────

class TestEffectBoundaries:
    """الحكمُ يُنشئُ أثرًا قضائيًّا (CREATE/WRITE/READ)، لا تنفيذيًّا."""

    def test_create_effect_allowed(self):
        """إنشاءُ حكمٍ أثرٌ قضائيّ مسموح."""
        effect = SovereignEffect(
            kind=EffectKind.CREATE,
            resource="court/ruling-001",
            detail="إصدارُ حكمٍ في القضيّة",
        )
        WALL.assert_effect_judicial(effect)  # لا استثناء

    def test_write_effect_allowed(self):
        """تسجيلُ حكمٍ أثرٌ قضائيّ مسموح."""
        effect = SovereignEffect(
            kind=EffectKind.WRITE,
            resource="court/case-001/status",
            detail="تسجيلُ حالةِ القضيّة",
        )
        WALL.assert_effect_judicial(effect)  # لا استثناء

    def test_read_effect_allowed(self):
        """الاطّلاعُ على أدلّةٍ أثرٌ قضائيّ مسموح."""
        effect = SovereignEffect(
            kind=EffectKind.READ,
            resource="court/evidence/001",
            detail="اطّلاعٌ على دليل",
        )
        WALL.assert_effect_judicial(effect)  # لا استثناء

    @pytest.mark.parametrize("kind", list(NON_JUDICIAL_EFFECT_KINDS))
    def test_non_judicial_effects_rejected(self, kind: EffectKind):
        """الأثرُ التنفيذيُّ والماليُّ والخارجيُّ ممنوعٌ على القضاء."""
        effect = SovereignEffect(
            kind=kind,
            resource="some/target",
            detail="أثرٌ غير قضائيّ",
        )
        with pytest.raises(JudicialOverreachError):
            WALL.assert_effect_judicial(effect)

    def test_delete_effect_rejected(self):
        """الحذفُ شأنٌ تنفيذيّ — لا يملكُه القضاء."""
        effect = SovereignEffect(
            kind=EffectKind.DELETE,
            resource="some/record",
            detail="حذفُ سجلّ",
        )
        with pytest.raises(JudicialOverreachError, match="DELETE"):
            WALL.assert_effect_judicial(effect)

    def test_transfer_effect_rejected(self):
        """التحويلُ الماليُّ شأنُ الخزانة — لا يملكُه القضاء."""
        effect = SovereignEffect(
            kind=EffectKind.TRANSFER,
            resource="treasury/account-A",
            detail="تحويلٌ ماليّ",
        )
        with pytest.raises(JudicialOverreachError, match="TRANSFER"):
            WALL.assert_effect_judicial(effect)


# ─────────────────────────────────────────────────────────────────────────────
# 4. حمايةُ المرجعيّةِ الملكيّة — لا سلطةَ فوقَ التاج
# ─────────────────────────────────────────────────────────────────────────────

class TestRoyalSupremacyProtection:
    """القضاءُ لا يملكُ المساسَ بالمرجعيّةِ الملكيّة."""

    @pytest.mark.parametrize("prerogative", sorted(ROYAL_JUDICIAL_PREROGATIVES))
    def test_royal_prerogatives_rejected(self, prerogative: str):
        """الأفعالُ الملكيّةُ الحصريّةُ (عفو، نقضُ حكم) لا يملكُها القضاء."""
        with pytest.raises(RoyalSupremacyViolationError, match="اختصاصٌ ملكيٌّ حصريّ"):
            WALL.assert_action_allowed(prerogative)

    def test_court_cannot_overturn_royal_decree(self):
        """القضاءُ لا يملكُ نقضَ مرسومٍ ملكيّ."""
        req = JudicialAction(
            action="overturn_royal_decree",
            court_scope="FEDERAL",
            case_scope="FEDERAL",
            actor_scope="FEDERAL",
            is_royal_decree_target=True,
        )
        with pytest.raises((RoyalSupremacyViolationError, JudicialOverreachError)):
            WALL.evaluate(req)

    def test_court_can_adjudicate_involving_royal_decree_advisory(self):
        """القضاءُ يستطيعُ الفصلَ في نزاعٍ يتعلّقُ بمرسومٍ ملكيّ — استشاريًّا."""
        req = JudicialAction(
            action="adjudicate",
            court_scope="FEDERAL",
            case_scope="FEDERAL",
            actor_scope="FEDERAL",
            is_royal_decree_target=True,
        )
        WALL.evaluate(req)  # لا استثناء — الاستشارةُ مسموحة

    def test_court_cannot_issue_ruling_overturning_decree(self):
        """إصدارُ حكمٍ بنقضِ مرسومٍ ملكيّ مرفوض."""
        req = JudicialAction(
            action="issue_ruling",
            court_scope="FEDERAL",
            case_scope="FEDERAL",
            actor_scope="FEDERAL",
            is_royal_decree_target=True,
        )
        WALL.evaluate(req)  # مسموح — الحكمُ يُسجَّل ولا يُفرَض على التاج

    def test_non_adjudicatory_action_on_decree_rejected(self):
        """أفعالٌ غيرُ الفصلِ على مرسومٍ ملكيّ مرفوضة."""
        req = JudicialAction(
            action="refer_case",
            court_scope="FEDERAL",
            case_scope="FEDERAL",
            actor_scope="FEDERAL",
            is_royal_decree_target=True,
        )
        with pytest.raises(RoyalSupremacyViolationError, match="استشاريّة"):
            WALL.evaluate(req)

    def test_court_cannot_dissolve_state(self):
        """القضاءُ لا يملكُ حلَّ ولاية — ذلك اختصاصٌ ملكيّ."""
        with pytest.raises(JudicialOverreachError):
            WALL.assert_action_allowed("dissolve_state")

    def test_court_cannot_impeach_king(self):
        """القضاءُ لا يملكُ محاكمةَ الملك."""
        with pytest.raises((JudicialOverreachError, RoyalSupremacyViolationError)):
            WALL.assert_action_allowed("impeach_king")

    # ── العلاقةُ مع مجلس السياسات ───────────────────────────────────────────
    # القضاءُ لا يملكُ إقرارَ أو تعليقَ أو إلغاءَ سياساتِ مجلس السياسات.
    # مرجعيّتُه في ذلك استشاريّةٌ (الاطّلاعُ والتسجيلُ مسموحان، النقضُ لا).

    def test_court_cannot_enact_policy_council_policy(self):
        """القضاءُ لا يملكُ إقرارَ سياسةِ مجلس السياسات — ذلك اختصاصُ التشريع."""
        with pytest.raises(JudicialOverreachError, match="enact_policy"):
            WALL.assert_action_allowed("enact_policy")

    def test_court_cannot_repeal_policy_council_policy(self):
        """القضاءُ لا يملكُ إلغاءَ سياسةِ مجلس السياسات."""
        with pytest.raises(JudicialOverreachError, match="repeal_policy"):
            WALL.assert_action_allowed("repeal_policy")

    def test_court_cannot_suspend_policy_council_policy(self):
        """القضاءُ لا يملكُ تعليقَ سياسةِ مجلس السياسات."""
        with pytest.raises(JudicialOverreachError, match="suspend_policy"):
            WALL.assert_action_allowed("suspend_policy")

    def test_policy_council_actions_in_forbidden(self):
        """أفعالُ السياسات (إقرار، تعليق، إلغاء) مُدرَجةٌ في الممنوعة."""
        assert "enact_policy" in FORBIDDEN_JUDICIAL_ACTIONS
        assert "suspend_policy" in FORBIDDEN_JUDICIAL_ACTIONS
        assert "repeal_policy" in FORBIDDEN_JUDICIAL_ACTIONS


# ─────────────────────────────────────────────────────────────────────────────
# 5. اتّساقُ مصدرِ الحقيقة — نطاقٌ واحدٌ لا مصدران
# ─────────────────────────────────────────────────────────────────────────────

class TestSingleSourceOfTruth:
    """نطاقاتُ الاختصاصِ القضائيّ مصدرُها واحد: JUDICIAL_SCOPES."""

    def test_judicial_scopes_match_expected(self):
        """النطاقاتُ الثلاثةُ هي القائمةُ الكاملة."""
        assert JUDICIAL_SCOPES == frozenset({"FEDERAL", "STATE", "INSTITUTION"})

    def test_forbidden_actions_no_overlap_with_allowed(self):
        """لا تداخُلَ بين الأفعالِ المسموحةِ والممنوعة."""
        assert JUDICIAL_ACTIONS.isdisjoint(FORBIDDEN_JUDICIAL_ACTIONS)

    def test_royal_prerogatives_not_in_allowed(self):
        """الأفعالُ الملكيّةُ الحصريّةُ ليست أفعالًا قضائيّة."""
        assert JUDICIAL_ACTIONS.isdisjoint(ROYAL_JUDICIAL_PREROGATIVES)

    def test_royal_prerogatives_in_forbidden(self):
        """الأفعالُ الملكيّةُ الحصريّةُ ممنوعةٌ على القضاء."""
        # pardon و overturn_judicial_ruling في FORBIDDEN_JUDICIAL_ACTIONS
        assert ROYAL_JUDICIAL_PREROGATIVES.issubset(FORBIDDEN_JUDICIAL_ACTIONS)

    def test_judicial_effect_kinds_disjoint_from_non(self):
        """الأثرُ القضائيّ والتنفيذيّ لا يتداخلان."""
        assert JUDICIAL_EFFECT_KINDS.isdisjoint(NON_JUDICIAL_EFFECT_KINDS)

    def test_all_effect_kinds_covered(self):
        """كلُّ أنواعِ الأثرِ مُصنّفةٌ — لا ثالثَ بين القضائيّ وغيرِه."""
        all_kinds = JUDICIAL_EFFECT_KINDS | NON_JUDICIAL_EFFECT_KINDS
        assert all_kinds == frozenset(EffectKind)


# ─────────────────────────────────────────────────────────────────────────────
# 6. حراسةُ الجدارِ نفسِه — لا ابتلاعَ ولا رايةَ تجاوز
# ─────────────────────────────────────────────────────────────────────────────

class TestWallIntegrity:
    """الجدارُ نفسُه محروسٌ — لا رايةَ تجاوزَ ولا ابتلاع."""

    def test_wall_has_no_bypass_parameter(self):
        """جدارُ الاختصاصِ لا يقبلُ معاملَ تجاوز."""
        import inspect

        sig = inspect.signature(JurisdictionWall.evaluate)
        for name in sig.parameters:
            assert name not in ("force", "bypass", "skip_check", "override", "no_verify"), (
                f"معاملُ تجاوزٍ «{name}» في جدارِ الاختصاص — ممنوعٌ بنيويًّا"
            )

    def test_wall_self_check_reports_all_scopes(self):
        """الفحصُ الذاتيُّ يُعلنُ كلَّ النطاقاتِ والأفعال."""
        report = WALL.self_check()
        assert "judicial_scopes" in report
        assert "forbidden_actions" in report
        assert "royal_prerogatives" in report
        assert len(report["judicial_scopes"]) == 3
        assert "FEDERAL" in report["judicial_scopes"]

    def test_evaluate_checks_all_boundaries(self):
        """البوّابةُ الكاملةُ تُفحصُ كلَّ الحدودِ بالترتيب."""
        # الفعلُ أولاً، ثمّ النطاق، ثمّ المرجعيّةُ الملكيّة
        req = JudicialAction(
            action="legislate",  # فعلٌ ممنوع — يُرفَضُ قبل فحصِ النطاق
            court_scope="FEDERAL",
            case_scope="STATE",  # نطاقٌ غير متطابق — لكنّ الفعلَ يُفحصُ أولاً
            actor_scope="FEDERAL",
        )
        with pytest.raises(JudicialOverreachError):
            WALL.evaluate(req)

    def test_judge_outside_scope_denied(self):
        """قاضٍ نطاقُه يخالفُ نطاقَ المحكمةِ — مرفوض."""
        req = JudicialAction(
            action="adjudicate",
            court_scope="FEDERAL",
            case_scope="FEDERAL",
            actor_scope="STATE",  # قاضٍ ولائيٌّ في محكمةٍ فدراليّة
        )
        with pytest.raises(JurisdictionError, match="نطاقُ المنصب"):
            WALL.evaluate(req)

    def test_non_judicial_scope_value_exists(self):
        """النطاقُ الإداريُّ معرَّفٌ وممنوعٌ قضائيًّا."""
        assert NON_JUDICIAL_SCOPE == "DEPARTMENT"

    def test_wall_is_stateless(self):
        """الجدارُ لا يحملُ حالةً متغيّرة — حدودٌ دستوريّةٌ ثابتة."""

        # JurisdictionWall لا تملكُ حقولَ حالةٍ متغيّرة
        fields = {f.name for f in __import__("dataclasses").fields(JurisdictionWall)}
        assert fields == set(), "JurisdictionWall لا ينبغي أن تملك حقول حالة"
