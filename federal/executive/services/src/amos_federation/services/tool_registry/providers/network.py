"""الهدف: سياسة شبكة صريحة للصندوق الرملي — لا وصول ضمني.

النطاق: services/tool_registry/providers
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17

`DENY` هو الافتراضي. أداة تحتاج الشبكة تُعلن ذلك في مواصفتها، وتُسمّي مضيفيها
إن كانت `ALLOWLIST`. و`ALLOW_ALL` موجودة لأن إخفاءها لا يمنعها: من أرادها
سيمرّر `ALLOWLIST` بمضيف `*` أو يعطّل الفحص. وجودها مُسمّاةً يعني أنها تظهر في
كل نتيجة تنفيذ وفي كل حدث، فتصبح قابلة للمراجعة.

قيد صريح على المدى: هذه الوحدة تحكم ما **يُطلب ويُعلَن ويُفحَص**. أما الحبس
الشبكي الفعلي فمن يملكه هو المزوِّد أو المضيف.

تحديث R6 — المزوِّد المحلّي: كان `DECLARED_ONLY` بلا حبس فعلي. وقد ثبت بالتنفيذ
أن `unshare --map-root-user --net` متاح في هذه البيئة ويقطع الشبكة فعلًا (فحصٌ
حقيقي: اتّصال TCP خارجي ينجح خارج النطاق ويفشل بـ`ENETUNREACH` داخله). فصار
المزوِّد المحلّي يُشغِّل العمليّة داخل namespace شبكي معزول عند سياسة `DENY`.

ولأن التوفُّر يتغيّر بالبيئة، الفرض **يُقاس ولا يُفترَض**: `local_enforcement()`
تفحص القدرة فعليًّا، فترجع `NAMESPACE_ENFORCED` إن نجح الفحص و`DECLARED_ONLY` إن
لم ينجح. لا تُرفَع القيمة بلا دليل، ولا تُخفَض حين يوجد الدليل.

حدٌّ باقٍ يُقال: `ALLOWLIST` عند المزوِّد المحلّي تبقى `DECLARED_ONLY` — عزل
الـnamespace يمنع الشبكة كلَّها أو لا يمنعها، ولا يُرشِّح مضيفًا بعينه. تصفية
المضيفين تحتاج proxy أو قواعد جدار داخل النطاق، ولم تُبنَ.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass

_logger = logging.getLogger(__name__)

#: القيم المسموحة لـ`SandboxSpec.network_policy`.
NETWORK_POLICIES: tuple[str, ...] = ("DENY", "ALLOWLIST", "ALLOW_ALL")

#: أنماط الفرض المعروفة — تُفحَص في الاختبارات ضدّ قيمة مُخترعة.
ENFORCEMENT_MODES: tuple[str, ...] = (
    "DECLARED_ONLY",
    "NAMESPACE_ENFORCED",
    "PROVIDER_ENFORCED",
    "NOT_APPLICABLE",
    "UNKNOWN",
)

#: أمر عزل الشبكة للمزوِّد المحلّي — يُسبَق به argv عند سياسة DENY.
NETWORK_ISOLATION_ARGV: tuple[str, ...] = ("unshare", "--map-root-user", "--net")

#: كيف تُفرَض السياسة عند كل مزوِّد — لا يُزعم فرضٌ غير موجود.
#: قيمة `local` تُحسَب عند الطلب في `enforcement_for` لأنها تعتمد على البيئة.
ENFORCEMENT_BY_PROVIDER: dict[str, str] = {
    "local": "DECLARED_ONLY",
    "modal": "PROVIDER_ENFORCED",
    "e2b": "PROVIDER_ENFORCED",
    "simulation": "NOT_APPLICABLE",
}


class NetworkPolicyViolation(RuntimeError):  # noqa: N818 — خرق سياسة، لا عطل
    """طلب شبكي يخالف سياسة الصندوق المُعلَنة."""


@dataclass(frozen=True)
class NetworkDecision:
    """قرار على مضيف بعينه، بسببه — صالح للسجل."""

    allowed: bool
    policy: str
    enforcement: str
    host: str | None = None
    reason: str | None = None


def normalize_policy(policy: str) -> str:
    """طبّع اسم السياسة وارفض المجهول — لا افتراض صامت إلى `DENY` ولا إلى السماح."""
    value = (policy or "").strip().upper()
    if value not in NETWORK_POLICIES:
        raise NetworkPolicyViolation(
            f"سياسة شبكة غير معروفة: '{policy}' — المسموح: {', '.join(NETWORK_POLICIES)}"
        )
    return value


#: ذاكرة نتيجة فحص القدرة — الفحص يُشغِّل عمليّة، فلا يُعاد في كل نداء.
_ISOLATION_PROBE: bool | None = None


def isolation_available(*, force_probe: bool = False) -> bool:
    """هل يمكن عزل الشبكة فعلًا في هذه البيئة؟ — يُقاس بالتشغيل لا يُفترَض.

    الفحص يُشغِّل `unshare --map-root-user --net true` مرّة ويحفظ النتيجة. وفشله
    لأي سبب — أمرٌ مفقود، صلاحية مرفوضة، نواة لا تدعم — يعني `False`، أي
    `DECLARED_ONLY` مُعلَنة، لا فرضًا مزعومًا.
    """
    global _ISOLATION_PROBE  # noqa: PLW0603 — ذاكرة فحص لمرّة واحدة
    if _ISOLATION_PROBE is not None and not force_probe:
        return _ISOLATION_PROBE
    if shutil.which(NETWORK_ISOLATION_ARGV[0]) is None:
        _ISOLATION_PROBE = False
        return False
    try:
        probe = subprocess.run(  # noqa: S603
            [*NETWORK_ISOLATION_ARGV, "true"],
            capture_output=True,
            timeout=10,
            check=False,
        )
        _ISOLATION_PROBE = probe.returncode == 0
    except (OSError, subprocess.SubprocessError) as exc:
        _logger.warning("تعذّر سبرُ عزل الشبكة — يُعَدُّ غيرَ مُتاح. %s", exc)
        _ISOLATION_PROBE = False
    return _ISOLATION_PROBE


def local_enforcement(policy: str = "DENY") -> str:
    """نمط الفرض الفعلي للمزوِّد المحلّي عند سياسة بعينها.

    `DENY` وحدها قابلة للفرض بالـnamespace. و`ALLOWLIST` تبقى مُعلَنة فقط: العزل
    يقطع الشبكة كلَّها ولا يُرشِّح مضيفًا، فلا يُزعم أنه ترشيح.
    """
    normalized = (policy or "").strip().upper()
    if normalized == "DENY" and isolation_available():
        return "NAMESPACE_ENFORCED"
    return "DECLARED_ONLY"


def enforcement_for(provider: str, policy: str | None = None) -> str:
    """كيف تُفرَض السياسة عند هذا المزوِّد — المجهول يُعلَن مجهولًا."""
    if provider == "local":
        return local_enforcement(policy or "DENY")
    return ENFORCEMENT_BY_PROVIDER.get(provider, "UNKNOWN")


def evaluate(
    policy: str,
    *,
    provider: str,
    host: str | None = None,
    allowed_hosts: tuple[str, ...] = (),
) -> NetworkDecision:
    """قرِّر السماح بمضيف وفق السياسة، وسمِّ السبب دائمًا."""
    normalized = normalize_policy(policy)
    enforcement = enforcement_for(provider, normalized)

    if normalized == "DENY":
        return NetworkDecision(
            allowed=False,
            policy=normalized,
            enforcement=enforcement,
            host=host,
            reason="سياسة الصندوق DENY — لا وصول شبكي",
        )
    if normalized == "ALLOW_ALL":
        return NetworkDecision(
            allowed=True,
            policy=normalized,
            enforcement=enforcement,
            host=host,
            reason="سياسة الصندوق ALLOW_ALL — مُعلَنة صراحةً",
        )

    if not allowed_hosts:
        return NetworkDecision(
            allowed=False,
            policy=normalized,
            enforcement=enforcement,
            host=host,
            reason="ALLOWLIST بلا مضيف واحد — تُعامَل معاملة DENY",
        )
    if host is None:
        return NetworkDecision(
            allowed=False,
            policy=normalized,
            enforcement=enforcement,
            host=None,
            reason="ALLOWLIST تحتاج مضيفًا مُسمّى للفحص",
        )
    if host in allowed_hosts:
        return NetworkDecision(
            allowed=True,
            policy=normalized,
            enforcement=enforcement,
            host=host,
            reason="المضيف في قائمة السماح",
        )
    return NetworkDecision(
        allowed=False,
        policy=normalized,
        enforcement=enforcement,
        host=host,
        reason="المضيف خارج قائمة السماح",
    )
