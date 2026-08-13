"""Публичная точка импорта селекторов панели."""

from apps.panel.corrections.selectors import (
    active_rewrite_rules,
    correct_objects_for_type,
    forbidden_links,
    open_disambiguation_cases,
    rewrite_rules_for_scope,
    usage_map,
    variants_for_type,
)

__all__ = [
    "active_rewrite_rules",
    "correct_objects_for_type",
    "forbidden_links",
    "open_disambiguation_cases",
    "rewrite_rules_for_scope",
    "usage_map",
    "variants_for_type",
]
