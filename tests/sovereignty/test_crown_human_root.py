"""الهدف: قياسُ مراسمِ الجذرِ البشريِّ الخارجيّ — تنسيبُ مفتاحٍ عامٍّ بإثباتِ حيازة.

النطاق: `core/sovereignty/crown.py` — التحدّي، إثباتُ الحيازة، أصلُ الجذر، ومنعُ
الانتحالِ وإعادةِ التشغيل. بلا شبكةٍ ولا سجلٍّ حقيقيّ: كلُّ كتابةٍ في `tmp_path`.

المالك: core/sovereignty/ — التاج
تاريخ الإنشاء: 2026-08-18

**القاعدةُ الحاكمةُ لهذه الحزمة:** مفتاحُ الملكِ الخاصُّ يُولَّد هنا في متغيّرٍ
محلّيٍّ يمثّل **جهازَ الملكِ خارجَ الدولة**، ولا يُمرَّر إلى أيِّ دالّةٍ من دوالِّ
الدولة قطُّ. فإن مرّرَه أحدٌ يومًا سقطَ `test_الدولةُ_لا_تستقبل_مادّةَ_مفتاحٍ_خاصّ`.

ما لا تفحصه هذه الحزمة: أمنَ الجهازِ الذي يوقّع عليه الملك، وهو خارجَ مقدرةِ
البرمجيّةِ أصلًا ومُصرَّحٌ به في حدودِ `core/crown/`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from core.sovereignty import crown as crown_mod
from core.sovereignty.crown import (
    ROOT_EXTERNAL_HUMAN,
    ROOT_STATE_GENERATED,
    CrownEnrollmentError,
    CrownError,
    CrownImpersonationError,
    CrownTamperError,
    enroll_crown,
    issue_enrollment_challenge,
    load_crown,
    load_enrollment_challenge,
    provision_crown,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


class _KingDevice:
    """جهازُ الملكِ خارجَ الدولة. الدولةُ تصل إلى `public_key_hex` فقط."""

    def __init__(self) -> None:
        self._private = ed25519.Ed25519PrivateKey.generate()

    @property
    def public_key_hex(self) -> str:
        return (
            self._private.public_key()
            .public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
            .hex()
        )

    @property
    def private_key_hex(self) -> str:
        """لا تُمرَّر إلى الدولة. تُستعمل للتأكّد من **غيابِها** عمّا تكتبه."""
        return self._private.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        ).hex()

    def sign(self, message: bytes) -> str:
        return self._private.sign(message).hex()


@pytest.fixture
def ملك() -> _KingDevice:
    return _KingDevice()


@pytest.fixture
def مسارات(tmp_path: Path) -> dict[str, Path]:
    return {"تحدٍّ": tmp_path / "CH.json", "سجلّ": tmp_path / "KEYS.json"}


def _نسِّب(ملك: _KingDevice, مسارات: dict[str, Path], **kw: object):
    تحدٍّ = issue_enrollment_challenge(path=مسارات["تحدٍّ"])
    return enroll_crown(
        ملك.public_key_hex,
        ملك.sign(تحدٍّ.message),
        challenge_path=مسارات["تحدٍّ"],
        registry_path=مسارات["سجلّ"],
        **kw,  # type: ignore[arg-type]
    )


class Testالتحدّي:
    """التحدّي نصٌّ عامٌّ لمرّةٍ واحدة، بمجالٍ مفصولٍ وأجلٍ منتهٍ."""

    def test_التحدّيانِ_لا_يتطابقان(self, tmp_path: Path) -> None:
        أ = issue_enrollment_challenge(path=tmp_path / "a.json")
        ب = issue_enrollment_challenge(path=tmp_path / "b.json")
        assert أ.nonce_hex != ب.nonce_hex, "رقمٌ عارضٌ متكرّرٌ = تحدٍّ قابلٌ للتوقّع"
        assert أ.challenge_id != ب.challenge_id
        assert len(bytes.fromhex(أ.nonce_hex)) == 32

    def test_رسالةُ_التحدّي_تحمل_فصلَ_المجال(self, tmp_path: Path) -> None:
        """توقيعٌ صُنع لغرضٍ آخرَ لا يصلح تنسيبًا ولو كان بمفتاحِ الملك."""
        تحدٍّ = issue_enrollment_challenge(path=tmp_path / "a.json")
        assert تحدٍّ.message.startswith(crown_mod.ENROLLMENT_DOMAIN)
        assert تحدٍّ.nonce_hex.encode() in تحدٍّ.message
        assert تحدٍّ.expires_at.encode() in تحدٍّ.message

    def test_الغيابُ_ليس_سماحًا(self, tmp_path: Path) -> None:
        with pytest.raises(CrownEnrollmentError, match="لا تحدّيَ قائمًا"):
            load_enrollment_challenge(tmp_path / "لا-يوجد.json")

    def test_التحدّيُ_الناقصُ_عبثٌ_لا_تحدٍّ(self, tmp_path: Path) -> None:
        ملف = tmp_path / "ch.json"
        ملف.write_text('{"challenge_id": "x"}', encoding="utf-8")
        with pytest.raises(CrownTamperError, match="ناقصُ الحقول"):
            load_enrollment_challenge(ملف)

    def test_مدّةٌ_غيرُ_موجبةٍ_مرفوضة(self, tmp_path: Path) -> None:
        with pytest.raises(CrownEnrollmentError, match="موجبة"):
            issue_enrollment_challenge(ttl_seconds=0, path=tmp_path / "a.json")

    def test_الانتهاءُ_يُقاس_لا_يُفترَض(self, tmp_path: Path) -> None:
        تحدٍّ = issue_enrollment_challenge(ttl_seconds=60, path=tmp_path / "a.json")
        assert not تحدٍّ.is_expired()
        بعدُ = datetime.now(timezone.utc) + timedelta(seconds=120)
        assert تحدٍّ.is_expired(now=بعدُ)


class Testإثباتُالحيازة:
    """لا يُنسَّب جذرٌ لا يُثبِت حائزُه أنه يملك المفتاحَ الخاصّ."""

    def test_الملكُ_يُنسَّب_بتوقيعٍ_صحيح(self, ملك, مسارات) -> None:
        تاج = _نسِّب(ملك, مسارات, holder="الملك")
        assert تاج.public_key_hex == ملك.public_key_hex
        assert تاج.root_origin == ROOT_EXTERNAL_HUMAN
        assert تاج.is_external_human_root is True
        assert تاج.holder == "الملك"

    def test_المنتحِلُ_يُرَدُّ_بخطأٍ_أمنيٍّ_لا_بقيمةٍ_كاذبة(self, ملك, مسارات) -> None:
        """من يقدّم مفتاحَ غيرِه لا يصير تاجًا: يُرفَع خطأٌ ولا يُرجَع `False`."""
        منتحِل = _KingDevice()
        تحدٍّ = issue_enrollment_challenge(path=مسارات["تحدٍّ"])
        with pytest.raises(CrownImpersonationError, match="أخفق إثباتُ الحيازة"):
            enroll_crown(
                ملك.public_key_hex,
                منتحِل.sign(تحدٍّ.message),
                challenge_path=مسارات["تحدٍّ"],
                registry_path=مسارات["سجلّ"],
            )
        assert not مسارات["سجلّ"].exists(), "كُتب سجلٌّ رغم فشلِ الإثبات"

    def test_توقيعُ_مجالٍ_آخرَ_لا_يصلح_تنسيبًا(self, ملك, مسارات) -> None:
        issue_enrollment_challenge(path=مسارات["تحدٍّ"])
        with pytest.raises(CrownImpersonationError):
            enroll_crown(
                ملك.public_key_hex,
                ملك.sign(b"AMOS/SOME-OTHER-PURPOSE/v1|payload"),
                challenge_path=مسارات["تحدٍّ"],
                registry_path=مسارات["سجلّ"],
            )

    def test_التحدّيُ_يُستهلَك_مرّةً_واحدة(self, ملك, مسارات, tmp_path) -> None:
        _نسِّب(ملك, مسارات)
        تحدٍّ = load_enrollment_challenge(مسارات["تحدٍّ"])
        assert تحدٍّ.consumed_at, "التحدّي لم يُوسَم مُستهلَكًا"
        with pytest.raises(CrownEnrollmentError, match="مُستهلَك"):
            enroll_crown(
                ملك.public_key_hex,
                ملك.sign(تحدٍّ.message),
                challenge_path=مسارات["تحدٍّ"],
                registry_path=tmp_path / "آخر.json",
            )

    def test_التحدّيُ_المنتهي_مرفوض(self, ملك, مسارات) -> None:
        تحدٍّ = issue_enrollment_challenge(ttl_seconds=1, path=مسارات["تحدٍّ"])
        بعدُ = datetime.now(timezone.utc) + timedelta(hours=2)
        with pytest.raises(CrownEnrollmentError, match="انتهى"):
            enroll_crown(
                ملك.public_key_hex,
                ملك.sign(تحدٍّ.message),
                challenge_path=مسارات["تحدٍّ"],
                registry_path=مسارات["سجلّ"],
                now=بعدُ,
            )

    @pytest.mark.parametrize(
        ("مفتاح", "علّة"),
        [("zz" * 32, "ستّ عشريًّا"), ("ab" * 16, "32 بايت"), ("", "32 بايت")],
    )
    def test_المفتاحُ_العامُّ_المعيبُ_مرفوضٌ_قبل_أيِّ_كتابة(
        self, ملك, مسارات, مفتاح: str, علّة: str
    ) -> None:
        تحدٍّ = issue_enrollment_challenge(path=مسارات["تحدٍّ"])
        with pytest.raises(CrownEnrollmentError, match=علّة):
            enroll_crown(مفتاح, ملك.sign(تحدٍّ.message),
                         challenge_path=مسارات["تحدٍّ"],
                         registry_path=مسارات["سجلّ"])
        assert not مسارات["سجلّ"].exists()

    def test_التوقيعُ_غيرُ_الستّعشريِّ_مرفوض(self, ملك, مسارات) -> None:
        issue_enrollment_challenge(path=مسارات["تحدٍّ"])
        with pytest.raises(CrownEnrollmentError, match="التوقيع ليس"):
            enroll_crown(ملك.public_key_hex, "ليس-hex",
                         challenge_path=مسارات["تحدٍّ"],
                         registry_path=مسارات["سجلّ"])

    def test_لا_تنسيبَ_فوق_تاجٍ_قائم(self, ملك, مسارات) -> None:
        """استبدالُ مفتاحِ التاج فعلٌ ممنوع (المادة العاشرة · 3 · 1)."""
        _نسِّب(ملك, مسارات)
        آخر = _KingDevice()
        تحدٍّ = issue_enrollment_challenge(path=مسارات["تحدٍّ"])
        with pytest.raises(CrownError, match="مُنصَّب بالفعل"):
            enroll_crown(آخر.public_key_hex, آخر.sign(تحدٍّ.message),
                         challenge_path=مسارات["تحدٍّ"],
                         registry_path=مسارات["سجلّ"])
        assert load_crown(مسارات["سجلّ"]).public_key_hex == ملك.public_key_hex


class Testالدولةُلاترىالمفتاحَالخاصّ:
    """الضمانُ البنيويّ: ما لم ترَه الدولةُ قطُّ لا يمكن أن تُسرِّبه."""

    def test_الدولةُ_لا_تستقبل_مادّةَ_مفتاحٍ_خاصّ(self) -> None:
        """`enroll_crown` بلا معاملٍ يقبل مفتاحًا خاصًّا أو مسارَ ملفٍّ له."""
        import inspect

        معاملات = set(inspect.signature(enroll_crown).parameters)
        محرَّم = {"private_key", "private_key_out", "private_key_path",
                  "secret_key", "seed", "passphrase"}
        assert معاملات & محرَّم == set(), f"مادّةُ مفتاحٍ في الواجهة: {معاملات & محرَّم}"

    def test_السجلُّ_المكتوبُ_خالٍ_من_المفتاحِ_الخاصّ(self, ملك, مسارات) -> None:
        _نسِّب(ملك, مسارات)
        محتوى = مسارات["سجلّ"].read_text(encoding="utf-8")
        assert ملك.private_key_hex not in محتوى
        assert "PRIVATE KEY" not in محتوى
        assert ملك.public_key_hex in محتوى, "المفتاحُ العامُّ هو المقصودُ حفظُه"

    def test_مصدرُ_المفتاح_مُسجَّلٌ_لا_مسكوتٌ_عنه(self, ملك, مسارات) -> None:
        """لا مفتاحَ بلا سببٍ معلَن: مراسمُه وبيئتُه وشهودُه وإثباتُ حيازتِه."""
        import json

        _نسِّب(ملك, مسارات, witnesses=("شاهد-١", "شاهد-٢"),
              keystore_kind="offline_air_gapped")
        قيد = json.loads(مسارات["سجلّ"].read_text(encoding="utf-8"))["keys"][0]
        مصدر = قيد["provenance"]
        assert مصدر["ceremony_kind"] == "GENESIS_EXTERNAL_HUMAN_ROOT"
        assert مصدر["keystore_kind"] == "offline_air_gapped"
        assert مصدر["witnesses"] == ["شاهد-١", "شاهد-٢"]
        assert مصدر["proof_of_possession"] == "ed25519_challenge_signature"
        assert قيد["root_origin"] == ROOT_EXTERNAL_HUMAN

    def test_التاجُ_المُنسَّبُ_يتحقّق_من_توقيعٍ_لاحق(self, ملك, مسارات) -> None:
        """التنسيبُ ليس تسجيلًا شكليًّا: المفتاحُ المحفوظُ يعمل فعلًا."""
        تاج = _نسِّب(ملك, مسارات)
        رسالة = b"decree-payload-001"
        assert تاج.verify(رسالة, bytes.fromhex(ملك.sign(رسالة))) is True
        assert تاج.verify(b"decree-payload-002", bytes.fromhex(ملك.sign(رسالة))) is False


class Testأصلُالجذر:
    """التمييزُ بين جذرٍ بشريٍّ وجذرٍ ولّدتْه الدولةُ ليس تجميلًا."""

    def test_ما_ولّدته_الدولةُ_يُوسَم_بأصلِه(self, tmp_path: Path) -> None:
        سجلّ = tmp_path / "K.json"
        تاج = provision_crown(tmp_path / "خارج" / "k.pem", registry_path=سجلّ)
        assert تاج.root_origin == ROOT_STATE_GENERATED
        assert تاج.is_external_human_root is False

    def test_سجلٌّ_بلا_حقلِ_أصلٍ_لا_يُمنَح_صفةَ_الجذرِ_البشريِّ_بالسكوت(
        self, tmp_path: Path, ملك
    ) -> None:
        """افتراضُ الأسوأ: الغيابُ لا يُقرَأ إثباتًا."""
        import json

        سجلّ = tmp_path / "قديم.json"
        سجلّ.write_text(json.dumps({
            "status": "provisioned",
            "active_key_id": "قديم-1",
            "keys": [{"key_id": "قديم-1", "public_key_hex": ملك.public_key_hex}],
        }, ensure_ascii=False), encoding="utf-8")
        assert load_crown(سجلّ).is_external_human_root is False

    def test_الدولةُ_الحقيقيّةُ_إمّا_غيرُ_مُنصَّبةٍ_أو_جذرُها_بشريّ(self) -> None:
        """بوابةٌ على السجلِّ الحقيقيِّ نفسِه لا على نسخةٍ مؤقّتة."""
        if not crown_mod.crown_is_provisioned():
            pytest.skip("التاجُ غيرُ مُنصَّبٍ — وهذا هو الحالُ المُعلَن")
        assert load_crown().is_external_human_root, (
            "جذرُ الدولةِ ولّدتْه الدولةُ نفسُها — ليس جذرًا بشريًّا"
        )

    def test_المستودعُ_خالٍ_من_مادّةِ_مفتاحٍ_خاصّ(self) -> None:
        """فحصٌ على الشجرةِ الحقيقيّة: لا مفتاحَ خاصًّا مُودَعًا في الدولة."""
        # تُقرأ بايتاتٍ لا نصًّا: فلا حاجةَ إلى ابتلاعِ خطأِ ترميزٍ يُخفي ملفًّا
        # غيرَ مفحوص. وخطأُ القراءةِ يُترَك ليُسقِط الاختبارَ لا ليُبتلَع.
        ترويسة = b"PRIVATE KEY"
        مشبوهة = [
            str(مسار)
            for مسار in (REPO_ROOT / "royal").rglob("*")
            if مسار.is_file()
            and مسار.suffix != ".pyc"
            and ترويسة in مسار.read_bytes()
        ]
        assert مشبوهة == [], f"مادّةُ مفتاحٍ خاصٍّ داخل الدولة: {مشبوهة}"
