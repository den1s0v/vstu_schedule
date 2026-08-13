"""Публичный API слоя корректировок."""

from apps.panel.services.corrections.dictionaries import (
    DICTIONARY_SCHEMA,
    import_dictionary,
    load_dictionary_file,
    validate_dictionary_payload,
)
from apps.panel.services.corrections.links import approve_link, forbid_link, remove_link
from apps.panel.services.corrections.matching import match_variant, similarity
from apps.panel.services.corrections.pipeline import run_pipeline
from apps.panel.services.corrections.rewrite import apply_rewrite
from apps.panel.services.corrections.usage import fingerprint_text, record_usage, usage_totals

__all__ = [
    "DICTIONARY_SCHEMA",
    "apply_rewrite",
    "approve_link",
    "fingerprint_text",
    "forbid_link",
    "import_dictionary",
    "load_dictionary_file",
    "match_variant",
    "record_usage",
    "remove_link",
    "run_pipeline",
    "similarity",
    "usage_totals",
    "validate_dictionary_payload",
]
