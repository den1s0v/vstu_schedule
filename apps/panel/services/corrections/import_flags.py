"""Флаги и фабрика резолвера для импорта с L1/L2/L3."""

from __future__ import annotations

from typing import Any

from django.conf import settings

from apps.common.services.timetable.load.resolution import EntityResolver, ResolutionReport
from apps.panel.services.corrections.timetable import (
    CorrectionsEntityResolver,
    seed_dictionary_from_orm,
)


def resolve_import_flags(
    *,
    use_corrections: bool | None = None,
    corrections_strict: bool | None = None,
) -> tuple[bool, bool]:
    """Явный аргумент побеждает env/settings; None → settings."""
    enabled = (
        bool(use_corrections)
        if use_corrections is not None
        else bool(getattr(settings, "IMPORT_USE_CORRECTIONS", False))
    )
    strict = (
        bool(corrections_strict)
        if corrections_strict is not None
        else bool(getattr(settings, "IMPORT_CORRECTIONS_STRICT", False))
    )
    if not enabled:
        strict = False
    return enabled, strict


def build_import_resolver(
    *,
    use_corrections: bool | None = None,
    actor: Any | None = None,
    seed: bool = True,
) -> EntityResolver | None:
    """Вернуть CorrectionsEntityResolver или None, если слой выключен."""
    enabled, _ = resolve_import_flags(use_corrections=use_corrections)
    if not enabled:
        return None
    if seed:
        seed_dictionary_from_orm(actor=actor)
    return CorrectionsEntityResolver(actor=actor)


def empty_resolution_report() -> ResolutionReport:
    return ResolutionReport()
