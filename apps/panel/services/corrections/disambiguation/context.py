"""Подсказки L3 на основе элементов контекста (не фильтр L2)."""

from __future__ import annotations

from typing import Any

from rapidfuzz.distance import JaroWinkler


def context_weight_score(
    occurrence_context: dict[str, Any],
    required: list[dict[str, Any]],
) -> float:
    """Взвешенная сумма совпавших элементов контекста."""
    total = 0.0
    for item in required:
        key = item.get("key")
        if key is None:
            continue
        weight = float(item.get("weight", 1.0))
        expected = item.get("value")
        actual = occurrence_context.get(key)
        if actual is None:
            if item.get("absence_allowed"):
                continue
            return 0.0
        if actual == expected:
            total += weight
        elif item.get("important"):
            return 0.0
    return total


def text_hint_score(a: str, b: str) -> float:
    """Подсказка близости для UI L3 на шкале [0..1]."""
    if a == b:
        return 1.0
    return float(JaroWinkler.normalized_similarity(a, b))
