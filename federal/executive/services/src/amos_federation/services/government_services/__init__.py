"""
AMOS-Federation Government Services
الهدف: خدمات الدولة وقضاياها وقراراتها فوق السجل الفدرالي وبأثر تنفيذي حقيقي
النطاق: services/government_services
المالك: federal/executive/services
تاريخ الإنشاء: 2026-08-17 (R7-A، الوحدة 2)
"""

from amos_federation.services.government_services.service import (
    GovernmentServices,
    get_government_services,
    reset_government_services,
)

__all__ = ["GovernmentServices", "get_government_services", "reset_government_services"]
