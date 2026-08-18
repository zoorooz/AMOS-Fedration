"""
الإغلاقُ عند الفشل — Fail-Closed (المرحلة 1J)
الهدف: منعُ الدولةِ من ادِّعاءِ تنفيذٍ ناجحٍ حين تكون المعاملةُ السياديةُ غيرَ مكتملة. لا نجاحَ صامتًا، ولا تراجعَ صامتًا، ولا حالةَ «نُفِّذ» غامضة.
النطاق: نموذجُ اكتمالِ التنفيذِ وقاعدةُ الإغلاقِ عند الفشلِ فحسب — لا تعويضَ (1I) ولا صندوقَ صادرٍ ولا رصدَ.
المالك: core/sovereignty/
تاريخ الإنشاء: 2026-08-18
تاريخ آخر تعديل: 2026-08-18

## لماذا وُجِدت هذه الوحدة

كان الأثرُ التنفيذيُّ يُكتَب بـ`executed=True` **قبل** استدعاءِ المُنفِّذ. فإذا
رفع المُنفِّذُ استثناءً بقي في سجلِّ الدولةِ ادِّعاءُ تنفيذٍ ناجحٍ لفعلٍ لم
يكتمل — وهو الغموضُ الذي وثَّقته المرحلةُ 1F صراحةً وأحالت تصحيحَه إلى
Fail-Closed. القرارُ الإنسانيُّ أسند هذا التصحيحَ إلى 1J.

## القاعدةُ الواحدة

معاملةٌ سياديةٌ غيرُ مكتملةٍ ⇒ لا ادِّعاءَ تنفيذٍ ناجح. وتُطبَّق هذه القاعدةُ
في **مسارِ التنفيذِ نفسِه** لا في أداةٍ اختياريةٍ يُنسى استدعاؤها: لا يملك
`ExecutionRecord` حقلًا يُضبَط فيه النجاحُ يدويًّا، بل يُشتَقُّ `executed` من
`completion` اشتقاقًا، فيمتنع النجاحُ الكاذبُ بنيويًّا لا اتّفاقًا.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Generic, TypeVar

if TYPE_CHECKING:  # pragma: no cover — للتوثيق لا للتشغيل
    from core.constitutional_engine.model import Verdict

T = TypeVar("T")


class ExecutionCompletion(str, Enum):
    """حالةُ اكتمالِ المعاملةِ السيادية — وواحدةٌ منها فقط تعني «نُفِّذ».

    ولاحظ ما ليس هنا: لا قيمةَ تعني «حاولنا» أو «استُدعي المُنفِّذ» أو «صدر
    إذن» أو «وقع أثرٌ جزئي» وتُحسَب مع ذلك نجاحًا. فالنجاحُ قيمةٌ واحدةٌ
    (`COMPLETED`) وما عداها ليس نجاحًا.
    """

    #: لم يُستدعَ المُنفِّذُ أصلًا: منعٌ دستوريٌّ أو صلاحيةٌ مسحوبةٌ أو
    #: مرتكزٌ تدقيقيٌّ مفقود. لا أثرَ على حالةِ الدولة.
    NOT_EXECUTED = "NOT_EXECUTED"
    #: صدر الإذنُ واستُدعي المُنفِّذُ ولم تُعرَف نتيجتُه بعد. أثرٌ وسيطٌ
    #: يُثبِت لحظةَ الإذنِ (القاعدة 22)، **وليس** ادِّعاءَ تنفيذ.
    AUTHORIZED = "AUTHORIZED"
    #: عاد المُنفِّذُ سالمًا ومرتكزُ الأثرِ التدقيقيِّ مُثبَّت. هذه وحدَها
    #: تعني `executed == True`.
    COMPLETED = "COMPLETED"
    #: رفع المُنفِّذُ استثناءً. الاستثناءُ يُعادُ رفعُه ولا يُبتلَع، والأثرُ
    #: يقول «لم يُنفَّذ» لا «نُفِّذ».
    EXECUTION_FAILED = "EXECUTION_FAILED"
    #: قد يكون أثرٌ وقع، ولا يمكن **التصديقُ** على اكتمالِ المعاملةِ لأن
    #: مرتكزًا إلزاميًّا غائب. لا تُعَدُّ تنفيذًا ناجحًا، وتُترَك للتعويضِ
    #: أو الاستردادِ (1I) — وهذا هو معنى «الجزئيُّ لا يتنكَّر مكتملًا».
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"

    @property
    def certifies_execution(self) -> bool:
        """هل تُصدِّق هذه الحالةُ على تنفيذٍ ناجحٍ فعليٍّ؟ واحدةٌ فقط تفعل."""
        return self is ExecutionCompletion.COMPLETED


class MandatoryStage(str, Enum):
    """المراحلُ الإلزاميةُ **الموجودةُ فعلًا** في هذه المعمارية.

    ولم تُختَرع هنا مرحلةٌ لا يملكها الكود: الميزانيةُ والسياسةُ والذاكرةُ
    ليست طبقاتٍ قائمةً في بوابةِ السيادةِ اليوم، فلا تُزوَّر لها حراسةٌ
    وهميةٌ يُتَّجر بها في التقارير.
    """

    IDENTITY = "IDENTITY"          # أصالةُ الادّعاءِ الملكيّ (توقيع Ed25519)
    AUTHORITY = "AUTHORITY"        # الاختصاصُ ولم يُسحَب
    CONSTITUTION = "CONSTITUTION"  # حكمُ الدستور
    AUDIT_ANCHOR = "AUDIT_ANCHOR"  # قيدُ السجلِّ الدستوريِّ المُثبَّت
    EXECUTION = "EXECUTION"        # عودةُ المُنفِّذِ سالمًا


class FailClosedError(Exception):
    """أصلُ أخطاءِ الإغلاقِ عند الفشل — الفشلُ يُرفَع ولا يُترجَم نجاحًا."""


class IncompleteSovereignTransaction(FailClosedError):
    """مرحلةٌ إلزاميةٌ غائبةٌ أو غيرُ مؤكَّدةٍ ⇒ يُمنَع التنفيذُ ولا يُدَّعى."""

    def __init__(self, stage: MandatoryStage, reason: str) -> None:
        self.stage = stage
        self.reason = reason
        super().__init__(f"[FAIL_CLOSED · {stage.value}] {reason}")


def audit_anchor_of(verdict: Verdict) -> str:
    """أرجِعْ مرتكزَ الأثرِ التدقيقيِّ للحكم، أو نصًّا فارغًا إن لم يُثبَت.

    والفراغُ ليس تفصيلًا: قيدُ السجلِّ هو الدليلُ الوحيدُ على أن الحكمَ خرج
    من الذاكرةِ إلى أثرٍ دائم. فبلا قيدٍ لا يوجد إلّا زعمٌ في الذاكرة،
    والذاكرةُ ليست مصدرَ الحقيقةِ التشغيليَّ (القاعدة 17).
    """
    anchor = getattr(verdict, "ledger_entry_hash", None)
    return anchor if isinstance(anchor, str) and anchor.strip() else ""


def require_audit_anchor(verdict: Verdict) -> str:
    """اشترطْ مرتكزًا تدقيقيًّا مُثبَّتًا قبل التنفيذ، أو أغلِقْ على الفشل."""
    anchor = audit_anchor_of(verdict)
    if not anchor:
        raise IncompleteSovereignTransaction(
            MandatoryStage.AUDIT_ANCHOR,
            "لم يُثبَّت قيدُ الحكمِ في السجلِّ الدستوريّ، فلا مرتكزَ تدقيقيًّا "
            "للتنفيذ. الأثرُ الإلزاميُّ الفاشلُ يُغلِق البوابةَ ولا يُتجاوَز.",
        )
    return anchor


@dataclass(frozen=True, slots=True)
class ExecutionAttempt(Generic[T]):
    """نتيجةُ محاولةِ تنفيذٍ واحدةٍ — بحقيقتِها لا بما نتمنّاه.

    ولا يوجد بانٍ عامٌّ يسمح بتلفيقِ `COMPLETED` بلا استدعاءٍ فعليٍّ ناجح:
    تُنشَأ هذه القيمةُ من `attempt_execution` وحدَها.
    """

    completion: ExecutionCompletion
    value: Any = None
    error: BaseException | None = None
    failure_reason: str = ""

    @property
    def certified(self) -> bool:
        """هل يُصدَّق على هذه المحاولةِ تنفيذًا ناجحًا؟"""
        return self.completion.certifies_execution and self.error is None

    def raise_if_failed(self) -> None:
        """أعِدْ رفعَ استثناءِ المُنفِّذِ إن وُجِد — لا ابتلاعَ ولا تحويلَ للنجاح.

        ويُعادُ رفعُ **الاستثناءِ نفسِه** لا بديلٍ عنه: تحويلُ الفشلِ إلى نوعٍ
        آخرَ يُخفي سببَه، وإخفاءُ السببِ أوّلُ خُطوةٍ نحو النجاحِ الصامت.
        """
        if self.error is not None:
            raise self.error


def attempt_execution(
    executor: Callable[[], T],
    *,
    audit_anchor: str,
) -> ExecutionAttempt[T]:
    """نفِّذْ واحكِ ما جرى — هذه هي قاعدةُ 1J في موضعٍ واحدٍ لا في نسختين.

    وهي مصدرُ الحقيقةِ الوحيدُ لدلالةِ الاكتمال:

    * رفع المُنفِّذُ استثناءً ⇒ `EXECUTION_FAILED` والاستثناءُ محفوظٌ ليُعادَ رفعُه.
    * عاد سالمًا ولا مرتكزَ تدقيقيًّا ⇒ `RECOVERY_REQUIRED`؛ فقد يكون أثرٌ وقع
      ولا يجوز التصديقُ على اكتمالِ ما لا أثرَ تدقيقيَّ له.
    * عاد سالمًا والمرتكزُ مُثبَّت ⇒ `COMPLETED` وحينها فقط.

    ويُلتقَط `BaseException` لا `Exception` وحدَه: انقطاعُ العمليةِ في منتصفِ
    المُنفِّذِ حالةُ فشلٍ حقيقيةٌ يجب أن يقولَها السجلُّ، ثم يُعادُ رفعُها كما
    هي فلا تُبتلَع.
    """
    try:
        value = executor()
    except BaseException as exc:  # noqa: BLE001 — يُعادُ رفعُه حرفيًّا في raise_if_failed
        return ExecutionAttempt(
            completion=ExecutionCompletion.EXECUTION_FAILED,
            value=None,
            error=exc,
            failure_reason=f"{type(exc).__name__}: {exc}",
        )

    if not audit_anchor:
        return ExecutionAttempt(
            completion=ExecutionCompletion.RECOVERY_REQUIRED,
            value=value,
            error=None,
            failure_reason=(
                "عاد المُنفِّذُ سالمًا بلا مرتكزٍ تدقيقيٍّ مُثبَّت، فلا يُصدَّق على "
                "اكتمالِ المعاملة. الحالةُ تحتاج استردادًا أو تعويضًا."
            ),
        )

    return ExecutionAttempt(
        completion=ExecutionCompletion.COMPLETED,
        value=value,
        error=None,
    )


__all__ = [
    "ExecutionAttempt",
    "ExecutionCompletion",
    "FailClosedError",
    "IncompleteSovereignTransaction",
    "MandatoryStage",
    "attempt_execution",
    "audit_anchor_of",
    "require_audit_anchor",
]
