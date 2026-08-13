"""Пакет L3: контракт resolver и ручные операции."""

from apps.panel.services.corrections.disambiguation.base import (
    CandidateResolver,
    PassthroughResolver,
    ScheduleGraphResolverStub,
    get_resolver,
    list_resolvers,
    register_resolver,
)
from apps.panel.services.corrections.disambiguation.manual import (
    open_case,
    resolve_case_manually,
    try_strategy,
)

__all__ = [
    "CandidateResolver",
    "PassthroughResolver",
    "ScheduleGraphResolverStub",
    "get_resolver",
    "list_resolvers",
    "open_case",
    "register_resolver",
    "resolve_case_manually",
    "try_strategy",
]
