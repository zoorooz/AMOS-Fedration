# TRUTH_MATRIX.md — مصفوفة الحقيقة

## الهدف: قياس الفجوة بين ما تقوله وثائق الدولة وما ينفذه الكود فعليًا
## النطاق: كل أقاليم المستودع الاثني عشر
## المالك: docs/audit/ — ديوان تدقيق الدولة
## تاريخ الإنشاء: 2026-08-16
## تاريخ آخر تعديل: يُحدَّد بـ commit التوليد (المخرج حتمي بلا طابع زمني)

> **هذا الملف مُولَّد آليًا. لا تحرّره يدويًا.**
> يُعاد توليده بالأمر: `python tools/governance/truth_audit.py`

> **القاعدة الذهبية:** لا تُقبل عبارة DONE لأن الملف موجود. `DONE = Capability Proven`.

---

## 1. الحكم الإجمالي

| المقياس | القيمة |
|---|---:|
| الأقاليم المفحوصة | 12 |
| الأقاليم بحالة PROVEN | 0 |
| إجمالي المخالفات | 97 |
| ملفات بلا ترويسة هوية (المادة 009) | 26 |
| منها CRITICAL | 11 |
| منها HIGH | 63 |
| منها MEDIUM | 23 |

### توزيع المخالفات حسب النوع

| النوع | العدد | المعنى |
|---|---:|---|
| IN_MEMORY_STORE | 60 | مخزن ذاكرة يُستخدم بديلًا عن تخزين دائم |
| SILENT_FALLBACK | 26 | استثناء يُبتلع بلا تسجيل ولا رفع |
| HARDCODED_TRUTH | 10 | قيمة ثابتة تُقدَّم كحقيقة تشغيلية بدل قاعدة البيانات |
| SANDBOX_DISABLED | 1 | أداة خطرة مسجّلة بلا عزل |

---

## 2. مصفوفة الأقاليم

| الإقليم | موثّق | منفّذ | مصدر حقيقي | زائف/مخبأ | مدمج | مختبَر | مؤمَّن | مُراقَب | منشور | **مُثبَت** | الحالة |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|---|
| `core/` | ✅ | ✅ | ✅ | ⚠️ | ✅ | ✅ | ✅ | ✅ | ❌ | **❌** | `UNIT_TESTED` |
| `royal/` | ✅ | ✅ | ✅ | — | ❌ | ❌ | ✅ | ❌ | ❌ | **❌** | `IMPLEMENTED` |
| `federal/` | ✅ | ✅ | ✅ | ⚠️ | ✅ | ✅ | ✅ | ✅ | ❌ | **❌** | `UNIT_TESTED` |
| `states/` | ✅ | ❌ | ❌ | — | ❌ | ❌ | ✅ | ❌ | ❌ | **❌** | `SPECIFIED` |
| `institutions/` | ✅ | ✅ | ✅ | ⚠️ | ❌ | ❌ | ✅ | ❌ | ❌ | **❌** | `IMPLEMENTED` |
| `agents/` | ✅ | ✅ | ✅ | ⚠️ | ✅ | ❌ | ✅ | ❌ | ❌ | **❌** | `IMPLEMENTED` |
| `tools/` | ✅ | ✅ | ✅ | ⚠️ | ✅ | ✅ | ✅ | ✅ | ❌ | **❌** | `UNIT_TESTED` |
| `interfaces/` | ✅ | ❌ | ❌ | — | ❌ | ❌ | ✅ | ❌ | ❌ | **❌** | `SPECIFIED` |
| `runtime/` | ✅ | ✅ | ✅ | ⚠️ | ❌ | ❌ | ✅ | ❌ | ❌ | **❌** | `IMPLEMENTED` |
| `docs/` | ✅ | ❌ | ❌ | — | ❌ | ❌ | ✅ | ❌ | ❌ | **❌** | `SPECIFIED` |
| `ops/` | ✅ | ✅ | ✅ | — | ❌ | ❌ | ✅ | ❌ | ❌ | **❌** | `IMPLEMENTED` |
| `tests/` | ✅ | ✅ | ✅ | — | ✅ | ✅ | ✅ | ❌ | ❌ | **❌** | `INTEGRATED` |

> `⚠️` في عمود «زائف/مخبأ» يعني وجود قيم ثابتة أو مخازن ذاكرة تُستخدم بديلًا عن مصدر الحقيقة. أي إقليم يحمل `⚠️` **لا يمكن** أن يصل PROVEN.

---

## 3. الحجم الفعلي لكل إقليم

| الإقليم | md | py | yaml | أسطر كود | نوى | بلا ترويسة هوية | حالات النوى |
|---|---:|---:|---:|---:|---:|---:|---|
| `core/` | 67 | 41 | 0 | 14729 | 14 | 2 | unspecified=14 |
| `royal/` | 51 | 2 | 1 | 92 | 14 | 3 | unspecified=14 |
| `federal/` | 60 | 221 | 3 | 62471 | 7 | 2 | unspecified=7 |
| `states/` | 47 | 2 | 0 | 32 | 7 | 2 | unspecified=7 |
| `institutions/` | 19 | 2 | 0 | 89 | 6 | 2 | unspecified=6 |
| `agents/` | 601 | 4 | 283 | 549 | 11 | 3 | unspecified=11 |
| `tools/` | 41 | 23 | 2 | 6210 | 12 | 3 | unspecified=12 |
| `interfaces/` | 14 | 2 | 0 | 30 | 4 | 2 | unspecified=4 |
| `runtime/` | 20 | 2 | 0 | 71 | 7 | 2 | unspecified=7 |
| `docs/` | 90 | 2 | 0 | 47 | 7 | 3 | unspecified=7 |
| `ops/` | 38 | 2 | 0 | 93 | 12 | 1 | unspecified=12 |
| `tests/` | 14 | 45 | 0 | 15194 | 5 | 1 | unspecified=5 |

---

## 4. سجل المخالفات بالأدلة

### CRITICAL (11)

| الموقع | النوع | الخطورة | التفصيل |
|---|---|---|---|
| `agents/registry/imported_agents_data.py:15` | HARDCODED_TRUTH | CRITICAL | `AGENTS` بيانات ثابتة بديلة عن قاعدة البيانات |
| `agents/stubs/registry_check.py:18` | HARDCODED_TRUTH | CRITICAL | `AGENT_COUNT = 342` عدّاد ثابت يُقدَّم كحقيقة تشغيلية |
| `agents/stubs/registry_check.py:21` | HARDCODED_TRUTH | CRITICAL | `AGENTS_SAMPLE` بيانات ثابتة بديلة عن قاعدة البيانات |
| `core/stubs/memory_check.py:19` | HARDCODED_TRUTH | CRITICAL | `MEMORIES` بيانات ثابتة بديلة عن قاعدة البيانات |
| `core/stubs/memory_check.py:34` | HARDCODED_TRUTH | CRITICAL | `EXPERIENCES` بيانات ثابتة بديلة عن قاعدة البيانات |
| `federal/executive/services/src/amos_federation/services/governance/expansion.py:108` | HARDCODED_TRUTH | CRITICAL | `FULL_POPULATION_CATEGORIES` بيانات ثابتة بديلة عن قاعدة البيانات |
| `institutions/stubs/registry_check.py:18` | HARDCODED_TRUTH | CRITICAL | `INSTITUTIONS` بيانات ثابتة بديلة عن قاعدة البيانات |
| `runtime/stubs/task_event_check.py:31` | HARDCODED_TRUTH | CRITICAL | `EVENT_COUNT = 156` عدّاد ثابت يُقدَّم كحقيقة تشغيلية |
| `runtime/stubs/task_event_check.py:34` | HARDCODED_TRUTH | CRITICAL | `EVENTS_SAMPLE` بيانات ثابتة بديلة عن قاعدة البيانات |
| `tools/registry/tool-index.yaml:49` | SANDBOX_DISABLED | CRITICAL | أداة مسجّلة بلا عزل (sandbox=false) |
| `tools/stubs/registry_check.py:18` | HARDCODED_TRUTH | CRITICAL | `TOOLS` بيانات ثابتة بديلة عن قاعدة البيانات |

### HIGH (63)

| الموقع | النوع | الخطورة | التفصيل |
|---|---|---|---|
| `federal/executive/services/src/amos_federation/common/events.py:20` | SILENT_FALLBACK | HIGH | استثناء يُبتلع بلا تسجيل ولا رفع — يخفي فشل مصدر الحقيقة |
| `federal/executive/services/src/amos_federation/services/api_gateway/store.py:14` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryTaskStore` يُستخدم كمصدر حقيقة |
| `federal/executive/services/src/amos_federation/services/api_gateway/store.py:102` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryTaskStore` يُستخدم كمصدر حقيقة |
| `federal/executive/services/src/amos_federation/services/critic/store.py:32` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryCriticStore` يُستخدم كمصدر حقيقة |
| `federal/executive/services/src/amos_federation/services/evaluation/benchmark.py:170` | SILENT_FALLBACK | HIGH | استثناء يُبتلع بلا تسجيل ولا رفع — يخفي فشل مصدر الحقيقة |
| `federal/executive/services/src/amos_federation/services/evaluation/store.py:33` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryExperienceStore` يُستخدم كمصدر حقيقة |
| `federal/executive/services/src/amos_federation/services/governance/federation.py:250` | SILENT_FALLBACK | HIGH | استثناء يُبتلع بلا تسجيل ولا رفع — يخفي فشل مصدر الحقيقة |
| `federal/executive/services/src/amos_federation/services/memory_service/store.py:50` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryVectorStore` يُستخدم كمصدر حقيقة |
| `federal/executive/services/src/amos_federation/services/model_gateway/main.py:29` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryShadowStore` يُستخدم كمصدر حقيقة |
| `federal/executive/services/src/amos_federation/services/model_gateway/main.py:47` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryShadowStore` يُستخدم كمصدر حقيقة |
| `federal/executive/services/src/amos_federation/services/model_gateway/shadow.py:28` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryShadowStore` يُستخدم كمصدر حقيقة |
| `federal/executive/services/src/amos_federation/services/model_gateway/shadow.py:142` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryShadowStore` يُستخدم كمصدر حقيقة |
| `federal/executive/services/src/amos_federation/services/tool_registry/store.py:31` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryToolStore` يُستخدم كمصدر حقيقة |
| `federal/executive/services/src/amos_federation/services/training/data_pipeline.py:31` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryDataPipeline` يُستخدم كمصدر حقيقة |
| `federal/executive/services/src/amos_federation/services/training/main.py:22` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryDataPipeline` يُستخدم كمصدر حقيقة |
| `federal/executive/services/src/amos_federation/services/training/main.py:23` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryModelRegistry` يُستخدم كمصدر حقيقة |
| `federal/executive/services/src/amos_federation/services/training/main.py:36` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryDataPipeline` يُستخدم كمصدر حقيقة |
| `federal/executive/services/src/amos_federation/services/training/main.py:37` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryModelRegistry` يُستخدم كمصدر حقيقة |
| `federal/executive/services/src/amos_federation/services/training/model_registry.py:30` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryModelRegistry` يُستخدم كمصدر حقيقة |
| `federal/executive/services/tests/test_common_branches.py:40` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryTaskStore` يُستخدم كمصدر حقيقة |
| `federal/executive/services/tests/test_common_branches.py:263` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryTaskStore` يُستخدم كمصدر حقيقة |
| `federal/executive/services/tests/test_edge_branches.py:13` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryShadowStore` يُستخدم كمصدر حقيقة |
| `federal/executive/services/tests/test_edge_branches.py:17` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryModelRegistry` يُستخدم كمصدر حقيقة |
| `federal/executive/services/tests/test_edge_branches.py:22` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryShadowStore` يُستخدم كمصدر حقيقة |
| `federal/executive/services/tests/test_edge_branches.py:43` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryModelRegistry` يُستخدم كمصدر حقيقة |
| `federal/executive/services/tests/test_edge_branches.py:47` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryModelRegistry` يُستخدم كمصدر حقيقة |
| `federal/executive/services/tests/test_edge_branches.py:55` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryModelRegistry` يُستخدم كمصدر حقيقة |
| `federal/executive/services/tests/test_inmemory_stores.py:12` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryCriticStore` يُستخدم كمصدر حقيقة |
| `federal/executive/services/tests/test_inmemory_stores.py:13` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryExperienceStore` يُستخدم كمصدر حقيقة |
| `federal/executive/services/tests/test_inmemory_stores.py:15` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryVectorStore` يُستخدم كمصدر حقيقة |
| `federal/executive/services/tests/test_inmemory_stores.py:25` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryToolStore` يُستخدم كمصدر حقيقة |
| `federal/executive/services/tests/test_inmemory_stores.py:33` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryCriticStore` يُستخدم كمصدر حقيقة |
| `federal/executive/services/tests/test_inmemory_stores.py:41` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryCriticStore` يُستخدم كمصدر حقيقة |
| `federal/executive/services/tests/test_inmemory_stores.py:46` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryCriticStore` يُستخدم كمصدر حقيقة |
| `federal/executive/services/tests/test_inmemory_stores.py:52` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryCriticStore` يُستخدم كمصدر حقيقة |
| `federal/executive/services/tests/test_inmemory_stores.py:58` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryCriticStore` يُستخدم كمصدر حقيقة |
| `federal/executive/services/tests/test_inmemory_stores.py:64` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryCriticStore` يُستخدم كمصدر حقيقة |
| `federal/executive/services/tests/test_inmemory_stores.py:71` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryCriticStore` يُستخدم كمصدر حقيقة |
| `federal/executive/services/tests/test_inmemory_stores.py:77` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryCriticStore` يُستخدم كمصدر حقيقة |
| `federal/executive/services/tests/test_inmemory_stores.py:83` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryCriticStore` يُستخدم كمصدر حقيقة |
| `federal/executive/services/tests/test_inmemory_stores.py:97` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryExperienceStore` يُستخدم كمصدر حقيقة |
| `federal/executive/services/tests/test_inmemory_stores.py:104` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryExperienceStore` يُستخدم كمصدر حقيقة |
| `federal/executive/services/tests/test_inmemory_stores.py:110` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryExperienceStore` يُستخدم كمصدر حقيقة |
| `federal/executive/services/tests/test_inmemory_stores.py:116` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryExperienceStore` يُستخدم كمصدر حقيقة |
| `federal/executive/services/tests/test_inmemory_stores.py:122` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryExperienceStore` يُستخدم كمصدر حقيقة |
| `federal/executive/services/tests/test_inmemory_stores.py:128` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryExperienceStore` يُستخدم كمصدر حقيقة |
| `federal/executive/services/tests/test_inmemory_stores.py:134` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryExperienceStore` يُستخدم كمصدر حقيقة |
| `federal/executive/services/tests/test_inmemory_stores.py:141` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryExperienceStore` يُستخدم كمصدر حقيقة |
| `federal/executive/services/tests/test_inmemory_stores.py:165` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryVectorStore` يُستخدم كمصدر حقيقة |
| `federal/executive/services/tests/test_inmemory_stores.py:171` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryVectorStore` يُستخدم كمصدر حقيقة |
| `federal/executive/services/tests/test_inmemory_stores.py:179` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryVectorStore` يُستخدم كمصدر حقيقة |
| `federal/executive/services/tests/test_inmemory_stores.py:186` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryVectorStore` يُستخدم كمصدر حقيقة |
| `federal/executive/services/tests/test_inmemory_stores.py:196` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryVectorStore` يُستخدم كمصدر حقيقة |
| `federal/executive/services/tests/test_inmemory_stores.py:237` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryToolStore` يُستخدم كمصدر حقيقة |
| `federal/executive/services/tests/test_inmemory_stores.py:244` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryToolStore` يُستخدم كمصدر حقيقة |
| `federal/executive/services/tests/test_inmemory_stores.py:250` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryToolStore` يُستخدم كمصدر حقيقة |
| `federal/executive/services/tests/test_inmemory_stores.py:264` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryToolStore` يُستخدم كمصدر حقيقة |
| `federal/executive/services/tests/test_training.py:12` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryDataPipeline` يُستخدم كمصدر حقيقة |
| `federal/executive/services/tests/test_training.py:68` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryDataPipeline` يُستخدم كمصدر حقيقة |
| `federal/executive/services/tests/test_training.py:77` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryDataPipeline` يُستخدم كمصدر حقيقة |
| `federal/executive/services/tests/test_training.py:86` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryDataPipeline` يُستخدم كمصدر حقيقة |
| `federal/executive/services/tests/test_training.py:98` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryDataPipeline` يُستخدم كمصدر حقيقة |
| `federal/executive/services/tests/test_training.py:110` | IN_MEMORY_STORE | HIGH | مخزن ذاكرة `InMemoryDataPipeline` يُستخدم كمصدر حقيقة |

### MEDIUM (23)

| الموقع | النوع | الخطورة | التفصيل |
|---|---|---|---|
| `federal/executive/services/src/amos_federation/common/events.py:64` | SILENT_FALLBACK | MEDIUM | استثناء يُبتلع بلا تسجيل ولا رفع — يخفي فشل مصدر الحقيقة |
| `federal/executive/services/src/amos_federation/common/events.py:79` | SILENT_FALLBACK | MEDIUM | استثناء يُبتلع بلا تسجيل ولا رفع — يخفي فشل مصدر الحقيقة |
| `federal/executive/services/src/amos_federation/common/persistent.py:66` | SILENT_FALLBACK | MEDIUM | استثناء يُبتلع بلا تسجيل ولا رفع — يخفي فشل مصدر الحقيقة |
| `federal/executive/services/src/amos_federation/common/persistent.py:285` | SILENT_FALLBACK | MEDIUM | استثناء يُبتلع بلا تسجيل ولا رفع — يخفي فشل مصدر الحقيقة |
| `federal/executive/services/src/amos_federation/common/persistent.py:536` | SILENT_FALLBACK | MEDIUM | استثناء يُبتلع بلا تسجيل ولا رفع — يخفي فشل مصدر الحقيقة |
| `federal/executive/services/src/amos_federation/common/persistent.py:649` | SILENT_FALLBACK | MEDIUM | استثناء يُبتلع بلا تسجيل ولا رفع — يخفي فشل مصدر الحقيقة |
| `federal/executive/services/src/amos_federation/common/persistent.py:660` | SILENT_FALLBACK | MEDIUM | استثناء يُبتلع بلا تسجيل ولا رفع — يخفي فشل مصدر الحقيقة |
| `federal/executive/services/src/amos_federation/common/service.py:25` | SILENT_FALLBACK | MEDIUM | استثناء يُبتلع بلا تسجيل ولا رفع — يخفي فشل مصدر الحقيقة |
| `federal/executive/services/src/amos_federation/common/tracing.py:22` | SILENT_FALLBACK | MEDIUM | استثناء يُبتلع بلا تسجيل ولا رفع — يخفي فشل مصدر الحقيقة |
| `federal/executive/services/src/amos_federation/common/tracing.py:36` | SILENT_FALLBACK | MEDIUM | استثناء يُبتلع بلا تسجيل ولا رفع — يخفي فشل مصدر الحقيقة |
| `federal/executive/services/src/amos_federation/services/governance/expansion.py:952` | SILENT_FALLBACK | MEDIUM | استثناء يُبتلع بلا تسجيل ولا رفع — يخفي فشل مصدر الحقيقة |
| `federal/executive/services/src/amos_federation/services/governance/federation.py:298` | SILENT_FALLBACK | MEDIUM | استثناء يُبتلع بلا تسجيل ولا رفع — يخفي فشل مصدر الحقيقة |
| `federal/executive/services/src/amos_federation/services/governance/policy_engine.py:46` | SILENT_FALLBACK | MEDIUM | استثناء يُبتلع بلا تسجيل ولا رفع — يخفي فشل مصدر الحقيقة |
| `federal/executive/services/src/amos_federation/services/governance/policy_engine.py:51` | SILENT_FALLBACK | MEDIUM | استثناء يُبتلع بلا تسجيل ولا رفع — يخفي فشل مصدر الحقيقة |
| `federal/executive/services/src/amos_federation/services/governance/policy_engine.py:56` | SILENT_FALLBACK | MEDIUM | استثناء يُبتلع بلا تسجيل ولا رفع — يخفي فشل مصدر الحقيقة |
| `federal/executive/services/src/amos_federation/services/governance/policy_engine.py:61` | SILENT_FALLBACK | MEDIUM | استثناء يُبتلع بلا تسجيل ولا رفع — يخفي فشل مصدر الحقيقة |
| `federal/executive/services/src/amos_federation/services/tool_registry/store.py:58` | SILENT_FALLBACK | MEDIUM | استثناء يُبتلع بلا تسجيل ولا رفع — يخفي فشل مصدر الحقيقة |
| `federal/executive/services/tests/test_2a_sovereign_runtime_integration.py:406` | SILENT_FALLBACK | MEDIUM | استثناء يُبتلع بلا تسجيل ولا رفع — يخفي فشل مصدر الحقيقة |
| `federal/executive/services/tests/test_2b_state_registry_sovereign.py:401` | SILENT_FALLBACK | MEDIUM | استثناء يُبتلع بلا تسجيل ولا رفع — يخفي فشل مصدر الحقيقة |
| `tools/audit/sovereign_write_inventory.py:374` | SILENT_FALLBACK | MEDIUM | استثناء يُبتلع بلا تسجيل ولا رفع — يخفي فشل مصدر الحقيقة |
| `tools/governance/truth_audit.py:349` | SILENT_FALLBACK | MEDIUM | استثناء يُبتلع بلا تسجيل ولا رفع — يخفي فشل مصدر الحقيقة |
| `tools/governance/truth_audit.py:377` | SILENT_FALLBACK | MEDIUM | استثناء يُبتلع بلا تسجيل ولا رفع — يخفي فشل مصدر الحقيقة |
| `tools/governance/truth_audit.py:551` | SILENT_FALLBACK | MEDIUM | استثناء يُبتلع بلا تسجيل ولا رفع — يخفي فشل مصدر الحقيقة |

### إعلاناتُ «ليست سرًّا» الصريحة (7)

> قيمٌ اختباريةٌ مُختَرَعةٌ أُعلن في المصدر صراحةً أنها ليست أسرارًا بالعلامة `truth-audit: not-a-secret`. تُنشَر هنا ولا تُخفى.

| الموقع | المفتاح |
|---|---|
| `federal/executive/services/tests/test_r5_multi_provider_sandbox.py:560` | `CLAUDE_API_KEY` |
| `federal/executive/services/tests/test_r5_multi_provider_sandbox.py:560` | `E2B_API_KEY` |
| `federal/executive/services/tests/test_r5_multi_provider_sandbox.py:560` | `GITHUB_TOKEN` |
| `federal/executive/services/tests/test_r5_multi_provider_sandbox.py:560` | `JWT_SECRET` |
| `federal/executive/services/tests/test_r5_multi_provider_sandbox.py:560` | `KING_LOGIN_SECRET` |
| `federal/executive/services/tests/test_r5_multi_provider_sandbox.py:560` | `MODAL_TOKEN_SECRET` |
| `tests/sovereignty/test_outbox.py:1083` | `api_key` |

---

## 5. تصنيفاتُ الجولات المُعلَنة

> المصدر: [`round_classifications.json`](round_classifications.json) — يُحرَّر يدويًا ويُقرأ آليًا. `REAL` = مُلاحَظٌ فعليًا · `PARTIAL` = جزئيٌّ مُعلَن · `UNRESOLVED` = دَينٌ مفتوح · `UNAVAILABLE` = غيرُ متوفّر · `UNOBSERVED` = لم يُلاحَظ.

### R8 — تكاملُ الدولة الاتحادية (federal_state)

> المرجع: `docs/audit/R8_FEDERAL_STATE_INTEGRATION.md §19`

| المجال | التصنيف | الدليل |
|---|---|---|
| سجلّ الحكومات وهويتُها ودورةُ حياتها | `REAL` | جداولٌ وقيودٌ مُلاحَظةٌ على PostgreSQL 18.4 محليًّا و17.6 على Supabase + 28 اختبارًا |
| انتماءُ المؤسّسة لحكومةٍ واحدة | `REAL` | قيدُ `uq_…_institution` مُلاحَظٌ في القاعدة + اختبار |
| حدودُ النطاق الأربعة | `REAL` | 28 اختبارًا في `tests/test_r8_federal_state_integration.py`، منها الحدودُ الأربعة صريحةً |
| التفويضُ الصريح النافذ | `REAL` | منحٌ/نقضٌ/انتهاءٌ/خصوصيةُ عملية مُختبَرة + قيودُ القاعدة |
| نطاقُ الخدمة والقضية | `REAL` | فرادةٌ وقيودُ اتساقٍ مُلاحَظةٌ على PostgreSQL |
| إثباتُ مصدر القضية | `PARTIAL` | بقصد: `PROVEN` يلزمه سلسلةُ إثباتٍ كاملة، والناقصُ يُعلَن ناقصًا |
| التنفيذُ عبر النواة | `REAL` | مهمّةٌ في `tasks` مُلاحَظة، والمرفوضُ بلا مهمّة |
| الخزانةُ بنطاقٍ وسقف | `REAL` | حقنًا لا إعادةَ بناءٍ: اختبارٌ عمليٌّ + حَظرٌ ساكنٌ للنسخ |
| صفوفُ ما قبل R8 غيرِ المرتبطة بحكومة | `UNRESOLVED` | مُعلَنٌ: لا ترحيلَ بياناتٍ مُختَرعًا |
| سلسلةُ الترحيلات كاملةً | `UNAVAILABLE` | تصنيفُ R8 كما أُعلن حينَه: عطلُ `004` كان قائمًا. أُصلح لاحقًا في R9 — انظر أدناه |
| GitHub CI | `UNOBSERVED` | لم تُشاهَد جولةٌ فعلية |
| Modal / E2B | `UNOBSERVED` | لم يُلاحَظ تشغيلٌ حقيقيّ |
| النفاذُ القانونيُّ خارج النظام | `UNAVAILABLE` | لا يُدَّعى |

### R9 — إصلاحُ عطل 004 وفشلِ matplotlib وإعادةُ الانحدار

> المرجع: `docs/audit/ACTIVE_EXECUTION_STATE.md §22`

| المجال | التصنيف | الدليل |
|---|---|---|
| سلسلةُ الترحيلات 001→010 على قاعدةٍ نظيفة | `REAL` | مُلاحَظ: تطبيقُ الملفات العشرة بالترتيب على قاعدةٍ فارغة `amos_chain` على PostgreSQL 18.4 محليًّا، 10/10 OK بلا خطأ، بعد إعادةِ كتابة `migrations/004_unify_tasks_schema.sql` |
| سببُ عطل 004 | `REAL` | مُلاحَظ: `001_init.sql` يمنح المفاتيحَ الأولية نوعَ UUID مع عمودِ هويةٍ منطقيٍّ VARCHAR منفصل، بينما نماذجُ ORM في `common/database.py` تستخدم `id VARCHAR` وحدَه، فتفشل مفاتيحُ الإحالة بـ «incompatible types: uuid and character varying» |
| توافقُ القاعدة المبنيّة بالسلسلة مع نماذج ORM | `REAL` | مُلاحَظ: تحقُّقُ تطابقِ الأعمدة 7/7 نماذج (agents, tasks, tools, experiences, memories, reviews, audit_entries) وكتابةٌ وقراءةٌ فعليةٌ عبر ORM على القاعدة المبنيّة بالسلسلة بلا `create_all` |
| قابليةُ إعادة تشغيل 004→010 | `REAL` | مُلاحَظ: إعادةُ تطبيق 004 حتى 010 على القاعدة نفسِها نجحت (idempotent) |
| قابليةُ إعادة تشغيل 001 و002 | `PARTIAL` | مُلاحَظ: `001` و`002` تفشلان عند إعادة التشغيل بعد التوحيد («column "agent_id" does not exist») لأنهما نصّا تهيئةٍ ابتدائيّان غيرُ متكافئَي التطبيق. يُعلَن ولا يُخفى |
| السلسلةُ على PostgreSQL خارجيّ (Supabase) | `UNOBSERVED` | قاعدةُ Supabase التجريبية مبنيّةٌ أصلًا بشكل ORM وليست فارغة، فلم تُطبَّق السلسلةُ عليها من الصفر. قيودُ 010 وحدَها هي المُلاحَظةُ هناك (PostgreSQL 17.6) |
| اعتمادُ matplotlib لأداة chart_generate | `REAL` | مُصلَحٌ في المصدر: أُضيفت `matplotlib>=3.9.0` إلى `dependencies` في `federal/executive/services/pyproject.toml`؛ كانت مُستخدَمةً في `tool_registry/sandbox.py` وغيرَ مُعلَنة |
| الانحدارُ الكامل للاختبارات | `REAL` | مُلاحَظ: 1040 ناجحًا، 25 مُتخطًّى، 0 فاشل (‏320 ثانية) على Python 3.14 بعد حذف `amos_federation_test.db`؛ خطُّ الأساس السابق كان 1038 ناجحًا و2 فاشلَين |
| ترحيلُ بيانات صفوف ما قبل R8 | `UNRESOLVED` | لم يُنفَّذ في R9 ولا يُدَّعى |
| GitHub CI | `UNOBSERVED` | لم تُشاهَد جولةٌ فعلية في R9 كذلك |
| بوابةُ عدم التراجع (truth_audit --ratchet) | `REAL` | مُلاحَظ: كانت البوابةُ تفشل عند إعادة التوليد (100 ← 118) لأن خطَّ الأساس لم يُحدَّث منذ f1e69eb. صارت 97 مخالفةً بعد الإصلاح في المصدر، وشُدَّ خطُّ الأساس إلى 97 |
| سبعُ مخالفات HARDCODED_SECRET المُكتشَفة | `REAL` | مُلاحَظٌ أنها إنذاراتٌ كاذبة: ستٌّ منها قيمٌ مُختَرَعةٌ في اختبارٍ سلبيٍّ يُثبت أن الصندوق لا يُورّث أسرارَ المضيف، وواحدةٌ عضوُ تعدادٍ يُسمّي نفسَه `TOKEN_VERIFIED`. أُصلح المُكتشِف: عضوُ التعداد لا يُعَدُّ سرًّا، والقيمُ الاختبارية تحتاج إعلانًا صريحًا بالعلامة `truth-audit: not-a-secret` ويُنشَر كلُّ إعلانٍ في المصفوفة |
| أحدَ عشرَ معالِجَ استثناءٍ صامتًا | `REAL` | مُصلَحٌ في المصدر: أُضيف `logger.warning` صريحٌ في 13 موضعًا (subsystem_boundary, federal_state/delegation, governance/security, national_registry/resolver, tool_registry/authorized_execution ×2, e2b_provider, modal_provider ×2, network, selection, sandbox ×2). SILENT_FALLBACK: 40 ← 26 |
| أثرُ الإصلاحات على الاختبارات | `REAL` | مُلاحَظ: الانحدارُ الكامل بعد الإصلاحات 1040 ناجحًا · 25 مُتخطًّى · 0 فاشل (325 ثانية) |

---

## 6. ماذا يعني هذا

كل صف بحالة أقل من `PROVEN` هو **دَين تنفيذي** مفتوح. خطة Phase E مرتّبة لسداد هذا الدين إقليمًا إقليمًا.

راجع [`PHASE_E_ROADMAP.md`](PHASE_E_ROADMAP.md) لترتيب السداد، و[`DEFINITION_OF_DONE.md`](DEFINITION_OF_DONE.md) لمعيار الإقفال.
