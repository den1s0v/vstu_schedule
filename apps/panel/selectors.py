"""Селекторы для сложных выборок из БД."""

from django.db.models import QuerySet

from apps.panel.models import Occurrence, CorrectObject, Resolution, Scope


def get_occurrences_by_scope(scope_id: int) -> QuerySet[Occurrence]:
    """Получение всех Occurrence для указанного scope."""
    return Occurrence.objects.filter(scope_id=scope_id).select_related("scope", "resolved_to")


def get_resolutions_by_occurrence(occurrence_id: int) -> QuerySet[Resolution]:
    """Получение всех Resolution для указанного Occurrence."""
    return Resolution.objects.filter(
        occurrence_id=occurrence_id
    ).select_related("occurrence", "correct_object", "scope").order_by("-score", "-created_at")


def get_conflicting_resolutions(scope_id: int) -> QuerySet[Resolution]:
    """
    Получение конфликтных Resolution (неразрешенные дубли).
    
    Конфликтные - это те, где один Occurrence имеет несколько PENDING Resolution
    без APPROVED.
    """
    from django.db.models import Count
    
    # Находим Occurrence с несколькими PENDING Resolution
    occurrences_with_multiple_pending = (
        Resolution.objects
        .filter(scope_id=scope_id, status=Resolution.Status.PENDING)
        .values("occurrence_id")
        .annotate(count=Count("id"))
        .filter(count__gt=1)
        .values_list("occurrence_id", flat=True)
    )
    
    # Возвращаем все PENDING Resolution для этих Occurrence
    return Resolution.objects.filter(
        occurrence_id__in=occurrences_with_multiple_pending,
        status=Resolution.Status.PENDING
    ).select_related("occurrence", "correct_object", "scope").order_by("occurrence_id", "-score")


def get_correct_objects_by_scope(scope_id: int) -> QuerySet[CorrectObject]:
    """Получение всех CorrectObject для указанного scope."""
    return CorrectObject.objects.filter(scope_id=scope_id).select_related("scope")


def get_approved_resolution_for_occurrence(occurrence_id: int) -> Resolution | None:
    """Получение APPROVED Resolution для указанного Occurrence (если есть)."""
    return Resolution.objects.filter(
        occurrence_id=occurrence_id,
        status=Resolution.Status.APPROVED
    ).select_related("occurrence", "correct_object").first()


def get_resolutions_by_status(scope_id: int, status: int) -> QuerySet[Resolution]:
    """Получение Resolution по статусу для указанного scope."""
    return Resolution.objects.filter(
        scope_id=scope_id,
        status=status
    ).select_related("occurrence", "correct_object", "scope").order_by("-score", "-created_at")
