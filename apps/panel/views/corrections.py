"""Views для работы с корректировками."""

import logging
from typing import Any

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from apps.panel.models import Resolution, Scope
from apps.panel.selectors import (
    get_conflicting_resolutions,
    get_resolutions_by_occurrence,
    get_resolutions_by_status,
)

logger = logging.getLogger("apps.panel.views.corrections")


@login_required
@require_http_methods(["GET"])
def resolution_list(request: HttpRequest) -> HttpResponse:
    """Список Resolution с фильтрами."""
    # Получаем параметры фильтрации
    scope_id = request.GET.get("scope_id", "")
    search_occurrence = request.GET.get("search_occurrence", "").strip()
    search_correct = request.GET.get("search_correct", "").strip()
    status_filter = request.GET.getlist("status", [])
    conflicts_only = request.GET.get("conflicts_only", "") == "1"
    sort_by = request.GET.get("sort_by", "-score")
    page_num = request.GET.get("page", 1)
    
    # Базовый QuerySet
    queryset = Resolution.objects.select_related(
        "occurrence", "correct_object", "scope"
    ).all()
    
    # Фильтр по scope
    if scope_id:
        try:
            scope_id_int = int(scope_id)
            queryset = queryset.filter(scope_id=scope_id_int)
        except ValueError:
            pass
    
    # Поиск по Occurrence.value
    if search_occurrence:
        queryset = queryset.filter(occurrence__value__icontains=search_occurrence)
    
    # Поиск по CorrectObject.value
    if search_correct:
        queryset = queryset.filter(correct_object__value__icontains=search_correct)
    
    # Фильтр по статусам
    if status_filter:
        try:
            status_ints = [int(s) for s in status_filter]
            queryset = queryset.filter(status__in=status_ints)
        except ValueError:
            pass
    
    # Фильтр по конфликтным случаям
    if conflicts_only:
        conflicting_occurrence_ids = (
            Resolution.objects
            .filter(scope_id=scope_id_int if scope_id else None)
            .values("occurrence_id")
            .annotate(count=Count("id"))
            .filter(count__gt=1, status=Resolution.Status.PENDING)
            .values_list("occurrence_id", flat=True)
        )
        queryset = queryset.filter(occurrence_id__in=conflicting_occurrence_ids)
    
    # Сортировка
    allowed_sort_fields = [
        "score", "-score",
        "occurrence__value", "-occurrence__value",
        "correct_object__value", "-correct_object__value",
        "created_at", "-created_at",
        "updated_at", "-updated_at",
    ]
    if sort_by in allowed_sort_fields:
        queryset = queryset.order_by(sort_by)
    else:
        queryset = queryset.order_by("-score", "-created_at")
    
    # Пагинация
    paginator = Paginator(queryset, per_page=50)
    page = paginator.get_page(page_num)
    
    # Статистика
    total_count = Resolution.objects.count()
    pending_count = Resolution.objects.filter(status=Resolution.Status.PENDING).count()
    approved_count = Resolution.objects.filter(status=Resolution.Status.APPROVED).count()
    invalid_count = Resolution.objects.filter(status=Resolution.Status.INVALID).count()
    
    # Список scope для фильтра
    scopes = Scope.objects.all().order_by("id")
    
    context = {
        "page": page,
        "resolutions": page.object_list,
        "scopes": scopes,
        "current_scope_id": scope_id,
        "search_occurrence": search_occurrence,
        "search_correct": search_correct,
        "status_filter": status_filter,
        "conflicts_only": conflicts_only,
        "sort_by": sort_by,
        "stats": {
            "total": total_count,
            "pending": pending_count,
            "approved": approved_count,
            "invalid": invalid_count,
        },
    }
    
    return render(request, "panel/corrections/resolution_list.html", context)


@login_required
@require_http_methods(["GET", "POST"])
def resolution_edit(request: HttpRequest, resolution_id: int) -> HttpResponse:
    """Редактирование Resolution."""
    resolution = get_object_or_404(
        Resolution.objects.select_related("occurrence", "correct_object", "scope"),
        id=resolution_id
    )
    
    if request.method == "POST":
        action = request.POST.get("action")
        
        if action == "approve":
            # Утверждение: сначала аннулируем другие APPROVED для этого Occurrence
            Resolution.objects.filter(
                occurrence=resolution.occurrence,
                status=Resolution.Status.APPROVED
            ).exclude(pk=resolution.pk).update(status=Resolution.Status.PENDING)
            
            resolution.status = Resolution.Status.APPROVED
            resolution.manual = True
            resolution.save()
            logger.info(f"Resolution #{resolution.id} утверждено пользователем {request.user.username}")
            return redirect("panel:corrections:resolution_list")
        
        elif action == "invalidate":
            resolution.status = Resolution.Status.INVALID
            resolution.manual = True
            resolution.save()
            logger.info(f"Resolution #{resolution.id} аннулировано пользователем {request.user.username}")
            return redirect("panel:corrections:resolution_list")
        
        elif action == "delete":
            resolution.delete()
            logger.info(f"Resolution #{resolution.id} удалено пользователем {request.user.username}")
            return redirect("panel:corrections:resolution_list")
        
        elif action == "change_status":
            new_status = request.POST.get("status")
            try:
                new_status_int = int(new_status)
                if new_status_int in [Resolution.Status.PENDING, Resolution.Status.APPROVED, Resolution.Status.INVALID]:
                    # При утверждении аннулируем другие APPROVED
                    if new_status_int == Resolution.Status.APPROVED:
                        Resolution.objects.filter(
                            occurrence=resolution.occurrence,
                            status=Resolution.Status.APPROVED
                        ).exclude(pk=resolution.pk).update(status=Resolution.Status.PENDING)
                    
                    resolution.status = new_status_int
                    resolution.manual = True
                    resolution.save()
                    logger.info(
                        f"Статус Resolution #{resolution.id} изменен на {new_status_int} "
                        f"пользователем {request.user.username}"
                    )
                    return redirect("panel:corrections:resolution_edit", resolution_id=resolution_id)
            except ValueError:
                pass
    
    # Получаем все Resolution для этого Occurrence
    related_resolutions = get_resolutions_by_occurrence(resolution.occurrence_id)
    
    context = {
        "resolution": resolution,
        "related_resolutions": related_resolutions,
    }
    
    return render(request, "panel/corrections/resolution_edit.html", context)
