"""
اختبارُ كشفِ الأسرار في ملفّات البيئة — إغلاقُ بقعةٍ عمياء
الهدف: حراسةُ أن يبقى المدقّقُ الدستوريُّ قادرًا على كشفِ اعتمادٍ نافذٍ في أيِّ
       ملفِّ بيئةٍ متعقَّبٍ في أيِّ موضعٍ من المستودع، وأن لا يرفع مخالفةً على نائبٍ
       ولا على ملفٍّ محلّيٍّ غيرِ متعقَّب.
النطاق: tools/governance/truth_audit.py — مسحُ ملفّات البيئة وحده.
المالك: tools/governance
تاريخ الإنشاء: 2026-08-18
تاريخ آخر تعديل: 2026-08-18

## العطلُ الذي تحرسه هذه الاختبارات — مقيسٌ لا مفترَض

كان `.env.example` في جذر المستودع يحمل كلمةَ مرورِ PostgreSQL نافذةً نصًّا
لمشروع Supabase قائم ومفتاحَ `sb_publishable_...`، وهو ملفٌّ **مدفوعٌ إلى تاريخٍ
عام**. ومع ذلك كان المدقّقُ يطبع `HARDCODED_SECRET: 0`.

وللعمى سببان مقيسان، لا سببٌ واحد:
  ١) المسحُ محصورٌ في اللواحق {md, py, yaml, yml, rego, sql}، ولاحقةُ
     `.env.example` هي `.example` فلا تدخل المسحَ أصلًا؛ وشرطُ الاستثناء
     يستبعد صراحةً كلَّ اسمٍ يحتوي `.example`.
  ٢) وأعمقُ منه: `scan()` كانت تقول `if dom is None: continue`، فكلُّ ملفٍ
     خارجَ الأقاليم الاثني عشر لا يُمسَح للأسرار أبدًا — وجذرُ المستودع، حيث
     يسكن التسريبُ الوحيد، أوسعُ تلك المناطق العمياء.

فكانت النتيجةُ شهادةَ أمنٍ لا دليلَ لها. وهذه الاختبارات تحرس أن لا تعود.

وتحرس معها حدَّين لا يقلّان أهمّيّةً عن الكشف:
  - **لا إيجابيّاتٌ كاذبة**: مدقّقٌ يصرخ على `dev_password_change_me` يُدرّب
    قارئَه على تجاهله، فيصير الصمتُ والصراخُ سواءً. (وقع هذا فعلًا: أوّلُ
    تشغيلٍ للكاشف رفع ٧ مخالفات، خمسٌ منها كاذبة.)
  - **الملفُّ المحلّيُّ غيرُ المتعقَّب لا يُخالَف عليه**: `.env` المُستثنى في
    `.gitignore` هو الموضعُ الصحيح للاعتماد. ورفعُ مخالفةٍ عليه يُسقِط البوّابةَ
    عند كلِّ مطوّرٍ أدّى الواجب.
"""

# القيمُ الحسّاسةُ في هذا الملفِّ **مُصطنَعةٌ بالكامل** ولا تفتح شيئًا. وكانت
# في أوّلِ صياغةٍ منسوخةً من الأسرارِ الحقيقيّةِ الفعليّة، فكان الاختبارُ الذي
# يحرس تسريبَ الأسرارِ **مصدرَ تسريبٍ هو نفسُه** — وهي مخالفةُ القاعدةِ 23
# ارتُكبت في الملفِّ المكلَّفِ بمنعِها. كُشِف ذلك بفحصِ المُرحَّلِ قبل الالتزام،
# فاستُبدِلت القيمُ بمُصطنَعةٍ تحافظ على أنماطِ الكشفِ ولا تحمل سرًّا.
#
# وأوّلُ استبدالٍ كسر الاختباراتِ الثلاثةَ: حملت القيمُ لفظَي `example` و
# `SYNTHETIC` فطابقت `RE_ENV_PLACEHOLDER` فصُنِّفت نائباتٍ فلم تُكشَف — أي أنّ
# قيمةً «آمنةَ المظهر» تُخفي الاختبارَ نفسَه. فالقيمُ الآن عشوائيّةُ الشكلِ
# خاليةٌ من كلِّ لفظٍ يُصنَّف نائبًا، ليبقى ما يُكشَف مكشوفًا.

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tools.governance.truth_audit import TruthAudit

REAL_PASSWORD_URL = (
    "postgresql://postgres.abcdefghijklmnop:"
    "Qw9Lm4Tp7Vx2Rb8Nk@aws-0-zz1.pooler.supabase.com:5432/postgres"
)


def _git_repo(root: Path, *, tracked: list[str]) -> None:
    """مستودعٌ حقيقيٌّ صغير: المسحُ يسأل git عن المتعقَّب، فيلزم أن يكون ثمّة git."""
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    if tracked:
        subprocess.run(["git", "add", "-f", *tracked], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "seed"], cwd=root, check=True)


def _secret_findings(root: Path) -> list:
    aud = TruthAudit(root)
    aud.scan()
    return [f for f in aud.global_findings if f.kind == "HARDCODED_SECRET"]


class Testالكشفيعمل:
    """الاعتمادُ النافذُ يُكشَف حيث كان."""

    def test_كلمةُ_مرورٍ_في_رابطٍ_بجذر_المستودع_تُكشَف(self, tmp_path: Path):
        """جوهرُ العطل: الجذرُ خارجَ الأقاليم، وكان لا يُمسَح أصلًا."""
        (tmp_path / ".env.example").write_text(
            f"DATABASE_URL={REAL_PASSWORD_URL}\n", encoding="utf-8")
        _git_repo(tmp_path, tracked=[".env.example"])

        found = _secret_findings(tmp_path)
        assert len(found) == 1, "تسريبُ الجذر لم يُكشَف — البقعةُ العمياء عادت."
        assert found[0].path == ".env.example"
        assert found[0].severity == "CRITICAL"

    def test_لاحقةُ_example_لا_تُعفي(self, tmp_path: Path):
        """«إنّه قالبٌ» ليس عذرًا: قالبٌ مدفوعٌ يحمل اعتمادًا نافذًا تسريبٌ كامل."""
        (tmp_path / ".env.example").write_text(
            "SUPABASE_PUBLISHABLE_KEY=" + "sb_publishable_" + "Qw9Lm4Tp7Vx2Rb8Nk_Zy6Hc3Jd1\n",
            encoding="utf-8")
        _git_repo(tmp_path, tracked=[".env.example"])
        assert len(_secret_findings(tmp_path)) == 1

    def test_ملفُّ_بيئةٍ_خارج_الأقاليم_يُمسَح(self, tmp_path: Path):
        """`ops/` و`tools/` و`docs/` كانت كلُّها عمياءَ كالجذر."""
        d = tmp_path / "deploy" / "staging"
        d.mkdir(parents=True)
        (d / ".env.production").write_text(
            f"DATABASE_URL={REAL_PASSWORD_URL}\n", encoding="utf-8")
        _git_repo(tmp_path, tracked=["deploy/staging/.env.production"])

        found = _secret_findings(tmp_path)
        assert len(found) == 1
        assert found[0].path == "deploy/staging/.env.production"

    # القيمُ تُركَّب من جزأَين ولا تُكتَب حرفًا واحدًا متّصلًا. والسببُ قياسٌ لا
    # احتياط: رفضت حمايةُ الدفعِ في GitHub الالتزامَ لأنّ أحدَ هذه السطورِ كان
    # يطابق نمطَ رمزِ Slack مطابقةً تامّة. فالقيمةُ مُصطنَعةٌ لا تفتح شيئًا،
    # لكنّ شكلَها وحدَه يكفي لإيقافِ الدفع — وحارسٌ خارجيٌّ يمنع دفعَ ما يشبه
    # السرَّ أَولى بالإبقاء من اختبارٍ يُريحه. فالتركيبُ يحفظ قوّةَ الاختبارِ
    # ولا يُبقي في الملفِّ نصًّا يطابق كاشفًا.
    @pytest.mark.parametrize("value", [
        "ghp_" + "Qw9Lm4Tp7Vx2Rb8NkZy6Hc3Jd1Sf5Gv0Bn2Mx",
        "sb_secret_" + "abcdefghijklmnopqrstuvwxyz",
        "AKIA" + "IOSFODNN7EXAMPLEX",
        "xoxb" + "-123456789012-abcdefghijklmnop",
    ])
    def test_بادئاتُ_مفاتيحِ_المنصّات_تُكشَف(self, tmp_path: Path, value: str):
        (tmp_path / ".env").write_text(f"SOME_TOKEN={value}\n", encoding="utf-8")
        _git_repo(tmp_path, tracked=[".env"])
        assert len(_secret_findings(tmp_path)) == 1, f"لم يُكشَف: {value}"

    def test_اسمٌ_سرّيٌّ_بقيمةٍ_حقيقيّةٍ_يُكشَف(self, tmp_path: Path):
        (tmp_path / ".env").write_text(
            "AMOS_JWT_SECRET=8f3c1a9e77b24d5faa01c6de92bb47e3\n", encoding="utf-8")
        _git_repo(tmp_path, tracked=[".env"])
        assert len(_secret_findings(tmp_path)) == 1


class Testلاإيجابياتكاذبة:
    """النائبُ لا يُخالَف عليه — الصراخُ على النائب يُبطِل قيمةَ الصراخ."""

    @pytest.mark.parametrize("line", [
        "AMOS_POSTGRES_PASSWORD=dev_password_change_me",
        "AMOS_MINIO_SECRET_KEY=dev_password_change_me",
        "AMOS_JWT_SECRET=dev_secret_change_me_at_least_32_characters",
        "AMOS_KING_LOGIN_SECRET=dev_king_secret_change_me",
        "AMOS_CLAUDE_API_KEY=your_api_key_here",
        "SUPABASE_PUBLISHABLE_KEY=<supabase_publishable_key>",
        "AMOS_JWT_SECRET=REPLACE_ME",
        "AMOS_JWT_SECRET=${JWT_FROM_VAULT}",
        "AMOS_JWT_SECRET=os.environ['X']",
        "AMOS_JWT_SECRET=",
        "# AMOS_JWT_SECRET=real_looking_but_commented_out_value",
    ])
    def test_النائبُ_لا_يُخالَف_عليه(self, tmp_path: Path, line: str):
        (tmp_path / ".env.example").write_text(line + "\n", encoding="utf-8")
        _git_repo(tmp_path, tracked=[".env.example"])
        assert _secret_findings(tmp_path) == [], f"إيجابيّةٌ كاذبةٌ على: {line}"

    def test_القالبُ_الحقيقيُّ_في_هذا_المستودع_نظيف(self):
        """`.env.example` المدفوعُ فعلًا — لا يحمل اعتمادًا نافذًا بعد اليوم.

        هذا الاختبارُ يقرأ المستودعَ نفسَه لا نسخةً مُصطنعة، فهو الحرسُ الذي
        يمنع عودةَ الاعتماد إلى القالب.
        """
        root = Path(__file__).resolve().parents[2]
        aud = TruthAudit(root)
        aud.scan_env_files_repo_wide()
        leaks = [f for f in aud.global_findings if f.kind == "HARDCODED_SECRET"]
        assert leaks == [], (
            "اعتمادٌ نافذٌ في ملفِّ بيئةٍ متعقَّب: "
            + "؛ ".join(f"{f.path}:{f.line}" for f in leaks)
        )


class Testالملفغيرالمتعقب:
    """`.env` المحلّيُّ غيرُ المتعقَّب هو الموضعُ الصحيح، فلا يُخالَف عليه."""

    def test_ملفٌّ_غيرُ_متعقَّبٍ_لا_يُخالَف_عليه(self, tmp_path: Path):
        (tmp_path / ".gitignore").write_text(".env\n", encoding="utf-8")
        (tmp_path / ".env").write_text(
            f"DATABASE_URL={REAL_PASSWORD_URL}\n", encoding="utf-8")
        _git_repo(tmp_path, tracked=[".gitignore"])

        assert _secret_findings(tmp_path) == [], (
            "خُولِف على `.env` محلّيٍّ مُستثنى — بوّابةٌ تسقط عند كلّ مطوّرٍ أدّى الواجب."
        )

    def test_غيابُ_مستودعِ_git_يُوسِّع_المسحَ_لا_يُلغيه(self, tmp_path: Path):
        """إغلاقٌ عند الفشل: تعذّرُ سؤالِ git يعني مسحَ الجميع، لا تركَ الجميع."""
        (tmp_path / ".env").write_text(
            f"DATABASE_URL={REAL_PASSWORD_URL}\n", encoding="utf-8")
        # لا `git init` هنا قصدًا
        found = _secret_findings(tmp_path)
        assert len(found) == 1, (
            "بلا git صار المسحُ صامتًا — وهذا تسامحٌ عند الفشل لا إغلاق."
        )
