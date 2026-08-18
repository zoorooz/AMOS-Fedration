# TREASURY_MIGRATION_ANALYSIS.md — تحليلُ هجرةِ الخزانةِ ومصدرُ حقيقةِ المال

**المرحلة:** P6 (القسمانِ A و B) · **التاريخ:** 2026-08-18 · **الفرع:** `main`
**خطُّ أساسِ القياس:** الالتزامُ `82ebc7c` (فتحُ P6) · **الدَّينُ الكلّيُّ حينَه:** 171
**القاعدةُ الحاكمة:** `SOVEREIGN_MIGRATION_PROGRAM.md` § 5.1 · الحالةُ المركزيّةُ § 8.0

> **حدُّ هذه الوثيقةِ الصريح:** تحليلٌ وقياسٌ فحسب. **لم تُهاجَرْ عمليّةُ مالٍ واحدةٌ،
> ولم يُمَسَّ سطرٌ إنتاجيٌّ في أيِّ خزانة، ولم يُغلَقْ مسارٌ قديم.** ولا يُقرأُ شيءٌ
> ممّا يلي إذنًا بهجرةٍ قبلَ الحسمِ المطلوبِ في § 5.

---

## 1. ما قِيسَ — المالُ في أربعةِ مواضعَ لا اثنين

صيغةُ Q-5 («أيُّ خزانةٍ هي المرجع؟») كانتْ أصغرَ من الواقع. أداةُ الجردِ نفسُها عدَّتْ:

| # | الموضع | الجداول | عمليّاتٌ عامّةٌ مُغيِّرة | تعبرُ الحدّ | تمثيلُ المبلغ |
|---|---|---|---|---|---|
| 1 | `state_treasury/service.py` (1795 سطرًا) | `state_treasuries` · `state_accounts` · `state_budgets` · `state_allocations` · `state_transactions` · `state_ledger_entries` | **7** | **0** | `Numeric(20,4)` |
| 2 | `governance/treasury.py` | `treasury_transactions` · `treasury_budgets` · `treasury_reports` | **9** | **0** | `Float` |
| 3 | `governance/state_runtime.py` — عمودُ `budget` | صفُّ الولايةِ الفدراليّة | كتابةٌ واحدةٌ عبرَ `_add_to_budget` | **مُهاجَرةٌ في 2A** | `String` |
| 4 | `national_economy/service.py` | `state_revenue_sources` · `state_expenditure_authorizations` · `state_economic_transfers` · `state_procurements` · `state_public_assets` · `state_public_liabilities` | **16** | **0** | `Numeric(20,4)` |

يُعادُ التوليدُ بـ `python tools/audit/sovereign_write_inventory.py --service <path>`.

**قياسانِ صريحان:** `state_treasury/service.py` فيه **صفرُ** إشاراتٍ إلى
`guard_declared` أو `ConstitutionalAuthorizer` أو جسرِ السيادة، وكذلك
`governance/treasury.py`. أي إنَّ 32 كتابةَ مالٍ عامّةً (7 + 9 + 16) لا يمرُّ منها شيءٌ
على البوابة، وموضعُ المالِ الوحيدُ المُهاجَرُ هو عمودُ ميزانيّةِ الولايةِ في 2A.

**وفرقُ التمثيلِ ليس تفصيلًا:** `Numeric(20,4)` و`Float` و**نصٌّ** (`String`) يُجمَعُ
بتحويلٍ في الشيفرة. ثلاثُ دقّاتٍ تعني أنَّ «الرصيد» ليس مفهومًا واحدًا في النظام،
وأنَّ أيَّ مطابقةٍ بينَها حسابٌ تقريبيٌّ لا تسويةٌ حسابيّة.

---

## 2. من يشيرُ إلى مَن — دليلُ الأولويّةِ البنيويّة

اتّجاهُ المفاتيحِ الأجنبيّةِ دليلٌ لا رأي، وقد قِيسَ:

| المُشيرُ | المُشارُ إليه | القيد |
|---|---|---|
| `national_economy.state_revenue_sources.revenue_account_id` | `state_accounts.id` | `RESTRICT` |
| `national_economy.state_expenditure_authorizations.budget_id` | `state_budgets.id` | `RESTRICT` · `NOT NULL` |
| `national_economy.state_economic_transfers.budget_id` | `state_budgets.id` | `RESTRICT` · `NOT NULL` |
| `national_registry.state_authority_grants.budget_id` / `.account_id` | `state_budgets.id` / `state_accounts.id` | `RESTRICT` |
| `national_registry.state_transaction_authority.transaction_id` | `state_transactions.id` | مفتاحٌ أوّليٌّ مُشترَك |

و**صفرُ** مفاتيحَ أجنبيّةٍ في `governance/treasury.py` بأكملِه، ولا مفتاحَ من جداولِ
الدولةِ إلى `treasury_*`، ولا رابطَ بينَ عمودِ `state_runtime.budget` وأيِّ حساب.

**ما يُستخلَصُ من هذا القياسِ وحدَه:** في نطاقِ **مالِ الدولةِ العامّ** `state_treasury`
هو المرجعُ البنيويّ — غيرُه يشيرُ إليه بقيدِ `RESTRICT` ولا يشيرُ هو إلى غيره —
و`national_economy`، على كِبَرِ عددِ كتاباتِه (16)، **مشتقٌّ** لا أصل: تصريحُ صرفٍ بلا
`budget_id` مرفوضٌ في المُخطَّطِ نفسِه.

**وما لا يُستخلَص:** أنَّ `governance/treasury.py` خزانةٌ منافسةٌ رُجِّحَ عليها
`state_treasury`. القياسُ يقولُ إنَّها **عالَمٌ منفصلٌ** بعملةٍ أخرى (`amos-credit`)
لوكلاءَ لا لمؤسّسات، بلا رابطٍ بنيويٍّ واحد. وهل هما «مالٌ واحد» دستوريًّا؟ ذاك ليس
سؤالًا تقنيًّا (Q-17).

---

## 3. أخطرُ ما قِيسَ — التسميةُ وحدَها تُقرِّرُ حمايةَ المال

الدستورُ يعرفُ أربعةَ أفعالٍ ماليّةٍ في معجمِه
(`core/constitutional_engine/rules.py::TREASURY_ACTIONS`) ويُسنِدُها إلى فرعِ الخزانة.
وقِيسَ حكمُ البوابةِ على عشرينَ فعلًا مرشَّحًا لكلِّ فاعلٍ من ثلاثة (المُخرَجُ الخامُّ
محفوظٌ في `docs/audit/evidence/treasury_gate_matrix.json`، ويُعادُ توليدُه بـ `python tools/audit/treasury_gate_probe.py`):

| الفعلُ المرشَّح | فاعلٌ تنفيذيّ | خزانة | ملكيّ |
|---|---|---|---|
| `allocate_budget` · `issue_tokens` · `allocate_resources` · `book_expense` | **DENY · R-003-1** | ALLOW | ALLOW |
| `disburse_funds` · `transfer_treasury` | ALLOW | ALLOW | ALLOW |
| `treasury.establish` · `treasury.account.open` · `treasury.budget.create` · `treasury.allocate` · `treasury.funding.post` · `treasury.disburse` · `treasury.decision.disburse` · `treasury.transaction.reverse` | ALLOW | ALLOW | ALLOW |
| `economy.expenditure.authorize` · `economy.transfer.execute` · `economy.procurement.award` | ALLOW | ALLOW | ALLOW |
| `reward_task_completion` · `charge_model_invoke` · `run_economic_cycle` | ALLOW | ALLOW | ALLOW |

قراءةُ الجدولِ بلا تلطيف: **فعلُ مالٍ يُسمّى باسمٍ دستوريٍّ يُمنَعُ على الفاعلِ
التنفيذيّ، وينفُذُ إن سُمِّيَ باسمٍ نطاقيّ.** و`disburse_funds` و`transfer_treasury`
مذكورانِ في `core/sovereignty/jurisdiction.py` ضمنَ ما يُمنَعُ على **القضاء** فحسب،
ولا وجودَ لهما في معجمِ المال، فيمرّانِ للتنفيذيِّ بلا حرس.

فتسميةُ عمليّةِ صرفٍ `treasury.disburse` بدلَ `book_expense` عندَ هجرتِها **ليست
اختيارَ مُعرِّف**، بل تحييدُ فعلٍ حصريٍّ هروبًا من `DENY` — وهو محظورٌ على المُنفِّذِ
نصًّا. ولذلك تتوقّفُ الهجرةُ هنا لا عندَ عائقٍ تقنيّ.

---

## 4. السابقةُ المُثبَتةُ في 2A — النمطُ الشرعيُّ موجودٌ ومقيس

لا يُقالُ إنَّ الطريقَ مجهول. في `governance/state_runtime.py` كتابةُ ميزانيّةٍ
مُهاجَرةٌ فعلًا (2A) بهذا النمطِ المقيسِ سطرًا سطرًا:

- الفعلُ هو **اسمُ الدستورِ نفسُه**: `ACTION_ALLOCATE_BUDGET = "allocate_budget"`،
  وتعليقُ الشيفرةِ فوقَه صريح: «فعلُ التوزيعِ كما يعرفُه الدستورُ نفسُه — لا اسمٌ
  محليٌّ يوازيه».
- الفاعلُ فاعلُ خزانةٍ لا تنفيذيّ: `TREASURY_ACTOR = "TREASURY"` ثمّ
  `ConstitutionalAuthorizer(actor=TREASURY_ACTOR)` (السطرُ 156)، ويُثبِّتُه اختبارُ
  `test_2a_sovereign_runtime_integration.py:104`.
- القيمةُ السابقةُ تُقرأُ **قبلَ** عبورِ الحدّ، والتعويضُ عكسٌ حقيقيٌّ للفرق:
  `lambda: self._add_to_budget(state_id, -delta)` — لا إسنادُ رقمٍ مُطلَق.
- مفتاحُ الذرّيّةِ نطاقُه `state_runtime.budget.allocate`، وعندَ الإعادةِ **لا توزيعَ
  ثانيًا** ويُقالُ «أُعيدَ» صراحةً.

**فما يبقى مجهولًا ليس النمطَ، بل ثلاثةَ أمورٍ لا يملكُها المُنفِّذ:** إسنادُ أفعالِ
الخزانةِ الثمانيةِ إلى معجمٍ فيه أربعةُ أفعالٍ فقط (Q-18)، وشرعيّةُ أن تحملَ خدمةٌ
كاملةٌ في الشجرةِ التنفيذيّةِ فاعلَ خزانةٍ لجميعِ عمليّاتِها (Q-19)، وطبيعةُ
`amos-credit` (Q-17).

---

## 5. حسمُ Q-5 — ما حُسِمَ بالدليلِ وما تفرَّعَ أسئلةً

**حُسِمَ بالدليلِ (لا يحتاجُ قرارًا):** في نطاقِ مالِ الدولةِ العامّ، `state_treasury`
هو مصدرُ الحقيقةِ البنيويُّ و`national_economy` طبقةٌ مشتقّةٌ منه — بدليلِ اتّجاهِ
المفاتيحِ الأجنبيّةِ وقيدِ `RESTRICT` وانفرادِ `state_ledger_entries` بقيدِ تفرُّدٍ على
المعاملة. وهذا يكفي لترتيبِ أيِّ هجرةٍ لاحقة: **الأصلُ قبلَ المشتقّ.**

**ولا يُحسَمُ بالقياس** (قُيِّدَ أسئلةً في `SOVEREIGN_DECISION_REGISTER.md`): **Q-17**
طبيعةُ `amos-credit` · **Q-18** إسنادُ أفعالِ المالِ إلى المعجمِ أو توسيعُه ·
**Q-19** حاملُ فاعلِ الخزانةِ في خدمةٍ تنفيذيّة · **Q-20** توحيدُ تمثيلِ المبلغِ من
عدمه (ويمسُّ بياناتٍ قائمةً لا شيفرةً فحسب).

وتُذكَرُ **Q-12** هنا مُشدَّدةً: كتابةُ المالِ **غيرُ ذرّيّةٍ بقيمتِها** (زيادةٌ
تراكميّةٌ لا إسنادُ حالة)، فسلوكُ سجلِّ الذرّيّةِ تجاهَ عمليّةٍ فاشلةٍ يصيرُ في
الخزانةِ فرقَ مالٍ حقيقيًّا لا فرقَ حالة.

---

## 6. تصنيفُ العمليّاتِ (P6-C) — بلا تنفيذِ أيِّها

| العمليّة | الموضعُ والسطر | التصنيف | ما يمنعُ اليوم |
|---|---|---|---|
| `establish_treasury` | `state_treasury:832` | **BLOCKED** | Q-18 · Q-19 |
| `open_account` | `state_treasury:888` | **BLOCKED** | Q-18 · Q-19 |
| `create_budget` | `state_treasury:973` | **BLOCKED** | Q-18 (وفعلُه المُرجَّحُ `allocate_budget` = DENY للتنفيذيّ) |
| `allocate` | `state_treasury:1056` | **BLOCKED** | Q-18 · Q-12 (تراكميّة) |
| `post_funding` | `state_treasury:1183` | **BLOCKED** | Q-18 · Q-12 |
| `disburse` | `state_treasury:1285` | **BLOCKED** | Q-18 (`book_expense`؟) · Q-19 |
| `reverse_transaction` | `state_treasury:1489` | **BLOCKED** | Q-18 · وهي تعويضٌ بطبيعتِها فيلزمُ حسمُ مالكِه |
| `execute_decision_disbursement` | `state_treasury:1423` | **DEFERRED** | لم تُعَدَّ موضعَ كتابةٍ مستقلًّا في الجرد (تُفوِّضُ الصرف) — تُصنَّفُ مع `disburse` |
| 16 عمليّةً | `national_economy/service.py` | **DEFERRED** | مشتقّةٌ من الأصل: لا تُهاجَرُ قبلَ أصلِها |
| 9 عمليّاتٍ | `governance/treasury.py` | **BLOCKED** | Q-17 قبلَ كلِّ شيء |
| عمودُ `budget` | `governance/state_runtime.py` | **PROVEN (2A)** | لا شيء — وهو السابقةُ المرجعيّةُ في § 4 |

**المجموع:** 32 كتابةَ مالٍ عامّةً غيرَ مُهاجَرة، **لا واحدةَ منها قابلةٌ للهجرةِ اليومَ
بلا قرارٍ بشريّ**. وهذا مُخرَجُ P6 الحقيقيّ: العائقُ دستوريٌّ لا هندسيّ.

---

## 7. ما لم يُفعَلْ ولماذا

- **لم يُوسَّعْ معجمُ الأفعالِ الماليّة** — توسيعُه تعديلٌ في عقدٍ دستوريٍّ قائم.
- **لم يُنسَخْ فاعلُ الخزانةِ من 2A إلى خزانةِ الدولة.** النمطُ مُثبَتٌ لكتابةٍ واحدةٍ
  في خدمةِ تشغيلِ الولايات؛ وتعميمُه على خدمةٍ ماليّةٍ كاملةٍ (1795 سطرًا) نقلُ اختصاصٍ
  بينَ فرعين لا تفصيلٌ تقنيّ (Q-19).
- **لم تُوحَّدْ تمثيلاتُ المبلغ** — هجرةُ بياناتٍ ماليّةٍ بلا قرارٍ مالكٍ ممنوعة.
- **لم يُمَسَّ `governance/treasury.py`** ولا سلسلةُ تجزئتِه، ولم يُقَلْ إنَّها ليست
  مالًا: ذاك جوابُ Q-17 لا جوابي.
- **لم يُغلَقْ مسارٌ قديمٌ في أيِّ خزانة**، ولم يتغيّرْ رقمُ الدَّينِ (171).

## 8. الخطوةُ التالية

P7 — تحليلُ القضاءِ والتشريع (Q-6 · Q-7)، وهي أكبرُ كتلةِ دَينٍ باقية: `federal_judiciary`
بـ 18 عمليّةً في `service.py` و5 في `docket.py` و2 في `registry.py` وواحدةٍ في كلٍّ من
`enforcement.py` و`rulings.py`. ولا تُفتَحُ هجرةُ مالٍ قبلَ جوابِ Q-17…Q-20.
