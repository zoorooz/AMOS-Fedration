"""الهدف: تنصيب التاج وحفظ مفتاحه العام والتحقق التعميّ من هوية الملك.

المالك: core/sovereignty/ — التاج
تاريخ الإنشاء: 2026-08-16
تاريخ آخر تعديل: 2026-08-16

المفتاح الخاص للملك لا يُحفَظ في المستودع ولا في أي نظام تشغيلي للدولة، بأي حال
(المادة العاشرة · 6 · 3). هذه الوحدة تعرف المفتاح العام فقط.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

_LOG = logging.getLogger("amos.sovereignty.crown")

_REPO_ROOT = Path(__file__).resolve().parents[2]
CROWN_KEYS_PATH = _REPO_ROOT / "royal" / "crown" / "CROWN_KEYS.json"
ENROLLMENT_CHALLENGE_PATH = _REPO_ROOT / "royal" / "crown" / "ENROLLMENT_CHALLENGE.json"

# ── أصلُ الجذر ───────────────────────────────────────────────────────────────
#
# الفرقُ بين الأصلين ليس تفصيلًا إجرائيًّا بل هو الفرقُ بين دولةٍ جذرُها بشرٌ
# ودولةٍ جذرُها نفسُها. فإن ولّدتِ الدولةُ مفتاحَ الملك فقد **رأتْه**، ووعدُ
# «لا يُحفَظ في أي نظام تشغيليّ للدولة» يصير وعدًا إجرائيًّا لا ضمانًا تقنيًّا.
ROOT_EXTERNAL_HUMAN = "EXTERNAL_HUMAN_ROOT"   # وُلِّد خارج الدولة — الملكُ وحده رآه
ROOT_STATE_GENERATED = "STATE_GENERATED"      # ولّدته الدولة — ليس جذرًا بشريًّا

# فصلُ المجال: توقيعٌ صُنع لغرضٍ آخرَ لا يصلح تنسيبًا، ولو كان بمفتاحِ الملك.
ENROLLMENT_DOMAIN = b"AMOS-FEDERATION/CROWN-ENROLLMENT/v1"
DEFAULT_CHALLENGE_TTL_SECONDS = 3600


class CrownError(Exception):
    """خطأ في شؤون التاج."""


class CrownNotProvisionedError(CrownError):
    """التاج غير مُنصَّب — الاختصاص الملكي مُجمَّد لا منقول (المادة العاشرة · 6 · 2)."""


class CrownTamperError(CrownError):
    """سجل مفاتيح التاج معبوث به."""


class CrownEnrollmentError(CrownError):
    """خلل في مراسم تنسيب الجذر البشريّ."""


class CrownImpersonationError(CrownEnrollmentError):
    """إثباتُ الحيازة أخفق — من يطلب التنسيب لا يملك المفتاح الخاصّ.

    وهذا **حدثٌ أمنيّ** لا نتيجةُ فحصٍ عادية: من يقدّم مفتاحًا عامًّا لا يملك
    خاصَّه يحاول أن يجعل نفسه تاجَ الدولة.
    """


@dataclass(frozen=True, slots=True)
class Crown:
    """التاج المُنصَّب: هوية الملك ومفتاحه العام."""

    key_id: str
    public_key_hex: str
    provisioned_at: str
    holder: str
    root_origin: str = ROOT_STATE_GENERATED

    @property
    def is_external_human_root(self) -> bool:
        """هل الجذرُ بشريٌّ خارجَ الدولة؟ الافتراضُ **لا** حتى يُثبَت.

        وافتراضُ الأسوأ هنا مقصود: سجلٌّ قديمٌ بلا حقلِ أصلٍ لا يُمنَح صفةَ
        الجذرِ البشريِّ بالسكوت.
        """
        return self.root_origin == ROOT_EXTERNAL_HUMAN

    @property
    def public_key(self) -> ed25519.Ed25519PublicKey:
        try:
            raw = bytes.fromhex(self.public_key_hex)
        except ValueError as exc:
            raise CrownTamperError(f"مفتاح التاج العام غير صالح: {exc}") from exc
        if len(raw) != 32:
            raise CrownTamperError(
                f"طول مفتاح Ed25519 يجب أن يكون 32 بايت، وُجد {len(raw)}."
            )
        return ed25519.Ed25519PublicKey.from_public_bytes(raw)

    def verify(self, message: bytes, signature: bytes) -> bool:
        """تحقق تعميّ حقيقي من توقيع الملك.

        فشل التحقق حدث أمني — محاولة انتحال صفة ملكية — فيُسجَّل ولا يُبتلع.
        """
        try:
            self.public_key.verify(signature, message)
        except InvalidSignature as exc:
            _LOG.warning(
                "فشل تحقق توقيع ملكي مقابل مفتاح التاج «%s»: %s — "
                "محاولة انتحال صفة ملكية محتملة.",
                self.key_id,
                exc.__class__.__name__,
            )
            return False
        return True


def _read_registry(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CrownTamperError(f"سجل مفاتيح التاج غير قابل للقراءة: {exc}") from exc
    if not isinstance(data, dict):
        raise CrownTamperError("سجل مفاتيح التاج يجب أن يكون كائن JSON.")
    return data


def load_crown(path: Path | None = None) -> Crown:
    """حمّل التاج المُنصَّب، أو ارفع CrownNotProvisionedError.

    الرفض هو الافتراض: أي نقص في السجل يُعامَل كعدم تنصيب، لا كتنصيب جزئي.
    """
    keys_path = path or CROWN_KEYS_PATH
    if not keys_path.exists():
        raise CrownNotProvisionedError(
            f"التاج غير مُنصَّب: لا يوجد {keys_path}. "
            "الاختصاص الملكي الحصري مُجمَّد ولا يُمنَح لأي طرف آخر."
        )
    data = _read_registry(keys_path)
    if data.get("status") != "provisioned":
        raise CrownNotProvisionedError(
            f"التاج غير مُنصَّب: الحالة «{data.get('status')}». "
            "الاختصاص الملكي الحصري مُجمَّد."
        )
    active_id = data.get("active_key_id")
    keys = data.get("keys")
    if not active_id or not isinstance(keys, list):
        raise CrownTamperError("سجل مفاتيح التاج ناقص: يلزم active_key_id و keys.")
    for entry in keys:
        if isinstance(entry, dict) and entry.get("key_id") == active_id:
            if entry.get("revoked"):
                raise CrownNotProvisionedError(
                    f"مفتاح التاج النشط «{active_id}» مسحوب. التاج غير مُنصَّب."
                )
            public_key_hex = entry.get("public_key_hex")
            if not isinstance(public_key_hex, str) or not public_key_hex:
                raise CrownTamperError(f"المفتاح «{active_id}» بلا مفتاح عام.")
            return Crown(
                key_id=active_id,
                public_key_hex=public_key_hex,
                provisioned_at=str(entry.get("provisioned_at", "")),
                holder=str(entry.get("holder", "الملك")),
                root_origin=str(entry.get("root_origin", ROOT_STATE_GENERATED)),
            )
    raise CrownTamperError(
        f"المفتاح النشط «{active_id}» غير موجود في سجل المفاتيح."
    )


def crown_is_provisioned(path: Path | None = None) -> bool:
    """هل التاج مُنصَّب؟ لا يرفع استثناءً — لكن السبب يُسجَّل ولا يُبتلع."""
    try:
        load_crown(path)
    except CrownError as exc:
        _LOG.info("التاج غير متاح: %s", exc)
        return False
    return True


def provision_crown(
    private_key_out: Path,
    *,
    holder: str = "الملك",
    key_id: str | None = None,
    registry_path: Path | None = None,
) -> Crown:
    """مراسم تنصيبٍ **تُولِّدها الدولةُ نفسُها** — ليست جذرًا بشريًّا.

    يرفض الكتابة داخل المستودع (المادة العاشرة · 6 · 3)، ويرفض استبدال تاج
    مُنصَّب (المادة العاشرة · 3 · 1 — replace_crown_key).

    **حدٌّ مُعلَنٌ لا يُتجمَّل:** المفتاحُ الخاصُّ يُولَّد هنا داخل عمليةٍ من
    عمليات الدولة، فالدولةُ **رأتْه**. ونقلُه إلى حرزِ الملكِ بعد ذلك إجراءٌ
    بشريٌّ لا ضمانٌ تقنيّ. ولذلك يُوسَم السجلُّ بـ `STATE_GENERATED`، ويظلّ هذا
    المسارُ للاختبارِ والإثباتِ الصناعيّ لا لتنصيبِ دولةٍ حقيقيّة. والمسارُ
    السياديُّ هو `enroll_crown` — جذرٌ يُولَد خارج الدولة ولا تراه.
    """
    keys_path = registry_path or CROWN_KEYS_PATH
    private_key_out = private_key_out.expanduser().resolve()

    if private_key_out.is_relative_to(_REPO_ROOT):
        raise CrownError(
            "المفتاح الخاص للملك لا يُحفَظ داخل المستودع بأي حال "
            f"(المادة العاشرة · 6 · 3). المسار المرفوض: {private_key_out}"
        )

    if crown_is_provisioned(keys_path):
        raise CrownError(
            "التاج مُنصَّب بالفعل. استبدال مفتاح التاج فعل ممنوع "
            "(المادة العاشرة · 3 · 1 — replace_crown_key)."
        )

    private_key = ed25519.Ed25519PrivateKey.generate()
    public_hex = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        .hex()
    )
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    resolved_key_id = key_id or f"crown-{now[:10]}"

    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    private_key_out.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(private_key_out), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(pem)
        handle.flush()
        os.fsync(handle.fileno())

    registry = {
        "_note": (
            "سجل مفاتيح التاج. المفتاح العام فقط. "
            "المفتاح الخاص للملك لا يُحفَظ في المستودع (المادة العاشرة · 6 · 3)."
        ),
        "status": "provisioned",
        "root_origin": ROOT_STATE_GENERATED,
        "active_key_id": resolved_key_id,
        "keys": [
            {
                "key_id": resolved_key_id,
                "holder": holder,
                "algorithm": "Ed25519",
                "public_key_hex": public_hex,
                "provisioned_at": now,
                "revoked": False,
                "root_origin": ROOT_STATE_GENERATED,
            }
        ],
    }
    keys_path.parent.mkdir(parents=True, exist_ok=True)
    keys_path.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return load_crown(keys_path)


# ── مراسمُ الجذرِ البشريّ: تحدٍّ ثمّ إثباتُ حيازة ─────────────────────────────
#
# الدولةُ لا تُولّد مفتاحَ الملك ولا تراه ولا تنقله. هي تُصدر **تحدّيًا**، والملكُ
# يوقّعه بجهازِه هو خارجَ الدولة، ثمّ تُنسِّب الدولةُ **المفتاحَ العامَّ وحده** بعد
# أن تتحقّق تعميًّا أن مُقدِّمَه يملك خاصَّه. وبهذا يصير الوعدُ ضمانًا بنيويًّا:
# ما لم تره الدولةُ قطُّ لا يمكن أن تُسرِّبه.


@dataclass(frozen=True, slots=True)
class EnrollmentChallenge:
    """تحدٍّ لمرّةٍ واحدة: نصٌّ يوقّعه الملكُ ليُثبت حيازةَ مفتاحِه."""

    challenge_id: str
    nonce_hex: str
    issued_at: str
    expires_at: str
    consumed_at: str | None = None

    @property
    def message(self) -> bytes:
        """البايتاتُ التي يقع عليها توقيعُ الملك — بفصلِ مجالٍ صريح."""
        return b"|".join((
            ENROLLMENT_DOMAIN,
            self.challenge_id.encode("utf-8"),
            self.nonce_hex.encode("utf-8"),
            self.expires_at.encode("utf-8"),
        ))

    def is_expired(self, *, now: datetime | None = None) -> bool:
        moment = now or datetime.now(timezone.utc)
        return moment > datetime.fromisoformat(self.expires_at)

    def as_dict(self) -> dict[str, Any]:
        return {
            "_note": (
                "تحدّي تنسيب الجذر البشريّ. لا سرَّ هنا: النصُّ عامٌّ، والسرُّ "
                "هو مفتاح الملك الذي لا يدخل الدولةَ أصلًا."
            ),
            "challenge_id": self.challenge_id,
            "nonce_hex": self.nonce_hex,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "consumed_at": self.consumed_at,
            "message_hex": self.message.hex(),
        }


def _utc_now_iso(moment: datetime | None = None) -> str:
    return (moment or datetime.now(timezone.utc)).replace(microsecond=0).isoformat()


def issue_enrollment_challenge(
    *,
    ttl_seconds: int = DEFAULT_CHALLENGE_TTL_SECONDS,
    path: Path | None = None,
    now: datetime | None = None,
) -> EnrollmentChallenge:
    """أصدِر تحدّيًا جديدًا. يُستهلَك مرّةً واحدةً ولا يُعاد استعماله."""
    if ttl_seconds <= 0:
        raise CrownEnrollmentError("مدّةُ صلاحيةِ التحدّي يجب أن تكون موجبة.")
    moment = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    challenge = EnrollmentChallenge(
        challenge_id=f"enroll-{secrets.token_hex(8)}",
        nonce_hex=secrets.token_hex(32),
        issued_at=_utc_now_iso(moment),
        expires_at=_utc_now_iso(moment + timedelta(seconds=ttl_seconds)),
    )
    target = path or ENROLLMENT_CHALLENGE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(challenge.as_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return challenge


def load_enrollment_challenge(path: Path | None = None) -> EnrollmentChallenge:
    """اقرأ التحدّي القائم، أو ارفع خطأً. الغيابُ ليس سماحًا."""
    target = path or ENROLLMENT_CHALLENGE_PATH
    if not target.exists():
        raise CrownEnrollmentError(
            f"لا تحدّيَ قائمًا في {target}. "
            "أصدِر تحدّيًا أوّلًا: python -m core.sovereignty.cli crown-challenge"
        )
    data = _read_registry(target)
    missing = [k for k in ("challenge_id", "nonce_hex", "issued_at", "expires_at")
               if not data.get(k)]
    if missing:
        raise CrownTamperError(f"تحدّي التنسيب ناقصُ الحقول: {', '.join(missing)}")
    return EnrollmentChallenge(
        challenge_id=str(data["challenge_id"]),
        nonce_hex=str(data["nonce_hex"]),
        issued_at=str(data["issued_at"]),
        expires_at=str(data["expires_at"]),
        consumed_at=data.get("consumed_at") or None,
    )


def _validated_public_key(public_key_hex: str) -> ed25519.Ed25519PublicKey:
    try:
        raw = bytes.fromhex(public_key_hex)
    except ValueError as exc:
        raise CrownEnrollmentError(f"المفتاح العام ليس ستّ عشريًّا صالحًا: {exc}") from exc
    if len(raw) != 32:
        raise CrownEnrollmentError(
            f"مفتاح Ed25519 العام طولُه 32 بايت، وُجد {len(raw)}."
        )
    return ed25519.Ed25519PublicKey.from_public_bytes(raw)


def enroll_crown(
    public_key_hex: str,
    signature_hex: str,
    *,
    holder: str = "الملك",
    key_id: str | None = None,
    keystore_kind: str = "offline_human_device",
    witnesses: tuple[str, ...] = (),
    attestation_ref: str = "",
    challenge_path: Path | None = None,
    registry_path: Path | None = None,
    now: datetime | None = None,
) -> Crown:
    """نسِّب جذرًا بشريًّا خارجيًّا: المفتاحُ العامُّ وحدَه بعد إثباتِ الحيازة.

    لا تُولَّد هنا مادّةُ مفتاحٍ ولا تُقرأ ولا تُكتَب. والدولةُ ترفض ما لم يُثبِت
    مُقدِّمُه أنه يملك المفتاحَ الخاصَّ بتوقيعِ تحدٍّ حيٍّ غيرِ منتهٍ ولا مُستهلَك.
    """
    keys_path = registry_path or CROWN_KEYS_PATH
    if crown_is_provisioned(keys_path):
        raise CrownError(
            "التاج مُنصَّب بالفعل. استبدال مفتاح التاج فعل ممنوع "
            "(المادة العاشرة · 3 · 1 — replace_crown_key)."
        )

    challenge = load_enrollment_challenge(challenge_path)
    if challenge.consumed_at:
        raise CrownEnrollmentError(
            f"التحدّي «{challenge.challenge_id}» مُستهلَك في {challenge.consumed_at}. "
            "إعادةُ استعمالِ تحدٍّ بابُ إعادةِ تشغيلٍ مغلَق."
        )
    if challenge.is_expired(now=now):
        raise CrownEnrollmentError(
            f"التحدّي «{challenge.challenge_id}» انتهى في {challenge.expires_at}. "
            "أصدِر تحدّيًا جديدًا."
        )

    public_key = _validated_public_key(public_key_hex)
    try:
        signature = bytes.fromhex(signature_hex)
    except ValueError as exc:
        raise CrownEnrollmentError(f"التوقيع ليس ستّ عشريًّا صالحًا: {exc}") from exc

    try:
        public_key.verify(signature, challenge.message)
    except InvalidSignature as exc:
        _LOG.warning(
            "أخفق إثباتُ الحيازة في تنسيب التاج للتحدّي «%s» — "
            "محاولةُ انتحالِ جذرِ الدولة محتملة.",
            challenge.challenge_id,
        )
        raise CrownImpersonationError(
            "أخفق إثباتُ الحيازة: التوقيعُ لا يطابق المفتاحَ العامَّ المُقدَّم على "
            "تحدّي التنسيب. لا يُنسَّب جذرٌ لا يُثبِت حائزُه حيازتَه."
        ) from exc

    moment = _utc_now_iso(now)
    resolved_key_id = key_id or f"crown-{moment[:10]}"
    registry = {
        "_note": (
            "سجل مفاتيح التاج. المفتاح العام فقط. المفتاح الخاص للملك لم يدخل "
            "هذه الدولةَ قطُّ: وُلِّد خارجها ولم تره (المادة العاشرة · 6 · 3)."
        ),
        "status": "provisioned",
        "root_origin": ROOT_EXTERNAL_HUMAN,
        "active_key_id": resolved_key_id,
        "keys": [
            {
                "key_id": resolved_key_id,
                "holder": holder,
                "algorithm": "Ed25519",
                "public_key_hex": public_key_hex,
                "provisioned_at": moment,
                "revoked": False,
                "root_origin": ROOT_EXTERNAL_HUMAN,
                "provenance": {
                    "ceremony_id": challenge.challenge_id,
                    "ceremony_kind": "GENESIS_EXTERNAL_HUMAN_ROOT",
                    "keystore_kind": keystore_kind,
                    "attestation_ref": attestation_ref,
                    "witnesses": list(witnesses),
                    "proof_of_possession": "ed25519_challenge_signature",
                    "challenge_message_hex": challenge.message.hex(),
                    "signature_hex": signature_hex,
                },
            }
        ],
    }
    keys_path.parent.mkdir(parents=True, exist_ok=True)
    keys_path.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    consumed = challenge.as_dict()
    consumed["consumed_at"] = moment
    consumed["enrolled_key_id"] = resolved_key_id
    target = challenge_path or ENROLLMENT_CHALLENGE_PATH
    target.write_text(
        json.dumps(consumed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return load_crown(keys_path)
