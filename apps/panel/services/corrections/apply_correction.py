"""Главная функция API для применения корректировок."""

import logging
from typing import Any, Optional

from django.db import transaction
from rapidfuzz.distance import JaroWinkler

from apps.panel.models import Occurrence, CorrectObject, Resolution, Scope
from apps.panel.services.corrections.cache import is_cache_valid, invalidate_cache_for_scope
from apps.panel.services.corrections.context import (
    ContextElement,
    check_context_match,
    parse_context_elements,
)
from apps.panel.services.corrections.correct_object import find_or_create_correct_object
from apps.panel.services.corrections.resolution import (
    create_resolution,
    get_best_resolution,
    update_resolution_cache,
)

logger = logging.getLogger("apps.panel.services.corrections")


def _find_or_create_occurrence(
    value: str,
    context: list[ContextElement],
    scope_id: int,
) -> Occurrence:
    """
    Поиск или создание Occurrence с проверкой покрытия контекста.
    
    Новый Occurrence не добавляется, если уже существует такой, набор элементов
    контекста которого полностью покрывает элементы контекста кандидата.
    """
    # Преобразуем ContextElement в словари для JSONField
    context_dicts = [elem.to_dict() for elem in context]
    
    # Ищем существующие Occurrence с совпадающим value
    existing = Occurrence.objects.filter(value=value, scope_id=scope_id)
    
    for occ in existing:
        # Проверяем, покрывает ли контекст существующего контекст кандидата
        existing_context = parse_context_elements(occ.context)
        existing_dict = {elem.key: elem.value for elem in existing_context}
        
        # Все элементы кандидата должны присутствовать в существующем с теми же значениями
        covers = True
        for candidate_elem in context:
            if candidate_elem.key not in existing_dict:
                covers = False
                break
            if existing_dict[candidate_elem.key] != candidate_elem.value:
                covers = False
                break
        
        if covers:
            logger.debug(f"Найден существующий Occurrence #{occ.id}, покрывающий контекст")
            return occ
    
    # Создаем новый
    occurrence = Occurrence.objects.create(
        value=value,
        context=context_dicts,
        scope_id=scope_id,
    )
    logger.info(f"Создан новый Occurrence #{occurrence.id} для value={value[:50]}")
    return occurrence


def _calculate_value_similarity(value1: str, value2: str) -> float:
    """
    Вычисление схожести значений.
    
    Полное равенство: 1.0
    Неполное совпадение: Jaro-Winkler normalized_similarity
    """
    if value1 == value2:
        return 1.0
    
    return JaroWinkler.normalized_similarity(value1, value2)


def _calculate_resolution_score(
    occurrence: Occurrence,
    correct_object: CorrectObject,
) -> float:
    """
    Вычисление score для Resolution.
    
    Формула: 10 * (оценка близости по value) + взвешенная сумма совпавших элементов контекста
    """
    # Оценка близости по value
    value_similarity = _calculate_value_similarity(occurrence.value, correct_object.value)
    value_score = 10.0 * value_similarity
    
    # Взвешенная сумма совпавших элементов контекста
    occurrence_context = parse_context_elements(occurrence.context)
    required_elements = parse_context_elements(correct_object.required_context_elements)
    
    _, context_score = check_context_match(occurrence_context, required_elements)
    
    total_score = value_score + context_score
    logger.debug(
        f"Score для Occurrence #{occurrence.id} → CorrectObject #{correct_object.id}: "
        f"{total_score} (value: {value_score}, context: {context_score})"
    )
    
    return total_score


def _get_or_create_default_scope(scope_id: int) -> Scope:
    """Получение или создание Scope по ID."""
    if scope_id == 0:
        # Создаем или получаем Scope с id=1 как дефолтный (id=0 не может быть для ForeignKey)
        scope, _ = Scope.objects.get_or_create(
            id=1,
            defaults={"description": "Default scope"}
        )
        return scope
    else:
        return Scope.objects.get(id=scope_id)


@transaction.atomic
def apply_correction(
    value: str,
    context: list[dict[str, Any]],
    scope_id: int = 0,
    hypotheses: Optional[list[dict[str, Any]]] = None,
) -> Optional[CorrectObject]:
    """
    Возвращает CorrectObject для заданного Occurrence.
    
    Алгоритм:
    0. Для поданного Occurrence: найти в БД или добавить в БД
    0.5. Обработка гипотез (если переданы)
    1. Найти существующее Resolution для Occurrence
    2. Если не найдено - выполнить анализ и создать Resolution
    3. Найти лучшую по score Resolution
    4. Если не найдено - создать новый CorrectObject
    5. Вернуть CorrectObject или None
    """
    if hypotheses is None:
        hypotheses = []
    
    # Получаем или создаем Scope
    scope = _get_or_create_default_scope(scope_id)
    actual_scope_id = scope.id
    
    # Парсим контекст
    occurrence_context = parse_context_elements(context)
    
    # 0. Поиск/создание Occurrence
    occurrence = _find_or_create_occurrence(value, occurrence_context, actual_scope_id)
    
    # 0.5. Обработка гипотез
    hypothesis_objects: list[CorrectObject] = []
    for hyp_data in hypotheses:
        hyp_context = parse_context_elements(hyp_data.get("context", []))
        hyp_required = parse_context_elements(hyp_data.get("required_context_elements", []))
        
        hyp_obj = find_or_create_correct_object(
            value=hyp_data.get("value", ""),
            scope_id=actual_scope_id,
            external_id=hyp_data.get("external_id"),
            name=hyp_data.get("name"),
            description=hyp_data.get("description"),
            required_context_elements=hyp_required,
            context=hyp_context,
        )
        hypothesis_objects.append(hyp_obj)
        logger.debug(f"Обработана гипотеза: CorrectObject #{hyp_obj.id}")
    
    # 1. Поиск существующего Resolution
    approved_resolution = Resolution.objects.filter(
        occurrence=occurrence,
        status=Resolution.Status.APPROVED
    ).first()
    
    if approved_resolution:
        logger.debug(f"Найден APPROVED Resolution #{approved_resolution.id}")
        return approved_resolution.correct_object
    
    # Проверка кеша
    if is_cache_valid(occurrence) and occurrence.resolved_to:
        logger.debug(f"Использован кеш resolved_to для Occurrence #{occurrence.id}")
        return occurrence.resolved_to
    
    # 2. Анализ и создание Resolution
    # Получаем все CorrectObject для scope (включая гипотезы)
    all_correct_objects = list(
        CorrectObject.objects.filter(scope_id=actual_scope_id)
    ) + hypothesis_objects
    
    # Удаляем дубликаты по id
    seen_ids = set()
    unique_correct_objects = []
    for co in all_correct_objects:
        if co.id not in seen_ids:
            seen_ids.add(co.id)
            unique_correct_objects.append(co)
    
    # Проверяем каждый CorrectObject на соответствие
    new_resolutions = []
    for correct_object in unique_correct_objects:
        required_elements = parse_context_elements(correct_object.required_context_elements)
        matches, _ = check_context_match(occurrence_context, required_elements)
        
        if matches:
            # Вычисляем score
            score = _calculate_resolution_score(occurrence, correct_object)
            
            # Проверяем, нет ли явного INVALID для этой пары
            existing_invalid = Resolution.objects.filter(
                occurrence=occurrence,
                correct_object=correct_object,
                status=Resolution.Status.INVALID
            ).exists()
            
            if not existing_invalid:
                resolution = create_resolution(
                    occurrence=occurrence,
                    correct_object=correct_object,
                    score=score,
                    manual=False,
                    status=Resolution.Status.PENDING,
                )
                new_resolutions.append(resolution)
                logger.debug(
                    f"Создан PENDING Resolution #{resolution.id} "
                    f"для Occurrence #{occurrence.id} → CorrectObject #{correct_object.id}"
                )
    
    # Удаляем старые Resolution, которые больше не корректны
    # (те, для которых больше нет соответствия)
    if new_resolutions:
        existing_resolutions = Resolution.objects.filter(
            occurrence=occurrence,
            status__in=[Resolution.Status.PENDING, Resolution.Status.INVALID]
        ).exclude(
            correct_object__in=[r.correct_object for r in new_resolutions]
        )
        
        # Не удаляем INVALID, созданные вручную
        to_delete = existing_resolutions.exclude(
            manual=True,
            status=Resolution.Status.INVALID
        )
        deleted_count = to_delete.count()
        to_delete.delete()
        if deleted_count > 0:
            logger.debug(f"Удалено {deleted_count} устаревших Resolution для Occurrence #{occurrence.id}")
    
    # 3. Найти лучшую по score Resolution
    best_resolution = get_best_resolution(occurrence)
    
    if best_resolution:
        update_resolution_cache(occurrence, best_resolution)
        logger.info(
            f"Найдено лучшее Resolution #{best_resolution.id} "
            f"для Occurrence #{occurrence.id} (score: {best_resolution.score})"
        )
        return best_resolution.correct_object
    
    # 4. Создать новый CorrectObject на основе Occurrence
    # Используем все элементы контекста со статусом important
    important_context = [
        elem for elem in occurrence_context if elem.important
    ]
    
    # Проверяем, нет ли явного INVALID для прямого Resolution
    # (создаем CorrectObject, идентичный Occurrence)
    direct_invalid = Resolution.objects.filter(
        occurrence=occurrence,
        correct_object__value=occurrence.value,
        correct_object__required_context_elements=[elem.to_dict() for elem in important_context],
        status=Resolution.Status.INVALID
    ).exists()
    
    if not direct_invalid:
        new_correct_object = find_or_create_correct_object(
            value=occurrence.value,
            scope_id=actual_scope_id,
            required_context_elements=important_context,
            context=occurrence_context,
        )
        
        # Создаем Resolution
        score = _calculate_resolution_score(occurrence, new_correct_object)
        resolution = create_resolution(
            occurrence=occurrence,
            correct_object=new_correct_object,
            score=score,
            manual=False,
            status=Resolution.Status.PENDING,
        )
        
        update_resolution_cache(occurrence, resolution)
        logger.info(
            f"Создан новый CorrectObject #{new_correct_object.id} "
            f"и Resolution #{resolution.id} для Occurrence #{occurrence.id}"
        )
        return new_correct_object
    
    # 5. Не удалось создать
    logger.warning(f"Не удалось создать CorrectObject для Occurrence #{occurrence.id}")
    return None
