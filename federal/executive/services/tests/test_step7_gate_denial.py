"""الهدف: إثباتُ أنَّ كتاباتِ المصنعِ الثلاثَ **خلفَ** البوّابةِ لا حولَها — وأنَّ البناءَ يكتبُ بلا بوّابة.

النطاق: `governance/factories.py` — `start_production` · `complete_step` ·
`assign_manager` · و`Factory.__init__`.
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-22

## لماذا هذا الملفُّ موجود (W-024 · T1 · الخطوة 7)

حزمةُ P13 (`test_p13_factories_sovereign.py`) تُثبِتُ أنَّ المساراتِ القديمةَ
مُقفَلةٌ وأنَّ الأثرَ يقعُ عبرَ الحدِّ وأنَّ المعوّضاتِ عكسٌ حقيقيّ. وما لم تُثبِتْه:
**ماذا يحدثُ لو رَدَّت البوّابة؟** فسطحٌ «يعبرُ الحدَّ» ثمَّ يكتبُ مهما كانَ الحكمُ
سطحٌ غيرُ مَحروسٍ بحقيقتِه. فهنا يُقاسُ الرَّدُّ نفسُه: عندَ الرَّدِّ **لا صفَّ
يُكتَبُ ولا حالةَ تتغيَّر** — والقياسُ على قاعدةِ البياناتِ لا على وقوعِ استثناء.

- G-1 الرَّدُّ يمنعُ إنشاءَ منتج.
- G-2 الرَّدُّ يمنعُ تغييرَ خطوةٍ على منتجٍ قائم.
- G-3 الرَّدُّ يمنعُ تغييرَ مديرِ مصنعٍ قائم.
- G-4 القيدُ الباقي مُقاسٌ لا مُخفًى: بناءُ `Factory` يكتبُ صفَّ مصنعٍ **بلا نداءِ
  بوّابةٍ واحد** (دليلٌ في بابِ Q-25 · لا تُغيَّرُ به قاعدةُ العدّ).
- G-5 أحكامُ المُحرِّكِ على الأفعالِ الثلاثةِ `ALLOW` لخمسةِ فاعلين — فالحدُّ هنا
  لا يُنشئُ فصلَ سلطاتٍ لا يملكُه المُحرِّك، كما قِيسَ في P13.
"""

from pathlib import Path
from typing import Any

import pytest

from amos_federation.services.executive_core.sovereignty_bridge import ConstitutionalAuthorizer
from amos_federation.services.governance import factories as factories_module
from amos_federation.services.governance.factories import (
    Factory,
    FactoryModel,
    FactoryProductModel,
    FactoryRegistry,
)

FACTORY_ID = "financial_report"
ACTORS = ("EXECUTIVE", "LEGISLATIVE", "JUDICIAL", "TREASURY", "ROYAL")


class DenyingAuthorizer(ConstitutionalAuthorizer):
    """مُصرِّحٌ يَرُدُّ كلَّ نداءٍ عندَ الحدِّ — ولا يمسُّ شيئًا بعدَه."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.calls: list[str] = []

    def guard_declared(self, action: str, target: str, **kwargs: Any) -> Any:  # type: ignore[override]
        self.calls.append(action)
        raise PermissionError(f"DENY::{action}")


class CountingAuthorizer(ConstitutionalAuthorizer):
    """مُصرِّحٌ يَعُدُّ نداءاتِ الحدِّ ولا يُغيِّرُ حُكمًا."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.calls: list[str] = []

    def guard_declared(self, action: str, target: str, **kwargs: Any) -> Any:  # type: ignore[override]
        self.calls.append(action)
        return super().guard_declared(action, target, **kwargs)


@pytest.fixture
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """قاعدةُ بياناتٍ خاصّةٌ بكلِّ فحصٍ — القياسُ على أثرٍ لا على بقايا غيرِه."""
    db_path = tmp_path / "step7.db"
    monkeypatch.setenv("AMOS_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.chdir(tmp_path)
    return db_path


def _count(owner: Any, model: Any) -> int:
    session = owner._Session()  # noqa: SLF001 — القياسُ على القاعدةِ لا على القيمةِ المُرجَعة
    try:
        return session.query(model).count()
    finally:
        session.close()


def _manager_of(registry: FactoryRegistry, factory_id: str) -> str | None:
    session = registry._Session()  # noqa: SLF001
    try:
        row = session.query(FactoryModel).filter(FactoryModel.factory_id == factory_id).first()
        return row.manager_agent_id if row else None
    finally:
        session.close()


def _authorizer(kind: type, tmp_path: Path, name: str) -> Any:
    return kind(
        actor=factories_module.FACTORY_ACTOR,
        idempotency_ledger_path=tmp_path / f"{name}-IDEM.json",
    )


# ═══════════════════════════════════════════════════════════════════════════
# G-1 … G-3 · الرَّدُّ عندَ البوّابةِ يمنعُ الكتابة
# ═══════════════════════════════════════════════════════════════════════════


def test_denied_production_writes_no_product(isolated_db: Path, tmp_path: Path) -> None:
    """G-1: رَدُّ البوّابةِ ⇒ لا صفَّ منتجٍ — الكتابةُ خلفَ الحدِّ لا بجانبِه."""
    denying = _authorizer(DenyingAuthorizer, tmp_path, "DENY-PROD")
    factory = Factory(FACTORY_ID, authorizer=denying)

    with pytest.raises(PermissionError):
        factory.start_production("منتجٌ لا يُنتَج", "agent-1", operation_ref="deny-1")

    assert denying.calls == [factories_module.ACTION_START_PRODUCTION]
    assert _count(factory, FactoryProductModel) == 0


def test_denied_step_changes_nothing(isolated_db: Path, tmp_path: Path) -> None:
    """G-2: منتجٌ قائمٌ ثمَّ رَدٌّ على الخطوةِ ⇒ حالتُه وخطواتُه كما كانت."""
    allowing = _authorizer(CountingAuthorizer, tmp_path, "ALLOW-PROD")
    factory = Factory(FACTORY_ID, authorizer=allowing)
    started = factory.start_production("منتجُ قياسٍ", "agent-1", operation_ref="ok-1")
    product_id = started["product_id"]

    session = factory._Session()  # noqa: SLF001
    try:
        row = (
            session.query(FactoryProductModel)
            .filter(FactoryProductModel.product_id == product_id)
            .first()
        )
        before_steps, before_status = row.pipeline_steps, row.status
    finally:
        session.close()

    denying = _authorizer(DenyingAuthorizer, tmp_path, "DENY-STEP")
    denied_factory = Factory(FACTORY_ID, authorizer=denying)
    with pytest.raises(PermissionError):
        denied_factory.complete_step(product_id, "extract", "مخرَجٌ لا يُكتَب", 90)

    assert denying.calls == [factories_module.ACTION_COMPLETE_STEP]
    session = denied_factory._Session()  # noqa: SLF001
    try:
        after = (
            session.query(FactoryProductModel)
            .filter(FactoryProductModel.product_id == product_id)
            .first()
        )
        assert after.pipeline_steps == before_steps
        assert after.status == before_status
    finally:
        session.close()


def test_denied_manager_assignment_changes_nothing(isolated_db: Path, tmp_path: Path) -> None:
    """G-3: رَدٌّ على التعيينِ ⇒ مديرُ المصنعِ كما كان."""
    Factory(FACTORY_ID)  # يُوجِدُ صفَّ المصنعِ — وهو نفسُه القيدُ المقيسُ في G-4
    denying = _authorizer(DenyingAuthorizer, tmp_path, "DENY-MGR")
    registry = FactoryRegistry(authorizer=denying)
    before = _manager_of(registry, FACTORY_ID)

    with pytest.raises(PermissionError):
        registry.assign_manager(FACTORY_ID, "agent-manager-x")

    assert denying.calls == [factories_module.ACTION_ASSIGN_MANAGER]
    assert _manager_of(registry, FACTORY_ID) == before


# ═══════════════════════════════════════════════════════════════════════════
# G-4 · القيدُ الباقي: البناءُ يكتبُ بلا بوّابة
# ═══════════════════════════════════════════════════════════════════════════


def test_construction_writes_a_factory_row_without_any_gate_call(
    isolated_db: Path, tmp_path: Path
) -> None:
    """G-4: بناءُ `Factory` يكتبُ صفًّا و**لا ينادي الحدَّ مرّةً واحدة**.

    هذا قيدٌ مُعلَنٌ لا عيبٌ يُكتشَفُ لاحقًا: `_init_factory` اسمُه خاصٌّ فلا
    يُحصى في دَينِ الهجرةِ بمعيارِ `public == true`، ويُبلَغُ إليه من `get_factory`
    وهو مدخلٌ عامّ. تغييرُ معيارِ العدِّ أو هجرةُ هذه الكتابةِ يستلزمُ حسمَ
    **Q-25** ومَن يملكُ إنشاءَ مصنعٍ (بابُ Q-24) — وليس ذلك لمُنفِّذ.
    """
    counting = _authorizer(CountingAuthorizer, tmp_path, "INIT")
    factory = Factory(FACTORY_ID, authorizer=counting)

    assert counting.calls == []
    assert _count(factory, FactoryModel) == 1


# ═══════════════════════════════════════════════════════════════════════════
# G-5 · أحكامُ المُحرِّكِ على الأفعالِ الثلاثة
# ═══════════════════════════════════════════════════════════════════════════


def test_engine_allows_the_three_actions_for_every_actor(isolated_db: Path) -> None:
    """G-5: `ALLOW` لخمسةِ فاعلين — فالحدُّ هنا حصيلةٌ وأثرٌ ومعوّضٌ لا فصلُ سلطات."""
    for action in (
        factories_module.ACTION_START_PRODUCTION,
        factories_module.ACTION_COMPLETE_STEP,
        factories_module.ACTION_ASSIGN_MANAGER,
    ):
        for actor in ACTORS:
            evidence = ConstitutionalAuthorizer(actor=actor).review_only(
                action, f"factory/{FACTORY_ID}"
            )
            assert evidence.as_dict()["decision"] == "ALLOW", (action, actor)
