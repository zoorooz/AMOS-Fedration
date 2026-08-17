"""
AMOS-Federation Phase 16 — Production Security
الهدف: أمان الإنتاج — RBAC، Secret Vault، TLS، Rate Limiting، Kill Switch تحقق
النطاق: services/governance/security
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-15

المتطلبات:
  16.1: RBAC — أدوار وصلاحيات
  16.2: Secret Vault — أسرار مشفرة
  16.3: TLS/mTLS — شهادات
  16.4: Rate Limiting
  16.5: Audit Verification دوري
  16.6: Kill Switch تحقق من السلامة
  16.7: Policy Engine في الإنتاج
  16.8: Health Monitoring دوري
"""

import hashlib
import json
import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Column, DateTime, Integer, String, Text, create_engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from amos_federation.common.database import get_database_url
from amos_federation.common.persistent import PersistentAuditStore
from amos_federation.common.principal import DEFAULT_TENANT

_logger = logging.getLogger(__name__)


class SecurityBase(DeclarativeBase):
    pass


class RoleModel(SecurityBase):
    """16.1: RBAC roles."""

    __tablename__ = "security_roles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    role_id = Column(String, nullable=False, unique=True, index=True)
    name = Column(String, nullable=False)
    permissions = Column(Text, default="[]")  # JSON array
    level = Column(Integer, default=0)  # 0=public, 1=citizen, 2=agent, 3=official, 4=royal, 5=king
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


class UserSessionModel(SecurityBase):
    """جلسات المستخدمين."""

    __tablename__ = "security_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_token = Column(String, nullable=False, unique=True, index=True)
    username = Column(String, nullable=False)
    role_id = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    expires_at = Column(DateTime, nullable=True)
    ip_address = Column(String, nullable=True)
    # R6.1: مستأجر الجلسة. كان الجدول قبله بلا مستأجر إطلاقًا، فكان كل مبدأ
    # مُتحقَّق من جلسة يخرج إلى طبقة التخويل بمستأجر `default` — فلا عزل بين
    # جلستين مهما اختلف مستأجراهما. و`nullable=False` مقصود: جلسة بلا مستأجر
    # تُقرأ لاحقًا على أنها «أيّ مستأجر»، وذلك عكس المراد.
    tenant_id = Column(String, nullable=False, default=DEFAULT_TENANT, index=True)


class SecretVaultModel(SecurityBase):
    """16.2: Secret Vault — أسرار مشفرة."""

    __tablename__ = "security_secrets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    secret_key = Column(String, nullable=False, unique=True, index=True)
    encrypted_value = Column(Text, nullable=False)
    scope = Column(String, default="global")  # global, state-specific, agent-specific
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    rotated_at = Column(DateTime, nullable=True)


class RateLimitModel(SecurityBase):
    """16.4: Rate Limiting."""

    __tablename__ = "security_rate_limits"

    id = Column(Integer, primary_key=True, autoincrement=True)
    identifier = Column(String, nullable=False, index=True)  # ip or agent_id
    endpoint = Column(String, nullable=False)
    request_count = Column(Integer, default=1)
    window_start = Column(DateTime, default=lambda: datetime.now(UTC))
    last_request = Column(DateTime, default=lambda: datetime.now(UTC))


class TLSCertificateModel(SecurityBase):
    """16.3: TLS Certificates."""

    __tablename__ = "security_certificates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cert_id = Column(String, nullable=False, unique=True, index=True)
    common_name = Column(String, nullable=False)
    cert_hash = Column(String, nullable=False)
    issuer = Column(String, default="AMOS-CA")
    valid_from = Column(DateTime, default=lambda: datetime.now(UTC))
    valid_until = Column(DateTime, nullable=True)
    status = Column(String, default="active")  # active, expired, revoked


# الأدوار الافتراضية
DEFAULT_ROLES = [
    {"role_id": "public", "name": "عام", "permissions": ["read:public"], "level": 0},
    {
        "role_id": "citizen",
        "name": "مواطن",
        "permissions": ["read:public", "write:feedback"],
        "level": 1,
    },
    {
        "role_id": "agent",
        "name": "وكيل",
        "permissions": ["read:public", "write:tasks", "execute:tools"],
        "level": 2,
    },
    {
        "role_id": "official",
        "name": "مسؤول",
        "permissions": ["read:all", "write:tasks", "execute:tools", "manage:agents"],
        "level": 3,
    },
    {
        "role_id": "royal",
        "name": "ملكي",
        "permissions": ["read:all", "write:all", "execute:all", "manage:all"],
        "level": 4,
    },
    {"role_id": "king", "name": "المالك", "permissions": ["*"], "level": 5},
]


class RBACSystem:
    """16.1: Role-Based Access Control."""

    def __init__(self) -> None:
        self._engine = create_engine(
            get_database_url(),
            connect_args={"check_same_thread": False}
            if get_database_url().startswith("sqlite")
            else {},
        )
        SecurityBase.metadata.create_all(self._engine)
        self._migrate_session_tenant()
        self._Session = sessionmaker(bind=self._engine, autoflush=False, expire_on_commit=False)
        self._init_roles()

    def _migrate_session_tenant(self) -> None:
        """R6.1: أضف `security_sessions.tenant_id` إلى جدول قائم إن غاب.

        `create_all` تُنشئ الجداول المفقودة و**لا تُضيف أعمدة إلى جدول موجود**.
        ولا نطام هجرة (alembic) في المستودع، فقاعدة قائمة من قبل R6.1 كانت
        ستكسر كل استعلام جلسة بـ`OperationalError: no such column`. وهذا ليس
        توسيع نطاق بل شرط لأن تعمل الميزة على قاعدة قائمة.

        إضافية وحدها: `ADD COLUMN` لا تُسقط شيئًا ولا تُعيد بناء جدول، والصفوف
        القائمة تأخذ `default` — وهو وصفٌ صادق لها: أُنشئت حين لم يكن للنشر
        إلا مستأجر واحد.
        """
        try:
            inspector = inspect(self._engine)
            if "security_sessions" not in inspector.get_table_names():
                return
            columns = {column["name"] for column in inspector.get_columns("security_sessions")}
            if "tenant_id" in columns:
                return
            with self._engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE security_sessions "
                        f"ADD COLUMN tenant_id VARCHAR DEFAULT '{DEFAULT_TENANT}'"
                    )
                )
                connection.execute(
                    text(
                        "UPDATE security_sessions "
                        f"SET tenant_id = '{DEFAULT_TENANT}' WHERE tenant_id IS NULL"
                    )
                )
        except SQLAlchemyError as exc:
            # الهجرة محاولة حسنة النيّة: فشلها يظهر فورًا عند أول استعلام جلسة
            # بخطأ واضح، ولا يُسكَت عنه بإدراج مستأجر وهمي. وإسقاط النظام كلّه
            # عند الإنشاء لأجل قاعدة لا تدعم ALTER أقسى من اللازم.
            # لكنه يُسجَّل: الفشلُ الصامت مخالفةٌ في ذاته.
            _logger.warning("تعذّرت هجرةُ tenant_id لجداول الأمن — %s", exc)

    def _init_roles(self) -> None:
        session = self._Session()
        try:
            for role in DEFAULT_ROLES:
                existing = (
                    session.query(RoleModel).filter(RoleModel.role_id == role["role_id"]).first()
                )
                if not existing:
                    session.add(
                        RoleModel(
                            role_id=role["role_id"],
                            name=role["name"],
                            permissions=json.dumps(role["permissions"]),
                            level=role["level"],
                        )
                    )
            session.commit()
        finally:
            session.close()

    def create_session(
        self,
        username: str,
        role_id: str,
        ip: str = "",
        *,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        """إنشاء جلسة مستخدم.

        Args:
            tenant_id: مستأجر الجلسة. يُملأ عند المصادقة من مصدر موثوق
                (سجلّ المستخدمين أو مُوفّر الهوية)، لا من جسم طلب تسجيل الدخول.
                وغيابه يعني `default` تحديدًا، لا «أيّ مستأجر».
        """
        session = self._Session()
        try:
            role = session.query(RoleModel).filter(RoleModel.role_id == role_id).first()
            if not role:
                return {"error": "role_not_found"}
            token = hashlib.sha256(f"{username}:{role_id}:{uuid.uuid4().hex}".encode()).hexdigest()
            from datetime import timedelta

            user_session = UserSessionModel(
                session_token=token,
                username=username,
                role_id=role_id,
                ip_address=ip,
                tenant_id=(tenant_id or DEFAULT_TENANT),
                expires_at=datetime.now(UTC) + timedelta(hours=24),
            )
            session.add(user_session)
            session.commit()
            return {
                "session_token": token,
                "username": username,
                "role_id": role_id,
                "level": role.level,
                "tenant_id": (tenant_id or DEFAULT_TENANT),
            }
        finally:
            session.close()

    def check_permission(self, session_token: str, permission: str) -> bool:
        """فحص صلاحية — والجلسة المنتهية لا صلاحية لها.

        كانت هذه الدالّة قبل R6 لا تنظر إلى `expires_at` إطلاقًا، فجلسة انتهت
        منذ شهر تمرّ كأنها حيّة. أُضيف الفحص: انتهاء الجلسة رفضٌ لا تحذير.
        """
        session = self._Session()
        try:
            user_session = (
                session.query(UserSessionModel)
                .filter(UserSessionModel.session_token == session_token)
                .first()
            )
            if not user_session:
                return False
            expires_at = user_session.expires_at
            if expires_at is not None:
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=UTC)
                if expires_at <= datetime.now(UTC):
                    return False
            role = (
                session.query(RoleModel).filter(RoleModel.role_id == user_session.role_id).first()
            )
            if not role:
                return False
            permissions = json.loads(role.permissions or "[]")
            if "*" in permissions:
                return True
            return permission in permissions
        finally:
            session.close()

    def get_role_level(self, role_id: str) -> int:
        """مستوى الدور."""
        session = self._Session()
        try:
            role = session.query(RoleModel).filter(RoleModel.role_id == role_id).first()
            return role.level if role else 0
        finally:
            session.close()

    def list_roles(self) -> list[dict[str, Any]]:
        session = self._Session()
        try:
            roles = session.query(RoleModel).all()
            return [
                {
                    "role_id": r.role_id,
                    "name": r.name,
                    "permissions": json.loads(r.permissions or "[]"),
                    "level": r.level,
                }
                for r in roles
            ]
        finally:
            session.close()


class SecretVault:
    """16.2: Secret Vault — أسرار مشفرة بـ SHA-256."""

    def __init__(self) -> None:
        self._engine = create_engine(
            get_database_url(),
            connect_args={"check_same_thread": False}
            if get_database_url().startswith("sqlite")
            else {},
        )
        SecurityBase.metadata.create_all(self._engine)
        self._Session = sessionmaker(bind=self._engine, autoflush=False, expire_on_commit=False)

    def _encrypt(self, value: str) -> str:
        """تشفير بسيط — SHA-256 hash (في الإنتاج: AES-256)."""
        salt = os.environ.get("AMOS_VAULT_SALT", "amos-federation-salt")
        return hashlib.sha256(f"{salt}:{value}".encode()).hexdigest()

    def store_secret(self, key: str, value: str, scope: str = "global") -> dict[str, Any]:
        session = self._Session()
        try:
            existing = (
                session.query(SecretVaultModel).filter(SecretVaultModel.secret_key == key).first()
            )
            if existing:
                existing.encrypted_value = self._encrypt(value)
                existing.scope = scope
                existing.rotated_at = datetime.now(UTC)
            else:
                session.add(
                    SecretVaultModel(
                        secret_key=key,
                        encrypted_value=self._encrypt(value),
                        scope=scope,
                    )
                )
            session.commit()
            audit = PersistentAuditStore()
            audit.append("security.secret_stored", "system", {"key": key, "scope": scope})
            return {"key": key, "scope": scope, "stored": True}
        finally:
            session.close()

    def verify_secret(self, key: str, value: str) -> bool:
        session = self._Session()
        try:
            secret = (
                session.query(SecretVaultModel).filter(SecretVaultModel.secret_key == key).first()
            )
            if not secret:
                return False
            return secret.encrypted_value == self._encrypt(value)
        finally:
            session.close()

    def list_secrets(self) -> list[dict[str, Any]]:
        session = self._Session()
        try:
            secrets = session.query(SecretVaultModel).all()
            return [{"key": s.secret_key, "scope": s.scope} for s in secrets]
        finally:
            session.close()


class RateLimiter:
    """16.4: Rate Limiting — منع الإفراط في الطلبات."""

    def __init__(self) -> None:
        self._engine = create_engine(
            get_database_url(),
            connect_args={"check_same_thread": False}
            if get_database_url().startswith("sqlite")
            else {},
        )
        SecurityBase.metadata.create_all(self._engine)
        self._Session = sessionmaker(bind=self._engine, autoflush=False, expire_on_commit=False)

    def check_rate(
        self, identifier: str, endpoint: str, max_requests: int = 100, window_minutes: int = 1
    ) -> dict[str, Any]:
        """فحص معدل الطلبات."""
        session = self._Session()
        try:
            from datetime import timedelta

            window_start = datetime.now(UTC) - timedelta(minutes=window_minutes)
            record = (
                session.query(RateLimitModel)
                .filter(
                    RateLimitModel.identifier == identifier,
                    RateLimitModel.endpoint == endpoint,
                    RateLimitModel.window_start >= window_start,
                )
                .first()
            )

            if record:
                if record.request_count >= max_requests:
                    return {"allowed": False, "count": record.request_count, "max": max_requests}
                record.request_count += 1
                record.last_request = datetime.now(UTC)
                session.commit()
                return {"allowed": True, "count": record.request_count, "max": max_requests}
            else:
                session.add(
                    RateLimitModel(
                        identifier=identifier,
                        endpoint=endpoint,
                        request_count=1,
                        window_start=datetime.now(UTC),
                    )
                )
                session.commit()
                return {"allowed": True, "count": 1, "max": max_requests}
        finally:
            session.close()


class TLSCertManager:
    """16.3: TLS Certificate Management."""

    def __init__(self) -> None:
        self._engine = create_engine(
            get_database_url(),
            connect_args={"check_same_thread": False}
            if get_database_url().startswith("sqlite")
            else {},
        )
        SecurityBase.metadata.create_all(self._engine)
        self._Session = sessionmaker(bind=self._engine, autoflush=False, expire_on_commit=False)

    def issue_certificate(self, common_name: str, validity_days: int = 365) -> dict[str, Any]:
        from datetime import timedelta

        cert_id = f"cert-{uuid.uuid4().hex[:10]}"
        cert_hash = hashlib.sha256(f"{common_name}:{cert_id}".encode()).hexdigest()
        session = self._Session()
        try:
            cert = TLSCertificateModel(
                cert_id=cert_id,
                common_name=common_name,
                cert_hash=cert_hash,
                valid_until=datetime.now(UTC) + timedelta(days=validity_days),
            )
            session.add(cert)
            session.commit()
            audit = PersistentAuditStore()
            audit.append("security.cert_issued", "system", {"cert_id": cert_id, "cn": common_name})
            return {
                "cert_id": cert_id,
                "common_name": common_name,
                "valid_until": str(cert.valid_until),
            }
        finally:
            session.close()

    def verify_certificate(self, cert_id: str) -> dict[str, Any]:
        session = self._Session()
        try:
            cert = (
                session.query(TLSCertificateModel)
                .filter(TLSCertificateModel.cert_id == cert_id)
                .first()
            )
            if not cert:
                return {"valid": False, "reason": "not_found"}
            if cert.status != "active":
                return {"valid": False, "reason": cert.status}
            if cert.valid_until:
                valid_until = cert.valid_until
                if valid_until.tzinfo is None:
                    valid_until = valid_until.replace(tzinfo=UTC)
                if datetime.now(UTC) > valid_until:
                    cert.status = "expired"
                    session.commit()
                    return {"valid": False, "reason": "expired"}
            return {"valid": True, "cert_id": cert_id, "common_name": cert.common_name}
        finally:
            session.close()


# Singletons
_rbac: RBACSystem | None = None
_vault: SecretVault | None = None
_limiter: RateLimiter | None = None
_tls: TLSCertManager | None = None


def get_rbac() -> RBACSystem:
    global _rbac
    if _rbac is None:
        _rbac = RBACSystem()
    return _rbac


def get_secret_vault() -> SecretVault:
    global _vault
    if _vault is None:
        _vault = SecretVault()
    return _vault


def get_rate_limiter() -> RateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = RateLimiter()
    return _limiter


def get_tls_manager() -> TLSCertManager:
    global _tls
    if _tls is None:
        _tls = TLSCertManager()
    return _tls
