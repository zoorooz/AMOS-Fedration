#!/usr/bin/env python3
"""قياسٌ حيٌّ لعدّاداتِ مصدرِ الحقيقة — بلا ثوابتَ وبلا ذاكرةٍ مؤقّتة.

الهدف: أن يكونَ لكلِّ إقليمٍ طريقٌ **واحدٌ** يقيسُ عدّاداتِه من قاعدةِ البياناتِ
       لحظةَ النداء، فإن لم يكن المصدرُ مُهيَّأً أعلنَ ذلك صريحًا بحالةِ
       `unmeasured` — فلا يُقال «ناجحٌ» عن شيءٍ لم يُقَس.
النطاق: قراءةُ عدّاداتٍ فقط (`select count(*)`) من جداولَ مُصرَّحٍ بأسمائِها،
       وقراءةُ لَقطةٍ مُؤرَّخةٍ من `docs/audit/measurements/`. لا كتابةَ ولا حكمَ
       دستوريًّا ولا تبعيّةً خارجيّةً لازمة: مُحرّكُ sqlite من المكتبةِ القياسيّة،
       وsqlalchemy يُستورَدُ عندَ الحاجةِ فقط (بوّابةُ الدخانِ في CI تعملُ ببايثون
       مُجرَّدٍ بلا تركيبِ حزم).
المالك: tools/audit
تاريخ الإنشاء: 2026-08-22
تاريخ آخر تعديل: 2026-08-22

القاعدةُ الحاكمةُ في هذا الملف (W-025):
    قِسْ الآن، أو أعلِنْ أنّك لم تَقِس. الثالثُ — أن تنسخَ رقمًا قديمًا وتُسمِّيَه
    نجاحًا — هو ما رصدَه محرِّكُ تدقيقِ الحقيقةِ بوصفِه `HARDCODED_TRUTH`.

الاستعمال:
    from tools.audit.live_truth import check_domain
    check_domain("tools", {"count": "tools"})

    python tools/audit/live_truth.py --tables tools,institutions
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# ثوابتُ إعدادٍ (مسارات وأسماءُ متغيّراتِ بيئة) — ليست عدّاداتٍ ولا بياناتِ حقيقة
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_PATH = REPO_ROOT / "docs" / "audit" / "measurements" / "domain_truth_snapshot.json"

# تُقرأُ بالترتيب؛ أوّلُ قيمةٍ غيرِ فارغةٍ هي رابطُ مصدرِ الحقيقة.
ENV_CANDIDATES = (
    "AMOS_TRUTH_DB_URL",
    "AMOS_SUPABASE_DB_URL",
    "AMOS_DATABASE_URL",
    "DATABASE_URL",
)

_SAFE_TABLE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_ISO_STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")


class SourceNotConfigured(RuntimeError):
    """لا مصدرَ حقيقةٍ قابلًا للقياسِ الآن — يُعلَنُ ولا يُبتلَع."""


# ---------------------------------------------------------------------------
# طبقةُ القياس
# ---------------------------------------------------------------------------


def source_url() -> str:
    """يُعيدُ رابطَ قاعدةِ البياناتِ من البيئة، أو يرفعُ `SourceNotConfigured`."""
    for key in ENV_CANDIDATES:
        value = os.environ.get(key, "").strip()
        if value:
            return value
    raise SourceNotConfigured(
        "لا مُتغيّرَ بيئةٍ يحملُ رابطَ قاعدةِ البيانات (" + " / ".join(ENV_CANDIDATES) + ")"
    )


def _validate_tables(tables) -> tuple[str, ...]:
    ordered = tuple(dict.fromkeys(tables))
    for table in ordered:
        if not _SAFE_TABLE.match(table):
            raise ValueError(f"اسمُ جدولٍ غيرُ مقبولٍ للقياس: {table!r}")
    return ordered


def _sqlite_path(url: str) -> str:
    tail = url.split("://", 1)[1] if "://" in url else url
    if tail.startswith("///"):
        tail = tail[2:]
    return tail or ":memory:"


def _measure_sqlite(url: str, tables: tuple[str, ...]) -> dict[str, int]:
    counted: dict[str, int] = {}
    with sqlite3.connect(_sqlite_path(url)) as conn:
        for table in tables:
            row = conn.execute(f'select count(*) from "{table}"').fetchone()
            counted[table] = int(row[0])
    return counted


def _measure_sqlalchemy(url: str, tables: tuple[str, ...]) -> dict[str, int]:
    try:
        from sqlalchemy import create_engine, text  # noqa: PLC0415
    except ModuleNotFoundError as exc:  # المحرّكُ غيرُ مُركَّبٍ في هذه البيئة
        raise SourceNotConfigured(
            f"مُحرّكُ الاتصالِ غيرُ مُركَّبٍ في هذه البيئة: {exc.name}"
        ) from exc

    counted: dict[str, int] = {}
    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            for table in tables:
                counted[table] = int(conn.execute(text(f'select count(*) from "{table}"')).scalar_one())
    finally:
        engine.dispose()
    return counted


def measure_tables(tables) -> tuple[dict[str, int], str]:
    """يقيسُ عددَ صفوفِ كلِّ جدولٍ الآن. يُعيدُ (العدّادات، اسمَ المحرّك)."""
    url = source_url()
    ordered = _validate_tables(tables)
    if url.startswith("sqlite"):
        return _measure_sqlite(url, ordered), "sqlite"
    return _measure_sqlalchemy(url, ordered), "sqlalchemy"


# ---------------------------------------------------------------------------
# طبقةُ اللَقطةِ المُؤرَّخة — تُقتبَسُ عندَ العجزِ عن القياس، ولا تُسمّى نجاحًا
# ---------------------------------------------------------------------------


def load_snapshot() -> dict:
    """يقرأُ اللَقطةَ المُؤرَّخة؛ يُعيدُ قاموسًا فارغًا إن لم تكن موجودة."""
    if not SNAPSHOT_PATH.is_file():
        return {}
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


def _age_days(stamp: str) -> int | None:
    """عمرُ اللَقطةِ بالأيّام. يُعيدُ None إن لم يكن الطابعُ بصيغةٍ زمنيّةٍ أصلًا.

    لا يُبتلَعُ هنا خطأٌ: الصيغةُ تُفحَصُ قبلَ التحويل، وأيُّ فشلٍ بعدَ الفحصِ يُرفَعُ
    كما هو ليظهرَ لا ليُخفى.
    """
    if not _ISO_STAMP.match(stamp or ""):
        return None
    then = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - then).days


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# واجهةُ الأقاليم
# ---------------------------------------------------------------------------


def check_domain(domain: str, aliases: dict[str, str], note: str | None = None) -> dict:
    """يقيسُ عدّاداتِ إقليمٍ الآن ويُعيدُ نتيجةً مُصرَّحةَ المصدر.

    Args:
        domain: اسمُ الإقليم.
        aliases: مفتاحُ التقرير -> اسمُ الجدولِ في قاعدةِ البيانات.
        note: ملاحظةٌ اختياريّةٌ تُضافُ إلى النتيجة.

    Returns:
        dict فيه `status`:
          - `pass`        قِيسَ الآنَ من قاعدةِ البيانات (`source` = live:*).
          - `unmeasured`  لا مصدرَ مُهيَّأً؛ الأرقامُ مُقتبَسةٌ من لَقطةٍ مُؤرَّخة.
          - `fail`        المصدرُ مُهيَّأٌ وفشلَ القياسُ (الخطأُ مذكورٌ في `reason`).
    """
    tables = tuple(aliases.values())
    result: dict = {"domain": domain}
    try:
        counted, engine = measure_tables(tables)
    except SourceNotConfigured as exc:
        snapshot = load_snapshot()
        rows = snapshot.get("row_counts", {})
        stamp = snapshot.get("measured_at", "")
        result.update(
            {
                "status": "unmeasured",
                "source": f"snapshot:{stamp}" if stamp else "snapshot:غير موجودة",
                "reason": str(exc),
                "snapshot_measured_at": stamp or None,
                "snapshot_age_days": _age_days(stamp) if stamp else None,
            }
        )
        for alias, table in aliases.items():
            result[alias] = rows.get(table)
    except Exception as exc:  # noqa: BLE001 — المصدرُ مُهيَّأٌ وفشل: فشلٌ مُعلَن
        result.update({"status": "fail", "source": "live", "reason": f"{type(exc).__name__}: {exc}"})
        for alias in aliases:
            result[alias] = None
    else:
        result.update({"status": "pass", "source": f"live:{engine}", "measured_at": _now()})
        for alias, table in aliases.items():
            result[alias] = counted[table]
    if note:
        result["note"] = note
    return result


def main(argv: list[str] | None = None) -> int:
    """قياسٌ يدويٌّ من سطرِ الأوامر: `--tables a,b,c`."""
    import argparse  # noqa: PLC0415

    parser = argparse.ArgumentParser(description="قياسُ عدّاداتِ جداولَ من مصدرِ الحقيقة")
    parser.add_argument("--tables", required=True, help="أسماءُ جداولٍ مفصولةٌ بفواصل")
    args = parser.parse_args(argv)
    wanted = [t.strip() for t in args.tables.split(",") if t.strip()]
    try:
        counted, engine = measure_tables(wanted)
    except SourceNotConfigured as exc:
        print(f"غيرُ مقيس: {exc}")
        return 2
    print(json.dumps({"engine": engine, "row_counts": counted}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
