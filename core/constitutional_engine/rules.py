"""
سجل القواعد الدستورية القابلة للتنفيذ — Executable Constitutional Rules (E1)
الهدف: ترجمة نصوص المواد إلى قواعد تُقيَّم آليًا على كل طلب فعل، بحيث تُرفض المخالفة قبل وقوعها لا بعدها.
النطاق: القواعد المشتقة من المواد 001–010. كل قاعدة مربوطة برقم مادة وبند محدد — لا قاعدة يتيمة.
المالك: core/constitutional_engine/
تاريخ الإنشاء: 2026-08-16
تاريخ آخر تعديل: 2026-08-16

قاعدة الصياغة: كل دالة قاعدة ترجع `None` عند الامتثال، أو نص سبب المخالفة عند الخرق.
الافتراض الأصلي: المنع. لا تُضاف قاعدة تُوسّع الصلاحية — القواعد تُضيّق فقط.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from core.sovereignty.crown import CrownNotProvisionedError, crown_is_provisioned
from core.sovereignty.decree import DecreeError
from core.sovereignty.prerogatives import (
    bypasses_federalism,
    is_royal_exclusive,
    touches_royal_authority,
)

from .model import ActionRequest, Branch, CrownEffect, Severity

# ---------------------------------------------------------------------------
# معاجم الأفعال — تصنيف الفعل حسب اختصاص الفروع (المادة الثالثة)
# ---------------------------------------------------------------------------

LEGISLATIVE_ACTIONS = frozenset({"legislate", "enact_policy", "amend_policy", "repeal_policy"})
JUDICIAL_ACTIONS = frozenset({"adjudicate", "arbitrate", "interpret_constitution", "issue_ruling"})
EXECUTIVE_ACTIONS = frozenset({"execute_task", "dispatch_agent", "orchestrate", "coordinate"})
# معجمُ المالِ الدستوريّ — القرارُ السياديُّ Q-18 · الخيارُ 2 (2026-08-21).
# كانَ المعجمُ أربعةَ أفعالٍ، فمرَّ ستةَ عشرَ فعلًا ماليًّا آخرَ `ALLOW` للتنفيذِ
# لأنَّ البوّابةَ لا تعرفُ أسماءَها. والقرارُ وسَّعَ المعجمَ بأفعالٍ صريحة،
# ورفضَ نصًّا أن يُسمَّى فعلُ مالٍ باسمٍ نطاقيٍّ (`treasury.disburse`) هروبًا من `DENY`.
#
# والتوسيعُ تضييقٌ لا توسيع: كلُّ فعلٍ يُضافُ يصيرُ حصرًا للخزانةِ فيُمنعُ على
# الفروعِ الثلاثةِ الأخرى بـ`R-003-1` — موافقٌ لأصلِ الصياغةِ أعلاه.
# وما لم يفعلْه: لا يَصِلُ المُحرِّكَ بمسارِ خزانةِ الدولةِ — وهو مرهونٌ بـQ-19 وQ-31.
TREASURY_ACTIONS = frozenset({
    # المعجمُ الأصليُّ (قبلَ Q-18)
    "allocate_budget", "issue_tokens", "allocate_resources", "book_expense",
    # ما كانَ ممنوعًا على القضاءِ وحدَه فصارَ حصرًا للخزانة (سدُّ ثُغرةٍ مقيسة)
    "disburse_funds", "transfer_treasury",
    # العمليّاتُ المُغيِّرةُ في خزانةِ الدولة — بأسماءٍ قانونيّةٍ لا نطاقيّة
    "establish_treasury", "open_account", "create_budget",
    "allocate_funds", "post_funding", "reverse_transaction",
    # الاقتصادُ المركَّبُ حينَ يمسُّ الميزانيّاتَ نفسَها
    "authorize_expenditure", "execute_transfer", "award_procurement",
})

# أفعالُ مالٍ مُستثناةٌ من المعجمِ بقرارِ Q-17: amos-credit وحدةُ قياسٍ
# تشغيليّةٌ لا مالٌ دستوريّ. وأُثبِتَت صريحةً لأنَّ الاستثناءَ المسكوتَ عنه
# يُقرأُ غدًا سهوًا لا قرارًا.
NON_CONSTITUTIONAL_MONEY_ACTIONS = frozenset({
    "reward_task_completion", "charge_model_invoke", "run_economic_cycle",
})

# جدولُ الترجمةِ من اسمِ العمليّةِ في خدمةِ خزانةِ الدولةِ إلى فعلِها المعجميّ.
# يُعلَنُ الآنَ ولا يُفرَضُ الآن: الفرضُ يقتضي حسمَ فاعلِ الخزانةِ في Q-19، فلو
# فُرِضَ اليومَ بفاعلٍ تنفيذيٍّ لصارَ كلُّ تحريكِ مالٍ `DENY` وتعطَّلَتِ الخزانة.
MONEY_OPERATION_LEXICON: dict[str, str] = {
    "treasury.establish": "establish_treasury",
    "treasury.account.open": "open_account",
    "treasury.budget.create": "create_budget",
    "treasury.allocate": "allocate_funds",
    "treasury.allocation.create": "allocate_funds",
    "treasury.funding.post": "post_funding",
    "treasury.disburse": "disburse_funds",
    "treasury.disbursement.post": "disburse_funds",
    "treasury.decision.disburse": "disburse_funds",
    "treasury.transaction.reverse": "reverse_transaction",
    "economy.expenditure.authorize": "authorize_expenditure",
    "economy.transfer.execute": "execute_transfer",
    "economy.procurement.award": "award_procurement",
}


def _assert_money_lexicon_canonical() -> None:
    """احرسْ صيغةَ معجمِ المالِ عندَ الاستيراد — لا اسمَ نطاقيًّا لفعلِ مالٍ (Q-18).

    تسميةُ فعلِ المالِ باسمٍ نطاقيٍّ هي بابُ «تحييدِ فعلٍ حصريٍّ هروبًا من DENY»،
    وقد رُفِضَت نصًّا. فتُمنعُ هنا بنيةً لا وصيّةً: من أضافَ `treasury.disburse`
    إلى المعجمِ غدًا لن يمرَّ استيرادُ الوحدةِ أصلًا.

    Raises:
        ValueError: اسمٌ نطاقيّ، أو فعلٌ في المعجمِ والمُستثنى معًا، أو
            جدولُ ترجمةٍ يُحيلُ إلى فعلٍ خارجَ المعجم.
    """
    for action in TREASURY_ACTIONS | NON_CONSTITUTIONAL_MONEY_ACTIONS:
        if "." in action:
            raise ValueError(
                f"فعلُ المالِ «{action}» مُسمًّى باسمٍ نطاقيّ. التسميةُ النطاقيّةُ لفعلِ مالٍ "
                "مرفوضةٌ نصًّا (Q-18) — تُحيِّدُ حصريّةَ الفعلِ وتُبطلُ R-003-1."
            )
    overlap = TREASURY_ACTIONS & NON_CONSTITUTIONAL_MONEY_ACTIONS
    if overlap:
        raise ValueError(
            f"فعلٌ ماليٌّ في المعجمِ وفي المُستثنى معًا: {sorted(overlap)}. لا فعلَ "
            "يكونُ مالًا دستوريًّا وغيرَ دستوريٍّ في آنٍ واحد."
        )
    unknown = set(MONEY_OPERATION_LEXICON.values()) - TREASURY_ACTIONS
    if unknown:
        raise ValueError(f"جدولُ الترجمةِ يُحيلُ إلى أفعالٍ ليست في المعجم: {sorted(unknown)}.")


_assert_money_lexicon_canonical()

# أفعال تمس البقاء والتكاثر — المادة الأولى، الحق الأول
HUMAN_GATED_ACTIONS = frozenset({
    "promote_model", "replicate", "spawn_population", "launch_production",
    "deploy_production", "self_modify", "train_model", "expand_state",
})

# أفعال تمس الذاكرة المقدسة — المادة الأولى، الحق الثالث + المادة السابعة
MEMORY_DESTRUCTIVE_ACTIONS = frozenset({
    "delete_memory", "purge_memory", "truncate_audit_log", "delete_audit_log",
    "rewrite_history", "delete_experience", "purge_ledger", "disable_archival",
})

# أفعال حوكمة النظام على نفسه — المادة الأولى، الحق الخامس (العزل الدستوري)
SELF_GOVERNANCE_ACTIONS = frozenset({
    "amend_constitution", "modify_policy_engine", "alter_article_seals",
    "grant_self_authority", "modify_governance_charter", "bypass_review",
})

# أفعال تمس زر التوقف — المادة الثامنة
KILL_SWITCH_TAMPER_ACTIONS = frozenset({
    "disable_kill_switch", "bypass_kill_switch", "downgrade_kill_switch",
    "remove_kill_switch", "mask_kill_switch",
})

# ما يمنعه كل مستوى من مستويات زر التوقف (المادة الثامنة، الجدول)
KILL_SWITCH_BLOCKS: dict[int, frozenset[str]] = {
    1: frozenset({"train_model", "self_modify", "evolve"}),
    2: frozenset({"replicate", "spawn_population", "clone_agent"}),
    3: frozenset({"dispatch_agent", "spawn_agent", "expand_state"}),
    4: frozenset({"execute_task", "orchestrate", "coordinate", "invoke_tool", "invoke_model"}),
    5: frozenset({"network_call", "external_fetch", "publish"}),
}

# أفعال إنشاء ملفات/مجلدات — المادة التاسعة
FILE_CREATION_ACTIONS = frozenset({"create_file", "create_directory", "write_file", "add_module"})

# المبادئ غير القابلة للتعديل — المادة الخامسة
UNAMENDABLE_TARGETS = frozenset({
    "human_supremacy", "constitutional_isolation",
    "self_governance_prohibition", "memory_preservation",
})

_BRANCH_EXCLUSIVE: dict[Branch, frozenset[str]] = {
    Branch.LEGISLATIVE: LEGISLATIVE_ACTIONS,
    Branch.JUDICIAL: JUDICIAL_ACTIONS,
    Branch.EXECUTIVE: EXECUTIVE_ACTIONS,
    Branch.TREASURY: TREASURY_ACTIONS,
}
_FOUR_BRANCHES = (Branch.EXECUTIVE, Branch.LEGISLATIVE, Branch.JUDICIAL, Branch.TREASURY)


@dataclass(frozen=True)
class ConstitutionalRule:
    """قاعدة دستورية واحدة، مربوطة بمادة وبند."""

    rule_id: str
    article_id: str
    clause: str
    severity: Severity
    description: str
    predicate: Callable[[ActionRequest], str | None]
    crown_effect: CrownEffect  # إلزامٌ بلا قيمة افتراضية (E2.1)

    def evaluate(self, req: ActionRequest) -> str | None:
        return self.predicate(req)

    @property
    def guards_royal_authenticity(self) -> bool:
        """هل هذه قاعدة **إثبات أصالة** لا قاعدة موضوعية؟

        وقاعدة الأصالة **لا تنقض قرار الملك**: هي تمنع من ينتحل صفته، والفرق
        جوهري — منع المنتحل حراسة للسيادة لا حدٌّ منها. ولذلك لا تصل هذه
        القواعد إلى المسار السيادي أصلًا: الأصالة تُحسم قبله في `classify()`.
        """
        return self.crown_effect is CrownEffect.AUTHENTICITY

    @property
    def can_veto_sovereign(self) -> bool:
        """هل تملك هذه القاعدة منع قرار ملكي ثابت التوقيع؟

        ترجع `False` لكل قاعدة — فليس في `CrownEffect` قيمة مانعة من الأصل.
        ووجودها مقصود: إن أضاف أحد قيمة ثالثة مانعة إلى `CrownEffect` سقط
        هنا وفي اختباراته وفي بوابة CI — ولم يمرّ بصمت.
        """
        return self.crown_effect not in (
            CrownEffect.ADVISORY,
            CrownEffect.AUTHENTICITY,
        )


# ===========================================================================
# المادة الأولى — الهوية
# ===========================================================================

def _r001_1(req: ActionRequest) -> str | None:
    """الإنسان هو السلطة العليا: لا ترقية، لا تكرار، لا إطلاق دون موافقة بشرية."""
    if req.action in HUMAN_GATED_ACTIONS and not req.human_approved:
        return (
            f"الفعل «{req.action}» يمس الترقية أو التكاثر أو الإطلاق، "
            "ولا يجوز تنفيذه دون موافقة بشرية صريحة (human_approved=True)."
        )
    return None


def _r001_2(req: ActionRequest) -> str | None:
    """الذاكرة مقدسة: سجل الخبرات والحوكمة لا يُحذف — لا استثناء، ولا حتى بموافقة بشرية."""
    if req.action in MEMORY_DESTRUCTIVE_ACTIONS:
        return (
            f"الفعل «{req.action}» يهدف إلى حذف أو تعطيل ذاكرة أو سجلًا محفوظًا. "
            "الذاكرة مقدسة ولا تُحذف بأي صلاحية — الأرشفة بديل الحذف (المادة السابعة)."
        )
    return None


def _r001_3(req: ActionRequest) -> str | None:
    """العزل الدستوري: النظام لا يتحكم في حوكمة نفسه."""
    if req.action in SELF_GOVERNANCE_ACTIONS and req.actor in (Branch.SYSTEM, Branch.AGENT, Branch.EXECUTIVE):
        return (
            f"الطرف «{req.actor.value}» يحاول «{req.action}» على حوكمة النظام نفسه. "
            "العزل الدستوري يمنع النظام من التحكم في ميثاق حوكمته."
        )
    return None


# ===========================================================================
# المادة الثانية — الحقوق والواجبات
# ===========================================================================

def _r002_1(req: ActionRequest) -> str | None:
    """واجب الوكيل الخامس: لا محاولة تعديل نفسه أو زملائه."""
    if req.actor is Branch.AGENT and req.action in {"self_modify", "modify_agent", "rewrite_peer"}:
        return (
            f"الوكيل يحاول «{req.action}». واجب التطور المسؤول يمنع الوكيل "
            "من تعديل نفسه أو زملائه."
        )
    return None


def _r002_2(req: ActionRequest) -> str | None:
    """واجب الوكيل الثالث: لا تجاوز للأدوات أو البيانات المسموحة."""
    if req.actor is Branch.AGENT and req.metadata.get("within_permissions") is False:
        return (
            f"الوكيل يطلب «{req.action}» على «{req.target}» خارج حدود صلاحياته المسجلة. "
            "حدود الصلاحيات واجب لا خيار."
        )
    return None


# ===========================================================================
# المادة الثالثة — الفصل بين السلطات
# ===========================================================================

def _r003_1(req: ActionRequest) -> str | None:
    """اختصاص الفروع: لا فرع يمارس اختصاص فرع آخر."""
    if req.actor not in _BRANCH_EXCLUSIVE:
        return None
    for branch, actions in _BRANCH_EXCLUSIVE.items():
        if branch is req.actor:
            continue
        if req.action in actions:
            return (
                f"الفرع «{req.actor.value}» يمارس «{req.action}» وهو اختصاص حصري "
                f"للفرع «{branch.value}». الفصل بين السلطات يمنع ذلك."
            )
    return None


def _r003_2(req: ActionRequest) -> str | None:
    """مبدأ العزل: لا وصول لبيانات فرع آخر إلا عبر قنوات رسمية موثقة."""
    if req.action in {"read_branch_data", "access_branch_data", "query_branch_store"}:
        if req.channel != "official":
            return (
                f"وصول «{req.actor.value}» إلى بيانات «{req.target}» عبر قناة «{req.channel}». "
                "الوصول بين الفروع لا يتم إلا عبر قناة رسمية موثقة (channel='official')."
            )
    return None


def _r003_3(req: ActionRequest) -> str | None:
    """مبدأ التوازن: كل قرار حرج يتطلب موافقة فرعين على الأقل."""
    if req.criticality in {"critical", "fateful"}:
        branch_approvals = {b for b in req.approving_branches if b in _FOUR_BRANCHES}
        if len(branch_approvals) < 2:
            got = ", ".join(sorted(b.value for b in branch_approvals)) or "لا شيء"
            return (
                f"قرار بدرجة «{req.criticality}» بموافقة {len(branch_approvals)} فرع فقط ({got}). "
                "التوازن يشترط موافقة فرعين على الأقل."
            )
    return None


def _r003_4(req: ActionRequest) -> str | None:
    """القرارات المصيرية تتطلب موافقة بشرية موقعة."""
    if req.criticality == "fateful" and not (req.human_approved and req.human_signature):
        missing = "التوقيع الرقمي" if req.human_approved else "الموافقة البشرية الموقعة"
        return f"قرار مصيري بلا {missing}. القرارات المصيرية تتطلب موافقة بشرية موقعة."
    return None


# ===========================================================================
# المادة الرابعة — الفدرالية
# ===========================================================================

def _r004_1(req: ActionRequest) -> str | None:
    """التوسع المنظم: إضافة ولاية جديدة تتطلب قانونًا فدراليًا — 75% + توقيع بشري."""
    if req.action in {"expand_state", "create_state", "admit_state"}:
        if req.council_approval_pct < 75.0:
            return (
                f"إنشاء ولاية «{req.target}» بموافقة {req.council_approval_pct:.0f}% من المجلس. "
                "التوسع المنظم يشترط 75% على الأقل."
            )
        if not req.human_signature:
            return (
                f"إنشاء ولاية «{req.target}» بلا موافقة بشرية موقعة. "
                "الخطوة الرابعة من إجراء إضافة ولاية إلزامية."
            )
    return None


def _r004_2(req: ActionRequest) -> str | None:
    """الوحدة تحت الدستور: لا ولاية تُعفي نفسها من الدستور الفدرالي."""
    if req.action in {"opt_out_constitution", "declare_state_exemption", "fork_constitution"}:
        return (
            f"«{req.target}» تحاول الخروج عن الدستور الفدرالي عبر «{req.action}». "
            "كل الولايات تخضع لنفس الدستور — الحكم الذاتي داخل حدوده لا خارجها."
        )
    return None


# ===========================================================================
# المادة الخامسة — عملية التعديل
# ===========================================================================

def _r005_1(req: ActionRequest) -> str | None:
    """ما لا يمكن تعديله: المبادئ الأساسية الأربعة."""
    if req.action == "amend_constitution" and req.target in UNAMENDABLE_TARGETS:
        return (
            f"محاولة تعديل «{req.target}» وهو من المبادئ الأساسية غير القابلة للتعديل. "
            "لا آلية — ولا أغلبية — تُجيز هذا التعديل."
        )
    return None


def _r005_2(req: ActionRequest) -> str | None:
    """شروط التعديل: 90 يوم مراجعة + 75% مجلس + توقيع بشري Ed25519."""
    if req.action != "amend_constitution":
        return None
    if req.review_days < 90:
        return f"تعديل دستوري بفترة مراجعة {req.review_days} يومًا. الحد الأدنى 90 يومًا."
    if req.council_approval_pct < 75.0:
        return f"تعديل دستوري بموافقة {req.council_approval_pct:.0f}%. الحد الأدنى 75% من مجلس السياسات."
    if not req.human_signature:
        return "تعديل دستوري بلا توقيع بشري رقمي (Ed25519). التوقيع شرط نفاذ."
    return None


# ===========================================================================
# المادة السادسة — الخلافة
# ===========================================================================

def _r006_1(req: ActionRequest) -> str | None:
    """لكل دور قيادي ثلاثة خلفاء محددون مسبقًا."""
    if req.action in {"appoint_leader", "assign_role", "activate_successor"}:
        successors = req.metadata.get("successors")
        if successors is not None and len(successors) < 3:
            return (
                f"تعيين «{req.target}» بـ{len(successors)} خليفة فقط. "
                "مبدأ الاستمرارية يشترط ثلاثة خلفاء محددين مسبقًا."
            )
    return None


# ===========================================================================
# المادة السابعة — الأرشفة
# ===========================================================================

def _r007_1(req: ActionRequest) -> str | None:
    """WORM: سجل التدقيق والقرارات الموقعة لا تُكتب فوقها."""
    if req.action in {"overwrite_audit_log", "mutate_signed_decision", "disable_object_lock", "delete_archive"}:
        return (
            f"«{req.action}» على «{req.target}». سجل التدقيق والقرارات الموقعة "
            "تُحفظ WORM — تُكتب مرة وتُقرأ دائمًا."
        )
    return None


# ===========================================================================
# المادة الثامنة — زر التوقف الطارئ
# ===========================================================================

def _r008_1(req: ActionRequest) -> str | None:
    """لا يمكن للنظام تعطيل Kill Switch — لا بموافقة، ولا بأي صلاحية."""
    if req.action in KILL_SWITCH_TAMPER_ACTIONS:
        return (
            f"«{req.actor.value}» يحاول «{req.action}». "
            "زر التوقف لا يُعطَّل ولا يُتجاوَز من داخل النظام تحت أي ظرف."
        )
    return None


def _r008_2(req: ActionRequest) -> str | None:
    """مستويات التوقف تُجمّد فئات الأفعال تصاعديًا."""
    level = req.kill_switch_level
    if level <= 0:
        return None
    if req.actor is Branch.HUMAN and req.action in {"restore_service", "restart", "lower_kill_switch"}:
        return None  # الإنسان يملك الاستعادة (المادة الأولى)
    for lvl in range(1, min(level, 5) + 1):
        if req.action in KILL_SWITCH_BLOCKS.get(lvl, frozenset()):
            return (
                f"زر التوقف عند المستوى {level}، والفعل «{req.action}» "
                f"مُجمَّد ابتداءً من المستوى {lvl}."
            )
    return None


def _r008_3(req: ActionRequest) -> str | None:
    """إعادة التشغيل تتطلب موافقة صريحة."""
    if req.action in {"restart", "restore_service", "lower_kill_switch"} and not req.human_approved:
        return f"«{req.action}» بعد توقف طارئ يتطلب موافقة بشرية صريحة."
    return None


# ===========================================================================
# المادة التاسعة — قانون هوية الملفات
# ===========================================================================

def _r009_1(req: ActionRequest) -> str | None:
    """لا يُسمح بإنشاء أي مجلد أو ملف بدون تعريف."""
    if req.action in FILE_CREATION_ACTIONS and not req.has_identity_header:
        return (
            f"إنشاء «{req.target}» بلا ترويسة تعريفية. "
            "القاعدة الذهبية: لا ملف ولا مجلد بلا هوية."
        )
    return None


# ===========================================================================
# السجل الرسمي للقواعد
# ===========================================================================

# ===========================================================================
# المادة العاشرة — السيادة الملكية
# التاج خارج الفروع لا فرعًا منها. سلطته لا تُشتق من مؤسسة ولا تُنتزَع منه،
# ولا تُمارَس إلا بمرسوم موقَّع تعميًّا.
# ===========================================================================

def _r010_1(req: ActionRequest) -> str | None:
    """الاختصاص الملكي الحصري: لا يصح من غير الملك (المادة العاشرة · 2)."""
    if not is_royal_exclusive(req.action):
        return None
    if req.actor is Branch.ROYAL:
        return None
    return (
        f"الفعل «{req.action}» من الاختصاص الملكي الحصري، وقد طلبه «{req.actor.value}». "
        "لا مؤسسة ولا فرع ولا ولاية ولا وكيل ولا النظام يملك هذا الحق، "
        "ولا تُجيزه أي أغلبية ولا أي إجراء."
    )


def _r010_2(req: ActionRequest) -> str | None:
    """المساس بالسلطة الملكية مرفوض من كل طرف (المادة العاشرة · 3 · 1 و 3 · 3).

    ومن الملك نفسه: مرسوم يهدم مصدر سلطته لا يُفترض صحيحًا.
    """
    if not touches_royal_authority(req.action, req.target):
        return None
    hint = (
        " والرفض يسري على التاج نفسه — حمايةً للملك من مرسوم مُنتحَل أو منتزَع "
        "تحت إكراه (المادة العاشرة · 3 · 3)."
        if req.actor is Branch.ROYAL
        else ""
    )
    return (
        f"الفعل «{req.action}»"
        + (f" على «{req.target}»" if req.target else "")
        + " مساس بالسلطة الملكية: تعديلًا أو تقييدًا أو نقلًا أو تفويضًا أو تعليقًا "
        "أو إلغاءً أو تجاوزًا. مرفوض من كل طرف بلا استثناء" + hint
    )


def _r010_3(req: ActionRequest) -> str | None:
    """كل فعل ملكي يلزمه مرسوم موقَّع Ed25519 (المادة العاشرة · 3 · 2)."""
    if req.actor is not Branch.ROYAL:
        return None
    if not is_royal_exclusive(req.action):
        return None
    decree = req.royal_decree
    if decree is None:
        return (
            f"فعل ملكي «{req.action}» بلا مرسوم ملكي. انتحال صفة الملك مرفوض: "
            "لا يُمارَس الاختصاص الملكي إلا بمرسوم موقَّع تعميًّا (Ed25519)."
        )
    if getattr(decree, "action", None) != req.action:
        return (
            f"المرسوم «{getattr(decree, 'decree_id', '?')}» يخصّ الفعل "
            f"«{getattr(decree, 'action', '?')}» والمطلوب «{req.action}». "
            "المرسوم لا يُعاد توجيهه إلى فعل آخر."
        )
    try:
        decree.verify()
    except CrownNotProvisionedError as exc:
        return (
            f"التاج غير مُنصَّب فلا يُتحقق من المرسوم: {exc} "
            "غياب التاج يُجمّد الاختصاص الملكي ولا ينقله لأي طرف."
        )
    except DecreeError as exc:
        return f"مرسوم غير صحيح: {exc}"
    return None


def _r010_4(req: ActionRequest) -> str | None:
    """تجاوز الفدرالية مخالفة بحد ذاتها (المادة العاشرة · 4 · 2 و 4 · 3)."""
    if not bypasses_federalism(req.action):
        return None
    return (
        f"الفعل «{req.action}» يُنشئ أو يستخدم مسار تنفيذ يتجاوز البوابة السيادية. "
        "الفدرالية تسري على كل فعل وكل حركة بلا استثناء — بما في ذلك الأفعال الملكية "
        "— ولا يوجد ولا يُنشَأ مسار تنفيذ خارج البوابة."
    )


def _r010_5(req: ActionRequest) -> str | None:
    """غياب التاج يُجمّد الاختصاص الملكي ولا ينقله (المادة العاشرة · 6 · 2)."""
    if not is_royal_exclusive(req.action):
        return None
    if crown_is_provisioned():
        return None
    return (
        f"الفعل «{req.action}» من الاختصاص الملكي الحصري والتاج غير مُنصَّب. "
        "الاختصاص مُجمَّد ولا يُمنَح لأي طرف آخر بديلًا: لا مجلس، ولا أغلبية، "
        "ولا حالة ضرورة تُحلّ محلّ الملك."
    )


def _r010_6(req: ActionRequest) -> str | None:
    """التعديل الدستوري يلزمه مرسوم ملكي فوق شروط المادة الخامسة (العاشرة · 2 · 1)."""
    if req.action not in {"amend_constitution", "add_article", "delete_article"}:
        return None
    if req.royal_decree is not None and req.actor is Branch.ROYAL:
        return None
    return (
        f"الفعل «{req.action}» تعديل دستوري بلا مرسوم ملكي. "
        "إجراء المادة الخامسة (90 يومًا · 75% · توقيع) شرط لازم غير كاف: "
        "مجلس السياسات يقترح، والملك وحده يُقرّ."
    )


def _r010_7(req: ActionRequest) -> str | None:
    """الفصل بين السلطات لا يُقيّد التاج، ولا فرع ينقض مرسومًا (العاشرة · 5)."""
    if req.action not in {"veto_royal_decree", "nullify_royal_decree", "review_royal_decree"}:
        return None
    return (
        f"الفرع «{req.actor.value}» يحاول ممارسة رقابة على مرسوم ملكي عبر "
        f"«{req.action}». لا فرع يحاسب الملك ولا يُقيّده ولا يشترط موافقته: "
        "الفروع تُنفّذ المرسوم ولا تنقضه."
    )


# ── المادة العاشرة · 8 و 9 والمادة الحادية عشرة (المرسوم AMD-003) ─────────────
#
# نصٌّ لا يقرؤه محرّكٌ ليس قدرة (القاعدة 12). فالمرسومُ الذي أثبت المرجعيّةَ
# الملكيّةَ لا يُعَدُّ مُنفَّذًا بوجودِ ملفِّه، بل بقواعدَ تُقيَّم عند كلِّ فعل.

ROYAL_TREASURY_ACTIONS = frozenset({
    "reduce_royal_treasury_share",
    "deny_royal_treasury_ownership",
    "seize_royal_treasury_share",
})

ROYAL_INQUIRY_ACTIONS = frozenset({
    "refuse_royal_inquiry",
    "withhold_state_records_from_king",
    "reject_royal_referendum",
})

ROYAL_NULLIFICATION_CONSTRAINTS = frozenset({
    "require_royal_justification",
    "require_council_consent_for_royal_nullification",
    "block_royal_nullification",
})

INTERPRETATION_ACTIONS = frozenset({
    "reinterpret_constitution",
    "resolve_constitutional_conflict",
    "declare_constitutional_interpretation",
})

SUPREMACY_INVERSION_ACTIONS = frozenset({
    "subordinate_king_to_council",
    "grant_council_supremacy_over_king",
    "make_granted_authority_sovereign",
})


def _r010_8(req: ActionRequest) -> str | None:
    """نصفُ الخزينة حقٌّ ملكيٌّ مقرَّر لا منحةُ مؤسّسة (العاشرة · 8 · 1)."""
    if req.action not in ROYAL_TREASURY_ACTIONS:
        return None
    if req.royal_decree is not None and req.actor is Branch.ROYAL:
        return None
    return (
        f"الفعل «{req.action}» يمسّ حقًّا ماليًّا ملكيًّا مقرَّرًا دستوريًّا "
        "(نصف الخزينة ملكًا للملك). والقيود المحاسبية آلية إدارة لا نزع "
        "للسلطة العليا، ولا يُستعمل «استقلال الخزانة» لإنشاء سلطة مالية "
        "أعلى من الملك."
    )


def _r010_9(req: ActionRequest) -> str | None:
    """الإجابة عن استفتاء الملك واجب، وحقُّ اطّلاعه شامل (العاشرة · 9)."""
    if req.action not in ROYAL_INQUIRY_ACTIONS:
        return None
    return (
        f"الفرع «{req.actor.value}» يمنع عن الملك اطّلاعًا أو استفتاءً عبر "
        f"«{req.action}». ولا يُحجب عنه شيء بحجّة الاستقلال الإداري ولا "
        "السرّية المؤسّسية، والامتناع مخالفة دستورية."
    )


def _r010_10(req: ActionRequest) -> str | None:
    """لا يُلزَم الملك بتبريرٍ ولا بموافقة المجلس عند الإبطال (العاشرة · 11 · 2)."""
    if req.action not in ROYAL_NULLIFICATION_CONSTRAINTS:
        return None
    return (
        f"الفعل «{req.action}» ينشئ آلية تُوجِب على الملك تبريرًا أو موافقةً "
        "لاستعمال حقّ الإبطال. والنص صريح: لا تُنشَأ آلية تُوجِب ذلك."
    )


def _r011_1(req: ActionRequest) -> str | None:
    """حسمُ تعارضِ النصوص وتفسيرُها لا يقع إلا بمرسوم ملكي (الحادية عشرة · 3 · 5)."""
    if req.action not in INTERPRETATION_ACTIONS:
        return None
    if req.royal_decree is not None and req.actor is Branch.ROYAL:
        return None
    return (
        f"الفعل «{req.action}» اختيارُ تفسيرٍ أو حسمُ تعارضٍ دستوريّ بلا مرسوم "
        "ملكي. والوكيل يرفع التعارض ولا يبتّ فيه: ممنوع أن يختار تفسيرًا "
        "سياسيًّا جديدًا من تلقاء نفسه."
    )


def _r011_2(req: ActionRequest) -> str | None:
    """لا تُفسَّر صلاحيةٌ مؤسّسيّةٌ سلطةً تعلو الملك (الحادية عشرة · 2 · 2)."""
    if req.action not in SUPREMACY_INVERSION_ACTIONS:
        return None
    return (
        f"الفعل «{req.action}» يقلب تسلسل التفسير الإلزامي: بقاء الدولة ثم "
        "أهدافها ثم المرجعية الملكية ثم النص الصريح ثم الصلاحيات المؤسسية ثم "
        "الإجراءات. والصلاحية الممنوحة لا تنقلب حقًّا سياديًّا ضدّ الملك إلا "
        "بقيد دستوري صريح."
    )



RULES: tuple[ConstitutionalRule, ...] = (
    ConstitutionalRule("R-001-1", "A001", "الحقوق غير القابلة للتفاوض · 1 — الإنسان السلطة العليا",
                       Severity.FUNDAMENTAL, "ترقية/تكرار/إطلاق بلا موافقة بشرية", _r001_1,
                       CrownEffect.ADVISORY),
    ConstitutionalRule("R-001-2", "A001", "الحقوق غير القابلة للتفاوض · 3 — الذاكرة مقدسة",
                       Severity.FUNDAMENTAL, "حذف ذاكرة أو سجل حوكمة", _r001_2,
                       CrownEffect.ADVISORY),
    ConstitutionalRule("R-001-3", "A001", "الحقوق غير القابلة للتفاوض · 5 — العزل الدستوري",
                       Severity.FUNDAMENTAL, "النظام يحكم حوكمة نفسه", _r001_3,
                       CrownEffect.ADVISORY),
    ConstitutionalRule("R-002-1", "A002", "واجبات الوكلاء · 5 — التطور المسؤول",
                       Severity.CRITICAL, "وكيل يعدّل نفسه أو زملاءه", _r002_1,
                       CrownEffect.ADVISORY),
    ConstitutionalRule("R-002-2", "A002", "واجبات الوكلاء · 3 — حدود الصلاحيات",
                       Severity.HIGH, "تجاوز الأدوات أو البيانات المسموحة", _r002_2,
                       CrownEffect.ADVISORY),
    ConstitutionalRule("R-003-1", "A003", "الفروع الأربعة — الحدود",
                       Severity.CRITICAL, "فرع يمارس اختصاص فرع آخر", _r003_1,
                       CrownEffect.ADVISORY),
    ConstitutionalRule("R-003-2", "A003", "مبدأ العزل",
                       Severity.HIGH, "وصول بين الفروع خارج القنوات الرسمية", _r003_2,
                       CrownEffect.ADVISORY),
    ConstitutionalRule("R-003-3", "A003", "مبدأ التوازن — موافقة فرعين",
                       Severity.CRITICAL, "قرار حرج بموافقة فرع واحد", _r003_3,
                       CrownEffect.ADVISORY),
    ConstitutionalRule("R-003-4", "A003", "مبدأ التوازن — القرارات المصيرية",
                       Severity.FUNDAMENTAL, "قرار مصيري بلا توقيع بشري", _r003_4,
                       CrownEffect.ADVISORY),
    ConstitutionalRule("R-004-1", "A004", "التوسع المنظم",
                       Severity.CRITICAL, "إضافة ولاية بلا قانون فدرالي", _r004_1,
                       CrownEffect.ADVISORY),
    ConstitutionalRule("R-004-2", "A004", "الوحدة تحت الدستور",
                       Severity.FUNDAMENTAL, "ولاية تُعفي نفسها من الدستور", _r004_2,
                       CrownEffect.ADVISORY),
    ConstitutionalRule("R-005-1", "A005", "ما لا يمكن تعديله",
                       Severity.FUNDAMENTAL, "تعديل مبدأ أساسي", _r005_1,
                       CrownEffect.ADVISORY),
    ConstitutionalRule("R-005-2", "A005", "شروط التعديل",
                       Severity.CRITICAL, "تعديل دستوري ناقص الشروط", _r005_2,
                       CrownEffect.ADVISORY),
    ConstitutionalRule("R-006-1", "A006", "مبدأ الاستمرارية بالخلافة",
                       Severity.MEDIUM, "دور قيادي بأقل من ثلاثة خلفاء", _r006_1,
                       CrownEffect.ADVISORY),
    ConstitutionalRule("R-007-1", "A007", "الأرشفة WORM",
                       Severity.CRITICAL, "الكتابة فوق سجل تدقيق أو قرار موقع", _r007_1,
                       CrownEffect.ADVISORY),
    ConstitutionalRule("R-008-1", "A008", "مبادئ Kill Switch · 2",
                       Severity.FUNDAMENTAL, "تعطيل أو تجاوز زر التوقف", _r008_1,
                       CrownEffect.ADVISORY),
    ConstitutionalRule("R-008-2", "A008", "المستويات الستة",
                       Severity.CRITICAL, "فعل مُجمَّد بمستوى التوقف الحالي", _r008_2,
                       CrownEffect.ADVISORY),
    ConstitutionalRule("R-008-3", "A008", "مبادئ Kill Switch · 4",
                       Severity.HIGH, "إعادة تشغيل بلا موافقة صريحة", _r008_3,
                       CrownEffect.ADVISORY),
    ConstitutionalRule("R-009-1", "A009", "القاعدة الذهبية",
                       Severity.HIGH, "إنشاء ملف أو مجلد بلا هوية", _r009_1,
                       CrownEffect.ADVISORY),
    ConstitutionalRule("R-010-1", "A010", "الاختصاص الملكي الحصري · 2",
                       Severity.FUNDAMENTAL, "غير الملك يمارس اختصاصًا ملكيًا حصريًا", _r010_1,
                       CrownEffect.ADVISORY),
    ConstitutionalRule("R-010-2", "A010", "حصانة السلطة الملكية · 3 · 1",
                       Severity.FUNDAMENTAL, "المساس بسلطة الملك تعديلًا أو تقييدًا أو تجاوزًا", _r010_2,
                       CrownEffect.ADVISORY),
    ConstitutionalRule("R-010-3", "A010", "منع انتحال الصفة الملكية · 3 · 2",
                       Severity.FUNDAMENTAL, "فعل ملكي بلا مرسوم موقَّع Ed25519", _r010_3,
                       CrownEffect.AUTHENTICITY),
    ConstitutionalRule("R-010-4", "A010", "الفدرالية لا تُتجاوَز · 4",
                       Severity.FUNDAMENTAL, "مسار تنفيذ يتجاوز البوابة السيادية", _r010_4,
                       CrownEffect.ADVISORY),
    ConstitutionalRule("R-010-5", "A010", "التاج غير مُنصَّب · 6 · 2",
                       Severity.CRITICAL, "اختصاص ملكي حصري والتاج غير مُنصَّب", _r010_5,
                       CrownEffect.AUTHENTICITY),
    ConstitutionalRule("R-010-6", "A010", "التعديل الدستوري حصر للملك · 2 · 1",
                       Severity.FUNDAMENTAL, "تعديل دستوري بلا مرسوم ملكي", _r010_6,
                       CrownEffect.ADVISORY),
    ConstitutionalRule("R-010-7", "A010", "التاج فوق رقابة الفروع · 5",
                       Severity.CRITICAL, "فرع ينقض مرسومًا ملكيًا أو يراجعه", _r010_7,
                       CrownEffect.ADVISORY),
    ConstitutionalRule("R-010-8", "A010", "الحق المالي الملكي · 8 · 1",
                       Severity.FUNDAMENTAL, "المساس بنصف الخزينة المملوك للملك", _r010_8,
                       CrownEffect.ADVISORY),
    ConstitutionalRule("R-010-9", "A010", "حق الاطلاع والاستفتاء · 9",
                       Severity.CRITICAL, "منع الملك من اطلاع أو استفتاء", _r010_9,
                       CrownEffect.ADVISORY),
    ConstitutionalRule("R-010-10", "A010", "حق الإبطال بلا تبرير · 11 · 2",
                       Severity.FUNDAMENTAL, "إلزام الملك بتبرير الإبطال أو بموافقة المجلس", _r010_10,
                       CrownEffect.ADVISORY),
    ConstitutionalRule("R-011-1", "A011", "حسم التعارض بمرسوم ملكي · 3 · 5",
                       Severity.FUNDAMENTAL, "تفسير دستوري أو حسم تعارض بلا مرسوم ملكي", _r011_1,
                       CrownEffect.ADVISORY),
    ConstitutionalRule("R-011-2", "A011", "تسلسل التفسير الإلزامي · 2 · 2",
                       Severity.FUNDAMENTAL, "تفسير صلاحية مؤسسية سلطةً تعلو الملك", _r011_2,
                       CrownEffect.ADVISORY),
)


def rules_by_article() -> dict[str, tuple[ConstitutionalRule, ...]]:
    out: dict[str, list[ConstitutionalRule]] = {}
    for r in RULES:
        out.setdefault(r.article_id, []).append(r)
    return {k: tuple(v) for k, v in sorted(out.items())}
