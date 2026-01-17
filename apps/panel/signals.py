"""Сигналы Django для обновления scope.updated_at при изменении CorrectObject."""

import logging

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.panel.models import CorrectObject, Scope
from apps.panel.services.corrections.cache import invalidate_cache_for_scope

logger = logging.getLogger("apps.panel.signals")


@receiver(post_save, sender=CorrectObject)
def update_scope_on_correct_object_save(sender, instance: CorrectObject, **kwargs) -> None:
    """Обновление scope.updated_at при сохранении CorrectObject."""
    from django.utils import timezone
    
    if instance.scope_id:
        Scope.objects.filter(id=instance.scope_id).update(updated_at=timezone.now())
        invalidate_cache_for_scope(instance.scope_id)
        logger.debug(f"Обновлен scope.updated_at для scope #{instance.scope_id} после сохранения CorrectObject #{instance.id}")


@receiver(post_delete, sender=CorrectObject)
def update_scope_on_correct_object_delete(sender, instance: CorrectObject, **kwargs) -> None:
    """Обновление scope.updated_at при удалении CorrectObject."""
    from django.utils import timezone
    
    if instance.scope_id:
        Scope.objects.filter(id=instance.scope_id).update(updated_at=timezone.now())
        invalidate_cache_for_scope(instance.scope_id)
        logger.debug(f"Обновлен scope.updated_at для scope #{instance.scope_id} после удаления CorrectObject #{instance.id}")
