# R5 — الصندوق الرملي متعدّد المزوِّدات

## الهدف
تقريرُ تدقيقٍ لجولةِ R5: طبقةُ مزوِّدات الصندوق الرملي — ما نُفِّذ، وما فُحص
بعقدٍ لا بخدمةٍ حقيقية، وما بقي غيرَ مُلاحَظ.

**الحالة:** المُهيّئات مُنفَّذة · اختبارات العقد مُتحقَّقة · التنفيذ الحقيقي على Modal و E2B **UNOBSERVED**
**النطاق:** `federal/executive/services/src/amos_federation/services/tool_registry/providers/`
**التاريخ:** 2026-08-17
**القاعدة الحاكمة:** لا يُدّعى REAL بلا تنفيذ مُلاحَظ.

---

## 0. جدول الحالة — الادعاء مقابل الملاحظة

هذا الجدول هو الفصل. ما دونه شرح له، لا توسيع لمزاعمه.

| المزوِّد | المُهيّئ (Adapter) | اختبارات العقد | اختبار التنفيذ الحقيقي (Smoke) |
| --- | --- | --- | --- |
| **Modal** | ✅ IMPLEMENTED | ✅ VERIFIED | ⬜ **UNOBSERVED** |
| **E2B** | ✅ IMPLEMENTED | ✅ VERIFIED | ⬜ **UNOBSERVED** |
| **Local (subprocess)** | ✅ IMPLEMENTED | ✅ VERIFIED | ✅ OBSERVED — نُفِّذ فعلًا في هذه الجولة |
| **Simulation** | ✅ IMPLEMENTED | ✅ VERIFIED | ⛔ غير منطبق — محاكاة معلَنة، ليست تنفيذًا |

**معنى UNOBSERVED هنا، حرفيًّا:** لم تُوجَد اعتمادات Modal ولا E2B حقيقية في بيئة هذه الجولة، فلم يُنشأ صندوق واحد عند أيٍّ من الخدمتين، ولم يُنفَّذ سطر كود واحد عليهما. المُهيّئان مكتوبان مقابل واجهتي SDK المنشورتين، ومُختبَران مقابل مضاعِفات (`_FakeModalSDK` و `_FakeE2BSandbox`) تفحص **العقد** لا الخدمة. أي زعم بأن Modal أو E2B «تعمل» في هذا المستودع اليوم هو زعم بلا مشاهدة.

**لماذا لم تُطلَب الاعتمادات:** أسرار الخزنة في بيئة التشغيل هذه تُحقَن عبر وسيط HTTPS ولا تظهر متغيّرات بيئة، بينما Modal يتكلّم gRPC و E2B يفتح نطاقات فرعية ديناميكية — فلا يبلغهما الحقن. والالتفاف على الوسيط ممنوع صراحةً. فاختير المسار الصريح: تُبنى المُهيّئات، ويُعلَن التنفيذ الحقيقي غير مُلاحَظ.

---

## 1. المعمارية

```
Agent Runtime (ToolSandbox — SIMULATION، كانوني، لا يعرف مزوِّدًا)
        │
        │  المسار الوحيد إلى تنفيذ حقيقي
        ▼
tool_registry.authorized_execution.authorize()
        Agent → Role → Capability → Permission → Tool  ← فحص محض، لا صندوق هنا
        │
        ▼  (وبعده فقط)
tool_registry.providers.selection.resolve_provider()
        │
        ▼
SandboxProvider (ABC)
   ├── LocalSubprocessProvider   REAL
   ├── ModalProvider             REAL  ← الملف الوحيد الذي يستورد `modal`
   ├── E2BProvider               REAL  ← الملف الوحيد الذي يستورد `e2b`
   └── SimulationProvider        SIMULATION (محظور في الإنتاج)
```

الملفّات (1708 سطرًا):

| الملف | الأسطر | الدور |
| --- | --- | --- |
| `contract.py` | 374 | العقد: الأخطاء، `ExecutionContext`، `SandboxSpec`، `SandboxHandle`، `ExecutionRequest`، `ExecutionResult`، `SandboxProvider` |
| `selection.py` | 269 | الاختيار، التوفُّر، السقوط الصريح، `execute_in_sandbox` |
| `modal_provider.py` | 226 | مُهيّئ Modal |
| `e2b_provider.py` | 212 | مُهيّئ E2B |
| `local_provider.py` | 169 | عملية فرعية مقيَّدة على المضيف |
| `secrets.py` | 149 | حدّ الأسرار |
| `simulation_provider.py` | 127 | محاكاة معلَنة للاختبار |
| `network.py` | 122 | سياسة الشبكة |
| `__init__.py` | 60 | تصدير + استيراد كسول |

---

## 2. تجريد المزوِّد

`SandboxProvider` صنف مجرَّد يفرض خمسة أعضاء، وهي `PROVIDER_CONTRACT_METHODS`:

| العضو | العقد |
| --- | --- |
| `availability()` | `ProviderAvailability` — متاح؟ ولماذا لا؟ وأيّ اعتماد ناقص بالاسم |
| `create_sandbox(spec)` | `SandboxHandle` — يرفع `ProviderUnavailableError` قبل أن يُنشئ شيئًا إن كان غير متاح |
| `execute(handle, request)` | `ExecutionResult` — `stdout`, `stderr`, `exit_code` |
| `terminate(handle)` | إنهاء، مُتكرِّر بلا خطأ |
| `cleanup(handle)` | تحرير الموارد، مُتكرِّر بلا خطأ |

**بنية النتيجة الموحّدة** — `REQUIRED_METADATA_FIELDS`، تُفحَص في الاختبار 16:

`task_id` · `agent_id` · `execution_id` · `correlation_id` · `tool_id` · `provider` · `sandbox_id` · `execution_fidelity`

ويُضاف إليها: `stdout`, `stderr`, `exit_code`, `duration_ms`, `timed_out`, `network_policy`, `secrets_injected`, `succeeded`, وعند السقوط `fallback_from` و `fallback_reason`.

`execution_id` و `correlation_id` يُولَّدان تلقائيًّا إن لم يُمرَّرا — فلا تنفيذ مجهول النَسَب.

---

## 3. مُهيّئ Modal

- الملف **الوحيد** المسموح له باستيراد `modal`؛ يحرسه اختبار ساكن على كل ملفات `services/`.
- الاستيراد **كسول** داخل `_load_sdk()`؛ غياب الحزمة لا يُعطِّل استيراد الوحدة، بل يُترجَم إلى `UNAVAILABLE` باسم الحزمة الناقصة.
- الاعتمادات: `MODAL_TOKEN_ID` و `MODAL_TOKEN_SECRET` (`MODAL_CREDENTIAL_VARS`).
- الصورة الافتراضية: `python:3.12-slim` (`DEFAULT_MODAL_IMAGE`).
- الشبكة: سياسة `DENY` تُترجَم إلى `block_network=True` عند الإنشاء — فرض عند المزوِّد لا إعلان فقط.
- رمز الخروج: يُقرأ من `proc.wait()`؛ وإن لم يعطِ المزوِّد رمزًا فالقيمة `None` **لا صفر**.

## 4. مُهيّئ E2B

- الملف **الوحيد** المسموح له باستيراد `e2b` / `e2b_code_interpreter`؛ محروس ساكنًا كذلك.
- الاعتماد: `E2B_API_KEY` (`E2B_CREDENTIAL_VARS`).
- القالب الافتراضي: `base` (`DEFAULT_E2B_TEMPLATE`).
- يقرأ `execution.logs.stdout` و `execution.logs.stderr` (قوائم) ويضمّها نصًّا، ويشتقّ رمز الخروج من وجود `execution.error`.

---

## 5. سياسة الاعتمادات

| الحالة | النتيجة |
| --- | --- |
| كل الاعتمادات موجودة | `available=True`، الصدق `REAL` |
| اعتماد أو أكثر ناقص | `available=False`، الصدق **`UNAVAILABLE`**، والأسماء الناقصة تُذكَر |
| الحزمة غير مُثبَّتة | `available=False`، `UNAVAILABLE`، `missing_package` مُسمّى |

قواعد غير قابلة للتفاوض، ومُختبَرة:

1. **الاعتماد الناقص لا يُنتج SIMULATION.** ينتج `UNAVAILABLE`. (اختبار 5، اختبار 17)
2. **أسماء الاعتمادات تُذكَر، قيمها لا تُذكَر أبدًا** — لا في `reason` ولا في `as_dict()`. مُختبَر بحقن قيمة مميّزة والتأكّد من غيابها عن المخرَج كله.
3. **الاعتماد الناقص لا يُنشئ صندوقًا** — `create_sandbox` يرفع `ProviderUnavailableError` قبل أي اتصال.

---

## 6. الاختيار

| المتغيّر | القيم | الافتراضي |
| --- | --- | --- |
| `AMOS_SANDBOX_PROVIDER` | `local` \| `modal` \| `e2b` \| `simulation` | `local` |
| `AMOS_SANDBOX_FALLBACK_PROVIDER` | اسم مزوِّد معروف | لا شيء |
| `AMOS_SANDBOX_FALLBACK_ENABLED` | `1` \| `true` \| `yes` \| `on` | معطَّل |
| `AMOS_SANDBOX_ALLOW_SIMULATION` | `1` | معطَّل — ولا يعمل في الإنتاج بحال |

الاسم المجهول يرفع `UnknownProviderError` — لا يُبتلَع ولا يُستبدَل بالافتراضي صامتًا. الافتراضي `local` مقصود: هو نفس العملية الفرعية التي كانت تُنفِّذ `python_execute` قبل R5، فمن لم يُعِدّ شيئًا لم يتغيّر سلوكه.

## 7. السقوط (Fallback)

**لا سقوط صامت.** ثلاث بوابات متتالية:

1. **بديل مُسمّى** في `AMOS_SANDBOX_FALLBACK_PROVIDER`. غيابه ⇒ الفشل يُرفَع.
2. **تفعيل صريح** بـ `AMOS_SANDBOX_FALLBACK_ENABLED`. اسمُ بديل بلا تفعيل ⇒ `ProviderUnavailableError` نصّها يذكر المتغيّر الناقص.
3. **البديل ليس محاكاة.** `simulation` في `NON_FALLBACK_PROVIDERS`؛ اختياره بديلًا يرفع `FallbackNotPermittedError` ولو فُعِّل السقوط.

وإذا حدث السقوط المسموح، فهو **مُسجَّل في كل نتيجة**: `fallback_from` (اسم المزوِّد الذي سقط) و `fallback_reason` (سببه، بأسماء الاعتمادات الناقصة). فلا يمرّ تنفيذ على مزوِّد غير المطلوب دون أن يُقال ذلك في المخرَج نفسه.

---

## 8. الحدّ الأمني

بيئة الصندوق تُبنى **من الفراغ** (`BASE_SANDBOX_ENV`)، لا بالوراثة من المضيف ثم الحذف. ما ليس في القائمة ليس موجودًا:

```
PATH · HOME · PYTHONPATH="" · PYTHONDONTWRITEBYTECODE · LANG · AMOS_SANDBOX=1
```

`PYTHONPATH` مُفرَّغ عمدًا: وراثته تُدخِل شجرة `src/` كلها إلى الصندوق.

### 8.1 سياسة الأسرار

`FORBIDDEN_SECRET_PATTERNS` — 23 نمطًا يُرفَض إدراجه في قائمة السماح ولو طُلب صراحةً:

`DATABASE_URL` · `POSTGRES` · `PGPASSWORD` · `SUPABASE` · `JWT_SECRET` · `KING_LOGIN_SECRET` · `GITHUB_TOKEN` · `GH_TOKEN` · `GITHUB_PAT` · `MODAL_TOKEN` · `E2B_API_KEY` · `CLAUDE_API_KEY` · `ANTHROPIC` · `OPENAI` · `MINIO_SECRET` · `AWS_SECRET` · `AWS_SESSION_TOKEN` · `REDIS_PASSWORD` · `NATS_PASSWORD` · `HTTPS_PROXY` · `HTTP_PROXY` · `ALL_PROXY`

المطابقة بالاحتواء لا بالتساوي، فـ`AMOS_DATABASE_URL` محجوب مثل `DATABASE_URL`. ومتغيّرات الوسيط محجوبة قصدًا: تمريرها إلى الصندوق يمنحه اعتمادات الخزنة كلها.

الحقن **بقائمة سماح صريحة لكل أداة** (`SandboxSpec.secret_allowlist`)، تُفحَص بـ`assert_allowlist_is_safe` **قبل** الإنشاء. وكل نتيجة تحمل `secrets_injected` بأسماء ما حُقن فعلًا.

**التحقّق:** الاختبار 14 يبني بيئة معادية فيها تسعة أسرار حقيقية الشكل ثم يؤكّد غيابها؛ ثم يُنفِّذ كودًا **حقيقيًّا** داخل الصندوق يقرأ `os.environ` ويُثبت `PROBE= None` و `DB= None` و `PYPATH= ''`. هذه ملاحظة، لا استدلال.

### 8.2 سياسة الشبكة

| السياسة | المعنى |
| --- | --- |
| `DENY` | لا شبكة — **الافتراضي** |
| `ALLOWLIST` | مضيفون مُسمّون فقط؛ وقائمة فارغة تُعامَل `DENY` |
| `ALLOW_ALL` | مفتوح — يلزمه طلب صريح |

ومستوى الفرض مُعلَن لا مزعوم (`ENFORCEMENT_BY_PROVIDER`):

| المزوِّد | الفرض |
| --- | --- |
| `local` | **`DECLARED_ONLY`** — عملية فرعية على المضيف؛ السياسة مُسجَّلة ولا تُفرَض على مستوى النواة. حدٌّ معروف يُقال. |
| `modal` | `PROVIDER_ENFORCED` — `block_network` عند الإنشاء |
| `e2b` | `PROVIDER_ENFORCED` — عزل المزوِّد |
| `simulation` | `NOT_APPLICABLE` |

---

## 9. مسار التخويل — لا صندوق قبله

`AUTHORIZATION_CHAIN = ("agent", "role", "capability", "permission", "tool", "sandbox")` — الصندوق آخر الحلقات، والترتيب نفسه مُختبَر.

- `AuthorizationDecision` يبدأ `allowed=False`. الرفض هو الحالة الافتراضية.
- `authorize()` **فحص محض**: لا تستورد طبقة المزوِّدات ولا تُنشئ صندوقًا. يحرس ذلك اختبار ساكن يقرأ جسم الدالّة ويؤكّد خلوّه من `create_sandbox` و`execute_in_sandbox`.
- أداة خارج `TOOL_CATALOG` ⇒ رفض. وتعذُّر قراءة السجلّ ⇒ رفض أيضًا (`_known_tools` تُرجع `()` عند الاستثناء) — fail closed لا fail open.
- **الملاحظة الحاسمة (اختبار 13):** وكيل حقيقي يطلب أداة ليست في `allowed_tools` — يُرصَد الرفض عند `permission`، ويُؤكَّد أن `create_sandbox` **لم تُستدعَ ولا مرّة** عبر مزوِّد يُسجّل كل استدعاء.

### 9.1 نطاق التخويل — مُعلَن في كل نتيجة

`execute_tool_with_governance` تُصرّح بنطاقها في المخرَج بحقل `authorization_scope`:

| النطاق | متى | القوّة |
| --- | --- | --- |
| `AGENT_CHAIN` | `params` فيها `agent_id` | السلسلة كاملة على الهوية الكانونية |
| `ROLE_ONLY` | لا `agent_id` | kill switch + محرِّك السياسة على الدور وحده — **أضعف** |

`ROLE_ONLY` هو سلوك ما قبل R5، أُبقي للتوافق ولم يُسمَّ تخويلًا كاملًا. وفي `AGENT_CHAIN` يُمرَّر دور المُستدعي كـ`actor_role` إلى حلقة السياسة، بينما تُفحَص حلقات `agent` و`capability` و`permission` على الهوية وحدها — فالمحصّلة **تقاطع لا اتحاد**، ولا يستطيع `actor_role` توسيع منح الهوية.

**دَين معروف يُقال:** `actor_role` مُدّعىً من المُستدعي ولا يُتحقَّق من رمز جلسة في هذه الطبقة. هذا نموذج الثقة القائم قبل R5؛ R5 لم تُغيّره ولم تدّعِ إصلاحه.

---

## 10. الصدق (Fidelity)

المفردات ثلاث لا رابع لها: **REAL** · **SIMULATION** · **UNAVAILABLE**.

| المكوّن | الصدق | السبب المُعلَن |
| --- | --- | --- |
| `LocalSubprocessProvider` | `REAL` | تنفيذ فعلي بعملية فرعية |
| `ModalProvider` | `REAL` عند التوفّر، وإلّا `UNAVAILABLE` | — |
| `E2BProvider` | `REAL` عند التوفّر، وإلّا `UNAVAILABLE` | — |
| `SimulationProvider` | `SIMULATION` | مُصرَّح في كل نتيجة بـ`fidelity_reason` |
| `agent_runtime.ToolSandbox` | `SIMULATION` | مُعالِجات `_mock_*` — مُعلَن في كل استجابة |
| `agent_runtime.ToolSandbox` لأداة غير مسجَّلة | `UNAVAILABLE` | لم يُنفَّذ شيء، فلا يجوز أن تبدو محاكاةً ناجحة |

قواعد مُختبَرة:

1. **لا انحدار صامت من UNAVAILABLE إلى SIMULATION.** `simulation` ليست بديلًا مسموحًا؛ و`_execute_via_provider` تُترجم `ProviderUnavailableError` إلى `execution_fidelity="UNAVAILABLE"` بسببها، لا إلى محاكاة.
2. **المحاكاة محظورة في الإنتاج حظرًا غير قابل للتعطيل.** في `production`/`prod`/`staging` تُرجع `UNAVAILABLE` **حتى مع** `AMOS_SANDBOX_ALLOW_SIMULATION=1`.
3. **إعلان صدق غير REAL بلا سبب مرفوض في البناء نفسه** — `fidelity.declare()` ترفع `ValueError`.
4. **الفشل لا يُقنَّع نجاحًا.** فشل المزوِّد ⇒ `exit_code=None`، `succeeded=False`، والسبب في `error`. والمهلة ⇒ `timed_out=True` مع `exit_code=None`، لا صفر مُخترَع.

---

## 11. الحرس الساكن

اختبار واحد (رقم 19) يقرأ كل ملفّات `services/*.py`، بعد تجريد التعليقات وسلاسل التوثيق حتى لا يمرّ بحكم التوثيق:

| # | الحرس |
| --- | --- |
| 1 | لا `import modal` خارج `modal_provider.py` |
| 2 | لا `import e2b` خارج `e2b_provider.py` |
| 3 | `agent_runtime/` لا يلمس `providers` ولا `create_sandbox` |
| 4 | `authorize(` تسبق `execute_in_sandbox` نصًّا، وجسم `authorize` خالٍ من إنشاء الصناديق |
| 5 | كل مُهيّئ يمرّ بـ`build_sandbox_env`، ولا `dict(os.environ)` ولا `os.environ.copy()` ولا `env=os.environ` |
| 6 | `selection.py` يذكر `fallback_from` و `fallback_enabled` |
| 7 | التخويل يقرأ `TOOL_CATALOG` — لا تجاوز لسجلّ الأدوات |

---

## 12. الاختبارات — 19 اختبارًا مُركَّزًا

الملف: `federal/executive/services/tests/test_r5_multi_provider_sandbox.py` (807 أسطر).

| # | الاختبار | ما يُثبته |
| --- | --- | --- |
| 1 | عقد المزوِّد | الأربعة يحقّقون الواجهة نفسها؛ وغير المتاح يلزمه سبب |
| 2 | مُهيّئ Modal | إنشاء/تنفيذ/إنهاء عبر SDK مضاعَف؛ `block_network=True` عند DENY |
| 3 | مُهيّئ E2B | قراءة `logs.stdout`/`stderr`، رمز خروج، إنهاء |
| 4 | الاختيار | الإعداد يحكم؛ الاسم المجهول خطأ |
| 5 | اعتمادات ناقصة | `UNAVAILABLE` بأسماء الناقص، والقيم لا تُسرَّب، ولا صندوق |
| 6 | مزوِّد غير متاح | فشل صريح؛ ولا سقوط بلا إذن؛ والمحاكاة ليست بديلًا |
| 7 | سقوط صريح | يعمل، و`fallback_from`/`fallback_reason` في النتيجة |
| 8 | دورة الحياة | مقبض غريب مرفوض؛ ولا تنفيذ بعد الإنهاء |
| 9 | المهلة | `timed_out=True`, `exit_code=None`, `succeeded=False` |
| 10 | فصل المخرَج | `stdout` و `stderr` لا يختلطان |
| 11 | رمز الخروج | 7 يبقى 7؛ والمجهول `None` لا صفر |
| 12 | الإنهاء والتنظيف | مساحة العمل تُحذف فعلًا؛ والتكرار آمن |
| 13 | رفض التخويل | fail closed، و**لا صندوق أُنشئ** |
| 14 | عزل الأسرار | تسعة أسرار غائبة؛ وتنفيذ حقيقي يُثبت `None` |
| 15 | سياسة الشبكة | DENY افتراضًا؛ ALLOWLIST فارغة = DENY؛ الفرض مُعلَن |
| 16 | النَسَب | الحقول الثمانية كاملة وغير فارغة |
| 17 | مفردات الصدق | ثلاث حالات؛ والمحاكاة محظورة إنتاجًا |
| 18 | انتشار الفشل | الفشل يصل بسببه، لا يُقنَّع |
| 19 | الحرس الساكن | البنود السبعة أعلاه |

### نتائج مُلاحَظة في هذه الجولة

```
tests/test_r5_multi_provider_sandbox.py  19 passed
الحزمة الكاملة: 847 passed, 25 skipped, 1 warning in 200.59s
ruff check src/ tests/   → All checks passed
ruff check .   (الجذر)   → All checks passed
```

الانحدار المستهدَف بعد ربط `execute_tool_with_governance` بالطبقة الجديدة: `test_real_tools.py` (20) · `test_population.py` (18) · `test_phase4_tools.py` (18) · `test_r4_*` (16) · `test_r3_*` (13) — كلّها خضراء.

**لم يُلاحَظ:** CI على GitHub Actions. الادعاء هنا يقتصر على ما نُفِّذ محلّيًّا ورُئي مخرَجه.

---

## 13. مسار التحقّق الحقيقي لاحقًا

لتحويل صفَّي Modal و E2B من UNOBSERVED إلى OBSERVED، لا يلزم تعديل كود المُهيّئات — يلزم متغيّرات بيئة حقيقية:

```bash
export MODAL_TOKEN_ID=...       # من modal.com
export MODAL_TOKEN_SECRET=...
export AMOS_SANDBOX_PROVIDER=modal
python -m pip install modal

export E2B_API_KEY=...          # من e2b.dev
export AMOS_SANDBOX_PROVIDER=e2b
python -m pip install e2b-code-interpreter
```

ثم للتحقّق:

```python
from amos_federation.services.tool_registry.providers.selection import availability_report
print(availability_report())   # يجب أن يُظهر available=True و REAL
```

وبعده يُنفَّذ `execute_in_sandbox` بكود يطبع علامة مميّزة، ويُرصَد `stdout` و`exit_code` و`sandbox_id`. **وعندها فقط** يُحدَّث جدول القسم 0.

اختبار الدخان الحقيقي يجب أن يُكتَب محروسًا بـ`pytest.mark.skipif` على وجود الاعتمادات، حتى لا يتحوّل الغياب إلى فشل ولا إلى نجاح كاذب.

---

## 14. حدود معروفة تُقال ولا تُخفى

1. **Modal و E2B لم يُنفَّذ عليهما شيء.** UNOBSERVED. (القسم 0)
2. **`local` يفرض الشبكة إعلانًا لا نواةً** — `DECLARED_ONLY`. عزلٌ جزئي: عملية فرعية بمستخدم المضيف نفسه. للعزل الحقيقي يلزم Modal أو E2B.
3. **`actor_role` مُدّعىً من المُستدعي** ولا يُتحقَّق من رمز جلسة هنا. (القسم 9.1)
4. **`ROLE_ONLY` ما زال مسارًا صالحًا** لمن لا يمرّر `agent_id` — أضعف، ومُعلَن في كل نتيجة، ولم يُحذف حفاظًا على التوافق.
5. **مضاعِفات SDK ليست الخدمة.** إن غيّر Modal أو E2B واجهتيهما فلن تلتقط اختبارات العقد ذلك؛ يلتقطه اختبار الدخان الحقيقي وحده.
6. **الأدوات غير `python_execute`** ما زالت على `ToolSandbox` المحلّي في `tool_registry/sandbox.py` (SQL، الرسم، المستندات، التلخيص). ليست تنفيذ كود عامًّا، ولم تُوزَّع على مزوِّد؛ صدقها `REAL` على المضيف.
7. **دَين تنسيق سابق:** `ruff format --check` يفشل على أربعة ملفّات سابقة لـR5 (`dispatcher.py`, `royal/main.py`, `test_r3_*.py`, `test_r4_*.py`). لم تُمَسّ — خارج نطاق R5 (STEP 17). ملفّات R5 كلها مُنسَّقة.

---

## 15. جدول الصدق النهائي

| الادعاء | الحالة | الدليل |
| --- | --- | --- |
| واجهة `SandboxProvider` مُنفَّذة | ✅ REAL | `contract.py`، اختبار 1 |
| مُهيّئ Modal مكتوب خلف الواجهة | ✅ IMPLEMENTED | `modal_provider.py` |
| مُهيّئ E2B مكتوب خلف الواجهة | ✅ IMPLEMENTED | `e2b_provider.py` |
| Modal يعمل فعلًا | ⬜ **UNOBSERVED** | لا اعتمادات، لا تنفيذ |
| E2B يعمل فعلًا | ⬜ **UNOBSERVED** | لا اعتمادات، لا تنفيذ |
| تنفيذ حقيقي عبر الطبقة (local) | ✅ OBSERVED | اختبارات 9–12، 14، 16 |
| عزل الأسرار | ✅ OBSERVED | اختبار 14 — تنفيذ حقيقي يقرأ البيئة |
| لا صندوق قبل التخويل | ✅ VERIFIED | اختبار 13 + حرس ساكن |
| لا تسرُّب مزوِّد خارج مُهيّئه | ✅ VERIFIED | اختبار 19 |
| لا سقوط صامت | ✅ VERIFIED | اختبارات 6، 7 |
| المحاكاة محظورة إنتاجًا | ✅ VERIFIED | اختبار 17 |
| 19 اختبارًا خضراء | ✅ OBSERVED | مخرَج pytest، القسم 12 |
| الحزمة الكاملة خضراء | ✅ OBSERVED | 847 passed, 25 skipped |
| CI على GitHub Actions | ⬜ **UNOBSERVED** | لم يُشاهَد تشغيله |
