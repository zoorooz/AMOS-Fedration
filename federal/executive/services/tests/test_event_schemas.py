"""
اختبارات مخططات الأحداث
الهدف: التحقق من قبول حدث صحيح ورفض حدث ناقص
النطاق: common/event_schemas.py
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-15
"""

import builtins
import logging

import pytest

from amos_federation.common.event_schemas import validate_event


def valid_task_event() -> dict[str, object]:
    """إنشاء مثال متوافق مع عقد task.created المسجل."""
    return {
        "event_id": "123e4567-e89b-12d3-a456-426614174000",
        "timestamp": "2026-08-15T00:00:00Z",
        "event_type": "task.created",
        "source": "api-gateway",
        "data": {
            "task_id": "task-001",
            "type": "analysis",
            "description": "تحليل المبيعات",
            "priority": "high",
            "domain": "finance",
        },
        "chain_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    }


def test_validate_event_accepts_correct_payload() -> None:
    """المخطط يقبل الحدث الكامل المتوافق."""
    assert validate_event("task.created", valid_task_event())


def test_validate_event_rejects_missing_required_field() -> None:
    """المخطط يرفض الحدث عند غياب حقل مطلوب."""
    payload = valid_task_event()
    del payload["data"]
    assert not validate_event("task.created", payload)


def violating_task_event() -> dict[str, object]:
    """حمل يحمل كل الحقول المطلوبة ويخالف المخطط فيما دونها."""
    payload = valid_task_event()
    payload["chain_hash"] = "not-a-sha256-digest"  # يخالف pattern
    payload["extra_field"] = "forbidden"  # يخالف additionalProperties=false
    return payload


def _block_jsonschema(monkeypatch: pytest.MonkeyPatch) -> None:
    """حجب jsonschema وحدها لقياس مسار الهبوط دون لمس الشيفرة."""
    real_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "jsonschema":
            raise ImportError("jsonschema محجوبة للقياس")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", fake_import)


def test_validate_event_rejects_schema_violation_beyond_required_fields() -> None:
    """التحقق الكامل يرفض مخالفة لا يبلغها فحص الحقول المطلوبة.

    وهذا هو مكسب إعلان jsonschema في pyproject.toml مقيسًا لا مدّعى.
    """
    assert not validate_event("task.created", violating_task_event())


def test_validate_event_degrades_visibly_when_jsonschema_absent(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """عند غياب jsonschema يقبل الحمل المخالف ويُعلن الضعف تحذيرًا لا صمتًا."""
    _block_jsonschema(monkeypatch)
    with caplog.at_level(logging.WARNING):
        assert validate_event("task.created", violating_task_event())
    assert any(
        "jsonschema" in record.getMessage() and record.levelno == logging.WARNING
        for record in caplog.records
    ), "هبوط قوة التحقق لا يجوز أن يجري في صمت"


def test_degraded_check_still_reads_nested_requirements_and_const(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """فحص الهبوط يبقى مقيسًا: يرفض نقص حقل متفرع ويرفض مخالفة const."""
    _block_jsonschema(monkeypatch)

    nested_missing = valid_task_event()
    del nested_missing["data"]["task_id"]  # type: ignore[index]
    assert not validate_event("task.created", nested_missing)

    wrong_const = valid_task_event()
    wrong_const["event_type"] = "task.deleted"
    assert not validate_event("task.created", wrong_const)
