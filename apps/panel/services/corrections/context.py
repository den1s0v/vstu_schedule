"""Функции для работы с контекстом и проверки соответствия элементов."""

import logging
from typing import Any

logger = logging.getLogger("apps.panel.services.corrections")


class ContextElement:
    """Элемент контекста (ключ-значение)."""

    def __init__(
        self,
        key: str,
        value: str,
        important: bool = False,
        weight: float = 1.0,
        absence_allowed: bool = False,
    ) -> None:
        self.key = key
        self.value = value
        self.important = important
        self.weight = weight
        self.absence_allowed = absence_allowed

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ContextElement":
        """Создание ContextElement из словаря."""
        return cls(
            key=data.get("key", ""),
            value=data.get("value", ""),
            important=data.get("important", False),
            weight=data.get("weight", 1.0),
            absence_allowed=data.get("absence_allowed", False),
        )

    def to_dict(self) -> dict[str, Any]:
        """Преобразование в словарь."""
        return {
            "key": self.key,
            "value": self.value,
            "important": self.important,
            "weight": self.weight,
            "absence_allowed": self.absence_allowed,
        }


def parse_context_elements(context_data: list[dict[str, Any]]) -> list[ContextElement]:
    """Парсинг списка элементов контекста из JSON."""
    return [ContextElement.from_dict(item) for item in context_data]


def check_context_match(
    occurrence_context: list[ContextElement],
    required_elements: list[ContextElement],
) -> tuple[bool, float]:
    """
    Проверка соответствия элементов контекста Occurrence требуемым элементам CorrectObject.
    
    Возвращает:
        (matches, score) - соответствует ли и оценка совпадения (сумма weight совпавших элементов)
    """
    matches = True
    total_score = 0.0

    # Создаем словарь для быстрого поиска элементов контекста Occurrence
    occurrence_dict = {elem.key: elem for elem in occurrence_context}

    for required in required_elements:
        occurrence_elem = occurrence_dict.get(required.key)

        if occurrence_elem is None:
            # Элемент отсутствует в Occurrence
            if required.absence_allowed:
                # Отсутствие допустимо, но score будет меньше
                matches = True
                # Не добавляем weight к score
            else:
                # Отсутствие недопустимо - не соответствует
                matches = False
                break
        else:
            # Элемент присутствует, проверяем значение
            if occurrence_elem.value == required.value:
                # Значения совпадают
                total_score += required.weight
            else:
                # Значения различаются
                if required.important:
                    # Важный элемент не совпал - не соответствует
                    matches = False
                    break
                else:
                    # Неважный элемент не совпал - соответствует, но score меньше
                    # Не добавляем weight к score
                    pass

    return matches, total_score
