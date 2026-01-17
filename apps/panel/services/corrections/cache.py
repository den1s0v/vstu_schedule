"""Функции для кеширования resolved_to."""

import logging

from apps.panel.models import Occurrence, Scope

logger = logging.getLogger("apps.panel.services.corrections")


def is_cache_valid(occurrence: Occurrence) -> bool:
    """
    Проверка актуальности кеша resolved_to.
    
    Кеш актуален, если occurrence.updated_at >= scope.updated_at.
    """
    if occurrence.resolved_to is None:
        return False

    try:
        scope = occurrence.scope
        if scope is None:
            # Если scope не найден, считаем кеш невалидным
            return False

        # Кеш актуален, если дата обновления occurrence >= даты обновления scope
        return occurrence.updated_at >= scope.updated_at
    except Scope.DoesNotExist:
        logger.warning(f"Scope для Occurrence #{occurrence.id} не найден")
        return False


def invalidate_cache_for_scope(scope_id: int) -> None:
    """
    Инвалидация кеша resolved_to для всех Occurrence в указанном scope.
    
    Фактически просто обновляет updated_at для всех Occurrence в scope,
    что приведет к пересчету при следующей проверке.
    """
    from django.db import transaction
    from django.utils import timezone

    with transaction.atomic():
        # Обновляем updated_at для всех Occurrence в scope
        # Это инвалидирует кеш, так как is_cache_valid проверяет updated_at
        Occurrence.objects.filter(scope_id=scope_id).update(updated_at=timezone.now())
        logger.info(f"Инвалидирован кеш для {Occurrence.objects.filter(scope_id=scope_id).count()} Occurrence в scope #{scope_id}")
