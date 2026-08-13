"""Локальный реестр строковых трансформеров по идеям vstuxls.string_matching."""

from __future__ import annotations

import math
import re
from collections.abc import Callable

_RE_SEVERAL_SPACES = re.compile(r"\s{2,}")
_RE_SPACES = re.compile(r"\s+")
_RE_GAPS = re.compile(r"\b\s+\b")
_RE_HYPHEN_SPACED = re.compile(r"\s*-\s*")

_LETTER_RE_HELPER_MAP = {
    "Z": "[A-Z]",
    "z": "[a-z]",
    "Я": "[А-ЯЁ]",
    "я": "[а-яё]",
    "б": "[a-zа-яё]",
    "Б": "[A-ZА-ЯЁ]",
    "L": "[A-ZА-ЯЁa-zа-яё]",
}
_RE_LETTER_RE_HELPER_MARKS = re.compile(
    r"(?<!\\)\\([{}])".format("".join(_LETTER_RE_HELPER_MAP.keys()))
)

TransformerFn = Callable[[str], str]
_REGISTRY: dict[str, TransformerFn] = {}


def register(transformer_id: str) -> Callable[[TransformerFn], TransformerFn]:
    """Регистрация трансформера по стабильному id."""

    def decorator(fn: TransformerFn) -> TransformerFn:
        _REGISTRY[transformer_id] = fn
        return fn

    return decorator


def apply_transformer(transformer_id: str | Callable[[str], str], string: str) -> str:
    """Применить трансформер по id или callable."""
    if callable(transformer_id):
        return transformer_id(string)
    fn = _REGISTRY.get(transformer_id)
    if fn is None:
        raise ValueError(f"Неизвестный трансформер: {transformer_id}")
    return fn(string)


def known_transformer_ids() -> frozenset[str]:
    return frozenset(_REGISTRY)


@register("decode_re_spaces")
def decode_re_spaces(re_spaces: str) -> str:
    """Упрощённый regex-helper: пробелы → \\s*/\\s+/\\s."""
    return (
        re_spaces.replace("   ", r"\s")
        .replace("  ", r"\s+")
        .replace(" ", r"\s*")
    )


@register("shrink_extra_inner_spaces")
def shrink_extra_inner_spaces(string: str) -> str:
    return _RE_SEVERAL_SPACES.sub(" ", string)


@register("fix_sparse_words")
def fix_sparse_words(string: str, _mul_of_longest_as_sep: float = 2) -> str:
    """'М А Т Е М А Т И К А' → 'МАТЕМАТИКА'."""
    spaces_count = string.count(" ")
    if spaces_count == 0 or spaces_count * 2 < len(string) - 1:
        return string
    gaps = {len(s) for s in _RE_GAPS.findall(string)}
    if not gaps:
        return string
    min_gap = min(gaps)
    separator_min_len = math.ceil(_mul_of_longest_as_sep * min_gap)
    words = string.split(" " * separator_min_len)
    words = [_RE_SPACES.sub("", w) for w in words]
    return " ".join(w for w in words if w)


@register("remove_all_spaces")
def remove_all_spaces(string: str) -> str:
    return string.replace(" ", "")


@register("remove_spaces_around_hypen")
def remove_spaces_around_hypen(string: str) -> str:
    return _RE_HYPHEN_SPACED.sub("-", string)


@register("inject_letter_helpers")
def inject_letter_helpers(string: str) -> str:
    return _RE_LETTER_RE_HELPER_MARKS.sub(
        lambda m: _LETTER_RE_HELPER_MAP.get(m[1], m[1]),
        string,
    )
