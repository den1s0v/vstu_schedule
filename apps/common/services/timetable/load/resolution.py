"""Контракт резолвера сущностей для импорта расписания.

apps.common не зависит от apps.panel: реализация инжектится снаружи.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

EntityType = Literal["teacher", "group", "subject", "place"]
HitSource = Literal["l2", "l3", "fallback"]


@dataclass(frozen=True, slots=True)
class ResolvedHit:
    """Однозначная привязка сырой строки к ORM-сущности."""

    entity_type: EntityType
    canonical_value: str
    model_label: str
    pk: int
    source: HitSource


class EntityResolver(Protocol):
    """Протокол L1→L2→L3 (или любого другого) резолвера строк."""

    def resolve(
        self,
        value: str,
        entity_type: EntityType,
        *,
        context: dict[str, Any] | None = None,
    ) -> ResolvedHit | None:
        """Вернуть hit или None, если однозначности нет."""
        ...


@dataclass
class ResolutionReport:
    """Счётчики резолва для TimetableFileImport.result / логов."""

    resolved: int = 0
    ambiguous: int = 0
    fallback: int = 0
    skipped: int = 0
    details: list[dict[str, Any]] = field(default_factory=list)

    def note_resolved(self, value: str, hit: ResolvedHit) -> None:
        self.resolved += 1
        self.details.append(
            {
                "value": value,
                "status": "resolved",
                "entity_type": hit.entity_type,
                "pk": hit.pk,
                "source": hit.source,
                "canonical": hit.canonical_value,
            }
        )

    def note_ambiguous(self, value: str, entity_type: EntityType) -> None:
        self.ambiguous += 1
        self.details.append(
            {"value": value, "status": "ambiguous", "entity_type": entity_type}
        )

    def note_fallback(self, value: str, entity_type: EntityType) -> None:
        self.fallback += 1
        self.details.append(
            {"value": value, "status": "fallback", "entity_type": entity_type}
        )

    def note_skipped(self, value: str, entity_type: EntityType) -> None:
        self.skipped += 1
        self.details.append(
            {"value": value, "status": "skipped", "entity_type": entity_type}
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "resolved": self.resolved,
            "ambiguous": self.ambiguous,
            "fallback": self.fallback,
            "skipped": self.skipped,
            "details": self.details,
        }
