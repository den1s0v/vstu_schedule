"""Функции для работы с Resolution."""

import logging

from apps.panel.models import CorrectObject, Occurrence, Resolution

logger = logging.getLogger("apps.panel.services.corrections")


def create_resolution(
    occurrence: Occurrence,
    correct_object: CorrectObject,
    score: float = 0.0,
    manual: bool = False,
    status: int = Resolution.Status.PENDING,
) -> Resolution:
    """Создание нового Resolution."""
    resolution, created = Resolution.objects.get_or_create(
        occurrence=occurrence,
        correct_object=correct_object,
        defaults={
            "score": score,
            "manual": manual,
            "status": status,
            "scope": occurrence.scope,
        }
    )

    if created:
        logger.debug(
            f"Создан Resolution #{resolution.id} для "
            f"Occurrence #{occurrence.id} → CorrectObject #{correct_object.id}"
        )
    else:
        logger.debug(
            f"Resolution уже существует для "
            f"Occurrence #{occurrence.id} → CorrectObject #{correct_object.id}"
        )

    return resolution


def get_best_resolution(occurrence: Occurrence) -> Resolution | None:
    """
    Получение лучшего Resolution для Occurrence.

    Приоритет:
    1. APPROVED (если есть)
    2. PENDING с максимальным score (исключая INVALID)
    """
    # Сначала ищем APPROVED
    approved = Resolution.objects.filter(
        occurrence=occurrence,
        status=Resolution.Status.APPROVED
    ).first()

    if approved:
        return approved

    # Ищем лучший PENDING по score
    best_pending = Resolution.objects.filter(
        occurrence=occurrence,
        status=Resolution.Status.PENDING
    ).order_by("-score").first()

    return best_pending


def update_resolution_cache(occurrence: Occurrence, resolution: Resolution | None) -> None:
    """
    Обновление кеша resolved_to для Occurrence.
    
    Сохраняет CorrectObject из лучшего Resolution в occurrence.resolved_to.
    """
    from django.utils import timezone

    if resolution and resolution.correct_object:
        occurrence.resolved_to = resolution.correct_object
    else:
        occurrence.resolved_to = None

    occurrence.updated_at = timezone.now()
    occurrence.save(update_fields=["resolved_to", "updated_at"])

    logger.debug(f"Обновлен кеш resolved_to для Occurrence #{occurrence.id}")
