"""
AMOS-Federation Phase 13 — Federal Factories
الهدف: أربعة مصانع إنتاج حقيقية تستهلك الوكلاء والأدوات والنماذج
النطاق: services/governance/factories
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-15

المتطلبات:
  13.1: مصنع التقارير المالية (استخراج ← تنظيف ← تحليل ← كتابة ← مراجعة ← نشر)
  13.2: مصنع المحتوى (مقالات، ترجمات، ملخصات)
  13.3: مصنع الأبحاث (أسئلة بحثية → أوراق علمية)
  13.4: مصنع المراقبة الأمنية (سجلات → تقارير تهديدات)
  13.5: توسيع كتالوج الأدوات
  13.6: ربط كل مصنع بمدير خط إنتاج وعمال حقيقيين
"""

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Column, DateTime, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from amos_federation.common.database import get_database_url
from amos_federation.common.persistent import PersistentAuditStore
from amos_federation.services.executive_core.sovereignty_bridge import (
    ConstitutionalAuthorizer,
    UndeclaredExecutionError,
    compensator,
    declared_effect,
    operation_key,
)

#: فاعلُ الإنتاج. قِيسَ في P13 أنَّ البوابةَ تُجيزُ `start_production` و `complete_step`
#: و `assign_manager` لكلِّ الفروعِ (ALLOW × 5)، فلا فعلَ حصريًّا يُهرَبُ منه بالتسمية.
#: والفاعلُ يُعلَنُ تنفيذيًّا لأنَّ الإنتاجَ عملُ السلطةِ التنفيذيّةِ فعلًا لا اختيارًا.
FACTORY_ACTOR = "EXECUTIVE"

#: أفعالُ المصنعِ بأسمائِها كما تُنادى — لا اسمَ نطاقيًّا يُخفي فعلًا.
ACTION_START_PRODUCTION = "start_production"
ACTION_COMPLETE_STEP = "complete_step"
ACTION_ASSIGN_MANAGER = "assign_manager"

#: نطاقاتُ مفاتيحِ الذرّيّة (1H).
PRODUCTION_START_SCOPE = "factories.production.start"
PRODUCTION_STEP_SCOPE = "factories.production.step"
MANAGER_ASSIGN_SCOPE = "factories.manager.assign"


class ProductNotFoundError(RuntimeError):
    """منتجٌ غيرُ موجودٍ — رفعٌ صريحٌ لا قاموسُ خطأٍ صامت."""


class FactoryNotFoundError(RuntimeError):
    """مصنعٌ غيرُ موجودٍ — رفعٌ صريحٌ لا قاموسُ خطأٍ صامت."""


class FactoryBase(DeclarativeBase):
    pass


class FactoryModel(FactoryBase):
    """جدول المصانع."""

    __tablename__ = "federal_factories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    factory_id = Column(String, nullable=False, unique=True, index=True)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)  # financial_report, content, research, security
    state_id = Column(String, nullable=True)  # الولاية التابع لها
    manager_agent_id = Column(String, nullable=True)
    status = Column(String, default="active")  # active, paused, closed
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


class FactoryProductModel(FactoryBase):
    """مخرجات المصانع."""

    __tablename__ = "factory_products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(String, nullable=False, unique=True, index=True)
    factory_id = Column(String, nullable=False, index=True)
    title = Column(String, nullable=False)
    content = Column(Text, default="")
    quality_score = Column(Integer, default=0)
    status = Column(String, default="draft")  # draft, reviewed, published
    pipeline_steps = Column(Text, default="[]")  # JSON array of completed steps
    produced_by = Column(String, nullable=True)  # agent_id
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    published_at = Column(DateTime, nullable=True)


# تعريف المصانع الأربعة
FACTORIES = {
    "financial_report": {
        "name": "مصنع التقارير المالية",
        "type": "financial_report",
        "state_id": "finance",
        "pipeline": ["extract", "clean", "analyze", "write", "review", "publish"],
    },
    "content": {
        "name": "مصنع المحتوى",
        "type": "content",
        "state_id": "culture",
        "pipeline": ["research", "draft", "edit", "review", "publish"],
    },
    "research": {
        "name": "مصنع الأبحاث",
        "type": "research",
        "state_id": "science",
        "pipeline": [
            "question",
            "literature",
            "methodology",
            "experiment",
            "write",
            "review",
            "publish",
        ],
    },
    "security": {
        "name": "مصنع المراقبة الأمنية",
        "type": "security",
        "state_id": "law",
        "pipeline": ["collect_logs", "analyze", "detect_threats", "assess", "report", "publish"],
    },
}


class Factory:
    """13.1-13.4: مصنع إنتاج حقيقي بخط أنابيب."""

    def __init__(
        self, factory_id: str, authorizer: ConstitutionalAuthorizer | None = None
    ) -> None:
        self._engine = create_engine(
            get_database_url(),
            connect_args={"check_same_thread": False}
            if get_database_url().startswith("sqlite")
            else {},
        )
        FactoryBase.metadata.create_all(self._engine)
        self._Session = sessionmaker(bind=self._engine, autoflush=False, expire_on_commit=False)
        self.factory_id = factory_id
        self._init_factory()
        # P13: المُصرِّحُ نفسُه لا مُصرِّحٌ ثانٍ — يُبنى عندَ أوّلِ حاجة.
        self._authorizer = authorizer

    @property
    def authorizer(self) -> ConstitutionalAuthorizer:
        """المُصرِّحُ السياديُّ بفاعلٍ تنفيذيٍّ مُعلَن."""
        if self._authorizer is None:
            self._authorizer = ConstitutionalAuthorizer(actor=FACTORY_ACTOR)
        return self._authorizer

    # ── المساراتُ القديمةُ المُقفَلة · P13 ────────────────────────────────
    def _start_production_unguarded(self, title: str) -> None:
        """مسارٌ **مُقفَلٌ** منذ P13 — يُرفَعُ دائمًا ولا يُنشئُ منتجًا."""
        raise UndeclaredExecutionError(
            f"بدءُ إنتاجِ «{title}» في المصنعِ «{self.factory_id}» مباشرةً لا يعبرُ حدَّ "
            "التنفيذِ السياديّ. المسارُ الوحيدُ هو `start_production` بأثرٍ مُعلَنٍ "
            "ومفتاحِ عمليّةٍ ومعوّضٍ يحذفُ المنتجَ المُنشَأَ فعلًا."
        )

    def _complete_step_unguarded(self, product_id: str, step: str) -> None:
        """مسارٌ **مُقفَلٌ** منذ P13 — يُرفَعُ دائمًا ولا يمسُّ خطَّ أنابيب."""
        raise UndeclaredExecutionError(
            f"إكمالُ الخطوةِ «{step}» في المنتجِ «{product_id}» مباشرةً لا يعبرُ حدَّ "
            "التنفيذِ السياديّ. المسارُ الوحيدُ هو `complete_step` بمعوّضٍ يُعيدُ "
            "الخطواتَ والحالةَ إلى قيمتِهما السابقةِ حقيقةً."
        )

    def _write_product_row(
        self, product_id: str, title: str, producer_agent_id: str
    ) -> None:
        """كتابةُ صفِّ منتجٍ — تُستعملُ للأثرِ وحدَه."""
        session = self._Session()
        try:
            session.add(
                FactoryProductModel(
                    product_id=product_id,
                    factory_id=self.factory_id,
                    title=title,
                    produced_by=producer_agent_id,
                    pipeline_steps="[]",
                )
            )
            session.commit()
        finally:
            session.close()

    def _delete_product_row(self, product_id: str) -> bool:
        """حذفُ صفِّ منتجٍ — عكسٌ حقيقيٌّ للإنشاء، و`False` إن غابَ فلا عكسَ يُزعَم."""
        session = self._Session()
        try:
            row = (
                session.query(FactoryProductModel)
                .filter(FactoryProductModel.product_id == product_id)
                .first()
            )
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True
        finally:
            session.close()

    def _restore_product_pipeline(
        self, product_id: str, steps_json: str, status: str, published_at: Any
    ) -> bool:
        """إعادةُ خطواتِ المنتجِ وحالتِه إلى قيمٍ قُرِئتْ قبلَ عبورِ الحدّ."""
        session = self._Session()
        try:
            row = (
                session.query(FactoryProductModel)
                .filter(FactoryProductModel.product_id == product_id)
                .first()
            )
            if row is None:
                return False
            row.pipeline_steps = steps_json
            row.status = status
            row.published_at = published_at
            session.commit()
            return True
        finally:
            session.close()

    def _init_factory(self) -> None:
        """تهيئة المصنع إذا لم يكن موجودًا."""
        session = self._Session()
        try:
            existing = (
                session.query(FactoryModel)
                .filter(FactoryModel.factory_id == self.factory_id)
                .first()
            )
            if not existing and self.factory_id in FACTORIES:
                info = FACTORIES[self.factory_id]
                factory = FactoryModel(
                    factory_id=self.factory_id,
                    name=info["name"],
                    type=info["type"],
                    state_id=info["state_id"],
                )
                session.add(factory)
                session.commit()
        finally:
            session.close()

    def start_production(
        self,
        title: str,
        producer_agent_id: str = "",
        operation_ref: str = "",
    ) -> dict[str, Any]:
        """بدء إنتاج منتج جديد — يدخل خط الأنابيب، عبرَ الحدِّ السياديِّ منذ P13.

        `operation_ref` مرجعُ العمليّةِ للذرّيّة: إن قدّمَه المُنادي صارَ نداءانِ
        بالمرجعِ نفسِه عمليّةً واحدةً تُعادُ لا تُكرَّر. وإن غابَ فلا يُزعَمُ ضدَّ
        تكرارٍ لا يملكُ المُنادي تسميتَه: يُولَّدُ مرجعٌ فريدٌ لكلِّ نداء.
        """
        # قاعدةُ نطاقٍ قبلَ الحدِّ: مصنعٌ بلا خطِّ أنابيبَ لا يُنتِج.
        pipeline = FACTORIES.get(self.factory_id, {}).get("pipeline", [])
        if not pipeline:
            raise FactoryNotFoundError(
                f"المصنعُ «{self.factory_id}» لا خطَّ أنابيبَ له — لا إنتاجَ يُزعَم"
            )

        reference = operation_ref or uuid.uuid4().hex
        # المُعرِّفُ مُشتقٌّ من (المصنعِ + المرجعِ) لا من عشوائيّةٍ جديدةٍ في كلِّ نداء:
        # قِيسَ أنَّ بصمةَ الذرّيّةِ تشملُ الهدفَ، فمُعرِّفٌ عشوائيٌّ يجعلُ الإعادةَ
        # «عمليّةً أخرى ببصمةٍ مختلفة» ويُسقِطُ الذرّيّةَ من أصلِها.
        product_id = "prod-" + hashlib.sha256(
            f"{self.factory_id}:{reference}".encode("utf-8")
        ).hexdigest()[:10]
        target = f"factory/{self.factory_id}/product/{product_id}"
        effect = declared_effect(
            "CREATE", target, f"منتجٌ جديدٌ «{title}» في المصنعِ «{self.factory_id}»"
        )

        def _apply(_effect: Any) -> dict[str, Any]:
            self._write_product_row(product_id, title, producer_agent_id)
            audit = PersistentAuditStore()
            audit.append(
                "factory.production_started",
                producer_agent_id or "system",
                {
                    "factory_id": self.factory_id,
                    "product_id": product_id,
                    "title": title,
                },
            )
            return {
                "product_id": product_id,
                "factory_id": self.factory_id,
                "title": title,
                "pipeline": pipeline,
                "status": "draft",
                "started": True,
            }

        guarded = self.authorizer.guard_declared(
            ACTION_START_PRODUCTION,
            target,
            declared_effects=(effect,),
            applier=_apply,
            operation_key=operation_key(PRODUCTION_START_SCOPE, f"{self.factory_id}:{reference}"),
            compensators=(
                compensator(
                    effect.signature,
                    lambda: self._delete_product_row(product_id),
                    "حذفُ صفِّ المنتجِ المُنشَأِ — عكسٌ حقيقيٌّ للإنشاء",
                ),
            ),
        )
        if guarded.is_replay:
            # إعادةٌ لمفتاحٍ مُثبَّت: لا صفَّ ثانيًا ولا أثرَ تدقيقٍ ثانيًا. والصدقُ
            # أن يُقالَ «أُعيدَ» لا أن يُزعَمَ إنتاجٌ جديدٌ لم يقع.
            return {
                "product_id": product_id,
                "factory_id": self.factory_id,
                "title": title,
                "pipeline": pipeline,
                "started": False,
                "replay": True,
                "operation_key": guarded.outcome.operation_key,
                "evidence": guarded.evidence.as_dict(),
            }
        value = guarded.value
        result = value if isinstance(value, dict) else next(
            item for item in value if isinstance(item, dict)
        )
        return {**result, "evidence": guarded.evidence.as_dict(), "replay": False}

    def complete_step(
        self, product_id: str, step: str, output: str = "", quality: int = 0
    ) -> dict[str, Any]:
        """إكمال خطوة في خط الأنابيب — عبرَ الحدِّ السياديِّ منذ P13."""
        # قواعدُ النطاقِ وقراءةُ الحالةِ السابقةِ **قبلَ** عبورِ الحدّ، حتّى يعكسَ
        # المعوّضُ قيمةً حقيقيّةً لا قيمةً يُظَنُّ أنَّها كانت.
        session = self._Session()
        try:
            row = (
                session.query(FactoryProductModel)
                .filter(FactoryProductModel.product_id == product_id)
                .first()
            )
            if row is None:
                raise ProductNotFoundError(
                    f"المنتجُ «{product_id}» غيرُ موجودٍ — لا خطوةَ تُزعَمُ عليه"
                )
            previous_steps = row.pipeline_steps or "[]"
            previous_status = row.status
            previous_published_at = row.published_at
        finally:
            session.close()

        # الهدفُ يُسمّي الخطوةَ بعينِها لا المنتجَ وحدَه: قِيسَ أنَّ هويّةَ الإذنِ
        # تجزئةُ (فاعلٍ · فعلٍ · هدفٍ · آثارٍ) في الثانيةِ الواحدة، فخطوتانِ في
        # ثانيةٍ واحدةٍ على هدفٍ خشِنٍ إذنٌ واحدٌ تُرفَضُ ثانيتُهما استهلاكًا.
        target = f"factory/{self.factory_id}/product/{product_id}/step/{step}"
        effect = declared_effect(
            "WRITE", target, f"إكمالُ الخطوةِ «{step}» على المنتجِ «{product_id}»"
        )

        def _apply(_effect: Any) -> dict[str, Any]:
            return self._complete_step_row(product_id, step, output, quality)

        guarded = self.authorizer.guard_declared(
            ACTION_COMPLETE_STEP,
            target,
            declared_effects=(effect,),
            applier=_apply,
            operation_key=operation_key(PRODUCTION_STEP_SCOPE, f"{product_id}:{step}"),
            compensators=(
                compensator(
                    effect.signature,
                    lambda: self._restore_product_pipeline(
                        product_id, previous_steps, previous_status, previous_published_at
                    ),
                    "إعادةُ الخطواتِ والحالةِ إلى قيمِها المقروءةِ قبلَ الحدّ",
                ),
            ),
        )
        if guarded.is_replay:
            return {
                "product_id": product_id,
                "step": step,
                "status": previous_status,
                "completed": False,
                "replay": True,
                "operation_key": guarded.outcome.operation_key,
                "evidence": guarded.evidence.as_dict(),
            }
        value = guarded.value
        result = value if isinstance(value, dict) else next(
            item for item in value if isinstance(item, dict)
        )
        return {**result, "evidence": guarded.evidence.as_dict(), "replay": False}

    def _complete_step_row(
        self, product_id: str, step: str, output: str, quality: int
    ) -> dict[str, Any]:
        """التطبيقُ الحقيقيُّ للخطوة — يُنادى من داخلِ الحدِّ وحدَه."""
        session = self._Session()
        try:
            product = (
                session.query(FactoryProductModel)
                .filter(FactoryProductModel.product_id == product_id)
                .first()
            )
            if not product:
                raise ProductNotFoundError(
                    f"المنتجُ «{product_id}» غابَ بينَ الفحصِ والتطبيقِ — لا أثرَ يُزعَم"
                )

            steps = json.loads(product.pipeline_steps or "[]")
            steps.append(
                {
                    "step": step,
                    "output": output[:200],
                    "quality": quality,
                    "completed_at": datetime.now(UTC).isoformat(),
                }
            )
            product.pipeline_steps = json.dumps(steps)

            # إذا كانت الخطوة هي النشر، حدّث الحالة
            pipeline = FACTORIES.get(self.factory_id, {}).get("pipeline", [])
            if step == pipeline[-1]:  # الخطوة الأخيرة
                product.status = "published"
                product.published_at = datetime.now(UTC)
            elif step == "review":
                product.status = "reviewed"

            session.commit()

            return {
                "product_id": product_id,
                "step": step,
                "quality": quality,
                "status": product.status,
                "steps_completed": len(steps),
                "total_steps": len(pipeline),
            }
        finally:
            session.close()

    def run_full_pipeline(self, title: str, producer_agent_id: str = "") -> dict[str, Any]:
        """تشغيل خط الأنابيب الكامل من البداية للنشر."""
        result = self.start_production(title, producer_agent_id)
        product_id = result["product_id"]
        pipeline = result["pipeline"]

        for step in pipeline:
            self.complete_step(product_id, step, f"مخرج {step}", quality=85)

        session = self._Session()
        try:
            product = (
                session.query(FactoryProductModel)
                .filter(FactoryProductModel.product_id == product_id)
                .first()
            )
            return {
                "product_id": product_id,
                "factory_id": self.factory_id,
                "title": title,
                "status": product.status,
                "steps_completed": len(pipeline),
                "published_at": product.published_at.isoformat() if product.published_at else None,
            }
        finally:
            session.close()

    def list_products(self, limit: int = 50) -> list[dict[str, Any]]:
        """مخرجات المصنع."""
        session = self._Session()
        try:
            products = (
                session.query(FactoryProductModel)
                .filter(FactoryProductModel.factory_id == self.factory_id)
                .order_by(FactoryProductModel.created_at.desc())
                .limit(limit)
                .all()
            )
            return [
                {
                    "product_id": p.product_id,
                    "title": p.title,
                    "status": p.status,
                    "quality_score": p.quality_score,
                    "produced_by": p.produced_by,
                    "steps_completed": len(json.loads(p.pipeline_steps or "[]")),
                    "created_at": p.created_at.isoformat() if p.created_at else None,
                }
                for p in products
            ]
        finally:
            session.close()

    def get_product(self, product_id: str) -> dict[str, Any] | None:
        """تفاصيل منتج."""
        session = self._Session()
        try:
            p = (
                session.query(FactoryProductModel)
                .filter(FactoryProductModel.product_id == product_id)
                .first()
            )
            if not p:
                return None
            return {
                "product_id": p.product_id,
                "factory_id": p.factory_id,
                "title": p.title,
                "content": p.content,
                "status": p.status,
                "quality_score": p.quality_score,
                "pipeline_steps": json.loads(p.pipeline_steps or "[]"),
                "produced_by": p.produced_by,
            }
        finally:
            session.close()


class FactoryRegistry:
    """13.6: سجل المصانع — ربط بمديري خطوط الإنتاج."""

    def __init__(self, authorizer: ConstitutionalAuthorizer | None = None) -> None:
        self._engine = create_engine(
            get_database_url(),
            connect_args={"check_same_thread": False}
            if get_database_url().startswith("sqlite")
            else {},
        )
        FactoryBase.metadata.create_all(self._engine)
        self._Session = sessionmaker(bind=self._engine, autoflush=False, expire_on_commit=False)
        self._authorizer = authorizer

    def list_factories(self) -> list[dict[str, Any]]:
        """قائمة المصانع."""
        session = self._Session()
        try:
            factories = session.query(FactoryModel).all()
            return [
                {
                    "factory_id": f.factory_id,
                    "name": f.name,
                    "type": f.type,
                    "state_id": f.state_id,
                    "manager_agent_id": f.manager_agent_id,
                    "status": f.status,
                }
                for f in factories
            ]
        finally:
            session.close()

    @property
    def authorizer(self) -> ConstitutionalAuthorizer:
        """المُصرِّحُ السياديُّ بفاعلٍ تنفيذيٍّ مُعلَن."""
        if self._authorizer is None:
            self._authorizer = ConstitutionalAuthorizer(actor=FACTORY_ACTOR)
        return self._authorizer

    def _assign_manager_unguarded(self, factory_id: str, agent_id: str) -> None:
        """مسارٌ **مُقفَلٌ** منذ P13 — يُرفَعُ دائمًا ولا يُعيِّنُ مديرًا."""
        raise UndeclaredExecutionError(
            f"تعيينُ «{agent_id}» مديرًا للمصنعِ «{factory_id}» مباشرةً لا يعبرُ حدَّ "
            "التنفيذِ السياديّ. المسارُ الوحيدُ هو `assign_manager` بمعوّضٍ يُعيدُ "
            "المديرَ السابقَ حقيقةً."
        )

    def _set_manager_row(self, factory_id: str, agent_id: str | None) -> bool:
        """كتابةُ مديرِ المصنعِ — تُستعملُ للأثرِ وللعكسِ معًا."""
        session = self._Session()
        try:
            factory = (
                session.query(FactoryModel).filter(FactoryModel.factory_id == factory_id).first()
            )
            if factory is None:
                return False
            factory.manager_agent_id = agent_id
            session.commit()
            return True
        finally:
            session.close()

    def assign_manager(self, factory_id: str, agent_id: str) -> dict[str, Any]:
        """13.6: تعيين مدير خط إنتاج — عبرَ الحدِّ السياديِّ منذ P13.

        قِيسَ أنَّ البوابةَ تُجيزُ `assign_manager` لكلِّ الفروع، فالحدُّ هنا لا يُنشئُ
        فصلَ سلطاتٍ لا يملكُه المُحرِّك؛ يُنشئُ مراحلَ وأثرًا مُعلَنًا وذرّيّةً ومعوّضًا
        ودليلًا. ومَن يملكُ فعلَ التعيينِ أصلًا سؤالٌ مفتوحٌ (Q-24) لم أحسمْه.
        """
        session = self._Session()
        try:
            factory = (
                session.query(FactoryModel).filter(FactoryModel.factory_id == factory_id).first()
            )
            if factory is None:
                raise FactoryNotFoundError(
                    f"المصنعُ «{factory_id}» غيرُ موجودٍ — لا تعيينَ يُزعَمُ عليه"
                )
            previous_manager = factory.manager_agent_id
        finally:
            session.close()

        # الهدفُ يُسمّي التعيينَ المقصودَ لا المصنعَ وحدَه، للسببِ المقيسِ نفسِه:
        # تعيينانِ مختلفانِ في ثانيةٍ واحدةٍ على هدفٍ خشِنٍ إذنٌ واحدٌ لا إذنان.
        target = f"factory/{factory_id}/manager/{agent_id}"
        effect = declared_effect(
            "WRITE", target, f"تعيينُ «{agent_id}» مديرًا للمصنعِ «{factory_id}»"
        )

        def _apply(_effect: Any) -> dict[str, Any]:
            if not self._set_manager_row(factory_id, agent_id):
                raise FactoryNotFoundError(
                    f"المصنعُ «{factory_id}» غابَ بينَ الفحصِ والتطبيقِ — لا أثرَ يُزعَم"
                )
            audit = PersistentAuditStore()
            audit.append(
                "factory.manager_assigned",
                "system",
                {"factory_id": factory_id, "agent_id": agent_id},
            )
            return {
                "factory_id": factory_id,
                "manager_agent_id": agent_id,
                "previous_manager_agent_id": previous_manager,
                "assigned": True,
            }

        guarded = self.authorizer.guard_declared(
            ACTION_ASSIGN_MANAGER,
            target,
            declared_effects=(effect,),
            applier=_apply,
            operation_key=operation_key(MANAGER_ASSIGN_SCOPE, f"{factory_id}:{agent_id}"),
            compensators=(
                compensator(
                    effect.signature,
                    lambda: self._set_manager_row(factory_id, previous_manager),
                    "إعادةُ المديرِ السابقِ — عكسٌ حقيقيٌّ لا رمزيّ",
                ),
            ),
        )
        if guarded.is_replay:
            # إعادةٌ لمفتاحٍ مُثبَّت. وهنا قيدٌ مُعلَنٌ لا يُجمَّل: مفتاحُ العمليّةِ
            # (مصنعٌ + وكيل) يجعلُ **إعادةَ تعيينِ مديرٍ سابقٍ** إعادةً لا فعلًا
            # جديدًا، فلا يعودُ إلى موقعِه. هذا امتدادُ Q-11/Q-12 على هذا السطحِ
            # ومُقيَّدٌ في السجلّ؛ حلُّه قرارٌ بشريٌّ في دلالةِ «العمليّةِ نفسِها».
            return {
                "factory_id": factory_id,
                "manager_agent_id": agent_id,
                "previous_manager_agent_id": previous_manager,
                "assigned": False,
                "replay": True,
                "operation_key": guarded.outcome.operation_key,
                "evidence": guarded.evidence.as_dict(),
            }
        value = guarded.value
        result = value if isinstance(value, dict) else next(
            item for item in value if isinstance(item, dict)
        )
        return {**result, "evidence": guarded.evidence.as_dict(), "replay": False}


# Singletons
_factories: dict[str, Factory] = {}
_registry: FactoryRegistry | None = None


def get_factory(factory_id: str) -> Factory:
    global _factories
    if factory_id not in _factories:
        _factories[factory_id] = Factory(factory_id)
    return _factories[factory_id]


def get_factory_registry() -> FactoryRegistry:
    global _registry
    if _registry is None:
        _registry = FactoryRegistry()
    return _registry
