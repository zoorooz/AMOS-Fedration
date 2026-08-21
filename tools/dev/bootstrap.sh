#!/usr/bin/env bash
# الهدف: تهيئةُ بيئةِ عملٍ صالحةٍ للقياسِ بأمرٍ واحد — بيئةٌ معزولةٌ وتبعيّاتُ
#        الجذرِ وحزمةُ الخدمات، ثمّ إعلانُ أوامرِ القياسِ الواجبةِ قبلَ أيِّ دفع.
# النطاق: جذرُ المستودعِ محلّيًّا. لا يُشغَّلُ في CI (لكلِّ وظيفةٍ تركيبُها المُعلَن).
# المالك: governance/
# تاريخ الإنشاء: 2026-08-21
# تاريخ آخر تعديل: 2026-08-21
#
# ── لماذا هذه الأداة (T0.2) ─────────────────────────────────────────────────
# كانت البيئةُ تُجهَّزُ يدويًّا بسبعِ خطواتٍ منثورةٍ في دليلِ المشروع § 8، فكلُّ
# قياسٍ غيرُ قابلٍ للتكرارِ إلّا بيقظةِ من يقرأ. وثلاثةُ مصائدَ **قيسَت فعلًا**
# وتُعالَجُ هنا صراحةً:
#   1) أرشيفٌ مضغوطٌ بدلَ `git clone` يُسقِطُ اختباري الهويّةِ لأنّ الخاتمَ يقرأُ
#      «تاريخَ آخر تعديل» من `git log`.
#   2) غيابُ حزمةِ الخدماتِ يُعطي `ModuleNotFoundError` في حزمِ التقاطع.
#   3) مسارُ SQLite النسبيُّ يُعطي «disk I/O error»، فالمطلقُ إلزاميّ.
#
# ولا يُخفي هذا السكربتُ فارقًا: إن لم يوجد Python 3.12 (إصدارُ CI) أَعلَنَ
# الفارقَ ومضى — ولا يزعمُ مطابقةَ CI (الحدُّ C-7).
#
# الاستعمال:
#   bash tools/dev/bootstrap.sh              # تهيئةٌ فحسب
#   bash tools/dev/bootstrap.sh --with-tools # + تبعيّاتُ مولِّداتِ الجذر
#   bash tools/dev/bootstrap.sh --verify     # + تشغيلُ حزمةِ الجذرِ والبوّابات

set -euo pipefail

VENV_DIR=".venv"
WITH_TOOLS=0
VERIFY=0

for arg in "$@"; do
  case "$arg" in
    --with-tools) WITH_TOOLS=1 ;;
    --verify) VERIFY=1 ;;
    -h|--help) sed -n '20,26p' "$0"; exit 0 ;;
    *) echo "✗ وسيطٌ غيرُ معروف: $arg" >&2; exit 2 ;;
  esac
done

# ── 0) الموضع: الجذرُ لا غيره ────────────────────────────────────────────────
root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$root_dir"
for marker in pytest.ini core/constitution requirements-dev.txt; do
  if [ ! -e "$marker" ]; then
    echo "✗ لا يبدو هذا جذرَ المستودع (غابَ «$marker»)." >&2
    exit 1
  fi
done
echo "• الجذر: $root_dir"

# ── 1) استنساخُ git لا أرشيف ─────────────────────────────────────────────────
if [ ! -d .git ]; then
  echo "✗ لا مجلدَ .git هنا. الخاتمُ يقرأُ تاريخَ آخر تعديلٍ من سجلِّ git،" >&2
  echo "  فاختبارا الهويّةِ يسقطان على أرشيفٍ مضغوط. استنسخْ بـ git:" >&2
  echo "  git clone https://github.com/zoorooz/AMOS-Fedration.git" >&2
  exit 1
fi
if [ "$(git rev-list --count HEAD 2>/dev/null || echo 0)" -le 1 ]; then
  echo "⚠ التاريخُ ضحلٌ (التزامٌ واحد). الخاتمُ سيرى كلَّ ملفٍّ مُعدَّلًا اليوم،"
  echo "  فتُعلَنُ بطاقاتٌ مخالفةً وهي صحيحة. الحلّ: git fetch --unshallow"
fi

# ── 2) مُفسِّرٌ يوافقُ CI إن وُجد ───────────────────────────────────────────────
if command -v python3.12 >/dev/null 2>&1; then
  PY=python3.12
else
  PY=python3
  echo "⚠ لا python3.12 هنا (إصدارُ CI). سيُستعملُ $("$PY" -V 2>&1)."
  echo "  الفارقُ مُعلَنٌ لا مُخفى: قياسُك قد يفارقُ CI في الحُزَمِ لا الإصدارِ وحدَه (C-7)."
fi

# ── 3) بيئةٌ معزولة ──────────────────────────────────────────────────────────
if [ ! -d "$VENV_DIR" ]; then
  echo "• إنشاءُ بيئةٍ معزولةٍ في $VENV_DIR"
  "$PY" -m venv "$VENV_DIR"
fi
# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"
python -m pip install --quiet --upgrade pip

# ── 4) تبعيّاتُ الجذرِ من إعلانِها الواحد (T0.1) ───────────────────────────────
echo "• تركيبُ تبعيّاتِ الجذر (requirements-dev.txt)"
python -m pip install --quiet -r requirements-dev.txt

if [ "$WITH_TOOLS" -eq 1 ]; then
  echo "• تركيبُ تبعيّاتِ مولِّداتِ الجذر (requirements-tools.txt)"
  python -m pip install --quiet -r requirements-tools.txt
fi

# ── 5) حزمةُ الخدماتِ الفدراليّة ──────────────────────────────────────────────
echo "• تركيبُ حزمةِ الخدماتِ (قد تطولُ: تبعيّاتٌ كثيرة)"
python -m pip install --quiet -e "federal/executive/services[dev]"

echo "✓ البيئةُ جاهزة. للتنشيطِ في جلسةٍ جديدة: source $VENV_DIR/bin/activate"

# ── 6) القياسُ عندَ الطلب ─────────────────────────────────────────────────────
if [ "$VERIFY" -eq 1 ]; then
  echo "── حزمةُ الجذر ──"
  python -m pytest tests/ -q
  echo "── بوّاباتُ الحوكمة ──"
  python tools/governance/truth_audit.py .
  python tools/governance/check_repository_identity.py .
  python tests/smoke/run_smoke_tests.py
  echo "── نظافةُ الشجرةِ بعدَ التشغيل (O-1N-1) ──"
  if [ -n "$(git status --porcelain)" ]; then
    echo "✗ التشغيلُ غيَّرَ الشجرة:" >&2
    git status --porcelain >&2
    exit 1
  fi
  echo "✓ الشجرةُ نظيفةٌ بعدَ حزمةٍ كاملة."
fi

cat <<'ملاحظة'

الأوامرُ الواجبةُ قبلَ أيِّ دفع (دليلُ المشروع § 8 و§ 9):
  python -m pytest tests/ -q
  AMOS_DATABASE_URL="sqlite:////tmp/amos_test.db" \
    python -m pytest federal/executive/services/tests -q
  python tools/governance/truth_audit.py .
  python tools/governance/check_repository_identity.py .
  python tools/governance/check_completion_ledger.py --commit HEAD
  python tests/smoke/run_smoke_tests.py
  ruff check . && ruff format --check \
    federal/executive/services/src federal/executive/services/tests

وتذكّرْ: آخرُ أمرٍ يُغيِّرُ بايتًا من الكودِ يسبقُ آخرَ توليدٍ للمصفوفة.
ملاحظة
