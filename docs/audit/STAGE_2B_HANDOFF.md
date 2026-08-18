# STAGE_2B_HANDOFF.md — تسليمُ المرحلةِ 2B (هجرةُ عائلةِ سجلِّ الدولة)

> **حالةُ الوثيقة:** تُبنى تدريجيًّا مع كلِّ عمليّةٍ من P1. وما لم تُذكرْ عمليّةٌ فيها فهي **لم تُهاجَرْ بعد** — لا يُفترَضُ إنجازٌ من سكوت.

| البند | القيمة |
|---|---|
| الأساس | `6a86205ce635a777673dce7a125f6b6bfeec433e` |
| P0 | `7823bf12f16fdafc7f635764cb27293ca8649511` — مدفوعٌ إلى GitHub |
| P1أ | `e814cd2cc966cea2980725ddab4a230177a4671b` — مدفوعٌ إلى GitHub |
| النطاق | `set_institution_status` · `create_department` · `appoint_official` · `revoke_official` · إغلاقُ المسارِ القديمِ في `state_registry/main.py` |
| المُنجَزُ حتى الآن | **2 من 5** (`set_institution_status` · `create_department`) |
| الرقمُ المرجعيّ | `non_sovereign_write_operations` بأداةِ الجردِ v2: خطُّ الأساس **208** ← الآن **206** |

---

## P1أ · `state_registry.set_institution_status` — **MIGRATED**

### 1. ما تغيّر

| الموضع | التغيير |
|---|---|
| `state_registry/service.py` | العمليّةُ صارت تعبرُ الحدَّ بـ`guard_declared` بأثرٍ مُعلَنٍ ومُعوِّضٍ مربوطٍ ومفتاحِ ذرّيّة |
| المُعوِّض | معاونٌ خاصٌّ واحدٌ `_set_institution_status_row` هو **مُطبِّقُ الأثرِ ومُعوِّضُه** — فلا مسارَ كتابةٍ ثانٍ للحالة |
| التوقيع | `set_institution_status(*, context, code, status, reason, change_id=None)` — `change_id` اختياريٌّ على سُنّةِ `allocation_id` في 2A، ولا مُعامِلَ تجاوزٍ فيه |
| الثوابت | `INSTITUTION_STATUS_SCOPE = "state_registry.institution.status"` · `ACTION_INSTITUTION_STATUS = "registry.institution.status"` |

### 2. الأدلّةُ الإحدى عشرةَ المطلوبةُ لكلِّ عمليّة

| # | المطلوب | الدليل |
|---|---|---|
| 1 | إعلانُ الأثرِ (ActionRequest/Contract) | `test_status_change_writes_row_and_passes_mandatory_stages` |
| 2 | صحّةُ الفاعل | الفاعلُ `EXECUTIVE` — والفعلُ ليس حصريًّا لسلطةٍ أخرى |
| 3 | المراحلُ الإلزاميّة | `MANDATORY_INTERNAL_STAGES <= set(outcome.stages)` |
| 4 | النطاق | `test_declared_effect_stays_within_the_target` — الأثرُ `…/status` تحتَ الهدفِ `institutions/{tenant}/{code}` |
| 5 | التنفيذ | صفُّ المؤسسةِ تغيّرَ فعلًا في قاعدةِ البيانات |
| 6 | المُعوِّضُ حقيقيٌّ لا `pass` | `test_compensator_restores_the_previous_status` + `test_compensation_plan_covers_the_declared_effect` (يُنادى المُعوِّضُ فيُرجِعُ الحالةَ فعلًا) |
| 7 | الذرّيّة | `test_same_change_key_changes_status_once` |
| 8 | التدقيق | حصيلةُ الحدِّ تحملُ إذنًا وعقدًا وتوقيعاتِ أثرٍ مُسجَّلة |
| 9 | أثرُ قاعدةِ البيانات | `_status_of(...)` يُقرأُ من القاعدةِ لا من الحصيلة |
| 10 | السلوكُ عند الفشل | `test_failure_inside_applier_does_not_claim_success` — لا نجاحٌ مُدَّعى ولا أثرٌ نصفيٌّ مسكوت |
| 11 | غيابُ المسارِ القديم | `test_institution_status_is_mutated_from_one_function_only` (قياسٌ بشجرةِ المصدرِ لا بعدِّ سطور) + `test_no_public_status_write_outside_the_guarded_operation` |

### 3. أدلّةُ عدمِ التجاوز

- `test_no_forbidden_bypass_parameter_in_the_migrated_operation` — لا `force/bypass/skip_check/unchecked/override/no_verify/unsafe`.
- `test_no_new_sovereignty_primitive_was_defined` — لم تُنشَأْ بدائيّةٌ سياديّةٌ جديدة.
- `test_local_authorization_denial_leaves_status_untouched` · `test_gateway_denial_leaves_status_untouched` — الرفضُ لا يُغيِّرُ شيئًا، والحكمُ في الثاني **حكمُ رفضٍ حقيقيٌّ** مقروءٌ من المحرِّكِ الدستوريِّ لا نصٌّ مُصطنَع.
- `test_unknown_status_is_still_refused_before_the_boundary` · `test_dissolved_institution_is_not_revived` · `test_dissolve_is_refused_while_an_active_department_remains` — قواعدُ ما قبلَ الهجرةِ باقيةٌ كما كانت.

### 4. ما اكتُشِفَ ولم يُخفَ

| الاكتشاف | التصنيف | ما فُعِلَ |
|---|---|---|
| عيبٌ في **أداةِ القياس**: العمليّةُ المُهاجَرةُ تختفي من العدِّ بدلًا من انتقالِها إلى «سياديّة» | `TECHNICAL_FIXABLE` | أُصلِحت الأداةُ (v2) وأُعيدَ قياسُ خطِّ الأساسِ بها: 185 ← **208**. أي أنّ الدَّينَ الحقيقيَّ كان أكبرَ من المُعلَن |
| **Q-11**: هويّةُ الإذنِ (1F) دقّتُها ثانيةٌ واحدة، فعمليّتانِ مختلفتانِ على الهدفِ نفسِها في الثانيةِ نفسِها لا تمرّانِ معًا | `HUMAN_DECISION_REQUIRED` | مُسجَّلٌ في سجلِّ القرارات · مُثبَّتٌ باختبارٍ **حتميّ** · لم تُمَسَّ `core/sovereignty` · قِيسَ أنّه **قائمٌ منذ 2A** لا أحدثَته الهجرة |
| **Q-12**: العمليّةُ الفاشلةُ تُعادُ بالمفتاحِ نفسِه في ثانيةٍ جديدةٍ فتُنتِجُ أثرًا ثانيًا (1000 ← 1400 ← 1800) | `HUMAN_DECISION_REQUIRED` | مُسجَّلٌ في سجلِّ القرارات · صُحِّحَ ادّعاءٌ في اختبارِ G-7 من 2A كان ينجحُ بالتوقيتِ وحدَه · لم تُمَسَّ `idempotency.py` |

**قيدٌ مُصرَّحٌ به على هذه العمليّةِ بعينِها:** بسببِ Q-11، تغييرانِ متعاقبانِ لحالةِ **المؤسسةِ نفسِها في الثانيةِ نفسِها** لا يمرّانِ معًا بعدَ الهجرة، وكانا يمرّانِ قبلَها. وهي عمليّةٌ ذرّيّةٌ بقيمتِها (إسنادُ حالةٍ لا زيادةٌ تراكميّة) فتكرارُ تنفيذِها لا يُنتِجُ حالةً مختلفة، ولذلك لم يُنشَأْ بها خطرُ أثرٍ مزدوجٍ من Q-12. ولا يُدَّعى أنّ حفظَ السلوكِ العامِّ كاملٌ: الفرقُ مُعلَنٌ هنا ومُعلَّقٌ على قرارٍ بشريّ.

### 5. الاختبارات

| المجموعة | النتيجة |
|---|---|
| `tests/test_2b_state_registry_sovereign.py` (جديد) | **18 passed** |
| مجموعةُ الانحدارِ (سجلُّ الدولة · 2A · الخزانة · الحدُّ 1N · الخدماتُ الحكوميّة · التكاملُ الفديراليّ · حالاتُ P12) | **181 passed** |
| `tests/sovereignty/` | **795 passed · 1 skipped** |

### 6. ما لم يُنجَزْ في P1أ

- المسارُ القديمُ في `state_registry/main.py` **لم يُغلَقْ بعد** — إغلاقُه في P1د كما في خطّةِ المرحلة.
- `create_department` · `appoint_official` · `revoke_official` — لم تُهاجَرْ بعد.

---

## P1ب · `state_registry.create_department` — **MIGRATED**

### 1. ما تغيّر

| الموضع | التغيير |
|---|---|
| `create_department` | تعبرُ الحدَّ بـ`guard_declared` بأثرٍ مُعلَنٍ ومُعوِّضٍ مربوطٍ ومفتاحِ ذرّيّة |
| المُعوِّض | `_delete_department_row` — حذفُ الصفِّ المُنشأِ فعلًا، على سُنّةِ `_delete_institution_row` المُثبَتةِ في 2A |
| الهدف | `institutions/{tenant}/{institution_code}/departments/{code}` — التبعيّةُ ظاهرةٌ في الهدفِ نفسِه لا مُستنبَطة |
| الثوابت | `DEPARTMENT_CREATE_SCOPE` · `ACTION_DEPARTMENT_CREATE = "registry.department.create"` (نصُّ التخويلِ المحلّيِّ القائمِ نفسُه) |
| المُنشئُ الوحيد | `DepartmentModel(...)` لا يُبنى إلاّ في مُطبِّقِ الأثرِ داخلَ الحدّ — مقيسٌ بشجرةِ المصدرِ بعدَ طرحِ الدوالِّ الداخليّة |

### 2. الأدلّة

| الدعوى | الدليل |
|---|---|
| العبورُ والمراحلُ والإذن | `test_creation_writes_row_and_passes_mandatory_stages` |
| النطاق | `test_declared_effect_stays_within_the_target` |
| المنعُ محلّيًّا وبالبوّابة | `test_local_authorization_denial_creates_no_row` · `test_gateway_denial_creates_no_row` (بحكمِ رفضٍ حقيقيٍّ من الدستور) |
| تعويضٌ حقيقيّ | `test_compensation_plan_covers_the_effect_and_reverses_it` — يُنادى المُعوِّضُ فيُحذَفُ الصفُّ فعلًا |
| الفشل | `test_failure_inside_applier_does_not_claim_success` |
| الإعادة | `test_duplicate_code_is_refused_before_the_boundary` · `test_replay_of_a_proven_key_creates_nothing` |
| إغلاقُ التجاوز | `test_department_rows_are_built_in_one_function_only` |
| الإنفاذُ الساكن | `test_no_forbidden_bypass_parameter_in_the_migrated_operation` |
| الانحدار | `test_department_under_inactive_institution_is_refused` · `test_department_under_unknown_institution_is_refused` |

### 3. ملاحظاتٌ مُصرَّحٌ بها

- **الحرسُ الطبيعيُّ يسبقُ الحدَّ:** منعُ تكرارِ رمزِ الإدارةِ فحصٌ قبلَ العبورِ كما كان قبلَ الهجرة، فمسارُ الإعادةِ (1H) لا يُرى إلاّ إن غابَ الصفُّ وبقيَ المفتاح (ما بعدَ تعويضٍ أو حذف). وقد قيسَ هذا الفرعُ صراحةً ولم يُترَكْ مجهولًا.
- **Q-11 لا يمسُّ هذه العمليّةَ:** إنشاءُ إدارتينِ مختلفتينِ في الثانيةِ نفسِها هدفُهما مختلفٌ فعقدُهما مختلفٌ فإذنُهما مختلف. والتصادمُ إنّما يقعُ على الهدفِ الواحد.
- **لا مفتاحَ عمليّةٍ من المُنادي:** لم يُضَفْ `change_id` هنا — الهويّةُ الطبيعيّةُ (مستأجر · مؤسسة · رمز) كافيةٌ ومُقيَّدةٌ أصلًا، وإضافةُ مفتاحٍ اختياريٍّ بلا حاجةٍ توسيعٌ للسطحِ لا إحكامٌ له.

### 4. الاختبارات

| المجموعة | النتيجة |
|---|---|
| ملفُّ إثباتِ 2B (P1أ + P1ب) | **30 passed** |
| مجموعةُ الانحدار | **193 passed** |
| `tests/sovereignty/` | **795 passed · 1 skipped** |

| المقياس | قبلَ P1ب | بعدَ P1ب |
|---|---|---|
| تعبرُ الحدَّ | 4 | **5** |
| لا تعبرُ الحدَّ | 207 | **206** |
