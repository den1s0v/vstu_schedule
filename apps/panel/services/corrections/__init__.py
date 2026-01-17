"""Модуль корректировок для автоматического разрешения неоднозначностей в данных."""

from apps.panel.services.corrections.apply_correction import apply_correction
from apps.panel.services.corrections.correct_object import find_or_create_correct_object

__all__ = [
    "apply_correction",
    "find_or_create_correct_object",
]
