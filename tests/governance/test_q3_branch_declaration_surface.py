"""الهدف: تقييدُ كلِّ رقمٍ في موجزِ Q-3 إلى موضعِه في الشِّفرةِ — قياسٌ لا نقل.

النطاق: سطحُ إعلانِ الفرعِ (Branch) وحدَه: سياقُ التخويلِ · معجمُ الفروع ·
معامَلُ الفاعلِ في الجسر · مواضعُ بناءِ المُصرِّحِ الإنتاجيّةُ · دَينُ W1 وتواقيعُه ·
أحكامُ البوّابةِ على أفعالِ ذلك الدَّين.
المالك: governance/
تاريخ الإنشاء: 2026-08-22
تاريخ آخر تعديل: 2026-08-22

## لماذا هذا الحرسُ موجود (W-023 · T2 · الخطوة 11)

يُعرَضُ على صاحبِ القرارِ في `docs/audit/SOVEREIGN_DECISION_REGISTER.md` موجزُ
Q-3 (مصدرُ اشتقاقِ الفرع) بأرقامٍ مقيسة. ورقمٌ يُعرَضُ في موجزٍ سياديٍّ ولا
يحرسُه فحصٌ **يموتُ صامتًا**: تتغيَّرُ الشِّفرةُ ويبقى الموجزُ يقولُ ما لم يعُدْ
صحيحًا، فيُبنى قرارٌ لا رجعةَ فيه على قياسٍ منتهي الصلاحية. فكلُّ رقمٍ في ذلك
الموجزِ له فحصٌ هنا، ومن غيَّرَ السطحَ أسقطَ الفحصَ، فيُعادُ القياسُ **قبلَ**
العرضِ لا بعدَه.

## حدُّ صدقِ هذا الحرس

يُثبِتُ **من أينَ يأتي الفرعُ اليومَ وما أثرُ ذلك على أحكامِ البوّابة**، ولا
يُثبِتُ صوابَ أيِّ خيارٍ من خياراتِ Q-3 — الاختيارُ قرارٌ بشريٌّ لا يقيسُه
اختبار. والقياسُ بنيويٌّ (شجرةُ تحليلِ المصدر) وحُكميٌّ (المُحرِّكُ نفسُه
يُستدعى)، لا قراءةَ وثائقَ ولا نقلَ أرقامٍ من تحليلٍ سابق.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICES_SRC = REPO_ROOT / "federal" / "executive" / "services" / "src"
PRINCIPAL_PATH = SERVICES_SRC / "amos_federation" / "common" / "principal.py"
BRIDGE_PATH = (
    SERVICES_SRC
    / "amos_federation"
    / "services"
    / "executive_core"
    / "sovereignty_bridge.py"
)
INVENTORY_TOOL = REPO_ROOT / "tools" / "audit" / "sovereign_write_inventory.py"

#: مسارُ الموجةِ الأولى كما تُعرِّفُه بوّابةُ القرار — لا كما تُعاد كتابتُه هنا.
W1_PATHS = ("federal_judiciary", "governance/federation.py", "national_registry")
W1_EXTRA = {("government_services/service.py", "process_case")}

#: معاييرُ تصنيفِ التوقيعِ — مُعلَنةٌ لأنَّ الرقمَ بلا معيارٍ دعوى.
CONTEXT_ARG_NAMES = {"context", "ctx", "auth_context"}


def _load_inventory_tool() -> ModuleType:
    """تحميلُ أداةِ الجردِ بمسارِها، مع تسجيلِها في `sys.modules`.

    التسجيلُ ضروريٌّ لا تجميليّ: الأداةُ تُعرِّفُ `dataclass` بتعليقاتٍ مؤجَّلة،
    وبناؤها يبحثُ عن وحدتِها بالاسم.
    """
    spec = importlib.util.spec_from_file_location("_q3_inventory", INVENTORY_TOOL)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _is_actor_arg(name: str) -> bool:
    """هل يحملُ الوسيطُ فاعلًا باسمٍ خاصٍّ؟ (`actor*` · `*_principal` · `principal`)."""
    return "actor" in name or name.endswith("_principal") or name == "principal"


def _function_node(
    tree: ast.Module, name: str
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    leaf = name.split(".")[-1]
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == leaf
        ):
            return node
    return None


def _w1_debt() -> list[Any]:
    """مواضعُ دَينِ الموجةِ الأولى — تُقاسُ بالأداةِ الحاكمةِ لا بقائمةٍ محفوظة."""
    inventory = _load_inventory_tool()
    sites = inventory.collect(REPO_ROOT)
    w1 = [
        site
        for site in sites
        if any(part in site.path for part in W1_PATHS)
        or any(
            part in site.path and site.function.endswith(fn) for part, fn in W1_EXTRA
        )
    ]
    return [s for s in w1 if s.public and not s.guarded and not s.closed_legacy]


def _signature_buckets() -> dict[str, list[str]]:
    buckets: dict[str, list[str]] = {
        "context_only": [],
        "actor_named": [],
        "neither": [],
        "both": [],
    }
    for site in _w1_debt():
        source = (REPO_ROOT / site.path).read_text(encoding="utf-8")
        node = _function_node(ast.parse(source), site.function)
        assert node is not None, f"لم يُعثر على تعريفِ {site.function} في {site.path}"
        args = [a.arg for a in node.args.args + node.args.kwonlyargs]
        has_context = any(a in CONTEXT_ARG_NAMES for a in args)
        has_actor = any(_is_actor_arg(a) for a in args)
        key = (
            "both"
            if has_context and has_actor
            else "context_only"
            if has_context
            else "actor_named"
            if has_actor
            else "neither"
        )
        buckets[key].append(f"{site.path}::{site.function}")
    return buckets


def _authorizer_construction_sites() -> dict[str, list[str]]:
    """مواضعُ بناءِ `ConstitutionalAuthorizer` في شِفرةِ الإنتاجِ — نداءاتٌ لا نصوصٌ.

    القياسُ من شجرةِ التحليلِ لا بالبحثِ النصّيّ، لأنَّ ذِكرَ الاسمِ في وثيقةٍ
    داخليّةٍ ليس بناءً، ولو عُدَّ لصارَ الرقمُ يكبرُ بتحريرِ تعليق.
    """
    inventory = _load_inventory_tool()
    declared: list[str] = []
    defaulted: list[str] = []
    for path in inventory.iter_source_files(SERVICES_SRC):
        source = path.read_text(encoding="utf-8")
        if "ConstitutionalAuthorizer(" not in source:
            continue
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = (
                func.attr
                if isinstance(func, ast.Attribute)
                else getattr(func, "id", "")
            )
            if name != "ConstitutionalAuthorizer":
                continue
            where = f"{path.relative_to(REPO_ROOT)}:{node.lineno}"
            (
                declared
                if any(kw.arg == "actor" for kw in node.keywords)
                else defaulted
            ).append(where)
    return {"declared": sorted(declared), "defaulted": sorted(defaulted)}


def _engine_verdicts(
    actions: list[str], actors: list[str]
) -> dict[str, dict[str, Any]]:
    for candidate in (REPO_ROOT, SERVICES_SRC):
        if str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
    from core.constitutional_engine.engine import ConstitutionalEngine
    from core.constitutional_engine.model import ActionRequest, Branch

    engine = ConstitutionalEngine()
    result: dict[str, dict[str, Any]] = {}
    for action in actions:
        row: dict[str, Any] = {}
        for actor in actors:
            verdict = engine.evaluate(
                ActionRequest(actor=Branch[actor], action=action, target="probe/q3")
            )
            decision = getattr(verdict, "decision", verdict)
            rules = tuple(
                getattr(v, "rule_id", str(v))
                for v in (getattr(verdict, "violations", None) or ())
            )
            row[actor] = (getattr(decision, "value", str(decision)), rules)
        result[action] = row
    return result


# ── 1. سياقُ التخويلِ لا يحملُ فرعًا ─────────────────────────────────────────
def test_authorization_context_declares_no_branch() -> None:
    """الدعوى المحروسة: `AuthorizationContext` بأحدَ عشرَ حقلًا **وبلا حقلِ فرع**."""
    tree = ast.parse(PRINCIPAL_PATH.read_text(encoding="utf-8"))
    node = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.ClassDef) and n.name == "AuthorizationContext"
    )
    fields = [
        item.target.id
        for item in node.body
        if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)
    ]
    assert fields == [
        "principal_id",
        "verification",
        "principal_kind",
        "role",
        "permissions",
        "capabilities",
        "session_id",
        "tenant_id",
        "expires_at",
        "correlation_id",
        "reason",
    ]
    assert not any(
        "branch" in name for name in fields
    ), "صارَ للسياقِ حقلُ فرعٍ — وهذا جوابٌ على Q-3 لا قياسٌ له: يُحدَّثُ الموجزُ ويُحسَمُ السجلّ."


# ── 2. الفروعُ الأربعةُ معجمٌ مُعلَنٌ في المُحرِّك ─────────────────────────────
def test_branch_lexicon_is_closed_and_declared() -> None:
    """الفرعُ نوعٌ مُعلَنٌ في النواةِ — فمن أعلنَ فاعلًا يُعلِنُه من هذا المعجمِ لا نصًّا حرًّا."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from core.constitutional_engine.model import Branch

    names = {member.name for member in Branch}
    assert {"EXECUTIVE", "LEGISLATIVE", "JUDICIAL", "TREASURY"} <= names
    assert names == {
        "EXECUTIVE",
        "LEGISLATIVE",
        "JUDICIAL",
        "TREASURY",
        "ROYAL",
        "HUMAN",
        "STATE",
        "INSTITUTION",
        "AGENT",
        "SYSTEM",
    }


# ── 3. الفاعلُ مُعلَنٌ افتراضُه تنفيذيٌّ (سابقةُ 2A) ───────────────────────────
def test_bridge_actor_is_declared_parameter_defaulting_to_executive() -> None:
    """الدعوى المحروسة: `actor` معامَلٌ مُسمّىً افتراضُه `DEFAULT_ACTOR = "EXECUTIVE"`."""
    tree = ast.parse(BRIDGE_PATH.read_text(encoding="utf-8"))
    klass = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.ClassDef) and n.name == "ConstitutionalAuthorizer"
    )
    default_actor = next(
        item.value.value
        for item in klass.body
        if isinstance(item, ast.Assign)
        and isinstance(item.targets[0], ast.Name)
        and item.targets[0].id == "DEFAULT_ACTOR"
        and isinstance(item.value, ast.Constant)
    )
    assert default_actor == "EXECUTIVE"

    init = next(
        n for n in klass.body if isinstance(n, ast.FunctionDef) and n.name == "__init__"
    )
    kwonly = [a.arg for a in init.args.kwonlyargs]
    assert "actor" in kwonly, "الفاعلُ لم يبقَ معامَلًا مُسمّىً — تغيَّرَ عقدُ 2A"
    default = init.args.kw_defaults[kwonly.index("actor")]
    assert isinstance(default, ast.Name) and default.id == "DEFAULT_ACTOR"


# ── 4. مواضعُ بناءِ المُصرِّحِ: أربعةٌ تُعلِنُ فاعلَها وأربعةٌ تتَّكِلُ على الافتراض ──
def test_production_authorizer_sites_split_four_declared_four_defaulted() -> None:
    sites = _authorizer_construction_sites()
    assert len(sites["declared"]) == 4, sites["declared"]
    assert len(sites["defaulted"]) == 4, sites["defaulted"]
    assert sorted(Path(p.split(":")[0]).name for p in sites["declared"]) == [
        "factories.py",
        "factories.py",
        "money_authority.py",
        "money_authority.py",
    ], sites["declared"]
    assert sorted(Path(p.split(":")[0]).name for p in sites["defaulted"]) == [
        "engine.py",
        "sovereignty_bridge.py",
        "state_runtime.py",
        "subsystem_boundary.py",
    ]


# ── 5. دَينُ W1 وتواقيعُه ─────────────────────────────────────────────────────
def test_w1_debt_is_fifty_two_sites() -> None:
    assert len(_w1_debt()) == 52


def test_w1_signature_buckets_are_twenty_eight_four_twenty() -> None:
    """الدعوى المحروسة: 28 سياقًا وحدَه · 4 فاعلًا مُسمّىً · 20 بلا فاعلٍ بأيِّ صورةٍ · 0 كِلاهما."""
    buckets = _signature_buckets()
    counts = {key: len(value) for key, value in buckets.items()}
    assert counts == {
        "context_only": 28,
        "actor_named": 4,
        "neither": 20,
        "both": 0,
    }, counts
    assert sum(counts.values()) == 52


def test_no_w1_debt_site_declares_a_branch_today() -> None:
    """لا موضعَ واحدًا من الـ52 يُمرِّرُ فرعًا — فالفرعُ اليومَ لا يُعلَنُ في التوقيعِ أصلًا."""
    for site in _w1_debt():
        source = (REPO_ROOT / site.path).read_text(encoding="utf-8")
        node = _function_node(ast.parse(source), site.function)
        assert node is not None
        args = [a.arg for a in node.args.args + node.args.kwonlyargs]
        assert not any(
            a in {"branch", "actor_branch"} for a in args
        ), f"{site.path}::{site.function}"


# ── 6. أثرُ الإعلانِ على الحكم — من المُحرِّكِ نفسِه ──────────────────────────
def test_only_one_debt_action_is_branch_sensitive_today() -> None:
    """الدعوى المحروسة: من 44 اسمَ فعلٍ في دَينِ W1 — 41 خارجَ المعجمِ · 1 حسّاسٌ للفرعِ · 2 ممنوعانِ لكلِّ فاعل."""
    actions = sorted({site.function.split(".")[-1] for site in _w1_debt()})
    assert len(actions) == 44, actions
    actors = ["EXECUTIVE", "JUDICIAL", "LEGISLATIVE", "TREASURY", "ROYAL"]
    verdicts = _engine_verdicts(actions, actors)

    outside, sensitive, denied = [], [], []
    for action, row in verdicts.items():
        allows = [actor for actor, (decision, _) in row.items() if decision == "ALLOW"]
        if len(allows) == len(actors):
            outside.append(action)
        elif not allows:
            denied.append(action)
        else:
            sensitive.append(action)

    assert len(outside) == 41, sorted(outside)
    assert sensitive == ["issue_ruling"], sensitive
    assert sorted(denied) == ["grant_authority", "revoke_authority"], sorted(denied)


def test_issue_ruling_is_denied_for_the_default_actor_and_allowed_for_judicial() -> (
    None
):
    """الفخُّ المقيس: لو هاجرَ `issue_ruling` بالفاعلِ الافتراضيِّ لسقطَ بـR-003-1."""
    verdicts = _engine_verdicts(["issue_ruling"], ["EXECUTIVE", "JUDICIAL", "ROYAL"])[
        "issue_ruling"
    ]
    assert verdicts["EXECUTIVE"][0] == "DENY"
    assert "R-003-1" in verdicts["EXECUTIVE"][1]
    assert verdicts["JUDICIAL"][0] == "ALLOW"
    assert verdicts["ROYAL"][0] == "ALLOW"


def test_authority_grants_are_denied_for_every_branch() -> None:
    """`grant_authority` و`revoke_authority` يُرفضانِ لكلِّ فاعلٍ — حتّى `ROYAL` بلا مرسوم."""
    actors = ["EXECUTIVE", "JUDICIAL", "LEGISLATIVE", "TREASURY", "ROYAL"]
    verdicts = _engine_verdicts(["grant_authority", "revoke_authority"], actors)
    for action, row in verdicts.items():
        for actor, (decision, rules) in row.items():
            assert decision == "DENY", f"{action} · {actor}"
            assert any(
                rule.startswith("R-010") for rule in rules
            ), f"{action} · {actor} · {rules}"
