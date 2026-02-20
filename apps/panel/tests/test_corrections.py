"""Тесты для модуля корректировок."""

import pytest
from django.utils import timezone

from apps.panel.models import Scope, Occurrence, CorrectObject, Resolution
from apps.panel.services.corrections import apply_correction, find_or_create_correct_object
from apps.panel.services.corrections.context import ContextElement, check_context_match


@pytest.fixture
def scope(db):
    """Создание тестового Scope."""
    return Scope.objects.create(description="Test scope")


@pytest.fixture
def occurrence_data():
    """Тестовые данные для Occurrence."""
    return {
        "value": "Тестовое значение",
        "context": [
            {"key": "type", "value": "test", "important": True, "weight": 1.0, "absence_allowed": False},
            {"key": "category", "value": "sample", "important": False, "weight": 0.5, "absence_allowed": True},
        ],
    }


@pytest.mark.django_db
def test_find_or_create_correct_object(scope):
    """Тест создания и поиска CorrectObject."""
    # Создание нового
    obj1 = find_or_create_correct_object(
        value="Test Object",
        scope_id=scope.id,
        external_id="ext-123",
    )
    assert obj1.id is not None
    assert obj1.value == "Test Object"
    assert obj1.external_id == "ext-123"
    
    # Поиск по external_id
    obj2 = find_or_create_correct_object(
        value="Different Value",
        scope_id=scope.id,
        external_id="ext-123",
    )
    assert obj2.id == obj1.id
    assert obj2.value == "Test Object"  # Не изменилось
    
    # Создание без external_id
    context_elements = [
        ContextElement(key="type", value="test", important=True),
    ]
    obj3 = find_or_create_correct_object(
        value="Test Object 2",
        scope_id=scope.id,
        required_context_elements=context_elements,
    )
    assert obj3.id is not None
    
    # Поиск по value + context
    obj4 = find_or_create_correct_object(
        value="Test Object 2",
        scope_id=scope.id,
        required_context_elements=context_elements,
    )
    assert obj4.id == obj3.id


@pytest.mark.django_db
def test_check_context_match():
    """Тест проверки соответствия контекста."""
    occurrence_context = [
        ContextElement(key="type", value="test", important=True),
        ContextElement(key="category", value="sample", important=False),
    ]
    
    required_elements = [
        ContextElement(key="type", value="test", important=True, absence_allowed=False),
    ]
    
    matches, score = check_context_match(occurrence_context, required_elements)
    assert matches is True
    assert score > 0
    
    # Несоответствие важного элемента
    required_elements_wrong = [
        ContextElement(key="type", value="different", important=True, absence_allowed=False),
    ]
    matches, _ = check_context_match(occurrence_context, required_elements_wrong)
    assert matches is False
    
    # Отсутствие элемента с absence_allowed=True
    required_elements_optional = [
        ContextElement(key="missing", value="any", important=False, absence_allowed=True),
    ]
    matches, _ = check_context_match(occurrence_context, required_elements_optional)
    assert matches is True


@pytest.mark.django_db
def test_apply_correction_simple(scope, occurrence_data):
    """Тест простого применения корректировки."""
    # Создаем CorrectObject заранее
    correct_obj = CorrectObject.objects.create(
        value="Тестовое значение",
        scope=scope,
        required_context_elements=[
            {"key": "type", "value": "test", "important": True, "weight": 1.0, "absence_allowed": False}
        ],
    )
    
    # Применяем корректировку
    result = apply_correction(
        value=occurrence_data["value"],
        context=occurrence_data["context"],
        scope_id=scope.id,
    )
    
    assert result is not None
    assert result.id == correct_obj.id
    
    # Проверяем, что создался Occurrence
    occurrence = Occurrence.objects.get(value=occurrence_data["value"], scope=scope)
    assert occurrence is not None
    
    # Проверяем, что создался Resolution
    resolution = Resolution.objects.filter(occurrence=occurrence, correct_object=correct_obj).first()
    assert resolution is not None
    assert resolution.status == Resolution.Status.PENDING


@pytest.mark.django_db
def test_apply_correction_with_hypotheses(scope, occurrence_data):
    """Тест применения корректировки с гипотезами."""
    # Применяем с гипотезой
    result = apply_correction(
        value=occurrence_data["value"],
        context=occurrence_data["context"],
        scope_id=scope.id,
        hypotheses=[
            {
                "value": "Гипотеза 1",
                "context": occurrence_data["context"],
                "required_context_elements": occurrence_data["context"],
            }
        ],
    )
    
    assert result is not None
    
    # Проверяем, что гипотеза сохранилась как CorrectObject
    hypothesis_obj = CorrectObject.objects.filter(value="Гипотеза 1", scope=scope).first()
    assert hypothesis_obj is not None


@pytest.mark.django_db
def test_apply_correction_creates_new_correct_object(scope, occurrence_data):
    """Тест создания нового CorrectObject при отсутствии подходящих."""
    # Применяем корректировку без существующих CorrectObject
    result = apply_correction(
        value="Уникальное значение",
        context=occurrence_data["context"],
        scope_id=scope.id,
    )
    
    assert result is not None
    assert result.value == "Уникальное значение"
    
    # Проверяем, что создался Resolution
    occurrence = Occurrence.objects.get(value="Уникальное значение", scope=scope)
    resolution = Resolution.objects.filter(occurrence=occurrence).first()
    assert resolution is not None


@pytest.mark.django_db
def test_resolution_approval_priority(scope, occurrence_data):
    """Тест приоритета APPROVED Resolution."""
    # Создаем CorrectObject
    correct_obj = CorrectObject.objects.create(
        value=occurrence_data["value"],
        scope=scope,
        required_context_elements=occurrence_data["context"],
    )
    
    # Применяем корректировку
    result1 = apply_correction(
        value=occurrence_data["value"],
        context=occurrence_data["context"],
        scope_id=scope.id,
    )
    assert result1 is not None
    
    # Создаем APPROVED Resolution вручную
    occurrence = Occurrence.objects.get(value=occurrence_data["value"], scope=scope)
    approved_resolution = Resolution.objects.create(
        occurrence=occurrence,
        correct_object=correct_obj,
        status=Resolution.Status.APPROVED,
        scope=scope,
    )
    
    # При повторном применении должен вернуться APPROVED
    result2 = apply_correction(
        value=occurrence_data["value"],
        context=occurrence_data["context"],
        scope_id=scope.id,
    )
    assert result2 is not None
    assert result2.id == correct_obj.id
