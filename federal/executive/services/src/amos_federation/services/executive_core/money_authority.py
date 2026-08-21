"""
AMOS-Federation Executive Core — Money Authority
الهدف: لا يتحرّكُ مالٌ عامٌّ حتّى يُسألَ المُحرِّكُ الدستوريُّ ويأذنَ بفاعلِ التفويضِ المُعلَن
النطاق: executive_core — نقطةُ فرضٍ واحدةٌ يستدعيها مسارُ تخويلِ المال
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-21 (Q-31)
تعتمد على: services/executive_core/sovereignty_bridge.py · common/money_delegation.py

## لماذا هنا لا في الخزانة

حُسِمَ **Q-31** بالخيارِ الثاني: «وصلُ المُحرِّكِ عندَ `_authorize_money`». وموضعُ
الوحدةِ اختيارٌ بُنيويٌّ لا ذوقيّ: خزانةُ الدولةِ تستوردُ `executive_core` أصلًا،
و`executive_core` لا تستوردُ الخزانةَ ولا الاقتصادَ. فلو وُضِعَ الوصلُ في الخزانةِ
لصارَ لكلِّ خدمةٍ ماليّةٍ نسختُها من طريقةِ سؤالِ المُحرِّك، ولو وُضِعَ في `common`
لاستوردتْ مفردةٌ مشتركةٌ جسرًا سياديًّا. فهو هنا: نقطةُ فرضٍ **واحدة**.

## لماذا تُحفَظُ البوّابةُ ولا يُحفَظُ الفاعل

هذا هو الحدُّ الفاصلُ بينَ هذه الوحدةِ وسابقةِ **2A**، وهو مقصودٌ حرفيًّا:

- **البوّابةُ** آلةٌ **بلا فاعل**: قواعدُ وسجلٌّ وتحقيقُ سلسلة. بناؤها مُكلِفٌ
  (قِيسَ: ‏50 مللي)، ولا تحملُ هويّةَ فرعٍ، فحفظُها لا يُخوِّلُ أحدًا.
- **المُصرِّحُ** هو الذي يحملُ الفاعلَ (`actor=TREASURY`)، فيُبنى **عندَ كلِّ
  نداءٍ** من `delegation.actor` المُستخرَجِ من جدولِ التفويضِ المُعلَن. وبناؤه
  ببوّابةٍ محفوظةٍ قِيسَ: ‏0.007 مللي — فلا عُذرَ أداءٍ يُبرِّرُ حفظَ فاعل.

وسابقةُ 2A فعلتِ العكسَ: بنَتْ مُصرِّحًا موسومًا بالخزانةِ **مرّةً واحدةً لكائنِ
التشغيلِ كلِّه**، فصارَ كلُّ ما يمرُّ منه خزانةً بحكمِ البناء. فحفظُ مُصرِّحٍ موسومٍ
هنا يُعيدُ إنتاجَ ما مَنَعَه Q-19 نصًّا، ولذلك يمنعُه هذا الملفُّ بُنيةً لا نصيحةً.

## المُحرِّكُ يكتبُ — قِيسَ لا افتُرِض

`review_only` اسمُها «مراجعةٌ فقط» بمعنى **أنّها لا تُنفِّذُ أثرًا ولا تصرفُ
تصريحًا**، لا بمعنى أنّها لا تكتبُ شيئًا. قِياسُ التنميطِ أثبتَ أنَّ
`engine.evaluate` تُلحِقُ قيدًا في السجلِّ الدستوريِّ
(`core/constitution/ledger/constitutional_ledger.jsonl`) وتُعيدُ تحقيقَ السلسلةِ
كلِّها قبلَ الإلحاق. فلهذا الوصلِ نتيجتانِ مُعلَنتان:

1. **مكسبٌ**: صارَ لكلِّ تحريكِ مالٍ يمرُّ من هنا **أثرٌ مُسلسَلٌ مانعُ التلاعب**.
   وحدُّ هذا الأثرِ مقيسٌ لا مُدَّعى: القيدُ يختمُ **الفعلَ الدستوريَّ والفاعلَ
   والمورِدَ والحكمَ وعددَ القواعدِ المُقيَّمةِ وبصمةَ الطلب**، و**لا يختمُ** اسمَ
   العمليّةِ النطاقيَّ ولا المدخل: بِنيةُ القيدِ في النواةِ تُسجِّلُ حكمَها لا
   بياناتِ مَن نادى. فمن أرادَ ختمَ العمليّةِ نفسِها فذاكَ تغييرٌ في النواةِ
   يُقرَّرُ سياديًّا، لا يُدَّعى هنا.
2. **كُلفةٌ**: زمنُ المراجعةِ ينمو خطّيًّا مع طولِ السجلِّ (قِيسَ: ‏153 مللي عندَ
   ‏9633 قيدًا)، فمجموعُ الكلفةِ تربيعيٌّ مع عددِ العمليّات. هذه صفةُ تصميمِ
   السجلِّ في النواةِ، لا صفةُ هذه الوحدةِ، ولا تُعالَجُ هنا بتلطيفٍ ولا بذاكرةٍ
   مؤقّتةٍ للأحكام: فحفظُ حكمٍ سابقٍ يعني أنَّ المُحرِّكَ لم يُسأَلْ، وذاكَ نقضُ
   Q-31 لا تنفيذُه. وقد سُجِّلَت الكُلفةُ حدًّا من حدودِ الصدقِ لا عيبًا مخفيًّا.

## الحدُّ المُعلَنُ لهذا الوصل (لا يُدَّعى ما ليس مفروضًا)

هذه الوحدةُ تُفرَضُ حيثُ تُنادى، وهي تُنادى من `_authorize_money` وحدَها. وقياسُ
Q-19 أثبتَ أنَّ **أربعةً** من عشرةِ مواضعِ تحريكِ المالِ تمرُّ بـ`_authorize_money`،
والستّةَ الباقيةَ لا تمرُّ به. فالمفروضُ دستوريًّا بعدَ هذا العملِ أربعةٌ لا عشرة،
وتوسيعُ النطاقِ إلى الستّةِ مسألةٌ سياديّةٌ مُقيَّدةٌ بـ**Q-32** لا تُحسَمُ اجتهادًا.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from amos_federation.common.money_delegation import resolve_money_delegation

from .sovereignty_bridge import AuthorityEvidence, ConstitutionalAuthorizer

if TYPE_CHECKING:  # pragma: no cover — للتوثيقِ لا للتشغيل
    from amos_federation.common.money_delegation import MoneyDelegation

ALLOWED_DECISION = "ALLOW"
"""الحكمُ الوحيدُ الذي يُمرِّرُ مالًا. وكلُّ ما سواه رفضٌ — إغلاقٌ لا تفسير."""


class ConstitutionalMoneyDenialError(PermissionError):  # noqa: N818 — رفضُ سلطةٍ لا عطل
    """رفضَ المُحرِّكُ الدستوريُّ تحريكَ هذا المال.

    يُورَثُ من `PermissionError` لا من `TreasuryError`، لأنَّ حالَه حالُ من لا
    صلاحيةَ له (كما `RegistryAuthorizationError`) لا حالَ خلَلٍ في الخزانة: فما
    منعَه الدستورُ ليس عطلًا يُعاد، بل حدًّا يُحترَم.
    """

    def __init__(self, delegation: MoneyDelegation, evidence: AuthorityEvidence) -> None:
        self.delegation = delegation
        self.evidence = evidence
        advisory = "؛ ".join(evidence.advisory_violations) or "لا مخالفةَ استشاريّةً مُبلَّغة"
        super().__init__(
            f"منعَ المُحرِّكُ الدستوريُّ العمليّةَ «{delegation.operation}»: "
            f"الفعلُ «{delegation.constitutional_action}» بفاعلِ «{delegation.actor}» "
            f"حُكِمَ «{evidence.decision}» في طبقةِ «{evidence.authority_layer}» "
            f"({evidence.rules_evaluated} قاعدةً مُقيَّمة · بصمةُ الطلبِ "
            f"{evidence.request_fingerprint}). المخالفاتُ الاستشاريّة: {advisory}."
        )


_SHARED_GATEWAY: Any | None = None


def _authorizer_for(actor: str) -> ConstitutionalAuthorizer:
    """مُصرِّحٌ جديدٌ بفاعلٍ مُعلَنٍ، على بوّابةٍ واحدةٍ محفوظةٍ بلا فاعل.

    أوّلُ نداءٍ يبني البوّابةَ ويحفظُها من المُصرِّحِ نفسِه (فلا جسرَ ثانيًا ولا
    استعمالَ لواجهةٍ خاصّة)، وما بعدَه يبني مُصرِّحًا جديدًا فوقَها. والمُصرِّحُ
    **لا يُحفَظُ أبدًا**: حفظُه هو عينُ سابقةِ 2A.
    """
    global _SHARED_GATEWAY
    if _SHARED_GATEWAY is None:
        first = ConstitutionalAuthorizer(actor=actor)
        _SHARED_GATEWAY = first.gateway
        return first
    return ConstitutionalAuthorizer(actor=actor, gateway=_SHARED_GATEWAY)


def require_constitutional_money_authority(
    operation: str,
    *,
    entrypoint: str,
    target: str,
    metadata: dict[str, Any] | None = None,
) -> AuthorityEvidence:
    """اسألِ المُحرِّكَ الدستوريَّ قبلَ تحريكِ المال، وأغلِقْ على غيرِ الإذن.

    الترتيبُ مقصود: يُحضَرُ التفويضُ المُعلَنُ أوّلًا، فالفعلُ الدستوريُّ والفاعلُ
    يُؤخَذانِ من الجدولِ المُعلَنِ لا من نصٍّ يُمرِّرُه النداء. فلا يستطيعُ منادٍ أن
    يُسمّيَ فعلًا دستوريًّا من عندِه.

    Args:
        operation: اسمُ العمليّةِ الماليّةِ كما في جدولِ التفويضِ المُعلَن.
        entrypoint: مدخلُ الشِّفرةِ المُعلَنُ لهذه العمليّة.
        target: المورِدُ المقصودُ — يُسجَّلُ في السجلِّ الدستوريِّ مع الحكم.
        metadata: بيانٌ إضافيٌّ يُعرَضُ على المُحرِّكِ في الطلب. **لا يُختَمُ في
            السجلِّ** (قِيسَ)، ولا يُغيِّرُ الفعلَ ولا الفاعل.

    Returns:
        `AuthorityEvidence` بحكمِ `ALLOW` — وأثرُها مُقيَّدٌ في السجلِّ الدستوريّ.

    Raises:
        UndeclaredMoneyDelegationError: عمليّةٌ أو مدخلٌ بلا تفويضٍ مُعلَن (Q-19).
        ConstitutionalMoneyDenialError: المُحرِّكُ حكمَ بغيرِ `ALLOW`.
        SovereigntyUnavailableError: تعذّرَ حضورُ المُحرِّكِ — إغلاقٌ لا تجاوُز.
    """
    delegation = resolve_money_delegation(operation, entrypoint=entrypoint)
    record: dict[str, Any] = {
        "money_operation": delegation.operation,
        "entrypoint": delegation.entrypoint,
        "delegation_basis": delegation.basis,
    }
    if metadata:
        record.update(metadata)

    evidence = _authorizer_for(delegation.actor).review_only(
        delegation.constitutional_action, target, record
    )
    if evidence.decision != ALLOWED_DECISION:
        raise ConstitutionalMoneyDenialError(delegation, evidence)
    return evidence


__all__ = [
    "ALLOWED_DECISION",
    "ConstitutionalMoneyDenialError",
    "require_constitutional_money_authority",
]
