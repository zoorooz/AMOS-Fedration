"""الهدف: جدارُ الاختصاصِ القضائيّ — منعُ تجاوزِ السلطةِ القضائيّةِ لحدودِها الدستوريّة.

النطاق: `core/sovereignty/` — حدودُ الاختصاصِ القضائيّ وعلاقتُه بالمرجعيّةِ الملكيّة.
المالك: core/sovereignty/ — التاج
تاريخ الإنشاء: 2026-08-18
تاريخ آخر تعديل: 2026-08-18

## الفجوةُ التي تسدُّها هذه الوحدة

المادة الثالثة (الفصل بين السلطات) تقول إنّ السلطة القضائيّة «لا تُشرّع، لا تنفّذ».
والمادة العاشرة تقول إنّ الملك هو المرجعيّةُ العليا. ولكن قبل 1G لم يكن في نواة
السيادة **جدارٌ يمنعُ القضاءَ من تجاوزِ حدودِه**:

1. **لا حدودَ للاختصاصِ القضائيّ**: لا يوجد ما يمنعُ محكمةً فدراليّةً من الفصلِ في
   قضيّةِ ولايةٍ (ترقيةٌ ضمنيّة)، ولا ما يمنعُ قاضٍ من خارجِ نطاقِ المحكمةِ من
   الجلوسِ فيها.
2. **لا فصلًا بين الحكمِ والتنفيذِ على المستوى القضائيّ**: لم يكن واضحًا أنّ
   الحكمَ القضائيّ **يُنشئ أثرًا** ولا **يُنفِّذُه** — فالتنفيذُ شأنُ العمودِ
   التنفيذيّ أو الخزانة، لا شأنُ القضاء.
3. **لا حمايةً للمرجعيّةِ الملكيّةِ من تجاوزٍ قضائيّ**: لم يكن صريحًا أنّ القضاءَ
   لا يملكُ نقضَ مرسومٍ ملكيٍّ أو إبطالَه أو تعليقَه، وأنّ مرجعيّتَه في ذلك
   استشاريّةٌ لا سياديّة.

## القرار: جدارٌ دستوريٌّ لا استثناءاتٌ散

لا تُبنى القواعدُ هنا كاستثناءاتٍ `if judicial: deny`، بل كجدارٍ بنيويٍّ يُعرّف
**حدودَ الاختصاصِ القضائيّ** ويمنعُ التجاوزَ قبل وقوعِه:

- **النطاقُ مساواةٌ صريحة**: لا ترقيةَ ولا احتواء. محكمةٌ فدراليّةٌ لا تملكُ
  قضايا الولايات، ومحكمةُ ولايةٍ لا تتجاوزُ إلى الفدراليّة.
- **منُ يُحيلُ ومن يفصلُ**: الإحالةُ والفصلُ صلاحيّتانِ مختلفتان، وكلتاهما
  تُفحَص على نطاقِ المحكمةِ ونطاقِ منصبِ القاضي.
- **الحكمُ أثرٌ لا تنفيذ**: الحكمُ يُنشئُ أثرًا مسجَّلًا (قضائيّ)، والتنفيذُ
  شأنُ العمودِ التنفيذيّ. القضاءُ لا يُحرّكُ مالًا ولا يُقدّمُ مهمّة.
- **لا سلطةَ فوقَ التاج**: القضاءُ لا يملكُ نقضَ مرسومٍ ملكيٍّ ولا تعليقَه ولا
  إبطالَه. مرجعيّتُه في ذلك **استشاريّةٌ** تُسجَّل ولا تُفرَض.
- **لا تشرّعَ ولا تُنفّذَ**: الفصلُ بين السلطاتِ (المادة الثالثة) محروسٌ هنا
  صريحًا: القضاءُ لا يُشرّعُ ولا يُنفّذُ ولا يُخصّصُ ميزانيّة.

## ما ليس مُثبَتًا — بصراحة

- **الجدارُ متاحٌ لا مفروض.** كما في 1F، لا شيءَ اليومَ يُلزِمُ المسارَ القضائيّ
  بالمرورِ عبر هذا الجدار. الفرضُ يلزمه حرسٌ ساكنٌ (1M).
- **لا استئنافَ ولا إحالةً بين المحاكم.** نقلُ قضيّةٍ من نطاقٍ إلى نطاقٍ يحتاج
  إجراءً قضائيًّا مُصمَّمًا (إحالة، ثمّ قبول، ثمّ أثر) — وهذا دَينٌ معلن.
- **لا سلسلةَ حيازةٍ كاملةٍ للأدلّة.** حفظُ الأدلّةِ هنا إشاريٌّ مرجعيٌّ، وليس
  `chain-of-custody` بمعناه القانونيّ الكامل.
- **لا ربطًا مفروضًا بطبقةِ الخدمات.** `federal_judiciary` في طبقةِ الخدماتِ لها
  منطقُها القائم، وهذا الجدارُ هو المرجعُ الدستوريّ لها لا بديلُها.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from core.sovereignty.contract import EffectKind, SovereignEffect

# ─────────────────────────────────────────────────────────────────────────────
# نطاقاتُ الاختصاصِ القضائيّ — مصدرُ الحقيقةِ الأعلى
#
# المادة الثالثة تُحدّدُ أربعةَ فروع: تنفيذيّ، تشريعيّ، قضائيّ، خزانة. والقضاءُ
# يمتدُّ على ثلاثةِ نطاقات: فدراليّ، ولائيّ، مؤسسيّ. ولا رابعَ.
#
# هذا التعدادُ هو **مصدرُ الحقيقةِ** لنطاقاتِ الاختصاصِ القضائيّ. وطبقةُ الخدماتِ
# (`federal_judiciary.models.JURISDICTIONS`) يجبُ أن تطابِقَه تمامًا — يحرسُ ذلك
# اختبارٌ ساكنٌ يمنعُ التباعدَ بين المصدرَين.
# ─────────────────────────────────────────────────────────────────────────────
JUDICIAL_SCOPES: Final[frozenset[str]] = frozenset(
    {
        "FEDERAL",
        "STATE",
        "INSTITUTION",
    }
)

#: النطاقُ غيرُ مسموحٍ به قضائيًّا (إداريّ داخليٌّ — لا محاكمَ داخلَ إدارة)
NON_JUDICIAL_SCOPE: Final[str] = "DEPARTMENT"


# ─────────────────────────────────────────────────────────────────────────────
# الأفعالُ القضائيّة المسموحة — ما يملكُ القضاءُ أن يفعلَه
# ─────────────────────────────────────────────────────────────────────────────
JUDICIAL_ACTIONS: Final[frozenset[str]] = frozenset(
    {
        "refer_case",          # إحالةُ قضيّةٍ إلى المحكمة
        "admit_case",          # قبولُ القضيّةِ للنظر
        "adjudicate",          # الفصلُ في النزاع
        "issue_ruling",        # إصدارُ الحكم
        "vacate_ruling",       # إلغاءُ حكمٍ سابق (داخلَ النطاقِ نفسِه)
        "admit_evidence",      # قبولُ دليل
        "recuse_judge",        # تنحيةُ قاضٍ (إجراءٌ داخليٌّ قضائيّ)
        "register_judgment",   # تسجيلُ الحكمِ في السجلّ
    }
)

# ─────────────────────────────────────────────────────────────────────────────
# الأفعالُ الممنوعةُ على القضاء — ما لا يملكُه أصلًا (المادة الثالثة + العاشرة)
#
# القضاءُ لا يُشرّعُ ولا يُنفّذُ ولا يُخصّصُ ميزانيّة. ولا يملكُ نقضَ مرسومٍ ملكيٍّ
# أو تعليقَه. وهذه ليست توصياتٍ بل حدودٌ دستوريّةٌ صريحة.
# ─────────────────────────────────────────────────────────────────────────────
FORBIDDEN_JUDICIAL_ACTIONS: Final[frozenset[str]] = frozenset(
    {
        # المادة الثالثة — لا تُشرّع
        "legislate",
        "amend_law",
        "enact_policy",
        "suspend_policy",
        "repeal_policy",
        # المادة الثالثة — لا تُنفّذ
        "execute",
        "deploy_service",
        "dispatch_agent",
        "deploy_production",
        # المادة الثالثة — لا تُخصّصُ ميزانيّة
        "allocate_budget",
        "disburse_funds",
        "transfer_treasury",
        # المادة العاشرة — لا سلطةَ فوقَ التاج
        "overturn_royal_decree",
        "suspend_royal_decree",
        "nullify_royal_decree",
        "veto_royal_decree",
        "review_royal_decree",     # المراجعةُ الاستشاريّةُ مسموحة، النقضُ لا
        "impeach_king",
        "depose_king",
        "amend_royal_authority",
        # لا ينشئُ ولاياتٍ ولا مؤسّسات
        "create_state",
        "dissolve_state",
        "create_institution",
        "dissolve_institution",
        # الأفعالُ الملكيّةُ الحصريّةُ في الشأنِ القضائيّ (ممنوعةٌ على القضاء)
        "pardon",
        "overturn_judicial_ruling",
    }
)

#: الأفعالُ التي يملكُها الملكُ وحدَه في الشأنِ القضائيّ (المادة العاشرة · 2 · 7)
ROYAL_JUDICIAL_PREROGATIVES: Final[frozenset[str]] = frozenset(
    {
        "pardon",
        "overturn_judicial_ruling",
    }
)


# ─────────────────────────────────────────────────────────────────────────────
# أنواعُ الأثرِ القضائيّ — ما يُنشئُه الحكمُ لا ما يُنفّذُه
# ─────────────────────────────────────────────────────────────────────────────
JUDICIAL_EFFECT_KINDS: Final[frozenset[EffectKind]] = frozenset(
    {
        EffectKind.CREATE,    # إنشاءُ حكمٍ أو أثرٍ قضائيّ
        EffectKind.WRITE,     # تسجيلُ حكمٍ أو تعديلُ حالةِ قضيّة
        EffectKind.READ,      # اطّلاعٌ على أدلّةٍ أو سجلّات
    }
)

#: الأنواعُ الممنوعةُ على القضاءِ من الأثر (لا يملكُها القضاءُ أصلًا)
NON_JUDICIAL_EFFECT_KINDS: Final[frozenset[EffectKind]] = frozenset(
    {
        EffectKind.DELETE,     # الحذفُ شأنٌ تنفيذيّ، لا قضائيّ
        EffectKind.TRANSFER,   # التحويلُ الماليُّ شأنُ الخزانة
        EffectKind.EXTERNAL,   # التأثيرُ الخارجيُّ شأنٌ تنفيذيّ
    }
)


class JurisdictionError(PermissionError):
    """الاختصاصُ القضائيّ لا يسمحُ بهذا الفعل — رفضٌ مقصودٌ يُرفَع إلى المُنادي."""


class JudicialOverreachError(JurisdictionError):
    """القضاءُ حاولَ فعلًا خارجَ حدودِه الدستوريّة — تجاوزٌ للسلطة."""


class RoyalSupremacyViolationError(JurisdictionError):
    """القضاءُ حاولَ المساسَ بالمرجعيّةِ الملكيّة — لا سلطةَ فوقَ التاج."""


@dataclass(frozen=True, slots=True)
class JudicialAction:
    """طلبُ فعلٍ قضائيّ — ما يُطلَبُ من القضاءِ أن يفعلَه.

    كلُّ حقلٍ هنا يُفحَص ضدَّ الجدار: منُ يُحيل، على أي نطاق، بأي فعّل، وعلى أي هدف.
    ولا يُتركُ شيءٌ للنيّةِ أو للتقدير.
    """

    action: str                    # الفعلُ القضائيّ المطلوب
    court_scope: str               # نطاقُ المحكمة (FEDERAL / STATE / INSTITUTION)
    case_scope: str                # نطاقُ القضيّة
    actor_scope: str               # نطاقُ منصبِ الفاعل (القاضي أو المُحيل)
    target: str = ""               # هدفُ الفعل (معرّفُ القضيّة أو الحكم)
    institution_id: str | None = None  # مؤسّسةُ المحكمة — يلزمُ في نطاق INSTITUTION
    case_institution_id: str | None = None  # مؤسّسةُ القضيّة — يلزمُ في INSTITUTION
    is_royal_decree_target: bool = False    # هل الهدفُ مرسومٌ ملكيّ؟


@dataclass(slots=True)
class JurisdictionWall:
    """جدارُ الاختصاصِ القضائيّ — يمنعُ التجاوزَ قبلَ وقوعِه.

    هذا الجدارُ هو الترجمةُ التشغيليّةُ للمادةِ الثالثة (الفصلُ بين السلطات)
    والمادةِ العاشرة (المرجعيّةُ الملكيّةُ العليا) في سياقِ السلطةِ القضائيّة.

    **ما لا يملكُه هذا الصنفُ هو التنفيذ:** لا يستوردُ `ExecutiveCore` ولا
    `StateTreasury` ولا أيَّ خدمة. وظيفتُه فحصُ الاختصاصِ ومنعُ التجاوز — فحسب.
    والامتناعُ عن التنفيذِ هنا **بنيويٌّ لا سلوكيّ**: لا يوجدُ فيه مسارٌ للصرفِ
    أو للتقديم.
    """

    # ── فحصُ النطاق ────────────────────────────────────────────────────────
    def assert_scope_known(self, scope: str) -> str:
        """اقبلْ نطاقًا معروفًا، وارفضْ ما عداه.

        النطاقُ يجبُ أن يكونَ من `JUDICIAL_SCOPES`. ولا يُقبلُ `DEPARTMENT`
        لأنّه نطاقٌ إداريٌّ داخليٌّ — لا محاكمَ داخلَ إدارة.
        """
        if scope == NON_JUDICIAL_SCOPE:
            raise JurisdictionError(
                f"النطاقُ «{scope}» إداريٌّ داخليٌّ — لا اختصاصَ قضائيًّا على إدارة"
            )
        if scope not in JUDICIAL_SCOPES:
            raise JurisdictionError(
                f"نطاقٌ غير معروف «{scope}» — المسموح: {', '.join(sorted(JUDICIAL_SCOPES))}"
            )
        return scope

    def assert_scope_match(
        self,
        *,
        court_scope: str,
        case_scope: str,
        court_institution_id: str | None = None,
        case_institution_id: str | None = None,
        what: str = "القضيّة",
    ) -> None:
        """اطلبْ مساواةً صريحةً بين نطاقِ المحكمةِ ونطاقِ القضيّة.

        لا ترقيةَ ضمنيّة: محكمةٌ فدراليّةٌ لا تملكُ قضايا الولايات، ومحكمةُ ولايةٍ
        لا تتجاوزُ إلى الفدراليّة. وفي نطاقِ `INSTITUTION` يلزمُ أن تكونَ
        مؤسّسةُ المحكمةِ **هي** المؤسّسة المعنيّة بالقضيّة.
        """
        self.assert_scope_known(court_scope)
        self.assert_scope_known(case_scope)
        if court_scope != case_scope:
            raise JurisdictionError(
                f"نطاقُ المحكمة «{court_scope}» لا يساوي نطاق {what} "
                f"«{case_scope}» — ولا ترقيةَ ضمنيّة بين النطاقات"
            )
        if court_scope == "INSTITUTION":
            if not court_institution_id or not case_institution_id:
                raise JurisdictionError(
                    "نطاقُ INSTITUTION يلزمه مؤسّسةٌ محدَّدة للمحكمةِ وللقضيّة معًا"
                )
            if court_institution_id != case_institution_id:
                raise JurisdictionError(
                    f"محكمةُ المؤسّسة «{court_institution_id}» لا تملكُ اختصاصًا على "
                    f"مؤسّسةٍ أخرى «{case_institution_id}»"
                )

    def assert_actor_in_scope(
        self,
        *,
        actor_scope: str,
        court_scope: str,
    ) -> None:
        """اطلبْ أن يكونَ نطاقُ منصبِ القاضي **هو نفسه** نطاقَ محكمته.

        فمنصبٌ نطاقُه `INSTITUTION` لا يُصدرُ حكمًا في محكمةٍ فدراليّة، ومنصبٌ
        فدراليّ لا يجلسُ تلقائيًّا في محكمةِ ولاية. وهذا ما يمنعُ «قاضٍ خارجَ
        نطاقِه» عمليًّا.
        """
        self.assert_scope_known(actor_scope)
        self.assert_scope_known(court_scope)
        if actor_scope != court_scope:
            raise JurisdictionError(
                f"نطاقُ المنصب «{actor_scope}» لا يساوي نطاقَ المحكمة "
                f"«{court_scope}» — ولا ترقيةَ ضمنيّة"
            )

    # ── فحصُ الفعل ─────────────────────────────────────────────────────────
    def assert_action_allowed(self, action: str) -> None:
        """اقبلْ فعلًا قضائيًّا مسموحًا، وارفضْ ما عداه.

        الأفعالُ المسموحةُ في `JUDICIAL_ACTIONS`. والأفعالُ الممنوعةُ في
        `FORBIDDEN_JUDICIAL_ACTIONS` — وهي ممنوعةٌ لأنّها خارجَ السلطةِ القضائيّة
        أصلًا (تشرّيعٌ أو تنفيذٌ أو مساسٌ بالتاج).
        """
        if action in FORBIDDEN_JUDICIAL_ACTIONS:
            # الأفعالُ الملكيّةُ الحصريّةُ أولى بالفحصِ قبل الممنوعةِ العامة
            if action in ROYAL_JUDICIAL_PREROGATIVES:
                raise RoyalSupremacyViolationError(
                    f"الفعلُ «{action}» اختصاصٌ ملكيٌّ حصريّ (المادة العاشرة · 2 · 7) — "
                    "لا يملكُه القضاءُ ولو بإجماع"
                )
            raise JudicialOverreachError(
                f"الفعلُ «{action}» ممنوعٌ على القضاء — خارجُ حدودِ السلطةِ القضائيّة "
                "(المادة الثالثة / العاشرة)"
            )
        if action not in JUDICIAL_ACTIONS:
            raise JurisdictionError(
                f"فعلٌ قضائيّ غير معروف «{action}» — المسموح: "
                f"{', '.join(sorted(JUDICIAL_ACTIONS))}"
            )

    # ── فحصُ الأثر القضائي ─────────────────────────────────────────────────
    def assert_effect_judicial(self, effect: SovereignEffect) -> None:
        """تأكّدْ أنّ الأثرَ المُنشَأ قضائيٌّ — لا تنفيذيّ ولا ماليّ.

        الحكمُ القضائيّ يُنشئُ أثرًا من نوع `CREATE` أو `WRITE` أو `READ`:
        - `CREATE`: إنشاءُ حكمٍ أو قرارٍ قضائيّ.
        - `WRITE`: تسجيلُ الحكمِ أو تعديلُ حالةِ القضيّة.
        - `READ`: اطّلاعٌ على أدلّةٍ أو سجلّات.

        وأمّا `DELETE` و`TRANSFER` و`EXTERNAL` فخارجةٌ عن السلطةِ القضائيّة:
        الحذفُ شأنٌ تنفيذيّ، والتحويلُ الماليُّ شأنُ الخزانة، والتأثيرُ الخارجيّ
        شأنٌ تنفيذيّ.
        """
        if effect.kind in NON_JUDICIAL_EFFECT_KINDS:
            raise JudicialOverreachError(
                f"الأثرُ «{effect.kind.name}» خارجُ السلطةِ القضائيّة — "
                f"القضاءُ لا يملكُ {effect.kind.arabic}. "
                "(المادة الثالثة: لا تُنفّذ، لا تُخصّص ميزانيّة)"
            )

    # ── فحصُ المرجعيّة الملكيّة ─────────────────────────────────────────────
    def assert_not_above_crown(self, request: JudicialAction) -> None:
        """تأكّدْ أنّ الفعلَ القضائيّ لا يمسُّ المرجعيّةَ الملكيّة.

        القضاءُ لا يملكُ:
        - نقضَ مرسومٍ ملكيٍّ أو تعليقَه أو إبطالَه.
        - مسَّ سلطةِ الملكِ أو تقييدَها.
        - عزلَ الملكِ أو محاكمتَه.

        ومرجعيّةُ القضاءِ في الشأنِ الملكيّ **استشاريّةٌ**: يُسجّلُ رأيَه ولا
        يُفرضُه. والمراجعةُ المسموحةُ هي `review` (اطّلاعٌ وتسجيلٌ)، أمّا
        `overturn` و`suspend` و`nullify` فخارجةٌ عن اختصاصِه.
        """
        if request.is_royal_decree_target and request.action not in (
            "adjudicate",
            "issue_ruling",
        ):
                raise RoyalSupremacyViolationError(
                    f"القضاءُ لا يملكُ الفعلَ «{request.action}» على مرسومٍ ملكيّ — "
                    "مرجعيّتُه في ذلك استشاريّةٌ تُسجَّل ولا تُفرَض "
                    "(المادة العاشرة · 1 · 1 و 11 · 1)"
                )

    # ── البوّابةُ الكاملة ──────────────────────────────────────────────────
    def evaluate(self, request: JudicialAction) -> None:
        """فحصٌ شاملٌ لطلبِ فعلٍ قضائيّ — كلُّ الحدودِ في ممرٍّ واحد.

        الترتيبُ مقصود:
        1. الفعلُ مسموحٌ (لا ممنوعٌ ولا ملكيٌّ حصريّ).
        2. النطاقُ معروفٌ ومتطابقٌ (محكمة = قضيّة = منصب).
        3. لا مساسَ بالمرجعيّةِ الملكيّة.
        4. الأثرُ (إن وُجد) قضائيٌّ لا تنفيذيّ.

        وأيُّ فحصٍ يفشلُ يرفعُ استثناءً صريحًا — لا رايةً منطقيّة ولا ابتلاع.
        """
        self.assert_action_allowed(request.action)
        self.assert_scope_match(
            court_scope=request.court_scope,
            case_scope=request.case_scope,
            court_institution_id=request.institution_id,
            case_institution_id=request.case_institution_id,
        )
        self.assert_actor_in_scope(
            actor_scope=request.actor_scope,
            court_scope=request.court_scope,
        )
        self.assert_not_above_crown(request)

    # ── الفحصُ الذاتي ──────────────────────────────────────────────────────
    def self_check(self) -> dict[str, object]:
        """تقريرُ حالةِ الجدار — مُعلَنٌ لا مخفيّ."""
        return {
            "judicial_scopes": sorted(JUDICIAL_SCOPES),
            "non_judicial_scope": NON_JUDICIAL_SCOPE,
            "judicial_actions": sorted(JUDICIAL_ACTIONS),
            "forbidden_actions": sorted(FORBIDDEN_JUDICIAL_ACTIONS),
            "royal_prerogatives": sorted(ROYAL_JUDICIAL_PREROGATIVES),
            "judicial_effect_kinds": sorted(k.name for k in JUDICIAL_EFFECT_KINDS),
            "non_judicial_effect_kinds": sorted(k.name for k in NON_JUDICIAL_EFFECT_KINDS),
        }


#: مثيلٌ واحدٌ للجدار — لا حالةً متغيّرة، فالحدودُ دستوريّةٌ ثابتة.
WALL: Final[JurisdictionWall] = JurisdictionWall()


__all__ = [
    "FORBIDDEN_JUDICIAL_ACTIONS",
    "JUDICIAL_ACTIONS",
    "JUDICIAL_EFFECT_KINDS",
    "JUDICIAL_SCOPES",
    "NON_JUDICIAL_EFFECT_KINDS",
    "NON_JUDICIAL_SCOPE",
    "ROYAL_JUDICIAL_PREROGATIVES",
    "WALL",
    "JudicialAction",
    "JudicialOverreachError",
    "JurisdictionError",
    "JurisdictionWall",
    "RoyalSupremacyViolationError",
]
