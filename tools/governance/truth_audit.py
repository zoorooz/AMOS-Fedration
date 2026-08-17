#!/usr/bin/env python3
"""
محرك تدقيق الحقيقة — Truth Audit Engine (E0)
الهدف: قياس الفجوة بين ما تقوله وثائق الدولة وما ينفذه الكود فعليًا، وإنتاج TRUTH_MATRIX بأدلة من الكود نفسه.
النطاق: المستودع كامل — كل مجال، كل وحدة بايثون، كل سجل، كل اختبار.
المالك: tools/governance/
تاريخ الإنشاء: 2026-08-16
تاريخ آخر تعديل: 2026-08-16

المبدأ: لا تُقبل عبارة DONE بلا دليل تنفيذي. هذا المحرك يستخرج الدليل آليًا.

Usage:
    python tools/governance/truth_audit.py [REPO_ROOT] [--strict] [--ratchet] [--set-baseline]

الأوضاع:
    (بلا علم)      توليد المصفوفة فقط
    --strict       يفشل عند وجود أي مخالفة CRITICAL (بوابة الإقفال النهائية)
    --ratchet      بوابة عدم التراجع: يفشل إذا ارتفع عدد المخالفات عن خط الأساس
    --set-baseline يثبّت خط أساس جديد (يُستخدم فقط بعد خفض المخالفات)

المخرجات:
    docs/audit/TRUTH_MATRIX.md    — المصفوفة البشرية
    docs/audit/truth_matrix.json  — المصفوفة الآلية (لبوابات CI)
    docs/audit/truth_baseline.json — خط الأساس لبوابة عدم التراجع

رموز الحالة لكل مكوّن:
    DOCUMENTED     — يوجد توثيق (README / NUCLEUS / index)
    IMPLEMENTED    — يوجد كود تنفيذي حقيقي (وليس ملفات md فقط)
    REAL_SOURCE    — يصل إلى مصدر حقيقة حقيقي (قاعدة بيانات / API / نظام ملفات)
    FAKE_OR_CACHED — يعتمد على قيم ثابتة أو مخازن ذاكرة كبديل عن مصدر الحقيقة
    INTEGRATED     — مربوط بمجالات أخرى (استيراد متبادل / نداءات خدمة)
    TESTED         — تغطيه اختبارات فعلية تشير إليه بالاسم
    SECURED        — لا يحتوي أسرارًا ثابتة ولا صلاحيات مفتوحة
    OBSERVED       — يصدر سجلات/مقاييس/أحداث
    DEPLOYED       — مذكور في بنية نشر (Docker / CI / compose / k8s)
    PROVEN         — كل ما سبق متحقق ولا يوجد FAKE_OR_CACHED
"""

from __future__ import annotations

import ast
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# إعدادات المسح
# ---------------------------------------------------------------------------

SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".ruff_cache",
             ".pytest_cache", ".mypy_cache", "dist", "build", ".egg-info"}

# المجالات الرئيسية للدولة (الأقاليم الاثنا عشر)
DOMAINS = ["core", "royal", "federal", "states", "institutions", "agents",
           "tools", "interfaces", "runtime", "docs", "ops", "tests"]

# ---------------------------------------------------------------------------
# أنماط الكشف — كل نمط هو دليل، وليس رأيًا
# ---------------------------------------------------------------------------

RE_REAL_SOURCE = re.compile(
    r"\b(sqlalchemy|create_engine|async_sessionmaker|psycopg|asyncpg|supabase|"
    r"httpx\.|requests\.(get|post|put|delete)|redis\.|boto3|minio|"
    r"open\s*\(|Path\([^)]*\)\.(read_text|write_text|read_bytes))",
    re.IGNORECASE,
)

RE_IN_MEMORY = re.compile(r"\bInMemory[A-Za-z_]*\b")

RE_FALLBACK_WORD = re.compile(r"\bfallback\b", re.IGNORECASE)

RE_SECRET_ASSIGN = re.compile(
    r"""^\s*(?!#)[A-Za-z_][A-Za-z0-9_]*\s*[:=]\s*['"][^'"]{6,}['"]""",
)
SECRET_NAME = re.compile(
    r"(password|passwd|secret|token|api_key|apikey|private_key|access_key|"
    r"jwt_secret|credential)",
    re.IGNORECASE,
)
# أسماء تحتوي كلمة سر لكنها ليست أسرارًا (وصف وليس قيمة)
SECRET_NAME_EXEMPT = re.compile(
    r"(_type$|_name$|_id$|_url$|_header$|_field$|_env$|_var$|_path$|_kind$|"
    r"_label$|_scheme$|_algorithm$|_alg$|_prefix$|_key_name$|^SECRET_NAME)",
    re.IGNORECASE,
)
# ملفات معفاة من فحص الأسرار (أدوات الفحص نفسها تذكر أسماء الأنماط)
SECRET_SCAN_EXEMPT_FILES = {"truth_audit.py", "check_repository_identity.py"}
# إعلانٌ صريحٌ في المصدر بأن القيمة ليست سرًّا (لقيم اختبارٍ سلبيّةٍ مُختَرَعة).
# لا يُسكِت الفحصَ بصمت: كلُّ إعلانٍ يُعَدُّ ويُنشَر في مصفوفة الحقيقة.
SECRET_DECLARATION_MARKER = "truth-audit: not-a-secret"
SECRET_SAFE_VALUE = re.compile(
    r"^(os\.|env|getenv|\$\{|<|change[_-]?me$|xxx|placeholder|example|\*+$)",
    re.IGNORECASE,
)

RE_OBSERVED = re.compile(
    r"\b(logging\.|logger\.|structlog|log\.(info|warning|error|debug)|"
    r"Counter\(|Histogram\(|Gauge\(|prometheus|emit_event|record_metric|"
    r"audit_log|OpenTelemetry|tracer)",
    re.IGNORECASE,
)

RE_API = re.compile(r"@(app|router)\.(get|post|put|patch|delete)\(")

RE_SANDBOX_FALSE = re.compile(r"sandbox(?:_required|_enabled)?\s*:\s*(false|no|off)\b",
                              re.IGNORECASE)

RE_NUCLEUS_STATUS = re.compile(
    r"(?:الحالة|status)\s*[:：]\s*\**\s*(stub|prototype|active|planned)",
    re.IGNORECASE,
)

# أسماء ثوابت تدّعي أنها حقيقة تشغيلية
TRUTH_CONSTANT_HINT = re.compile(
    r"(COUNT|TOTAL|MEMORIES|EXPERIENCES|AGENTS|EVENTS|TOOLS|INSTITUTIONS|"
    r"REGISTRY|POPULATION|ROWS|RECORDS)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# نماذج البيانات
# ---------------------------------------------------------------------------

@dataclass
class Finding:
    """دليل مفرد مستخرج من الكود."""
    kind: str          # نوع المخالفة/الدليل
    path: str
    line: int
    detail: str
    severity: str      # CRITICAL / HIGH / MEDIUM / INFO

    def as_row(self) -> str:
        return f"| `{self.path}:{self.line}` | {self.kind} | {self.severity} | {self.detail} |"


@dataclass
class DomainReport:
    """تقرير مجال واحد من أقاليم الدولة."""
    domain: str
    md_files: int = 0
    py_files: int = 0
    yaml_files: int = 0
    code_lines: int = 0
    nucleus_count: int = 0
    nucleus_status: dict = field(default_factory=dict)
    has_readme: bool = False
    real_source_hits: int = 0
    fake_hits: int = 0
    in_memory_hits: int = 0
    secret_hits: int = 0
    observed_hits: int = 0
    api_routes: int = 0
    test_refs: int = 0
    identity_violations: int = 0
    deployed: bool = False
    findings: list = field(default_factory=list)

    # -- تقييم الأعمدة ------------------------------------------------------
    @property
    def documented(self) -> bool:
        return self.has_readme and self.md_files > 0

    @property
    def implemented(self) -> bool:
        return self.py_files > 0 and self.code_lines >= 50

    @property
    def real_source(self) -> bool:
        return self.implemented and self.real_source_hits > 0

    @property
    def fake_or_cached(self) -> bool:
        return self.fake_hits > 0 or self.in_memory_hits > 0

    @property
    def integrated(self) -> bool:
        return self.api_routes > 0 or self.real_source_hits >= 3

    @property
    def tested(self) -> bool:
        return self.test_refs > 0

    @property
    def secured(self) -> bool:
        return self.secret_hits == 0

    @property
    def observed(self) -> bool:
        return self.observed_hits > 0

    @property
    def proven(self) -> bool:
        return all([self.documented, self.implemented, self.real_source,
                    not self.fake_or_cached, self.integrated, self.tested,
                    self.secured, self.observed, self.deployed])

    def maturity(self) -> str:
        """الحالة وفق نظام الحالات الجديد (DESIGNED → PROVEN)."""
        if self.proven:
            return "PROVEN"
        if self.deployed and self.tested and self.secured:
            return "DEPLOYED"
        if self.tested and self.implemented and not self.fake_or_cached:
            return "INTEGRATED"
        if self.tested and self.implemented:
            return "UNIT_TESTED"
        if self.implemented:
            return "IMPLEMENTED"
        if self.documented and (self.md_files > 3):
            return "SPECIFIED"
        return "DESIGNED"

    def mark(self, value: bool) -> str:
        return "✅" if value else "❌"


# ---------------------------------------------------------------------------
# المحرك
# ---------------------------------------------------------------------------

class TruthAudit:
    def __init__(self, root: Path):
        self.root = root
        self.reports: dict[str, DomainReport] = {d: DomainReport(d) for d in DOMAINS}
        self.global_findings: list[Finding] = []
        # إعلاناتُ «ليست سرًّا» الصريحةُ في المصدر — تُنشَر ولا تُخفى
        self._declared_exemptions: list[tuple[str, int, str]] = []
        self.test_corpus = ""
        self.deploy_corpus = ""

    # -- أدوات مساعدة -------------------------------------------------------
    def _iter_files(self):
        # الترتيب مُحتَّم قصدًا: `rglob` يُسلِّم بترتيب نظام الملفات، فيختلف بين
        # جهازٍ وآخر. وبوابة CI تقارن المصفوفة المدفوعة بالمولَّدة حرفًا بحرف،
        # فترتيبٌ غير محتَّم يعني بوابةً تسقط لاختلاف السطور لا لاختلاف الحقيقة.
        for p in sorted(self.root.rglob("*")):
            if not p.is_file():
                continue
            if any(part in SKIP_DIRS or part.endswith(".egg-info") for part in p.parts):
                continue
            yield p

    def _domain_of(self, p: Path) -> str | None:
        try:
            rel = p.relative_to(self.root)
        except ValueError:
            return None
        return rel.parts[0] if rel.parts and rel.parts[0] in DOMAINS else None

    def _rel(self, p: Path) -> str:
        return str(p.relative_to(self.root))

    # -- المرحلة 1: بناء مجموعة الاختبارات والنشر ---------------------------
    def build_corpora(self):
        test_chunks, deploy_chunks = [], []
        for p in self._iter_files():
            rel = self._rel(p)
            low = rel.lower()
            if p.suffix == ".py" and ("test" in low or low.startswith("tests/")):
                test_chunks.append(self._read(p))
            if (p.name in {"Dockerfile", "docker-compose.yml", "docker-compose.yaml",
                           "Makefile", "pyproject.toml"}
                    or "/.github/" in "/" + low
                    or low.startswith(".github/")
                    or "deploy" in low or "k8s" in low or "helm" in low):
                deploy_chunks.append(rel + "\n" + self._read(p))
        self.test_corpus = "\n".join(test_chunks)
        self.deploy_corpus = "\n".join(deploy_chunks)

    @staticmethod
    def _read(p: Path) -> str:
        try:
            return p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return ""

    # -- المرحلة 2: مسح الملفات --------------------------------------------
    def scan(self):
        self.build_corpora()
        for p in self._iter_files():
            dom = self._domain_of(p)
            if dom is None:
                continue
            rep = self.reports[dom]
            rel = self._rel(p)
            suffix = p.suffix.lower()

            if suffix in {".md", ".py", ".yaml", ".yml", ".rego", ".sql"} \
                    and not any(x in p.name for x in (".example", "truth_matrix", "truth_baseline")):
                if not self._has_identity_header(p, self._read(p)):
                    rep.identity_violations += 1

            if suffix == ".md":
                rep.md_files += 1
                if p.name == "README.md" and p.parent == self.root / dom:
                    rep.has_readme = True
                if p.name == "NUCLEUS.md":
                    rep.nucleus_count += 1
                    m = RE_NUCLEUS_STATUS.search(self._read(p))
                    st = (m.group(1).lower() if m else "unspecified")
                    rep.nucleus_status[st] = rep.nucleus_status.get(st, 0) + 1
            elif suffix in {".yaml", ".yml"}:
                rep.yaml_files += 1
                self._scan_yaml(p, rel, rep)
            elif suffix == ".py":
                rep.py_files += 1
                self._scan_python(p, rel, rep)

        self._score_tests_and_deploy()

    # -- فحص YAML ----------------------------------------------------------
    def _scan_yaml(self, p: Path, rel: str, rep: DomainReport):
        text = self._read(p)
        for i, line in enumerate(text.splitlines(), 1):
            if RE_SANDBOX_FALSE.search(line):
                f = Finding("SANDBOX_DISABLED", rel, i,
                            "أداة مسجّلة بلا عزل (sandbox=false)", "CRITICAL")
                rep.findings.append(f)
                self.global_findings.append(f)
            if SECRET_NAME.search(line) and RE_SECRET_ASSIGN.search(line):
                val = line.split(":", 1)[-1].strip().strip("'\"")
                if val and not SECRET_SAFE_VALUE.match(val):
                    f = Finding("HARDCODED_SECRET", rel, i,
                                "سر ثابت داخل ملف إعداد", "CRITICAL")
                    rep.findings.append(f)
                    rep.secret_hits += 1
                    self.global_findings.append(f)

    # -- فحص Python --------------------------------------------------------
    def _scan_python(self, p: Path, rel: str, rep: DomainReport):
        text = self._read(p)
        lines = text.splitlines()
        rep.code_lines += len([ln for ln in lines
                               if ln.strip() and not ln.strip().startswith("#")])

        rep.real_source_hits += len(RE_REAL_SOURCE.findall(text))
        rep.observed_hits += len(RE_OBSERVED.findall(text))
        rep.api_routes += len(RE_API.findall(text))

        for m in RE_IN_MEMORY.finditer(text):
            line_no = text[:m.start()].count("\n") + 1
            f = Finding("IN_MEMORY_STORE", rel, line_no,
                        f"مخزن ذاكرة `{m.group(0)}` يُستخدم كمصدر حقيقة", "HIGH")
            rep.findings.append(f)
            rep.in_memory_hits += 1
            self.global_findings.append(f)

        # التحليل النحوي: أسرار ثابتة + ثوابت الحقيقة الزائفة + الاستثناءات الصامتة
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return

        self._scan_secrets_ast(tree, rel, rep, lines)

        for node in ast.walk(tree):
            # ثابت على مستوى الوحدة يمثّل "حقيقة" تشغيلية
            if isinstance(node, ast.Assign) and getattr(node, "col_offset", 1) == 0:
                for tgt in node.targets:
                    if not isinstance(tgt, ast.Name):
                        continue
                    name = tgt.id
                    if not name.isupper() or not TRUTH_CONSTANT_HINT.search(name):
                        continue
                    if isinstance(node.value, (ast.List, ast.Dict, ast.Tuple, ast.Set)):
                        f = Finding("HARDCODED_TRUTH", rel, node.lineno,
                                    f"`{name}` بيانات ثابتة بديلة عن قاعدة البيانات",
                                    "CRITICAL")
                    elif isinstance(node.value, ast.Constant) and isinstance(
                            node.value.value, (int, float)):
                        f = Finding("HARDCODED_TRUTH", rel, node.lineno,
                                    f"`{name} = {node.value.value}` عدّاد ثابت "
                                    f"يُقدَّم كحقيقة تشغيلية", "CRITICAL")
                    else:
                        continue
                    rep.findings.append(f)
                    rep.fake_hits += 1
                    self.global_findings.append(f)

            # except صامت
            if isinstance(node, ast.ExceptHandler):
                body = node.body
                raises = any(isinstance(n, ast.Raise) for n in ast.walk(node))
                logs = any(
                    isinstance(n, ast.Attribute)
                    and n.attr in {"error", "warning", "exception", "critical"}
                    for n in ast.walk(node)
                )
                # الاستثناء ليس مبتلعًا إذا انتقلت معلومته إلى الخارج:
                # اسم الاستثناء مُستخدم فعليًا داخل الجسم (رسالة تُرجَع، أو مخالفة تُسجَّل).
                propagates = bool(node.name) and any(
                    isinstance(n, ast.Name) and n.id == node.name
                    for n in ast.walk(ast.Module(body=node.body, type_ignores=[]))
                )
                if not raises and not logs and not propagates:
                    seg = "\n".join(lines[node.lineno - 1:node.end_lineno or node.lineno])
                    sev = "HIGH" if RE_FALLBACK_WORD.search(seg) or len(body) > 1 else "MEDIUM"
                    f = Finding("SILENT_FALLBACK", rel, node.lineno,
                                "استثناء يُبتلع بلا تسجيل ولا رفع — يخفي فشل مصدر الحقيقة",
                                sev)
                    rep.findings.append(f)
                    self.global_findings.append(f)

    # -- فحص ترويسة الهوية (المادة الدستورية 009) --------------------------
    @staticmethod
    def _has_identity_header(p: Path, text: str) -> bool:
        head = "\n".join(text.splitlines()[:15])
        if p.suffix == ".md":
            return head.lstrip().startswith("#")
        return any(m in head for m in ("الهدف", "التعريف", "المالك", "النطاق"))

    # -- كشف الأسرار عبر الشجرة النحوية ------------------------------------
    def _secret_hit(self, rel: str, line: int, detail: str, rep: DomainReport):
        f = Finding("HARDCODED_SECRET", rel, line, detail, "CRITICAL")
        rep.findings.append(f)
        rep.secret_hits += 1
        self.global_findings.append(f)

    @staticmethod
    def _is_secret_name(name: str) -> bool:
        return bool(SECRET_NAME.search(name)) and not SECRET_NAME_EXEMPT.search(name)

    @staticmethod
    def _is_unsafe_secret_value(node) -> bool:
        """قيمة نصية صريحة تصلح أن تكون سرًا فعليًا."""
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            return False
        v = node.value.strip()
        return bool(v) and len(v) >= 6 and not SECRET_SAFE_VALUE.match(v)

    def _declared_not_secret(self, node, lines: list[str]) -> bool:
        """أُعلن صراحةً في المصدر أن القيمة ليست سرًّا؟ يُعَدُّ الإعلانُ ويُنشَر."""
        start = getattr(node, "lineno", 0)
        end = getattr(node, "end_lineno", None) or start
        # يُقبل الإعلانُ داخل مدى العقدة أو في تعليقٍ يعلوها بثلاثة أسطر كأكثر
        seg = "\n".join(lines[max(start - 4, 0):end])
        return SECRET_DECLARATION_MARKER in seg

    def _scan_secrets_ast(
        self, tree: ast.AST, rel: str, rep: DomainReport, lines: list[str] | None = None
    ):
        if Path(rel).name in SECRET_SCAN_EXEMPT_FILES:
            return
        lines = lines or []
        for node in ast.walk(tree):
            # x = "secret"  /  x: str = "secret"
            targets = []
            value = None
            if isinstance(node, ast.Assign):
                targets, value = node.targets, node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets, value = [node.target], node.value

            for tgt in targets:
                name = getattr(tgt, "id", None) or getattr(tgt, "attr", None)
                if name and self._is_secret_name(name) and self._is_unsafe_secret_value(value):
                    # عضوُ تعدادٍ يُسمّي نفسَه (`TOKEN_VERIFIED = "TOKEN_VERIFIED"`)
                    # ليس سرًّا: القيمةُ هي الاسمُ نفسُه.
                    if isinstance(value, ast.Constant) and value.value.strip() == name:
                        continue
                    if self._declared_not_secret(node, lines):
                        self._declared_exemptions.append((rel, node.lineno, name))
                        continue
                    self._secret_hit(rel, node.lineno,
                                     f"`{name}` قيمة سرية افتراضية مكتوبة داخل الكود", rep)

            # مقارنة اعتماد: req.password == "literal"
            if isinstance(node, ast.Compare) and len(node.comparators) == 1:
                left = node.left
                lname = getattr(left, "attr", None) or getattr(left, "id", None)
                if lname and self._is_secret_name(lname) and \
                        self._is_unsafe_secret_value(node.comparators[0]):
                    self._secret_hit(rel, node.lineno,
                                     f"مصادقة بمقارنة `{lname}` مع قيمة ثابتة في الكود", rep)

            # كلمات مرور داخل قواميس الإعداد: {"password": "literal"}
            if isinstance(node, ast.Dict):
                for k, v in zip(node.keys, node.values):
                    if isinstance(k, ast.Constant) and isinstance(k.value, str) \
                            and self._is_secret_name(k.value) \
                            and self._is_unsafe_secret_value(v):
                        if self._declared_not_secret(node, lines):
                            self._declared_exemptions.append((rel, node.lineno, k.value))
                            continue
                        self._secret_hit(rel, node.lineno,
                                         f"مفتاح `{k.value}` بقيمة سرية ثابتة", rep)

    # -- ربط الاختبارات والنشر ---------------------------------------------
    def _score_tests_and_deploy(self):
        for dom, rep in self.reports.items():
            rep.test_refs = len(re.findall(rf"\b{dom}\b", self.test_corpus))
            rep.deployed = bool(re.search(rf"\b{dom}\b", self.deploy_corpus))

    # -- المخرجات -----------------------------------------------------------
    def to_json(self) -> dict:
        # المخرج حتمي (deterministic) بلا طوابع زمنية متغيرة،
        # حتى تستطيع بوابة CI مقارنة المصفوفة المدفوعة بالمولَّدة.
        return {
            "schema_version": 1,
            "repo": str(self.root.name),
            "domains": {
                d: {
                    **{k: v for k, v in asdict(r).items() if k != "findings"},
                    "columns": {
                        "DOCUMENTED": r.documented,
                        "IMPLEMENTED": r.implemented,
                        "REAL_SOURCE": r.real_source,
                        "FAKE_OR_CACHED": r.fake_or_cached,
                        "INTEGRATED": r.integrated,
                        "TESTED": r.tested,
                        "SECURED": r.secured,
                        "OBSERVED": r.observed,
                        "DEPLOYED": r.deployed,
                        "PROVEN": r.proven,
                    },
                    "maturity": r.maturity(),
                    "findings_count": len(r.findings),
                }
                for d, r in self.reports.items()
            },
            "findings": [asdict(f) for f in self.global_findings],
            "declared_not_secret": [
                {"path": rel, "line": line, "key": name}
                for rel, line, name in sorted(self._declared_exemptions)
            ],
            "summary": self.summary(),
        }

    def summary(self) -> dict:
        by_sev: dict[str, int] = {}
        by_kind: dict[str, int] = {}
        for f in self.global_findings:
            by_sev[f.severity] = by_sev.get(f.severity, 0) + 1
            by_kind[f.kind] = by_kind.get(f.kind, 0) + 1
        return {
            "domains_total": len(self.reports),
            "domains_proven": sum(1 for r in self.reports.values() if r.proven),
            "findings_total": len(self.global_findings),
            "identity_violations": sum(r.identity_violations for r in self.reports.values()),
            "by_severity": by_sev,
            "by_kind": by_kind,
        }

    def _load_round_classifications(self) -> list[dict]:
        """قراءةُ تصنيفات الجولات المُعلَنة — مُدخَلٌ يدويٌّ يُقرأ آليًا."""
        path = self.root / "docs" / "audit" / "round_classifications.json"
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[TRUTH AUDIT] تعذّرت قراءةُ {path}: {exc}", file=sys.stderr)
            return []
        rounds = data.get("rounds", [])
        return rounds if isinstance(rounds, list) else []

    def to_markdown(self) -> str:
        s = self.summary()
        out: list[str] = []
        a = out.append

        a("# TRUTH_MATRIX.md — مصفوفة الحقيقة")
        a("")
        a("## الهدف: قياس الفجوة بين ما تقوله وثائق الدولة وما ينفذه الكود فعليًا")
        a("## النطاق: كل أقاليم المستودع الاثني عشر")
        a("## المالك: docs/audit/ — ديوان تدقيق الدولة")
        a("## تاريخ الإنشاء: 2026-08-16")
        a("## تاريخ آخر تعديل: يُحدَّد بـ commit التوليد (المخرج حتمي بلا طابع زمني)")
        a("")
        a("> **هذا الملف مُولَّد آليًا. لا تحرّره يدويًا.**")
        a("> يُعاد توليده بالأمر: `python tools/governance/truth_audit.py`")
        a("")
        a("> **القاعدة الذهبية:** لا تُقبل عبارة DONE لأن الملف موجود. "
          "`DONE = Capability Proven`.")
        a("")
        a("---")
        a("")
        a("## 1. الحكم الإجمالي")
        a("")
        a("| المقياس | القيمة |")
        a("|---|---:|")
        a(f"| الأقاليم المفحوصة | {s['domains_total']} |")
        a(f"| الأقاليم بحالة PROVEN | {s['domains_proven']} |")
        a(f"| إجمالي المخالفات | {s['findings_total']} |")
        a(f"| ملفات بلا ترويسة هوية (المادة 009) | {s['identity_violations']} |")
        for sev in ("CRITICAL", "HIGH", "MEDIUM", "INFO"):
            if sev in s["by_severity"]:
                a(f"| منها {sev} | {s['by_severity'][sev]} |")
        a("")
        a("### توزيع المخالفات حسب النوع")
        a("")
        a("| النوع | العدد | المعنى |")
        a("|---|---:|---|")
        meanings = {
            "HARDCODED_TRUTH": "قيمة ثابتة تُقدَّم كحقيقة تشغيلية بدل قاعدة البيانات",
            "HARDCODED_SECRET": "سر/كلمة مرور مكتوبة داخل الكود أو الإعداد",
            "IN_MEMORY_STORE": "مخزن ذاكرة يُستخدم بديلًا عن تخزين دائم",
            "SILENT_FALLBACK": "استثناء يُبتلع بلا تسجيل ولا رفع",
            "SANDBOX_DISABLED": "أداة خطرة مسجّلة بلا عزل",
        }
        for k, v in sorted(s["by_kind"].items(), key=lambda x: -x[1]):
            a(f"| {k} | {v} | {meanings.get(k, '—')} |")
        a("")
        a("---")
        a("")
        a("## 2. مصفوفة الأقاليم")
        a("")
        a("| الإقليم | موثّق | منفّذ | مصدر حقيقي | زائف/مخبأ | مدمج | مختبَر | "
          "مؤمَّن | مُراقَب | منشور | **مُثبَت** | الحالة |")
        a("|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|---|")
        for d in DOMAINS:
            r = self.reports[d]
            a(f"| `{d}/` | {r.mark(r.documented)} | {r.mark(r.implemented)} | "
              f"{r.mark(r.real_source)} | {'⚠️' if r.fake_or_cached else '—'} | "
              f"{r.mark(r.integrated)} | {r.mark(r.tested)} | {r.mark(r.secured)} | "
              f"{r.mark(r.observed)} | {r.mark(r.deployed)} | "
              f"**{r.mark(r.proven)}** | `{r.maturity()}` |")
        a("")
        a("> `⚠️` في عمود «زائف/مخبأ» يعني وجود قيم ثابتة أو مخازن ذاكرة "
          "تُستخدم بديلًا عن مصدر الحقيقة. أي إقليم يحمل `⚠️` **لا يمكن** أن يصل PROVEN.")
        a("")
        a("---")
        a("")
        a("## 3. الحجم الفعلي لكل إقليم")
        a("")
        a("| الإقليم | md | py | yaml | أسطر كود | نوى | بلا ترويسة هوية | حالات النوى |")
        a("|---|---:|---:|---:|---:|---:|---:|---|")
        for d in DOMAINS:
            r = self.reports[d]
            st = ", ".join(f"{k}={v}" for k, v in sorted(r.nucleus_status.items())) or "—"
            a(f"| `{d}/` | {r.md_files} | {r.py_files} | {r.yaml_files} | "
              f"{r.code_lines} | {r.nucleus_count} | {r.identity_violations} | {st} |")
        a("")
        a("---")
        a("")
        a("## 4. سجل المخالفات بالأدلة")
        a("")
        order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "INFO": 3}
        for sev in ("CRITICAL", "HIGH", "MEDIUM", "INFO"):
            items = [f for f in self.global_findings if f.severity == sev]
            if not items:
                continue
            a(f"### {sev} ({len(items)})")
            a("")
            a("| الموقع | النوع | الخطورة | التفصيل |")
            a("|---|---|---|---|")
            for f in sorted(items, key=lambda x: (order[x.severity], x.path, x.line)):
                a(f.as_row())
            a("")
        if self._declared_exemptions:
            a("### إعلاناتُ «ليست سرًّا» الصريحة "
              f"({len(self._declared_exemptions)})")
            a("")
            a("> قيمٌ اختباريةٌ مُختَرَعةٌ أُعلن في المصدر صراحةً أنها ليست أسرارًا "
              f"بالعلامة `{SECRET_DECLARATION_MARKER}`. تُنشَر هنا ولا تُخفى.")
            a("")
            a("| الموقع | المفتاح |")
            a("|---|---|")
            for rel, line, name in sorted(self._declared_exemptions):
                a(f"| `{rel}:{line}` | `{name}` |")
            a("")
        a("---")
        a("")
        a("## 5. تصنيفاتُ الجولات المُعلَنة")
        a("")
        rounds = self._load_round_classifications()
        if not rounds:
            a("> لا يوجد ملفُّ تصنيفاتٍ مُعلَنة (`docs/audit/round_classifications.json`).")
            a("")
        else:
            a("> المصدر: [`round_classifications.json`](round_classifications.json) — "
              "يُحرَّر يدويًا ويُقرأ آليًا. "
              "`REAL` = مُلاحَظٌ فعليًا · `PARTIAL` = جزئيٌّ مُعلَن · "
              "`UNRESOLVED` = دَينٌ مفتوح · `UNAVAILABLE` = غيرُ متوفّر · "
              "`UNOBSERVED` = لم يُلاحَظ.")
            a("")
            for rnd in rounds:
                title = str(rnd.get("title", "")).strip()
                head = str(rnd.get("round", "?")).strip()
                a(f"### {head}" + (f" — {title}" if title else ""))
                a("")
                ref = str(rnd.get("reference", "")).strip()
                if ref:
                    a(f"> المرجع: `{ref}`")
                    a("")
                a("| المجال | التصنيف | الدليل |")
                a("|---|---|---|")
                for claim in rnd.get("claims", []):
                    area = str(claim.get("area", "")).replace("|", "\\|")
                    cls = str(claim.get("classification", "")).replace("|", "\\|")
                    ev = str(claim.get("evidence", "")).replace("|", "\\|")
                    a(f"| {area} | `{cls}` | {ev} |")
                a("")
        a("---")
        a("")
        a("## 6. ماذا يعني هذا")
        a("")
        a("كل صف بحالة أقل من `PROVEN` هو **دَين تنفيذي** مفتوح. "
          "خطة Phase E مرتّبة لسداد هذا الدين إقليمًا إقليمًا.")
        a("")
        a("راجع [`PHASE_E_ROADMAP.md`](PHASE_E_ROADMAP.md) لترتيب السداد، "
          "و[`DEFINITION_OF_DONE.md`](DEFINITION_OF_DONE.md) لمعيار الإقفال.")
        a("")
        return "\n".join(out)


# ---------------------------------------------------------------------------

def ratchet_gate(out_dir: Path, summary: dict, set_baseline: bool) -> int:
    """بوابة عدم التراجع — عدد المخالفات لا يجوز أن يرتفع أبدًا."""
    baseline_path = out_dir / "truth_baseline.json"
    current = {
        "findings_total": summary["findings_total"],
        "by_kind": summary["by_kind"],
        "by_severity": summary["by_severity"],
    }

    if set_baseline or not baseline_path.exists():
        baseline_path.write_text(
            json.dumps({"updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        **current}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[RATCHET] ثُبّت خط الأساس: {current['findings_total']} مخالفة.")
        return 0

    base = json.loads(baseline_path.read_text(encoding="utf-8"))
    failures: list[str] = []

    if current["findings_total"] > base["findings_total"]:
        failures.append(f"إجمالي المخالفات ارتفع من {base['findings_total']} "
                        f"إلى {current['findings_total']}")
    for kind, count in current["by_kind"].items():
        prev = base.get("by_kind", {}).get(kind, 0)
        if count > prev:
            failures.append(f"{kind} ارتفع من {prev} إلى {count}")

    if failures:
        print("[RATCHET] فشلت بوابة عدم التراجع:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        print("  الدولة لا تتراجع. أصلح المخالفات الجديدة قبل الدفع.", file=sys.stderr)
        return 1

    if current["findings_total"] < base["findings_total"]:
        print(f"[RATCHET] تقدّم: {base['findings_total']} → {current['findings_total']} مخالفة. "
              f"ثبّت خط أساس جديدًا بـ --set-baseline")
    else:
        print(f"[RATCHET] ثابت عند {current['findings_total']} مخالفة.")
    return 0


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    strict = "--strict" in argv
    ratchet = "--ratchet" in argv
    set_baseline = "--set-baseline" in argv
    root = Path(args[0]).resolve() if args else Path(__file__).resolve().parents[2]

    audit = TruthAudit(root)
    audit.scan()

    out_dir = root / "docs" / "audit"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "TRUTH_MATRIX.md").write_text(audit.to_markdown(), encoding="utf-8")
    (out_dir / "truth_matrix.json").write_text(
        json.dumps(audit.to_json(), ensure_ascii=False, indent=2), encoding="utf-8")

    s = audit.summary()
    print(f"[TRUTH AUDIT] أقاليم: {s['domains_total']} | "
          f"مُثبَتة: {s['domains_proven']} | مخالفات: {s['findings_total']}")
    for k, v in sorted(s["by_kind"].items(), key=lambda x: -x[1]):
        print(f"  - {k}: {v}")
    print(f"[TRUTH AUDIT] كُتبت: {out_dir/'TRUTH_MATRIX.md'}")

    exit_code = 0
    if ratchet or set_baseline:
        exit_code |= ratchet_gate(out_dir, s, set_baseline)

    if strict:
        critical = s["by_severity"].get("CRITICAL", 0)
        if critical:
            print(f"[TRUTH AUDIT] فشل صارم: {critical} مخالفة حرجة.", file=sys.stderr)
            exit_code |= 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
