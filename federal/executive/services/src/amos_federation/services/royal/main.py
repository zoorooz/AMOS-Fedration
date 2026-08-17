"""
AMOS-Federation Royal Service
الهدف: واجهات المالك/الملك — مراسيم، مؤسسات، حراس، توليد واجهات وأدوات
النطاق: royal service
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-15
"""

import hmac
import json
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text

from amos_federation.common.auth import (
    ROLE_KING,
    create_king_token,
    require_auth,
    require_king,
)
from amos_federation.common.config import PLACEHOLDER_SECRETS, settings
from amos_federation.common.database import get_database_url
from amos_federation.common.service import create_service_app

router = APIRouter(prefix="/v1", tags=["royal"])

#: اسم الدخول ليس سرًّا؛ السرّ وحده يأتي من البيئة.
KING_USERNAME = "king"


def _get_pg_engine():
    url = get_database_url()
    connect_args = {}
    if url.startswith("postgresql"):
        connect_args = {"sslmode": "require", "connect_timeout": 15}
    else:
        connect_args = {"check_same_thread": False}
    return create_engine(
        url, connect_args=connect_args, pool_pre_ping=True, pool_size=3, max_overflow=5
    )


# === النماذج ===


class DecreeCreate(BaseModel):
    title: str
    decree_text: str
    decree_type: str = "royal"
    affected_entity: str = "all"


class InstitutionCreate(BaseModel):
    institution_id: str
    name: str
    type: str
    state: str = "federal"
    budget: int = 0


class InstitutionClose(BaseModel):
    reason: str = "closed_by_king"


class InterfaceGenerate(BaseModel):
    name: str
    description: str = ""
    interface_type: str = "custom"
    route_path: str = ""
    html_content: str = ""


class ToolGenerate(BaseModel):
    tool_name: str
    description: str
    tool_type: str = "utility"
    permissions_required: list[str] = Field(default_factory=list)


class AgentTrain(BaseModel):
    agent_name: str
    target_role: str = "worker"
    specialization: str = "general"
    training_type: str = "standard"


class LoginRequest(BaseModel):
    username: str
    password: str


# === المصادقة ===


@router.post("/auth/login", response_model=dict)
async def login(req: LoginRequest) -> dict[str, Any]:
    """تسجيل الدخول — المالك يحصل على صلاحيات مطلقة."""
    expected = settings.king_login_secret
    if not expected or expected in PLACEHOLDER_SECRETS:
        raise HTTPException(
            status_code=503,
            detail="بيانات دخول الملك غير مهيّأة — تُقرأ من البيئة ولا تُكتب في الكود",
        )
    if req.username == KING_USERNAME and hmac.compare_digest(req.password, expected):
        token = create_king_token()
        return {
            "access_token": token,
            "token_type": "bearer",
            "role": ROLE_KING,
            "subject": "king",
            "expires_in": 3600,
        }
    raise HTTPException(status_code=401, detail="بيانات الدخول غير صحيحة")


@router.get("/auth/me", response_model=dict)
async def get_me(
    user: Annotated[dict[str, Any], Depends(require_auth)],
) -> dict[str, Any]:
    """معلومات المستخدم الحالي."""
    return {
        "subject": user.get("sub"),
        "role": user.get("role", "citizen"),
        "scopes": user.get("scopes", []),
        "tenant_id": user.get("tenant_id"),
    }


# === لوحة المالك الشاملة ===


@router.get("/royal/dashboard", response_model=dict)
async def royal_dashboard(
    user: Annotated[dict[str, Any], Depends(require_auth)],
) -> dict[str, Any]:
    """لوحة المالك الشاملة — كل ما يحتاجه الملك لرؤية حالة الدولة."""
    engine = _get_pg_engine()
    with engine.connect() as conn:
        # إحصائيات عامة
        # R4: العدّ من السجل الكانوني `agents` لا من إسقاط السكّان.
        agents_count = conn.execute(text("SELECT COUNT(*) FROM agents")).scalar()
        events_count = conn.execute(text("SELECT COUNT(*) FROM event_store")).scalar()
        experiences_count = conn.execute(text("SELECT COUNT(*) FROM experiences")).scalar()
        memories_count = conn.execute(text("SELECT COUNT(*) FROM memories")).scalar()
        tools_count = conn.execute(text("SELECT COUNT(*) FROM tools")).scalar()
        tasks_count = conn.execute(text("SELECT COUNT(*) FROM tasks")).scalar()
        reviews_count = conn.execute(text("SELECT COUNT(*) FROM reviews")).scalar()
        audit_count = conn.execute(text("SELECT COUNT(*) FROM audit_entries")).scalar()
        institutions_count = conn.execute(
            text("SELECT COUNT(*) FROM institutions WHERE status='active'")
        ).scalar()
        decrees_count = conn.execute(text("SELECT COUNT(*) FROM king_decrees")).scalar()
        guards_count = conn.execute(
            text("SELECT COUNT(*) FROM royal_guards WHERE status='active'")
        ).scalar()

        # توزيع الوكلاء حسب الحالة
        state_dist = conn.execute(
            text("SELECT status, COUNT(*) as cnt FROM agents GROUP BY status ORDER BY cnt DESC")
        ).fetchall()

        # توزيع الوكلاء حسب الدور
        role_dist = conn.execute(
            text("SELECT role, COUNT(*) as cnt FROM agents GROUP BY role ORDER BY cnt DESC")
        ).fetchall()

        # آخر الأحداث
        recent_events = conn.execute(
            text("SELECT subject, created_at FROM event_store ORDER BY id DESC LIMIT 10")
        ).fetchall()

        # آخر المراسيم
        recent_decrees = conn.execute(
            text(
                "SELECT decree_id, title, enacted_at, status FROM king_decrees ORDER BY enacted_at DESC LIMIT 5"
            )
        ).fetchall()

    return {
        "stats": {
            "agents": agents_count,
            "events": events_count,
            "experiences": experiences_count,
            "memories": memories_count,
            "tools": tools_count,
            "tasks": tasks_count,
            "reviews": reviews_count,
            "audit_entries": audit_count,
            "institutions": institutions_count,
            "decrees": decrees_count,
            "royal_guards": guards_count,
        },
        "agent_distribution": {
            "by_state": {row[0]: row[1] for row in state_dist},
            "by_role": {row[0]: row[1] for row in role_dist},
        },
        "recent_events": [{"subject": row[0], "created_at": str(row[1])} for row in recent_events],
        "recent_decrees": [
            {"decree_id": row[0], "title": row[1], "enacted_at": str(row[2]), "status": row[3]}
            for row in recent_decrees
        ],
        "king_user": user.get("sub"),
        "king_role": user.get("role"),
    }


# === المراسيم الملكية ===


@router.get("/royal/decrees", response_model=list)
async def list_decrees(
    user: Annotated[dict[str, Any], Depends(require_auth)],
    limit: int = 50,
) -> list[dict[str, Any]]:
    engine = _get_pg_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT decree_id, title, decree_text, decree_type, affected_entity, status, enacted_at "
                "FROM king_decrees ORDER BY enacted_at DESC LIMIT :lim"
            ),
            {"lim": limit},
        ).fetchall()
    return [
        {
            "decree_id": r[0],
            "title": r[1],
            "decree_text": r[2],
            "decree_type": r[3],
            "affected_entity": r[4],
            "status": r[5],
            "enacted_at": str(r[6]),
        }
        for r in rows
    ]


@router.post("/royal/decrees", response_model=dict)
async def create_decree(
    req: DecreeCreate,
    king: Annotated[dict[str, Any], Depends(require_king)],
) -> dict[str, Any]:
    """إصدار مرسوم ملكي — حصري للمالك."""
    engine = _get_pg_engine()
    decree_id = f"decree-{uuid.uuid4()}"
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO king_decrees (decree_id, title, decree_text, decree_type, affected_entity, status, metadata) "
                "VALUES (:id, :title, :text, :type, :entity, 'enacted', :meta)"
            ),
            {
                "id": decree_id,
                "title": req.title,
                "text": req.decree_text,
                "type": req.decree_type,
                "entity": req.affected_entity,
                "meta": json.dumps(
                    {"issued_by": "king", "issued_at": datetime.now(UTC).isoformat()}
                ),
            },
        )
    return {"decree_id": decree_id, "status": "enacted", "title": req.title}


# === المؤسسات ===


@router.get("/royal/institutions", response_model=list)
async def list_institutions(
    user: Annotated[dict[str, Any], Depends(require_auth)],
) -> list[dict[str, Any]]:
    engine = _get_pg_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT institution_id, name, type, state, status, head_agent_id, budget, "
                "established_at, closed_at FROM institutions ORDER BY established_at DESC"
            )
        ).fetchall()
    return [
        {
            "institution_id": r[0],
            "name": r[1],
            "type": r[2],
            "state": r[3],
            "status": r[4],
            "head_agent_id": r[5],
            "budget": r[6],
            "established_at": str(r[7]),
            "closed_at": str(r[8]) if r[8] else None,
        }
        for r in rows
    ]


@router.post("/royal/institutions", response_model=dict)
async def create_institution(
    req: InstitutionCreate,
    king: Annotated[dict[str, Any], Depends(require_king)],
) -> dict[str, Any]:
    """إنشاء مؤسسة جديدة — حصري للمالك."""
    engine = _get_pg_engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO institutions (institution_id, name, type, state, status, budget) "
                "VALUES (:id, :name, :type, :state, 'active', :budget)"
            ),
            {
                "id": req.institution_id,
                "name": req.name,
                "type": req.type,
                "state": req.state,
                "budget": req.budget,
            },
        )
    return {"institution_id": req.institution_id, "status": "active", "name": req.name}


@router.post("/royal/institutions/{institution_id}/close", response_model=dict)
async def close_institution(
    institution_id: str,
    req: InstitutionClose,
    king: Annotated[dict[str, Any], Depends(require_king)],
) -> dict[str, Any]:
    """إغلاق مؤسسة — حصري للمالك."""
    engine = _get_pg_engine()
    with engine.begin() as conn:
        result = conn.execute(
            text(
                "UPDATE institutions SET status='closed', closed_at=NOW() "
                "WHERE institution_id=:id AND status='active'"
            ),
            {"id": institution_id},
        )
        if result.rowcount == 0:
            raise HTTPException(404, "المؤسسة غير موجودة أو مغلقة بالفعل")
    return {"institution_id": institution_id, "status": "closed", "reason": req.reason}


# === الوكلاء الحراس (للمالك فقط) ===


@router.get("/royal/guards", response_model=list)
async def list_guards(
    king: Annotated[dict[str, Any], Depends(require_king)],
) -> list[dict[str, Any]]:
    """قائمة الوكلاء الحراس — حصري للمالك."""
    engine = _get_pg_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT guard_id, codename, cover_role, cover_institution, mission, "
                "loyalty_level, status, last_report, created_at "
                "FROM royal_guards ORDER BY id"
            )
        ).fetchall()
    return [
        {
            "guard_id": r[0],
            "codename": r[1],
            "cover_role": r[2],
            "cover_institution": r[3],
            "mission": r[4],
            "loyalty_level": r[5],
            "status": r[6],
            "last_report": str(r[7]) if r[7] else None,
            "created_at": str(r[8]),
        }
        for r in rows
    ]


# === توليد الواجهات ===


@router.get("/royal/interfaces", response_model=list)
async def list_interfaces(
    user: Annotated[dict[str, Any], Depends(require_auth)],
) -> list[dict[str, Any]]:
    engine = _get_pg_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT interface_id, name, description, interface_type, route_path, "
                "created_by, status, created_at FROM interface_registry ORDER BY created_at DESC"
            )
        ).fetchall()
    return [
        {
            "interface_id": r[0],
            "name": r[1],
            "description": r[2],
            "interface_type": r[3],
            "route_path": r[4],
            "created_by": r[5],
            "status": r[6],
            "created_at": str(r[7]),
        }
        for r in rows
    ]


@router.post("/royal/interfaces", response_model=dict)
async def generate_interface(
    req: InterfaceGenerate,
    user: Annotated[dict[str, Any], Depends(require_auth)],
) -> dict[str, Any]:
    """توليد واجهة جديدة حسب الاحتياج."""
    engine = _get_pg_engine()
    interface_id = f"ui-{uuid.uuid4()}"
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO interface_registry (interface_id, name, description, interface_type, "
                "route_path, html_content, created_by, status) "
                "VALUES (:id, :name, :desc, :type, :route, :html, :by, 'active')"
            ),
            {
                "id": interface_id,
                "name": req.name,
                "desc": req.description,
                "type": req.interface_type,
                "route": req.route_path,
                "html": req.html_content,
                "by": user.get("sub", "system"),
            },
        )
    return {"interface_id": interface_id, "status": "active", "name": req.name}


# === توليد الأدوات ===


@router.get("/royal/tools/queue", response_model=list)
async def list_tool_queue(
    user: Annotated[dict[str, Any], Depends(require_auth)],
) -> list[dict[str, Any]]:
    engine = _get_pg_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT request_id, tool_name, description, tool_type, status, "
                "permissions_required, created_at, completed_at "
                "FROM tool_generation_queue ORDER BY created_at DESC"
            )
        ).fetchall()
    return [
        {
            "request_id": r[0],
            "tool_name": r[1],
            "description": r[2],
            "tool_type": r[3],
            "status": r[4],
            "permissions_required": r[5],
            "created_at": str(r[6]),
            "completed_at": str(r[7]) if r[7] else None,
        }
        for r in rows
    ]


@router.post("/royal/tools/generate", response_model=dict)
async def request_tool_generation(
    req: ToolGenerate,
    user: Annotated[dict[str, Any], Depends(require_auth)],
) -> dict[str, Any]:
    """طلب توليد أداة جديدة."""
    engine = _get_pg_engine()
    request_id = f"tg-{uuid.uuid4()}"
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO tool_generation_queue (request_id, tool_name, description, tool_type, "
                "permissions_required, status, requested_by) "
                "VALUES (:id, :name, :desc, :type, :perms, 'pending', :by)"
            ),
            {
                "id": request_id,
                "name": req.tool_name,
                "desc": req.description,
                "type": req.tool_type,
                "perms": json.dumps(req.permissions_required),
                "by": user.get("sub", "system"),
            },
        )
    return {"request_id": request_id, "status": "pending", "tool_name": req.tool_name}


# === تدريب الوكلاء ===


@router.get("/royal/training/queue", response_model=list)
async def list_training_queue(
    user: Annotated[dict[str, Any], Depends(require_auth)],
) -> list[dict[str, Any]]:
    engine = _get_pg_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT request_id, agent_name, target_role, specialization, training_type, "
                "status, progress, created_at, completed_at "
                "FROM agent_training_queue ORDER BY created_at DESC"
            )
        ).fetchall()
    return [
        {
            "request_id": r[0],
            "agent_name": r[1],
            "target_role": r[2],
            "specialization": r[3],
            "training_type": r[4],
            "status": r[5],
            "progress": r[6],
            "created_at": str(r[7]),
            "completed_at": str(r[8]) if r[8] else None,
        }
        for r in rows
    ]


@router.post("/royal/training/request", response_model=dict)
async def request_agent_training(
    req: AgentTrain,
    user: Annotated[dict[str, Any], Depends(require_auth)],
) -> dict[str, Any]:
    """طلب تدريب وكيل جديد."""
    engine = _get_pg_engine()
    request_id = f"at-{uuid.uuid4()}"
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO agent_training_queue (request_id, agent_name, target_role, "
                "specialization, training_type, status, progress, requested_by) "
                "VALUES (:id, :name, :role, :spec, :type, 'pending', 0, :by)"
            ),
            {
                "id": request_id,
                "name": req.agent_name,
                "role": req.target_role,
                "spec": req.specialization,
                "type": req.training_type,
                "by": user.get("sub", "system"),
            },
        )
    return {"request_id": request_id, "status": "pending", "agent_name": req.agent_name}


# === إدارة الوكلاء (للمالك) ===


@router.post("/royal/agents/{agent_id}/dismiss", response_model=dict)
async def dismiss_agent(
    agent_id: str,
    king: Annotated[dict[str, Any], Depends(require_king)],
) -> dict[str, Any]:
    """إقصاء وكيل — حصري للمالك."""
    engine = _get_pg_engine()
    with engine.begin() as conn:
        result = conn.execute(
            text("UPDATE agents SET status='retired' WHERE id=:id AND status != 'retired'"),
            {"id": agent_id},
        )
        if result.rowcount == 0:
            raise HTTPException(404, "الوكيل غير موجود أو متقاعد بالفعل")
    return {"agent_id": agent_id, "status": "retired", "action": "dismissed_by_king"}


@router.post("/royal/agents/{agent_id}/restore", response_model=dict)
async def restore_agent(
    agent_id: str,
    king: Annotated[dict[str, Any], Depends(require_king)],
) -> dict[str, Any]:
    """إعادة تفعيل وكيل — حصري للمالك."""
    engine = _get_pg_engine()
    with engine.begin() as conn:
        result = conn.execute(
            text("UPDATE agents SET status='active' WHERE id=:id AND status='retired'"),
            {"id": agent_id},
        )
        if result.rowcount == 0:
            raise HTTPException(404, "الوكيل غير موجود أو نشط بالفعل")
    return {"agent_id": agent_id, "status": "active", "action": "restored_by_king"}


# === الموافقة على الترقيات ===


@router.post("/royal/approve-promotion", response_model=dict)
async def approve_promotion(
    king: Annotated[dict[str, Any], Depends(require_king)],
    promotion_id: str = "",
    agent_id: str = "",
    approved: bool = True,
) -> dict[str, Any]:
    """الموافقة على ترقية وكيل — حصري للمالك."""
    engine = _get_pg_engine()
    # تسجيل الموافقة في سجل التدقيق
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO audit_entries (id, action, actor, details, prev_hash, hash) "
                "VALUES (:id, 'promotion_approval', 'king', :details, :prev, :hash)"
            ),
            {
                "id": f"audit-{uuid.uuid4()}",
                "details": json.dumps(
                    {
                        "promotion_id": promotion_id,
                        "agent_id": agent_id,
                        "approved": approved,
                        "by": "king",
                    }
                ),
                "prev": "0" * 64,
                "hash": uuid.uuid4().hex,
            },
        )
    return {
        "promotion_id": promotion_id,
        "agent_id": agent_id,
        "approved": approved,
        "by": "king",
    }


# === الوكلاء والسكان ===


@router.get("/population", response_model=list)
async def list_population(
    user: Annotated[dict[str, Any], Depends(require_auth)],
    state: str = "",
    role: str = "",
    limit: int = 100,
) -> list[dict[str, Any]]:
    """قائمة السكان — مع فلترة."""
    engine = _get_pg_engine()
    # R4: الهوية من `agents`؛ الملفّ التدريبي (category/specialization/graduated_at)
    # من إسقاط السكّان عبر LEFT JOIN — بلا سجل هوية ثانٍ وبلا تغيير شكل الرد.
    query = (
        "SELECT a.id, a.name, a.role, COALESCE(p.category, '') AS category, a.status, "
        "a.permissions, a.allowed_tools, a.token_budget, COALESCE(p.specialization, '') "
        "AS specialization, p.graduated_at FROM agents a "
        "LEFT JOIN agent_population p ON p.agent_id = a.id"
    )
    conditions = []
    params: dict[str, Any] = {"lim": limit}
    if state:
        conditions.append("a.status = :state")
        params["state"] = state
    if role:
        conditions.append("a.role = :role")
        params["role"] = role
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY a.created_at DESC LIMIT :lim"

    with engine.connect() as conn:
        rows = conn.execute(text(query), params).fetchall()
    return [
        {
            "agent_id": r[0],
            "name": r[1],
            "role": r[2],
            "category": r[3],
            "state": r[4],
            "permissions": r[5],
            "allowed_tools": r[6],
            "token_budget": r[7],
            "specialization": r[8],
            "graduated_at": str(r[9]) if r[9] else None,
        }
        for r in rows
    ]


# === الخدمة ===

_service = SERVICES = None


def get_royal_app():
    """الحصول على تطبيق FastAPI للخدمة الملكية."""
    app = create_service_app("royal", 8011, "الخدمة الملكية — واجهة المالك", [router])
    return app


def create_app():
    return get_royal_app()
