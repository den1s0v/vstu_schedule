"""DTO и Django-free ядро слоёв корректировок."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class RewriteRuleDTO:
    """Правило L1 без ORM."""

    id: int | None
    mode: str
    search: str
    replacement: str
    preprocess: tuple[str, ...] = ()
    priority: int = 100
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class RewriteStep:
    """Один шаг трассировки rewrite."""

    kind: str
    detail: str
    before: str
    after: str
    rule_id: int | None = None


@dataclass(frozen=True, slots=True)
class RewriteResult:
    """Результат применения правил L1."""

    input_text: str
    output_text: str
    steps: tuple[RewriteStep, ...] = ()
    applied_rule_ids: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class EntityCandidate:
    """Кандидат L2."""

    correct_object_id: int
    canonical_value: str
    score: float
    origin: str = ""
    external_id: str = ""
    source: str = "fuzzy"


@dataclass(frozen=True, slots=True)
class EntityMatchResult:
    """Результат matching L2 для одного варианта."""

    variant_value: str
    entity_type: str
    candidates: tuple[EntityCandidate, ...] = ()
    linked_object_ids: tuple[int, ...] = ()
    created_object_id: int | None = None
    auto_linked_object_id: int | None = None


@dataclass(frozen=True, slots=True)
class ResolutionContext:
    """Generic-контекст для L3 без привязки к моделям расписания."""

    entities: dict[str, Any] = field(default_factory=dict)
    relations: list[dict[str, Any]] = field(default_factory=list)
    features: dict[str, Any] = field(default_factory=dict)
    fingerprint: str = ""


@dataclass(frozen=True, slots=True)
class ResolutionResult:
    """Результат разрешения неоднозначности L3."""

    selected_object_id: int | None
    status: str
    evidence: dict[str, Any] = field(default_factory=dict)
    strategy: str = "manual"


@dataclass(frozen=True, slots=True)
class PipelineResult:
    """Результат опционального pipeline L1→L2→L3."""

    rewrite: RewriteResult | None = None
    match: EntityMatchResult | None = None
    resolution: ResolutionResult | None = None
