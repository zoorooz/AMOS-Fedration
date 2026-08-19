# docs/audit — ديوان تدقيق الدولة

## التعريف
ديوان التدقيق هو الجهة التي تقول الحقيقة عن حالة الدولة، حتى لو خالفت ما تعلنه بقية الوثائق.
مهمته قياس الفجوة بين ما يقول المشروع إنه يفعله وما ينفذه الكود فعليًا، وإصدار مصفوفة الحقيقة، وحراسة تعريف الإنجاز.
لا تُقفل أي مرحلة في هذه الدولة إلا بشهادة من هذا الديوان.

## النطاق
**يدخل:** مصفوفة الحقيقة، تعريف الإنجاز، خارطة عصر التنفيذ، تقارير التدقيق الدورية، سجل المخالفات.
**لا يدخل:** التنفيذ نفسه، السياسات، المراسيم، الوثائق المعمارية.

## المالك
royal/ — المجلس التأسيسي، بتفويض التنفيذ إلى `tools/governance/`.

## تاريخ الإنشاء
2026-08-16

## تاريخ آخر تعديل
2026-08-19

## المحتويات

| الملف | الدور | التوليد |
|---|---|---|
| [`PHASE_E_ROADMAP.md`](PHASE_E_ROADMAP.md) | خطة السجل — E0 إلى E24 | يدوي |
| [`DEFINITION_OF_DONE.md`](DEFINITION_OF_DONE.md) | تعريف الإنجاز ونظام الحالات | يدوي |
| [`TRUTH_MATRIX.md`](TRUTH_MATRIX.md) | مصفوفة الحقيقة بالأدلة | **آلي — لا تحرره** |
| `truth_matrix.json` | المصفوفة الآلية لبوابات CI | **آلي — لا تحرره** |
| [`COMPLETION_LEDGER.md`](COMPLETION_LEDGER.md) | سجلُّ الإكمال — خريطةُ الطريقِ إلى 100٪، والقاعدةُ الملزمةُ (التوثيقُ قبلَ الدفع)، وسجلُّ ما نُفِّذ | يدوي — **مُلزِمٌ لكلِّ عامل** |
| [`SOVEREIGN_DECISION_REGISTER.md`](SOVEREIGN_DECISION_REGISTER.md) | سجلُّ القراراتِ السياديّةِ المعلَّقة — Q-1…Q-27 | يدوي |
| [`Q5_TREASURY_DECISION_BRIEF.md`](Q5_TREASURY_DECISION_BRIEF.md) | مذكّرةُ حسمِ Q-5: مرجعُ المالِ وأفعالُه — Q-17…Q-20 خيارًا خيارًا | يدوي |

## إعادة توليد المصفوفة

```bash
python tools/governance/truth_audit.py            # توليد
python tools/governance/truth_audit.py --strict   # بوابة CI (تفشل عند CRITICAL)
```

## بوابةُ التوثيقِ قبلَ الدفع

```bash
python tools/governance/check_completion_ledger.py --staged     # قبل الالتزام
python tools/governance/check_completion_ledger.py --self-check  # شكلُ السجلِّ وحده
```

وتُنفَذُ في التكاملِ المستمرِّ بوظيفةِ `ledger-gate` — ثلاثُ بوابات: سلامةُ
شكلِ السجلّ، وقيدُ كلِّ عملٍ مدفوع، ومُراقبةُ البوّابةِ نفسِها باختباراتِها.

## القاعدة

> `DONE = Capability Proven`
> `PUSH = Work + Its Record, Together` — [`COMPLETION_LEDGER.md`](COMPLETION_LEDGER.md) § 2

راجع [`WORKING_PRINCIPLE.md`](../governance/WORKING_PRINCIPLE.md) — المبدأ الملزم لكل من يعمل في هذا المستودع.
