"""الهدف: إثباتُ أنَّ تبعيّاتِ جذرِ المستودعِ مُعلَنةٌ في موضعٍ واحدٍ لا مبثوثةٌ في CI.

النطاق: `requirements-dev.txt` و`requirements-tools.txt` و`.github/workflows/ci.yml`.
المالك: governance/
تاريخ الإنشاء: 2026-08-21
تاريخ آخر تعديل: 2026-08-21

## ما يحرسُه هذا الملفّ (H-1N-2 · T0.1 · T0.7)

كانت تبعيّاتُ الجذرِ مكتوبةً بأسمائِها في سطورِ `pip install` داخلَ ستِّ وظائفَ
في CI، فلا مصدرَ واحدَ يُقرَأ، وكلُّ إضافةٍ تُنسى في وظيفةٍ تُسقِطُ بوّابةً لسببٍ
لا علاقةَ له بما تحرسُه. فصارَ الإعلانُ واحدًا، وهذا الحارسُ يمنعُ العودةَ إلى
البثِّ: أيُّ سطرِ تركيبٍ في CI يُسمّي حزمةً مجرّدةً يُسقِطُ الاختبار.

والقائمةُ المسموحُ بها مُعلَنةٌ بأسبابِها أدناه، فلا تُوسَّع بلا سببٍ مكتوب.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"
DEV = REPO_ROOT / "requirements-dev.txt"
TOOLS = REPO_ROOT / "requirements-tools.txt"

#: سطورُ التركيبِ المسموحُ بها، وسببُ كلٍّ منها:
#: - `-r requirements-dev.txt` — إعلانُ تبعيّاتِ الجذرِ الواحد.
#: - `-r requirements.lock` و`-e . --no-deps` و`-e ".[dev]"` — حزمةُ الخدماتِ
#:   بمِلفِّ قُفلِها، وهي إعلانٌ قائمٌ منفصلٌ لا يُكرَّر هنا.
#: - `-e "federal/executive/services[dev]"` و`-r federal/.../requirements.lock`
#:   — الحزمةُ نفسُها من جذرِ المستودع.
#: - `ruff==0.6.9` — أداةُ الفحصِ الساكنِ مُثبَّتةُ الإصدارِ في وظيفةِ اللِّنت:
#:   إصدارُها جزءٌ من معنى البوّابة (قاعدةٌ تظهرُ في إصدارٍ وتغيبُ في آخر)،
#:   فتثبيتُه في موضعِه أصدقُ من إعلانٍ فضفاضٍ في مِلفٍّ عامّ.
ALLOWED = (
    "-r requirements-dev.txt",
    "-r requirements.lock",
    "-r federal/executive/services/requirements.lock",
    "-e . --no-deps",
    '-e ".[dev]"',
    '-e "federal/executive/services[dev]"',
    "ruff==0.6.9",
)

_INSTALL = re.compile(r"pip install\s+(?P<args>.+?)\s*$")


def _أوامر_التركيب(نص: str) -> list[str]:
    """وسائطُ كلِّ `pip install` **مُنفَّذٍ** — والتعليقُ ليس أمرًا.

    يُستبعدُ ما كان داخلَ تعليقٍ (`#`)، وإلّا أسقطَ الحارسَ شرحٌ يذكرُ أمرًا
    قديمًا رُفِع — فيصيرُ الحارسُ مانعًا للتوثيق لا للبثّ.
    """
    أوامر: list[str] = []
    for سطر in نص.splitlines():
        فعلي = سطر.split("#", 1)[0]
        مطابقة = _INSTALL.search(فعلي)
        if مطابقة:
            أوامر.append(مطابقة.group("args").strip())
    return أوامر


def _معلنة(نص: str) -> set[str]:
    """أسماءُ الحزمِ المُعلَنةِ في مِلفِّ متطلّبات — بلا تعليقاتٍ ولا حدودِ إصدار."""
    أسماء = set()
    for سطر in نص.splitlines():
        سطر = سطر.split("#", 1)[0].strip()
        if سطر:
            أسماء.add(re.split(r"[<>=!~\[]", سطر, maxsplit=1)[0].strip().lower())
    return أسماء


def test_إعلان_تبعيات_الجذر_قائم_ويذكر_ما_تلزمه_البوابات() -> None:
    """الثلاثةُ التي كانت مبثوثةً في CI مُعلَنةٌ الآن في مِلفٍّ واحد."""
    assert DEV.exists(), "لا إعلانَ لتبعيّاتِ الجذرِ — العودةُ إلى البثِّ في CI."
    أسماء = _معلنة(DEV.read_text(encoding="utf-8"))
    for حزمة in ("pytest", "pytest-cov", "cryptography"):
        assert حزمة in أسماء, f"«{حزمة}» تلزمُ بوّاباتِ الجذرِ ولم تُعلَن في {DEV.name}."


def test_إعلان_تبعيات_الأدوات_قائم_ويسمي_مستخدميه() -> None:
    """تبعيّتا المولِّدَين مُعلَنتان، وكلٌّ مربوطةٌ بمُستخدِمِها بالاسم."""
    assert TOOLS.exists(), "تبعيّاتُ أدواتِ الجذرِ غيرُ مُعلَنة — دَينٌ مُخفى."
    نص = TOOLS.read_text(encoding="utf-8")
    أسماء = _معلنة(نص)
    assert {"pyyaml", "sqlalchemy"} <= أسماء
    assert "generate_imported.py" in نص, "تبعيّةٌ بلا مُستخدِمٍ مُسمّى ليست إعلانًا."
    assert "r4_unify_agent_identity.py" in نص


def test_لا_سطر_تركيب_في_CI_يسمي_حزمة_مجردة() -> None:
    """كلُّ `pip install` في CI يقرأُ إعلانًا، أو يُثبِّتُ ما يُسوَّغُ في مكانِه."""
    أوامر = _أوامر_التركيب(CI.read_text(encoding="utf-8"))
    assert أوامر, "لم يُقرَأ أمرُ تركيبٍ واحد — الحارسُ لا يقيسُ شيئًا."
    مخالف = [
        وسائط
        for وسائط in أوامر
        if not any(وسائط.startswith(مسموح) for مسموح in ALLOWED)
    ]
    assert not مخالف, (
        "سطورُ تركيبٍ تُسمّي حزمًا مجرّدةً بدلَ الإعلانِ الواحد: "
        + " · ".join(مخالف)
        + " — أَعلِنْها في requirements-dev.txt أو سوّغْ إضافتَها إلى القائمةِ هنا."
    )
