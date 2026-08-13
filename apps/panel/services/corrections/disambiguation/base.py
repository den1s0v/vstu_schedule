"""Контракт L3 resolver и реестр стратегий."""

from __future__ import annotations

from typing import Protocol

from apps.panel.services.corrections.dto import (
    EntityCandidate,
    ResolutionContext,
    ResolutionResult,
)

_REGISTRY: dict[str, CandidateResolver] = {}


class CandidateResolver(Protocol):
    """Точка расширения для графовых/эвристических стратегий L3."""

    name: str

    def resolve(
        self,
        candidates: list[EntityCandidate],
        context: ResolutionContext,
    ) -> ResolutionResult:
        """Выбрать объект или оставить кейс неразрешённым."""
        ...


def register_resolver(resolver: CandidateResolver) -> CandidateResolver:
    _REGISTRY[resolver.name] = resolver
    return resolver


def get_resolver(name: str) -> CandidateResolver | None:
    return _REGISTRY.get(name)


def list_resolvers() -> list[str]:
    return sorted(_REGISTRY)


class PassthroughResolver:
    """Заглушка: не выбирает победителя, только регистрирует стратегию."""

    name = "passthrough"

    def resolve(
        self,
        candidates: list[EntityCandidate],
        context: ResolutionContext,
    ) -> ResolutionResult:
        return ResolutionResult(
            selected_object_id=None,
            status="unresolved",
            evidence={
                "candidate_ids": [c.correct_object_id for c in candidates],
                "fingerprint": context.fingerprint,
            },
            strategy=self.name,
        )


class ScheduleGraphResolverStub:
    """
    Зарезервированная стратегия минимизации связей расписания.

    Реализация алгоритма — в следующей итерации; контракт уже зарегистрирован.
    См. docs/corrections.md.
    """

    name = "schedule_graph"

    def resolve(
        self,
        candidates: list[EntityCandidate],
        context: ResolutionContext,
    ) -> ResolutionResult:
        return ResolutionResult(
            selected_object_id=None,
            status="unresolved",
            evidence={
                "message": "Графовая эвристика ещё не реализована",
                "entities": list(context.entities.keys()),
                "relations_count": len(context.relations),
                "candidate_ids": [c.correct_object_id for c in candidates],
            },
            strategy=self.name,
        )


register_resolver(PassthroughResolver())
register_resolver(ScheduleGraphResolverStub())
